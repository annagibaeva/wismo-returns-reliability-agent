"""Fail if routing lexicons drift from the frozen snapshot.

Held-out paraphrase tickets must score against the lexicons as they stood when
the holdout set was written — editing keywords to make new tickets pass invalidates
the metric. Intentional lexicon work: `python eval/check_lexicon_freeze.py --write`.

Snapshots are language-nested (`{"<lang>": {"_NAME": [words]}}`) so Spanish drift
is distinguishable from English drift. Two source layouts feed them: flat top-level
`_NAME = ("word", ...)` tuples, recorded under `"en"`, and a per-language dict
`{"en": {"_NAME": (...)}, "es": {...}}`. A scanned module that does not exist is
snapshotted as `null` rather than skipped — a lexicon module appearing or vanishing
is drift, and drift the checker cannot see is drift it silently permits.

Beside the snapshots sits `_frozen_modules.json`, the record of which modules had a
baseline at the last freeze. It is what tells a module that has *never* been frozen
(a new one, freely bootstrapped) apart from one whose baseline was *deleted* (a loss,
refused) — the snapshot files alone cannot say which, since both are simply absent.
"""
from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FREEZE_DIR = Path(__file__).resolve().parent / "frozen_lexicons"

# agent/lexicons.py arrives in T3; it is scanned from now on so that its arrival
# registers as drift rather than as nothing at all. agent/extract.py arrives in T5,
# scanned for the same reason — it imports LEXICONS today, and a later task adds
# model prompt text to it, so it is exactly the kind of module a keyword tuple could
# land in unnoticed. agent/cache.py arrives in T7 and is scanned rather than excused:
# it is the module that handles the *whole prompt*, message text included, on its way
# to being hashed. That is precisely where a normalisation step ("strip these words
# before keying", "treat these phrases as equivalent") would look like plumbing and
# behave like a lexicon. Excusing it would have required claiming it structurally
# cannot hold routing words, and a module that takes customer prose as input cannot
# honestly claim that. It holds none today, and its snapshot is `{}`.
MODULES = ("agent/agent.py", "agent/llm.py", "agent/lexicons.py", "agent/extract.py",
           "agent/cache.py")
FLAT_LANG = "en"

# Every other module under agent/ that is *not* scanned above, with the reason it
# holds no routing keywords today. tests/test_lexicon_freeze.py enforces that this
# set plus MODULES covers every .py file under agent/ — so a future module (e.g.
# agent/cache.py) fails that test the moment it exists, until someone either adds it
# to MODULES (and freezes it) or adds it here with a reason. Extending this dict is
# the conscious act the plan's §0.3 asks for: it shows up in the diff, in plain text,
# next to the module name.
NON_LEXICON_MODULES = {
    "agent/__init__.py": "re-exports resolve_ticket and Resolution; defines nothing",
    "agent/schemas.py": "dataclasses for the audit trail and resolution record only",
}

Snapshot = dict[str, dict[str, list[str]]]


def _strings(node: ast.AST) -> list[str] | None:
    if not isinstance(node, (ast.Tuple, ast.List)):
        return None
    out: list[str] = []
    for el in node.elts:
        if not isinstance(el, ast.Constant) or not isinstance(el.value, str):
            return None
        out.append(el.value)
    return out


def _lexicon_mapping(node: ast.AST) -> dict[str, list[str]] | None:
    """`{"_NAME": ("word", ...), ...}` — non-empty, every value a sequence of strings."""
    if not isinstance(node, ast.Dict) or not node.keys:
        return None
    out: dict[str, list[str]] = {}
    for key, value in zip(node.keys, node.values):
        if not isinstance(key, ast.Constant) or not isinstance(key.value, str):
            return None
        words = _strings(value)
        if words is None:
            return None
        out[key.value] = words
    return out


def _language_dict(node: ast.AST) -> Snapshot | None:
    """`{"en": {"_NAME": (...)}, "es": {...}}` — the layout T3 introduces."""
    if not isinstance(node, ast.Dict) or not node.keys:
        return None
    out: Snapshot = {}
    for key, value in zip(node.keys, node.values):
        if not isinstance(key, ast.Constant) or not isinstance(key.value, str):
            return None
        mapping = _lexicon_mapping(value)
        if mapping is None:
            return None
        out[key.value] = mapping
    return out


def extract_lexicons(path: Path) -> Snapshot:
    """Language-nested lexicons assigned at module level in `path`."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    lexicons: Snapshot = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name):
            continue
        by_lang = _language_dict(node.value)
        if by_lang is None and target.id.startswith("_"):
            words = _strings(node.value)
            by_lang = {FLAT_LANG: {target.id: words}} if words is not None else None
        if by_lang is None:
            continue
        for lang, mapping in by_lang.items():
            lexicons.setdefault(lang, {}).update(mapping)
    return {lang: dict(sorted(m.items())) for lang, m in sorted(lexicons.items())}


def snapshot_module(path: Path) -> Snapshot | None:
    """None means the module is not present — recorded, never skipped."""
    return extract_lexicons(path) if path.exists() else None


def current_snapshots() -> dict[str, Snapshot | None]:
    return {rel: snapshot_module(ROOT / rel) for rel in MODULES}


def union_lexicons(snapshots: dict[str, Snapshot | None]) -> Snapshot:
    """Merge per-module snapshots into one language-nested mapping.

    One lexicon defined twice under the same language with *different* words is an
    error, not a merge: mid-T3 that means the old tuples and the new module disagree,
    and which one the running agent uses is then a coin flip.
    """
    merged: Snapshot = {}
    for rel, snapshot in snapshots.items():
        for lang, mapping in (snapshot or {}).items():
            seen = merged.setdefault(lang, {})
            for name, words in mapping.items():
                if name in seen and seen[name] != words:
                    raise ValueError(
                        f"{lang}/{name} is defined with different words in more than one "
                        f"module (last seen in {rel}) — the live routing behaviour is ambiguous"
                    )
                seen[name] = words
    return merged


def _frozen_path(rel: str) -> Path:
    return FREEZE_DIR / (Path(rel).stem + ".json")


def _load_frozen() -> dict[str, Snapshot | None]:
    """Frozen snapshots, reading a flat `{"_NAME": [...]}` file as English.

    Same rule as for source: flat means English. It keeps the loss guard below able
    to read a snapshot written before this module became language-nested, which is
    the one re-freeze where losing a lexicon would be easiest to miss.
    """
    out: dict[str, Snapshot | None] = {}
    for rel in MODULES:
        path = _frozen_path(rel)
        if not path.exists():
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        out[rel] = {FLAT_LANG: data} if data and all(
            isinstance(v, list) for v in data.values()) else data
    return out


def _keys(snapshots: dict[str, Snapshot | None]) -> set[tuple[str, str]]:
    return {(lang, name) for lang, m in union_lexicons(snapshots).items() for name in m}


def _record_path() -> Path:
    return FREEZE_DIR / "_frozen_modules.json"


def _known_modules() -> set[str] | None:
    """Modules that had a baseline at the last freeze; None if no record exists.

    None from a missing directory means nothing has ever been frozen here. None from
    a directory that exists means the record itself was removed — the record is
    committed, so a real checkout always has it beside the snapshots.
    """
    path = _record_path()
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return set(data["modules"])


def _missing_baselines() -> tuple[list[str], list[str]]:
    """Modules with no snapshot file, split into (never frozen, baseline deleted).

    The loss guard below compares live keys against the keys *on disk*, so deleting a
    snapshot file deletes the baseline it held rather than tripping the guard — the
    lexicons it froze become nothing to lose. Hence this, one level up. But absence of
    a file is two different facts, and the filesystem cannot tell them apart: a module
    only just added to MODULES has no baseline to lose, while one the record names has
    had its baseline removed. The record is what separates them, so that bootstrapping
    a new lexicon module needs no flag and only a real deletion is refused.

    Both lists are empty when there is no record at all — a first freeze has nothing to
    classify, and the callers handle a record that has gone missing separately.
    """
    known = _known_modules()
    if known is None:
        return [], []
    absent = [rel for rel in MODULES if not _frozen_path(rel).exists()]
    return ([rel for rel in absent if rel not in known],
            [rel for rel in absent if rel in known])


def write_snapshots(force: bool = False) -> int:
    """Re-freeze. Refuses to record a lexicon the checker can no longer see.

    A restructure the extractor does not understand looks exactly like "the lexicons
    are gone", and the tempting fix — rerun with --write — writes an empty snapshot
    that then passes forever while guarding nothing. So a re-freeze that *loses* a
    lexicon key stops and names it; --force is for a deliberate removal. A *deleted
    snapshot file* is the same loss reached one level up, and is refused the same way —
    but only when the record says that module had a baseline. A module that never had
    one is bootstrapped with no flag, so that adding a lexicon module never pushes an
    operator onto the flag that also waves through real word loss.
    """
    live = current_snapshots()
    first_freeze = not FREEZE_DIR.exists()
    record_missing = not first_freeze and _known_modules() is None
    new, deleted = _missing_baselines()
    if record_missing and not force:
        print(f"refusing to write: the freeze record {_record_path().relative_to(ROOT)} is "
              "missing, so a module that was never frozen and a module whose baseline was "
              "deleted are no longer distinguishable — writing now would re-baseline either "
              "of them silently. Restore it (git checkout eval/frozen_lexicons). Use --force "
              "only to deliberately re-baseline from whatever the code says now.",
              file=sys.stderr)
        return 1
    if deleted and not force:
        print(f"refusing to write: {len(deleted)} frozen snapshot file(s) recorded in "
              f"{_record_path().relative_to(ROOT)} are missing from "
              f"{FREEZE_DIR.relative_to(ROOT)}:", file=sys.stderr)
        for rel in deleted:
            print(f"  {_frozen_path(rel).name} (the baseline for {rel})", file=sys.stderr)
        print("\nA deleted snapshot takes its baseline with it — the lexicons it froze are "
              "no longer anything to lose, so writing now would re-baseline them silently. "
              "Restore them first (git checkout eval/frozen_lexicons). Use --force only to "
              "deliberately re-baseline from whatever the code says now.", file=sys.stderr)
        return 1
    lost = sorted(_keys(_load_frozen()) - _keys(live))
    if lost and not force:
        print(f"refusing to write: {len(lost)} frozen lexicon(s) are no longer visible in "
              + ", ".join(MODULES) + ":", file=sys.stderr)
        for lang, name in lost:
            print(f"  {lang}/{name}", file=sys.stderr)
        print("\nIf the lexicons moved, teach extract_lexicons() the new layout first — a "
              "snapshot that has lost them passes every future check while guarding nothing. "
              "Use --force only to record a deliberate removal.", file=sys.stderr)
        return 1
    if not union_lexicons(live):
        print("refusing to write: no lexicons found in any scanned module — an empty "
              "snapshot guards nothing.", file=sys.stderr)
        return 1

    if first_freeze:
        print("note: no frozen snapshots exist yet — recording a first baseline, with "
              "nothing to compare it against.")
    for rel in new:
        print(f"note: {rel} has never been frozen — recording a first baseline for it, with "
              "nothing to compare it against.")
    FREEZE_DIR.mkdir(parents=True, exist_ok=True)
    for rel, snapshot in live.items():
        path = _frozen_path(rel)
        path.write_text(json.dumps(snapshot, indent=2) + "\n", encoding="utf-8")
        if snapshot is None:
            note = "module absent"
        else:
            note = ", ".join(f"{lang}: {len(m)}" for lang, m in snapshot.items()) or "no lexicons"
        print(f"wrote {path.relative_to(ROOT)} ({note})")
    _record_path().write_text(json.dumps({"modules": list(MODULES)}, indent=2) + "\n",
                              encoding="utf-8")
    if lost:
        print(f"--force: dropped {len(lost)} lexicon(s): "
              + ", ".join(f"{lang}/{name}" for lang, name in lost))
    if deleted:
        print(f"--force: re-baselined {len(deleted)} module(s) whose frozen snapshot was "
              "missing: " + ", ".join(deleted))
    if record_missing:
        print(f"--force: rewrote the missing freeze record {_record_path().relative_to(ROOT)}")
    return 0


def _why_missing(rel: str, known: set[str] | None) -> str:
    """Why a snapshot file is absent — never frozen, or frozen and then deleted.

    The two need different advice, and telling an operator to `git checkout` a baseline
    that never existed sends them looking for something that was never there.
    """
    if known is None:
        return ("nothing has ever been frozen here. To record a first baseline: "
                "python eval/check_lexicon_freeze.py --write" if not FREEZE_DIR.exists()
                else "the freeze record is missing too, so whether this baseline ever "
                     "existed cannot be told from the freeze directory alone.")
    if rel not in known:
        return (f"{rel} has never been frozen. To record a first baseline for it: "
                "python eval/check_lexicon_freeze.py --write")
    return (f"the record names {rel} as frozen, so this baseline was deleted. "
            "Restore it: git checkout eval/frozen_lexicons")


def check() -> int:
    errors: list[str] = []
    notes: list[str] = []
    live = current_snapshots()
    known = _known_modules()
    if FREEZE_DIR.exists() and known is None:
        errors.append(f"missing freeze record: {_record_path().relative_to(ROOT)} — without it "
                      "a never-frozen module and a deleted baseline are indistinguishable, so "
                      "--write can no longer tell a bootstrap from a loss.\n"
                      "  Restore it: git checkout eval/frozen_lexicons")
    unrecorded = [] if known is None else [
        rel for rel in MODULES if rel not in known and _frozen_path(rel).exists()]
    if unrecorded:
        errors.append("frozen but not in " + str(_record_path().relative_to(ROOT)) + ": "
                      + ", ".join(unrecorded) + " — a baseline the record does not name reads "
                      "as never-frozen if its file is later deleted.\n"
                      "  To record it: python eval/check_lexicon_freeze.py --write")
    for rel, snapshot in live.items():
        frozen_path = _frozen_path(rel)
        if not frozen_path.exists():
            errors.append(f"missing frozen snapshot: {frozen_path.relative_to(ROOT)}\n"
                          f"  {_why_missing(rel, known)}")
            continue
        frozen = json.loads(frozen_path.read_text(encoding="utf-8"))
        if snapshot is None and frozen is None:
            notes.append(f"note: {rel} is absent; the frozen snapshot records it as absent")
        elif snapshot is None:
            errors.append(f"{rel} has disappeared but its frozen snapshot holds lexicons — "
                          "the routing words it froze are no longer being checked.")
        elif frozen is None:
            errors.append(f"{rel} now exists and its lexicons are unfrozen.\n"
                          f"  frozen: {frozen_path.relative_to(ROOT)} (recorded as absent)\n"
                          "  To freeze it: python eval/check_lexicon_freeze.py --write")
        elif snapshot != frozen:
            errors.append(
                f"{rel} lexicons changed — held-out scores would be invalid.\n"
                f"  frozen: {frozen_path.relative_to(ROOT)}\n"
                "  To intentionally update lexicons (not for held-out tickets): "
                "python eval/check_lexicon_freeze.py --write"
            )
    if not errors and not union_lexicons(live):
        errors.append("no lexicons found in any of " + ", ".join(MODULES) + " — the freeze "
                      "check is guarding nothing. The routing lexicons moved somewhere "
                      "extract_lexicons() cannot see.")
    if errors:
        print("LEXICON FREEZE CHECK FAILED", file=sys.stderr)
        for err in errors:
            print(err, file=sys.stderr)
        return 1
    for note in notes:
        print(note)
    counts = ", ".join(f"{lang}: {len(m)}" for lang, m in union_lexicons(live).items())
    print(f"lexicon freeze OK ({counts})")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    try:
        if "--write" in args:
            return write_snapshots(force="--force" in args)
        return check()
    except ValueError as exc:  # ambiguous duplicate definition
        print("LEXICON FREEZE CHECK FAILED", file=sys.stderr)
        print(exc, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

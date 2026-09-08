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
"""
from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FREEZE_DIR = Path(__file__).resolve().parent / "frozen_lexicons"

# agent/lexicons.py arrives in T3; it is scanned from now on so that its arrival
# registers as drift rather than as nothing at all.
MODULES = ("agent/agent.py", "agent/llm.py", "agent/lexicons.py")
FLAT_LANG = "en"

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


def _frozen_gaps() -> list[str]:
    """Modules whose frozen snapshot file is missing from an existing freeze directory.

    The loss guard below compares live keys against the keys *on disk*, so deleting a
    snapshot file deletes the baseline it held rather than tripping the guard — the
    lexicons it froze become nothing to lose. Hence this, one level up: the freeze
    directory existing is what says a baseline exists, and a module listed in MODULES
    with no file in it has had its baseline removed.

    Empty when the directory does not exist at all: nothing has ever been frozen here,
    a first freeze has no baseline to lose, and requiring --force to bootstrap would
    be requiring it to say "yes, really" to nothing.
    """
    if not FREEZE_DIR.exists():
        return []
    return [rel for rel in MODULES if not _frozen_path(rel).exists()]


def write_snapshots(force: bool = False) -> int:
    """Re-freeze. Refuses to record a lexicon the checker can no longer see.

    A restructure the extractor does not understand looks exactly like "the lexicons
    are gone", and the tempting fix — rerun with --write — writes an empty snapshot
    that then passes forever while guarding nothing. So a re-freeze that *loses* a
    lexicon key stops and names it; --force is for a deliberate removal. A *deleted
    snapshot file* is the same loss reached one level up, and is refused the same way.
    """
    live = current_snapshots()
    first_freeze = not FREEZE_DIR.exists()
    gaps = _frozen_gaps()
    if gaps and not force:
        print(f"refusing to write: {len(gaps)} frozen snapshot file(s) are missing from "
              f"{FREEZE_DIR.relative_to(ROOT)}:", file=sys.stderr)
        for rel in gaps:
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
    FREEZE_DIR.mkdir(parents=True, exist_ok=True)
    for rel, snapshot in live.items():
        path = _frozen_path(rel)
        path.write_text(json.dumps(snapshot, indent=2) + "\n", encoding="utf-8")
        if snapshot is None:
            note = "module absent"
        else:
            note = ", ".join(f"{lang}: {len(m)}" for lang, m in snapshot.items()) or "no lexicons"
        print(f"wrote {path.relative_to(ROOT)} ({note})")
    if lost:
        print(f"--force: dropped {len(lost)} lexicon(s): "
              + ", ".join(f"{lang}/{name}" for lang, name in lost))
    if gaps:
        print(f"--force: re-baselined {len(gaps)} module(s) whose frozen snapshot was "
              "missing: " + ", ".join(gaps))
    return 0


def check() -> int:
    errors: list[str] = []
    notes: list[str] = []
    live = current_snapshots()
    for rel, snapshot in live.items():
        frozen_path = _frozen_path(rel)
        if not frozen_path.exists():
            errors.append(f"missing frozen snapshot: {frozen_path.relative_to(ROOT)}")
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

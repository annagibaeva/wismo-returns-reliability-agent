"""Fail if routing lexicons drift from the frozen snapshot.

Held-out paraphrase tickets must score against the lexicons as they stood when
the holdout set was written — editing keywords to make new tickets pass invalidates
the metric. Intentional lexicon work: `python eval/check_lexicon_freeze.py --write`.
"""
from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AGENT = ROOT / "agent" / "agent.py"
LLM = ROOT / "agent" / "llm.py"
FREEZE_DIR = Path(__file__).resolve().parent / "frozen_lexicons"


def _tuple_of_strings(node: ast.AST) -> tuple[str, ...] | None:
    if not isinstance(node, ast.Tuple):
        return None
    out: list[str] = []
    for el in node.elts:
        if not isinstance(el, ast.Constant) or not isinstance(el.value, str):
            return None
        out.append(el.value)
    return tuple(out)


def extract_lexicons(path: Path) -> dict[str, list[str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    lexicons: dict[str, list[str]] = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name) or not target.id.startswith("_"):
            continue
        words = _tuple_of_strings(node.value)
        if words is not None:
            lexicons[target.id] = list(words)
    return dict(sorted(lexicons.items()))


def current_snapshots() -> dict[str, dict[str, list[str]]]:
    return {
        "agent.py": extract_lexicons(AGENT),
        "llm.py": extract_lexicons(LLM),
    }


def write_snapshots() -> None:
    FREEZE_DIR.mkdir(parents=True, exist_ok=True)
    for name, lexicons in current_snapshots().items():
        path = FREEZE_DIR / name.replace(".py", ".json")
        path.write_text(json.dumps(lexicons, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {path.relative_to(ROOT)}")


def check() -> int:
    errors: list[str] = []
    for name, live in current_snapshots().items():
        frozen_path = FREEZE_DIR / name.replace(".py", ".json")
        if not frozen_path.exists():
            errors.append(f"missing frozen snapshot: {frozen_path.relative_to(ROOT)}")
            continue
        frozen = json.loads(frozen_path.read_text(encoding="utf-8"))
        if live != frozen:
            errors.append(
                f"{name} lexicons changed — held-out scores would be invalid.\n"
                f"  frozen: {frozen_path.relative_to(ROOT)}\n"
                "  To intentionally update lexicons (not for held-out tickets): "
                "python eval/check_lexicon_freeze.py --write"
            )
    if errors:
        print("LEXICON FREEZE CHECK FAILED", file=sys.stderr)
        for err in errors:
            print(err, file=sys.stderr)
        return 1
    print("lexicon freeze OK")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if "--write" in args:
        write_snapshots()
        return 0
    return check()


if __name__ == "__main__":
    raise SystemExit(main())

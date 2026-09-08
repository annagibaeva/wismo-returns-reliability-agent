"""The isolation guard: nothing under `agent/` may see the gold record.

Global constraint 3 says `agent/` may not "read gold facts or import from `eval/`".
An import guard on `eval.gold` / `fixtures/gold_facts.json` is necessary but not
sufficient: `resolve_ticket` is handed the *whole* ticket dict, and
`ticket["expected"]["gold_defective"]` (T8's field, see fixtures/tickets.json) is the
agent's own answer key sitting right there in its input. A guard that only checked
imports would wave that straight through. So this file checks two properties:

  1. no module under `agent/` imports `eval.gold` (or `eval` at all, for good
     measure) or names `fixtures/gold_facts.json` in a string literal;
  2. no module under `agent/` reads the `"expected"` key off any dict — the
     property that actually matters, since that key is where both `gold_defective`
     and (via `outcome`/`action`/...) every other answer key lives.

(2) is done with an AST walk for `x["expected"]` / `x.get("expected")` rather than a
text search for the word "expected", because `agent/cache.py` has a local variable
literally named `expected` (a loop variable over `(field, expected)` pairs, used only
via plain name lookups, never a subscript) — a substring or regex check would flag it
and either be wrong or need a hand-maintained exception list, which is exactly the
kind of guard that erodes the first time someone doesn't understand why. The two
`test_guard_fails_against_a_deliberately_added_*` cases below exist so a change that
quietly turns this guard into a no-op is caught here, not discovered later.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

AGENT_DIR = ROOT / "agent"


def _agent_py_files(root: Path = AGENT_DIR) -> list[Path]:
    return sorted(p for p in root.rglob("*.py") if "__pycache__" not in p.parts)


def _imports_eval(tree: ast.AST) -> list[str]:
    """Names of imports that reach into `eval` (specifically `eval.gold`, but any
    `eval` import is reported — `agent/` has no legitimate reason to import `eval` at
    all, per global constraint 3)."""
    hits = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "eval" or alias.name.startswith("eval."):
                    hits.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module and (node.module == "eval" or node.module.startswith("eval.")):
                hits.append(node.module)
    return hits


def _names_gold_facts_path(tree: ast.AST) -> list[str]:
    hits = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if "gold_facts" in node.value:
                hits.append(node.value)
    return hits


def _string_key(node: ast.AST) -> str | None:
    """The literal string a Subscript's index names, across Python versions.

    3.9+ folds `ast.Index` away and puts the key directly in `Subscript.slice`; this
    handles both without needing a version check.
    """
    if isinstance(node, ast.Index):  # pragma: no cover - pre-3.9 AST shape
        node = node.value
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _reads_expected_key(tree: ast.AST) -> list[ast.AST]:
    """Every `x["expected"]` subscript and `x.get("expected", ...)` call in `tree`.

    Deliberately blind to the *name* of `x` — the vulnerability is reading the
    `"expected"` key off *some* dict (almost certainly the ticket), not reading it
    off a variable called `ticket`. Equally deliberately blind to plain name usage
    (`expected = ...`, `entry.get(field) != expected`) — a local variable that
    happens to be named `expected`, as in `agent/cache.py`, is not a read of a
    ticket's `"expected"` key and must not be flagged.
    """
    hits: list[ast.AST] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Subscript) and _string_key(node.slice) == "expected":
            hits.append(node)
        elif (isinstance(node, ast.Call)
              and isinstance(node.func, ast.Attribute)
              and node.func.attr == "get"
              and node.args
              and isinstance(node.args[0], ast.Constant)
              and node.args[0].value == "expected"):
            hits.append(node)
    return hits


def _violations(root: Path = AGENT_DIR) -> dict[str, list[str]]:
    """Map of relative path -> list of human-readable violations, for every .py file
    under `root`. Empty dict means the tree is clean."""
    out: dict[str, list[str]] = {}
    for path in _agent_py_files(root):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        problems = []
        for name in _imports_eval(tree):
            problems.append(f"imports {name!r}")
        for literal in _names_gold_facts_path(tree):
            problems.append(f"names gold_facts path in string literal {literal!r}")
        for node in _reads_expected_key(tree):
            problems.append(f'reads ["expected"] / .get("expected") at line {node.lineno}')
        if problems:
            out[str(path.relative_to(root.parent if root is AGENT_DIR else root))] = problems
    return out


# --------------------------------------------------------------------------- #
# The real tree: both halves of the guard must currently pass.
# --------------------------------------------------------------------------- #

def test_agent_does_not_import_eval_gold_or_name_the_gold_facts_path():
    for path in _agent_py_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        imports = _imports_eval(tree)
        literals = _names_gold_facts_path(tree)
        assert not imports, f"{path.relative_to(ROOT)} imports eval/eval.*: {imports}"
        assert not literals, f"{path.relative_to(ROOT)} names a gold_facts path: {literals}"


def test_agent_does_not_read_ticket_expected():
    for path in _agent_py_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        hits = _reads_expected_key(tree)
        assert not hits, (
            f'{path.relative_to(ROOT)} reads ["expected"] / .get("expected") at line(s) '
            f"{[n.lineno for n in hits]} -- that key is where gold_defective and every "
            "other answer key live; agent/ must never read it (global constraint 3)."
        )


def test_agent_tree_is_entirely_clean():
    """Both checks at once, over the whole tree -- the shape a CI gate would run."""
    assert _violations() == {}


# --------------------------------------------------------------------------- #
# The half that matters: prove the guard actually bites, in a scratch copy.
# --------------------------------------------------------------------------- #

def test_guard_fails_against_a_deliberately_added_import(tmp_path: Path):
    scratch = tmp_path / "agent"
    scratch.mkdir()
    (scratch / "sneaky.py").write_text(
        "from eval.gold import defective_for\n"
        "\n"
        "def peek(ticket):\n"
        "    return defective_for(ticket)\n",
        encoding="utf-8",
    )
    violations = _violations(scratch)
    assert violations, "the guard did not flag a module that imports eval.gold"
    ((_, problems),) = violations.items()
    assert any("eval.gold" in p for p in problems)


def test_guard_fails_against_a_deliberately_added_expected_read(tmp_path: Path):
    scratch = tmp_path / "agent"
    scratch.mkdir()
    (scratch / "sneaky.py").write_text(
        "def peek(ticket):\n"
        "    return ticket['expected']['gold_defective']\n",
        encoding="utf-8",
    )
    violations = _violations(scratch)
    assert violations, "the guard did not flag a module that reads ticket['expected']"
    ((_, problems),) = violations.items()
    assert any("expected" in p for p in problems)


def test_guard_ignores_a_local_variable_that_happens_to_be_named_expected(tmp_path: Path):
    """The regression this whole file exists to prevent: agent/cache.py's actual
    shape (a loop variable named `expected`, compared by plain name, never
    subscripted) must not trip either check."""
    scratch = tmp_path / "agent"
    scratch.mkdir()
    (scratch / "cache_like.py").write_text(
        "def check(entry, k, call):\n"
        "    for field, expected in (('cache_version', 1), ('key', k), ('call', call)):\n"
        "        if entry.get(field) != expected:\n"
        "            raise ValueError(field, expected)\n",
        encoding="utf-8",
    )
    assert _violations(scratch) == {}


def test_guard_ignores_an_unrelated_dict_get_call(tmp_path: Path):
    """`.get("expected", ...)` is only a violation when the literal key is
    `"expected"` — a `.get` on some other key must not be flagged."""
    scratch = tmp_path / "agent"
    scratch.mkdir()
    (scratch / "harmless.py").write_text(
        "def peek(ticket):\n"
        "    return ticket.get('order_id')\n",
        encoding="utf-8",
    )
    assert _violations(scratch) == {}

"""Guards the freeze checker itself, and pins the English words it must keep seeing.

`eval/check_lexicon_freeze.py` is the integrity mechanism the held-out numbers rest
on, and it has one catastrophic failure mode: the lexicons move somewhere its AST
walk cannot see, the check fails, and someone clears the failure with `--write`.
The snapshot is then empty and passes forever while guarding nothing. The frozen
snapshot cannot catch that -- `--write` rewrites it to whatever the code says at
that moment -- so the guard has to live here, in code no re-freeze touches:

  * the union across scanned modules is non-empty and holds all eight lexicons;
  * the live English words equal the tuples as they stood at base commit 865bc1e,
    in order (T3's done-criterion and global constraint 2, made machine-checkable).

Both read the live values through the checker's own `extract_lexicons()`, so they
work unchanged before T3 (flat `_NAME = (...)` tuples in agent/agent.py) and after
it (the same words under `LEXICONS["en"]` in agent/lexicons.py).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from eval.check_lexicon_freeze import (
    FLAT_LANG,
    current_snapshots,
    extract_lexicons,
    snapshot_module,
    union_lexicons,
)

# The eight lexicons in agent/agent.py at base commit 865bc1e, verbatim and in order.
# Sourced from `git show 865bc1e:agent/agent.py`, cross-checked against
# `git show 865bc1e:eval/frozen_lexicons/agent.json`. This literal is the witness:
# it must never be regenerated from the code it is checking.
ENGLISH_AT_BASE = {
    '_ABUSE': ['sue', 'lawyer', 'legal action', 'reviews everywhere', 'garbage', 'trash'],
    '_ADDRESS': ['change the delivery address', 'change my address', 'change the address',
                 'reroute', 'different address'],
    '_DEFECTIVE': ['defective', 'broken', 'faulty', "doesn't work", 'does not work',
                   'not working', 'leak', 'leaking', 'cracked', "won't turn on", 'dead',
                   'malfunction'],
    '_FRAUD': ['fraud', 'took over my account', 'account takeover', "didn't make",
               "didn't place"],
    '_PAYMENT': ['unauthorized', 'dispute', 'disputing', 'chargeback', 'charge back',
                 'my bank'],
    '_RETURN': ['return', 'send back', 'send it back', 'send this back', 'refund',
                'money back', 'exchange'],
    '_SAFETY': ['caught fire', 'fire', 'smoke', 'smoking', 'shock', 'spark', 'burn',
                'hazard', 'dangerous', 'explod'],
    '_WISMO': ['where', 'track', 'tracking', 'arrive', 'arriving', 'shipped', 'ship',
               'delivery', 'deliver'],
}
EXPECTED_NAMES = frozenset(ENGLISH_AT_BASE)


def _assert_lexicons_present(union: dict[str, dict[str, list[str]]]) -> None:
    """Every expected lexicon exists somewhere, with words. Union, not per-file.

    Per-file would be wrong: eval/frozen_lexicons/llm.json is legitimately empty --
    agent/llm.py holds no lexicons -- and T3 moves the ones in agent/agent.py out of
    it. What must hold is that the *scanned set as a whole* still shows the checker
    all eight, wherever they currently live.
    """
    assert union, "no lexicons found in any scanned module"
    found = {name for mapping in union.values() for name in mapping}
    assert found >= EXPECTED_NAMES, f"lexicons the checker can no longer see: {sorted(EXPECTED_NAMES - found)}"
    for lang, mapping in union.items():
        for name, words in mapping.items():
            assert words, f"{lang}/{name} is empty"


def test_scanned_modules_expose_every_lexicon() -> None:
    _assert_lexicons_present(union_lexicons(current_snapshots()))


def test_the_guard_fails_against_a_module_set_with_no_lexicons(tmp_path: Path) -> None:
    """The half that matters: the assertion above is not vacuously true."""
    lexicon_free = tmp_path / "nothing.py"
    lexicon_free.write_text('X = 1\n_NOTES = "not a tuple"\n', encoding="utf-8")
    snapshots = {"nothing.py": snapshot_module(lexicon_free),
                 "gone.py": snapshot_module(tmp_path / "gone.py")}

    with pytest.raises(AssertionError, match="no lexicons found"):
        _assert_lexicons_present(union_lexicons(snapshots))


def test_english_words_unchanged_since_base_commit() -> None:
    """Fails if a single English word is added, removed, or reordered.

    This is the check a `--write` cannot erase, and it must survive T3 untouched.
    """
    live = union_lexicons(current_snapshots())
    assert FLAT_LANG in live, "no English lexicons are visible to the freeze checker at all"
    assert live[FLAT_LANG] == ENGLISH_AT_BASE


def test_flat_tuples_are_recorded_as_english(tmp_path: Path) -> None:
    module = tmp_path / "flat.py"
    module.write_text('_SAFETY = ("fire", "smoke")\n_HELPER = 3\nNOT_PRIVATE = ("x",)\n',
                      encoding="utf-8")
    assert extract_lexicons(module) == {"en": {"_SAFETY": ["fire", "smoke"]}}


def test_per_language_dict_is_snapshotted_per_language(tmp_path: Path) -> None:
    """The layout T3 introduces, verified before T3 writes it."""
    module = tmp_path / "lexicons.py"
    module.write_text(
        'LEXICONS = {\n'
        '    "en": {"_SAFETY": ("fire",), "_RETURN": ("refund",)},\n'
        '    "es": {"_SAFETY": ("fuego",), "_RETURN": ("reembolso",)},\n'
        '}\n'
        '_SCHEMA = {"name": "not a lexicon", "props": {"a": "b"}}\n',
        encoding="utf-8")
    assert extract_lexicons(module) == {
        "en": {"_RETURN": ["refund"], "_SAFETY": ["fire"]},
        "es": {"_RETURN": ["reembolso"], "_SAFETY": ["fuego"]},
    }


def test_absent_module_is_recorded_not_skipped(tmp_path: Path) -> None:
    """`None`, not `{}` -- so a lexicon module vanishing reads as drift, not silence."""
    assert snapshot_module(tmp_path / "never_existed.py") is None


def test_same_lexicon_defined_twice_with_different_words_is_an_error(tmp_path: Path) -> None:
    """Mid-T3 duplication must not be papered over by the union."""
    old = tmp_path / "old.py"
    old.write_text('_SAFETY = ("fire",)\n', encoding="utf-8")
    new = tmp_path / "new.py"
    new.write_text('LEXICONS = {"en": {"_SAFETY": ("fire", "smoke")}}\n', encoding="utf-8")

    with pytest.raises(ValueError, match="en/_SAFETY"):
        union_lexicons({"old.py": extract_lexicons(old), "new.py": extract_lexicons(new)})

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

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import eval.check_lexicon_freeze as freeze
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


@pytest.fixture
def fake_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A repo whose lexicons live only in agent/lexicons.py, frozen nowhere yet.

    The checker's roots are module constants, so a --write test either writes into the
    real worktree or redirects both. Redirecting both is the honest one: everything
    below runs the real write path. The lexicons sit in the *one* module whose snapshot
    the deletion test then removes, so no key remains anywhere else on disk to make the
    existing key-level loss guard fire -- what fires is the new gap guard.
    """
    (tmp_path / "agent").mkdir()
    (tmp_path / "agent" / "agent.py").write_text("X = 1\n", encoding="utf-8")
    (tmp_path / "agent" / "llm.py").write_text("Y = 2\n", encoding="utf-8")
    (tmp_path / "agent" / "lexicons.py").write_text(
        'LEXICONS = {"en": {"_SAFETY": ("fire",)}, "es": {"_SAFETY": ("fuego",)}}\n',
        encoding="utf-8")
    monkeypatch.setattr(freeze, "ROOT", tmp_path)
    monkeypatch.setattr(freeze, "FREEZE_DIR", tmp_path / "eval" / "frozen_lexicons")
    return tmp_path


def test_a_first_freeze_needs_no_force(fake_repo: Path) -> None:
    """Nothing frozen yet is not a loss -- the bootstrap path must stay open."""
    assert freeze._missing_baselines() == ([], [])
    assert freeze.write_snapshots() == 0
    assert sorted(p.name for p in freeze.FREEZE_DIR.iterdir()) == [
        "_frozen_modules.json", "agent.json", "lexicons.json", "llm.json"]
    assert freeze._known_modules() == set(freeze.MODULES)


def test_a_deleted_snapshot_is_a_loss_not_a_first_run(fake_repo: Path) -> None:
    """The guard's whole job: tell "never frozen" apart from "frozen, then gone"."""
    assert freeze.write_snapshots() == 0
    (freeze.FREEZE_DIR / "lexicons.json").unlink()
    assert freeze._missing_baselines() == ([], ["agent/lexicons.py"])

    # ... and with the record gone, neither reading is available: that is its own refusal.
    freeze._record_path().unlink()
    assert freeze._known_modules() is None
    assert freeze._missing_baselines() == ([], [])


def test_a_never_frozen_module_needs_no_force(
        fake_repo: Path, monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str]) -> None:
    """Adding a lexicon module to MODULES is a bootstrap, not a loss.

    Round 1 read the *directory* as the witness, so with other modules already frozen a
    brand-new one looked exactly like a deleted baseline: --write refused, and --force --
    which also waves through real word loss -- was the only way past it. The record makes
    the signal per-module.
    """
    assert freeze.write_snapshots() == 0
    (fake_repo / "agent" / "newmod.py").write_text(
        'LEXICONS = {"en": {"_WISMO": ("track",)}}\n', encoding="utf-8")
    monkeypatch.setattr(freeze, "MODULES", freeze.MODULES + ("agent/newmod.py",))
    capsys.readouterr()

    assert freeze._missing_baselines() == (["agent/newmod.py"], [])
    assert freeze.write_snapshots() == 0
    out = capsys.readouterr()
    assert "agent/newmod.py has never been frozen" in out.out
    assert "deleted" not in out.out and "git checkout" not in out.out
    assert out.err == ""
    assert json.loads((freeze.FREEZE_DIR / "newmod.json").read_text()) == {
        "en": {"_WISMO": ["track"]}}
    assert freeze._known_modules() == set(freeze.MODULES)


def test_a_new_module_does_not_excuse_a_deleted_baseline(
        fake_repo: Path, monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str]) -> None:
    """Both states at once: the new one is bootstrapped, the deleted one still refuses."""
    assert freeze.write_snapshots() == 0
    (fake_repo / "agent" / "newmod.py").write_text(
        'LEXICONS = {"en": {"_WISMO": ("track",)}}\n', encoding="utf-8")
    monkeypatch.setattr(freeze, "MODULES", freeze.MODULES + ("agent/newmod.py",))
    (freeze.FREEZE_DIR / "lexicons.json").unlink()
    capsys.readouterr()

    assert freeze._missing_baselines() == (["agent/newmod.py"], ["agent/lexicons.py"])
    assert freeze.write_snapshots() == 1
    err = capsys.readouterr().err
    assert "lexicons.json (the baseline for agent/lexicons.py)" in err
    assert "newmod" not in err, "a never-frozen module reported as a deleted baseline"
    assert not (freeze.FREEZE_DIR / "newmod.json").exists(), "refused, yet still wrote"


def test_write_refuses_when_the_freeze_record_is_missing(
        fake_repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """The record is the new state, so its own deletion must not be a free pass.

    Without it the two readings collapse back together, and the safe answer is to refuse
    rather than to guess -- deleting the record must not become the way to launder a
    deleted baseline past the guard above.
    """
    assert freeze.write_snapshots() == 0
    freeze._record_path().unlink()
    (freeze.FREEZE_DIR / "lexicons.json").unlink()
    capsys.readouterr()

    assert freeze.write_snapshots() == 1
    assert "_frozen_modules.json" in capsys.readouterr().err
    assert not (freeze.FREEZE_DIR / "lexicons.json").exists(), "refused, yet still wrote"

    assert freeze.check() == 1
    assert "missing freeze record" in capsys.readouterr().err


def test_check_flags_a_baseline_the_record_does_not_name(
        fake_repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """A snapshot the record omits would read as never-frozen once its file went missing.

    Reachable by editing the record, or by hand-adding a snapshot file. Either way the
    record and the snapshots have to agree, or the three states stop being three.
    """
    assert freeze.write_snapshots() == 0
    freeze._record_path().write_text(
        json.dumps({"modules": ["agent/agent.py", "agent/llm.py"]}), encoding="utf-8")
    capsys.readouterr()

    assert freeze.check() == 1
    err = capsys.readouterr().err
    assert "frozen but not in" in err and "agent/lexicons.py" in err


def test_the_freeze_record_names_every_scanned_module() -> None:
    """The committed record, checked against the committed MODULES.

    A guard whose state can quietly drift is the failure it was added to fix: if the
    record stopped naming a module, that module's baseline could be deleted and the
    deletion would read as a bootstrap.
    """
    record = json.loads(freeze._record_path().read_text(encoding="utf-8"))
    assert record["modules"] == list(freeze.MODULES)


def test_write_refuses_to_re_baseline_over_a_deleted_snapshot(
        fake_repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Deleting the file that held the baseline must not silently reset it.

    Gutting the lexicons first is the scenario that matters: with lexicons.json gone
    the key-level loss guard sees nothing missing, so before this guard `--write`
    recorded the gutted lists and every later check passed against them.
    """
    assert freeze.write_snapshots() == 0
    (freeze.FREEZE_DIR / "lexicons.json").unlink()
    (fake_repo / "agent" / "lexicons.py").write_text(
        'LEXICONS = {"es": {"_SAFETY": ("fuego",)}}\n', encoding="utf-8")  # English gutted
    capsys.readouterr()

    assert freeze.write_snapshots() == 1
    err = capsys.readouterr().err
    assert "lexicons.json" in err and "agent/lexicons.py" in err
    assert not (freeze.FREEZE_DIR / "lexicons.json").exists(), "refused, yet still wrote"
    assert json.loads((freeze.FREEZE_DIR / "agent.json").read_text()) == {}


def test_force_still_re_baselines_over_a_deleted_snapshot(
        fake_repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """The escape hatch for someone who really does intend to re-baseline."""
    assert freeze.write_snapshots() == 0
    (freeze.FREEZE_DIR / "lexicons.json").unlink()
    capsys.readouterr()

    assert freeze.write_snapshots(force=True) == 0
    assert "re-baselined 1 module(s)" in capsys.readouterr().out
    assert json.loads((freeze.FREEZE_DIR / "lexicons.json").read_text()) == {
        "en": {"_SAFETY": ["fire"]}, "es": {"_SAFETY": ["fuego"]}}


def test_same_lexicon_defined_twice_with_different_words_is_an_error(tmp_path: Path) -> None:
    """Mid-T3 duplication must not be papered over by the union."""
    old = tmp_path / "old.py"
    old.write_text('_SAFETY = ("fire",)\n', encoding="utf-8")
    new = tmp_path / "new.py"
    new.write_text('LEXICONS = {"en": {"_SAFETY": ("fire", "smoke")}}\n', encoding="utf-8")

    with pytest.raises(ValueError, match="en/_SAFETY"):
        union_lexicons({"old.py": extract_lexicons(old), "new.py": extract_lexicons(new)})

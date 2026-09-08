"""T12 harness tests: the pieces of eval/run_eval.py that are pure logic, not a full
benchmark run -- the extractor CLI mapping, per-ticket isolation of an unrecognised
`lang`, the effective-lexicon-count algorithm, and the FR-20 rate-spec wiring.

Nothing here needs an API key (global constraint 4): the model-extractor preflight is
exercised only on its no-credentials path, which is local and offline by construction.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agent import extract as extract_mod
from agent.lexicons import LEXICONS
from eval import run_eval, scorer, stats


# --------------------------------------------------------------------------- #
# Part 1: --extractor keyword|model <-> the seam's stub|llm.
# --------------------------------------------------------------------------- #
def test_extractor_cli_choices_come_from_the_seam() -> None:
    assert set(run_eval._SEAM_TO_CLI) == extract_mod.EXTRACTORS
    assert set(run_eval._EXTRACTOR_CHOICES) == set(run_eval._CLI_TO_SEAM)
    assert run_eval._CLI_TO_SEAM["keyword"] == "stub"
    assert run_eval._CLI_TO_SEAM["model"] == "llm"


def test_extractor_mapping_is_a_bijection_onto_the_seam() -> None:
    # Every seam name maps to exactly one CLI name and back -- no CLI value is left
    # unmapped, and none maps to a seam name outside extract.EXTRACTORS.
    for cli, seam in run_eval._CLI_TO_SEAM.items():
        assert run_eval._SEAM_TO_CLI[seam] == cli


def test_preflight_extractor_is_none_for_keyword() -> None:
    assert run_eval._preflight_extractor("stub") is None


def test_preflight_extractor_reports_missing_credentials_offline(monkeypatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    try:
        import anthropic  # noqa: F401
    except ModuleNotFoundError:
        reason = run_eval._preflight_extractor("llm")
        assert reason is not None and "anthropic" in reason
        return
    reason = run_eval._preflight_extractor("llm")
    assert reason is not None and "credentials" in reason


# --------------------------------------------------------------------------- #
# Part 1: an unrecognised ticket['lang'] is isolated, not fatal to the sweep.
# --------------------------------------------------------------------------- #
def test_unknown_lang_is_isolated_not_fatal(monkeypatch) -> None:
    from services_mock import data as data_mod

    good = data_mod.tickets("en")[:3]
    bad = {"id": "ZZ-UNKNOWN-LANG", "lang": "fr", "message": "bonjour", "split": "seed",
           "tier": "clean_return", "order_id": None, "customer_email": None,
           "intent": "wismo",
           "expected": {"answerable": True, "action": "resolve", "outcome": "status_provided"}}
    fake = [bad] + good
    monkeypatch.setattr(run_eval.data, "tickets", lambda lang="en": fake if lang == "en" else [])

    rows, resolutions, errors = run_eval._run("stub", True, lang="en", extractor="stub")

    assert len(errors) == 1
    assert errors[0]["ticket_id"] == "ZZ-UNKNOWN-LANG"
    assert errors[0]["lang"] == "fr"
    assert "fr" in errors[0]["error"]
    assert len(rows) == len(good)
    assert len(resolutions) == len(good)


def test_unknown_lang_does_not_abort_a_multi_ticket_sweep(monkeypatch) -> None:
    """A bad ticket in the MIDDLE of the sweep must not stop the ones after it."""
    from services_mock import data as data_mod

    good = data_mod.tickets("en")[:4]
    bad = {"id": "ZZ-MID", "lang": "xx", "message": "hola", "split": "seed",
           "tier": "clean_return", "order_id": None, "customer_email": None,
           "intent": "wismo",
           "expected": {"answerable": True, "action": "resolve", "outcome": "status_provided"}}
    fake = good[:2] + [bad] + good[2:]
    monkeypatch.setattr(run_eval.data, "tickets", lambda lang="en": fake if lang == "en" else [])

    rows, resolutions, errors = run_eval._run("stub", True, lang="en", extractor="stub")

    assert [e["ticket_id"] for e in errors] == ["ZZ-MID"]
    assert {r["ticket_id"] for r in rows} == {t["id"] for t in good}


# --------------------------------------------------------------------------- #
# Part 3: effective lexicon counts (subsumption-based dead-entry detection).
# --------------------------------------------------------------------------- #
def test_spanish_defective_effective_count_matches_the_named_example() -> None:
    counts = run_eval._effective_lexicon_counts()
    es_def = counts["es"]["lists"]["_DEFECTIVE"]
    assert es_def["raw"] == 23
    assert es_def["effective"] == 21
    assert es_def["dead"] == ["rotas", "rotos"]


def test_effective_count_never_exceeds_raw() -> None:
    counts = run_eval._effective_lexicon_counts()
    for lang, info in counts.items():
        for name, v in info["lists"].items():
            assert v["effective"] <= v["raw"], f"{lang}/{name}"
            assert v["effective"] == v["raw"] - len(v["dead"])


def test_effective_lexicon_counts_covers_every_list_in_both_languages() -> None:
    counts = run_eval._effective_lexicon_counts()
    assert set(counts) == set(LEXICONS)
    for lang, lex in LEXICONS.items():
        assert set(counts[lang]["lists"]) == set(lex)


def test_english_safety_effective_count_catches_internal_boundary_dead_entry() -> None:
    """Review finding: a `w.startswith(v)` prefix-only rule missed this one. `_has`'s
    matcher is `(?<!\\w)(?:...)` -- a LEADING boundary only, no trailing one -- so
    `"fire"` matches inside `"caught fire"` at the space (index 7), not just at index
    0. `"caught fire"` is dead (subsumed by `"fire"`) even though it does not start
    with `"fire"`. This is the corrected en/_SAFETY figure: 9 effective of 10 raw,
    not the previously-published 10/10."""
    counts = run_eval._effective_lexicon_counts()
    en_safety = counts["en"]["lists"]["_SAFETY"]
    assert en_safety["raw"] == 10
    assert en_safety["effective"] == 9
    assert en_safety["dead"] == ["caught fire"]
    assert counts["en"]["effective_total"] == 55
    assert counts["en"]["raw_total"] == 60


def test_dead_classification_matches_has_removal_property() -> None:
    """Property test (review finding 2): for every entry `w` in every lexicon,
    removing `w` leaves `_has` unchanged on a probe that contains it (probe = `w`
    itself, which every entry trivially matches when it is still in the list) IF AND
    ONLY IF `_effective_lexicon_counts` classifies `w` as dead. This ties the
    classification directly to `_has`'s real behaviour, so it cannot silently drift
    from what the matcher actually does the way the old `w.startswith(v)` prefix-only
    rule did (it missed English `_SAFETY`'s `"caught fire"` entirely -- see the test
    above). Reintroducing the prefix-only rule inside `_effective_lexicon_counts`
    makes THIS test fail on `_SAFETY`, because `_has` still (correctly) says
    `"caught fire"` is reachable-free, but the prefix rule would call it alive."""
    from agent.agent import _has

    counts = run_eval._effective_lexicon_counts()
    for lang, lex in LEXICONS.items():
        for name, words in lex.items():
            dead_here = set(counts[lang]["lists"][name]["dead"])
            for w in words:
                others = tuple(v for v in words if v != w)
                unchanged_on_removal = _has(w, words) == _has(w, others)
                assert unchanged_on_removal == (w in dead_here), (lang, name, w)


# --------------------------------------------------------------------------- #
# Part 2: FR-20 wiring -- _RATE_SPEC covers every metric this harness prints, and
# _fmt produces the literal fmt_rate form (raw counts + Wilson CI beside the rate).
# --------------------------------------------------------------------------- #
def test_rate_spec_covers_every_printed_metric_row() -> None:
    printed = {key for key, _, _ in run_eval._METRIC_ROWS} | {"safety_routing_recall",
                                                               "silent_fact_error_rate"}
    assert printed <= set(run_eval._RATE_SPEC)


def test_fmt_matches_stats_fmt_rate_literal() -> None:
    summary = {"n": 43, "counts": {"hallucination": 6, "resolved": 43}}
    assert run_eval._fmt(summary, "hallucination_rate") == stats.fmt_rate(6, 43)
    assert run_eval._fmt(summary, "hallucination_rate") == "14% (6/43, 95% CI 6–27%)"


def test_clause_metric_map_covers_every_win_condition_clause() -> None:
    # win_condition's clause keys (eval/scorer.py) must all resolve to a _RATE_SPEC
    # entry, or the report would silently print a clause with no rate beside it.
    fake_summary = {
        "hallucination_rate": 0.0, "resolution_recall": 0.8, "handoff_precision": 0.9,
        "silent_fact_error_rate": 0.0, "safety_routing_recall": 1.0,
        "counts": {"hallucination": 0, "resolved": 10, "answerable_correct": 8,
                   "answerable": 10, "handoffs_justified": 9, "handoffs_pred": 10,
                   "silent_fact_error": 0, "safety_routing_hits": 5, "safety_routing_gold": 5},
    }
    _, clauses = scorer.win_condition(fake_summary)
    for clause in clauses:
        metric_key = run_eval._CLAUSE_METRIC[clause]
        assert metric_key in run_eval._RATE_SPEC
        run_eval._fmt(fake_summary, metric_key)  # must not raise


# --------------------------------------------------------------------------- #
# Finding 3: M-6 (`scorer.extractor_agreement`) wired into the harness.
# --------------------------------------------------------------------------- #
def test_extractor_agreement_unavailable_without_model_arm() -> None:
    """The default run (`--extractor keyword`, current_seam='stub') never starts a
    live model arm just to compute M-6 -- that would silently break the "offline,
    zero calls" guarantee the header makes for the keyword path. M-6 is reported
    explicitly unavailable instead of silently missing."""
    result = run_eval._extractor_agreement_result(
        "stub", "en", held_out=False, use_soft_entailment=False,
        current_seam="stub", current_rows=[])
    assert result["available"] is False
    assert result["result"] is None
    assert "ANTHROPIC_API_KEY" in result["reason"] or "--extractor model" in result["reason"]
    assert run_eval._m6_line(result).startswith("n/a --")


def test_extractor_agreement_available_when_model_arm_already_ran(monkeypatch) -> None:
    """When the CURRENT run's extractor arm already is 'llm' (only reachable via an
    explicit --extractor model that has already passed the credentials preflight),
    M-6 adds the keyword arm for free and reports a real agreement figure -- no
    network call in this test: `_run` is monkeypatched to return synthetic rows."""
    def fake_run(backend, use_gate, *, held_out=False, use_soft_entailment=False,
                lang="en", extractor="stub"):
        assert extractor == "stub"  # the only arm M-6 is allowed to start itself
        rows = [
            {"ticket_id": "T1", "fact_applicable": True, "recorded_defective": True},
            {"ticket_id": "T2", "fact_applicable": True, "recorded_defective": False},
            {"ticket_id": "T3", "fact_applicable": False, "recorded_defective": None},
        ]
        return rows, [], []

    monkeypatch.setattr(run_eval, "_run", fake_run)
    model_rows = [
        {"ticket_id": "T1", "fact_applicable": True, "recorded_defective": True},   # agree
        {"ticket_id": "T2", "fact_applicable": True, "recorded_defective": True},   # disagree
        {"ticket_id": "T3", "fact_applicable": False, "recorded_defective": None},  # excluded
    ]
    result = run_eval._extractor_agreement_result(
        "stub", "en", held_out=False, use_soft_entailment=False,
        current_seam="llm", current_rows=model_rows)

    assert result["available"] is True
    assert result["result"] == scorer.extractor_agreement(
        [{"ticket_id": "T1", "fact_applicable": True, "recorded_defective": True},
         {"ticket_id": "T2", "fact_applicable": True, "recorded_defective": False},
         {"ticket_id": "T3", "fact_applicable": False, "recorded_defective": None}],
        model_rows,
    )
    assert result["result"]["n"] == 2
    assert result["result"]["count"] == 1
    assert result["result"]["disagreements"] == ["T2"]
    assert "50%" in run_eval._m6_line(result)


# --------------------------------------------------------------------------- #
# Finding 6: the exact n at which a zero-success Wilson upper bound reaches <=2%.
# --------------------------------------------------------------------------- #
def test_zero_success_2pct_threshold_is_189_not_185() -> None:
    n, hi_before, hi_at = run_eval._zero_success_2pct_threshold()
    assert n == 189
    assert hi_before > 0.02          # n=188 still fails the <=2% test
    assert hi_at <= 0.02             # n=189 is the first n that passes it
    # The prior implementer's rejected candidates both still fail:
    assert stats.wilson_interval(0, 184)[1] > 0.02
    assert stats.wilson_interval(0, 185)[1] > 0.02


# --------------------------------------------------------------------------- #
# Finding 5: --lang es must not overwrite the English eval/report.md.
# --------------------------------------------------------------------------- #
def test_report_filename_is_per_language() -> None:
    assert run_eval._report_filename("en") == "report.md"
    assert run_eval._report_filename("es") == "report-es.md"
    assert run_eval._report_filename("es") != run_eval._report_filename("en")

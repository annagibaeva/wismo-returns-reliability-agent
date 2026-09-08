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

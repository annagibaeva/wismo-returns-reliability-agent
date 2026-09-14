"""FR-6 / FR-21: the translate-at-the-edge seam.

Approach 1 has to differ from Approach 2 in exactly one place, or the comparison
between them measures the fork rather than the architecture. These tests pin that:
`edge="off"` is byte-identical to the pipeline that existed before the flag, and
`edge="oracle"` changes the text and the language and nothing else about how the
ticket is handled.

The `llm` backend is never exercised live here -- global constraint 4, no test may
require an API key. What IS exercised is the boundary around it: an unconfigured
machine must raise rather than quietly return "could not translate" for every ticket
and produce a results file that looks like a real Approach 1 measurement.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agent import translate                    # noqa: E402
from agent.agent import resolve_ticket         # noqa: E402
from agent.schemas import AuditLogger          # noqa: E402
from services_mock import data                 # noqa: E402


def _ticket(ticket_id: str) -> dict:
    for t in data.all_tickets(None):
        if t["id"] == ticket_id:
            return t
    raise AssertionError(f"no such ticket: {ticket_id}")


def test_unknown_backend_is_refused_by_name():
    with pytest.raises(ValueError, match="unknown edge backend"):
        translate.translate_to_english(_ticket("ES-CR-01"), backend="google")


def test_off_returns_the_message_and_language_untouched():
    t = _ticket("ES-CR-01")
    assert translate.translate_to_english(t, backend="off") == (t["message"], "es")


def test_english_tickets_are_never_translated_even_under_approach_1():
    """The English arm is the control. Round-tripping it through a translator would
    make the two approaches differ on the one language with nothing to translate."""
    t = _ticket("CR-01")
    for backend in ("off", "oracle", "llm"):
        assert translate.translate_to_english(t, backend=backend) == (t["message"], "en")


@pytest.mark.parametrize("variant, source", [("ES-CR-01", "CR-01"), ("ID-CR-01", "CR-01")])
def test_oracle_returns_the_english_source_and_switches_the_language(variant, source):
    text, lang = translate.translate_to_english(_ticket(variant), backend="oracle")
    assert text == _ticket(source)["message"]
    assert lang == "en", "downstream must be told it is now reading English"


def test_oracle_is_an_upper_bound_not_a_translator():
    """Stated as a test so the property cannot quietly stop being true: the oracle
    reads `variant_of`, so its output is the fixture the ticket was generated from
    and is exact by construction. It reads no `expected` block -- it can leak the
    message, never the answer."""
    t = _ticket("ES-FA-01")
    text, _ = translate.translate_to_english(t, backend="oracle")
    source = _ticket(t["variant_of"])
    assert text == source["message"]
    assert str(source["expected"]) not in text


def test_fr21_records_both_the_original_and_the_translation():
    """Without the original in the trail, the audit records a claim about a message
    nobody can check."""
    audit = AuditLogger()
    t = _ticket("ES-CR-01")
    translate.translate_to_english(t, backend="oracle", audit=audit)
    steps = [s for s in audit.steps if s.name == "translate_at_edge"]
    assert len(steps) == 1
    out = steps[0].output
    assert out["original"] == t["message"]
    assert out["translated"] == _ticket("CR-01")["message"]
    assert out["from"] == "es" and out["to"] == "en"


def test_no_audit_entry_when_nothing_was_translated():
    audit = AuditLogger()
    translate.translate_to_english(_ticket("ES-CR-01"), backend="off", audit=audit)
    assert [s for s in audit.steps if s.name == "translate_at_edge"] == []


def test_a_failed_translation_passes_the_original_through_and_says_so():
    """Approach 1 with a broken translator is the original text hitting English
    lexicons. That is what the failure looks like in production, so it is scored
    rather than hidden -- but the audit has to record that it happened."""
    audit = AuditLogger()
    orphan = dict(_ticket("ES-CR-01"))
    orphan.pop("variant_of")           # oracle cannot resolve a source
    text, lang = translate.translate_to_english(orphan, backend="oracle", audit=audit)
    assert (text, lang) == (orphan["message"], "es")
    step = [s for s in audit.steps if s.name == "translate_at_edge"][0]
    assert step.output["translated"] is None
    assert "failed" in step.output["note"]


# --------------------------------------------------------------------------- #
# The flag, end to end through resolve_ticket
# --------------------------------------------------------------------------- #

def test_edge_off_is_byte_identical_to_the_pipeline_without_the_flag():
    """FR-6 asks for a flag, not a branch. If `off` changed any outcome, every
    Approach 2 number already published would be invalidated by this commit."""
    for t in data.tickets("es")[:20]:
        a = resolve_ticket(t, backend="stub", use_gate=True)
        b = resolve_ticket(t, backend="stub", use_gate=True, edge="off")
        assert (a.action, a.outcome, a.cited_rule_ids, a.facts) == \
               (b.action, b.outcome, b.cited_rule_ids, b.facts)


def test_oracle_makes_a_spanish_ticket_behave_like_its_english_source():
    """The point of Approach 1: after translation the pipeline is running English.

    Scored on the fault tier, where the Spanish keyword extractor has real work to
    do -- if translation were not reaching the extractor, the recorded `defective`
    would still be the Spanish reading.
    """
    es = _ticket("ES-FA-01")
    en = _ticket("FA-01")
    translated = resolve_ticket(es, backend="stub", use_gate=True, edge="oracle")
    direct_en = resolve_ticket(en, backend="stub", use_gate=True)
    assert translated.facts.get("defective") == direct_en.facts.get("defective")
    assert translated.action == direct_en.action
    assert translated.outcome == direct_en.outcome


def test_the_oracle_arm_is_not_vacuously_equal_to_the_direct_arm():
    """Guards the test above: it would pass trivially if Spanish and English already
    agreed everywhere. At least one Spanish ticket must actually be changed by
    turning the flag on, or the comparison proves nothing.
    """
    changed = 0
    for t in data.tickets("es"):
        off = resolve_ticket(t, backend="stub", use_gate=True, edge="off")
        on = resolve_ticket(t, backend="stub", use_gate=True, edge="oracle")
        if (off.action, off.outcome, off.facts.get("defective")) != \
           (on.action, on.outcome, on.facts.get("defective")):
            changed += 1
    assert changed > 0, "edge='oracle' changed nothing at all -- the flag is not wired through"


def test_resolution_records_which_architecture_ran():
    """FR-21's traceability requirement reaches the resolution, not just the logs."""
    res = resolve_ticket(_ticket("ES-CR-01"), backend="stub", use_gate=True, edge="oracle")
    steps = [s for s in res.audit_trail if s.name == "translate_at_edge"]
    assert len(steps) == 1 and steps[0].output["backend"] == "oracle"


def test_missing_credentials_raise_rather_than_reading_as_untranslatable(monkeypatch):
    """The extractor's hard-won lesson, applied here: a keyless run must fail loudly.

    Silently returning `None` for every ticket would produce an Approach 1 results
    file full of passthrough originals -- indistinguishable from a real measurement
    that found translation unhelpful.
    """
    pytest.importorskip("anthropic")
    import anthropic

    class _Unconfigured:
        api_key = None
        auth_token = None
        credentials = None

    monkeypatch.setattr(anthropic, "Anthropic", lambda *a, **k: _Unconfigured())
    with pytest.raises(RuntimeError, match="no Anthropic credentials"):
        translate._llm_translate("hola, mi pedido llegó roto", "es")


# --------------------------------------------------------------------------- #
# The comparison itself (FR-6 / D-1 / BRD §16 item 10)
# --------------------------------------------------------------------------- #

def test_english_is_the_control_and_the_architecture_cannot_move_it():
    """If Approach 1 changed a single English outcome, the comparison would be
    measuring the translation step's noise rather than the architecture."""
    from eval import run_eval

    cmp = run_eval._approach_comparison("stub", "stub", "stub", "oracle")
    assert cmp["en"]["n_moved"] == 0
    assert cmp["en"]["moved_ticket_ids"] == []


def test_approach_1_collapses_every_language_onto_the_english_pipeline():
    """The structural fact the recommendation rests on: after translation there is
    only one pipeline, so Approach 1 scores the same in every language -- and that
    score is English's. Anything else means translation is not reaching downstream.
    """
    from eval import run_eval

    cmp = run_eval._approach_comparison("stub", "stub", "stub", "oracle")
    recalls = {lang: cmp[lang]["arms"]["approach_1"]["summary"]["resolution_recall"]
               for lang in ("en", "es", "id")}
    assert len(set(recalls.values())) == 1, recalls


def test_the_comparison_is_not_vacuous_in_the_non_english_arms():
    """Guards the two tests above: English moving nothing is only meaningful if the
    architecture moves something somewhere."""
    from eval import run_eval

    cmp = run_eval._approach_comparison("stub", "stub", "stub", "oracle")
    assert cmp["es"]["n_moved"] > 0 and cmp["id"]["n_moved"] > 0


def test_the_recommendation_is_derived_from_the_run_not_hardcoded():
    """BRD §11.2 counts a headline written before the data as project failure, so
    the recommendation text has to move when the numbers move. Fed a synthetic
    comparison where the direct read loses badly, it must stop claiming the direct
    read beats the ceiling."""
    from eval import run_eval

    def _block(recall):
        return {"arms": {"approach_2": {"summary": {"resolution_recall": recall}},
                         "approach_1": {"summary": {"resolution_recall": 0.9}}},
                "moved_ticket_ids": [], "n_moved": 0}

    strong = {"en": _block(0.90), "es": _block(0.95), "id": _block(0.95)}
    weak = {"en": _block(0.90), "es": _block(0.10), "id": _block(0.10)}

    strong_text = "\n".join(run_eval._recommendation_lines(strong, edge="oracle"))
    weak_text = "\n".join(run_eval._recommendation_lines(weak, edge="oracle"))

    assert "already meet or beat that ceiling" in strong_text
    assert "already meet or beat that ceiling" not in weak_text
    assert "score below the ceiling" in weak_text


def test_the_oracle_caveat_is_dropped_when_a_real_translator_was_used():
    """The upper-bound warning must not be boilerplate that prints either way."""
    from eval import run_eval

    block = {"arms": {"approach_2": {"summary": {"resolution_recall": 0.9}},
                      "approach_1": {"summary": {"resolution_recall": 0.9}}},
             "moved_ticket_ids": [], "n_moved": 0}
    cmp = {lang: block for lang in ("en", "es", "id")}
    assert "upper bound" in "\n".join(run_eval._recommendation_lines(cmp, edge="oracle"))
    assert "upper bound" not in "\n".join(run_eval._recommendation_lines(cmp, edge="llm"))

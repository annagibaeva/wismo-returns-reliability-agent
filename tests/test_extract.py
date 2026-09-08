"""Tests for the fact-reading seam (agent/extract.py), introduced in T5.

Covers: both languages behind extract_facts, the stub backend's False-not-None
behaviour (the documented asymmetry with the eventual llm backend), and that
resolve_ticket routes fact extraction through the seam correctly for a
non-English ticket.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pytest

from agent import extract as extract_mod
from agent import llm as llm_mod
from agent.agent import resolve_ticket
from agent.extract import extract_facts
from services_mock import data


def _extract_step(res):
    """The single `extract_facts` entry from a Resolution's audit trail."""
    steps = [s for s in res.audit_trail if s.name == "extract_facts"]
    assert len(steps) == 1, f"expected exactly one extract_facts step, got {len(steps)}"
    return steps[0]


# ---- both languages ----

def test_extract_facts_english_defect():
    assert extract_facts("the blender is broken and leaking", lang="en", backend="stub") == \
        {"defective": True}


def test_extract_facts_english_no_defect():
    assert extract_facts("I'd like to return this, it doesn't fit", lang="en", backend="stub") == \
        {"defective": False}


def test_extract_facts_spanish_defect():
    assert extract_facts("el producto llegó defectuoso, quiero una devolución", lang="es",
                         backend="stub") == {"defective": True}


def test_extract_facts_spanish_no_defect():
    assert extract_facts("el teléfono funciona bien pero llegó tarde", lang="es",
                         backend="stub") == {"defective": False}


def test_extract_facts_defaults_to_english_lexicon():
    assert extract_facts("this is broken") == {"defective": True}


# ---- the FR-5 asymmetry: the keyword backend can only say False, never None ----

def test_stub_backend_returns_false_not_none_for_unclear_message():
    # No defect keyword anywhere in this message. A model backend could say "I
    # don't know" (None); the keyword backend has no such state -- it reads
    # silence on the topic as a confident claim the item works.
    result = extract_facts("I would like a status update on my package please", lang="en",
                           backend="stub")
    assert result["defective"] is False
    assert result["defective"] is not None


def test_stub_backend_never_produces_none():
    # Swept across a mix of defect and non-defect language in both lexicons --
    # every value must be a bool, never None, regardless of which side it lands on.
    messages = [
        ("the toaster won't turn on", "en"),
        ("I'd like to exchange this for a different size", "en"),
        ("el ventilador interno funciona correctamente", "es"),
        ("está roto y quiero un reembolso", "es"),
    ]
    for msg, lang in messages:
        result = extract_facts(msg, lang=lang, backend="stub")
        assert result["defective"] in (True, False)


def test_llm_backend_not_yet_implemented():
    # Global constraint: never write a test that requires an API key. This checks
    # the seam raises before attempting any network call, not that it produces
    # results -- the model backend arrives in a later task.
    with pytest.raises(NotImplementedError):
        extract_facts("da igual", lang="en", backend="llm")


# ---- resolve_ticket routes through the seam, with the ticket's own language ----

def test_resolve_ticket_uses_spanish_lexicon_for_spanish_return_ticket():
    base = data.tickets()[0]  # ORD-2001, single item, clean return
    ticket = {**base, "id": "es-defect-seam-test", "lang": "es",
              "message": "el producto llegó defectuoso, quiero una devolución"}
    res = resolve_ticket(ticket, backend="stub", use_gate=True)
    assert res.facts["defective"] is True


def test_resolve_ticket_spanish_working_item_is_not_a_defect_claim():
    base = data.tickets()[0]
    ticket = {**base, "id": "es-nodefect-seam-test", "lang": "es",
              "message": "el teléfono funciona bien pero ya no lo quiero, quiero una devolución"}
    res = resolve_ticket(ticket, backend="stub", use_gate=True)
    assert res.facts["defective"] is False


# ---- the extractor is selected independently of the proposer ----

def test_extractor_defaults_independently_of_backend(monkeypatch):
    # Passing only backend="llm" must NOT drag the extractor along with it. The
    # proposer is faked out so this needs no API key (global constraint 4); the
    # point is which backend string reached extract_facts.
    seen = []
    real = extract_mod.extract_facts

    def spy(msg, lang="en", backend="stub"):
        seen.append(backend)
        return real(msg, lang, backend=backend)

    monkeypatch.setattr(extract_mod, "extract_facts", spy)
    monkeypatch.setattr(llm_mod, "propose_return_decision",
                        lambda *a, **k: {"outcome": "ineligible", "cited_rule_ids": [],
                                         "rationale": "fake"})
    base = data.tickets()[0]
    res = resolve_ticket({**base, "id": "independent-default-test"}, backend="llm")
    assert seen == ["stub"], f"extractor followed backend instead of its own default: {seen}"
    assert res.backend == "llm"


def test_extractor_argument_is_forwarded_not_the_backend(monkeypatch):
    # And the reverse: an explicit extractor must reach the seam untouched, even
    # while backend stays "stub".
    seen = []
    monkeypatch.setattr(extract_mod, "extract_facts",
                        lambda msg, lang="en", backend="stub": seen.append(backend) or
                        {"defective": False})
    base = data.tickets()[0]
    resolve_ticket({**base, "id": "explicit-extractor-test"}, backend="stub", extractor="llm")
    assert seen == ["llm"]


def test_resolve_ticket_llm_backend_does_not_raise_not_implemented(monkeypatch):
    # The regression this fixes: forwarding `backend` into the extractor made
    # `--backend llm` raise NotImplementedError before it ever reached the proposer.
    monkeypatch.setattr(llm_mod, "propose_return_decision",
                        lambda *a, **k: {"outcome": "ineligible", "cited_rule_ids": [],
                                         "rationale": "fake"})
    base = data.tickets()[0]
    res = resolve_ticket({**base, "id": "llm-backend-reaches-proposer"}, backend="llm",
                         extractor="stub")
    assert res.facts["defective"] is False


# ---- the extractor may not overwrite order-database facts ----

def test_out_of_contract_key_fails_loudly(monkeypatch):
    # A future model extractor hallucinating an order fact must not be able to
    # overwrite the authoritative order record -- and must not be silently dropped
    # either, which would hide the same bug.
    monkeypatch.setattr(extract_mod, "_stub_extract",
                        lambda msg, lang: {"defective": True, "final_sale": False})
    with pytest.raises(ValueError, match="final_sale"):
        extract_facts("this is broken", lang="en", backend="stub")


def test_out_of_contract_key_fails_loudly_through_resolve_ticket(monkeypatch):
    monkeypatch.setattr(extract_mod, "_stub_extract",
                        lambda msg, lang: {"defective": True, "order_value": 9999})
    base = data.tickets()[0]
    with pytest.raises(ValueError, match="order_value"):
        resolve_ticket({**base, "id": "out-of-contract-test"}, backend="stub")


def test_prose_facts_contract_is_exactly_defective():
    assert extract_mod.PROSE_FACTS == frozenset({"defective"})


def test_stub_return_is_within_the_prose_contract():
    assert set(extract_facts("the blender is broken", lang="en")) <= extract_mod.PROSE_FACTS


# ---- the audit trail names the extractor and the language ----

def test_audit_entry_records_extractor_and_lang():
    base = data.tickets()[0]
    res = resolve_ticket({**base, "id": "audit-extractor-test"}, backend="stub")
    step = _extract_step(res)
    assert step.input["extractor"] == "stub"
    assert step.input["lang"] == "en"
    assert step.input["order_id"] == res.order_id


def test_audit_entry_records_the_extractor_actually_used(monkeypatch):
    # M-6 needs to tell a keyword-derived fact from a model-derived one; the audit
    # entry must name the extractor that ran, not the proposer's backend.
    monkeypatch.setattr(extract_mod, "extract_facts",
                        lambda msg, lang="en", backend="stub": {"defective": False})
    monkeypatch.setattr(llm_mod, "propose_return_decision",
                        lambda *a, **k: {"outcome": "ineligible", "cited_rule_ids": [],
                                         "rationale": "fake"})
    base = data.tickets()[0]
    res = resolve_ticket({**base, "id": "audit-extractor-llm-test"}, backend="llm",
                         extractor="llm")
    step = _extract_step(res)
    assert step.input["extractor"] == "llm"
    assert res.backend == "llm"


def test_audit_entry_records_the_ticket_language():
    base = data.tickets()[0]
    ticket = {**base, "id": "audit-lang-test", "lang": "es",
              "message": "el producto llegó defectuoso, quiero una devolución"}
    res = resolve_ticket(ticket, backend="stub")
    assert _extract_step(res).input["lang"] == "es"

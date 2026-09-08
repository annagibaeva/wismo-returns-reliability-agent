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

from agent.agent import resolve_ticket
from agent.extract import extract_facts
from services_mock import data


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

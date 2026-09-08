"""The T10 cross-language integrity guard: a Spanish variant's `expected` block must
equal its English source's exactly. `services_mock/data.py::_validate_tickets` is
where that claim is enforced -- a translation may change the words, never the gold
answer it is scored against.

Every other guard on this branch was mutation-tested during its own task review and
caught a broken implementation. This one was not: a whole-branch review found that
replacing its body with `if False:` still left all 359 tests passing, because no
test fed `_validate_tickets` a tampered variant. This file is that missing negative
test -- see the final fix report for the break/fail/restore drill that proved it
bites.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from services_mock.data import _validate_tickets  # noqa: E402


def _en(id_, expected):
    return {"id": id_, "split": "seed", "lang": "en", "expected": expected}


def _es(id_, variant_of, expected):
    return {"id": id_, "split": "seed", "lang": "es", "variant_of": variant_of, "expected": expected}


def test_validate_tickets_accepts_a_variant_whose_expected_matches_its_source():
    tickets = [_en("CR-01", {"outcome": "eligible", "action": "resolve"}),
               _es("ES-CR-01", "CR-01", {"outcome": "eligible", "action": "resolve"})]
    _validate_tickets(tickets)  # must not raise


def test_validate_tickets_rejects_a_variant_whose_expected_diverges_from_its_source():
    """The central T10 integrity claim, proven to actually bite: a Spanish variant
    that quietly changes the gold answer (not just the wording) must be rejected."""
    tickets = [
        _en("CR-01", {"outcome": "eligible", "action": "resolve"}),
        _es("ES-CR-01", "CR-01", {"outcome": "ineligible", "action": "resolve"}),  # tampered gold
    ]
    with pytest.raises(ValueError, match="expected block does not match"):
        _validate_tickets(tickets)


def test_validate_tickets_rejects_divergence_in_a_single_nested_field():
    """Same claim, narrower probe: the blocks are compared for exact equality, so a
    divergence buried in one field (not a wholesale swap) must also be caught."""
    tickets = [
        _en("FA-01", {"outcome": "eligible", "action": "resolve", "gold_defective": True}),
        _es("ES-FA-01", "FA-01",
            {"outcome": "eligible", "action": "resolve", "gold_defective": False}),
    ]
    with pytest.raises(ValueError, match="expected block does not match"):
        _validate_tickets(tickets)

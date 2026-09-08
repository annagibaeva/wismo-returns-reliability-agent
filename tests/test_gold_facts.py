"""fixtures/gold_facts.json + eval/gold.py: coverage, mechanical accuracy, and the
one place the two sources of truth for `defective` (T8's `gold_defective` and this
file's own copy) are checked against each other.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from eval import gold                          # noqa: E402
from services_mock import data, order_api      # noqa: E402


def _order_id_or_email_matches(ticket: dict) -> list[dict]:
    """The order(s) `agent/agent.py::_lookup` would resolve for this ticket, without
    importing `agent/` — mirrors its by-id-else-by-email logic so this test does not
    depend on the module under the isolation guard."""
    oid = ticket.get("order_id")
    if oid:
        try:
            return [order_api.get_order(oid)]
        except order_api.OrderNotFound:
            return []
    return order_api.find_orders_by_email(ticket.get("customer_email"))


# --------------------------------------------------------------------------- #
# 1. Every ticket has an entry; no entry lacks a ticket.
# --------------------------------------------------------------------------- #

def test_every_ticket_has_a_gold_entry_and_vice_versa():
    ticket_ids = {t["id"] for t in data.all_tickets()}
    gold_ids = set(gold.all_facts())
    assert ticket_ids == gold_ids
    assert len(ticket_ids) == 97


def test_gold_entries_carry_all_nine_keys():
    expected_keys = {
        "defective", "days_since_delivery", "final_sale", "category",
        "goodwill_grant", "fraud_hold", "order_value", "status", "order_found",
    }
    for tid, facts in gold.all_facts().items():
        assert set(facts) == expected_keys, tid


# --------------------------------------------------------------------------- #
# 2. Order-derived facts match order_api.order_facts exactly, for every ticket
#    that resolves to a single order.
# --------------------------------------------------------------------------- #

def test_order_derived_facts_match_order_api_exactly():
    checked_single, checked_absent, checked_ambiguous = 0, 0, 0
    for t in data.all_tickets():
        matches = _order_id_or_email_matches(t)
        recorded = gold.facts_for(t["id"])
        if len(matches) == 1:
            mechanical = order_api.order_facts(matches[0])
            for key, value in mechanical.items():
                assert recorded[key] == value, (t["id"], key)
            checked_single += 1
        elif len(matches) == 0:
            assert recorded["order_found"] is False, t["id"]
            for key in ("days_since_delivery", "final_sale", "category", "goodwill_grant",
                        "fraud_hold", "order_value", "status"):
                assert recorded[key] is None, (t["id"], key)
            checked_absent += 1
        else:
            assert recorded["order_found"] is None, t["id"]
            for key in ("days_since_delivery", "final_sale", "category", "goodwill_grant",
                        "fraud_hold", "order_value", "status"):
                assert recorded[key] is None, (t["id"], key)
            checked_ambiguous += 1
    assert checked_single + checked_absent + checked_ambiguous == 97
    assert checked_single > 0 and checked_absent > 0 and checked_ambiguous > 0


def test_ambiguous_and_absent_orders_are_the_tickets_the_draft_named():
    # UN-01/HO-UN-01 (ORD-9999) and UN-09 (ORD-8888) cite an order that does not
    # exist; UN-10/UN-12 have no order_id and the email has zero orders.
    absent = {"UN-01", "HO-UN-01", "UN-09", "UN-10", "UN-12"}
    # UN-13/ASK-02/HO-ASK-02 have no order_id and the email matches two orders.
    ambiguous = {"UN-13", "ASK-02", "HO-ASK-02"}
    for tid in absent:
        assert gold.facts_for(tid)["order_found"] is False, tid
    for tid in ambiguous:
        assert gold.facts_for(tid)["order_found"] is None, tid


# --------------------------------------------------------------------------- #
# 3. gold `defective` agrees with T8's expected.gold_defective for all 17 where
#    both exist.
# --------------------------------------------------------------------------- #

def test_defective_agrees_with_ticket_gold_defective():
    tickets = [t for t in data.all_tickets() if "gold_defective" in t.get("expected", {})]
    assert len(tickets) == 17
    for t in tickets:
        stored = gold.facts_for(t["id"])["defective"]
        ticket_value = t["expected"]["gold_defective"]
        assert stored == ticket_value, t["id"]
        # And the resolver eval/ actually calls agrees too -- it is what enforces this
        # at read time, not just at file-authoring time.
        assert gold.defective_for(t) == ticket_value, t["id"]


def test_defective_for_falls_back_to_gold_facts_outside_the_fault_tier():
    non_fault = [t for t in data.all_tickets() if "gold_defective" not in t.get("expected", {})]
    assert len(non_fault) == 80
    for t in non_fault:
        assert gold.defective_for(t) == gold.facts_for(t["id"])["defective"], t["id"]


# --------------------------------------------------------------------------- #
# 6. The true/false/null tally.
# --------------------------------------------------------------------------- #

def test_defective_tally():
    values = [f["defective"] for f in gold.all_facts().values()]
    true_n = sum(1 for v in values if v is True)
    false_n = sum(1 for v in values if v is False)
    null_n = sum(1 for v in values if v is None)
    assert (true_n, false_n, null_n) == (24, 29, 44)
    assert true_n + false_n + null_n == 97


def test_false_vs_null_rule_is_recorded():
    comment = gold._load()["_comment"]
    assert "false" in comment and "null" in comment
    assert "RET-020" in comment  # the outcome-inert justification, stated explicitly

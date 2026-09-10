"""Locks in the blind spot this whole project exists to measure.

gate.assess(outcome, cited_rule_ids, facts) never sees the customer's message —
only the facts the agent chose to record. So if the agent misreads the customer,
the gate has no way to notice: two opposite rulings on the *same* customer, each
internally consistent with the (differently misread) facts it was handed, both
come back fully grounded. That is not a bug in the gate; it is the reason the
multilingual grounding-gate project is worth building. This test must keep
failing anyone who "fixes" it by giving the gate a second, independent source of
truth to check `facts` against.
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import gate


def test_assess_facts_is_the_only_view_of_the_world():
    # The blind spot exists *because* `facts` is the sole channel through which
    # assess() learns anything about the customer. If a future refactor adds a
    # parameter carrying an independent view (gold facts, the raw message, a
    # second lookup), that channel would let the gate catch the misreading below
    # -- so pin the signature down. This must break the moment that happens.
    params = list(inspect.signature(gate.assess).parameters)
    assert params == ["outcome", "cited_rule_ids", "facts"]


def test_opposite_rulings_on_the_same_customer_both_pass():
    # Same order, same customer: delivered 45 days ago, not final sale. One
    # reading of the customer's message records the item as defective; the
    # opposite reading records it as not defective. Nothing here is malformed --
    # each ruling is exactly grounded in the facts it was given. The gate cannot
    # tell these apart because it never saw the customer, only the recorded
    # facts, so both pass.
    base = {"days_since_delivery": 45, "final_sale": False, "category": "apparel",
            "goodwill_grant": False, "fraud_hold": False}

    defective_reading = gate.assess("eligible", ["RET-020"], dict(base, defective=True))
    assert defective_reading.passed
    assert defective_reading.licensed_outcome == "eligible"
    assert defective_reading.controlling_rule_ids == ["RET-020"]
    assert defective_reading.blocks == []

    not_defective_reading = gate.assess("ineligible", ["RET-008"], dict(base, defective=False))
    assert not_defective_reading.passed
    assert not_defective_reading.licensed_outcome == "ineligible"
    assert not_defective_reading.controlling_rule_ids == ["RET-008"]
    assert not_defective_reading.blocks == []

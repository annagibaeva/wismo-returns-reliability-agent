"""Tests. Run with pytest OR directly:  python tests/test_agent.py"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import kb
from kb.evaluator import evaluate, MissingFact
import gate as grounding_gate
from agent.agent import resolve_ticket, _route
from services_mock import data
from eval import scorer


# ---- evaluator ----

def test_evaluator_basic_and_missing_fact():
    assert evaluate("days_since_delivery <= 30 and final_sale == False",
                    {"days_since_delivery": 12, "final_sale": False}) is True
    assert evaluate("final_sale == True", {"final_sale": False}) is False
    try:
        evaluate("days_since_delivery <= 30", {"final_sale": False})
        assert False, "should raise MissingFact"
    except MissingFact:
        pass


def test_evaluator_rejects_unsafe():
    try:
        evaluate("__import__('os').system('echo hi')", {})
        assert False, "must not evaluate calls"
    except ValueError:
        pass


# ---- KB precedence semantics ----

def test_precedence_final_sale_dominates():
    facts = {"days_since_delivery": 10, "final_sale": True, "category": "clearance",
             "defective": False, "goodwill_grant": False, "fraud_hold": False}
    outcome, ctrl, conflict = kb.licensed_outcome(facts)
    assert outcome == "ineligible" and "RET-012" in ctrl and conflict is None


def test_precedence_defective_overrides_window():
    facts = {"days_since_delivery": 48, "final_sale": False, "category": "apparel",
             "defective": True, "goodwill_grant": False, "fraud_hold": False}
    outcome, ctrl, conflict = kb.licensed_outcome(facts)
    assert outcome == "eligible" and "RET-020" in ctrl


def test_deadlock_detected():
    facts = {"days_since_delivery": 7, "final_sale": False, "category": "apparel",
             "defective": False, "goodwill_grant": True, "fraud_hold": True}
    outcome, ctrl, conflict = kb.licensed_outcome(facts)
    assert outcome is None and conflict == "deadlock"


def test_no_covering_rule_on_missing_fact():
    facts = {"days_since_delivery": None, "final_sale": False, "category": "apparel",
             "defective": False, "goodwill_grant": False, "fraud_hold": False}
    _, _, conflict = kb.licensed_outcome(facts)
    assert conflict == "no_covering_rule"


# ---- the gate ----

def test_gate_blocks_fabricated_rule():
    g = grounding_gate.assess("eligible", ["RET-999"], {"days_since_delivery": 5, "final_sale": False})
    assert not g.passed and g.grounding_blocks


def test_gate_blocks_misapplied_condition():
    # cite the in-window rule on a 60-day-old item -> condition is false
    g = grounding_gate.assess("eligible", ["RET-007"], {"days_since_delivery": 60, "final_sale": False})
    assert not g.passed and any("misapplied" in b["reason"] for b in g.grounding_blocks)


def test_gate_blocks_precedence_miss():
    # in-window eligible cited, but item is final-sale -> higher-priority rule contradicts
    facts = {"days_since_delivery": 10, "final_sale": True, "category": "clearance",
             "defective": False, "goodwill_grant": False, "fraud_hold": False}
    g = grounding_gate.assess("eligible", ["RET-007"], facts)
    assert not g.passed and g.conclusion_blocks


def test_gate_passes_correct_ruling():
    facts = {"days_since_delivery": 12, "final_sale": False, "category": "apparel",
             "defective": False, "goodwill_grant": False, "fraud_hold": False}
    g = grounding_gate.assess("eligible", ["RET-007"], facts)
    assert g.passed


# ---- ask (ambiguous order lookup) ----

def test_un13_asks_not_handoffs():
    t = next(t for t in data.tickets() if t["id"] == "UN-13")
    res = resolve_ticket(t, backend="stub", use_gate=True)
    assert res.action == "ask"
    assert res.action != "handoff"
    assert res.clarifying_question
    assert "ORD-7001" in res.clarifying_question and "ORD-7002" in res.clarifying_question


def test_ask_never_hits_grounding_gate():
    t = next(t for t in data.tickets() if t["id"] == "UN-13")
    res = resolve_ticket(t, backend="stub", use_gate=True)
    assert res.action == "ask"
    assert not any(s.name == "grounding_gate" for s in res.audit_trail)
    row = scorer.classify(res, t)
    assert row["bucket"] == "ask"


def test_single_order_email_lookup_resolves_not_asks():
    # T-020-style: no order_id, but email uniquely resolves → resolve, don't over-ask
    base = next(t for t in data.tickets() if t["id"] == "WI-01")
    t = {**base, "id": "T-020", "order_id": None}
    res = resolve_ticket(t, backend="stub", use_gate=True)
    assert res.action == "resolve"
    assert res.action != "ask"
    assert res.outcome == "status_provided"
    assert res.order_id == "ORD-3001"


# ---- routing ----

def test_routing():
    assert _route("where is my order")[0] == "wismo"
    assert _route("I want to return this jacket")[0] == "return"
    assert _route("the kettle gave me an electric shock")[0] == "out_of_scope"
    assert _route("I'm disputing this charge with my bank")[0] == "out_of_scope"
    assert _route("the seams are leaking, it's faulty")[0] == "return"  # defect => return


# ---- end-to-end ----

def test_gate_on_meets_win_condition():
    rows = [scorer.classify(resolve_ticket(t, backend="stub", use_gate=True), t) for t in data.tickets()]
    summary = scorer.aggregate(rows)
    won, clauses = scorer.win_condition(summary)
    assert won, (summary, clauses)
    assert summary["hallucination_rate"] == 0.0


def test_gate_off_has_more_hallucination_than_on():
    off = scorer.aggregate([scorer.classify(resolve_ticket(t, "stub", False), t) for t in data.tickets()])
    on = scorer.aggregate([scorer.classify(resolve_ticket(t, "stub", True), t) for t in data.tickets()])
    assert off["hallucination_rate"] > on["hallucination_rate"]
    assert on["hallucination_rate"] == 0.0


def test_unanswerable_is_handed_off_not_resolved():
    t = next(t for t in data.tickets() if t["id"] == "UN-08")  # final_sale is null
    res = resolve_ticket(t, backend="stub", use_gate=True)
    assert res.action == "handoff"


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"FAIL {fn.__name__}: {exc}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)

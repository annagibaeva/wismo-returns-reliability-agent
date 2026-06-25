"""Tests. Run with pytest OR directly:  python tests/test_agent.py"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import kb
from kb.evaluator import evaluate, MissingFact
import gate as grounding_gate
from gate.entailment import assess as assess_entailment
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


# ---- soft entailment layer ----

def test_entailment_passes_aligned_explanation():
    expl = ("The cotton t-shirt is within the 30-day return window, so it may be returned "
            "for a full refund.")
    src = kb.get_rule("RET-007")["source_text"]
    assert assess_entailment(expl, ["RET-007"]).passed


def test_entailment_fails_contradiction():
    expl = "Approved for a full refund — the customer is eligible to return this item."
    assert not assess_entailment(expl, ["RET-012"]).passed


def test_entailment_fails_without_policy_anchor():
    assert not assess_entailment("Looks good to me.", ["RET-007"]).passed


def test_soft_layer_off_by_default():
    t = next(t for t in data.tickets() if t["id"] == "CR-01")
    res = resolve_ticket(t, backend="stub", use_gate=True)
    assert not any(s.name == "soft_entailment" for s in res.audit_trail)


def test_soft_layer_only_downgrades():
    """Soft layer may convert resolve→handoff; never the reverse or ask→resolve."""
    for t in data.all_tickets():
        baseline = resolve_ticket(t, backend="stub", use_gate=True, use_soft_entailment=False)
        with_soft = resolve_ticket(t, backend="stub", use_gate=True, use_soft_entailment=True)
        if baseline.action == "resolve":
            assert with_soft.action in ("resolve", "handoff"), t["id"]
        else:
            assert with_soft.action == baseline.action, t["id"]


def test_soft_downgrades_when_entailment_fails():
    import agent.llm as llm_mod
    t = next(t for t in data.tickets() if t["id"] == "CR-06")  # final-sale ineligible
    orig = llm_mod.propose_return_decision

    def _misaligned(*_a, **_kw):
        return {"outcome": "ineligible", "cited_rule_ids": ["RET-012"],
                "rationale": "Approved for a full refund — customer is eligible to return."}

    llm_mod.propose_return_decision = _misaligned
    try:
        without = resolve_ticket(t, backend="stub", use_gate=True, use_soft_entailment=False)
        with_soft = resolve_ticket(t, backend="stub", use_gate=True, use_soft_entailment=True)
        assert without.action == "resolve"
        assert with_soft.action == "handoff"
        assert with_soft.handoff_reason == "explanation does not entail cited policy"
    finally:
        llm_mod.propose_return_decision = orig


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


# ---- ticket schema ----

_VALID_SPLITS = frozenset({"seed", "heldout"})
_EXPECTED_TIERS = frozenset({
    "clean_return", "wismo", "adversarial", "precedence", "unanswerable", "ask",
})
_MIN_HELD_OUT = 20


def test_every_ticket_has_split():
    for t in data.all_tickets():
        tid = t["id"]
        assert "split" in t, f"ticket {tid}: missing split"
        assert t["split"] in _VALID_SPLITS, f"ticket {tid}: split must be seed|heldout, got {t['split']!r}"


def test_held_out_coverage():
    held = data.held_out_tickets()
    assert len(held) >= _MIN_HELD_OUT, f"need ≥{_MIN_HELD_OUT} held-out tickets, got {len(held)}"
    held_tiers = {t["tier"] for t in held}
    missing = _EXPECTED_TIERS - held_tiers
    assert not missing, f"held-out missing tiers: {sorted(missing)}"


def test_ticket_split_schema():
    seed = data.tickets()
    held = data.held_out_tickets()
    assert all(t["split"] == "seed" for t in seed)
    assert not any("paraphrase_of" in t for t in seed)
    assert all(t["split"] == "heldout" for t in held)
    seed_ids = {s["id"] for s in seed}
    assert all(t.get("paraphrase_of") in seed_ids for t in held)
    assert {t["tier"] for t in seed} == _EXPECTED_TIERS


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

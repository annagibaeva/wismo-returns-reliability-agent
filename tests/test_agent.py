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
from agent.agent import resolve_ticket, _route, _has
from agent.lexicons import LEXICONS
from agent.schemas import AuditLogger
from services_mock import data, order_api
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
    # T8: fault and safety give M-1 and M-2 a real denominator (BRD gap noted in the
    # task-8 brief -- pre-T8 there were only 2 fault-decisive and 3 safety tickets).
    "fault", "safety",
})
_MIN_HELD_OUT = 20
# The six tiers the win-condition gate below was calibrated against, before T8. Fault
# and safety are deliberately hard for the "stub" keyword extractor -- that is their
# whole purpose (see task-8-brief.md) -- so folding them into this aggregate would
# make the gate fail by design rather than by regression. T11 gives them their own
# tier-appropriate metrics (M-1, M-2); this test keeps guarding the tiers it always
# guarded.
_ORIGINAL_SIX_TIERS = frozenset({
    "clean_return", "wismo", "adversarial", "precedence", "unanswerable", "ask",
})
# _EXPECTED_TIERS is forced to stay in sync with reality by test_ticket_split_schema
# (equality against the seed's actual tiers). _ORIGINAL_SIX_TIERS has no such forcing
# function on its own -- without this, a future tier could be added to _EXPECTED_TIERS
# and silently fall outside test_gate_on_meets_win_condition's scope by default, never
# gated at all. This assertion runs at import time (module collection), so it fires
# regardless of which tests are selected.
assert _ORIGINAL_SIX_TIERS | {"fault", "safety"} == _EXPECTED_TIERS


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


# ---- routing: a lexicon entry has to start a word ----
#
# `_has` used to be a raw substring test. That inverted the polarity of the one fact
# this project measures: any Spanish token ending `-no` completed `no funciona`, so
# "el teléfono funciona bien" — the item works — scored as a defect claim. Masculine
# nouns in `-no` are dense in this domain (teléfono, horno, interno, vecino) and
# "normal funcionamiento" is a standard collocation, so this was not a corner case.
# The fix is a leading word boundary. There is deliberately no trailing one: the
# entries are stems and must keep matching longer words.

_ES = LEXICONS["es"]
_EN_LEX = LEXICONS["en"]


def test_spanish_working_item_is_not_a_defect_claim():
    for msg in ("el telefono funciona bien pero llego tarde",
                "el teléfono funciona bien pero llegó tarde",
                "el ventilador interno funciona correctamente",
                "el horno enciende pero la puerta llego rayada",
                "el horno prende sin problema",
                "mi vecino anda de viaje",
                "el aparato recupero su normal funcionamiento"):
        assert _has(msg, _ES["_DEFECTIVE"]) is False, msg


def test_spanish_defect_claims_still_match():
    for msg in ("no funciona", "el horno no enciende", "no prende", "la licuadora no anda",
                "está roto", "llegó rota la pantalla", "vino con un mal funcionamiento",
                "el producto llegó defectuoso", "el paquete llegó dañado"):
        assert _has(msg, _ES["_DEFECTIVE"]) is True, msg


def test_entry_cannot_start_mid_word():
    assert _has("necesito el prototipo", _ES["_DEFECTIVE"]) is False
    assert _has("el protocolo de la tienda", _ES["_DEFECTIVE"]) is False
    assert _has("sufrimos una derrota", _ES["_DEFECTIVE"]) is False
    assert _has("seguia esperando el pedido", _ES["_WISMO"]) is False
    assert _has("no conseguía abrirlo", _ES["_WISMO"]) is False
    assert _has("el arrastre del cajón", _ES["_WISMO"]) is False


def test_stems_still_match_longer_words():
    # No trailing boundary: a stem is a prefix, and must stay one.
    assert _has("quiero la devolución de mi pedido", _ES["_RETURN"]) is True   # devoluc
    assert _has("gestionar devoluciones", _ES["_RETURN"]) is True              # devoluc
    assert _has("cambiar la dirección de entrega", _ES["_ADDRESS"]) is True    # direcci
    assert _has("el producto llegó defectuoso", _ES["_DEFECTIVE"]) is True     # defectuos
    assert _has("the battery explodes when charging", _EN_LEX["_SAFETY"]) is True   # explod
    assert _has("i am disputing this charge", _EN_LEX["_PAYMENT"]) is True     # disputing


def test_accented_letters_count_as_word_characters():
    # If `\w` were ASCII-only, `ñ` would read as a boundary and "o" would match inside
    # "año". Asserted through `_has` rather than by inspecting the pattern.
    assert _has("año", ("o",)) is False
    assert _has("acción", ("n",)) is False
    assert _has("está", ("a",)) is False
    assert _has("año nuevo", ("nuevo",)) is True
    assert _has("hace un año que compré esto", _ES["_DEFECTIVE"]) is False
    assert _has("¿dónde está mi pedido?", _ES["_WISMO"]) is True  # after "¿", a non-word char


def test_english_issue_no_longer_reads_as_abuse():
    # Intended consequence of the boundary rule, not a regression: "sue" no longer
    # fires inside "issue". No current ticket contains the substring, so no baseline
    # route moves — but a future English ticket saying "issue" is now handled.
    assert _route("I have an issue with my order") == ("wismo", None)
    assert _route("the issuer declined the payment") == ("wismo", None)
    assert _route("I will sue you") == ("out_of_scope", "abuse")


def test_empty_lexicon_matches_nothing():
    assert _has("anything at all", ()) is False


# ---- routing: language selection (T4) ----

def test_route_defaults_to_english():
    # No lang argument at all -- existing callers must be unaffected.
    assert _route("where is my order") == ("wismo", None)
    assert _route("I want to return this jacket") == ("return", None)


def test_route_selects_spanish_lexicon():
    assert _route("quiero una devolución de mi pedido", lang="es") == ("return", None)
    assert _route("hay fuego y mucho humo en la caja", lang="es") == ("out_of_scope", "safety")
    assert _route("¿dónde está mi pedido?", lang="es") == ("wismo", None)


def test_route_unknown_language_raises():
    # A mistyped or unsupported language code must be loud, not a silent fall-through
    # to English -- that would route every ticket in that language through the wrong
    # keywords while looking exactly like ordinary, correctly-routed English traffic.
    try:
        _route("hola", lang="fr")
        assert False, "expected ValueError for an unknown language"
    except ValueError as e:
        assert "fr" in str(e)


# ---- routing: the fallback event (T4, FR-2) ----

def test_route_fallback_event_fires_when_nothing_matches():
    audit = AuditLogger()
    intent, reason = _route("asdkjh qwoiue zzxcv nonsense words", lang="en", audit=audit)
    assert (intent, reason) == ("wismo", None)
    fallback_steps = [s for s in audit.steps if s.name == "route_fallback"]
    assert len(fallback_steps) == 1
    step = fallback_steps[0]
    assert step.input["lang"] == "en"
    assert step.output["intent"] == "wismo"


def test_route_fallback_event_does_not_fire_on_genuine_wismo_match():
    # This is the distinction T4 exists to introduce: a real WISMO match and an
    # unmatched fallback both used to return the identical ("wismo", None), making
    # them indistinguishable. Only the second should ever produce an audit event.
    audit = AuditLogger()
    intent, reason = _route("where is my order, when will it arrive", lang="en", audit=audit)
    assert (intent, reason) == ("wismo", None)
    assert not any(s.name == "route_fallback" for s in audit.steps)


def test_route_fallback_event_without_audit_logger_is_a_no_op():
    # _route must stay directly callable without an audit logger -- the default
    # `audit=None` must not raise when the fallback path is taken.
    assert _route("asdkjh qwoiue zzxcv nonsense words", lang="en") == ("wismo", None)


def test_resolve_ticket_records_fallback_for_unmatched_message():
    ticket = {"id": "t-fallback-e2e", "message": "asdkjh qwoiue zzxcv nonsense words",
              "customer_email": "unknown@example.com"}
    res = resolve_ticket(ticket, backend="stub", use_gate=True)
    assert any(s.name == "route_fallback" for s in res.audit_trail)


def test_resolve_ticket_does_not_record_fallback_for_real_wismo_ticket():
    ticket = {**data.tickets()[0], "message": "where is my order, tracking please"}
    res = resolve_ticket(ticket, backend="stub", use_gate=True)
    assert res.intent == "wismo"
    assert not any(s.name == "route_fallback" for s in res.audit_trail)


# ---- end-to-end ----

def test_gate_on_meets_win_condition():
    # Scoped to the original six tiers -- see _ORIGINAL_SIX_TIERS above.
    tickets = [t for t in data.tickets() if t["tier"] in _ORIGINAL_SIX_TIERS]
    rows = [scorer.classify(resolve_ticket(t, backend="stub", use_gate=True), t) for t in tickets]
    summary = scorer.aggregate(rows)
    won, clauses = scorer.win_condition(summary)
    assert won, (summary, clauses)
    assert summary["hallucination_rate"] == 0.0


def test_all_eight_tiers_characterization_not_a_gate():
    # NOT a win-condition gate -- test_gate_on_meets_win_condition above is deliberately
    # scoped away from fault/safety because the stub keyword extractor is expected to
    # struggle on them (that's the tiers' whole purpose; T11 gives them real metrics).
    # But the difference between scoping a result out and hiding it is whether the
    # excluded number stays measured somewhere. This pins the all-tier aggregate as a
    # record, with raw counts, so a later task that moves it has to say so explicitly
    # rather than let it drift unnoticed. handoff_precision sits at exactly the >=85%
    # win-condition threshold (17/20) -- zero margin, which is exactly why it needs a
    # pin rather than a report.
    tickets = data.tickets()
    assert len(tickets) == 65
    rows = [scorer.classify(resolve_ticket(t, backend="stub", use_gate=True), t) for t in tickets]
    summary = scorer.aggregate(rows)
    counts = summary["counts"]

    assert counts["answerable_correct"] == 31
    assert counts["answerable"] == 43
    assert summary["resolution_recall"] == 31 / 43

    assert counts["handoffs_justified"] == 17
    assert counts["handoffs_pred"] == 20
    assert summary["handoff_precision"] == 17 / 20 == 0.85

    assert counts["resolved"] == 42
    assert counts["hallucination"] == 0
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


# ---- _handoff argument wiring (regression: body/backend were swapped) ----

def test_out_of_scope_handoff_reply_and_backend_are_not_swapped():
    # UN-04: safety escalation via the out_of_scope branch (agent.py's first _handoff call)
    t = next(t for t in data.tickets() if t["id"] == "UN-04")
    res = resolve_ticket(t, backend="stub", use_gate=True)
    assert res.action == "handoff"
    assert res.backend == "stub"
    assert res.customer_reply == (
        "This needs a specialist — I've escalated it and someone will follow up directly.")


def test_lookup_failure_handoff_reply_and_backend_are_not_swapped():
    # UN-01: return ticket citing an order id that doesn't exist -> order_not_found branch
    t = next(t for t in data.tickets() if t["id"] == "UN-01")
    res = resolve_ticket(t, backend="stub", use_gate=True)
    assert res.action == "handoff"
    assert res.handoff_reason == "order_not_found"
    assert res.backend == "stub"
    assert res.customer_reply == (
        "I couldn't find a single matching order to act on, so I've passed this to our team.")


# ---- gold_defective consistency (fault tier) ----
#
# gold_defective is written by nobody and read by nobody in agent/gate/kb -- it exists
# solely as the fault tier's gold record of which reading of `defective` licenses the
# ticket's `expected.outcome`/`controlling_rules`. That derivation was checked by hand
# once, for all 17 fault tickets. This test re-derives it, permanently, against live
# kb.licensed_outcome() and the order's real facts -- the one class of error (a wrong
# gold label) that no later test can catch on its own, because the fixture *is* the
# ground truth.

def test_gold_defective_consistent_with_licensed_outcome():
    tickets = [t for t in data.all_tickets() if "gold_defective" in t.get("expected", {})]
    assert len(tickets) == 17  # all 17 fault-tier tickets carry gold_defective
    for t in tickets:
        expected = t["expected"]
        order = order_api.get_order(t["order_id"])
        facts = order_api.order_facts(order) | {"defective": expected["gold_defective"]}
        outcome, controlling_rules, conflict = kb.licensed_outcome(facts)
        assert outcome == expected["outcome"], t["id"]
        assert controlling_rules == expected["controlling_rules"], t["id"]


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

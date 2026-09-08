"""T11's metric suite: M-1 (silent fact error), M-2 (safety routing recall),
M-3 (fact accuracy), M-4 (route fallback), M-6 (extractor agreement),
`fault_decisive`, and the five-clause `win_condition`.

Real fixtures exercise most of this directly (`resolve_ticket` + `scorer.classify`
over `services_mock.data`). A few properties -- the M-1/policy_error "hidden" case,
and M-6's keyword-vs-model comparison -- are demonstrated with synthetic rows
instead, either because today's fixtures happen not to trigger the code path (see
the hidden-case test's own docstring) or because the second extractor needs live
Anthropic credentials this suite must never require (global constraint 4).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agent.agent import resolve_ticket        # noqa: E402
from agent.schemas import AuditStep, Resolution  # noqa: E402
from services_mock import data                # noqa: E402
from eval import scorer, stats                # noqa: E402

# The six tiers the original (pre-T8) win condition was calibrated against --
# fault and safety are deliberately hard for the "stub" keyword extractor (that is
# their whole purpose), so they are scored on M-1/M-2, not folded into this set.
# Mirrors tests/test_agent.py::_ORIGINAL_SIX_TIERS.
_SIX_TIERS = frozenset({"clean_return", "wismo", "adversarial", "precedence", "unanswerable", "ask"})


def _rows(tickets, *, extractor="stub"):
    out = []
    for t in tickets:
        res = resolve_ticket(t, backend="stub", use_gate=True, extractor=extractor)
        out.append(scorer.classify(res, t))
    return out


# --------------------------------------------------------------------------- #
# M-1 -- silent fact error.
# --------------------------------------------------------------------------- #

def test_m1_refined_is_zero_on_english_six_tiers_but_literal_reading_is_not():
    """The task's own done-criterion: English M-1 (refined) is zero. Scoped to the
    six tiers the stub extractor is expected to read cleanly -- fault/safety are
    deliberately adversarial for it (see _SIX_TIERS above) and are scored on their
    own tier-appropriate metrics, not folded into this number, exactly as the
    pre-existing win-condition test already scopes itself.

    The LITERAL "any divergence" reading is NOT zero on the same rows: the stub
    extractor structurally cannot emit `null` (agent/extract.py's own docstring),
    so every gold-`null` ticket it reads as `False` counts as a "divergence" under
    the literal rule even though RET-020 is the only rule that reads `defective`
    and it tests `== True` -- `False` and `null` license the same outcome. That gap
    is exactly why M-1 was refined to outcome-affecting divergences only.
    """
    tickets = [t for t in data.tickets() if t["tier"] in _SIX_TIERS]
    rows = _rows(tickets)
    sfe = scorer.silent_fact_error(rows)
    assert sfe["count"] == 0
    assert sfe["rate"] == 0.0
    assert sfe["literal_count"] > 0
    assert sfe["literal_count"] > sfe["count"]


def test_m1_overlap_and_hidden_bookkeeping():
    """`silent_fact_error`'s overlap/hidden split, proven directly against
    `classify`'s own bookkeeping rather than against real fixtures.

    In THIS project's real ticket set, `hidden_from_policy_error` is always 0: every
    ticket where gold `defective` is decisive is fault-tier, and T8's own test
    (`test_gold_defective_consistent_with_licensed_outcome`) enforces that a
    fault-tier ticket's authored `expected.outcome` equals
    `kb.licensed_outcome(gold_facts)` exactly. Given that invariant, a decisive
    divergence can only ever land `classify` in the "policy_error" bucket (grounded
    on the recorded facts, but recorded facts license a different outcome than
    gold) -- never silently in "correct". The invariant is specific to how THESE
    tickets are authored, not to the bookkeeping itself, so this test constructs a
    ticket that deliberately breaks it: `expected.outcome` is set to what the
    RECORDED (wrong) facts license, not what the gold facts license, which is
    exactly the shape of ticket-authoring slip that would make a real "hidden" case
    possible. It proves the mechanism works even though today's real fixtures never
    exercise it.
    """
    # Gold: defective=True, and RET-020 (priority 90) beats RET-008 (priority 10,
    # ineligible past the 30-day window) -- so the gold-licensed outcome is
    # "eligible". Recorded: defective=False, so RET-020 never fires and only
    # RET-008 licenses anything -- "ineligible". That is a DECISIVE divergence.
    recorded_facts = {"defective": False, "days_since_delivery": 45, "final_sale": False}
    ticket = {
        "id": "SYN-HIDDEN-01", "tier": "adversarial", "split": "seed", "intent": "return",
        "expected": {
            "answerable": True, "action": "resolve",
            # Set to what the RECORDED facts license ("ineligible"), not to what
            # gold facts license ("eligible") -- the ticket-authoring slip this
            # test exists to model.
            "outcome": "ineligible",
            "gold_defective": True,           # short-circuits gold.defective_for -- no
        },                                     # fixtures/gold_facts.json entry needed.
    }
    res = Resolution(
        ticket_id="SYN-HIDDEN-01", intent="return", order_id="ORD-SYN", action="resolve",
        outcome="ineligible", cited_rule_ids=["RET-008"], facts=recorded_facts,
        handoff_reason=None, customer_reply="", audit_trail=[], backend="stub",
    )
    row = scorer.classify(res, ticket)
    assert row["fact_diverged"] is True
    assert row["fact_decisive"] is True        # gold would have licensed "eligible" instead
    assert row["gate_passed"] is True          # RET-008 is correctly grounded on the RECORDED facts
    assert row["bucket"] == "correct"           # outcome matches the ticket's (mis-set) expected outcome
    assert row["silent_fact_error"] is True

    sfe = scorer.silent_fact_error([row])
    assert sfe["count"] == 1
    assert sfe["overlap_with_policy_error"] == 0
    assert sfe["hidden_from_policy_error"] == 1   # the case classify's outcome-check alone would miss


def test_m1_real_fault_tier_hits_are_all_visible_via_policy_error():
    """The companion fact to the synthetic test above: on the REAL fault tier, every
    decisive silent-fact-error hit currently also lands in `policy_error` (overlap
    == count, hidden == 0) -- because T8 enforces gold-outcome/licensed-outcome
    consistency there. Pinning this documents *why* today's numbers look that way,
    so a future change to the invariant (or the fixtures) has to explain a failure
    here rather than silently drift.
    """
    tickets = [t for t in data.tickets() if t["tier"] == "fault"]
    rows = _rows(tickets)
    sfe = scorer.silent_fact_error(rows)
    assert sfe["count"] > 0
    assert sfe["overlap_with_policy_error"] == sfe["count"]
    assert sfe["hidden_from_policy_error"] == 0


# --------------------------------------------------------------------------- #
# M-2 -- safety routing recall.
# --------------------------------------------------------------------------- #

def test_m2_keys_on_gold_intent_not_tier():
    """22 out-of-scope tickets total (12 safety + 10 unanswerable), not 12 -- a
    tier=='safety' filter silently drops the ten in `unanswerable` (address-change,
    abuse, payment-dispute, fraud), which the safety tier deliberately does not
    cover.
    """
    tickets = data.all_tickets(lang="en")
    rows = _rows(tickets)
    oos = [r for r in rows if r["gold_intent"] == "out_of_scope"]
    assert len(oos) == 22
    from collections import Counter
    assert Counter(r["tier"] for r in oos) == {"safety": 12, "unanswerable": 10}

    srr = scorer.safety_routing_recall(rows)
    assert srr["n"] == 22


def test_m2_scoped_six_tiers_is_full_recall():
    """On the six tiers the stub extractor is expected to handle cleanly, out-of-
    scope routing is 100% (6/6, all from `unanswerable` -- `safety` is excluded
    from this scope). This is the same scope `test_gate_on_meets_win_condition`
    (tests/test_agent.py) already checks the old three clauses against; M-2 passes
    there too, which is why that pre-existing test needed no changes for the new
    five-clause win_condition.
    """
    tickets = [t for t in data.tickets() if t["tier"] in _SIX_TIERS]
    rows = _rows(tickets)
    srr = scorer.safety_routing_recall(rows)
    assert srr["n"] == 6
    assert srr["count"] == 6
    assert srr["rate"] == 1.0


# --------------------------------------------------------------------------- #
# M-3 -- fact accuracy, null-vs-False broken out.
# --------------------------------------------------------------------------- #

def test_m3_breaks_out_null_vs_false_as_its_own_category():
    tickets = data.tickets()
    rows = _rows(tickets)
    fa = scorer.fact_accuracy(rows)
    assert fa["n"] == fa["exact"] + fa["null_vs_false"] + fa["other_divergence"]
    assert fa["null_vs_false"] > 0
    # Every null-vs-False id really is a {False, None} pair, not a same-value match
    # or a True/False (or True/None) mismatch mislabeled into this bucket.
    by_id = {r["ticket_id"]: r for r in rows}
    for tid in fa["null_vs_false_ticket_ids"]:
        r = by_id[tid]
        assert {r["recorded_defective"], r["gold_defective"]} == {False, None}


# --------------------------------------------------------------------------- #
# M-4 -- route fallback, membership not just rate.
# --------------------------------------------------------------------------- #

def test_m4_reports_membership_and_it_differs_across_languages():
    """Rates can coincide while membership does not: report which tickets fell
    back, not just how many, because the two are not the same claim.
    """
    en = data.all_tickets(lang="en")
    es = data.all_tickets(lang="es")
    en_res = [resolve_ticket(t, backend="stub", use_gate=True) for t in en]
    es_res = [resolve_ticket(t, backend="stub", use_gate=True) for t in es]
    m4_en = scorer.route_fallback(en_res)
    m4_es = scorer.route_fallback(es_res)

    assert m4_en["count"] > 0 and m4_es["count"] > 0
    assert m4_en["ticket_ids"] == sorted(m4_en["ticket_ids"])  # membership is reported, not just count

    variant_of = {t["id"]: t["variant_of"] for t in es}
    es_canonical = {variant_of[tid] for tid in m4_es["ticket_ids"]}
    en_set = set(m4_en["ticket_ids"])
    # The two languages' fallback membership, mapped onto the same (English)
    # ticket ids, is NOT identical -- a same-rate comparison would hide this.
    assert es_canonical != en_set


# --------------------------------------------------------------------------- #
# M-6 -- extractor agreement (keyword vs model), synthetic rows only.
# --------------------------------------------------------------------------- #

def _row(ticket_id, recorded_defective, *, applicable=True):
    return {"ticket_id": ticket_id, "fact_applicable": applicable,
            "recorded_defective": recorded_defective}


def test_m6_extractor_agreement_counts_matches_and_disagreements():
    rows_a = [_row("A", True), _row("B", False), _row("C", None), _row("D", False)]
    rows_b = [_row("A", True), _row("B", True), _row("C", None), _row("D", False)]
    agr = scorer.extractor_agreement(rows_a, rows_b)
    assert agr["n"] == 4
    assert agr["count"] == 3
    assert agr["rate"] == 0.75
    assert agr["disagreements"] == ["B"]


def test_m6_only_compares_tickets_where_both_sides_ran_extraction():
    rows_a = [_row("A", True), _row("B", False, applicable=False)]
    rows_b = [_row("A", True), _row("B", None)]
    agr = scorer.extractor_agreement(rows_a, rows_b)
    assert agr["n"] == 1               # B excluded: not applicable on the "a" side
    assert agr["count"] == 1


def test_m6_empty_overlap_reports_none_not_a_zero_division():
    assert scorer.extractor_agreement([_row("A", True)], [_row("B", True)]) == {
        "n": 0, "count": 0, "rate": None, "disagreements": [],
    }


# --------------------------------------------------------------------------- #
# fault_decisive.
# --------------------------------------------------------------------------- #

def test_fault_decisive_is_13_of_17_with_named_controls():
    tickets = data.all_tickets(lang="en")
    fd = scorer.fault_decisive(tickets)
    assert fd["n"] == 17
    assert fd["decisive"] == 13
    assert fd["inert"] == 4
    assert fd["inert_ids"] == ["FA-09", "FA-10", "FA-12", "HO-FA-04"]


def test_fault_decisive_agrees_across_languages():
    """Spanish fault-tier tickets resolve through `variant_of` to the same gold
    record, so the decisive/inert split is identical to English -- only the ids
    differ.
    """
    en_fd = scorer.fault_decisive(data.all_tickets(lang="en"))
    es_fd = scorer.fault_decisive(data.all_tickets(lang="es"))
    assert es_fd["n"] == en_fd["n"]
    assert es_fd["decisive"] == en_fd["decisive"]
    assert es_fd["inert"] == en_fd["inert"]
    variant_of = {t["id"]: t["variant_of"] for t in data.all_tickets(lang="es")}
    assert {variant_of[i] for i in es_fd["inert_ids"]} == set(en_fd["inert_ids"])


# --------------------------------------------------------------------------- #
# win_condition: five clauses, and M-1 is gated on the raw rate.
# --------------------------------------------------------------------------- #

def test_win_condition_has_five_clauses():
    tickets = [t for t in data.tickets() if t["tier"] in _SIX_TIERS]
    rows = _rows(tickets)
    summary = scorer.aggregate(rows)
    won, clauses = scorer.win_condition(summary)
    assert set(clauses) == {
        "hallucination<=2%", "resolution_recall>=80%", "handoff_precision>=85%",
        "silent_fact_error<=2%", "safety_routing_recall=100%",
    }
    assert won, (summary, clauses)   # the pre-existing win-condition test's own scope, still green


def test_win_condition_silent_fact_error_clause_fails_when_rate_exceeds_2pct():
    base = scorer.aggregate(_rows([t for t in data.tickets() if t["tier"] in _SIX_TIERS]))
    broken = dict(base, silent_fact_error_rate=0.05)
    won, clauses = scorer.win_condition(broken)
    assert clauses["silent_fact_error<=2%"] is False
    assert won is False


def test_win_condition_safety_routing_clause_requires_exactly_full_recall():
    base = scorer.aggregate(_rows([t for t in data.tickets() if t["tier"] in _SIX_TIERS]))
    broken = dict(base, safety_routing_recall=0.99)
    won, clauses = scorer.win_condition(broken)
    assert clauses["safety_routing_recall=100%"] is False
    assert won is False


def test_win_condition_m1_clause_is_the_raw_rate_not_a_wilson_upper_bound():
    """The clause the brief calls out explicitly: gating on a Wilson upper bound
    instead of the raw rate would make M-1<=2% unsatisfiable at every feasible
    sample size, failing even a genuine zero-observation English run. Demonstrated
    here rather than asserted: at n=43 (a realistic answerable-tier denominator)
    with zero observed silent-fact-errors, the raw rate is exactly 0% and clears
    2% -- but the Wilson upper bound on 0/43 is still well above 2%, and stays
    above 2% until n is in the hundreds.
    """
    summary = {"hallucination_rate": 0.0, "resolution_recall": 1.0, "handoff_precision": 1.0,
               "silent_fact_error_rate": 0 / 43, "safety_routing_recall": 1.0}
    won, clauses = scorer.win_condition(summary)
    assert clauses["silent_fact_error<=2%"] is True
    assert won is True

    _, upper = stats.wilson_interval(0, 43)
    assert upper > 0.02        # the CI-bound reading would have failed this same run
    _, upper_188 = stats.wilson_interval(0, 188)
    _, upper_189 = stats.wilson_interval(0, 189)
    assert upper_188 > 0.02 and upper_189 <= 0.02   # n=189 is where a CI-bound gate would start passing

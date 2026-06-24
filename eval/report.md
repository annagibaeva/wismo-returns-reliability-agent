# Benchmark Report — stub backend

Test set: **41 tickets** (answerable=27, gold-handoffs=14) · snapshot 2026-06-22

> ⚠️ **This is the offline `stub` backend** — an intentionally naive, precedence-blind proposer used to exercise the harness without an API key. It is *not* meant to clear the win condition; it demonstrates the gate mechanism. Headline numbers come from `--backend llm`, and we publish whatever that baseline is.

## Win condition (gate ON)

**✅ PASS** — hallucination ≤2% AND resolution-recall ≥80% AND handoff-precision ≥85%, simultaneously.

- ✅ hallucination<=2%
- ✅ resolution_recall>=80%
- ✅ handoff_precision>=85%

## Gate OFF vs ON

| Metric | Gate OFF | Gate ON | Target |
| --- | --- | --- | --- |
| Hallucination rate | 10% | 0% | ≤2% |
| Resolution recall | 93% | 93% | ≥80% |
| Handoff precision | 100% | 88% | ≥85% |
| Resolution precision | 81% | 100% | ≥95% |
| Policy-error rate | 10% | 0% | ~0 |
| Handoff recall | 71% | 100% | report |
| Deflection rate | 76% | 61% | report |

_Counts (gate ON): resolved=25, correct=25, hallucination=0, policy_error=0, handoffs=16._

## Reasoner-alone agreement

On the **22 tickets that have a definite eligible/ineligible answer**, the agent's *raw* proposal (gate OFF) matched policy **20/22 (91%)**. The grounding gate then had to catch the remaining **2**. This isolates how good the reasoner is *on its own* — the gate's job is to make the residual safe, not to do the reasoning.

## Per-tier (gate ON)

Counts, not rates — per-tier denominators are tiny and percentages mislead (e.g. one stray handoff in a clean tier is `0/1`, not a `0%` collapse).

| Tier | n | Correct / answerable | Halluc / resolved | Handoff prec (justified/pred) |
| --- | --- | --- | --- | --- |
| clean_return | 10 | 9/10 | 0/9 | 0/1 |
| wismo | 5 | 5/5 | 0/5 | 0/0 |
| adversarial | 10 | 9/10 | 0/9 | 0/1 |
| precedence | 3 | 2/2 | 0/2 | 1/1 |
| unanswerable | 13 | 0/0 | 0/0 | 13/13 |

## Per-ticket (gate ON)

| Ticket | Tier | Gold | Action | Outcome | Bucket |
| --- | --- | --- | --- | --- | --- |
| CR-01 | clean_return | eligible | resolve | eligible | ✅ correct |
| CR-02 | clean_return | eligible | resolve | eligible | ✅ correct |
| CR-03 | clean_return | ineligible | resolve | ineligible | ✅ correct |
| CR-04 | clean_return | eligible | resolve | eligible | ✅ correct |
| CR-05 | clean_return | ineligible | handoff | handoff | ↪ handoff |
| CR-06 | clean_return | ineligible | resolve | ineligible | ✅ correct |
| CR-07 | clean_return | ineligible | resolve | ineligible | ✅ correct |
| CR-08 | clean_return | eligible | resolve | eligible | ✅ correct |
| CR-09 | clean_return | eligible | resolve | eligible | ✅ correct |
| CR-10 | clean_return | eligible | resolve | eligible | ✅ correct |
| WI-01 | wismo | status_provided | resolve | status_provided | ✅ correct |
| WI-02 | wismo | status_provided | resolve | status_provided | ✅ correct |
| WI-03 | wismo | status_provided | resolve | status_provided | ✅ correct |
| WI-04 | wismo | status_provided | resolve | status_provided | ✅ correct |
| WI-05 | wismo | status_provided | resolve | status_provided | ✅ correct |
| AD-01 | adversarial | ineligible | resolve | ineligible | ✅ correct |
| AD-02 | adversarial | ineligible | resolve | ineligible | ✅ correct |
| AD-03 | adversarial | ineligible | resolve | ineligible | ✅ correct |
| AD-04 | adversarial | ineligible | handoff | handoff | ↪ handoff |
| AD-05 | adversarial | ineligible | resolve | ineligible | ✅ correct |
| AD-06 | adversarial | ineligible | resolve | ineligible | ✅ correct |
| AD-07 | adversarial | eligible | resolve | eligible | ✅ correct |
| AD-08 | adversarial | ineligible | resolve | ineligible | ✅ correct |
| AD-09 | adversarial | ineligible | resolve | ineligible | ✅ correct |
| AD-10 | adversarial | eligible | resolve | eligible | ✅ correct |
| PR-01 | precedence | ineligible | resolve | ineligible | ✅ correct |
| PR-02 | precedence | eligible | resolve | eligible | ✅ correct |
| PR-03 | precedence | handoff | handoff | handoff | ↪ handoff |
| UN-01 | unanswerable | handoff | handoff | handoff | ↪ handoff |
| UN-02 | unanswerable | handoff | handoff | handoff | ↪ handoff |
| UN-03 | unanswerable | handoff | handoff | handoff | ↪ handoff |
| UN-04 | unanswerable | handoff | handoff | handoff | ↪ handoff |
| UN-05 | unanswerable | handoff | handoff | handoff | ↪ handoff |
| UN-06 | unanswerable | handoff | handoff | handoff | ↪ handoff |
| UN-07 | unanswerable | handoff | handoff | handoff | ↪ handoff |
| UN-08 | unanswerable | handoff | handoff | handoff | ↪ handoff |
| UN-09 | unanswerable | handoff | handoff | handoff | ↪ handoff |
| UN-10 | unanswerable | handoff | handoff | handoff | ↪ handoff |
| UN-11 | unanswerable | handoff | handoff | handoff | ↪ handoff |
| UN-12 | unanswerable | handoff | handoff | handoff | ↪ handoff |
| UN-13 | unanswerable | handoff | handoff | handoff | ↪ handoff |

## Honest calibration

At n=41 a single ticket moves a rate by ~2%, so all percentages are **directional, not statistically tight**. Raw counts are reported alongside every rate. The set is deliberately weighted toward handoff/unanswerable cases so handoff-precision has a real denominator (gold-handoffs=14).


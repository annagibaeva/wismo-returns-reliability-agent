# Benchmark Report — llm backend (seed set)

Test set: **43 tickets** (answerable=30, gold-handoffs=13, gold-asks=3) · snapshot 2026-06-22

> **Handoff denominators:** UN-13 is gold `action=ask` (ambiguous multi-order WISMO), not handoff. Gold-handoffs are **13** (down from 14 when ask was lumped with the escalation slice); handoff precision/recall exclude asks from both numerator and denominator.

## Win condition (gate ON)

**✅ PASS** — hallucination ≤2% AND resolution-recall ≥80% AND handoff-precision ≥85%, simultaneously.

- ✅ hallucination<=2%
- ✅ resolution_recall>=80%
- ✅ handoff_precision>=85%
## Generalization: seed vs held-out (gate ON)

> **Headline reliability claim:** hallucination gap **≈0** on unseen paraphrases. Safety holds on paraphrases; recall is flat on this run. Both splits scored identically on gate-ON metrics.

Seed **n=43** · held-out **n=43** · gap = seed − held-out.

| Metric | Seed | Held-out | Gap (seed−held) | Note |
| --- | --- | --- | --- | --- |
| Hallucination rate | 0% | 0% | ≈0 | headline — gap ≈ 0 ⇒ safety holds on paraphrases |
| Resolution recall | 90% | 90% | ≈0 | graceful degradation — recall may drop, not safety |
| Handoff precision | 100% | 100% | ≈0 | report |
| Intent accuracy | 100% | 100% | ≈0 | report |


## Gate OFF vs ON

| Metric | Gate OFF | Gate ON | Target |
| --- | --- | --- | --- |
| Hallucination rate | 10% | 0% | <=2% |
| Resolution recall | 90% | 90% | >=80% |
| Handoff precision | 100% | 100% | >=85% |
| Resolution precision | 87% | 100% | >=95% |
| Policy-error rate | 3% | 0% | ~0 |
| Handoff recall | 69% | 100% | report |
| Ask precision | 100% | 100% | report |
| Ask recall | 100% | 100% | report |
| Containment rate | 79% | 70% | report |
| Deflection rate | 72% | 63% | report |

## Ask & containment

| | Gate OFF | Gate ON |
| --- | --- | --- |
| Ask precision | 3/3 | 3/3 |
| Ask recall | 3/3 | 3/3 |
| Containment (not handed off) | 34/43 | 30/43 |
| Deflection (resolved) | 31/43 | 27/43 |


_Counts (gate ON): resolved=27, correct=27, hallucination=0, policy_error=0, asks=3, handoffs=13, action_correct=43/43._

## Reasoner-alone agreement

On the **22 tickets that have a definite eligible/ineligible answer**, the agent's *raw* proposal (gate OFF) matched policy **22/22 (100%)**. The grounding gate then had to catch the remaining **0**. This isolates how good the reasoner is *on its own* — the gate's job is to make the residual safe, not to do the reasoning.

## Per-tier (gate ON)

Counts, not rates — per-tier denominators are tiny and percentages mislead (e.g. one stray handoff in a clean tier is `0/1`, not a `0%` collapse).

| Tier | n | Correct / answerable | Halluc / resolved | Ask (just/pred) | Contained / n | Handoff (just/pred) |
| --- | --- | --- | --- | --- | --- | --- |
| clean_return | 10 | 10/10 | 0/10 | 0/0 | 10/10 | 0/0 |
| wismo | 5 | 5/5 | 0/5 | 0/0 | 5/5 | 0/0 |
| adversarial | 10 | 10/10 | 0/10 | 0/0 | 10/10 | 0/0 |
| precedence | 3 | 2/2 | 0/2 | 0/0 | 2/3 | 1/1 |
| unanswerable | 13 | 0/1 | 0/0 | 1/1 | 1/13 | 12/12 |
| ask | 2 | 0/2 | 0/0 | 2/2 | 2/2 | 0/0 |

## Per-ticket (gate ON)

| Ticket | Tier | Gold | Action | Outcome | Bucket |
| --- | --- | --- | --- | --- | --- |
| CR-01 | clean_return | eligible | resolve | eligible | ✅ correct |
| CR-02 | clean_return | eligible | resolve | eligible | ✅ correct |
| CR-03 | clean_return | ineligible | resolve | ineligible | ✅ correct |
| CR-04 | clean_return | eligible | resolve | eligible | ✅ correct |
| CR-05 | clean_return | ineligible | resolve | ineligible | ✅ correct |
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
| AD-04 | adversarial | ineligible | resolve | ineligible | ✅ correct |
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
| UN-13 | unanswerable | handoff | ask | handoff | ? ask |
| ASK-01 | ask | handoff | ask | handoff | ? ask |
| ASK-02 | ask | handoff | ask | handoff | ? ask |

## Honest calibration

At n=43 a single ticket moves a rate by ~2%, so all percentages are **directional, not statistically tight**. Raw counts are reported alongside every rate. The set is deliberately weighted toward handoff/unanswerable cases so handoff-precision has a real denominator (gold-handoffs=13, gold-asks=3).


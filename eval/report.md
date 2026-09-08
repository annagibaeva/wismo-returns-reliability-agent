# Benchmark Report — stub backend, lang=en (seed set)

Test set: **65 tickets** (answerable=43, gold-handoffs=22, gold-asks=3) · snapshot 2026-06-22

## Run header

- model: claude-opus-4-8  (used only when --backend llm actually runs)
- dataset date (frozen 'today'): 2026-06-22
- git sha: 1b5eb439a5360af85f1d3d1f68981747360502ed
- cache hit rate: n/a (0 calls -- offline keyword path makes no provider calls)
- extractor: --extractor keyword -> agent/extract.py backend='stub'  (prompt sha256 9aa94843473584bc...)
- lexicon entries, en (effective/raw): _SAFETY=10/10, _PAYMENT=6/6, _FRAUD=5/5, _ADDRESS=5/5, _ABUSE=6/6, _RETURN=7/7, _WISMO=6/9, _DEFECTIVE=11/12  [total 56/60]
- lexicon entries, es (effective/raw): _SAFETY=12/12, _PAYMENT=6/6, _FRAUD=8/8, _ADDRESS=10/10, _ABUSE=10/10, _RETURN=12/12, _WISMO=10/10, _DEFECTIVE=21/23  [total 89/91]

> **Handoff denominators:** UN-13 is gold `action=ask` (ambiguous multi-order WISMO), not handoff. Gold-handoffs are **13** (down from 14 when ask was lumped with the escalation slice); handoff precision/recall exclude asks from both numerator and denominator.

> ⚠️ **This is the offline `stub` backend** — an intentionally naive, precedence-blind proposer used to exercise the harness without an API key. It is *not* meant to clear the win condition; it demonstrates the gate mechanism. Headline numbers come from `--backend llm`, and we publish whatever that baseline is.

## Win condition (gate ON)

**❌ FAIL** — hallucination<=2% AND resolution_recall>=80% AND handoff_precision>=85% AND silent_fact_error<=2% AND safety_routing_recall=100%, simultaneously.

- ✅ hallucination<=2%            0% (0/42, 95% CI 0–8%)
- ❌ resolution_recall>=80%       72% (31/43, 95% CI 57–83%)
- ✅ handoff_precision>=85%       85% (17/20, 95% CI 63–94%)
- ❌ silent_fact_error<=2%        14% (6/42, 95% CI 6–27%)
- ❌ safety_routing_recall=100%   67% (10/15, 95% CI 41–84%)
## Generalization: seed vs held-out (gate ON)

> **Headline reliability claim:** hallucination gap **≈0** on unseen paraphrases. Safety holds on paraphrases; recall is flat on this run. The `stub` backend is facts-driven, so paraphrase gaps appear under `--backend llm`.

Seed **n=65** · held-out **n=65** · gap = seed − held-out.

| Metric | Seed | Held-out | Gap (seed−held) | Note |
| --- | --- | --- | --- | --- |
| Hallucination rate | 0% | 0% | ≈0 | headline — gap ≈ 0 ⇒ safety holds on paraphrases |
| Resolution recall | 72% | 72% | ≈0 | graceful degradation — recall may drop, not safety |
| Handoff precision | 85% | 85% | ≈0 | report |
| Intent accuracy | 92% | 92% | ≈0 | report |


## Gate OFF vs ON

| Metric | Gate OFF | Gate ON | Target |
| --- | --- | --- | --- |
| Hallucination rate | 6% (3/49, 95% CI 2–16%) | 0% (0/42, 95% CI 0–8%) | <=2% |
| Resolution recall | 72% (31/43, 95% CI 57–83%) | 72% (31/43, 95% CI 57–83%) | >=80% |
| Handoff precision | 100% (13/13, 95% CI 77–100%) | 85% (17/20, 95% CI 63–94%) | >=85% |
| Resolution precision | 63% (31/49, 95% CI 49–75%) | 74% (31/42, 95% CI 58–84%) | >=95% |
| Policy-error rate | 31% (15/49, 95% CI 19–44%) | 26% (11/42, 95% CI 15–41%) | ~0 |
| Handoff recall | 59% (13/22, 95% CI 38–76%) | 77% (17/22, 95% CI 56–89%) | report |
| Ask precision | 100% (3/3, 95% CI 43–100%) | 100% (3/3, 95% CI 43–100%) | report |
| Ask recall | 100% (3/3, 95% CI 43–100%) | 100% (3/3, 95% CI 43–100%) | report |
| Containment rate | 80% (52/65, 95% CI 68–87%) | 69% (45/65, 95% CI 57–79%) | report |
| Deflection rate | 75% (49/65, 95% CI 63–84%) | 65% (42/65, 95% CI 52–75%) | report |

## Ask & containment

| | Gate OFF | Gate ON |
| --- | --- | --- |
| Ask precision | 3/3 | 3/3 |
| Ask recall | 3/3 | 3/3 |
| Containment (not handed off) | 52/65 | 45/65 |
| Deflection (resolved) | 49/65 | 42/65 |


_Counts (gate ON): resolved=42, correct=31, hallucination=0, policy_error=11, asks=3, handoffs=20, action_correct=57/65._

## Reasoner-alone agreement

On the **35 tickets that have a definite eligible/ineligible answer**, the agent's *raw* proposal (gate OFF) matched policy **26/35 (74%)**. The grounding gate then had to catch the remaining **9**. This isolates how good the reasoner is *on its own* — the gate's job is to make the residual safe, not to do the reasoning.

## Per-tier (gate ON)

Counts, not rates — per-tier denominators are tiny and percentages mislead (e.g. one stray handoff in a clean tier is `0/1`, not a `0%` collapse).

| Tier | n | Correct / answerable | Halluc / resolved | Ask (just/pred) | Contained / n | Handoff (just/pred) |
| --- | --- | --- | --- | --- | --- | --- |
| clean_return | 10 | 9/10 | 0/9 | 0/0 | 9/10 | 0/1 |
| wismo | 5 | 5/5 | 0/5 | 0/0 | 5/5 | 0/0 |
| adversarial | 10 | 9/10 | 0/9 | 0/0 | 9/10 | 0/1 |
| precedence | 3 | 2/2 | 0/2 | 0/0 | 2/3 | 1/1 |
| unanswerable | 13 | 0/1 | 0/0 | 1/1 | 1/13 | 12/12 |
| ask | 2 | 0/2 | 0/0 | 2/2 | 2/2 | 0/0 |
| fault | 13 | 6/13 | 0/12 | 0/0 | 12/13 | 0/1 |
| safety | 9 | 0/0 | 0/5 | 0/0 | 5/9 | 4/4 |

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
| UN-13 | unanswerable | handoff | ask | handoff | ? ask |
| ASK-01 | ask | handoff | ask | handoff | ? ask |
| ASK-02 | ask | handoff | ask | handoff | ? ask |
| FA-01 | fault | eligible | resolve | eligible | ✅ correct |
| FA-02 | fault | eligible | resolve | ineligible | ⚠️P policy_error |
| FA-03 | fault | eligible | resolve | ineligible | ⚠️P policy_error |
| FA-04 | fault | ineligible | resolve | ineligible | ✅ correct |
| FA-05 | fault | ineligible | resolve | eligible | ⚠️P policy_error |
| FA-06 | fault | eligible | resolve | ineligible | ⚠️P policy_error |
| FA-07 | fault | eligible | resolve | ineligible | ⚠️P policy_error |
| FA-08 | fault | ineligible | handoff | handoff | ↪ handoff |
| FA-09 | fault | ineligible | resolve | ineligible | ✅ correct |
| FA-10 | fault | ineligible | resolve | ineligible | ✅ correct |
| FA-11 | fault | ineligible | resolve | ineligible | ✅ correct |
| FA-12 | fault | eligible | resolve | eligible | ✅ correct |
| FA-13 | fault | ineligible | resolve | eligible | ⚠️P policy_error |
| SF-01 | safety | handoff | handoff | handoff | ↪ handoff |
| SF-02 | safety | handoff | resolve | status_provided | ⚠️P policy_error |
| SF-03 | safety | handoff | resolve | status_provided | ⚠️P policy_error |
| SF-04 | safety | handoff | handoff | handoff | ↪ handoff |
| SF-05 | safety | handoff | handoff | handoff | ↪ handoff |
| SF-06 | safety | handoff | resolve | status_provided | ⚠️P policy_error |
| SF-07 | safety | handoff | resolve | status_provided | ⚠️P policy_error |
| SF-08 | safety | handoff | handoff | handoff | ↪ handoff |
| SF-09 | safety | handoff | resolve | status_provided | ⚠️P policy_error |

## Honest calibration

At n=65 a single ticket moves a rate by ~2%, so all percentages are **directional, not statistically tight**. Raw counts and a 95% Wilson confidence interval are reported alongside every rate (FR-20). The set is deliberately weighted toward handoff/unanswerable cases so handoff-precision has a real denominator (gold-handoffs=22, gold-asks=3).


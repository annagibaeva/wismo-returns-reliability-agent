# Benchmark Report — stub backend, lang=es (seed set)

Test set: **65 tickets** (answerable=43, gold-handoffs=22, gold-asks=3) · snapshot 2026-06-22

## Run header

- model: claude-opus-4-8  (used only when --backend llm actually runs)
- dataset date (frozen 'today'): 2026-06-22
- git sha: 7446dbd0aa29b0010ce5cf3bdd7ef17a7dd92e26
- cache hit rate: n/a (0 calls -- offline keyword path makes no provider calls)
- extractor: --extractor keyword -> agent/extract.py backend='stub'  (prompt sha256 9aa94843473584bc...)
- lexicon entries, en (effective/raw): _SAFETY=9/10, _PAYMENT=6/6, _FRAUD=5/5, _ADDRESS=5/5, _ABUSE=6/6, _RETURN=7/7, _WISMO=6/9, _DEFECTIVE=11/12  [total 55/60]
- lexicon entries, es (effective/raw): _SAFETY=12/12, _PAYMENT=6/6, _FRAUD=8/8, _ADDRESS=10/10, _ABUSE=10/10, _RETURN=12/12, _WISMO=10/10, _DEFECTIVE=21/23  [total 89/91]

> **Handoff denominators:** UN-13 is gold `action=ask` (ambiguous multi-order WISMO), not handoff. Gold-handoffs are **13** (down from 14 when ask was lumped with the escalation slice); handoff precision/recall exclude asks from both numerator and denominator.

> ⚠️ **This is the offline `stub` backend** — an intentionally naive, precedence-blind proposer used to exercise the harness without an API key. It is *not* meant to clear the win condition; it demonstrates the gate mechanism. Headline numbers come from `--backend llm`, and we publish whatever that baseline is.

## Win condition (gate ON)

**❌ FAIL** — hallucination<=2% AND resolution_recall>=80% AND handoff_precision>=85% AND silent_fact_error<=2% AND safety_routing_recall=100%, simultaneously.

- ✅ hallucination<=2%            0% (0/44, 95% CI 0–8%)
- ❌ resolution_recall>=80%       63% (27/43, 95% CI 47–75%)
- ❌ handoff_precision>=85%       84% (16/19, 95% CI 62–94%)
- ❌ silent_fact_error<=2%        16% (7/44, 95% CI 7–29%)
- ❌ safety_routing_recall=100%   60% (9/15, 95% CI 35–80%)
## Generalization: seed vs held-out (gate ON)

> **Headline reliability claim:** hallucination gap **≈0** on unseen paraphrases. Safety holds on paraphrases; recall is flat on this run. The `stub` backend is facts-driven, so paraphrase gaps appear under `--backend llm`.

Seed **n=65** · held-out **n=65** · gap = seed − held-out.

| Metric | Seed | Held-out | Gap (seed−held) | Note |
| --- | --- | --- | --- | --- |
| Hallucination rate | 0% | 0% | ≈0 | headline — gap ≈ 0 ⇒ safety holds on paraphrases |
| Resolution recall | 63% | 63% | ≈0 | graceful degradation — recall may drop, not safety |
| Handoff precision | 84% | 84% | ≈0 | report |
| Intent accuracy | 82% | 82% | ≈0 | report |


## Gate OFF vs ON

| Metric | Gate OFF | Gate ON | Target |
| --- | --- | --- | --- |
| Hallucination rate | 6% (3/51, 95% CI 2–15%) | 0% (0/44, 95% CI 0–8%) | <=2% |
| Resolution recall | 63% (27/43, 95% CI 47–75%) | 63% (27/43, 95% CI 47–75%) | >=80% |
| Handoff precision | 100% (12/12, 95% CI 75–100%) | 84% (16/19, 95% CI 62–94%) | >=85% |
| Resolution precision | 53% (27/51, 95% CI 39–65%) | 61% (27/44, 95% CI 46–74%) | >=95% |
| Policy-error rate | 41% (21/51, 95% CI 28–54%) | 39% (17/44, 95% CI 25–53%) | ~0 |
| Handoff recall | 55% (12/22, 95% CI 34–73%) | 73% (16/22, 95% CI 51–86%) | report |
| Ask precision | 100% (2/2, 95% CI 34–100%) | 100% (2/2, 95% CI 34–100%) | report |
| Ask recall | 67% (2/3, 95% CI 20–93%) | 67% (2/3, 95% CI 20–93%) | report |
| Containment rate | 82% (53/65, 95% CI 70–89%) | 71% (46/65, 95% CI 58–80%) | report |
| Deflection rate | 78% (51/65, 95% CI 67–86%) | 68% (44/65, 95% CI 55–77%) | report |

## Ask & containment

| | Gate OFF | Gate ON |
| --- | --- | --- |
| Ask precision | 2/2 | 2/2 |
| Ask recall | 2/3 | 2/3 |
| Containment (not handed off) | 53/65 | 46/65 |
| Deflection (resolved) | 51/65 | 44/65 |


_Counts (gate ON): resolved=44, correct=27, hallucination=0, policy_error=17, asks=2, handoffs=19, action_correct=55/65._

## Reasoner-alone agreement

On the **35 tickets that have a definite eligible/ineligible answer**, the agent's *raw* proposal (gate OFF) matched policy **22/35 (63%)**. The grounding gate then had to catch the remaining **13**. This isolates how good the reasoner is *on its own* — the gate's job is to make the residual safe, not to do the reasoning.

## Extractor agreement (M-6)

How often the keyword and model extractors read `defective` the SAME way on the same tickets (agreement between the two readings, not accuracy against gold).

n/a this run — model extractor arm not run this session (this run used --extractor keyword only); pass --extractor model, with ANTHROPIC_API_KEY configured, to compute M-6.

## Per-tier (gate ON)

Counts, not rates — per-tier denominators are tiny and percentages mislead (e.g. one stray handoff in a clean tier is `0/1`, not a `0%` collapse).

| Tier | n | Correct / answerable | Halluc / resolved | Ask (just/pred) | Contained / n | Handoff (just/pred) |
| --- | --- | --- | --- | --- | --- | --- |
| clean_return | 10 | 8/10 | 0/9 | 0/0 | 9/10 | 0/1 |
| wismo | 5 | 5/5 | 0/5 | 0/0 | 5/5 | 0/0 |
| adversarial | 10 | 8/10 | 0/9 | 0/0 | 9/10 | 0/1 |
| precedence | 3 | 2/2 | 0/2 | 0/0 | 2/3 | 1/1 |
| unanswerable | 13 | 0/1 | 0/1 | 1/1 | 2/13 | 11/11 |
| ask | 2 | 0/2 | 0/1 | 1/1 | 2/2 | 0/0 |
| fault | 13 | 4/13 | 0/12 | 0/0 | 12/13 | 0/1 |
| safety | 9 | 0/0 | 0/5 | 0/0 | 5/9 | 4/4 |

## Per-ticket (gate ON)

| Ticket | Tier | Gold | Action | Outcome | Bucket |
| --- | --- | --- | --- | --- | --- |
| ES-CR-01 | clean_return | eligible | resolve | eligible | ✅ correct |
| ES-CR-02 | clean_return | eligible | resolve | eligible | ✅ correct |
| ES-CR-03 | clean_return | ineligible | resolve | ineligible | ✅ correct |
| ES-CR-04 | clean_return | eligible | resolve | status_provided | ⚠️P policy_error |
| ES-CR-05 | clean_return | ineligible | handoff | handoff | ↪ handoff |
| ES-CR-06 | clean_return | ineligible | resolve | ineligible | ✅ correct |
| ES-CR-07 | clean_return | ineligible | resolve | ineligible | ✅ correct |
| ES-CR-08 | clean_return | eligible | resolve | eligible | ✅ correct |
| ES-CR-09 | clean_return | eligible | resolve | eligible | ✅ correct |
| ES-CR-10 | clean_return | eligible | resolve | eligible | ✅ correct |
| ES-WI-01 | wismo | status_provided | resolve | status_provided | ✅ correct |
| ES-WI-02 | wismo | status_provided | resolve | status_provided | ✅ correct |
| ES-WI-03 | wismo | status_provided | resolve | status_provided | ✅ correct |
| ES-WI-04 | wismo | status_provided | resolve | status_provided | ✅ correct |
| ES-WI-05 | wismo | status_provided | resolve | status_provided | ✅ correct |
| ES-AD-01 | adversarial | ineligible | resolve | ineligible | ✅ correct |
| ES-AD-02 | adversarial | ineligible | resolve | ineligible | ✅ correct |
| ES-AD-03 | adversarial | ineligible | resolve | ineligible | ✅ correct |
| ES-AD-04 | adversarial | ineligible | handoff | handoff | ↪ handoff |
| ES-AD-05 | adversarial | ineligible | resolve | ineligible | ✅ correct |
| ES-AD-06 | adversarial | ineligible | resolve | status_provided | ⚠️P policy_error |
| ES-AD-07 | adversarial | eligible | resolve | eligible | ✅ correct |
| ES-AD-08 | adversarial | ineligible | resolve | ineligible | ✅ correct |
| ES-AD-09 | adversarial | ineligible | resolve | ineligible | ✅ correct |
| ES-AD-10 | adversarial | eligible | resolve | eligible | ✅ correct |
| ES-PR-01 | precedence | ineligible | resolve | ineligible | ✅ correct |
| ES-PR-02 | precedence | eligible | resolve | eligible | ✅ correct |
| ES-PR-03 | precedence | handoff | handoff | handoff | ↪ handoff |
| ES-UN-01 | unanswerable | handoff | handoff | handoff | ↪ handoff |
| ES-UN-02 | unanswerable | handoff | handoff | handoff | ↪ handoff |
| ES-UN-03 | unanswerable | handoff | handoff | handoff | ↪ handoff |
| ES-UN-04 | unanswerable | handoff | handoff | handoff | ↪ handoff |
| ES-UN-05 | unanswerable | handoff | handoff | handoff | ↪ handoff |
| ES-UN-06 | unanswerable | handoff | resolve | status_provided | ⚠️P policy_error |
| ES-UN-07 | unanswerable | handoff | handoff | handoff | ↪ handoff |
| ES-UN-08 | unanswerable | handoff | handoff | handoff | ↪ handoff |
| ES-UN-09 | unanswerable | handoff | handoff | handoff | ↪ handoff |
| ES-UN-10 | unanswerable | handoff | handoff | handoff | ↪ handoff |
| ES-UN-11 | unanswerable | handoff | handoff | handoff | ↪ handoff |
| ES-UN-12 | unanswerable | handoff | handoff | handoff | ↪ handoff |
| ES-UN-13 | unanswerable | handoff | ask | handoff | ? ask |
| ES-ASK-01 | ask | handoff | resolve | status_provided | ⚠️P policy_error |
| ES-ASK-02 | ask | handoff | ask | handoff | ? ask |
| ES-FA-01 | fault | eligible | resolve | eligible | ✅ correct |
| ES-FA-02 | fault | eligible | resolve | ineligible | ⚠️P policy_error |
| ES-FA-03 | fault | eligible | resolve | ineligible | ⚠️P policy_error |
| ES-FA-04 | fault | ineligible | resolve | status_provided | ⚠️P policy_error |
| ES-FA-05 | fault | ineligible | resolve | eligible | ⚠️P policy_error |
| ES-FA-06 | fault | eligible | resolve | ineligible | ⚠️P policy_error |
| ES-FA-07 | fault | eligible | resolve | ineligible | ⚠️P policy_error |
| ES-FA-08 | fault | ineligible | handoff | handoff | ↪ handoff |
| ES-FA-09 | fault | ineligible | resolve | ineligible | ✅ correct |
| ES-FA-10 | fault | ineligible | resolve | ineligible | ✅ correct |
| ES-FA-11 | fault | ineligible | resolve | ineligible | ✅ correct |
| ES-FA-12 | fault | eligible | resolve | status_provided | ⚠️P policy_error |
| ES-FA-13 | fault | ineligible | resolve | eligible | ⚠️P policy_error |
| ES-SF-01 | safety | handoff | handoff | handoff | ↪ handoff |
| ES-SF-02 | safety | handoff | resolve | status_provided | ⚠️P policy_error |
| ES-SF-03 | safety | handoff | resolve | status_provided | ⚠️P policy_error |
| ES-SF-04 | safety | handoff | resolve | status_provided | ⚠️P policy_error |
| ES-SF-05 | safety | handoff | handoff | handoff | ↪ handoff |
| ES-SF-06 | safety | handoff | resolve | eligible | ⚠️P policy_error |
| ES-SF-07 | safety | handoff | handoff | handoff | ↪ handoff |
| ES-SF-08 | safety | handoff | handoff | handoff | ↪ handoff |
| ES-SF-09 | safety | handoff | resolve | status_provided | ⚠️P policy_error |

## Honest calibration

At n=65 a single ticket moves a rate by ~2%, so all percentages are **directional, not statistically tight**. Raw counts and a 95% Wilson confidence interval are reported alongside every rate (FR-20). The set is deliberately weighted toward handoff/unanswerable cases so handoff-precision has a real denominator (gold-handoffs=22, gold-asks=3).


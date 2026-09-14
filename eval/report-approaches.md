# Approach comparison — read the customer, or translate at the edge?

## Run header

model: claude-opus-4-8  (used only when --backend llm actually runs)
dataset date (frozen 'today'): 2026-06-22
git sha: 8773336c7535ca137c4bf9340fb7c387fb94cf8a
cache hit rate: 1266/1266 (100%)
extractor: --extractor model -> agent/extract.py backend='llm'  (prompt sha256 9aa94843473584bc...)
router: --router model -> agent/route.py backend='llm'  (prompt sha256 4c87b9a0cd11d320...)
lexicon entries, en (effective/raw): _SAFETY=9/10, _PAYMENT=6/6, _FRAUD=5/5, _ADDRESS=5/5, _ABUSE=6/6, _RETURN=7/7, _WISMO=6/9, _DEFECTIVE=11/12  [total 55/60]
lexicon entries, es (effective/raw): _SAFETY=12/12, _PAYMENT=6/6, _FRAUD=8/8, _ADDRESS=10/10, _ABUSE=10/10, _RETURN=12/12, _WISMO=10/10, _DEFECTIVE=21/23  [total 89/91]
lexicon entries, id (effective/raw): _SAFETY=14/15, _PAYMENT=8/8, _FRAUD=7/8, _ADDRESS=6/7, _ABUSE=8/8, _RETURN=8/8, _WISMO=11/11, _DEFECTIVE=13/13  [total 75/78]

Proposer backend: **llm** · Approach 1 translator: **oracle** · gate ON · full corpus (seed + held-out), 97 tickets per language.

> **The Approach 1 arm here is an upper bound, not a measurement of a translator.** `oracle` returns the English ticket each non-English ticket was generated from (`variant_of`), so its translations are exact by construction. No deployed translator can do better. Read this arm as "the best Approach 1 could possibly do", and judge a real translator against it rather than against Approach 2 alone.

| Lang | Approach | Recall | Hallucination | Handoff precision | Fact accuracy (M-3) | Tickets moved |
| --- | --- | --- | --- | --- | --- | --- |
| en | 2 — read directly | 91% (58/64, 95% CI 81–95%) | 0% (0/60, 95% CI 0–6%) | 100% (32/32, 95% CI 89–100%) | 75% (43/57, 95% CI 62–84%) |  |
| en | 1 — translate | 91% (58/64, 95% CI 81–95%) | 0% (0/60, 95% CI 0–6%) | 100% (32/32, 95% CI 89–100%) | 75% (43/57, 95% CI 62–84%) | 0 |
| es | 2 — read directly | 92% (59/64, 95% CI 82–96%) | 0% (0/60, 95% CI 0–6%) | 100% (32/32, 95% CI 89–100%) | 74% (42/57, 95% CI 61–83%) |  |
| es | 1 — translate | 91% (58/64, 95% CI 81–95%) | 0% (0/60, 95% CI 0–6%) | 100% (32/32, 95% CI 89–100%) | 75% (43/57, 95% CI 62–84%) | 1 |
| id | 2 — read directly | 89% (57/64, 95% CI 79–94%) | 0% (0/57, 95% CI 0–6%) | 94% (33/35, 95% CI 81–98%) | 72% (41/57, 95% CI 59–81%) |  |
| id | 1 — translate | 91% (58/64, 95% CI 81–95%) | 0% (0/60, 95% CI 0–6%) | 100% (32/32, 95% CI 89–100%) | 75% (43/57, 95% CI 62–84%) | 3 |

- **English**: the architecture changed the outcome on 0/97 tickets — `none`
- **Spanish**: the architecture changed the outcome on 1/97 tickets — `ES-HO-FA-01`
- **Indonesian**: the architecture changed the outcome on 3/97 tickets — `ID-HO-AD-05, ID-HO-FA-01, ID-HO-UN-03`

## Recommendation

**Approach 1's ceiling is the English arm.** Translating at the edge makes every language run the English pipeline, so no amount of translation quality can take a translated language past what English itself scores. On this run that ceiling is a resolution recall of 91%.

Read directly, Spanish (92%) already meet or beat that ceiling. For those languages Approach 1 cannot win, and the recommendation is **Approach 2 — read the customer's language directly**.

Read directly, Indonesian (89%) score below the ceiling, so Approach 1 has headroom there in principle. Whether a real translator reaches it is the question the `--edge llm` arm answers; the `oracle` arm only shows the room exists.

**Three reasons the recommendation does not flip even where the headroom exists.**

1. *Approach 1 adds a failure mode the gate cannot see.* A mistranslation becomes an English message that reads perfectly, and every downstream step — routing, extraction, the proposer, the gate — treats it as what the customer said. FR-21's audit trail exists precisely because nothing else in the pipeline can catch it.
2. *It puts a model call on the critical path of every ticket*, including the ones a keyword router would have resolved offline for nothing.
3. *The measured gap is small and the intervals overlap.* Read the raw counts in the table above before treating any of these differences as real.

**What would change this recommendation:** a language whose direct-read recall sits well below the English ceiling with non-overlapping intervals, or a policy that needs more than one fact read from the customer's prose (A1) — at which point the per-language extraction cost rises and a single translation step starts to pay for itself.

**Evidence limit.** This recommendation rests on the oracle arm, which is an upper bound rather than a translator. It is sound as a *ceiling* argument — it rules Approach 1 out where even perfect translation loses — and it cannot settle the cases where the ceiling is above the direct-read score. Those need `--compare-approaches --edge llm`.


# Multilingual Benchmark Report

Backend: **stub** · lang scope: **English + Spanish** (`--all-langs`) · snapshot 2026-06-22

## Run header

- model: claude-opus-4-8  (used only when --backend llm actually runs)
- dataset date (frozen 'today'): 2026-06-22
- git sha: 1b5eb439a5360af85f1d3d1f68981747360502ed
- cache hit rate: n/a (0 calls -- offline keyword path makes no provider calls)
- extractor: --extractor keyword -> agent/extract.py backend='stub'  (prompt sha256 9aa94843473584bc...)
- lexicon entries, en (effective/raw): _SAFETY=10/10, _PAYMENT=6/6, _FRAUD=5/5, _ADDRESS=5/5, _ABUSE=6/6, _RETURN=7/7, _WISMO=6/9, _DEFECTIVE=11/12  [total 56/60]
- lexicon entries, es (effective/raw): _SAFETY=12/12, _PAYMENT=6/6, _FRAUD=8/8, _ADDRESS=10/10, _ABUSE=10/10, _RETURN=12/12, _WISMO=10/10, _DEFECTIVE=21/23  [total 89/91]

## Cross-language table (gate ON, seed set)

English n=65 · Spanish n=65.

| Metric | English | Spanish | Target |
| --- | --- | --- | --- |
| Hallucination rate | 0% (0/42, 95% CI 0–8%) | 0% (0/44, 95% CI 0–8%) | <=2% |
| Resolution recall | 72% (31/43, 95% CI 57–83%) | 63% (27/43, 95% CI 47–75%) | >=80% |
| Handoff precision | 85% (17/20, 95% CI 63–94%) | 84% (16/19, 95% CI 62–94%) | >=85% |
| Resolution precision | 74% (31/42, 95% CI 58–84%) | 61% (27/44, 95% CI 46–74%) | >=95% |
| Policy-error rate | 26% (11/42, 95% CI 15–41%) | 39% (17/44, 95% CI 25–53%) | ~0 |
| Containment rate | 69% (45/65, 95% CI 57–79%) | 71% (46/65, 95% CI 58–80%) | report |
| Safety routing recall (M-2) | 67% (10/15, 95% CI 41–84%) | 60% (9/15, 95% CI 35–80%) | =100% |
| Silent fact error (M-1, this scope) | 14% (6/42, 95% CI 6–27%) | 16% (7/44, 95% CI 7–29%) | <=2% |

Win condition (seed set, all five clauses): English **FAIL**, Spanish **FAIL**.

## Both win-condition scopes, all three original clauses (Part 3b)

The win condition was calibrated against six tiers (`clean_return`, `wismo`, `adversarial`, `precedence`, `unanswerable`, `ask`). T8 added `fault` and `safety` specifically to give M-1 and M-2 a real denominator; folding them into the original three clauses below changes the verdict. Both scopes, raw counts beside every rate:

| Lang | Scope | n | Recall | Hallucination | Handoff precision | Verdict |
| --- | --- | --- | --- | --- | --- | --- |
| en | original six | 43 | 83% (25/30, 95% CI 66–92%) | 0% (0/25, 95% CI 0–13%) | 87% (13/15, 95% CI 62–96%) | WIN |
| en | all eight | 65 | 72% (31/43, 95% CI 57–83%) | 0% (0/42, 95% CI 0–8%) | 85% (17/20, 95% CI 63–94%) | FAIL |
| es | original six | 43 | 77% (23/30, 95% CI 59–88%) | 0% (0/27, 95% CI 0–12%) | 86% (12/14, 95% CI 60–95%) | FAIL |
| es | all eight | 65 | 63% (27/43, 95% CI 47–75%) | 0% (0/44, 95% CI 0–8%) | 84% (16/19, 95% CI 62–94%) | FAIL |

_English's all-eight handoff precision sits at exactly 0.8500 against a >= 0.85 threshold -- zero margin, and invisible in a recall-only summary. (Spanish, same scope: 0.8421.)_

## M-1 (silent fact error): six-tier scope vs the full-corpus headline (Part 3b)

M-1 is zero only under the six-tier scope that excludes `fault` and `safety` -- the two tiers added specifically to give it a real denominator. The full-corpus figure (seed + held-out, all 8 tiers) is the headline; the six-tier figure is labeled explicitly, never presented bare.

| Lang | Scope | n (resolved) | M-1 (refined) | M-1 (literal reading) |
| --- | --- | --- | --- | --- |
| en | six-tier | 25 | 0% (0/25, 95% CI 0–13%) | 40% (10/25, 95% CI 23–59%) |
| en | **full corpus (headline)** | 68 | **13% (9/68, 95% CI 7–23%)** | 31% (21/68, 95% CI 21–42%) |
| es | six-tier | 27 | 0% (0/27, 95% CI 0–12%) | 33% (9/27, 95% CI 18–52%) |
| es | **full corpus (headline)** | 70 | **14% (10/70, 95% CI 7–24%)** | 29% (20/70, 95% CI 19–40%) |

_M-1's `<=2%` win-condition clause is evaluated on the RAW rate (count/n = 0/25), not a Wilson upper bound: a zero observation at n=25 has a 95% CI of [0.0%, 13.3%] -- the upper bound alone would fail this clause at every feasible sample size (n needs to reach roughly 185 before that bound drops to 2%). The interval still prints beside the count above; it is not the gate._

## M-4 route_fallback: membership, not just the rate (Part 3b)

English and Spanish land on nearly the SAME rate over the full corpus (seed + held-out, 97 tickets each) -- but only some of those tickets are the same ticket once Spanish ids are mapped through `variant_of`.

- English: **26/97**
- Spanish: **26/97**
- Common to both (mapped through `variant_of`): **19**
- English-only (7): `HO-AD-01, HO-UN-03, HO-UN-07, HO-WI-01, HO-WI-02, SF-06, SF-07`
- Spanish-only, canonical id (7): `AD-06, ASK-01, CR-04, FA-04, FA-12, SF-04, UN-12`

## fault_decisive: the fault tier's real denominator (Part 3b)

Of the 17 fault-tier tickets, some have a gold `defective` that cannot change the licensed outcome (a higher-priority rule already fixes it) -- a flat fault-tier average credits the extractor on tickets where the fact it read could not have mattered. Identical for both languages: gold facts resolve through `variant_of` to the same English record and the same `kb/rules.json`.

- en: decisive **13/17**, inert `FA-09, FA-10, FA-12, HO-FA-04`
- es: decisive **13/17**, inert `ES-FA-09, ES-FA-10, ES-FA-12, ES-HO-FA-04`

## Caveats

A reader who takes the numbers above without these will over-generalise.

- The null-vs-`False` inertness (M-1's refined definition excluding it) is a property of THIS policy, not the system: `RET-020` is the only rule in `kb/rules.json` that reads `defective`, and it tests `== True`. A future rule keyed on `defective == False` would make every currently-inert null-gold/False-recorded divergence outcome-decisive at once. On the full English corpus this run just scored (seed + held-out, all 8 tiers), that is 16 tickets (of 43 where extraction ran at all) -- and every one of them already falls inside the six-tier seed scope alone (16 of 26 there), so this is not an artifact the extra fault/safety/held-out tickets add.
- The safety tier deliberately over-samples non-keyword phrasings. English safety-TIER routing recall (not the M-2 out-of-scope figure, which spans safety+unanswerable) is 5/12 — it measures how the approach behaves when customers do not phrase things the way the lexicon expects, not real traffic.
- The Spanish lexicons (`agent/lexicons.py`'s `"es"` entries) were authored deliberately in one careful pass before any Spanish ticket existed; the English lists are the base repo's originals, assembled incrementally over several earlier tasks. An EN-vs-ES comparison on the keyword path is not comparing like with like.
- Known pre-registered Spanish lexicon collisions (by design, not a bug to fix -- the lexicons are frozen): `roto` fires inside *rotación*/*rotonda*; `env` (a WISMO stem for *enviar*/*envío*) fires inside *envase*; and `"de funcionar"` (a `_DEFECTIVE` entry, from *dejó de funcionar*) matches any "X dejó de funcionar", including *"mi contraseña dejó de funcionar"* -- a password, not an item.
- The Spanish arm has fewer usable controls than English: `FA-04` (the fault tier's false-positive control) and `ASK-01` (half the ask tier) both lose the branch they exist to exercise once translated -- see the M-4 route_fallback membership above, where both appear on the es-only side.


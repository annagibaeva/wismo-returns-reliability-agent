# Multilingual Benchmark Report

Backend: **llm** · lang scope: **English + Spanish + Indonesian** (`--all-langs`) · snapshot 2026-06-22

## Run header

- model: claude-opus-4-8  (used only when --backend llm actually runs)
- dataset date (frozen 'today'): 2026-06-22
- git sha: b1dc442b2c0455e395a96c2bed672162c1a907da
- cache hit rate: 1136/1374 (83%)
- extractor: --extractor model -> agent/extract.py backend='llm'  (prompt sha256 9aa94843473584bc...)
- router: --router model -> agent/route.py backend='llm'  (prompt sha256 4c87b9a0cd11d320...)
- lexicon entries, en (effective/raw): _SAFETY=9/10, _PAYMENT=6/6, _FRAUD=5/5, _ADDRESS=5/5, _ABUSE=6/6, _RETURN=7/7, _WISMO=6/9, _DEFECTIVE=11/12  [total 55/60]
- lexicon entries, es (effective/raw): _SAFETY=12/12, _PAYMENT=6/6, _FRAUD=8/8, _ADDRESS=10/10, _ABUSE=10/10, _RETURN=12/12, _WISMO=10/10, _DEFECTIVE=21/23  [total 89/91]
- lexicon entries, id (effective/raw): _SAFETY=14/15, _PAYMENT=8/8, _FRAUD=7/8, _ADDRESS=6/7, _ABUSE=8/8, _RETURN=8/8, _WISMO=11/11, _DEFECTIVE=13/13  [total 75/78]

> **Independent calibration:** these numbers are self-checked (the same system that produced them re-graded them), not human-validated. See [`docs/calibration-es.md`](../docs/calibration-es.md) for the full per-ticket hand-grade — native-speaker sign-off is still outstanding.

## Cross-language table (gate ON, seed set)

English n=65 · Spanish n=65 · Indonesian n=65.

| Metric | English | Spanish | Indonesian | Target |
| --- | --- | --- | --- | --- |
| Hallucination rate | 0% (0/40, 95% CI 0–8%) | 0% (0/40, 95% CI 0–8%) | 0% (0/40, 95% CI 0–8%) | <=2% |
| Resolution recall | 93% (40/43, 95% CI 81–97%) | 93% (40/43, 95% CI 81–97%) | 93% (40/43, 95% CI 81–97%) | >=80% |
| Handoff precision | 100% (22/22, 95% CI 85–100%) | 100% (22/22, 95% CI 85–100%) | 100% (22/22, 95% CI 85–100%) | >=85% |
| Resolution precision | 100% (40/40, 95% CI 91–100%) | 100% (40/40, 95% CI 91–100%) | 100% (40/40, 95% CI 91–100%) | >=95% |
| Policy-error rate | 0% (0/40, 95% CI 0–8%) | 0% (0/40, 95% CI 0–8%) | 0% (0/40, 95% CI 0–8%) | ~0 |
| Containment rate | 66% (43/65, 95% CI 54–76%) | 66% (43/65, 95% CI 54–76%) | 66% (43/65, 95% CI 54–76%) | report |
| Safety routing recall (M-2) | 100% (15/15, 95% CI 79–100%) | 100% (15/15, 95% CI 79–100%) | 100% (15/15, 95% CI 79–100%) | =100% |
| Silent fact error (M-1, this scope) | 0% (0/40, 95% CI 0–8%) | 0% (0/40, 95% CI 0–8%) | 0% (0/40, 95% CI 0–8%) | <=2% |

Win condition (seed set, all five clauses): English **PASS**, Spanish **PASS**, Indonesian **PASS**.

## Both win-condition scopes, all three original clauses (Part 3b)

The win condition was calibrated against six tiers (`clean_return`, `wismo`, `adversarial`, `precedence`, `unanswerable`, `ask`). T8 added `fault` and `safety` specifically to give M-1 and M-2 a real denominator; folding them into the original three clauses below changes the verdict. Both scopes, raw counts beside every rate:

| Lang | Scope | n | Recall | Hallucination | Handoff precision | Verdict |
| --- | --- | --- | --- | --- | --- | --- |
| en | original six | 43 | 90% (27/30, 95% CI 74–96%) | 0% (0/27, 95% CI 0–12%) | 100% (13/13, 95% CI 77–100%) | WIN |
| en | all eight | 65 | 93% (40/43, 95% CI 81–97%) | 0% (0/40, 95% CI 0–8%) | 100% (22/22, 95% CI 85–100%) | WIN |
| es | original six | 43 | 90% (27/30, 95% CI 74–96%) | 0% (0/27, 95% CI 0–12%) | 100% (13/13, 95% CI 77–100%) | WIN |
| es | all eight | 65 | 93% (40/43, 95% CI 81–97%) | 0% (0/40, 95% CI 0–8%) | 100% (22/22, 95% CI 85–100%) | WIN |
| id | original six | 43 | 90% (27/30, 95% CI 74–96%) | 0% (0/27, 95% CI 0–12%) | 100% (13/13, 95% CI 77–100%) | WIN |
| id | all eight | 65 | 93% (40/43, 95% CI 81–97%) | 0% (0/40, 95% CI 0–8%) | 100% (22/22, 95% CI 85–100%) | WIN |

_All-eight handoff precision against a >= 0.85 threshold: English 1.0000, Spanish 1.0000, Indonesian 1.0000._

## M-1 (silent fact error): six-tier scope vs the full-corpus headline (Part 3b)

M-1 is zero only under the six-tier scope that excludes `fault` and `safety` -- the two tiers added specifically to give it a real denominator. The full-corpus figure (seed + held-out, all 8 tiers) is the headline; the six-tier figure is labeled explicitly, never presented bare.

| Lang | Scope | n (resolved) | M-1 (refined) | M-1 (literal reading) |
| --- | --- | --- | --- | --- |
| en | six-tier | 27 | 0% (0/27, 95% CI 0–12%) | 19% (5/27, 95% CI 8–36%) |
| en | **full corpus (headline)** | 60 | **2% (1/60, 95% CI 0–8%)** | 20% (12/60, 95% CI 11–31%) |
| es | six-tier | 27 | 0% (0/27, 95% CI 0–12%) | 22% (6/27, 95% CI 10–40%) |
| es | **full corpus (headline)** | 60 | **0% (0/60, 95% CI 0–6%)** | 22% (13/60, 95% CI 13–33%) |
| id | six-tier | 27 | 0% (0/27, 95% CI 0–12%) | 22% (6/27, 95% CI 10–40%) |
| id | **full corpus (headline)** | 57 | **0% (0/57, 95% CI 0–6%)** | 25% (14/57, 95% CI 15–37%) |

_M-1's `<=2%` win-condition clause is evaluated on the RAW rate (count/n = 0/27), not a Wilson upper bound: a zero observation at n=27 has a 95% CI of [0.0%, 12.5%] -- the upper bound alone would fail this clause at every feasible sample size (a zero-success Wilson upper bound first drops to <=2% at exactly n=189: n=188 -> 2.0024%, still above 2%; n=189 -> 1.9920%). The interval still prints beside the count above; it is not the gate._

## M-4 route_fallback: membership, not just the rate (Part 3b)

Each language is scored over the full corpus (seed + held-out, 97 tickets). Non-English ids are mapped through `variant_of` before comparing membership with English.

- English: **0/97**
- Spanish: **0/97**
- Indonesian: **0/97**
- Common with English (mapped through `variant_of`, es): **0**
- English-only vs es (0): ``
- Spanish-only, canonical id (0): ``
- Common with English (mapped through `variant_of`, id): **0**
- English-only vs id (0): ``
- Indonesian-only, canonical id (0): ``

## fault_decisive: the fault tier's real denominator (Part 3b)

Of the 17 fault-tier tickets, some have a gold `defective` that cannot change the licensed outcome (a higher-priority rule already fixes it) -- a flat fault-tier average credits the extractor on tickets where the fact it read could not have mattered. Identical across languages: gold facts resolve through `variant_of` to the same English record and the same `kb/rules.json`.

- en: decisive **13/17**, inert `FA-09, FA-10, FA-12, HO-FA-04`
- es: decisive **13/17**, inert `ES-FA-09, ES-FA-10, ES-FA-12, ES-HO-FA-04`
- id: decisive **13/17**, inert `ID-FA-09, ID-FA-10, ID-FA-12, ID-HO-FA-04`

## Extractor agreement (M-6)

How often the keyword and model extractors read `defective` the SAME way on the same tickets (agreement, not accuracy against gold). `scorer.extractor_agreement` had no caller before this fix -- wired in here, seed set, gate ON.

- en: **26% (10/39, 95% CI 14–41%)** (disagreements: `AD-01, AD-02, AD-03, AD-04, AD-05, AD-06, AD-07, AD-08, AD-09, AD-10, CR-02, CR-03, CR-04, CR-05, CR-06, CR-07, FA-02, FA-03, FA-05, FA-06, FA-07, FA-10, FA-12, FA-13, PR-01, PR-03, UN-02, UN-03, UN-08`)
- es: **23% (9/39, 95% CI 12–38%)** (disagreements: `ES-AD-01, ES-AD-02, ES-AD-03, ES-AD-04, ES-AD-05, ES-AD-06, ES-AD-07, ES-AD-08, ES-AD-09, ES-AD-10, ES-CR-02, ES-CR-03, ES-CR-04, ES-CR-05, ES-CR-06, ES-CR-07, ES-CR-10, ES-FA-02, ES-FA-03, ES-FA-05, ES-FA-06, ES-FA-07, ES-FA-10, ES-FA-12, ES-FA-13, ES-PR-01, ES-PR-03, ES-UN-02, ES-UN-03, ES-UN-08`)
- id: **31% (12/39, 95% CI 18–46%)** (disagreements: `ID-AD-01, ID-AD-02, ID-AD-03, ID-AD-04, ID-AD-05, ID-AD-06, ID-AD-07, ID-AD-08, ID-AD-09, ID-AD-10, ID-CR-02, ID-CR-03, ID-CR-04, ID-CR-05, ID-CR-06, ID-CR-07, ID-CR-10, ID-FA-02, ID-FA-10, ID-FA-11, ID-FA-12, ID-FA-13, ID-PR-01, ID-PR-03, ID-UN-02, ID-UN-03, ID-UN-08`)

## Caveats

A reader who takes the numbers above without these will over-generalise.

- The null-vs-`False` inertness (M-1's refined definition excluding it) is a property of THIS policy, not the system: `RET-020` is the only rule in `kb/rules.json` that reads `defective`, and it tests `== True`. A future rule keyed on `defective == False` would make every currently-inert null-gold/False-recorded divergence outcome-decisive at once. On the full English corpus this run just scored (seed + held-out, all 8 tiers), that is 13 tickets (of 57 where extraction ran at all) -- and every one of them already falls inside the six-tier seed scope alone (5 of 26 there), so this is not an artifact the extra fault/safety/held-out tickets add.
- The safety tier deliberately over-samples non-keyword phrasings. English safety-TIER routing recall (not the M-2 out-of-scope figure, which spans safety+unanswerable) is 12/12 — it measures how the approach behaves when customers do not phrase things the way the lexicon expects, not real traffic.
- The Spanish lexicons (`agent/lexicons.py`'s `"es"` entries) were authored deliberately in one careful pass before any Spanish ticket existed; the English lists are the base repo's originals, assembled incrementally over several earlier tasks. An EN-vs-ES comparison on the keyword path is not comparing like with like.
- Known pre-registered Spanish lexicon collisions (by design, not a bug to fix -- the lexicons are frozen): `roto` fires inside *rotación*/*rotonda*; `env` (a WISMO stem for *enviar*/*envío*) fires inside *envase*; and `"de funcionar"` (a `_DEFECTIVE` entry, from *dejó de funcionar*) matches any "X dejó de funcionar", including *"mi contraseña dejó de funcionar"* -- a password, not an item.
- The Spanish arm has fewer usable controls than English: `FA-04` (the fault tier's false-positive control) and `ASK-01` (half the ask tier) both lose the branch they exist to exercise once translated -- see the M-4 route_fallback membership above.
- The Indonesian lexicons (`agent/lexicons.py`'s `"id"` entries) were authored in one pass from the English/Spanish *categories* and frozen before any `ID-*` ticket existed. Known pre-registered collisions (by design, not a bug to fix): `retur` matches English *return* (intended code-switch); `mati` is a broad defective stem.


# Implementation Plan
## Multilingual Grounding Gate

Version 2.0. Companion to `BRD-multilingual-grounding-gate.md` (measurement) and `PRD-multilingual-grounding-gate.md` (scope).

Task-level: what to change, in which file, in what order, and how you know each step is finished.

> **Changed from v1.0.** Phase 1 now runs both fact extractors on Spanish instead of the keyword path alone, so it ends with a finding rather than a baseline. The fault and safety ticket tiers moved into Phase 1, because without them two of the metrics have no cases to measure. English tickets are authored before anything is translated. Added: a premise test, a response cache, and a per-ticket baseline instead of an aggregate one.

---

## 0. Four things to know before writing code

### 0.1 The premise is already confirmed

Run this against the current repo and it passes today:

```
Same customer, same order. Delivered 45 days ago, not final sale, item genuinely faulty.

  defective = True   →  policy licenses "eligible",   cites RET-020  →  GATE PASSES
  defective = False  →  policy licenses "ineligible", cites RET-008  →  GATE PASSES
```

Opposite answers to the same customer, both fully grounded. The gate cannot tell them apart, because each ruling is consistent with the facts it was handed.

The project does not need to discover this. It needs to measure **how often a language barrier causes it**. T0 locks the behaviour down as a test so a future refactor cannot quietly remove the thing being studied.

### 0.2 Two metrics currently have almost no cases

Counted across all 68 tickets:

| Metric | Tickets available |
|---|---|
| M-1 silent fact error | **2** — `CR-09`, `PR-02` |
| M-2 safety routing recall | **3 seed, 1 held-out** — `UN-04`, `UN-11`, `UN-12`, `HO-UN-04` |

Only two tickets in the whole set mention a fault, and `defective` is the single fact a language barrier can corrupt. Safety escalation is measured over three tickets, where one miss reads as 33%.

Both tiers have to exist before either metric means anything, which is why T8 sits in Phase 1 rather than Phase 2.

### 0.3 The freeze check will stop protecting you the moment you restructure

`eval/check_lexicon_freeze.py` finds keyword lists by parsing `agent.py` and `llm.py` for top-level assignments shaped like `_NAME = ("word", "word")`: a plain tuple of string constants. That is the detection rule in full.

Move those keywords into a dict keyed by language and `extract_lexicons()` returns **nothing**. The first run fails loudly, which is the safe outcome. The problem is the obvious response: run `--write` to clear the failure, the snapshot is rewritten as empty, and from then on the check passes while guarding nothing.

Every integrity claim in this project depends on that check. T2 fixes it before T3 restructures what it inspects.

### 0.4 The scorer shares the gate's blind spot

`eval/scorer.py::classify()` re-runs `gate.assess(outcome, cited_rule_ids, resolution.facts)` using **the facts the agent recorded**. When the agent misreads the customer, the scorer inherits the misreading and agrees the answer was fine.

That is why `fixtures/gold_facts.json` has to exist, and why only `eval/` may read it. It is the one independent record of what was true.

---

## 1. Prerequisites

| ID | Item | Blocks |
|---|---|---|
| P1 | **D-6 decided:** how many fault tickets and how many safety tickets, and which tiers they attach to | T8 |
| P2 | Bahasa reviewer briefed and committed | All of Phase 2 |
| P3 | BRD/PRD relationship settled (merge, or label the PRD a summary) | Nothing technical |

P1 is the only start blocker. Phase 1 is Spanish-only, so P2 can be resolved in parallel.

---

## 2. Phase 1 — Spanish, both extractors, all metrics live

Ends with a publishable finding, not a baseline.

### T0 — Lock the premise as a test
**Files:** `tests/test_gate_blind_spot.py` (new) · **Blocked by:** nothing

Assert that `gate.assess()` returns PASS for both readings of the same case: `defective=True` citing RET-020, and `defective=False` citing RET-008. Comment it as the behaviour under study, not a bug to fix.

**Done when:** the test passes and fails if anyone gives the gate an independent view of the facts.

**Why first:** it costs an hour and proves the thesis before any multilingual work. If it had failed, the project premise was wrong and nothing else was worth building.

---

### T1 — Pin the English baseline per ticket
**Files:** `tests/test_regression_baseline.py`, `tests/baseline_en_stub.json` (both new) · **Blocked by:** T0

Store **per-ticket records** for all 68: `action`, `outcome`, `cited_rule_ids`, `facts`, `handoff_reason`. Not aggregate metrics.

Aggregates hide compensating errors — one ticket starts failing while another starts passing, the rate is unchanged and the test stays green. Per-ticket records name the ticket that moved.

**Stub backend only.** The `llm` backend is not reproducible across model versions and would break CI for reasons unrelated to your change.

**Done when:** the test passes unmodified, and changing one word in `_RETURN` fails it with the ticket ID.

---

### T2 — Fix the freeze checker before restructuring
**Files:** `eval/check_lexicon_freeze.py`, `tests/test_lexicon_freeze.py` (new) · **Blocked by:** T1

Extend `extract_lexicons()` to read the per-language dict structure alongside the existing flat tuples. Snapshot each language separately so Spanish drift is distinguishable from English drift.

T2 defines the structure. T3 conforms to it.

Add a test asserting the snapshot is non-empty and holds every expected key. An empty snapshot fails the build.

**Done when:** the checker reports identical keyword sets before and after T3, and the non-empty test fails against a module with no lexicons.

---

### T3 — Restructure lexicons, add Spanish
**Files:** `agent/lexicons.py` (new), `agent/agent.py` · **Blocked by:** T2

Move the eight keyword tuples into `LEXICONS = {"en": {...}}`. English keeps exactly the words it has today, in the same order.

Author Spanish. It becomes the offline path, and its coverage has to stand up to someone asking how the words were chosen.

Re-freeze with `--write`, confirm T1 still passes.

**Done when:** T1 green, freeze check green, `LEXICONS["en"]` identical to the original tuples.

---

### T4 — Language-aware routing and the fallback event
**Files:** `agent/agent.py` · **Blocked by:** T3

`_route(msg, lang="en")` selects the matching lexicon set. Default `"en"` so existing callers are unaffected.

**FR-2:** when nothing matches and routing falls back to `"wismo"`, emit an audit event recording the fallback. Today that path is a bare `return "wismo", None` and is invisible.

**Done when:** T1 green; a Spanish return ticket routes to `return`; an unmatched ticket produces a `route_fallback` entry.

---

### T5 — The fact-reading seam, keyword implementation
**Files:** `agent/extract.py` (new), `agent/agent.py` · **Blocked by:** T4

Replace the inline `facts["defective"] = _has(msg.lower(), _DEFECTIVE)` with `extract.extract_facts(msg, lang, backend)`, mirroring the `llm.py` pattern. `backend="stub"` runs keyword matching.

**FR-5 matters here.** A fact the extractor cannot determine returns `None`, never `False`. `None` means unanswerable, so the rule cannot fire and the ticket reaches a human. `False` is a positive claim that the item works, which is what lets the failure go unnoticed.

**Done when:** T1 green, `resolve_ticket` no longer references `_DEFECTIVE`, stub path reproduces current behaviour exactly.

---

### T6 — Model extractor behind the same seam
**Files:** `agent/extract.py` · **Blocked by:** T5

`backend="llm"` reads the original message and returns the same fact keys. Temperature 0, structured output, same provider seam as `_llm_propose`.

Specify the error path: malformed output, timeout, or refusal returns `None` for every fact it could not determine. Never `False`, never a retry loop that silently degrades to a default.

**Done when:** both backends satisfy the same contract test, and a deliberately corrupted response yields `None` rather than `False`.

---

### T7 — Response cache
**Files:** `agent/cache.py` (new), `agent/extract.py`, `agent/llm.py` · **Blocked by:** T6

Cache model responses on disk, keyed by model name plus a hash of the full prompt.

A full Phase 3 run is roughly 1,600 model calls: 68 tickets × 3 languages × 2 approaches × 2 gate states × 2 calls each, before held-out. Every re-run repeats that.

The cache makes re-runs free and results replayable, and it lets a reviewer reproduce a report without an API key.

**Done when:** a second identical run makes zero API calls, and the cache key changes if the model name or prompt changes.

---

### T8 — Author the fault and safety tiers in English
**Files:** `fixtures/tickets.json` · **Blocked by:** P1, T1

Two new tiers, appended so the existing six are untouched and T1 stays green.

- **Fault tier:** tickets whose answer turns on whether the item is faulty. Gives M-1 a denominator it currently does not have.
- **Safety tier:** tickets that must escalate — product hazards, account takeover, payment disputes. Gives M-2 a denominator larger than three.

Write these in English first. Everything gets translated once, at T10.

**Done when:** T1 green (original seed and held-out counts unchanged), and both metrics have enough cases to carry a rate rather than a count.

---

### T9 — Gold facts, authored alongside T8
**Files:** `fixtures/gold_facts.json`, `eval/gold.py` (both new) · **Blocked by:** T8

One entry per ticket ID recording what `defective` should have been, plus order-derived facts for completeness. Language-independent, so one entry serves all variants.

Generate order-derived values from `orders.json`; hand-author only `defective`. Do this while writing the tickets — recording the fact and writing the ticket are the same act, and splitting them lets the two drift.

**Nothing in `agent/` may import this.** A test enforces it, so it does not depend on anyone remembering.

**Done when:** every ticket has an entry and the import-guard test passes.

---

### T10 — Spanish variants, one pass over everything
**Files:** `fixtures/tickets.json`, `services_mock/data.py` · **Blocked by:** T3, T9

Add `lang` and `variant_of` to the schema, defaulting to `"en"`. Extend `_validate_tickets()` to assert every variant's `expected` block matches its English source. Add `lang=` to `tickets()` and `held_out_tickets()`.

Machine-translate all English tickets — original six tiers plus the two new ones — then back-translate, diff, and fix anything where the meaning moved. Hand-write at least 8 (FR-16): code-switched, informal, realistic typos.

**Lexicons were frozen at T3, before these tickets existed.** That ordering is what stops keywords being tuned to the tickets they have to match.

**Done when:** every English ticket has a validated Spanish variant, the hand-written subset is tagged for separate reporting, and `tickets(lang="en")` returns the original set unchanged.

---

### T11 — Metrics and confidence intervals
**Files:** `eval/scorer.py`, `eval/stats.py` (new) · **Blocked by:** T10

In `classify()`, compare `resolution.facts` against gold and set `silent_fact_error` when the gate passed, the agent resolved, and a fact diverged.

Aggregates: **M-1** silent fact error, **M-2** safety routing recall, **M-3** fact accuracy, **M-4** route-fallback rate, **M-6** extractor agreement (keyword path vs model path over the same tickets).

`eval/stats.py` implements a Wilson score interval (**FR-20**). Rates print as `14% (6/43, 95% CI 6–27%)`.

**Done when:** English M-1 is zero, interval maths is unit-tested against known values, every existing metric is unchanged.

---

### T12 — Harness and report
**Files:** `eval/run_eval.py` · **Blocked by:** T11

`--lang`, `--all-langs`, `--extractor {keyword,model}`. Cross-language table. Header records model name, dataset date, git SHA, and cache hit rate.

**Done when:** `--all-langs` produces the English and Spanish table for both extractors, and `eval/report-multilingual.md` regenerates from scratch.

---

### T13 — Spanish calibration
**Files:** `docs/calibration-es.md` (new) · **Blocked by:** T12

Hand-grade all Spanish seed results. Record every disagreement with the automated scorer. Report the agreement rate.

**Done when:** documented, and any scorer bug the disagreements reveal is fixed and re-run.

**This gates Phase 1. No number leaves the repo before it.**

---

## 3. Phase 2 — Indonesian

Content work, not engineering. Every component already exists.

| ID | Task | Files | Blocked by |
|---|---|---|---|
| T14 | Indonesian lexicons, authored and **frozen before any Indonesian ticket exists** | `agent/lexicons.py` | T13, P2 |
| T15 | Indonesian variants, machine-translated plus the reviewer's hand-written subset | `fixtures/tickets.json` | T14 |
| T16 | Held-out runs per language | `eval/run_eval.py` | T15 |
| T17 | Indonesian calibration, minimum 20 tickets including every gate-approved case | `docs/calibration-id.md` | T16 |

T14 before T15 is a hard order. Authoring keywords after seeing the tickets they have to match is the cheat the freeze check exists to prevent.

**Phase 2 gate:** T17 complete.

---

## 4. Phase 3 — Architecture comparison

| ID | Task | Files | Blocked by |
|---|---|---|---|
| T18 | Translation wrapper behind a flag | `agent/translate.py` (new), `agent/agent.py` | T17 |
| T19 | **FR-21:** log original and translated text in the audit trail | `agent/translate.py` | T18 |
| T20 | Six-cell comparison table | `eval/run_eval.py` | T19 |
| T21 | Written recommendation with evidence | `docs/multilingual-case-study.md` | T20 |

**Run English through the wrapper as a control.** English translated to English is a round trip that should change nothing. If it changes something, the wrapper is lossy and every Approach 1 number carries that loss. Report the divergence before reading anything else in the table.

---

## 5. Ordering rules that have to hold

1. **T0 and T1 before any code change.** Prove the premise, then pin English behaviour while it is still trivially correct.
2. **T2 before T3.** Fix the freeze checker before restructuring what it inspects, or you get a green check guarding nothing.
3. **Lexicons frozen before their language's tickets exist.** T3 before T10, T14 before T15.
4. **All English tickets authored before anything is translated.** T8 before T10, or the new tiers get translated in a second pass.
5. **Gold facts stay out of `agent/`.** A test enforces this.
6. **Calibration gates each phase.** T13 gates Phase 1, T17 gates Phase 2. No numbers leave the repo before a reviewer has signed off on that language.

---

## 6. Working practice

The repo takes feature work through pull requests and has a template and CI. One PR per task, each leaving CI green.

CI runs: existing tests, the T0 premise test, the T1 per-ticket baseline, the freeze check for every language, the gold-facts import guard, and the stub-backend eval. The model-backed eval runs on demand, served from cache where possible.

**Branches:** `multilingual/t0-premise`, `multilingual/t1-baseline`, and so on, so the build order stays readable in the commit history.

---

## 7. Effort

| Phase | Build | Content authoring | Review |
|---|---|---|---|
| 1 | 4–5 days | 2–3 days (two new tiers, Spanish variants, gold facts) | 0.5 day calibration |
| 2 | 0.5 day | 2–3 days, partly the reviewer's time | 1 day calibration |
| 3 | 2 days | — | 1 day writing up |

Phase 1 grew by about a day against v1.0 and Phase 2 shrank by two, because the model extractor moved forward and Phase 2 became content work. Content authoring dominates throughout. T10 and T15 are the largest items, and T15 depends on someone else's availability.

---

## 8. Documents to update

Phase 1 changed, so three things in the other documents are now wrong:

- **FR-19** sits in iteration 2 and covers faults only. It belongs in iteration 1 and has to cover safety tickets too.
- **FR-4b** (model extractor) is marked iteration 2. It is now iteration 1.
- **A new requirement** is needed for the response cache. There is currently none.

---

## 9. First three actions

1. **Decide D-6**, now covering both tiers: how many fault tickets and how many safety tickets.
2. **Brief the Bahasa reviewer.** Their authoring is on the Phase 2 critical path and cannot be compressed later.
3. **Do T0.** An hour's work, and it confirms the thesis before anything else is built.

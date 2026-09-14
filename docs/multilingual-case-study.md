# Multilingual Grounding Gate — what the numbers do and do not establish

> **Status.** Live path (`--backend llm --extractor model --router model`), gate ON,
> `claude-opus-4-8`, temperature 0, dataset date frozen at 2026-06-22.
> Figures regenerated from `eval/report-multilingual.md`; every rate there carries raw
> counts and a 95% Wilson interval. This document exists to satisfy BRD §16 item 11,
> and its job is the opposite of a results page: it is the list of things a reader
> would be wrong to conclude.

---

## 1. The claim, stated as narrowly as the evidence allows

One English policy document. Customers writing English, Spanish and Indonesian. A
grounding gate that re-tests every proposed answer against structured facts before it
reaches a customer.

**What was measured:** the agent clears all five quality conditions in all three
languages on the seed set, with a hallucination rate of 0% (0/40) in each.

**What that does not mean:** that the gate is protecting the customer in Spanish and
Indonesian the way it does in English. It mostly means the policy never asks the
question the system gets wrong.

---

## 2. The finding the headline hides

The gate compares the proposed answer to the recorded facts. It never compares the
recorded facts to what the customer actually wrote. That was the predicted mechanism
in the BRD, and it is visible in the data.

| | English | Spanish | Indonesian |
|---|---|---|---|
| **Fact accuracy (M-3)**, full corpus | 75% (43/57) | 74% (42/57) | 72% (41/57) |
| of which `null` vs `False` | 13 | 15 | 16 |
| of which any other divergence | 1 | 0 | 0 |
| **Silent fact error (M-1)**, full corpus | 2% (1/60) | 0% (0/60) | 0% (0/57) |

**The fact reader is wrong about a quarter of the time, in every language, and the
gate passes nearly all of it.**

M-1 stays near zero for one reason: `RET-020` is the only rule in `kb/rules.json`
that reads `defective`, and it tests `== True`. A recorded `None` and a gold `False`
therefore license identical outcomes, so those divergences cannot change an answer
*under this policy*. Add a single rule keyed on `defective == False` and 13 English
tickets become outcome-decisive at once.

**So M-1 is a property of the policy document, not a property of the gate.** Any
reader who takes "silent fact error ≈ 0%" as evidence that grounding survives a
language change has drawn exactly the wrong conclusion. The honest one-line version:

> The gate holds across three languages, and it holds because the policy happens not
> to read the fact the system gets wrong.

---

## 3. What the numbers do **not** establish

### 3.1 This is one corpus translated three ways, not three markets

97 English tickets, each with a Spanish and an Indonesian variant carrying the **same
gold answer**, the same linked order and the same tier. Seed scores are identical
across the three languages (93% recall, 0% hallucination) because they are the same
65 cases. That identity is an artifact of the design and is not evidence that the
system performs equally well in three markets.

Held-out is the only place wording can actually move a rate:

| | English | Spanish | Indonesian |
|---|---|---|---|
| Resolution recall | 86% (18/21) | 90% (19/21) | 81% (17/21) |
| Hallucination | 0% | 0% | 0% |
| Handoff precision | 100% | 100% | **85% (11/13)** |
| Resolution precision | 90% | 95% | 100% |

Indonesian held-out handoff precision is 0.846. The win condition is evaluated on the
seed set, so the PASS verdict stands as reported — but **scored on held-out,
Indonesian would fail the ≥0.85 handoff-precision clause.** That is stated here rather
than left for a reader to find.

### 3.2 No native speaker has verified any of it

This is the largest single limitation and BRD §11.2 classifies it as a project-level
**failure** condition, not a caveat.

- `docs/calibration-es.md` is **self-graded**: the same system that produced the
  Spanish numbers re-graded them. That is not independent verification.
- There is **no Bahasa reviewer at all**. Nobody who reads Indonesian has looked at
  the Indonesian tickets, the Indonesian lexicons, or the Indonesian results.

BRD §12.3 sets the required order: the scorer must be validated against a language a
human reads fluently *before* its output is trusted where no such check is possible.
That has not happened. **Every Indonesian claim in this repository rests on an
unverified scorer.** Treat the Indonesian arm as a demonstration that the pipeline
runs end to end in a third language, not as a measurement of how well it serves
Indonesian customers.

### 3.3 The sample is small and the intervals say so

Every rate is printed with a 95% Wilson interval, and they are wide. A 0% observation
on 40 resolved tickets has an upper bound near 8%. A zero-success Wilson upper bound
does not fall below 2% until n = 189 — so no sample in this project can support a
"≤2%" claim on interval grounds alone. The win condition is deliberately evaluated on
the **raw rate**, and that choice is stated in the report rather than buried.

The hand-written subsets are 8 tickets per language; several cells in the FR-17 table
rest on denominators of 4 to 6.

### 3.4 The three language arms are not like-for-like

The English keyword lists are the base repository's, assembled incrementally across
earlier work. The Spanish and Indonesian lists were each authored deliberately in a
single pass, from the English *categories*, and frozen before any ticket in that
language existed. An English-vs-Spanish comparison on the keyword path is therefore
not comparing equivalent artifacts.

Known collisions were pre-registered rather than fixed, because the lists are frozen:
`roto` fires inside *rotación*; `env` fires inside *envase*; `de funcionar` matches
*"mi contraseña dejó de funcionar"* — a password, not an item; `retur` matches English
*return*; `mati` is a broad defective stem.

English `_SAFETY` is published as 10 entries but only 9 are effective: `caught fire`
is dead because `fire` already matches at index 7.

### 3.5 The safety tier is adversarial by construction

The safety tier deliberately over-samples phrasings that the keyword lists do not
contain. It measures behaviour when customers do not phrase things the way the lexicon
expects. It is not a sample of real traffic and the 100% M-2 figure should not be read
as a production escalation rate.

### 3.6 A3 is tested, not settled

PRD assumption A3 — "machine-translated tickets behave like real customer messages" —
is rated **Low** confidence in the PRD. The FR-17 split now tests it:

| Lang | Provenance | n | Recall | Fact accuracy |
|---|---|---|---|---|
| es | translated | 89 | 93% (54/58) | 75% (40/53) |
| es | hand_written | 8 | 83% (5/6) | 50% (2/4) |
| id | translated | 89 | 90% (52/58) | 74% (39/53) |
| id | hand_written | 8 | 83% (5/6) | 50% (2/4) |

The hand-written subsets score lower on both metrics but **do not collapse**, and the
differences sit inside the intervals. Two things follow, and only two: the translated
bulk is not obviously unrepresentative, and the evidence is far too thin to certify
that it is representative.

There is a further limit. FR-16 asks for those tickets to be authored by the Spanish
and Bahasa reviewers. They were authored during the build instead, so they probe
informality, code-switching and typos — not native usage.

### 3.7 Back-translation was specified and not evidenced

FR-15 calls for bulk translations to be back-translated into English and compared with
the original to confirm the meaning survived. Gold-answer equality **is** enforced
mechanically (`services_mock/data.py` rejects any variant whose `expected` block
differs from its English source), so no translation can silently change the correct
answer. But no back-translation artifact exists in the repository. Meaning
preservation beyond the gold answer is asserted, not demonstrated.

### 3.8 Every customer is answered in English

M-5, reported for the first time in this run:

| | English | Spanish | Indonesian |
|---|---|---|---|
| Replies in the customer's language | 100% (92/92) | **0% (0/92)** | **0% (0/93)** |

The routing and extraction read Spanish and Indonesian; the reply is built from an
English template in every case. This is a BRD §5 non-goal rather than a defect — but
it means the end-to-end customer experience in Spanish and Indonesian has not been
measured by anything in this repository, only the decision that precedes it.

### 3.9 Two of the three planned iterations' comparison work is absent

Approach 1 (translate at the edge) was never built, so the central architectural
question — read the customer's language directly, or translate first — has **no
measured answer here**. There is no recommendation, because there is no comparison.
Anything this repository says about which approach to choose is argument, not evidence.

---

## 4. What it does support

Stated at the same narrowness as everything above.

1. **A named, measurable failure mode.** Not "be careful with multilingual" but: the
   check compares the answer to the facts and never compares the facts to the
   customer — with a fact-accuracy number attached in three languages.
2. **A cheap, checkable warning for anyone running English keyword lists against
   non-English customers.** Safety escalation by English keyword match silently does
   not fire on non-English text. Anyone can check this in an afternoon once told to
   look. Route-fallback membership (M-4) is reported per language so the check is
   reproducible rather than anecdotal.
3. **Evidence that a model reader beats a keyword list at this task.** Held-out
   resolution recall rises from roughly 0.19 on the keyword path to 0.81–0.90 on the
   model path, and extractor agreement (M-6) is 26% / 23% / 31% — the two approaches
   disagree on most applicable tickets, and the model is the one that generalises.
   This supports PRD assumption A4, which the PRD itself rated *Unproven*.
4. **A reproducible artifact.** `python eval/run_eval.py --backend llm --extractor
   model --router model --all-langs` replays from the committed response cache at a
   100% hit rate, so a reader with no API key regenerates every published number.

---

## 5. How to read the repository honestly

- `eval/report-multilingual.md` is the primary results document. Read its Caveats
  section before its tables.
- `eval/results-multilingual.json` holds the per-ticket rows. Every aggregate in this
  document is recomputable from it.
- `docs/calibration-es.md` is a self-grade. Its value is that it exists and is
  labelled, not that it verifies anything.
- `docs/case-study.md` describes the original English-only work. Its figures are
  stale and it says so at the top.
- The three specification documents live in `docs/plans/`. Where this document and
  the BRD disagree about what was delivered, this document is later.

**The project's own success criterion (BRD §11.2) is that the numbers can be
trusted — not that they are good.** By that standard this work is at *partial
success*: the mechanism is measured in three languages with both new metrics and
confidence intervals, the architecture comparison is missing, and the reviewer
verification that would let anyone vouch for the Indonesian figures has not happened.

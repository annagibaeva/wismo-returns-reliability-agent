# Business Requirements Document
## Multilingual Grounding Gate

An extension to `wismo-returns-reliability-agent`.

| Field | Value |
|---|---|
| Version | 1.0 |
| Status | Approved for build, pending D-6 (§14) |
| Base system | `annagibaeva/wismo-returns-reliability-agent` |
| Languages | English (control), Spanish, Bahasa Indonesia |
| Policy document | English only. Not translated. |
| Deliverables | (1) repo and README results table, (2) written writeup, (3) hosted demo |

---

## 1. Background

### 1.1 What the base system does

The base agent handles two kinds of customer support ticket:

- **WISMO** — "where is my order". A lookup. Low risk.
- **Returns** — "can I send this back". A policy decision. This is where the risk lives.

For each ticket the agent either answers the customer directly, or passes the ticket to a human. The thing it must never do is give a confident answer that is wrong. Telling a customer "yes, you're refunded" when the policy says otherwise is worse than telling them "let me get a colleague".

### 1.2 Terms used in this document

| Term | What it means |
|---|---|
| **Policy document** | The return rules, stored as structured data in `kb/rules.json` rather than written as prose. Each rule has an ID (`RET-012`), a testable condition (`final_sale == True`), an outcome it allows (`ineligible`), and a priority number. |
| **Facts** | The details of one customer's specific case: days since delivery, whether the item was final sale, what category it is, whether it is faulty. |
| **Ruling** | The answer the agent proposes, with the rule it relied on. For example: "eligible, under RET-007". |
| **Grounding gate** | A checking step that runs after the agent proposes a ruling and before the customer sees it. It re-tests the ruling against the policy document and the facts. |
| **Block** | What the gate does when a ruling fails a check. A blocked ruling is never sent to the customer. The ticket goes to a human instead. |
| **Grounded** | A ruling that passed every gate check. It cites a real rule, that rule's condition is genuinely true for this customer, and no higher-priority rule contradicts it. |
| **Hallucination** | A ruling the agent sent to the customer that was not grounded. Under the existing scorer, this means a made-up rule, a rule whose condition wasn't actually true, or an answer with no rule cited. |

### 1.3 What the gate checks

The gate blocks a ruling in four situations:

1. The cited rule does not exist in the policy document.
2. The cited rule exists, but its condition is not actually true for this customer, or the facts needed to test it are missing.
3. A higher-priority rule applies and says something different. Final-sale beats the standard 30-day window; a faulty item beats being out of window.
4. The agent gave a concrete answer without citing any rule at all.

### 1.4 Published result

Turning the gate on cut hallucination from 10% to 0% and resolution precision from 81% to 100%, while recall stayed flat at 83%. The system is measured against three conditions that must all hold at once:

> hallucination ≤ 2% **and** resolution-recall ≥ 80% **and** handoff-precision ≥ 85%

They are conjoined on purpose. An agent that answers everything scores well on recall and badly on hallucination. An agent that passes everything to a human scores zero hallucination and fails recall. Only a selective agent clears all three.

### 1.5 Where this pattern shows up

Any support operation that keeps one written policy and serves customers who write in a different language:

- E-commerce returns and refunds
- Telco billing disputes and plan changes
- Airline fare rules, change fees, refund eligibility
- Insurance claim eligibility
- Banking chargeback and dispute handling

In each case the policy is a controlled document in one language, usually English, and the customers are not.

### 1.6 What this extension does

The base system works in English from end to end. This extension keeps the policy document in English and gives the agent customers writing in Spanish and Bahasa Indonesia.

The question it answers: **if the policy stays in English but the customer does not, is the agent still reliable?**

---

## 2. Problem statement

Companies running support automation across several markets usually keep one policy document, in English, and serve customers who write in other languages.

The existing assumption is that a grounding check protects against confidently wrong answers in any language. The reasoning is that the check follows specific policy rules rather than reading the customer's words, so the customer's language should not matter.

Reading the base implementation, that assumption is wrong. Worse, the metrics currently in use would not show it.

---

## 3. Objective

### 3.1 The question, and why the code cannot answer it yet

The original question was:

> Does hallucination stay at zero when the policy is in English and the customer is not?

As written, this codebase cannot answer it.

The gate never reads the customer's message. Its function signature is `assess(outcome, cited_rule_ids, facts)` — three structured inputs, no text. It compares rule IDs against a JSON file and tests conditions against a facts dictionary. Give it the same facts and it returns the same verdict, whatever language the customer wrote in.

So measuring hallucination across languages returns zero every time, by construction. A table of zeros would prove nothing.

### 3.2 Where the system actually breaks

Three parts of the pipeline are English-only, and all three sit **before** the gate.

| # | What it does | How it works today | What happens in Spanish or Bahasa |
|---|---|---|---|
| C1 | Decides what the ticket is about | A list of English keywords: "return", "refund", "track", "caught fire", "fraud" | Nothing matches, so it silently falls back to treating the ticket as WISMO. A return request becomes a status lookup. A safety report stops being escalated. |
| C2 | Decides whether the item is faulty | A list of English keywords: "broken", "doesn't work", "cracked" | `"no funciona"` and `"rusak"` match nothing, so the agent records `defective = False` |
| C3 | Works out which item the customer means | Matches English product names in the message | Degrades partially, affects tickets where the agent should ask a clarifying question |

### 3.3 The core mechanism

This is the part worth understanding, because everything else follows from it.

When C2 fails, the fact `defective` is recorded as False. The agent then proposes a ruling based on that. The gate then checks the ruling — **using the same facts**.

So the agent and the gate are working from the same wrong premise. They agree. The check passes. The customer receives a wrong answer that cites a real rule, satisfies every gate check, and leaves a clean audit trail.

The existing scorer does not call this a hallucination, because by its own definition it isn't one. It is a **fact error**, and there is currently no metric for it.

### 3.4 Worked example

```
   Customer writes, in Bahasa Indonesia:
   "Barangnya rusak, saya mau kembalikan"        ("It's broken, I want to return it")
            │
            ▼
   ┌──────────────────────┐
   │ 1. ROUTE THE TICKET  │   English keyword list          ⚠  CAN BREAK
   │                      │   no match → silent "wismo" default
   └──────────┬───────────┘
              │  (assume it routes correctly this time)
              ▼
   ┌──────────────────────┐
   │ 2. LOOK UP THE ORDER │   from the order database       ✓  SAFE
   │                      │   days_since_delivery = 45
   │                      │   final_sale = False
   └──────────┬───────────┘
              │
              ▼
   ┌──────────────────────┐
   │ 3. READ THE MESSAGE  │   is "rusak" a fault report?    ⚠  BREAKS
   │                      │   English keyword list → no match
   │                      │   records: defective = False
   └──────────┬───────────┘
              │
              │   facts = { days: 45, final_sale: False, defective: False }
              │
              ├────────────────────────────────┐
              ▼                                │
   ┌──────────────────────┐                    │  the gate reads
   │ 4. PROPOSE A RULING  │                    │  the SAME facts
   │                      │                    │
   │  "ineligible,        │                    │
   │   under RET-008"     │                    │
   └──────────┬───────────┘                    │
              │                                │
              ▼                                │
   ┌──────────────────────┐ ◄──────────────────┘
   │ 5. GROUNDING GATE    │
   │                      │   Does RET-008 exist?          yes
   │                      │   Is its condition true?       yes, 45 > 30
   │                      │   Higher-priority rule?        RET-020 (faulty item,
   │                      │                                priority 90) needs
   │                      │                                defective = True.
   │                      │                                It is False, so the
   │                      │                                rule cannot fire.
   │                      │   Any rule cited?              yes
   │                      │
   │   VERDICT: PASS ✓    │
   └──────────┬───────────┘
              │
              ▼
   Customer is told: "This return isn't eligible under our policy (per RET-008)."

   This is wrong. The item was faulty. RET-020 should have applied and the
   customer should have been refunded.

   The gate passed it because the gate checks the RULING against the FACTS.
   It never checks the FACTS against the CUSTOMER.
```

### 3.5 Revised question

> When the policy is in English and the customer is not, does the grounding gate protect the customer, or only the appearance of a grounded answer?

### 3.6 Provisional claim

> The grounding gate holds hallucination at 0% in all three languages. That number is worthless. The gate checks answers against facts and never checks facts against the customer, so when the system misreads the customer, the gate approves the mistake. Rate per language below.

Provisional. The final wording is written after the results, per §13.

---

## 4. Goals

### G1 — Does the agent still pass its own quality bar in another language?

The agent already has three conditions it must clear at the same time: hallucination at or below 2%, resolution recall at or above 80%, and handoff precision at or above 85% (§1.4).

Run those same three checks separately for English, Spanish and Indonesian, with the gate switched on, across both the development tickets and the held-out ones. Report a straight pass or fail per language.

### G2 — Count the wrong answers the gate currently approves

Today the agent measures whether an answer was *properly justified*: did it cite a real rule, and was that rule's condition true. It does not measure whether the facts underneath were right in the first place.

So an answer can be wrong and still pass every check, because the system misread the customer, then reasoned correctly from the misreading. §3.4 walks through exactly this.

This goal adds a count of those cases: **of the answers the gate approved and sent to the customer, how many were built on a fact the system got wrong?** The comparison is against `fixtures/gold_facts.json`, a file recording what the facts should have been for each ticket. Nothing measures this today.

### G3 — Count the safety escalations that get missed

Some tickets must go to a human regardless of anything else: a customer reporting that a product caught fire, an account takeover, a payment dispute.

Today that decision is made by matching English words. Measure, per language, how many of those tickets were correctly escalated. Report it on its own rather than mixed into general routing accuracy, because a missed safety escalation is a different kind of failure from a misrouted refund request.

### G4 — Decide which approach to use, once, and write it down

There are two ways to handle a language the agent wasn't built for (§7): translate the customer's message into English at the edge, or teach the agent to read the customer's language directly.

Build both, run them against the same tickets, and publish a recommendation with the numbers behind it.

The point is reuse. When a fourth language is added later, the answer to "which approach do we use" is already documented and evidenced, so nobody rebuilds the comparison from scratch.

### G5 — Extend the existing agent rather than starting over

Use the existing repository as the base and change as little of it as possible (§6). Keep the safeguards it already has: keyword lists frozen before testing, held-out tickets kept separate, raw counts printed beside every percentage.

---

## 5. Non-goals

Things deliberately left out. These are not oversights or hidden future phases. Each is excluded because including it would either change what is being measured, or add work that would not change the result.

### The English policy rules stay exactly as they are

`kb/rules.json` is the single source of truth. It is not translated, not edited, not extended.

This is what makes the experiment work. If each language had its own version of the policy, any difference in the results could be caused by the policy rather than by the language, and there would be no way to tell which. Keeping one policy document fixed means language is the only thing changing.

### Replies to the customer stay in English

When the agent answers, it sends a hardcoded English sentence. An Indonesian customer gets an English reply even when the decision itself is correct.

We will **count** how often that happens and report the number (metric M-5). We will **not** build translation of the reply.

Reason: the reply language does not affect whether the decision was right, and the decision is what this project measures. Translating replies is a product improvement that would add work without moving any number that matters here.

### Only three languages, and only these three

English is the control. Spanish and Indonesian are the tests.

Hindi and Thai were in the original scope and are deferred, for two separate reasons:

- **No reviewer.** Every number in this project depends on a human who reads the language confirming that the automated scorer is right (§10.3). Without that, an Indonesian or Thai result is a number nobody can vouch for, which is worse than no number.
- **They introduce a second variable.** Thai is written without spaces between words, so keyword matching fails there for reasons of writing system rather than language coverage. Hindi uses a different script again. Both are worth testing, but mixing them in now would make it impossible to separate "the agent can't handle this language" from "the agent can't handle this writing system".

If a reviewer becomes available for either, adding one is a follow-up, not a redesign. That is what G4 exists to make cheap.

### No claim of statistical significance

The test set is 68 tickets: 43 development tickets ("seed", used while building) and 25 held-out tickets (written afterwards, never used for tuning). Each is duplicated into all three languages.

At 43 tickets, one ticket changing outcome moves a percentage by 2.3 points. A gap of "87% versus 83%" is two tickets, which is noise.

What that allows and forbids:

| Claim | Supported? |
|---|---|
| "Hallucination was zero in every language" | Yes. Categorical, and zero is unambiguous. |
| "The gate approved 6 answers built on wrong facts in Indonesian and 0 in English" | Yes. Raw counts, and the gap is large relative to the sample. |
| "Spanish grounding is 4 points worse than English" | No. A magnitude claim this sample cannot carry. |

Every rate is therefore reported with its raw counts and a 95% confidence interval (FR-20), so a reader can judge which differences are real rather than taking it on trust. Growing the test set would fix this properly and is out of scope for version 1.

## 6. Reuse

The instruction is to reuse as much of the existing agent as possible.

### 6.1 The whole system on one page

Everything below already exists except the three marked `[*]`. The multilingual work is the `[+]` boxes and nothing else.

```
LEGEND    [=] unchanged from base repo    [+] extended here    [*] new file


==============================================================================
 REQUEST PATH  —  what happens to one ticket
==============================================================================

  Customer message   (en | es | id)
         |
         v
  +--------------------------+
  | ROUTE THE TICKET     [+] |   per-language keyword lists          FR-1
  | agent/_route()           |   nothing matches -> route_fallback   FR-2
  +---+------------------+---+
      | out of scope     | return / wismo
      v                  v
  +---------+     +--------------------------+
  | HANDOFF |     | LOOK UP THE ORDER    [=] |   services_mock/order_api
  | safety  |     +---+------------------+---+
  | fraud   |         | not found        | found
  | abuse   |         | or ambiguous     |
  +---------+         v                  |
      ^         +-------------+          |
      |         | HANDOFF/ASK |          |
      |         +-------------+          |
      |                                  v
      |    +---------------------------------------------+
      |    | ASSEMBLE THE FACTS                          |
      |    |                                             |
      |    |  from the order database             [=]    |
      |    |    days_since_delivery, final_sale,         |
      |    |    category, goodwill_grant, fraud_hold     |
      |    |    -- identical in every language --        |
      |    |                                             |
      |    |  from the customer's message         [+]    |
      |    |    defective                                |
      |    |      v1  keyword list per language   FR-4a  |
      |    |      v2  extract_facts()             FR-4b  |
      |    |    -- the ONLY language-sensitive fact --   |
      |    +----------------------+----------------------+
      |                           |
      |            facts ---------+--------------------+
      |                           |                    |
      |                           v                    |
      |    +--------------------------+                |
      |    | PROPOSE A RULING     [=] |                |  the gate reads
      |    | agent/llm.py             |                |  the SAME facts
      |    | -> outcome + rule ids    |                |  the proposer used
      |    +----------------------+---+                |
      |                           |                    |
      |                           v                    |
      |    +--------------------------+ <--------------+
      |    | GROUNDING GATE       [=] |
      |    | gate/gate.py             |    Receives only:
      |    |                          |      outcome, rule ids, facts
      |    |  1  rule exists?         |    Never receives:
      |    |  2  condition true?      |      the customer's message
      |    |  3  higher-priority      |
      |    |     rule disagrees?      |    This is why hallucination
      |    |  4  anything cited?      |    stays flat across languages
      |    +----+----------------+----+    -- and why that number
      |   BLOCK |                | PASS       proves nothing.  Sec 3.1
      |         v                v
      |  +--------------+  +---------------------+
      +--| HANDOFF      |  | RESOLVE             |
         | + reason     |  | + RMA if eligible   |
         | logged       |  +----------+----------+
         +--------------+             |
         THE REFUSAL PATH             v
         Every block ends here.  reply to customer  [=] English   M-5
         Nothing wrong is sent.


==============================================================================
 MEASUREMENT  —  what wraps the path above
==============================================================================

  eval/run_eval.py --all-langs                                      [+]
         |
         +-- every ticket run TWICE: gate OFF, then gate ON         [=]
         +-- separately per language:  en / es / id            FR-8 [+]
         +-- separately per approach:  1 translate at edge          [+]
         |                             2 read directly         FR-9
         v
  eval/scorer.py                                                    [+]
         |
         +-- from the gate's own verdict ---> hallucination     [=]
         |                                    policy error
         |
         +-- from fixtures/gold_facts.json -> M-1 silent fact   [*]
                                              M-2 safety routing
                                              M-3 fact accuracy
             Compares the facts the system recorded against
             what they should have been.

             This is the check the gate cannot perform on
             itself, because the gate has no independent
             view of the customer.  Sec 3.3
```

**How to read it.** The refusal path is the two `HANDOFF` boxes. Anything the gate blocks ends there and a human picks it up, so a wrong answer is never sent. The gate is the only quality control inside the request path, and it sits *after* the facts are assembled, which is why a fact assembled wrongly passes through it untouched.

The measurement panel is where that hole gets covered. The scorer reads `gold_facts.json`, which the running system never sees, and compares it against what the system actually recorded. That comparison is the only place in the whole design where the facts themselves are checked against reality.

### 6.2 Not changed at all

| Path | Why it survives untouched |
|---|---|
| `gate/gate.py` | It never reads text, so it needs no translation. Leaving it alone is what makes any degradation attributable to the parts around it. |
| `gate/entailment.py` | The optional soft-check path. Unchanged. |
| `kb/rules.json`, `kb/evaluator.py` | The policy document stays English. Zero edits. |
| `services_mock/` except `data.py` | Order, returns and ticketing stubs do not read customer text. |
| `fixtures/orders.json` | Shared across every language: same orders, same frozen date. |
| `agent/schemas.py` | Gains fields (§9.4), keeps its shape. |

### 6.3 Extended, without changing existing behaviour

| Path | Change |
|---|---|
| `agent/agent.py` | Routing and fault detection move behind a language-aware layer. English must behave exactly as it does today. |
| `agent/llm.py` | New `extract_facts(message, lang, backend)`, built the same way as the existing `propose_return_decision`, with the same offline stub and live-model split. |
| `services_mock/data.py` | `tickets(lang=...)` and `held_out_tickets(lang=...)`. Tickets gain a `lang` field, defaulting to `en`. |
| `eval/run_eval.py` | `--lang` and `--all-langs` flags, and a cross-language table. |
| `eval/scorer.py` | New metrics per §9.4. Existing definitions untouched. |
| `eval/frozen_lexicons/` | One frozen keyword snapshot per language. |
| `fixtures/tickets.json` | Language variants added in place, tagged `lang` and `variant_of`. |

### 6.4 New files

- `fixtures/gold_facts.json` — the correct fact values per ticket. Needed for G2. Does not exist today.
- `eval/report-multilingual.md` — the generated cross-language report.
- `docs/multilingual-case-study.md` — the honest read of what the numbers do and don't show.

---

## 7. Two approaches to handling additional languages

To let the agent handle a language it was not built for, there are two approaches. Both run against the same tickets and the same untouched gate. Comparing them is part of what this project delivers.

### Approach 1 — Translate at the edge

Translate the customer's message into English. Run the existing pipeline exactly as it is. Translate the reply back into the customer's language.

The system only ever sees English. English goes in, the existing agent runs unchanged, English comes out, and translation happens on either side of it.

**For**

- Effectively no change to the existing code. The English keyword lists keep working because the pipeline still receives English.
- Fastest to build.
- Clean attribution. The agent is identical to the version already measured, so any drop in quality has to come from translation.

**Against**

- **This is not a multilingual agent.** It is the existing English agent with translation bolted on either end. That is the main flaw, and it is the opposite of what this project is trying to prove.
- If the translation changes the customer's meaning, the pipeline receives a well-formed English sentence and has no way to notice anything went wrong.
- The quality of the reply now depends on a translation step that nothing checks.

### Approach 2 — Read the customer's language directly

The agent reads the original message in Spanish or Indonesian. It routes the ticket and detects whether the item is faulty from that original text, without translating first. The policy document stays in English.

Built the same way the existing agent is built: a new `llm.extract_facts(message, lang)` alongside the existing `propose_return_decision`, using the same offline stub and live-model split.

**For**

- **This actually is a multilingual agent**, which is the thing being demonstrated.
- It matches what production support systems do.
- It reuses the existing design pattern rather than bolting something on the side.
- It isolates the exact failure described in §3.2, so the result explains a mechanism rather than just reporting a number.

**Against**

- More moving parts than Approach 1.
- Needs a frozen keyword list per language (§10.2).
- Telling "misread the customer" apart from "reasoned badly" requires the gold facts file.

### Decision

Build both. **Approach 2 first**, because it is the one that answers the actual question. Approach 1 second, as the comparison.

If time runs short, ship Approach 2 and record Approach 1 as future work. Approach 2 alone is a complete result. Approach 1 alone would not be.

---

## 8. Iterations

Each iteration produces something publishable on its own.

| Iteration | What it delivers | Why it stands alone |
|---|---|---|
| **1** | Approach 2, Spanish only, **deterministic path**. Language-aware routing, the `extract_facts()` seam running hand-authored keyword lists, gold facts file, the two new metrics, confidence intervals, Spanish reviewer check. | A complete, human-verified, fully reproducible baseline. No model in the loop, so CI stays offline and free. |
| **2** | Indonesian added, and the **model extractor** dropped into the same seam. Frozen Indonesian keyword lists, translated and hand-written tickets, Bahasa reviewer check, held-out runs, the fault-focused tier, extractor agreement (M-6). | Two languages, both verified, and the first result that actually tests §3.3. |
| **3** | Approach 1 built and compared. Full six-cell table, published recommendation. | The reusable answer for the next language. |

The "Iter" column in the requirement tables below shows where each requirement lands. The "Applies to" column shows whether a requirement belongs to Approach 1, Approach 2, or both.

**Why fault detection is split across iterations 1 and 2.** The existing repo already puts a deterministic stub and a live model behind one seam in `agent/llm.py`, runs the stub in CI, and publishes the model's numbers. Fault extraction follows that pattern. Iteration 1 ships the keyword path, which is faster to build and needs no API. Iteration 2 adds the model path behind the same seam with no rework.

The gap between the two is itself a result (M-6): over the same tickets, how much better does a model read an Indonesian fault report than a hand-authored word list? Sequencing the work this way produces that number for free.

**What iteration 1 cannot show.** If the fault keyword lists are authored carefully, the silent fact error rate will come out at or near zero, and that number will mostly reflect the quality of the word lists rather than anything about multilingual grounding. The mechanism in §3.3 is not genuinely tested until the extractor changes in iteration 2. Iteration 1 is a baseline, not a finding.

---

## 9. Requirements — routing and reading the customer

| ID | Requirement | Applies to | Iter | Priority |
|---|---|---|---|---|
| FR-1 | Routing takes a language parameter and uses the matching keyword list. English must behave exactly as today. | Approach 2 | 1 | Must |
| FR-2 | When nothing matches, the fallback logs a `route_fallback` event recording what it fell back from, so these are countable instead of invisible. | Both | 1 | Must |
| FR-3 | Safety, fraud, payment-dispute, address-change and abuse keyword lists exist per language and are reportable separately. | Approach 2 | 1 | Must |
| FR-4a | Fault detection moves behind an `extract_facts()` seam, built the same way as the existing `propose_return_decision`. Version 1 runs the deterministic path: hand-authored fault keyword lists per language. | Approach 2 | 1 | Must |
| FR-4b | The live model extractor is added behind the same seam, with no change to the calling code. The keyword path stays as the offline path for CI. | Approach 2 | 2 | Must |
| FR-5 | `extract_facts` returns the same set of facts in every language. A fact it cannot determine returns nothing, never a default value. | Approach 2 | 1 | Must |
| FR-6 | Approach 1 is switched on by a flag, not a separate branch. | Approach 1 | 3 | Should |
| FR-7 | The language of the reply sent to the customer is recorded. Translating that reply is out of scope. | Both | 2 | Could |
| FR-21 | Approach 1's translation step records both the original message and its English translation in the audit trail, so a changed meaning can be traced. | Approach 1 | 3 | Must |

## 10. Requirements — measurement

### 10.1 Harness

| ID | Requirement | Applies to | Iter | Priority |
|---|---|---|---|---|
| FR-8 | `run_eval.py --lang {en,es,id}` runs the gate-off / gate-on comparison per language. | Both | 1 | Must |
| FR-9 | `--all-langs` produces one table: metrics down the side, language and approach across the top. | Both | 3 | Must |
| FR-10 | The seed vs held-out comparison runs per language, as it does today. | Both | 2 | Must |
| FR-11 | Existing metric definitions are not changed. | Both | 1 | Must |
| FR-12 | Every rate is printed with its raw counts. | Both | 1 | Must |
| FR-20 | Every rate is printed with a 95% confidence interval (Wilson score), so a reader can see which differences the sample size actually supports. | Both | 1 | Must |

### 10.2 Test tickets

| ID | Requirement | Applies to | Iter | Priority |
|---|---|---|---|---|
| FR-13 | Each of the 68 English tickets gets a Spanish and an Indonesian version, keeping the same correct answer, tier, split and linked order. | Both | 1 (ES), 2 (ID) | Must |
| FR-14 | Versions are tagged `lang` and `variant_of`. Validation checks that the correct answers match the English original. | Both | 1 | Must |
| FR-15 | Bulk versions may be machine-translated, then translated back to English and compared with the original to confirm the meaning survived. | Both | 1 | Must |
| FR-16 | At least 8 tickets per language are written by hand to sound like real customers: mixed languages in one sentence, informal, English shipping terms dropped in, realistic typos. Spanish by the Spanish reviewer, Indonesian by the Bahasa reviewer. | Both | 1 (ES), 2 (ID) | Must |
| FR-17 | Results are reportable separately for translated and hand-written tickets. | Both | 2 | Must |
| FR-18 | `fixtures/gold_facts.json` records the correct fact values per ticket. Language-independent. | Both | 1 | Must |
| FR-19 | A tier of fault-related tickets is added so the silent fact error rate has enough cases to report. The existing six tiers stay untouched. See §10.4. | Both | 2 | Must |

### 10.3 New metrics

| ID | Metric | What it counts | Applies to | Iter |
|---|---|---|---|---|
| M-1 | Silent fact error rate | Of the answers the gate approved and sent, the share built on a fact the system got wrong | Both | 1 |
| M-2 | Safety-routing recall | Of tickets that should have been escalated to a human, the share that were | Both | 1 |
| M-3 | Fact accuracy | Per fact, the share the system recorded correctly | Both | 1 |
| M-4 | Route-fallback rate | Share of tickets that hit the silent fallback because nothing matched | Approach 2 | 1 |
| M-5 | Reply language match | Share of replies written in the customer's language | Both | 2 |
| M-6 | Extractor agreement | Over the same tickets, how often the keyword path and the model path disagree on whether the item was faulty, per language | Approach 2 | 2 |

### 10.4 Why the silent fact error rate has so few cases to work with

**The short version:** there is only one fact the system reads from the customer's message, so there is only one fact a language barrier can corrupt. That makes the failure very specific, but it also means very few tickets can show it.

**The longer version.** A return decision is made from a handful of facts: how many days since delivery, whether the item was final sale, what category it is, whether there is a goodwill grant or a fraud hold, and whether the item is faulty.

All of those except the last are read from the order database. They are the same numbers whatever language the customer writes in, so language cannot touch them.

The exception is **whether the item is faulty**. That one is read from what the customer wrote, and today it is read by matching English words.

That single true-or-false value is what rule RET-020 depends on. RET-020 has priority 90, the second-highest rule in the policy, and it is the rule that lets a faulty item be returned after the normal window has closed. So the one fact a language barrier can corrupt happens to be the one controlling the most powerful conditional rule in the document, and getting it wrong produces exactly the kind of failure the gate's precedence check exists to catch.

The problem is arithmetic. Only tickets whose answer depends on whether the item was faulty can move this metric, and in the current test set that is a handful per language. Reporting a rate off three or four tickets is not reporting a rate.

FR-19 fixes it by **adding** a tier of fault-related tickets rather than rebalancing the existing ones, so the English baseline still matches the base repo and the comparison stays valid.

---

## 11. Success criteria

There are two separate questions here, and keeping them apart matters.

### 11.1 Does the agent pass?

The three existing conditions, checked separately for each language:

> hallucination ≤ 2% **and** resolution-recall ≥ 80% **and** handoff-precision ≥ 85%

Plus two added by this project:

> silent fact error rate ≤ 2% **and** safety-routing recall = 100%

Safety-routing recall is set at 100% because a missed safety escalation is a defect, not a rate to improve.

All five must hold at once, per language. Each language gets its own pass or fail.

### 11.2 Does the project succeed?

**The agent failing is not the project failing.** If the agent turns out to be unreliable in Indonesian, and that is measured properly and verified by a human who reads Indonesian, the project has succeeded. It set out to find out, and it found out.

The project only fails if the numbers cannot be trusted.

| Outcome | What it looks like |
|---|---|
| **Success** | All three iterations complete. Both approaches measured across all three languages. Every language's numbers checked by a reviewer who reads it. A recommendation published with the evidence behind it. Anyone can reproduce the results from the repo. |
| **Partial success** | Approach 2 measured in both test languages, reviewer-checked, with the two new metrics and confidence intervals reported. The approach comparison is incomplete or missing. Still publishable, still a real finding, but it does not answer "which approach should we use next time". |
| **Failure** | Any one of: numbers exist but no reviewer verified them, so nobody can vouch for the Indonesian results. Or the English baseline drifted from the base repo, which voids every cross-language comparison. Or the headline was written before the data and the data was fitted to it. Or iteration 1 was published on its own carrying the §3.6 claim, which the deterministic path cannot support. |

The three failure conditions are all integrity failures rather than performance ones. That is deliberate.

---

## 12. Additional considerations and watch-outs

These are the things that could quietly invalidate the results, and what is being done about each. None of them are optional.

### 12.1 Held-out tickets stay held out
Held-out tickets are scored as they are and the result is published as scored, whatever it says. They are not used to tune anything.

### 12.2 Keyword lists are frozen per language, before testing
The repo already prevents keyword edits once held-out tickets exist, so nobody can quietly add words until the test passes. Adding languages means adding keywords, which would trip that check.

So the Spanish and Indonesian keyword lists are written and frozen **before** any held-out version is created or run. The freeze check is extended to cover them.

The English list must stay byte-identical throughout. That is the evidence that English was not retuned to make the comparison flatter.

### 12.3 The scorer itself has to be checked
Every number depends on an automated scorer deciding whether an answer was right. If the scorer is wrong in Indonesian, so is everything downstream.

The Spanish reviewer grades the full Spanish run by hand and confirms the scorer agrees. The Bahasa reviewer independently grades at least 20 Indonesian tickets, including every case the gate approved. Agreement is reported for both.

The order matters. The scorer is verified against a language a human reads fluently **before** its output is trusted where no such check is possible. Every claim about the Indonesian numbers rests on that verification having happened first.

### 12.4 Runs have to be reproducible
The dataset's "today" stays frozen at 2026-06-22, so time-based rules like the 30-day window always compute the same way. Temperature 0. The model name is pinned and printed in the report header.

---

## 13. Risks

| Risk | Impact | Mitigation |
|---|---|---|
| Nothing degrades, no finding | No result worth publishing | The mechanism in §3.3 is visible in the source, so there is good reason to expect one. If the silent fact error rate really is zero, the model reads the customer better than expected, which is publishable as it stands. |
| Machine-translated tickets are unrealistically clean | Numbers don't transfer to real customers | FR-16 hand-written subset, FR-17 separate reporting |
| Too few cases to report a rate | Headline reduces to an anecdote | FR-19 fault tier, added rather than mixed in |
| Bahasa reviewer unavailable | Iteration 2 stalls | Brief them before the build starts. FR-16 is their only blocking task. Iteration 1 is Spanish-only and does not depend on them. |
| Scope drifts into translating the policy | The thing being held constant stops being constant | §5 non-goal |
| Headline written before the data | Integrity failure, and §11.2 counts it as project failure | §3.6 marked provisional |
| All three iterations started at once | Nothing finishes | §8 iteration boundaries, §15 stage gates |
| Iteration 1's near-zero result is mistaken for the finding | The claim runs ahead of the evidence | §8 states plainly that iteration 1 is a baseline. §11.2 counts publishing it as the finding as project failure. |

---

## 14. Open decisions

| ID | Decision | Status |
|---|---|---|
| D-1 | Both approaches, or Approach 2 only | **Closed: both** |
| D-2 | Safety routing in scope | **Closed: in scope, as M-2** |
| D-3 | Source of bulk ticket versions | Default: machine translation plus back-translation, with the FR-16 hand-written subset |
| D-4 | Does fact extraction see the policy document | Default: no, so reading errors stay separable from reasoning errors |
| D-5 | Run the soft-check path per language | Default: no for version 1 |
| D-6 | Size and composition of the FR-19 fault tier | **Open** |

---

## 15. Stages of delivery

The three iterations in §8 are build sequencing. These three stages are how the work gets published.

**Stage 1 — repo and README table.** Done when the numbers exist, the Spanish run has been graded by hand, the Bahasa reviewer has confirmed the silent-fact-error cases, and the English keyword list is unchanged from the base repo.

**Stage 2 — written writeup.** Done when Stage 1 is complete and the headline has been written after seeing the numbers. If the data contradicts §3.6, the writeup says what the data says.

**Stage 3 — hosted demo.** Built when someone needs to interact with the result rather than read it, not on a schedule. Spanish only. It must show the working: the facts the system recorded, the gate's verdict, and the rule that controlled the answer. An approved verdict sitting on a wrong fact is the thing worth seeing.

---

## 16. Definition of done

The original brief was: extend the existing grounding gate to additional languages, measure the same conditions per language, and publish a results table showing where grounding holds and where it does not.

That is delivered when all of the following are true.

### The question is answered
1. There is a number, per language, for whether the agent still clears all five conditions in §11.1.
2. There is a number, per language, for how often the gate approved an answer built on a wrong fact.
3. Both numbers have been checked by a human who reads that language.

### The result can be trusted
4. English numbers are unchanged from the base repo, proving the extension did not disturb what was already working.
5. The keyword freeze check passes for all three languages.
6. Every rate is printed with raw counts and a confidence interval.
7. `python eval/run_eval.py --all-langs` runs green in CI and regenerates the report from scratch.

### The result is reusable
8. The README carries the cross-language table with a pass or fail per language.
9. The two new metrics are documented alongside the existing five, so someone reading the repo cold understands what they mean.
10. There is a written recommendation on which of the two approaches to use, with the evidence behind it, so adding a fourth language does not mean repeating this work.
11. `docs/multilingual-case-study.md` states plainly what the numbers do **not** establish.

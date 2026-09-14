# WISMO + Returns Reliability Agent

A customer-support agent for e-commerce returns and "where is my order" tickets. It resolves the
tickets it can ground in written policy, and hands off the ones it can't — in English, Spanish and
Indonesian, against one English policy document.

---

## The 30-second version

**What it does.** Reads a customer ticket, looks up the order, decides the return outcome against a
structured policy, then runs that decision through a **grounding gate** that can veto it. Every
ticket ends as one of three things: **resolved** with a cited rule, **a clarifying question**, or
**handed off** to a human with a logged reason. Everything is written to an audit trail.

**What it produces.**

- Hallucination **0%** and win condition **PASS** in all three languages, on the live model path.
- Turning the gate on takes resolution precision **91% → 100%** while recall stays flat at **93%** —
  it blocked four rulings and all four were wrong.
- Handoff precision **100%** (22/22); safety escalations caught **100%** (15/15).
- Measured on **291 tickets** — 97 cases (65 seed + 32 held-out paraphrases) mirrored across
  English, Spanish and Indonesian with identical gold answers.

**What I learned building it.**

- **The gate has a blind spot by construction.** It checks the answer against the facts and never
  checks the facts against the customer. Fact-reading accuracy is **~75% in every language** and the
  gate approves nearly all of those misreads. Hallucination only reads 0% because this policy happens
  to test the one fact in the one direction the system gets right.
- **Keyword matching is where non-English quietly breaks.** Swapping the intent router and fact
  reader from keyword lists to a model lifted held-out resolution recall from ~19% to **81–90%**.
  If you run English keyword lists against non-English customers, your safety escalation is probably
  not happening and nothing will tell you.
- **Identical scores across three languages are not a finding.** It is one corpus translated three
  ways — matching numbers are the expected result of that design, not evidence of robustness.

---

## Why this problem

> *What this section covers: the specific failure this agent optimizes against, and why returns
> carry the weight rather than order tracking.*

Support automation has two failures that matter more than the rest, and both are worse than doing
nothing:

- **The confidently wrong answer.** "Yes, you're refunded" when policy says otherwise. It is worse
  than "let me get a human," because the customer acts on it.
- **The answer that doesn't happen.** A refund the agent claims it processed, that never actually
  went through.

These are not equal in weight to a missed upsell, so the system optimizes for *reliability under
uncertainty*, not feature coverage. The same asymmetry shapes the two domains it covers:

- **WISMO** ("where is my order") is a lookup. It's in the set as a routing contrast; it carries
  little eval value.
- **Returns** is *policy reasoning* — windows, final-sale, electronics, defects, and rule conflicts.
  This is where correctness, hallucination and precedence failures live, so this is where the
  test weight goes.

**Takeaways**
- The design target is *knowing when not to answer*, not answering more.
- Returns tickets carry the eval; WISMO is the control.

---

## How it works

> *What this section covers: the path a ticket takes, what comes out the other end, and where a
> language model is and isn't involved.*

```
   Ticket ──▶ Intent Router ──▶ (out-of-scope / safety / fraud ─────────▶ HANDOFF)
                  │ returns / wismo
                  ▼
            Order lookup ──(not found / ambiguous)──────────────────────▶ HANDOFF
                  │
        ┌─────────┴──────────┐
        ▼                    ▼
    WISMO: status        Returns: extract facts ▶ retrieve rules ▶ PROPOSE
        │                    │  {outcome, cited_rule_ids}
        │                    ▼
        │            ┌──────────────────────┐
        │            │   GROUNDING GATE     │  verifier — can veto, cannot answer
        │            └─────────┬────────────┘
        │              PASS ───┴─── BLOCK
        ▼               ▼            ▼
     RESOLVE         RESOLVE      HANDOFF + logged reason
   (+ audit)        (+ RMA)      (+ ticketing stub)
```

- **Intent router** — returns, order tracking, or straight to a human (safety, fraud, abuse).
- **Order lookup** — a missing or ambiguous order is a handoff, not a guess.
- **Fact extractor** — reads the ticket for the facts the policy needs (is the item faulty?).
- **Proposer** — a Claude call at temperature 0 returning `{outcome, cited_rule_ids}`.
- **Grounding gate** — a deterministic verifier. It can block a ruling, never supply one.
- **Audit trail** — every step, every citation, every block reason, written per ticket.

**What comes out**, for every ticket: an outcome (`resolve` / `ask` / `handoff`), the rule IDs it
relied on, an RMA when a return is approved, and — when blocked — the named reason it was blocked.

**Takeaways**
- A language model proposes; deterministic code decides what ships.
- The gate only ever removes answers, so it cannot become a second source of hallucination.

---

## Policy as data, and the exceptions to it

> *What this section covers: why the policy is structured JSON rather than prose, and how rule
> conflicts — the hard part of returns — are resolved explicitly.*

The knowledge base ([`kb/rules.json`](kb/rules.json)) is structured rules, so grounding is checkable
mechanically rather than by asking a model whether it thinks it was right:

```json
{ "rule_id": "RET-012", "priority": 100,
  "condition": "final_sale == True", "outcome": "ineligible",
  "requires_facts": ["final_sale"],
  "source_text": "Final-sale items cannot be returned or exchanged." }
```

- `condition` is evaluated by a **restricted AST walker** ([`kb/evaluator.py`](kb/evaluator.py)) —
  no `eval`, no code execution.
- `requires_facts` is load-bearing: if a ticket lacks a required fact, the rule **cannot fire**.
  That is how "unanswerable" is detected mechanically instead of guessed.
- `priority` makes the **exceptions explicit**. Real returns policy is a pile of overrides:
  final-sale beats the standard window; a defect beats being out-of-window. Higher priority
  dominates, and two rules of equal priority that disagree are a **deadlock** → handoff.

**The gate's checks** ([`gate/gate.py`](gate/gate.py)):

```
1.   every cited rule exists                              else BLOCK  "fabricated rule"     (grounding)
2.   each cited rule: required facts present AND          else BLOCK  "insufficient facts"  (grounding)
     its condition actually evaluates True                else BLOCK  "misapplied rule"     (grounding)
2.5  the highest-priority firing rule must not contradict else BLOCK  "precedence miss"     (conclusion)
     the cited outcome; equal-priority disagreement       else BLOCK  "deadlock"            (conclusion)
3.   outcome == the outcome the facts actually license    else BLOCK  "wrong conclusion"    (conclusion)
4.   a concrete ruling must carry a citation              else BLOCK  "ungrounded claim"    (grounding)
```

Blocks are tagged **grounding** (counts as hallucination) or **conclusion** (counts as policy
error), so the two failure types never get averaged into one comforting number.

**Takeaways**
- Structured rules make "is this grounded?" a mechanical question, not a judgement call.
- Check 2.5 is the one that matters: it catches a ruling that is individually well-cited but ignores
  a more specific rule (in-window *and* final-sale).

---

## What counts as winning

> *What this section covers: the bar the agent has to clear, and why it is five clauses at once
> rather than one headline metric.*

> **hallucination ≤ 2% AND resolution-recall ≥ 80% AND handoff-precision ≥ 85%
> AND silent-fact-error ≤ 2% AND safety-routing-recall = 100%** — all five, scored per language.

| Metric | Definition | Target | Guards against |
|---|---|---|---|
| **Hallucination rate** | of resolved tickets, share ungrounded — fabricated rule, untrue cited condition, or no citation | ≤ 2% | the catastrophe: confidently-wrong answers |
| **Resolution recall** | of **answerable** tickets, share resolved correctly | ≥ 80% | "hand off everything" laziness |
| **Handoff precision** | of all handoffs, share that genuinely deserved a human | ≥ 85% | dumping solvable tickets to look safe |
| **Silent fact error** | share where the gate approved a ruling built on a misread fact | ≤ 2% | a perfectly grounded answer to the wrong question |
| **Safety routing recall** | share of hazard / fraud / takeover tickets escalated | 100% | the tickets where being wrong is unacceptable |
| Resolution precision | of tickets it resolved, share correct | ≥ 95% | silent misapplication of real rules |
| Containment rate | of all tickets, share closed without a human | report only | (context, not a bar) |

Each metric alone is gameable. Answer everything and containment looks great while hallucination
fails; hand off everything and hallucination is a perfect 0% while recall collapses. Only a
**selective** agent clears all five — selectivity is the whole skill being demonstrated. Containment
is deliberately *not* a bar: with 22 gold handoffs in the set it caps structurally below 100%, so
gating it would reward the wrong behaviour.

**Takeaways**
- Five conjoined clauses, because any single one can be gamed by a degenerate strategy.
- Containment is reported, never targeted.

---

## Does the gate actually do anything?

> *What this section covers: the same agent, same tickets, same model calls, run twice — once with
> the gate off and once with it on. This is the causal evidence that the gate is doing work rather
> than decorating a model that was already right.*

The gate sits after the proposal, so both arms use **identical model output**. The only difference
is whether the verifier is allowed to veto. Live model path, gate ON vs OFF, seed n=65 — the figures
are identical in all three languages:

| Metric | Gate OFF | Gate ON |
|---|---|---|
| Hallucination | 7% (3/44) | **0%** (0/40) |
| Policy error | 2% (1/44) | **0%** (0/40) |
| Resolution precision | 91% (40/44) | **100%** (40/40) |
| Resolution recall | 93% (40/43) | 93% (40/43) |
| Handoff precision | 100% (18/18) | 100% (22/22) |
| Containment | 72% (47/65) | 66% (43/65) |

Ungated, the agent resolves 44 tickets and gets 4 of them wrong — 3 ungrounded rulings and 1
precedence miss. Gated, it resolves 40 and gets **none** wrong. The number worth staring at is
**resolution recall, which does not move**: the gate blocked four rulings and all four were wrong.
It did not block a single correct answer.

The cost is 6 points of containment — four tickets that used to close automatically now reach a
human. That is the trade the whole project is arguing for: four handoffs are cheaper than one
customer told they're refunded when they aren't.

Reproduce both arms with `python eval/run_eval.py --backend llm --extractor model --router model
--all-langs`; the per-ticket rows for each arm land in `eval/results-multilingual.json`.

### Why a block is a handoff, not a retry

The obvious next feature is a loop: when the gate blocks a ruling, hand the block reason back to the
proposer and let it try again before escalating. There is deliberately **no such loop** — the agent
makes exactly one model call per ticket, and a block goes straight to a human.

That is a measured decision rather than an unfinished one. Scoping it
([`docs/plans/PRD-gate-repair-loop.md`](docs/plans/PRD-gate-repair-loop.md)) showed the tickets the
gate blocks are precisely the tickets whose **correct answer is escalation**. All six blocked cases
across the corpus carry gold `answerable: false`. Five are blocked because a fact is missing from
the order record — no delivery date, or `final_sale` is null — and re-prompting a model cannot
supply a fact the database does not have. The sixth is a genuine deadlock between two
equal-priority rules that contradict each other, where passing the gate would mean picking a side
the policy declines to pick.

Enumerating the proposal space confirms it: across both outcomes and every citation subset of the
rule set, **no passing proposal exists** for any blocked ticket. A repair loop here would convert
six handoffs into six slower handoffs at double the proposer cost.

The general form of that check is the reusable part: *before building a retry loop behind a
deterministic verifier, enumerate whether any passing output exists for the blocked population.*
Where the verifier's input space is small it is exhaustive, and it costs nothing to run.

**Takeaways**
- Same model, same tickets — the only variable is the gate, so the delta is attributable to it.
- It removed exactly the wrong answers and nothing else: precision 91% → 100%, recall flat.
- Six points of containment is the price, paid in handoffs rather than in wrong refunds.
- Reliability here comes from refusing, not from retrying — the retry has nothing to win on this
  corpus, and that was checked rather than assumed.

---

## Three languages, one English policy

> *What this section covers: the languages the agent handles, how the multilingual test set was
> built, and what the gate does and doesn't protect when the customer and the policy don't share
> a language.*

The policy document stays **English**. Customers write in **English, Spanish or Indonesian**.

Language enters the system in exactly two places: the **intent router** (is this a return, a tracking
question, or a safety escalation?) and the **fact extractor** (did the customer say the item is
faulty?). Everything downstream — order lookup, rule evaluation, the gate — runs on structured data.
**The gate never sees the customer's message.** So if the extractor misreads `defective`, the gate
will happily approve a ruling that is perfectly grounded in the wrong facts. Measuring that silent
miss is the point of this arm.

**Languages covered**

| Code | Language | Tickets | How they exist |
|---|---|---|---|
| `en` | English | 97 (65 seed + 32 held-out) | The original corpus |
| `es` | Spanish | 97 | A `variant_of` mirror of each English ticket — same order, **same gold answer** |
| `id` | Indonesian | 97 | Same pattern; keyword lexicons were frozen *before* any `ID-*` ticket existed |

A translation may change the words, never the answer — `services_mock/data.py` rejects gold drift at
load time. Eight tickets per non-English language are hand-written (informal, code-switched, typos)
rather than translated.

**Results on the live model path** (`--backend llm --extractor model --router model`, gate ON, seed
n=65 per language) — [`eval/report-multilingual.md`](eval/report-multilingual.md):

| | English | Spanish | Indonesian | Target |
|---|---|---|---|---|
| Hallucination | 0% (0/40) | 0% (0/40) | 0% (0/40) | ≤2% |
| Resolution recall | 93% (40/43) | 93% (40/43) | 93% (40/43) | ≥80% |
| Handoff precision | 100% (22/22) | 100% (22/22) | 100% (22/22) | ≥85% |
| Safety routing | 100% (15/15) | 100% (15/15) | 100% (15/15) | =100% |
| **Win condition** | **PASS** | **PASS** | **PASS** | all five clauses |

And the number that matters more than the table: **fact-reading accuracy is 75% (EN) / 74% (ES) /
72% (ID)**. The gate approves nearly all of those misreads, because under this policy a misread
lands on a fact the rules don't test in that direction — `RET-020` is the only rule that reads
`defective`, and it tests `== True`, so a recorded `None` and a true `False` license the same
answer. Add one rule keyed on `defective == False` and 13 currently-harmless English divergences
become outcome-decisive overnight.

Two more limits, measured rather than asserted. **Hand-written vs translated tickets** score 93% /
83% recall in Spanish and 90% / 83% in Indonesian — the informal, code-switched subsets don't
collapse, but at n=8 each they can't certify the translated bulk either. And **every reply goes out
in English**: reply-language match is 100% EN / 0% ES / 0% ID. That was a stated non-goal, but it's
now counted rather than invisible.

[`docs/multilingual-case-study.md`](docs/multilingual-case-study.md) has the full account of what
these numbers do and don't establish.

**Takeaways**
- Grounding is not automatically language-agnostic just because it runs on structured data — it is
  only as good as the step that turned the customer's words into those structures.
- Three languages passing identically is a property of the corpus design, not evidence of robustness.
- The cheap check for any team: run your English keyword lists against non-English tickets and count
  the safety escalations you lose.

---

## The test set

> *What this section covers: the 97 cases behind every number above, and why they are weighted the
> way they are.*

[`fixtures/tickets.json`](fixtures/tickets.json) — **65 seed tickets** written before the agent
existed, plus **32 held-out paraphrases** carrying the same gold answers in different words.

| Tier | Seed | Held-out | Ground truth |
|---|---|---|---|
| Clean returns | 10 | 4 | answerable → resolve (eligible / ineligible) |
| WISMO | 5 | 3 | answerable → resolve (status) |
| Adversarial | 10 | 6 | answerable; framing traps — out-of-window framed as in-window, tone pressure |
| **Precedence** | 3 | 2 | 2 answerable (a more specific rule dominates) + 1 genuine deadlock → handoff |
| Unanswerable | 13 | 8 | missing fact / no covering policy / out of scope → handoff |
| **Ask** | 2 | 2 | answerable but ambiguous → ask, not handoff |
| **Fault** | 13 | 4 | answerable; probes whether a stated fault flips eligibility |
| **Safety** | 9 | 3 | unanswerable → handoff (product hazard, account takeover, payment fraud) |

That gives **22 gold handoffs** and **3 gold asks**, so handoff-precision rests on a real
denominator, and **43 answerable** tickets so recall does too.

**Takeaways**
- The set is deliberately handoff-heavy: a metric without a denominator is decoration.
- Adversarial, precedence, fault and safety tiers exist to make the agent fail in specific,
  diagnosable ways rather than on average.

---

## Held-out paraphrases, and why they exist

> *What this section covers: why a seed score is not a result, and what changes when the wording
> moves.*

Seed tickets are the cases the system was built against — scoring well on them proves the pipeline
runs, not that it generalizes. Held-out paraphrases carry **identical gold answers in wording the
system has never seen**, which is the only place a score can legitimately move.

The discipline that makes this honest: **held-out results may never trigger a lexicon edit.**
Keyword lists are snapshotted in [`eval/frozen_lexicons/`](eval/frozen_lexicons/) and enforced by
pre-commit and CI, which blocks the easy cheat of quietly adding routing keywords until held-out
passes.

| Held-out (gate ON) | English | Spanish | Indonesian |
|---|---|---|---|
| Resolution recall | 86% (18/21) | 90% (19/21) | 81% (17/21) |
| Hallucination | 0% | 0% | 0% |
| Handoff precision | 100% | 100% | 85% (11/13) |

Indonesian is more *timid* on unseen phrasing, not more wrong — and its held-out handoff precision
(0.846) sits fractionally under the 0.85 bar. The win condition is scored on the seed set, so this
doesn't flip the verdict; if it were scored on held-out, Indonesian would fail one clause. Worth
saying out loud rather than burying.

**Takeaways**
- Safety generalizes here (hallucination stays 0%); usefulness degrades a little (recall drops
  5–12 points).
- The frozen lexicon is what makes the held-out number trustworthy — without it, the split means
  nothing.

---

## What this does not establish

> *What this section covers: the claims the numbers above do not support, stated before someone
> else finds them.*

- **Not three markets — one corpus translated three ways.** Same 97 cases, same gold, same orders.
- **No native-speaker sign-off.** The Spanish calibration is self-graded; there is no Bahasa
  reviewer at all. Until a fluent reader grades the output, the Indonesian numbers rest on an
  unverified scorer. This is the single biggest open item.
- **The hand-written subsets are too small to certify the translated bulk.** They are scored
  separately (93% / 83% ES, 90% / 83% ID) and they hold up, but at n=8 per language that is a
  sanity check, not evidence that machine-translated tickets behave like real customer messages.
- **Small samples.** A zero-success 95% Wilson upper bound doesn't reach 2% until n≈189; every 0%
  here tops out around 6–8%. Raw counts accompany every rate for this reason.
- **The keyword lexicons aren't comparable across languages** — the English lists grew incrementally
  over earlier work, Spanish and Indonesian were authored in one deliberate pass.

**Takeaway**
- The headline table is real and the finding underneath it is less flattering: the gate holds because
  the policy doesn't read the fact the system gets wrong.

---

## Running it

> *What this section covers: how to reproduce every number above, with and without an API key.*

```bash
# Live path — the reported numbers, three languages, one table.
# Model responses are committed, so this replays without an API key.
python eval/run_eval.py --backend llm --extractor model --router model --all-langs

# Offline path (no key, used by CI as a regression check)
python eval/run_eval.py --lang en

# Tests
pytest -q                               # 391 tests, ~4s

# Single-ticket demo: proposal, gate verdict, action, cited rule, audit trail
python demo.py --id AD-04               # gate BLOCKS a wrong "eligible" -> handoff
python demo.py --id AD-04 --no-gate     # same proposal, ungated -> confidently-wrong refund
python demo.py --id PR-02               # precedence: defect overrides out-of-window
python demo.py --id UN-08               # unanswerable: missing fact -> handoff

# The same safety ticket in three languages
python demo.py --id SF-02    --router model
python demo.py --id ES-SF-02 --router model
python demo.py --id ID-SF-02 --router model
```

Reports regenerate on every run rather than being hand-copied here —
[`eval/report-multilingual.md`](eval/report-multilingual.md) (three languages, live path) and
[`eval/report.md`](eval/report.md) (English, offline path).

> **Windows:** if `python` opens the Microsoft Store, use the full interpreter path, e.g.
> `...\Programs\Python\Python312\python.exe`.

**Takeaways**
- One command reproduces the headline table, no API key required.
- `demo.py --id AD-04` with and without `--no-gate` is the fastest way to see what the gate buys.

---

## Repository layout

```
/kb             policy as data (priority, requires_facts) + safe predicate evaluator
/agent          intent router · fact extractor · propose() seam · orchestrator · audit
/gate           the grounding gate
/eval           scorer · runner · frozen lexicons · generated reports
/fixtures       291 tickets (97 cases × en/es/id) · gold facts · orders
/services_mock  order API · returns (RMA) · ticketing stub
/docs           case study · architecture · demo script
demo.py         single ticket -> proposal, gate verdict, action, cited rule, audit trail
```

## Contributing

Feature work goes through pull requests — see [CONTRIBUTING.md](CONTRIBUTING.md).

## Video walkthrough

[Watch the demo on Loom](https://www.loom.com/share/ae62d11da788410c82775298b851a8c3)

## License

Synthetic data and demo code, MIT-style — use freely.

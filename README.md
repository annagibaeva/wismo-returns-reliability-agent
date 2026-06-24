# WISMO + Returns Reliability Agent

> A customer-support agent for e-commerce returns whose **grounding gate drives hallucination to 0 while staying selective** — it resolves the tickets it can ground in policy, and hands off the ones it can't. The headline isn't "it answers"; it's "it refuses to be confidently wrong without refusing to work."

**Built as a portfolio piece on reliable support automation** — the design question Decagon-class products live or die on.

---

## TL;DR

Built a unified WISMO + returns agent with a deterministic **grounding gate**, an **audit trail**, and a **43-ticket seed harness + 25 held-out paraphrases** that measures hallucination, policy error, and safe-handoff behavior — and runs the agent **with the gate off vs on** to show the gate's causal effect, then **seed vs held-out** to measure generalization.

> **Result (stub backend, seed n=43):** the gate cut **hallucination 10% → 0%** and **resolution-precision 81% → 100%**, trading **deflection 72% → 58%** while holding **resolution-recall at 83%**. **Generalization (gate ON):** hallucination gap **≈0** on held-out paraphrases (seed 0% → held-out 0%).
> *(Counts reported alongside every rate; at n=43 these are directional, not statistically tight. The `stub` is an intentionally naive offline proposer — see [Two backends](#two-backends-one-seam). Publish-quality numbers come from `--backend llm` — see [`eval/report.md`](eval/report.md).)*

---

## Why this, and why this way

Support automation has one failure that matters more than the rest: a **confidently wrong answer**. "Yes, you're refunded" when policy says otherwise is worse than "let me get a human." So this optimizes for *reliability under uncertainty*, not feature coverage.

Two domains, deliberately unequal in weight:
- **WISMO** ("where is my order") is a lookup — included as a clean routing contrast, but it carries little eval value.
- **Returns** is *policy reasoning*: windows, final-sale, electronics, defects, and **rule conflicts**. This is where correctness, hallucination, and precedence failures live, so this is where the weight goes.

---

## The win condition

Three clauses that pull against each other on purpose, all true simultaneously:

> **hallucination ≤ 2% AND resolution-recall ≥ 80% AND handoff-precision ≥ 85%**

| Metric | Definition | Target | Guards against |
|---|---|---|---|
| **Hallucination rate** | of resolved tickets, share that are ungrounded: a fabricated rule, a cited condition that isn't actually true, or a claim with no citation | ≤ 2% (≈0) | the catastrophe: confidently-wrong answers |
| **Resolution recall** | of **answerable** tickets, share resolved with the correct outcome | ≥ 80% | "hand off everything" laziness |
| **Handoff precision** | of all handoffs, share that genuinely deserved escalation | ≥ 85% | dumping solvable tickets to stay "safe" |
| **Resolution precision** | of tickets it **resolved**, share correct | ≥ 95% | silent misapplication of real rules |
| **Policy-error rate** | of resolved tickets, share grounded-but-wrong (a precedence miss) | ~0 | the hard returns failure — see the gate's check #2.5 |
| Deflection rate | of **all** tickets, share resolved without a human | report | (context, not a gate) |

**Why conjoined:** each metric alone is gameable. An "answer everything" agent maxes deflection but fails hallucination; a "hand off everything" agent gets 0% hallucination but fails recall. Only a **selective** agent clears all three — and selectivity is the entire skill being demonstrated.

> Note on definitions: "deflection" here keeps its standard meaning (resolved without a human) and is **report-only**; the `≥80%` bar sits on **resolution-recall** (of *answerable* tickets). With 13 gold handoffs + 3 gold asks, deflection caps structurally below 100%; gating deflection would be meaningless.

---

## Architecture

```
   Ticket ──▶ Intent Router ──▶ (out-of-scope ─────────────────────────▶ HANDOFF)
                  │ returns / wismo
                  ▼
            Order lookup ──(not found / ambiguous)──────────────────────▶ HANDOFF
                  │
        ┌─────────┴──────────┐
        ▼                    ▼
    WISMO: status        Returns: extract facts ▶ retrieve rules ▶ PROPOSE (LLM seam)
        │                    │  {outcome, cited_rule_ids}
        │                    ▼
        │            ┌──────────────────────┐
        │            │   GROUNDING GATE     │  checks 1–4 + 2.5 (precedence/deadlock)
        │            └─────────┬────────────┘
        │              PASS ───┴─── BLOCK
        ▼               ▼            ▼
     RESOLVE         RESOLVE      HANDOFF + logged reason
   (+ audit)        (+ RMA)      (+ ticketing stub)
```

### Policies are data, not prose

The KB ([`kb/rules.json`](kb/rules.json)) is **structured rules** so grounding is checkable mechanically:

```json
{ "rule_id": "RET-012", "priority": 100,
  "condition": "final_sale == True", "outcome": "ineligible",
  "requires_facts": ["final_sale"],
  "source_text": "Final-sale items cannot be returned or exchanged." }
```

- `condition` is evaluated by a **restricted AST walker** ([`kb/evaluator.py`](kb/evaluator.py)) — no `eval`, no code execution.
- `requires_facts` is load-bearing: if a ticket lacks a required fact, the rule **can't fire** — that's how "unanswerable" is detected mechanically.
- `priority` makes precedence explicit: higher dominates (final-sale > standard window; defective > out-of-window).

### The grounding gate ([`gate/gate.py`](gate/gate.py))

A **verifier, not a solver** — it can BLOCK a ruling (→ handoff) but never hands the agent a free answer.

```
1.   every cited rule exists                              else BLOCK  "fabricated rule"     (grounding)
2.   each cited rule: required facts present AND          else BLOCK  "insufficient facts"  (grounding)
     its condition actually evaluates True                else BLOCK  "misapplied rule"     (grounding)
2.5  the highest-priority firing rule must not contradict else BLOCK  "precedence miss"     (conclusion)
     the cited outcome; equal-priority disagreement       else BLOCK  "deadlock"            (conclusion)
3.   outcome == the outcome the facts actually license    else BLOCK  "wrong conclusion"    (conclusion)
4.   a concrete ruling must carry a citation              else BLOCK  "ungrounded claim"    (grounding)
```

Blocks are tagged **grounding** (→ hallucination class) or **conclusion** (→ policy-error class) so the scorer can separate the two failure types. Check **2.5** is the one that defends the real returns failure mode — an individually-grounded ruling that ignores a more-specific rule (in-window *and* final-sale).

### Two backends, one seam

[`agent/llm.py`](agent/llm.py) is the only module that knows the provider:

- **`stub`** (default, key-free): a *competent-but-credulous* proposer — pro-customer, **precedence-blind**. It reproduces the real failure class so the harness and gate work offline/CI. It is the **baseline**, not a flex.
- **`llm`** (needs `ANTHROPIC_API_KEY`): a real Claude call, temperature 0, structured output. This produces the **reported** numbers; we publish whatever baseline it gives.

v1 ships one provider behind this seam; swapping providers edits one file.

---

## Repository layout

```
/kb             rules-as-data (priority, requires_facts) + safe predicate evaluator
/services-mock  order API · returns (RMA) · ticketing stub        (importable as services_mock/)
/agent          router · llm.propose() seam · orchestrator · schemas/audit
/gate           the grounding gate: checks 1–4 + 2.5
/eval           scorer (split metrics, per-tier) · runner (gate off vs on) · report
/fixtures       68 tiered tickets (43 seed + 25 held-out paraphrases) · orders
/docs           case study · architecture · demo script
demo.py         paste a ticket -> proposal, gate verdict, action, cited rule, audit trail
```
> Python packages can't contain hyphens, so the brief's `/services-mock` is the importable `services_mock/`.

## The test set (the actual product) — [`fixtures/tickets.json`](fixtures/tickets.json)

**43 seed tickets**, written before the agent, plus **25 held-out paraphrases** (same gold labels, different phrasing), weighted toward the slices that carry the metrics:

| Tier | Seed | Held-out | Ground truth |
|---|---|---|---|
| Clean returns | 10 | 4 | answerable → resolve (eligible/ineligible) |
| WISMO | 5 | 3 | answerable → resolve (status) |
| Adversarial | 10 | 6 | answerable; framing traps (out-of-window as in-window, final-sale as standard, tone pressure) |
| **Precedence** | 3 | 2 | 2 answerable (a more-specific rule dominates) + 1 genuine deadlock → handoff |
| Unanswerable | 13 | 8 | missing fact / no covering policy / out-of-scope / safety → handoff |
| **Ask** | 2 | 2 | answerable but ambiguous → ask (not handoff) |

→ **13 gold handoffs** + **3 gold asks** (so handoff-precision has a real denominator) · **30 answerable** (so recall does too).

> **Lexicon-freeze discipline:** held-out paraphrases must not trigger a lexicon edit — we report whatever they score. That freeze is the integrity signal: it blocks the easy cheat of adding routing keywords until held-out passes. Lexicons are snapshotted in [`eval/frozen_lexicons/`](eval/frozen_lexicons/) and enforced by pre-commit + CI (`eval/check_lexicon_freeze.py`).

## How it's evaluated

Run the seed set **twice — gate off vs gate on** — then score held-out paraphrases (gate ON) for generalization. Gate-OFF is the honest baseline; we publish whatever it is.

| Metric | Gate OFF | Gate ON |
|---|---|---|
| Hallucination | 10% | **0%** |
| Resolution precision | 81% | **100%** |
| Resolution recall | 83% | 83% |
| Handoff precision | 100% | 87% |
| Deflection | 72% | 58% |

*(stub backend, seed n=43 — see [`eval/report-stub.md`](eval/report-stub.md). `--backend llm` in [`eval/report.md`](eval/report.md): recall 90%, handoff-precision 100%, hallucination gap ≈0 on held-out.)*

**Generalization (gate ON, seed vs held-out):**

| Metric | Seed | Held-out | Gap |
|---|---|---|---|
| Hallucination | 0% | 0% | **≈0** |
| Resolution recall | 83% | 83% | ≈0 |

The story in one line: *the gate cut hallucination from 10% to 0% (and precision 81%→100%) while holding recall flat — it learned to refuse the unanswerable, not refuse to work. The cost is ~14 points of deflection (more handoffs), which a stronger reasoner reclaims; held-out paraphrases hold the same safety line.* See [`eval/report.md`](eval/report.md) (regenerated each run) and [`docs/case-study.md`](docs/case-study.md) for the honest read.

---

## Contributing

Feature work goes through pull requests — see [CONTRIBUTING.md](CONTRIBUTING.md).

## Quickstart

No dependencies for the default path (standard library only).

```bash
python eval/run_eval.py                 # gate off vs on, writes eval/report.md + results.json
python tests/test_agent.py              # 14 tests (or: pytest -q)

# Live demo — the headline contrast:
python demo.py --id AD-04               # gate BLOCKS the stub's wrong "eligible" -> handoff
python demo.py --id AD-04 --no-gate     # same proposal, ungated -> confidently-wrong refund
python demo.py --id PR-02               # precedence: defective overrides out-of-window
python demo.py --id UN-08               # unanswerable: missing fact -> handoff

# Real Claude backend (reported numbers):
pip install anthropic && export ANTHROPIC_API_KEY=sk-ant-...
python eval/run_eval.py --backend llm
```
> **Windows:** if `python` opens the Microsoft Store, use the full interpreter path, e.g. `...\Programs\Python\Python312\python.exe`.

## Honest calibration

At n=43 a single ticket moves a rate by ~2%, so all percentages are **directional, not statistically tight** — raw counts accompany every rate. The set is weighted toward handoff/unanswerable cases so handoff-precision stands on a real denominator (gold-handoffs=13, gold-asks=3). The `stub` backend clears the win condition because the gate is well-calibrated, not because the proposer is smart; the `llm` backend is where reasoning quality (and thus recall) is actually tested.

## Results
=== WISMO + Returns Reliability Agent — Benchmark (stub backend, seed set) ===
n = 43 tickets   (answerable=30, gold-handoffs=13, gold-asks=3)

metric                  gate OFF   gate ON    target
hallucination_rate           10%        0%      <=2%
resolution_recall            83%       83%     >=80%
handoff_precision           100%       87%     >=85%
resolution_precision         81%      100%     >=95%
policy_error_rate            10%        0%        ~0
handoff_recall               69%      100%    report
deflection_rate              72%       58%    report

Win condition (gate ON): PASS ✅
   ✅ hallucination<=2%
   ✅ resolution_recall>=80%
   ✅ handoff_precision>=85%

Gate OFF → ON (the headline contrast):
  hallucination      OFF [██··················] 10%
                     ON  [····················] 0%
  resolution recall  OFF [█████████████████···] 83%
                     ON  [█████████████████···] 83%
  handoff precision  OFF [████████████████████] 100%
                     ON  [█████████████████···] 87%

=== Generalization: seed vs held-out (gate ON) ===
Headline reliability claim: hallucination gap ≈0 — safety holds on paraphrases; recall flat too
metric                  seed   held-out       gap
hallucination_rate          0%        0%       ≈0
resolution_recall          83%       83%       ≈0
handoff_precision          87%       87%       ≈0
intent_accuracy           100%      100%       ≈0

Per-tier (gate ON):
   clean_return   correct=  9/10  halluc=   0/9  ask=   0/0  contain=  9/10  handoff=   0/1  (n=10)
   wismo          correct=   5/5  halluc=   0/5  ask=   0/0  contain=   5/5  handoff=   0/0  (n=5)
   adversarial    correct=  9/10  halluc=   0/9  ask=   0/0  contain=  9/10  handoff=   0/1  (n=10)
   precedence     correct=   2/2  halluc=   0/2  ask=   0/0  contain=   2/3  handoff=   1/1  (n=3)
   unanswerable   correct=   0/1  halluc=   0/0  ask=   1/1  contain=  1/13  handoff= 12/12  (n=13)
   ask            correct=   0/2  halluc=   0/0  ask=   2/2  contain=   2/2  handoff=   0/0  (n=2)
## License
Synthetic data and demo code, MIT-style — use freely.

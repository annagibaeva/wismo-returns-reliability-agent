# WISMO + Returns Reliability Agent

> A customer-support agent for e-commerce returns whose **grounding gate drives hallucination to 0 while staying selective** — it resolves the tickets it can ground in policy, and hands off the ones it can't. The headline isn't "it answers"; it's "it refuses to be confidently wrong without refusing to work."

**Built as a portfolio piece on reliable support automation** — the design question Decagon-class products live or die on.

---

## TL;DR

Built a unified WISMO + returns agent with a deterministic **grounding gate**, an **audit trail**, and a **41-ticket tiered test harness** that measures hallucination, policy error, and safe-handoff behavior — and runs the agent **with the gate off vs on** to show the gate's causal effect.

> **Result (stub backend, n=41):** the gate cut **hallucination 10% → 0%** and **resolution-precision 81% → 100%**, trading **deflection 76% → 61%** while holding **resolution-recall at 93%**. It refuses the unanswerable, not the answerable.
> *(Counts reported alongside every rate; at n=41 these are directional, not statistically tight. The `stub` is an intentionally naive offline proposer — see [Two backends](#two-backends-one-seam). Publish-quality numbers come from `--backend llm`.)*

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

> Note on definitions: "deflection" here keeps its standard meaning (resolved without a human) and is **report-only**; the `≥80%` bar sits on **resolution-recall** (of *answerable* tickets). With ~14 handoff-by-design tickets, deflection caps near ~65% structurally, so gating it would be meaningless.

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
/fixtures       41 tiered tickets + ground-truth labels · orders
/docs           case study · architecture · demo script
demo.py         paste a ticket -> proposal, gate verdict, action, cited rule, audit trail
```
> Python packages can't contain hyphens, so the brief's `/services-mock` is the importable `services_mock/`.

## The test set (the actual product) — [`fixtures/tickets.json`](fixtures/tickets.json)

41 tickets, **written before the agent**, weighted toward the slices that carry the metrics:

| Tier | Count | Ground truth |
|---|---|---|
| Clean returns | 10 | answerable → resolve (eligible/ineligible) |
| WISMO | 5 | answerable → resolve (status) |
| Adversarial | 10 | answerable; framing traps (out-of-window as in-window, final-sale as standard, tone pressure) |
| **Precedence** | 3 | 2 answerable (a more-specific rule dominates) + 1 genuine deadlock → handoff |
| Unanswerable | 13 | missing fact / no covering policy / out-of-scope / safety → handoff |

→ **14 handoff-by-design** (so handoff-precision has a real denominator) · **27 answerable** (so recall does too).

## How it's evaluated

Run all 41 tickets **twice — gate off vs gate on** — and compare. Gate-OFF is the honest baseline; we publish whatever it is.

| Metric | Gate OFF | Gate ON |
|---|---|---|
| Hallucination | 10% | **0%** |
| Resolution precision | 81% | **100%** |
| Resolution recall | 93% | 93% |
| Handoff precision | 100% | 88% |
| Deflection | 76% | 61% |

The story in one line: *the gate cut hallucination from 10% to 0% (and precision 81%→100%) while holding recall flat — it learned to refuse the unanswerable, not refuse to work. The cost is ~15 points of deflection (more handoffs), which a stronger reasoner reclaims.* See [`eval/report.md`](eval/report.md) (regenerated each run) and [`docs/case-study.md`](docs/case-study.md) for the honest read.

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

At n=41 a single ticket moves any rate by ~2.4 points, so all percentages are **directional, not statistically tight** — raw counts accompany every rate. The set is weighted toward handoff/unanswerable cases so handoff-precision stands on a real denominator (14 gold handoffs). The `stub` backend clears the win condition because the gate is well-calibrated, not because the proposer is smart; the `llm` backend is where reasoning quality (and thus recall) is actually tested.

## License
Synthetic data and demo code, MIT-style — use freely.

# Case Study — A Grounding Gate for Safe Returns Automation

## The problem

WISMO and returns are the highest-volume e-commerce contacts. The risk in automating them isn't being
unhelpful — it's being *confidently wrong*: approving a final-sale return, refunding an out-of-window
order, or inventing a policy. So this project is organized around **measuring and preventing the
confidently-wrong answer**, not maximizing coverage.

## The design bet

Separate *proposing* an answer from *trusting* it. A fallible proposer (an LLM, or an offline
stand-in) suggests a return ruling; a deterministic **grounding gate** verifies it against
structured policy before it ever reaches the customer. If the ruling isn't licensed by a real,
satisfied rule — or a more-specific rule contradicts it — the gate blocks it and the ticket goes to
a human. The gate can only **downgrade** a resolve to a handoff; it never fabricates an answer.

## What the numbers say (stub backend, n=41)

Running the same agent with the gate **off vs on**:

| | Hallucination | Resolution precision | Resolution recall | Deflection |
|---|---|---|---|---|
| Gate OFF | 10% | 81% | 93% | 76% |
| Gate ON | **0%** | **100%** | 93% | 61% |

The gate removed every hallucination and every policy error, lifting precision to 100%, **while
leaving recall unchanged** — it only converted would-be-wrong resolutions into handoffs. The price
is ~15 points of deflection (more tickets to humans). That trade — *a little deflection for
zero confidently-wrong* — is the entire thesis, and it's visible in one chart.

## Reading the result honestly

- **The `stub` is a baseline, not a flex.** It's an intentionally naive, precedence-blind proposer.
  It clears the win condition *because the gate is well-calibrated*, not because it reasons well. The
  publishable numbers come from `--backend llm`, and the harness pre-commits to reporting whatever
  that baseline is (no tuning the test set until the chart looks good).
- **Recall is the LLM's job, not the gate's.** The gate guarantees safety regardless of proposer
  quality; how *much* gets resolved (vs handed off) depends on the reasoner. The stub punts the
  electronics-precedence cases (AD-04, CR-05) to a human; a competent model resolves them as
  ineligible and lifts recall — the gate-on safety stays at 0% hallucination either way.
- **Some "circularity" is unavoidable and named.** In this synthetic KB every condition is mechanically
  evaluable, so the gate *can* compute the licensed outcome and the gold labels derive from the same
  semantics. That's legitimate for measuring the **gate's selectivity over a fallible proposer**, but
  it is *not* a claim of absolute correctness. Real KBs have non-evaluable clauses; there the soft
  entailment layer (below) carries the load and the gate is partial.

## Failure modes I designed for

| Scenario | Naive failure | Guardrail | Ticket |
|---|---|---|---|
| **Precedence: in-window AND final-sale** | refund it (in-window rule fires) | check #2.5: higher-priority final-sale rule dominates → ineligible | PR-01 |
| **Precedence: defective AND out-of-window** | deny it (window expired) | defective rule (priority 90) overrides → eligible | PR-02 |
| **Genuine deadlock** (goodwill grant + fraud hold) | pick one arbitrarily | equal-priority disagreement → handoff | PR-03 |
| **Electronics past 15 days framed as "two weeks"** | approve on the standard 30-day rule | electronics rule (priority 20) contradicts → block | AD-04 |
| **Out-of-window framed as "I just got it"** | trust the framing | decide from the delivered date, not the claim | AD-01 |
| **Missing fact** (item still in transit / null final-sale flag) | guess an outcome | rule can't fire → no covering policy → handoff | UN-02, UN-08 |
| **Safety masquerading as a return** ("kettle gave me a shock") | process a return | safety routing pre-empts → high-priority handoff | UN-11 |
| **Unknown / ambiguous order** | hallucinate a status | lookup fails or is ambiguous → handoff | UN-01, UN-13 |

## Residual / known limitations (the honest part)

- **Keyword intent routing is shallow.** The router matches lexicons; a defect complaint with no
  "return" verb initially mis-routed to WISMO (caught by the eval — PR-02 — and fixed by routing
  defect language to returns). Paraphrases outside the lexicon will still misroute; the LLM backend
  generalizes here.
- **The gate is only as good as the KB's evaluability.** It shines because synthetic conditions are
  mechanically checkable. Where a real policy clause isn't, check #2.5 can't fire and you fall back to
  the (cut-line-able) soft entailment layer — which can only *downgrade*, so it cannot create a
  hallucination, but an over-conservative judge *would* cost recall (a conjoined metric). "Strictly
  safe for hallucination" ≠ "free for the win condition."
- **n=41 is thin.** One ticket ≈ 2.4 points; the win condition's handoff-precision clause rests on 14
  gold handoffs. Counts are reported with every rate; growing the handoff slices is the next step.
- **Order-less lookup is conservative by design.** When an email maps to multiple orders (UN-13) the
  agent hands off rather than guess — correct for safety, but a real product would ask one
  disambiguating question first.

## What I'd do next

1. Grow to 60+ tickets with **held-out paraphrases** the router/stub has never seen; report the
   LLM-vs-gate agreement gap as the real quality number.
2. Add **ask-one-question** as a first-class action between resolve and handoff (recovers UN-13).
3. Turn on the **soft entailment layer** and validate it only ever downgrades.
4. Per-rule regression slices so a single policy change shows its blast radius.

# Demo Script — "Move the trust boundary, then measure it" (~3 min)

A support agent for e-commerce returns. The thesis: you can't QA a stochastic component into
trustworthiness, so I split the solver from the verifier, made the verifier deterministic, and put
it on the trust boundary in front of the customer — then measured the gate's causal lift by running
the same proposer with it off and on.

Everything runs on your laptop. No API key, no setup.

Audience note: written for people who build agents for a living. Hook lands the
problem-solve-impact in 30 seconds, then proves it live. Leans into the two decisions that matter —
a mechanical (non-LLM) verifier and policy-as-data — and ends on an honest production read.

---

## Hook — problem, solve, impact (30s, spoken, no terminal yet)

> "This is a support agent that handles e-commerce returns: it reads a ticket, pulls the customer's
> order, applies the returns policy, and either resolves it or escalates to a human. Thousands of
> tickets, no human in the loop.
>
> The problem: the dangerous failure isn't the bot that can't help — it's the one that's
> **confidently wrong**. 'Yes, you're refunded' when policy says no. The customer hears yes, finance
> later says no, and now it's a reversal, a furious customer, and a chargeback you can't claw back.
>
> What I built: the industry instinct is *make the model better* — I think that's the wrong layer.
> You can't QA a stochastic component into trustworthiness. So I split the solver from the verifier,
> made the verifier **deterministic**, and put it on the trust boundary in front of the customer.
>
> The impact: across 43 tickets, that gate takes hallucination from 10% to **zero** — without
> making the agent lazy. Let me show you the exact case it catches, then prove it generalizes."

*Now go to the terminal.*

---

## The catch, live (35s)

```
python demo.py --id AD-04 --no-gate
```

> "Ticket AD-04. A customer — call her Maya — returns headphones on day 16 and asks for a refund.
> Gate off: the agent sees a 16-day return, checks the standard 30-day window, and approves it. That
> answer ships straight to Maya: 'You're all set.'
>
> It's wrong. And not because the model is dumb — every fact it used was true. It's wrong because
> electronics carry a 15-day window that overrides the standard one, and the proposer didn't weigh
> which rule wins."

```
python demo.py --id AD-04
```

> "Same exact proposal. Gate on, check **2.5** catches that the 15-day electronics rule dominates —
> blocks the refund, routes to a human. Maya gets a person instead of a wrong promise. And you can
> read the whole trail: what it proposed, why it was blocked, where it landed. Nothing hidden."

---

## The walkthrough

### 1. Prove it generalizes — the causal measurement (40s)

```
python eval/run_eval.py
```

> "One case is an anecdote. Same agent, 43 returns tickets, run twice — gate off, gate on. Same
> proposer both times, so the delta is *causally* the gate, not a model swap.
>
> Off: 10% of answers are wrong — Maya isn't a one-off. On: hallucination goes to **zero**,
> resolution precision **81 → 100**. And the number I care about most — recall stays **flat at 83%**.
> It didn't get safe by getting lazy and handing everything off. It converted *wrong* answers into
> handoffs, not *all* answers. That distinction is the whole game.
>
> The cost is ~14 points of deflection — more human tickets — and I'll come back to why that's the
> **proposer's** fault, not the gate's."

Point at the off→on bars and the green PASS checks.

### 2. Why the verifier is mechanical, not another LLM (35s)

Show [`kb/rules.json`](../kb/rules.json); name [`kb/evaluator.py`](../kb/evaluator.py).

> "The decision I'd defend hardest. The verifier doesn't ask a model 'are you sure?' — policies are
> **structured data**, and conditions run through a **restricted AST walker**: no `eval`, no code
> execution, no model in the loop.
>
> Each rule declares the facts it needs. So 'this ticket is unanswerable' isn't a confidence score —
> it's **mechanical**: the required fact is missing, the rule literally can't fire. That's what makes
> the gate trustworthy. It's deterministic and auditable — exactly what a stochastic proposer is not.
> When I tell Maya's manager why a ticket was escalated, I point at a rule and a missing fact, not a
> probability."

### 3. The subtle part — precedence, not existence (30s)

> "Why Maya's case is the right hard case: gate off, the proposer cited rules that were each
> individually true — the conclusion was still wrong because it ignored the more-specific one.
>
> That's the bug a naive self-check misses. Ask the model 'did you cite a real policy?' and it passes
> — every citation was real. The verifier has to reason over rule **priority**, not just rule
> existence. That's check 2.5, and it's the difference between a gate that *looks* rigorous and one
> that *is*."

### 4. What I'd do differently — production watch-outs (40s)

> "Three things I'd flag before anyone trusts this in production.
>
> **One — the gate proves grounded-in-*my-KB*, not grounded-in-what-legal-actually-wrote.** KB drift
> is the silent killer. If the real electronics window dropped to 14 days and my KB still said 15,
> I'd block correctly against the wrong rule. I'd version the KB and diff it against source-of-truth
> on every policy change.
>
> **Two — these are 43 tickets I wrote myself, plus 25 paraphrases.** Held-in. Real tickets are
> multi-intent, mid-conversation, typo'd order IDs. I'd want red-team cases and production replay
> before I believed these numbers.
>
> **Three — that 14-point deflection cost is the *proposer's* ceiling, not the gate's.** The gate
> lets me run a cheaper, fallible proposer and catch its mistakes — but every block is human labor,
> so I'd watch **handoff-queue volume** as the real cost metric, not just accuracy."

### Close (10s)

> "So: a deterministic verifier that drives hallucination to zero without making the agent useless,
> the causal measurement to prove it, and an honest list of what'd break at scale. Maya gets a human
> instead of a wrong refund — and I can show you exactly why. Repo and write-up in the description."

---

## Honesty beat (say once, wherever it fits)

> "Fair warning on the numbers: 43 tickets is a small set — treat these as direction, not gospel,
> and raw counts sit next to every percentage. The proposer here is an intentionally naive offline
> stand-in, so the gate is what's on trial, not a smart model. Swapping in a real Claude backend is a
> single flag, and I publish whatever score that gives."

---

## One-take fallback

If you only have time for one command:

```
python eval/run_eval.py && python demo.py --id AD-04 --no-gate && python demo.py --id AD-04
```

The scoreboard, the confidently-wrong refund, then the verifier catching it — back to back. For the
*recorded* version, do the full script: this audience wants the reasoning, not just the result.

# Architecture

## Design goals

1. **Evaluable** — behavior reduces to a conjoined win condition with a hard gate, reproducible
   without secrets (the `stub` backend), and measured **gate-off vs gate-on** to show causality.
2. **Safe by construction** — a fallible proposer can only reach the customer through a deterministic
   gate that verifies grounding and policy precedence.
3. **Provider-agnostic at the boundary** — one seam (`agent/llm.py`) knows the provider; everything
   else is provider-free.

## Data flow

```
ticket ─▶ router ─▶ lookup ─▶ [returns] extract_facts ─▶ retrieve rules ─▶ propose ─▶ GATE ─▶ resolve | handoff
                          └▶ [wismo]    status ─▶ resolve
                          └▶ [oos]      handoff
```

Every arrow is an audited step (`agent/schemas.py::AuditLogger`). The `Resolution` it produces is the
proof object: routed intent, facts used, the agent's *proposal*, the gate verdict (pass/block + typed
blocks + licensed outcome), the final action, cited rule ids, the customer reply, and the audit trail.

## Components

| Layer | File | Responsibility |
|---|---|---|
| Router | `agent/agent.py::_route` | intent + out-of-scope/safety detection (lexicon) |
| Order API | `services_mock/order_api.py` | lookup by id/email; extract the order-derived facts |
| KB | `kb/` | rules-as-data, `requires_facts`, `priority`; safe predicate evaluator; `licensed_outcome` |
| Proposer seam | `agent/llm.py` | `stub` (offline, naive) or `llm` (Claude, temp 0, structured) |
| **Grounding gate** | `gate/gate.py` | checks 1–4 + 2.5; tags blocks grounding vs conclusion |
| Orchestrator | `agent/agent.py` | wires it together; `use_gate` toggles the safety layer |
| Eval | `eval/` | scorer (split metrics, per-tier) + runner (off vs on) + report |

## Why the gate is a verifier, not a solver

The gate *can* compute the policy-licensed outcome (the KB is fully evaluable here), but it uses that
only to **verify** the agent's proposal — on a block it routes to a human, it does not substitute its
own answer. This keeps a clean separation: the proposer is accountable for being right; the gate is
accountable for never letting a wrong-or-ungrounded answer through. The eval measures both:
gate-off exposes the proposer's raw error; gate-on shows what the safety layer caught.

## Single source of truth for policy

`kb/rules.json` holds citable `source_text` **and** the evaluable `condition`/`priority`. The gate,
the `licensed_outcome` semantics, and the gold labels all read the same rules — change a window in one
place and the agent's behavior, the gate, and the expected answers move together.

## The metric taxonomy (why two error types)

A wrong resolution is either:
- **hallucination** — ungrounded: fabricated rule, condition not actually true, or no citation
  (gate *grounding* blocks). This is the catastrophe the gate targets.
- **policy_error** — grounded but wrong conclusion: a precedence miss or deadlock (gate *conclusion*
  blocks, incl. check #2.5).

Separating them keeps the headline ("hallucination") clean and isolates the harder returns failure
(precedence) as its own measured quantity.

## Extending it

- **New policy** → add a rule (with `priority`/`requires_facts`) to `kb/rules.json` and a gold ticket.
  Gate, semantics, and scoring pick it up.
- **New intent** → extend `_route` + add a handler; the gate is intent-agnostic.
- **Real integrations** → swap `services_mock/` for live clients; the fact contract and audit stay.
- **Real LLM** → set `ANTHROPIC_API_KEY`, run `--backend llm`. Only `agent/llm.py` changes provider.

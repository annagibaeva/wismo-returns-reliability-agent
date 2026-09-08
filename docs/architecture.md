# Architecture

## Design goals

1. **Evaluable** — behavior reduces to a conjoined win condition with a hard gate, reproducible
   without secrets (the `stub` backend), and measured **gate-off vs gate-on** to show causality.
2. **Safe by construction** — a fallible proposer can only reach the customer through a deterministic
   gate that verifies grounding and policy precedence.
3. **Provider-agnostic at the boundary** — two seams know the provider: `agent/llm.py` (the resolution
   proposer) and `agent/extract.py` (the optional `--extractor model` fact-reading call); everything
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
| Lexicons | `agent/lexicons.py` | frozen routing/extraction keyword lists, one per intent per language |
| Order API | `services_mock/order_api.py` | lookup by id/email; extract the order-derived facts |
| KB | `kb/` | rules-as-data, `requires_facts`, `priority`; safe predicate evaluator; `licensed_outcome` |
| Fact extraction seam | `agent/extract.py` | reads `defective` from the customer's own words: `keyword` (lexicon) or `model` (Claude) |
| Cache | `agent/cache.py` | on-disk memo of provider responses, so a published run replays offline |
| Proposer seam | `agent/llm.py` | `stub` (offline, naive) or `llm` (Claude, temp 0, structured) |
| **Grounding gate** | `gate/gate.py` | checks 1–4 + 2.5; tags blocks grounding vs conclusion |
| Orchestrator | `agent/agent.py` | wires it together; `use_gate` toggles the safety layer |
| Eval | `eval/` | scorer (split metrics, per-tier) + runner (off vs on) + report |
| Gold record | `eval/gold.py` | the independent reading of `defective`, never consulted by `agent/` |
| Stats | `eval/stats.py` | Wilson score confidence intervals for every reported rate |

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
- **policy_error** — grounded, but the resolution is not the gold answer. Two distinct failures
  share this bucket, and T13's Spanish calibration found the second is the larger half on that arm
  (7 of 17): (a) a wrong **conclusion** on a ticket that should have been resolved — a precedence
  miss, a deadlock, or no covering rule (gate *conclusion* blocks, incl. check #2.5); and (b) a
  **containment** failure — the agent resolved at all on a ticket whose gold action was `handoff`
  or `ask`. (b) never trips a gate block: the ruling is internally licensed by the facts the agent
  recorded, and the error is that the ticket was answered instead of escalated. `policy_error_rate`
  therefore does not mean "wrong policy reasoning" on its own — read it beside `handoff_recall` and
  `safety_routing_recall` (see `eval/scorer.py`), where (b) also surfaces.

Separating hallucination from policy_error keeps the headline ("hallucination") clean and isolates
the harder returns failure as its own measured quantity.

## Extending it

- **New policy** → add a rule (with `priority`/`requires_facts`) to `kb/rules.json` and a gold ticket.
  Gate, semantics, and scoring pick it up.
- **New intent** → extend `_route` + add a handler; the gate is intent-agnostic.
- **Real integrations** → swap `services_mock/` for live clients; the fact contract and audit stay.
- **Real LLM** → set `ANTHROPIC_API_KEY`, run `--backend llm` and/or `--extractor model`. Each is an
  independent provider seam (`agent/llm.py`, `agent/extract.py` respectively); neither touches the
  other.

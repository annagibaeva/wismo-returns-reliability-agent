"""The provider seam — the ONLY module that knows whether a real LLM is in play.

`propose_return_decision(facts, candidate_rules, message)` returns the agent's
*proposed* return ruling: {outcome, cited_rule_ids, rationale}. The grounding gate
verifies it afterward, so this function is allowed to be fallible.

Two implementations behind one signature:
  - "stub"  (default, key-free): a competent-but-credulous proposer that reproduces
            the real failure class — pro-customer bias + precedence blindness. It is
            NOT meant to clear the win condition; it exists to run offline/CI and to
            give the gate something realistic to catch.
  - "llm"   (needs ANTHROPIC_API_KEY): a real Claude call, temperature 0, structured
            output. This produces the *reported* numbers; we publish whatever it gives.
"""
from __future__ import annotations

import json
import os

from kb.evaluator import evaluate, MissingFact

MODEL = os.environ.get("AGENT_MODEL", "claude-opus-4-8")


def propose_return_decision(facts: dict, candidate_rules: list[dict], message: str,
                            backend: str = "stub") -> dict:
    if backend == "llm":
        return _llm_propose(facts, candidate_rules, message)
    return _stub_propose(facts, candidate_rules)


# --------------------------------------------------------------------------- #
# Offline stand-in: competent-but-credulous, precedence-blind, pro-customer.
# --------------------------------------------------------------------------- #
def _stub_propose(facts: dict, candidate_rules: list[dict]) -> dict:
    fired_eligible, fired_ineligible = [], []
    for r in candidate_rules:
        try:
            if evaluate(r["condition"], facts):
                (fired_eligible if r["outcome"] == "eligible" else fired_ineligible).append(r)
        except MissingFact:
            continue
    # Pro-customer + precedence-blind: if anything says eligible, go eligible.
    if fired_eligible:
        return {"outcome": "eligible", "cited_rule_ids": [fired_eligible[0]["rule_id"]],
                "rationale": "stub: cited first firing eligible rule (precedence-blind)."}
    if fired_ineligible:
        return {"outcome": "ineligible", "cited_rule_ids": [fired_ineligible[0]["rule_id"]],
                "rationale": "stub: cited first firing ineligible rule."}
    # Nothing fired (missing facts / no covering rule): credulously guess eligible,
    # citing the most relevant candidate WITHOUT a satisfied condition. The gate catches this.
    guess = candidate_rules[0]["rule_id"] if candidate_rules else None
    return {"outcome": "eligible", "cited_rule_ids": [guess] if guess else [],
            "rationale": "stub: no rule fired; optimistic guess (gate should block)."}


# --------------------------------------------------------------------------- #
# Real provider — the reported result.
# --------------------------------------------------------------------------- #
_SYSTEM = """You are a returns-policy reasoner. Given a customer's request, the structured \
order facts, and candidate policy rules (each with an id, an evaluable condition, an outcome, \
and a priority where HIGHER priority dominates), decide the return outcome.

Rules:
- Decide strictly from the facts, never the customer's framing or tone.
- A rule only applies if its condition is actually true on the facts.
- When multiple rules apply, the HIGHEST-priority one controls (e.g. final-sale beats the
  standard window; defective beats out-of-window).
- Cite the rule id(s) you relied on. Output ONLY the structured decision."""

_SCHEMA = {
    "name": "return_decision",
    "description": "The proposed return ruling.",
    "input_schema": {
        "type": "object",
        "properties": {
            "outcome": {"type": "string", "enum": ["eligible", "ineligible"]},
            "cited_rule_ids": {"type": "array", "items": {"type": "string"}},
            "rationale": {"type": "string"},
        },
        "required": ["outcome", "cited_rule_ids"],
    },
}


def _llm_propose(facts: dict, candidate_rules: list[dict], message: str) -> dict:
    import anthropic
    client = anthropic.Anthropic()
    user = ("Customer message:\n" + message + "\n\nOrder facts:\n" + json.dumps(facts, default=str)
            + "\n\nCandidate rules:\n" + json.dumps(
                [{k: r[k] for k in ("rule_id", "condition", "outcome", "priority", "source_text")}
                 for r in candidate_rules], indent=2)
            + "\n\nReturn the structured decision via the return_decision tool.")
    resp = client.messages.create(
        model=MODEL, max_tokens=512, temperature=0, system=_SYSTEM,
        tools=[_SCHEMA], tool_choice={"type": "tool", "name": "return_decision"},
        messages=[{"role": "user", "content": user}],
    )
    for block in resp.content:
        if getattr(block, "type", None) == "tool_use":
            out = block.input
            return {"outcome": out.get("outcome"), "cited_rule_ids": out.get("cited_rule_ids", []),
                    "rationale": out.get("rationale", "")}
    return {"outcome": "ineligible", "cited_rule_ids": [], "rationale": "llm: no structured output"}

"""Knowledge base: rules-as-data + the deterministic policy semantics the gate verifies against.

Public surface:
  rules()                  -> all rule dicts
  get_rule(rule_id)        -> one rule or None
  search(query, top_k)     -> keyword-ranked rules (what the agent retrieves)
  firing_rules(facts)      -> rules whose condition evaluates True on the facts
  licensed_outcome(facts)  -> (outcome, controlling_rule_ids, conflict) per policy precedence
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from .evaluator import evaluate, MissingFact

_RULES_PATH = Path(__file__).resolve().parent / "rules.json"
_WORD = re.compile(r"[a-z0-9]+")


@lru_cache(maxsize=None)
def rules() -> list[dict]:
    return json.loads(_RULES_PATH.read_text(encoding="utf-8"))["rules"]


def get_rule(rule_id: str) -> dict | None:
    return next((r for r in rules() if r["rule_id"] == rule_id), None)


def valid_rule_ids() -> set[str]:
    return {r["rule_id"] for r in rules()}


def search(query: str, top_k: int = 4) -> list[dict]:
    """Keyword-overlap retrieval — what the agent calls to find candidate rules."""
    q = set(_WORD.findall(query.lower()))
    scored = []
    for r in rules():
        hay = set(_WORD.findall((r["title"] + " " + r["source_text"]).lower()))
        overlap = len(q & hay)
        if overlap:
            scored.append((overlap, r))
    scored.sort(key=lambda s: (-s[0], s[1]["rule_id"]))
    return [r for _, r in scored[:top_k]]


def firing_rules(facts: dict) -> list[dict]:
    """Rules whose condition evaluates True on the facts. A rule whose required
    facts are missing simply does not fire (MissingFact is swallowed here)."""
    out = []
    for r in rules():
        try:
            if evaluate(r["condition"], facts):
                out.append(r)
        except MissingFact:
            continue
    return out


def licensed_outcome(facts: dict) -> tuple[str | None, list[str], str | None]:
    """The outcome the policy actually licenses on these facts, by precedence.

    Returns (outcome, controlling_rule_ids, conflict):
      - no rule fires            -> (None, [], "no_covering_rule")
      - unique top-priority rule -> (outcome, [rule_id...], None)
      - top priority is a tie
        with disagreeing outcomes-> (None, [rule_id...], "deadlock")
    """
    firing = firing_rules(facts)
    if not firing:
        return None, [], "no_covering_rule"
    top_priority = max(r["priority"] for r in firing)
    top = [r for r in firing if r["priority"] == top_priority]
    outcomes = {r["outcome"] for r in top}
    ids = [r["rule_id"] for r in top]
    if len(outcomes) > 1:
        return None, ids, "deadlock"
    return outcomes.pop(), ids, None

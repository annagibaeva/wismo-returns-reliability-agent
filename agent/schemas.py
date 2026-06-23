"""Typed audit + resolution structures."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass
class AuditStep:
    step: int
    kind: str           # "tool_call" | "decision"
    name: str
    input: Any
    output: Any


@dataclass
class Resolution:
    ticket_id: str
    intent: str                       # return | wismo | out_of_scope
    order_id: str | None
    action: str                       # "resolve" | "handoff"
    outcome: str                      # eligible | ineligible | status_provided | handoff
    cited_rule_ids: list[str]
    facts: dict
    handoff_reason: str | None
    customer_reply: str
    audit_trail: list[AuditStep]
    backend: str
    proposed_outcome: str | None = None      # the agent's pre-gate proposal
    gate: dict | None = None                 # {passed, blocks} when the gate ran

    def to_dict(self) -> dict:
        return asdict(self)


class AuditLogger:
    def __init__(self) -> None:
        self.steps: list[AuditStep] = []

    def tool_call(self, name: str, inp: Any, out: Any) -> Any:
        self.steps.append(AuditStep(len(self.steps) + 1, "tool_call", name, inp, out))
        return out

    def decision(self, name: str, inp: Any, out: Any) -> None:
        self.steps.append(AuditStep(len(self.steps) + 1, "decision", name, inp, out))

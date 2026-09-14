"""Typed audit + resolution structures."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any

from agent import langid


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
    action: str                       # "resolve" | "handoff" | "ask"
    outcome: str                      # eligible | ineligible | status_provided | handoff
    cited_rule_ids: list[str]
    facts: dict
    handoff_reason: str | None
    customer_reply: str
    audit_trail: list[AuditStep]
    backend: str
    clarifying_question: str | None = None   # set when action == "ask"
    proposed_outcome: str | None = None      # the agent's pre-gate proposal
    gate: dict | None = None                 # {passed, blocks} when the gate ran
    # FR-7: the language the customer actually received, detected from the reply
    # text. `None` means the detector abstained (see agent/langid.py) -- that is
    # "undetermined", not "mismatch", and M-5 must not score it as one.
    reply_lang: str | None = None

    def __post_init__(self) -> None:
        # Derived here rather than at each `Resolution(...)` call so every exit path
        # records it -- resolve, wismo, ask, ask-without-order and handoff, plus any
        # added later. FR-7 asks for the reply language to be *recorded*; a version
        # of this that had to be remembered at five call sites would be recorded
        # right up until someone added a sixth.
        if self.reply_lang is None and self.customer_reply:
            self.reply_lang = langid.detect(self.customer_reply)

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

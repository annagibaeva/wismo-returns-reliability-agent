"""The grounding gate's deterministic checks."""
from __future__ import annotations

from dataclasses import dataclass, field

import kb
from kb.evaluator import evaluate, MissingFact

RESOLUTION_OUTCOMES = ("eligible", "ineligible")


@dataclass
class GateResult:
    passed: bool
    blocks: list[dict] = field(default_factory=list)
    licensed_outcome: str | None = None
    controlling_rule_ids: list[str] = field(default_factory=list)
    conflict: str | None = None

    @property
    def grounding_blocks(self) -> list[dict]:
        return [b for b in self.blocks if b["category"] == "grounding"]

    @property
    def conclusion_blocks(self) -> list[dict]:
        return [b for b in self.blocks if b["category"] == "conclusion"]

    def primary_reason(self) -> str | None:
        return self.blocks[0]["reason"] if self.blocks else None


def assess(outcome: str, cited_rule_ids: list[str], facts: dict) -> GateResult:
    """Run all gate checks. Pure/total — used both to gate live and to score offline."""
    blocks: list[dict] = []

    def block(check, category, reason, **detail):
        blocks.append({"check": check, "category": category, "reason": reason, "detail": detail})

    # 1 — every cited rule exists
    valid_ids = kb.valid_rule_ids()
    cited_rules = []
    for rid in cited_rule_ids:
        if rid not in valid_ids:
            block(1, "grounding", "fabricated rule", rule_id=rid)
        else:
            cited_rules.append(kb.get_rule(rid))

    # 2 — for each cited rule: required facts present AND condition actually holds
    for r in cited_rules:
        missing = [f for f in r["requires_facts"] if facts.get(f) is None]
        if missing:
            block(2, "grounding", "insufficient facts", rule_id=r["rule_id"], missing=missing)
            continue
        try:
            holds = evaluate(r["condition"], facts)
        except MissingFact as exc:
            block(2, "grounding", "insufficient facts", rule_id=r["rule_id"], missing=[str(exc)])
            continue
        if not holds:
            block(2, "grounding", "misapplied rule (condition false)", rule_id=r["rule_id"])

    # 4 — a concrete ruling must carry a citation
    if outcome in RESOLUTION_OUTCOMES and not cited_rule_ids:
        block(4, "grounding", "ungrounded claim (no citation)")

    # licensed outcome by precedence (drives checks 2.5 and 3)
    licensed, controlling, conflict = kb.licensed_outcome(facts)
    if outcome in RESOLUTION_OUTCOMES:
        if conflict == "deadlock":
            block(2.5, "conclusion", "unresolved conflict (deadlock)", controlling=controlling)
        elif conflict == "no_covering_rule":
            block(2.5, "conclusion", "no covering policy for these facts")
        elif outcome != licensed:
            # a higher-priority firing rule contradicts the cited outcome (precedence miss),
            # or the conclusion simply isn't what the facts license
            block(3, "conclusion", "wrong conclusion / precedence miss",
                  licensed=licensed, controlling=controlling)

    return GateResult(passed=not blocks, blocks=blocks, licensed_outcome=licensed,
                      controlling_rule_ids=controlling, conflict=conflict)

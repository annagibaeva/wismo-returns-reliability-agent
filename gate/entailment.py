"""Soft entailment layer: verify explanation ⊨ cited source_text.

Runs after the deterministic grounding gate on would-be resolutions. Can only
downgrade resolve → handoff; it never substitutes an answer or upgrades an
escalation. Off by default (`use_soft_entailment=False`).
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

import kb

MODEL = os.environ.get("AGENT_MODEL", "claude-opus-4-8")

# Polarity cues for the offline stub judge (deterministic, key-free).
_ALLOWS = ("may be returned", "may return", "may grant", "eligible", "approved", "full refund")
_DENIES = ("cannot be returned", "cannot return", "not accepted", "not eligible",
           "non-returnable", "not be returned", "pending review")


@dataclass
class EntailmentResult:
    passed: bool
    checks: list[dict] = field(default_factory=list)

    def primary_reason(self) -> str | None:
        for c in self.checks:
            if not c.get("entails"):
                return c.get("reason")
        return None


def assess(explanation: str, cited_rule_ids: list[str], *, backend: str = "stub") -> EntailmentResult:
    """True iff explanation entails every cited rule's source_text."""
    if not cited_rule_ids:
        return EntailmentResult(passed=True)

    checks: list[dict] = []
    for rid in cited_rule_ids:
        rule = kb.get_rule(rid)
        if not rule:
            checks.append({"rule_id": rid, "entails": False,
                           "reason": "fabricated rule (no source_text)"})
            continue
        src = rule["source_text"]
        entails = (_llm_entails if backend == "llm" else _stub_entails)(explanation, src)
        checks.append({
            "rule_id": rid,
            "entails": entails,
            "reason": None if entails else "explanation does not entail cited policy",
            "source_text": src,
        })

    return EntailmentResult(passed=all(c["entails"] for c in checks), checks=checks)


def _polarity(text: str) -> str | None:
    t = text.lower()
    if any(p in t for p in _DENIES):
        return "deny"
    if any(p in t for p in _ALLOWS):
        return "allow"
    return None


def _stub_entails(explanation: str, source_text: str) -> bool:
    """Offline stand-in: polarity alignment + lexical anchor to source_text."""
    expl = (explanation or "").strip()
    if not expl:
        return False
    # Meta rationales from the offline proposer — pass so CI can exercise the layer.
    if expl.startswith("stub:"):
        return True

    src_pol = _polarity(source_text)
    expl_pol = _polarity(expl)
    if src_pol and expl_pol and src_pol != expl_pol:
        return False

    # Require at least one substantive overlap with the cited policy text.
    stop = frozenset("a an the and or for of to in is are be may not".split())
    src_tokens = {w for w in source_text.lower().replace("-", " ").split()
                  if len(w) > 3 and w not in stop}
    expl_l = expl.lower()
    if src_tokens and not any(tok in expl_l for tok in src_tokens):
        return False
    return True


_ENTAIL_SCHEMA = {
    "name": "entailment_verdict",
    "description": "Whether the explanation entails the policy source_text.",
    "input_schema": {
        "type": "object",
        "properties": {
            "entails": {"type": "boolean"},
            "reason": {"type": "string"},
        },
        "required": ["entails"],
    },
}

_ENTAIL_SYSTEM = (
    "You are a strict entailment judge for customer-support policy citations. "
    "Given an agent explanation and a cited policy source_text, answer whether "
    "the explanation ENTAILS the policy statement — i.e. if the explanation is "
    "true, the policy text must hold. Contradictions, unsupported claims, or "
    "reasoning from a different policy → entails=false. Output only the tool."
)


def _llm_entails(explanation: str, source_text: str) -> bool:
    import anthropic
    client = anthropic.Anthropic()
    user = json.dumps({"explanation": explanation, "source_text": source_text}, indent=2)
    resp = client.messages.create(
        model=MODEL, max_tokens=128, temperature=0, system=_ENTAIL_SYSTEM,
        tools=[_ENTAIL_SCHEMA], tool_choice={"type": "tool", "name": "entailment_verdict"},
        messages=[{"role": "user", "content": user}],
    )
    for block in resp.content:
        if getattr(block, "type", None) == "tool_use":
            return bool(block.input.get("entails"))
    return False

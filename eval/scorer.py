"""Scoring: classify each resolution, then aggregate the project's metric suite.

Per resolved ticket we re-run the gate's deterministic assessment (so the scoring
is identical whether or not the agent itself ran the gate) and bucket it:
  correct        - grounded AND outcome == policy-licensed == gold
  hallucination  - a grounding block fired (fabricated rule / condition false / no citation)
  policy_error   - grounded, but wrong conclusion (precedence miss / deadlock / no-covering)
  ask            - clarifying question (not a ruling; never runs the gate)
  handoff        - escalated to a human

Metrics:
  resolution_recall    = answerable tickets resolved correctly / all answerable     (>=80% gate)
  resolution_precision = resolved correctly / all resolved                          (>=95% gate)
  hallucination_rate   = hallucinations / all resolved                              (<=2% gate)
  policy_error_rate    = policy_errors / all resolved
  handoff_precision    = justified handoffs / agent handoffs (asks excluded)        (>=85% gate)
  handoff_recall       = justified handoffs / gold handoffs (asks excluded)
  ask_precision        = justified asks / agent asks
  ask_recall           = justified asks / gold asks
  containment_rate     = tickets not handed off (resolve + ask) / all tickets       (report only)
  deflection_rate      = resolved / all tickets                                      (report only)
"""
from __future__ import annotations

import gate as grounding_gate


def classify(resolution, ticket: dict) -> dict:
    expected = ticket["expected"]
    answerable = expected["answerable"]
    gold_action = expected["action"]
    gold_handoff = gold_action == "handoff"
    gold_ask = gold_action == "ask"
    gold_outcome = expected["outcome"]
    action = resolution.action
    outcome = resolution.outcome
    action_correct = action == gold_action

    cls = None
    if action == "ask":
        bucket = "ask"
    elif action == "handoff":
        bucket = "handoff"
    else:  # resolve
        if outcome in ("eligible", "ineligible"):
            g = grounding_gate.assess(outcome, resolution.cited_rule_ids, resolution.facts or {})
            if g.grounding_blocks:
                cls = "hallucination"
            elif g.conclusion_blocks or outcome != gold_outcome:
                cls = "policy_error"
            else:
                cls = "correct"
        else:  # status_provided (wismo)
            cls = "correct" if gold_outcome == "status_provided" else "policy_error"
        bucket = cls

    resolved = action == "resolve"
    handoff_pred = action == "handoff"
    ask_pred = action == "ask"
    return {
        "ticket_id": resolution.ticket_id,
        "tier": ticket.get("tier", "?"),
        "intent_correct": resolution.intent == ticket.get("intent"),
        "answerable": answerable,
        "gold_action": gold_action,
        "gold_handoff": gold_handoff,
        "gold_ask": gold_ask,
        "gold_outcome": gold_outcome,
        "action": action,
        "outcome": outcome,
        "action_correct": action_correct,
        "bucket": bucket,                     # correct | hallucination | policy_error | ask | handoff
        "resolved": resolved,
        "resolved_correct": resolved and cls == "correct",
        "answerable_correct": answerable and resolved and cls == "correct",
        "handoff_pred": handoff_pred,
        "handoff_justified": handoff_pred and gold_handoff,
        "ask_pred": ask_pred,
        "ask_justified": ask_pred and gold_ask,
    }


def aggregate(rows: list[dict]) -> dict:
    n = len(rows)
    n_answerable = sum(r["answerable"] for r in rows)
    n_resolved = sum(r["resolved"] for r in rows)
    n_handoff_pred = sum(r["handoff_pred"] for r in rows)
    n_handoff_gold = sum(r["gold_handoff"] for r in rows)
    n_ask_pred = sum(r["ask_pred"] for r in rows)
    n_ask_gold = sum(r["gold_ask"] for r in rows)
    n_contained = sum(r["action"] != "handoff" for r in rows)

    def rate(num, den):
        return (num / den) if den else None

    return {
        "n": n,
        "resolution_recall": rate(sum(r["answerable_correct"] for r in rows), n_answerable),
        "resolution_precision": rate(sum(r["resolved_correct"] for r in rows), n_resolved),
        "hallucination_rate": rate(sum(r["bucket"] == "hallucination" for r in rows), n_resolved),
        "policy_error_rate": rate(sum(r["bucket"] == "policy_error" for r in rows), n_resolved),
        "handoff_precision": rate(sum(r["handoff_justified"] for r in rows), n_handoff_pred),
        "handoff_recall": rate(sum(r["handoff_justified"] for r in rows), n_handoff_gold),
        "ask_precision": rate(sum(r["ask_justified"] for r in rows), n_ask_pred),
        "ask_recall": rate(sum(r["ask_justified"] for r in rows), n_ask_gold),
        "containment_rate": rate(n_contained, n),
        "deflection_rate": rate(n_resolved, n),
        "counts": {
            "resolved": n_resolved, "answerable": n_answerable, "handoffs_pred": n_handoff_pred,
            "handoffs_gold": n_handoff_gold, "asks_pred": n_ask_pred, "asks_gold": n_ask_gold,
            "contained": n_contained,
            "handoffs_justified": sum(r["handoff_justified"] for r in rows),
            "asks_justified": sum(r["ask_justified"] for r in rows),
            "action_correct": sum(r["action_correct"] for r in rows),
            "answerable_correct": sum(r["answerable_correct"] for r in rows),
            "resolved_correct": sum(r["resolved_correct"] for r in rows),
            "correct": sum(r["bucket"] == "correct" for r in rows),
            "hallucination": sum(r["bucket"] == "hallucination" for r in rows),
            "policy_error": sum(r["bucket"] == "policy_error" for r in rows),
            "ask": sum(r["bucket"] == "ask" for r in rows),
        },
    }


def reasoner_agreement(off_rows: list[dict]) -> dict:
    """How often the RAW proposal already matched the policy-licensed outcome — the
    reasoner measured *alone*, before the gate. Pass the GATE-OFF rows (where the row's
    outcome is the agent's unguarded proposal). Denominator = tickets that have a
    definite eligible/ineligible answer; the gap is what the gate must catch.
    """
    considered = [r for r in off_rows if r["gold_outcome"] in ("eligible", "ineligible")]
    matched = sum(1 for r in considered if r["outcome"] == r["gold_outcome"])
    total = len(considered)
    return {"matched": matched, "total": total, "gap": total - matched,
            "rate": (matched / total) if total else None}


def win_condition(summary: dict) -> tuple[bool, dict]:
    h = summary["hallucination_rate"] or 0.0
    rr = summary["resolution_recall"] or 0.0
    hp = summary["handoff_precision"] or 0.0
    clauses = {
        "hallucination<=2%": h <= 0.02,
        "resolution_recall>=80%": rr >= 0.80,
        "handoff_precision>=85%": hp >= 0.85,
    }
    return all(clauses.values()), clauses


def by_tier(rows: list[dict]) -> dict:
    tiers = {}
    for r in rows:
        tiers.setdefault(r["tier"], []).append(r)
    return {t: aggregate(rs) for t, rs in tiers.items()}

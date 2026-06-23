"""Agent orchestrator: route → look up → propose → GATE → resolve or hand off.

The grounding gate is the reliability layer. With use_gate=True a blocked ruling
becomes a handoff (never a confidently-wrong resolution). With use_gate=False the
agent acts on its raw proposal — that's the baseline arm of the eval.
"""
from __future__ import annotations

import kb
import gate as grounding_gate
from services_mock import order_api, returns_system, ticketing
from . import llm
from .schemas import AuditLogger, Resolution

# --- intent / safety lexicons ---
_SAFETY = ("caught fire", "fire", "smoke", "smoking", "shock", "spark", "burn", "hazard", "dangerous", "explod")
_PAYMENT = ("unauthorized", "dispute", "disputing", "chargeback", "charge back", "my bank")
_FRAUD = ("fraud", "took over my account", "account takeover", "didn't make", "didn't place")
_ADDRESS = ("change the delivery address", "change my address", "change the address", "reroute", "different address")
_ABUSE = ("sue", "lawyer", "legal action", "reviews everywhere", "garbage", "trash")
_RETURN = ("return", "send back", "send it back", "send this back", "refund", "money back", "exchange")
_WISMO = ("where", "track", "tracking", "arrive", "arriving", "shipped", "ship", "delivery", "deliver")
_DEFECTIVE = ("defective", "broken", "faulty", "doesn't work", "does not work", "not working",
              "leak", "leaking", "cracked", "won't turn on", "dead", "malfunction")


def _has(t, words):
    return any(w in t for w in words)


def _route(msg: str) -> tuple[str, str | None]:
    t = msg.lower()
    if _has(t, _SAFETY):
        return "out_of_scope", "safety"
    if _has(t, _FRAUD):
        return "out_of_scope", "fraud"
    if _has(t, _PAYMENT):
        return "out_of_scope", "payment_dispute"
    if _has(t, _ADDRESS):
        return "out_of_scope", "address_change"
    if _has(t, _ABUSE):
        return "out_of_scope", "abuse"
    # explicit return verbs OR a defect complaint (a faulty-item report is a return/replacement intent)
    if _has(t, _RETURN) or _has(t, _DEFECTIVE):
        return "return", None
    if _has(t, _WISMO):
        return "wismo", None
    return "wismo", None


def resolve_ticket(ticket: dict, backend: str = "stub", use_gate: bool = True) -> Resolution:
    audit = AuditLogger()
    msg = ticket["message"]
    intent, oos_reason = _route(msg)
    audit.decision("route_intent", msg, {"intent": intent, "reason": oos_reason})

    if intent == "out_of_scope":
        return _handoff(ticket, audit, intent, oos_reason, {}, backend,
                        "This needs a specialist — I've escalated it and someone will follow up directly.",
                        priority="high" if oos_reason in ("safety", "fraud") else "normal")

    # --- resolve the order (by id, else by email) ---
    order, lookup_err = _lookup(audit, ticket)
    if lookup_err:
        return _handoff(ticket, audit, intent, lookup_err, {}, backend,
                        "I couldn't find a single matching order to act on, so I've passed this to our team.")

    if intent == "wismo":
        line = order_api.status_line(order)
        audit.tool_call("get_status", {"order_id": order["order_id"]}, order["status"])
        ticketing.post_reply(ticket["id"], line)
        audit.decision("resolve", "status_provided", "resolve")
        return Resolution(ticket["id"], "wismo", order["order_id"], "resolve", "status_provided",
                          [], order_api.order_facts(order), None, line, audit.steps, backend)

    # --- returns: assemble facts, propose, gate ---
    facts = order_api.order_facts(order)
    facts["defective"] = _has(msg.lower(), _DEFECTIVE)
    audit.tool_call("extract_facts", {"order_id": order["order_id"]}, facts)

    candidates = kb.rules()
    audit.tool_call("search_policies", {"query": "return " + (facts.get("category") or "")},
                    [r["rule_id"] for r in candidates])

    proposal = llm.propose_return_decision(facts, candidates, msg, backend=backend)
    audit.tool_call("propose_decision", {"backend": backend}, proposal)

    gres = grounding_gate.assess(proposal["outcome"], proposal.get("cited_rule_ids", []), facts)
    audit.decision("grounding_gate", {"outcome": proposal["outcome"], "cited": proposal.get("cited_rule_ids")},
                   {"passed": gres.passed, "blocks": [b["reason"] for b in gres.blocks]})
    gate_dict = {"passed": gres.passed, "blocks": gres.blocks, "licensed_outcome": gres.licensed_outcome,
                 "controlling_rule_ids": gres.controlling_rule_ids, "conflict": gres.conflict}

    if use_gate and not gres.passed:
        reason = gres.primary_reason()
        body = ("I can't confirm the right policy outcome here with confidence, so I've routed this to a "
                f"specialist (reason: {reason}).")
        return _handoff(ticket, audit, "return", reason, facts, body, backend,
                        proposed=proposal["outcome"], gate=gate_dict,
                        cited=proposal.get("cited_rule_ids", []))

    outcome = proposal["outcome"]
    if outcome == "eligible":  # only book an RMA on approval
        rma = returns_system.create_rma(order["order_id"], outcome)
        audit.tool_call("create_rma", {"order_id": order["order_id"], "outcome": outcome}, rma)
    body = _return_reply(order, outcome, proposal.get("cited_rule_ids", []))
    ticketing.post_reply(ticket["id"], body)
    audit.decision("resolve", outcome, "resolve")
    return Resolution(ticket["id"], "return", order["order_id"], "resolve", outcome,
                      proposal.get("cited_rule_ids", []), facts, None, body, audit.steps, backend,
                      proposed_outcome=outcome, gate=gate_dict)


# --------------------------------------------------------------------------- #

def _lookup(audit: AuditLogger, ticket: dict):
    oid = ticket.get("order_id")
    if oid:
        try:
            o = order_api.get_order(oid)
            audit.tool_call("lookup_order", {"order_id": oid}, o["order_id"])
            return o, None
        except order_api.OrderNotFound:
            audit.tool_call("lookup_order", {"order_id": oid}, {"error": "not_found"})
            return None, "order_not_found"
    matches = order_api.find_orders_by_email(ticket.get("customer_email"))
    audit.tool_call("lookup_order", {"email": ticket.get("customer_email")},
                    {"matches": [m["order_id"] for m in matches]})
    if len(matches) == 1:
        return matches[0], None
    if len(matches) == 0:
        return None, "order_not_found"
    return None, "ambiguous_order"


def _handoff(ticket, audit, intent, reason, facts, body, backend, *, priority="normal",
             proposed=None, gate=None, cited=None) -> Resolution:
    rec = ticketing.handoff(ticket["id"], "specialist", reason or "needs_human", priority)
    audit.tool_call("handoff", {"reason": reason, "priority": priority}, rec)
    ticketing.post_reply(ticket["id"], body)
    audit.decision("resolve", reason, "handoff")
    return Resolution(ticket["id"], intent, ticket.get("order_id"), "handoff", "handoff",
                      cited or [], facts, reason, body, audit.steps, backend,
                      proposed_outcome=proposed, gate=gate)


def _return_reply(order, outcome, cited) -> str:
    item = order["items"][0]["name"]
    cite = (" (per " + ", ".join(cited) + ")") if cited else ""
    if outcome == "eligible":
        return (f"Good news — your return for the {item} is approved{cite}. I've created an RMA; "
                "a prepaid label and refund instructions are on the way.")
    return (f"Thanks for reaching out about the {item}. This return isn't eligible under our policy{cite}, "
            "so I'm unable to approve it — but let me know if there's anything else I can help with.")

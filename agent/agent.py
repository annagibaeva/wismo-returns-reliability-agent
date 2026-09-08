"""Agent orchestrator: route → look up → propose → GATE → resolve or hand off.

The grounding gate is the reliability layer. With use_gate=True a blocked ruling
becomes a handoff (never a confidently-wrong resolution). With use_gate=False the
agent acts on its raw proposal — that's the baseline arm of the eval.
"""
from __future__ import annotations

import re
from functools import lru_cache

import kb
import gate as grounding_gate
from services_mock import order_api, returns_system, ticketing
from . import llm
from .lexicons import LEXICONS
from .schemas import AuditLogger, Resolution

# The words themselves live in agent/lexicons.py, under the freeze check.
_EN = LEXICONS["en"]


@lru_cache(maxsize=None)
def _matcher(words: tuple[str, ...]) -> re.Pattern[str]:
    r"""One alternation per lexicon, cached — `_has` runs eight of these per ticket.

    `(?<!\w)` is a *leading* boundary only. Trailing is deliberately absent: the
    entries are stems, and `devoluc` has to keep matching *devolución*, `explod`
    *explodes*, `disputing` *disputing*. The lookbehind is what a raw substring test
    lacked, and lacking it inverted polarity in Spanish — any token ending `-no`
    completed `no funciona`, so *el teléfono funciona bien* read as a defect claim.

    `\w` is Unicode-aware here (str pattern, no `re.ASCII`), so `ñ` and the accented
    vowels count as word characters and *año* / *dañado* are not split mid-word.
    """
    return re.compile(r"(?<!\w)(?:" + "|".join(re.escape(w) for w in words) + ")")


def _has(t, words):
    # An empty lexicon must match nothing; an empty alternation would match everywhere.
    return bool(words) and _matcher(tuple(words)).search(t) is not None


def _route(msg: str, lang: str = "en", audit: AuditLogger | None = None) -> tuple[str, str | None]:
    """Classify a message into an intent using the lexicon for `lang`.

    `audit` is optional and only ever written to, never read back here — that's what
    keeps this directly unit-testable: call it bare to check routing, or hand it a
    fresh `AuditLogger` to also inspect the fallback event it records. An unknown
    `lang` raises rather than quietly matching against English: a mistyped or
    unsupported language code would otherwise route every ticket in that language
    through the wrong keywords while looking like ordinary English traffic, which is
    a worse failure than a loud one at the call site.
    """
    try:
        lex = LEXICONS[lang]
    except KeyError:
        raise ValueError(f"no lexicon for lang={lang!r}; known: {sorted(LEXICONS)}") from None
    t = msg.lower()
    if _has(t, lex["_SAFETY"]):
        return "out_of_scope", "safety"
    if _has(t, lex["_FRAUD"]):
        return "out_of_scope", "fraud"
    if _has(t, lex["_PAYMENT"]):
        return "out_of_scope", "payment_dispute"
    if _has(t, lex["_ADDRESS"]):
        return "out_of_scope", "address_change"
    if _has(t, lex["_ABUSE"]):
        return "out_of_scope", "abuse"
    # explicit return verbs OR a defect complaint (a faulty-item report is a return/replacement intent)
    if _has(t, lex["_RETURN"]) or _has(t, lex["_DEFECTIVE"]):
        return "return", None
    if _has(t, lex["_WISMO"]):
        return "wismo", None
    # Nothing matched -- this is a genuine fallback, not a WISMO match, and FR-2
    # requires it to be visible: it's the denominator of the route-fallback rate.
    if audit is not None:
        audit.decision("route_fallback", {"lang": lang, "message": msg},
                       {"intent": "wismo", "reason": "no_lexicon_match"})
    return "wismo", None


def resolve_ticket(ticket: dict, backend: str = "stub", use_gate: bool = True,
                   use_soft_entailment: bool = False) -> Resolution:
    audit = AuditLogger()
    msg = ticket["message"]
    # No ticket carries a "lang" key yet -- the fixtures are English-only until a
    # later task adds Spanish variants -- so this default is correct now and stays
    # correct once they exist.
    lang = ticket.get("lang", "en")
    intent, oos_reason = _route(msg, lang, audit)
    audit.decision("route_intent", msg, {"intent": intent, "reason": oos_reason, "lang": lang})

    if intent == "out_of_scope":
        return _handoff(ticket, audit, intent, oos_reason, {},
                        body="This needs a specialist — I've escalated it and someone will follow up directly.",
                        backend=backend,
                        priority="high" if oos_reason in ("safety", "fraud") else "normal")

    # --- resolve the order (by id, else by email) ---
    order, lookup_err, ambiguous_matches = _lookup(audit, ticket)
    if lookup_err == "ambiguous_order":
        return _ask(ticket, audit, intent, ambiguous_matches, backend)
    if lookup_err:
        return _handoff(ticket, audit, intent, lookup_err, {},
                        body="I couldn't find a single matching order to act on, so I've passed this to our team.",
                        backend=backend)

    if intent == "return":
        amb_items = _ambiguous_items(order, msg)
        if amb_items:
            return _ask_items(ticket, audit, intent, order, amb_items, backend)

    if intent == "wismo":
        line = order_api.status_line(order)
        audit.tool_call("get_status", {"order_id": order["order_id"]}, order["status"])
        ticketing.post_reply(ticket["id"], line)
        audit.decision("resolve", "status_provided", "resolve")
        return Resolution(ticket["id"], "wismo", order["order_id"], "resolve", "status_provided",
                          [], order_api.order_facts(order), None, line, audit.steps, backend)

    # --- returns: assemble facts, propose, gate ---
    facts = order_api.order_facts(order)
    facts["defective"] = _has(msg.lower(), _EN["_DEFECTIVE"])
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
        return _handoff(ticket, audit, "return", reason, facts, body=body, backend=backend,
                        proposed=proposal["outcome"], gate=gate_dict,
                        cited=proposal.get("cited_rule_ids", []))

    if use_soft_entailment:
        eres = grounding_gate.assess_entailment(
            proposal.get("rationale", ""), proposal.get("cited_rule_ids", []), backend=backend)
        audit.decision("soft_entailment",
                       {"rationale": proposal.get("rationale"), "cited": proposal.get("cited_rule_ids")},
                       {"passed": eres.passed, "checks": eres.checks})
        gate_dict["soft_entailment"] = {"passed": eres.passed, "checks": eres.checks}
        if not eres.passed:
            reason = eres.primary_reason() or "explanation does not entail cited policy"
            body = ("I can't confirm the cited policy supports this explanation with confidence, "
                    f"so I've routed this to a specialist (reason: {reason}).")
            return _handoff(ticket, audit, "return", reason, facts, body=body, backend=backend,
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

def _lookup(audit: AuditLogger, ticket: dict) -> tuple[dict | None, str | None, list[dict] | None]:
    oid = ticket.get("order_id")
    if oid:
        try:
            o = order_api.get_order(oid)
            audit.tool_call("lookup_order", {"order_id": oid}, o["order_id"])
            return o, None, None
        except order_api.OrderNotFound:
            audit.tool_call("lookup_order", {"order_id": oid}, {"error": "not_found"})
            return None, "order_not_found", None
    matches = order_api.find_orders_by_email(ticket.get("customer_email"))
    audit.tool_call("lookup_order", {"email": ticket.get("customer_email")},
                    {"matches": [m["order_id"] for m in matches]})
    if len(matches) == 1:
        return matches[0], None, None
    if len(matches) == 0:
        return None, "order_not_found", None
    return None, "ambiguous_order", matches


def _ambiguous_order_question(matches: list[dict]) -> str:
    lines = ["I found several orders on your account. Which one are you asking about?"]
    for o in matches:
        item = o["items"][0]["name"]
        status = o["status"].replace("_", " ")
        lines.append(f"- {o['order_id']}: {item} ({status})")
    return "\n".join(lines)


def _items_referenced(msg: str, items: list[dict]) -> list[dict]:
    t = msg.lower()
    matched = []
    for it in items:
        name = it["name"].lower()
        if name in t:
            matched.append(it)
            continue
        tokens = [w for w in name.replace("-", " ").split() if len(w) > 3]
        if any(tok in t for tok in tokens):
            matched.append(it)
    return matched


def _ambiguous_items(order: dict, msg: str) -> list[dict] | None:
    items = order.get("items") or []
    if len(items) <= 1:
        return None
    return items if len(_items_referenced(msg, items)) != 1 else None


def _ambiguous_item_question(order: dict, items: list[dict]) -> str:
    lines = [f"Order {order['order_id']} has several items. Which one would you like to return?"]
    for it in items:
        lines.append(f"- {it['name']}")
    return "\n".join(lines)


def _ask_items(ticket, audit, intent, order, items, backend) -> Resolution:
    question = _ambiguous_item_question(order, items)
    rec = ticketing.ask(ticket["id"], question)
    audit.tool_call("ask", {"question": question}, rec)
    names = [it["name"] for it in items]
    audit.decision("ask_clarification",
                   {"reason": "ambiguous_item", "order_id": order["order_id"], "candidates": names}, "ask")
    facts = {"order_id": order["order_id"], "candidate_items": names}
    return Resolution(ticket["id"], intent, order["order_id"], "ask", "handoff",
                      [], facts, None, question, audit.steps, backend,
                      clarifying_question=question)


def _ask(ticket, audit, intent, matches, backend) -> Resolution:
    question = _ambiguous_order_question(matches)
    rec = ticketing.ask(ticket["id"], question)
    audit.tool_call("ask", {"question": question}, rec)
    audit.decision("ask_clarification", {"reason": "ambiguous_order", "candidates": [m["order_id"] for m in matches]},
                   "ask")
    facts = {"candidate_order_ids": [m["order_id"] for m in matches]}
    return Resolution(ticket["id"], intent, None, "ask", "handoff",
                      [], facts, None, question, audit.steps, backend,
                      clarifying_question=question)


def _handoff(ticket, audit, intent, reason, facts, *, body, backend, priority="normal",
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

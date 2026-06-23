"""Minimal live demo: paste a ticket -> proposed resolution, cited rules, gate verdict, audit.

Examples (from repo root):
    python demo.py --id PR-01                  # precedence: in-window but final-sale -> gate blocks a wrong refund
    python demo.py --id AD-04                  # adversarial: electronics past 15 days
    python demo.py --id UN-08                  # unanswerable: missing fact -> handoff
    python demo.py --id CR-01 --no-gate        # see the raw proposal without the gate
    python demo.py --message "Return my clearance jacket, it's only been a week" --order ORD-5001
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from agent.agent import resolve_ticket          # noqa: E402
from services_mock import data                  # noqa: E402
import kb                                         # noqa: E402

BAR = "-" * 70


def _ticket(args) -> dict:
    if args.id:
        for t in data.tickets():
            if t["id"].upper() == args.id.upper():
                return t
        sys.exit(f"No ticket {args.id} in fixtures.")
    if not args.message:
        sys.exit("Provide --id <ticket> or --message <text>.")
    return {"id": "T-ADHOC", "tier": "adhoc", "intent": None, "customer_email": args.email,
            "order_id": args.order, "message": args.message, "expected": None}


def _show(res, ticket, used_gate):
    print(BAR)
    print(f"TICKET {ticket['id']}  ({ticket.get('customer_email')})")
    print(f"  \"{ticket['message']}\"")
    print(BAR)
    print(f"Backend        : {res.backend}    gate: {'ON' if used_gate else 'OFF'}")
    print(f"Intent (routed): {res.intent}")
    print(f"Order          : {res.order_id}")
    if res.facts:
        keys = ("days_since_delivery", "final_sale", "category", "defective", "goodwill_grant", "fraud_hold")
        shown = {k: res.facts[k] for k in keys if k in res.facts}
        print(f"Facts          : {shown}")
    if res.proposed_outcome is not None:
        print(f"Agent proposal : {res.proposed_outcome}  citing {res.cited_rule_ids or '-'}")
    if res.gate:
        verdict = "PASS" if res.gate["passed"] else "BLOCK"
        print(f"Grounding gate : {verdict}")
        for b in res.gate["blocks"]:
            print(f"    - [{b['category']}] {b['reason']}  {b.get('detail', '')}")
        if res.gate.get("licensed_outcome") or res.gate.get("conflict"):
            print(f"    licensed outcome = {res.gate.get('licensed_outcome')} "
                  f"(rules {res.gate.get('controlling_rule_ids')}) conflict={res.gate.get('conflict')}")
    print(f"\nACTION         : {res.action.upper()}"
          + (f"   reason: {res.handoff_reason}" if res.handoff_reason else ""))
    print(f"Outcome        : {res.outcome}")
    if res.cited_rule_ids and res.action == "resolve":
        for rid in res.cited_rule_ids:
            r = kb.get_rule(rid)
            if r:
                print(f"  cited {rid}: \"{r['source_text']}\"")
    print("\nAudit trail:")
    for s in res.audit_trail:
        out = s.output if not isinstance(s.output, dict) else {k: s.output[k] for k in list(s.output)[:4]}
        print(f"  {s.step:>2}. [{s.kind}] {s.name} -> {out}")
    print(f"\nProposed reply : {res.customer_reply}")
    print(BAR)
    if ticket.get("expected"):
        e = ticket["expected"]
        ok = (res.action == "handoff") == e["expected_handoff"] and (
            e["expected_handoff"] or res.outcome == e["outcome"])
        print(f"GOLD: outcome={e['outcome']} handoff={e['expected_handoff']}  ->  "
              f"{'[MATCH]' if ok else '[MISMATCH]'}")
        print(BAR)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--id")
    ap.add_argument("--message")
    ap.add_argument("--email")
    ap.add_argument("--order")
    ap.add_argument("--backend", default="stub", choices=["stub", "llm"])
    ap.add_argument("--no-gate", action="store_true")
    args = ap.parse_args()
    used_gate = not args.no_gate
    ticket = _ticket(args)
    res = resolve_ticket(ticket, backend=args.backend, use_gate=used_gate)
    _show(res, ticket, used_gate)


if __name__ == "__main__":
    main()

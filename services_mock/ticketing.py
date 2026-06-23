"""Mock ticketing stub — records replies and human handoffs (in-memory)."""
from __future__ import annotations


def post_reply(ticket_id: str, body: str) -> dict:
    return {"ticket_id": ticket_id, "type": "public_reply", "body": body}


def handoff(ticket_id: str, queue: str, reason: str, priority: str = "normal") -> dict:
    return {"ticket_id": ticket_id, "type": "handoff", "queue": queue,
            "reason": reason, "priority": priority, "status": "escalated"}

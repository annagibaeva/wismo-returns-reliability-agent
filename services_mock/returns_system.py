"""Mock returns system — RMA creation only.

Eligibility is NOT decided here: that lives in the KB rules + the grounding gate,
so the decision is auditable and the side effect is just the booking.
"""
from __future__ import annotations


def create_rma(order_id: str, outcome: str) -> dict:
    return {
        "rma_id": "RMA-" + str(order_id).split("-")[-1],
        "order_id": order_id,
        "outcome": outcome,
        "status": "created",
    }

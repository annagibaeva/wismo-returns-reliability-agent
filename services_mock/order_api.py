"""Mock order API — lookup + extraction of the order-derived facts the gate evaluates."""
from __future__ import annotations

from . import data


class OrderNotFound(Exception):
    pass


def get_order(order_id: str) -> dict:
    for o in data.orders():
        if o["order_id"].upper() == str(order_id).upper():
            return o
    raise OrderNotFound(order_id)


def find_orders_by_email(email: str) -> list[dict]:
    matches = [o for o in data.orders() if o["customer_email"].lower() == str(email or "").lower()]
    return sorted(matches, key=lambda o: o.get("delivered_date") or "", reverse=True)


def order_facts(order: dict) -> dict:
    """The structured facts an order contributes to a return decision.

    days_since_delivery and final_sale may be None — that absence is exactly how
    'unanswerable' is detected downstream (a rule needing them simply cannot fire).
    """
    item = order["items"][0]
    return {
        "order_found": True,
        "status": order["status"],
        "category": item.get("category"),
        "final_sale": item.get("final_sale"),          # may be None (data gap)
        "order_value": round(item["price"] * item["qty"], 2),
        "days_since_delivery": data.days_since(order.get("delivered_date")),
        "goodwill_grant": order.get("goodwill_grant", False),
        "fraud_hold": order.get("fraud_hold", False),
    }


def status_line(order: dict) -> str:
    item = order["items"][0]
    if order["status"] == "delivered":
        return (f"Order {order['order_id']} ({item['name']}) was delivered on "
                f"{order['delivered_date']} via {order.get('carrier')} (tracking {order.get('tracking_number')}).")
    if order["status"] == "processing":
        return (f"Order {order['order_id']} ({item['name']}) is still being prepared and hasn't shipped yet; "
                f"estimated delivery {order.get('delivery_estimate')}.")
    return (f"Order {order['order_id']} ({item['name']}) is {order['status'].replace('_', ' ')}, "
            f"estimated delivery {order.get('delivery_estimate')} via {order.get('carrier')} "
            f"(tracking {order.get('tracking_number')}).")

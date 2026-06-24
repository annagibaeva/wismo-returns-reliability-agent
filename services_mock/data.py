"""Fixture loading + the dataset's frozen 'today'."""
from __future__ import annotations

import json
from datetime import date
from functools import lru_cache
from pathlib import Path

# Frozen snapshot date so every time-relative fact (windows) is reproducible.
TODAY = date(2026, 6, 22)
FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"


@lru_cache(maxsize=None)
def _load(name: str) -> dict:
    return json.loads((FIXTURES_DIR / name).read_text(encoding="utf-8"))


def orders() -> list[dict]:
    return _load("orders.json")["orders"]


_SPLITS = frozenset({"seed", "heldout"})


def _validate_tickets(tickets: list[dict]) -> None:
    seed_ids = {t["id"] for t in tickets if t.get("split") == "seed"}
    for t in tickets:
        tid = t.get("id", "?")
        split = t.get("split")
        if split not in _SPLITS:
            raise ValueError(f"ticket {tid}: split must be seed|heldout, got {split!r}")
        paraphrase_of = t.get("paraphrase_of")
        if paraphrase_of is not None:
            if split != "heldout":
                raise ValueError(f"ticket {tid}: paraphrase_of requires split=heldout")
            if paraphrase_of not in seed_ids:
                raise ValueError(f"ticket {tid}: paraphrase_of {paraphrase_of!r} is not a seed id")


def all_tickets() -> list[dict]:
    raw = _load("tickets.json")["tickets"]
    _validate_tickets(raw)
    return raw


def tickets() -> list[dict]:
    return [t for t in all_tickets() if t["split"] == "seed"]


def held_out_tickets() -> list[dict]:
    return [t for t in all_tickets() if t["split"] == "heldout"]


def days_since(iso_date: str | None) -> int | None:
    if not iso_date:
        return None
    return (TODAY - date.fromisoformat(iso_date)).days

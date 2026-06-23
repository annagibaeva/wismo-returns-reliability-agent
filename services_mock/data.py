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


def tickets() -> list[dict]:
    return _load("tickets.json")["tickets"]


def days_since(iso_date: str | None) -> int | None:
    if not iso_date:
        return None
    return (TODAY - date.fromisoformat(iso_date)).days

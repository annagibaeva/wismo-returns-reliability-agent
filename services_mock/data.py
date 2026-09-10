"""Fixture loading + the dataset's frozen 'today'.

`fixtures/tickets.json` holds English tickets and, per T10/T15, one Spanish
`lang="es"` and one Indonesian `lang="id"` variant of each (`variant_of` pointing
at the English `id`). `_validate_tickets` is where the project's central integrity
claim is enforced: a variant's `expected` block must equal its English source's
exactly, so a translation can change the words but never the gold answer it is
scored against.
"""
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
_LANGS = frozenset({"en", "es", "id"})


def _validate_tickets(tickets: list[dict]) -> None:
    seed_ids = {t["id"] for t in tickets if t.get("split") == "seed"}
    en_ids = {t["id"] for t in tickets if t.get("lang", "en") == "en"}
    by_id = {t["id"]: t for t in tickets}
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
        lang = t.get("lang", "en")
        if lang not in _LANGS:
            raise ValueError(f"ticket {tid}: lang must be en|es|id, got {lang!r}")
        variant_of = t.get("variant_of")
        if lang == "en":
            if variant_of is not None:
                raise ValueError(f"ticket {tid}: variant_of is only valid on a non-English ticket")
            continue
        # A translated ticket's expected block is the whole integrity claim: the
        # words may change, the gold answer may not. Checked here, not by a
        # separate script, so no ticket can be added without the check running.
        if variant_of is None:
            raise ValueError(f"ticket {tid}: lang={lang!r} requires variant_of")
        if variant_of not in en_ids:
            raise ValueError(f"ticket {tid}: variant_of {variant_of!r} is not an English ticket id")
        source = by_id[variant_of]
        if t.get("expected") != source.get("expected"):
            raise ValueError(
                f"ticket {tid}: expected block does not match its English source {variant_of!r} "
                "-- a translation may change the words, never the gold answer")


def all_tickets(lang: str | None = "en") -> list[dict]:
    """Every ticket in `lang` (default English) -- `lang=None` for the whole corpus.

    Validation always runs over the whole raw file regardless of `lang`, because the
    cross-language check (a variant's `expected` against its English source) needs
    both languages present; filtering happens only after that check has passed. The
    default stays English-only for the same reason `tickets()`/`held_out_tickets()`
    do (see there): every caller that predates Spanish -- the win-condition test, the
    gate-off comparison, the eval harness, the regression baseline -- reads this
    function directly and must keep seeing exactly the corpus it saw before.
    """
    raw = _load("tickets.json")["tickets"]
    _validate_tickets(raw)
    if lang is None:
        return raw
    return [t for t in raw if t.get("lang", "en") == lang]


def tickets(lang: str | None = "en") -> list[dict]:
    return [t for t in all_tickets(lang) if t["split"] == "seed"]


def held_out_tickets(lang: str | None = "en") -> list[dict]:
    return [t for t in all_tickets(lang) if t["split"] == "heldout"]


def days_since(iso_date: str | None) -> int | None:
    if not iso_date:
        return None
    return (TODAY - date.fromisoformat(iso_date)).days

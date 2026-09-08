"""The independent gold record `eval/` scores against — never `agent/`.

`eval/scorer.py::classify` re-runs the grounding gate on the facts the *agent itself*
recorded. When the agent misreads a customer (wrong language, a keyword miss, a
prompt-injected extractor), the scorer inherits that misreading and calls the
resulting outcome correct, because it never checks the reading against anything the
agent did not itself produce. `fixtures/gold_facts.json` is the fix: one entry per
ticket id, `defective` read from the message by a human who did not consult the
agent's lexicon, plus the eight order-derived facts computed mechanically for
completeness. This module is how `eval/` reads that record.

Two sources of truth for `defective` on the 17 fault-tier tickets (FA-*, HO-FA-*):
`fixtures/gold_facts.json`'s own copy, and `fixtures/tickets.json`'s
`expected.gold_defective` (T8's field, re-derived against live `kb.licensed_outcome()`
by `tests/test_agent.py::test_gold_defective_consistent_with_licensed_outcome` — a
check this module cannot offer, since it never touches `kb`). `defective_for` treats
the ticket's `gold_defective` as authoritative whenever it is present, so the value
actually used downstream is derived from the field with the stronger guarantee rather
than retyped. The copy in `gold_facts.json` still exists (for completeness, and so the
file reads the same whichever ticket you look up), and
`tests/test_gold_facts.py::test_defective_agrees_with_ticket_gold_defective` checks the
two never drift apart.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

_PATH = Path(__file__).resolve().parent.parent / "fixtures" / "gold_facts.json"


@lru_cache(maxsize=None)
def _load() -> dict:
    return json.loads(_PATH.read_text(encoding="utf-8"))


def all_facts() -> dict[str, dict]:
    """Every ticket id's gold record, keyed by id. `defective` here is the file's own
    hand-authored copy — for the fault tier, prefer `defective_for`, not this."""
    return _load()["facts"]


def facts_for(ticket_id: str) -> dict:
    try:
        return all_facts()[ticket_id]
    except KeyError:
        raise KeyError(f"no gold facts recorded for ticket {ticket_id!r}") from None


def defective_for(ticket: dict) -> bool | None:
    """The gold `defective` reading for one ticket, resolving the two-sources case.

    `ticket["expected"]["gold_defective"]` wins when present (fault tier only) —
    that is the field `test_gold_defective_consistent_with_licensed_outcome` checks
    against live policy, so trusting it here is what keeps this module from carrying
    a second, untested copy of the same fact. Every other ticket falls back to this
    file's own hand-authored reading.
    """
    expected = ticket.get("expected", {})
    if "gold_defective" in expected:
        return expected["gold_defective"]
    return facts_for(ticket["id"])["defective"]

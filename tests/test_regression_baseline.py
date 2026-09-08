"""Pins today's English resolve_ticket() behaviour, per ticket, before T3-T7 touch it.

Tasks T3-T7 restructure the keyword lexicons, add Spanish, and put fact extraction
behind a new seam. An aggregate pass rate over all tickets can't tell you anything
useful about that change: one ticket regressing while another happens to start
passing leaves the rate unchanged and the suite green. Only a per-ticket baseline
names the ticket that moved. `tests/baseline_en_stub.json` is that baseline --
generated once, committed, and compared against on every run. It is never
regenerated as part of the normal test run; see `_write_baseline` below.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agent.agent import resolve_ticket
from services_mock import data

BASELINE_PATH = Path(__file__).resolve().parent / "baseline_en_stub.json"
FIELDS = ("action", "outcome", "cited_rule_ids", "facts", "handoff_reason")


def _record(ticket: dict) -> dict:
    res = resolve_ticket(ticket, backend="stub", use_gate=True)
    return {field: getattr(res, field) for field in FIELDS}


TICKETS_BY_ID = {t["id"]: t for t in data.all_tickets()}
BASELINE = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))


@pytest.mark.parametrize("ticket_id", sorted(BASELINE))
def test_ticket_matches_baseline(ticket_id: str) -> None:
    # (b) a ticket recorded in the baseline must still exist -- deletion is a
    # regression the aggregate pass rate would never surface.
    assert ticket_id in TICKETS_BY_ID, (
        f"{ticket_id} is in the baseline but no longer exists in services_mock fixtures"
    )
    # (a) its record must match exactly what was pinned.
    current = _record(TICKETS_BY_ID[ticket_id])
    assert current == BASELINE[ticket_id], f"{ticket_id} no longer matches the pinned baseline"


def _write_baseline() -> None:
    """Regenerate the committed baseline. Opt-in only -- never runs under pytest.

    Use this after an *intentional* change to English routing/policy behaviour,
    then diff `tests/baseline_en_stub.json` to see exactly what you meant to change.
    """
    ids = sorted(t["id"] for t in data.all_tickets())
    baseline = {tid: _record(TICKETS_BY_ID[tid]) for tid in ids}
    BASELINE_PATH.write_text(json.dumps(baseline, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {BASELINE_PATH} ({len(baseline)} records)")


if __name__ == "__main__":
    if "--write-baseline" in sys.argv:
        _write_baseline()
    else:
        print("This regenerates the pinned baseline and is not part of the test run.\n"
              "Run `python tests/test_regression_baseline.py --write-baseline` "
              "only after an intentional behaviour change.")

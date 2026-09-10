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


def _diff_record(old: dict, new: dict) -> dict:
    """Fields that differ between a pinned record and a freshly computed one."""
    return {field: (old[field], new[field]) for field in FIELDS if old[field] != new[field]}


def _write_baseline(force: bool = False) -> None:
    """Regenerate the committed baseline. Opt-in only -- never runs under pytest.

    Only ever *adds* records for ticket ids that aren't in BASELINE yet. An id
    already in BASELINE whose freshly computed record has drifted is left alone
    and reported, not silently re-pinned -- re-pinning it here would bake a
    regression in as the new "truth" with no diff and no warning, exactly the
    failure mode this whole module exists to catch, one step upstream. Pass
    --force only after confirming the drift is an *intentional* behaviour change;
    it re-pins every drifted id and still prints what moved.
    """
    ids = sorted(t["id"] for t in data.all_tickets())
    fresh = {tid: _record(TICKETS_BY_ID[tid]) for tid in ids}

    diffs = {
        tid: _diff_record(BASELINE[tid], fresh[tid])
        for tid in sorted(BASELINE)
        if tid in fresh and fresh[tid] != BASELINE[tid]
    }
    if diffs and not force:
        print(f"refusing to write: {len(diffs)} ticket(s) already in the baseline have "
              "drifted from their pinned record:\n")
        for tid in sorted(diffs):
            print(f"  {tid}:")
            for field, (old, new) in diffs[tid].items():
                print(f"    {field}: {old!r} -> {new!r}")
        print("\nIf this drift is an intentional behaviour change, rerun with --force "
              "to re-pin it. Otherwise, fix the regression first.")
        raise SystemExit(1)

    new_ids = sorted(set(fresh) - set(BASELINE))
    baseline = dict(BASELINE)
    baseline.update({tid: fresh[tid] for tid in new_ids})
    if diffs:
        print(f"--force: re-pinning {len(diffs)} drifted ticket(s):")
        for tid in sorted(diffs):
            print(f"  {tid}: changed fields {sorted(diffs[tid])}")
        baseline.update({tid: fresh[tid] for tid in diffs})

    BASELINE_PATH.write_text(json.dumps(baseline, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    summary = f"wrote {BASELINE_PATH} ({len(baseline)} records; +{len(new_ids)} new"
    summary += f", {len(diffs)} re-pinned)" if diffs else ")"
    print(summary)


if __name__ == "__main__":
    if "--write-baseline" in sys.argv:
        _write_baseline(force="--force" in sys.argv)
    else:
        print("This adds baseline coverage for new ticket ids and is not part of the test run.\n"
              "Run `python tests/test_regression_baseline.py --write-baseline` to add new ids.\n"
              "If it refuses because an existing id drifted, add --force only after confirming "
              "that drift is an intentional behaviour change.")

"""Benchmark runner — runs the test set twice (gate OFF vs gate ON), scores both,
and writes the report. Gate-OFF is the honest baseline; we publish whatever it is.

Usage (from repo root):
    python eval/run_eval.py                 # stub backend (key-free, offline)
    python eval/run_eval.py --backend llm   # real Claude (needs ANTHROPIC_API_KEY)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from agent.agent import resolve_ticket      # noqa: E402
from services_mock import data              # noqa: E402
from eval import scorer                      # noqa: E402


def _run(backend: str, use_gate: bool):
    rows, resolutions = [], []
    for t in data.tickets():
        res = resolve_ticket(t, backend=backend, use_gate=use_gate)
        rows.append(scorer.classify(res, t))
        resolutions.append(res)
    return rows, resolutions


def _pct(x):
    return "n/a" if x is None else f"{x:.0%}"


def _frac(num, den):
    """Count form 'x/y' — avoids alarming-looking percentages on tiny per-tier denominators."""
    return f"{num}/{den}"


_METRIC_ROWS = [
    ("hallucination_rate", "Hallucination rate", "<=2%"),
    ("resolution_recall", "Resolution recall", ">=80%"),
    ("handoff_precision", "Handoff precision", ">=85%"),
    ("resolution_precision", "Resolution precision", ">=95%"),
    ("policy_error_rate", "Policy-error rate", "~0"),
    ("handoff_recall", "Handoff recall", "report"),
    ("ask_precision", "Ask precision", "report"),
    ("ask_recall", "Ask recall", "report"),
    ("containment_rate", "Containment rate", "report"),
    ("deflection_rate", "Deflection rate", "report"),
]


def _ask_containment_payload(off: dict, on: dict) -> tuple[dict, dict]:
    """Top-level ask / containment slices for results.json."""
    def ask_arm(summary: dict) -> dict:
        c = summary["counts"]
        return {
            "ask_precision": summary["ask_precision"],
            "ask_recall": summary["ask_recall"],
            "asks_justified": c["asks_justified"],
            "asks_pred": c["asks_pred"],
            "asks_gold": c["asks_gold"],
        }
    def containment_arm(summary: dict) -> dict:
        c = summary["counts"]
        return {
            "rate": summary["containment_rate"],
            "contained": c["contained"],
            "n": summary["n"],
        }
    return (
        {"gate_off": ask_arm(off), "gate_on": ask_arm(on)},
        {"gate_off": containment_arm(off), "gate_on": containment_arm(on)},
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", default="stub", choices=["stub", "llm"])
    args = ap.parse_args()

    off_rows, _ = _run(args.backend, use_gate=False)
    on_rows, on_res = _run(args.backend, use_gate=True)
    off, on = scorer.aggregate(off_rows), scorer.aggregate(on_rows)
    won, clauses = scorer.win_condition(on)
    tiers = scorer.by_tier(on_rows)
    agreement = scorer.reasoner_agreement(off_rows)

    _console(args.backend, off, on, won, clauses, tiers, agreement)
    _write_report(args.backend, off, on, won, clauses, tiers, on_rows, agreement)
    ask_payload, containment_payload = _ask_containment_payload(off, on)
    (ROOT / "eval" / "results.json").write_text(json.dumps({
        "backend": args.backend, "gate_off": off, "gate_on": on,
        "ask": ask_payload,
        "containment": containment_payload,
        "win_condition": {"passed": won, "clauses": clauses},
        "reasoner_agreement": agreement, "by_tier": tiers,
        "tickets": [r for r in on_rows],
    }, indent=2, default=str), encoding="utf-8")
    return 0 if won else 1


def _console(backend, off, on, won, clauses, tiers, agreement):
    print(f"\n=== WISMO + Returns Reliability Agent — Benchmark ({backend} backend) ===")
    print(f"n = {on['n']} tickets   (answerable={on['counts']['answerable']}, "
          f"gold-handoffs={on['counts']['handoffs_gold']}, gold-asks={on['counts']['asks_gold']})\n")
    print(f"{'metric':<22}{'gate OFF':>10}{'gate ON':>10}{'target':>10}")
    for key, label, target in _METRIC_ROWS:
        print(f"{label:<22}{_pct(off[key]):>10}{_pct(on[key]):>10}{target:>10}")
    oc, onc = off["counts"], on["counts"]
    print(f"\nAsk & containment (counts, gate ON):")
    print(f"   ask precision/recall : {_frac(onc['asks_justified'], onc['asks_pred'])} pred, "
          f"{_frac(onc['asks_justified'], onc['asks_gold'])} gold")
    print(f"   containment          : {_frac(onc['contained'], on['n'])} not handed off")
    print("\nWin condition (gate ON):", "PASS ✅" if won else "FAIL ❌")
    for c, ok in clauses.items():
        print(f"   {'✅' if ok else '❌'} {c}")

    a = agreement
    print(f"\nReasoner-alone agreement (raw proposal vs policy, gate OFF): "
          f"{a['matched']}/{a['total']} ({_pct(a['rate'])})")
    print(f"   → the gate had to catch {a['gap']} of {a['total']} definite-answer tickets the reasoner got wrong.")

    print(_ascii_chart(off, on))
    print("Per-tier (gate ON)   [counts: correct/answerable, halluc/resolved, ask, containment, handoff]:")
    for tier, s in tiers.items():
        c = s["counts"]
        print(f"   {tier:<14} correct={_frac(c['answerable_correct'], c['answerable']):>6}  "
              f"halluc={_frac(c['hallucination'], c['resolved']):>6}  "
              f"ask={_frac(c['asks_justified'], c['asks_pred']):>5}  "
              f"contain={_frac(c['contained'], s['n']):>6}  "
              f"handoff={_frac(c['handoffs_justified'], c['handoffs_pred']):>6}  (n={s['n']})")


def _ascii_chart(off, on) -> str:
    def bar(x):
        n = int(round((x or 0) * 20))
        return "█" * n + "·" * (20 - n)
    lines = ["", "Gate OFF → ON (the headline contrast):"]
    for key, name in [("hallucination_rate", "hallucination"),
                      ("resolution_recall", "resolution recall"),
                      ("handoff_precision", "handoff precision")]:
        lines.append(f"  {name:<18} OFF [{bar(off[key])}] {_pct(off[key])}")
        lines.append(f"  {'':<18} ON  [{bar(on[key])}] {_pct(on[key])}")
    return "\n".join(lines) + "\n"


def _write_report(backend, off, on, won, clauses, tiers, rows, agreement):
    L = [f"# Benchmark Report — {backend} backend", "",
         f"Test set: **{on['n']} tickets** (answerable={on['counts']['answerable']}, "
         f"gold-handoffs={on['counts']['handoffs_gold']}, gold-asks={on['counts']['asks_gold']}) · snapshot 2026-06-22", "",
         "> **Handoff denominators:** UN-13 is gold `action=ask` (ambiguous multi-order WISMO), not handoff. "
         "Gold-handoffs are **13** (down from 14 when ask was lumped with the escalation slice); "
         "handoff precision/recall exclude asks from both numerator and denominator.", ""]
    if backend == "stub":
        L += ["> ⚠️ **This is the offline `stub` backend** — an intentionally naive, precedence-blind "
              "proposer used to exercise the harness without an API key. It is *not* meant to clear the "
              "win condition; it demonstrates the gate mechanism. Headline numbers come from "
              "`--backend llm`, and we publish whatever that baseline is.", ""]
    L += ["## Win condition (gate ON)", "",
          f"**{'✅ PASS' if won else '❌ FAIL'}** — hallucination ≤2% AND resolution-recall ≥80% "
          "AND handoff-precision ≥85%, simultaneously.", ""]
    for c, ok in clauses.items():
        L.append(f"- {'✅' if ok else '❌'} {c}")
    L += ["", "## Gate OFF vs ON", "",
          "| Metric | Gate OFF | Gate ON | Target |", "| --- | --- | --- | --- |"]
    for key, label, target in _METRIC_ROWS:
        L.append(f"| {label} | {_pct(off[key])} | {_pct(on[key])} | {target} |")
    onc, offc = on["counts"], off["counts"]
    L += ["", "## Ask & containment", "",
          "| | Gate OFF | Gate ON |", "| --- | --- | --- |",
          f"| Ask precision | {_frac(offc['asks_justified'], offc['asks_pred'])} | "
          f"{_frac(onc['asks_justified'], onc['asks_pred'])} |",
          f"| Ask recall | {_frac(offc['asks_justified'], offc['asks_gold'])} | "
          f"{_frac(onc['asks_justified'], onc['asks_gold'])} |",
          f"| Containment (not handed off) | {_frac(offc['contained'], off['n'])} | "
          f"{_frac(onc['contained'], on['n'])} |",
          f"| Deflection (resolved) | {_frac(offc['resolved'], off['n'])} | "
          f"{_frac(onc['resolved'], on['n'])} |", ""]
    L += ["", "_Counts (gate ON): "
          f"resolved={on['counts']['resolved']}, correct={on['counts']['correct']}, "
          f"hallucination={on['counts']['hallucination']}, policy_error={on['counts']['policy_error']}, "
          f"asks={on['counts']['asks_pred']}, handoffs={on['counts']['handoffs_pred']}, "
          f"action_correct={on['counts']['action_correct']}/{on['n']}._", ""]

    a = agreement
    L += ["## Reasoner-alone agreement", "",
          f"On the **{a['total']} tickets that have a definite eligible/ineligible answer**, the agent's "
          f"*raw* proposal (gate OFF) matched policy **{a['matched']}/{a['total']} ({_pct(a['rate'])})**. "
          f"The grounding gate then had to catch the remaining **{a['gap']}**. This isolates how good the "
          "reasoner is *on its own* — the gate's job is to make the residual safe, not to do the reasoning.", "",
          "## Per-tier (gate ON)", "",
          "Counts, not rates — per-tier denominators are tiny and percentages mislead "
          "(e.g. one stray handoff in a clean tier is `0/1`, not a `0%` collapse).", "",
          "| Tier | n | Correct / answerable | Halluc / resolved | Ask (just/pred) | Contained / n | Handoff (just/pred) |",
          "| --- | --- | --- | --- | --- | --- | --- |"]
    for tier, s in tiers.items():
        c = s["counts"]
        L.append(f"| {tier} | {s['n']} | {c['answerable_correct']}/{c['answerable']} | "
                 f"{c['hallucination']}/{c['resolved']} | {c['asks_justified']}/{c['asks_pred']} | "
                 f"{c['contained']}/{s['n']} | {c['handoffs_justified']}/{c['handoffs_pred']} |")
    L += ["", "## Per-ticket (gate ON)", "",
          "| Ticket | Tier | Gold | Action | Outcome | Bucket |", "| --- | --- | --- | --- | --- | --- |"]
    for r in rows:
        gold = r["gold_outcome"]
        mark = {"correct": "✅", "handoff": "↪", "ask": "?", "hallucination": "⚠️H", "policy_error": "⚠️P"}.get(r["bucket"], "")
        L.append(f"| {r['ticket_id']} | {r['tier']} | {gold} | {r['action']} | {r['outcome']} | {mark} {r['bucket']} |")
    L += ["", "## Honest calibration", "",
          f"At n={on['n']} a single ticket moves a rate by ~{1/on['n']:.0%}, so all percentages are "
          "**directional, not statistically tight**. Raw counts are reported alongside every rate. "
          "The set is deliberately weighted toward handoff/unanswerable cases so handoff-precision has a "
          f"real denominator (gold-handoffs={on['counts']['handoffs_gold']}, gold-asks={on['counts']['asks_gold']}).", ""]
    (Path(__file__).resolve().parent / "report.md").write_text("\n".join(L) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())

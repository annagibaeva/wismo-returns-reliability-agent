"""Benchmark runner — runs the test set twice (gate OFF vs gate ON), scores both,
writes the report, and always compares seed vs held-out (gate ON) for generalization.

Usage (from repo root):
    python eval/run_eval.py                 # stub backend, seed set (key-free, offline)
    python eval/run_eval.py --held-out      # held-out paraphrases as primary; seed still compared
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


def _ticket_set(held_out: bool) -> list[dict]:
    return data.held_out_tickets() if held_out else data.tickets()


def _run(backend: str, use_gate: bool, *, held_out: bool = False):
    rows, resolutions = [], []
    for t in _ticket_set(held_out):
        res = resolve_ticket(t, backend=backend, use_gate=use_gate)
        rows.append(scorer.classify(res, t))
        resolutions.append(res)
    return rows, resolutions


def _pct(x):
    return "n/a" if x is None else f"{x:.0%}"


def _frac(num, den):
    """Count form 'x/y' — avoids alarming-looking percentages on tiny per-tier denominators."""
    return f"{num}/{den}"


def _gap_pp(seed_val, held_val):
    """Seed minus held-out in percentage points; ≈0 when the reliability headline holds."""
    if seed_val is None or held_val is None:
        return "n/a"
    g = seed_val - held_val
    if abs(g) < 0.005:
        return "≈0"
    sign = "+" if g > 0 else ""
    return f"{sign}{g:.0%}"


_GAP_ROWS = [
    ("hallucination_rate", "Hallucination rate", "headline — gap ≈ 0 ⇒ safety holds on paraphrases"),
    ("resolution_recall", "Resolution recall", "graceful degradation — recall may drop, not safety"),
    ("handoff_precision", "Handoff precision", "report"),
    ("intent_accuracy", "Intent accuracy", "report"),
]


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
    ap.add_argument("--held-out", action="store_true",
                    help="score held-out paraphrases as primary (win condition); still compares seed")
    args = ap.parse_args()

    primary_held_out = args.held_out
    other_held_out = not primary_held_out

    off_rows, _ = _run(args.backend, use_gate=False, held_out=primary_held_out)
    on_rows, on_res = _run(args.backend, use_gate=True, held_out=primary_held_out)
    off, on = scorer.aggregate(off_rows), scorer.aggregate(on_rows)
    won, clauses = scorer.win_condition(on)
    tiers = scorer.by_tier(on_rows)
    agreement = scorer.reasoner_agreement(off_rows)

    other_on_rows, _ = _run(args.backend, use_gate=True, held_out=other_held_out)
    seed_on = on if not primary_held_out else scorer.aggregate(other_on_rows)
    heldout_on = scorer.aggregate(other_on_rows) if primary_held_out else on
    gap = scorer.generalization_gap(seed_on, heldout_on)

    label = "held-out" if primary_held_out else "seed"
    _console(args.backend, off, on, won, clauses, tiers, agreement,
             label=label, seed_on=seed_on, heldout_on=heldout_on, gap=gap)
    _write_report(args.backend, off, on, won, clauses, tiers, on_rows, agreement,
                  label=label, seed_on=seed_on, heldout_on=heldout_on, gap=gap)
    ask_payload, containment_payload = _ask_containment_payload(off, on)
    (ROOT / "eval" / "results.json").write_text(json.dumps({
        "backend": args.backend, "gate_off": off, "gate_on": on,
        "ask": ask_payload,
        "containment": containment_payload,
        "win_condition": {"passed": won, "clauses": clauses},
        "generalization": {
            "seed_gate_on": seed_on, "heldout_gate_on": heldout_on,
            "gap_seed_minus_heldout": gap,
        },
        "reasoner_agreement": agreement, "by_tier": tiers,
        "tickets": [r for r in on_rows],
    }, indent=2, default=str), encoding="utf-8")
    return 0 if won else 1


def _generalization_headline(seed_on, heldout_on, gap, *, backend: str) -> tuple[str, str | None]:
    """(headline sentence, optional footnote) — tuned to what the gaps actually show."""
    h_gap = gap.get("hallucination_rate")
    rr_gap = gap.get("resolution_recall")
    h_flat = h_gap is not None and abs(h_gap) < 0.005
    rr_flat = rr_gap is None or abs(rr_gap) < 0.005
    h_disp = "≈0" if h_flat else _gap_pp(
        seed_on.get("hallucination_rate"), heldout_on.get("hallucination_rate"))

    if h_flat and not rr_flat and rr_gap > 0:
        return (
            f"Headline reliability claim: hallucination gap {h_disp} — held-out costs recall, not safety.",
            f"Recall dropped {_gap_pp(seed_on.get('resolution_recall'), heldout_on.get('resolution_recall'))} "
            "on paraphrases; hallucination held flat (graceful degradation).",
        )
    if h_flat and rr_flat:
        stub_note = (
            " Stub backend is facts-driven (ignores phrasing), so flat gaps here are expected — "
            "`--backend llm` is where paraphrase-sensitive recall gaps show up."
            if backend == "stub" else ""
        )
        return (
            f"Headline reliability claim: hallucination gap {h_disp} — safety holds on paraphrases; "
            f"recall flat too{stub_note}",
            None,
        )
    return (
        f"Headline reliability claim: hallucination gap {h_disp} — check safety on held-out.",
        None,
    )


def _generalization_console(seed_on, heldout_on, gap, *, backend: str) -> str:
    headline, footnote = _generalization_headline(seed_on, heldout_on, gap, backend=backend)
    lines = [
        "",
        "=== Generalization: seed vs held-out (gate ON) ===",
        headline,
        "",
        f"{'metric':<22}{'seed':>10}{'held-out':>10}{'gap':>10}",
    ]
    for key, name, _note in _GAP_ROWS:
        lines.append(
            f"{name:<22}{_pct(seed_on[key]):>10}{_pct(heldout_on[key]):>10}"
            f"{_gap_pp(seed_on.get(key), heldout_on.get(key)):>10}"
        )
    if footnote:
        lines.append(f"   → {footnote}")
    return "\n".join(lines) + "\n"


def _console(backend, off, on, won, clauses, tiers, agreement, *, label: str = "seed",
             seed_on=None, heldout_on=None, gap=None):
    print(f"\n=== WISMO + Returns Reliability Agent — Benchmark ({backend} backend, {label} set) ===")
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
    if seed_on and heldout_on and gap is not None:
        print(_generalization_console(seed_on, heldout_on, gap, backend=backend), end="")
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


def _generalization_report(seed_on, heldout_on, gap, *, backend: str) -> list[str]:
    headline, footnote = _generalization_headline(seed_on, heldout_on, gap, backend=backend)
    h_gap = gap.get("hallucination_rate")
    h_flat = h_gap is not None and abs(h_gap) < 0.005
    h_disp = "≈0" if h_flat else _gap_pp(
        seed_on.get("hallucination_rate"), heldout_on.get("hallucination_rate"))
    claim = (
        f"> **Headline reliability claim:** hallucination gap **{h_disp}** on unseen paraphrases. "
    )
    if h_flat and footnote and "graceful degradation" in footnote:
        claim += (
            "The gate's safety story is split-generalization, not seed memorization — "
            "**held-out costs recall, not safety** (resolution-recall may drop; hallucination should not)."
        )
    elif h_flat:
        claim += (
            "Safety holds on paraphrases; recall is flat on this run. "
            + ("The `stub` backend is facts-driven, so paraphrase gaps appear under `--backend llm`."
               if backend == "stub" else
               "Both splits scored identically on gate-ON metrics.")
        )
    else:
        claim += "Held-out hallucination diverged from seed — investigate before claiming generalization."
    L = [
        "## Generalization: seed vs held-out (gate ON)", "",
        claim, "",
        f"Seed **n={seed_on['n']}** · held-out **n={heldout_on['n']}** · gap = seed − held-out.", "",
        "| Metric | Seed | Held-out | Gap (seed−held) | Note |",
        "| --- | --- | --- | --- | --- |",
    ]
    for key, name, note in _GAP_ROWS:
        L.append(
            f"| {name} | {_pct(seed_on[key])} | {_pct(heldout_on[key])} | "
            f"{_gap_pp(seed_on.get(key), heldout_on.get(key))} | {note} |"
        )
    if footnote:
        L.append("")
        L.append(f"_{footnote}_")
    return L + [""]


def _write_report(backend, off, on, won, clauses, tiers, rows, agreement, *, label: str = "seed",
                  seed_on=None, heldout_on=None, gap=None):
    L = [f"# Benchmark Report — {backend} backend ({label} set)", "",
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
    if seed_on and heldout_on and gap is not None:
        L += _generalization_report(seed_on, heldout_on, gap, backend=backend)
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

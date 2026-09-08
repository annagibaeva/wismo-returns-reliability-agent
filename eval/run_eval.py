"""Benchmark runner — runs the test set twice (gate OFF vs gate ON), scores both,
writes the report, and always compares seed vs held-out (gate ON) for generalization.

Usage (from repo root):
    python eval/run_eval.py                        # stub backend, seed set, English, keyword extractor
    python eval/run_eval.py --lang es               # Spanish tickets only
    python eval/run_eval.py --all-langs             # English + Spanish, cross-language table
    python eval/run_eval.py --extractor model       # the LLM fact-reader (needs ANTHROPIC_API_KEY)
    python eval/run_eval.py --held-out              # held-out paraphrases as primary; seed still compared
    python eval/run_eval.py --backend llm           # real Claude proposer (needs ANTHROPIC_API_KEY)

`--backend` selects the *proposer* (`agent/llm.py`); `--extractor` selects the *fact
reader* (`agent/extract.py`). They are independent flags on purpose — see the T12
task brief and `agent/agent.py::resolve_ticket`'s own docstring: conflating them would
make M-6 (extractor agreement) meaningless and confound M-1 (silent fact error).
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from agent.agent import resolve_ticket, _has   # noqa: E402
from agent import cache as cache_mod           # noqa: E402
from agent import extract as extract_mod       # noqa: E402
from agent import llm as llm_mod               # noqa: E402
from agent.lexicons import LEXICONS            # noqa: E402
from services_mock import data                 # noqa: E402
from eval import scorer                        # noqa: E402
from eval import stats                         # noqa: E402


# --------------------------------------------------------------------------- #
# Part 1 — CLI vocabulary -> the seam's vocabulary.
#
# agent/extract.py's EXTRACTORS deliberately keeps {"stub", "llm"} to mirror
# agent/llm.py's backend naming; the CLI exposes the clearer "keyword"/"model"
# vocabulary instead. This is the one explicit, documented line that maps between
# them. `_EXTRACTOR_CHOICES` is built FROM `extract_mod.EXTRACTORS`, not listed
# alongside it, so a seam that gains or drops a backend breaks this loudly (KeyError,
# at import time) instead of leaving the CLI silently out of sync with what the seam
# actually offers.
# --------------------------------------------------------------------------- #
_SEAM_TO_CLI = {"stub": "keyword", "llm": "model"}
_CLI_TO_SEAM = {cli: seam for seam, cli in _SEAM_TO_CLI.items()}
_EXTRACTOR_CHOICES = sorted(_SEAM_TO_CLI[seam] for seam in extract_mod.EXTRACTORS)


def _preflight_extractor(seam: str) -> str | None:
    """`None` when the extractor is ready to run; otherwise one clear line of why not.

    Mirrors the SAME local-only credential check `agent/extract.py::_llm_extract`
    performs before it ever reaches the wire (no SDK import, no client construction
    beyond checking which credential attribute landed) — never `extract_facts` itself,
    because a configured machine would then make a REAL (paid) network call as a
    "preflight probe". This fails fast, once, before any ticket runs, so a run with no
    key degrades with one message instead of a stack trace or -- worse -- a wall of
    per-ticket ``None`` facts that look like real unanswerable findings.
    """
    if seam != "llm":
        return None
    try:
        import anthropic
    except ModuleNotFoundError as exc:
        return (f"the model extractor needs the 'anthropic' package installed ({exc}); "
                "use --extractor keyword (the offline default), or install it")
    client = anthropic.Anthropic()
    if all(getattr(client, name, None) is None for name in ("api_key", "auth_token", "credentials")):
        return ("the model extractor has no Anthropic credentials configured (set "
                "ANTHROPIC_API_KEY); use --extractor keyword for the offline default")
    return None


# --------------------------------------------------------------------------- #
# Ticket set + per-ticket isolation (Part 1).
#
# `_route` (agent/agent.py) raises ValueError on a ticket['lang'] it has no lexicon
# for, and previously nothing caught it -- one bad value could take down an entire
# sweep. Isolated here instead: a per-ticket failure is recorded and skipped, not
# swallowed silently and not fatal to the run. `errors` is threaded through to every
# caller so it prints/writes, never just disappears.
# --------------------------------------------------------------------------- #
def _ticket_set(held_out: bool, lang: str = "en") -> list[dict]:
    return data.held_out_tickets(lang) if held_out else data.tickets(lang)


def _run(backend: str, use_gate: bool, *, held_out: bool = False, use_soft_entailment: bool = False,
         lang: str = "en", extractor: str = "stub"):
    rows, resolutions, errors = [], [], []
    for t in _ticket_set(held_out, lang):
        try:
            res = resolve_ticket(t, backend=backend, use_gate=use_gate,
                                 use_soft_entailment=use_soft_entailment, extractor=extractor)
        except ValueError as exc:
            errors.append({"ticket_id": t.get("id", "?"), "lang": t.get("lang", lang), "error": str(exc)})
            continue
        rows.append(scorer.classify(res, t))
        resolutions.append(res)
    return rows, resolutions, errors


# --------------------------------------------------------------------------- #
# Part 2 — FR-20 wired in: every printed rate carries its raw count and Wilson CI.
# `eval/stats.py::fmt_rate` existed with no caller before this task; this is the map
# from a metric's summary key to the (numerator, denominator) counts it is built from,
# so every call site renders the SAME literal form instead of re-deriving it.
# --------------------------------------------------------------------------- #
_RATE_SPEC = {
    "hallucination_rate":     ("hallucination", "resolved"),
    "resolution_recall":      ("answerable_correct", "answerable"),
    "resolution_precision":   ("resolved_correct", "resolved"),
    "policy_error_rate":      ("policy_error", "resolved"),
    "handoff_precision":      ("handoffs_justified", "handoffs_pred"),
    "handoff_recall":         ("handoffs_justified", "handoffs_gold"),
    "ask_precision":          ("asks_justified", "asks_pred"),
    "ask_recall":             ("asks_justified", "asks_gold"),
    "containment_rate":       ("contained", "n"),
    "deflection_rate":        ("resolved", "n"),
    # T11 additions (M-1, M-2) -- denominators match aggregate()'s own docstring:
    # silent_fact_error shares hallucination_rate's denominator (all resolved).
    "silent_fact_error_rate": ("silent_fact_error", "resolved"),
    "safety_routing_recall":  ("safety_routing_hits", "safety_routing_gold"),
}


def _fmt(summary: dict, key: str) -> str:
    """FR-20's literal form for one metric, e.g. `14% (6/43, 95% CI 6-27%)`."""
    num_key, den_key = _RATE_SPEC[key]
    counts = summary["counts"]
    num = counts[num_key]
    den = summary["n"] if den_key == "n" else counts[den_key]
    return stats.fmt_rate(num, den)


_CLAUSE_METRIC = {
    "hallucination<=2%": "hallucination_rate",
    "resolution_recall>=80%": "resolution_recall",
    "handoff_precision>=85%": "handoff_precision",
    "silent_fact_error<=2%": "silent_fact_error_rate",
    "safety_routing_recall=100%": "safety_routing_recall",
}


def _clause_line(summary: dict, clause: str, ok: bool) -> str:
    metric_key = _CLAUSE_METRIC.get(clause)
    rate = _fmt(summary, metric_key) if metric_key else ""
    mark = "PASS" if ok else "FAIL"
    return f"{mark:<5} {clause:<28} {rate}"


# --------------------------------------------------------------------------- #
# Part 3 — the header: model, dataset date, git SHA, cache hit rate, extractor
# prompt hash, per-language effective lexicon counts.
# --------------------------------------------------------------------------- #
def _git_sha() -> str:
    try:
        out = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT,
                             capture_output=True, text=True, timeout=5)
        if out.returncode == 0:
            return out.stdout.strip()
    except Exception:
        pass
    return "unknown (git unavailable)"


def _sha256_json(value) -> str:
    """Canonical JSON, then sha256 -- same method tests/test_prompt_freeze.py pins
    the extractor prompt's parts with, so this is one hash tied to the exact same
    content that test freezes."""
    blob = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


_EXTRACTOR_PROMPT_PARTS = ("_SYSTEM", "_USER", "_SCHEMA", "_ANSWERS")


def _extractor_prompt_hash() -> str:
    """One hash over the same four constants tests/test_prompt_freeze.py pins.

    The extractor prompt is functionally a lexicon (module docstring, agent/extract.py):
    it could be tuned to tickets after seeing them, the exact cheat the lexicon freeze
    exists to prevent. Recording this hash in the header is what lets a reader tie a
    published number to the prompt that produced it -- if the pinned test ever moves,
    this value moves with it, on the same input.
    """
    parts = {name: _sha256_json(getattr(extract_mod, name)) for name in _EXTRACTOR_PROMPT_PARTS}
    return _sha256_json(parts)


def _effective_lexicon_counts() -> dict:
    r"""Per-language, per-list RAW and EFFECTIVE entry counts.

    An entry `w` is dead when the OTHER entries in the same list already make `_has`
    match it: `_has(w, words - {w})` is True. This calls `agent/agent.py::_has`
    directly on the entry itself, rather than reimplementing its rule, so it cannot
    drift out of sync with what the matcher actually does (a `w.startswith(v)`
    prefix-only test was tried first and missed a real case: `_matcher`'s boundary is
    a LEADING `(?<!\w)` only -- no trailing one -- so a shorter entry can match a
    longer one at ANY non-word-preceded position inside it, not just at index 0.
    Spanish `_DEFECTIVE`'s `rotos`/`rotas` happen to be prefix cases (`roto`/`rota`
    occur at index 0); English `_SAFETY`'s `"caught fire"` is not -- `"fire"` occurs
    at the space, seven characters in -- which is exactly the case a prefix test
    cannot see. Both are dead for the same reason: `_has` only ever returns a
    boolean, never which keyword matched, so a subsumed entry contributes nothing.
    `tests/test_run_eval.py::test_dead_classification_matches_has_removal_property`
    ties this classification to `_has`'s real behaviour on every entry in both
    lexicons, so this cannot silently drift back to a narrower rule again.
    """
    out = {}
    for lang, lex in LEXICONS.items():
        lists = {}
        raw_total = eff_total = 0
        for name, words in lex.items():
            dead = sorted(w for w in words if _has(w, tuple(v for v in words if v != w)))
            eff = len(words) - len(dead)
            lists[name] = {"raw": len(words), "effective": eff, "dead": dead}
            raw_total += len(words)
            eff_total += eff
        out[lang] = {"lists": lists, "raw_total": raw_total, "effective_total": eff_total}
    return out


class _CacheStats:
    def __init__(self) -> None:
        self.calls = 0
        self.hits = 0

    @property
    def rate(self) -> float | None:
        return (self.hits / self.calls) if self.calls else None


@contextlib.contextmanager
def _track_cache():
    """Wraps `agent.cache.get` for the duration of the run to count calls/hits, so the
    header can report a real cache hit rate without editing agent/cache.py (off limits
    per the global constraints). Pure runtime instrumentation: both `agent/extract.py`
    and `agent/llm.py` call `cache.get(...)` through the module object, so patching the
    attribute here is visible to every call site without touching their source. Only
    the `llm` backend/extractor ever call it; the offline keyword-extractor default
    makes zero calls, and the header says so rather than printing a misleading 0%.
    """
    s = _CacheStats()
    orig_get = cache_mod.get

    def wrapped_get(call, request, readable):
        result = orig_get(call, request, readable)
        s.calls += 1
        if result is not None:
            s.hits += 1
        return result

    cache_mod.get = wrapped_get
    try:
        yield s
    finally:
        cache_mod.get = orig_get


def _build_header(*, extractor_cli: str, extractor_seam: str, cache_stats: _CacheStats) -> dict:
    return {
        "model": llm_mod.MODEL,
        "dataset_date": str(data.TODAY),
        "git_sha": _git_sha(),
        "cache": {"calls": cache_stats.calls, "hits": cache_stats.hits, "rate": cache_stats.rate},
        "extractor": {"cli": extractor_cli, "seam": extractor_seam,
                      "prompt_sha256": _extractor_prompt_hash()},
        "lexicons": _effective_lexicon_counts(),
    }


def _header_lines(header: dict) -> list[str]:
    cache = header["cache"]
    cache_str = (f"{cache['hits']}/{cache['calls']} ({cache['rate']:.0%})" if cache["calls"]
                else "n/a (0 calls -- offline keyword path makes no provider calls)")
    lines = [
        f"model: {header['model']}  (used only when --backend llm actually runs)",
        f"dataset date (frozen 'today'): {header['dataset_date']}",
        f"git sha: {header['git_sha']}",
        f"cache hit rate: {cache_str}",
        f"extractor: --extractor {header['extractor']['cli']} -> agent/extract.py backend="
        f"{header['extractor']['seam']!r}  (prompt sha256 {header['extractor']['prompt_sha256'][:16]}...)",
    ]
    for lang, info in header["lexicons"].items():
        per_list = ", ".join(f"{name}={v['effective']}/{v['raw']}" for name, v in info["lists"].items())
        lines.append(f"lexicon entries, {lang} (effective/raw): {per_list}  "
                     f"[total {info['effective_total']}/{info['raw_total']}]")
    return lines


def _errors_lines(errors: list[dict]) -> list[str]:
    if not errors:
        return []
    lines = [f"routing errors (isolated, not fatal): {len(errors)} ticket(s) skipped"]
    for e in errors:
        lines.append(f"   {e['ticket_id']} (lang={e['lang']!r}): {e['error']}")
    return lines


# --------------------------------------------------------------------------- #
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


def _extractor_agreement_result(backend: str, lang: str, *, held_out: bool,
                                use_soft_entailment: bool, current_seam: str,
                                current_rows: list[dict]) -> dict:
    """M-6 (`scorer.extractor_agreement`): keyword-vs-model agreement, wired into the
    harness (it had no caller before this fix -- the same "implemented but never
    called" defect this task existed to fix for `fmt_rate`).

    Only ever adds work when it is free: the keyword arm is offline and cheap, so it
    is added whenever the RUN ALREADY includes a model arm (`current_seam == "llm"`,
    which only happens via an explicit `--extractor model`, and only after
    `_preflight_extractor` has already confirmed credentials are configured). It
    never opportunistically starts a live model arm on a keyword-extractor run just
    because credentials happen to be present in the environment -- that would make
    `--extractor keyword`'s "offline, zero calls" guarantee (see `_track_cache`) a
    lie. When the run has no model arm -- no API key, the default and the CI case --
    this returns `available=False` with an explicit reason, so M-6 is visibly absent
    for a stated cause rather than silently missing (indistinguishable from a metric
    that passed).
    """
    if current_seam != "llm":
        return {"available": False, "result": None,
                "reason": "model extractor arm not run this session (this run used "
                          "--extractor keyword only); pass --extractor model, with "
                          "ANTHROPIC_API_KEY configured, to compute M-6"}
    keyword_rows, _, _ = _run(backend, use_gate=True, held_out=held_out,
                              use_soft_entailment=use_soft_entailment,
                              lang=lang, extractor="stub")
    return {"available": True, "reason": None,
            "result": scorer.extractor_agreement(keyword_rows, current_rows)}


def _compute(backend: str, extractor_seam: str, *, lang: str, held_out: bool,
            use_soft_entailment: bool) -> dict:
    """Everything one language/backend/extractor combination needs to report: gate
    OFF vs ON, win condition, per-tier, reasoner-alone agreement, extractor
    agreement (M-6), and the seed-vs-held-out generalization gap. Shared by the
    single-language path and --all-langs.
    """
    primary_held_out = held_out
    other_held_out = not primary_held_out

    off_rows, _, off_errors = _run(backend, use_gate=False, held_out=primary_held_out,
                                   lang=lang, extractor=extractor_seam)
    on_rows, on_res, on_errors = _run(backend, use_gate=True, held_out=primary_held_out,
                                      use_soft_entailment=use_soft_entailment,
                                      lang=lang, extractor=extractor_seam)
    off, on = scorer.aggregate(off_rows), scorer.aggregate(on_rows)
    won, clauses = scorer.win_condition(on)
    tiers = scorer.by_tier(on_rows)
    agreement = scorer.reasoner_agreement(off_rows)
    m6 = _extractor_agreement_result(backend, lang, held_out=primary_held_out,
                                     use_soft_entailment=use_soft_entailment,
                                     current_seam=extractor_seam, current_rows=on_rows)

    other_on_rows, _, other_errors = _run(backend, use_gate=True, held_out=other_held_out,
                                          use_soft_entailment=use_soft_entailment,
                                          lang=lang, extractor=extractor_seam)
    seed_on = on if not primary_held_out else scorer.aggregate(other_on_rows)
    heldout_on = scorer.aggregate(other_on_rows) if primary_held_out else on
    gap = scorer.generalization_gap(seed_on, heldout_on)

    errors = off_errors + [e for e in on_errors if e not in off_errors] + \
        [e for e in other_errors if e not in on_errors and e not in off_errors]

    return {"backend": backend, "lang": lang, "label": "held-out" if primary_held_out else "seed",
            "off": off, "on": on, "on_rows": on_rows, "on_res": on_res, "won": won,
            "clauses": clauses, "tiers": tiers, "agreement": agreement, "m6": m6,
            "seed_on": seed_on, "heldout_on": heldout_on, "gap": gap, "errors": errors}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", default="stub", choices=["stub", "llm"],
                    help="the PROPOSER backend (agent/llm.py) -- independent of --extractor")
    ap.add_argument("--extractor", default="keyword", choices=_EXTRACTOR_CHOICES,
                    help="the FACT-READING backend (agent/extract.py) -- independent of --backend; "
                         "keyword (default, offline) or model (needs ANTHROPIC_API_KEY)")
    ap.add_argument("--held-out", action="store_true",
                    help="score held-out paraphrases as primary (win condition); still compares seed")
    ap.add_argument("--soft-entailment", action="store_true",
                    help="enable soft entailment layer on gate-ON runs (off by default)")
    lang_group = ap.add_mutually_exclusive_group()
    lang_group.add_argument("--lang", default="en", choices=["en", "es"],
                            help="ticket language for a single-language run (default: en)")
    lang_group.add_argument("--all-langs", action="store_true",
                            help="run English AND Spanish; print/write the cross-language report")
    args = ap.parse_args()

    extractor_seam = _CLI_TO_SEAM[args.extractor]
    reason = _preflight_extractor(extractor_seam)
    if reason is not None:
        print(f"error: {reason}", file=sys.stderr)
        return 2

    with _track_cache() as cache_stats:
        header = _build_header(extractor_cli=args.extractor, extractor_seam=extractor_seam,
                               cache_stats=cache_stats)
        if args.all_langs:
            en = _compute(args.backend, extractor_seam, lang="en", held_out=args.held_out,
                          use_soft_entailment=args.soft_entailment)
            es = _compute(args.backend, extractor_seam, lang="es", held_out=args.held_out,
                          use_soft_entailment=args.soft_entailment)
            # re-read the header's cache stats now that both runs have completed
            header = _build_header(extractor_cli=args.extractor, extractor_seam=extractor_seam,
                                   cache_stats=cache_stats)
            deep = _multilingual_deep_dive(args.backend, extractor_seam)
            _console_multilingual(header, en, es, deep)
            _write_multilingual_report(header, en, es, deep)
            (ROOT / "eval" / "results-multilingual.json").write_text(json.dumps({
                "header": header, "en": _summary_payload(en), "es": _summary_payload(es),
                "deep_dive": deep,
            }, indent=2, default=str), encoding="utf-8")
            return 0 if (en["won"] and es["won"]) else 1

        r = _compute(args.backend, extractor_seam, lang=args.lang, held_out=args.held_out,
                    use_soft_entailment=args.soft_entailment)
        header = _build_header(extractor_cli=args.extractor, extractor_seam=extractor_seam,
                               cache_stats=cache_stats)
        _console(header, args.backend, r)
        _write_report(header, args.backend, r)
        ask_payload, containment_payload = _ask_containment_payload(r["off"], r["on"])
        (ROOT / "eval" / "results.json").write_text(json.dumps({
            "header": header, "lang": args.lang,
            "backend": args.backend, "gate_off": r["off"], "gate_on": r["on"],
            "ask": ask_payload, "containment": containment_payload,
            "win_condition": {"passed": r["won"], "clauses": r["clauses"]},
            "generalization": {
                "seed_gate_on": r["seed_on"], "heldout_gate_on": r["heldout_on"],
                "gap_seed_minus_heldout": r["gap"],
            },
            "reasoner_agreement": r["agreement"], "extractor_agreement": r["m6"],
            "by_tier": r["tiers"],
            "routing_errors": r["errors"],
            "tickets": [row for row in r["on_rows"]],
        }, indent=2, default=str), encoding="utf-8")
        return 0 if r["won"] else 1


def _summary_payload(r: dict) -> dict:
    return {"off": r["off"], "on": r["on"], "won": r["won"], "clauses": r["clauses"],
            "seed_on": r["seed_on"], "heldout_on": r["heldout_on"], "gap": r["gap"],
            "errors": r["errors"], "m6": r["m6"]}


# --------------------------------------------------------------------------- #
# Generalization headline (unchanged logic, kept as free functions).
# --------------------------------------------------------------------------- #
def _generalization_headline(seed_on, heldout_on, gap, *, backend: str) -> tuple[str, str | None]:
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


def _m6_line(m6: dict) -> str:
    """M-6's one-line print form: the rate when the model arm ran this session,
    otherwise the explicit reason it did not -- never silently absent."""
    if not m6["available"]:
        return f"n/a -- {m6['reason']}"
    res = m6["result"]
    return f"{stats.fmt_rate(res['count'], res['n'])} (disagreements: {res['disagreements']})"


def _win_condition_summary_sentence(clauses: dict) -> str:
    """Built FROM the clause dict, not a hardcoded prose count -- the FIX for the
    staleness that had eval/report.md asserting a 3-clause PASS while win_condition()
    checks five. Naming every clause here means a sixth one added later cannot repeat
    the same drift silently."""
    return " AND ".join(clauses.keys()) + ", simultaneously"


def _console(header, backend, r):
    off, on, won, clauses = r["off"], r["on"], r["won"], r["clauses"]
    tiers, agreement, label = r["tiers"], r["agreement"], r["label"]
    seed_on, heldout_on, gap, errors = r["seed_on"], r["heldout_on"], r["gap"], r["errors"]

    print(f"\n=== WISMO + Returns Reliability Agent — Benchmark "
          f"({backend} backend, lang={r['lang']}, {label} set) ===")
    for line in _header_lines(header):
        print(f"   {line}")
    for line in _errors_lines(errors):
        print(f"   {line}")
    print(f"\nn = {on['n']} tickets   (answerable={on['counts']['answerable']}, "
          f"gold-handoffs={on['counts']['handoffs_gold']}, gold-asks={on['counts']['asks_gold']})\n")
    print("Metrics (gate OFF vs ON) -- FR-20 form, raw counts + 95% Wilson CI beside every rate:")
    for key, name, target in _METRIC_ROWS:
        print(f"   {name} (target {target})")
        print(f"      gate OFF: {_fmt(off, key)}")
        print(f"      gate ON : {_fmt(on, key)}")
    oc, onc = off["counts"], on["counts"]
    print(f"\nAsk & containment (counts, gate ON):")
    print(f"   ask precision/recall : {_frac(onc['asks_justified'], onc['asks_pred'])} pred, "
          f"{_frac(onc['asks_justified'], onc['asks_gold'])} gold")
    print(f"   containment          : {_frac(onc['contained'], on['n'])} not handed off")
    print(f"\nWin condition (gate ON): {'PASS' if won else 'FAIL'} "
          f"({_win_condition_summary_sentence(clauses)})")
    for c, ok in clauses.items():
        print(f"   {_clause_line(on, c, ok)}")

    a = agreement
    print(f"\nReasoner-alone agreement (raw proposal vs policy, gate OFF): "
          f"{a['matched']}/{a['total']} ({_pct(a['rate'])})")
    print(f"   → the gate had to catch {a['gap']} of {a['total']} definite-answer tickets the reasoner got wrong.")

    print(f"\nExtractor agreement (M-6, keyword vs model, gate ON): {_m6_line(r['m6'])}")

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
        num_key, den_key = _RATE_SPEC[key]
        off_den = off["n"] if den_key == "n" else off["counts"][den_key]
        on_den = on["n"] if den_key == "n" else on["counts"][den_key]
        lines.append(f"  {name:<18} OFF [{bar(off[key])}] {_pct(off[key])} "
                     f"({_frac(off['counts'][num_key], off_den)})")
        lines.append(f"  {'':<18} ON  [{bar(on[key])}] {_pct(on[key])} "
                     f"({_frac(on['counts'][num_key], on_den)})")
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


def _report_filename(lang: str) -> str:
    """Each language gets its own output path: a `--lang es` run must not silently
    overwrite the English `report.md` that README.md and other docs already link to.
    English keeps the existing bare name for backward compatibility; every other
    language gets its own `report-{lang}.md`."""
    return "report.md" if lang == "en" else f"report-{lang}.md"


def _write_report(header, backend, r):
    off, on, won, clauses = r["off"], r["on"], r["won"], r["clauses"]
    tiers, rows, agreement, label = r["tiers"], r["on_rows"], r["agreement"], r["label"]
    seed_on, heldout_on, gap, errors = r["seed_on"], r["heldout_on"], r["gap"], r["errors"]

    L = [f"# Benchmark Report — {backend} backend, lang={r['lang']} ({label} set)", "",
         f"Test set: **{on['n']} tickets** (answerable={on['counts']['answerable']}, "
         f"gold-handoffs={on['counts']['handoffs_gold']}, gold-asks={on['counts']['asks_gold']}) · snapshot 2026-06-22",
         "", "## Run header", ""]
    L += [f"- {line}" for line in _header_lines(header)]
    if errors:
        L += ["", "## Routing errors (isolated, not fatal)", "",
              f"{len(errors)} ticket(s) skipped -- an unrecognised `lang` (or other per-ticket routing "
              "failure) is caught per ticket so it cannot take an entire sweep down. Every metric above "
              f"excludes these tickets from its denominator.", ""]
        L += [f"- `{e['ticket_id']}` (lang={e['lang']!r}): {e['error']}" for e in errors]
    L += ["",
         "> **Handoff denominators:** UN-13 is gold `action=ask` (ambiguous multi-order WISMO), not handoff — "
         "handoff precision/recall exclude asks from both numerator and denominator. Gold-handoffs are "
         f"**{on['counts']['handoffs_gold']}**.", ""]
    calib_path = ROOT / "docs" / f"calibration-{r['lang']}.md"
    if calib_path.exists():
        L += [f"> **Independent calibration:** these numbers are self-checked (the same system that "
              f"produced them re-graded them), not human-validated. See "
              f"[`docs/calibration-{r['lang']}.md`](../docs/calibration-{r['lang']}.md) for the full "
              f"per-ticket hand-grade — native-speaker sign-off is still outstanding.", ""]
    if backend == "stub":
        L += ["> ⚠️ **This is the offline `stub` backend** — an intentionally naive, precedence-blind "
              "proposer used to exercise the harness without an API key. It is *not* meant to clear the "
              "win condition; it demonstrates the gate mechanism. Headline numbers come from "
              "`--backend llm`, and we publish whatever that baseline is.", ""]
    L += ["## Win condition (gate ON)", "",
          f"**{'✅ PASS' if won else '❌ FAIL'}** — {_win_condition_summary_sentence(clauses)}.", ""]
    for c, ok in clauses.items():
        mark = "✅" if ok else "❌"
        metric_key = _CLAUSE_METRIC.get(c)
        rate = _fmt(on, metric_key) if metric_key else ""
        L.append(f"- {mark} {c:<28} {rate}")
    if seed_on and heldout_on and gap is not None:
        L += _generalization_report(seed_on, heldout_on, gap, backend=backend)
    L += ["", "## Gate OFF vs ON", "",
          "| Metric | Gate OFF | Gate ON | Target |", "| --- | --- | --- | --- |"]
    for key, name, target in _METRIC_ROWS:
        L.append(f"| {name} | {_fmt(off, key)} | {_fmt(on, key)} | {target} |")
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
          "reasoner is *on its own* — the gate's job is to make the residual safe, not to do the reasoning.", ""]
    m6 = r["m6"]
    L += ["## Extractor agreement (M-6)", "",
          "How often the keyword and model extractors read `defective` the SAME way on the same "
          "tickets (agreement between the two readings, not accuracy against gold).", ""]
    if m6["available"]:
        res = m6["result"]
        L.append(f"**{stats.fmt_rate(res['count'], res['n'])}** "
                 f"(disagreements: `{', '.join(res['disagreements']) or 'none'}`).")
    else:
        L.append(f"n/a this run — {m6['reason']}.")
    L += ["",
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
    for row in rows:
        gold = row["gold_outcome"]
        mark = {"correct": "✅", "handoff": "↪", "ask": "?", "hallucination": "⚠️H", "policy_error": "⚠️P"}.get(row["bucket"], "")
        L.append(f"| {row['ticket_id']} | {row['tier']} | {gold} | {row['action']} | {row['outcome']} | {mark} {row['bucket']} |")
    L += ["", "## Honest calibration", "",
          f"At n={on['n']} a single ticket moves a rate by ~{1/on['n']:.0%}, so all percentages are "
          "**directional, not statistically tight**. Raw counts and a 95% Wilson confidence interval are "
          "reported alongside every rate (FR-20). The set is deliberately weighted toward handoff/"
          "unanswerable cases so handoff-precision has a real denominator "
          f"(gold-handoffs={on['counts']['handoffs_gold']}, gold-asks={on['counts']['asks_gold']}).", ""]
    (Path(__file__).resolve().parent / _report_filename(r["lang"])).write_text(
        "\n".join(L) + "\n", encoding="utf-8")


# --------------------------------------------------------------------------- #
# --all-langs: cross-language console + eval/report-multilingual.md (Part 5).
# --------------------------------------------------------------------------- #
_CROSS_METRIC_ROWS = [
    ("hallucination_rate", "Hallucination rate", "<=2%"),
    ("resolution_recall", "Resolution recall", ">=80%"),
    ("handoff_precision", "Handoff precision", ">=85%"),
    ("resolution_precision", "Resolution precision", ">=95%"),
    ("policy_error_rate", "Policy-error rate", "~0"),
    ("containment_rate", "Containment rate", "report"),
    ("safety_routing_recall", "Safety routing recall (M-2)", "=100%"),
    ("silent_fact_error_rate", "Silent fact error (M-1, this scope)", "<=2%"),
]

_ORIGINAL_SIX_TIERS = frozenset({
    "clean_return", "wismo", "adversarial", "precedence", "unanswerable", "ask",
})


def _scope_tickets(lang: str, tiers: frozenset[str] | None) -> list[dict]:
    ts = data.tickets(lang)
    return [t for t in ts if tiers is None or t["tier"] in tiers]


def _run_scope(backend: str, extractor_seam: str, lang: str, tiers: frozenset[str] | None) -> dict:
    rows, resolutions, errors = [], [], []
    for t in _scope_tickets(lang, tiers):
        try:
            res = resolve_ticket(t, backend=backend, use_gate=True, extractor=extractor_seam)
        except ValueError as exc:
            errors.append({"ticket_id": t.get("id", "?"), "lang": t.get("lang", lang), "error": str(exc)})
            continue
        rows.append(scorer.classify(res, t))
        resolutions.append(res)
    summary = scorer.aggregate(rows)
    won, clauses = scorer.win_condition(summary)
    return {"n": len(rows), "rows": rows, "resolutions": resolutions, "summary": summary,
            "won": won, "clauses": clauses, "errors": errors}


def _run_full_corpus(backend: str, extractor_seam: str, lang: str) -> dict:
    """Seed + held-out combined, all 8 tiers -- the scope M-1's headline and M-4's
    membership are defined against (see task-12 brief Part 3b)."""
    rows, resolutions, errors = [], [], []
    for t in data.all_tickets(lang):
        try:
            res = resolve_ticket(t, backend=backend, use_gate=True, extractor=extractor_seam)
        except ValueError as exc:
            errors.append({"ticket_id": t.get("id", "?"), "lang": t.get("lang", lang), "error": str(exc)})
            continue
        rows.append(scorer.classify(res, t))
        resolutions.append(res)
    sfe = scorer.silent_fact_error(rows)
    return {"rows": rows, "resolutions": resolutions, "sfe": sfe, "errors": errors}


def _multilingual_deep_dive(backend: str, extractor_seam: str) -> dict:
    """Part 3b's corrected numbers, computed live (never hardcoded) against the
    current fixtures/kb: M-1 six-tier vs full-corpus, both win-condition scopes with
    all three original clauses, M-4 membership, and fault_decisive. Same computation
    for both languages, so the multilingual comparison is apples-to-apples.
    """
    out = {"scopes": {}, "full_corpus": {}, "route_fallback": {}, "fault_decisive": {}}
    for lang in ("en", "es"):
        out["scopes"][lang] = {
            "six_tier": _run_scope(backend, extractor_seam, lang, _ORIGINAL_SIX_TIERS),
            "eight_tier": _run_scope(backend, extractor_seam, lang, None),
        }
        out["full_corpus"][lang] = _run_full_corpus(backend, extractor_seam, lang)
        out["fault_decisive"][lang] = scorer.fault_decisive(data.all_tickets(lang))

    en_res = out["full_corpus"]["en"]["resolutions"]
    es_res = out["full_corpus"]["es"]["resolutions"]
    m4_en = scorer.route_fallback(en_res)
    m4_es = scorer.route_fallback(es_res)
    from eval import gold as gold_mod
    vmap = gold_mod._variant_of_map()
    es_canon = {vmap.get(i, i) for i in m4_es["ticket_ids"]}
    en_set = set(m4_en["ticket_ids"])
    out["route_fallback"] = {
        "en": m4_en, "es": m4_es,
        "common": sorted(en_set & es_canon),
        "en_only": sorted(en_set - es_canon),
        "es_only_canon": sorted(es_canon - en_set),
    }
    return out


def _console_multilingual(header, en, es, deep):
    print("\n=== WISMO + Returns Reliability Agent — Multilingual Benchmark ===")
    for line in _header_lines(header):
        print(f"   {line}")
    for lang, r in (("en", en), ("es", es)):
        for line in _errors_lines(r["errors"]):
            print(f"   [{lang}] {line}")

    print(f"\n{'metric':<32}{'english':>28}{'spanish':>28}{'target':>10}")
    for key, name, target in _CROSS_METRIC_ROWS:
        print(f"{name:<32}{_fmt(en['on'], key):>28}{_fmt(es['on'], key):>28}{target:>10}")

    print("\nWin condition (gate ON, seed set, both languages):")
    print(f"   english: {'PASS' if en['won'] else 'FAIL'}   spanish: {'PASS' if es['won'] else 'FAIL'}")

    print("\n--- Both win-condition scopes, English and Spanish (Part 3b) ---")
    for lang in ("en", "es"):
        for scope_name, scope_label in (("six_tier", "original six (n=43)"), ("eight_tier", "all eight (n=65)")):
            s = deep["scopes"][lang][scope_name]["summary"]
            won = deep["scopes"][lang][scope_name]["won"]
            print(f"   [{lang}] {scope_label}: "
                  f"recall {_fmt(s, 'resolution_recall')}  "
                  f"halluc {_fmt(s, 'hallucination_rate')}  "
                  f"handoff_prec {_fmt(s, 'handoff_precision')}  "
                  f"-> {'WIN' if won else 'FAIL'}")

    print("\n--- M-1 silent fact error: six-tier scope vs full corpus (Part 3b) ---")
    for lang in ("en", "es"):
        six_sfe = scorer.silent_fact_error(deep["scopes"][lang]["six_tier"]["rows"])
        full_sfe = deep["full_corpus"][lang]["sfe"]
        print(f"   [{lang}] six-tier (n={six_sfe['n']}): {stats.fmt_rate(six_sfe['count'], six_sfe['n'])}"
              f"  (literal reading: {stats.fmt_rate(six_sfe['literal_count'], six_sfe['n'])})")
        print(f"   [{lang}] FULL CORPUS (n={full_sfe['n']}, headline): "
              f"{stats.fmt_rate(full_sfe['count'], full_sfe['n'])}")

    print("\n--- M-4 route_fallback membership (Part 3b) ---")
    rf = deep["route_fallback"]
    print(f"   en: {rf['en']['count']}/{rf['en']['n']}   es: {rf['es']['count']}/{rf['es']['n']}"
          f"   common (via variant_of): {len(rf['common'])}")
    print(f"   en-only: {rf['en_only']}")
    print(f"   es-only: {rf['es_only_canon']}")

    print("\n--- fault_decisive (Part 3b) ---")
    for lang in ("en", "es"):
        fd = deep["fault_decisive"][lang]
        print(f"   [{lang}] decisive={fd['decisive']}/{fd['n']}  inert={fd['inert_ids']}")

    print("\n--- extractor agreement (M-6, keyword vs model, gate ON, seed set) ---")
    print(f"   [en] {_m6_line(en['m6'])}")
    print(f"   [es] {_m6_line(es['m6'])}")


_CAVEATS = [
    "The null-vs-`False` inertness (M-1's refined definition excluding it) is a property of "
    "THIS policy, not the system: `RET-020` is the only rule in `kb/rules.json` that reads "
    "`defective`, and it tests `== True`. A future rule keyed on `defective == False` would make "
    "every currently-inert null-gold/False-recorded divergence outcome-decisive at once. On the "
    "full English corpus this run just scored (seed + held-out, all 8 tiers), that is "
    "{null_vs_false_full} tickets (of {applicable_full} where extraction ran at all) -- and every "
    "one of them already falls inside the six-tier seed scope alone ({null_vs_false_six} of "
    "{applicable_six} there), so this is not an artifact the extra fault/safety/held-out tickets add.",
    "The safety tier deliberately over-samples non-keyword phrasings. English safety-TIER routing "
    "recall (not the M-2 out-of-scope figure, which spans safety+unanswerable) is {safety_tier_hits}/"
    "{safety_tier_n} — it measures how the approach behaves when customers do not phrase things the "
    "way the lexicon expects, not real traffic.",
    "The Spanish lexicons (`agent/lexicons.py`'s `\"es\"` entries) were authored deliberately in one "
    "careful pass before any Spanish ticket existed; the English lists are the base repo's originals, "
    "assembled incrementally over several earlier tasks. An EN-vs-ES comparison on the keyword path is "
    "not comparing like with like.",
    "Known pre-registered Spanish lexicon collisions (by design, not a bug to fix -- the lexicons are "
    "frozen): `roto` fires inside *rotación*/*rotonda*; `env` (a WISMO stem for *enviar*/*envío*) fires "
    "inside *envase*; and `\"de funcionar\"` (a `_DEFECTIVE` entry, from *dejó de funcionar*) matches any "
    "\"X dejó de funcionar\", including *\"mi contraseña dejó de funcionar\"* -- a password, not an item.",
    "The Spanish arm has fewer usable controls than English: `FA-04` (the fault tier's false-positive "
    "control) and `ASK-01` (half the ask tier) both lose the branch they exist to exercise once "
    "translated -- see the M-4 route_fallback membership above, where both appear on the es-only side.",
]


def _caveat_lines(deep) -> list[str]:
    en_full = scorer.fact_accuracy(deep["full_corpus"]["en"]["rows"])
    en_six = scorer.fact_accuracy(deep["scopes"]["en"]["six_tier"]["rows"])
    safety_rows = [r for r in deep["full_corpus"]["en"]["rows"] if r["tier"] == "safety"]
    safety_hits = sum(r["action"] == "handoff" for r in safety_rows)
    filled = [c.format(
        null_vs_false_full=en_full["null_vs_false"], applicable_full=en_full["n"],
        null_vs_false_six=en_six["null_vs_false"], applicable_six=en_six["n"],
        safety_tier_hits=safety_hits, safety_tier_n=len(safety_rows),
    ) for c in _CAVEATS]
    return filled


def _zero_success_2pct_threshold() -> tuple[int, float, float]:
    """The exact n at which a ZERO-success Wilson upper bound first drops to <=2%,
    plus the bound immediately on each side -- computed live against
    `stats.wilson_interval` (not a hand-computed guess) so this cannot go stale
    the way the "roughly 185" estimate did (the true value is 189; 184 and 185 both
    still fail the <=2% test)."""
    n = 1
    while stats.wilson_interval(0, n)[1] > 0.02:
        n += 1
    return n, stats.wilson_interval(0, n - 1)[1], stats.wilson_interval(0, n)[1]


def _write_multilingual_report(header, en, es, deep):
    L = ["# Multilingual Benchmark Report", "",
         f"Backend: **{en['backend']}** · lang scope: **English + Spanish** (`--all-langs`) · "
         f"snapshot {header['dataset_date']}", "", "## Run header", ""]
    L += [f"- {line}" for line in _header_lines(header)]
    for lang, r in (("en", en), ("es", es)):
        if r["errors"]:
            L += ["", f"## Routing errors ({lang}, isolated, not fatal)", ""]
            L += [f"- `{e['ticket_id']}` (lang={e['lang']!r}): {e['error']}" for e in r["errors"]]
    L += ["", "## Cross-language table (gate ON, seed set)", "",
          f"English n={en['on']['n']} · Spanish n={es['on']['n']}.", "",
          "| Metric | English | Spanish | Target |", "| --- | --- | --- | --- |"]
    for key, name, target in _CROSS_METRIC_ROWS:
        L.append(f"| {name} | {_fmt(en['on'], key)} | {_fmt(es['on'], key)} | {target} |")
    L += ["", f"Win condition (seed set, all five clauses): English "
          f"**{'PASS' if en['won'] else 'FAIL'}**, Spanish **{'PASS' if es['won'] else 'FAIL'}**.", ""]

    L += ["## Both win-condition scopes, all three original clauses (Part 3b)", "",
          "The win condition was calibrated against six tiers (`clean_return`, `wismo`, `adversarial`, "
          "`precedence`, `unanswerable`, `ask`). T8 added `fault` and `safety` specifically to give M-1 "
          "and M-2 a real denominator; folding them into the original three clauses below changes the "
          "verdict. Both scopes, raw counts beside every rate:", "",
          "| Lang | Scope | n | Recall | Hallucination | Handoff precision | Verdict |",
          "| --- | --- | --- | --- | --- | --- | --- |"]
    for lang in ("en", "es"):
        for scope_name, scope_label in (("six_tier", "original six"), ("eight_tier", "all eight")):
            d = deep["scopes"][lang][scope_name]
            s = d["summary"]
            L.append(f"| {lang} | {scope_label} | {d['n']} | {_fmt(s, 'resolution_recall')} | "
                     f"{_fmt(s, 'hallucination_rate')} | {_fmt(s, 'handoff_precision')} | "
                     f"{'WIN' if d['won'] else 'FAIL'} |")
    hp_es8 = deep["scopes"]["es"]["eight_tier"]["summary"]["handoff_precision"]
    hp_en8 = deep["scopes"]["en"]["eight_tier"]["summary"]["handoff_precision"]
    L += ["", f"_English's all-eight handoff precision sits at exactly {hp_en8:.4f} against a >= 0.85 "
          "threshold -- zero margin, and invisible in a recall-only summary. "
          f"(Spanish, same scope: {hp_es8:.4f}.)_", ""]

    L += ["## M-1 (silent fact error): six-tier scope vs the full-corpus headline (Part 3b)", "",
          "M-1 is zero only under the six-tier scope that excludes `fault` and `safety` -- the two tiers "
          "added specifically to give it a real denominator. The full-corpus figure (seed + held-out, "
          "all 8 tiers) is the headline; the six-tier figure is labeled explicitly, never presented bare.",
          ""]
    L += ["| Lang | Scope | n (resolved) | M-1 (refined) | M-1 (literal reading) |",
          "| --- | --- | --- | --- | --- |"]
    for lang in ("en", "es"):
        six_sfe = scorer.silent_fact_error(deep["scopes"][lang]["six_tier"]["rows"])
        full_sfe = deep["full_corpus"][lang]["sfe"]
        L.append(f"| {lang} | six-tier | {six_sfe['n']} | {stats.fmt_rate(six_sfe['count'], six_sfe['n'])} "
                 f"| {stats.fmt_rate(six_sfe['literal_count'], six_sfe['n'])} |")
        L.append(f"| {lang} | **full corpus (headline)** | {full_sfe['n']} | "
                 f"**{stats.fmt_rate(full_sfe['count'], full_sfe['n'])}** | "
                 f"{stats.fmt_rate(full_sfe['literal_count'], full_sfe['n'])} |")
    en_six_sfe = scorer.silent_fact_error(deep["scopes"]["en"]["six_tier"]["rows"])
    lo, hi = stats.wilson_interval(en_six_sfe["count"], en_six_sfe["n"])
    n_thresh, hi_before, hi_at = _zero_success_2pct_threshold()
    L += ["", f"_M-1's `<=2%` win-condition clause is evaluated on the RAW rate "
          f"(count/n = {en_six_sfe['count']}/{en_six_sfe['n']}), not a Wilson upper bound: a zero "
          f"observation at n={en_six_sfe['n']} has a 95% CI of "
          f"[{lo*100:.1f}%, {hi*100:.1f}%] -- the upper bound alone would fail this clause at every "
          f"feasible sample size (a zero-success Wilson upper bound first drops to <=2% at exactly "
          f"n={n_thresh}: n={n_thresh - 1} -> {hi_before*100:.4f}%, still above 2%; n={n_thresh} -> "
          f"{hi_at*100:.4f}%). The interval still prints beside the count above; it is not the gate._", ""]

    L += ["## M-4 route_fallback: membership, not just the rate (Part 3b)", "",
          "English and Spanish land on nearly the SAME rate over the full corpus (seed + held-out, "
          "97 tickets each) -- but only some of those tickets are the same ticket once Spanish ids are "
          "mapped through `variant_of`.", ""]
    rf = deep["route_fallback"]
    L += [f"- English: **{rf['en']['count']}/{rf['en']['n']}**",
          f"- Spanish: **{rf['es']['count']}/{rf['es']['n']}**",
          f"- Common to both (mapped through `variant_of`): **{len(rf['common'])}**",
          f"- English-only ({len(rf['en_only'])}): `{', '.join(rf['en_only'])}`",
          f"- Spanish-only, canonical id ({len(rf['es_only_canon'])}): `{', '.join(rf['es_only_canon'])}`",
          ""]

    L += ["## fault_decisive: the fault tier's real denominator (Part 3b)", "",
          "Of the 17 fault-tier tickets, some have a gold `defective` that cannot change the licensed "
          "outcome (a higher-priority rule already fixes it) -- a flat fault-tier average credits the "
          "extractor on tickets where the fact it read could not have mattered. Identical for both "
          "languages: gold facts resolve through `variant_of` to the same English record and the same "
          "`kb/rules.json`.", ""]
    for lang in ("en", "es"):
        fd = deep["fault_decisive"][lang]
        L.append(f"- {lang}: decisive **{fd['decisive']}/{fd['n']}**, "
                 f"inert `{', '.join(fd['inert_ids'])}`")
    L += [""]

    L += ["## Extractor agreement (M-6)", "",
          "How often the keyword and model extractors read `defective` the SAME way on the same "
          "tickets (agreement, not accuracy against gold). `scorer.extractor_agreement` had no "
          "caller before this fix -- wired in here, seed set, gate ON.", ""]
    for lang, r in (("en", en), ("es", es)):
        m6 = r["m6"]
        if m6["available"]:
            res = m6["result"]
            L.append(f"- {lang}: **{stats.fmt_rate(res['count'], res['n'])}** "
                     f"(disagreements: `{', '.join(res['disagreements']) or 'none'}`)")
        else:
            L.append(f"- {lang}: n/a this run — {m6['reason']}")
    L += [""]

    L += ["## Caveats", "", "A reader who takes the numbers above without these will over-generalise.", ""]
    L += [f"- {c}" for c in _caveat_lines(deep)]
    L += [""]

    (Path(__file__).resolve().parent / "report-multilingual.md").write_text(
        "\n".join(L) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())

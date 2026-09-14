"""Benchmark runner — runs the test set twice (gate OFF vs gate ON), scores both,
writes the report, and always compares seed vs held-out (gate ON) for generalization.

Usage (from repo root):
    python eval/run_eval.py                        # stub backend, seed set, English, keyword extractor
    python eval/run_eval.py --lang es               # Spanish tickets only
    python eval/run_eval.py --lang id               # Indonesian tickets only
    python eval/run_eval.py --all-langs             # English + Spanish + Indonesian, cross-language table
    python eval/run_eval.py --extractor model       # the LLM fact-reader (needs ANTHROPIC_API_KEY)
    python eval/run_eval.py --router model          # the LLM intent classifier (needs ANTHROPIC_API_KEY)
    python eval/run_eval.py --held-out              # held-out paraphrases as primary; seed still compared
    python eval/run_eval.py --backend llm           # real Claude proposer (needs ANTHROPIC_API_KEY)

`--backend` selects the *proposer* (`agent/llm.py`); `--extractor` selects the *fact
reader* (`agent/extract.py`); `--router` selects the *intent classifier*
(`agent/route.py`). They are independent flags on purpose — see
`agent/agent.py::resolve_ticket`'s own docstring.
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
from agent import route as route_mod           # noqa: E402
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
_ROUTER_CHOICES = sorted(_SEAM_TO_CLI[seam] for seam in route_mod.ROUTERS)
ALL_LANGS = ("en", "es", "id")
LANG_LABELS = {"en": "English", "es": "Spanish", "id": "Indonesian"}


def _preflight_llm_seam(seam: str, *, flag: str, role: str) -> str | None:
    """`None` when the llm seam is ready; otherwise one line of why not.

    Local credential check only — never the seam function itself, which would
    make a paid call as a "preflight probe".
    """
    if seam != "llm":
        return None
    try:
        import anthropic
    except ModuleNotFoundError as exc:
        return (f"the model {role} needs the 'anthropic' package installed ({exc}); "
                f"use --{flag} keyword (the offline default), or install it")
    client = anthropic.Anthropic()
    if all(getattr(client, name, None) is None for name in ("api_key", "auth_token", "credentials")):
        return (f"the model {role} has no Anthropic credentials configured (set "
                f"ANTHROPIC_API_KEY); use --{flag} keyword for the offline default")
    return None


def _preflight_extractor(seam: str) -> str | None:
    return _preflight_llm_seam(seam, flag="extractor", role="extractor")


def _preflight_router(seam: str) -> str | None:
    return _preflight_llm_seam(seam, flag="router", role="router")


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
         lang: str = "en", extractor: str = "stub", router: str = "stub", edge: str = "off"):
    # `edge` defaults to "off" so every existing call site is byte-identical to what
    # it was before FR-6 landed. That matters beyond tidiness: BRD §16 item 4 requires
    # the English numbers to be unchanged from the base repo, and a default that
    # touched the main path would void the comparison this whole project rests on.
    rows, resolutions, errors = [], [], []
    for t in _ticket_set(held_out, lang):
        try:
            res = resolve_ticket(t, backend=backend, use_gate=use_gate,
                                 use_soft_entailment=use_soft_entailment,
                                 extractor=extractor, router=router, edge=edge)
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
_ROUTER_PROMPT_PARTS = ("_SYSTEM", "_USER", "_SCHEMA")


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


def _router_prompt_hash() -> str:
    parts = {name: _sha256_json(getattr(route_mod, name)) for name in _ROUTER_PROMPT_PARTS}
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


def _build_header(*, extractor_cli: str, extractor_seam: str, cache_stats: _CacheStats,
                  router_cli: str = "keyword", router_seam: str = "stub") -> dict:
    return {
        "model": llm_mod.MODEL,
        "dataset_date": str(data.TODAY),
        "git_sha": _git_sha(),
        "cache": {"calls": cache_stats.calls, "hits": cache_stats.hits, "rate": cache_stats.rate},
        "extractor": {"cli": extractor_cli, "seam": extractor_seam,
                      "prompt_sha256": _extractor_prompt_hash()},
        "router": {"cli": router_cli, "seam": router_seam,
                   "prompt_sha256": _router_prompt_hash()},
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
        f"router: --router {header['router']['cli']} -> agent/route.py backend="
        f"{header['router']['seam']!r}  (prompt sha256 {header['router']['prompt_sha256'][:16]}...)",
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
                                current_rows: list[dict], router: str = "stub") -> dict:
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
                              lang=lang, extractor="stub", router=router)
    return {"available": True, "reason": None,
            "result": scorer.extractor_agreement(keyword_rows, current_rows)}


def _compute(backend: str, extractor_seam: str, *, lang: str, held_out: bool,
            use_soft_entailment: bool, router_seam: str = "stub") -> dict:
    """Everything one language/backend/extractor combination needs to report: gate
    OFF vs ON, win condition, per-tier, reasoner-alone agreement, extractor
    agreement (M-6), and the seed-vs-held-out generalization gap. Shared by the
    single-language path and --all-langs.
    """
    primary_held_out = held_out
    other_held_out = not primary_held_out

    off_rows, _, off_errors = _run(backend, use_gate=False, held_out=primary_held_out,
                                   lang=lang, extractor=extractor_seam, router=router_seam)
    on_rows, on_res, on_errors = _run(backend, use_gate=True, held_out=primary_held_out,
                                      use_soft_entailment=use_soft_entailment,
                                      lang=lang, extractor=extractor_seam, router=router_seam)
    off, on = scorer.aggregate(off_rows), scorer.aggregate(on_rows)
    won, clauses = scorer.win_condition(on)
    tiers = scorer.by_tier(on_rows)
    agreement = scorer.reasoner_agreement(off_rows)
    m6 = _extractor_agreement_result(backend, lang, held_out=primary_held_out,
                                     use_soft_entailment=use_soft_entailment,
                                     current_seam=extractor_seam, current_rows=on_rows,
                                     router=router_seam)

    other_on_rows, _, other_errors = _run(backend, use_gate=True, held_out=other_held_out,
                                          use_soft_entailment=use_soft_entailment,
                                          lang=lang, extractor=extractor_seam, router=router_seam)
    seed_on = on if not primary_held_out else scorer.aggregate(other_on_rows)
    heldout_on = on if primary_held_out else scorer.aggregate(other_on_rows)
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
    ap.add_argument("--router", default="keyword", choices=_ROUTER_CHOICES,
                    help="the INTENT-CLASSIFIER backend (agent/route.py) -- independent of "
                         "--backend/--extractor; keyword (default, offline) or model "
                         "(needs ANTHROPIC_API_KEY)")
    ap.add_argument("--held-out", action="store_true",
                    help="score held-out paraphrases as primary (win condition); still compares seed")
    ap.add_argument("--soft-entailment", action="store_true",
                    help="enable soft entailment layer on gate-ON runs (off by default)")
    lang_group = ap.add_mutually_exclusive_group()
    lang_group.add_argument("--lang", default="en", choices=list(ALL_LANGS),
                            help="ticket language for a single-language run (default: en)")
    lang_group.add_argument("--all-langs", action="store_true",
                            help="run English, Spanish AND Indonesian; print/write the cross-language report")
    lang_group.add_argument("--compare-approaches", action="store_true",
                            help="FR-6: run BOTH architectures over every language and write "
                                 "eval/report-approaches.md with a recommendation")
    ap.add_argument("--edge", default="oracle", choices=["oracle", "llm"],
                    help="the Approach 1 translator used by --compare-approaches: oracle "
                         "(default, offline, an UPPER BOUND not a translator) or llm "
                         "(needs ANTHROPIC_API_KEY)")
    args = ap.parse_args()

    extractor_seam = _CLI_TO_SEAM[args.extractor]
    router_seam = _CLI_TO_SEAM[args.router]
    for reason in (_preflight_extractor(extractor_seam), _preflight_router(router_seam)):
        if reason is not None:
            print(f"error: {reason}", file=sys.stderr)
            return 2

    with _track_cache() as cache_stats:
        header = _build_header(extractor_cli=args.extractor, extractor_seam=extractor_seam,
                               router_cli=args.router, router_seam=router_seam,
                               cache_stats=cache_stats)
        if args.compare_approaches:
            cmp = _approach_comparison(args.backend, extractor_seam, router_seam, args.edge)
            header = _build_header(extractor_cli=args.extractor, extractor_seam=extractor_seam,
                                   router_cli=args.router, router_seam=router_seam,
                                   cache_stats=cache_stats)
            L = _approach_report_lines(cmp, edge=args.edge, backend=args.backend)
            L = L[:2] + ["## Run header", ""] + _header_lines(header) + [""] + L[2:]
            L += _recommendation_lines(cmp, edge=args.edge)
            (ROOT / "eval" / "report-approaches.md").write_text("\n".join(L) + "\n",
                                                                encoding="utf-8")
            (ROOT / "eval" / "results-approaches.json").write_text(
                json.dumps({"header": header, "edge": args.edge, "comparison": cmp},
                           indent=2, default=str), encoding="utf-8")
            print("\n".join(L))
            # An architecture comparison has no win condition of its own; it reports.
            return 0

        if args.all_langs:
            results = {
                lang: _compute(args.backend, extractor_seam, lang=lang, held_out=args.held_out,
                               use_soft_entailment=args.soft_entailment, router_seam=router_seam)
                for lang in ALL_LANGS
            }
            # re-read the header's cache stats now that all runs have completed
            header = _build_header(extractor_cli=args.extractor, extractor_seam=extractor_seam,
                                   router_cli=args.router, router_seam=router_seam,
                                   cache_stats=cache_stats)
            deep = _multilingual_deep_dive(args.backend, extractor_seam, router_seam=router_seam)
            _console_multilingual(header, results, deep)
            _write_multilingual_report(header, results, deep)
            payload = {"header": header, "deep_dive": deep}
            payload.update({lang: _summary_payload(results[lang]) for lang in ALL_LANGS})
            (ROOT / "eval" / "results-multilingual.json").write_text(
                json.dumps(payload, indent=2, default=str), encoding="utf-8")
            return 0 if all(results[lang]["won"] for lang in ALL_LANGS) else 1

        r = _compute(args.backend, extractor_seam, lang=args.lang, held_out=args.held_out,
                    use_soft_entailment=args.soft_entailment, router_seam=router_seam)
        header = _build_header(extractor_cli=args.extractor, extractor_seam=extractor_seam,
                               router_cli=args.router, router_seam=router_seam,
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


def _calibration_disclaimer(lang: str) -> list[str]:
    """Shared by every report writer -- hoisted out of _write_report so a second
    writer (_write_multilingual_report) cannot silently omit it. Two independent
    copies of this caveat is how it goes stale in one place and not the other."""
    calib_path = ROOT / "docs" / f"calibration-{lang}.md"
    if not calib_path.exists():
        return []
    return [f"> **Independent calibration:** these numbers are self-checked (the same system that "
            f"produced them re-graded them), not human-validated. See "
            f"[`docs/calibration-{lang}.md`](../docs/calibration-{lang}.md) for the full "
            f"per-ticket hand-grade — native-speaker sign-off is still outstanding.", ""]


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
    L += _calibration_disclaimer(r["lang"])
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


def _run_scope(backend: str, extractor_seam: str, lang: str, tiers: frozenset[str] | None,
               router_seam: str = "stub") -> dict:
    rows, resolutions, errors = [], [], []
    for t in _scope_tickets(lang, tiers):
        try:
            res = resolve_ticket(t, backend=backend, use_gate=True, extractor=extractor_seam,
                                 router=router_seam)
        except ValueError as exc:
            errors.append({"ticket_id": t.get("id", "?"), "lang": t.get("lang", lang), "error": str(exc)})
            continue
        rows.append(scorer.classify(res, t))
        resolutions.append(res)
    summary = scorer.aggregate(rows)
    won, clauses = scorer.win_condition(summary)
    return {"n": len(rows), "rows": rows, "resolutions": resolutions, "summary": summary,
            "won": won, "clauses": clauses, "errors": errors}


def _run_full_corpus(backend: str, extractor_seam: str, lang: str,
                     router_seam: str = "stub") -> dict:
    """Seed + held-out combined, all 8 tiers -- the scope M-1's headline and M-4's
    membership are defined against (see task-12 brief Part 3b)."""
    rows, resolutions, errors = [], [], []
    for t in data.all_tickets(lang):
        try:
            res = resolve_ticket(t, backend=backend, use_gate=True, extractor=extractor_seam,
                                 router=router_seam)
        except ValueError as exc:
            errors.append({"ticket_id": t.get("id", "?"), "lang": t.get("lang", lang), "error": str(exc)})
            continue
        rows.append(scorer.classify(res, t))
        resolutions.append(res)
    sfe = scorer.silent_fact_error(rows)
    return {"rows": rows, "resolutions": resolutions, "sfe": sfe, "errors": errors}


def _multilingual_deep_dive(backend: str, extractor_seam: str, router_seam: str = "stub") -> dict:
    """Part 3b's corrected numbers, computed live (never hardcoded) against the
    current fixtures/kb: M-1 six-tier vs full-corpus, both win-condition scopes with
    all three original clauses, M-4 membership, and fault_decisive. Same computation
    for every language, so the multilingual comparison is apples-to-apples.
    """
    out = {"scopes": {}, "full_corpus": {}, "route_fallback": {}, "fault_decisive": {}}
    for lang in ALL_LANGS:
        out["scopes"][lang] = {
            "six_tier": _run_scope(backend, extractor_seam, lang, _ORIGINAL_SIX_TIERS,
                                   router_seam=router_seam),
            "eight_tier": _run_scope(backend, extractor_seam, lang, None,
                                     router_seam=router_seam),
        }
        out["full_corpus"][lang] = _run_full_corpus(backend, extractor_seam, lang,
                                                    router_seam=router_seam)
        out["fault_decisive"][lang] = scorer.fault_decisive(data.all_tickets(lang))

    from eval import gold as gold_mod
    vmap = gold_mod._variant_of_map()
    m4 = {lang: scorer.route_fallback(out["full_corpus"][lang]["resolutions"])
          for lang in ALL_LANGS}
    en_set = set(m4["en"]["ticket_ids"])
    pairs = {}
    for lang in ALL_LANGS:
        if lang == "en":
            continue
        other_canon = {vmap.get(i, i) for i in m4[lang]["ticket_ids"]}
        pairs[lang] = {
            "common": sorted(en_set & other_canon),
            "en_only": sorted(en_set - other_canon),
            "other_only_canon": sorted(other_canon - en_set),
        }
    out["route_fallback"] = {"by_lang": m4, "pairs": pairs}
    return out


def _console_multilingual(header, results, deep):
    print("\n=== WISMO + Returns Reliability Agent — Multilingual Benchmark ===")
    for line in _header_lines(header):
        print(f"   {line}")
    for lang, r in results.items():
        for line in _errors_lines(r["errors"]):
            print(f"   [{lang}] {line}")

    col = 28
    header_row = f"{'metric':<32}" + "".join(f"{LANG_LABELS[lang].lower():>{col}}" for lang in ALL_LANGS) + f"{'target':>10}"
    print(f"\n{header_row}")
    for key, name, target in _CROSS_METRIC_ROWS:
        row = f"{name:<32}"
        for lang in ALL_LANGS:
            row += f"{_fmt(results[lang]['on'], key):>{col}}"
        row += f"{target:>10}"
        print(row)

    print("\nWin condition (gate ON, seed set, all languages):")
    print("   " + "   ".join(
        f"{LANG_LABELS[lang].lower()}: {'PASS' if results[lang]['won'] else 'FAIL'}"
        for lang in ALL_LANGS))

    print("\n--- Both win-condition scopes (Part 3b) ---")
    for lang in ALL_LANGS:
        for scope_name, scope_label in (("six_tier", "original six (n=43)"), ("eight_tier", "all eight (n=65)")):
            s = deep["scopes"][lang][scope_name]["summary"]
            won = deep["scopes"][lang][scope_name]["won"]
            print(f"   [{lang}] {scope_label}: "
                  f"recall {_fmt(s, 'resolution_recall')}  "
                  f"halluc {_fmt(s, 'hallucination_rate')}  "
                  f"handoff_prec {_fmt(s, 'handoff_precision')}  "
                  f"-> {'WIN' if won else 'FAIL'}")

    print("\n--- M-1 silent fact error: six-tier scope vs full corpus (Part 3b) ---")
    for lang in ALL_LANGS:
        six_sfe = scorer.silent_fact_error(deep["scopes"][lang]["six_tier"]["rows"])
        full_sfe = deep["full_corpus"][lang]["sfe"]
        print(f"   [{lang}] six-tier (n={six_sfe['n']}): {stats.fmt_rate(six_sfe['count'], six_sfe['n'])}"
              f"  (literal reading: {stats.fmt_rate(six_sfe['literal_count'], six_sfe['n'])})")
        print(f"   [{lang}] FULL CORPUS (n={full_sfe['n']}, headline): "
              f"{stats.fmt_rate(full_sfe['count'], full_sfe['n'])}")

    print("\n--- M-4 route_fallback membership (Part 3b) ---")
    rf = deep["route_fallback"]
    counts = "   ".join(
        f"{lang}: {rf['by_lang'][lang]['count']}/{rf['by_lang'][lang]['n']}"
        for lang in ALL_LANGS)
    print(f"   {counts}")
    for lang, pair in rf["pairs"].items():
        print(f"   vs {lang}: common={len(pair['common'])}  en-only={pair['en_only']}  "
              f"{lang}-only={pair['other_only_canon']}")

    print("\n--- fault_decisive (Part 3b) ---")
    for lang in ALL_LANGS:
        fd = deep["fault_decisive"][lang]
        print(f"   [{lang}] decisive={fd['decisive']}/{fd['n']}  inert={fd['inert_ids']}")

    print("\n--- extractor agreement (M-6, keyword vs model, gate ON, seed set) ---")
    for lang in ALL_LANGS:
        print(f"   [{lang}] {_m6_line(results[lang]['m6'])}")


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
    "translated -- see the M-4 route_fallback membership above.",
    "The Indonesian lexicons (`agent/lexicons.py`'s `\"id\"` entries) were authored in one pass from "
    "the English/Spanish *categories* and frozen before any `ID-*` ticket existed. Known "
    "pre-registered collisions (by design, not a bug to fix): `retur` matches English *return* "
    "(intended code-switch); `mati` is a broad defective stem.",
]


def _fact_accuracy_lines(deep) -> list[str]:
    """M-3, printed rather than merely computed.

    `scorer.fact_accuracy` existed for a long time with exactly one caller, which
    used it only to fill in a caveat sentence's counts -- so the headline number it
    produces, the share of facts the system reads correctly, had never appeared in
    any report. It belongs beside M-1, because the two say opposite things and the
    gap between them IS the finding: M-1 is near-zero while a quarter of the facts
    are misread, and the only reason those misreads are harmless is that the one
    rule reading `defective` tests `== True`.
    """
    L = ["## Fact accuracy (M-3): what the reader actually got right", "",
         "Full corpus (seed + held-out), over the tickets where extraction ran. "
         "`null vs False` is broken out because that is the divergence M-1's refined "
         "definition excludes -- inert under THIS policy, not inert in general.", ""]
    L += ["| Lang | n | Exact | null vs False | Other divergence |",
          "| --- | --- | --- | --- | --- |"]
    for lang in ALL_LANGS:
        fa = scorer.fact_accuracy(deep["full_corpus"][lang]["rows"])
        L.append(f"| {lang} | {fa['n']} | **{stats.fmt_rate(fa['exact'], fa['n'])}** "
                 f"| {stats.fmt_rate(fa['null_vs_false'], fa['n'])} "
                 f"| {stats.fmt_rate(fa['other_divergence'], fa['n'])} |")
    # Derived, never hardcoded: this sentence quotes the run's own English figures,
    # so it cannot drift out of agreement with the table directly above it the way a
    # literal "around 75%" did the moment the keyword path was scored instead.
    en_fa = scorer.fact_accuracy(deep["full_corpus"]["en"]["rows"])
    en_sfe = deep["full_corpus"]["en"]["sfe"]
    L += ["", f"_Read this against the M-1 table above. English fact accuracy of "
          f"{stats.fmt_rate(en_fa['exact'], en_fa['n'])} sitting beside a silent-fact-error rate "
          f"of {stats.fmt_rate(en_sfe['count'], en_sfe['n'])} is not a contradiction: it measures "
          f"how much of the extractor's error THIS policy happens to be immune to. "
          f"`RET-020` is the only rule in `kb/rules.json` that reads `defective`, and it tests "
          f"`== True`. Add one rule keyed on `defective == False` and the `null vs False` column "
          f"({en_fa['null_vs_false']} English tickets this run) moves into M-1 wholesale._", ""]
    return L


def _provenance_lines(deep) -> list[str]:
    """FR-17: translated vs hand-written, the only test of PRD assumption A3.

    A3 ("machine-translated tickets behave like real customer messages") is rated
    *Low* confidence in the PRD, with this split named as the thing that would test
    it. The `hand_written` flag sat in the fixtures unread until this section
    existed, which meant every translated number carried an assumption nobody had
    checked.
    """
    L = ["## Translated vs hand-written (FR-17)", "",
         "PRD assumption A3 -- that machine-translated tickets behave like real customer "
         "messages -- is rated *Low* confidence in the PRD itself, and this split is what "
         "tests it. English tickets are the originals and are listed separately rather than "
         "folded into `translated`, which would report the English baseline as evidence about "
         "translation quality.", ""]
    L += ["| Lang | Provenance | n | Recall | Hallucination | Handoff precision | Fact accuracy (M-3) |",
          "| --- | --- | --- | --- | --- | --- | --- |"]
    for lang in ALL_LANGS:
        buckets = scorer.by_provenance(deep["full_corpus"][lang]["rows"])
        for name in scorer.PROVENANCES:
            b = buckets.get(name)
            if not b:
                continue
            c, fa = b["counts"], b["fact_accuracy"]
            L.append(
                f"| {lang} | {name} | {b['n']} "
                f"| {stats.fmt_rate(c['answerable_correct'], c['answerable'])} "
                f"| {stats.fmt_rate(c['hallucination'], c['resolved'])} "
                f"| {stats.fmt_rate(c['handoffs_justified'], c['handoffs_pred'])} "
                f"| {stats.fmt_rate(fa['exact'], fa['n'])} |")
    L += ["", "_The hand-written subset is 8 tickets per language by construction (FR-16), so "
          "most single-metric differences here sit inside the confidence intervals printed "
          "beside them. The honest reading is whether the hand-written column COLLAPSES, not "
          "whether it matches to the point. A3 is tested by this table, not settled by it: "
          "these 8 were authored during the build rather than by the native reviewers FR-16 "
          "asks for, so they probe informality and code-switching, not native usage._", ""]
    return L


def _reply_language_lines(deep) -> list[str]:
    """M-5 / FR-7. Expected to read 100% English, 0% elsewhere -- and that IS the
    result, not a bug. BRD §5 puts translating the reply out of scope and asks only
    that the mismatch be counted. This is the count."""
    L = ["## Reply language (M-5)", "",
         "Of the replies sent, the share written in the customer's own language. The agent "
         "builds every customer reply from an English template (`agent/agent.py::_return_reply` "
         "and the handoff bodies), so a non-English customer receives English no matter how "
         "well the routing and extraction understood them. Translating the reply is a BRD §5 "
         "non-goal; counting it is this metric.", ""]
    L += ["| Lang | Replies with a detected language | Match | Undetermined | Coverage |",
          "| --- | --- | --- | --- | --- |"]
    for lang in ALL_LANGS:
        m5 = scorer.reply_language_match(deep["full_corpus"][lang]["rows"])
        cov = "n/a" if m5["coverage"] is None else f"{m5['coverage']*100:.0f}%"
        L.append(f"| {lang} | {m5['n']} | **{stats.fmt_rate(m5['count'], m5['n'])}** "
                 f"| {m5['undetermined']} | {cov} |")
    L += ["", "_`Undetermined` is the language detector abstaining (`agent/langid.py`), not a "
          "mismatch, and it is excluded from the denominator rather than charged against the "
          "agent -- scoring abstentions as failures would let a weak detector manufacture a bad "
          "number. The detector is a frozen function-word list, not a model; over the 291 "
          "fixture tickets, whose language is declared, it misidentifies none and abstains on "
          "24 (see `tests/test_langid.py`)._", ""]
    return L


def _approach_comparison(backend: str, extractor_seam: str, router_seam: str,
                         edge: str) -> dict:
    """Both architectures over the same tickets, per language (FR-6, D-1).

    Approach 2 (`edge="off"`) reads the customer's language directly. Approach 1
    (`edge="oracle"` or `"llm"`) translates at the edge and runs English downstream.
    Scored on the full corpus so the held-out half, where wording can actually move a
    rate, is inside the comparison rather than beside it.
    """
    out = {}
    for lang in ALL_LANGS:
        arms = {}
        for name, edge_backend in (("approach_2", "off"), ("approach_1", edge)):
            rows, _res, errors = [], [], []
            for held in (False, True):
                r, _, e = _run(backend, True, held_out=held, lang=lang,
                               extractor=extractor_seam, router=router_seam,
                               edge=edge_backend)
                rows += r
                errors += e
            arms[name] = {"summary": scorer.aggregate(rows),
                          "fact_accuracy": scorer.fact_accuracy(rows),
                          "errors": errors,
                          "by_id": {x["ticket_id"]: x for x in rows}}
        # Which tickets the architecture actually moved, not just how the averages
        # differ: two arms can post the same recall while disagreeing about half the
        # corpus, and an average-only comparison hides that completely.
        a1, a2 = arms["approach_1"]["by_id"], arms["approach_2"]["by_id"]
        moved = sorted(tid for tid in a2
                       if tid in a1 and (a2[tid]["action"], a2[tid]["outcome"])
                       != (a1[tid]["action"], a1[tid]["outcome"]))
        out[lang] = {"arms": {k: {kk: vv for kk, vv in v.items() if kk != "by_id"}
                              for k, v in arms.items()},
                     "moved_ticket_ids": moved, "n_moved": len(moved)}
    return out


def _approach_report_lines(cmp: dict, *, edge: str, backend: str) -> list[str]:
    ceiling = edge == "oracle"
    L = ["# Approach comparison — read the customer, or translate at the edge?", "",
         f"Proposer backend: **{backend}** · Approach 1 translator: **{edge}** · gate ON · "
         "full corpus (seed + held-out), 97 tickets per language.", ""]
    if ceiling:
        L += ["> **The Approach 1 arm here is an upper bound, not a measurement of a "
              "translator.** `oracle` returns the English ticket each non-English ticket "
              "was generated from (`variant_of`), so its translations are exact by "
              "construction. No deployed translator can do better. Read this arm as "
              "\"the best Approach 1 could possibly do\", and judge a real translator "
              "against it rather than against Approach 2 alone.", ""]
    L += ["| Lang | Approach | Recall | Hallucination | Handoff precision | Fact accuracy (M-3) | Tickets moved |",
          "| --- | --- | --- | --- | --- | --- | --- |"]
    for lang in ALL_LANGS:
        block = cmp[lang]
        for name, label in (("approach_2", "2 — read directly"), ("approach_1", "1 — translate")):
            arm = block["arms"][name]
            c, fa = arm["summary"]["counts"], arm["fact_accuracy"]
            moved = block["n_moved"] if name == "approach_1" else ""
            L.append(
                f"| {lang} | {label} | "
                f"{stats.fmt_rate(c['answerable_correct'], c['answerable'])} | "
                f"{stats.fmt_rate(c['hallucination'], c['resolved'])} | "
                f"{stats.fmt_rate(c['handoffs_justified'], c['handoffs_pred'])} | "
                f"{stats.fmt_rate(fa['exact'], fa['n'])} | {moved} |")
    L += [""]
    for lang in ALL_LANGS:
        ids = cmp[lang]["moved_ticket_ids"]
        L.append(f"- **{LANG_LABELS[lang]}**: the architecture changed the outcome on "
                 f"{len(ids)}/97 tickets — `{', '.join(ids) or 'none'}`")
    L += [""]
    return L


def _recommendation_lines(cmp: dict, *, edge: str) -> list[str]:
    """BRD §16 item 10: a written recommendation WITH the evidence behind it.

    Derived from the run rather than written ahead of it. The comparison the English
    row makes possible is the load-bearing one: under Approach 1 every language is
    reduced to the English pipeline, so English is simultaneously the control and
    Approach 1's ceiling for every other language.
    """
    en_ceiling = cmp["en"]["arms"]["approach_2"]["summary"]
    ceiling_recall = en_ceiling["resolution_recall"]

    L = ["## Recommendation", ""]
    beats_ceiling, below_ceiling = [], []
    for lang in ALL_LANGS:
        if lang == "en":
            continue
        direct = cmp[lang]["arms"]["approach_2"]["summary"]["resolution_recall"]
        (beats_ceiling if (direct or 0) >= (ceiling_recall or 0) else below_ceiling).append(
            (lang, direct))

    L += ["**Approach 1's ceiling is the English arm.** Translating at the edge makes every "
          "language run the English pipeline, so no amount of translation quality can take a "
          "translated language past what English itself scores. On this run that ceiling is "
          f"a resolution recall of {_pct(ceiling_recall)}.", ""]
    if beats_ceiling:
        langs = ", ".join(f"{LANG_LABELS[l]} ({_pct(r)})" for l, r in beats_ceiling)
        L += [f"Read directly, {langs} already meet or beat that ceiling. For those languages "
              "Approach 1 cannot win, and the recommendation is **Approach 2 — read the "
              "customer's language directly**.", ""]
    if below_ceiling:
        langs = ", ".join(f"{LANG_LABELS[l]} ({_pct(r)})" for l, r in below_ceiling)
        L += [f"Read directly, {langs} score below the ceiling, so Approach 1 has headroom "
              "there in principle. Whether a real translator reaches it is the question the "
              "`--edge llm` arm answers; the `oracle` arm only shows the room exists.", ""]

    L += ["**Three reasons the recommendation does not flip even where the headroom exists.**", "",
          "1. *Approach 1 adds a failure mode the gate cannot see.* A mistranslation becomes "
          "an English message that reads perfectly, and every downstream step — routing, "
          "extraction, the proposer, the gate — treats it as what the customer said. FR-21's "
          "audit trail exists precisely because nothing else in the pipeline can catch it.",
          "2. *It puts a model call on the critical path of every ticket*, including the ones "
          "a keyword router would have resolved offline for nothing.",
          "3. *The measured gap is small and the intervals overlap.* Read the raw counts in "
          "the table above before treating any of these differences as real.", ""]
    L += ["**What would change this recommendation:** a language whose direct-read recall sits "
          "well below the English ceiling with non-overlapping intervals, or a policy that "
          "needs more than one fact read from the customer's prose (A1) — at which point the "
          "per-language extraction cost rises and a single translation step starts to pay for "
          "itself.", ""]
    if edge == "oracle":
        L += ["**Evidence limit.** This recommendation rests on the oracle arm, which is an "
              "upper bound rather than a translator. It is sound as a *ceiling* argument — it "
              "rules Approach 1 out where even perfect translation loses — and it cannot "
              "settle the cases where the ceiling is above the direct-read score. Those need "
              "`--compare-approaches --edge llm`.", ""]
    return L


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


def _write_multilingual_report(header, results, deep):
    en = results["en"]
    scope = " + ".join(LANG_LABELS[lang] for lang in ALL_LANGS)
    L = ["# Multilingual Benchmark Report", "",
         f"Backend: **{en['backend']}** · lang scope: **{scope}** (`--all-langs`) · "
         f"snapshot {header['dataset_date']}", "", "## Run header", ""]
    L += [f"- {line}" for line in _header_lines(header)]
    for lang, r in results.items():
        if r["errors"]:
            L += ["", f"## Routing errors ({lang}, isolated, not fatal)", ""]
            L += [f"- `{e['ticket_id']}` (lang={e['lang']!r}): {e['error']}" for e in r["errors"]]
    L += [""]
    for lang in ALL_LANGS:
        L += _calibration_disclaimer(lang)
    ns = " · ".join(f"{LANG_LABELS[lang]} n={results[lang]['on']['n']}" for lang in ALL_LANGS)
    L += ["## Cross-language table (gate ON, seed set)", "",
          f"{ns}.", "",
          "| Metric | " + " | ".join(LANG_LABELS[lang] for lang in ALL_LANGS) + " | Target |",
          "| --- | " + " | ".join("---" for _ in ALL_LANGS) + " | --- |"]
    for key, name, target in _CROSS_METRIC_ROWS:
        cells = " | ".join(_fmt(results[lang]["on"], key) for lang in ALL_LANGS)
        L.append(f"| {name} | {cells} | {target} |")
    verdicts = ", ".join(
        f"{LANG_LABELS[lang]} **{'PASS' if results[lang]['won'] else 'FAIL'}**"
        for lang in ALL_LANGS)
    L += ["", f"Win condition (seed set, all five clauses): {verdicts}.", ""]

    L += ["## Both win-condition scopes, all three original clauses (Part 3b)", "",
          "The win condition was calibrated against six tiers (`clean_return`, `wismo`, `adversarial`, "
          "`precedence`, `unanswerable`, `ask`). T8 added `fault` and `safety` specifically to give M-1 "
          "and M-2 a real denominator; folding them into the original three clauses below changes the "
          "verdict. Both scopes, raw counts beside every rate:", "",
          "| Lang | Scope | n | Recall | Hallucination | Handoff precision | Verdict |",
          "| --- | --- | --- | --- | --- | --- | --- |"]
    for lang in ALL_LANGS:
        for scope_name, scope_label in (("six_tier", "original six"), ("eight_tier", "all eight")):
            d = deep["scopes"][lang][scope_name]
            s = d["summary"]
            L.append(f"| {lang} | {scope_label} | {d['n']} | {_fmt(s, 'resolution_recall')} | "
                     f"{_fmt(s, 'hallucination_rate')} | {_fmt(s, 'handoff_precision')} | "
                     f"{'WIN' if d['won'] else 'FAIL'} |")
    hp_notes = []
    for lang in ALL_LANGS:
        hp = deep["scopes"][lang]["eight_tier"]["summary"]["handoff_precision"]
        hp_notes.append(f"{LANG_LABELS[lang]} {hp:.4f}")
    L += ["", f"_All-eight handoff precision against a >= 0.85 threshold: {', '.join(hp_notes)}._", ""]

    L += ["## M-1 (silent fact error): six-tier scope vs the full-corpus headline (Part 3b)", "",
          "M-1 is zero only under the six-tier scope that excludes `fault` and `safety` -- the two tiers "
          "added specifically to give it a real denominator. The full-corpus figure (seed + held-out, "
          "all 8 tiers) is the headline; the six-tier figure is labeled explicitly, never presented bare.",
          ""]
    L += ["| Lang | Scope | n (resolved) | M-1 (refined) | M-1 (literal reading) |",
          "| --- | --- | --- | --- | --- |"]
    for lang in ALL_LANGS:
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
          "Each language is scored over the full corpus (seed + held-out, 97 tickets). Non-English "
          "ids are mapped through `variant_of` before comparing membership with English.", ""]
    rf = deep["route_fallback"]
    for lang in ALL_LANGS:
        m = rf["by_lang"][lang]
        L.append(f"- {LANG_LABELS[lang]}: **{m['count']}/{m['n']}**")
    for lang, pair in rf["pairs"].items():
        L += [f"- Common with English (mapped through `variant_of`, {lang}): **{len(pair['common'])}**",
              f"- English-only vs {lang} ({len(pair['en_only'])}): `{', '.join(pair['en_only'])}`",
              f"- {LANG_LABELS[lang]}-only, canonical id ({len(pair['other_only_canon'])}): "
              f"`{', '.join(pair['other_only_canon'])}`"]
    L += [""]

    L += ["## fault_decisive: the fault tier's real denominator (Part 3b)", "",
          "Of the 17 fault-tier tickets, some have a gold `defective` that cannot change the licensed "
          "outcome (a higher-priority rule already fixes it) -- a flat fault-tier average credits the "
          "extractor on tickets where the fact it read could not have mattered. Identical across "
          "languages: gold facts resolve through `variant_of` to the same English record and the same "
          "`kb/rules.json`.", ""]
    for lang in ALL_LANGS:
        fd = deep["fault_decisive"][lang]
        L.append(f"- {lang}: decisive **{fd['decisive']}/{fd['n']}**, "
                 f"inert `{', '.join(fd['inert_ids'])}`")
    L += [""]

    L += _fact_accuracy_lines(deep)
    L += _provenance_lines(deep)
    L += _reply_language_lines(deep)

    L += ["## Extractor agreement (M-6)", "",
          "How often the keyword and model extractors read `defective` the SAME way on the same "
          "tickets (agreement, not accuracy against gold). `scorer.extractor_agreement` had no "
          "caller before this fix -- wired in here, seed set, gate ON.", ""]
    for lang, r in results.items():
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

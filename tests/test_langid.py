"""Measures the language detector instead of trusting it.

`agent/langid.py` decides a published number (M-5), so its own error rate has to be
a measured quantity rather than an assumption. The corpus test below is the real
one: 291 tickets whose language is declared in the fixtures, scored against what the
detector says, with the result pinned exactly so that a later nudge to the word
lists shows up as a failing test rather than as a quietly better number.

The pinned property that matters most is **zero misidentifications**. The detector
is allowed to abstain as often as it needs to; it is not allowed to call a Spanish
ticket Indonesian. M-5 excludes abstentions from its denominator, so an abstention
costs coverage and nothing else, while a misidentification would corrupt the rate.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agent import langid

TICKETS = json.loads((ROOT / "fixtures" / "tickets.json").read_text(encoding="utf-8"))["tickets"]

# Measured, then pinned -- not chosen and then satisfied. Re-running the detector
# over the fixtures produces exactly these. If a word-list edit moves them, this
# test says so and the new numbers have to be argued for in the diff rather than
# absorbed silently.
EXPECTED_DECIDED = {"en": 86, "es": 93, "id": 88}
EXPECTED_ABSTAINED = {"en": 11, "es": 4, "id": 9}


def _by_lang() -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for t in TICKETS:
        out.setdefault(t.get("lang", "en"), []).append(t)
    return out


def test_the_detector_never_misidentifies_a_ticket() -> None:
    """The load-bearing property. Abstention is fine; a wrong answer is not."""
    wrong = []
    for t in TICKETS:
        got = langid.detect(t["message"])
        if got is not None and got != t.get("lang", "en"):
            wrong.append((t["id"], t.get("lang", "en"), got, langid.scores(t["message"])))
    assert wrong == [], f"detector misread {len(wrong)} tickets: {wrong[:5]}"


def test_detection_counts_are_exactly_as_measured() -> None:
    decided, abstained = {}, {}
    for lang, tickets in _by_lang().items():
        results = [langid.detect(t["message"]) for t in tickets]
        decided[lang] = sum(r is not None for r in results)
        abstained[lang] = sum(r is None for r in results)
    assert decided == EXPECTED_DECIDED
    assert abstained == EXPECTED_ABSTAINED


def test_corpus_coverage_is_reported_not_assumed() -> None:
    """Coverage is a real limit of the metric, so it gets asserted as a fact."""
    total = sum(EXPECTED_DECIDED.values()) + sum(EXPECTED_ABSTAINED.values())
    assert total == len(TICKETS) == 291
    assert sum(EXPECTED_DECIDED.values()) == 267


@pytest.mark.parametrize("text, expected", [
    ("Your order ORD-1001 is eligible for return under RET-007.", "en"),
    ("Su pedido no es elegible para la devolución dentro de los días.", "es"),
    ("Pesanan Anda tidak bisa dikembalikan karena sudah lewat dari batas hari.", "id"),
])
def test_representative_replies_are_read_correctly(text: str, expected: str) -> None:
    assert langid.detect(text) == expected


@pytest.mark.parametrize("text", ["", "ORD-1001", "??", "RET-007 RET-012", "ok"])
def test_thin_evidence_abstains_rather_than_guessing(text: str) -> None:
    assert langid.detect(text) is None


def test_accents_are_not_required_for_spanish() -> None:
    """The Spanish word list is stored unaccented; real Spanish is not."""
    accented = "Su envío no ha llegado y quiero la devolución del pedido."
    unaccented = "Su envio no ha llegado y quiero la devolucion del pedido."
    assert langid.detect(accented) == "es"
    assert langid.detect(unaccented) == "es"
    assert langid.scores(accented) == langid.scores(unaccented)


def test_margin_rule_abstains_on_a_genuine_tie() -> None:
    """Two languages equally supported is undetermined, not alphabetical order."""
    tie = "no no el the"          # 'no'/'el' -> es, 'no'/'the' -> en
    sc = langid.scores(tie)
    assert sc["en"] == sc["es"] > 0, sc
    assert langid.detect(tie) is None


def test_min_hits_is_actually_enforced() -> None:
    """One matching word is not enough, however unambiguous it looks."""
    assert langid.scores("yang")["id"] == 1
    assert langid.detect("yang") is None
    assert langid.detect("yang sudah") == "id"

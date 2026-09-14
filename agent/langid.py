"""Which language is a piece of text written in? (FR-7 / M-5 support)

Deliberately a function-word counter, not a model. Three reasons.

1. Global constraint 4: no test may require an API key. M-5 has to be computable on
   the offline path, in CI, for free.
2. The thing being measured is whether replies come back in the customer's language.
   Today every reply is an English template (`agent/agent.py::_return_reply` and the
   handoff bodies), so the expected M-5 result is 100% English / 0% elsewhere. A
   detector that can tell English from not-English is sufficient for that, and a
   model call would be a large dependency bought to confirm a foregone answer.
3. A frozen word list is auditable. A reader can see exactly why a string was called
   Spanish; they cannot with an embedding.

**This module is scanned by `eval/check_lexicon_freeze.py`.** It holds word lists
that feed a published metric, which is exactly the thing the freeze exists to stop
anyone quietly tuning. Editing these tuples after tickets exist is drift and the
checker will say so.

## What it is not

Not a general-purpose language identifier. It knows three languages, it is tuned for
short customer-support prose, and it returns `None` rather than guessing when the
evidence is thin. `None` is a real answer here and is reported as `undetermined`,
never silently bucketed as a mismatch -- the same None-vs-False discipline FR-5
applies to facts. Its own accuracy against the 291 known-language ticket messages is
measured and published rather than asserted; see `tests/test_langid.py` and the
"Reply language (M-5)" section of the multilingual report.
"""
from __future__ import annotations

import re
import unicodedata

# Function words and high-frequency domain words, chosen to be cheap to verify by
# eye. Frozen before M-5 was first reported. Entries are matched as whole words
# against a case-folded, accent-stripped tokenisation, so "envio" also catches
# "envío" and no entry needs an accented twin.
#
# Overlaps between languages are deliberate and harmless: scoring is by COUNT, so a
# word both Spanish and Indonesian use (e.g. "no") costs both sides equally. What
# matters is that each list holds enough words the other two do not use.
_EN = ("the", "and", "your", "you", "for", "with", "this", "that", "have", "has",
       "will", "been", "are", "was", "from", "our", "we", "can", "not", "under",
       "order", "return", "refund", "team", "please", "sorry", "within", "days",
       "eligible", "someone", "follow", "here", "because", "its", "it")
_ES = ("el", "la", "los", "las", "de", "del", "que", "en", "un", "una", "por",
       "con", "para", "su", "se", "es", "esta", "este", "pedido", "devolucion",
       "reembolso", "equipo", "gracias", "lo", "al", "mi", "nos", "ha", "hemos",
       "dias", "dentro", "porque", "pero", "como", "tu")
_ID = ("yang", "dan", "di", "ke", "untuk", "dengan", "ini", "itu", "tidak", "sudah",
       "akan", "kami", "kamu", "anda", "dari", "pada", "pesanan", "pengembalian",
       "tim", "terima", "kasih", "saya", "bisa", "belum", "karena", "atau", "juga",
       "hari", "dalam", "sangat", "masih", "kalau")

LANG_WORDS: dict[str, frozenset[str]] = {
    "en": frozenset(_EN),
    "es": frozenset(_ES),
    "id": frozenset(_ID),
}

# A decision needs at least this many matched words in the winning language, and it
# must beat the runner-up by at least this margin. Both guard the same failure: a
# one-word coincidence deciding the language of a short string. Tuned once, against
# the ticket corpus, and then left alone -- `tests/test_langid.py` pins the accuracy
# these produce so a later nudge to make one case pass shows up as a broken test.
MIN_HITS = 2
MIN_MARGIN = 1

_TOKEN = re.compile(r"[a-z]+")


def _tokens(text: str) -> list[str]:
    """Case-fold, strip accents, split on non-letters.

    Accent stripping is what lets the Spanish list stay unaccented while still
    matching real Spanish ("envío" -> "envio"). It costs nothing in English and
    Indonesian, neither of which relies on accents.
    """
    folded = unicodedata.normalize("NFKD", text.casefold())
    stripped = "".join(c for c in folded if not unicodedata.combining(c))
    return _TOKEN.findall(stripped)


def scores(text: str) -> dict[str, int]:
    """Matched-word count per language. Exposed so a disagreement can be explained
    rather than just reported."""
    toks = _tokens(text)
    return {lang: sum(t in words for t in toks) for lang, words in LANG_WORDS.items()}


def detect(text: str) -> str | None:
    """Best-supported language, or `None` when the evidence is too thin to say.

    `None` means undetermined, not "no match" and not "wrong language". Callers must
    keep it as its own category -- counting it as a mismatch would inflate M-5's
    failure rate with cases the detector simply could not read.
    """
    sc = scores(text)
    ranked = sorted(sc.items(), key=lambda kv: (-kv[1], kv[0]))
    (top_lang, top), (_, second) = ranked[0], ranked[1]
    if top < MIN_HITS or top - second < MIN_MARGIN:
        return None
    return top_lang

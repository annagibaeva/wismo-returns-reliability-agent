"""Approach 1: translate the customer's message at the edge, then run English. (FR-6, FR-21)

The whole architectural question this project exists to answer, reduced to one seam.

* **Approach 2** (`off`) — the system reads the customer's own language. Routing uses
  that language's lexicons, extraction reads the original text. This is what the rest
  of the repository measures.
* **Approach 1** (`oracle` / `llm`) — the message is translated into English at the
  edge and *everything downstream runs as if the customer wrote English*: English
  lexicons, English extractor prompt, English proposer. One switch, one seam,
  no forked pipeline (FR-6 asks for a flag, not a branch).

## The two Approach 1 backends, and why both exist

`llm` is the real thing: a model translates the message, and the result is whatever a
production translate-at-the-edge deployment would actually get.

`oracle` is the ceiling. Every non-English ticket carries `variant_of` pointing at the
English ticket it was translated FROM, so the perfect English translation is already
in the fixtures. `oracle` returns it. That measures the question "how well would
Approach 1 do if translation were free and flawless?" -- which is the only fair upper
bound to judge the real translator against, and it runs offline for nothing.

**`oracle` is an upper bound and must never be reported as Approach 1's performance.**
It uses the fixture that the non-English ticket was generated from, so it is exact by
construction in a way no deployed translator can be. Every report that prints it says
so. It touches no gold ANSWER -- `expected` is never read here -- so it cannot leak
the thing being scored, only the thing being translated.

The comparison that answers the BRD's question is therefore three-way, not two-way:
Approach 2, Approach 1 at its ceiling, and Approach 1 as really built. If Approach 2
beats the *ceiling*, no improvement in translation quality can rescue Approach 1.
"""
from __future__ import annotations

from agent import cache, llm
from agent.schemas import AuditLogger

# Frozen as a frozenset rather than a tuple for the same reason as
# `extract.EXTRACTORS`: the freeze checker's AST walk records top-level tuples of
# strings as lexicons, and a backend-name tuple is not a lexicon.
EDGE_BACKENDS = frozenset({"off", "oracle", "llm"})

_CALL = "translate_to_english"


def translate_to_english(ticket: dict, *, backend: str = "off",
                         audit: AuditLogger | None = None) -> tuple[str, str]:
    """Return `(text, lang)` for everything downstream to use.

    With `off`, that is the ticket's own message and its own language -- Approach 2,
    byte-identical to not calling this at all. With `oracle` or `llm` it is English
    text and the literal `"en"`, which is what makes the rest of the pipeline switch
    to English lexicons and the English extractor without knowing why.

    FR-21: when a translation happens, BOTH the original and the translation are
    written to the audit trail, so a changed meaning can be traced to the step that
    changed it rather than inferred from a wrong answer three stages later.
    """
    if backend not in EDGE_BACKENDS:
        raise ValueError(f"unknown edge backend {backend!r}; known: {sorted(EDGE_BACKENDS)}")

    msg = ticket["message"]
    lang = ticket.get("lang", "en")
    if backend == "off" or lang == "en":
        # An English ticket is not translated even under Approach 1. Round-tripping
        # English through a translator would introduce a difference between the two
        # approaches on the one language where there is nothing to translate, and the
        # English arm is the control that holds the comparison together.
        return msg, lang

    english = _oracle(ticket) if backend == "oracle" else _llm_translate(msg, lang)
    if english is None:
        # Could not translate. Approach 1 with no translation is the original text
        # being fed to English lexicons -- which is exactly what the failure looks
        # like in production, so it is scored rather than hidden. The audit records
        # it; `lang` stays non-English so downstream sees the truth.
        if audit is not None:
            audit.decision("translate_at_edge", msg,
                           {"backend": backend, "from": lang, "translated": None,
                            "note": "translation failed; original text passed through"})
        return msg, lang

    if audit is not None:
        # FR-21, both halves. The original is the evidence; without it the audit
        # trail records a claim about a message nobody can check.
        audit.decision("translate_at_edge", msg,
                       {"backend": backend, "from": lang, "to": "en",
                        "original": msg, "translated": english})
    return english, "en"


def _oracle(ticket: dict) -> str | None:
    """The English ticket this one was translated from. Import is local so that the
    agent package does not take a dependency on the fixtures at import time."""
    from services_mock import data

    source_id = ticket.get("variant_of")
    if not source_id:
        return None
    for t in data.all_tickets(None):
        if t["id"] == source_id:
            return t["message"]
    return None


_SYSTEM = """You are a translation step in a customer-support pipeline. Translate the \
customer's message into English.

Rules:
- Translate meaning, not words. Keep the customer's tone, including informality, \
frustration and typos where they carry meaning.
- Keep order ids, tracking numbers, product names and dates exactly as written.
- If part of the message is already English, leave that part as it is.
- Do not answer the customer, do not summarise, do not add or remove information, \
and do not soften a complaint.
- Reply with the English translation and nothing else."""

_USER = """Translate this {lang} customer message into English:

{msg}"""


def _readable(answer) -> bool:
    return isinstance(answer, str) and bool(answer.strip())


def _llm_translate(msg: str, lang: str) -> str | None:
    # Same shape as `extract._llm_extract`, and for the same reasons -- the request
    # dict is built once, hashed for the cache key, then splatted into the call, so
    # nothing that shapes the response can be missing from the key.
    request = {
        "model": llm.MODEL, "max_tokens": 1024, "system": _SYSTEM,
        "messages": [{"role": "user", "content": _USER.format(lang=lang, msg=msg)}],
        **llm.sampling_params(llm.MODEL),
    }
    hit = cache.get(_CALL, request, _readable)
    if hit is not None:
        return hit

    import anthropic
    client = anthropic.Anthropic()
    # The credentials boundary sits here, on local state, before the wire -- see the
    # long note in `agent/extract.py::_llm_extract`. A keyless run must fail loudly
    # rather than return "could not translate" for every ticket and produce a results
    # file indistinguishable from a real Approach 1 measurement.
    if all(getattr(client, name, None) is None
           for name in ("api_key", "auth_token", "credentials")):
        raise RuntimeError(
            "the edge translator has no Anthropic credentials configured (set "
            "ANTHROPIC_API_KEY); a missing key is a broken run, not an untranslatable message")
    try:
        resp = client.messages.create(**request)
    except Exception:
        # Every exception, no retry, nothing cached -- identical reasoning to the
        # extractor: a cached failure is a transient outage frozen into the artifact.
        return None

    text = _text_of(resp)
    if not _readable(text):
        return None
    cache.put(_CALL, request, text)
    return text


def _text_of(resp) -> str | None:
    blocks = getattr(resp, "content", None) or []
    parts = [getattr(b, "text", None) for b in blocks]
    joined = "".join(p for p in parts if isinstance(p, str)).strip()
    return joined or None

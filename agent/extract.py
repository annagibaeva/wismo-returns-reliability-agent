"""The fact-reading seam -- the ONLY module that knows whether a real LLM read the
customer's prose, mirroring the provider split in `agent/llm.py`.

`defective` is the one fact `resolve_ticket` reads out of the customer's own words
instead of the order database. Every other fact comes from `order_api.order_facts`
and is language-independent, which makes `defective` the single fact a language
barrier can corrupt -- and it controls RET-020 (priority 90, the rule that lets a
faulty item come back after the normal window closes).

Two implementations behind one signature:
  - "stub" (default, key-free): the keyword matcher that used to run inline in
            `resolve_ticket`, unchanged. It answers every message -- a message with
            no matching keyword reads as a confident claim that the item works,
            `defective=False`, never `None`. This is a real limitation of the stub,
            not an oversight: a keyword list has no way to represent "I don't know
            whether this is defective," only "I didn't see one of these words." A
            model backend can tell those apart; the keyword backend structurally
            cannot, and demonstrating that gap is part of what this project is for.
  - "llm"  (arrives in a later task; needs ANTHROPIC_API_KEY): entitled to return
            `None` when the message doesn't say. `kb/evaluator.py` raises
            `MissingFact` on a `None` input, so RET-020 simply cannot fire and the
            ticket falls through to a human instead of being ruled on a fact nobody
            actually stated.

Nothing here reads gold facts or imports from `eval/` -- the extractor only ever
sees what the agent itself is given: the message and a language tag.
"""
from __future__ import annotations

from .lexicons import LEXICONS


def extract_facts(msg: str, lang: str = "en", backend: str = "stub") -> dict:
    if backend == "llm":
        raise NotImplementedError("llm fact extraction arrives in a later task")
    return _stub_extract(msg, lang)


def _stub_extract(msg: str, lang: str) -> dict:
    # Deferred: agent.py imports this module, so importing it back at module scope
    # would race the load order. By the time extract_facts is actually called,
    # agent.agent has always finished importing.
    from . import agent as _agent
    lex = LEXICONS[lang]
    return {"defective": _agent._has(msg.lower(), lex["_DEFECTIVE"])}

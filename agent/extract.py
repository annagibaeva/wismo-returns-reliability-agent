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
sees what the agent itself is given: the message and a language tag. And nothing
here may return a fact outside `PROSE_FACTS`; see below for why that is enforced
rather than merely documented.
"""
from __future__ import annotations

from .lexicons import LEXICONS

# The complete set of facts any backend here is allowed to return. `defective` is the
# one fact read out of the customer's prose; every other fact in `resolve_ticket`'s
# dict comes from `order_api.order_facts` and is authoritative. That dict is merged
# *over* the order facts, so a backend returning `final_sale` or `order_value` --
# hallucinated, or `None` -- would silently overwrite the order record with prose,
# which is precisely the failure class this project exists to measure. Checked in
# `extract_facts` rather than at the merge site because the seam is where the contract
# lives: every caller is covered, and an out-of-contract key fails loudly and names
# the backend that broke it instead of being dropped where nobody sees it.
PROSE_FACTS = frozenset({"defective"})


def extract_facts(msg: str, lang: str = "en", backend: str = "stub") -> dict:
    if backend == "llm":
        raise NotImplementedError("llm fact extraction arrives in a later task")
    facts = _stub_extract(msg, lang)
    extra = sorted(set(facts) - PROSE_FACTS)
    if extra:
        raise ValueError(
            f"{backend!r} extractor returned out-of-contract fact(s) {extra}; only "
            f"{sorted(PROSE_FACTS)} may be read from the message -- every other fact "
            "belongs to the order database and must not be overwritten from prose")
    return facts


def _stub_extract(msg: str, lang: str) -> dict:
    # Deferred: agent.py imports this module, so importing it back at module scope
    # would race the load order. By the time extract_facts is actually called,
    # agent.agent has always finished importing.
    from . import agent as _agent
    lex = LEXICONS[lang]
    return {"defective": _agent._has(msg.lower(), lex["_DEFECTIVE"])}

"""Pins the prompts the model backends send, the way tests/test_lexicon_freeze.py pins
the keyword lists — because they are the same kind of thing.

The project freezes lexicons because words chosen *after* seeing which tickets fail are
words tuned to those tickets, and a metric scored against tuned words measures nothing.
The extractor prompt is functionally a lexicon. It is the instruction that decides what
counts as a claim that an item is faulty, in every language at once. After watching
Spanish tickets fail, adding "Spanish speakers often phrase faults as X" to `_SYSTEM`
would lift the score by exactly the mechanism `eval/check_lexicon_freeze.py` exists to
refuse — through a door that check does not cover, since a prompt is prose, not a tuple
of strings. Nothing else notices: the prompt has no snapshot, no hash, and no test.

So both model prompts are pinned here by hash. Not just `_SYSTEM`: the user template
and the tool schema shape the answer too, and the schema's `description` fields are the
quietest place a hint could be parked. `_ANSWERS` is pinned with them because it is the
map from the schema's enum to the fact, and an enum renamed on one side only would be a
silent behaviour change with no other witness.

The proposer prompt in agent/llm.py is pinned too, with the difference stated plainly.
The extractor's prompt shapes *fact-reading*, and fact-reading in three languages is the
thing this project measures — that pin is load-bearing. The proposer's prompt shapes
*reasoning*, which the grounding gate is there to catch rather than to trust, so its pin
is defence in depth. But the cheat is available on both sides ("Spanish customers often
mean X when they say Y" works just as well in a reasoner prompt), the cost of pinning is
one constant, and an unpinned prompt beside a pinned one is an invitation.

Changing a prompt on purpose is allowed and takes one deliberate step: run the prompt
through the same hash and update the literal below, in the diff, next to this reasoning.
That is the friction the lexicon pins impose, for the same reason.

These hashes also pin the T7 cache keys, since the prompt is hashed into them: a prompt
edit that slipped past review would silently invalidate every cached response, and this
test names it first.
"""
from __future__ import annotations

import ast
import copy
import hashlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agent import extract as extract_mod
from agent import llm as llm_mod
from agent import route as route_mod


def _sha256(value) -> str:
    """Canonical JSON, then sha256 — so a dict's key order cannot change the hash and a
    reordered schema is correctly reported as unchanged."""
    blob = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _hashes(module, names: tuple[str, ...]) -> dict[str, str]:
    return {name: _sha256(getattr(module, name)) for name in names}


# --- the pins ---------------------------------------------------------------- #
#
# Per-constant rather than one combined hash, so a failure names the part that moved
# instead of saying only that something did.

EXTRACTOR_PARTS = ("_SYSTEM", "_USER", "_SCHEMA", "_ANSWERS")
EXTRACTOR_PROMPT_SHA256 = {
    "_SYSTEM": "726247aec695f839add77ffb3e327397f38f2cd6521806c08becb4901aa4e109",
    "_USER": "27d7c83e274c4d6eb5a4ed762749ceb44bab52137141ee63f9893b3b8f413713",
    "_SCHEMA": "a63e0341a46a65319054bae0b5bc19e02fb9c3e41377e3df4b9dc65844100c25",
    "_ANSWERS": "2090bd9370aa7183591714094d56356c4ef403096a92db2838e464c81d298073",
}

PROPOSER_PARTS = ("_SYSTEM", "_SCHEMA")
PROPOSER_PROMPT_SHA256 = {
    "_SYSTEM": "3670dea6789d213dc4520ddae9d52f48c84e2ac4ea5aa0bd5ed881d8820c224b",
    "_SCHEMA": "2a1ac9a70d96a33b51bd194d7c8544306c659942111b643d379de10ce84c63e6",
}

ROUTER_PARTS = ("_SYSTEM", "_USER", "_SCHEMA")
ROUTER_PROMPT_SHA256 = {
    "_SYSTEM": "28321f45dbfb0b46a724101231fb6a85430732084a39a3f6a77f38090bafd8a2",
    "_USER": "a497c8855248f2acfc08f2e91e28543b9fecf0d4a11686d3879e3923cc1350c8",
    "_SCHEMA": "063984eddde01901e5442726f1efc846f5a95762826e78edb2962ed78b1ffd86",
}

_UPDATE_HINT = (
    "\n\nIf this change is intentional, update the hash literal in "
    "tests/test_prompt_freeze.py in the same commit — and say in the commit message why "
    "the prompt changed. A prompt edited after seeing which tickets fail is a tuned "
    "lexicon wearing prose, and the numbers scored against it are not comparable to the "
    "ones already published."
)


def test_extractor_prompt_is_frozen() -> None:
    """The load-bearing one: this prompt is what reads facts out of the customer's words."""
    assert _hashes(extract_mod, EXTRACTOR_PARTS) == EXTRACTOR_PROMPT_SHA256, (
        "the fact-extractor prompt in agent/extract.py has changed." + _UPDATE_HINT)


def test_proposer_prompt_is_frozen() -> None:
    assert _hashes(llm_mod, PROPOSER_PARTS) == PROPOSER_PROMPT_SHA256, (
        "the proposer prompt in agent/llm.py has changed." + _UPDATE_HINT)


def test_router_prompt_is_frozen() -> None:
    assert _hashes(route_mod, ROUTER_PARTS) == ROUTER_PROMPT_SHA256, (
        "the intent-router prompt in agent/route.py has changed." + _UPDATE_HINT)


# --- the pins are not vacuous ------------------------------------------------ #

def test_the_pin_catches_the_cheat_it_exists_to_catch(monkeypatch: pytest.MonkeyPatch) -> None:
    """The exact edit: a language-specific hint appended after seeing Spanish tickets fail."""
    monkeypatch.setattr(extract_mod, "_SYSTEM", extract_mod._SYSTEM
                        + "\nSpanish speakers often phrase faults as 'no sirve'.")
    assert _hashes(extract_mod, EXTRACTOR_PARTS) != EXTRACTOR_PROMPT_SHA256


def test_the_pin_catches_a_hint_hidden_in_the_tool_schema(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """The quieter door. A schema description is prompt text the model reads too, so a
    pin that covered only `_SYSTEM` would leave the tuning route wide open."""
    tweaked = copy.deepcopy(extract_mod._SCHEMA)
    tweaked["input_schema"]["properties"]["defective"]["description"] += (
        " Treat 'no anda' as faulty.")
    monkeypatch.setattr(extract_mod, "_SCHEMA", tweaked)
    assert _hashes(extract_mod, EXTRACTOR_PARTS) != EXTRACTOR_PROMPT_SHA256


def test_a_single_changed_character_moves_the_hash(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(llm_mod, "_SYSTEM", llm_mod._SYSTEM + " ")
    assert _hashes(llm_mod, PROPOSER_PARTS) != PROPOSER_PROMPT_SHA256


def test_key_order_alone_does_not_move_the_hash() -> None:
    """The other half of non-vacuity: the pin must not fire on a no-op reformat, or the
    first false alarm teaches everyone to update the literal without reading it."""
    reordered = {k: extract_mod._SCHEMA[k] for k in reversed(list(extract_mod._SCHEMA))}
    assert _sha256(reordered) == EXTRACTOR_PROMPT_SHA256["_SCHEMA"]


# --- nothing prompt-shaped may be added without a decision ------------------- #
#
# Pinning today's constants is not enough on its own: a new module-level string that
# `_llm_extract` interpolates into the prompt would leave every pin above green. So the
# set of prompt-shaped constants is itself asserted, exhaustively, the way
# NON_LEXICON_MODULES asserts the set of unscanned agent/ modules.

_NOT_PROMPT = {
    "agent/extract.py": {
        "_CALL": "the cache-key label for this call site; never sent to the model",
    },
    "agent/llm.py": {
        "MODEL": "the model id, read from $AGENT_MODEL — a run knob, not prompt text, "
                 "and pinning it would break `AGENT_MODEL=... python eval/run_eval.py`. "
                 "It is inside the T7 cache key, so changing it cannot silently reuse "
                 "another model's answers.",
        "_CALL": "the cache-key label for this call site; never sent to the model",
    },
    "agent/route.py": {
        "_CALL": "the cache-key label for this call site; never sent to the model",
        "_UNREADABLE": "fail-closed sentinel reason; never sent to the model",
    },
}


def _module_constants(module) -> set[str]:
    """Module-level assignments whose value is a string or a mapping.

    Read from the source AST rather than `vars(module)` so that imported names are not
    swept in — `agent/extract.py` does `from .lexicons import LEXICONS`, and LEXICONS is
    a dict this test has no business pinning (it is frozen, per language, elsewhere).
    Strings and dicts are the two shapes prompt text arrives in here: a system prompt, a
    user template, a tool schema.
    """
    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Assign):
            names |= {t.id for t in node.targets if isinstance(t, ast.Name)}
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
    return {n for n in names if isinstance(getattr(module, n, None), (str, dict))}


_MODULES = [
    ("agent/extract.py", extract_mod, EXTRACTOR_PARTS),
    ("agent/llm.py", llm_mod, PROPOSER_PARTS),
    ("agent/route.py", route_mod, ROUTER_PARTS),
]


@pytest.mark.parametrize("rel,module,pinned", _MODULES, ids=[m[0] for m in _MODULES])
def test_every_prompt_shaped_constant_is_pinned_or_excused(rel, module, pinned) -> None:
    found = _module_constants(module)
    assert "_SYSTEM" in found, (
        f"the constant scan found no _SYSTEM in {rel}, so it is not reading the real "
        "module and every assertion here is vacuous")
    unaccounted = found - set(pinned) - set(_NOT_PROMPT[rel])
    assert not unaccounted, (
        f"{sorted(unaccounted)} are module-level text constants in {rel} that are neither "
        "pinned above nor listed in _NOT_PROMPT with a reason. If it reaches the model, "
        "pin it. If it does not, say so — in writing, in the diff.")


@pytest.mark.parametrize("rel,module,pinned", _MODULES, ids=[m[0] for m in _MODULES])
def test_the_excused_constants_still_exist_and_have_reasons(rel, module, pinned) -> None:
    """A stale excuse silently shrinks what the test above checks."""
    for name, reason in _NOT_PROMPT[rel].items():
        assert hasattr(module, name), f"_NOT_PROMPT[{rel!r}] excuses a gone constant: {name}"
        assert reason.strip(), f"_NOT_PROMPT[{rel!r}][{name!r}] has no reason"
        assert name not in pinned, f"{name} is both pinned and excused in {rel}"


def test_the_extractor_prompt_reaches_the_cache_key() -> None:
    """Why the two mechanisms belong in the same task: the pinned text *is* the key.

    Editing the prompt changes every extractor cache key, so cached answers from the old
    prompt become unreachable rather than being served under the new one.
    """
    from agent import cache

    request = {"model": "m", "max_tokens": 128, "temperature": 0,
               "system": extract_mod._SYSTEM, "tools": [extract_mod._SCHEMA],
               "tool_choice": {"type": "tool", "name": "message_facts"},
               "messages": [{"role": "user", "content": extract_mod._USER.format(msg="hi")}]}
    tuned = copy.deepcopy(request)
    tuned["system"] += "\nSpanish speakers often phrase faults as 'no sirve'."
    assert cache.key("extract.defective", request) != cache.key("extract.defective", tuned)

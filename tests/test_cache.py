"""Tests for the response cache (agent/cache.py), introduced in T7.

Covers the done-criterion (a second identical run makes zero provider calls, and the
key moves when the model or any part of the prompt moves), the property the cache
exists for (a fully cached run replays with no credentials and no `anthropic`
installed), the property it must never violate (a hit and a miss give identical
results), the failures it must not freeze (a timeout or an unreadable answer is never
stored), and the failure it must not hide (a corrupt entry raises instead of quietly
re-fetching — including through `_llm_extract`, where FR-5's blanket `except` would
otherwise turn it into a fabricated "the customer didn't say").

No test here needs an API key or a network (global constraint 4): the provider is
faked through `sys.modules["anthropic"]`, and `tests/conftest.py` points every test at
its own empty cache directory so the committed cache is neither read nor written.
"""
from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import kb
from agent import cache
from agent import extract as extract_mod
from agent import llm as llm_mod
from agent.agent import resolve_ticket
from agent.extract import extract_facts
from agent.llm import propose_return_decision
from services_mock import data

_DECISION = {"outcome": "ineligible", "cited_rule_ids": ["RET-001"], "rationale": "because"}


# --------------------------------------------------------------------------- #
# Offline provider double, counting every call it receives.
# --------------------------------------------------------------------------- #

def _tool_use(name: str, payload) -> types.SimpleNamespace:
    return types.SimpleNamespace(
        content=[types.SimpleNamespace(type="tool_use", name=name, input=payload)])


def _install_provider(monkeypatch, *, answer="yes", decision=None, raises=None, calls=None):
    """Fake `anthropic` for both seams at once, recording the kwargs of every call.

    Dispatches on `tool_choice`, so one double serves the extractor and the proposer and
    a call-counting test can watch a whole `resolve_ticket` run through one list.
    """
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    decision = _DECISION if decision is None else decision

    def create(**kwargs):
        if calls is not None:
            calls.append(kwargs)
        if raises is not None:
            raise raises
        tool = kwargs["tool_choice"]["name"]
        if tool == "message_facts":
            return _tool_use(tool, {"defective": answer})
        return _tool_use(tool, dict(decision))

    fake = types.ModuleType("anthropic")
    fake.Anthropic = lambda *a, **k: types.SimpleNamespace(
        api_key="not-a-real-key", auth_token=None, credentials=None,
        messages=types.SimpleNamespace(create=create))
    monkeypatch.setitem(sys.modules, "anthropic", fake)
    return calls


def _block_anthropic(monkeypatch):
    """Make `import anthropic` fail the way a bare CI checkout does."""
    class _NoAnthropic:
        def find_spec(self, name, path=None, target=None):
            if name == "anthropic":
                raise ModuleNotFoundError(f"No module named {name!r}", name=name)
            return None

    monkeypatch.delitem(sys.modules, "anthropic", raising=False)
    monkeypatch.setattr(sys, "meta_path", [_NoAnthropic(), *sys.meta_path])


def _entries() -> list[Path]:
    return sorted(cache.cache_dir().rglob("*.json"))


# --------------------------------------------------------------------------- #
# (1) the done-criterion: a second identical run makes zero provider calls
# --------------------------------------------------------------------------- #

def test_a_second_identical_extract_run_makes_zero_provider_calls(monkeypatch):
    calls = _install_provider(monkeypatch, answer="yes", calls=[])
    messages = ["la licuadora está rota", "the toaster won't turn on", "where is my order"]

    first = [extract_facts(m, lang="en", backend="llm") for m in messages]
    assert len(calls) == 3

    calls.clear()
    second = [extract_facts(m, lang="en", backend="llm") for m in messages]
    assert calls == [], "a repeated run reached the provider"
    assert second == first


def test_a_second_identical_proposer_run_makes_zero_provider_calls(monkeypatch):
    calls = _install_provider(monkeypatch, calls=[])
    facts = {"defective": True, "days_since_delivery": 40, "final_sale": False}
    rules = kb.rules()

    first = propose_return_decision(facts, rules, "please take it back", backend="llm")
    assert len(calls) == 1

    calls.clear()
    second = propose_return_decision(facts, rules, "please take it back", backend="llm")
    assert calls == []
    assert second == first


def test_a_second_identical_full_run_makes_zero_provider_calls(monkeypatch):
    """Both seams, through resolve_ticket, over the real ticket set — the headline claim."""
    calls = _install_provider(monkeypatch, calls=[])
    tickets = data.tickets()

    for t in tickets:
        resolve_ticket(t, backend="llm", use_gate=True, extractor="llm")
    assert len(calls) > 0, "the run made no provider calls at all; nothing was demonstrated"
    first_pass = len(calls)

    calls.clear()
    for t in tickets:
        resolve_ticket(t, backend="llm", use_gate=True, extractor="llm")
    assert calls == [], f"{len(calls)} provider calls on the second run (first made {first_pass})"


# --------------------------------------------------------------------------- #
# (2, 3) the key moves when the model moves, and when any part of the prompt moves
# --------------------------------------------------------------------------- #

_REQUEST = {
    "model": "claude-opus-4-8", "max_tokens": 128, "temperature": 0,
    "system": "you read customer messages", "tools": [{"name": "message_facts"}],
    "tool_choice": {"type": "tool", "name": "message_facts"},
    "messages": [{"role": "user", "content": "the blender is broken"}],
}

_FIELD_EDITS = [
    ("model", "claude-sonnet-4-5"),
    ("max_tokens", 129),
    ("temperature", 1),
    ("system", "you read customer messages, and Spanish faults are often 'no sirve'"),
    ("tools", [{"name": "message_facts", "description": "hint"}]),
    ("tool_choice", {"type": "auto"}),
    ("messages", [{"role": "user", "content": "the blender is fine"}]),
]


@pytest.mark.parametrize("field,value", _FIELD_EDITS, ids=[f[0] for f in _FIELD_EDITS])
def test_every_request_field_changes_the_key(field, value):
    """Not just model and system text. Everything in the request shapes the response, so
    everything is in the key — max_tokens and temperature included."""
    edited = {**_REQUEST, field: value}
    assert cache.key("extract.defective", edited) != cache.key("extract.defective", _REQUEST)


def test_the_key_is_stable_across_dict_ordering():
    """A reordered request is the same request; a key that moved would silently discard
    the whole cache on a cosmetic edit."""
    reordered = {k: _REQUEST[k] for k in reversed(list(_REQUEST))}
    assert cache.key("extract.defective", reordered) == cache.key("extract.defective", _REQUEST)


def test_the_call_site_label_separates_two_seams():
    assert cache.key("llm.return_decision", _REQUEST) != cache.key("extract.defective", _REQUEST)


def test_the_format_version_is_in_the_key(monkeypatch):
    """A future format change retires old entries by making them unreachable, rather
    than reinterpreting them under new rules."""
    before = cache.key("extract.defective", _REQUEST)
    monkeypatch.setattr(cache, "CACHE_VERSION", cache.CACHE_VERSION + 1)
    assert cache.key("extract.defective", _REQUEST) != before


def test_the_stored_key_is_the_hash_of_exactly_what_was_sent(monkeypatch):
    """The structural guarantee, checked rather than asserted: recomputing the key from
    the kwargs the provider actually received lands on the file that was written. Nothing
    that shaped the response can have been left out of the key."""
    calls = _install_provider(monkeypatch, calls=[])
    extract_facts("the blender is broken", lang="en", backend="llm")

    sent = calls[0]
    assert cache.entry_path("extract.defective", sent).exists()
    entry = json.loads(cache.entry_path("extract.defective", sent).read_text(encoding="utf-8"))
    assert entry["key"] == cache.key("extract.defective", sent)
    assert entry["key"] == cache.entry_path("extract.defective", sent).stem
    assert entry["model"] == llm_mod.MODEL
    assert entry["response"] == "yes"


def test_a_different_model_name_refetches(monkeypatch):
    calls = _install_provider(monkeypatch, calls=[])
    extract_facts("the blender is broken", lang="en", backend="llm")
    assert len(calls) == 1

    monkeypatch.setattr(llm_mod, "MODEL", "claude-some-other-model")
    extract_facts("the blender is broken", lang="en", backend="llm")
    assert len(calls) == 2, "a model change reused the previous model's answer"


def test_a_changed_prompt_refetches(monkeypatch):
    calls = _install_provider(monkeypatch, calls=[])
    extract_facts("the blender is broken", lang="en", backend="llm")
    assert len(calls) == 1

    monkeypatch.setattr(extract_mod, "_SYSTEM", extract_mod._SYSTEM + "\nAnd be brisk.")
    extract_facts("the blender is broken", lang="en", backend="llm")
    assert len(calls) == 2, "an edited prompt was served an answer from the old prompt"


# --------------------------------------------------------------------------- #
# (4) a hit and a miss produce identical results
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("answer,expected", [("yes", True), ("no", False),
                                             ("not_stated", None)])
def test_hit_and_miss_agree_for_every_answer(monkeypatch, answer, expected):
    """`not_stated` matters most: it is a real answer that maps to `None`, and `None` is
    also how the cache reports a miss. The stored value is the answer *string*, so the
    two can never be confused."""
    calls = _install_provider(monkeypatch, answer=answer, calls=[])
    miss = extract_facts("cualquier mensaje", lang="es", backend="llm")
    assert len(calls) == 1

    hit = extract_facts("cualquier mensaje", lang="es", backend="llm")
    assert len(calls) == 1, "not served from cache"
    assert hit == miss == {"defective": expected}
    assert hit["defective"] is expected


def test_a_cached_not_stated_is_stored_as_the_answer_not_as_an_absence(monkeypatch):
    _install_provider(monkeypatch, answer="not_stated")
    extract_facts("¿cuándo llega mi pedido?", lang="es", backend="llm")
    entry = json.loads(_entries()[0].read_text(encoding="utf-8"))
    assert entry["response"] == "not_stated"


def test_proposer_hit_and_miss_agree(monkeypatch):
    calls = _install_provider(monkeypatch, calls=[])
    facts, rules = {"defective": False, "days_since_delivery": 5}, kb.rules()
    miss = propose_return_decision(facts, rules, "take it back", backend="llm")
    hit = propose_return_decision(facts, rules, "take it back", backend="llm")
    assert len(calls) == 1
    assert hit == miss == _DECISION


# --------------------------------------------------------------------------- #
# the reason the cache is committed: replay with no key and no SDK
# --------------------------------------------------------------------------- #

def test_a_cached_run_replays_with_no_credentials_and_no_sdk(monkeypatch):
    """The integrity property. A reviewer with neither an API key nor `anthropic`
    installed must get the same answers back out of the committed cache."""
    _install_provider(monkeypatch, answer="yes")
    live = extract_facts("it arrived smashed", lang="en", backend="llm")

    _block_anthropic(monkeypatch)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    replayed = extract_facts("it arrived smashed", lang="en", backend="llm")
    assert replayed == live == {"defective": True}


def test_the_proposer_replays_with_no_sdk_too(monkeypatch):
    _install_provider(monkeypatch)
    facts, rules = {"defective": True}, kb.rules()
    live = propose_return_decision(facts, rules, "broken", backend="llm")

    _block_anthropic(monkeypatch)
    assert propose_return_decision(facts, rules, "broken", backend="llm") == live


def test_a_cache_miss_with_no_sdk_still_raises(monkeypatch):
    """The boundary is unmoved, only reordered: replay is free, but a ticket the cache
    does not cover still reports a broken setup loudly rather than as unanswerable."""
    _block_anthropic(monkeypatch)
    with pytest.raises(ModuleNotFoundError, match="anthropic"):
        extract_facts("a message nothing has cached", lang="en", backend="llm")


def test_a_cache_miss_with_no_credentials_still_raises(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    fake = types.ModuleType("anthropic")
    fake.Anthropic = lambda *a, **k: types.SimpleNamespace(
        api_key=None, auth_token=None, credentials=None,
        messages=types.SimpleNamespace(create=lambda **kw: pytest.fail("reached the wire")))
    monkeypatch.setitem(sys.modules, "anthropic", fake)
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        extract_facts("a message nothing has cached", lang="en", backend="llm")


# --------------------------------------------------------------------------- #
# (5) corruption fails loudly
# --------------------------------------------------------------------------- #

def _seed(monkeypatch, msg="the blender is broken", answer="yes") -> Path:
    """One real cached entry, so a test can then damage it."""
    _install_provider(monkeypatch, answer=answer)
    extract_facts(msg, lang="en", backend="llm")
    entries = _entries()
    assert len(entries) == 1
    return entries[0]


_DAMAGE = [
    ("not_json", lambda e: "{ this is not json"),
    ("not_an_object", lambda e: json.dumps(["yes"])),
    ("truncated", lambda e: json.dumps(e)[: len(json.dumps(e)) // 2]),
    ("wrong_version", lambda e: json.dumps({**e, "cache_version": 99})),
    ("wrong_key", lambda e: json.dumps({**e, "key": "0" * 64})),
    ("wrong_call", lambda e: json.dumps({**e, "call": "llm.return_decision"})),
    ("no_response_field", lambda e: json.dumps({k: v for k, v in e.items() if k != "response"})),
    ("unreadable_answer", lambda e: json.dumps({**e, "response": "SI, muy roto"})),
    ("null_answer", lambda e: json.dumps({**e, "response": None})),
    ("boolean_answer", lambda e: json.dumps({**e, "response": True})),
]


@pytest.mark.parametrize("label,damage", _DAMAGE, ids=[d[0] for d in _DAMAGE])
def test_a_corrupt_entry_raises_and_names_the_file(monkeypatch, label, damage):
    path = _seed(monkeypatch)
    path.write_text(damage(json.loads(path.read_text(encoding="utf-8"))), encoding="utf-8")

    with pytest.raises(cache.CacheCorrupt) as exc:
        extract_facts("the blender is broken", lang="en", backend="llm")
    assert path.name in str(exc.value), "the operator is not told which file to delete"
    assert "AGENT_CACHE=0" in str(exc.value), "the error does not say how to proceed"


def test_a_corrupt_entry_does_not_become_a_silent_refetch(monkeypatch):
    """The fail-open behaviour this project refuses, stated as a test: a damaged entry
    must not be replaced by a live call whose result nobody can trace to the artifact."""
    path = _seed(monkeypatch)
    path.write_text("{ broken", encoding="utf-8")

    calls = _install_provider(monkeypatch, calls=[])
    with pytest.raises(cache.CacheCorrupt):
        extract_facts("the blender is broken", lang="en", backend="llm")
    assert calls == [], "a corrupt entry was quietly re-fetched"


def test_a_corrupt_entry_is_not_swallowed_into_an_fr5_none(monkeypatch):
    """The dangerous interaction. `_llm_extract` catches every exception from the
    provider call and returns `None`; a cache lookup inside that `try` would turn a
    corrupt artifact into a run full of plausible "the customer didn't say". It is
    outside, so it raises."""
    path = _seed(monkeypatch)
    path.write_text("{ broken", encoding="utf-8")
    with pytest.raises(cache.CacheCorrupt):
        extract_facts("the blender is broken", lang="en", backend="llm")


def test_a_corrupt_proposer_entry_raises(monkeypatch):
    _install_provider(monkeypatch)
    facts, rules = {"defective": True}, kb.rules()
    propose_return_decision(facts, rules, "broken", backend="llm")
    path = _entries()[0]
    entry = json.loads(path.read_text(encoding="utf-8"))
    entry["response"] = {"outcome": "maybe", "cited_rule_ids": [], "rationale": ""}
    path.write_text(json.dumps(entry), encoding="utf-8")

    with pytest.raises(cache.CacheCorrupt):
        propose_return_decision(facts, rules, "broken", backend="llm")


def test_an_entry_planted_under_the_wrong_key_is_corruption_not_a_hit(monkeypatch):
    """The `key` field inside the file is what catches a copied or renamed entry — a
    cache whose filename and contents can disagree is a cache that can serve one
    ticket's answer for another and never say so."""
    stolen = json.loads(_seed(monkeypatch).read_text(encoding="utf-8"))
    other = {"messages": [{"role": "user", "content": "a different ticket entirely"}]}
    target = cache.entry_path("extract.defective", other)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(stolen), encoding="utf-8")

    with pytest.raises(cache.CacheCorrupt, match="key="):
        cache.get("extract.defective", other, extract_mod._readable)


# --------------------------------------------------------------------------- #
# (failures are never frozen into the artifact)
# --------------------------------------------------------------------------- #

def test_a_failed_call_is_not_cached(monkeypatch):
    calls = _install_provider(monkeypatch, raises=TimeoutError("timed out"), calls=[])
    assert extract_facts("hello", lang="en", backend="llm") == {"defective": None}
    assert _entries() == [], "a transient failure was written into the cache"

    _install_provider(monkeypatch, answer="yes", calls=calls)
    assert extract_facts("hello", lang="en", backend="llm") == {"defective": True}


def test_an_unreadable_answer_is_not_cached(monkeypatch):
    _install_provider(monkeypatch, answer="no lo se, tal vez?")
    assert extract_facts("hello", lang="en", backend="llm") == {"defective": None}
    assert _entries() == []


def test_the_proposer_fallback_ruling_is_not_cached(monkeypatch):
    """"no structured output" is a failed call, not a ruling. Caching it would pin an
    `ineligible` nobody decided onto that ticket for good."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    fake = types.ModuleType("anthropic")
    fake.Anthropic = lambda *a, **k: types.SimpleNamespace(
        api_key="k", auth_token=None, credentials=None,
        messages=types.SimpleNamespace(
            create=lambda **kw: types.SimpleNamespace(content=[])))
    monkeypatch.setitem(sys.modules, "anthropic", fake)

    out = propose_return_decision({"defective": True}, kb.rules(), "hi", backend="llm")
    assert out["rationale"] == "llm: no structured output"
    assert _entries() == []


# --------------------------------------------------------------------------- #
# the stub path must not be perturbed at all
# --------------------------------------------------------------------------- #

def test_the_stub_path_never_touches_the_cache():
    """tests/baseline_en_stub.json is byte-pinned against this path; the cache must be
    invisible to it."""
    for t in data.tickets():
        resolve_ticket(t, backend="stub", use_gate=True, extractor="stub")
    assert not cache.cache_dir().exists(), "the stub path created cache state"


# --------------------------------------------------------------------------- #
# knobs and on-disk hygiene
# --------------------------------------------------------------------------- #

def test_agent_cache_0_bypasses_the_cache_entirely(monkeypatch):
    calls = _install_provider(monkeypatch, calls=[])
    monkeypatch.setenv("AGENT_CACHE", "0")
    extract_facts("the blender is broken", lang="en", backend="llm")
    extract_facts("the blender is broken", lang="en", backend="llm")
    assert len(calls) == 2, "AGENT_CACHE=0 still served from cache"
    assert _entries() == [], "AGENT_CACHE=0 still wrote to the cache"


def test_agent_cache_0_ignores_an_existing_corrupt_entry(monkeypatch):
    """The documented escape hatch has to actually work when the cache is the problem."""
    path = _seed(monkeypatch)
    path.write_text("{ broken", encoding="utf-8")
    monkeypatch.setenv("AGENT_CACHE", "0")
    _install_provider(monkeypatch, answer="yes")
    assert extract_facts("the blender is broken", lang="en", backend="llm") == \
        {"defective": True}


def test_entries_are_one_file_per_key_and_only_ever_added(monkeypatch):
    """Why the diff of a future task stays clean: nothing is rewritten."""
    calls = _install_provider(monkeypatch, calls=[])
    for msg in ("one", "two", "three"):
        extract_facts(msg, lang="en", backend="llm")
    first = {p: p.read_bytes() for p in _entries()}
    assert len(first) == 3

    for msg in ("one", "two", "three"):
        extract_facts(msg, lang="en", backend="llm")
    assert {p: p.read_bytes() for p in _entries()} == first, "a re-run rewrote entries"


def test_no_temp_files_are_left_behind(monkeypatch):
    _seed(monkeypatch)
    assert list(cache.cache_dir().rglob("*.tmp")) == []


def test_an_unserialisable_request_raises_rather_than_hashing_a_repr():
    """Two requests that differ only in a field JSON cannot represent must not collide on
    one entry. Raising is local and happens before any request goes out."""
    with pytest.raises(TypeError):
        cache.key("extract.defective", {"messages": object()})


def test_the_default_cache_directory_is_the_committed_one(monkeypatch):
    monkeypatch.delenv("AGENT_CACHE_DIR", raising=False)
    assert cache.cache_dir() == ROOT / "response_cache"
    assert (ROOT / "response_cache" / "README.md").exists(), (
        "the committed cache directory has no README explaining what it is for")

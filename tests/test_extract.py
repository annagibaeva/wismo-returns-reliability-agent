"""Tests for the fact-reading seam (agent/extract.py), introduced in T5, model
backend added in T6.

Covers: both languages behind extract_facts, the stub backend's False-not-None
behaviour (the documented asymmetry with the model backend), that resolve_ticket
routes fact extraction through the seam correctly for a non-English ticket, the
model backend's FR-5 error contract -- every way the provider call can fail yields
`None`, never `False` -- and the boundary that sits beside it: a broken *setup* (no
SDK, no credentials) raises instead, and an unknown extractor name raises instead of
quietly running the keyword path under a model label.

Every model-backend test here fakes the provider by substituting `sys.modules`
["anthropic"], so the suite needs no API key and makes no network call (global
constraint 4). `_install_provider` also unsets ANTHROPIC_API_KEY for the duration,
so a machine that happens to have one set exercises the same code path CI does.
"""
from __future__ import annotations

import inspect
import json
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pytest

import kb
from agent import extract as extract_mod
from agent import llm as llm_mod
from agent.agent import resolve_ticket
from agent.extract import extract_facts
from services_mock import data


def _extract_step(res):
    """The single `extract_facts` entry from a Resolution's audit trail."""
    steps = [s for s in res.audit_trail if s.name == "extract_facts"]
    assert len(steps) == 1, f"expected exactly one extract_facts step, got {len(steps)}"
    return steps[0]


# --------------------------------------------------------------------------- #
# Offline provider double. No API key, no network -- global constraint 4.
# --------------------------------------------------------------------------- #

def _tool_use(payload) -> types.SimpleNamespace:
    """A response shaped like the SDK's: one tool_use block carrying `payload`."""
    return types.SimpleNamespace(
        content=[types.SimpleNamespace(type="tool_use", name="message_facts", input=payload)])


def _text(body: str) -> types.SimpleNamespace:
    """A response with prose instead of a tool call -- what a refusal looks like."""
    return types.SimpleNamespace(content=[types.SimpleNamespace(type="text", text=body)])


def _install_provider(monkeypatch, response=None, *, raises=None, calls=None):
    """Fake `anthropic` so `backend="llm"` runs end to end with no key and no network.

    `response` is returned from messages.create (or called with the kwargs, if it is
    callable); `raises` is an exception instance raised instead. `calls` collects the
    request kwargs so a test can inspect what was actually sent to the model.
    """
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    def create(**kwargs):
        if calls is not None:
            calls.append(kwargs)
        if raises is not None:
            raise raises
        return response(**kwargs) if callable(response) else response

    fake = types.ModuleType("anthropic")
    fake.Anthropic = lambda *a, **k: _fake_client(create, api_key="not-a-real-key")
    monkeypatch.setitem(sys.modules, "anthropic", fake)


def _fake_client(create, **credentials):
    """A client shaped like the real one: the three credential attributes, then `messages`.

    The real SDK exposes `api_key`, `auth_token` and `credentials` on every constructed
    client and sets each to `None` when it could not resolve one, so a double that omits
    them is a double of a client that cannot exist. Default here is *configured* --
    unconfigured is the special case, and it gets its own tests below.
    """
    return types.SimpleNamespace(
        api_key=credentials.get("api_key"), auth_token=credentials.get("auth_token"),
        credentials=credentials.get("credentials"),
        messages=types.SimpleNamespace(create=create))


# ---- both languages ----

def test_extract_facts_english_defect():
    assert extract_facts("the blender is broken and leaking", lang="en", backend="stub") == \
        {"defective": True}


def test_extract_facts_english_no_defect():
    assert extract_facts("I'd like to return this, it doesn't fit", lang="en", backend="stub") == \
        {"defective": False}


def test_extract_facts_spanish_defect():
    assert extract_facts("el producto llegó defectuoso, quiero una devolución", lang="es",
                         backend="stub") == {"defective": True}


def test_extract_facts_spanish_no_defect():
    assert extract_facts("el teléfono funciona bien pero llegó tarde", lang="es",
                         backend="stub") == {"defective": False}


def test_extract_facts_indonesian_defect():
    assert extract_facts("barangnya rusak, saya ingin pengembalian", lang="id",
                         backend="stub") == {"defective": True}


def test_extract_facts_indonesian_no_defect():
    assert extract_facts("barang berfungsi baik tapi ukurannya tidak pas", lang="id",
                         backend="stub") == {"defective": False}


def test_extract_facts_defaults_to_english_lexicon():
    assert extract_facts("this is broken") == {"defective": True}


# ---- the FR-5 asymmetry: the keyword backend can only say False, never None ----

def test_stub_backend_returns_false_not_none_for_unclear_message():
    # No defect keyword anywhere in this message. A model backend could say "I
    # don't know" (None); the keyword backend has no such state -- it reads
    # silence on the topic as a confident claim the item works.
    result = extract_facts("I would like a status update on my package please", lang="en",
                           backend="stub")
    assert result["defective"] is False
    assert result["defective"] is not None


def test_stub_backend_never_produces_none():
    # Swept across a mix of defect and non-defect language in both lexicons --
    # every value must be a bool, never None, regardless of which side it lands on.
    messages = [
        ("the toaster won't turn on", "en"),
        ("I'd like to exchange this for a different size", "en"),
        ("el ventilador interno funciona correctamente", "es"),
        ("está roto y quiero un reembolso", "es"),
        ("barangnya rusak", "id"),
        ("ukuran tidak pas, berfungsi baik", "id"),
    ]
    for msg, lang in messages:
        result = extract_facts(msg, lang=lang, backend="stub")
        assert result["defective"] in (True, False)


# ---- the model backend reads the three answers ----

@pytest.mark.parametrize("answer,expected", [
    ("yes", True),
    ("no", False),
    ("not_stated", None),
])
def test_llm_backend_maps_each_answer(monkeypatch, answer, expected):
    _install_provider(monkeypatch, _tool_use({"defective": answer}))
    assert extract_facts("cualquier mensaje", lang="es", backend="llm") == \
        {"defective": expected}


def test_llm_backend_can_say_it_does_not_know_where_the_stub_cannot(monkeypatch):
    # The whole point of the seam. Same message, same call; the keyword backend has
    # to claim the item works, the model backend is allowed to decline.
    msg = "I would like a status update on my package please"
    _install_provider(monkeypatch, _tool_use({"defective": "not_stated"}))
    assert extract_facts(msg, lang="en", backend="llm")["defective"] is None
    assert extract_facts(msg, lang="en", backend="stub")["defective"] is False


# ---- FR-5: every error path yields None, never False ----
#
# Each entry is (label, response, raises). The label is the failure mode; it shows up
# in the pytest node id so a regression names the path that broke.
_ERROR_PATHS = [
    # -- malformed output: the tool call came back, but not in the agreed shape --
    ("malformed_input_is_a_json_string", _tool_use('{"defective": "yes"}'), None),
    ("malformed_input_is_a_list", _tool_use([{"defective": "yes"}]), None),
    ("malformed_input_is_none", _tool_use(None), None),
    ("corrupted_free_text_answer", _tool_use({"defective": "SI, muy roto"}), None),
    ("corrupted_truncated_answer", _tool_use({"defective": "not_stat"}), None),
    ("corrupted_bool_instead_of_enum", _tool_use({"defective": True}), None),
    ("corrupted_false_bool_instead_of_enum", _tool_use({"defective": False}), None),
    ("corrupted_nested_object", _tool_use({"defective": {"value": "yes"}}), None),
    ("corrupted_null_answer", _tool_use({"defective": None}), None),
    # -- missing field: the tool call answered something else entirely --
    ("missing_field", _tool_use({"reason": "the customer seems upset"}), None),
    ("missing_field_empty_object", _tool_use({}), None),
    # -- refusal / no structured output at all --
    ("refusal_text_block", _text("I'm sorry, I can't help with that."), None),
    ("empty_content", types.SimpleNamespace(content=[]), None),
    ("content_is_none", types.SimpleNamespace(content=None), None),
    ("response_has_no_content_attribute", types.SimpleNamespace(), None),
    # -- transport: the call never came back --
    ("timeout", None, TimeoutError("request timed out")),
    ("connection_error", None, ConnectionError("connection reset by peer")),
    ("api_error", None, RuntimeError("overloaded_error: 529")),
    ("rate_limited", None, RuntimeError("rate_limit_error: 429")),
]


@pytest.mark.parametrize("label,response,raises",
                         _ERROR_PATHS, ids=[p[0] for p in _ERROR_PATHS])
def test_llm_error_paths_return_none_never_false(monkeypatch, label, response, raises):
    _install_provider(monkeypatch, response, raises=raises)
    facts = extract_facts("the message barely matters here", lang="en", backend="llm")
    assert set(facts) == {"defective"}, f"{label} changed the fact keys"
    assert facts["defective"] is None, f"{label} did not yield None"
    # Stated separately and on purpose: `is None` above would still pass if the value
    # were some other falsey thing, and `False` specifically is the fabrication FR-5
    # exists to prevent -- a positive claim that the item works.
    assert facts["defective"] is not False, f"{label} fabricated defective=False"


def test_a_deliberately_corrupted_response_yields_none_rather_than_false(monkeypatch):
    # The named acceptance criterion, with a real payload rather than a claim about
    # one. `bool("no lo se")` is True and `bool("")` is False -- coercing a corrupted
    # answer to a bool would invent a fact in either direction, so nothing is coerced.
    corrupted = {"defective": "no lo se, tal vez?", "confidence": 0.42}
    _install_provider(monkeypatch, _tool_use(corrupted))
    facts = extract_facts("el aparato llegó ayer", lang="es", backend="llm")
    assert facts == {"defective": None}
    assert facts["defective"] is not False


def test_llm_backend_does_not_retry_on_a_corrupted_response(monkeypatch):
    # A retry loop that eventually settles for a default is the same fabrication
    # with extra steps. One call in, one answer out.
    calls = []
    _install_provider(monkeypatch, _tool_use({"defective": "???"}), calls=calls)
    assert extract_facts("hello", lang="en", backend="llm") == {"defective": None}
    assert len(calls) == 1


def test_llm_backend_does_not_retry_on_a_timeout(monkeypatch):
    calls = []
    _install_provider(monkeypatch, None, raises=TimeoutError("timed out"), calls=calls)
    assert extract_facts("hello", lang="en", backend="llm") == {"defective": None}
    assert len(calls) == 1


# ---- the configuration boundary: broken setup raises, the provider's answers do not ----
#
# A missing key or a missing SDK is the operator failing to set the run up, not the
# customer failing to say. Swallowing either into `None` would turn a broken model arm
# into a wall of plausible-looking handoffs and report it as data.
#
# The failure has to be injected where the SDK really produces it. `anthropic.Anthropic()`
# does *not* raise on a missing key -- it constructs fine, leaves all three credential
# attributes `None`, and raises `TypeError("Could not resolve authentication method...")`
# from inside `messages.create`, which sits inside the `except Exception`. A double that
# raises in the constructor tests a code path the SDK does not have.

_SDK_AUTH_TYPEERROR = TypeError(
    '"Could not resolve authentication method. Expected one of api_key, auth_token, or '
    'credentials to be set. Or for one of the `X-Api-Key` or `Authorization` headers to '
    'be explicitly omitted"')


def test_an_unconfigured_client_raises_and_never_reaches_the_provider(monkeypatch):
    # The real shape: construction succeeds, credentials are all None, and create() would
    # raise the SDK's TypeError. Ours must raise *before* create is ever called -- if it
    # reached create, the TypeError would be caught and every ticket in the run would read
    # as "the customer didn't say".
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    calls = []

    def create(**kwargs):
        calls.append(kwargs)
        raise _SDK_AUTH_TYPEERROR

    fake = types.ModuleType("anthropic")
    fake.Anthropic = lambda *a, **k: _fake_client(create)  # no credentials at all
    monkeypatch.setitem(sys.modules, "anthropic", fake)
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        extract_facts("hello", lang="en", backend="llm")
    assert calls == [], "the unconfigured client was allowed to reach the provider"


@pytest.mark.parametrize("source", ["api_key", "auth_token", "credentials"])
def test_any_one_credential_source_is_enough_to_proceed(monkeypatch, source):
    # The precondition asks whether the client is configured, not whether it holds a key.
    # A machine authenticated by auth token or by credentials file is set up correctly and
    # must not be turned away -- that would trade a silent wrong answer for a loud one.
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    fake = types.ModuleType("anthropic")
    fake.Anthropic = lambda *a, **k: _fake_client(
        lambda **kw: _tool_use({"defective": "yes"}), **{source: "configured"})
    monkeypatch.setitem(sys.modules, "anthropic", fake)
    assert extract_facts("it arrived smashed", lang="en", backend="llm") == {"defective": True}


def test_the_real_sdk_constructs_without_a_key_and_the_seam_still_raises(monkeypatch):
    # The finding itself, against the installed SDK rather than a double: no fake anywhere,
    # no network (we raise before create), and skipped rather than faked where the SDK is
    # absent or the machine is genuinely authenticated -- global constraint 4.
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    anthropic = pytest.importorskip("anthropic", reason="SDK not installed; nothing to check")
    client = anthropic.Anthropic()  # the point: this does NOT raise
    if any(getattr(client, name, None) is not None
           for name in ("api_key", "auth_token", "credentials")):
        pytest.skip("this machine has Anthropic credentials configured")
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        extract_facts("hello", lang="en", backend="llm")


def test_a_missing_sdk_raises_rather_than_reading_as_unanswerable(monkeypatch):
    # The sibling case, and the state CI is actually in: `anthropic` not installed at all.
    # Blocked through the import machinery so the failure is the genuine
    # ModuleNotFoundError, message included, not a sentinel in sys.modules.
    class _NoAnthropic:
        def find_spec(self, name, path=None, target=None):
            if name == "anthropic":
                raise ModuleNotFoundError(f"No module named {name!r}", name=name)
            return None

    monkeypatch.delitem(sys.modules, "anthropic", raising=False)
    monkeypatch.setattr(sys, "meta_path", [_NoAnthropic(), *sys.meta_path])
    with pytest.raises(ModuleNotFoundError, match="anthropic"):
        extract_facts("hello", lang="en", backend="llm")


def test_an_auth_failure_from_the_wire_stays_on_the_none_side(monkeypatch):
    # The other side of the same boundary, and the case that says where it is drawn: the
    # client IS configured, the key is simply wrong, and the provider says 401. That is a
    # provider answer, not a local misconfiguration -- separating a permanently bad key
    # from a revoked one, an auth outage or a transient 401 means naming SDK error classes,
    # which is exactly the coupling FR-5's blanket `except` refuses. So it returns None.
    class AuthenticationError(Exception):
        status_code = 401

    _install_provider(monkeypatch, None,
                      raises=AuthenticationError("authentication_error: invalid x-api-key"))
    facts = extract_facts("the blender is broken", lang="en", backend="llm")
    assert facts == {"defective": None}
    assert facts["defective"] is not False


# ---- an unknown extractor name raises rather than silently running the keyword path ----

@pytest.mark.parametrize("name", ["model", "LLM", "Stub", "lmm", "anthropic", ""])
def test_an_unknown_extractor_name_raises(name):
    # `resolve_ticket` writes the *requested* extractor into the audit trail without
    # checking which one ran, so falling through to the keyword path would file keyword
    # numbers under a model label. Same failure `_route` refuses for a mistyped `lang`.
    with pytest.raises(ValueError, match="no extractor named") as exc:
        extract_facts("the blender is broken", lang="en", backend=name)
    assert repr(name) in str(exc.value)


def test_the_unknown_extractor_error_lists_the_known_names():
    # What makes the error self-correcting, and the reason `_route` lists its lexicons.
    with pytest.raises(ValueError) as exc:
        extract_facts("hello", lang="en", backend="model")
    assert "'stub'" in str(exc.value) and "'llm'" in str(exc.value)


def test_an_unknown_extractor_raises_through_resolve_ticket():
    base = data.tickets()[0]
    with pytest.raises(ValueError, match="no extractor named 'model'"):
        resolve_ticket({**base, "id": "unknown-extractor-test"}, backend="stub",
                       extractor="model")


def test_extractors_contract_is_exactly_stub_and_llm():
    assert extract_mod.EXTRACTORS == frozenset({"stub", "llm"})


# ---- the model may not smuggle an order fact out through the seam ----

def test_llm_hallucinated_key_never_reaches_the_caller(monkeypatch):
    # The model invents `final_sale` and `order_value`. Neither may leave the
    # extractor: reading them is how prose would overwrite the order database.
    _install_provider(monkeypatch, _tool_use(
        {"defective": "yes", "final_sale": "no", "order_value": 9999}))
    assert extract_facts("it arrived smashed", lang="en", backend="llm") == \
        {"defective": True}


def test_dispatcher_guard_also_covers_the_llm_path(monkeypatch):
    # The guard lives in extract_facts, not in either implementation, so it holds for
    # a model backend too -- including a future one that stops filtering its own keys.
    monkeypatch.setattr(extract_mod, "_llm_extract",
                        lambda msg: {"defective": True, "final_sale": False})
    with pytest.raises(ValueError, match="final_sale"):
        extract_facts("this is broken", lang="en", backend="llm")


# ---- one contract, satisfied by both backends ----

_CONTRACT_CASES = [
    ("the blender is broken and leaking", "en", "yes"),
    ("I'd like to return this, it doesn't fit", "en", "no"),
    ("I would like a status update on my package please", "en", "not_stated"),
    ("el producto llegó defectuoso, quiero una devolución", "es", "yes"),
    ("el teléfono funciona bien pero llegó tarde", "es", "no"),
    ("¿cuándo llega mi pedido?", "es", "not_stated"),
]


@pytest.mark.parametrize("backend", ["stub", "llm"])
@pytest.mark.parametrize("msg,lang,answer",
                         _CONTRACT_CASES, ids=[c[0][:24] for c in _CONTRACT_CASES])
def test_both_backends_satisfy_the_seam_contract(monkeypatch, backend, msg, lang, answer):
    # The seam's contract, not either implementation's answers: the two backends are
    # *expected* to disagree on values (that disagreement is the finding), so pinning
    # agreement here would pin the very gap the project measures. What both must do is
    # return a dict whose keys are exactly the prose contract, with a value drawn from
    # the three-state domain, for any message in any supported language.
    if backend == "llm":
        _install_provider(monkeypatch, _tool_use({"defective": answer}))
    facts = extract_facts(msg, lang=lang, backend=backend)
    assert isinstance(facts, dict)
    assert set(facts) == {"defective"}
    assert set(facts) <= extract_mod.PROSE_FACTS
    assert facts["defective"] in (True, False, None)


@pytest.mark.parametrize("backend", ["stub", "llm"])
def test_backends_diverge_on_an_unknown_language(monkeypatch, backend):
    # Divergence worth naming: the keyword backend cannot read `lang="de"` and says so;
    # the model backend does not consult `lang` at all, so it answers. Pinned here so
    # that a future change to either side is a visible decision rather than a surprise.
    if backend == "llm":
        _install_provider(monkeypatch, _tool_use({"defective": "not_stated"}))
        assert extract_facts("das Gerät ist kaputt", lang="de", backend="llm") == \
            {"defective": None}
    else:
        with pytest.raises(KeyError):
            extract_facts("das Gerät ist kaputt", lang="de", backend="stub")


# ---- D-4: the extractor is not told what the fact is for ----

def _request_payload(monkeypatch) -> str:
    """Everything actually sent to the model, as one string."""
    calls = []
    _install_provider(monkeypatch, _tool_use({"defective": "not_stated"}), calls=calls)
    extract_facts("the toaster won't turn on", lang="en", backend="llm")
    assert len(calls) == 1
    return json.dumps(calls[0], default=str)


# Policy vocabulary, drawn from kb/rules.json plus the words its rules are about. A
# prompt containing any of these has told the extractor what `defective` unlocks.
_POLICY_TERMS = [
    "ret-0", "policy", "rule", "eligib", "ineligib", "return", "refund", "exchange",
    "replacement", "final sale", "final_sale", "clearance", "window", "30 day",
    "15 day", "days since", "delivery", "warranty", "override", "priority", "rma",
]


def test_the_prompt_contains_no_policy_text(monkeypatch):
    payload = _request_payload(monkeypatch).lower()
    leaked = [term for term in _POLICY_TERMS if term in payload]
    assert not leaked, f"policy vocabulary reached the extractor prompt: {leaked}"


def test_no_rule_id_or_rule_source_text_reaches_the_extractor(monkeypatch):
    payload = _request_payload(monkeypatch).lower()
    for rule in kb.rules():
        assert rule["rule_id"].lower() not in payload
        assert rule["source_text"].lower() not in payload
        assert rule["title"].lower() not in payload


def test_no_order_fact_name_other_than_defective_reaches_the_extractor(monkeypatch):
    # `defective` is the fact being read, so it is expected. Every other fact the
    # rules consume belongs to the order database and has no business in a prompt
    # whose only job is to report what the customer said.
    payload = _request_payload(monkeypatch).lower()
    names = {f for rule in kb.rules() for f in rule["requires_facts"]} - {"defective"}
    leaked = [n for n in names if n in payload or n.replace("_", " ") in payload]
    assert not leaked, f"order-database fact names reached the extractor prompt: {leaked}"


def test_the_prompt_carries_only_the_message_and_the_question(monkeypatch):
    calls = []
    _install_provider(monkeypatch, _tool_use({"defective": "yes"}), calls=calls)
    extract_facts("la licuadora está rota", lang="es", backend="llm")
    sent = calls[0]
    assert len(sent["messages"]) == 1
    assert "la licuadora está rota" in sent["messages"][0]["content"]
    # The language tag is the router's guess and never reaches the model -- structural,
    # not a matter of what today's prompt happens to interpolate.
    assert list(inspect.signature(extract_mod._llm_extract).parameters) == ["msg"]


# ---- the provider call is shaped like the rest of the seam ----

def test_llm_call_omits_temperature_on_adaptive_models(monkeypatch):
    calls = []
    _install_provider(monkeypatch, _tool_use({"defective": "yes"}), calls=calls)
    extract_facts("it's broken", lang="en", backend="llm")
    sent = calls[0]
    assert "temperature" not in sent
    assert sent["model"] == llm_mod.MODEL
    assert sent["tools"] == [extract_mod._SCHEMA]
    assert sent["tool_choice"] == {"type": "tool", "name": "message_facts"}
    assert sent["system"] == extract_mod._SYSTEM


def test_llm_call_keeps_temperature_zero_on_sampling_models(monkeypatch):
    monkeypatch.setattr(llm_mod, "MODEL", "claude-sonnet-4-5")
    calls = []
    _install_provider(monkeypatch, _tool_use({"defective": "yes"}), calls=calls)
    extract_facts("it's broken", lang="en", backend="llm")
    assert calls[0]["temperature"] == 0


def test_the_schema_offers_a_third_answer_for_unanswerable(monkeypatch):
    # If the schema only had true/false, "didn't say" would have nowhere to go and
    # the model would be forced to pick one -- which is the FR-5 failure by design.
    enum = extract_mod._SCHEMA["input_schema"]["properties"]["defective"]["enum"]
    assert enum == ["yes", "no", "not_stated"]
    assert extract_mod._ANSWERS["not_stated"] is None
    assert extract_mod._ANSWERS["no"] is False


# ---- end to end: an unanswerable fact reaches the gate as unanswerable ----

def test_resolve_ticket_with_a_not_stated_reading_leaves_defective_none(monkeypatch):
    _install_provider(monkeypatch, _tool_use({"defective": "not_stated"}))
    base = data.tickets()[0]
    res = resolve_ticket({**base, "id": "llm-extractor-not-stated"}, backend="stub",
                         extractor="llm")
    assert res.facts["defective"] is None
    assert _extract_step(res).input["extractor"] == "llm"


def test_resolve_ticket_with_a_failed_call_leaves_defective_none(monkeypatch):
    # The failure that matters most: the provider fell over and the ticket still
    # must not carry a fabricated "the item works" into the gate.
    _install_provider(monkeypatch, None, raises=TimeoutError("timed out"))
    base = data.tickets()[0]
    res = resolve_ticket({**base, "id": "llm-extractor-timeout"}, backend="stub",
                         extractor="llm")
    assert res.facts["defective"] is None
    assert res.facts["defective"] is not False


# ---- resolve_ticket routes through the seam, with the ticket's own language ----

def test_resolve_ticket_uses_spanish_lexicon_for_spanish_return_ticket():
    base = data.tickets()[0]  # ORD-2001, single item, clean return
    ticket = {**base, "id": "es-defect-seam-test", "lang": "es",
              "message": "el producto llegó defectuoso, quiero una devolución"}
    res = resolve_ticket(ticket, backend="stub", use_gate=True)
    assert res.facts["defective"] is True


def test_resolve_ticket_spanish_working_item_is_not_a_defect_claim():
    base = data.tickets()[0]
    ticket = {**base, "id": "es-nodefect-seam-test", "lang": "es",
              "message": "el teléfono funciona bien pero ya no lo quiero, quiero una devolución"}
    res = resolve_ticket(ticket, backend="stub", use_gate=True)
    assert res.facts["defective"] is False


# ---- the extractor is selected independently of the proposer ----

def test_extractor_defaults_independently_of_backend(monkeypatch):
    # Passing only backend="llm" must NOT drag the extractor along with it. The
    # proposer is faked out so this needs no API key (global constraint 4); the
    # point is which backend string reached extract_facts.
    seen = []
    real = extract_mod.extract_facts

    def spy(msg, lang="en", backend="stub"):
        seen.append(backend)
        return real(msg, lang, backend=backend)

    monkeypatch.setattr(extract_mod, "extract_facts", spy)
    monkeypatch.setattr(llm_mod, "propose_return_decision",
                        lambda *a, **k: {"outcome": "ineligible", "cited_rule_ids": [],
                                         "rationale": "fake"})
    base = data.tickets()[0]
    res = resolve_ticket({**base, "id": "independent-default-test"}, backend="llm")
    assert seen == ["stub"], f"extractor followed backend instead of its own default: {seen}"
    assert res.backend == "llm"


def test_extractor_argument_is_forwarded_not_the_backend(monkeypatch):
    # And the reverse: an explicit extractor must reach the seam untouched, even
    # while backend stays "stub".
    seen = []
    monkeypatch.setattr(extract_mod, "extract_facts",
                        lambda msg, lang="en", backend="stub": seen.append(backend) or
                        {"defective": False})
    base = data.tickets()[0]
    resolve_ticket({**base, "id": "explicit-extractor-test"}, backend="stub", extractor="llm")
    assert seen == ["llm"]


def test_resolve_ticket_llm_backend_does_not_raise_not_implemented(monkeypatch):
    # The regression this fixes: forwarding `backend` into the extractor made
    # `--backend llm` raise NotImplementedError before it ever reached the proposer.
    monkeypatch.setattr(llm_mod, "propose_return_decision",
                        lambda *a, **k: {"outcome": "ineligible", "cited_rule_ids": [],
                                         "rationale": "fake"})
    base = data.tickets()[0]
    res = resolve_ticket({**base, "id": "llm-backend-reaches-proposer"}, backend="llm",
                         extractor="stub")
    assert res.facts["defective"] is False


# ---- the extractor may not overwrite order-database facts ----

def test_out_of_contract_key_fails_loudly(monkeypatch):
    # A future model extractor hallucinating an order fact must not be able to
    # overwrite the authoritative order record -- and must not be silently dropped
    # either, which would hide the same bug.
    monkeypatch.setattr(extract_mod, "_stub_extract",
                        lambda msg, lang: {"defective": True, "final_sale": False})
    with pytest.raises(ValueError, match="final_sale"):
        extract_facts("this is broken", lang="en", backend="stub")


def test_out_of_contract_key_fails_loudly_through_resolve_ticket(monkeypatch):
    monkeypatch.setattr(extract_mod, "_stub_extract",
                        lambda msg, lang: {"defective": True, "order_value": 9999})
    base = data.tickets()[0]
    with pytest.raises(ValueError, match="order_value"):
        resolve_ticket({**base, "id": "out-of-contract-test"}, backend="stub")


def test_prose_facts_contract_is_exactly_defective():
    assert extract_mod.PROSE_FACTS == frozenset({"defective"})


def test_stub_return_is_within_the_prose_contract():
    assert set(extract_facts("the blender is broken", lang="en")) <= extract_mod.PROSE_FACTS


# ---- the audit trail names the extractor and the language ----

def test_audit_entry_records_extractor_and_lang():
    base = data.tickets()[0]
    res = resolve_ticket({**base, "id": "audit-extractor-test"}, backend="stub")
    step = _extract_step(res)
    assert step.input["extractor"] == "stub"
    assert step.input["lang"] == "en"
    assert step.input["order_id"] == res.order_id


def test_audit_entry_records_the_extractor_actually_used(monkeypatch):
    # M-6 needs to tell a keyword-derived fact from a model-derived one; the audit
    # entry must name the extractor that ran, not the proposer's backend.
    monkeypatch.setattr(extract_mod, "extract_facts",
                        lambda msg, lang="en", backend="stub": {"defective": False})
    monkeypatch.setattr(llm_mod, "propose_return_decision",
                        lambda *a, **k: {"outcome": "ineligible", "cited_rule_ids": [],
                                         "rationale": "fake"})
    base = data.tickets()[0]
    res = resolve_ticket({**base, "id": "audit-extractor-llm-test"}, backend="llm",
                         extractor="llm")
    step = _extract_step(res)
    assert step.input["extractor"] == "llm"
    assert res.backend == "llm"


def test_audit_entry_records_the_ticket_language():
    base = data.tickets()[0]
    ticket = {**base, "id": "audit-lang-test", "lang": "es",
              "message": "el producto llegó defectuoso, quiero una devolución"}
    res = resolve_ticket(ticket, backend="stub")
    assert _extract_step(res).input["lang"] == "es"

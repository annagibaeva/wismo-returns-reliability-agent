"""Tests for the intent-routing seam (agent/route.py)."""
from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agent import route as route_mod
from agent.agent import _route, resolve_ticket
from agent.route import route_intent
from services_mock import data


def _tool_use(payload) -> types.SimpleNamespace:
    return types.SimpleNamespace(
        content=[types.SimpleNamespace(type="tool_use", name="route_intent", input=payload)])


def _install_provider(monkeypatch, response=None, *, raises=None, calls=None):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    def create(**kwargs):
        if calls is not None:
            calls.append(kwargs)
        if raises is not None:
            raise raises
        return response(**kwargs) if callable(response) else response

    fake = types.ModuleType("anthropic")
    fake.Anthropic = lambda *a, **k: types.SimpleNamespace(
        api_key="not-a-real-key", auth_token=None, credentials=None,
        messages=types.SimpleNamespace(create=create))
    monkeypatch.setitem(sys.modules, "anthropic", fake)


def test_stub_matches_legacy_keyword_route():
    assert route_intent("where is my order") == _route("where is my order") == ("wismo", None)
    assert route_intent("I want to return this jacket") == ("return", None)
    assert route_intent("the kettle gave me an electric shock") == ("out_of_scope", "safety")
    assert route_intent("I'm disputing this charge with my bank") == ("out_of_scope", "payment_dispute")


def test_stub_sf02_still_falls_through_to_wismo():
    """The live miss: no _SAFETY word, so the keyword router guesses WISMO."""
    t = next(x for x in data.tickets() if x["id"] == "SF-02")
    assert route_intent(t["message"]) == ("wismo", None)


def test_unknown_router_raises():
    with pytest.raises(ValueError, match="no router named"):
        route_intent("hello", backend="model")


def test_llm_router_classifies_safety_without_keywords(monkeypatch):
    _install_provider(monkeypatch, _tool_use({"intent": "out_of_scope", "reason": "safety"}))
    t = next(x for x in data.tickets() if x["id"] == "SF-02")
    assert route_intent(t["message"], backend="llm") == ("out_of_scope", "safety")


def test_llm_router_through_resolve_ticket_hands_off_sf02(monkeypatch):
    _install_provider(monkeypatch, _tool_use({"intent": "out_of_scope", "reason": "safety"}))
    t = next(x for x in data.tickets() if x["id"] == "SF-02")
    res = resolve_ticket(t, backend="stub", use_gate=True, router="llm")
    assert res.action == "handoff"
    assert res.intent == "out_of_scope"


def test_llm_router_fails_closed_on_timeout(monkeypatch):
    _install_provider(monkeypatch, raises=TimeoutError("slow"))
    intent, reason = route_intent("where is my order", backend="llm")
    assert intent == "out_of_scope"
    assert reason == "router_unreadable"


def test_llm_router_missing_key_raises(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    fake = types.ModuleType("anthropic")
    fake.Anthropic = lambda *a, **k: types.SimpleNamespace(
        api_key=None, auth_token=None, credentials=None)
    monkeypatch.setitem(sys.modules, "anthropic", fake)
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        route_intent("hello", backend="llm")


def test_llm_call_omits_temperature_on_adaptive_models(monkeypatch):
    calls = []
    _install_provider(monkeypatch, _tool_use({"intent": "return", "reason": None}), calls=calls)
    route_intent("I want to return this", backend="llm")
    assert "temperature" not in calls[0]
    assert calls[0]["system"] == route_mod._SYSTEM
    assert calls[0]["tool_choice"] == {"type": "tool", "name": "route_intent"}


def test_default_resolve_ticket_still_uses_keyword_router():
    t = next(x for x in data.tickets() if x["id"] == "SF-02")
    res = resolve_ticket(t, backend="stub", use_gate=True)
    assert res.action == "resolve"
    assert res.outcome == "status_provided"

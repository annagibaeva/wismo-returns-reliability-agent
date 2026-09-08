"""Every test gets its own empty response cache. This is isolation, not a bypass.

The committed cache under `response_cache/` is an evidence artifact: a reviewer with
no API key replays it to reproduce a published report. Every model-backend test in
this suite fakes the provider (global constraint 4 -- no test may need a key), so the
"responses" they produce are fiction, and fiction written into that directory would be
indistinguishable from a real answer once committed. Redirecting `AGENT_CACHE_DIR` per
test makes that structurally impossible: no test can write the committed cache, and no
test can read it either, so a suite that passes says nothing about what happens to be
cached on the machine running it.

Autouse and unconditional on purpose. An opt-in fixture is one a new test forgets, and
the failure mode of forgetting is invisible -- a green run that quietly appended
invented answers to the artifact. `tests/test_cache.py` exercises the real cache
machinery inside these tmpdirs; nothing needs the committed one.
"""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def isolated_response_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_CACHE_DIR", str(tmp_path / "response_cache"))

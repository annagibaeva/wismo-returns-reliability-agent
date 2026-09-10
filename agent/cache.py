"""On-disk memo for provider responses, so a published result can be re-checked
without an API key.

Three reasons, in ascending order of importance. A full run is roughly 1,600 model
calls and every re-run repeats them, so the cache makes iteration cheap. Cached
answers make a run replayable, so a number can be traced to the response it came
from. And a reviewer with no credentials can re-run the eval against the committed
cache and get the published numbers back — a result nobody can reproduce is a result
nobody can check, which makes that last one an integrity property rather than a
convenience.

**What is in the key.** Everything the call site sends. `key()` takes the exact
kwargs dict the call site is about to hand to `messages.create` — model, max_tokens,
temperature, system, tools, tool_choice, messages — hashes a canonical serialisation
of it, and the call site then splats that same dict into the request. A parameter
cannot be left out of the key by accident, because leaving it out of the key means
leaving it out of the call. That is the whole point of taking a dict rather than a
list of named arguments: "the full prompt" is not a thing anyone has to remember to
enumerate. `cache_version` is hashed in too, so a change to *how* entries are written
retires the old ones by making them unreachable instead of reinterpreting them, and
`call` names the call site so two seams cannot read each other's entries even if their
requests ever coincided.

**Layout.** One file per key, `response_cache/<first two hex>/<key>.json`, atomically
replaced. Content-addressed and one-per-entry on purpose: entries are only ever added,
never rewritten, so a task that adds no model calls produces no diff at all. A single
combined JSON file would be rewritten in full by every run and would put thousands of
churned lines into the diff of every future task.

**Corruption fails loudly.** An entry that cannot be read raises `CacheCorrupt` rather
than falling through to a live call. Falling through is the tempting choice — it is
invisible and it always "works" — and it is wrong twice over. A reviewer replaying
without a key would get an authentication error from a cache problem, naming the wrong
thing. Worse, a run that silently re-fetches is a run whose numbers came from somewhere
other than the artifact under review, and nothing anywhere would say so. This project
has been bitten repeatedly by mechanisms that fail open; a cache that quietly repairs
itself is one more. So a corrupt entry stops the run and names the file, and the fix is
to delete that file and re-fetch on purpose.

Note the two things that are deliberately *not* cached: a call that raised, and a
response the call site could not read. Both are failures, and a cached failure is a
transient outage frozen into the artifact forever.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Callable

CACHE_VERSION = 1
DEFAULT_DIR = Path(__file__).resolve().parent.parent / "response_cache"


class CacheCorrupt(RuntimeError):
    """An entry exists but cannot be trusted. Never caught inside this package."""


def cache_dir() -> Path:
    """Where entries live. `AGENT_CACHE_DIR` redirects it — tests point it at a tmpdir
    so a faked provider's fiction can never reach the committed cache."""
    override = os.environ.get("AGENT_CACHE_DIR")
    return Path(override) if override else DEFAULT_DIR


def enabled() -> bool:
    """`AGENT_CACHE=0` forces every call to the wire — for re-fetching on purpose."""
    return os.environ.get("AGENT_CACHE", "1") != "0"


def key(call: str, request: dict) -> str:
    """sha256 over the whole request as sent, plus the call site and the format version.

    No `default=` on the dump: a request holding something that will not serialise
    cannot be represented in a key faithfully, and hashing its `repr` would collapse
    two different requests onto one entry. Raising is the honest answer, and it raises
    locally, before any request goes out.
    """
    blob = json.dumps({"cache_version": CACHE_VERSION, "call": call, "request": request},
                      sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def entry_path(call: str, request: dict) -> Path:
    """Where this request's entry lives — sharded by the key's first byte so the
    directory stays navigable at a few thousand entries."""
    k = key(call, request)
    return cache_dir() / k[:2] / f"{k}.json"


def get(call: str, request: dict, readable: Callable[[Any], bool]) -> Any | None:
    """The cached response, or `None` for a miss. Raises `CacheCorrupt` for anything else.

    `readable` is the call site's own predicate on the response — the same one that
    decides whether a fresh response is worth storing. A stored response the call site
    can no longer read is corruption, not a miss: treating it as a miss would silently
    re-fetch, which is the fail-open behaviour this module refuses. It must reject
    `None`, since `None` is how a miss is reported.
    """
    if not enabled():
        return None
    k = key(call, request)
    path = entry_path(call, request)
    if not path.exists():
        return None
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise CacheCorrupt(_complaint(path, f"could not be read: {exc}")) from exc
    try:
        entry = json.loads(raw)
    except ValueError as exc:
        raise CacheCorrupt(_complaint(path, f"is not valid JSON: {exc}")) from exc
    if not isinstance(entry, dict):
        raise CacheCorrupt(_complaint(path, f"holds {type(entry).__name__}, not an object"))
    for field, expected in (("cache_version", CACHE_VERSION), ("key", k), ("call", call)):
        if entry.get(field) != expected:
            raise CacheCorrupt(_complaint(
                path, f"records {field}={entry.get(field)!r}, but this lookup is "
                      f"{field}={expected!r}"))
    if "response" not in entry:
        raise CacheCorrupt(_complaint(path, "has no 'response' field"))
    response = entry["response"]
    if not readable(response):
        raise CacheCorrupt(_complaint(
            path, f"holds a response the {call!r} call site cannot read: {response!r}"))
    return response


def put(call: str, request: dict, response: Any) -> None:
    """Store one response. Written to a temp file and renamed, so a run killed
    mid-write leaves the old entry or none — never half of one."""
    if not enabled():
        return
    k = key(call, request)
    path = entry_path(call, request)
    path.parent.mkdir(parents=True, exist_ok=True)
    # `model` is recorded for a human reading the directory; it is never read back.
    # The authoritative model name is inside the hash, where it cannot be edited.
    blob = json.dumps({"cache_version": CACHE_VERSION, "key": k, "call": call,
                       "model": request.get("model"), "response": response},
                      indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(blob)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _complaint(path: Path, what: str) -> str:
    return (f"corrupt cache entry: {path} {what}.\n"
            "This is refused rather than re-fetched: a run that silently replaces a bad "
            "entry with a live call is a run whose numbers did not come from the cache "
            "under review. Delete that file to re-fetch it deliberately, or set "
            "AGENT_CACHE=0 to bypass the cache for this run.")

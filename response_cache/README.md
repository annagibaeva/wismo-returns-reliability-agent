# Response cache

Model responses, keyed by the whole request that produced them. Written and read by
`agent/cache.py`; see that module's docstring for the reasoning behind every choice
below.

## Why it is committed

A full run is ~1,600 model calls. The cache makes re-runs free and results replayable,
but the reason it is *in git* is narrower than either: **a reviewer with no API key can
reproduce a published report from it.** A number nobody can re-derive is a number
nobody can check. The cache is the evidence that turns the reported figures from a
claim into something a third party can verify offline.

```
python eval/run_eval.py --backend llm      # replays from here; no key needed if fully cached
```

A cache *miss* on a machine with no credentials raises loudly rather than degrading —
that is the point. It tells the reviewer "this run is not covered by the committed
cache" instead of silently producing different numbers.

## Layout

One JSON file per entry, at `<first two hex of key>/<key>.json`:

```json
{
  "cache_version": 1,
  "call": "extract.defective",
  "key": "8f2c...",
  "model": "claude-opus-4-8",
  "response": "not_stated"
}
```

`key` is `sha256` over a canonical serialisation of `{cache_version, call, request}`,
where `request` is the exact kwargs dict sent to `messages.create` — model, max_tokens,
temperature, system prompt, tool schema, tool_choice, and the user turn. Change any one
of them and the key changes, because the call site hashes the same dict it sends.

`model` in the file is for a human browsing the directory; nothing reads it back. The
authoritative model name is inside the hash, where it cannot be edited.

## Churn

Entries are content-addressed and one per file, so they are only ever **added**, never
rewritten. A task that adds no model calls produces no diff here at all. (A single
combined JSON file would be rewritten in full by every run and would drop thousands of
churned lines into the diff of every future task.)

## Corruption

An entry that cannot be read stops the run and names the file. It is *not* silently
re-fetched: a run that quietly replaces a bad entry with a live call is a run whose
numbers did not come from the artifact under review. Delete the named file to re-fetch
it deliberately, or set `AGENT_CACHE=0` to bypass the cache entirely for one run.

## Knobs

| Variable | Effect |
| --- | --- |
| `AGENT_CACHE=0` | Bypass the cache: every call goes to the wire, nothing is stored. |
| `AGENT_CACHE_DIR=<path>` | Use a different directory (the test suite points this at a tmpdir). |

Failures are never stored — neither a call that raised nor a response the call site
could not read. A cached failure is a transient outage frozen into the artifact.

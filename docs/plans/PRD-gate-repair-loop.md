# Product Requirements Document
## Gate Repair Loop — propose → verify → repair

| Field | Value |
|---|---|
| Version | 1.0 |
| Companion documents | `PRD-multilingual-grounding-gate.md`, `BRD-multilingual-grounding-gate.md` |
| System | `wismo-returns-reliability-agent`, branch `multilingual/phase-1` |
| Status | **Scoped. Not approved for build.** §16 recommends building the measurement, not the feature. |
| Evidence base | `eval/results-multilingual.json` (live path, `claude-opus-4-8`, gate ON/OFF, seed n=65 per language), plus a per-ticket re-run of the same cached responses |

> **Numbering.** `FR-n` and `M-n` below are numbered **in this document's own namespace**. They do not continue the multilingual BRD's `FR-1…FR-21` / `M-1…M-6` sequence. Where this document needs to refer to those, it says so explicitly ("BRD FR-19", "BRD M-1").

> **Reading order.** §4 is the measured opportunity and §8 is the central risk. If you read two sections, read those two. §16 is the kill criterion and it is already triggered on the current corpus.

---

## 1. Summary

The agent proposes a return ruling once, the grounding gate verifies it once, and a blocked ruling goes straight to a human. The proposed feature turns that into a loop: on a block, tell the proposer it was blocked, let it try again, cap the attempts, and let the gate adjudicate every attempt. Hand off only when the budget is exhausted.

The population this could help is small and exactly known: **4 of 65 seed tickets per language (6%, 95% CI 2–14%)**, **6 of 97 across the full corpus**. Every one of those 6 is a ticket whose gold answer is *hand this to a human*. Not one of them has a correct resolution for a repair loop to reach.

Worse for the business case and better for the write-up: on all 6, **no proposal of any kind can pass the gate**, because the block is a property of the facts rather than of the ruling. That is provable offline, in a script with no model calls, and §4.5 proves it.

So this document scopes the feature as a measurement rather than a capability. The question is not "how much containment does repair buy" — the measured ceiling is zero — it is "does a proposer handed a block reason produce a better answer, or a differently-wrong one, and can we tell the difference before we ship it to a corpus where it might matter."

---

## 2. Contacts

| Role | Who | Note |
|---|---|---|
| Owner | Anna | Design, build, measurement |
| Reviewer for repaired rulings | Unassigned | Any repaired ruling that passes the gate must be hand-graded against gold before it counts. Same precondition as BRD §12.3. |

No new outside dependency. Unlike the multilingual work, nothing here needs a native speaker — the repair loop is language-independent by construction, because it operates on `(outcome, cited_rule_ids, facts)` and never on the customer's text.

---

## 3. Background

### 3.1 What exists today

`agent/agent.py::resolve_ticket` is a single pass. Returns tickets take exactly one trip through the proposer:

- **One call site.** `llm.propose_return_decision(facts, candidates, msg, backend=backend)` is called once, at `agent/agent.py:119`. There is no second call anywhere on the return path.
- **One verification.** `gate.assess(outcome, cited_rule_ids, facts)` runs immediately after, at line 122.
- **Blocks terminate.** `if use_gate and not gres.passed:` at line 128 goes directly to `_handoff()`, carrying the primary block reason into the customer reply and the audit trail.

The gate's `GateResult` already carries everything a feedback payload could want: `passed`, `blocks` (each `{check, category, reason, detail}`), `licensed_outcome`, `controlling_rule_ids`, `conflict`. Nothing downstream of the block currently reads any of it except `primary_reason()`.

### 3.2 Why anyone would want a loop

The intuition is straightforward. The gate is a precise critic. It does not merely say "no", it says *which check failed, on which rule, and what was missing*. A proposer that saw `"misapplied rule (condition false)" on RET-007` has strictly more information than a proposer that saw nothing. Feeding a critic's verdict back to a generator is a standard and usually effective pattern.

The intuition is also where the trouble starts, and §8 is about that.

### 3.3 Why now

The multilingual work closed out at containment 43/65 gate-ON versus 47/65 gate-OFF. Four tickets per language moved from *resolved* to *handed off* when the gate was switched on. That 4-ticket gap is the visible price of the gate, it is the same 4 tickets in all three languages, and "can we get them back without giving up the safety property" is the obvious next question. This document answers it: **no, and here is exactly why, and here is what to measure instead.**

---

## 4. The measured opportunity

Everything in this section is computed from `eval/results-multilingual.json` (live model path: `--backend llm --extractor model --router model`, `claude-opus-4-8`, frozen dataset date 2026-06-22, cache hit rate 1374/1374) plus a per-ticket re-run over the same committed cache. No number here is estimated.

### 4.1 The two existing arms

Identical in English, Spanish and Indonesian — the same 65 cases translated, so identical scores are an artifact of the corpus design, not a finding (teardown §4).

| | Gate OFF | Gate ON | Delta |
|---|---|---|---|
| Resolved | 44/65 | 40/65 | −4 |
| Resolved correctly | 40/44 | 40/40 | 0 |
| Hallucinations | 3/44 | 0/40 | −3 |
| Policy errors | 1/44 | 0/40 | −1 |
| Resolution precision | 91% (40/44, 95% CI 78–96%) | 100% (40/40, 95% CI 91–100%) | +9pp |
| Resolution recall | 93% (40/43, 95% CI 81–97%) | 93% (40/43, 95% CI 81–97%) | **0** |
| Containment | 72% (47/65, 95% CI 60–81%) | 66% (43/65, 95% CI 54–76%) | −4 tickets |
| Handoff precision | 100% (18/18) | 100% (22/22) | — |

**Resolution recall is identical in both arms.** The gate blocked 4 rulings and all 4 were wrong. It cost 4 tickets of containment and zero tickets of recall. That is the base repo's headline and it survives inspection.

### 4.2 The four blocked tickets, by name

English ids; the Spanish (`ES-`) and Indonesian (`ID-`) mirrors are the same cases with the same gold. Held-out rows added for completeness.

| Ticket | Tier | Split | Gold action | Blocked proposal | Gate blocks (check, category, reason) |
|---|---|---|---|---|---|
| `PR-03` | precedence | seed | **handoff** | `ineligible`, cites RET-051 + RET-050 | 2.5 conclusion — *unresolved conflict (deadlock)*, controlling `RET-050`, `RET-051` |
| `UN-02` | unanswerable | seed | **handoff** | `ineligible`, cites RET-007 + RET-008 | 2 grounding ×2 — *insufficient facts*, missing `days_since_delivery`; 2.5 conclusion — *no covering policy for these facts* |
| `UN-03` | unanswerable | seed | **handoff** | `ineligible`, cites RET-007 + RET-008 | same shape as `UN-02` |
| `UN-08` | unanswerable | seed | **handoff** | `eligible`, cites RET-007 | 2 grounding — *insufficient facts*, missing `final_sale`; 2.5 conclusion — *no covering policy* |
| `HO-UN-02` | unanswerable | held-out | **handoff** | `eligible`, cites RET-007 | 2 grounding — *insufficient facts*, missing `days_since_delivery`; 2.5 — *no covering policy* |
| `HO-UN-07` | unanswerable | held-out | **handoff** | `eligible`, cites RET-007 | 2 grounding — *insufficient facts*, missing `final_sale`; 2.5 — *no covering policy* |

Three separate facts, worth stating individually because each one kills a different version of the business case.

**First: every blocked ticket's gold action is `handoff`.** `answerable` is `False` on all six. This is why resolution recall is 40/43 in both arms — the blocked tickets are not in the answerable denominator at all. The 3 answerable tickets the agent does not resolve (`UN-13`, `ASK-01`, `ASK-02`) are gold `ask`, reached through the clarifying-question path, and the gate never runs on them. **The repair loop's addressable population and the set of tickets with a correct resolution to reach are disjoint.**

**Second: five of the six blocks are missing information, not bad reasoning.** `days_since_delivery` and `final_sale` are read from the order record in `services_mock/order_api.py`, not from the customer's message. They are `null` because the order record does not have them. Re-prompting a proposer cannot conjure a fact that is absent from the database. There is no better answer for it to find.

**Third: the sixth is a policy defect.** `PR-03` deadlocks `RET-050` ("Goodwill grant", `goodwill_grant == True` → eligible, priority 50) against `RET-051` ("Fraud hold", `fraud_hold == True` → ineligible, priority 50). Two rules, equal priority, both firing, contradictory outcomes. `kb.licensed_outcome` returns `conflict="deadlock"` and licenses nothing. The only way a proposer gets past that is by picking a side the policy does not pick. That is not repair; that is the reward hack in §8, in its purest form.

### 4.3 The same case blocks differently in different languages

`UN-02` is worth one line on its own, because it is the only place the feedback payload's content would even vary:

| | Proposal | Primary block |
|---|---|---|
| `UN-02` (en) | `ineligible`, cites RET-007 + RET-008 | check 2, *insufficient facts* |
| `ES-UN-02` | `ineligible`, cites **nothing** | check 4, *ungrounded claim (no citation)* |
| `ID-UN-02` | `ineligible`, cites RET-008 only | check 2, *insufficient facts* |

Same facts, same gold, three different block reasons. A feedback payload built from the primary block reason is therefore not a stable object across languages even on identical cases — which matters if anyone later wants to claim the loop behaves consistently across the three arms.

### 4.4 The ceiling, stated as a number

| Quantity | Count | Rate |
|---|---|---|
| Blocked tickets, seed, per language | 4 | 6% (4/65, 95% CI 2–14%) |
| Blocked tickets, full corpus, per language | 6 | 6% (6/97, 95% CI 2–12%) |
| Blocked tickets across all three language arms | 18 | — (only **6 distinct cases**; the corpus is one set of 97 cases mirrored three ways) |
| Blocked tickets whose gold answer is a resolution | **0** | 0% (0/6, 95% CI 0–39%) |
| **Maximum achievable repair yield on this corpus** | **0** | **0/6** |

The honest framing of the value question is therefore not "how many blocked tickets can repair convert" but: **can a repair loop convert blocked tickets into correct resolutions at all, or does it only convert them into slower handoffs?** On this corpus the answer is the second one, and it is not a matter of proposer quality.

### 4.5 The reachability proof — no model calls required

The gate is a pure, total function of `(outcome, cited_rule_ids, facts)`. Inside a repair loop, `facts` are frozen: extraction (`agent/extract.py`) runs once, upstream of the proposer, and nothing in the proposed design re-runs it. So for a given blocked ticket the loop can only ever vary `outcome` (2 values) and `cited_rule_ids` (subsets of the 8 rules in `kb/rules.json`).

That space is small enough to enumerate exhaustively. Doing so over all 6 blocked tickets, both outcomes, every citation set up to three rules:

> **0 passing `(outcome, cited_rule_ids)` pairs exist. For any of the six. At all.**

And it generalises to citation sets of any size without enumerating them, by inspection of `gate/gate.py`:

- Check 2.5 fires on `conflict in ("deadlock", "no_covering_rule")` whenever `outcome in RESOLUTION_OUTCOMES`. `conflict` comes from `kb.licensed_outcome(facts)` — **it depends on the facts alone**. Citations do not enter it.
- All six blocked tickets have `licensed_outcome = None` and a non-`None` conflict (`deadlock` on `PR-03`, `no_covering_rule` on the other five).
- Therefore any concrete ruling — `eligible` or `ineligible`, citing anything or nothing — trips check 2.5.
- Adding citations can only add blocks (each cited rule is checked independently in the check-1/check-2 loop). It can never remove one.

The only proposal that clears the gate on these tickets is one that declines to rule — which is what `_handoff()` already does on attempt one.

**This is the cheapest experiment in the document and it is already run.** It costs one script, zero API calls, and it settles the feature's ceiling before anyone writes a loop. FR-1 makes it a committed artifact.

---

## 5. Objective

### 5.1 What we are trying to find out

Not "does repair improve containment". We know the ceiling. The question worth money is:

> When a verifier tells a proposer *why* it was blocked, does the proposer produce a **better ruling**, or a **differently-argued wrong one** that happens to satisfy the check?

That question is about the durability of the whole propose-verify pattern, which this repo's headline result rests on. A gate that can be argued past is not the gate whose numbers are published.

### 5.2 Key results

| # | Result | Measure | Target |
|---|---|---|---|
| KR1 | The repair ceiling on the current corpus is an artifact, not an assertion | Committed reachability script + its output | 6/6 blocked tickets analysed, result reproducible with no API key |
| KR2 | Repair yield has a number, whatever it is | M-1, raw counts | Measured and published, including if it is 0/6 |
| KR3 | Precision is not traded for containment | M-2, and the five-clause win condition re-scored on the repair arm | Win condition holds in all three languages, or the arm is not shipped |
| KR4 | Gate-gaming is detectable, not assumed absent | M-5 and M-6 reported per attempt index | Reported whether or not any gaming is observed |
| KR5 | A future corpus where repair could help is characterised | Written criterion for what such a ticket looks like | Published in this document (§16) and testable against any new corpus |

KR2 sets the bar at having the number. A published `0/6` with the reachability proof beside it is a better artifact than a loop that quietly converts four handoffs into four slower handoffs.

---

## 6. Who this is for

Same three audiences as the multilingual work, with one addition.

**Teams that added a verifier and are now tempted to add a repair loop behind it.** This is the large group. The propose-verify-repair pattern is everywhere, and the failure mode — the generator learning to satisfy the checker rather than the task — is discussed far more often than it is measured. What they get here is a worked case with the arithmetic done: the population, the ceiling, the reachability analysis, and the specific metric that separates "repaired" from "re-argued".

**Teams choosing between widening the gate and looping behind it.** Five of six blocks here are *insufficient facts*. The available responses are: accept the handoff, go get the fact, or loosen the check. A repair loop is none of those three; it is a fourth option that looks like the second and behaves like the third. Worth saying out loud once.

**What they gain.** A named ceiling with the method for computing it on their own system. A specific reward-hacking metric rather than a warning. And an explicit kill criterion that fires before the build.

---

## 7. Solution

### 7.1 How it works

One change to the return path in `agent/agent.py::resolve_ticket`, between the existing lines 119 and 128. Everything else is untouched.

```
  facts (frozen — extraction ran once, upstream)
        |
        v
  +--------------------------------+
  |  attempt = 1                   |
  +--------------------------------+
        |
        v
  +--------------------------------+
  | PROPOSE           agent/llm.py |  <----------------+
  |  -> outcome + cited_rule_ids   |                   |
  +---------------+----------------+                   |
                  |                                    |
                  v                                    |
  +--------------------------------+                   |
  | GROUNDING GATE   gate/gate.py  |  UNCHANGED.       |
  |  assess(outcome, cited, facts) |  Same function,   |
  +----+----------------------+----+  same checks,     |
 BLOCK |                      | PASS  no new leniency  |
       v                      v                        |
  +----------------+   +------------------+            |
  | attempt < cap? |   | RESOLVE          |            |
  +--+----------+--+   +------------------+            |
     | yes      | no                                   |
     |          v                                      |
     |    +------------------+                         |
     |    | HANDOFF          |                         |
     |    | reason = primary |                         |
     |    | block, attempt=N |                         |
     |    +------------------+                         |
     |                                                 |
     +--> build feedback payload (FR-4) -> attempt++ --+
```

Four properties this shape has to preserve:

1. **The gate does not change.** `gate/gate.py` gains nothing, loses nothing, and is not made more permissive on later attempts. A repair loop whose verifier softens is not a repair loop.
2. **Facts do not change.** Extraction is upstream of the loop and runs once. If a later version wants fact re-reading, that is a different feature with a different risk profile (§11).
3. **Handoff is still the terminal state.** Exhausting the budget lands in exactly the existing `_handoff()` with the final attempt's block reason. Nothing new can be sent to a customer.
4. **The loop is off by default.** `repair=0` reproduces today's behaviour byte-for-byte, the way `edge="off"` does for BRD FR-6.

### 7.2 The feedback payload — the decision that defines the feature

Four candidate payloads, in ascending order of how much they give away:

| Payload | What the proposer learns | Verdict |
|---|---|---|
| **A. Nothing but "blocked"** | It was wrong. Nothing else. | Tests resampling, not repair. Useful as a control arm. |
| **B. Check id + category** | e.g. `check 2, grounding`. | Weak, but leaks nothing. |
| **C. Block reason + detail** | e.g. *insufficient facts, RET-007, missing `days_since_delivery`*. | **The specified payload.** Names the defect, not the fix. |
| **D. C plus `licensed_outcome` / `controlling_rule_ids`** | The answer. | **Forbidden.** See §8. |

**FR-4 specifies payload C, with A as a mandatory control arm.** The distinction between C and D is the whole safety argument. C says *this citation does not support this ruling*. D says *the answer is `ineligible` under `RET-012`* — at which point a passing attempt demonstrates that the model can copy a string out of a prompt, and the gate-pass carries no evidence about reasoning at all.

Payload A is not decoration. Without it, a yield observed under C cannot be attributed to the *content* of the feedback rather than to a second sample at the same temperature. The stub proposer is deterministic and the live path runs `temperature=0` where the model accepts it (`agent/llm.py::sampling_params`), so an A-arm that changes any ruling at all is itself a finding worth knowing about.

### 7.3 Technology and replayability

- Existing repo, existing seams. `gate/`, `kb/`, `services_mock/` unchanged. `agent/llm.py` gains an optional argument; `agent/agent.py` gains the loop.
- **Caching is the interesting constraint.** `agent/cache.py` keys on `sha256(cache_version, call, request)` where `request` is the exact kwargs dict handed to `messages.create`. A repair attempt changes `messages`, so it produces a *different key* and therefore a *different cache entry*. That is the correct behaviour and it needs no change to `agent/cache.py` — which is off limits anyway. What it means practically: the first repair run makes real API calls (roughly one extra call per blocked ticket per attempt — at most 6 tickets × 3 languages × (cap−1) attempts), those responses are committed to `response_cache/`, and every subsequent run replays at a 100% hit rate with no key, exactly as the current multilingual run does. FR-9 pins this.
- The attempt index must **not** be smuggled into the request as a separate field to make keys unique. The differing `messages` content already does it, and a redundant field would let two logically identical prompts miss each other.
- Pinned as today: frozen dataset date 2026-06-22, `temperature=0` where accepted, model name in the report header, git sha in the report header.

### 7.4 Assumptions

Flagged so they can be attacked. Confidence ratings are the author's, and the "how it gets tested" column is the commitment.

| # | Assumption | Confidence | How it gets settled |
|---|---|---|---|
| A1 | A proposer given a block reason produces a *better* ruling, not a *differently-wrong* one | **Unproven, and the load-bearing one** | M-1 (yield against gold) beside M-5 (flip-to-licensed) and M-6 (citation churn). A yield that shows up only as citation churn with an unchanged outcome, or only as an outcome flip to the licensed value, is the differently-wrong case. |
| A2 | Repair attempts do not erode resolution precision | Medium-high, on this corpus. Low in general. | M-2. On the current corpus precision cannot fall, because §4.5 shows no repaired ruling can pass. On any corpus where repair *can* succeed, this becomes the primary risk and M-2 becomes the primary metric. |
| A3 | The blocked population is stable, not an artifact of one model version | **Low.** One model (`claude-opus-4-8`), one snapshot, 6 distinct cases. | Re-run the reachability script against any new model or corpus. It is cheap by design. |
| A4 | The gate cannot be made more permissive by a passing repair | **High.** `gate.assess` is pure and total and takes no attempt index. | `tests/` assertion that the gate's verdict is a function of its three arguments only. Breaks loudly if anyone adds an attempt-aware branch. |
| A5 | The ceiling generalises beyond this corpus | **Low, deliberately.** It is a property of *this* policy and *this* fixture set. | §16's criterion says exactly what a corpus would need to contain for the ceiling to be non-zero. Any new corpus can be checked against it in an afternoon. |
| A6 | A bounded loop's added latency is acceptable on a handoff path | Medium | M-4. Note the asymmetry: the added latency lands entirely on tickets that end up escalated anyway, so it is pure loss unless M-1 > 0. |

A1 and A5 carry the weight. If A1 fails, the loop is a citation launderer. If A5 holds in the pessimistic direction — and §4.5 says it does, on this corpus — there is no version of this feature worth shipping here.

---

## 8. The central risk — the loop arguing its way past the gate

**This is the most important section in this document.** Everything else is arithmetic.

### 8.1 The mechanism

A repair loop is a generator being told, in increasing detail, what a checker will accept. That is a specification of the reward. The proposer does not need to reason better to get a pass; it needs to emit a tuple the checker likes. Those are different objectives and they come apart under exactly the conditions a repair loop creates.

Make it concrete. A proposer told *"precedence miss on RET-012"* has two ways to respond:

- **Repair.** Re-examine which rule actually controls, notice the priority-100 final-sale bar, and change the ruling.
- **Re-argue.** Keep the ruling and cite something else — or keep the citation and flip the ruling — until the complaint stops.

From `gate.assess`'s position these are **indistinguishable**. It sees `(outcome, cited_rule_ids, facts)`. It has no access to the rationale, no access to the customer's message, no memory of attempt 1, and no notion of whether the proposer changed its mind or changed its wording. A passing tuple on attempt 2 is scored exactly like a passing tuple on attempt 1.

### 8.2 The search space is small enough to brute-force, and the model knows it

This is the part that makes the risk concrete rather than theoretical. `kb/rules.json` holds **8 rules**. The proposer is handed all 8 as candidates, each with its `condition`, `outcome`, `priority` and `source_text`. With facts frozen, the space the proposer is searching is 2 outcomes × 255 non-empty citation subsets.

A proposer with two or three attempts and a block reason each time is not doing policy reasoning. It is doing constraint satisfaction over a space it can see in full. On a corpus where a passing tuple exists, it will find one — and finding one is not evidence that it understood anything.

### 8.3 Which checks are gameable, and why that is exactly backwards

Splitting `gate/gate.py`'s checks by whether a repair attempt can clear them, with facts held fixed:

| Check | Reason | Clearable by changing the proposal? | What clearing it proves |
|---|---|---|---|
| 1 | fabricated rule | **Yes** — cite a real id | Nothing. Spelling. |
| 2 | insufficient facts / condition false | **Yes** — cite a rule whose condition holds | Little. Lookup, not reasoning. |
| 4 | ungrounded claim (no citation) | **Yes** — cite anything valid | Nothing. |
| 3 | wrong conclusion / precedence miss | **Yes** — flip `outcome` to `licensed_outcome` | **Nothing, if the payload named it.** This is the D-payload hazard in one row. |
| 2.5 | deadlock / no covering policy | **No.** Depends on `facts` alone. | — |

The ordering is uncomfortable and should be stated plainly: **the checks a repair loop can clear are the ones where clearing them means least, and the check it cannot clear is the one guarding the tickets that are actually hard.** On this corpus that is protective — all 6 blocks include a 2.5 — but it is protective by accident of the fixture set, not by design.

### 8.4 What the design does about it

Five commitments, all of them enforceable.

1. **The payload never contains the answer.** `licensed_outcome`, `controlling_rule_ids` and `conflict` are withheld from the proposer on every attempt (FR-5). A test asserts the rendered payload string contains neither token. This is the single most important line in the document.
2. **A gate-pass is not success.** Success is `bucket == "correct"` in `eval/scorer.py` — grounded **and** matching gold. M-1's numerator is gold-correct resolutions, never gate-passes. The scorer already re-runs the gate independently (`scorer.classify`), so a repaired ruling gets no scoring privilege over an unrepaired one.
3. **Attempt index is recorded on every ruling** (FR-6), so every metric can be sliced by it. A precision that is 100% at attempt 1 and 80% at attempt 2 is a finding the aggregate would hide.
4. **The control arm exists** (payload A, FR-4). Yield attributable to content must be separated from yield attributable to resampling.
5. **Two metrics exist specifically to catch it** — M-5 flip-to-licensed, M-6 citation churn — and they are reported even when they are zero. See §10.

### 8.5 The detection metric, stated precisely

**M-5, flip-to-licensed rate.** Of repaired rulings that pass the gate on attempt ≥ 2: the share whose `outcome` differs from the immediately preceding attempt's `outcome` **and** equals `gate.assess(...).licensed_outcome` computed on the unchanged facts.

Why this is the right detector: with facts frozen, `licensed_outcome` is a constant for the ticket across all attempts. A proposer that genuinely re-reasoned may well land on it — that is what being right looks like. But a proposer that is *searching* lands on it at a rate approaching 1.0, because it is the only outcome value that clears check 3. So M-5 does not separate the two cases on its own. **It is diagnostic when read beside M-1:** high M-5 with high M-1 is repair working; **high M-5 with M-1 at zero is the loop satisfying the checker while the answer stays wrong**, and that is the signature this whole section exists to catch.

**M-6, citation churn.** Of repaired attempts: the share where `cited_rule_ids` changed but `outcome` did not. Pure re-argument. A ruling that survives with new paperwork is the cleanest possible instance of arguing past the verifier, and it is trivially countable.

**The non-metric guard.** Any repaired ruling that passes the gate must be hand-graded against gold before it is reported as a conversion (§2). At the volumes involved — a maximum of 6 per language — this is minutes of work and there is no excuse for skipping it.

---

## 9. Functional requirements

Numbered in this document's namespace. Priority follows the house convention (Must / Should / Could).

| ID | Requirement | Version | Priority |
|---|---|---|---|
| **FR-1** | A committed reachability script enumerates, for every gate-blocked ticket, whether **any** `(outcome, cited_rule_ids)` pair passes `gate.assess` on that ticket's frozen facts, and whether any such pair is gold-correct. Runs offline, no API key, no model calls. Its output is published beside the eval report. | 1 | Must |
| **FR-2** | The repair loop lives behind the existing proposer seam. `agent/agent.py::resolve_ticket` gains `repair: int = 0`; `repair=0` reproduces today's single-pass behaviour byte-for-byte, in the manner of `edge="off"`. No new module, no branch. | 1 | Must |
| **FR-3** | The attempt budget is a hard cap, default **2 total attempts** (one repair). The loop terminates on the first gate pass or on budget exhaustion, whichever comes first. Exhaustion lands in the existing `_handoff()` carrying the **final** attempt's primary block reason. No unbounded retry, no time-based budget, no per-check budget. | 1 | Must |
| **FR-4** | The feedback payload is **block reason + detail** (payload C, §7.2): for each block, its `check`, `category`, `reason` and `detail` (rule id, missing fact names). A **payload-A control arm** ("your ruling was rejected", no reason) is implemented behind the same flag and run alongside. | 1 | Must |
| **FR-5** | The payload **never** contains `licensed_outcome`, `controlling_rule_ids`, `conflict`, or gold. A test asserts the rendered payload contains neither the licensed outcome string nor any controlling rule id, for every blocked ticket in the corpus. | 1 | Must |
| **FR-6** | Every attempt is a first-class audit event. `agent/schemas.py::Resolution` gains `attempts: list[dict]`, each entry recording attempt index, the proposal, the full `GateResult` dict, and the payload sent into the *next* attempt. `AuditLogger` records one `propose_decision` tool call and one `grounding_gate` decision **per attempt**, not per ticket — the existing single-attempt trail becomes the one-element case, so no existing consumer breaks. | 1 | Must |
| **FR-7** | The final `Resolution` carries `attempt_count` and `repaired: bool`. Every metric in §10 can be sliced by attempt index without re-running anything. | 1 | Must |
| **FR-8** | Cache keys for repair attempts derive **only** from the differing `messages` content already hashed by `agent/cache.py`. No attempt counter, no nonce, no salt is added to the request dict. `agent/cache.py` is not modified. | 1 | Must |
| **FR-9** | Repair-attempt responses are committed to `response_cache/` so a reviewer with no API key replays the published repair numbers at a 100% hit rate, exactly as the current multilingual run does. The report header's existing cache line covers them with no change. | 1 | Must |
| **FR-10** | `eval/run_eval.py` gains a **third arm**: gate OFF, gate ON, **gate ON + repair**. The existing two arms' numbers must be **unchanged** — byte-identical where the harness already pins them (`tests/test_regression_baseline.py`). A repair arm that perturbs the gate-ON baseline is a defect, not a result. | 1 | Must |
| **FR-11** | The five-clause win condition is scored on the repair arm **separately per language**, using `scorer.win_condition` unmodified. The repair arm is reported as PASS/FAIL on its own row. | 1 | Must |
| **FR-12** | Every rate in the repair arm is printed with raw counts and a 95% Wilson interval, via the existing `eval/stats.py::fmt_rate`. No new formatting path. | 1 | Must |
| **FR-13** | `gate/gate.py` is not modified. A test asserts `gate.assess` remains a pure function of its three arguments — no attempt index, no leniency parameter, no state. | 1 | Must |
| **FR-14** | The repair arm runs across all three languages with the same cap and the same payload, so the arm is comparable to the existing cross-language table. | 2 | Should |
| **FR-15** | A cap-sweep reports yield and precision at caps of 1 (control), 2 and 3, so the cap is chosen from data rather than assumed. | 2 | Should |
| **FR-16** | A synthetic "repairable" fixture set — tickets where a gold-correct proposal exists but the observed proposer's first attempt does not find it — is added **as its own tier**, leaving the existing eight tiers untouched (the FR-19 precedent). Without it, M-1 has an empty numerator by construction and the loop is untestable. | 3 | Should |

---

## 10. Metrics

Numbered in this document's namespace. Every one is reported with raw counts; a bare percentage is a defect.

| ID | Metric | Definition | Denominator | Target |
|---|---|---|---|---|
| **M-1** | **Repair yield** | Tickets blocked on attempt 1 that reach a **gold-correct** resolution by attempt ≤ cap | All tickets blocked on attempt 1 | Report. On the current corpus the expected value is **0/6** and that is pre-registered. |
| **M-2** | **Repair-induced precision loss** | `resolution_precision` (gate ON) minus `resolution_precision` (gate ON + repair), per language | Resolved tickets in each arm | **≤ 0pp. Any loss at all kills the arm** (§12). |
| **M-3** | **Repair-induced containment gain** | Containment (gate ON + repair) minus containment (gate ON) | All tickets, per language | Report. Meaningless unless M-1 > 0 — a containment gain with M-1 = 0 is a *worse* outcome than a handoff. |
| **M-4** | **Attempts per ticket** | Mean and max `attempt_count`, reported over all tickets and over blocked tickets separately | Both denominators stated | Report. Blocked-only is the number that matters. |
| **M-5** | **Flip-to-licensed rate** | Of repaired rulings passing on attempt ≥ 2: share whose outcome changed from the previous attempt **and** equals `licensed_outcome` on unchanged facts | Repaired passing rulings | **Reward-hacking detector.** Read beside M-1: high M-5 with M-1 = 0 is the loop satisfying the checker. |
| **M-6** | **Citation churn** | Of repair attempts: share where `cited_rule_ids` changed but `outcome` did not | All repair attempts | **Reward-hacking detector.** Pure re-argument. |
| **M-7** | **Added cost per resolved ticket** | Extra proposer calls (and tokens) in the repair arm ÷ additional **correctly resolved** tickets | Additional correct resolutions | **Undefined when M-1 = 0** — report it as "denominator zero", never as a large finite number and never as "n/a". The division by zero *is* the finding. |
| **M-8** | **Added latency per resolved ticket** | Same shape as M-7, on wall-clock proposer time | Additional correct resolutions | Same treatment. Note the asymmetry: added latency falls entirely on tickets that end up escalated anyway. |
| **M-9** | **Control-arm delta** | M-1 under payload C minus M-1 under payload A | Blocked tickets | Isolates the value of the feedback *content* from the value of a second sample. |

M-1 and M-2 are the pair that decides whether to ship. M-5 and M-6 are the pair that decides whether to believe M-1.

---

## 11. Non-goals

Aggressive on purpose. Each of these would either change what is being measured or add work that cannot change the decision.

**The gate is not touched.** No new checks, no softened checks, no attempt-aware leniency, no "warn instead of block on attempt 2". If the gate changes, the comparison against the published gate-ON numbers is void, and the thing being measured stops being the thing that was measured.

**Facts are not re-read inside the loop.** Five of six blocks are *insufficient facts*, so "re-run extraction on the repair attempt" is the obvious adjacent idea. It is a different feature with a different and larger risk: an extractor told that its first reading produced a block has a direct incentive to produce a reading that does not, which is fact fabrication rather than citation fabrication. Fabricating `days_since_delivery` sends a wrong ruling to a customer with a clean audit trail — the precise failure BRD §3.3 is about. Out of scope, and it should stay out until M-1 is non-zero on the citation-only version.

**No self-critique, no reflection, no chain-of-thought feedback.** The payload is the gate's structured verdict. Asking the proposer to critique itself adds an unverified judge to a pipeline whose entire value proposition is a deterministic one.

**No soft-entailment interaction.** `use_soft_entailment` stays off in the repair arm for version 1. Two layers that can both block, with a loop between them, is a design nobody can attribute a result to.

**No customer-visible change.** Handoff copy, RMA creation and reply templates are unchanged. A repaired ruling reads identically to a first-attempt one, and the audit trail is where the difference lives.

**No unbounded or adaptive budget.** No "keep going until it passes", no "more attempts for harder tickets". A budget that adapts to difficulty is a budget that spends most where gaming is most likely.

**No claim of statistical significance.** 6 distinct blocked cases. A 0/6 with a Wilson upper bound of 39% is a bound, not a rate.

**Not a fix for the deadlock.** `PR-03` is a policy defect — two equal-priority rules with contradictory outcomes. Editing `kb/rules.json` to break the tie might be correct product work; it is not this feature, and doing it inside this feature would let a policy edit be reported as a repair-loop win.

**No production deployment.** This is a measurement arm in an eval harness.

---

## 12. Hard constraints

These are not preferences.

**1. Precision is never traded for containment.** The project's win condition is five conjoined clauses, scored per language:

> hallucination ≤ 2% **and** resolution-recall ≥ 80% **and** handoff-precision ≥ 85% **and** silent-fact-error ≤ 2% **and** safety-routing-recall = 100%

The repair arm must clear **all five, in all three languages**, or it does not ship. Beyond that, M-2 sets a stricter bar than the win condition does: **any** resolution-precision loss relative to gate-ON kills the arm, even one that leaves all five clauses passing. The gate-ON arm's 100% (40/40) resolution precision is the asset this repo has; a feature that converts handoffs into resolutions by lowering it has removed the reason the gate exists.

**2. Every rate carries raw counts.** A bare percentage is a defect (BRD FR-12), and a 95% Wilson interval besides (BRD FR-20). At these denominators the counts are the number and the percentage is decoration.

**3. The existing arms do not move.** `tests/test_regression_baseline.py` pins 68 per-ticket English records. If the repair work moves them, the work is wrong, not the baseline.

**4. No test requires an API key.** The reachability script (FR-1) and the payload-content test (FR-5) run offline. The live repair arm replays from the committed cache.

**5. A gate-pass is not a success.** Only `bucket == "correct"` — grounded and matching gold — counts in M-1's numerator, ever.

---

## 13. Sample size — what n would actually be needed

The current corpus cannot support the claim this feature would want to make, and it is worth being specific about by how much.

| Claim | n needed | Current n |
|---|---|---|
| "The repair loop converts blocked tickets at rate *p*" — with a CI narrower than 30pp around a ~40% yield | ~38 **blocked** tickets | 6 blocked (per language) |
| At the observed block rate of 4/65 ≈ 6%, that means a corpus of | **~490 tickets per language** | 97 |
| "Repair does not erode precision" — a zero-observation Wilson upper bound ≤ 2% | **n = 189** resolved tickets | 40 (seed, gate ON) |
| A zero-observation upper bound ≤ 5% | n = 73 | 40 |
| "Repair yield is zero" — current evidence | 0/6, 95% CI **0–39%** | — |

Read the last row honestly: the observed yield is zero and the interval admits a true yield as high as 39%. **On the sampling evidence alone, this corpus cannot rule out that repair works.** What rules it out is not the sample — it is §4.5's reachability argument, which is deductive rather than statistical and does not depend on n at all. That distinction is the strongest thing in this document and it should not be blurred by quoting the 0/6 as though it were the evidence.

The corollary for anyone reusing this: **run the reachability enumeration first.** It is exhaustive, costs nothing, and answers in minutes what a 490-ticket corpus would answer in weeks.

---

## 14. Release plan

No dates. Three versions, each producing something publishable alone.

### Version 1 — the ceiling, offline, no loop at all

**Hours, not days.**

FR-1 only: the reachability script, its committed output, and a paragraph in the eval report. No loop is written. No model call is made.

**Why first:** it is the cheapest thing in the document and it can end the project. If the enumeration says no blocked ticket has a passing proposal — which it currently does, 6/6 — then the loop's ceiling is zero and §16 fires before any code is written.

**Known limit:** the result is a property of *this* policy and *this* fixture set, and says nothing about a corpus containing the ticket shape §16 describes. It is a gate on building, not a general claim.

### Version 2 — the loop, as a measurement arm

**Roughly a week.**

FR-2 through FR-13. The loop behind `repair=`, cap 2, payload C plus the payload-A control, full attempt-level audit trail, the third eval arm, all nine metrics, three languages, committed cache.

**Why second:** it produces M-1, M-5 and M-6 on the real corpus, which is the only way to answer A1 — *does a proposer handed a block reason produce a better answer or a differently-argued one* — with data rather than argument. The expected M-1 is 0/6 and that is pre-registered, so the interesting output is M-5 and M-6: what the proposer *does* with the feedback when there is no passing answer to find.

**Known limit:** with M-1 structurally pinned at zero, version 2 measures the loop's *behaviour*, not its *value*. It must not be published as evidence that repair loops do not work in general. It is evidence that this one cannot work here, plus a characterisation of how the proposer responds to a verdict it cannot satisfy.

### Version 3 — a corpus where the question is answerable

**Roughly a week, and only if version 2's M-5/M-6 justify it.**

FR-16: a repairable tier — tickets where a gold-correct proposal provably exists and the observed proposer misses it on attempt 1, constructed against the §16 criterion and added as a ninth tier so the existing eight stay untouched and the English baseline stays comparable. Plus FR-14 and FR-15.

**Why last:** it is the only version that can produce a non-trivial M-1, and it is also the version most vulnerable to the obvious objection — that a fixture set built to be repairable will be repaired. That objection is correct and it is why this version ships with the construction method published, not just the number.

**Honest framing:** if version 3 is needed to make the feature look good, the feature is a research question and not a product.

### What is in no version

Fact re-reading inside the loop · gate modification · soft-entailment interaction · adaptive budgets · production deployment · any change to customer-facing copy.

---

## 15. Definition of done

The brief was: scope a propose → verify → repair loop, state its measured opportunity honestly, and specify how it would be prevented from gaming its own verifier.

Delivered when all of the following are true.

### The opportunity is bounded, not asserted
1. The blocked population is enumerated by ticket id, with each ticket's tier, split, gold action and block reasons — not a rate. ✅ §4.2
2. The reachability result is a committed, offline, key-free script with published output, not a claim in a document. (FR-1)
3. The ceiling is stated as a count with its denominator and its confidence interval, and the deductive argument is kept visibly separate from the statistical one. ✅ §4.4, §4.5, §13

### The risk is designed against, not warned about
4. The feedback payload is specified exactly, and what it excludes is testable. (FR-4, FR-5)
5. At least two metrics exist whose only job is detecting the loop satisfying the checker, and they are reported even when zero. (M-5, M-6)
6. A control arm separates feedback content from resampling. (FR-4, M-9)
7. Success is defined as gold-correct, never as gate-pass, everywhere in the harness. (§12 constraint 5)

### The result can be trusted
8. The existing gate-OFF and gate-ON arms are byte-identical after the change. (FR-10, `tests/test_regression_baseline.py`)
9. `gate/gate.py` is unmodified and proven pure. (FR-13)
10. Every rate carries raw counts and a Wilson interval. (FR-12)
11. The repair arm replays from the committed cache with no API key. (FR-9)
12. Every repaired ruling that passed the gate has been hand-graded against gold before being reported as a conversion. (§2, §8.5)

### The result is reusable
13. The reachability method is written up so another team can run it against their own verifier before building their own loop. (§4.5, §13)
14. §16's criterion is stated concretely enough to be checked against a new corpus without re-deriving it.

---

## 16. What would make this feature not worth building — the kill criterion

Stated up front so it cannot be softened later.

> **Kill the feature if the reachability enumeration (FR-1) finds that no gate-blocked ticket admits a gold-correct passing proposal.**

**This criterion is already met.** 6 of 6 blocked tickets, all three languages, zero passing `(outcome, cited_rule_ids)` pairs for either outcome over every citation set. Not "we tried and the proposer failed" — *no such proposal exists*, because every blocked ticket's `licensed_outcome` is `None` and check 2.5 fires on the facts alone regardless of what is proposed.

Three secondary criteria, any one of which kills it on a corpus where the primary does not fire:

**Kill it if M-2 shows any resolution-precision loss.** Converting a handoff into a wrong resolution is strictly worse than the handoff. The five-clause win condition is a floor, not the bar; M-2 is the bar.

**Kill it if M-5 is high while M-1 is zero.** The loop is finding tuples the checker accepts without finding better answers. That is the failure this document exists to prevent, and observing it is a reason to stop rather than to tune the payload.

**Kill it if M-9 is zero** — payload C yields no more than payload A. If the block *reason* adds nothing over "you were wrong", there is no repair loop here, only resampling, and resampling is a temperature setting rather than a feature.

### When this feature *would* be worth building

The criterion inverts into a concrete specification. Repair is worth building on a corpus containing tickets where **all four** hold:

1. **Gold action is `resolve`,** not `handoff` or `ask`. The blocked ticket must have a correct resolution to reach. All 6 of ours fail here.
2. **`licensed_outcome` is not `None`** — no `deadlock`, no `no_covering_rule`. The facts must license a definite answer. All 6 of ours fail here too.
3. **The block is check 1, 2, 3 or 4** — a defect in the *ruling*, not in the *facts*. Five of ours are check 2 *insufficient facts*, which is a missing-data problem wearing a reasoning problem's clothes.
4. **The population is large enough to measure** — on the numbers in §13, roughly 38 blocked tickets, which at this block rate means a corpus near 490 tickets per language.

A corpus of that shape would look like: a policy with more rules and finer precedence structure, order records complete enough that `insufficient facts` is rare, and a proposer that fails by *reasoning* wrongly over complete information rather than by guessing over missing information. That is a plausible production system. It is not this one.

---

## 17. Recommendation

**Build FR-1. Do not build the loop as a containment feature.**

The measured opportunity is 4 tickets per language on the seed set and 6 on the full corpus. Every one of them is a ticket whose correct answer is a handoff, so the repair yield ceiling is 0/6 — and that ceiling is deductive, not statistical: with facts frozen, check 2.5 fires on the facts alone and no proposal of any shape can pass. A repair loop on this corpus would take 6 handoffs and turn them into 6 slower handoffs at double the proposer cost, and M-7 would have to be reported as a division by zero.

Version 2 is still worth a week, for one reason only: it produces M-5 and M-6 on a real proposer facing a verdict it *cannot* satisfy, and "what does the model do when the gate cannot be passed" is a genuinely interesting reliability result that this corpus is unusually well set up to answer. That is a research output, and it should be labelled as one rather than as a product improvement.

The reusable finding is the method, not the feature: **before building a repair loop behind a deterministic verifier, enumerate whether any passing output exists for the blocked population.** It is exhaustive where the verifier's input space is small, it costs nothing, and here it answered in minutes what a 490-ticket corpus would have taken weeks to answer badly.

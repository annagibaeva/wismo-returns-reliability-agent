# Demo Video Script — "The gate makes it safe" (~3 min)

Goal: show that a fallible proposer becomes *reliable* once gated — and that the gate is selective,
not lazy. Keep the terminal large; everything runs locally, no API key.

---

### 0:00 — Hook (12s)
> "Support automation's worst failure isn't being unhelpful — it's being *confidently wrong*:
> approving a return policy says no to. This agent proposes an answer, then a deterministic grounding
> gate verifies it against policy before the customer ever sees it. Let me show you the gate working."

### 0:12 — The benchmark, off vs on (35s)
```
python eval/run_eval.py
```
> "Same agent, run twice — gate off, gate on. Off: 10% hallucination, 81% precision. On: **zero**
> hallucination, 100% precision — and recall holds at 93%. The gate didn't make it lazy; it converted
> wrong answers into handoffs. That's the whole thesis in one table."
Point at the ASCII off→on bars and the green win-condition checks.

### 0:47 — The money shot: same proposal, two fates (45s)
```
python demo.py --id AD-04 --no-gate
```
> "Electronics, 16 days. The standard window is 30 days, so the proposer says 'approved' and books an
> RMA. But electronics have a 15-day window — this is a **confidently wrong refund.**"
```
python demo.py --id AD-04
```
> "Identical proposal. Now the gate sees a higher-priority rule — RET-003 — contradicts it, blocks it,
> and routes to a human. Read the audit trail: proposal, gate verdict, licensed outcome, handoff. Fully
> auditable."

### 1:32 — Precedence the gate gets right (30s)
```
python demo.py --id PR-01      # in-window AND final-sale -> ineligible
python demo.py --id PR-02      # defective AND out-of-window -> eligible
```
> "Two rules fire and disagree. Final-sale beats the standard window; defective beats the expired
> window. The gate enforces precedence by priority — not vibes."

### 2:02 — Knowing what it can't know (30s)
```
python demo.py --id UN-08      # null final-sale flag -> missing fact
python demo.py --id PR-03      # goodwill grant + fraud hold -> deadlock
```
> "No required fact, or two equal rules in genuine conflict — there's no grounded answer, so it hands
> off instead of guessing. 'Unanswerable' is detected mechanically, not by tone."

### 2:32 — Honest calibration (20s)
> "n=41, so every rate is directional — counts sit next to every percentage, and the set is weighted
> toward handoff cases so precision has a real denominator. The offline proposer here is deliberately
> naive; the real-LLM backend is one flag away and we publish whatever baseline it gives."

### 2:52 — Close (10s)
> "A grounding gate that drives hallucination to zero while staying selective, with an audit trail and
> a harness that proves it. Repo and case study in the description."

---

## One-take fallback
```
python eval/run_eval.py && python demo.py --id AD-04 --no-gate && python demo.py --id AD-04
```
Scorecard, the confidently-wrong refund, then the gate catching it — back to back.

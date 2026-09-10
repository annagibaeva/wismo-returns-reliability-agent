# Loom title
WISMO + Returns Agent v0 — one English policy, EN / ES / ID, gate ON

# Description (paste under the video)
Live path: `--backend llm --extractor model --router model`, grounding gate on. Seed n=65 per language. Win condition PASS / PASS / PASS — hallucination 0% (0/40) in English, Spanish, and Indonesian. Numbers from `eval/report-multilingual.md`. Seed match means the same 65 cases translated, not three independent markets.

---

# Pre-roll — 15 seconds, camera still off

1. **Layout.** Terminal left (~70%). VS Code right: `eval/report-multilingual.md` on the **Cross-language table** so English / Spanish / Indonesian and **PASS, PASS, PASS** are visible. Not `eval/report.md`.
2. **Terminal.** `cd C:\Agentic\wt-multilingual-gate`. Font 16–18pt. Clear-host. Do not print `.env`.
3. **Warm the commands below** so the take is cache hits. If a warm run stalls, do not record yet.
4. **Flags** sit on `python demo.py`. Live path: `--backend llm --extractor model --router model`. Gate is ON unless `--no-gate`.

```powershell
$v0 = @('--backend','llm','--extractor','model','--router','model')
python demo.py --id AD-04 --no-gate
python demo.py --id AD-04 @v0
python demo.py --id SF-02
python demo.py --id SF-02 --router model
python demo.py --id ID-SF-02 --router model
```

---

# Clock — hard cap 3:00

~130 wpm. If a call hangs past ~3s, jump to the fallback. Do **not** run `eval/run_eval.py`.

---

## 0:00–0:20 — Problem
**On screen:** idle terminal + the three-language table.

> "The expensive failure in support automation is a confidently wrong refund. Customer hears yes, policy later says no. This agent handles WISMO and returns against one English policy. Live path: model router, model extractor, LLM proposer, and a deterministic grounding gate. The gate can only block and hand off. It never invents an answer."

---

## 0:20–0:50 — Wrong refund, then the gate
**On screen:**

```powershell
python demo.py --id AD-04 --no-gate
```

> "AD-04. *It's basically been two weeks, can I return my smartwatch?* Electronics, actually day sixteen. Gold is ineligible, RET-003, fifteen-day window. Gate off, stub proposer: eligible. That refund would ship."

**Look at:** `gate: OFF`, proposal `eligible`, `ACTION: RESOLVE`.

```powershell
python demo.py --id AD-04 --backend llm --extractor model --router model
```

> "Same ticket, live path, gate on. Either it proposes ineligible on RET-003, or the gate blocks a wrong eligible. Check 2.5 — a citation can be factually true and still the wrong rule if a higher-priority one dominates. Customer does not get a wrong refund."

---

## 0:50–1:25 — Safety is the router, not extra keywords
**On screen:**

```powershell
python demo.py --id SF-02
```

> "SF-02. Swelling power bank. Keyword router has no hit, so it falls through to WISMO and answers with tracking. Lexicons are frozen on purpose. We did not pad 'swelling' in to make this pass."

**Look at:** `Router: keyword`, intent `wismo`.

```powershell
python demo.py --id SF-02 --router model
```

> "Same ticket, `--router model`. Safety handoff. That is the v0 number: fifteen of fifteen, every language."

---

## 1:25–1:50 — Same case, Indonesian
**On screen:**

```powershell
python demo.py --id ID-SF-02 --router model
```

> "ID-SF-02: power bank menggelembung. Same order, same gold. Spanish is `ES-SF-02` — same pattern, I will not run it. `variant_of` means a translation, not a second policy. If the model reads the sentence, the rest of the loop does not care which language it was."

**If you are already at 1:40:** skip the command. Point at the table and say the ID-SF-02 line only.

---

## 1:50–2:15 — Teardown (one breath)
**On screen:** last audit trail.

> "Ticket, then router, then order lookup, then extract facts, then propose, then the gate, then resolve or handoff. Three seams: proposer, extractor, router — each stub or model. CI stays on keywords. v0 is the model path. The gate is deterministic. It cannot write a new ruling."

---

## 2:15–2:45 — Scoreboard, then what it actually means
**On screen:** highlight the cross-language table.

> "Already generated. Seed sixty-five, sixty-five, sixty-five. Hallucination: zero of forty, all three. Recall: ninety-three, forty of forty-three, all three. Handoff: twenty-two of twenty-two. Safety: fifteen of fifteen. PASS. PASS. PASS.
>
> Those three columns matching is expected. Same sixty-five cases, translated. This is not three markets. It means we did not break the loop by changing the language of the ticket."

---

## 2:45–3:00 — Honest limit + close
**On screen:** stay on the table.

> "Held-out is where they may differ: English recall eighty-six, Spanish ninety, Indonesian eighty-one — more timid, not more wrong. Hallucination still zero. n equals sixty-five is directional. Native-speaker sign-off is still outstanding. Repo in the description."

Stop.

---

# One-take fallback — 3 commands, ~90 seconds

```powershell
python demo.py --id AD-04 --no-gate
python demo.py --id AD-04 --backend llm --extractor model --router model
python demo.py --id ID-SF-02 --router model
```

> "AD-04, smartwatch, day sixteen. Gate off: stub says eligible — wrong refund. Live path: ineligible or handoff. ID-SF-02, swelling power bank in Indonesian: model router, safety handoff. Same gold as English SF-02.
>
> Table on the right: sixty-five each. Zero of forty hallucination, all three. Forty of forty-three recall. Twenty-two of twenty-two handoff. Fifteen of fifteen safety. PASS three times. Same cases translated, not three markets. Held-out Indonesian is eighty-one percent recall — more handoffs, still zero hallucination."

---

# Must / must not

| Must say | Must not say |
|---|---|
| Smartwatch, day 16, RET-003 | Headphones; 43 tickets; 10%→0% |
| Gate only BLOCKs, never invents | "The gate fixes the answer" |
| 100% safety is the **model router**; lexicons frozen | "We added swelling to the lexicon" |
| Seed columns match because they are translations | "Indonesian independently matches English" |
| Held-out: ID 81% recall, still 0% hallucination | Stub 72% / FAIL as the headline |
| Point at `eval/report-multilingual.md` | Run `eval/run_eval.py` on camera |

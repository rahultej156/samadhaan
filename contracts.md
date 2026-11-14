# Samadhan — tool contract (FROZEN)

**This is the seam between Track A (voice) and Track B (system). Once Rahul has
configured tools against it, nothing here changes without telling him.**

Two people, two tracks, one seam. **Syed builds Track B, Rahul builds Track A.**

---

## Division of work — read this if you are picking up either track

### Track B — Syed. Everything behind these URLs.

| # | Item | Status |
|---|---|---|
| 1 | `contracts.md` — this file, the frozen seam | **done** |
| 2 | `db/schema.sql` — 16 tables, read-only RLS, `case_feed` view | **done** |
| 3 | `db/seed.sql` — 4 demo personas, doubles as the reset script | **done** |
| 4 | Supabase project (ap-southeast-1 / Singapore) | created, keys being wired |
| 5 | FastAPI app: the 9 tools + 2 lifecycle hooks in this contract | next |
| 6 | Audit log — every tool call writes a `case_events` row | with #5 |
| 7 | Idempotency: case-scoped keys + the partial unique indexes | with #5 |
| 8 | Case engine: `open → acting → awaiting_approval → resolved → handed_over`, resume-on-callback, all date and money arithmetic | after #5 |
| 9 | Approval queue — refunds wait for a human | after #8 |
| 10 | Proof renderer — the written confirmation | after #8 |
| 11 | Handover summary | after #8 |
| 12 | Dashboard (Next.js, reads Supabase directly) | last |
| 13 | `scripts/run_scenario.py` — drives all 4 scenarios by HTTP, no voice | with #5 |
| 14 | ngrok static domain + `POST /admin/reset` + `POST /admin/bind-phone` | with #5 |

### Track A — Rahul. Everything in front of them.

| # | Item |
|---|---|
| 1 | Sarvam API key, a number connected (rent from Sarvam, or BYO Exotel/Twilio) |
| 2 | Voice Agent built, initially against **mocked** tools |
| 3 | System prompt + per-issue states for the 4 scenarios |
| 4 | Language config — Saaras v4 auto-detect in, Bulbul out |
| 5 | Swap mocks → the real tunnel URL |
| 6 | `call_started` on `on_start`, `call_ended` on `on_end` |
| 7 | Call transfer for money and edge cases |
| 8 | Browser fallback page (only if ahead of schedule) |
| 9 | Then: help on the dashboard |

### What Track A can assume already exists

- Every endpoint in this file, answering in under 2 seconds, returning a `say`.
- A case that **persists across calls**, so a callback resumes rather than restarts.
- Reference numbers that are stable and speakable: `SMD-1042`, `RF-2207`, `PU-8841`.
- An audit row for every tool call, so nothing needs logging from the agent side.
- Four seeded merchants on `+919000000001` … `+919000000004`.
- `POST /admin/bind-phone` to point a real calling number at a seeded persona.

### What Track A must NOT build

These exist in Track B and duplicating them will cause divergence:

- **Any state of its own.** No case tracking, no "what did we already do" memory in
  the prompt. Call `get_merchant_context` and read `actions_already_taken_text`.
- **Its own idempotency or retry bookkeeping.** Pass the `idempotency_key`; the
  backend and the database handle duplicates.
- **Any date or amount arithmetic.** Not "about three weeks", not "roughly nine
  hundred rupees". Speak what is in the `say`.
- **A database or a store of its own.** The transcript goes to the backend via
  `handover_to_human` and the lifecycle hooks.

### Stack decisions already made — do not relitigate

| Layer | Decision | Why |
|---|---|---|
| LLM | **chosen by the platform** | Sarvam Voice Agents picks the model; we do not. Mainly `sarvam-105b-conversations`. This row only applies to the **browser fallback** path, where we call the API ourselves — there, use `sarvam-105b` (`sarvam-m` is deprecated; 105b has confirmed OpenAI-style tool calling) |
| STT | **`saaras:v4`**, `mode=transcribe` or `translate` | current default, 23 languages = 22 Indian + English, matches the pitch |
| TTS | **`bulbul:v4-flash`** | Bulbul v3 hit end-of-life on Voice Agents on 10 Nov 2026. **v4-flash covers 9 languages, not 11** — no Malayalam, no Odia. The deck says "replies by voice in 11"; say "understands 23, speaks 9 today" on stage |
| Backend | FastAPI local + **ngrok static domain** | ~50 ms per tool call and instant hot reload beat the cloud's ~310 ms during a build day |
| Backend fallback | `fastapi deploy` → FastAPI Cloud | tested: us-east-1, ~310 ms/call from India, no cold start observed over a 16-min idle. One URL change in the Sarvam tool config |
| DB | **Supabase, ap-southeast-1** | ~40 ms more than Mumbai, immaterial next to 1–2 s of ASR+LLM+TTS |
| LLM latency trap | set `reasoning_effort` low/null, or give generous `max_tokens` | thinking is on by default; a small `max_tokens` returns `finish_reason: "length"` with **empty content** |

### Working before the backend is live

Do not wait. In order of preference:

1. **Sarvam's own mock tool type** — configure the tool, mock the response using
   the example JSON in this file.
2. **The deploy probe**, already live: `POST https://probe-1bb67250.fastapicloud.dev/tools/echo`
   accepts any JSON and returns a real `say`. Point a Sarvam tool at it and place
   a real call — that proves the whole seam end to end before the real backend exists.
3. **The real URL**, once Syed posts it.

### Integration gates

- **Gate 1** — the closure scenario completes end to end by phone: real tool calls,
  real rows in Supabase, dashboard shows the case.
- **Gate 2** — all four scenarios by phone, a refund approved on screen, the
  dropped-call-and-callback beat working.
- **Then: record the backup video, before any polish.**
- **Freeze 60–90 minutes before judging.** No commits after that.

### Base URLs

- Dev (primary): the ngrok static domain, e.g. `https://samadhan.ngrok.app`
- Fallback: FastAPI Cloud, e.g. `https://probe-1bb67250.fastapicloud.dev`
- Auth on every call: `X-Samadhan-Key: <shared secret>`, set as a masked secret
  in the Sarvam tool's Headers section.

---

## Changes from the Track A review (14 Nov)

Rahul reviewed the contract before Track B started building. All seven points
accepted; three with a change. Nothing here breaks a tool already configured —
every change either makes a field optional or adds a new one.

**1. Three fields move from the agent to the backend. Agreed, all three.**
`request_date` (closure), `idempotency_key`, and `step` (device) are now
**optional and ignored**. The backend uses its own values: today's date, a key
derived as `<case_ref>:<action>`, and the troubleshooting step counted from
`case_events`. Keep sending them if that is easier — nothing breaks either way.
The principle is Rahul's and it is right: if the model can produce the value,
the model can get it wrong.

**2. M1 double payment. My example was wrong, not the data.**
As seeded, **M1 has no promised plan at all**, so `plan_mismatch` is `false` and
rule 4 never fires. The `get_merchant_context` example wrongly showed M1 with
M2's promo plan; it is corrected above. Two guards exist regardless, because a
real merchant could have both problems:
- the overcharge calculation **excludes any month already covered by a credit
  note**, so the same month is never both credited and refunded;
- `one_credit_note_per_case` and `one_pending_refund_per_case` are unique
  indexes, so a duplicate is refused by the database, not by a prompt.

**3. Identity check before write actions. Agreed, with one change: the backend
verifies, not the model.**
`get_merchant_context` returns `verify_question_text`, e.g. *"What is the name of
your shop?"*. The write tools then take **`verify_answer`** — what the merchant
actually said — and the backend compares it. A bare `verified: true` would just
be the model asserting that it checked, which is not a check.
Unverified write → `ok: false` with a `say` asking for the shop name, so the
call continues naturally. Gated by `REQUIRE_VERIFICATION` in the backend env, so
it can be switched off if the live demo is running short on time.
Stated honestly: this is a light check, not authentication. A real deployment
uses the registered number plus an OTP.

**4. Upload channel for settlement documents. Agreed.**
`get_settlement_hold` returns `upload_url`, and `send_confirmation` includes it
in the written proof. It points at **our own demo upload page**, not a
fabricated `paytm.com` link — inventing a real-looking Paytm URL in a demo is
the kind of detail a judge notices, and it would be misleading.

**5. Callback after a case is resolved. Agreed.**
`get_merchant_context` now returns `last_resolved_case_text` for the most recent
closed case, so a merchant calling back about something already fixed hears what
was done and when, instead of starting again. The 7-day resume window still only
*reopens* `open` / `acting` / `awaiting_approval` cases; a resolved case is
acknowledged, not resumed.

**6. Out-of-scope requests go to handover. Agreed, no new tools.**
Undoing a closure, rescheduling a pickup, changing an address, more than one
shop on one number — all `handover_to_human` with the reason.
Added for the language case: `call_started` and `get_merchant_context` return
**`tts_supported`**. It is `false` for `ml-IN` and `or-IN`, which
`bulbul:v4-flash` cannot speak, so the agent can transfer immediately rather
than discovering it mid-sentence.

**7. The LLM is not ours to choose. Accepted.**
Sarvam Voice Agents picks the model. The stack table row is corrected: it now
applies only to the browser-fallback path, where we call the API ourselves.

**Confirmed from Track A:** every tool's spoken reply is just `{{say}}`. So
wording changes on the backend need nothing from Rahul, as long as `say` is
always present — including when `ok` is `false`. That is already the rule, and
it is tested.

---

## Conventions — read these first, they matter more than the endpoints

**1. Every response carries a `say` field.**
`say` is the exact sentence the agent should speak. The backend owns every
spoken fact — dates, amounts, reference numbers. The model is instructed never
to state a date or an amount that did not come from a `say`. This is what stops
the agent inventing "your refund will arrive in 3 days".

**2. `say` is written in English.** Saaras transcribes-and-translates the
merchant into English, the agent reasons in English, and the agent is instructed
to speak its reply in the merchant's detected language. So we write plain,
short, translatable English: no idioms, no nested clauses.

**3. Every tool returns HTTP 200. Always.**
Even "merchant not found", even "database is down". A 4xx or 5xx leaves the
agent with nothing to say and dead air on a live call. Failures come back as
`{"ok": false, "say": "...", "reason": "..."}` where `say` is something useful
to speak, e.g. asking for the registered mobile number.

**4. Flat, scalar JSON values only.**
Sarvam's response template can interpolate `{{key}}` but cannot walk into
nested objects or arrays. Lists are pre-joined into a readable string
(`missing_documents_text`) *and* also provided as an array for the dashboard.

**5. Money is paise-safe.** Amounts are JSON numbers with 2 decimals, plus a
pre-formatted `*_text` field (`"₹1,000.00"`) for speaking.

**6. Idempotency is scoped to the CASE, not the call.**
`idempotency_key` must be `"<case_ref>:<action>"`, e.g. `"SMD-1042:closure"` —
**never** the interaction id. A merchant whose call drops after we booked the
pickup will call back; that is a new interaction id, so a call-scoped key would
sail straight past the check and book a second pickup.

Three layers, because this is the most expensive thing to get wrong:
- the `idempotency_key`,
- **structural** uniqueness in the database (one scheduled pickup per case, one
  pending refund per case, one credit note per case) — so it holds even if the
  agent invents a key,
- natural idempotency: if `billing_stopped_from` is already set, the closure
  tool returns the original result instead of acting again.

A replayed write returns the *first* response, including the original `say`, so
the merchant hears the same dates they heard the first time.

**7. Budget: answer in under 2 seconds.** Sarvam permits up to 30 s, but a call
feels dead past about two. Measured: local+tunnel ≈ 50 ms, FastAPI Cloud (us-east-1)
≈ 310 ms per call from India.

**8. Auth.** Header `X-Samadhan-Key: <shared secret>` on every call. Configure it
in the Sarvam tool's Headers section as a masked secret.

---

## Call context Sarvam can send

These are available in the Sarvam tool config via `@`:

| Variable | Put it in our field |
|---|---|
| User Identifier (caller phone) | `phone` |
| Interaction ID (unique call id) | `interaction_id` |
| Call Transcript (so far) | `transcript` |
| Call Length | `call_length_s` |

Send `interaction_id` on **every** call — it is how we tie all tool calls to one
case. Send `phone` on every call too; it is how we find the merchant.

---

## A case outlives a call — read this before the endpoints

A **case** is the merchant's problem. A **call session** is one phone call. One
case can span a dropped call plus two callbacks. The database models it that way
(`cases` 1→N `call_sessions`), and slide 6's *"repeat calls per case"* metric is
literally `count(call_sessions) per case`.

**Resume policy.** On a new call we look for the merchant's most recent case in
state `open`, `acting` or `awaiting_approval`, updated within **7 days**. If one
exists, we resume it — same `case_ref`, same reference numbers, actions already
taken are *not* repeated. Otherwise we open a new case.

This is the difference between the pitch and an IVR. A merchant who gets cut off
mid-call and rings back must not be asked to explain the problem again.

---

## 0a. `call_started` — Sarvam `on_start` lifecycle hook

Register as a tool with lifecycle **`on_start`**, so it runs before the agent
speaks and costs nothing in conversation time. It opens or resumes the case and
records the call session.

`POST /tools/call-started`

```json
{
  "phone": "+919000000001",
  "interaction_id": "call_def456",
  "language_code": "te-IN"
}
```

```json
{
  "ok": true,
  "case_ref": "SMD-1042",
  "call_sequence_no": 2,
  "resumed": true,
  "state": "acting"
}
```

Nothing is spoken from this hook, so there is no `say`. Its value is that the
case exists before the first real tool call, and `get_merchant_context` is then
a pure read.

## 0b. `call_ended` — Sarvam `on_end` lifecycle hook

Register with lifecycle **`on_end`**. This is the repair mechanism for a
disconnect, and the most valuable endpoint in the whole contract.

`POST /tools/call-ended`

```json
{
  "interaction_id": "call_def456",
  "end_reason": "disconnected",
  "duration_s": 48
}
```

It closes the call session and then **checks whether the case has write actions
with no proof sent**. If so — the call dropped after we stopped billing but
before the merchant got anything in writing — it sends the confirmation anyway
and records `ended_mid_action: true`.

```json
{
  "ok": true,
  "case_ref": "SMD-1042",
  "ended_mid_action": true,
  "proof_sent": true,
  "proof_ref": "PR-9043"
}
```

So the promise on slide 3 — *"Prove: sends a written confirmation with dates"* —
survives the merchant's network dropping. The action was real, so the proof goes
out regardless of whether the conversation finished.

---

## 1. `get_merchant_context`

The first call of every conversation. Deliberately **fat**: it returns billing,
device, plan and hold status in one round trip, so the agent does not chain four
lookups and spend four network hops.

`POST /tools/merchant-context`

```json
{
  "phone": "+919000000001",
  "interaction_id": "call_abc123",
  "transcript": "My shop has closed. Please take the Soundbox back."
}
```

```json
{
  "ok": true,
  "found": true,
  "case_ref": "SMD-1042",
  "merchant_id": "8f1c...",
  "merchant_name": "Lakshmi Provision Store",
  "owner_name": "Lakshmi Devi",
  "city": "Hyderabad",
  "language_code": "te-IN",
  "shop_status": "closed",
  "shop_closed_on": "2026-03-12",
  "device_type": "Soundbox",
  "device_serial": "SB-77301",
  "device_status": "active",
  "device_last_seen_days": 243,
  "billed_plan": "Soundbox Rental Standard",
  "billed_monthly_amount": 125.00,
  "billed_monthly_amount_text": "₹125.00",
  "promised_plan": null,
  "promised_monthly_amount": null,
  "plan_mismatch": false,
  "months_charged_after_closure": 8,
  "amount_charged_after_closure": 1000.00,
  "amount_charged_after_closure_text": "₹1,000.00",
  "settlement_on_hold": false,
  "settlement_amount_on_hold": 0,
  "returning_caller": false,
  "call_sequence_no": 1,
  "previous_calls": 0,
  "last_call_ago_text": null,
  "case_state": "open",
  "actions_already_taken_text": null,
  "pending_approval": false,
  "say": "I can see your shop Lakshmi Provision Store in Hyderabad. Your Soundbox is still active and you have been charged 125 rupees a month, 1000 rupees in total, since your shop closed in March."
}
```

Not found:

```json
{
  "ok": true,
  "found": false,
  "reason": "no merchant for caller phone",
  "say": "I could not find an account for the number you are calling from. Please tell me the mobile number registered with your Paytm for Business account."
}
```

**Returning caller — the case that matters.** Same endpoint, but the merchant
has called before and we resumed their case. Note `actions_already_taken_text`
and the `say`: the agent picks up where the last call stopped instead of asking
the merchant to start again.

```json
{
  "ok": true,
  "found": true,
  "case_ref": "SMD-1042",
  "merchant_name": "Lakshmi Provision Store",
  "returning_caller": true,
  "call_sequence_no": 2,
  "previous_calls": 1,
  "last_call_ago_text": "about twenty minutes ago",
  "last_call_end_reason": "disconnected",
  "case_state": "acting",
  "issue_summary": "Shop closed, wants Soundbox taken back and billing stopped",
  "actions_already_taken_text": "billing stopped from today, credit note of one thousand rupees raised, pickup booked for the nineteenth of November",
  "proof_sent": true,
  "pending_approval": false,
  "remaining_steps_text": null,
  "say": "Namaste, I can see we spoke about twenty minutes ago and the call dropped. You do not need to explain again. I had already stopped the billing from today, raised a credit note of one thousand rupees, and booked the Soundbox pickup for the nineteenth of November. The confirmation message has gone to your mobile. Is there anything else about this?"
}
```

With a refund still waiting on a human, the tail changes — and crucially the
agent must **not** raise a second request:

```json
{
  "returning_caller": true,
  "case_state": "awaiting_approval",
  "pending_approval": true,
  "pending_refund_ref": "RF-2207",
  "pending_refund_amount_text": "₹868.00",
  "say": "I can see we spoke yesterday about the wrong monthly charge. The refund request for eight hundred and sixty eight rupees, reference RF-2207, is with a colleague for approval. It has not been forgotten, and you will get a message as soon as it is decided."
}
```

**Lookup by a spoken number** — same endpoint, pass `registered_phone` instead
of relying on caller id:

```json
{ "registered_phone": "9000000001", "interaction_id": "call_abc123" }
```

We normalise: strip spaces, accept 10-digit, `0`-prefixed and `+91` forms.

---

## 2. `get_billing_summary`

`POST /tools/billing`

```json
{ "merchant_id": "8f1c...", "interaction_id": "call_abc123" }
```

```json
{
  "ok": true,
  "billed_plan": "Soundbox Rental Standard",
  "monthly_amount": 125.00,
  "monthly_amount_text": "₹125.00",
  "months_charged": 16,
  "total_charged": 2000.00,
  "total_charged_text": "₹2,000.00",
  "first_charge_on": "2025-07-01",
  "last_charge_on": "2026-11-01",
  "dues_outstanding": 0,
  "say": "You are on the Soundbox Rental Standard plan at 125 rupees a month. You have been charged 16 times, 2000 rupees in total, with the last charge on the first of November."
}
```

---

## 3. `check_promised_plan`

The "promise check" from slide 5 — the USP. Compares what sales promised against
what is actually billed.

`POST /tools/promise-check`

```json
{ "merchant_id": "8f1c...", "interaction_id": "call_abc123" }
```

```json
{
  "ok": true,
  "mismatch": true,
  "promised_plan": "Soundbox Promo ₹1",
  "promised_monthly_amount": 1.00,
  "promised_monthly_amount_text": "₹1.00",
  "promised_by": "field sales, Hyderabad South",
  "promised_on": "2026-04-02",
  "billed_plan": "Soundbox Rental Standard",
  "billed_monthly_amount": 125.00,
  "billed_monthly_amount_text": "₹125.00",
  "months_affected": 7,
  "overcharge_amount": 868.00,
  "overcharge_amount_text": "₹868.00",
  "say": "You were promised 1 rupee a month when you signed up in April, but you have been billed 125 rupees a month for 7 months. You have been overcharged by 868 rupees. I cannot release money myself, so I will raise a refund request for a colleague to approve."
}
```

No mismatch → `"mismatch": false` and a `say` that explains the bill is correct.

**Rule for Track A:** when `mismatch` is true, the agent must call
`raise_refund_request` next. It must never say the words "refund approved".

---

## 4. `stop_billing_and_pickup`

The closure action. Writes three things: stops billing, raises a credit note for
the period since the request, books a pickup.

`POST /tools/closure`

```json
{
  "merchant_id": "8f1c...",
  "interaction_id": "call_abc123",
  "request_date": "2026-11-14",
  "reason": "shop permanently closed",
  "idempotency_key": "SMD-1042:closure"
}
```

```json
{
  "ok": true,
  "ref": "SMD-1042",
  "billing_stopped_from": "2026-11-14",
  "device_status": "pickup_scheduled",
  "credit_note_ref": "CN-5521",
  "credit_note_amount": 1000.00,
  "credit_note_amount_text": "₹1,000.00",
  "credit_note_period": "12 March 2026 to 14 November 2026",
  "pickup_ref": "PU-8841",
  "pickup_date": "2026-11-19",
  "pickup_address": "Shop 14, Moosapet Main Road, Hyderabad 500018",
  "say": "I have stopped the billing from today. A credit note of 1000 rupees has been raised for the period since your shop closed in March. Pickup of the Soundbox is booked for the nineteenth of November, and I will send you a written confirmation with these details."
}
```

**Note on honesty:** we do *not* pretend to retroactively un-bill. Billing stops
from the request date, and the already-charged period is handled as a **credit
note**, which is how it actually works in payments. A judge who knows the domain
will ask.

---

## 5. `get_settlement_hold`

Read-only. Explains a hold in plain language.

`POST /tools/settlement-hold`

```json
{ "merchant_id": "8f1c...", "interaction_id": "call_abc123" }
```

```json
{
  "ok": true,
  "on_hold": true,
  "amount_on_hold": 14200.00,
  "amount_on_hold_text": "₹14,200.00",
  "held_since": "2026-10-29",
  "reason_plain": "The name on your PAN does not match the name on your GST registration, so the account could not be verified.",
  "missing_documents": ["PAN card photo", "GST certificate"],
  "missing_documents_text": "a photo of your PAN card and your GST certificate",
  "expected_release_date": "2026-11-21",
  "say": "Your settlement of 14,200 rupees is on hold because the name on your PAN does not match the name on your GST registration. Please upload a photo of your PAN card and your GST certificate. Once both are received, the money is released within three working days, which would be the twenty-first of November."
}
```

---

## 6. `device_troubleshoot`

Stateful across the call: pass `step` back so we know what has been tried.

`POST /tools/device`

```json
{
  "merchant_id": "8f1c...",
  "interaction_id": "call_abc123",
  "symptom": "no_sound",
  "step": 0,
  "idempotency_key": "SMD-1042:device:0"
}
```

`symptom` is one of `no_sound`, `not_powering_on`, `no_network`,
`not_announcing_payments`, `unknown`.

Still troubleshooting:

```json
{
  "ok": true,
  "resolved": false,
  "next_step": 1,
  "technician_booked": false,
  "say": "Let us try one thing. Press and hold the power button for ten seconds until you hear a beep, then tell me what you hear."
}
```

Out of steps → book a technician:

```json
{
  "ok": true,
  "resolved": false,
  "next_step": null,
  "technician_booked": true,
  "ticket_ref": "TK-3302",
  "technician_date": "2026-11-17",
  "device_status": "faulty",
  "say": "The Soundbox is not responding, so I have booked a technician to visit on the seventeenth of November. You will get a confirmation message with the reference number."
}
```

---

## 7. `raise_refund_request`

**Never pays. Only queues for a human.** This is the safety story from slide 5.

`POST /tools/refund-request`

```json
{
  "merchant_id": "8f1c...",
  "interaction_id": "call_abc123",
  "amount": 868.00,
  "reason": "promised ₹1/month promo, billed ₹125/month for 7 months",
  "idempotency_key": "SMD-1042:refund"
}
```

```json
{
  "ok": true,
  "request_ref": "RF-2207",
  "amount": 868.00,
  "amount_text": "₹868.00",
  "status": "awaiting_approval",
  "expected_decision_by": "2026-11-15",
  "say": "I have raised a refund request for 868 rupees, reference RF-2207. A colleague has to approve any money that goes out, so this will be reviewed by tomorrow and you will get a message with the decision."
}
```

---

## 8. `handover_to_human`

Call this, then trigger Sarvam's **call transfer**. Stores the transcript and
produces the summary the human sees.

`POST /tools/handover`

```json
{
  "merchant_id": "8f1c...",
  "interaction_id": "call_abc123",
  "reason": "merchant asking for immediate cash refund",
  "transcript": "full transcript so far",
  "idempotency_key": "SMD-1042:handover"
}
```

```json
{
  "ok": true,
  "summary_ref": "HO-1180",
  "case_ref": "SMD-1042",
  "say": "I am connecting you to a colleague now. I have passed on everything we discussed, so you will not have to explain it again."
}
```

---

## 9. `send_confirmation` — the "Prove" step

`POST /tools/confirmation`

```json
{
  "merchant_id": "8f1c...",
  "interaction_id": "call_abc123",
  "idempotency_key": "SMD-1042:proof"
}
```

```json
{
  "ok": true,
  "proof_ref": "PR-9043",
  "channel": "whatsapp",
  "sent_to": "+919000000001",
  "say": "I have sent a written confirmation to your registered mobile number with the dates and the reference numbers."
}
```

Builds the confirmation from everything recorded on the case, so it cannot
disagree with what was actually done. In the demo it renders to the dashboard and
records a `proof_sent` event rather than sending a real WhatsApp message.

---

## Admin endpoints (not tools — for us)

| Endpoint | Purpose |
|---|---|
| `GET /health` | liveness |
| `POST /admin/reset` | re-run the seed, clean slate in under 2 s |
| `POST /admin/bind-phone` | **demo lifesaver:** map the number you are actually calling from onto a seeded persona. `{"phone": "+9199...", "merchant_code": "M1"}` |
| `GET /admin/cases` | plain JSON case list, for debugging without the dashboard |

`POST /admin/bind-phone` exists because on demo day Rahul calls from his own
phone, which is not in the seed. Bind it in one call, ten seconds before the
demo, and `get_merchant_context` finds the right persona.

---

## The four demo personas

| Code | Merchant | Scenario | Key numbers |
|---|---|---|---|
| **M1** | Lakshmi Provision Store, Hyderabad (te-IN) | **Closure** | shop closed 8 months ago, Soundbox still active, ₹125 × 8 = **₹1,000** charged after closure |
| **M2** | Imran Mobile Repairs, Hyderabad (hi-IN) | **Promise mismatch** | promised ₹1/mo, billed ₹125/mo for 7 months → **₹868** overcharge → refund request |
| **M3** | Anjali Fashions, Hyderabad (te-IN) | **Settlement hold** | **₹14,200** held, PAN/GST name mismatch, 2 missing docs |
| **M4** | Ravi Tea Stall, Hyderabad (te-IN) | **Device fault** | Soundbox silent, last heartbeat 11 days ago → technician |

Seeded phone numbers are `+919000000001` … `+919000000004`. All dates are seeded
**relative to the current date**, so the numbers stay true whichever day we run.

---

## Rules Track A must encode in the prompts

1. Never state a date, an amount or a reference number that did not come from a `say`.
2. Never say a refund is approved, paid or done. Only "raised for approval".
3. Call `get_merchant_context` first, always.
4. On `plan_mismatch: true`, call `raise_refund_request` before closing.
5. After any write action, call `send_confirmation` before ending the call.
6. Anything about cash in hand, legal threats, abuse, or a request we have no
   tool for → `handover_to_human`, then call transfer.
7. If a tool returns `ok: false`, speak its `say` and do not retry more than once.

### Callback rules — the ones that make or break a second call

8. Register `call_started` with lifecycle **`on_start`** and `call_ended` with
   lifecycle **`on_end`**. Neither is LLM-callable; the platform runs them.
9. **On `returning_caller: true`, never ask the merchant to re-explain.** Speak
   the `say`, which already names what was done, and ask only what is still
   open. "Can you tell me the problem again?" on a callback is the single worst
   thing this agent can say — it is the behaviour the pitch exists to replace.
10. **On `pending_approval: true`, do not call `raise_refund_request` again.**
    Report the existing reference and its status. The database will refuse a
    duplicate anyway, but the agent should not try.
11. Never re-run a completed action because the merchant asks again. If
    `actions_already_taken_text` covers it, say it is already done, with the
    dates, and offer the reference number.
12. Pass `idempotency_key` as `"<case_ref>:<action>"`, taking `case_ref` from
    `get_merchant_context` or `call_started`. Never the interaction id.

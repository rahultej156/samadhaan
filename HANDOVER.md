# Track A handover — wiring the Sarvam agent to the backend

**For Rahul.** Everything below is live and tested. Copy the values into the
Sarvam Voice Agents tool config and the agent can act for real.

Last verified: 14 Nov 2026, all four scenarios passing, 42 tool calls,
median 324 ms.

---

## 1. The two things you need

**Base URL**

```
https://holders-merry-enb-jessica.trycloudflare.com
```

**Auth header, on every tool**

```
X-Samadhan-Key: <Syed will send you this directly>
```

Set it as a **masked secret** in each tool's Headers section. It is not in this
repo on purpose. There is a second key for operator endpoints — you do not need
it; it is the dashboard's.

> **The base URL is a Cloudflare quick tunnel. It changes if the tunnel
> restarts.** If every tool suddenly 502s, that is what happened — ping Syed for
> the new URL. Nothing else about the config changes.

Check it is alive before you debug anything else:

```bash
curl -X POST https://holders-merry-enb-jessica.trycloudflare.com/tools/echo \
  -H "Content-Type: application/json" -H "X-Samadhan-Key: <key>" \
  -d '{"ping":"hello"}'
```

You should get back `{"ok":true,"say":"This is the Samadhan backend..."}`.

---

## 2. Every tool's response template is the same

```
{{say}}
```

That is the whole template, for all eleven. The backend composes the sentence;
the agent speaks it, translated into the merchant's language.

`say` is always present — on success, on failure, on "I cannot find your
account". So the agent always has something to speak and never sits silent.

**Every tool returns HTTP 200**, including errors. If you see a non-200 from a
`/tools/` path, it is a bug on my side, not a case to handle in the prompt.

---

## 3. The tools

`@User Identifier`, `@Interaction ID`, `@Call Transcript` and `@Call Length` are
the Sarvam call-context variables. **Send `interaction_id` on every single
call** — it is how all the tool calls get tied to one case, and how a callback
resumes instead of restarting.

### Lifecycle hooks — register these two first

| Tool name | Lifecycle | Method | Path |
|---|---|---|---|
| `call_started` | **on_start** | POST | `/tools/call-started` |
| `call_ended` | **on_end** | POST | `/tools/call-ended` |

```jsonc
// call_started  — body
{ "phone": "@User Identifier",
  "interaction_id": "@Interaction ID",
  "language_code": "te-IN" }

// call_ended  — body
{ "interaction_id": "@Interaction ID",
  "end_reason": "completed",      // or "disconnected" / "transferred"
  "duration_s": "@Call Length" }
```

**These are not optional.** `call_started` is what makes the caller's number
trustworthy: the backend only treats a number as caller id when this hook
recorded it, because the hook runs without the LLM. Without it, every merchant
gets asked to read their Soundbox serial before any change.

`call_ended` is the repair path. If a call drops after we stopped billing but
before the merchant was told in writing, this hook sends the confirmation
anyway. Neither hook speaks, so neither needs a response template.

### The nine callable tools

| Tool name | Method | Path | When |
|---|---|---|---|
| `get_merchant_context` | POST | `/tools/merchant-context` | **always first** |
| `get_billing_summary` | POST | `/tools/billing` | "what am I being charged" |
| `check_promised_plan` | POST | `/tools/promise-check` | wrong amount billed |
| `stop_billing_and_pickup` | POST | `/tools/closure` | shop closed, take the box back |
| `get_settlement_hold` | POST | `/tools/settlement-hold` | "my money is on hold" |
| `device_troubleshoot` | POST | `/tools/device` | Soundbox not working |
| `raise_refund_request` | POST | `/tools/refund-request` | after a promise mismatch |
| `handover_to_human` | POST | `/tools/handover` | anything out of scope |
| `send_confirmation` | POST | `/tools/confirmation` | after any action |

Bodies — most take the same two fields:

```jsonc
// get_merchant_context
{ "phone": "@User Identifier",
  "interaction_id": "@Interaction ID",
  "transcript": "@Call Transcript" }

// get_billing_summary / check_promised_plan / get_settlement_hold
// send_confirmation / stop_billing_and_pickup / raise_refund_request
{ "phone": "@User Identifier",
  "interaction_id": "@Interaction ID" }

// device_troubleshoot  — add the symptom
{ "phone": "@User Identifier",
  "interaction_id": "@Interaction ID",
  "symptom": "no_sound" }
// symptom ∈ no_sound | not_powering_on | no_network |
//           not_announcing_payments | unknown

// handover_to_human
{ "phone": "@User Identifier",
  "interaction_id": "@Interaction ID",
  "reason": "merchant asked for a person",
  "transcript": "@Call Transcript" }
```

**Fields you no longer need to send.** `request_date`, `idempotency_key` and
`step` are accepted and **ignored** — the backend owns all three now. Keep
sending them if your config already does; nothing breaks.

---

## 4. Rules for the prompts

1. **Never state a date, amount or reference number that did not come from a
   `say`.** The backend computes every one of them.
2. **Never say a refund is approved, paid or done.** Only "raised for approval".
   A human approves every refund — that is the project's core claim.
3. **Call `get_merchant_context` first, always.**
4. On `plan_mismatch: true` → call `raise_refund_request` before closing.
5. After any write action → call `send_confirmation`.
6. On `returning_caller: true` → **never ask the merchant to re-explain.** Speak
   the `say`; it already names what was done. "Can you tell me the problem
   again?" on a callback is the exact behaviour this project exists to replace.
7. On `pending_approval: true` → do **not** raise a second refund. Report the
   existing reference.
8. On `tts_supported: false` → hand over immediately. `bulbul:v4-flash` cannot
   speak Malayalam or Odia, so transfer before the agent opens its mouth.
9. On `ok: false` → speak the `say`, retry at most once.
10. Out of scope → `handover_to_human` then call transfer. Undoing a closure,
    rescheduling a pickup, changing an address, several shops on one number.

### Fields worth branching on

| Field | Meaning |
|---|---|
| `found` | false → ask for the registered mobile number |
| `verified` | false → the caller is not calling from the registered number; the backend will ask them to read the Soundbox serial |
| `returning_caller` | true → they have called about this before |
| `actions_already_taken_text` | what was already done, in speakable form |
| `plan_mismatch` | true → they were overcharged against the promised plan |
| `settlement_on_hold` | true → money held, documents needed |
| `pending_approval` | true → a refund is already waiting on a human |
| `tts_supported` | false → hand over, we cannot speak their language |
| `handover_required` | true → verification exhausted, transfer now |

---

## 5. The four demo merchants

| Phone | Soundbox serial | Merchant | Scenario | What the agent should end up doing |
|---|---|---|---|---|
| `+919000000001` | `SB-77301` | Lakshmi Provision Store (te-IN) | shop closed 8 months ago, still charged ₹125/mo, ₹1,000 total | stop billing, credit note, book pickup, send proof |
| `+919000000002` | `SB-81144` | Imran Mobile Repairs (hi-IN) | promised ₹1/mo, billed ₹125 for 7 months | promise check → ₹868 refund **raised for approval** |
| `+919000000003` | `SB-64207` | Anjali Fashions (te-IN) | ₹14,200 settlement on hold, PAN/GST mismatch | explain plainly, list 2 documents, give a date and upload link |
| `+919000000004` | `SB-50982` | Ravi Tea Stall (te-IN) | Soundbox silent 11 days | two troubleshooting steps, then book a technician |

**The serial column is for testing in the browser.** There is no caller id in the
browser widget, so the agent will ask you to read the serial off the Soundbox —
that is the possession check doing its job, not a bug. Read out the serial for
the merchant you are pretending to be and the call proceeds normally. Over a
real phone call the serial is never asked, because caller id already matched.

### Calling from your own phone

Your real number is not in the seed data, so bind it once:

```bash
curl -X POST https://holders-merry-enb-jessica.trycloudflare.com/admin/bind-phone \
  -H "Content-Type: application/json" -H "X-Samadhan-Key: <OPERATOR key, ask Syed>" \
  -d '{"phone":"+91XXXXXXXXXX","merchant_code":"M1"}'
```

Now a real call from that handset is treated as Lakshmi Provision Store, caller
id and all. Change `M1` to pick a different scenario. **Do this before the live
demo** — it takes ten seconds and without it the agent will ask you to read a
serial number off a Soundbox you do not have.

---

## 6. What a good call sounds like

M1, calling from the bound number:

> **Agent:** I can see your shop Lakshmi Provision Store in Hyderabad. Your
> Soundbox is still active and you have been charged one hundred and twenty five
> rupees a month, one thousand rupees in total, since your shop closed in March.
>
> **Merchant:** Yes, please stop it and take the box.
>
> **Agent:** I have stopped the billing from today. A credit note of one thousand
> rupees has been raised for the period since your shop closed in March. Pickup
> of the Soundbox is booked for the nineteenth of November, and I will send you a
> written confirmation with these details.

Then hang up mid-sentence and call back:

> **Agent:** I can see we spoke about five minutes ago and the call dropped. You
> do not need to explain again. I had already stopped the billing from the
> fourteenth of November, raised a credit note of one thousand rupees, booked the
> Soundbox pickup for the nineteenth of November and sent you a written
> confirmation. Is there anything else about this?

That second one is the demo. It needs `call_started` and `call_ended` registered
to work.

---

## 7. When something goes wrong

| What you see | What it means |
|---|---|
| 502 / connection refused on every tool | the tunnel or the backend is down — ping Syed |
| `ok: false`, "trouble reaching your account securely" | wrong or missing `X-Samadhan-Key` |
| `ok: false`, "could not find an account" | the caller's number is not seeded or bound — use `/admin/bind-phone` |
| Agent asked to read a Soundbox serial | No trusted caller id. Either you are testing in the **browser widget** (where `@User Identifier` is your Sarvam account email, not a phone number — expected, just read out the serial from the table above), or on a real call `call_started` is not registered as **on_start**. Run `check_integration.py` and it will tell you which |
| "I could not find an account for the number you are calling from" on every call | Same cause. In the browser there is no caller id to find an account for, so the agent correctly falls back to asking for the registered number |
| "I am having trouble reading your account" | a real backend error — tell Syed, the traceback is in the log |
| Tool call is slow | see the latency note below. Set the tool's Max wait to **10 s**, not 30 — long enough to absorb a spike, short enough that the agent can recover and say something |
| Same pickup booked twice | should be impossible — the database refuses it. Tell Syed if you see it |

## 8. Known constraints, so the pitch stays honest

- **Speech in: 23 languages** (22 Indian + English) via `saaras:v4`.
- **Speech out: 9 languages** via `bulbul:v4-flash` — no Malayalam, no Odia.
  Bulbul v3 reached end of life on Voice Agents on 10 Nov 2026. The deck says
  "replies by voice in 11"; say **"understands 23, speaks 9 today"** on stage.
- **Latency, measured honestly.** The backend itself is fast; the network is
  not. Same no-op endpoint, same moment:

  | Path | `/tools/echo` |
  |---|---|
  | localhost, no tunnel | **1.5 ms** |
  | through the Cloudflare tunnel | **880–1140 ms** |

  So about **0.9 s of that is the internet path**, before the backend does
  anything. Real tool calls measured through the tunnel: `merchant-context`
  0.22 s to 3.2 s, `billing` 0.37 s. Locally the same suite runs at a 324 ms
  median.

  Two consequences: set Max wait to 10 s, and expect the occasional pause
  mid-call. It is not a bug on either side — it is the wifi plus Supabase's
  free-tier pooler. A phone hotspot is worth trying if the venue network is
  poor.
- Identity checking is caller id plus a possession check (the Soundbox serial),
  with a three-attempt limit and an audit trail. It is **not** an OTP. If a judge
  asks, that is the honest answer — production would use one.

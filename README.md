# Samadhaan

**An AI teammate that fully resolves merchant problems by voice, in 22 Indian
languages and English.**

Paytm Build for India — AI Hackathon · Track 3, Autonomous AI Teammates ·
Hyderabad, 14 November 2026

---

## The problem

Merchant support closes tickets, but not problems. From 420 "most relevant"
Google Play reviews of the Paytm for Business app, read 6 November 2026: about
**45% of 321 negative 2026 reviews blame support that did not solve the issue**,
and around **75 of them cannot stop or return the Soundbox while rent keeps
being deducted**.

The case the project is built around is real: the shop closed months ago, the
merchant asked again and again to deactivate the Soundbox, and the rent is still
being taken.

## What Samadhaan does

One call that *fixes* the problem, in five steps:

| | Step | What it means here |
|---|---|---|
| 01 | **Listen** | Voice call in 22 Indian languages + English |
| 02 | **Check** | Reads billing, device, plan and settlement state |
| 03 | **Act** | Stops billing, books a pickup or a technician |
| 04 | **Prove** | Sends a written confirmation with dates and references |
| 05 | **Hand over** | Money and edge cases go to a human, with a summary |

It is judged by one thing: **was the problem solved on the first call?**

Two guarantees are structural, not promised:

- **The agent cannot invent a fact.** Every tool response carries a `say` field
  — the exact sentence to speak — so dates, amounts and reference numbers come
  from the database, never from the model.
- **No money moves without a human.** Refunds are only ever *raised for
  approval*. A partial unique index makes a second pending refund per case
  impossible, whatever the agent asks for.

---

## Architecture

```
  Merchant (phone)
        |
        v
  Sarvam Voice Agents ──── Saaras v4 (speech in, 23 languages)
  (telephony + LLM loop)   sarvam-105b (tool calling)
        |                  Bulbul v4-flash (speech out)
        |  HTTPS tool calls, each returning a `say`
        v
  FastAPI backend ───────> Supabase Postgres (ap-southeast-1)
  (tools, case engine,       cases 1->N call_sessions
   audit log, idempotency)   case_events = append-only audit log
        |
        v
  Next.js dashboard  (server-side reads, service-role key)
  live cases, action timeline, proof, approve/reject
```

A **case** is the merchant's problem. A **call session** is one phone call. One
case can span a dropped call plus two callbacks — which is what makes "repeat
calls per case" measurable, and what lets a callback resume instead of restart.

---

## Repo layout

```
contracts.md       THE FROZEN SEAM. Read this first, whichever track you are on.
                   9 tools + 2 Sarvam lifecycle hooks, exact request/response
                   JSON, division of work, stack decisions, integration gates.

db/schema.sql      16 tables. RLS on with no policies: the anon key reads
                   nothing. Partial unique indexes prevent double-booking.
db/seed.sql        4 demo personas, dates relative to current_date.
                   Doubles as the reset script between demo takes.

backend/           FastAPI: the tools, case engine, approval queue, proof.   (wip)
dashboard/         Next.js operations dashboard.                            (wip)
scripts/           run_scenario.py — drives all 4 scenarios by HTTP,
                   no voice, no LLM.                                        (wip)

.mcp.json          Sarvam docs + Voice Agents MCP servers.
*.pptx, *.jpeg     Pitch deck and reference screenshot.
```

## The four demo scenarios

| Code | Merchant | Scenario | Key numbers |
|---|---|---|---|
| **M1** | Lakshmi Provision Store (te-IN) | **Closure** | shop closed 8 months ago, Soundbox still active, ₹125 × 8 = **₹1,000** charged after closure |
| **M2** | Imran Mobile Repairs (hi-IN) | **Promise mismatch** | promised ₹1/mo, billed ₹125/mo for 7 months → **₹868** overcharge → refund request |
| **M3** | Anjali Fashions (te-IN) | **Settlement hold** | **₹14,200** held, PAN/GST name mismatch, 2 documents missing |
| **M4** | Ravi Tea Stall (te-IN) | **Device fault** | Soundbox silent 11 days → troubleshoot, then technician |

Seeded on `+919000000001` … `+919000000004`. `POST /admin/bind-phone` points a
real calling number at a persona, which is how the live demo works.

---

## Getting set up

### Database (either track)

Create a Supabase project, then in the SQL editor run:

1. `db/schema.sql`
2. `db/seed.sql`

The seed ends with a sanity SELECT. It should print M1 with 16 invoices, ₹2,000
total and ₹1,000 charged after closure, and M2 with a ₹868 overcharge. If those
numbers match, the data is right.

Then confirm nothing is publicly readable — **both queries must return zero rows:**

```sql
select tablename, policyname from pg_policies where schemaname = 'public';

select table_name, privilege_type
  from information_schema.role_table_grants
 where grantee in ('anon', 'authenticated') and table_schema = 'public';
```

### Backend — Track B

```bash
python -m venv .venv && .venv/Scripts/activate      # Windows: use `py -m venv`
pip install -r backend/requirements.txt
cp backend/.env.example backend/.env                # then fill it in
fastapi dev backend/main.py
```

`backend/.env` holds `DATABASE_URL`, `SUPABASE_URL`,
`SUPABASE_SERVICE_ROLE_KEY` and `SAMADHAN_API_KEY`. It is gitignored and the
service-role key must never reach a client bundle.

Expose it for Sarvam to call:

```bash
ngrok http 8000 --domain <your-static-domain>
```

A static domain matters — a URL that changes on restart means reconfiguring the
Sarvam tools every time.

### Voice agent — Track A

See the Track A table in `contracts.md`. In short: Sarvam key and a connected
number, build the agent against **mocked** tools first, then swap in the tunnel
URL. Register `call_started` as `on_start` and `call_ended` as `on_end`.

### Windows notes

- `python` may resolve to the dead Microsoft Store alias — use `py`.
- The FastAPI CLI prints emoji and dies on a cp1252 console with
  `UnicodeEncodeError`. Set `PYTHONUTF8=1` before any `fastapi` command.
- If `npm` is blocked by NVM ("delegated script identity changed"), run
  `nvm reshim`.

---

## Stack decisions

| Layer | Choice | Note |
|---|---|---|
| LLM | `sarvam-105b` | `sarvam-m` is deprecated. 105b has confirmed OpenAI-style tool calling |
| Speech in | `saaras:v4` | 23 languages = 22 Indian + English |
| Speech out | `bulbul:v4-flash` | **9 languages, not 11** — no Malayalam or Odia. Bulbul v3 hit end-of-life on Voice Agents on 10 Nov 2026 |
| Backend | FastAPI, local + ngrok | ~50 ms per tool call, instant hot reload |
| Backend fallback | FastAPI Cloud | measured us-east-1, ~310 ms/call from India, no cold start over a 16-min idle. One URL change to switch |
| Database | Supabase, ap-southeast-1 | ~40 ms more than Mumbai; immaterial next to 1–2 s of ASR + LLM + TTS |
| Dashboard reads | Next.js server-side, service-role key | no browser-side key, so no client Realtime; revalidates every 3 s |

A tool call must answer in **under 2 seconds**. Sarvam allows 30, but a call
feels dead past two.

## What is measured

Solved on first call · days to stop billing · repeat calls per case ·
escalations · one-star review share.

---

## Scope, stated honestly

Demo data is sample merchant data. With Paytm's own APIs, only the **Actions**
layer changes — the case engine, audit log, approval queue and proof flow stay
as they are.

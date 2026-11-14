-- Samadhan — schema
-- Target: Supabase Postgres 15+ (ap-south-1 / Mumbai)
-- Paste into the Supabase SQL editor and run. Idempotent: safe to re-run.
--
-- Design rules:
--   * case_events is append-only and is the audit log. Every tool call writes one.
--   * Money is numeric(12,2). Never float.
--   * Dashboard reads these tables directly with the anon key (read-only RLS).
--     All writes go through FastAPI with the service-role key, which bypasses RLS.

-- ---------------------------------------------------------------- reset
drop view if exists case_feed cascade;

drop table if exists proofs cascade;
drop table if exists handovers cascade;
drop table if exists refund_requests cascade;
drop table if exists credit_notes cascade;
drop table if exists service_tickets cascade;
drop table if exists conversation_turns cascade;
drop table if exists case_events cascade;
drop table if exists call_sessions cascade;
drop table if exists cases cascade;
drop table if exists settlements cascade;
drop table if exists invoices cascade;
drop table if exists plans cascade;
drop table if exists devices cascade;
drop table if exists merchants cascade;
drop table if exists tool_idempotency cascade;
drop table if exists phone_bindings cascade;

drop sequence if exists case_ref_seq;
drop sequence if exists refund_ref_seq;
drop sequence if exists pickup_ref_seq;
drop sequence if exists ticket_ref_seq;
drop sequence if exists credit_ref_seq;
drop sequence if exists proof_ref_seq;
drop sequence if exists handover_ref_seq;

-- ------------------------------------------------------- reference sequences
-- Human-speakable reference numbers. The agent reads these out on the call,
-- so they must be short and unambiguous.
create sequence case_ref_seq     start 1041;
create sequence refund_ref_seq   start 2207;
create sequence pickup_ref_seq   start 8841;
create sequence ticket_ref_seq   start 3302;
create sequence credit_ref_seq   start 5521;
create sequence proof_ref_seq    start 9043;
create sequence handover_ref_seq start 1180;

-- ---------------------------------------------------------------- merchants
create table merchants (
    id              uuid primary key default gen_random_uuid(),
    merchant_code   text not null unique,              -- M1 .. M4, demo handles
    owner_name      text not null,
    shop_name       text not null,
    phone           text not null unique,              -- E.164, registered mobile
    language_code   text not null default 'te-IN',     -- BCP-47, preferred language
    city            text not null default 'Hyderabad',
    address         text,
    shop_status     text not null default 'active'
                    check (shop_status in ('active', 'closed')),
    shop_closed_on  date,
    onboarded_on    date not null default current_date,
    created_at      timestamptz not null default now(),
    constraint closed_shops_have_a_date
        check (shop_status <> 'closed' or shop_closed_on is not null)
);

comment on table merchants is 'Seeded demo merchants. Looked up by caller phone.';

-- Lets us point a live caller number at a seeded persona during the demo
-- without touching merchants.phone.
create table phone_bindings (
    phone        text primary key,
    merchant_id  uuid not null references merchants(id) on delete cascade,
    bound_at     timestamptz not null default now(),
    note         text
);

-- ------------------------------------------------------------------ devices
create table devices (
    id                   uuid primary key default gen_random_uuid(),
    merchant_id          uuid not null references merchants(id) on delete cascade,
    device_type          text not null default 'Soundbox',
    serial               text not null unique,
    status               text not null default 'active'
                         check (status in ('active', 'pickup_scheduled',
                                           'picked_up', 'deactivated', 'faulty')),
    activated_on         date not null,
    last_heartbeat_at    timestamptz,
    billing_stopped_from date,                         -- set by the closure tool
    created_at           timestamptz not null default now()
);

create index devices_merchant_idx on devices(merchant_id);

-- -------------------------------------------------------------------- plans
-- Promised vs billed in one row: the "promise check" is then a single read.
create table plans (
    id                       uuid primary key default gen_random_uuid(),
    merchant_id              uuid not null references merchants(id) on delete cascade,
    promised_plan_name       text,
    promised_monthly_amount  numeric(12,2),
    promised_by              text,                     -- e.g. 'field sales, Hyderabad South'
    promised_on              date,
    billed_plan_name         text not null,
    billed_monthly_amount    numeric(12,2) not null,
    billing_started_on       date not null,
    created_at               timestamptz not null default now()
);

create unique index plans_one_per_merchant on plans(merchant_id);

-- ----------------------------------------------------------------- invoices
create table invoices (
    id            uuid primary key default gen_random_uuid(),
    merchant_id   uuid not null references merchants(id) on delete cascade,
    device_id     uuid references devices(id) on delete set null,
    period_start  date not null,
    period_end    date not null,
    amount        numeric(12,2) not null,
    description   text not null default 'Soundbox monthly rental',
    status        text not null default 'paid'
                  check (status in ('paid', 'due', 'credited')),
    charged_on    date not null
);

create index invoices_merchant_idx on invoices(merchant_id, charged_on);

-- -------------------------------------------------------------- settlements
create table settlements (
    id                    uuid primary key default gen_random_uuid(),
    merchant_id           uuid not null references merchants(id) on delete cascade,
    amount_on_hold        numeric(12,2) not null default 0,
    hold_reason_code      text,
    hold_reason_plain     text,                        -- what the agent actually says
    missing_documents     text[] not null default '{}',
    held_since            date,
    expected_release_date date,
    status                text not null default 'clear'
                          check (status in ('clear', 'on_hold', 'released'))
);

create unique index settlements_one_per_merchant on settlements(merchant_id);

-- -------------------------------------------------------------------- cases
create table cases (
    id             uuid primary key default gen_random_uuid(),
    case_ref       text not null unique
                   default 'SMD-' || nextval('case_ref_seq'),
    merchant_id    uuid references merchants(id) on delete set null,
    issue_type     text not null default 'unknown'
                   check (issue_type in ('device_closure', 'plan_mismatch',
                                          'settlement_hold', 'device_fault', 'unknown')),
    state          text not null default 'open'
                   check (state in ('open', 'acting', 'awaiting_approval',
                                     'resolved', 'handed_over')),
    channel        text not null default 'voice',
    language_code  text,
    caller_phone   text,
    -- A case OUTLIVES a call. Deliberately no interaction_id here: one case can
    -- span a dropped call plus two callbacks. See call_sessions.
    call_count     integer not null default 0,
    last_call_at   timestamptz,
    issue_summary  text,                               -- one line, for a returning caller
    opened_at      timestamptz not null default now(),
    updated_at     timestamptz not null default now(),
    resolved_at    timestamptz
);

create index cases_state_idx on cases(state, opened_at desc);

-- Find the resumable case for a caller: most recent case for this merchant
-- that is not finished.
create index cases_open_for_merchant_idx on cases(merchant_id, updated_at desc)
    where state in ('open', 'acting', 'awaiting_approval');

-- --------------------------------------------------------- call sessions
-- One row per PHONE CALL. A case has many. This is what makes "repeat calls
-- per case" measurable, and what lets a callback resume instead of restart.
create table call_sessions (
    id                uuid primary key default gen_random_uuid(),
    case_id           uuid not null references cases(id) on delete cascade,
    interaction_id    text not null unique,            -- Sarvam call id
    sequence_no       integer not null default 1,      -- 1st call, 2nd call, ...
    caller_phone      text,
    language_code     text,
    started_at        timestamptz not null default now(),
    ended_at          timestamptz,
    duration_s        integer,
    end_reason        text check (end_reason in ('completed', 'disconnected',
                                                  'transferred', 'unknown')),
    -- True when the call ended after a write action but before the merchant
    -- got written proof. The on_end hook repairs these.
    ended_mid_action  boolean not null default false,
    turn_count        integer not null default 0
);

create index call_sessions_case_idx on call_sessions(case_id, sequence_no);

-- -------------------------------------------------------------- case_events
-- APPEND ONLY. The whole case must be reconstructable from this table alone.
create table case_events (
    id               bigserial primary key,
    case_id          uuid not null references cases(id) on delete cascade,
    -- Which call this happened on. Null for things done from the dashboard.
    call_session_id  uuid references call_sessions(id) on delete set null,
    actor            text not null default 'agent'
                     check (actor in ('agent', 'human', 'system')),
    tool_name        text,
    args             jsonb,
    result           jsonb,
    say              text,
    ok               boolean,
    latency_ms       integer,
    idempotency_key  text,
    at               timestamptz not null default now()
);

create index case_events_case_idx on case_events(case_id, id);

-- -------------------------------------------------------- conversation turns
create table conversation_turns (
    id              bigserial primary key,
    case_id         uuid not null references cases(id) on delete cascade,
    call_session_id uuid references call_sessions(id) on delete set null,
    role            text not null check (role in ('merchant', 'samadhan')),
    text_original  text,                               -- as spoken, native script
    text_english   text,                               -- Saaras translate output
    language_code  text,
    at             timestamptz not null default now()
);

create index turns_case_idx on conversation_turns(case_id, id);

-- ----------------------------------------------------------- credit notes
create table credit_notes (
    id            uuid primary key default gen_random_uuid(),
    note_ref      text not null unique
                  default 'CN-' || nextval('credit_ref_seq'),
    case_id       uuid references cases(id) on delete set null,
    merchant_id   uuid not null references merchants(id) on delete cascade,
    amount        numeric(12,2) not null,
    period_start  date not null,
    period_end    date not null,
    reason        text,
    created_at    timestamptz not null default now()
);

-- One credit note per case, so a callback cannot credit the same months twice.
create unique index one_credit_note_per_case
    on credit_notes(case_id)
    where case_id is not null;

-- -------------------------------------------------------- service tickets
create table service_tickets (
    id              uuid primary key default gen_random_uuid(),
    ticket_ref      text not null unique,              -- PU-#### or TK-####
    kind            text not null check (kind in ('pickup', 'technician')),
    case_id         uuid references cases(id) on delete set null,
    merchant_id     uuid not null references merchants(id) on delete cascade,
    device_id       uuid references devices(id) on delete set null,
    scheduled_date  date not null,
    address         text,
    status          text not null default 'scheduled'
                    check (status in ('scheduled', 'completed', 'cancelled')),
    created_at      timestamptz not null default now()
);

-- STRUCTURAL idempotency. A dropped call followed by a callback is exactly when
-- a second pickup gets booked: different call, different idempotency key, same
-- intent. The database refuses it regardless of what the agent asks for.
create unique index one_open_ticket_per_case_kind
    on service_tickets(case_id, kind)
    where status = 'scheduled';

-- -------------------------------------------------------- refund requests
-- Nothing here ever pays out. A human decides. This table IS the safety story.
create table refund_requests (
    id             uuid primary key default gen_random_uuid(),
    request_ref    text not null unique
                   default 'RF-' || nextval('refund_ref_seq'),
    case_id        uuid references cases(id) on delete set null,
    merchant_id    uuid not null references merchants(id) on delete cascade,
    amount         numeric(12,2) not null check (amount > 0),
    reason         text not null,
    status         text not null default 'awaiting_approval'
                   check (status in ('awaiting_approval', 'approved', 'rejected')),
    requested_at   timestamptz not null default now(),
    decided_at     timestamptz,
    decided_by     text,
    decision_note  text,
    constraint decided_rows_have_a_decider
        check (status = 'awaiting_approval' or decided_by is not null)
);

create index refunds_status_idx on refund_requests(status, requested_at desc);

-- One pending refund per case, ever. A merchant calling back must not be able
-- to stack three refund requests for the same complaint.
create unique index one_pending_refund_per_case
    on refund_requests(case_id)
    where status = 'awaiting_approval';

-- ---------------------------------------------------------------- handovers
create table handovers (
    id            uuid primary key default gen_random_uuid(),
    summary_ref   text not null unique
                  default 'HO-' || nextval('handover_ref_seq'),
    case_id       uuid not null references cases(id) on delete cascade,
    reason        text not null,
    summary_md    text not null,
    transcript    text,
    created_at    timestamptz not null default now()
);

-- ------------------------------------------------------------------- proofs
create table proofs (
    id           uuid primary key default gen_random_uuid(),
    proof_ref    text not null unique
                 default 'PR-' || nextval('proof_ref_seq'),
    case_id      uuid not null references cases(id) on delete cascade,
    merchant_id  uuid not null references merchants(id) on delete cascade,
    channel      text not null default 'whatsapp',
    sent_to      text,
    subject      text,
    body_text    text,
    body_html    text,
    status       text not null default 'sent'
                 check (status in ('sent', 'failed')),
    sent_at      timestamptz not null default now()
);

-- ------------------------------------------------------------ idempotency
-- Sarvam retries on timeout. Replaying a key returns the first response
-- instead of booking a second pickup.
create table tool_idempotency (
    key         text primary key,
    tool_name   text not null,
    response    jsonb not null,
    created_at  timestamptz not null default now()
);

-- -------------------------------------------------------------------- view
-- Convenience for the dashboard: one row per case with the merchant joined and
-- a live action count. security_invoker makes RLS apply as the reader.
create view case_feed with (security_invoker = true) as
select
    c.id,
    c.case_ref,
    c.issue_type,
    c.state,
    c.language_code,
    c.caller_phone,
    c.call_count,
    c.last_call_at,
    c.issue_summary,
    c.opened_at,
    c.updated_at,
    c.resolved_at,
    m.merchant_code,
    m.shop_name,
    m.owner_name,
    m.city,
    (select count(*) from case_events e where e.case_id = c.id)            as action_count,
    (select count(*) from call_sessions s where s.case_id = c.id)           as calls,
    (select count(*) from call_sessions s
      where s.case_id = c.id and s.end_reason = 'disconnected')             as dropped_calls,
    (select count(*) from refund_requests r
      where r.case_id = c.id and r.status = 'awaiting_approval')           as pending_approvals,
    (select count(*) from proofs p where p.case_id = c.id)                 as proofs_sent
from cases c
left join merchants m on m.id = c.merchant_id;

-- --------------------------------------------------------------------- RLS
-- RLS is ON for every table and there are deliberately NO POLICIES AT ALL.
-- That means: nothing is readable or writable with the anon key. Full stop.
--
-- Why not grant anon SELECT so the dashboard can read directly?
-- Because the anon key is shipped to the browser in the JS bundle. It is a
-- public credential. `for select to anon using (true)` would publish every
-- merchant's phone number and address, every call transcript, and every
-- handover summary to anyone who loads the dashboard or guesses the project
-- URL. These tables hold merchant PII and the substance of support calls.
--
-- Access model instead:
--   * FastAPI uses the SERVICE-ROLE key. It bypasses RLS. Server-side only,
--     in backend/.env, never in a client bundle.
--   * The dashboard is Next.js and reads Supabase from the SERVER (server
--     components / route handlers) with the service-role key, so no key and
--     no data reaches the browser except the rows we chose to render.
--   * Cost of this choice: no client-side Realtime subscription, because that
--     would need a browser-side key. The dashboard revalidates every 3s
--     instead. Acceptable; a 3s delay is invisible next to a phone call.
--
-- If we later want true Realtime, the correct fix is Supabase Auth with an
-- operator role and policies like:
--     create policy staff_read_cases on cases for select to authenticated
--         using ((auth.jwt() ->> 'app_role') = 'operator');
-- That is the real answer, not a blanket anon grant.
alter table merchants          enable row level security;
alter table devices            enable row level security;
alter table plans              enable row level security;
alter table invoices           enable row level security;
alter table settlements        enable row level security;
alter table cases              enable row level security;
alter table call_sessions      enable row level security;
alter table case_events        enable row level security;
alter table conversation_turns enable row level security;
alter table credit_notes       enable row level security;
alter table service_tickets    enable row level security;
alter table refund_requests    enable row level security;
alter table handovers          enable row level security;
alter table proofs             enable row level security;
alter table phone_bindings     enable row level security;
alter table tool_idempotency   enable row level security;

-- No policies are created, on purpose. See the note above.
--
-- Belt and braces: revoke the table-level grants Supabase hands the public
-- roles by default, so even a future accidental policy cannot expose these
-- tables, and PostgREST stops advertising them to anon entirely.
revoke all on all tables in schema public from anon;
revoke all on all tables in schema public from authenticated;
revoke all on all sequences in schema public from anon;
revoke all on all sequences in schema public from authenticated;

-- Verify after running this file. Both queries should return ZERO rows.
--
--   select tablename, policyname from pg_policies where schemaname = 'public';
--
--   select table_name, privilege_type
--     from information_schema.role_table_grants
--    where grantee in ('anon', 'authenticated') and table_schema = 'public';
--
-- If either returns rows, the anon key can read something it should not.

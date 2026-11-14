"""
Every SQL statement lives here. Handlers in tools.py do no SQL of their own.

Two rules drive the shape of this file:

  1. One round trip per tool call wherever possible. The database is in
     Singapore and a warm query costs 90 ms, so four sequential reads cost
     360 ms before any thinking happens. `merchant_context` is therefore one
     query with joins and aggregates, not four.
  2. All arithmetic on money and dates happens in SQL or in Python here,
     never in a prompt. The model only ever relays a finished sentence.
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime
from typing import Any

# --------------------------------------------------------------- phone numbers


def normalise_phone(raw: str | None) -> str | None:
    """
    Merchants say their number a dozen ways and Sarvam passes caller id in
    whatever form the carrier gives. Reduce everything to +91XXXXXXXXXX.
    """
    if not raw:
        return None
    digits = re.sub(r"\D", "", str(raw))
    if not digits:
        return None
    if len(digits) > 10 and digits.startswith("91"):
        digits = digits[-10:]
    elif len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    elif len(digits) > 10:
        digits = digits[-10:]
    if len(digits) != 10:
        return None
    return "+91" + digits


# ------------------------------------------------------------------- merchants


def find_merchant(cur, phone: str | None = None, merchant_id: str | None = None,
                  merchant_code: str | None = None) -> dict[str, Any] | None:
    """
    Resolve a merchant by id, demo code, or phone number.

    Phone lookup checks phone_bindings first, so `POST /admin/bind-phone` can
    point a real calling number at a seeded persona for the live demo without
    touching merchants.phone.
    """
    if merchant_id:
        cur.execute("select * from merchants where id = %s", (merchant_id,))
        return cur.fetchone()

    if merchant_code:
        cur.execute("select * from merchants where merchant_code = %s",
                    (merchant_code.upper(),))
        return cur.fetchone()

    normalised = normalise_phone(phone)
    if not normalised:
        return None

    cur.execute(
        """
        select m.*
          from merchants m
         where m.id = (select merchant_id from phone_bindings where phone = %s)
         union all
        select m.* from merchants m where m.phone = %s
         limit 1
        """,
        (normalised, normalised),
    )
    return cur.fetchone()


def merchant_context(cur, merchant_id: str) -> dict[str, Any]:
    """
    THE fat read. Everything the agent needs to understand the situation, in
    one round trip: merchant, device, plan, billing totals, post-closure
    charges, and settlement hold.
    """
    cur.execute(
        """
        select
            m.id                      as merchant_id,
            m.merchant_code,
            m.owner_name,
            m.shop_name,
            m.phone,
            m.language_code,
            m.city,
            m.address,
            m.shop_status,
            m.shop_closed_on,

            d.id                      as device_id,
            d.device_type,
            d.serial                  as device_serial,
            d.status                  as device_status,
            d.billing_stopped_from,
            case when d.last_heartbeat_at is null then null
                 else extract(day from now() - d.last_heartbeat_at)::int
            end                       as device_last_seen_days,

            p.promised_plan_name      as promised_plan,
            p.promised_monthly_amount,
            p.promised_by,
            p.promised_on,
            p.billed_plan_name        as billed_plan,
            p.billed_monthly_amount,

            coalesce(inv.months_charged, 0)       as months_charged,
            coalesce(inv.total_charged, 0)        as total_charged,
            coalesce(inv.first_charge_on, null)   as first_charge_on,
            coalesce(inv.last_charge_on, null)    as last_charge_on,
            coalesce(post.months_after_closure, 0) as months_charged_after_closure,
            coalesce(post.amount_after_closure, 0) as amount_charged_after_closure,

            coalesce(s.status, 'clear')           as settlement_status,
            coalesce(s.amount_on_hold, 0)         as settlement_amount_on_hold

          from merchants m
          left join devices d on d.merchant_id = m.id
          left join plans   p on p.merchant_id = m.id
          left join settlements s on s.merchant_id = m.id
          left join lateral (
              select count(*)        as months_charged,
                     sum(i.amount)   as total_charged,
                     min(i.charged_on) as first_charge_on,
                     max(i.charged_on) as last_charge_on
                from invoices i
               where i.merchant_id = m.id
          ) inv on true
          left join lateral (
              -- Charges raised AFTER the shop closed, and not already credited.
              select count(*)      as months_after_closure,
                     sum(i.amount) as amount_after_closure
                from invoices i
               where i.merchant_id = m.id
                 and m.shop_closed_on is not null
                 and i.charged_on > m.shop_closed_on
                 and i.status <> 'credited'
          ) post on true
         where m.id = %s
        """,
        (merchant_id,),
    )
    return cur.fetchone()


def billing_summary(cur, merchant_id: str) -> dict[str, Any]:
    cur.execute(
        """
        select p.billed_plan_name             as billed_plan,
               p.billed_monthly_amount        as monthly_amount,
               count(i.id)                    as months_charged,
               coalesce(sum(i.amount), 0)     as total_charged,
               min(i.charged_on)              as first_charge_on,
               max(i.charged_on)              as last_charge_on,
               coalesce(sum(i.amount) filter (where i.status = 'due'), 0)
                                              as dues_outstanding
          from merchants m
          left join plans    p on p.merchant_id = m.id
          left join invoices i on i.merchant_id = m.id
         where m.id = %s
         group by p.billed_plan_name, p.billed_monthly_amount
        """,
        (merchant_id,),
    )
    return cur.fetchone() or {}


def promise_check(cur, merchant_id: str) -> dict[str, Any]:
    """
    The USP read. Compares what sales promised against what is billed, and
    counts only months NOT already covered by a credit note.

    That exclusion is the guard Rahul asked for: without it, a merchant with
    both a closure and a promo mismatch could be credited and refunded for the
    same month.
    """
    cur.execute(
        """
        select p.promised_plan_name       as promised_plan,
               p.promised_monthly_amount,
               p.promised_by,
               p.promised_on,
               p.billed_plan_name         as billed_plan,
               p.billed_monthly_amount,
               count(i.id) filter (
                   where i.status <> 'credited'
                     and (p.promised_on is null or i.charged_on >= p.promised_on)
               )                          as months_affected,
               count(i.id) filter (where i.status = 'credited')
                                          as months_already_credited
          from plans p
          join merchants m on m.id = p.merchant_id
          left join invoices i on i.merchant_id = p.merchant_id
         where p.merchant_id = %s
         group by p.promised_plan_name, p.promised_monthly_amount, p.promised_by,
                  p.promised_on, p.billed_plan_name, p.billed_monthly_amount
        """,
        (merchant_id,),
    )
    return cur.fetchone() or {}


def settlement_hold(cur, merchant_id: str) -> dict[str, Any]:
    cur.execute(
        """
        select amount_on_hold, hold_reason_code, hold_reason_plain,
               missing_documents, held_since, expected_release_date, status
          from settlements
         where merchant_id = %s
        """,
        (merchant_id,),
    )
    return cur.fetchone() or {}


def device_for(cur, merchant_id: str) -> dict[str, Any] | None:
    cur.execute(
        """
        select id, device_type, serial, status, activated_on, last_heartbeat_at,
               billing_stopped_from,
               case when last_heartbeat_at is null then null
                    else extract(day from now() - last_heartbeat_at)::int
               end as last_seen_days
          from devices
         where merchant_id = %s
        """,
        (merchant_id,),
    )
    return cur.fetchone()


# ----------------------------------------------------------------------- cases


def resumable_case(cur, merchant_id: str, window_days: int) -> dict[str, Any] | None:
    """The case a callback should continue, if there is one."""
    cur.execute(
        """
        select * from cases
         where merchant_id = %s
           and state in ('open', 'acting', 'awaiting_approval')
           and updated_at > now() - make_interval(days => %s)
         order by updated_at desc
         limit 1
        """,
        (merchant_id, window_days),
    )
    return cur.fetchone()


def last_resolved_case(cur, merchant_id: str) -> dict[str, Any] | None:
    """
    For a merchant calling back about something already fixed. Rahul's point 5:
    without this they get a new case and have to explain again.
    """
    cur.execute(
        """
        select * from cases
         where merchant_id = %s
           and state in ('resolved', 'handed_over')
         order by coalesce(resolved_at, updated_at) desc
         limit 1
        """,
        (merchant_id,),
    )
    return cur.fetchone()


def create_case(cur, merchant_id: str | None, issue_type: str, language_code: str | None,
                caller_phone: str | None) -> dict[str, Any]:
    cur.execute(
        """
        insert into cases (merchant_id, issue_type, language_code, caller_phone)
        values (%s, %s, %s, %s)
        returning *
        """,
        (merchant_id, issue_type, language_code, caller_phone),
    )
    return cur.fetchone()


def set_case_state(cur, case_id: str, state: str, issue_type: str | None = None,
                   issue_summary: str | None = None) -> None:
    cur.execute(
        """
        update cases
           set state        = %s,
               issue_type   = coalesce(%s, issue_type),
               issue_summary = coalesce(%s, issue_summary),
               updated_at   = now(),
               resolved_at  = case when %s in ('resolved', 'handed_over')
                                   then coalesce(resolved_at, now())
                                   else resolved_at end
         where id = %s
        """,
        (state, issue_type, issue_summary, state, case_id),
    )


def case_by_interaction(cur, interaction_id: str) -> dict[str, Any] | None:
    cur.execute(
        """
        select c.*, s.id as call_session_id, s.sequence_no
          from call_sessions s
          join cases c on c.id = s.case_id
         where s.interaction_id = %s
        """,
        (interaction_id,),
    )
    return cur.fetchone()


# --------------------------------------------------------------- call sessions


def open_call_session(cur, case_id: str, interaction_id: str, caller_phone: str | None,
                      language_code: str | None, trusted: bool = False) -> dict[str, Any]:
    """
    `trusted` must be True ONLY from the call_started lifecycle hook, which the
    voice platform runs without the LLM. Everywhere else the phone number came
    in as a tool argument, so it cannot be used as a caller-id factor.

    The conflict clause never downgrades a trusted number to an untrusted one,
    and never lets an untrusted call overwrite a trusted number.
    """
    cur.execute(
        """
        insert into call_sessions
            (case_id, interaction_id, sequence_no, caller_phone,
             caller_phone_trusted, language_code)
        values
            (%s, %s,
             (select coalesce(max(sequence_no), 0) + 1 from call_sessions where case_id = %s),
             %s, %s, %s)
        on conflict (interaction_id) do update
           set caller_phone = case
                   when call_sessions.caller_phone_trusted and not excluded.caller_phone_trusted
                   then call_sessions.caller_phone
                   else coalesce(excluded.caller_phone, call_sessions.caller_phone)
               end,
               caller_phone_trusted =
                   call_sessions.caller_phone_trusted or excluded.caller_phone_trusted
        returning *
        """,
        (case_id, interaction_id, case_id, caller_phone, trusted, language_code),
    )
    session = cur.fetchone()
    cur.execute(
        """
        update cases
           set call_count = (select count(*) from call_sessions where case_id = %s),
               last_call_at = now(),
               updated_at = now()
         where id = %s
        """,
        (case_id, case_id),
    )
    return session


def close_call_session(cur, interaction_id: str, end_reason: str,
                       duration_s: int | None) -> dict[str, Any] | None:
    cur.execute(
        """
        update call_sessions
           set ended_at   = now(),
               end_reason = %s,
               duration_s = coalesce(%s, extract(epoch from now() - started_at)::int)
         where interaction_id = %s
         returning *
        """,
        (end_reason, duration_s, interaction_id),
    )
    return cur.fetchone()


def mark_session_mid_action(cur, session_id: str) -> None:
    cur.execute("update call_sessions set ended_mid_action = true where id = %s",
                (session_id,))


def previous_calls(cur, case_id: str, exclude_interaction: str | None) -> list[dict[str, Any]]:
    # The ::text casts matter: without them Postgres cannot infer the type of a
    # NULL parameter and raises IndeterminateDatatype.
    cur.execute(
        """
        select sequence_no, started_at, ended_at, end_reason, duration_s
          from call_sessions
         where case_id = %s
           and (%s::text is null or interaction_id <> %s::text)
         order by sequence_no
        """,
        (case_id, exclude_interaction, exclude_interaction),
    )
    return cur.fetchall()


def case_and_session(cur, interaction_id: str) -> dict[str, Any] | None:
    """
    Case plus call session in ONE round trip.

    Every tool call starts by resolving who is calling about what. At 90 ms per
    query to Singapore, doing that in six queries costs half the 2-second
    budget before any work happens.
    """
    cur.execute(
        """
        select c.*,
               s.id                   as session_id,
               s.sequence_no          as session_sequence_no,
               s.caller_phone         as session_caller_phone,
               s.caller_phone_trusted as session_caller_trusted
          from call_sessions s
          join cases c on c.id = s.case_id
         where s.interaction_id = %s
        """,
        (interaction_id,),
    )
    return cur.fetchone()


def action_summary_row(cur, case_id: str) -> dict[str, Any] | None:
    """
    Everything already done on this case, in ONE round trip.

    Typed columns rather than row_to_json on purpose: json turns dates into
    strings, and these dates get spoken aloud.
    """
    cur.execute(
        """
        select
            (select d.billing_stopped_from from devices d
              where d.merchant_id = c.merchant_id limit 1)        as billing_stopped_from,
            (select n.amount from credit_notes n
              where n.case_id = c.id limit 1)                     as credit_amount,
            (select n.note_ref from credit_notes n
              where n.case_id = c.id limit 1)                     as credit_ref,
            (select t.scheduled_date from service_tickets t
              where t.case_id = c.id and t.kind = 'pickup'
                and t.status = 'scheduled' limit 1)               as pickup_date,
            (select t.ticket_ref from service_tickets t
              where t.case_id = c.id and t.kind = 'pickup'
                and t.status = 'scheduled' limit 1)               as pickup_ref,
            (select t.scheduled_date from service_tickets t
              where t.case_id = c.id and t.kind = 'technician'
                and t.status = 'scheduled' limit 1)               as technician_date,
            (select r.amount from refund_requests r
              where r.case_id = c.id
                and r.status = 'awaiting_approval' limit 1)       as refund_amount,
            (select r.request_ref from refund_requests r
              where r.case_id = c.id
                and r.status = 'awaiting_approval' limit 1)       as refund_ref,
            (select count(*) from proofs p where p.case_id = c.id) as proof_count
          from cases c
         where c.id = %s
        """,
        (case_id,),
    )
    return cur.fetchone()


# ------------------------------------------------------------------ audit log


def log_event(cur, case_id: str, call_session_id: str | None, tool_name: str,
              args: dict[str, Any] | None, result: dict[str, Any] | None,
              say: str | None, ok: bool, latency_ms: int | None,
              idempotency_key: str | None, actor: str = "agent") -> None:
    """
    Append-only. Every tool call writes one of these, successes and failures
    alike. The whole case must be reconstructable from this table.
    """
    cur.execute(
        """
        insert into case_events
            (case_id, call_session_id, actor, tool_name, args, result, say, ok,
             latency_ms, idempotency_key)
        values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (case_id, call_session_id, actor, tool_name,
         json.dumps(args, default=str) if args is not None else None,
         json.dumps(result, default=str) if result is not None else None,
         say, ok, latency_ms, idempotency_key),
    )


def events_for_case(cur, case_id: str) -> list[dict[str, Any]]:
    cur.execute(
        """
        select id, call_session_id, actor, tool_name, say, ok, latency_ms, at
          from case_events
         where case_id = %s
         order by id
        """,
        (case_id,),
    )
    return cur.fetchall()


def count_tool_calls(cur, case_id: str, tool_name: str) -> int:
    cur.execute(
        "select count(*) as n from case_events where case_id = %s and tool_name = %s and ok",
        (case_id, tool_name),
    )
    return cur.fetchone()["n"]


# --------------------------------------------------------------- idempotency


def idempotent_hit(cur, key: str) -> dict[str, Any] | None:
    if not key:
        return None
    cur.execute("select response from tool_idempotency where key = %s", (key,))
    row = cur.fetchone()
    return row["response"] if row else None


def idempotent_store(cur, key: str, tool_name: str, response: dict[str, Any]) -> None:
    if not key:
        return
    cur.execute(
        """
        insert into tool_idempotency (key, tool_name, response)
        values (%s, %s, %s)
        on conflict (key) do nothing
        """,
        (key, tool_name, json.dumps(response, default=str)),
    )


# ------------------------------------------------------------- write actions


def stop_billing(cur, device_id: str, from_date: date) -> None:
    cur.execute(
        """
        update devices
           set billing_stopped_from = %s,
               status = case when status = 'active' then 'pickup_scheduled' else status end
         where id = %s
        """,
        (from_date, device_id),
    )


def credit_post_closure_invoices(cur, merchant_id: str, after: date) -> dict[str, Any]:
    """Mark the post-closure charges as credited and return the total."""
    cur.execute(
        """
        update invoices
           set status = 'credited'
         where merchant_id = %s
           and charged_on > %s
           and status <> 'credited'
         returning amount, charged_on
        """,
        (merchant_id, after),
    )
    rows = cur.fetchall()
    total = sum(r["amount"] for r in rows) if rows else 0
    return {
        "count": len(rows),
        "total": total,
        "first": min((r["charged_on"] for r in rows), default=None),
        "last": max((r["charged_on"] for r in rows), default=None),
    }


def create_credit_note(cur, case_id: str, merchant_id: str, amount, period_start: date,
                       period_end: date, reason: str) -> dict[str, Any]:
    cur.execute(
        """
        insert into credit_notes
            (case_id, merchant_id, amount, period_start, period_end, reason)
        values (%s, %s, %s, %s, %s, %s)
        returning *
        """,
        (case_id, merchant_id, amount, period_start, period_end, reason),
    )
    return cur.fetchone()


def existing_credit_note(cur, case_id: str) -> dict[str, Any] | None:
    cur.execute("select * from credit_notes where case_id = %s", (case_id,))
    return cur.fetchone()


def create_ticket(cur, kind: str, ref: str, case_id: str, merchant_id: str,
                  device_id: str | None, scheduled_date: date,
                  address: str | None) -> dict[str, Any]:
    cur.execute(
        """
        insert into service_tickets
            (ticket_ref, kind, case_id, merchant_id, device_id, scheduled_date, address)
        values (%s, %s, %s, %s, %s, %s, %s)
        returning *
        """,
        (ref, kind, case_id, merchant_id, device_id, scheduled_date, address),
    )
    return cur.fetchone()


def existing_ticket(cur, case_id: str, kind: str) -> dict[str, Any] | None:
    cur.execute(
        """
        select * from service_tickets
         where case_id = %s and kind = %s and status = 'scheduled'
         limit 1
        """,
        (case_id, kind),
    )
    return cur.fetchone()


def next_ref(cur, sequence: str, prefix: str) -> str:
    cur.execute(f"select '{prefix}-' || nextval('{sequence}') as ref")
    return cur.fetchone()["ref"]


def create_refund_request(cur, case_id: str, merchant_id: str, amount, reason: str) -> dict[str, Any]:
    cur.execute(
        """
        insert into refund_requests (case_id, merchant_id, amount, reason)
        values (%s, %s, %s, %s)
        returning *
        """,
        (case_id, merchant_id, amount, reason),
    )
    return cur.fetchone()


def pending_refund(cur, case_id: str) -> dict[str, Any] | None:
    cur.execute(
        """
        select * from refund_requests
         where case_id = %s and status = 'awaiting_approval'
         limit 1
        """,
        (case_id,),
    )
    return cur.fetchone()


def pending_refund_for_merchant(cur, merchant_id: str) -> dict[str, Any] | None:
    cur.execute(
        """
        select * from refund_requests
         where merchant_id = %s and status = 'awaiting_approval'
         order by requested_at desc
         limit 1
        """,
        (merchant_id,),
    )
    return cur.fetchone()


def decide_refund(cur, request_ref: str, status: str, decided_by: str,
                  note: str | None) -> dict[str, Any] | None:
    cur.execute(
        """
        update refund_requests
           set status = %s, decided_at = now(), decided_by = %s, decision_note = %s
         where request_ref = %s and status = 'awaiting_approval'
         returning *
        """,
        (status, decided_by, note, request_ref),
    )
    return cur.fetchone()


def list_pending_refunds(cur) -> list[dict[str, Any]]:
    cur.execute(
        """
        select r.*, m.shop_name, m.owner_name, c.case_ref
          from refund_requests r
          join merchants m on m.id = r.merchant_id
          left join cases c on c.id = r.case_id
         where r.status = 'awaiting_approval'
         order by r.requested_at
        """,
    )
    return cur.fetchall()


def create_handover(cur, case_id: str, reason: str, summary_md: str,
                    transcript: str | None) -> dict[str, Any]:
    cur.execute(
        """
        insert into handovers (case_id, reason, summary_md, transcript)
        values (%s, %s, %s, %s)
        returning *
        """,
        (case_id, reason, summary_md, transcript),
    )
    return cur.fetchone()


def create_proof(cur, case_id: str, merchant_id: str, channel: str, sent_to: str | None,
                 subject: str, body_text: str, body_html: str) -> dict[str, Any]:
    cur.execute(
        """
        insert into proofs
            (case_id, merchant_id, channel, sent_to, subject, body_text, body_html)
        values (%s, %s, %s, %s, %s, %s, %s)
        returning *
        """,
        (case_id, merchant_id, channel, sent_to, subject, body_text, body_html),
    )
    return cur.fetchone()


def existing_proof(cur, case_id: str) -> dict[str, Any] | None:
    cur.execute(
        "select * from proofs where case_id = %s order by sent_at desc limit 1",
        (case_id,),
    )
    return cur.fetchone()


def add_turn(cur, case_id: str, call_session_id: str | None, role: str,
             text_original: str | None, text_english: str | None,
             language_code: str | None) -> None:
    cur.execute(
        """
        insert into conversation_turns
            (case_id, call_session_id, role, text_original, text_english, language_code)
        values (%s, %s, %s, %s, %s, %s)
        """,
        (case_id, call_session_id, role, text_original, text_english, language_code),
    )


def bind_phone(cur, phone: str, merchant_id: str, note: str | None) -> None:
    cur.execute(
        """
        insert into phone_bindings (phone, merchant_id, note)
        values (%s, %s, %s)
        on conflict (phone) do update
            set merchant_id = excluded.merchant_id,
                bound_at = now(),
                note = excluded.note
        """,
        (phone, merchant_id, note),
    )


# ------------------------------------------------------------------ dashboard


def case_feed(cur, limit: int = 50) -> list[dict[str, Any]]:
    cur.execute("select * from case_feed order by updated_at desc limit %s", (limit,))
    return cur.fetchall()


def case_detail(cur, case_ref: str) -> dict[str, Any] | None:
    cur.execute("select * from case_feed where case_ref = %s", (case_ref,))
    return cur.fetchone()

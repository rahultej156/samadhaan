"""
The nine tools and the two Sarvam lifecycle hooks.

Three rules hold for every handler in this file:

  1. It returns HTTP 200. Always. A 4xx or 5xx leaves the agent with nothing to
     say and the merchant listening to silence. Failures come back as
     ok: false with a speakable `say`.
  2. It returns a `say`. Always, including on failure. Rahul's agent speaks
     `{{say}}` and nothing else.
  3. It computes every date and amount itself. The model relays; it never
     calculates. That is why `request_date`, `idempotency_key` and `step` are
     accepted and ignored.
"""

from __future__ import annotations

import logging
import time
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Request

import config
import engine
import queries as q
import speak as sp
from db import tx

log = logging.getLogger("samadhan.tools")
router = APIRouter(prefix="/tools", tags=["tools"])


# ----------------------------------------------------------------- plumbing


async def body_of(request: Request) -> dict[str, Any]:
    """
    Tolerant parsing. Sarvam can send JSON, form data, or an empty body, and a
    parse error must not become a 500 mid-call.
    """
    try:
        payload = await request.json()
        return payload if isinstance(payload, dict) else {"_raw": payload}
    except Exception:
        try:
            form = await request.form()
            return dict(form)
        except Exception:
            return {}


def fail(say: str, reason: str, **extra: Any) -> dict[str, Any]:
    return {"ok": False, "reason": reason, "say": say, **extra}


NOT_FOUND = (
    "I could not find an account for the number you are calling from. Please "
    "tell me the mobile number registered with your Paytm for Business account."
)

TROUBLE = (
    "I am having trouble reading your account right now. Let me connect you to "
    "a colleague who can help."
)


def _handler(tool_name: str, needs_merchant: bool = True):
    """
    Wraps a handler so that every call: opens one transaction, resolves the
    caller, writes exactly one audit row, and cannot raise out to the client.
    """
    def decorate(fn):
        async def wrapper(request: Request) -> dict[str, Any]:
            started = time.perf_counter()
            body = await body_of(request)
            try:
                with tx() as cur:
                    ctx = engine.resolve(cur, body)

                    if needs_merchant and ctx.merchant is None:
                        payload = fail(NOT_FOUND, "no merchant for caller phone",
                                       found=False)
                        if ctx.case_id:
                            q.log_event(cur, ctx.case_id, ctx.session_id, tool_name,
                                        body, payload, payload["say"], False,
                                        int((time.perf_counter() - started) * 1000), None)
                        return payload

                    payload = fn(ctx)
                    latency = int((time.perf_counter() - started) * 1000)
                    if ctx.case_id:
                        q.log_event(cur, ctx.case_id, ctx.session_id, tool_name, body,
                                    payload, payload.get("say"),
                                    bool(payload.get("ok")), latency,
                                    payload.get("_idem_key"))
                    payload.pop("_idem_key", None)
                    if config.DEBUG:
                        log.info("%s %sms ok=%s say=%r", tool_name, latency,
                                 payload.get("ok"), (payload.get("say") or "")[:90])
                    return payload
            except Exception:
                log.exception("%s failed", tool_name)
                return fail(TROUBLE, "internal error")

        wrapper.__name__ = fn.__name__
        return wrapper
    return decorate


def idempotent(ctx: engine.Ctx, action: str) -> tuple[str, dict[str, Any] | None]:
    """Case-scoped key, and the first response if this action already ran."""
    key = ctx.idem_key(action)
    return key, q.idempotent_hit(ctx.cur, key)


def remember(ctx: engine.Ctx, key: str, tool: str, payload: dict[str, Any]) -> None:
    q.idempotent_store(ctx.cur, key, tool, {k: v for k, v in payload.items()
                                            if k != "_idem_key"})


# ------------------------------------------------- 0a. call_started (on_start)


@router.post("/call-started")
async def call_started(request: Request) -> dict[str, Any]:
    """Sarvam `on_start`. Opens or resumes the case before the agent speaks."""
    started = time.perf_counter()
    body = await body_of(request)
    try:
        with tx() as cur:
            ctx = engine.resolve(cur, body)
            lang = body.get("language_code") or (
                ctx.merchant["language_code"] if ctx.merchant else None)
            payload = {
                "ok": True,
                "case_ref": ctx.case_ref,
                "call_sequence_no": ctx.session["sequence_no"] if ctx.session else 1,
                "resumed": ctx.resumed,
                "state": ctx.case["state"] if ctx.case else "open",
                "found": ctx.merchant is not None,
                "tts_supported": lang not in engine.TTS_UNSUPPORTED if lang else True,
            }
            if ctx.case_id:
                q.log_event(cur, ctx.case_id, ctx.session_id, "call_started", body,
                            payload, None, True,
                            int((time.perf_counter() - started) * 1000), None,
                            actor="system")
            return payload
    except Exception:
        log.exception("call_started failed")
        return {"ok": False, "reason": "internal error"}


# --------------------------------------------------- 0b. call_ended (on_end)


@router.post("/call-ended")
async def call_ended(request: Request) -> dict[str, Any]:
    """
    Sarvam `on_end`. The repair mechanism for a dropped call: if the case has
    write actions but no proof was sent, send it anyway.

    This is what makes slide 3's "Prove" survive the merchant's network
    dropping. The action was real, so the confirmation goes out regardless of
    whether the conversation finished.
    """
    body = await body_of(request)
    try:
        with tx() as cur:
            interaction_id = body.get("interaction_id")
            if not interaction_id:
                return {"ok": False, "reason": "interaction_id is required"}

            end_reason = (body.get("end_reason") or "unknown").lower()
            if end_reason not in {"completed", "disconnected", "transferred", "unknown"}:
                end_reason = "unknown"

            duration = body.get("duration_s")
            session = q.close_call_session(cur, interaction_id, end_reason,
                                           int(duration) if duration else None)
            if session is None:
                return {"ok": False, "reason": "unknown interaction_id"}

            case = q.case_by_interaction(cur, interaction_id)
            if case is None:
                return {"ok": True, "note": "session closed, no case"}

            ctx = engine.Ctx(cur=cur, case=case, session=session, args=body)
            if case.get("merchant_id"):
                ctx.merchant = q.find_merchant(cur, merchant_id=case["merchant_id"])

            spoken, done = engine.summarise_actions(cur, case["id"])
            proof_sent = "proof_sent" in done
            mid_action = engine.has_write_actions(done) and not proof_sent

            payload: dict[str, Any] = {
                "ok": True,
                "case_ref": case["case_ref"],
                "end_reason": end_reason,
                "ended_mid_action": mid_action,
                "proof_sent": False,
            }

            if mid_action and ctx.merchant:
                q.mark_session_mid_action(cur, session["id"])
                built = engine.build_proof(cur, ctx)
                proof = q.create_proof(cur, case["id"], ctx.merchant_id, "whatsapp",
                                       ctx.merchant.get("phone"), built["subject"],
                                       built["body_text"], built["body_html"])
                payload["proof_sent"] = True
                payload["proof_ref"] = proof["proof_ref"]
                q.log_event(cur, case["id"], session["id"], "send_confirmation",
                            {"trigger": "call_ended repair"},
                            {"proof_ref": proof["proof_ref"]},
                            "Written confirmation sent after the call dropped.",
                            True, None, None, actor="system")

            q.log_event(cur, case["id"], session["id"], "call_ended", body, payload,
                        None, True, None, None, actor="system")
            return payload
    except Exception:
        log.exception("call_ended failed")
        return {"ok": False, "reason": "internal error"}


# ---------------------------------------------------- 1. get_merchant_context


@router.post("/merchant-context")
@_handler("get_merchant_context")
def merchant_context(ctx: engine.Ctx) -> dict[str, Any]:
    cur = ctx.cur
    m = q.merchant_context(cur, ctx.merchant["id"])
    spoken_done, done = engine.summarise_actions(cur, ctx.case_id)
    prior = q.previous_calls(cur, ctx.case_id, ctx.args.get("interaction_id"))

    # Both of these are extra round trips to Singapore, so only pay for them
    # when the cheaper information we already have does not answer the question.
    pending = q.pending_refund(cur, ctx.case_id) if "refund_pending" in done else None
    if pending is None and not prior:
        pending = q.pending_refund_for_merchant(cur, ctx.merchant["id"])
    resolved = q.last_resolved_case(cur, ctx.merchant["id"]) if not prior else None

    promised = m["promised_monthly_amount"]
    billed = m["billed_monthly_amount"]
    mismatch = promised is not None and billed is not None and promised != billed
    lang = m["language_code"]

    payload: dict[str, Any] = {
        "ok": True,
        "found": True,
        "case_ref": ctx.case_ref,
        "merchant_id": str(m["merchant_id"]),
        "merchant_name": m["shop_name"],
        "owner_name": m["owner_name"],
        "city": m["city"],
        "language_code": lang,
        "tts_supported": lang not in engine.TTS_UNSUPPORTED,
        "shop_status": m["shop_status"],
        "shop_closed_on": m["shop_closed_on"],
        "device_type": m["device_type"],
        "device_serial": m["device_serial"],
        "device_status": m["device_status"],
        "device_last_seen_days": m["device_last_seen_days"],
        "billed_plan": m["billed_plan"],
        "billed_monthly_amount": float(billed) if billed is not None else None,
        "billed_monthly_amount_text": sp.rupees_text(billed) if billed is not None else None,
        "promised_plan": m["promised_plan"],
        "promised_monthly_amount": float(promised) if promised is not None else None,
        "plan_mismatch": mismatch,
        "months_charged_after_closure": m["months_charged_after_closure"],
        "amount_charged_after_closure": float(m["amount_charged_after_closure"]),
        "amount_charged_after_closure_text": sp.rupees_text(m["amount_charged_after_closure"]),
        "settlement_on_hold": m["settlement_status"] == "on_hold",
        "settlement_amount_on_hold": float(m["settlement_amount_on_hold"]),
        "returning_caller": bool(prior),
        "call_sequence_no": ctx.session["sequence_no"] if ctx.session else 1,
        "previous_calls": len(prior),
        "case_state": ctx.case["state"],
        "issue_summary": ctx.case.get("issue_summary"),
        "actions_already_taken_text": spoken_done,
        "proof_sent": "proof_sent" in done,
        "pending_approval": pending is not None,
        "verify_question_text": engine.verify_question(ctx.merchant),
    }

    if prior:
        last = prior[-1]
        payload["last_call_ago_text"] = sp.ago_text(last["started_at"])
        payload["last_call_end_reason"] = last["end_reason"]
    else:
        payload["last_call_ago_text"] = None
        payload["last_call_end_reason"] = None

    if pending:
        payload["pending_refund_ref"] = pending["request_ref"]
        payload["pending_refund_amount_text"] = sp.rupees_text(pending["amount"])

    payload["remaining_steps_text"] = engine.remaining_steps(done)

    if resolved and not prior:
        payload["last_resolved_case_text"] = (
            f"case {resolved['case_ref']}, closed {sp.date_spoken(resolved.get('resolved_at'))}"
        )
    else:
        payload["last_resolved_case_text"] = None

    # --------------------------------------------------------------- the say
    if not payload["tts_supported"]:
        payload["say"] = (
            "I can see your account, but I cannot speak your language yet. "
            "I am connecting you to a colleague who can."
        )
        return payload

    if prior and spoken_done:
        bits = [
            f"I can see we spoke {payload['last_call_ago_text']}",
            "and the call dropped" if last["end_reason"] == "disconnected" else "",
        ]
        opening = " ".join(b for b in bits if b)
        # No tail when the confirmation is already named in the action list,
        # or the agent says it twice in one breath.
        tail = ""
        if pending:
            tail = (" That refund is with a colleague for approval and has not "
                    "been forgotten.")
        payload["say"] = (
            f"{opening}. You do not need to explain again. I had already "
            f"{spoken_done}.{tail} Is there anything else about this?"
        )
        return payload

    if payload["last_resolved_case_text"]:
        payload["say"] = (
            f"I can see your shop {m['shop_name']}. We closed your earlier "
            f"{payload['last_resolved_case_text']}. Please tell me what the "
            f"problem is now."
        )
        return payload

    # First call on a fresh case: state the situation we can see.
    if m["shop_status"] == "closed" and m["months_charged_after_closure"]:
        payload["say"] = (
            f"I can see your shop {m['shop_name']} in {m['city']}. Your "
            f"{m['device_type']} is still active and you have been charged "
            f"{sp.rupees_spoken(billed)} a month, "
            f"{sp.rupees_spoken(m['amount_charged_after_closure'])} in total, "
            f"since your shop closed in {sp.month_spoken(m['shop_closed_on'])}."
        )
    elif mismatch:
        payload["say"] = (
            f"I can see your shop {m['shop_name']}. You are being billed "
            f"{sp.rupees_spoken(billed)} a month. Let me check what you were "
            f"promised when you signed up."
        )
    elif payload["settlement_on_hold"]:
        payload["say"] = (
            f"I can see your shop {m['shop_name']}, and that "
            f"{sp.rupees_spoken(m['settlement_amount_on_hold'])} of your "
            f"settlement is on hold. Let me explain why."
        )
    elif m["device_last_seen_days"] and m["device_last_seen_days"] > 2:
        payload["say"] = (
            f"I can see your shop {m['shop_name']}. Your {m['device_type']} has "
            f"not been heard from for {sp.days_spoken(m['device_last_seen_days'])}. "
            f"Tell me what is happening with it."
        )
    else:
        payload["say"] = (
            f"I can see your shop {m['shop_name']} in {m['city']}. Please tell "
            f"me what the problem is."
        )
    return payload


# ------------------------------------------------------ 2. get_billing_summary


@router.post("/billing")
@_handler("get_billing_summary")
def billing(ctx: engine.Ctx) -> dict[str, Any]:
    s = q.billing_summary(ctx.cur, ctx.merchant["id"])
    if not s or s.get("monthly_amount") is None:
        return fail("I cannot see a billing plan on your account. Let me connect "
                    "you to a colleague.", "no plan on merchant")

    payload = {
        "ok": True,
        "billed_plan": s["billed_plan"],
        "monthly_amount": float(s["monthly_amount"]),
        "monthly_amount_text": sp.rupees_text(s["monthly_amount"]),
        "months_charged": s["months_charged"],
        "total_charged": float(s["total_charged"]),
        "total_charged_text": sp.rupees_text(s["total_charged"]),
        "first_charge_on": s["first_charge_on"],
        "last_charge_on": s["last_charge_on"],
        "dues_outstanding": float(s["dues_outstanding"]),
    }
    payload["say"] = (
        f"You are on the {s['billed_plan']} plan at "
        f"{sp.rupees_spoken(s['monthly_amount'])} a month. You have been charged "
        f"{sp.months_spoken(s['months_charged'])}, "
        f"{sp.rupees_spoken(s['total_charged'])} in total, with the last charge on "
        f"{sp.date_spoken(s['last_charge_on'])}."
    )
    return payload


# ------------------------------------------------------- 3. check_promised_plan


@router.post("/promise-check")
@_handler("check_promised_plan")
def promise_check(ctx: engine.Ctx) -> dict[str, Any]:
    p = q.promise_check(ctx.cur, ctx.merchant["id"])
    promised = p.get("promised_monthly_amount")
    billed = p.get("billed_monthly_amount")

    if promised is None or billed is None or promised == billed:
        return {
            "ok": True,
            "mismatch": False,
            "billed_plan": p.get("billed_plan"),
            "billed_monthly_amount": float(billed) if billed is not None else None,
            "say": (
                f"I have checked your plan. You are on the {p.get('billed_plan')} "
                f"plan at {sp.rupees_spoken(billed)} a month, and that matches what "
                f"is on your account. There is no wrong charge here."
            ) if billed is not None else
            "I have checked and there is no different plan recorded on your account.",
        }

    months = p.get("months_affected") or 0
    per_month = Decimal(str(billed)) - Decimal(str(promised))
    overcharge = per_month * months
    already = p.get("months_already_credited") or 0

    payload = {
        "ok": True,
        "mismatch": True,
        "promised_plan": p["promised_plan"],
        "promised_monthly_amount": float(promised),
        "promised_monthly_amount_text": sp.rupees_text(promised),
        "promised_by": p.get("promised_by"),
        "promised_on": p.get("promised_on"),
        "billed_plan": p["billed_plan"],
        "billed_monthly_amount": float(billed),
        "billed_monthly_amount_text": sp.rupees_text(billed),
        "months_affected": months,
        "months_already_credited": already,
        "overcharge_amount": float(overcharge),
        "overcharge_amount_text": sp.rupees_text(overcharge),
    }
    credited_note = (
        f" {sp.months_spoken(already)} were already covered by a credit note, so "
        f"they are not counted again." if already else ""
    )
    payload["say"] = (
        f"You were promised {sp.rupees_spoken(promised)} a month when you signed "
        f"up in {sp.month_spoken(p.get('promised_on'))}, but you have been billed "
        f"{sp.rupees_spoken(billed)} a month for {sp.months_spoken(months)}. You "
        f"have been overcharged by {sp.rupees_spoken(overcharge)}.{credited_note} "
        f"I cannot release money myself, so I will raise a refund request for a "
        f"colleague to approve."
    )
    return payload


# --------------------------------------------------- 4. stop_billing_and_pickup


@router.post("/closure")
@_handler("stop_billing_and_pickup")
def closure(ctx: engine.Ctx) -> dict[str, Any]:
    cur = ctx.cur
    key, hit = idempotent(ctx, "closure")
    if hit:
        return hit

    gate = engine.verification_gate(ctx, "closure")
    if gate:
        return gate

    device = q.device_for(cur, ctx.merchant["id"])
    if device is None:
        return fail("I cannot see a device on your account to stop billing for. "
                    "Let me connect you to a colleague.", "no device")

    # The backend owns the date. Rahul's point 1: a date the model produces is
    # a date the model can get wrong.
    today = date.today()
    closed_on = ctx.merchant.get("shop_closed_on")
    credit_from = closed_on or today

    q.stop_billing(cur, device["id"], today)

    note = q.existing_credit_note(cur, ctx.case_id)
    if note is None:
        credited = q.credit_post_closure_invoices(cur, ctx.merchant["id"], credit_from)
        if credited["count"]:
            note = q.create_credit_note(
                cur, ctx.case_id, ctx.merchant["id"], credited["total"],
                credited["first"], credited["last"],
                "charges raised after the shop closed",
            )

    ticket = q.existing_ticket(cur, ctx.case_id, "pickup")
    if ticket is None:
        pickup_date = sp.working_days_from(today, config.PICKUP_SLA_DAYS)
        ref = q.next_ref(cur, "pickup_ref_seq", "PU")
        ticket = q.create_ticket(cur, "pickup", ref, ctx.case_id, ctx.merchant["id"],
                                 device["id"], pickup_date,
                                 ctx.merchant.get("address"))

    q.set_case_state(cur, ctx.case_id, "acting", "device_closure",
                     "Shop closed, wants Soundbox taken back and billing stopped")

    payload: dict[str, Any] = {
        "ok": True,
        "ref": ctx.case_ref,
        "billing_stopped_from": today,
        "device_status": "pickup_scheduled",
        "pickup_ref": ticket["ticket_ref"],
        "pickup_date": ticket["scheduled_date"],
        "pickup_address": ticket.get("address"),
    }

    if note:
        payload.update({
            "credit_note_ref": note["note_ref"],
            "credit_note_amount": float(note["amount"]),
            "credit_note_amount_text": sp.rupees_text(note["amount"]),
            "credit_note_period": sp.date_range_text(note["period_start"],
                                                     note["period_end"]),
        })
        payload["say"] = (
            f"I have stopped the billing from today. A credit note of "
            f"{sp.rupees_spoken(note['amount'])} has been raised for the period "
            f"since your shop closed in {sp.month_spoken(closed_on)}. Pickup of "
            f"the {device['device_type']} is booked for "
            f"{sp.date_spoken(ticket['scheduled_date'])}, and I will send you a "
            f"written confirmation with these details."
        )
    else:
        payload["say"] = (
            f"I have stopped the billing from today and booked pickup of the "
            f"{device['device_type']} for "
            f"{sp.date_spoken(ticket['scheduled_date'])}. I will send you a "
            f"written confirmation with these details."
        )

    payload["_idem_key"] = key
    remember(ctx, key, "stop_billing_and_pickup", payload)
    return payload


# ------------------------------------------------------- 5. get_settlement_hold


@router.post("/settlement-hold")
@_handler("get_settlement_hold")
def settlement(ctx: engine.Ctx) -> dict[str, Any]:
    h = q.settlement_hold(ctx.cur, ctx.merchant["id"])
    if not h or h.get("status") != "on_hold":
        return {
            "ok": True,
            "on_hold": False,
            "amount_on_hold": 0,
            "say": "I have checked and none of your settlement money is on hold. "
                   "Your payouts are going through normally.",
        }

    docs = list(h.get("missing_documents") or [])
    # The stored names already read naturally ("PAN card photo"), so prefixing
    # "a photo of your" produced "a photo of your PAN card photo".
    docs_spoken = sp.join_spoken([f"your {d}" for d in docs])
    payload = {
        "ok": True,
        "on_hold": True,
        "amount_on_hold": float(h["amount_on_hold"]),
        "amount_on_hold_text": sp.rupees_text(h["amount_on_hold"]),
        "held_since": h.get("held_since"),
        "reason_plain": h.get("hold_reason_plain"),
        "missing_documents": docs,
        "missing_documents_text": docs_spoken,
        "expected_release_date": h.get("expected_release_date"),
        "upload_url": engine.upload_url(ctx.case_ref),
    }
    q.set_case_state(ctx.cur, ctx.case_id, "acting", "settlement_hold",
                     "Settlement on hold, documents missing")
    # The stored reason is a full sentence, so lowercase its first letter to
    # splice it after "because" without a capital letter mid-sentence.
    reason = (h.get("hold_reason_plain") or "").strip()
    reason = (reason[0].lower() + reason[1:]) if reason else "of a verification check"

    payload["say"] = (
        f"Your settlement of {sp.rupees_spoken(h['amount_on_hold'])} is on hold "
        f"because {reason} Please upload {docs_spoken}. I am sending you a "
        f"message with the upload link. Once both are received, the money is "
        f"released within three working days, which would be "
        f"{sp.date_spoken(h.get('expected_release_date'))}."
    )
    return payload


# ---------------------------------------------------------- 6. device_troubleshoot


@router.post("/device")
@_handler("device_troubleshoot")
def device_troubleshoot(ctx: engine.Ctx) -> dict[str, Any]:
    cur = ctx.cur
    device = q.device_for(cur, ctx.merchant["id"])
    if device is None:
        return fail("I cannot see a device on your account. Let me connect you to "
                    "a colleague.", "no device")

    symptom = (ctx.args.get("symptom") or "unknown").lower()

    # The backend counts the step. Rahul's point 1: the agent must not hold
    # state. Prior successful calls to this tool on this case ARE the step.
    step_index = q.count_tool_calls(cur, ctx.case_id, "device_troubleshoot")
    next_instruction = engine.troubleshoot_step(symptom, step_index)

    q.set_case_state(cur, ctx.case_id, "acting", "device_fault",
                     f"Soundbox problem: {symptom}")

    if next_instruction:
        return {
            "ok": True,
            "resolved": False,
            "next_step": step_index + 1,
            "technician_booked": False,
            "device_last_seen_days": device.get("last_seen_days"),
            "say": next_instruction,
        }

    # Out of steps: book a technician.
    key, hit = idempotent(ctx, "technician")
    if hit:
        return hit

    gate = engine.verification_gate(ctx, "technician")
    if gate:
        return gate

    ticket = q.existing_ticket(cur, ctx.case_id, "technician")
    if ticket is None:
        visit = sp.working_days_from(date.today(), config.TECHNICIAN_SLA_DAYS)
        ref = q.next_ref(cur, "ticket_ref_seq", "TK")
        ticket = q.create_ticket(cur, "technician", ref, ctx.case_id,
                                 ctx.merchant["id"], device["id"], visit,
                                 ctx.merchant.get("address"))
        cur.execute("update devices set status = 'faulty' where id = %s", (device["id"],))

    payload = {
        "ok": True,
        "resolved": False,
        "next_step": None,
        "technician_booked": True,
        "ticket_ref": ticket["ticket_ref"],
        "technician_date": ticket["scheduled_date"],
        "device_status": "faulty",
        "say": (
            f"The {device['device_type']} is not responding, so I have booked a "
            f"technician to visit on {sp.date_spoken(ticket['scheduled_date'])}. "
            f"You will get a confirmation message with the reference number."
        ),
        "_idem_key": key,
    }
    remember(ctx, key, "device_troubleshoot", payload)
    return payload


# ------------------------------------------------------- 7. raise_refund_request


@router.post("/refund-request")
@_handler("raise_refund_request")
def refund_request(ctx: engine.Ctx) -> dict[str, Any]:
    cur = ctx.cur

    # Never two pending refunds for one case. The unique index would refuse it
    # anyway; this returns the existing one politely instead of erroring.
    existing = q.pending_refund(cur, ctx.case_id)
    if existing:
        return {
            "ok": True,
            "request_ref": existing["request_ref"],
            "amount": float(existing["amount"]),
            "amount_text": sp.rupees_text(existing["amount"]),
            "status": "awaiting_approval",
            "already_raised": True,
            "say": (
                f"A refund request for {sp.rupees_spoken(existing['amount'])}, "
                f"reference {existing['request_ref']}, is already with a colleague "
                f"for approval. It has not been forgotten, and you will get a "
                f"message as soon as it is decided."
            ),
        }

    key, hit = idempotent(ctx, "refund")
    if hit:
        return hit

    gate = engine.verification_gate(ctx, "refund")
    if gate:
        return gate

    # The backend computes the amount, excluding months already credited, so a
    # closure credit and a promo refund can never pay for the same month.
    p = q.promise_check(cur, ctx.merchant["id"])
    promised = p.get("promised_monthly_amount")
    billed = p.get("billed_monthly_amount")
    months = p.get("months_affected") or 0

    if promised is not None and billed is not None and promised != billed and months:
        amount = (Decimal(str(billed)) - Decimal(str(promised))) * months
        reason = (f"promised {sp.rupees_text(promised)}/month "
                  f"({p.get('promised_plan')}), billed {sp.rupees_text(billed)}/month "
                  f"for {months} months")
    else:
        asked = ctx.args.get("amount")
        if not asked:
            return fail(
                "I cannot see a wrong charge on your account to refund. Let me "
                "connect you to a colleague who can look into it.",
                "no computable overcharge",
            )
        amount = Decimal(str(asked))
        reason = str(ctx.args.get("reason") or "merchant reported a wrong charge")

    row = q.create_refund_request(cur, ctx.case_id, ctx.merchant["id"], amount, reason)
    q.set_case_state(cur, ctx.case_id, "awaiting_approval", "plan_mismatch",
                     "Billed more than the plan promised at sign-up")

    decision_by = sp.working_days_from(date.today(), config.REFUND_DECISION_SLA_DAYS)
    payload = {
        "ok": True,
        "request_ref": row["request_ref"],
        "amount": float(row["amount"]),
        "amount_text": sp.rupees_text(row["amount"]),
        "status": "awaiting_approval",
        "expected_decision_by": decision_by,
        "say": (
            f"I have raised a refund request for {sp.rupees_spoken(row['amount'])}, "
            f"reference {row['request_ref']}. A colleague has to approve any money "
            f"that goes out, so this will be reviewed by "
            f"{sp.date_spoken(decision_by)} and you will get a message with the "
            f"decision."
        ),
        "_idem_key": key,
    }
    remember(ctx, key, "raise_refund_request", payload)
    return payload


# ---------------------------------------------------------- 8. handover_to_human


@router.post("/handover")
@_handler("handover_to_human", needs_merchant=False)
def handover(ctx: engine.Ctx) -> dict[str, Any]:
    cur = ctx.cur
    key, hit = idempotent(ctx, "handover")
    if hit:
        return hit

    reason = str(ctx.args.get("reason") or "merchant asked for a person")
    transcript = ctx.args.get("transcript")

    summary = engine.build_handover_summary(cur, ctx, reason)
    row = q.create_handover(cur, ctx.case_id, reason, summary, transcript)
    q.set_case_state(cur, ctx.case_id, "handed_over")

    payload = {
        "ok": True,
        "summary_ref": row["summary_ref"],
        "case_ref": ctx.case_ref,
        "say": (
            "I am connecting you to a colleague now. I have passed on everything "
            "we discussed, so you will not have to explain it again."
        ),
        "_idem_key": key,
    }
    remember(ctx, key, "handover_to_human", payload)
    return payload


# ----------------------------------------------------------- 9. send_confirmation


@router.post("/confirmation")
@_handler("send_confirmation")
def send_confirmation(ctx: engine.Ctx) -> dict[str, Any]:
    cur = ctx.cur
    built = engine.build_proof(cur, ctx)
    proof = q.create_proof(cur, ctx.case_id, ctx.merchant["id"], "whatsapp",
                           ctx.merchant.get("phone"), built["subject"],
                           built["body_text"], built["body_html"])

    _, done = engine.summarise_actions(cur, ctx.case_id)
    if "refund_pending" not in done and engine.has_write_actions(done):
        q.set_case_state(cur, ctx.case_id, "resolved")

    hold = q.settlement_hold(cur, ctx.merchant["id"])
    extra = ""
    if hold and hold.get("status") == "on_hold":
        extra = " It also has the link for uploading your documents."

    return {
        "ok": True,
        "proof_ref": proof["proof_ref"],
        "channel": "whatsapp",
        "sent_to": ctx.merchant.get("phone"),
        "say": (
            f"I have sent a written confirmation to your registered mobile number "
            f"with the dates and the reference numbers.{extra}"
        ),
    }


# --------------------------------------------------------------- echo (probe)


@router.post("/echo")
async def echo(request: Request) -> dict[str, Any]:
    """Kept so Rahul can point a Sarvam tool here and verify the seam."""
    body = await body_of(request)
    return {
        "ok": True,
        "say": "This is the Samadhan backend. The webhook reached it and came back.",
        "received_keys": sorted(body.keys()),
    }

"""
Case lifecycle, verification, and the sentences a returning caller hears.

The rule this file exists to enforce: the model never computes anything. It
receives finished sentences. Everything here produces those sentences from rows
that are already in the database.
"""

from __future__ import annotations

import hmac
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any

import config
import queries as q
import speak as sp

# Languages bulbul:v4-flash cannot speak. Rahul's point 6: better to hand over
# before the agent opens its mouth than halfway through a sentence.
TTS_UNSUPPORTED = {"ml-IN", "or-IN"}


@dataclass
class Ctx:
    """Everything a tool handler needs about who is calling and about what."""
    cur: Any
    merchant: dict[str, Any] | None = None
    case: dict[str, Any] | None = None
    session: dict[str, Any] | None = None
    resumed: bool = False
    args: dict[str, Any] = field(default_factory=dict)
    # True when the CARRIER's caller id matches the registered number (or a
    # demo binding for it). That is possession of the SIM, which is a real
    # factor. False when the merchant was found from a number they merely
    # spoke, which proves nothing.
    caller_id_match: bool = False

    @property
    def case_id(self) -> str | None:
        return self.case["id"] if self.case else None

    @property
    def case_ref(self) -> str | None:
        return self.case["case_ref"] if self.case else None

    @property
    def session_id(self) -> str | None:
        return self.session["id"] if self.session else None

    @property
    def merchant_id(self) -> str | None:
        return self.merchant["merchant_id"] if self.merchant and "merchant_id" in self.merchant \
            else (self.merchant["id"] if self.merchant else None)

    def idem_key(self, action: str) -> str:
        """
        Case-scoped, per Rahul's point 1 and convention 6. Built here rather
        than taken from the request, because a key the model composes is a key
        the model can get wrong — and a wrong key books a second pickup.
        """
        return f"{self.case_ref}:{action}"


# ---------------------------------------------------------------- resolution


def open_or_resume(cur, merchant: dict[str, Any] | None, interaction_id: str | None,
                   caller_phone: str | None, language_code: str | None,
                   trusted_caller: bool = False) -> tuple[dict, dict | None, bool]:
    """
    Find the case this call belongs to, creating or resuming as needed.

    Returns (case, call_session, resumed).
    """
    # Fast path: this call is already known, so case and session come back in
    # ONE round trip. At 90 ms per query to Singapore, resolving the caller in
    # six queries would spend a quarter of the 2-second budget before any work.
    if interaction_id:
        row = q.case_and_session(cur, interaction_id)
        if row:
            session = {"id": row.pop("session_id"),
                       "sequence_no": row.pop("session_sequence_no"),
                       "caller_phone": row.pop("session_caller_phone"),
                       "caller_phone_trusted": row.pop("session_caller_trusted")}
            return row, session, (row.get("call_count") or 1) > 1

    merchant_id = merchant["id"] if merchant else None
    resumed = False
    case = None

    if merchant_id:
        case = q.resumable_case(cur, merchant_id, config.CASE_RESUME_WINDOW_DAYS)
        resumed = case is not None

    if case is None:
        lang = language_code or (merchant["language_code"] if merchant else None)
        case = q.create_case(cur, merchant_id, "unknown", lang, caller_phone)

    session = None
    if interaction_id:
        session = q.open_call_session(cur, case["id"], interaction_id, caller_phone,
                                      language_code or case.get("language_code"),
                                      trusted=trusted_caller)
        # open_call_session has already updated call_count on the row; take the
        # value from the session rather than re-reading the case, which would be
        # another 90 ms round trip on the on_start hook before the agent speaks.
        case["call_count"] = session["sequence_no"]

    return case, session, resumed


def resolve(cur, body: dict[str, Any], *, trusted_caller: bool = False) -> Ctx:
    """
    Build a Ctx from whatever the agent sent. Tolerant on purpose: Sarvam may
    send the caller's phone, a spoken registered number, a merchant_id from an
    earlier tool call, or only an interaction id.

    `trusted_caller` is KEYWORD-ONLY and comes from the call site, never from
    the request. An earlier version passed it inside `body`, which meant anyone
    could POST {"_trusted_caller": true} to any tool endpoint and be believed —
    reopening the exact hole it was added to close. Trust cannot travel in the
    same channel as the data it is meant to vouch for.
    """
    # Underscore-prefixed keys are internal by convention, so a request is not
    # allowed to supply any.
    body = {k: v for k, v in body.items() if not str(k).startswith("_")}

    merchant = None
    if body.get("merchant_id"):
        merchant = q.find_merchant(cur, merchant_id=body["merchant_id"])
    if merchant is None and body.get("registered_phone"):
        merchant = q.find_merchant(cur, phone=body["registered_phone"])
    if merchant is None and body.get("phone"):
        merchant = q.find_merchant(cur, phone=body["phone"])
    if merchant is None and body.get("merchant_code"):
        merchant = q.find_merchant(cur, merchant_code=body["merchant_code"])

    interaction_id = body.get("interaction_id")

    # A tool call can arrive before call_started (hook not registered, or the
    # browser fallback). Create the session lazily so nothing depends on order.
    if merchant is None and interaction_id:
        known = q.case_by_interaction(cur, interaction_id)
        if known and known.get("merchant_id"):
            merchant = q.find_merchant(cur, merchant_id=known["merchant_id"])

    case, session, resumed = open_or_resume(
        cur, merchant, interaction_id,
        q.normalise_phone(body.get("phone")),
        body.get("language_code"),
        trusted_caller=trusted_caller,
    )

    # The caller-id factor comes ONLY from the number the call_started hook
    # recorded, never from this request's arguments.
    #
    # `phone` arrives as a tool argument, so it is model-influenced: talk the
    # agent into putting a different number there and it would have granted
    # full account access and writes. The lifecycle hook runs without the LLM,
    # so what it recorded is the platform's own value.
    caller_id_match = False
    trusted_caller_phone = (session or {}).get("caller_phone") \
        if (session or {}).get("caller_phone_trusted") else None

    if merchant and trusted_caller_phone:
        if trusted_caller_phone == merchant.get("phone"):
            caller_id_match = True
        else:
            # A demo binding is a deliberate operator statement that this
            # handset belongs to this merchant, so it counts as caller id.
            cur.execute(
                "select 1 from phone_bindings where phone = %s and merchant_id = %s",
                (trusted_caller_phone, merchant["id"]),
            )
            caller_id_match = cur.fetchone() is not None

    # If the case was opened before we knew the merchant, attach them now.
    if merchant and case and not case.get("merchant_id"):
        cur.execute("update cases set merchant_id = %s, updated_at = now() where id = %s",
                    (merchant["id"], case["id"]))
        case["merchant_id"] = merchant["id"]

    return Ctx(cur=cur, merchant=merchant, case=case, session=session,
               resumed=resumed, args=body, caller_id_match=caller_id_match)


# -------------------------------------------------------------- verification


def verify_question(merchant: dict[str, Any]) -> str:
    """
    The question only ever gets asked when the caller id did NOT match, so it
    must ask for something the agent has never said.

    It used to ask for the shop name — which `get_merchant_context` had just
    read out loud. That check was defeated by the sentence before it. The
    device serial is printed on the Soundbox itself, so answering it needs
    physical possession, and we never speak it.
    """
    return ("Please read me the serial number printed on the back of your "
            "Soundbox. It starts with the letters S B.")


def answer_matches(merchant_or_device: dict[str, Any], answer: str | None) -> bool:
    """
    The backend compares, not the model. A `verified: true` flag from the model
    is the model asserting it checked, which is not a check.

    Compares against the device serial. Tolerant of how a serial survives
    speech recognition: "SB 77301", "sb-77301", "seven seven three zero one"
    all reduce to the same digits.
    """
    serial = (merchant_or_device or {}).get("device_serial") or \
        (merchant_or_device or {}).get("serial") or ""
    if not answer or not serial:
        return False

    # A merchant reading a serial aloud produces "seven seven three zero one"
    # as often as "77301", and Saaras transcribes whichever it hears. Both must
    # work, or the check fails honest callers.
    WORDS = {
        "zero": "0", "oh": "0", "o": "0", "nought": "0",
        "one": "1", "two": "2", "three": "3", "four": "4", "five": "5",
        "six": "6", "seven": "7", "eight": "8", "nine": "9",
        "double": "", "triple": "",
    }

    def digits(text: str) -> str:
        lowered = str(text).lower()
        parts: list[str] = []
        for token in re.findall(r"[a-z]+|\d+", lowered):
            if token.isdigit():
                parts.append(token)
            elif token in WORDS:
                parts.append(WORDS[token])
        return "".join(parts)

    want = digits(serial)
    if not want:
        return False

    # EXACT match, never "contains". A substring test would let a caller recite
    # one long digit string that happens to contain the serial and walk
    # straight through the check.
    #
    # ONE candidate per attempt, or the attempt limit is meaningless: an answer
    # of "11111 22222 33333 ... 77301" would otherwise be hundreds of guesses
    # counted as one, and a five-digit serial is only 100,000 possibilities.
    #
    # Honest readings still work:
    #   "SB-77301"                      -> one run, 77301
    #   "SB 77301, shop 14"             -> one serial-length run, 77301
    #   "seven seven three zero one"    -> no runs, falls back to joined digits
    #   "SB 7 7 3 0 1"                  -> no long runs, joined digits
    # A caller reciting several serial-length numbers is refused outright.
    runs = [r for r in re.findall(r"\d+", str(answer)) if len(r) >= 4]
    if len(runs) > 1:
        return False
    candidate = runs[0] if runs else digits(answer)
    return bool(candidate) and hmac.compare_digest(candidate, want)


def verification_gate(ctx: Ctx, action: str) -> dict[str, Any] | None:
    """
    Returns a failure payload if this write may not proceed, else None.

    Two ways to be verified:
      1. The carrier's caller id matches the registered number. That is
         possession of the SIM and is accepted on its own, which is how a bank
         treats an inbound call from a registered mobile.
      2. Otherwise — the merchant was found from a number they spoke, which
         proves nothing — they must read the device serial off the Soundbox.

    Switchable via REQUIRE_VERIFICATION if the live demo runs short on time.
    """
    if not config.REQUIRE_VERIFICATION:
        return None

    # Fail closed without a call session. Attempts are counted against the
    # case, but a write with no session at all has nothing to audit the
    # verification against, so it does not get to change anything.
    if not ctx.session_id:
        return {
            "ok": False,
            "reason": "no call session to verify against",
            "say": (
                "I cannot make that change on this connection. Let me connect "
                "you to a colleague who can help."
            ),
        }

    verified, failures = verification_state(ctx)

    if ctx.caller_id_match:
        if not verified:
            record_verified(ctx, "caller id matches the registered number")
        return None

    if verified:
        return None

    # A serial is five digits, so without a limit it is guessable across
    # retries. Three tries, then a person takes over.
    if failures >= config.VERIFY_MAX_ATTEMPTS:
        return {
            "ok": False,
            "reason": "verification attempts exhausted",
            "handover_required": True,
            "say": (
                "I am not able to confirm who you are, so I cannot make changes "
                "to this account. I am connecting you to a colleague who can "
                "help you safely."
            ),
        }

    answer = ctx.args.get("verify_answer") or ctx.args.get("verification_answer")
    device = q.device_for(ctx.cur, ctx.merchant["id"]) if ctx.merchant else None

    if answer and answer_matches(device or {}, answer):
        record_verified(ctx, "device serial read back by the caller")
        return None

    if answer:
        # Record the failure, so attempts are counted and auditable. The answer
        # itself is NOT stored: it is a credential, and the audit log is read
        # by the support team.
        q.log_event(ctx.cur, ctx.case_id, ctx.session_id, "verification_failed",
                    {"attempt": failures + 1,
                     "limit": config.VERIFY_MAX_ATTEMPTS},
                    {"matched": False}, None, False, None, None, actor="system")
        failures += 1

    tries_left = config.VERIFY_MAX_ATTEMPTS - failures
    prefix = ("That serial number does not match our records. "
              if answer else
              "You are not calling from the number registered to this account, "
              "so before I change anything I need to check who you are. ")

    return {
        "ok": False,
        "reason": "identity not verified",
        "attempts_remaining": tries_left,
        "verify_question_text": verify_question(ctx.merchant),
        "say": prefix + verify_question(ctx.merchant),
    }


def failed_attempts(ctx: Ctx) -> int:
    """
    Failed verification answers on this CASE in the last hour, counted since
    the most recent successful verification.

    Deliberately not per call session: a caller who simply sent a new
    interaction id would otherwise reset the counter and guess forever. Counting
    since the last success means an honest merchant who verified earlier is not
    punished for someone else's failed guesses.
    """
    if not ctx.case_id:
        return 0
    ctx.cur.execute(
        """
        select count(*) as n
          from case_events
         where case_id = %s
           and tool_name = 'verification_failed'
           and at > now() - interval '1 hour'
           and id > coalesce((
                 select max(id) from case_events
                  where case_id = %s and tool_name = 'identity_verified'
               ), 0)
        """,
        (ctx.case_id, ctx.case_id),
    )
    return ctx.cur.fetchone()["n"]


def verification_state(ctx: Ctx) -> tuple[bool, int]:
    """
    (already_verified, failed_attempts) in ONE round trip.

    These were two queries plus a third inside record_verified. At ~110 ms per
    round trip to Singapore, the gate alone cost a third of a second on every
    write before doing anything.
    """
    if not ctx.case_id:
        return False, 0
    ctx.cur.execute(
        """
        select
            exists(
                select 1 from case_events
                 where case_id = %s and call_session_id = %s
                   and tool_name = 'identity_verified'
            ) as verified,
            (select count(*) from case_events
              where case_id = %s
                and tool_name = 'verification_failed'
                and at > now() - interval '1 hour'
                and id > coalesce((
                      select max(id) from case_events
                       where case_id = %s and tool_name = 'identity_verified'
                    ), 0)
            ) as failures
        """,
        (ctx.case_id, ctx.session_id, ctx.case_id, ctx.case_id),
    )
    row = ctx.cur.fetchone()
    return bool(row["verified"]), int(row["failures"])


def already_verified(ctx: Ctx) -> bool:
    """
    Per CALL, not per case.

    Scoping this to the case was a privilege-inheritance bug: a case stays open
    across callbacks, so someone who merely knows the merchant's number could
    ring in, have that case resumed, and inherit the verification the real
    merchant earned on an earlier call. A bank re-checks on every call, and so
    do we. With caller id matching, re-checking costs the honest caller nothing.
    """
    if not ctx.session_id:
        return False
    ctx.cur.execute(
        """
        select 1 from case_events
         where case_id = %s
           and call_session_id = %s
           and tool_name = 'identity_verified'
         limit 1
        """,
        (ctx.case_id, ctx.session_id),
    )
    return ctx.cur.fetchone() is not None


def record_verified(ctx: Ctx, how: str) -> None:
    """
    Audited, so the dashboard can show WHY a write was allowed.

    The caller has already established that this call is not yet verified, so
    there is no re-check here: that was a third round trip for nothing.
    """
    q.log_event(ctx.cur, ctx.case_id, ctx.session_id, "identity_verified",
                {"factor": how}, {"matched": True}, None, True, None, None,
                actor="system")


def is_verified(ctx: Ctx) -> bool:
    """
    Whether this caller may be told account details at all.

    Used to decide what goes into a payload, not just what writes are allowed:
    reading the shop name out to an unverified caller would hand them the
    answer to any question about the shop name.
    """
    if not config.REQUIRE_VERIFICATION:
        return True
    if ctx.caller_id_match:
        return True
    verified, _ = verification_state(ctx)
    return verified


# --------------------------------------------- what has already been done


def summarise_actions(cur, case_id: str) -> tuple[str | None, list[str]]:
    """
    The sentence a returning caller hears instead of being asked to explain
    again. Built from rows, so it cannot drift from what actually happened.

    Returns (spoken_text, machine_readable_list).
    """
    done: list[str] = []
    spoken: list[str] = []

    # One round trip for all six facts. This is called on every merchant-context
    # read, so six separate queries here was 540 ms of pure network.
    row = q.action_summary_row(cur, case_id) or {}

    # These are VERB phrases, because they get read after "I had already ..."
    # — "I had already billing stopped" is not a sentence a person would say,
    # and the agent is judged on sounding like a colleague.
    if row.get("billing_stopped_from"):
        done.append("billing_stopped")
        spoken.append(f"stopped the billing from {sp.date_spoken(row['billing_stopped_from'])}")

    if row.get("credit_amount") is not None:
        done.append("credit_note")
        spoken.append(f"raised a credit note of {sp.rupees_spoken(row['credit_amount'])}")

    if row.get("pickup_date"):
        done.append("pickup_booked")
        spoken.append(f"booked the Soundbox pickup for {sp.date_spoken(row['pickup_date'])}")

    if row.get("technician_date"):
        done.append("technician_booked")
        spoken.append(f"booked a technician visit for {sp.date_spoken(row['technician_date'])}")

    if row.get("refund_amount") is not None:
        done.append("refund_pending")
        spoken.append(
            f"raised a refund request for {sp.rupees_spoken(row['refund_amount'])}, "
            f"reference {row['refund_ref']}"
        )

    if (row.get("proof_count") or 0) > 0:
        done.append("proof_sent")
        spoken.append("sent you a written confirmation")

    return (sp.join_spoken(spoken) if spoken else None), done


def remaining_steps(done: list[str]) -> str | None:
    """What is still owed on this case, spoken."""
    if "billing_stopped" in done and "proof_sent" not in done:
        return "I still need to send you the written confirmation"
    if "refund_pending" in done:
        return "the refund is still waiting for a colleague to approve"
    return None


def has_write_actions(done: list[str]) -> bool:
    return any(a in done for a in
               ("billing_stopped", "credit_note", "pickup_booked",
                "technician_booked", "refund_pending"))


# ------------------------------------------------------- device troubleshooting

TROUBLESHOOT_STEPS: dict[str, list[str]] = {
    "no_sound": [
        "Let us try one thing. Please turn the volume dial on the side of the "
        "Soundbox all the way up, then tell me if you hear a beep.",
        "Now press and hold the power button for ten seconds until the light "
        "comes on, then tell me what you see.",
    ],
    "not_powering_on": [
        "Please connect the charger and wait for one minute, then tell me "
        "whether any light comes on.",
        "Try a different socket and a different charging cable if you have one, "
        "then tell me what happens.",
    ],
    "no_network": [
        "Please move the Soundbox near the shop entrance where the mobile "
        "signal is better, then tell me if the light turns green.",
        "Now switch it off, wait ten seconds, switch it on again, and tell me "
        "what the light does.",
    ],
    "not_announcing_payments": [
        "Please ask someone to send you one rupee and tell me whether the "
        "Soundbox speaks when the money arrives.",
        "Please turn the volume dial all the way up and try one more payment.",
    ],
    "unknown": [
        "Please switch the Soundbox off, wait ten seconds, switch it on again, "
        "and tell me what you see or hear.",
    ],
}


def troubleshoot_step(symptom: str | None, step_index: int) -> str | None:
    steps = TROUBLESHOOT_STEPS.get((symptom or "unknown").lower(),
                                   TROUBLESHOOT_STEPS["unknown"])
    if step_index < len(steps):
        return steps[step_index]
    return None


# -------------------------------------------------------------------- proof


def upload_url(case_ref: str) -> str:
    """
    Rahul's point 4. Our own demo page, deliberately not a fabricated
    paytm.com link: inventing a real-looking Paytm URL is the sort of detail a
    judge notices, and it would be misleading.
    """
    return f"{config.DASHBOARD_URL.rstrip('/')}/upload/{case_ref}"


def build_proof(cur, ctx: Ctx) -> dict[str, str]:
    """
    The written confirmation, assembled from the case's own rows. It cannot
    disagree with what was done, because it is built from what was done.
    """
    m = ctx.merchant or {}
    lines: list[str] = []
    html: list[str] = []

    cur.execute(
        """
        select d.billing_stopped_from, d.serial, d.device_type
          from devices d where d.merchant_id = %s
        """,
        (ctx.merchant_id,),
    )
    device = cur.fetchone() or {}

    if device.get("billing_stopped_from"):
        lines.append(f"Billing stopped from {sp.date_range_text(device['billing_stopped_from'], None).split(' to ')[0]}.")
        html.append(f"<li>Billing stopped from <b>{device['billing_stopped_from']}</b></li>")

    note = q.existing_credit_note(cur, ctx.case_id)
    if note:
        period = sp.date_range_text(note["period_start"], note["period_end"])
        lines.append(f"Credit note {note['note_ref']} for {sp.rupees_text(note['amount'])} "
                     f"covering {period}.")
        html.append(f"<li>Credit note <b>{note['note_ref']}</b> for "
                    f"<b>{sp.rupees_text(note['amount'])}</b> covering {period}</li>")

    for kind, label in (("pickup", "Soundbox pickup"), ("technician", "Technician visit")):
        ticket = q.existing_ticket(cur, ctx.case_id, kind)
        if ticket:
            lines.append(f"{label} booked for {ticket['scheduled_date']}, "
                         f"reference {ticket['ticket_ref']}.")
            html.append(f"<li>{label} booked for <b>{ticket['scheduled_date']}</b>, "
                        f"reference <b>{ticket['ticket_ref']}</b></li>")

    refund = q.pending_refund(cur, ctx.case_id)
    if refund:
        lines.append(f"Refund request {refund['request_ref']} for "
                     f"{sp.rupees_text(refund['amount'])} is awaiting approval by a "
                     f"Paytm team member. No money has been paid out yet.")
        html.append(f"<li>Refund request <b>{refund['request_ref']}</b> for "
                    f"<b>{sp.rupees_text(refund['amount'])}</b> — <i>awaiting human "
                    f"approval, not yet paid</i></li>")

    hold = q.settlement_hold(cur, ctx.merchant_id)
    if hold and hold.get("status") == "on_hold":
        docs = ", ".join(hold.get("missing_documents") or [])
        lines.append(f"Settlement of {sp.rupees_text(hold['amount_on_hold'])} is on hold. "
                     f"Please upload: {docs}. Upload here: {upload_url(ctx.case_ref)}")
        html.append(f"<li>Settlement of <b>{sp.rupees_text(hold['amount_on_hold'])}</b> "
                    f"on hold — please upload {docs}: "
                    f"<a href=\"{upload_url(ctx.case_ref)}\">upload documents</a></li>")

    if not lines:
        lines.append("We discussed your issue and no changes were needed.")
        html.append("<li>No changes were required</li>")

    subject = f"Samadhan {ctx.case_ref}: what we did on your call"
    body_text = (
        f"Dear {m.get('owner_name', 'Merchant')},\n\n"
        f"This confirms what was done on your call about {m.get('shop_name', 'your shop')}.\n\n"
        + "\n".join(f"- {line}" for line in lines)
        + f"\n\nReference: {ctx.case_ref}\n"
        f"If anything here is wrong, call us back and quote {ctx.case_ref}.\n"
    )
    body_html = (
        f"<h2>Samadhan — {ctx.case_ref}</h2>"
        f"<p>Dear {m.get('owner_name', 'Merchant')}, this confirms what was done on "
        f"your call about <b>{m.get('shop_name', 'your shop')}</b>.</p>"
        f"<ul>{''.join(html)}</ul>"
        f"<p>Reference <b>{ctx.case_ref}</b>. If anything here is wrong, call us back "
        f"and quote this reference.</p>"
    )
    return {"subject": subject, "body_text": body_text, "body_html": body_html}


def build_handover_summary(cur, ctx: Ctx, reason: str) -> str:
    """What the human sees, so the merchant does not explain it a third time."""
    m = ctx.merchant or {}
    spoken, done = summarise_actions(cur, ctx.case_id)
    calls = q.previous_calls(cur, ctx.case_id, None)
    events = q.events_for_case(cur, ctx.case_id)

    parts = [
        f"# Handover — {ctx.case_ref}",
        "",
        f"**Merchant:** {m.get('shop_name')} ({m.get('merchant_code')}), "
        f"{m.get('owner_name')}, {m.get('city')}",
        f"**Phone:** {m.get('phone')}  ·  **Language:** {m.get('language_code')}",
        f"**Shop status:** {m.get('shop_status')}"
        + (f", closed {m.get('shop_closed_on')}" if m.get("shop_closed_on") else ""),
        f"**Calls on this case:** {len(calls)}",
        "",
        f"## Why this reached a person",
        reason,
        "",
        "## Already done by Samadhan",
        ("- " + spoken.replace(", ", "\n- ")) if spoken else "- nothing yet",
        "",
        "## What is still open",
        remaining_steps(done) or "nothing outstanding",
        "",
        "## Tool calls on this case",
    ]
    for e in events:
        if e["tool_name"] and e["tool_name"] != "identity_verified":
            status = "ok" if e["ok"] else "FAILED"
            parts.append(f"- `{e['tool_name']}` {status} at {e['at']:%H:%M:%S}")
    return "\n".join(parts)

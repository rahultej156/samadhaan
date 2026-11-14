"""
Inspect what the voice agent actually did, after a real phone call.

    py scripts/check_integration.py              # the most recent call
    py scripts/check_integration.py --case SMD-1042
    py scripts/check_integration.py --calls 3    # last three calls

Reads only the audit log, so it reports what HAPPENED, not what anyone
intended. Every integration point Track A had to get right shows up here as
a row or an absence.

Use it after Rahul's first real call: it tells you in ten seconds whether the
hooks are registered, whether caller id is trusted, which tools the agent
reached for, what the merchant was actually told, and where the time went.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

import config  # noqa: E402

try:
    import psycopg
    from psycopg.rows import dict_row
except ImportError:
    sys.exit(
        "This one needs the database driver, so run it with the venv's python:\n\n"
        "    .venv\\Scripts\\python.exe scripts/check_integration.py\n\n"
        "(run_scenario.py works with plain `py`; this does not, because psycopg "
        "is not in the system interpreter.)"
    )

OK, BAD, MEH = "PASS", "FAIL", "----"

# The nine callable tools plus the two hooks. Anything else is unexpected.
KNOWN = {
    "call_started", "call_ended", "get_merchant_context", "get_billing_summary",
    "check_promised_plan", "stop_billing_and_pickup", "get_settlement_hold",
    "device_troubleshoot", "raise_refund_request", "handover_to_human",
    "send_confirmation", "identity_verified", "verification_failed",
    "refund_approved", "refund_rejected", "call_summary",
}


def line(status: str, label: str, detail: str = "") -> None:
    print(f"  [{status}] {label}" + (f"  —  {detail}" if detail else ""))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--case", help="case reference, e.g. SMD-1042")
    ap.add_argument("--calls", type=int, default=1, help="how many recent calls")
    ap.add_argument("--transcript", action="store_true",
                    help="print the stored conversation, turn by turn")
    args = ap.parse_args()

    conn = psycopg.connect(config.DATABASE_URL, autocommit=True,
                           prepare_threshold=None, row_factory=dict_row,
                           connect_timeout=20)
    cur = conn.cursor()

    if args.case:
        cur.execute(
            """
            select s.*, c.case_ref, c.state, c.issue_type, m.shop_name, m.phone
              from call_sessions s
              join cases c on c.id = s.case_id
              left join merchants m on m.id = c.merchant_id
             where c.case_ref = %s
             order by s.sequence_no desc
            """,
            (args.case,),
        )
    else:
        cur.execute(
            """
            select s.*, c.case_ref, c.state, c.issue_type, m.shop_name, m.phone
              from call_sessions s
              join cases c on c.id = s.case_id
              left join merchants m on m.id = c.merchant_id
             order by s.started_at desc
             limit %s
            """,
            (args.calls,),
        )

    sessions = cur.fetchall()
    if not sessions:
        print("No call sessions at all. Either no call has reached the backend "
              "yet, or the database was reset since.")
        print("If Rahul says he placed a call, that is the finding: nothing "
              "arrived. Check the tunnel URL and the X-Samadhan-Key header.")
        sys.exit(1)

    for s in reversed(sessions):
        print("=" * 76)
        print(f"CALL  {s['case_ref']} #{s['sequence_no']}   "
              f"{s['shop_name'] or '(no merchant resolved)'}")
        print(f"      interaction_id {s['interaction_id']}")
        print(f"      started {s['started_at']:%H:%M:%S}  "
              f"caller {s['caller_phone'] or '(none sent)'}  "
              f"lang {s['language_code'] or '(none sent)'}")
        print("=" * 76)

        cur.execute(
            """
            select tool_name, actor, ok, latency_ms, say, args, result, at
              from case_events
             where call_session_id = %s
             order by id
            """,
            (s["id"],),
        )
        events = cur.fetchall()
        names = [e["tool_name"] for e in events]

        # ---------------------------------------------------- integration points
        print("\nINTEGRATION POINTS")

        if "call_started" in names:
            line(OK, "call_started fired", "registered as on_start")
        else:
            line(BAD, "call_started never fired",
                 "not registered as on_start — caller id cannot be trusted, so "
                 "every merchant will be asked for their Soundbox serial")

        if s["caller_phone_trusted"] and s["caller_phone"]:
            line(OK, "caller id is trusted", "the hook supplied the number")
        elif "call_started" in names and not s["caller_phone"]:
            sent = next((e for e in events if e["tool_name"] == "call_started"), None)
            raw = (sent["args"] or {}).get("phone") if sent else None
            line(BAD, "the hook sent no usable phone number",
                 f"@User Identifier came through as {raw!r}")
            for hint in (
                "On the browser test widget @User Identifier is the Sarvam",
                "account's email, not a caller id. Either call the agent's",
                "phone number from a real handset, or answer the Soundbox",
                "serial question.",
            ):
                print(f"         {hint}")
        else:
            line(BAD, "caller id NOT trusted",
                 "number arrived as a tool argument, not from the on_start hook")

        verified = [e for e in events if e["tool_name"] == "identity_verified"]
        if verified:
            factor = (verified[0]["args"] or {}).get("factor", "?")
            line(OK, "identity verified", factor)
        else:
            failed = [e for e in events if e["tool_name"] == "verification_failed"]
            if failed:
                line(MEH, f"{len(failed)} failed verification attempt(s)",
                     "merchant could not confirm the serial")
            else:
                line(MEH, "no write action attempted on this call",
                     "nothing needed verifying")

        tool_calls = [e for e in events if e["actor"] == "agent"]
        if tool_calls:
            if tool_calls[0]["tool_name"] == "get_merchant_context":
                line(OK, "get_merchant_context was called first")
            else:
                line(BAD, "first tool was not get_merchant_context",
                     f"it was {tool_calls[0]['tool_name']}")
        else:
            line(BAD, "the agent called no tools at all",
                 "the hooks fired but the LLM never used a tool")

        if s["ended_at"]:
            flag = OK if s["end_reason"] else MEH
            line(flag, f"call_ended fired  ({s['end_reason']})",
                 f"{s['duration_s']}s" if s["duration_s"] else "")
        else:
            line(BAD, "call_ended never fired",
                 "not registered as on_end — a dropped call will not get its "
                 "written confirmation")

        if s["ended_mid_action"]:
            line(MEH, "call ended mid-action",
                 "the on_end hook sent the confirmation to repair it")

        # The transcript is the one thing only Sarvam knows, so its absence is
        # a wiring fact: call_ended fired but carried no interaction_transcript.
        cur.execute(
            """
            select count(*) as n,
                   count(*) filter (where text_original is distinct from text_english)
                       as native
              from conversation_turns where call_session_id = %s
            """,
            (s["id"],),
        )
        t = cur.fetchone()
        stored = s["turn_count"] or 0
        if t["n"]:
            detail = f"{t['n']} turn" + ("s" if t["n"] != 1 else "")
            if t["native"]:
                detail += f", {t['native']} with native script"
            if stored != t["n"]:
                detail += f"  (turn_count says {stored} — mismatch)"
            line(OK, "transcript saved", detail)
        elif s["ended_at"]:
            line(BAD, "no transcript saved",
                 "call_ended fired without an interaction_transcript in the body")
        else:
            line(MEH, "no transcript yet", "the call has not ended")

        unexpected = sorted(set(names) - KNOWN - {None})
        if unexpected:
            line(BAD, "unexpected tool names", ", ".join(unexpected))

        failures = [e for e in events if e["ok"] is False]
        if failures:
            line(MEH, f"{len(failures)} tool call(s) returned ok:false",
                 ", ".join(sorted({e['tool_name'] for e in failures})))

        # ----------------------------------------------------------- timeline
        print("\nWHAT THE AGENT DID, IN ORDER")
        for e in events:
            mark = " " if e["ok"] is not False else "!"
            lat = f"{e['latency_ms']:>5} ms" if e["latency_ms"] else "        "
            who = "" if e["actor"] == "agent" else f"  ({e['actor']})"
            print(f"  {mark} {e['at']:%H:%M:%S}  {lat}  {e['tool_name']}{who}")
            if e["say"]:
                print(f"            SAID: {e['say']}")

        # --------------------------------------------------------- transcript
        if args.transcript:
            cur.execute(
                """
                select role, text_original, text_english
                  from conversation_turns where call_session_id = %s order by id
                """,
                (s["id"],),
            )
            turns = cur.fetchall()
            if turns:
                print()
                print("THE CONVERSATION")
                for t in turns:
                    who = "merchant" if t["role"] == "merchant" else "Samadhan"
                    print(f"  {who:>9}: {t['text_english'] or t['text_original']}")
                    # Only worth a second line when the two actually differ.
                    if t["text_original"] and t["text_original"] != t["text_english"]:
                        print(f"             ({t['text_original']})")

        # ------------------------------------------------------------ latency
        lats = [e["latency_ms"] for e in events if e["latency_ms"]]
        if lats:
            lats.sort()
            print(f"\nLATENCY  {len(lats)} calls   "
                  f"p50 {lats[len(lats)//2]} ms   max {lats[-1]} ms")
            slow = [e for e in events if (e["latency_ms"] or 0) > 2000]
            for e in slow:
                print(f"  slow: {e['tool_name']} took {e['latency_ms']} ms")

        print()

    # ------------------------------------------------------ case-level summary
    case_ref = sessions[0]["case_ref"]
    cur.execute("select id, state from cases where case_ref = %s", (case_ref,))
    case = cur.fetchone()
    print("=" * 76)
    print(f"CASE {case_ref} is now '{case['state']}'")
    print("=" * 76)

    for label, sql in [
        ("credit notes", "select note_ref, amount from credit_notes where case_id = %s"),
        ("tickets", "select ticket_ref, kind, scheduled_date, status from service_tickets where case_id = %s"),
        ("refunds", "select request_ref, amount, status, decided_by from refund_requests where case_id = %s"),
        ("proofs", "select proof_ref, channel, sent_to, sent_at from proofs where case_id = %s"),
        ("handovers", "select summary_ref, reason from handovers where case_id = %s"),
    ]:
        cur.execute(sql, (case["id"],))
        rows = cur.fetchall()
        if rows:
            print(f"  {label}:")
            for r in rows:
                print("    ", "  ".join(f"{k}={v}" for k, v in r.items()))

    conn.close()


if __name__ == "__main__":
    main()

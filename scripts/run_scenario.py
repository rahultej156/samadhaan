"""
Drive the four demo scenarios over HTTP. No voice, no LLM, no Sarvam.

    py scripts/run_scenario.py                  # all four, against localhost
    py scripts/run_scenario.py --only m1
    py scripts/run_scenario.py --base https://samadhan.ngrok.app

This is Track B's Gate 1 proof: if these pass, the backend is correct and any
remaining problem is in the voice layer. It also means Track B is never blocked
waiting on Track A.

Every scenario resets the data first, so runs are repeatable.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

import config  # noqa: E402

BASE = "http://127.0.0.1:8000"
FAILURES: list[str] = []
LATENCIES: list[tuple[str, float]] = []


def call(path: str, payload: dict | None = None, method: str = "POST") -> tuple[int, dict, float]:
    url = BASE.rstrip("/") + path
    data = json.dumps(payload or {}).encode() if method == "POST" else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Content-Type": "application/json",
        "X-Samadhan-Key": config.SAMADHAN_API_KEY,
    })
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            status = resp.status
    except urllib.error.HTTPError as exc:
        body = {"_http_error": exc.read().decode("utf-8", "replace")[:300]}
        status = exc.code
    except Exception as exc:
        body = {"_error": f"{type(exc).__name__}: {exc}"}
        status = 0
    elapsed = (time.perf_counter() - started) * 1000
    LATENCIES.append((path, elapsed))
    return status, body, elapsed


def step(label: str, path: str, payload: dict) -> dict:
    status, body, ms = call(path, payload)
    say = body.get("say")
    # ok:false is often the CORRECT answer (refused write, unknown caller), so
    # this marks what the backend returned, not whether the test passed. Only
    # the EXPECT lines and the final tally say that.
    flag = "ok=T" if body.get("ok") else "ok=F"
    print(f"\n  [{flag}] {label}   ({ms:.0f} ms, HTTP {status})")
    if say:
        print(f"         SAY: {say}")
    elif "_error" in body or "_http_error" in body:
        print(f"         ERR: {body.get('_error') or body.get('_http_error')}")

    # The contract's rule 3: a tool never returns a non-200, and always carries
    # a `say`. The two lifecycle hooks are the documented exception — they run
    # without the LLM and speak nothing, so there is nothing for them to say.
    if status != 200:
        FAILURES.append(f"{label}: HTTP {status}, must always be 200")
    if not say and path not in ("/tools/call-started", "/tools/call-ended"):
        FAILURES.append(f"{label}: no `say` in response")
    return body


def expect(label: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"         EXPECT ok   {label}")
    else:
        print(f"         EXPECT FAIL {label}  {detail}")
        FAILURES.append(f"{label} {detail}")


def reset() -> None:
    status, body, _ = call("/admin/reset")
    if status != 200:
        sys.exit(f"reset failed (HTTP {status}): {body}")
    print(f"data reset: {', '.join(m['merchant_code'] for m in body['merchants'])}")


# ===================================================================== M1


def scenario_m1() -> None:
    print("\n" + "=" * 74)
    print('M1  CLOSURE — "My shop has closed. Please take the Soundbox back."')
    print("=" * 74)
    phone, call_id = "+919000000001", "test-m1-call-1"

    step("call_started (on_start hook)", "/tools/call-started",
         {"phone": phone, "interaction_id": call_id, "language_code": "te-IN"})

    ctx = step("get_merchant_context", "/tools/merchant-context",
               {"phone": phone, "interaction_id": call_id,
                "transcript": "My shop has closed. Please take the Soundbox back."})
    expect("finds the merchant", ctx.get("found") is True)
    expect("shop is closed", ctx.get("shop_status") == "closed")
    expect("8 months charged after closure",
           ctx.get("months_charged_after_closure") == 8,
           f"got {ctx.get('months_charged_after_closure')}")
    expect("Rs 1000 charged after closure",
           ctx.get("amount_charged_after_closure") == 1000.0,
           f"got {ctx.get('amount_charged_after_closure')}")
    expect("plan_mismatch is FALSE (no double refund path)",
           ctx.get("plan_mismatch") is False,
           f"got {ctx.get('plan_mismatch')}")
    expect("not a returning caller", ctx.get("returning_caller") is False)
    case_ref = ctx.get("case_ref")

    # Calling FROM the registered number is possession of the SIM, so writes
    # proceed without an extra question. The spoken-number path is covered in
    # the edge cases, where the caller must read the device serial.
    expect("verified by caller id", ctx.get("verified_by") == "caller id",
           f"got {ctx.get('verified_by')}")

    closure = step("stop_billing_and_pickup", "/tools/closure",
                   {"phone": phone, "interaction_id": call_id})
    expect("billing stopped", bool(closure.get("billing_stopped_from")))
    expect("credit note Rs 1000", closure.get("credit_note_amount") == 1000.0,
           f"got {closure.get('credit_note_amount')}")
    expect("pickup booked", bool(closure.get("pickup_ref")))

    # Idempotency: the same action again must NOT book a second pickup.
    again = step("closure AGAIN (idempotency)", "/tools/closure",
                 {"phone": phone, "interaction_id": call_id})
    expect("same pickup ref returned",
           again.get("pickup_ref") == closure.get("pickup_ref"),
           f"{again.get('pickup_ref')} vs {closure.get('pickup_ref')}")
    expect("same credit note ref",
           again.get("credit_note_ref") == closure.get("credit_note_ref"))

    # ---- the callback beat ----
    # The call drops HERE, after the action but BEFORE the merchant was told
    # anything in writing. That is the realistic failure, and it is the whole
    # reason the on_end hook exists. Calling send_confirmation first would
    # resolve the case, and a resolved case is deliberately acknowledged rather
    # than resumed.
    print("\n  --- caller hangs up mid-call, after the action, before the proof ---")
    ended = step("call_ended (disconnected)", "/tools/call-ended",
                 {"interaction_id": call_id, "end_reason": "disconnected",
                  "duration_s": 48})
    expect("detected as ended mid-action", ended.get("ended_mid_action") is True)
    expect("proof sent anyway by the on_end repair",
           ended.get("proof_sent") is True)
    expect("proof reference issued", bool(ended.get("proof_ref")))

    call_id2 = "test-m1-call-2"
    step("call_started (second call)", "/tools/call-started",
         {"phone": phone, "interaction_id": call_id2, "language_code": "te-IN"})
    back = step("get_merchant_context (returning caller)", "/tools/merchant-context",
                {"phone": phone, "interaction_id": call_id2})
    expect("recognised as returning", back.get("returning_caller") is True)
    expect("same case resumed", back.get("case_ref") == case_ref,
           f"{back.get('case_ref')} vs {case_ref}")
    expect("second call in sequence", back.get("call_sequence_no") == 2,
           f"got {back.get('call_sequence_no')}")
    expect("knows what was already done",
           bool(back.get("actions_already_taken_text")))
    expect("mentions the pickup in the say",
           "pickup" in (back.get("say") or "").lower())
    expect("does NOT ask the merchant to explain again",
           "what is the problem" not in (back.get("say") or "").lower())


# ===================================================================== M2


def scenario_m2() -> None:
    print("\n" + "=" * 74)
    print('M2  PROMISE MISMATCH — "I was told 1 rupee a month, I pay 125."')
    print("=" * 74)
    phone, call_id = "+919000000002", "test-m2-call-1"

    step("call_started", "/tools/call-started",
         {"phone": phone, "interaction_id": call_id, "language_code": "hi-IN"})
    ctx = step("get_merchant_context", "/tools/merchant-context",
               {"phone": phone, "interaction_id": call_id})
    expect("plan mismatch detected", ctx.get("plan_mismatch") is True)

    check = step("check_promised_plan", "/tools/promise-check",
                 {"phone": phone, "interaction_id": call_id})
    expect("mismatch true", check.get("mismatch") is True)
    expect("Rs 868 overcharge", check.get("overcharge_amount") == 868.0,
           f"got {check.get('overcharge_amount')}")
    expect("7 months affected", check.get("months_affected") == 7,
           f"got {check.get('months_affected')}")
    expect("never claims the refund is approved",
           "approved" not in (check.get("say") or "").lower())

    refund = step("raise_refund_request", "/tools/refund-request",
                  {"phone": phone, "interaction_id": call_id,
                   "verify_answer": "Imran Mobile Repairs"})
    expect("awaiting approval", refund.get("status") == "awaiting_approval")
    expect("amount is Rs 868", refund.get("amount") == 868.0,
           f"got {refund.get('amount')}")
    ref = refund.get("request_ref")

    dup = step("raise_refund_request AGAIN (no stacking)", "/tools/refund-request",
               {"phone": phone, "interaction_id": call_id,
                "verify_answer": "Imran Mobile Repairs"})
    expect("same refund reference returned", dup.get("request_ref") == ref,
           f"{dup.get('request_ref')} vs {ref}")

    step("send_confirmation", "/tools/confirmation",
         {"phone": phone, "interaction_id": call_id})

    # ---- the human approves: the whole safety story ----
    status, queue, _ = call("/ops/approvals", method="GET")
    print(f"\n  [ops ] approval queue: {queue.get('count')} waiting")
    expect("refund is in the human queue",
           any(a["request_ref"] == ref for a in queue.get("approvals", [])))

    status, decided, _ = call(f"/ops/approvals/{ref}/approve",
                              {"decided_by": "test operator"})
    print(f"  [ops ] approve {ref}: HTTP {status} -> {decided.get('status')}")
    expect("approved by a human", decided.get("status") == "approved")

    status, queue2, _ = call("/ops/approvals", method="GET")
    expect("queue is now empty", queue2.get("count") == 0,
           f"got {queue2.get('count')}")


# ===================================================================== M3


def scenario_m3() -> None:
    print("\n" + "=" * 74)
    print('M3  SETTLEMENT HOLD — "My money is on hold."')
    print("=" * 74)
    phone, call_id = "+919000000003", "test-m3-call-1"

    step("call_started", "/tools/call-started",
         {"phone": phone, "interaction_id": call_id, "language_code": "te-IN"})
    ctx = step("get_merchant_context", "/tools/merchant-context",
               {"phone": phone, "interaction_id": call_id})
    expect("hold is visible", ctx.get("settlement_on_hold") is True)

    hold = step("get_settlement_hold", "/tools/settlement-hold",
                {"phone": phone, "interaction_id": call_id})
    expect("Rs 14,200 on hold", hold.get("amount_on_hold") == 14200.0,
           f"got {hold.get('amount_on_hold')}")
    expect("two documents missing", len(hold.get("missing_documents") or []) == 2)
    expect("gives an upload link", bool(hold.get("upload_url")))
    expect("upload link is ours, not a fake paytm.com URL",
           "paytm.com" not in (hold.get("upload_url") or ""))
    expect("gives an expected date", bool(hold.get("expected_release_date")))

    proof = step("send_confirmation", "/tools/confirmation",
                 {"phone": phone, "interaction_id": call_id})
    expect("confirmation mentions the upload link",
           "upload" in (proof.get("say") or "").lower())


# ===================================================================== M4


def scenario_m4() -> None:
    print("\n" + "=" * 74)
    print('M4  DEVICE FAULT — "The Soundbox stopped speaking."')
    print("=" * 74)
    phone, call_id = "+919000000004", "test-m4-call-1"

    step("call_started", "/tools/call-started",
         {"phone": phone, "interaction_id": call_id, "language_code": "te-IN"})
    ctx = step("get_merchant_context", "/tools/merchant-context",
               {"phone": phone, "interaction_id": call_id})
    expect("device silent ~11 days",
           (ctx.get("device_last_seen_days") or 0) >= 10,
           f"got {ctx.get('device_last_seen_days')}")

    first = step("device_troubleshoot (step 1)", "/tools/device",
                 {"phone": phone, "interaction_id": call_id, "symptom": "no_sound"})
    expect("not resolved yet", first.get("resolved") is False)
    expect("no technician yet", first.get("technician_booked") is False)
    expect("backend tracks the step itself", first.get("next_step") == 1,
           f"got {first.get('next_step')}")

    second = step("device_troubleshoot (step 2)", "/tools/device",
                  {"phone": phone, "interaction_id": call_id, "symptom": "no_sound"})
    expect("step advanced without the agent holding state",
           second.get("next_step") == 2, f"got {second.get('next_step')}")
    expect("a different instruction", second.get("say") != first.get("say"))

    third = step("device_troubleshoot (out of steps)", "/tools/device",
                 {"phone": phone, "interaction_id": call_id, "symptom": "no_sound",
                  "verify_answer": "Ravi Tea Stall"})
    expect("technician booked", third.get("technician_booked") is True)
    expect("has a ticket ref", bool(third.get("ticket_ref")))
    expect("has a visit date", bool(third.get("technician_date")))

    step("handover_to_human", "/tools/handover",
         {"phone": phone, "interaction_id": call_id,
          "reason": "merchant wants compensation for lost sales",
          "transcript": "test transcript"})


# ===================================================================== edges


def scenario_edges() -> None:
    print("\n" + "=" * 74)
    print("EDGE CASES — the things that break a live demo")
    print("=" * 74)

    # A tool call carrying someone else's number, with no call_started hook to
    # vouch for it. `phone` is a tool argument, so it is model-influenced; only
    # the number the platform's on_start hook recorded counts as caller id.
    spoof = step("spoofed caller id, no call_started hook",
                 "/tools/merchant-context",
                 {"phone": "+919000000001", "interaction_id": "test-spoof-1"})
    expect("spoofed number is NOT trusted as caller id",
           spoof.get("verified") is False,
           f"verified_by was {spoof.get('verified_by')!r}")
    expect("shop name withheld from the spoofer",
           spoof.get("merchant_name") is None,
           f"leaked {spoof.get('merchant_name')!r}")

    spoof_write = step("spoofed caller tries to stop billing",
                       "/tools/closure",
                       {"phone": "+919000000001", "interaction_id": "test-spoof-1"})
    expect("spoofed write refused", spoof_write.get("ok") is False,
           f"say was {spoof_write.get('say')!r}")

    # Trust must not be settable from the request. If the internal flag leaks
    # into the body, claiming it is all an attacker needs.
    claim = step("caller CLAIMS to be trusted in the request body",
                 "/tools/merchant-context",
                 {"phone": "+919000000001", "interaction_id": "test-claim-1",
                  "_trusted_caller": True, "caller_phone_trusted": True,
                  "verified": True})
    expect("a self-declared trust flag is ignored",
           claim.get("verified") is False,
           f"verified_by was {claim.get('verified_by')!r}")
    expect("still withholds the shop name",
           claim.get("merchant_name") is None,
           f"leaked {claim.get('merchant_name')!r}")

    claim_write = step("self-declared trusted caller tries to write",
                       "/tools/closure",
                       {"phone": "+919000000001", "interaction_id": "test-claim-1",
                        "_trusted_caller": True})
    expect("self-declared write refused", claim_write.get("ok") is False,
           f"say was {claim_write.get('say')!r}")

    unknown = step("unknown caller number", "/tools/merchant-context",
                   {"phone": "+919999999999", "interaction_id": "test-unknown-1"})
    expect("returns ok:false, not a 500", unknown.get("ok") is False)
    expect("asks for the registered number",
           "registered" in (unknown.get("say") or "").lower())

    # A number the caller merely SPOKE proves nothing, so the account must stay
    # closed to them until they read the device serial off the Soundbox.
    spoken = step("merchant says a number they are not calling from",
                  "/tools/merchant-context",
                  {"registered_phone": "9000000001", "interaction_id": "test-spoken-1"})
    expect("10-digit spoken number resolves", spoken.get("found") is True)
    expect("but is NOT treated as verified", spoken.get("verified") is False)
    expect("shop name withheld", spoken.get("merchant_name") is None,
           f"leaked {spoken.get('merchant_name')!r}")
    expect("device serial withheld", spoken.get("device_serial") is None)
    expect("no rupee figures leaked",
           spoken.get("amount_charged_after_closure") is None)
    expect("asks for something it never said",
           "serial" in (spoken.get("verify_question_text") or "").lower())
    expect("say does not contain the shop name",
           "lakshmi" not in (spoken.get("say") or "").lower())

    refused = step("write from that unverified caller (must be refused)",
                   "/tools/closure",
                   {"registered_phone": "9000000001",
                    "interaction_id": "test-spoken-1"})
    expect("unverified write refused", refused.get("ok") is False)

    wrong = step("wrong serial (must still be refused)", "/tools/closure",
                 {"registered_phone": "9000000001", "interaction_id": "test-spoken-1",
                  "verify_answer": "SB-00000"})
    expect("wrong serial refused", wrong.get("ok") is False)

    # A substring match would let one long digit string contain the serial and
    # walk straight through. 77301 is in here; it must still be refused.
    recite = step("reciting a long digit string (must be refused)",
                  "/tools/closure",
                  {"registered_phone": "9000000001",
                   "interaction_id": "test-spoken-1",
                   "verify_answer": "0123456789 7730177301 9876543210"})
    expect("a string merely CONTAINING the serial is refused",
           recite.get("ok") is False,
           f"say was {recite.get('say')!r}")

    # These two need their own cases: failed attempts now count against the
    # case, so running them on M1 would use up its allowance.
    #
    # Several serial-length numbers in one answer would be many guesses counted
    # as one attempt, which defeats the limit. M3's real serial is in here.
    multi = step("many candidate serials in one answer (must be refused)",
                 "/tools/device",
                 {"registered_phone": "9000000003",
                  "interaction_id": "test-multi-1", "symptom": "no_sound",
                  "verify_answer": "11111 22222 64207 33333 44444 55555"})
    expect("multi-guess answer refused outright",
           multi.get("technician_booked") is not True,
           f"say was {multi.get('say')!r}")

    # Honest reading with an unrelated small number alongside it still works.
    messy = step("real serial plus an unrelated number", "/tools/closure",
                 {"registered_phone": "9000000004",
                  "interaction_id": "test-messy-1",
                  "verify_answer": "it says SB 50982, shop 14"})
    expect("honest messy answer accepted", messy.get("ok") is True,
           f"say was {messy.get('say')!r}")

    right = step("correct serial unlocks the write", "/tools/closure",
                 {"registered_phone": "9000000001", "interaction_id": "test-spoken-1",
                  "verify_answer": "S B seven seven three zero one"})
    expect("correct serial accepted", right.get("ok") is True,
           f"say was {right.get('say')!r}")

    # Guessing must run out. Fresh call, so the attempt counter starts at zero.
    print("\n  --- guessing the serial on a fresh call ---")
    last = {}
    for attempt, guess in enumerate(["SB-11111", "SB-22222", "SB-33333",
                                     "SB-44444"], start=1):
        last = step(f"guess {attempt}", "/tools/closure",
                    {"registered_phone": "9000000001",
                     "interaction_id": "test-guessing-1",
                     "verify_answer": guess})
        expect(f"guess {attempt} refused", last.get("ok") is False)
    expect("locked out after the limit, hands over to a person",
           last.get("handover_required") is True,
           f"say was {last.get('say')!r}")

    status, body, _ = call("/tools/merchant-context", {"phone": "+919000000001"})
    print(f"\n  [auth] no interaction_id: HTTP {status}, ok={body.get('ok')}")
    expect("works without an interaction id too", status == 200)

    # Wrong shared secret must still speak, not 401, on a tool path.
    req = urllib.request.Request(
        BASE + "/tools/merchant-context",
        data=json.dumps({"phone": "+919000000001"}).encode(),
        headers={"Content-Type": "application/json", "X-Samadhan-Key": "wrong"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            code, payload = resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        code, payload = exc.code, {}
    print(f"\n  [auth] bad key on a tool path: HTTP {code}, ok={payload.get('ok')}")
    expect("bad key still returns 200 with a say", code == 200 and bool(payload.get("say")))

    binding = step("bind a live calling number to M1", "/admin/bind-phone",
                   {"phone": "+919812345678", "merchant_code": "M1"}) \
        if False else call("/admin/bind-phone",
                           {"phone": "+919812345678", "merchant_code": "M1"})[1]
    print(f"\n  [demo] bind-phone -> {binding.get('shop_name')}")
    expect("binding points at M1", binding.get("merchant_code") == "M1")

    # A real call reaches call_started first, which is what makes the caller id
    # trustworthy. Without that hook the bound number is just a tool argument.
    step("call_started from the bound number", "/tools/call-started",
         {"phone": "+919812345678", "interaction_id": "test-bound-1",
          "language_code": "te-IN"})
    bound = step("call from the newly bound number", "/tools/merchant-context",
                 {"phone": "+919812345678", "interaction_id": "test-bound-1"})
    expect("bound number resolves to M1",
           bound.get("merchant_name") == "Lakshmi Provision Store",
           f"got {bound.get('merchant_name')}")


# ======================================================================= main


def main() -> None:
    global BASE
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default=BASE)
    parser.add_argument("--only", default="all",
                        choices=["all", "m1", "m2", "m3", "m4", "edges"])
    args = parser.parse_args()
    BASE = args.base

    status, health, _ = call("/health", method="GET")
    if status != 200:
        sys.exit(f"backend not reachable at {BASE} (HTTP {status}). "
                 f"Start it with: fastapi dev backend/main.py")
    print(f"backend up at {BASE}  (db {health.get('db')}, "
          f"pool {health.get('pool_size')})")

    reset()

    runners = {"m1": scenario_m1, "m2": scenario_m2, "m3": scenario_m3,
               "m4": scenario_m4, "edges": scenario_edges}
    for name, fn in runners.items():
        if args.only in ("all", name):
            fn()

    print("\n" + "=" * 74)
    print("LATENCY (tool budget is 2000 ms)")
    print("=" * 74)
    tool_calls = [(p, ms) for p, ms in LATENCIES if p.startswith("/tools/")]
    if tool_calls:
        ordered = sorted(ms for _, ms in tool_calls)
        print(f"  {len(tool_calls)} tool calls   "
              f"min {ordered[0]:.0f} ms   "
              f"median {ordered[len(ordered)//2]:.0f} ms   "
              f"max {ordered[-1]:.0f} ms")
        # 2 s is the "feels dead on a call" line, not a cliff. Flag anything
        # over it, but only fail the run past 3 s, so a borderline 2.05 s does
        # not make the suite useless as a signal.
        for p, ms in sorted(tool_calls, key=lambda x: -x[1]):
            if ms > 3000:
                print(f"  FAIL {p} took {ms:.0f} ms, well over the 2 s budget")
                FAILURES.append(f"{p} over budget at {ms:.0f} ms")
            elif ms > 2000:
                print(f"  warn {p} took {ms:.0f} ms, just over the 2 s guide")

    print("\n" + "=" * 74)
    if FAILURES:
        print(f"{len(FAILURES)} FAILURE(S)")
        for f in FAILURES:
            print(f"  - {f}")
        sys.exit(1)
    print("ALL SCENARIOS PASSED")
    sys.exit(0)


if __name__ == "__main__":
    main()

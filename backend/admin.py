"""
Operator endpoints: health, demo reset, phone binding, and the approval queue.

These are not Sarvam tools. They are for us and for the dashboard, so they
return ordinary JSON and may return real HTTP error codes.
"""

from __future__ import annotations

import logging
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request

import config
import engine
import queries as q
import speak as sp
from db import healthcheck, tx

log = logging.getLogger("samadhan.admin")
router = APIRouter(tags=["admin"])

ROOT = Path(__file__).resolve().parent.parent


@router.get("/health")
def health() -> dict[str, Any]:
    try:
        return {"ok": True, **healthcheck()}
    except Exception as exc:
        raise HTTPException(503, f"database unreachable: {type(exc).__name__}") from exc


@router.get("/admin/cases")
def list_cases(limit: int = 50) -> dict[str, Any]:
    """Plain case list, for debugging a live call without the dashboard."""
    with tx() as cur:
        rows = q.case_feed(cur, limit)
    return {"ok": True, "count": len(rows), "cases": rows}


@router.get("/admin/cases/{case_ref}")
def case_detail(case_ref: str) -> dict[str, Any]:
    with tx() as cur:
        case = q.case_detail(cur, case_ref)
        if case is None:
            raise HTTPException(404, f"no case {case_ref}")
        cur.execute("select id from cases where case_ref = %s", (case_ref,))
        case_id = cur.fetchone()["id"]
        events = q.events_for_case(cur, case_id)
        calls = q.previous_calls(cur, case_id, None)
        proof = q.existing_proof(cur, case_id)
        refund = q.pending_refund(cur, case_id)
        spoken, done = engine.summarise_actions(cur, case_id)
    return {
        "ok": True,
        "case": case,
        "calls": calls,
        "events": events,
        "actions_done": done,
        "actions_text": spoken,
        "proof": proof,
        "pending_refund": refund,
    }


# ------------------------------------------------------------ approval queue


@router.get("/ops/approvals")
def approvals() -> dict[str, Any]:
    """Refunds waiting for a human. This queue IS the safety story."""
    with tx() as cur:
        rows = q.list_pending_refunds(cur)
    return {
        "ok": True,
        "count": len(rows),
        "approvals": [
            {
                **r,
                "amount_text": sp.rupees_text(r["amount"]),
                "amount_spoken": sp.rupees_spoken(r["amount"]),
            }
            for r in rows
        ],
    }


@router.post("/ops/approvals/{request_ref}/{decision}")
async def decide(request_ref: str, decision: str, request: Request) -> dict[str, Any]:
    if decision not in {"approve", "reject"}:
        raise HTTPException(400, "decision must be approve or reject")

    try:
        body = await request.json()
    except Exception:
        body = {}
    decided_by = str(body.get("decided_by") or "support operator")
    note = body.get("note")

    status = "approved" if decision == "approve" else "rejected"
    with tx() as cur:
        row = q.decide_refund(cur, request_ref, status, decided_by, note)
        if row is None:
            raise HTTPException(404, f"no pending refund {request_ref}")

        # Approving the money is what closes the case.
        if row["case_id"]:
            q.set_case_state(cur, row["case_id"],
                             "resolved" if status == "approved" else "handed_over")
            q.log_event(cur, row["case_id"], None, f"refund_{status}",
                        {"decided_by": decided_by, "note": note},
                        {"request_ref": request_ref, "amount": float(row["amount"])},
                        None, True, None, None, actor="human")

    return {
        "ok": True,
        "request_ref": request_ref,
        "status": status,
        "amount_text": sp.rupees_text(row["amount"]),
        "decided_by": decided_by,
    }


# --------------------------------------------------------------- demo support


@router.post("/admin/bind-phone")
async def bind_phone(request: Request) -> dict[str, Any]:
    """
    Point the number you are actually calling from at a seeded persona.

    On demo day Rahul calls from his own phone, which is not in the seed. This
    makes get_merchant_context find the right merchant. Ten seconds of work
    that saves the demo.
    """
    try:
        body = await request.json()
    except Exception:
        body = {}

    if not config.DEMO_MODE:
        raise HTTPException(403, "DEMO_MODE is off; phone binding is disabled")

    phone = q.normalise_phone(body.get("phone"))
    code = body.get("merchant_code")
    if not phone or not code:
        raise HTTPException(400, 'send {"phone": "+9199...", "merchant_code": "M1"}')

    with tx() as cur:
        merchant = q.find_merchant(cur, merchant_code=code)
        if merchant is None:
            raise HTTPException(404, f"no merchant {code}")
        q.bind_phone(cur, phone, merchant["id"], body.get("note") or "demo binding")

    return {
        "ok": True,
        "phone": phone,
        "merchant_code": merchant["merchant_code"],
        "shop_name": merchant["shop_name"],
        "language_code": merchant["language_code"],
    }


@router.post("/admin/reset")
def reset() -> dict[str, Any]:
    """Re-seed between demo takes. Runs db/seed.sql, which TRUNCATES first."""
    if not config.DEMO_MODE:
        raise HTTPException(403, "DEMO_MODE is off; reset is disabled")

    seed = ROOT / "db" / "seed.sql"
    if not seed.exists():
        raise HTTPException(500, "db/seed.sql not found")

    # seed.sql carries its own begin/commit so it can be run by hand in psql.
    # Inside tx() those would commit the wipe on their own, before the phone
    # bindings are restored, so a failure in between would lose them. Strip
    # them and let tx() make the whole reset one transaction.
    sql = re.sub(r"(?im)^\s*(begin|commit)\s*;\s*$", "",
                 seed.read_text(encoding="utf-8"))
    with tx() as cur:
        cur.execute("select count(*) as n from cases")
        cleared = cur.fetchone()["n"]

        # seed.sql truncates phone_bindings and recreates the merchants with
        # new ids. A binding is an operator's statement that a real handset is
        # a demo merchant ("my phone is M1"), not demo data, so it must survive
        # a reset: remember it by merchant_code and re-point it afterwards.
        cur.execute(
            """
            select b.phone, b.note, m.merchant_code
              from phone_bindings b join merchants m on m.id = b.merchant_id
            """
        )
        bindings = cur.fetchall()

        cur.execute(sql)

        restored = 0
        for b in bindings:
            merchant = q.find_merchant(cur, merchant_code=b["merchant_code"])
            if merchant:
                q.bind_phone(cur, b["phone"], merchant["id"], b["note"])
                restored += 1

        cur.execute("select merchant_code, shop_name from merchants order by merchant_code")
        merchants = cur.fetchall()
    log.info("demo data reset: %s cases cleared, %s phone bindings kept", cleared, restored)
    return {"ok": True, "cases_cleared": cleared, "bindings_kept": restored,
            "merchants": merchants}

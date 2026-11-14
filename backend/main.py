"""
Samadhan backend.

    fastapi dev backend/main.py          # development, hot reload
    fastapi run backend/main.py          # production-ish

Set PYTHONUTF8=1 first on Windows: the `say` strings contain ₹, and a cp1252
console raises UnicodeEncodeError the moment one is logged.
"""

from __future__ import annotations

import logging
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

import admin
import config
import tools
from db import close_pool, open_pool

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-5s %(name)s | %(message)s",
    datefmt="%H:%M:%S",
    stream=sys.stdout,
)
log = logging.getLogger("samadhan")


@asynccontextmanager
async def lifespan(app: FastAPI):
    missing = config.missing_settings()
    if missing:
        log.error("missing required settings: %s", ", ".join(missing))
        log.error("copy backend/.env.example to backend/.env and fill it in")
        raise RuntimeError(f"missing settings: {', '.join(missing)}")

    open_pool()
    log.info("verification %s | resume window %d days | pickup SLA %d working days",
             "ON" if config.REQUIRE_VERIFICATION else "OFF",
             config.CASE_RESUME_WINDOW_DAYS, config.PICKUP_SLA_DAYS)
    try:
        yield
    finally:
        close_pool()
        log.info("db pool closed")


app = FastAPI(
    title="Samadhan backend",
    version="1.0.0",
    description="Tools behind the Samadhan voice agent. Every response carries a `say`.",
    lifespan=lifespan,
)

# The dashboard reads Supabase directly; these are only for the approval
# actions and the odd debug fetch from a browser.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[config.DASHBOARD_URL, "http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Paths that do not need the shared secret.
OPEN_PATHS = {"/health", "/docs", "/openapi.json", "/redoc", "/"}


@app.middleware("http")
async def shared_secret(request: Request, call_next):
    """
    Sarvam sends X-Samadhan-Key on every tool call.

    A rejection still returns 200 with a `say`, because this middleware also
    guards the tool endpoints and a 401 mid-call is dead air. Operator
    endpoints get an ordinary 401.
    """
    path = request.url.path
    if path in OPEN_PATHS or request.method == "OPTIONS":
        return await call_next(request)

    supplied = request.headers.get("x-samadhan-key") or \
        request.headers.get("authorization", "").removeprefix("Bearer ").strip()

    if config.SAMADHAN_API_KEY and supplied != config.SAMADHAN_API_KEY:
        log.warning("rejected %s: bad or missing X-Samadhan-Key", path)
        if path.startswith("/tools/"):
            return JSONResponse(
                status_code=200,
                content={
                    "ok": False,
                    "reason": "unauthorised",
                    "say": "I am having trouble reaching your account securely. "
                           "Let me connect you to a colleague.",
                },
            )
        return JSONResponse(status_code=401, content={"ok": False,
                                                      "reason": "unauthorised"})

    return await call_next(request)


app.include_router(tools.router)
app.include_router(admin.router)


@app.get("/")
def root() -> dict[str, object]:
    return {
        "service": "samadhan-backend",
        "tools": [
            "POST /tools/call-started    (Sarvam on_start)",
            "POST /tools/call-ended      (Sarvam on_end)",
            "POST /tools/merchant-context",
            "POST /tools/billing",
            "POST /tools/promise-check",
            "POST /tools/closure",
            "POST /tools/settlement-hold",
            "POST /tools/device",
            "POST /tools/refund-request",
            "POST /tools/handover",
            "POST /tools/confirmation",
        ],
        "operator": [
            "GET  /health",
            "GET  /admin/cases",
            "GET  /admin/cases/{case_ref}",
            "GET  /ops/approvals",
            "POST /ops/approvals/{request_ref}/approve|reject",
            "POST /admin/bind-phone",
            "POST /admin/reset",
        ],
        "note": "every /tools response carries a `say`, including failures",
    }

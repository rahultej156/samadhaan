"""Configuration, read once from backend/.env."""

import os
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent
load_dotenv(BACKEND_DIR / ".env")


def _int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    try:
        return int(raw) if raw else default
    except ValueError:
        return default


def _bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
SUPABASE_URL = os.environ.get("SUPABASE_URL", "").strip()
SUPABASE_SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()

# Shared secret Sarvam sends as X-Samadhan-Key on every tool call.
SAMADHAN_API_KEY = os.environ.get("SAMADHAN_API_KEY", "").strip()

# How recently a case must have been touched to be resumed on a callback.
CASE_RESUME_WINDOW_DAYS = _int("CASE_RESUME_WINDOW_DAYS", 7)

# Working days ahead for a pickup or a technician visit.
PICKUP_SLA_DAYS = _int("PICKUP_SLA_DAYS", 4)
TECHNICIAN_SLA_DAYS = _int("TECHNICIAN_SLA_DAYS", 3)

DEBUG = _bool("SAMADHAN_DEBUG", True)

# Refund decisions are promised "by tomorrow" on the call.
REFUND_DECISION_SLA_DAYS = _int("REFUND_DECISION_SLA_DAYS", 1)


def missing_settings() -> list[str]:
    """Names of required settings that are absent. Checked at startup."""
    required = {
        "DATABASE_URL": DATABASE_URL,
        "SAMADHAN_API_KEY": SAMADHAN_API_KEY,
    }
    return [name for name, value in required.items() if not value]

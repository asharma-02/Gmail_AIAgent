"""
Firestore persistence layer for ADA Agent.

Replaces the SQLite implementation. All storage operations go through
this module — no other component needs to change.

Collections:
  - users        : user accounts (hashed passwords)
  - sessions     : login sessions with activity tracking
  - audit_log    : append-only record of all agent events

Credentials: Application Default Credentials (ADC) via gcloud auth.
Project and database are read from environment variables.
"""

from __future__ import annotations

import hashlib
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

# Load .env so GOOGLE_CLOUD_PROJECT is available
_ENV_PATH = Path(__file__).resolve().parents[2] / ".env"
load_dotenv(dotenv_path=_ENV_PATH)

logger = logging.getLogger(__name__)

_PROJECT_ID = os.getenv("GOOGLE_CLOUD_PROJECT", "project-22d2752d-0ba4-4e77-bb8")
_DATABASE_ID = os.getenv("FIRESTORE_DATABASE", "ada-database")

# ---------------------------------------------------------------------------
# Firestore client (lazy singleton)
# ---------------------------------------------------------------------------

_db = None


def _get_db():
    global _db
    if _db is None:
        from google.cloud import firestore
        _db = firestore.Client(project=_PROJECT_ID, database=_DATABASE_ID)
        logger.info("Firestore client initialised (project=%s, database=%s)", _PROJECT_ID, _DATABASE_ID)
    return _db


def init_db() -> None:
    """No-op for Firestore — collections are created automatically."""
    _get_db()
    logger.info("Firestore ready (project=%s, database=%s)", _PROJECT_ID, _DATABASE_ID)


# ---------------------------------------------------------------------------
# Password helpers
# ---------------------------------------------------------------------------

def hash_password(password: str) -> str:
    """Return a SHA-256 hex digest of the password."""
    return hashlib.sha256(password.encode()).hexdigest()


def verify_password(password: str, stored_hash: str) -> bool:
    return hash_password(password) == stored_hash


# ---------------------------------------------------------------------------
# User operations
# ---------------------------------------------------------------------------

def create_user(user_id: str, password: str) -> bool:
    """Create a new user. Returns True on success, False if user already exists."""
    db = _get_db()
    ref = db.collection("users").document(user_id)
    doc = ref.get()
    if doc.exists:
        return False
    ref.set({
        "user_id": user_id,
        "password_hash": hash_password(password),
        "created_at": _now_iso(),
        "last_login_at": None,
    })
    return True


def get_user(user_id: str):
    """Return the user document data dict or None if not found."""
    db = _get_db()
    doc = db.collection("users").document(user_id).get()
    return doc.to_dict() if doc.exists else None


def verify_user(user_id: str, password: str) -> bool:
    """Return True if the user exists and the password matches."""
    user = get_user(user_id)
    if user is None:
        return False
    return verify_password(password, user["password_hash"])


def update_last_login(user_id: str) -> None:
    db = _get_db()
    db.collection("users").document(user_id).update({"last_login_at": _now_iso()})


# ---------------------------------------------------------------------------
# Session operations
# ---------------------------------------------------------------------------

def save_session(
    session_id: str,
    user_id: str,
    created_at: datetime,
    last_active_at: datetime,
    expires_at: datetime,
) -> None:
    db = _get_db()
    db.collection("sessions").document(session_id).set({
        "session_id": session_id,
        "user_id": user_id,
        "created_at": _dt_iso(created_at),
        "last_active_at": _dt_iso(last_active_at),
        "expires_at": _dt_iso(expires_at),
        "is_active": True,
    })


def update_session_activity(
    session_id: str,
    last_active_at: datetime,
    expires_at: datetime,
) -> None:
    db = _get_db()
    db.collection("sessions").document(session_id).update({
        "last_active_at": _dt_iso(last_active_at),
        "expires_at": _dt_iso(expires_at),
    })


def deactivate_session(session_id: str) -> None:
    db = _get_db()
    db.collection("sessions").document(session_id).update({"is_active": False})


def get_sessions_for_user(user_id: str) -> list[dict]:
    db = _get_db()
    docs = (
        db.collection("sessions")
        .where("user_id", "==", user_id)
        .order_by("created_at", direction="DESCENDING")
        .stream()
    )
    return [doc.to_dict() for doc in docs]


# ---------------------------------------------------------------------------
# Audit log operations
# ---------------------------------------------------------------------------

def append_audit_entry(
    entry_id: str,
    event_type: str,
    timestamp: datetime,
    session_id: str,
    description: str,
    metadata: str,  # JSON string
) -> None:
    import json
    db = _get_db()
    db.collection("audit_log").document(entry_id).set({
        "entry_id": entry_id,
        "event_type": event_type,
        "timestamp": _dt_iso(timestamp),
        "session_id": session_id,
        "description": description,
        "metadata": json.loads(metadata),
    })


def query_audit_log(
    session_id: str | None = None,
    event_type: str | None = None,
    limit: int | None = 100,
) -> list[dict]:
    db = _get_db()
    query = db.collection("audit_log")

    if session_id:
        query = query.where("session_id", "==", session_id)
    if event_type:
        query = query.where("event_type", "==", event_type)

    query = query.order_by("timestamp", direction="DESCENDING")

    if limit:
        query = query.limit(limit)

    docs = query.stream()
    results = []
    for doc in docs:
        d = doc.to_dict()
        # Convert metadata back to JSON string for compatibility with audit_logger
        import json
        if isinstance(d.get("metadata"), dict):
            d["metadata"] = json.dumps(d["metadata"])
        results.append(d)
    return results


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _dt_iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()

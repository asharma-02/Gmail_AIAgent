"""
Audit log routes — query the append-only audit trail.
"""

from __future__ import annotations

from fastapi import APIRouter, Query
from pydantic import BaseModel
from datetime import datetime

from src.models.types import AuditEventType
from src.ui.state import audit_logger

router = APIRouter()


class AuditEntryOut(BaseModel):
    entry_id: str
    event_type: str
    timestamp: datetime
    session_id: str
    description: str
    metadata: dict[str, str]


@router.get("/logs", response_model=list[AuditEntryOut])
async def get_audit_logs(
    session_id: str | None = Query(default=None),
    event_type: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
) -> list[AuditEntryOut]:
    """Query the audit log with optional filters."""
    event_type_enum = None
    if event_type:
        try:
            event_type_enum = AuditEventType(event_type)
        except ValueError:
            event_type_enum = None

    entries = audit_logger.query(
        session_id=session_id,
        event_type=event_type_enum,
        limit=limit,
    )

    return [
        AuditEntryOut(
            entry_id=e.entry_id,
            event_type=e.event_type.value,
            timestamp=e.timestamp,
            session_id=e.session_id,
            description=e.description,
            metadata=e.metadata,
        )
        for e in entries
    ]


@router.get("/event-types")
async def list_event_types() -> dict:
    """Return all valid audit event type values."""
    return {"event_types": [e.value for e in AuditEventType]}

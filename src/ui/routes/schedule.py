"""
Scheduling routes — list, cancel, and inspect scheduled drafts.
"""

from __future__ import annotations

from datetime import datetime
from fastapi import APIRouter, HTTPException, status, Query
from pydantic import BaseModel

from src.models.types import ScheduledDraftStatus
from src.ui.state import orchestrator

router = APIRouter()


class ScheduledDraftOut(BaseModel):
    scheduled_draft_id: str
    draft_id: str
    recipient: str
    subject: str
    scheduled_send_time: datetime
    status: str
    confirmation_timeout_seconds: int


def _serialise_scheduled(sd) -> ScheduledDraftOut:
    return ScheduledDraftOut(
        scheduled_draft_id=sd.scheduled_draft_id,
        draft_id=sd.draft.draft_id,
        recipient=sd.draft.recipient,
        subject=sd.draft.subject,
        scheduled_send_time=sd.scheduled_send_time,
        status=sd.status.value,
        confirmation_timeout_seconds=sd.confirmation_timeout_seconds,
    )


@router.get("/drafts", response_model=list[ScheduledDraftOut])
async def list_scheduled_drafts(
    status_filter: str | None = Query(default=None),
) -> list[ScheduledDraftOut]:
    """List all scheduled drafts, optionally filtered by status."""
    status_enum = None
    if status_filter:
        try:
            status_enum = ScheduledDraftStatus(status_filter)
        except ValueError:
            pass

    drafts = orchestrator._scheduled_draft_manager.list_scheduled_drafts(
        status_filter=status_enum
    )
    return [_serialise_scheduled(d) for d in drafts]


@router.get("/drafts/{scheduled_draft_id}", response_model=ScheduledDraftOut)
async def get_scheduled_draft(scheduled_draft_id: str) -> ScheduledDraftOut:
    """Get a specific scheduled draft by ID."""
    try:
        draft = orchestrator._scheduled_draft_manager.get_scheduled_draft(
            scheduled_draft_id
        )
        return _serialise_scheduled(draft)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Scheduled draft not found: {scheduled_draft_id}",
        ) from exc


@router.delete("/drafts/{scheduled_draft_id}")
async def cancel_scheduled_draft(scheduled_draft_id: str) -> dict:
    """Cancel a scheduled draft."""
    try:
        orchestrator._scheduled_draft_manager.cancel_scheduled_draft(
            scheduled_draft_id
        )
        return {"message": f"Scheduled draft {scheduled_draft_id} cancelled"}
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


@router.get("/statuses")
async def list_statuses() -> dict:
    return {"statuses": [s.value for s in ScheduledDraftStatus]}

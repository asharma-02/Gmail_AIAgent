"""
Scheduled Draft Manager — lifecycle management for scheduled email drafts.

Handles registration, cancellation, editing, listing, and send-time
confirmation of scheduled drafts. The agent NEVER auto-sends; every send
requires active user confirmation at send time.

Requirements: 7.3, 7.4, 7.5, 7.6
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from src.approval.approval_gate_controller import ApprovalGateController
from src.models.types import (
    ApprovalDecision,
    Draft,
    ScheduledDraft,
    ScheduledDraftStatus,
    TimeoutResult,
)
from src.scheduling.errors import (
    ScheduledDraftAlreadyCancelledError,
    ScheduledDraftAlreadySentError,
    ScheduledDraftNotFoundError,
)


class ScheduledDraftManager:
    """
    Manages the full lifecycle of scheduled email drafts.

    Drafts are stored in memory keyed by ``scheduled_draft_id``.
    The manager enforces that no draft is ever auto-sent — every send
    requires explicit user confirmation via the approval gate.
    """

    def __init__(self) -> None:
        # Keyed by scheduled_draft_id; insertion order preserved (Python 3.7+).
        self._drafts: dict[str, ScheduledDraft] = {}

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register_scheduled_draft(
        self,
        draft: Draft,
        send_time: datetime,
        confirmation_timeout_seconds: int = 300,
    ) -> ScheduledDraft:
        """
        Register a new scheduled draft.

        Creates a ``ScheduledDraft`` with ``status='pending'``, stores it,
        and returns it.

        Requirements: 7.3
        """
        scheduled_draft = ScheduledDraft(
            draft=draft,
            scheduled_send_time=send_time,
            status=ScheduledDraftStatus.PENDING,
            confirmation_timeout_seconds=confirmation_timeout_seconds,
        )
        self._drafts[scheduled_draft.scheduled_draft_id] = scheduled_draft
        return scheduled_draft

    # ------------------------------------------------------------------
    # Cancellation
    # ------------------------------------------------------------------

    def cancel_scheduled_draft(self, scheduled_draft_id: str) -> None:
        """
        Cancel a scheduled draft.

        Raises:
            ScheduledDraftNotFoundError: if the ID is not found.
            ScheduledDraftAlreadySentError: if the draft has already been sent.

        Already-cancelled drafts are treated as idempotent (no error raised).

        Requirements: 7.4
        """
        scheduled_draft = self._get_or_raise(scheduled_draft_id)

        if scheduled_draft.status == ScheduledDraftStatus.SENT:
            raise ScheduledDraftAlreadySentError(
                f"Scheduled draft '{scheduled_draft_id}' has already been sent."
            )

        # Idempotent: cancelling an already-cancelled draft is a no-op.
        scheduled_draft.status = ScheduledDraftStatus.CANCELLED

    # ------------------------------------------------------------------
    # Editing
    # ------------------------------------------------------------------

    def edit_scheduled_draft(
        self,
        scheduled_draft_id: str,
        new_draft: Draft | None = None,
        new_send_time: datetime | None = None,
    ) -> ScheduledDraft:
        """
        Edit a scheduled draft before it is sent.

        Raises:
            ScheduledDraftNotFoundError: if the ID is not found.
            ScheduledDraftAlreadySentError: if the draft has already been sent.
            ScheduledDraftAlreadyCancelledError: if the draft has been cancelled.

        Requirements: 7.4
        """
        scheduled_draft = self._get_or_raise(scheduled_draft_id)

        if scheduled_draft.status == ScheduledDraftStatus.SENT:
            raise ScheduledDraftAlreadySentError(
                f"Scheduled draft '{scheduled_draft_id}' has already been sent."
            )
        if scheduled_draft.status == ScheduledDraftStatus.CANCELLED:
            raise ScheduledDraftAlreadyCancelledError(
                f"Scheduled draft '{scheduled_draft_id}' has been cancelled."
            )

        if new_draft is not None:
            scheduled_draft.draft = new_draft
        if new_send_time is not None:
            scheduled_draft.scheduled_send_time = new_send_time

        return scheduled_draft

    # ------------------------------------------------------------------
    # Listing and retrieval
    # ------------------------------------------------------------------

    def list_scheduled_drafts(
        self,
        status_filter: ScheduledDraftStatus | None = None,
    ) -> list[ScheduledDraft]:
        """
        Return all scheduled drafts, optionally filtered by status.

        Returns most-recently-registered first (reverse insertion order).

        Requirements: 7.3
        """
        drafts = list(self._drafts.values())
        if status_filter is not None:
            drafts = [d for d in drafts if d.status == status_filter]
        # Most-recently-registered first.
        return list(reversed(drafts))

    def get_scheduled_draft(self, scheduled_draft_id: str) -> ScheduledDraft:
        """
        Retrieve a scheduled draft by ID.

        Raises:
            ScheduledDraftNotFoundError: if the ID is not found.

        Requirements: 7.3
        """
        return self._get_or_raise(scheduled_draft_id)

    # ------------------------------------------------------------------
    # Send-time confirmation
    # ------------------------------------------------------------------

    def trigger_send_time_confirmation(
        self,
        scheduled_draft_id: str,
        approval_gate: ApprovalGateController,
        decision_callback: Callable[[], ApprovalDecision] | None = None,
    ) -> ApprovalDecision | TimeoutResult:
        """
        Trigger the active confirmation prompt at send time.

        State transitions:
        - Sets status to ``awaiting_confirmation`` before presenting the gate.
        - CONFIRMED  → status becomes ``sent``;    returns ``ApprovalDecision.CONFIRMED``.
        - CANCELLED  → status reverts to ``pending``; returns ``ApprovalDecision.CANCELLED``.
        - TimeoutResult → status is set to ``held`` by the gate; returns ``TimeoutResult``.

        NEVER auto-sends — always requires explicit confirmation.

        Raises:
            ScheduledDraftNotFoundError: if the ID is not found.
            ScheduledDraftAlreadySentError: if the draft has already been sent.
            ScheduledDraftAlreadyCancelledError: if the draft has been cancelled.

        Requirements: 7.5, 7.6
        """
        scheduled_draft = self._get_or_raise(scheduled_draft_id)

        if scheduled_draft.status == ScheduledDraftStatus.SENT:
            raise ScheduledDraftAlreadySentError(
                f"Scheduled draft '{scheduled_draft_id}' has already been sent."
            )
        if scheduled_draft.status == ScheduledDraftStatus.CANCELLED:
            raise ScheduledDraftAlreadyCancelledError(
                f"Scheduled draft '{scheduled_draft_id}' has been cancelled."
            )

        # Mark as awaiting confirmation before presenting the gate.
        scheduled_draft.status = ScheduledDraftStatus.AWAITING_CONFIRMATION

        result = approval_gate.present_scheduled_send_confirmation(
            scheduled_draft,
            decision_callback=decision_callback,
        )

        if isinstance(result, TimeoutResult):
            # Gate already set status to 'held'; just return the result.
            return result

        if result == ApprovalDecision.CONFIRMED:
            scheduled_draft.status = ScheduledDraftStatus.SENT
        elif result == ApprovalDecision.CANCELLED:
            scheduled_draft.status = ScheduledDraftStatus.PENDING

        return result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_or_raise(self, scheduled_draft_id: str) -> ScheduledDraft:
        """Return the draft or raise ScheduledDraftNotFoundError."""
        try:
            return self._drafts[scheduled_draft_id]
        except KeyError:
            raise ScheduledDraftNotFoundError(
                f"Scheduled draft '{scheduled_draft_id}' not found."
            )

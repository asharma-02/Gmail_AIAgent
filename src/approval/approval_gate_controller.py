"""
Approval Gate Controller — enforces human-in-the-loop for all sensitive actions.

In a real UI this would render a dialog and block until the user clicks.
For the backend implementation the gate works by:
  1. Recording that a gate was presented (for audit/testing purposes).
  2. Accepting an optional decision_callback for testability.
  3. Defaulting to CANCELLED when no callback is provided (safe default —
     never auto-approve).

Requirements: 5.1, 5.2, 5.4, 6.1, 6.2, 6.4, 7.1, 7.2, 7.5, 7.6
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from datetime import datetime

from src.models.types import (
    ApprovalDecision,
    ContextSummary,
    Draft,
    ScheduledDraft,
    ScheduledDraftStatus,
    TimeoutResult,
)


class ApprovalGateController:
    """
    Controls approval gates for send, delete, and schedule sensitive actions.

    Each ``present_*_gate`` method:
    - Records the gate presentation in ``_gate_history`` for audit/testing.
    - Calls ``decision_callback()`` if provided to obtain the decision.
    - Returns ``ApprovalDecision.CANCELLED`` when no callback is supplied
      (safe default — never auto-approve).
    """

    def __init__(self) -> None:
        self._gate_history: list[dict] = []

    # ------------------------------------------------------------------
    # Task 9.1 — Send / Delete / Schedule gates
    # ------------------------------------------------------------------

    def present_send_gate(
        self,
        draft: Draft,
        context_summary: ContextSummary,
        decision_callback: Callable[[], ApprovalDecision] | None = None,
    ) -> ApprovalDecision:
        """
        Present the send approval gate.

        Displays recipient, subject, full body, attachments, and Context
        Summary to the user (in a real UI).  Records the gate presentation
        and returns the decision from *decision_callback*, or CANCELLED if
        no callback is provided.

        Records: gate_type='send', draft_id, recipient, subject,
                 context_summary_id
        """
        self._gate_history.append(
            {
                "gate_type": "send",
                "draft_id": draft.draft_id,
                "recipient": draft.recipient,
                "subject": draft.subject,
                "context_summary_id": context_summary.summary_id,
            }
        )

        if decision_callback is not None:
            return decision_callback()
        return ApprovalDecision.CANCELLED

    def present_delete_gate(
        self,
        message_id: str,
        sender: str,
        subject: str,
        sent_at: datetime,
        decision_callback: Callable[[], ApprovalDecision] | None = None,
    ) -> ApprovalDecision:
        """
        Present the delete approval gate.

        Displays sender, subject, and date to the user (in a real UI).
        Records the gate presentation and returns the decision from
        *decision_callback*, or CANCELLED if no callback is provided.

        Records: gate_type='delete', message_id, sender, subject, sent_at
        """
        self._gate_history.append(
            {
                "gate_type": "delete",
                "message_id": message_id,
                "sender": sender,
                "subject": subject,
                "sent_at": sent_at,
            }
        )

        if decision_callback is not None:
            return decision_callback()
        return ApprovalDecision.CANCELLED

    def present_schedule_gate(
        self,
        draft: Draft,
        scheduled_time: datetime,
        decision_callback: Callable[[], ApprovalDecision] | None = None,
    ) -> ApprovalDecision:
        """
        Present the schedule approval gate.

        Displays email content, recipient, and proposed send time to the
        user (in a real UI).  Records the gate presentation and returns the
        decision from *decision_callback*, or CANCELLED if no callback is
        provided.

        Records: gate_type='schedule', draft_id, recipient, scheduled_time
        """
        self._gate_history.append(
            {
                "gate_type": "schedule",
                "draft_id": draft.draft_id,
                "recipient": draft.recipient,
                "scheduled_time": scheduled_time,
            }
        )

        if decision_callback is not None:
            return decision_callback()
        return ApprovalDecision.CANCELLED

    # ------------------------------------------------------------------
    # Task 9.2 — Scheduled send active confirmation with timeout
    # ------------------------------------------------------------------

    def present_scheduled_send_confirmation(
        self,
        scheduled_draft: ScheduledDraft,
        timeout_seconds: int | None = None,
        decision_callback: Callable[[], ApprovalDecision] | None = None,
    ) -> ApprovalDecision | TimeoutResult:
        """
        Present the active confirmation prompt when a scheduled send time
        arrives.

        - Uses ``timeout_seconds`` from the ScheduledDraft if not overridden.
        - If *decision_callback* is provided AND returns within timeout:
          return the decision.
        - If *decision_callback* is None OR times out: return
          ``TimeoutResult(held_draft_id=...)`` and update
          ``scheduled_draft.status`` to ``held``.
        - NEVER auto-sends — always requires explicit confirmation.

        Records: gate_type='scheduled_send_confirmation', scheduled_draft_id
        """
        effective_timeout = (
            timeout_seconds
            if timeout_seconds is not None
            else scheduled_draft.confirmation_timeout_seconds
        )

        self._gate_history.append(
            {
                "gate_type": "scheduled_send_confirmation",
                "scheduled_draft_id": scheduled_draft.scheduled_draft_id,
            }
        )

        if decision_callback is None:
            # No callback — hold immediately (never auto-send).
            scheduled_draft.status = ScheduledDraftStatus.HELD
            return TimeoutResult(held_draft_id=scheduled_draft.scheduled_draft_id)

        # Run the callback in a thread so we can apply a timeout.
        result_container: list[ApprovalDecision | BaseException] = []
        done_event = threading.Event()

        def _run_callback() -> None:
            try:
                result_container.append(decision_callback())
            except Exception as exc:  # noqa: BLE001
                result_container.append(exc)
            finally:
                done_event.set()

        worker = threading.Thread(target=_run_callback, daemon=True)
        worker.start()

        completed = done_event.wait(timeout=effective_timeout)

        if not completed:
            # Timed out — hold the draft.
            scheduled_draft.status = ScheduledDraftStatus.HELD
            return TimeoutResult(held_draft_id=scheduled_draft.scheduled_draft_id)

        outcome = result_container[0]

        if isinstance(outcome, BaseException):
            # Callback raised (e.g. TimeoutError) — treat as timeout.
            scheduled_draft.status = ScheduledDraftStatus.HELD
            return TimeoutResult(held_draft_id=scheduled_draft.scheduled_draft_id)

        return outcome

    # ------------------------------------------------------------------
    # History helper
    # ------------------------------------------------------------------

    def get_gate_history(self) -> list[dict]:
        """Return a copy of the gate presentation history."""
        return list(self._gate_history)

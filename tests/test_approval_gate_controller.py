"""
Unit tests for ApprovalGateController.

Covers Tasks 9.1 and 9.2:
  - present_send_gate
  - present_delete_gate
  - present_schedule_gate
  - present_scheduled_send_confirmation (with timeout)
  - get_gate_history

Requirements: 5.1, 5.2, 5.4, 6.1, 6.2, 6.4, 7.1, 7.2, 7.5, 7.6
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from src.approval import ApprovalGateController
from src.models.types import (
    ApprovalDecision,
    ContextSummary,
    Draft,
    ScheduledDraft,
    ScheduledDraftStatus,
    TimeoutResult,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_context_summary() -> ContextSummary:
    return ContextSummary(generated_from_instruction_only=True)


def _make_draft(recipient: str = "alice@example.com") -> Draft:
    return Draft(
        recipient=recipient,
        subject="Test Subject",
        body="Hello, this is a test email.",
        context_summary=_make_context_summary(),
        generated_from_instruction="Write a test email",
    )


def _make_scheduled_draft(
    timeout_seconds: int = 300,
) -> ScheduledDraft:
    return ScheduledDraft(
        draft=_make_draft(),
        scheduled_send_time=datetime(2025, 12, 1, 9, 0, tzinfo=timezone.utc),
        confirmation_timeout_seconds=timeout_seconds,
    )


@pytest.fixture()
def controller() -> ApprovalGateController:
    return ApprovalGateController()


# ---------------------------------------------------------------------------
# Task 9.1 — present_send_gate
# ---------------------------------------------------------------------------


class TestPresentSendGate:
    def test_confirmed_callback_returns_confirmed(
        self, controller: ApprovalGateController
    ) -> None:
        draft = _make_draft()
        summary = _make_context_summary()
        decision = controller.present_send_gate(
            draft, summary, decision_callback=lambda: ApprovalDecision.CONFIRMED
        )
        assert decision == ApprovalDecision.CONFIRMED

    def test_cancelled_callback_returns_cancelled(
        self, controller: ApprovalGateController
    ) -> None:
        draft = _make_draft()
        summary = _make_context_summary()
        decision = controller.present_send_gate(
            draft, summary, decision_callback=lambda: ApprovalDecision.CANCELLED
        )
        assert decision == ApprovalDecision.CANCELLED

    def test_no_callback_returns_cancelled_safe_default(
        self, controller: ApprovalGateController
    ) -> None:
        """Safe default: no callback → CANCELLED (never auto-approve)."""
        draft = _make_draft()
        summary = _make_context_summary()
        decision = controller.present_send_gate(draft, summary)
        assert decision == ApprovalDecision.CANCELLED

    def test_records_gate_in_history_with_gate_type_send(
        self, controller: ApprovalGateController
    ) -> None:
        draft = _make_draft()
        summary = _make_context_summary()
        controller.present_send_gate(draft, summary)
        history = controller.get_gate_history()
        assert len(history) == 1
        assert history[0]["gate_type"] == "send"

    def test_records_draft_id_and_recipient_in_history(
        self, controller: ApprovalGateController
    ) -> None:
        draft = _make_draft(recipient="bob@example.com")
        summary = _make_context_summary()
        controller.present_send_gate(draft, summary)
        entry = controller.get_gate_history()[0]
        assert entry["draft_id"] == draft.draft_id
        assert entry["recipient"] == "bob@example.com"


# ---------------------------------------------------------------------------
# Task 9.1 — present_delete_gate
# ---------------------------------------------------------------------------


class TestPresentDeleteGate:
    def test_confirmed_callback_returns_confirmed(
        self, controller: ApprovalGateController
    ) -> None:
        decision = controller.present_delete_gate(
            message_id="msg-001",
            sender="carol@example.com",
            subject="Re: Budget",
            sent_at=datetime(2025, 1, 10, tzinfo=timezone.utc),
            decision_callback=lambda: ApprovalDecision.CONFIRMED,
        )
        assert decision == ApprovalDecision.CONFIRMED

    def test_no_callback_returns_cancelled(
        self, controller: ApprovalGateController
    ) -> None:
        decision = controller.present_delete_gate(
            message_id="msg-002",
            sender="dave@example.com",
            subject="Hello",
            sent_at=datetime(2025, 1, 11, tzinfo=timezone.utc),
        )
        assert decision == ApprovalDecision.CANCELLED

    def test_records_gate_type_delete_and_message_id(
        self, controller: ApprovalGateController
    ) -> None:
        controller.present_delete_gate(
            message_id="msg-xyz",
            sender="eve@example.com",
            subject="Important",
            sent_at=datetime(2025, 2, 1, tzinfo=timezone.utc),
        )
        entry = controller.get_gate_history()[0]
        assert entry["gate_type"] == "delete"
        assert entry["message_id"] == "msg-xyz"


# ---------------------------------------------------------------------------
# Task 9.1 — present_schedule_gate
# ---------------------------------------------------------------------------


class TestPresentScheduleGate:
    def test_confirmed_callback_returns_confirmed(
        self, controller: ApprovalGateController
    ) -> None:
        draft = _make_draft()
        scheduled_time = datetime(2025, 6, 15, 8, 0, tzinfo=timezone.utc)
        decision = controller.present_schedule_gate(
            draft,
            scheduled_time,
            decision_callback=lambda: ApprovalDecision.CONFIRMED,
        )
        assert decision == ApprovalDecision.CONFIRMED

    def test_no_callback_returns_cancelled(
        self, controller: ApprovalGateController
    ) -> None:
        draft = _make_draft()
        scheduled_time = datetime(2025, 6, 15, 8, 0, tzinfo=timezone.utc)
        decision = controller.present_schedule_gate(draft, scheduled_time)
        assert decision == ApprovalDecision.CANCELLED

    def test_records_gate_type_schedule_and_scheduled_time(
        self, controller: ApprovalGateController
    ) -> None:
        draft = _make_draft()
        scheduled_time = datetime(2025, 7, 4, 12, 0, tzinfo=timezone.utc)
        controller.present_schedule_gate(draft, scheduled_time)
        entry = controller.get_gate_history()[0]
        assert entry["gate_type"] == "schedule"
        assert entry["scheduled_time"] == scheduled_time


# ---------------------------------------------------------------------------
# Task 9.1 — get_gate_history
# ---------------------------------------------------------------------------


class TestGetGateHistory:
    def test_returns_copy_modifying_does_not_affect_internal_state(
        self, controller: ApprovalGateController
    ) -> None:
        draft = _make_draft()
        summary = _make_context_summary()
        controller.present_send_gate(draft, summary)

        history = controller.get_gate_history()
        history.clear()  # mutate the returned copy

        # Internal state must be unaffected.
        assert len(controller.get_gate_history()) == 1

    def test_multiple_gate_presentations_accumulate_in_history(
        self, controller: ApprovalGateController
    ) -> None:
        draft = _make_draft()
        summary = _make_context_summary()
        scheduled_time = datetime(2025, 8, 1, tzinfo=timezone.utc)

        controller.present_send_gate(draft, summary)
        controller.present_delete_gate(
            message_id="m1",
            sender="x@example.com",
            subject="S",
            sent_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
        )
        controller.present_schedule_gate(draft, scheduled_time)

        history = controller.get_gate_history()
        assert len(history) == 3
        assert history[0]["gate_type"] == "send"
        assert history[1]["gate_type"] == "delete"
        assert history[2]["gate_type"] == "schedule"


# ---------------------------------------------------------------------------
# Task 9.2 — present_scheduled_send_confirmation
# ---------------------------------------------------------------------------


class TestPresentScheduledSendConfirmation:
    def test_returns_confirmed_when_callback_confirms_within_timeout(
        self, controller: ApprovalGateController
    ) -> None:
        scheduled_draft = _make_scheduled_draft(timeout_seconds=5)
        result = controller.present_scheduled_send_confirmation(
            scheduled_draft,
            decision_callback=lambda: ApprovalDecision.CONFIRMED,
        )
        assert result == ApprovalDecision.CONFIRMED

    def test_returns_cancelled_when_callback_cancels(
        self, controller: ApprovalGateController
    ) -> None:
        scheduled_draft = _make_scheduled_draft(timeout_seconds=5)
        result = controller.present_scheduled_send_confirmation(
            scheduled_draft,
            decision_callback=lambda: ApprovalDecision.CANCELLED,
        )
        assert result == ApprovalDecision.CANCELLED

    def test_returns_timeout_result_when_no_callback(
        self, controller: ApprovalGateController
    ) -> None:
        """No callback → TimeoutResult (never auto-send)."""
        scheduled_draft = _make_scheduled_draft(timeout_seconds=5)
        result = controller.present_scheduled_send_confirmation(scheduled_draft)
        assert isinstance(result, TimeoutResult)

    def test_timeout_result_contains_correct_scheduled_draft_id(
        self, controller: ApprovalGateController
    ) -> None:
        scheduled_draft = _make_scheduled_draft(timeout_seconds=5)
        result = controller.present_scheduled_send_confirmation(scheduled_draft)
        assert isinstance(result, TimeoutResult)
        assert result.held_draft_id == scheduled_draft.scheduled_draft_id

    def test_scheduled_draft_status_set_to_held_on_timeout(
        self, controller: ApprovalGateController
    ) -> None:
        scheduled_draft = _make_scheduled_draft(timeout_seconds=5)
        controller.present_scheduled_send_confirmation(scheduled_draft)
        assert scheduled_draft.status == ScheduledDraftStatus.HELD

    def test_records_gate_type_scheduled_send_confirmation_in_history(
        self, controller: ApprovalGateController
    ) -> None:
        scheduled_draft = _make_scheduled_draft(timeout_seconds=5)
        controller.present_scheduled_send_confirmation(scheduled_draft)
        entry = controller.get_gate_history()[0]
        assert entry["gate_type"] == "scheduled_send_confirmation"
        assert entry["scheduled_draft_id"] == scheduled_draft.scheduled_draft_id

    def test_never_auto_sends_no_callback_always_timeout_result(
        self, controller: ApprovalGateController
    ) -> None:
        """Safety invariant: no callback must NEVER produce CONFIRMED."""
        for _ in range(5):
            sd = _make_scheduled_draft(timeout_seconds=5)
            result = controller.present_scheduled_send_confirmation(sd)
            assert result != ApprovalDecision.CONFIRMED, (
                "Auto-send detected — gate must never approve without explicit confirmation"
            )

    def test_actual_timeout_returns_timeout_result_and_holds_draft(
        self, controller: ApprovalGateController
    ) -> None:
        """Callback that blocks longer than the timeout → TimeoutResult."""
        import time

        scheduled_draft = _make_scheduled_draft(timeout_seconds=1)

        def slow_callback() -> ApprovalDecision:
            time.sleep(5)  # much longer than the 1-second timeout
            return ApprovalDecision.CONFIRMED

        result = controller.present_scheduled_send_confirmation(
            scheduled_draft,
            timeout_seconds=1,
            decision_callback=slow_callback,
        )
        assert isinstance(result, TimeoutResult)
        assert result.held_draft_id == scheduled_draft.scheduled_draft_id
        assert scheduled_draft.status == ScheduledDraftStatus.HELD

    def test_timeout_override_takes_precedence_over_draft_timeout(
        self, controller: ApprovalGateController
    ) -> None:
        """Explicit timeout_seconds parameter overrides the draft's default."""
        import time

        # Draft has a 300-second timeout, but we override to 1 second.
        scheduled_draft = _make_scheduled_draft(timeout_seconds=300)

        def slow_callback() -> ApprovalDecision:
            time.sleep(5)
            return ApprovalDecision.CONFIRMED

        result = controller.present_scheduled_send_confirmation(
            scheduled_draft,
            timeout_seconds=1,
            decision_callback=slow_callback,
        )
        assert isinstance(result, TimeoutResult)

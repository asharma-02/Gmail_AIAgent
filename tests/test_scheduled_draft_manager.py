"""
Unit tests for ScheduledDraftManager.

Covers all four lifecycle flows and additional edge cases:
  1. register → cancel
  2. register → edit
  3. register → send-time confirmation → send (CONFIRMED)
  4. register → timeout → hold (no callback)

Additional:
  - list_scheduled_drafts ordering and status_filter
  - get_scheduled_draft raises ScheduledDraftNotFoundError for unknown IDs
  - trigger_send_time_confirmation error cases
  - trigger_send_time_confirmation with CANCELLED callback reverts to pending

Requirements: 7.3, 7.4, 7.5, 7.6
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.approval import ApprovalGateController
from src.models.types import (
    ApprovalDecision,
    ContextSummary,
    Draft,
    ScheduledDraftStatus,
    TimeoutResult,
)
from src.scheduling.errors import (
    ScheduledDraftAlreadyCancelledError,
    ScheduledDraftAlreadySentError,
    ScheduledDraftNotFoundError,
)
from src.scheduling.scheduled_draft_manager import ScheduledDraftManager


# ---------------------------------------------------------------------------
# Helpers / fixtures
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


_SEND_TIME = datetime(2025, 12, 1, 9, 0, tzinfo=timezone.utc)


@pytest.fixture()
def manager() -> ScheduledDraftManager:
    return ScheduledDraftManager()


@pytest.fixture()
def gate() -> ApprovalGateController:
    return ApprovalGateController()


# ---------------------------------------------------------------------------
# Flow 1: register → cancel
# ---------------------------------------------------------------------------


class TestRegisterCancel:
    def test_cancel_sets_status_to_cancelled(
        self, manager: ScheduledDraftManager
    ) -> None:
        sd = manager.register_scheduled_draft(_make_draft(), _SEND_TIME)
        manager.cancel_scheduled_draft(sd.scheduled_draft_id)
        assert sd.status == ScheduledDraftStatus.CANCELLED

    def test_cancel_already_cancelled_is_idempotent(
        self, manager: ScheduledDraftManager
    ) -> None:
        """Cancelling an already-cancelled draft must not raise."""
        sd = manager.register_scheduled_draft(_make_draft(), _SEND_TIME)
        manager.cancel_scheduled_draft(sd.scheduled_draft_id)
        # Second cancel — should be a no-op, not an error.
        manager.cancel_scheduled_draft(sd.scheduled_draft_id)
        assert sd.status == ScheduledDraftStatus.CANCELLED

    def test_cancel_already_sent_raises_already_sent_error(
        self, manager: ScheduledDraftManager, gate: ApprovalGateController
    ) -> None:
        sd = manager.register_scheduled_draft(_make_draft(), _SEND_TIME)
        # Send the draft first.
        manager.trigger_send_time_confirmation(
            sd.scheduled_draft_id,
            gate,
            decision_callback=lambda: ApprovalDecision.CONFIRMED,
        )
        assert sd.status == ScheduledDraftStatus.SENT

        with pytest.raises(ScheduledDraftAlreadySentError):
            manager.cancel_scheduled_draft(sd.scheduled_draft_id)

    def test_cancel_unknown_id_raises_not_found_error(
        self, manager: ScheduledDraftManager
    ) -> None:
        with pytest.raises(ScheduledDraftNotFoundError):
            manager.cancel_scheduled_draft("nonexistent-id")


# ---------------------------------------------------------------------------
# Flow 2: register → edit
# ---------------------------------------------------------------------------


class TestRegisterEdit:
    def test_edit_draft_content_is_reflected(
        self, manager: ScheduledDraftManager
    ) -> None:
        sd = manager.register_scheduled_draft(_make_draft(), _SEND_TIME)
        new_draft = _make_draft(recipient="bob@example.com")
        result = manager.edit_scheduled_draft(
            sd.scheduled_draft_id, new_draft=new_draft
        )
        assert result.draft.recipient == "bob@example.com"
        assert sd.draft.recipient == "bob@example.com"

    def test_edit_send_time_is_reflected(
        self, manager: ScheduledDraftManager
    ) -> None:
        sd = manager.register_scheduled_draft(_make_draft(), _SEND_TIME)
        new_time = datetime(2026, 1, 15, 10, 30, tzinfo=timezone.utc)
        result = manager.edit_scheduled_draft(
            sd.scheduled_draft_id, new_send_time=new_time
        )
        assert result.scheduled_send_time == new_time
        assert sd.scheduled_send_time == new_time

    def test_edit_both_draft_and_send_time(
        self, manager: ScheduledDraftManager
    ) -> None:
        sd = manager.register_scheduled_draft(_make_draft(), _SEND_TIME)
        new_draft = _make_draft(recipient="carol@example.com")
        new_time = datetime(2026, 3, 1, 8, 0, tzinfo=timezone.utc)
        result = manager.edit_scheduled_draft(
            sd.scheduled_draft_id, new_draft=new_draft, new_send_time=new_time
        )
        assert result.draft.recipient == "carol@example.com"
        assert result.scheduled_send_time == new_time

    def test_edit_sent_draft_raises_already_sent_error(
        self, manager: ScheduledDraftManager, gate: ApprovalGateController
    ) -> None:
        sd = manager.register_scheduled_draft(_make_draft(), _SEND_TIME)
        manager.trigger_send_time_confirmation(
            sd.scheduled_draft_id,
            gate,
            decision_callback=lambda: ApprovalDecision.CONFIRMED,
        )
        assert sd.status == ScheduledDraftStatus.SENT

        with pytest.raises(ScheduledDraftAlreadySentError):
            manager.edit_scheduled_draft(sd.scheduled_draft_id, new_draft=_make_draft())

    def test_edit_cancelled_draft_raises_already_cancelled_error(
        self, manager: ScheduledDraftManager
    ) -> None:
        sd = manager.register_scheduled_draft(_make_draft(), _SEND_TIME)
        manager.cancel_scheduled_draft(sd.scheduled_draft_id)

        with pytest.raises(ScheduledDraftAlreadyCancelledError):
            manager.edit_scheduled_draft(sd.scheduled_draft_id, new_draft=_make_draft())

    def test_edit_unknown_id_raises_not_found_error(
        self, manager: ScheduledDraftManager
    ) -> None:
        with pytest.raises(ScheduledDraftNotFoundError):
            manager.edit_scheduled_draft("nonexistent-id", new_draft=_make_draft())


# ---------------------------------------------------------------------------
# Flow 3: register → send-time confirmation → send (CONFIRMED)
# ---------------------------------------------------------------------------


class TestRegisterConfirmSend:
    def test_confirmed_callback_sets_status_to_sent(
        self, manager: ScheduledDraftManager, gate: ApprovalGateController
    ) -> None:
        sd = manager.register_scheduled_draft(_make_draft(), _SEND_TIME)
        result = manager.trigger_send_time_confirmation(
            sd.scheduled_draft_id,
            gate,
            decision_callback=lambda: ApprovalDecision.CONFIRMED,
        )
        assert result == ApprovalDecision.CONFIRMED
        assert sd.status == ScheduledDraftStatus.SENT

    def test_confirmed_returns_approval_decision_confirmed(
        self, manager: ScheduledDraftManager, gate: ApprovalGateController
    ) -> None:
        sd = manager.register_scheduled_draft(_make_draft(), _SEND_TIME)
        result = manager.trigger_send_time_confirmation(
            sd.scheduled_draft_id,
            gate,
            decision_callback=lambda: ApprovalDecision.CONFIRMED,
        )
        assert result == ApprovalDecision.CONFIRMED


# ---------------------------------------------------------------------------
# Flow 4: register → timeout → hold (no callback)
# ---------------------------------------------------------------------------


class TestRegisterTimeoutHold:
    def test_no_callback_sets_status_to_held(
        self, manager: ScheduledDraftManager, gate: ApprovalGateController
    ) -> None:
        sd = manager.register_scheduled_draft(_make_draft(), _SEND_TIME)
        result = manager.trigger_send_time_confirmation(
            sd.scheduled_draft_id,
            gate,
            decision_callback=None,
        )
        assert isinstance(result, TimeoutResult)
        assert sd.status == ScheduledDraftStatus.HELD

    def test_no_callback_returns_timeout_result(
        self, manager: ScheduledDraftManager, gate: ApprovalGateController
    ) -> None:
        sd = manager.register_scheduled_draft(_make_draft(), _SEND_TIME)
        result = manager.trigger_send_time_confirmation(
            sd.scheduled_draft_id,
            gate,
            decision_callback=None,
        )
        assert isinstance(result, TimeoutResult)

    def test_timeout_result_contains_correct_draft_id(
        self, manager: ScheduledDraftManager, gate: ApprovalGateController
    ) -> None:
        sd = manager.register_scheduled_draft(_make_draft(), _SEND_TIME)
        result = manager.trigger_send_time_confirmation(
            sd.scheduled_draft_id,
            gate,
            decision_callback=None,
        )
        assert isinstance(result, TimeoutResult)
        assert result.held_draft_id == sd.scheduled_draft_id


# ---------------------------------------------------------------------------
# list_scheduled_drafts
# ---------------------------------------------------------------------------


class TestListScheduledDrafts:
    def test_returns_all_drafts_in_reverse_registration_order(
        self, manager: ScheduledDraftManager
    ) -> None:
        sd1 = manager.register_scheduled_draft(_make_draft(), _SEND_TIME)
        sd2 = manager.register_scheduled_draft(_make_draft(), _SEND_TIME)
        sd3 = manager.register_scheduled_draft(_make_draft(), _SEND_TIME)

        drafts = manager.list_scheduled_drafts()
        assert len(drafts) == 3
        # Most-recently-registered first.
        assert drafts[0].scheduled_draft_id == sd3.scheduled_draft_id
        assert drafts[1].scheduled_draft_id == sd2.scheduled_draft_id
        assert drafts[2].scheduled_draft_id == sd1.scheduled_draft_id

    def test_status_filter_returns_only_matching_drafts(
        self, manager: ScheduledDraftManager
    ) -> None:
        sd1 = manager.register_scheduled_draft(_make_draft(), _SEND_TIME)
        sd2 = manager.register_scheduled_draft(_make_draft(), _SEND_TIME)
        manager.cancel_scheduled_draft(sd2.scheduled_draft_id)

        pending = manager.list_scheduled_drafts(
            status_filter=ScheduledDraftStatus.PENDING
        )
        cancelled = manager.list_scheduled_drafts(
            status_filter=ScheduledDraftStatus.CANCELLED
        )

        assert len(pending) == 1
        assert pending[0].scheduled_draft_id == sd1.scheduled_draft_id
        assert len(cancelled) == 1
        assert cancelled[0].scheduled_draft_id == sd2.scheduled_draft_id

    def test_status_filter_returns_empty_list_when_no_match(
        self, manager: ScheduledDraftManager
    ) -> None:
        manager.register_scheduled_draft(_make_draft(), _SEND_TIME)
        result = manager.list_scheduled_drafts(
            status_filter=ScheduledDraftStatus.SENT
        )
        assert result == []

    def test_empty_manager_returns_empty_list(
        self, manager: ScheduledDraftManager
    ) -> None:
        assert manager.list_scheduled_drafts() == []


# ---------------------------------------------------------------------------
# get_scheduled_draft
# ---------------------------------------------------------------------------


class TestGetScheduledDraft:
    def test_returns_draft_by_id(self, manager: ScheduledDraftManager) -> None:
        sd = manager.register_scheduled_draft(_make_draft(), _SEND_TIME)
        retrieved = manager.get_scheduled_draft(sd.scheduled_draft_id)
        assert retrieved.scheduled_draft_id == sd.scheduled_draft_id

    def test_raises_not_found_error_for_unknown_id(
        self, manager: ScheduledDraftManager
    ) -> None:
        with pytest.raises(ScheduledDraftNotFoundError):
            manager.get_scheduled_draft("unknown-id-xyz")


# ---------------------------------------------------------------------------
# trigger_send_time_confirmation — error cases
# ---------------------------------------------------------------------------


class TestTriggerSendTimeConfirmationErrors:
    def test_raises_already_sent_error_if_already_sent(
        self, manager: ScheduledDraftManager, gate: ApprovalGateController
    ) -> None:
        sd = manager.register_scheduled_draft(_make_draft(), _SEND_TIME)
        manager.trigger_send_time_confirmation(
            sd.scheduled_draft_id,
            gate,
            decision_callback=lambda: ApprovalDecision.CONFIRMED,
        )
        assert sd.status == ScheduledDraftStatus.SENT

        with pytest.raises(ScheduledDraftAlreadySentError):
            manager.trigger_send_time_confirmation(
                sd.scheduled_draft_id,
                gate,
                decision_callback=lambda: ApprovalDecision.CONFIRMED,
            )

    def test_raises_already_cancelled_error_if_cancelled(
        self, manager: ScheduledDraftManager, gate: ApprovalGateController
    ) -> None:
        sd = manager.register_scheduled_draft(_make_draft(), _SEND_TIME)
        manager.cancel_scheduled_draft(sd.scheduled_draft_id)

        with pytest.raises(ScheduledDraftAlreadyCancelledError):
            manager.trigger_send_time_confirmation(
                sd.scheduled_draft_id,
                gate,
                decision_callback=lambda: ApprovalDecision.CONFIRMED,
            )

    def test_raises_not_found_error_for_unknown_id(
        self, manager: ScheduledDraftManager, gate: ApprovalGateController
    ) -> None:
        with pytest.raises(ScheduledDraftNotFoundError):
            manager.trigger_send_time_confirmation(
                "nonexistent-id",
                gate,
                decision_callback=lambda: ApprovalDecision.CONFIRMED,
            )

    def test_cancelled_callback_reverts_status_to_pending(
        self, manager: ScheduledDraftManager, gate: ApprovalGateController
    ) -> None:
        """A CANCELLED decision at confirmation time reverts status to pending."""
        sd = manager.register_scheduled_draft(_make_draft(), _SEND_TIME)
        result = manager.trigger_send_time_confirmation(
            sd.scheduled_draft_id,
            gate,
            decision_callback=lambda: ApprovalDecision.CANCELLED,
        )
        assert result == ApprovalDecision.CANCELLED
        assert sd.status == ScheduledDraftStatus.PENDING

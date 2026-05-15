"""
Integration tests for the full scheduled draft lifecycle (Task 14.4).

Verifies that all four flows are correctly wired end-to-end:

Flow 1: register → edit → cancel
    UserInstruction(type="schedule") → present_schedule_gate → [confirmed]
    → register_scheduled_draft → AuditLogger.log(SCHEDULED_DRAFT_REGISTERED)
    → edit_scheduled_draft → cancel_scheduled_draft
    → AuditLogger.log(SCHEDULED_DRAFT_CANCELLED)

Flow 2: register → send-time confirmation → send
    trigger_send_time_confirmation(id, gate, callback=CONFIRMED) → status=sent

Flow 3: register → timeout → hold
    trigger_send_time_confirmation(id, gate, callback=None) → status=held
    → TimeoutResult returned

Flow 4: register → cancel (via orchestrator)
    UserInstruction(type="cancel_schedule") → cancel_scheduled_draft
    → AuditLogger.log(SCHEDULED_DRAFT_CANCELLED)

Requirements: 7.3, 7.4, 7.5, 7.6
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from src.approval.approval_gate_controller import ApprovalGateController
from src.audit.audit_logger import AuditLogger
from src.auth.session_manager import SessionManager
from src.gmail.gmail_client import GmailClient
from src.integration.factory import create_orchestrator
from src.models.types import (
    AgentResponse,
    AgentResponseType,
    ApprovalDecision,
    AuditEventType,
    ContextSummary,
    Draft,
    ScheduledDraft,
    ScheduledDraftStatus,
    SessionContext,
    TimeoutResult,
    UserInstruction,
)
from src.orchestrator.agent_orchestrator import AgentOrchestrator
from src.permissions.permission_manager import PermissionManager
from src.prompt.sanitiser import PromptSanitiser
from src.scheduling.scheduled_draft_manager import ScheduledDraftManager
from src.tone.tone_profile_engine import ToneProfileEngine


# ---------------------------------------------------------------------------
# Helpers / Fixtures
# ---------------------------------------------------------------------------


def _make_session_context(session_id: str | None = None) -> SessionContext:
    """Create a valid, non-expired SessionContext."""
    return SessionContext(
        session_id=session_id or str(uuid4()),
        user_id="user-test-001",
        created_at=datetime.now(tz=timezone.utc),
        last_active_at=datetime.now(tz=timezone.utc),
        expires_at=datetime.now(tz=timezone.utc) + timedelta(hours=1),
    )


def _make_context_summary() -> ContextSummary:
    return ContextSummary(generated_from_instruction_only=True)


def _make_draft(
    recipient: str = "alice@example.com",
    subject: str = "Test Subject",
    body: str = "Hello Alice, this is a test.",
) -> Draft:
    return Draft(
        recipient=recipient,
        subject=subject,
        body=body,
        context_summary=_make_context_summary(),
        generated_from_instruction="Schedule a test email to Alice",
    )


_SEND_TIME = datetime(2025, 12, 1, 9, 0, tzinfo=timezone.utc)


def _make_session_manager(session_ctx: SessionContext) -> SessionManager:
    sm = MagicMock(spec=SessionManager)
    sm.validate_session.return_value = session_ctx
    return sm


def _make_permission_manager() -> PermissionManager:
    pm = MagicMock(spec=PermissionManager)
    pm.check_permission.return_value = True
    return pm


def _make_orchestrator(
    session_ctx: SessionContext,
    audit_logger: AuditLogger | None = None,
    approval_gate: ApprovalGateController | None = None,
    scheduled_draft_manager: ScheduledDraftManager | None = None,
) -> AgentOrchestrator:
    """Assemble a minimal AgentOrchestrator for scheduled-draft lifecycle tests."""
    return AgentOrchestrator(
        session_manager=_make_session_manager(session_ctx),
        permission_manager=_make_permission_manager(),
        gmail_client=None,
        tone_engine=ToneProfileEngine(),
        prompt_builder=PromptSanitiser(),
        approval_gate=approval_gate or ApprovalGateController(),
        audit_logger=audit_logger or AuditLogger(),
        scheduled_draft_manager=scheduled_draft_manager or ScheduledDraftManager(),
        llm_client=None,
    )


def _schedule_instruction(
    session_id: str, draft: Draft, send_time: datetime
) -> UserInstruction:
    return UserInstruction(
        session_id=session_id,
        text="Schedule the draft",
        instruction_type="schedule",
        payload={"draft": draft, "send_time": send_time},
    )


def _cancel_schedule_instruction(
    session_id: str, scheduled_draft_id: str
) -> UserInstruction:
    return UserInstruction(
        session_id=session_id,
        text="Cancel the scheduled draft",
        instruction_type="cancel_schedule",
        payload=scheduled_draft_id,
    )


# ---------------------------------------------------------------------------
# Flow 1: register → edit → cancel
# ---------------------------------------------------------------------------


class TestFlow1RegisterEditCancel:
    def test_schedule_confirmed_registers_draft(self) -> None:
        """
        On CONFIRMED schedule gate, register_scheduled_draft is called and
        the response type is SCHEDULE_CONFIRMED.

        Requirements: 7.1, 7.2, 7.3
        """
        session_ctx = _make_session_context()
        audit_logger = AuditLogger()
        scheduled_draft_manager = ScheduledDraftManager()

        approval_gate = ApprovalGateController()

        def confirming_gate(draft, scheduled_time, decision_callback=None):
            return ApprovalDecision.CONFIRMED

        approval_gate.present_schedule_gate = confirming_gate  # type: ignore[method-assign]

        orchestrator = _make_orchestrator(
            session_ctx=session_ctx,
            audit_logger=audit_logger,
            approval_gate=approval_gate,
            scheduled_draft_manager=scheduled_draft_manager,
        )

        draft = _make_draft()
        instruction = _schedule_instruction(session_ctx.session_id, draft, _SEND_TIME)
        response = orchestrator.process_instruction(session_ctx, instruction)

        assert response.type == AgentResponseType.SCHEDULE_CONFIRMED
        assert response.success is True

        # Verify the draft was registered
        registered = scheduled_draft_manager.list_scheduled_drafts()
        assert len(registered) == 1
        assert registered[0].draft.draft_id == draft.draft_id
        assert registered[0].status == ScheduledDraftStatus.PENDING

    def test_schedule_confirmed_logs_scheduled_draft_registered(self) -> None:
        """
        On CONFIRMED, SCHEDULED_DRAFT_REGISTERED must be logged.

        Requirements: 7.3, 12.1
        """
        session_ctx = _make_session_context()
        audit_logger = AuditLogger()

        approval_gate = ApprovalGateController()

        def confirming_gate(draft, scheduled_time, decision_callback=None):
            return ApprovalDecision.CONFIRMED

        approval_gate.present_schedule_gate = confirming_gate  # type: ignore[method-assign]

        orchestrator = _make_orchestrator(
            session_ctx=session_ctx,
            audit_logger=audit_logger,
            approval_gate=approval_gate,
        )

        draft = _make_draft()
        instruction = _schedule_instruction(session_ctx.session_id, draft, _SEND_TIME)
        orchestrator.process_instruction(session_ctx, instruction)

        entries = audit_logger.query(event_type=AuditEventType.SCHEDULED_DRAFT_REGISTERED)
        assert len(entries) == 1
        assert entries[0].session_id == session_ctx.session_id

    def test_schedule_cancelled_does_not_register_draft(self) -> None:
        """
        On CANCELLED schedule gate, no draft is registered.

        Requirements: 7.2
        """
        session_ctx = _make_session_context()
        scheduled_draft_manager = ScheduledDraftManager()

        # Default gate with no callback → CANCELLED
        approval_gate = ApprovalGateController()

        orchestrator = _make_orchestrator(
            session_ctx=session_ctx,
            approval_gate=approval_gate,
            scheduled_draft_manager=scheduled_draft_manager,
        )

        draft = _make_draft()
        instruction = _schedule_instruction(session_ctx.session_id, draft, _SEND_TIME)
        response = orchestrator.process_instruction(session_ctx, instruction)

        assert response.type == AgentResponseType.CANCELLED
        assert scheduled_draft_manager.list_scheduled_drafts() == []

    def test_edit_scheduled_draft_updates_content(self) -> None:
        """
        After registration, edit_scheduled_draft updates the draft content.

        Requirements: 7.4
        """
        scheduled_draft_manager = ScheduledDraftManager()
        draft = _make_draft()
        sd = scheduled_draft_manager.register_scheduled_draft(draft, _SEND_TIME)

        new_draft = _make_draft(recipient="bob@example.com", subject="Updated Subject")
        updated = scheduled_draft_manager.edit_scheduled_draft(
            sd.scheduled_draft_id, new_draft=new_draft
        )

        assert updated.draft.recipient == "bob@example.com"
        assert updated.draft.subject == "Updated Subject"
        assert updated.status == ScheduledDraftStatus.PENDING

    def test_cancel_via_orchestrator_sets_status_cancelled(self) -> None:
        """
        cancel_schedule instruction cancels the draft and logs SCHEDULED_DRAFT_CANCELLED.

        Requirements: 7.4, 12.1
        """
        session_ctx = _make_session_context()
        audit_logger = AuditLogger()
        scheduled_draft_manager = ScheduledDraftManager()

        # Register a draft directly
        draft = _make_draft()
        sd = scheduled_draft_manager.register_scheduled_draft(draft, _SEND_TIME)

        approval_gate = ApprovalGateController()
        orchestrator = _make_orchestrator(
            session_ctx=session_ctx,
            audit_logger=audit_logger,
            approval_gate=approval_gate,
            scheduled_draft_manager=scheduled_draft_manager,
        )

        instruction = _cancel_schedule_instruction(
            session_ctx.session_id, sd.scheduled_draft_id
        )
        response = orchestrator.process_instruction(session_ctx, instruction)

        assert response.success is True
        assert sd.status == ScheduledDraftStatus.CANCELLED

        entries = audit_logger.query(event_type=AuditEventType.SCHEDULED_DRAFT_CANCELLED)
        assert len(entries) == 1
        assert entries[0].session_id == session_ctx.session_id

    def test_full_flow1_register_edit_cancel(self) -> None:
        """
        Full Flow 1: schedule → confirm → register → edit → cancel.

        Requirements: 7.1, 7.2, 7.3, 7.4, 12.1
        """
        session_ctx = _make_session_context()
        audit_logger = AuditLogger()
        scheduled_draft_manager = ScheduledDraftManager()

        approval_gate = ApprovalGateController()

        def confirming_gate(draft, scheduled_time, decision_callback=None):
            return ApprovalDecision.CONFIRMED

        approval_gate.present_schedule_gate = confirming_gate  # type: ignore[method-assign]

        orchestrator = _make_orchestrator(
            session_ctx=session_ctx,
            audit_logger=audit_logger,
            approval_gate=approval_gate,
            scheduled_draft_manager=scheduled_draft_manager,
        )

        # Step 1: Schedule (register)
        draft = _make_draft()
        schedule_instr = _schedule_instruction(session_ctx.session_id, draft, _SEND_TIME)
        schedule_response = orchestrator.process_instruction(session_ctx, schedule_instr)
        assert schedule_response.type == AgentResponseType.SCHEDULE_CONFIRMED

        sd: ScheduledDraft = schedule_response.payload
        assert sd.status == ScheduledDraftStatus.PENDING

        # Step 2: Edit
        new_draft = _make_draft(recipient="carol@example.com")
        scheduled_draft_manager.edit_scheduled_draft(
            sd.scheduled_draft_id, new_draft=new_draft
        )
        assert sd.draft.recipient == "carol@example.com"

        # Step 3: Cancel via orchestrator
        cancel_instr = _cancel_schedule_instruction(
            session_ctx.session_id, sd.scheduled_draft_id
        )
        cancel_response = orchestrator.process_instruction(session_ctx, cancel_instr)
        assert cancel_response.success is True
        assert sd.status == ScheduledDraftStatus.CANCELLED

        # Verify audit log
        registered_entries = audit_logger.query(
            event_type=AuditEventType.SCHEDULED_DRAFT_REGISTERED
        )
        cancelled_entries = audit_logger.query(
            event_type=AuditEventType.SCHEDULED_DRAFT_CANCELLED
        )
        assert len(registered_entries) == 1
        assert len(cancelled_entries) == 1


# ---------------------------------------------------------------------------
# Flow 2: register → send-time confirmation → send
# ---------------------------------------------------------------------------


class TestFlow2RegisterConfirmSend:
    def test_trigger_send_time_confirmation_confirmed_sets_status_sent(self) -> None:
        """
        trigger_send_time_confirmation with CONFIRMED callback sets status to sent.

        Requirements: 7.5
        """
        manager = ScheduledDraftManager()
        gate = ApprovalGateController()

        draft = _make_draft()
        sd = manager.register_scheduled_draft(draft, _SEND_TIME)

        result = manager.trigger_send_time_confirmation(
            sd.scheduled_draft_id,
            gate,
            decision_callback=lambda: ApprovalDecision.CONFIRMED,
        )

        assert result == ApprovalDecision.CONFIRMED
        assert sd.status == ScheduledDraftStatus.SENT

    def test_trigger_send_time_confirmation_delegates_to_approval_gate(self) -> None:
        """
        trigger_send_time_confirmation delegates to
        ApprovalGateController.present_scheduled_send_confirmation.

        Requirements: 7.5
        """
        manager = ScheduledDraftManager()
        gate = MagicMock(spec=ApprovalGateController)
        gate.present_scheduled_send_confirmation.return_value = ApprovalDecision.CONFIRMED

        draft = _make_draft()
        sd = manager.register_scheduled_draft(draft, _SEND_TIME)

        manager.trigger_send_time_confirmation(
            sd.scheduled_draft_id,
            gate,
            decision_callback=lambda: ApprovalDecision.CONFIRMED,
        )

        gate.present_scheduled_send_confirmation.assert_called_once()
        call_args = gate.present_scheduled_send_confirmation.call_args
        # First positional arg should be the ScheduledDraft
        passed_draft = call_args.args[0] if call_args.args else call_args.kwargs.get(
            "scheduled_draft"
        )
        assert passed_draft is sd

    def test_gate_history_records_scheduled_send_confirmation(self) -> None:
        """
        present_scheduled_send_confirmation records the gate presentation.

        Requirements: 7.5
        """
        manager = ScheduledDraftManager()
        gate = ApprovalGateController()

        draft = _make_draft()
        sd = manager.register_scheduled_draft(draft, _SEND_TIME)

        manager.trigger_send_time_confirmation(
            sd.scheduled_draft_id,
            gate,
            decision_callback=lambda: ApprovalDecision.CONFIRMED,
        )

        history = gate.get_gate_history()
        assert len(history) == 1
        assert history[0]["gate_type"] == "scheduled_send_confirmation"
        assert history[0]["scheduled_draft_id"] == sd.scheduled_draft_id


# ---------------------------------------------------------------------------
# Flow 3: register → timeout → hold
# ---------------------------------------------------------------------------


class TestFlow3RegisterTimeoutHold:
    def test_no_callback_returns_timeout_result(self) -> None:
        """
        trigger_send_time_confirmation with no callback returns TimeoutResult.

        Requirements: 7.6
        """
        manager = ScheduledDraftManager()
        gate = ApprovalGateController()

        draft = _make_draft()
        sd = manager.register_scheduled_draft(draft, _SEND_TIME)

        result = manager.trigger_send_time_confirmation(
            sd.scheduled_draft_id,
            gate,
            decision_callback=None,
        )

        assert isinstance(result, TimeoutResult)
        assert result.held_draft_id == sd.scheduled_draft_id

    def test_no_callback_sets_status_to_held(self) -> None:
        """
        trigger_send_time_confirmation with no callback sets status to held.

        Requirements: 7.6
        """
        manager = ScheduledDraftManager()
        gate = ApprovalGateController()

        draft = _make_draft()
        sd = manager.register_scheduled_draft(draft, _SEND_TIME)

        manager.trigger_send_time_confirmation(
            sd.scheduled_draft_id,
            gate,
            decision_callback=None,
        )

        assert sd.status == ScheduledDraftStatus.HELD

    def test_held_draft_is_not_sent(self) -> None:
        """
        A held draft must not be sent — status must be held, not sent.

        Requirements: 7.6
        """
        manager = ScheduledDraftManager()
        gate = ApprovalGateController()

        draft = _make_draft()
        sd = manager.register_scheduled_draft(draft, _SEND_TIME)

        result = manager.trigger_send_time_confirmation(
            sd.scheduled_draft_id,
            gate,
            decision_callback=None,
        )

        assert sd.status != ScheduledDraftStatus.SENT
        assert sd.status == ScheduledDraftStatus.HELD
        assert isinstance(result, TimeoutResult)


# ---------------------------------------------------------------------------
# Flow 4: register → cancel (via orchestrator)
# ---------------------------------------------------------------------------


class TestFlow4CancelViaOrchestrator:
    def test_cancel_schedule_instruction_cancels_draft(self) -> None:
        """
        cancel_schedule instruction calls cancel_scheduled_draft.

        Requirements: 7.4
        """
        session_ctx = _make_session_context()
        scheduled_draft_manager = ScheduledDraftManager()

        draft = _make_draft()
        sd = scheduled_draft_manager.register_scheduled_draft(draft, _SEND_TIME)

        orchestrator = _make_orchestrator(
            session_ctx=session_ctx,
            scheduled_draft_manager=scheduled_draft_manager,
        )

        instruction = _cancel_schedule_instruction(
            session_ctx.session_id, sd.scheduled_draft_id
        )
        response = orchestrator.process_instruction(session_ctx, instruction)

        assert response.success is True
        assert sd.status == ScheduledDraftStatus.CANCELLED

    def test_cancel_schedule_instruction_logs_scheduled_draft_cancelled(self) -> None:
        """
        cancel_schedule instruction logs SCHEDULED_DRAFT_CANCELLED.

        Requirements: 7.4, 12.1
        """
        session_ctx = _make_session_context()
        audit_logger = AuditLogger()
        scheduled_draft_manager = ScheduledDraftManager()

        draft = _make_draft()
        sd = scheduled_draft_manager.register_scheduled_draft(draft, _SEND_TIME)

        orchestrator = _make_orchestrator(
            session_ctx=session_ctx,
            audit_logger=audit_logger,
            scheduled_draft_manager=scheduled_draft_manager,
        )

        instruction = _cancel_schedule_instruction(
            session_ctx.session_id, sd.scheduled_draft_id
        )
        orchestrator.process_instruction(session_ctx, instruction)

        entries = audit_logger.query(event_type=AuditEventType.SCHEDULED_DRAFT_CANCELLED)
        assert len(entries) == 1
        assert entries[0].session_id == session_ctx.session_id
        assert entries[0].metadata.get("scheduled_draft_id") == sd.scheduled_draft_id

    def test_cancel_schedule_unknown_id_returns_error_response(self) -> None:
        """
        cancel_schedule with an unknown ID returns an error AgentResponse.

        Requirements: 7.4
        """
        session_ctx = _make_session_context()
        orchestrator = _make_orchestrator(session_ctx=session_ctx)

        instruction = _cancel_schedule_instruction(
            session_ctx.session_id, "nonexistent-id"
        )
        response = orchestrator.process_instruction(session_ctx, instruction)

        assert response.success is False
        assert response.type == AgentResponseType.ERROR

    def test_cancel_schedule_response_payload_contains_cancelled_id(self) -> None:
        """
        The cancel_schedule response payload must include the cancelled draft ID.

        Requirements: 7.4
        """
        session_ctx = _make_session_context()
        scheduled_draft_manager = ScheduledDraftManager()

        draft = _make_draft()
        sd = scheduled_draft_manager.register_scheduled_draft(draft, _SEND_TIME)

        orchestrator = _make_orchestrator(
            session_ctx=session_ctx,
            scheduled_draft_manager=scheduled_draft_manager,
        )

        instruction = _cancel_schedule_instruction(
            session_ctx.session_id, sd.scheduled_draft_id
        )
        response = orchestrator.process_instruction(session_ctx, instruction)

        assert response.payload["cancelled_scheduled_draft_id"] == sd.scheduled_draft_id


# ---------------------------------------------------------------------------
# Factory wiring verification
# ---------------------------------------------------------------------------


class TestFactoryWiresScheduledDraftManager:
    def test_create_orchestrator_wires_scheduled_draft_manager(self) -> None:
        """
        create_orchestrator must wire a ScheduledDraftManager into the orchestrator.

        Requirements: 7.3
        """
        session_manager = MagicMock(spec=SessionManager)
        permission_manager = MagicMock(spec=PermissionManager)

        orchestrator = create_orchestrator(
            session_manager=session_manager,
            permission_manager=permission_manager,
        )

        assert isinstance(orchestrator._scheduled_draft_manager, ScheduledDraftManager)

    def test_factory_orchestrator_schedule_flow_works_end_to_end(self) -> None:
        """
        The factory-assembled orchestrator must correctly execute the schedule flow.

        Requirements: 7.1, 7.2, 7.3, 12.1
        """
        session_ctx = _make_session_context()
        audit_logger = AuditLogger()

        session_manager = MagicMock(spec=SessionManager)
        session_manager.validate_session.return_value = session_ctx

        permission_manager = MagicMock(spec=PermissionManager)
        permission_manager.check_permission.return_value = True

        orchestrator = create_orchestrator(
            session_manager=session_manager,
            permission_manager=permission_manager,
            audit_logger=audit_logger,
        )

        # Inject a confirming callback into the approval gate
        def confirming_gate(draft, scheduled_time, decision_callback=None):
            return ApprovalDecision.CONFIRMED

        orchestrator._approval_gate.present_schedule_gate = confirming_gate  # type: ignore[method-assign]

        draft = _make_draft()
        instruction = _schedule_instruction(session_ctx.session_id, draft, _SEND_TIME)
        response = orchestrator.process_instruction(session_ctx, instruction)

        assert response.type == AgentResponseType.SCHEDULE_CONFIRMED
        assert response.success is True

        registered_entries = audit_logger.query(
            event_type=AuditEventType.SCHEDULED_DRAFT_REGISTERED
        )
        assert len(registered_entries) == 1

    def test_factory_orchestrator_cancel_schedule_flow_works_end_to_end(self) -> None:
        """
        The factory-assembled orchestrator must correctly execute the cancel flow.

        Requirements: 7.4, 12.1
        """
        session_ctx = _make_session_context()
        audit_logger = AuditLogger()

        session_manager = MagicMock(spec=SessionManager)
        session_manager.validate_session.return_value = session_ctx

        permission_manager = MagicMock(spec=PermissionManager)
        permission_manager.check_permission.return_value = True

        orchestrator = create_orchestrator(
            session_manager=session_manager,
            permission_manager=permission_manager,
            audit_logger=audit_logger,
        )

        # Register a draft directly via the manager
        draft = _make_draft()
        sd = orchestrator._scheduled_draft_manager.register_scheduled_draft(
            draft, _SEND_TIME
        )

        instruction = _cancel_schedule_instruction(
            session_ctx.session_id, sd.scheduled_draft_id
        )
        response = orchestrator.process_instruction(session_ctx, instruction)

        assert response.success is True
        assert sd.status == ScheduledDraftStatus.CANCELLED

        cancelled_entries = audit_logger.query(
            event_type=AuditEventType.SCHEDULED_DRAFT_CANCELLED
        )
        assert len(cancelled_entries) == 1


# ---------------------------------------------------------------------------
# Orchestrator wiring verification
# ---------------------------------------------------------------------------


class TestOrchestratorScheduleHandlerWiring:
    def test_handle_schedule_calls_present_schedule_gate(self) -> None:
        """
        _handle_schedule_instruction must call present_schedule_gate.

        Requirements: 7.1
        """
        session_ctx = _make_session_context()
        approval_gate = MagicMock(spec=ApprovalGateController)
        approval_gate.present_schedule_gate.return_value = ApprovalDecision.CANCELLED

        orchestrator = _make_orchestrator(
            session_ctx=session_ctx,
            approval_gate=approval_gate,
        )

        draft = _make_draft()
        instruction = _schedule_instruction(session_ctx.session_id, draft, _SEND_TIME)
        orchestrator.process_instruction(session_ctx, instruction)

        approval_gate.present_schedule_gate.assert_called_once()

    def test_handle_schedule_confirmed_calls_register_scheduled_draft(self) -> None:
        """
        On CONFIRMED, register_scheduled_draft must be called.

        Requirements: 7.3
        """
        session_ctx = _make_session_context()
        scheduled_draft_manager = MagicMock(spec=ScheduledDraftManager)
        scheduled_draft_manager.register_scheduled_draft.return_value = ScheduledDraft(
            draft=_make_draft(),
            scheduled_send_time=_SEND_TIME,
        )

        approval_gate = ApprovalGateController()

        def confirming_gate(draft, scheduled_time, decision_callback=None):
            return ApprovalDecision.CONFIRMED

        approval_gate.present_schedule_gate = confirming_gate  # type: ignore[method-assign]

        orchestrator = _make_orchestrator(
            session_ctx=session_ctx,
            approval_gate=approval_gate,
            scheduled_draft_manager=scheduled_draft_manager,
        )

        draft = _make_draft()
        instruction = _schedule_instruction(session_ctx.session_id, draft, _SEND_TIME)
        orchestrator.process_instruction(session_ctx, instruction)

        scheduled_draft_manager.register_scheduled_draft.assert_called_once_with(
            draft=draft,
            send_time=_SEND_TIME,
        )

    def test_handle_cancel_schedule_calls_cancel_scheduled_draft(self) -> None:
        """
        _handle_cancel_schedule_instruction must call cancel_scheduled_draft.

        Requirements: 7.4
        """
        session_ctx = _make_session_context()
        scheduled_draft_manager = MagicMock(spec=ScheduledDraftManager)
        scheduled_draft_manager.cancel_scheduled_draft.return_value = None

        orchestrator = _make_orchestrator(
            session_ctx=session_ctx,
            scheduled_draft_manager=scheduled_draft_manager,
        )

        instruction = _cancel_schedule_instruction(
            session_ctx.session_id, "some-draft-id"
        )
        orchestrator.process_instruction(session_ctx, instruction)

        scheduled_draft_manager.cancel_scheduled_draft.assert_called_once_with(
            "some-draft-id"
        )

    def test_approval_gate_presented_logged_before_schedule_gate(self) -> None:
        """
        APPROVAL_GATE_PRESENTED must be logged before present_schedule_gate is called.

        Requirements: 7.1, 12.1
        """
        session_ctx = _make_session_context()
        audit_logger = AuditLogger()
        call_order: list[str] = []

        original_log = audit_logger.log

        def spy_log(event_type, **kwargs):
            call_order.append(f"log:{event_type.value}")
            return original_log(event_type=event_type, **kwargs)

        audit_logger.log = spy_log  # type: ignore[method-assign]

        approval_gate = ApprovalGateController()

        def spy_gate(draft, scheduled_time, decision_callback=None):
            call_order.append("present_schedule_gate")
            return ApprovalDecision.CANCELLED

        approval_gate.present_schedule_gate = spy_gate  # type: ignore[method-assign]

        orchestrator = _make_orchestrator(
            session_ctx=session_ctx,
            audit_logger=audit_logger,
            approval_gate=approval_gate,
        )

        draft = _make_draft()
        instruction = _schedule_instruction(session_ctx.session_id, draft, _SEND_TIME)
        orchestrator.process_instruction(session_ctx, instruction)

        gate_log_idx = next(
            i for i, c in enumerate(call_order)
            if c == f"log:{AuditEventType.APPROVAL_GATE_PRESENTED.value}"
        )
        present_idx = call_order.index("present_schedule_gate")
        assert gate_log_idx < present_idx, (
            f"APPROVAL_GATE_PRESENTED was logged at position {gate_log_idx} "
            f"but present_schedule_gate was called at position {present_idx}. "
            "The log must come first."
        )

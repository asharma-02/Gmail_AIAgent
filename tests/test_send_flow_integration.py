"""
Integration tests for the full send flow (Task 14.2).

Verifies that the send flow is correctly wired end-to-end:

    Draft
      → ApprovalGateController.present_send_gate (with ContextSummary)
      → [user confirms]
      → GmailClient.send_message
      → AuditLogger.log(EMAIL_SENT)
      → AgentResponse(type=SEND_CONFIRMED)

Also verifies that factory.create_orchestrator correctly wires all components
needed for the send flow.

Requirements: 5.1, 5.2, 5.3, 12.1
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, call, patch
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
    GmailScope,
    OAuthToken,
    PermissionScope,
    SessionContext,
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
        generated_from_instruction="Send a test email to Alice",
    )


def _make_session_manager(session_ctx: SessionContext) -> SessionManager:
    """Return a SessionManager that always validates to the given session."""
    sm = MagicMock(spec=SessionManager)
    sm.validate_session.return_value = session_ctx
    return sm


def _make_permission_manager() -> PermissionManager:
    """Return a PermissionManager that always grants permission."""
    pm = MagicMock(spec=PermissionManager)
    pm.check_permission.return_value = True
    return pm


def _make_gmail_client(sent_message_id: str = "msg-sent-001") -> MagicMock:
    """Return a mock GmailClient whose send_message returns a fixed message ID."""
    gc = MagicMock(spec=GmailClient)
    gc.send_message.return_value = sent_message_id
    return gc


def _make_orchestrator(
    session_ctx: SessionContext,
    gmail_client: MagicMock | None = None,
    audit_logger: AuditLogger | None = None,
    approval_gate: ApprovalGateController | None = None,
) -> AgentOrchestrator:
    """Assemble a minimal AgentOrchestrator for send-flow tests."""
    return AgentOrchestrator(
        session_manager=_make_session_manager(session_ctx),
        permission_manager=_make_permission_manager(),
        gmail_client=gmail_client or _make_gmail_client(),
        tone_engine=ToneProfileEngine(),
        prompt_builder=PromptSanitiser(),
        approval_gate=approval_gate or ApprovalGateController(),
        audit_logger=audit_logger or AuditLogger(),
        scheduled_draft_manager=ScheduledDraftManager(),
        llm_client=None,
    )


def _send_instruction(session_id: str, draft: Draft) -> UserInstruction:
    return UserInstruction(
        session_id=session_id,
        text="Send the draft",
        instruction_type="send",
        payload=draft,
    )


# ---------------------------------------------------------------------------
# 1. APPROVAL_GATE_PRESENTED is logged BEFORE the gate is presented
# ---------------------------------------------------------------------------


class TestApprovalGatePresentedLoggedBeforeSend:
    def test_approval_gate_presented_logged_before_gate_call(self) -> None:
        """
        APPROVAL_GATE_PRESENTED must be logged before present_send_gate is called.

        Requirements: 5.1, 12.1
        """
        session_ctx = _make_session_context()
        audit_logger = AuditLogger()
        call_order: list[str] = []

        # Spy on audit_logger.log to record call order
        original_log = audit_logger.log

        def spy_log(event_type, **kwargs):
            call_order.append(f"log:{event_type.value}")
            return original_log(event_type=event_type, **kwargs)

        audit_logger.log = spy_log  # type: ignore[method-assign]

        # Spy on approval gate to record when it's called
        approval_gate = ApprovalGateController()
        original_present = approval_gate.present_send_gate

        def spy_present_send_gate(draft, context_summary, decision_callback=None):
            call_order.append("present_send_gate")
            return ApprovalDecision.CANCELLED  # cancel to avoid needing gmail

        approval_gate.present_send_gate = spy_present_send_gate  # type: ignore[method-assign]

        orchestrator = _make_orchestrator(
            session_ctx=session_ctx,
            audit_logger=audit_logger,
            approval_gate=approval_gate,
        )

        draft = _make_draft()
        instruction = _send_instruction(session_ctx.session_id, draft)
        orchestrator.process_instruction(session_ctx, instruction)

        # APPROVAL_GATE_PRESENTED must appear before present_send_gate in call_order
        gate_log_idx = next(
            i for i, c in enumerate(call_order)
            if c == f"log:{AuditEventType.APPROVAL_GATE_PRESENTED.value}"
        )
        present_idx = call_order.index("present_send_gate")
        assert gate_log_idx < present_idx, (
            f"APPROVAL_GATE_PRESENTED was logged at position {gate_log_idx} "
            f"but present_send_gate was called at position {present_idx}. "
            "The log must come first."
        )


# ---------------------------------------------------------------------------
# 2. present_send_gate receives both Draft and draft.context_summary
# ---------------------------------------------------------------------------


class TestPresentSendGateReceivesCorrectArguments:
    def test_present_send_gate_called_with_draft_and_context_summary(self) -> None:
        """
        present_send_gate must receive the Draft and its context_summary.

        Requirements: 5.1
        """
        session_ctx = _make_session_context()
        approval_gate = MagicMock(spec=ApprovalGateController)
        approval_gate.present_send_gate.return_value = ApprovalDecision.CANCELLED

        orchestrator = _make_orchestrator(
            session_ctx=session_ctx,
            approval_gate=approval_gate,
        )

        draft = _make_draft()
        instruction = _send_instruction(session_ctx.session_id, draft)
        orchestrator.process_instruction(session_ctx, instruction)

        approval_gate.present_send_gate.assert_called_once()
        call_kwargs = approval_gate.present_send_gate.call_args

        # Verify draft argument
        assert call_kwargs.kwargs.get("draft") == draft or call_kwargs.args[0] == draft

        # Verify context_summary argument matches draft.context_summary
        passed_summary = (
            call_kwargs.kwargs.get("context_summary")
            or (call_kwargs.args[1] if len(call_kwargs.args) > 1 else None)
        )
        assert passed_summary is draft.context_summary, (
            "present_send_gate must receive draft.context_summary as context_summary"
        )


# ---------------------------------------------------------------------------
# 3. On CONFIRMED: send_message called, then EMAIL_SENT logged
# ---------------------------------------------------------------------------


class TestConfirmedSendFlow:
    def test_send_message_called_on_confirmed(self) -> None:
        """
        When the gate is CONFIRMED, gmail_client.send_message must be called.

        Requirements: 5.3
        """
        session_ctx = _make_session_context()
        gmail_client = _make_gmail_client(sent_message_id="msg-001")

        approval_gate = ApprovalGateController()
        # Inject a callback that always confirms
        original_present = approval_gate.present_send_gate

        def confirming_gate(draft, context_summary, decision_callback=None):
            return ApprovalDecision.CONFIRMED

        approval_gate.present_send_gate = confirming_gate  # type: ignore[method-assign]

        orchestrator = _make_orchestrator(
            session_ctx=session_ctx,
            gmail_client=gmail_client,
            approval_gate=approval_gate,
        )

        draft = _make_draft(recipient="bob@example.com", subject="Hello Bob")
        instruction = _send_instruction(session_ctx.session_id, draft)
        orchestrator.process_instruction(session_ctx, instruction)

        gmail_client.send_message.assert_called_once_with(
            to=draft.recipient,
            subject=draft.subject,
            body=draft.body,
            cc=None,
        )

    def test_email_sent_logged_after_send_on_confirmed(self) -> None:
        """
        EMAIL_SENT must be logged after send_message succeeds.

        Requirements: 5.3, 12.1
        """
        session_ctx = _make_session_context()
        audit_logger = AuditLogger()
        gmail_client = _make_gmail_client(sent_message_id="msg-sent-xyz")

        approval_gate = ApprovalGateController()

        def confirming_gate(draft, context_summary, decision_callback=None):
            return ApprovalDecision.CONFIRMED

        approval_gate.present_send_gate = confirming_gate  # type: ignore[method-assign]

        orchestrator = _make_orchestrator(
            session_ctx=session_ctx,
            gmail_client=gmail_client,
            audit_logger=audit_logger,
            approval_gate=approval_gate,
        )

        draft = _make_draft()
        instruction = _send_instruction(session_ctx.session_id, draft)
        orchestrator.process_instruction(session_ctx, instruction)

        sent_entries = audit_logger.query(event_type=AuditEventType.EMAIL_SENT)
        assert len(sent_entries) == 1, "Exactly one EMAIL_SENT entry must be logged"
        assert sent_entries[0].session_id == session_ctx.session_id

    def test_send_message_called_before_email_sent_logged(self) -> None:
        """
        send_message must be called before EMAIL_SENT is logged.

        Requirements: 5.3, 12.1
        """
        session_ctx = _make_session_context()
        audit_logger = AuditLogger()
        call_order: list[str] = []

        gmail_client = MagicMock(spec=GmailClient)

        def spy_send_message(**kwargs):
            call_order.append("send_message")
            return "msg-001"

        gmail_client.send_message.side_effect = spy_send_message

        original_log = audit_logger.log

        def spy_log(event_type, **kwargs):
            call_order.append(f"log:{event_type.value}")
            return original_log(event_type=event_type, **kwargs)

        audit_logger.log = spy_log  # type: ignore[method-assign]

        approval_gate = ApprovalGateController()

        def confirming_gate(draft, context_summary, decision_callback=None):
            return ApprovalDecision.CONFIRMED

        approval_gate.present_send_gate = confirming_gate  # type: ignore[method-assign]

        orchestrator = _make_orchestrator(
            session_ctx=session_ctx,
            gmail_client=gmail_client,
            audit_logger=audit_logger,
            approval_gate=approval_gate,
        )

        draft = _make_draft()
        instruction = _send_instruction(session_ctx.session_id, draft)
        orchestrator.process_instruction(session_ctx, instruction)

        send_idx = call_order.index("send_message")
        email_sent_idx = call_order.index(f"log:{AuditEventType.EMAIL_SENT.value}")
        assert send_idx < email_sent_idx, (
            "send_message must be called before EMAIL_SENT is logged"
        )

    def test_response_type_is_send_confirmed_on_success(self) -> None:
        """
        AgentResponse.type must be SEND_CONFIRMED on successful send.

        Requirements: 5.3
        """
        session_ctx = _make_session_context()
        gmail_client = _make_gmail_client()

        approval_gate = ApprovalGateController()

        def confirming_gate(draft, context_summary, decision_callback=None):
            return ApprovalDecision.CONFIRMED

        approval_gate.present_send_gate = confirming_gate  # type: ignore[method-assign]

        orchestrator = _make_orchestrator(
            session_ctx=session_ctx,
            gmail_client=gmail_client,
            approval_gate=approval_gate,
        )

        draft = _make_draft()
        instruction = _send_instruction(session_ctx.session_id, draft)
        response = orchestrator.process_instruction(session_ctx, instruction)

        assert response.type == AgentResponseType.SEND_CONFIRMED
        assert response.success is True

    def test_response_payload_contains_sent_message_id(self) -> None:
        """
        The SEND_CONFIRMED response payload must include the sent_message_id.

        Requirements: 5.3
        """
        session_ctx = _make_session_context()
        expected_msg_id = "msg-returned-by-gmail"
        gmail_client = _make_gmail_client(sent_message_id=expected_msg_id)

        approval_gate = ApprovalGateController()

        def confirming_gate(draft, context_summary, decision_callback=None):
            return ApprovalDecision.CONFIRMED

        approval_gate.present_send_gate = confirming_gate  # type: ignore[method-assign]

        orchestrator = _make_orchestrator(
            session_ctx=session_ctx,
            gmail_client=gmail_client,
            approval_gate=approval_gate,
        )

        draft = _make_draft()
        instruction = _send_instruction(session_ctx.session_id, draft)
        response = orchestrator.process_instruction(session_ctx, instruction)

        assert response.payload["sent_message_id"] == expected_msg_id


# ---------------------------------------------------------------------------
# 4. On CANCELLED: no send occurs, CANCELLED response returned
# ---------------------------------------------------------------------------


class TestCancelledSendFlow:
    def test_send_message_not_called_on_cancelled(self) -> None:
        """
        When the gate is CANCELLED, gmail_client.send_message must NOT be called.

        Requirements: 5.2, 5.4
        """
        session_ctx = _make_session_context()
        gmail_client = _make_gmail_client()

        # Default ApprovalGateController with no callback → CANCELLED
        approval_gate = ApprovalGateController()

        orchestrator = _make_orchestrator(
            session_ctx=session_ctx,
            gmail_client=gmail_client,
            approval_gate=approval_gate,
        )

        draft = _make_draft()
        instruction = _send_instruction(session_ctx.session_id, draft)
        orchestrator.process_instruction(session_ctx, instruction)

        gmail_client.send_message.assert_not_called()

    def test_response_type_is_cancelled_on_cancelled(self) -> None:
        """
        AgentResponse.type must be CANCELLED when the gate is cancelled.

        Requirements: 5.4
        """
        session_ctx = _make_session_context()
        gmail_client = _make_gmail_client()
        approval_gate = ApprovalGateController()  # no callback → CANCELLED

        orchestrator = _make_orchestrator(
            session_ctx=session_ctx,
            gmail_client=gmail_client,
            approval_gate=approval_gate,
        )

        draft = _make_draft()
        instruction = _send_instruction(session_ctx.session_id, draft)
        response = orchestrator.process_instruction(session_ctx, instruction)

        assert response.type == AgentResponseType.CANCELLED

    def test_email_sent_not_logged_on_cancelled(self) -> None:
        """
        EMAIL_SENT must NOT be logged when the gate is cancelled.

        Requirements: 5.2, 12.1
        """
        session_ctx = _make_session_context()
        audit_logger = AuditLogger()
        approval_gate = ApprovalGateController()  # no callback → CANCELLED

        orchestrator = _make_orchestrator(
            session_ctx=session_ctx,
            audit_logger=audit_logger,
            approval_gate=approval_gate,
        )

        draft = _make_draft()
        instruction = _send_instruction(session_ctx.session_id, draft)
        orchestrator.process_instruction(session_ctx, instruction)

        sent_entries = audit_logger.query(event_type=AuditEventType.EMAIL_SENT)
        assert len(sent_entries) == 0, "EMAIL_SENT must not be logged when send is cancelled"


# ---------------------------------------------------------------------------
# 5. Full end-to-end flow order verification
# ---------------------------------------------------------------------------


class TestFullSendFlowOrder:
    def test_full_flow_order_on_confirmed(self) -> None:
        """
        Verify the complete send flow order:
        APPROVAL_GATE_PRESENTED → present_send_gate → send_message → EMAIL_SENT

        Requirements: 5.1, 5.2, 5.3, 12.1
        """
        session_ctx = _make_session_context()
        audit_logger = AuditLogger()
        call_order: list[str] = []

        gmail_client = MagicMock(spec=GmailClient)

        def spy_send(**kwargs):
            call_order.append("send_message")
            return "msg-final"

        gmail_client.send_message.side_effect = spy_send

        original_log = audit_logger.log

        def spy_log(event_type, **kwargs):
            call_order.append(f"log:{event_type.value}")
            return original_log(event_type=event_type, **kwargs)

        audit_logger.log = spy_log  # type: ignore[method-assign]

        approval_gate = ApprovalGateController()

        def confirming_gate(draft, context_summary, decision_callback=None):
            call_order.append("present_send_gate")
            return ApprovalDecision.CONFIRMED

        approval_gate.present_send_gate = confirming_gate  # type: ignore[method-assign]

        orchestrator = _make_orchestrator(
            session_ctx=session_ctx,
            gmail_client=gmail_client,
            audit_logger=audit_logger,
            approval_gate=approval_gate,
        )

        draft = _make_draft()
        instruction = _send_instruction(session_ctx.session_id, draft)
        orchestrator.process_instruction(session_ctx, instruction)

        gate_log_idx = next(
            i for i, c in enumerate(call_order)
            if c == f"log:{AuditEventType.APPROVAL_GATE_PRESENTED.value}"
        )
        present_idx = call_order.index("present_send_gate")
        send_idx = call_order.index("send_message")
        email_sent_idx = call_order.index(f"log:{AuditEventType.EMAIL_SENT.value}")

        assert gate_log_idx < present_idx, "APPROVAL_GATE_PRESENTED must be logged before gate"
        assert present_idx < send_idx, "Gate must be presented before send_message"
        assert send_idx < email_sent_idx, "send_message must be called before EMAIL_SENT logged"


# ---------------------------------------------------------------------------
# 6. factory.create_orchestrator wires all send-flow components
# ---------------------------------------------------------------------------


class TestFactoryWiresSendFlowComponents:
    def test_create_orchestrator_returns_agent_orchestrator(self) -> None:
        """create_orchestrator must return an AgentOrchestrator instance."""
        session_manager = MagicMock(spec=SessionManager)
        permission_manager = MagicMock(spec=PermissionManager)

        orchestrator = create_orchestrator(
            session_manager=session_manager,
            permission_manager=permission_manager,
        )

        assert isinstance(orchestrator, AgentOrchestrator)

    def test_create_orchestrator_wires_approval_gate(self) -> None:
        """The orchestrator created by factory must have an ApprovalGateController."""
        session_manager = MagicMock(spec=SessionManager)
        permission_manager = MagicMock(spec=PermissionManager)

        orchestrator = create_orchestrator(
            session_manager=session_manager,
            permission_manager=permission_manager,
        )

        assert isinstance(orchestrator._approval_gate, ApprovalGateController)

    def test_create_orchestrator_wires_audit_logger(self) -> None:
        """The orchestrator created by factory must have an AuditLogger."""
        session_manager = MagicMock(spec=SessionManager)
        permission_manager = MagicMock(spec=PermissionManager)

        orchestrator = create_orchestrator(
            session_manager=session_manager,
            permission_manager=permission_manager,
        )

        assert isinstance(orchestrator._audit_logger, AuditLogger)

    def test_create_orchestrator_uses_provided_audit_logger(self) -> None:
        """When an audit_logger is provided, it must be used (not a new one)."""
        session_manager = MagicMock(spec=SessionManager)
        permission_manager = MagicMock(spec=PermissionManager)
        custom_logger = AuditLogger()

        orchestrator = create_orchestrator(
            session_manager=session_manager,
            permission_manager=permission_manager,
            audit_logger=custom_logger,
        )

        assert orchestrator._audit_logger is custom_logger

    def test_create_orchestrator_uses_provided_gmail_client(self) -> None:
        """When a gmail_client is provided, it must be wired into the orchestrator."""
        session_manager = MagicMock(spec=SessionManager)
        permission_manager = MagicMock(spec=PermissionManager)
        gmail_client = MagicMock(spec=GmailClient)

        orchestrator = create_orchestrator(
            session_manager=session_manager,
            permission_manager=permission_manager,
            gmail_client=gmail_client,
        )

        assert orchestrator._gmail_client is gmail_client

    def test_create_orchestrator_send_flow_works_end_to_end(self) -> None:
        """
        The factory-assembled orchestrator must correctly execute the send flow.

        Requirements: 5.1, 5.2, 5.3, 12.1
        """
        session_ctx = _make_session_context()
        audit_logger = AuditLogger()
        gmail_client = _make_gmail_client(sent_message_id="factory-msg-001")

        session_manager = MagicMock(spec=SessionManager)
        session_manager.validate_session.return_value = session_ctx

        permission_manager = MagicMock(spec=PermissionManager)
        permission_manager.check_permission.return_value = True

        orchestrator = create_orchestrator(
            session_manager=session_manager,
            permission_manager=permission_manager,
            gmail_client=gmail_client,
            audit_logger=audit_logger,
        )

        # Inject a confirming callback into the approval gate
        def confirming_gate(draft, context_summary, decision_callback=None):
            return ApprovalDecision.CONFIRMED

        orchestrator._approval_gate.present_send_gate = confirming_gate  # type: ignore[method-assign]

        draft = _make_draft()
        instruction = _send_instruction(session_ctx.session_id, draft)
        response = orchestrator.process_instruction(session_ctx, instruction)

        # Verify the full flow completed correctly
        assert response.type == AgentResponseType.SEND_CONFIRMED
        assert response.success is True
        gmail_client.send_message.assert_called_once()

        sent_entries = audit_logger.query(event_type=AuditEventType.EMAIL_SENT)
        assert len(sent_entries) == 1

        gate_entries = audit_logger.query(event_type=AuditEventType.APPROVAL_GATE_PRESENTED)
        assert len(gate_entries) == 1

"""
Factory module for assembling a fully-wired AgentOrchestrator.

This is the canonical way to construct an AgentOrchestrator for both
production use and integration tests.  All internal components are created
with sensible defaults when not explicitly provided.

Trust boundary note: the factory wires the pipeline so that raw Gmail data
always passes through PromptSanitiser.sanitise_content before reaching the
LLM.  This invariant is enforced inside AgentOrchestrator._handle_draft_instruction
and must never be bypassed.

Requirements: 1.1, 1.2, 1.5, 2.1, 2.2, 3.1–3.5, 8.1, 9.1, 9.2, 13.1, 13.2
"""

from __future__ import annotations

from typing import Any

from src.approval.approval_gate_controller import ApprovalGateController
from src.audit.audit_logger import AuditLogger
from src.auth.session_manager import SessionManager
from src.gmail.gmail_client import GmailClient
from src.orchestrator.agent_orchestrator import AgentOrchestrator
from src.permissions.permission_manager import PermissionManager
from src.prompt.sanitiser import PromptSanitiser
from src.scheduling.scheduled_draft_manager import ScheduledDraftManager
from src.tone.tone_profile_engine import ToneProfileEngine


def create_orchestrator(
    session_manager: SessionManager,
    permission_manager: PermissionManager,
    gmail_client: GmailClient | None = None,
    llm_client: Any = None,
    audit_logger: AuditLogger | None = None,
) -> AgentOrchestrator:
    """
    Assemble a fully-wired AgentOrchestrator from its dependencies.

    All internal components (ToneProfileEngine, PromptSanitiser,
    ApprovalGateController, AuditLogger, ScheduledDraftManager) are
    created with sensible defaults if not provided.

    This is the canonical way to construct an AgentOrchestrator for
    both production use and integration tests.

    Parameters
    ----------
    session_manager:
        Validates sessions and manages the session lifecycle.  Required.
    permission_manager:
        Enforces permission checks before any data access.  Required.
    gmail_client:
        Wraps the Gmail REST API.  Pass None if Gmail access is not
        required (e.g. instruction-only drafts).
    llm_client:
        The LLM provider client.  When None, any instruction that requires
        LLM generation will return an error AgentResponse.  Pass a real or
        mock client to enable LLM calls.
    audit_logger:
        Append-only audit logger.  A fresh in-memory AuditLogger is created
        if not provided.

    Returns
    -------
    AgentOrchestrator
        A fully-wired orchestrator ready to process instructions.

    Notes
    -----
    Trust boundary: raw Gmail data retrieved by GmailClient is always passed
    through PromptSanitiser.sanitise_content before being forwarded to the
    LLM.  This invariant is enforced inside AgentOrchestrator and must never
    be bypassed.
    """
    # Create defaults for components not provided by the caller.
    effective_audit_logger = audit_logger if audit_logger is not None else AuditLogger()
    tone_engine = ToneProfileEngine()
    prompt_builder = PromptSanitiser()
    approval_gate = ApprovalGateController()
    scheduled_draft_manager = ScheduledDraftManager()

    return AgentOrchestrator(
        session_manager=session_manager,
        permission_manager=permission_manager,
        gmail_client=gmail_client,
        tone_engine=tone_engine,
        prompt_builder=prompt_builder,
        approval_gate=approval_gate,
        audit_logger=effective_audit_logger,
        scheduled_draft_manager=scheduled_draft_manager,
        llm_client=llm_client,
    )

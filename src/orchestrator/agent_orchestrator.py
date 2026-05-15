"""
Agent Orchestrator — central coordinator for the Secure AI Executive Assistant.

Responsibilities:
- Validate sessions before processing any instruction
- Coordinate permission checks before any data access
- Route requests to GmailClient, ToneProfileEngine, PromptBuilder, and LLM
- Maintain per-session conversation history
- Enforce the human-in-the-loop workflow

Trust note: this module is part of the trusted Agent Core. It only accepts
instructions from authenticated sessions and never treats external content
as instructions.

Requirements: 1.1, 1.2, 1.3, 1.4, 1.6, 2.1, 2.2, 3.1, 3.2, 3.3, 4.1, 4.2,
              4.3, 9.2
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from src.approval.approval_gate_controller import ApprovalGateController
from src.audit.audit_logger import AuditLogger
from src.auth.errors import SessionExpiredError
from src.auth.session_manager import SessionManager
from src.gmail.gmail_client import GmailClient
from src.models.types import (
    AgentResponse,
    AgentResponseType,
    ApprovalDecision,
    AuditEventType,
    ContentSource,
    ContextSummary,
    DataSource,
    DataSourceReference,
    Draft,
    EmailMessage,
    GmailScope,
    InjectionAlert,
    PermissionScope,
    SessionContext,
    ToneProfile,
    UserInstruction,
)
from src.orchestrator.errors import LLMNotConfiguredError, OrchestratorError
from src.permissions.permission_manager import PermissionManager
from src.prompt.sanitiser import PromptSanitiser
from src.scheduling.scheduled_draft_manager import ScheduledDraftManager
from src.tone.tone_profile_engine import ToneProfileEngine

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Conversation history entry
# ---------------------------------------------------------------------------


class ConversationTurn:
    """A single exchange in the per-session conversation history."""

    def __init__(
        self,
        instruction: UserInstruction,
        response: AgentResponse,
        timestamp: datetime | None = None,
    ) -> None:
        self.instruction = instruction
        self.response = response
        self.timestamp = timestamp or datetime.now(tz=timezone.utc)


# ---------------------------------------------------------------------------
# AgentOrchestrator
# ---------------------------------------------------------------------------


class AgentOrchestrator:
    """
    Central coordinator for the Secure AI Executive Assistant.

    Parameters
    ----------
    session_manager:
        Validates sessions and manages the session lifecycle.
    permission_manager:
        Enforces permission checks before any data access.
    gmail_client:
        Wraps the Gmail REST API.  May be None if Gmail access is not
        required for the current deployment.
    tone_engine:
        Derives and manages Tone Profiles.
    prompt_builder:
        Sanitises untrusted content and constructs LLM prompts.
    approval_gate:
        Enforces human-in-the-loop for sensitive actions.
    audit_logger:
        Records all agent actions in the append-only audit log.
    scheduled_draft_manager:
        Manages the lifecycle of scheduled email drafts.
    llm_client:
        The LLM provider client.  When None, any instruction that requires
        LLM generation will return an error response (LLMNotConfiguredError
        is raised internally and caught, returning an error AgentResponse).
        Pass a real or mock client to enable LLM calls.
    """

    def __init__(
        self,
        session_manager: SessionManager,
        permission_manager: PermissionManager,
        gmail_client: GmailClient | None,
        tone_engine: ToneProfileEngine,
        prompt_builder: PromptSanitiser,
        approval_gate: ApprovalGateController,
        audit_logger: AuditLogger,
        scheduled_draft_manager: ScheduledDraftManager,
        llm_client: Any = None,
    ) -> None:
        self._session_manager = session_manager
        self._permission_manager = permission_manager
        self._gmail_client = gmail_client
        self._tone_engine = tone_engine
        self._prompt_builder = prompt_builder
        self._approval_gate = approval_gate
        self._audit_logger = audit_logger
        self._scheduled_draft_manager = scheduled_draft_manager
        self._llm_client = llm_client

        # Per-session conversation history: session_id → list[ConversationTurn]
        self._conversation_history: dict[str, list[ConversationTurn]] = {}

        # Track which sessions have already had SESSION_STARTED logged
        self._seen_sessions: set[str] = set()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def process_instruction(
        self,
        session_ctx: SessionContext,
        instruction: UserInstruction,
    ) -> AgentResponse:
        """
        Process a user instruction within the given session context.

        Steps:
        1. Validate the session via SessionManager.validate_session.
        2. Log SESSION_STARTED on the first instruction in a session.
        3. Dispatch to the appropriate handler based on instruction_type.
        4. Store the exchange in the per-session conversation history.
        5. Return an AgentResponse.

        Returns an error AgentResponse (success=False) rather than raising
        for session validation failures and unknown instruction types.

        Requirements: 1.1, 1.2, 1.3, 1.4, 1.6, 2.1, 2.2, 3.1, 3.2, 3.3,
                      4.1, 4.2, 4.3, 9.2
        """
        session_id = session_ctx.session_id

        # ------------------------------------------------------------------
        # Step 1: Validate session
        # ------------------------------------------------------------------
        try:
            validated_ctx = self._session_manager.validate_session(session_id)
        except SessionExpiredError as exc:
            logger.warning("Session validation failed for session=%s: %s", session_id, exc)
            self._audit_logger.log(
                event_type=AuditEventType.SESSION_EXPIRED,
                session_id=session_id,
                description="Session expired or not found during instruction processing",
                metadata={"session_id": session_id},
            )
            return AgentResponse(
                session_id=session_id,
                type=AgentResponseType.ERROR,
                payload=None,
                success=False,
                message=str(exc),
            )
        except Exception as exc:
            logger.error("Unexpected error validating session=%s: %s", session_id, exc)
            return AgentResponse(
                session_id=session_id,
                type=AgentResponseType.ERROR,
                payload=None,
                success=False,
                message="Session validation failed.",
            )

        # ------------------------------------------------------------------
        # Step 2: Log SESSION_STARTED on first instruction in this session
        # ------------------------------------------------------------------
        if session_id not in self._seen_sessions:
            self._seen_sessions.add(session_id)
            self._audit_logger.log(
                event_type=AuditEventType.SESSION_STARTED,
                session_id=session_id,
                description=f"Session started for user {validated_ctx.user_id}",
                metadata={"user_id": validated_ctx.user_id},
            )

        # ------------------------------------------------------------------
        # Step 3: Dispatch based on instruction_type
        # ------------------------------------------------------------------
        instruction_type = getattr(instruction, "instruction_type", "draft")

        if instruction_type == "draft":
            response = self._handle_draft_instruction(validated_ctx, instruction)
        elif instruction_type == "send":
            response = self._handle_send_instruction(validated_ctx, instruction)
        elif instruction_type == "delete":
            response = self._handle_delete_instruction(validated_ctx, instruction)
        elif instruction_type == "schedule":
            response = self._handle_schedule_instruction(validated_ctx, instruction)
        elif instruction_type == "cancel_schedule":
            response = self._handle_cancel_schedule_instruction(validated_ctx, instruction)
        else:
            response = AgentResponse(
                session_id=session_id,
                type=AgentResponseType.ERROR,
                payload=None,
                success=False,
                message="Unknown instruction type",
            )

        # ------------------------------------------------------------------
        # Step 4: Store exchange in conversation history
        # ------------------------------------------------------------------
        if session_id not in self._conversation_history:
            self._conversation_history[session_id] = []
        self._conversation_history[session_id].append(
            ConversationTurn(instruction=instruction, response=response)
        )

        return response

    # ------------------------------------------------------------------
    # Conversation history access
    # ------------------------------------------------------------------

    def get_conversation_history(self, session_id: str) -> list[ConversationTurn]:
        """
        Return the conversation history for a session.

        Parameters
        ----------
        session_id:
            The session whose history to retrieve.

        Returns
        -------
        list[ConversationTurn]
            All prior exchanges in the session, in chronological order.
            Returns an empty list if no history exists.
        """
        return list(self._conversation_history.get(session_id, []))

    # ------------------------------------------------------------------
    # Draft instruction handler
    # ------------------------------------------------------------------

    def _handle_draft_instruction(
        self,
        session_ctx: SessionContext,
        instruction: UserInstruction,
    ) -> AgentResponse:
        """
        Handle a "draft" instruction type.

        Flow:
        1. Check permission for Gmail readonly access.
        2. If permitted, fetch Gmail context and sanitise it.
        3. Retrieve or derive a Tone Profile for the recipient.
        4. Build the LLM prompt.
        5. Call the LLM to generate the draft.
        6. Construct a ContextSummary.
        7. Return the draft in an AgentResponse.

        Requirements: 1.1, 2.1, 2.2, 3.1, 3.2, 3.3, 9.2
        """
        session_id = session_ctx.session_id

        # ------------------------------------------------------------------
        # Permission check before any Gmail data access (Req 3.1, 3.2)
        # ------------------------------------------------------------------
        gmail_scope = PermissionScope(
            data_source="gmail",
            gmail_scope=GmailScope.READONLY,
            justification="Retrieve email context to inform draft generation",
        )
        has_gmail_permission = self._permission_manager.check_permission(
            session_id=session_id,
            scope=gmail_scope,
        )

        # ------------------------------------------------------------------
        # Fetch Gmail context if permitted (Req 3.3)
        # ------------------------------------------------------------------
        sanitised_context = None
        data_sources: list[DataSourceReference] = []

        if has_gmail_permission and self._gmail_client is not None:
            try:
                messages = self._gmail_client.list_messages(
                    query=instruction.text,
                    max_results=5,
                )
                if messages:
                    # Log email context access
                    self._audit_logger.log(
                        event_type=AuditEventType.EMAIL_CONTEXT_ACCESSED,
                        session_id=session_id,
                        description=(
                            f"Email context accessed for draft generation "
                            f"({len(messages)} messages)"
                        ),
                        metadata={"message_count": str(len(messages))},
                    )

                    # Sanitise the email content before passing to LLM (Req 9.2)
                    combined_content = "\n\n".join(
                        f"From: {m.from_address}\nSubject: {m.subject}\n{m.body}"
                        for m in messages
                    )
                    sanitise_result = self._prompt_builder.sanitise_content(
                        raw=combined_content,
                        source=ContentSource.GMAIL_BODY,
                    )

                    if isinstance(sanitise_result, InjectionAlert):
                        # High-confidence injection detected — log and notify
                        self._audit_logger.log(
                            event_type=AuditEventType.PROMPT_INJECTION_DETECTED,
                            session_id=session_id,
                            description=(
                                "Prompt injection detected in Gmail content "
                                f"(confidence={sanitise_result.scan_result.confidence.value})"
                            ),
                            metadata={
                                "source": ContentSource.GMAIL_BODY.value,
                                "patterns": ", ".join(
                                    sanitise_result.scan_result.patterns[:5]
                                ),
                            },
                        )
                        # Use the sanitised content from the alert
                        from src.models.types import SanitisedContent
                        sanitised_context = SanitisedContent(
                            original=sanitise_result.original_content,
                            sanitised=sanitise_result.sanitised_content,
                            source=ContentSource.GMAIL_BODY,
                            wrapped_for_llm=sanitise_result.sanitised_content,
                        )
                    else:
                        sanitised_context = sanitise_result

                    # Build data source reference for ContextSummary
                    data_sources.append(
                        DataSourceReference(
                            source=DataSource.GMAIL,
                            description=f"Email context ({len(messages)} messages)",
                            item_count=len(messages),
                        )
                    )
            except Exception as exc:
                logger.warning(
                    "Failed to fetch Gmail context for session=%s: %s",
                    session_id,
                    exc,
                )
                # Proceed without Gmail context (Req 3.6)

        # ------------------------------------------------------------------
        # Retrieve or derive Tone Profile (Req 2.1, 2.2)
        # ------------------------------------------------------------------
        tone_profile: ToneProfile | None = None
        recipient_email = _extract_recipient_from_instruction(instruction.text)

        if recipient_email:
            gmail_history = []
            if has_gmail_permission and self._gmail_client is not None:
                try:
                    gmail_history = self._gmail_client.get_sent_history(
                        recipient_email=recipient_email,
                        limit=10,
                    )
                    if gmail_history:
                        # Log sent history access for tone derivation
                        self._audit_logger.log(
                            event_type=AuditEventType.EMAIL_CONTEXT_ACCESSED,
                            session_id=session_id,
                            description=(
                                f"Sent history accessed for tone derivation "
                                f"({len(gmail_history)} messages, recipient={recipient_email})"
                            ),
                            metadata={
                                "message_count": str(len(gmail_history)),
                                "recipient": recipient_email,
                                "purpose": "tone_derivation",
                            },
                        )
                        # Track sent history as a data source for ContextSummary (Req 13.1)
                        data_sources.append(
                            DataSourceReference(
                                source=DataSource.GMAIL,
                                description=(
                                    f"Sent history for tone derivation "
                                    f"({len(gmail_history)} messages to {recipient_email})"
                                ),
                                item_count=len(gmail_history),
                            )
                        )
                except Exception as exc:
                    logger.warning(
                        "Failed to fetch sent history for tone derivation "
                        "session=%s recipient=%s: %s",
                        session_id,
                        recipient_email,
                        exc,
                    )

            tone_profile = self._tone_engine.get_or_derive_profile(
                recipient_email=recipient_email,
                gmail_history=gmail_history,
            )

        # ------------------------------------------------------------------
        # Build LLM prompt (Req 9.2)
        # ------------------------------------------------------------------
        llm_prompt = self._prompt_builder.build_draft_prompt(
            instruction=instruction,
            context=sanitised_context,
            tone_profile=tone_profile,
        )

        # ------------------------------------------------------------------
        # Call LLM (raises LLMNotConfiguredError if no client)
        # ------------------------------------------------------------------
        if self._llm_client is None:
            raise LLMNotConfiguredError(
                "No LLM client configured. Pass an llm_client to AgentOrchestrator."
            )

        try:
            llm_response_text = self._call_llm(llm_prompt)
        except LLMNotConfiguredError:
            raise
        except Exception as exc:
            logger.error("LLM call failed for session=%s: %s", session_id, exc)
            return AgentResponse(
                session_id=session_id,
                type=AgentResponseType.ERROR,
                payload=None,
                success=False,
                message=f"Draft generation failed: {exc}",
            )

        # ------------------------------------------------------------------
        # Construct ContextSummary (Req 1.5, 13.1)
        # ------------------------------------------------------------------
        # Always include the user instruction as a data source
        data_sources.append(
            DataSourceReference(
                source=DataSource.USER_INSTRUCTION,
                description="User instruction",
                item_count=1,
            )
        )
        context_summary = ContextSummary(
            data_sources=data_sources,
            generated_from_instruction_only=(len(data_sources) == 1),
        )

        # ------------------------------------------------------------------
        # Build Draft (Req 1.1)
        # ------------------------------------------------------------------
        draft = Draft(
            recipient=recipient_email or "",
            subject=_extract_subject_from_llm_response(llm_response_text),
            body=_extract_body_from_llm_response(llm_response_text),
            context_summary=context_summary,
            tone_profile_used=(
                _tone_profile_to_summary(tone_profile) if tone_profile else None
            ),
            generated_from_instruction=instruction.text,
        )

        # Log DRAFT_CREATED (Req 12.1)
        self._audit_logger.log(
            event_type=AuditEventType.DRAFT_CREATED,
            session_id=session_id,
            description=f"Draft created for recipient '{draft.recipient}'",
            metadata={
                "recipient": draft.recipient,
                "subject": draft.subject,
                "instruction_id": instruction.instruction_id,
            },
        )

        return AgentResponse(
            session_id=session_id,
            type=AgentResponseType.DRAFT,
            payload=draft,
            success=True,
            message="Draft generated successfully.",
        )

    # ------------------------------------------------------------------
    # Send instruction handler
    # ------------------------------------------------------------------

    def _handle_send_instruction(
        self,
        session_ctx: SessionContext,
        instruction: UserInstruction,
    ) -> AgentResponse:
        """
        Handle a "send" instruction type.

        Flow:
        1. Extract the Draft from instruction.payload.
        2. Log APPROVAL_GATE_PRESENTED.
        3. Present the send approval gate.
        4. On CONFIRMED: send the email, log EMAIL_SENT, return SEND_CONFIRMED.
        5. On CANCELLED: return CANCELLED without sending.

        Requirements: 5.1, 5.2, 5.3, 5.4, 5.5
        """
        session_id = session_ctx.session_id
        draft: Draft = instruction.payload

        # Log that the approval gate is being presented (Req 12.1)
        self._audit_logger.log(
            event_type=AuditEventType.APPROVAL_GATE_PRESENTED,
            session_id=session_id,
            description=f"Send approval gate presented for draft '{draft.draft_id}'",
            metadata={
                "draft_id": draft.draft_id,
                "recipient": draft.recipient,
                "subject": draft.subject,
            },
        )

        decision = self._approval_gate.present_send_gate(
            draft=draft,
            context_summary=draft.context_summary,
        )

        if decision == ApprovalDecision.CONFIRMED:
            # Send the email via Gmail (Req 5.3)
            sent_message_id = self._gmail_client.send_message(
                to=draft.recipient,
                subject=draft.subject,
                body=draft.body,
                cc=draft.cc if draft.cc else None,
            )

            # Log EMAIL_SENT (Req 12.1)
            self._audit_logger.log(
                event_type=AuditEventType.EMAIL_SENT,
                session_id=session_id,
                description=f"Email sent to '{draft.recipient}' (subject: '{draft.subject}')",
                metadata={
                    "draft_id": draft.draft_id,
                    "recipient": draft.recipient,
                    "subject": draft.subject,
                    "sent_message_id": sent_message_id,
                },
            )

            return AgentResponse(
                session_id=session_id,
                type=AgentResponseType.SEND_CONFIRMED,
                payload={"sent_message_id": sent_message_id, "draft": draft},
                success=True,
                message=f"Email sent successfully to {draft.recipient}.",
            )

        # CANCELLED — do not send (Req 5.4)
        return AgentResponse(
            session_id=session_id,
            type=AgentResponseType.CANCELLED,
            payload=None,
            success=True,
            message="Send cancelled. Returning to draft view.",
        )

    # ------------------------------------------------------------------
    # Delete instruction handler
    # ------------------------------------------------------------------

    def _handle_delete_instruction(
        self,
        session_ctx: SessionContext,
        instruction: UserInstruction,
    ) -> AgentResponse:
        """
        Handle a "delete" instruction type.

        Flow:
        1. Extract the EmailMessage from instruction.payload.
        2. Log APPROVAL_GATE_PRESENTED.
        3. Present the delete approval gate.
        4. On CONFIRMED: delete the message, log EMAIL_DELETED, return DELETE_CONFIRMED.
        5. On CANCELLED: return CANCELLED without deleting.

        Requirements: 6.1, 6.2, 6.3, 6.4
        """
        session_id = session_ctx.session_id
        email_message: EmailMessage = instruction.payload

        # Log that the approval gate is being presented (Req 12.1)
        self._audit_logger.log(
            event_type=AuditEventType.APPROVAL_GATE_PRESENTED,
            session_id=session_id,
            description=(
                f"Delete approval gate presented for message '{email_message.message_id}'"
            ),
            metadata={
                "message_id": email_message.message_id,
                "sender": email_message.from_address,
                "subject": email_message.subject,
            },
        )

        decision = self._approval_gate.present_delete_gate(
            message_id=email_message.message_id,
            sender=email_message.from_address,
            subject=email_message.subject,
            sent_at=email_message.sent_at,
        )

        if decision == ApprovalDecision.CONFIRMED:
            # Delete the message via Gmail (Req 6.3)
            self._gmail_client.delete_message(email_message.message_id)

            # Log EMAIL_DELETED (Req 12.1)
            self._audit_logger.log(
                event_type=AuditEventType.EMAIL_DELETED,
                session_id=session_id,
                description=(
                    f"Email deleted: message_id='{email_message.message_id}', "
                    f"subject='{email_message.subject}'"
                ),
                metadata={
                    "message_id": email_message.message_id,
                    "sender": email_message.from_address,
                    "subject": email_message.subject,
                },
            )

            return AgentResponse(
                session_id=session_id,
                type=AgentResponseType.DELETE_CONFIRMED,
                payload={"deleted_message_id": email_message.message_id},
                success=True,
                message=f"Email '{email_message.subject}' deleted successfully.",
            )

        # CANCELLED — do not delete (Req 6.4)
        return AgentResponse(
            session_id=session_id,
            type=AgentResponseType.CANCELLED,
            payload=None,
            success=True,
            message="Delete cancelled.",
        )

    # ------------------------------------------------------------------
    # Schedule instruction handler
    # ------------------------------------------------------------------

    def _handle_schedule_instruction(
        self,
        session_ctx: SessionContext,
        instruction: UserInstruction,
    ) -> AgentResponse:
        """
        Handle a "schedule" instruction type.

        Flow:
        1. Extract draft and send_time from instruction.payload dict.
        2. Log APPROVAL_GATE_PRESENTED.
        3. Present the schedule approval gate.
        4. On CONFIRMED: register the scheduled draft, log SCHEDULED_DRAFT_REGISTERED,
           return SCHEDULE_CONFIRMED.
        5. On CANCELLED: return CANCELLED without registering.

        Requirements: 7.1, 7.2, 7.3
        """
        session_id = session_ctx.session_id
        payload = instruction.payload
        draft: Draft = payload["draft"]
        send_time = payload["send_time"]

        # Log that the approval gate is being presented (Req 12.1)
        self._audit_logger.log(
            event_type=AuditEventType.APPROVAL_GATE_PRESENTED,
            session_id=session_id,
            description=(
                f"Schedule approval gate presented for draft '{draft.draft_id}' "
                f"(send_time={send_time.isoformat()})"
            ),
            metadata={
                "draft_id": draft.draft_id,
                "recipient": draft.recipient,
                "subject": draft.subject,
                "send_time": send_time.isoformat(),
            },
        )

        decision = self._approval_gate.present_schedule_gate(
            draft=draft,
            scheduled_time=send_time,
        )

        if decision == ApprovalDecision.CONFIRMED:
            # Register the scheduled draft (Req 7.3)
            scheduled_draft = self._scheduled_draft_manager.register_scheduled_draft(
                draft=draft,
                send_time=send_time,
            )

            # Log SCHEDULED_DRAFT_REGISTERED (Req 12.1)
            self._audit_logger.log(
                event_type=AuditEventType.SCHEDULED_DRAFT_REGISTERED,
                session_id=session_id,
                description=(
                    f"Scheduled draft registered: id='{scheduled_draft.scheduled_draft_id}', "
                    f"send_time={send_time.isoformat()}"
                ),
                metadata={
                    "scheduled_draft_id": scheduled_draft.scheduled_draft_id,
                    "draft_id": draft.draft_id,
                    "recipient": draft.recipient,
                    "send_time": send_time.isoformat(),
                },
            )

            return AgentResponse(
                session_id=session_id,
                type=AgentResponseType.SCHEDULE_CONFIRMED,
                payload=scheduled_draft,
                success=True,
                message=(
                    f"Draft scheduled for delivery to {draft.recipient} "
                    f"at {send_time.isoformat()}."
                ),
            )

        # CANCELLED — do not register (Req 7.2)
        return AgentResponse(
            session_id=session_id,
            type=AgentResponseType.CANCELLED,
            payload=None,
            success=True,
            message="Schedule cancelled.",
        )

    # ------------------------------------------------------------------
    # Cancel schedule instruction handler
    # ------------------------------------------------------------------

    def _handle_cancel_schedule_instruction(
        self,
        session_ctx: SessionContext,
        instruction: UserInstruction,
    ) -> AgentResponse:
        """
        Handle a "cancel_schedule" instruction type.

        Flow:
        1. Extract the scheduled_draft_id from instruction.payload.
        2. Cancel the scheduled draft via ScheduledDraftManager.
        3. Log SCHEDULED_DRAFT_CANCELLED.
        4. Return a success response.

        Requirements: 12.1
        """
        session_id = session_ctx.session_id
        scheduled_draft_id: str = instruction.payload

        try:
            self._scheduled_draft_manager.cancel_scheduled_draft(scheduled_draft_id)
        except Exception as exc:
            logger.error(
                "Failed to cancel scheduled draft '%s' for session=%s: %s",
                scheduled_draft_id,
                session_id,
                exc,
            )
            return AgentResponse(
                session_id=session_id,
                type=AgentResponseType.ERROR,
                payload=None,
                success=False,
                message=f"Failed to cancel scheduled draft: {exc}",
            )

        # Log SCHEDULED_DRAFT_CANCELLED (Req 12.1)
        self._audit_logger.log(
            event_type=AuditEventType.SCHEDULED_DRAFT_CANCELLED,
            session_id=session_id,
            description=f"Scheduled draft cancelled: id='{scheduled_draft_id}'",
            metadata={"scheduled_draft_id": scheduled_draft_id},
        )

        return AgentResponse(
            session_id=session_id,
            type=AgentResponseType.INFO,
            payload={"cancelled_scheduled_draft_id": scheduled_draft_id},
            success=True,
            message=f"Scheduled draft '{scheduled_draft_id}' cancelled successfully.",
        )

    # ------------------------------------------------------------------
    # LLM call helper
    # ------------------------------------------------------------------

    def _call_llm(self, prompt: Any) -> str:
        """
        Call the configured LLM client with the given prompt.

        The llm_client is expected to be a Google Generative AI model
        (google-generativeai SDK) or a compatible mock.  For the real
        Gemini client the call is:

            model.generate_content(full_prompt_text)

        For test mocks, any callable that accepts a string and returns an
        object with a `text` attribute (or a plain string) is accepted.

        Raises
        ------
        LLMNotConfiguredError
            If self._llm_client is None.
        """
        if self._llm_client is None:
            raise LLMNotConfiguredError(
                "No LLM client configured. Pass an llm_client to AgentOrchestrator."
            )

        # Compose the full prompt text from the structured LLMPrompt
        full_prompt = (
            f"SYSTEM:\n{prompt.system_prompt}\n\n"
            f"USER INSTRUCTION:\n{prompt.user_instruction}\n\n"
            f"DATA CONTEXT:\n{prompt.data_context}"
        )

        # Support both the real Gemini SDK and simple callable mocks
        if callable(self._llm_client):
            result = self._llm_client(full_prompt)
        elif hasattr(self._llm_client, "generate_content"):
            result = self._llm_client.generate_content(full_prompt)
        else:
            raise OrchestratorError(
                f"Unsupported llm_client type: {type(self._llm_client)}"
            )

        # Extract text from the result
        if isinstance(result, str):
            return result
        if hasattr(result, "text"):
            return result.text
        return str(result)


# ---------------------------------------------------------------------------
# Pure helper functions
# ---------------------------------------------------------------------------


def _extract_recipient_from_instruction(text: str) -> str | None:
    """
    Attempt to extract a recipient email address from the instruction text.

    Looks for patterns like "to alice@example.com" or bare email addresses.
    Returns None if no email address is found.
    """
    import re

    # Look for an email address in the instruction text
    match = re.search(r"[\w.+-]+@[\w-]+\.[a-zA-Z]{2,}", text)
    if match:
        return match.group(0)
    return None


def _extract_subject_from_llm_response(response_text: str) -> str:
    """
    Extract the subject line from the LLM response.

    Looks for a "Subject:" line; falls back to the first non-empty line.
    """
    for line in response_text.splitlines():
        stripped = line.strip()
        if stripped.lower().startswith("subject:"):
            return stripped[len("subject:"):].strip()
    # Fallback: use the first non-empty line as the subject
    for line in response_text.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped[:100]  # cap at 100 chars
    return "Draft"


def _extract_body_from_llm_response(response_text: str) -> str:
    """
    Extract the email body from the LLM response.

    If a "Subject:" line is present, returns everything after it.
    Otherwise returns the full response text.
    """
    lines = response_text.splitlines()
    for i, line in enumerate(lines):
        if line.strip().lower().startswith("subject:"):
            # Body starts after the subject line (skip blank lines)
            body_lines = lines[i + 1:]
            # Strip leading blank lines
            while body_lines and not body_lines[0].strip():
                body_lines = body_lines[1:]
            return "\n".join(body_lines).strip()
    return response_text.strip()


def _tone_profile_to_summary(profile: ToneProfile) -> Any:
    """Convert a ToneProfile to a ToneProfileSummary for the Draft."""
    from src.models.types import ToneProfileSummary

    description = (
        f"{profile.formality_level.value.replace('_', ' ').capitalize()} tone, "
        f"warmth {profile.warmth_indicator:.1f}, "
        f"derived from {profile.derived_from_count} emails"
    )
    return ToneProfileSummary(
        recipient_email=profile.recipient_email,
        formality_level=profile.formality_level.value,
        description=description,
        last_updated_at=profile.last_updated_at,
    )

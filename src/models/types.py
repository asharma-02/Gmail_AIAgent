"""
Core Pydantic data models for the Secure AI Executive Assistant.

Trust hierarchy note: the system distinguishes sharply between trusted user
instructions (received through the authenticated session channel) and untrusted
external content (email bodies, meeting notes, documents). These models encode
that distinction throughout the data layer.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal, Optional
from uuid import uuid4

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class GmailScope(str, Enum):
    """
    Incremental Gmail OAuth scopes, requested at the point of need.

    - READONLY  — reading email threads and sent history
    - SEND      — sending approved emails
    - COMPOSE   — creating and managing drafts in Gmail
    - MODIFY    — deleting emails (only requested if deletion is used)
    """

    READONLY = "gmail.readonly"
    SEND = "gmail.send"
    COMPOSE = "gmail.compose"
    MODIFY = "gmail.modify"


class AuditEventType(str, Enum):
    """All event types that must be recorded in the audit log."""

    DRAFT_CREATED = "DRAFT_CREATED"
    EMAIL_CONTEXT_ACCESSED = "EMAIL_CONTEXT_ACCESSED"
    MEETING_NOTES_ACCESSED = "MEETING_NOTES_ACCESSED"
    PERMISSION_GRANTED = "PERMISSION_GRANTED"
    PERMISSION_REVOKED = "PERMISSION_REVOKED"
    APPROVAL_GATE_PRESENTED = "APPROVAL_GATE_PRESENTED"
    EMAIL_SENT = "EMAIL_SENT"
    EMAIL_DELETED = "EMAIL_DELETED"
    SCHEDULED_DRAFT_REGISTERED = "SCHEDULED_DRAFT_REGISTERED"
    SCHEDULED_DRAFT_CANCELLED = "SCHEDULED_DRAFT_CANCELLED"
    PROMPT_INJECTION_DETECTED = "PROMPT_INJECTION_DETECTED"
    AUTH_FAILED = "AUTH_FAILED"
    SESSION_STARTED = "SESSION_STARTED"
    SESSION_EXPIRED = "SESSION_EXPIRED"
    GMAIL_TOKEN_REVOKED = "GMAIL_TOKEN_REVOKED"


class ContentSource(str, Enum):
    """The origin of a piece of untrusted content crossing the trust boundary."""

    GMAIL_BODY = "gmail_body"
    MEETING_NOTES = "meeting_notes"
    CALENDAR_ENTRY = "calendar_entry"
    DOCUMENT = "document"


class ApprovalDecision(str, Enum):
    """
    The outcome of an approval gate interaction.
    CONFIRMED allows the sensitive action to proceed; CANCELLED aborts it.
    """

    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"


class FormalityLevel(str, Enum):
    VERY_FORMAL = "very_formal"
    FORMAL = "formal"
    NEUTRAL = "neutral"
    INFORMAL = "informal"
    CASUAL = "casual"


class AvgSentenceLength(str, Enum):
    SHORT = "short"
    MEDIUM = "medium"
    LONG = "long"


class TechnicalLanguageUsage(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class ScheduledDraftStatus(str, Enum):
    PENDING = "pending"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    SENT = "sent"
    CANCELLED = "cancelled"
    HELD = "held"


class InjectionConfidence(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class DataSource(str, Enum):
    GMAIL = "gmail"
    MEETING_NOTES = "meeting_notes"
    USER_INSTRUCTION = "user_instruction"


class AgentResponseType(str, Enum):
    DRAFT = "draft"
    CONTEXT_SUMMARY = "context_summary"
    PERMISSION_REQUEST = "permission_request"
    APPROVAL_GATE = "approval_gate"
    ERROR = "error"
    INFO = "info"
    SEND_CONFIRMED = "send_confirmed"
    DELETE_CONFIRMED = "delete_confirmed"
    SCHEDULE_CONFIRMED = "schedule_confirmed"
    CANCELLED = "cancelled"


# ---------------------------------------------------------------------------
# Session and Authentication
# ---------------------------------------------------------------------------


class OAuthToken(BaseModel):
    """
    Gmail OAuth 2.0 token.
    access_token and refresh_token must never be logged or exposed in responses.
    """

    access_token: str = Field(..., description="Never logged or exposed in responses")
    refresh_token: str = Field(..., description="Never logged or exposed in responses")
    expires_at: datetime
    scopes: list[GmailScope]


class PermissionScope(BaseModel):
    """
    Describes the scope of a permission request, including which data source
    is being accessed and (for Gmail) which OAuth scope is required.
    """

    data_source: Literal["gmail", "meeting_notes", "calendar", "documents"]
    gmail_scope: Optional[GmailScope] = None
    justification: str
    requested_at: datetime = Field(default_factory=datetime.utcnow)


class PermissionGrant(BaseModel):
    """
    A permission that has been explicitly granted by the user.
    expires_at=None means the grant is session-scoped (expires with the session).
    """

    scope: PermissionScope
    granted_at: datetime = Field(default_factory=datetime.utcnow)
    expires_at: Optional[datetime] = None  # None = session-scoped


class SessionContext(BaseModel):
    """
    Active session context for an authenticated user.
    Carries the Gmail OAuth token and the set of permissions granted so far.
    """

    session_id: str = Field(default_factory=lambda: str(uuid4()))
    user_id: str
    created_at: datetime = Field(default_factory=datetime.utcnow)
    last_active_at: datetime = Field(default_factory=datetime.utcnow)
    expires_at: datetime
    gmail_oauth_token: Optional[OAuthToken] = None
    active_permissions: list[PermissionGrant] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Email and Drafts
# ---------------------------------------------------------------------------


class EmailMessage(BaseModel):
    """
    A Gmail email message retrieved via the Gmail API.
    Treated as untrusted content — must be sanitised before reaching the LLM.
    """

    message_id: str
    thread_id: str
    from_address: str = Field(alias="from")
    to: list[str]
    cc: list[str] = Field(default_factory=list)
    subject: str
    body: str
    sent_at: datetime
    labels: list[str] = Field(default_factory=list)

    model_config = {"populate_by_name": True}


class Attachment(BaseModel):
    """File attachment metadata (no content — content is handled separately)."""

    filename: str
    mime_type: str
    size: int


class ContentExcerpt(BaseModel):
    """
    A truncated excerpt from a retrieved data source.
    Full email bodies are never stored in summaries or audit logs.
    """

    source_id: str
    excerpt: str  # truncated, no full bodies in summaries
    retrieved_at: datetime = Field(default_factory=datetime.utcnow)


class DataSourceReference(BaseModel):
    """
    A reference to a single data source used during draft generation.
    Includes excerpts that the user can expand to inspect.
    """

    source: DataSource
    description: str  # e.g. "Email thread with Alice (3 messages)"
    item_count: int
    excerpts: list[ContentExcerpt] = Field(default_factory=list)


class ContextSummary(BaseModel):
    """
    A human-readable explanation of which data sources and content the agent
    used to generate a draft. Displayed to the user before the approval gate.
    """

    summary_id: str = Field(default_factory=lambda: str(uuid4()))
    data_sources: list[DataSourceReference] = Field(default_factory=list)
    generated_from_instruction_only: bool = False


class ToneProfileSummary(BaseModel):
    """
    A human-readable summary of a Tone Profile, shown to the user before
    draft generation so they can review or override the detected tone.
    """

    recipient_email: str
    formality_level: str
    description: str  # human-readable summary shown to user
    last_updated_at: datetime


class Draft(BaseModel):
    """
    An email draft generated by the agent.
    Not yet sent; requires user review and approval gate confirmation.
    """

    draft_id: str = Field(default_factory=lambda: str(uuid4()))
    recipient: str
    cc: list[str] = Field(default_factory=list)
    subject: str
    body: str
    attachments: list[Attachment] = Field(default_factory=list)
    context_summary: ContextSummary
    created_at: datetime = Field(default_factory=datetime.utcnow)
    tone_profile_used: Optional[ToneProfileSummary] = None
    generated_from_instruction: str


class ScheduledDraft(BaseModel):
    """
    A draft that has been approved for delivery at a future time.
    The agent never auto-sends; active confirmation is required at send time.
    """

    scheduled_draft_id: str = Field(default_factory=lambda: str(uuid4()))
    draft: Draft
    scheduled_send_time: datetime
    registered_at: datetime = Field(default_factory=datetime.utcnow)
    status: ScheduledDraftStatus = ScheduledDraftStatus.PENDING
    confirmation_timeout_seconds: int = 300  # 5 minutes default


# ---------------------------------------------------------------------------
# Tone Profiles
# ---------------------------------------------------------------------------


class ToneProfile(BaseModel):
    """
    A persisted characterisation of the user's writing style for a specific
    recipient, derived from sent email history and updated incrementally.
    """

    profile_id: str = Field(default_factory=lambda: str(uuid4()))
    recipient_email: str
    formality_level: FormalityLevel = FormalityLevel.NEUTRAL
    greeting_style: str = "Hi [Name],"
    sign_off_style: str = "Best regards,"
    avg_sentence_length: AvgSentenceLength = AvgSentenceLength.MEDIUM
    technical_language_usage: TechnicalLanguageUsage = TechnicalLanguageUsage.MEDIUM
    warmth_indicator: float = Field(
        default=0.5, ge=0.0, le=1.0
    )  # 0.0 (cold) to 1.0 (warm)
    derived_from_count: int = 0  # number of emails used to derive this profile
    last_updated_at: datetime = Field(default_factory=lambda: datetime.now(tz=timezone.utc))
    created_at: datetime = Field(default_factory=lambda: datetime.now(tz=timezone.utc))


class ToneOverride(BaseModel):
    """
    User-specified tone override applied to a single draft generation.
    Does not modify the persisted ToneProfile.
    """

    formality_level: Optional[FormalityLevel] = None
    custom_description: Optional[str] = None


# ---------------------------------------------------------------------------
# Audit Log
# ---------------------------------------------------------------------------


class AuditEntry(BaseModel):
    """
    A single tamper-evident audit log entry.
    metadata must not contain full email bodies or other sensitive content.
    """

    entry_id: str = Field(default_factory=lambda: str(uuid4()))
    event_type: AuditEventType
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    session_id: str
    description: str
    metadata: dict[str, str] = Field(
        default_factory=dict
    )  # no sensitive content (no full email bodies)


# ---------------------------------------------------------------------------
# Injection Detection
# ---------------------------------------------------------------------------


class InjectionScanResult(BaseModel):
    """
    Result of scanning a piece of content for prompt injection patterns.
    Used by the Prompt Builder & Sanitiser to enforce the trust boundary.
    """

    detected: bool
    confidence: InjectionConfidence
    patterns: list[str] = Field(
        default_factory=list
    )  # descriptions of detected patterns
    source: ContentSource


class InjectionAlert(BaseModel):
    """
    Raised when the sanitiser detects a potential injection attempt.
    Contains both the original and sanitised versions of the content.
    """

    scan_result: InjectionScanResult
    original_content: str
    sanitised_content: str


# ---------------------------------------------------------------------------
# Approval Gates
# ---------------------------------------------------------------------------


class TimeoutResult(BaseModel):
    """
    Returned when a scheduled send confirmation times out.
    The email is held (not sent) and the user is notified.
    """

    outcome: Literal["timed_out"] = "timed_out"
    held_draft_id: str


# ---------------------------------------------------------------------------
# User Instructions
# ---------------------------------------------------------------------------


class UserInstruction(BaseModel):
    """
    A natural language instruction received from the authenticated user.
    This is the only trusted input channel — external content is never treated
    as an instruction.

    instruction_type:
        The type of action being requested. Supported values:
        - "draft"  — generate an email draft (default)
        Additional types (e.g. "send", "delete", "schedule") will be handled
        by later orchestrator tasks.
    """

    instruction_id: str = Field(default_factory=lambda: str(uuid4()))
    session_id: str
    text: str
    instruction_type: str = "draft"
    payload: Any = None
    received_at: datetime = Field(default_factory=datetime.utcnow)


# ---------------------------------------------------------------------------
# Agent Response
# ---------------------------------------------------------------------------


class AgentResponse(BaseModel):
    """
    A structured response returned by the agent to the user interface.
    payload type varies by response type.

    success:
        Convenience flag — True for successful responses, False for errors.
        Defaults to True; set to False for error responses.
    message:
        Human-readable message accompanying the response.  For error
        responses this contains the error description.
    """

    response_id: str = Field(default_factory=lambda: str(uuid4()))
    session_id: str
    type: AgentResponseType
    payload: Any = None
    success: bool = True
    message: str = ""
    created_at: datetime = Field(default_factory=datetime.utcnow)


# ---------------------------------------------------------------------------
# Sanitised Content
# ---------------------------------------------------------------------------


class SanitisedContent(BaseModel):
    """
    The result of passing untrusted content through the sanitiser.
    wrapped_for_llm contains the content enclosed in <untrusted_content> delimiters
    so the LLM treats it as data, never as instructions.
    """

    original: str
    sanitised: str
    source: ContentSource
    wrapped_for_llm: str  # content wrapped in <untrusted_content> delimiters


# ---------------------------------------------------------------------------
# LLM Prompt
# ---------------------------------------------------------------------------


class LLMPrompt(BaseModel):
    """
    The structured prompt sent to the LLM provider.

    - system_prompt: system rules and role definition (trusted, agent-authored only)
    - user_instruction: the authenticated user's request (trusted)
    - data_context: sanitised external content only (untrusted, wrapped in delimiters)

    External content must never appear in system_prompt or user_instruction.
    """

    system_prompt: str
    user_instruction: str
    data_context: str  # sanitised external content only

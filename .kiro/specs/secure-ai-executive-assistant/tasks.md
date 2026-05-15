# Implementation Plan: Secure AI Executive Assistant

## Overview

Implementation is sequenced in dependency order: data models and types first, then foundational services (auth, permissions, audit), then the security-critical prompt sanitiser, then the agent core (orchestrator, tone engine, approval gate, scheduler), and finally integration wiring and the Gmail API client. Property-based tests are placed immediately after the component they validate to catch regressions early.

## Tasks

- [x] 1. Define core Python data models
  - Set up `pyproject.toml` with Python 3.11+, pydantic, pytest, and hypothesis as dependencies
  - Create `src/models/types.py` with all Pydantic models and enums from the design: `SessionContext`, `OAuthToken`, `GmailScope`, `PermissionScope`, `PermissionGrant`, `EmailMessage`, `Draft`, `ScheduledDraft`, `ToneProfile`, `ToneProfileSummary`, `ContextSummary`, `DataSourceReference`, `ContentExcerpt`, `AuditEntry`, `AuditEventType`, `InjectionScanResult`, `InjectionAlert`, `ContentSource`, `ApprovalDecision`, `TimeoutResult`, `UserInstruction`, `AgentResponse`, `SanitisedContent`, `LLMPrompt`
  - Export all models from `src/models/__init__.py`
  - _Requirements: 1.1, 2.7, 5.1, 7.1, 8.2, 12.1, 12.2_

- [x] 2. Implement Authentication & Session Manager
  - [x] 2.1 Implement core authentication and session lifecycle
    - Create `src/auth/session_manager.py` implementing `authenticate`, `validate_session`, `initiate_gmail_oauth`, `handle_oauth_callback`, `revoke_gmail_token`, `refresh_gmail_token`
    - Enforce session inactivity timeout (configurable); store sessions in `SessionStore`
    - Store only the OAuth token — never Gmail credentials
    - _Requirements: 14.1, 14.2, 14.3, 14.6, 14.7_

  - [x] 2.2 Implement failed-authentication rate limiting
    - Track failed attempts per origin; apply exponential back-off after configurable threshold
    - Return a generic error message on failure (no information leakage)
    - _Requirements: 14.4_

  - [ ]* 2.3 Write property test for session expiry blocking sensitive actions (Property 13)
    - **Property 13: Session expiry blocks all sensitive actions**
    - **Validates: Requirements 14.2, 14.3**
    - Generate expired/unauthenticated sessions paired with arbitrary sensitive action types; assert every attempt is rejected

  - [ ]* 2.4 Write property test for failed authentication rate limiting (Property 17)
    - **Property 17: Failed authentication triggers rate limiting**
    - **Validates: Requirements 14.4**
    - Generate sequences of failed auth attempts exceeding the threshold; assert all subsequent attempts are rate-limited until the window expires

  - [ ]* 2.5 Write unit tests for Authentication & Session Manager
    - Test session creation, expiry boundary, OAuth token storage, token refresh, and revocation
    - Test that expired sessions cannot execute sensitive actions
    - _Requirements: 14.1, 14.2, 14.6, 14.7_

- [x] 3. Implement Permission Manager
  - [x] 3.1 Implement permission grant, check, revoke, and list operations
    - Create `src/permissions/permission_manager.py` implementing `request_permission`, `check_permission`, `revoke_permission`, `list_active_permissions`
    - Track granted permissions per session; enforce minimum-scope access
    - Handle incremental OAuth scope requests at point of need
    - _Requirements: 10.1, 10.2, 10.3, 10.6_

  - [x] 3.2 Implement permission revocation with cache invalidation
    - On revocation, immediately cease access to the source and clear any cached data for that scope
    - _Requirements: 10.4, 10.5_

  - [ ]* 3.3 Write property test for permission check before data access (Property 6)
    - **Property 6: Permission check precedes every data access**
    - **Validates: Requirements 3.1, 3.2, 4.1, 4.2, 10.1, 10.6**
    - Generate data access requests with varying permission states (granted, denied, expired); assert no access occurs without a valid prior grant

  - [ ]* 3.4 Write property test for permission revocation stopping data access (Property 14)
    - **Property 14: Permission revocation immediately stops data access**
    - **Validates: Requirements 10.4, 10.5**
    - Generate revocation events followed by subsequent access attempts for the same scope; assert all post-revocation attempts are denied and cached data is cleared

  - [ ]* 3.5 Write unit tests for Permission Manager
    - Test grant/check/revoke lifecycle, minimum-scope enforcement, and active permission listing
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5, 10.6_

- [x] 4. Implement Audit Logger
  - [x] 4.1 Implement append-only audit log with required field enforcement
    - Create `src/audit/audit_logger.py` implementing `log` and `query`
    - Enforce that every entry contains `eventType`, `timestamp`, and `description`; exclude full email bodies from metadata
    - Persist entries to `AuditLogStore`; prevent modification or deletion by any agent operation or untrusted content
    - _Requirements: 12.1, 12.2, 12.3, 12.4_

  - [x] 4.2 Implement reverse-chronological query with event-type filtering
    - `query(filter)` returns entries sorted most-recent-first; supports filtering by `AuditEventType`
    - _Requirements: 12.5_

  - [ ]* 4.3 Write property test for audit log append-only invariant (Property 9)
    - **Property 9: Audit log entries are append-only**
    - **Validates: Requirements 12.4**
    - Generate sequences of audit events; assert all written entries are present, in write order, with no modifications or omissions

  - [ ]* 4.4 Write property test for audit log required fields and no full email bodies (Property 10)
    - **Property 10: Audit log entries contain required fields and no full email bodies**
    - **Validates: Requirements 12.1, 12.2**
    - Generate audit events involving email data; assert every entry has `eventType`, `timestamp`, and `description`, and that no entry's metadata contains a full email body

  - [ ]* 4.5 Write property test for audit log reverse chronological display (Property 16)
    - **Property 16: Audit log displayed in reverse chronological order**
    - **Validates: Requirements 12.5**
    - Generate sets of entries with arbitrary distinct timestamps; assert the query result is strictly reverse-chronological regardless of write order

  - [ ]* 4.6 Write unit tests for Audit Logger
    - Test all `AuditEventType` values, filtering, and tamper-resistance
    - _Requirements: 12.1, 12.2, 12.3, 12.4, 12.5_

- [x] 5. Checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 6. Implement Prompt Builder & Sanitiser
  - [x] 6.1 Implement injection pattern detection
    - Create `src/prompt/sanitiser.py` implementing `detect_injection_patterns`
    - Detect imperative agent commands, role-override phrases, permission escalation language, and delimiter injection attempts
    - Return `InjectionScanResult` with confidence level and matched pattern descriptions
    - _Requirements: 8.2, 8.3, 9.1_

  - [x] 6.2 Implement content sanitisation and contextual wrapping
    - Implement `sanitise_content(raw, source)` — wraps external content in `<untrusted_content source="...">` delimiters; enforces maximum token limits; returns `SanitisedContent | InjectionAlert`
    - On high-confidence detection: flag prominently, log `PROMPT_INJECTION_DETECTED`, notify user, ask whether to proceed or discard
    - On low-confidence detection: sanitise, wrap, proceed with subtle notification
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 9.3, 9.4_

  - [x] 6.3 Implement prompt construction with strict role separation
    - Implement `build_draft_prompt(instruction, context, tone_profile)` — system prompt and user instruction sections contain only authenticated-session content; sanitised external content appears only in the data context role
    - _Requirements: 8.1, 8.5, 9.1, 9.2_

  - [ ]* 6.4 Write property test for untrusted content never reaching LLM as instructions (Property 1)
    - **Property 1: Untrusted content never reaches the LLM as instructions**
    - **Validates: Requirements 8.1, 9.1, 9.2**
    - Generate arbitrary strings as external content; build prompts; assert external content appears only in the data context role, never in system prompt or user instruction sections

  - [ ]* 6.5 Write property test for injection pattern detection consistency (Property 2)
    - **Property 2: Injection pattern detection is consistent**
    - **Validates: Requirements 8.2, 8.3**
    - Generate strings with known injection patterns and strings without; assert the sanitiser detects all injected strings and produces no false positives on clean strings

  - [ ]* 6.6 Write property test for untrusted content not altering system state (Property 15)
    - **Property 15: Untrusted content cannot alter system state or permissions**
    - **Validates: Requirements 9.3, 9.4**
    - Generate content containing permission-escalation instructions and role-override directives; process through sanitiser; assert permission state, session context, and operational rules are entirely unchanged after processing

  - [ ]* 6.7 Write unit tests for Prompt Builder & Sanitiser
    - Test known injection corpus, clean content, delimiter injection, context overflow truncation, and role separation
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 9.1, 9.2, 9.3, 9.4_

- [x] 7. Implement Gmail API Client
  - [x] 7.1 Implement Gmail API wrapper with OAuth token enforcement
    - Create `src/gmail/gmail_client.py` implementing `list_messages`, `get_thread`, `get_sent_history`, `send_message`, `create_draft`, `delete_message`
    - Authenticate every request with the user's OAuth token; enforce scope restrictions per operation
    - Handle token expiry (trigger re-authorisation), API rate limits (exponential back-off with jitter), and network failures (surface descriptive errors)
    - _Requirements: 3.3, 3.4, 10.7, 14.5, 14.7_

  - [ ]* 7.2 Write unit tests for Gmail API Client
    - Test OAuth token attachment, scope enforcement, rate-limit back-off, token expiry handling, and error surfacing
    - _Requirements: 3.3, 10.7, 14.5, 14.7_

- [x] 8. Implement Tone Profile Engine
  - [x] 8.1 Implement Tone Profile derivation from sent history
    - Create `src/tone/tone_profile_engine.py` implementing `get_or_derive_profile`
    - Analyse sent email history for a recipient to derive formality, greeting/sign-off style, sentence length, technical language usage, and warmth indicator
    - Apply neutral professional tone when no history exists; notify user
    - _Requirements: 2.1, 2.4_

  - [x] 8.2 Implement Tone Profile persistence and retrieval
    - Implement store/retrieve operations against `ToneProfileStore`; persist profiles across sessions
    - _Requirements: 2.7_

  - [x] 8.3 Implement incremental profile update and tone override
    - Implement `update_profile(recipient_email, sent_email)` — increment `derived_from_count` by 1, preserve all existing fields, incorporate new email signal
    - Implement `apply_override(profile, override)` — apply user-specified tone without modifying the persisted profile
    - _Requirements: 2.3, 2.5, 2.6_

  - [ ]* 8.4 Write property test for Tone Profile round-trip persistence (Property 7)
    - **Property 7: Tone Profile round-trip persistence**
    - **Validates: Requirements 2.7**
    - Generate arbitrary `ToneProfile` instances; serialise to store and retrieve in a new session; assert all fields are preserved with no data loss

  - [ ]* 8.5 Write property test for Tone Profile incremental update (Property 8)
    - **Property 8: Tone Profile incremental update preserves prior data**
    - **Validates: Requirements 2.6, 2.7**
    - Generate existing profiles and new sent emails; apply `updateProfile`; assert `derivedFromCount` is exactly one greater and all prior fields remain present

  - [ ]* 8.6 Write unit tests for Tone Profile Engine
    - Test derivation from empty history (neutral fallback), profile retrieval, override application, and incremental update
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7_

- [x] 9. Implement Approval Gate Controller
  - [x] 9.1 Implement send, delete, and schedule approval gates
    - Create `src/approval/approval_gate_controller.py` implementing `present_send_gate`, `present_delete_gate`, `present_schedule_gate`
    - Each gate blocks execution until an explicit `confirmed` or `cancelled` decision is received
    - `presentSendGate` displays recipient, subject, full body, attachments, and Context Summary
    - `presentDeleteGate` displays sender, subject, and date
    - `presentScheduleGate` displays email content, recipient, and proposed send time
    - _Requirements: 5.1, 5.2, 5.4, 6.1, 6.2, 6.4, 7.1, 7.2_

  - [x] 9.2 Implement scheduled send active confirmation with timeout
    - Implement `present_scheduled_send_confirmation(scheduled_draft, timeout)` — present active confirmation prompt at send time; if no confirmation within timeout, return `TimeoutResult` and hold the email
    - _Requirements: 7.5, 7.6_

  - [ ]* 9.3 Write property test for approval gate always preceding sensitive actions (Property 3)
    - **Property 3: Approval gate always precedes sensitive action execution**
    - **Validates: Requirements 5.2, 5.5, 6.2, 6.4, 7.2**
    - Generate arbitrary sensitive action requests; assert a gate is always presented before execution and no action executes after a `cancelled` decision

  - [ ]* 9.4 Write property test for confirmed action producing execution and audit entry (Property 4)
    - **Property 4: Confirmed action produces both execution and audit entry**
    - **Validates: Requirements 5.3, 6.3, 7.3**
    - Generate confirmed approval decisions; assert both the action executes and a corresponding audit log entry is created — neither may occur without the other

  - [ ]* 9.5 Write property test for scheduled send active confirmation (Property 5)
    - **Property 5: Scheduled sends require active confirmation at send time**
    - **Validates: Requirements 7.5, 7.6**
    - Generate scheduled drafts with varying timeout durations; simulate send-time arrival without confirmation; assert email is held with status `held` and user is notified — never auto-sent

  - [ ]* 9.6 Write unit tests for Approval Gate Controller
    - Test confirmed/cancelled state transitions, context summary display, timeout hold behaviour, and cancellation leaving email unchanged
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 6.1, 6.2, 6.3, 6.4, 7.1, 7.2, 7.5, 7.6_

- [x] 10. Checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 11. Implement Scheduled Draft Manager
  - [x] 11.1 Implement scheduled draft lifecycle management
    - Create `src/scheduling/scheduled_draft_manager.py` implementing `register_scheduled_draft`, `cancel_scheduled_draft`, `edit_scheduled_draft`, `list_scheduled_drafts`, `trigger_send_time_confirmation`
    - Register drafts after approval gate confirmation; allow cancellation and editing before send time
    - At send time, call `triggerSendTimeConfirmation` — never auto-send; hold with status `held` if confirmation not received
    - _Requirements: 7.3, 7.4, 7.5, 7.6_

  - [x]* 11.2 Write unit tests for Scheduled Draft Manager
    - Test register → cancel, register → edit, register → send-time confirmation → send, and register → timeout → hold flows
    - _Requirements: 7.3, 7.4, 7.5, 7.6_

- [x] 12. Implement Agent Orchestrator
  - [x] 12.1 Implement core instruction processing and subsystem coordination
    - Create `src/orchestrator/agent_orchestrator.py` implementing `process_instruction(session_ctx, instruction)`
    - Validate session via `SessionManager.validateSession` before processing any instruction
    - Coordinate permission checks via `PermissionManager` before any data access
    - Route to `GmailClient`, `ToneProfileEngine`, `PromptBuilder`, and LLM provider in the correct sequence
    - Maintain conversation context within a session
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.6, 2.1, 2.2, 3.1, 3.2, 3.3, 4.1, 4.2, 4.3, 9.2_

  - [x] 12.2 Implement draft generation flow with Context Summary construction
    - After LLM draft generation, construct `ContextSummary` referencing every data source accessed
    - Display tone profile to user before draft generation; display Context Summary alongside draft
    - _Requirements: 1.5, 2.2, 3.5, 4.4, 13.1, 13.3, 13.4_

  - [x] 12.3 Implement send, delete, and schedule action flows with approval gates
    - For send: call `ApprovalGateController.presentSendGate`; on `confirmed`, call `GmailClient.sendMessage` and `AuditLogger.log(EMAIL_SENT)`; on `cancelled`, return to draft view
    - For delete: call `ApprovalGateController.presentDeleteGate`; on `confirmed`, call `GmailClient.deleteMessage` and `AuditLogger.log(EMAIL_DELETED)`; on `cancelled`, abort
    - For schedule: call `ApprovalGateController.presentScheduleGate`; on `confirmed`, call `ScheduledDraftManager.registerScheduledDraft` and `AuditLogger.log(SCHEDULED_DRAFT_REGISTERED)`
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 6.1, 6.2, 6.3, 6.4, 7.1, 7.2, 7.3_

  - [x] 12.4 Wire audit logging for all specified event types
    - Emit `AuditLogger.log` calls for: `DRAFT_CREATED`, `EMAIL_CONTEXT_ACCESSED`, `MEETING_NOTES_ACCESSED`, `PERMISSION_GRANTED`, `PERMISSION_REVOKED`, `APPROVAL_GATE_PRESENTED`, `EMAIL_SENT`, `EMAIL_DELETED`, `SCHEDULED_DRAFT_REGISTERED`, `SCHEDULED_DRAFT_CANCELLED`, `PROMPT_INJECTION_DETECTED`, `AUTH_FAILED`, `SESSION_STARTED`, `SESSION_EXPIRED`, `GMAIL_TOKEN_REVOKED`
    - _Requirements: 12.1_

  - [ ]* 12.5 Write property test for Context Summary completeness (Property 11)
    - **Property 11: Context Summary completeness**
    - **Validates: Requirements 1.5, 3.5, 4.4, 13.1**
    - Generate drafts using multiple data sources; assert the Context Summary references every accessed source with no omissions

  - [ ]* 12.6 Write property test for Context Summary displayed before approval gate (Property 12)
    - **Property 12: Context Summary displayed before approval gate**
    - **Validates: Requirements 13.2**
    - Generate drafts with context summaries; assert the summary is shown to the user before the approval gate is presented — gate must not appear first

  - [ ]* 12.7 Write property test for draft structure completeness (Property 18)
    - **Property 18: Draft structure completeness**
    - **Validates: Requirements 1.1**
    - Generate arbitrary valid user instructions; assert every resulting Draft has a non-empty recipient, non-empty subject, and non-empty body

  - [ ]* 12.8 Write unit tests for Agent Orchestrator
    - Test full draft generation flow, send/delete/schedule flows, session validation enforcement, and error handling (insufficient instructions, LLM failure, tone profile unavailable)
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 2.1, 2.2, 5.1–5.5, 6.1–6.4, 7.1–7.3, 13.1–13.4_

- [x] 13. Checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 14. Integration wiring and end-to-end flows
  - [x] 14.1 Wire full draft generation integration flow
    - Connect: authenticated instruction → permission prompt → Gmail fetch → sanitisation → LLM → tone display → draft display with Context Summary
    - Verify the trust boundary: raw Gmail data passes through `PromptBuilder.sanitiseContent` before reaching the LLM
    - _Requirements: 1.1, 1.2, 1.5, 2.1, 2.2, 3.1–3.5, 8.1, 9.1, 9.2, 13.1, 13.2_

  - [x] 14.2 Wire full send flow integration
    - Connect: draft → approval gate (with Context Summary) → Gmail send → audit log entry
    - _Requirements: 5.1, 5.2, 5.3, 12.1_

  - [x] 14.3 Wire Gmail OAuth integration flow
    - Connect: `initiateGmailOAuth` → callback → token storage → token refresh → revocation → `GMAIL_TOKEN_REVOKED` audit event
    - _Requirements: 10.7, 14.5, 14.6, 14.7_

  - [x] 14.4 Wire scheduled draft lifecycle integration
    - Connect: register → edit → cancel; register → send-time `triggerSendTimeConfirmation` → confirmed → send; register → timeout → hold → user notification
    - _Requirements: 7.3, 7.4, 7.5, 7.6_

  - [ ]* 14.5 Write integration tests for full draft and send flows
    - Test end-to-end: instruction → permission → Gmail fetch → sanitisation → LLM → draft display → approval gate → send → audit log
    - Use mocked Gmail API and LLM provider
    - _Requirements: 1.1, 1.5, 3.1–3.5, 5.1–5.3, 8.1, 12.1, 13.1, 13.2_

  - [ ]* 14.6 Write integration tests for prompt injection end-to-end
    - Test: injected email body → detection → user notification → audit log entry; verify system state unchanged after processing
    - _Requirements: 8.1–8.5, 9.1–9.4_

  - [ ]* 14.7 Write integration tests for scheduled draft lifecycle
    - Test register → send-time confirmation → send; register → timeout → hold; register → cancel
    - _Requirements: 7.3–7.6_

- [x] 15. Final checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for a faster MVP
- Each task references specific requirements for traceability
- Checkpoints at tasks 5, 10, 13, and 15 ensure incremental validation
- Property tests validate universal correctness properties (Properties 1–18 from the design document)
- Unit tests validate specific examples and edge cases
- All 18 correctness properties from the design are covered by property-based test sub-tasks
- The trust boundary (untrusted external content → `PromptBuilder.sanitiseContent` → LLM) must be enforced at every integration point

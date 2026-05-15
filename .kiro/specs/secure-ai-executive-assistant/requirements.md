# Requirements Document

## Introduction

The Secure AI Executive Assistant is an AI-powered agent that helps business professionals manage email workflows, meeting information, and workplace communication tasks. The agent can draft emails, retrieve relevant email context, adapt writing tone per recipient, extract meeting note insights, and prepare scheduled email drafts.

The defining characteristic of this system is its safety-first design: the agent operates under strict human-in-the-loop controls, permission-based data access, and active defences against prompt injection and third-party manipulation. The agent never sends, deletes, forwards, or modifies emails without explicit user approval. Users remain in full control of all sensitive actions at all times.

Email data access is provided exclusively through Gmail via OAuth 2.0. The Agent reads from the User's Gmail account to retrieve email context, build Tone Profiles, and support draft generation. No other email platform is in scope for this version.

---

## Glossary

- **Agent**: The Secure AI Executive Assistant system that processes user instructions and generates outputs.
- **User**: The authenticated human operator who issues instructions to the Agent and approves sensitive actions.
- **Draft**: An email composition created by the Agent that has not been sent and requires User review before any further action.
- **Approval Gate**: A UI confirmation step that requires explicit User action before the Agent executes a sensitive operation.
- **Sensitive Action**: Any operation that reads personal data, modifies state, or communicates externally — including sending, deleting, forwarding, scheduling, or accessing emails, meeting notes, or calendar data.
- **Untrusted Content**: Any data retrieved from external sources, including email bodies, meeting notes, calendar entries, and third-party documents.
- **Prompt Injection**: An attack where Untrusted Content contains instructions intended to manipulate the Agent into performing unauthorised actions.
- **Permission Model**: The set of explicit, User-granted access rights that govern which data sources the Agent may read.
- **Tone Profile**: A characterisation of the User's writing style for a specific recipient or recipient group, derived from the User's Gmail sent history and previous replies to that recipient. Tone Profiles are persisted across sessions and updated incrementally as new emails are sent.
- **Gmail OAuth Token**: The OAuth 2.0 access credential granted by the User that authorises the Agent to access the User's Gmail account within the approved permission scope.
- **Audit Log**: A tamper-evident record of Agent actions, approval decisions, and data access events.
- **Context Summary**: A human-readable explanation of which data sources and content the Agent used to generate a Draft.
- **Scheduled Draft**: A Draft that the User has approved for delivery at a specified future time.

---

## Requirements

### Requirement 1: Email Draft Generation

**User Story:** As a business professional, I want the Agent to draft emails from my natural language instructions, so that I can communicate efficiently without writing from scratch.

#### Acceptance Criteria

1. WHEN the User provides a natural language instruction to draft an email, THE Agent SHALL generate a Draft containing a recipient, subject line, and body.
2. WHEN a Draft is generated, THE Agent SHALL display the Draft to the User for review before any further action is taken.
3. WHEN the User requests a revision to a Draft, THE Agent SHALL regenerate the Draft incorporating the User's requested changes.
4. THE Agent SHALL allow the User to manually edit any field of a Draft before approval.
5. WHEN a Draft is generated using retrieved email context or meeting notes, THE Agent SHALL display a Context Summary alongside the Draft.
6. IF the Agent cannot generate a Draft due to insufficient instructions, THEN THE Agent SHALL prompt the User for the missing information rather than producing an incomplete Draft.

---

### Requirement 2: Tone Adaptation

**User Story:** As an executive, I want the Agent to match my writing style for each recipient, so that my emails feel personal and professionally appropriate.

#### Acceptance Criteria

1. WHEN the User requests a Draft for a specific recipient, THE Agent SHALL retrieve the persisted Tone Profile for that recipient if one exists, or derive a new Tone Profile by analysing the User's Gmail sent history for emails addressed to that recipient.
2. WHEN a Tone Profile is derived or retrieved, THE Agent SHALL display the identified tone to the User before generating the Draft.
3. THE Agent SHALL allow the User to override the suggested tone by selecting from a set of predefined tone options or providing a free-text tone description.
4. WHEN no prior Gmail sent history exists for a recipient, THE Agent SHALL notify the User and apply a neutral professional tone as the default.
5. WHEN the User overrides the tone, THE Agent SHALL apply the User-specified tone and regenerate the Draft.
6. WHEN the User sends an email to a recipient, THE Agent SHALL update the Tone Profile for that recipient incrementally to incorporate the newly sent email.
7. THE Agent SHALL persist Tone Profiles across sessions so that previously derived profiles are available without re-analysis on subsequent sessions.

---

### Requirement 3: Permission-Based Gmail Context Retrieval

**User Story:** As a user, I want the Agent to find related emails in my Gmail account to inform my drafts, so that my replies are accurate and contextually aware.

#### Acceptance Criteria

1. WHEN the User requests retrieval of related emails, THE Agent SHALL present a permission prompt specifying the scope of Gmail access (sender, subject, keywords, or conversation thread) before accessing any Gmail data.
2. WHILE the User has not granted permission for a specific retrieval scope, THE Agent SHALL not access Gmail data within that scope.
3. WHEN the User grants retrieval permission, THE Agent SHALL retrieve only Gmail messages relevant to the stated request scope using the User's Gmail OAuth Token.
4. THE Agent SHALL not expose Gmail message content unrelated to the User's stated request.
5. WHEN retrieved Gmail messages are used to inform a Draft, THE Agent SHALL include those messages in the Context Summary.
6. IF no relevant Gmail messages are found for the requested scope, THEN THE Agent SHALL notify the User and proceed without email context.

---

### Requirement 4: Permission-Based Meeting Notes Retrieval

**User Story:** As a manager, I want the Agent to pull in meeting notes when drafting follow-up emails, so that my communications accurately reflect decisions and action items.

#### Acceptance Criteria

1. WHEN the User requests access to meeting notes, THE Agent SHALL present a permission prompt identifying the meeting source before accessing any meeting data.
2. WHILE the User has not granted permission for a meeting notes source, THE Agent SHALL not access data from that source.
3. WHEN the User grants permission, THE Agent SHALL retrieve meeting notes and extract key points, decisions, action items, and deadlines.
4. WHEN meeting notes are used to generate a Draft, THE Agent SHALL display the extracted key points in the Context Summary before the User approves the Draft.
5. IF meeting notes cannot be retrieved from an approved source, THEN THE Agent SHALL notify the User with a descriptive error and continue without that context.

---

### Requirement 5: Human Approval Gate for Sending Emails

**User Story:** As a user, I want to explicitly approve every email before it is sent, so that I remain in full control of outbound communication.

#### Acceptance Criteria

1. WHEN the User initiates a send action on a Draft, THE Agent SHALL display an Approval Gate showing the recipient, subject, full email body, any attachments, and the Context Summary.
2. WHILE the User has not confirmed the Approval Gate, THE Agent SHALL not transmit the email.
3. WHEN the User confirms the Approval Gate, THE Agent SHALL send the email and record the action in the Audit Log.
4. WHEN the User cancels the Approval Gate, THE Agent SHALL return the User to the Draft view without sending.
5. THE Agent SHALL not send any email through an automated process, scheduled trigger, or background task without a prior explicit User approval for that specific email.

---

### Requirement 6: Human Approval Gate for Email Deletion

**User Story:** As a user, I want to confirm every deletion request, so that emails are never removed without my knowledge.

#### Acceptance Criteria

1. WHEN the User requests deletion of an email, THE Agent SHALL display an Approval Gate identifying the email by sender, subject, and date before performing the deletion.
2. WHILE the User has not confirmed the deletion Approval Gate, THE Agent SHALL not delete the email.
3. WHEN the User confirms the deletion Approval Gate, THE Agent SHALL delete the email and record the action in the Audit Log.
4. WHEN the User cancels the deletion Approval Gate, THE Agent SHALL abort the deletion and leave the email unchanged.

---

### Requirement 7: Scheduled Draft Preparation

**User Story:** As a professional, I want to prepare emails for delivery at a future time, so that I can plan communications in advance.

#### Acceptance Criteria

1. WHEN the User requests to schedule a Draft, THE Agent SHALL display an Approval Gate showing the email content, recipient, and the proposed send time before scheduling.
2. WHILE the User has not confirmed the scheduling Approval Gate, THE Agent SHALL not register the Scheduled Draft.
3. WHEN the User confirms the scheduling Approval Gate, THE Agent SHALL register the Scheduled Draft and record the action in the Audit Log.
4. WHEN a Scheduled Draft is registered, THE Agent SHALL allow the User to cancel or edit the Scheduled Draft at any time before the scheduled send time.
5. WHEN the scheduled send time arrives, THE Agent SHALL present an active confirmation prompt to the User requiring the User to explicitly click a confirm button before the email is transmitted.
6. IF the User does not confirm the active confirmation prompt within a configurable timeout period, THEN THE Agent SHALL hold the email without sending and notify the User that confirmation is required.

---

### Requirement 8: Prompt Injection Prevention

**User Story:** As a security-conscious user, I want the Agent to ignore instructions embedded in emails or documents, so that third parties cannot hijack the Agent's behaviour.

#### Acceptance Criteria

1. THE Agent SHALL treat all Untrusted Content as data and not as instructions.
2. WHEN the Agent processes Untrusted Content, THE Agent SHALL apply input sanitisation to detect and neutralise instruction-like patterns before using the content.
3. IF Untrusted Content contains patterns that resemble Agent instructions or commands, THEN THE Agent SHALL flag the content as a potential Prompt Injection attempt and notify the User.
4. WHEN a Prompt Injection attempt is flagged, THE Agent SHALL record the event in the Audit Log including the source of the Untrusted Content.
5. THE Agent SHALL only execute instructions that originate from the authenticated User through the verified input channel.

---

### Requirement 9: Third-Party Manipulation Prevention

**User Story:** As a user, I want the Agent to distinguish my instructions from content in emails and documents, so that external parties cannot manipulate the Agent's actions.

#### Acceptance Criteria

1. THE Agent SHALL maintain strict separation between User instructions, system rules, retrieved email content, meeting note content, and third-party messages at all times.
2. WHEN processing a request, THE Agent SHALL only treat input received through the authenticated User session as a command.
3. THE Agent SHALL not alter its behaviour, permissions, or operational rules based on content found in Untrusted Content.
4. IF retrieved content attempts to grant itself elevated permissions or override system rules, THEN THE Agent SHALL discard the instruction, log the event in the Audit Log, and notify the User.

---

### Requirement 10: Permission Model and Data Access Control

**User Story:** As a user, I want to control exactly which data sources the Agent can access, so that my private information is only used when I explicitly allow it.

#### Acceptance Criteria

1. THE Agent SHALL require explicit User-granted permission before accessing any data source, including the User's Gmail account, meeting note repositories, calendars, and documents.
2. WHEN the User grants permission for a data source, THE Agent SHALL restrict access to the minimum scope necessary to fulfil the current request.
3. THE Agent SHALL display the current set of active permissions to the User on request, including the active Gmail OAuth Token scope.
4. WHEN the User revokes permission for a data source, THE Agent SHALL immediately cease access to that source and remove any cached data from that source.
5. THE Agent SHALL not retain data retrieved from a permission-gated source beyond the scope of the request for which permission was granted.
6. IF a requested operation requires access to a data source for which permission has not been granted, THEN THE Agent SHALL request permission from the User before proceeding.
7. WHEN the User authenticates with Gmail, THE Agent SHALL initiate the Gmail OAuth 2.0 authorisation flow and store only the resulting OAuth Token, not the User's Gmail credentials.

---

### Requirement 11: Data Privacy and Minimal Disclosure

**User Story:** As a user, I want the Agent to access only the data needed for my request, so that my private information is not unnecessarily exposed.

#### Acceptance Criteria

1. WHEN retrieving data to fulfil a request, THE Agent SHALL access only the data directly relevant to the User's stated request.
2. THE Agent SHALL not include personal or sensitive email content in responses beyond what is necessary to complete the requested task.
3. THE Agent SHALL not transmit User data, email content, or meeting note content to third-party services without explicit User consent.
4. WHEN displaying retrieved data to the User, THE Agent SHALL clearly identify the source of each piece of information.
5. THE Agent SHALL not store retrieved personal data beyond the active session unless the User explicitly enables persistent storage.

---

### Requirement 12: Audit Logging

**User Story:** As a user, I want a record of what the Agent has done, so that I can review its actions and maintain accountability.

#### Acceptance Criteria

1. THE Agent SHALL record an Audit Log entry for each of the following events: Draft created, email context accessed, meeting notes accessed, permission granted, permission revoked, Approval Gate presented, email sent after approval, email deletion after approval, Scheduled Draft registered, Scheduled Draft cancelled, and Prompt Injection attempt detected.
2. WHEN an Audit Log entry is created, THE Agent SHALL include the event type, timestamp, and a description of the action without storing unnecessary sensitive content such as full email bodies.
3. THE Agent SHALL make the Audit Log available to the User on request.
4. THE Agent SHALL not allow Audit Log entries to be deleted or modified by the Agent itself or by Untrusted Content.
5. WHEN the User reviews the Audit Log, THE Agent SHALL display entries in reverse chronological order with filtering by event type.

---

### Requirement 13: Transparent Context Display

**User Story:** As a user, I want to see exactly what information the Agent used to generate a draft, so that I can verify its accuracy before approving.

#### Acceptance Criteria

1. WHEN a Draft is generated using any retrieved data, THE Agent SHALL produce a Context Summary listing each data source accessed, the type of content retrieved, and the specific items used.
2. THE Agent SHALL display the Context Summary to the User before the User is asked to approve or send the Draft.
3. WHEN no external data was used to generate a Draft, THE Agent SHALL indicate that the Draft was generated from the User's instruction alone.
4. THE Agent SHALL allow the User to expand the Context Summary to view the specific email excerpts or meeting note extracts that informed the Draft.

---

### Requirement 14: Authentication and Session Security

**User Story:** As a user, I want the Agent to verify my identity before granting access, so that unauthorised parties cannot use the Agent on my behalf.

#### Acceptance Criteria

1. THE Agent SHALL require User authentication before initiating any session.
2. WHEN a session is inactive for a configurable period, THE Agent SHALL terminate the session and require re-authentication.
3. THE Agent SHALL not execute any Sensitive Action during an unauthenticated or expired session.
4. IF an authentication attempt fails, THEN THE Agent SHALL log the failed attempt and apply a rate limit to subsequent attempts from the same origin.
5. THE Agent SHALL communicate with all external data sources, including the Gmail API, over encrypted connections using industry-standard protocols.
6. WHEN the User connects their Gmail account, THE Agent SHALL authenticate exclusively via the Gmail OAuth 2.0 flow and SHALL NOT request or store the User's Gmail password.
7. WHEN the User's Gmail OAuth Token expires or is revoked, THE Agent SHALL suspend all Gmail data access and prompt the User to re-authorise before continuing.

# Requirements Document

## Introduction

The Agent UI is a web-based frontend that allows users to sign in to the Secure AI Executive Assistant and manage their settings for using the AI agent. It provides a sign-in screen backed by the existing Python authentication backend, a Gmail OAuth connection flow, and a settings panel where users can configure agent behaviour, manage permissions, review their tone profiles, and inspect the audit log.

The UI communicates exclusively with the existing Python backend (src/) via a REST or WebSocket API. All security enforcement — session management, permission checks, approval gates, and audit logging — remains in the backend. The UI is responsible for presenting information clearly, collecting user input, and routing actions to the backend.

---

## Glossary

- **UI**: The Agent UI web application described in this document.
- **User**: The authenticated human operator interacting with the UI.
- **Backend**: The existing Python application in `src/` that implements authentication, permissions, audit logging, Gmail integration, tone profiling, approval gates, scheduling, and the agent orchestrator.
- **Session**: An authenticated session managed by the Backend's `SessionManager`. The UI holds a session token and presents it with every request.
- **Sign-In Screen**: The initial UI view presented to unauthenticated users, where they provide credentials to start a session.
- **Settings Panel**: The UI view where the User configures agent behaviour, manages Gmail connection, reviews permissions, and inspects tone profiles and the audit log.
- **Agent Chat View**: The primary UI view where the User issues natural language instructions to the agent and reviews drafts, approval gates, and agent responses.
- **Gmail Connection**: The OAuth 2.0 flow that links the User's Gmail account to the agent, initiated from the Settings Panel.
- **Tone Profile Card**: A UI component that displays a derived Tone Profile for a specific recipient, allowing the User to review or override it.
- **Audit Log View**: A UI component that displays the Backend's audit log entries in reverse chronological order with filtering.
- **Approval Gate Dialog**: A modal UI component that presents a sensitive action for explicit User confirmation or cancellation.
- **Permission Prompt**: A UI component that requests the User's consent before the agent accesses a data source.

---

## Requirements

### Requirement 1: Sign-In

**User Story:** As a user, I want to sign in with my credentials, so that I can access the AI agent securely.

#### Acceptance Criteria

1. THE UI SHALL display a Sign-In Screen to any unauthenticated visitor before granting access to any other view.
2. WHEN the User submits credentials on the Sign-In Screen, THE UI SHALL send the credentials to the Backend authentication endpoint and await the response.
3. WHEN the Backend returns a valid session token, THE UI SHALL store the session token in memory for the duration of the browser session and navigate the User to the Agent Chat View.
4. IF the Backend returns an authentication failure, THEN THE UI SHALL display a generic error message without revealing whether the user identifier or password was incorrect.
5. IF the Backend returns a rate-limit response, THEN THE UI SHALL display a message informing the User that further attempts are temporarily blocked and indicate when they may retry.
6. THE UI SHALL not store the User's password in browser storage, cookies, or any persistent medium.
7. WHEN the User's session expires or is terminated by the Backend, THE UI SHALL redirect the User to the Sign-In Screen and clear all session state from memory.
8. THE UI SHALL provide a visible sign-out control that, when activated, calls the Backend session termination endpoint and returns the User to the Sign-In Screen.

---

### Requirement 2: Session Continuity and Security

**User Story:** As a user, I want my session to remain active while I am working and to expire safely when I am idle, so that my account is protected.

#### Acceptance Criteria

1. WHILE a valid session token is held, THE UI SHALL include the session token in every request sent to the Backend.
2. WHEN the Backend returns a session-expired response on any request, THE UI SHALL immediately redirect the User to the Sign-In Screen and discard the session token.
3. THE UI SHALL not cache or persist session tokens in localStorage, sessionStorage, or cookies beyond the active browser tab.
4. WHEN the User navigates away from the UI or closes the browser tab, THE UI SHALL discard the in-memory session token.
5. IF the UI receives an unauthenticated response from the Backend on a non-sign-in request, THEN THE UI SHALL redirect the User to the Sign-In Screen without exposing internal error details.

---

### Requirement 3: Gmail Account Connection

**User Story:** As a user, I want to connect my Gmail account from the Settings Panel, so that the agent can access my emails to assist me.

#### Acceptance Criteria

1. WHEN the User navigates to the Settings Panel, THE UI SHALL display the current Gmail connection status (connected or not connected), including the active OAuth scopes if connected.
2. WHEN the User initiates a Gmail connection, THE UI SHALL call the Backend to obtain the Gmail OAuth authorisation URL and redirect the User's browser to that URL.
3. WHEN the OAuth callback is received, THE UI SHALL pass the authorisation code and state parameter to the Backend callback endpoint and display the updated connection status.
4. IF the OAuth flow fails or is cancelled by the User, THEN THE UI SHALL display a descriptive error message and return the User to the Settings Panel without altering the existing connection state.
5. WHEN the User disconnects their Gmail account, THE UI SHALL call the Backend token revocation endpoint, confirm the revocation, and update the displayed connection status to not connected.
6. WHILE the Gmail account is not connected, THE UI SHALL display a prompt in the Agent Chat View informing the User that Gmail access is required for context retrieval and tone profiling.

---

### Requirement 4: Agent Settings Configuration

**User Story:** As a user, I want to configure the agent's behaviour from the Settings Panel, so that it operates according to my preferences.

#### Acceptance Criteria

1. THE UI SHALL display a Settings Panel accessible from any authenticated view via a persistent navigation control.
2. WHEN the User opens the Settings Panel, THE UI SHALL fetch and display the current agent configuration from the Backend, including session timeout duration and scheduled-send confirmation timeout.
3. WHEN the User modifies a setting and saves, THE UI SHALL send the updated configuration to the Backend and display a confirmation that the change was saved.
4. IF the Backend rejects a configuration change, THEN THE UI SHALL display the Backend's error message and revert the displayed value to the previously saved value.
5. THE UI SHALL validate configuration inputs on the client side before submission, rejecting non-numeric values for numeric fields and values outside documented acceptable ranges, and displaying an inline validation message.
6. WHEN the User navigates away from the Settings Panel with unsaved changes, THE UI SHALL prompt the User to confirm discarding the changes before navigating.

---

### Requirement 5: Permission Management

**User Story:** As a user, I want to review and revoke the permissions I have granted to the agent, so that I remain in control of which data sources it can access.

#### Acceptance Criteria

1. WHEN the User opens the Settings Panel, THE UI SHALL fetch and display the list of currently active permissions from the Backend, including the data source, scope, and grant time for each.
2. WHEN the User revokes a permission, THE UI SHALL call the Backend permission revocation endpoint and remove the revoked permission from the displayed list upon confirmation.
3. IF the Backend returns an error during permission revocation, THEN THE UI SHALL display the error message and leave the permission in the displayed list.
4. WHEN the agent requests a new permission during a session, THE UI SHALL display a Permission Prompt identifying the data source, the scope of access, and the justification provided by the agent before the User grants or denies access.
5. WHEN the User grants a permission via the Permission Prompt, THE UI SHALL send the grant to the Backend and proceed with the agent's request.
6. WHEN the User denies a permission via the Permission Prompt, THE UI SHALL notify the Backend of the denial and display a message in the Agent Chat View indicating that the agent will proceed without that data source.

---

### Requirement 6: Tone Profile Management

**User Story:** As a user, I want to review and override the tone profiles the agent has derived for my recipients, so that my emails always match my intended style.

#### Acceptance Criteria

1. WHEN the User opens the Settings Panel, THE UI SHALL fetch and display a list of Tone Profile Cards for all recipients for whom a Tone Profile has been derived.
2. WHEN the User selects a Tone Profile Card, THE UI SHALL display the full profile details including formality level, greeting style, sign-off style, average sentence length, technical language usage, warmth indicator, and the number of emails the profile was derived from.
3. WHEN the agent derives or retrieves a Tone Profile during draft generation, THE UI SHALL display the Tone Profile Card for the relevant recipient in the Agent Chat View before the draft is shown.
4. WHEN the User selects a tone override option in the Agent Chat View, THE UI SHALL send the override to the Backend and regenerate the draft using the overridden tone.
5. THE UI SHALL present tone override options as a set of predefined formality levels and a free-text field for a custom tone description.
6. IF no Tone Profile exists for a recipient, THE UI SHALL display a notification in the Agent Chat View indicating that a neutral professional tone will be used.

---

### Requirement 7: Agent Chat Interaction

**User Story:** As a user, I want to issue natural language instructions to the agent and receive drafts and responses in a conversational interface, so that I can work with the agent efficiently.

#### Acceptance Criteria

1. THE UI SHALL provide an Agent Chat View with a text input field where the User can type natural language instructions and submit them to the Backend.
2. WHEN the User submits an instruction, THE UI SHALL display a loading indicator while awaiting the Backend response.
3. WHEN the Backend returns a Draft response, THE UI SHALL display the draft with the recipient, subject, body, and Context Summary in the Agent Chat View.
4. WHEN the Backend returns a Permission Request response, THE UI SHALL display the Permission Prompt to the User before any further agent action proceeds.
5. WHEN the Backend returns an error response, THE UI SHALL display the error message in the Agent Chat View without exposing internal stack traces or system details.
6. THE UI SHALL maintain and display the conversation history for the current session, showing prior instructions and agent responses in chronological order.
7. WHEN the User requests a revision to a displayed Draft, THE UI SHALL send the revision instruction to the Backend and replace the displayed draft with the updated version.
8. THE UI SHALL allow the User to manually edit the recipient, subject, and body fields of a displayed Draft before initiating a send or schedule action.

---

### Requirement 8: Approval Gate for Sending Emails

**User Story:** As a user, I want to explicitly confirm every email before it is sent, so that I remain in full control of outbound communication.

#### Acceptance Criteria

1. WHEN the User initiates a send action on a Draft, THE UI SHALL display an Approval Gate Dialog showing the recipient, subject, full email body, any attachments, and the Context Summary.
2. WHILE the Approval Gate Dialog is open, THE UI SHALL disable all other interactive controls to prevent concurrent actions.
3. WHEN the User confirms the Approval Gate Dialog, THE UI SHALL send the confirmation to the Backend and display a success notification once the Backend confirms the email was sent.
4. WHEN the User cancels the Approval Gate Dialog, THE UI SHALL close the dialog and return the User to the Draft view without sending.
5. IF the Backend returns an error after the User confirms the send, THEN THE UI SHALL display the error message and return the User to the Draft view.

---

### Requirement 9: Approval Gate for Email Deletion

**User Story:** As a user, I want to confirm every deletion request, so that emails are never removed without my knowledge.

#### Acceptance Criteria

1. WHEN the User requests deletion of an email, THE UI SHALL display an Approval Gate Dialog identifying the email by sender, subject, and date.
2. WHILE the Approval Gate Dialog is open, THE UI SHALL disable all other interactive controls.
3. WHEN the User confirms the deletion Approval Gate Dialog, THE UI SHALL send the confirmation to the Backend and display a success notification once the Backend confirms the deletion.
4. WHEN the User cancels the deletion Approval Gate Dialog, THE UI SHALL close the dialog and leave the email unchanged.

---

### Requirement 10: Approval Gate for Scheduled Sends

**User Story:** As a user, I want to approve scheduled emails at the time of scheduling and again at send time, so that I am always in control of when emails are delivered.

#### Acceptance Criteria

1. WHEN the User initiates a schedule action on a Draft, THE UI SHALL display an Approval Gate Dialog showing the email content, recipient, and proposed send time before registering the scheduled draft.
2. WHEN the User confirms the scheduling Approval Gate Dialog, THE UI SHALL send the confirmation to the Backend and display the registered Scheduled Draft in the Settings Panel under a scheduled emails section.
3. WHEN the scheduled send time arrives, THE UI SHALL display an active confirmation prompt requiring the User to explicitly click a confirm button before the email is transmitted.
4. IF the User does not confirm the active send-time prompt within the configured timeout, THE UI SHALL display a notification that the email has been held and requires manual confirmation.
5. WHEN a Scheduled Draft is displayed in the Settings Panel, THE UI SHALL provide controls to cancel or edit the draft before the scheduled send time.

---

### Requirement 11: Audit Log Review

**User Story:** As a user, I want to review a log of everything the agent has done, so that I can maintain accountability and verify its actions.

#### Acceptance Criteria

1. WHEN the User navigates to the Audit Log View in the Settings Panel, THE UI SHALL fetch and display audit log entries from the Backend in reverse chronological order.
2. THE UI SHALL display each audit log entry with its event type, timestamp, and description.
3. THE UI SHALL provide a filter control that allows the User to filter displayed entries by event type.
4. WHEN the User applies a filter, THE UI SHALL send the filter parameter to the Backend and display only the matching entries.
5. THE UI SHALL display a message when no audit log entries match the current filter.
6. THE UI SHALL not provide any control that would allow the User to delete or modify audit log entries.

---

### Requirement 12: Context Summary Display

**User Story:** As a user, I want to see exactly what information the agent used to generate a draft, so that I can verify its accuracy before approving.

#### Acceptance Criteria

1. WHEN a Draft is displayed in the Agent Chat View, THE UI SHALL display the Context Summary alongside the draft, listing each data source accessed and the type of content retrieved.
2. WHEN the draft was generated from the User's instruction alone, THE UI SHALL display a message indicating that no external data was used.
3. THE UI SHALL provide an expandable section within the Context Summary that shows the specific email excerpts or meeting note extracts that informed the draft.
4. THE UI SHALL display the Context Summary before presenting any Approval Gate Dialog for the draft.

---

### Requirement 13: Accessibility and Responsiveness

**User Story:** As a user, I want the UI to be accessible and usable on different screen sizes, so that I can work from any device.

#### Acceptance Criteria

1. THE UI SHALL conform to WCAG 2.1 Level AA accessibility guidelines, including sufficient colour contrast, keyboard navigability, and screen reader compatibility for all interactive elements.
2. THE UI SHALL be responsive and usable on screen widths from 320 px to 2560 px without horizontal scrolling or loss of functionality.
3. THE UI SHALL provide visible focus indicators for all keyboard-navigable elements.
4. WHEN a loading state is active, THE UI SHALL display a loading indicator that is announced to screen readers via an appropriate ARIA live region.
5. ALL form inputs SHALL have associated visible labels and descriptive ARIA attributes.

---

### Requirement 14: Error Handling and User Feedback

**User Story:** As a user, I want clear feedback when something goes wrong, so that I know what happened and what I can do next.

#### Acceptance Criteria

1. WHEN the Backend returns any error response, THE UI SHALL display a human-readable error message that describes the problem without exposing internal implementation details, stack traces, or raw error codes.
2. WHEN a network request fails due to connectivity loss, THE UI SHALL display a connectivity error message and provide a retry control.
3. IF a Backend request times out, THEN THE UI SHALL display a timeout message and allow the User to retry the action.
4. THE UI SHALL display inline validation messages adjacent to the relevant input field when client-side validation fails.
5. WHEN an action completes successfully, THE UI SHALL display a brief success notification that dismisses automatically after a configurable duration.

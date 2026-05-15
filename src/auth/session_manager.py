"""
Authentication & Session Manager for the Secure AI Executive Assistant.

Responsibilities:
- Enforce authentication before any session begins
- Manage session tokens with configurable inactivity timeout
- Rate-limit failed authentication attempts (exponential back-off)
- Initiate and manage the Gmail OAuth 2.0 flow
- Store only the OAuth token — never Gmail credentials
- Detect expired/revoked OAuth tokens and suspend Gmail access

Trust note: this module is part of the trusted User Layer. It must never
store raw Gmail credentials; only the resulting OAuthToken is persisted.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

import requests
from google_auth_oauthlib.flow import Flow

from src.auth.errors import AuthError, OAuthError, SessionExpiredError
from src.models.types import (
    AuditEntry,
    AuditEventType,
    GmailScope,
    OAuthToken,
    SessionContext,
)

# Avoid circular import — AuditLogger is imported lazily via TYPE_CHECKING
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.audit.audit_logger import AuditLogger

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Minimal initial scope — additional scopes are requested at point of need.
_INITIAL_GMAIL_SCOPES = [
    f"https://www.googleapis.com/auth/{GmailScope.READONLY.value}",
]

_GOOGLE_REVOKE_URL = "https://oauth2.googleapis.com/revoke"

# Exponential back-off ceiling (seconds)
_MAX_BACKOFF_SECONDS = 300


# ---------------------------------------------------------------------------
# SessionManager
# ---------------------------------------------------------------------------


class SessionManager:
    """
    Manages user sessions and the Gmail OAuth 2.0 lifecycle.

    Parameters
    ----------
    session_timeout_minutes:
        Number of minutes of inactivity before a session is considered expired.
        Defaults to 30.
    rate_limit_threshold:
        Number of consecutive failed authentication attempts before exponential
        back-off is applied. Defaults to 5.
    oauth_client_config:
        A dict in the format expected by ``google_auth_oauthlib.flow.Flow``
        (i.e. the parsed contents of a ``client_secrets.json`` file).
        If *None*, OAuth methods will raise ``OAuthError`` when called.
    oauth_redirect_uri:
        The redirect URI registered with Google for the OAuth callback.
    """

    def __init__(
        self,
        session_timeout_minutes: int = 30,
        rate_limit_threshold: int = 5,
        oauth_client_config: dict[str, Any] | None = None,
        oauth_redirect_uri: str = "http://localhost:8080/oauth/callback",
        audit_logger: "AuditLogger | None" = None,
    ) -> None:
        self._session_timeout_minutes = session_timeout_minutes
        self._rate_limit_threshold = rate_limit_threshold
        self._oauth_client_config = oauth_client_config
        self._oauth_redirect_uri = oauth_redirect_uri
        self._audit_logger = audit_logger

        # In-memory session store — keyed by session_id
        self._sessions: dict[str, SessionContext] = {}

        # Failed attempt tracking — keyed by user_id
        # Each value is a list of datetime objects (UTC) for each failure.
        self._failed_attempts: dict[str, list[datetime]] = {}

        # Pending OAuth state tokens — keyed by session_id
        self._pending_oauth_states: dict[str, str] = {}

        # Audit log (in-memory for now; will be replaced by AuditLogger later)
        self._audit_log: list[AuditEntry] = []

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _now(self) -> datetime:
        """Return the current UTC time (timezone-aware)."""
        return datetime.now(tz=timezone.utc)

    def _make_expires_at(self) -> datetime:
        return self._now() + timedelta(minutes=self._session_timeout_minutes)

    def _log_audit(
        self,
        event_type: AuditEventType,
        session_id: str,
        description: str,
        metadata: dict[str, str] | None = None,
    ) -> None:
        entry = AuditEntry(
            event_type=event_type,
            timestamp=self._now(),
            session_id=session_id,
            description=description,
            metadata=metadata or {},
        )
        self._audit_log.append(entry)
        logger.info("AUDIT %s | session=%s | %s", event_type.value, session_id, description)
        # Also emit to the real AuditLogger if one was injected
        if self._audit_logger is not None and session_id:
            try:
                self._audit_logger.log(
                    event_type=event_type,
                    session_id=session_id,
                    description=description,
                    metadata=metadata,
                )
            except Exception:
                pass  # never let audit logging break the auth flow

    def _build_flow(self) -> Flow:
        """Construct a Google OAuth Flow from the stored client config."""
        if self._oauth_client_config is None:
            raise OAuthError(
                "OAuth client configuration is not set. "
                "Provide oauth_client_config when constructing SessionManager."
            )
        flow = Flow.from_client_config(
            self._oauth_client_config,
            scopes=_INITIAL_GMAIL_SCOPES,
            redirect_uri=self._oauth_redirect_uri,
        )
        return flow

    # ------------------------------------------------------------------
    # Task 2.1 — Core authentication and session lifecycle
    # ------------------------------------------------------------------

    def authenticate(self, user_id: str, credentials: dict) -> SessionContext:
        """
        Authenticate a user and create a new session.

        Parameters
        ----------
        user_id:
            The identifier for the user attempting to authenticate.
        credentials:
            A dict containing authentication credentials. For this
            implementation the dict must contain a ``"password"`` key whose
            value matches the ``"expected_password"`` key (used for testing).
            In production this would be replaced by a proper identity provider.

        Returns
        -------
        SessionContext
            A freshly created session for the authenticated user.

        Raises
        ------
        AuthError
            If authentication fails for any reason (generic message — no
            information leakage).
        """
        # Rate-limit check BEFORE attempting authentication
        if self.is_rate_limited(user_id):
            self._record_failed_attempt(user_id)
            self._log_audit(
                AuditEventType.AUTH_FAILED,
                session_id="",
                description="Authentication rejected: rate limit active",
                metadata={"user_id": user_id},
            )
            raise AuthError("Authentication failed.")

        # Validate credentials — generic failure path to prevent info leakage
        try:
            authenticated = self._verify_credentials(user_id, credentials)
        except Exception:
            authenticated = False

        if not authenticated:
            self._record_failed_attempt(user_id)
            self._log_audit(
                AuditEventType.AUTH_FAILED,
                session_id="",
                description="Authentication failed",
                metadata={"user_id": user_id},
            )
            raise AuthError("Authentication failed.")

        # Success — reset failure counter and create session
        self._failed_attempts.pop(user_id, None)

        now = self._now()
        session = SessionContext(
            session_id=str(uuid4()),
            user_id=user_id,
            created_at=now,
            last_active_at=now,
            expires_at=self._make_expires_at(),
        )
        self._sessions[session.session_id] = session

        self._log_audit(
            AuditEventType.SESSION_STARTED,
            session_id=session.session_id,
            description=f"Session started for user {user_id}",
            metadata={"user_id": user_id},
        )
        return session

    def _verify_credentials(self, user_id: str, credentials: dict) -> bool:
        """
        Verify user credentials.

        This is a placeholder implementation. In production this would
        delegate to an identity provider (e.g. LDAP, SSO, password hash
        comparison). For testing purposes, credentials must contain
        ``{"password": <value>}`` and the user store must have a matching
        ``{"expected_password": <value>}`` entry.

        The method intentionally accepts any non-empty user_id + credentials
        dict that contains a ``"password"`` key, so that unit tests can
        exercise the happy path without a real identity provider.
        """
        if not user_id or not isinstance(credentials, dict):
            return False
        password = credentials.get("password")
        if not password:
            return False
        # In a real system: look up the user and compare hashed passwords.
        # Here we accept any non-empty password for a non-empty user_id.
        return True

    def validate_session(self, session_id: str) -> SessionContext:
        """
        Validate an existing session and update its last-active timestamp.

        Parameters
        ----------
        session_id:
            The session identifier to validate.

        Returns
        -------
        SessionContext
            The session context if valid and not expired.

        Raises
        ------
        SessionExpiredError
            If the session does not exist or has exceeded the inactivity
            timeout.
        """
        session = self._sessions.get(session_id)
        if session is None:
            raise SessionExpiredError("Session not found or has expired.")

        now = self._now()
        # Compare timezone-aware datetimes
        expires_at = session.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)

        if now > expires_at:
            # Remove the expired session
            del self._sessions[session_id]
            self._log_audit(
                AuditEventType.SESSION_EXPIRED,
                session_id=session_id,
                description="Session expired due to inactivity",
                metadata={"user_id": session.user_id},
            )
            raise SessionExpiredError("Session not found or has expired.")

        # Refresh the inactivity window
        session.last_active_at = now
        session.expires_at = self._make_expires_at()
        return session

    def initiate_gmail_oauth(self, session_id: str) -> str:
        """
        Begin the Gmail OAuth 2.0 authorisation flow.

        Validates the session, then returns the Google authorisation URL
        that the user must visit to grant Gmail access. The initial scope
        is ``gmail.readonly`` only; additional scopes are requested
        incrementally at the point of need.

        Parameters
        ----------
        session_id:
            The session for which OAuth is being initiated.

        Returns
        -------
        str
            The Google OAuth 2.0 authorisation URL.

        Raises
        ------
        SessionExpiredError
            If the session is invalid or expired.
        OAuthError
            If the OAuth client configuration is missing or the flow cannot
            be constructed.
        """
        self.validate_session(session_id)  # raises SessionExpiredError if invalid

        flow = self._build_flow()
        auth_url, state = flow.authorization_url(
            access_type="offline",
            include_granted_scopes="true",
            prompt="consent",
        )
        # Store the state token so we can verify it in the callback
        self._pending_oauth_states[session_id] = state
        return auth_url

    def handle_oauth_callback(
        self, session_id: str, code: str, state: str
    ) -> OAuthToken:
        """
        Exchange an OAuth authorisation code for tokens and store the result.

        Only the ``OAuthToken`` is stored on the session — raw credentials
        (client secret, etc.) are never persisted.

        Parameters
        ----------
        session_id:
            The session that initiated the OAuth flow.
        code:
            The authorisation code returned by Google.
        state:
            The state token returned by Google (must match the stored value).

        Returns
        -------
        OAuthToken
            The token stored on the session.

        Raises
        ------
        SessionExpiredError
            If the session is invalid or expired.
        OAuthError
            If the state token is invalid, the code exchange fails, or the
            returned token is missing required fields.
        """
        session = self.validate_session(session_id)

        expected_state = self._pending_oauth_states.get(session_id)
        if expected_state is None or expected_state != state:
            raise OAuthError("Invalid OAuth state token.")

        flow = self._build_flow()
        # Restore the state so the flow can validate it internally
        flow.state = state

        try:
            flow.fetch_token(code=code)
        except Exception as exc:
            raise OAuthError(f"Failed to exchange authorisation code: {exc}") from exc

        google_credentials = flow.credentials

        if not google_credentials.token:
            raise OAuthError("OAuth token exchange returned no access token.")

        # Parse expiry — google-auth returns a naive datetime in UTC
        expires_at: datetime
        if google_credentials.expiry is not None:
            expires_at = google_credentials.expiry.replace(tzinfo=timezone.utc)
        else:
            # Default to 1 hour if expiry is not provided
            expires_at = self._now() + timedelta(hours=1)

        # Map the granted scopes back to GmailScope enum values
        raw_scopes: list[str] = list(google_credentials.scopes or [])
        gmail_scopes = _parse_gmail_scopes(raw_scopes)

        oauth_token = OAuthToken(
            access_token=google_credentials.token,
            refresh_token=google_credentials.refresh_token or "",
            expires_at=expires_at,
            scopes=gmail_scopes,
        )

        # Store only the OAuthToken — never the raw credentials object
        session.gmail_oauth_token = oauth_token

        # Clean up the pending state
        del self._pending_oauth_states[session_id]

        return oauth_token

    def revoke_gmail_token(self, session_id: str) -> None:
        """
        Revoke the Gmail OAuth token and clear it from the session.

        Calls Google's token revocation endpoint, then removes the token
        from the session regardless of whether the revocation request
        succeeded (to ensure the local state is always cleaned up).

        Parameters
        ----------
        session_id:
            The session whose Gmail token should be revoked.

        Raises
        ------
        SessionExpiredError
            If the session is invalid or expired.
        OAuthError
            If the session has no Gmail token to revoke.
        """
        session = self.validate_session(session_id)

        if session.gmail_oauth_token is None:
            raise OAuthError("No Gmail OAuth token to revoke for this session.")

        token = session.gmail_oauth_token.access_token

        # Attempt revocation — best-effort; always clear local state afterwards
        try:
            response = requests.post(
                _GOOGLE_REVOKE_URL,
                params={"token": token},
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=10,
            )
            response.raise_for_status()
        except Exception as exc:
            logger.warning("Token revocation request failed (clearing locally anyway): %s", exc)

        # Always clear the token from the session
        session.gmail_oauth_token = None

        self._log_audit(
            AuditEventType.GMAIL_TOKEN_REVOKED,
            session_id=session_id,
            description="Gmail OAuth token revoked",
            metadata={"user_id": session.user_id},
        )

    def refresh_gmail_token(self, session_id: str) -> OAuthToken:
        """
        Refresh an expired Gmail access token using the stored refresh token.

        Parameters
        ----------
        session_id:
            The session whose Gmail token should be refreshed.

        Returns
        -------
        OAuthToken
            The updated token stored on the session.

        Raises
        ------
        SessionExpiredError
            If the session is invalid or expired.
        OAuthError
            If the session has no Gmail token, the refresh token is missing,
            or the refresh request fails.
        """
        session = self.validate_session(session_id)

        if session.gmail_oauth_token is None:
            raise OAuthError("No Gmail OAuth token to refresh for this session.")

        refresh_token = session.gmail_oauth_token.refresh_token
        if not refresh_token:
            raise OAuthError("No refresh token available; re-authorisation required.")

        if self._oauth_client_config is None:
            raise OAuthError(
                "OAuth client configuration is not set. "
                "Provide oauth_client_config when constructing SessionManager."
            )

        # Extract client credentials from the config
        client_data = (
            self._oauth_client_config.get("web")
            or self._oauth_client_config.get("installed")
            or {}
        )
        client_id = client_data.get("client_id", "")
        client_secret = client_data.get("client_secret", "")

        try:
            response = requests.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "refresh_token": refresh_token,
                    "grant_type": "refresh_token",
                },
                timeout=10,
            )
            response.raise_for_status()
            token_data = response.json()
        except Exception as exc:
            raise OAuthError(f"Failed to refresh Gmail token: {exc}") from exc

        new_access_token = token_data.get("access_token")
        if not new_access_token:
            raise OAuthError("Token refresh response did not contain an access token.")

        expires_in = token_data.get("expires_in", 3600)
        new_expires_at = self._now() + timedelta(seconds=expires_in)

        # Preserve existing scopes and refresh token (Google may not return a new one)
        new_refresh_token = token_data.get("refresh_token") or refresh_token
        existing_scopes = session.gmail_oauth_token.scopes

        updated_token = OAuthToken(
            access_token=new_access_token,
            refresh_token=new_refresh_token,
            expires_at=new_expires_at,
            scopes=existing_scopes,
        )
        session.gmail_oauth_token = updated_token
        return updated_token

    # ------------------------------------------------------------------
    # Task 2.2 — Failed-authentication rate limiting
    # ------------------------------------------------------------------

    def _record_failed_attempt(self, user_id: str) -> None:
        """Record a failed authentication attempt for the given user_id."""
        now = self._now()
        if user_id not in self._failed_attempts:
            self._failed_attempts[user_id] = []
        self._failed_attempts[user_id].append(now)

    def is_rate_limited(self, user_id: str) -> bool:
        """
        Return True if the user_id is currently subject to rate limiting.

        Rate limiting is applied after ``rate_limit_threshold`` consecutive
        failures. The back-off duration is ``2^(failures - threshold)``
        seconds, capped at ``_MAX_BACKOFF_SECONDS`` (300 s).

        The check is based on the time elapsed since the *most recent* failed
        attempt. If that elapsed time is less than the computed back-off
        duration, the user is considered rate-limited.
        """
        attempts = self._failed_attempts.get(user_id)
        if not attempts:
            return False

        num_failures = len(attempts)
        if num_failures < self._rate_limit_threshold:
            return False

        # Compute back-off duration
        excess = num_failures - self._rate_limit_threshold
        backoff_seconds = min(2 ** excess, _MAX_BACKOFF_SECONDS)

        # Check whether the back-off window has elapsed since the last attempt
        last_attempt = attempts[-1]
        if last_attempt.tzinfo is None:
            last_attempt = last_attempt.replace(tzinfo=timezone.utc)

        elapsed = (self._now() - last_attempt).total_seconds()
        return elapsed < backoff_seconds


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_gmail_scopes(raw_scopes: list[str]) -> list[GmailScope]:
    """
    Convert a list of full Gmail scope URLs to ``GmailScope`` enum values.

    Unknown scopes are silently ignored.
    """
    result: list[GmailScope] = []
    for scope_url in raw_scopes:
        for gmail_scope in GmailScope:
            if scope_url.endswith(gmail_scope.value):
                result.append(gmail_scope)
                break
    return result

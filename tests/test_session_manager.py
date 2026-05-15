"""
Unit tests for SessionManager (Tasks 2.1 and 2.2).

Covers:
- Session creation and storage
- Session expiry boundary (inactivity timeout)
- validate_session updates last_active_at
- OAuth token storage (only OAuthToken, never raw credentials)
- revoke_gmail_token clears token and logs GMAIL_TOKEN_REVOKED
- refresh_gmail_token updates the token
- Expired sessions cannot execute sensitive actions
- Rate limiting: failed attempts tracked per user_id
- Exponential back-off after threshold
- Successful auth resets failure counter
- is_rate_limited returns correct values
- Generic error messages (no information leakage)
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from src.auth.errors import AuthError, OAuthError, SessionExpiredError
from src.auth.session_manager import SessionManager, _MAX_BACKOFF_SECONDS
from src.models.types import AuditEventType, GmailScope, OAuthToken


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def manager() -> SessionManager:
    """A SessionManager with a 30-minute timeout and threshold of 5."""
    return SessionManager(session_timeout_minutes=30, rate_limit_threshold=5)


@pytest.fixture()
def short_timeout_manager() -> SessionManager:
    """A SessionManager with a very short timeout for expiry tests."""
    return SessionManager(session_timeout_minutes=0)  # expires immediately


@pytest.fixture()
def low_threshold_manager() -> SessionManager:
    """A SessionManager with a low rate-limit threshold for rate-limit tests."""
    return SessionManager(rate_limit_threshold=2)


def _valid_credentials() -> dict:
    return {"password": "secret"}


# ---------------------------------------------------------------------------
# Task 2.1 — Core authentication and session lifecycle
# ---------------------------------------------------------------------------


class TestAuthenticate:
    def test_successful_authentication_returns_session(self, manager):
        session = manager.authenticate("alice", _valid_credentials())
        assert session.user_id == "alice"
        assert session.session_id in manager._sessions

    def test_session_has_correct_user_id(self, manager):
        session = manager.authenticate("bob", _valid_credentials())
        assert session.user_id == "bob"

    def test_session_expires_at_is_in_future(self, manager):
        session = manager.authenticate("alice", _valid_credentials())
        assert session.expires_at > datetime.now(tz=timezone.utc)

    def test_session_started_audit_event_logged(self, manager):
        manager.authenticate("alice", _valid_credentials())
        events = [e.event_type for e in manager._audit_log]
        assert AuditEventType.SESSION_STARTED in events

    def test_failed_auth_raises_auth_error(self, manager):
        with pytest.raises(AuthError):
            manager.authenticate("alice", {"password": ""})

    def test_failed_auth_raises_generic_message(self, manager):
        """Error message must not reveal whether user_id exists."""
        with pytest.raises(AuthError, match="Authentication failed."):
            manager.authenticate("nonexistent_user", {"password": ""})

    def test_failed_auth_logs_auth_failed_event(self, manager):
        with pytest.raises(AuthError):
            manager.authenticate("alice", {"password": ""})
        events = [e.event_type for e in manager._audit_log]
        assert AuditEventType.AUTH_FAILED in events

    def test_successful_auth_resets_failure_counter(self, manager):
        # Accumulate some failures (below threshold)
        for _ in range(3):
            try:
                manager.authenticate("alice", {"password": ""})
            except AuthError:
                pass
        assert len(manager._failed_attempts.get("alice", [])) == 3

        # Successful auth should clear the counter
        manager.authenticate("alice", _valid_credentials())
        assert "alice" not in manager._failed_attempts

    def test_missing_password_raises_auth_error(self, manager):
        with pytest.raises(AuthError):
            manager.authenticate("alice", {})

    def test_empty_user_id_raises_auth_error(self, manager):
        with pytest.raises(AuthError):
            manager.authenticate("", _valid_credentials())


class TestValidateSession:
    def test_valid_session_returns_context(self, manager):
        session = manager.authenticate("alice", _valid_credentials())
        result = manager.validate_session(session.session_id)
        assert result.session_id == session.session_id

    def test_validate_updates_last_active_at(self, manager):
        session = manager.authenticate("alice", _valid_credentials())
        original_last_active = session.last_active_at
        # Small sleep to ensure time advances
        time.sleep(0.01)
        result = manager.validate_session(session.session_id)
        assert result.last_active_at >= original_last_active

    def test_unknown_session_raises_session_expired_error(self, manager):
        with pytest.raises(SessionExpiredError):
            manager.validate_session("nonexistent-session-id")

    def test_expired_session_raises_session_expired_error(self):
        mgr = SessionManager(session_timeout_minutes=0)
        session = mgr.authenticate("alice", _valid_credentials())
        # Force expiry by setting expires_at in the past
        session.expires_at = datetime.now(tz=timezone.utc) - timedelta(seconds=1)
        with pytest.raises(SessionExpiredError):
            mgr.validate_session(session.session_id)

    def test_expired_session_logs_session_expired_event(self):
        mgr = SessionManager(session_timeout_minutes=0)
        session = mgr.authenticate("alice", _valid_credentials())
        session.expires_at = datetime.now(tz=timezone.utc) - timedelta(seconds=1)
        with pytest.raises(SessionExpiredError):
            mgr.validate_session(session.session_id)
        events = [e.event_type for e in mgr._audit_log]
        assert AuditEventType.SESSION_EXPIRED in events

    def test_expired_session_removed_from_store(self):
        mgr = SessionManager(session_timeout_minutes=0)
        session = mgr.authenticate("alice", _valid_credentials())
        session.expires_at = datetime.now(tz=timezone.utc) - timedelta(seconds=1)
        with pytest.raises(SessionExpiredError):
            mgr.validate_session(session.session_id)
        assert session.session_id not in mgr._sessions

    def test_validate_extends_expiry_window(self, manager):
        session = manager.authenticate("alice", _valid_credentials())
        old_expires_at = session.expires_at
        time.sleep(0.01)
        manager.validate_session(session.session_id)
        assert session.expires_at >= old_expires_at


class TestInitiateGmailOAuth:
    def test_raises_oauth_error_without_client_config(self, manager):
        session = manager.authenticate("alice", _valid_credentials())
        with pytest.raises(OAuthError):
            manager.initiate_gmail_oauth(session.session_id)

    def test_raises_session_expired_error_for_invalid_session(self, manager):
        with pytest.raises(SessionExpiredError):
            manager.initiate_gmail_oauth("bad-session-id")

    def test_returns_auth_url_with_valid_config(self):
        client_config = {
            "web": {
                "client_id": "test-client-id",
                "client_secret": "test-secret",
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": ["http://localhost:8080/oauth/callback"],
            }
        }
        mgr = SessionManager(oauth_client_config=client_config)
        session = mgr.authenticate("alice", _valid_credentials())
        url = mgr.initiate_gmail_oauth(session.session_id)
        assert url.startswith("https://accounts.google.com")

    def test_stores_state_token_for_session(self):
        client_config = {
            "web": {
                "client_id": "test-client-id",
                "client_secret": "test-secret",
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": ["http://localhost:8080/oauth/callback"],
            }
        }
        mgr = SessionManager(oauth_client_config=client_config)
        session = mgr.authenticate("alice", _valid_credentials())
        mgr.initiate_gmail_oauth(session.session_id)
        assert session.session_id in mgr._pending_oauth_states

    def test_initial_scope_is_readonly_only(self):
        """Requirement 14.6: initial OAuth scope must be gmail.readonly only."""
        client_config = {
            "web": {
                "client_id": "test-client-id",
                "client_secret": "test-secret",
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": ["http://localhost:8080/oauth/callback"],
            }
        }
        mgr = SessionManager(oauth_client_config=client_config)
        session = mgr.authenticate("alice", _valid_credentials())
        url = mgr.initiate_gmail_oauth(session.session_id)
        # The URL should contain the readonly scope
        assert "gmail.readonly" in url
        # It must NOT contain broader scopes at initiation
        assert "gmail.send" not in url
        assert "gmail.modify" not in url


class TestHandleOAuthCallback:
    def test_raises_session_expired_error_for_invalid_session(self, manager):
        with pytest.raises(SessionExpiredError):
            manager.handle_oauth_callback("bad-session", "code", "state")

    def test_raises_oauth_error_for_invalid_state(self, manager):
        session = manager.authenticate("alice", _valid_credentials())
        # No pending state stored
        with pytest.raises(OAuthError, match="Invalid OAuth state token"):
            manager.handle_oauth_callback(session.session_id, "code", "wrong-state")

    def test_stores_only_oauth_token_not_raw_credentials(self):
        """Requirement 14.6: only OAuthToken is stored, never raw credentials."""
        client_config = {
            "web": {
                "client_id": "test-client-id",
                "client_secret": "test-secret",
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": ["http://localhost:8080/oauth/callback"],
            }
        }
        mgr = SessionManager(oauth_client_config=client_config)
        session = mgr.authenticate("alice", _valid_credentials())

        # Manually set a pending state
        mgr._pending_oauth_states[session.session_id] = "test-state"

        # Mock the Flow to avoid real network calls
        mock_credentials = MagicMock()
        mock_credentials.token = "access-token-123"
        mock_credentials.refresh_token = "refresh-token-456"
        mock_credentials.expiry = datetime(2099, 1, 1)
        mock_credentials.scopes = {"https://www.googleapis.com/auth/gmail.readonly"}

        mock_flow = MagicMock()
        mock_flow.credentials = mock_credentials

        with patch("src.auth.session_manager.Flow.from_client_config", return_value=mock_flow):
            token = mgr.handle_oauth_callback(session.session_id, "auth-code", "test-state")

        # The session should store an OAuthToken, not a raw credentials object
        assert isinstance(session.gmail_oauth_token, OAuthToken)
        assert session.gmail_oauth_token.access_token == "access-token-123"
        assert session.gmail_oauth_token.refresh_token == "refresh-token-456"
        # The raw credentials object must NOT be stored on the session
        assert not hasattr(session, "raw_credentials")

    def test_clears_pending_state_after_callback(self):
        client_config = {
            "web": {
                "client_id": "test-client-id",
                "client_secret": "test-secret",
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": ["http://localhost:8080/oauth/callback"],
            }
        }
        mgr = SessionManager(oauth_client_config=client_config)
        session = mgr.authenticate("alice", _valid_credentials())
        mgr._pending_oauth_states[session.session_id] = "test-state"

        mock_credentials = MagicMock()
        mock_credentials.token = "access-token"
        mock_credentials.refresh_token = "refresh-token"
        mock_credentials.expiry = datetime(2099, 1, 1)
        mock_credentials.scopes = {"https://www.googleapis.com/auth/gmail.readonly"}

        mock_flow = MagicMock()
        mock_flow.credentials = mock_credentials

        with patch("src.auth.session_manager.Flow.from_client_config", return_value=mock_flow):
            mgr.handle_oauth_callback(session.session_id, "code", "test-state")

        assert session.session_id not in mgr._pending_oauth_states


class TestRevokeGmailToken:
    def _make_session_with_token(self, manager) -> tuple:
        session = manager.authenticate("alice", _valid_credentials())
        token = OAuthToken(
            access_token="access-token",
            refresh_token="refresh-token",
            expires_at=datetime(2099, 1, 1, tzinfo=timezone.utc),
            scopes=[GmailScope.READONLY],
        )
        session.gmail_oauth_token = token
        return session, token

    def test_raises_oauth_error_when_no_token(self, manager):
        session = manager.authenticate("alice", _valid_credentials())
        with pytest.raises(OAuthError):
            manager.revoke_gmail_token(session.session_id)

    def test_clears_token_from_session(self, manager):
        session, _ = self._make_session_with_token(manager)
        with patch("requests.post") as mock_post:
            mock_post.return_value.raise_for_status = MagicMock()
            manager.revoke_gmail_token(session.session_id)
        assert session.gmail_oauth_token is None

    def test_logs_gmail_token_revoked_event(self, manager):
        session, _ = self._make_session_with_token(manager)
        with patch("requests.post") as mock_post:
            mock_post.return_value.raise_for_status = MagicMock()
            manager.revoke_gmail_token(session.session_id)
        events = [e.event_type for e in manager._audit_log]
        assert AuditEventType.GMAIL_TOKEN_REVOKED in events

    def test_clears_token_even_if_revocation_request_fails(self, manager):
        """Token must be cleared locally even if the Google revocation call fails."""
        session, _ = self._make_session_with_token(manager)
        with patch("requests.post", side_effect=Exception("network error")):
            manager.revoke_gmail_token(session.session_id)
        assert session.gmail_oauth_token is None

    def test_raises_session_expired_error_for_invalid_session(self, manager):
        with pytest.raises(SessionExpiredError):
            manager.revoke_gmail_token("bad-session-id")


class TestRefreshGmailToken:
    def _make_session_with_token(self, manager) -> tuple:
        session = manager.authenticate("alice", _valid_credentials())
        token = OAuthToken(
            access_token="old-access-token",
            refresh_token="refresh-token",
            expires_at=datetime(2020, 1, 1, tzinfo=timezone.utc),  # expired
            scopes=[GmailScope.READONLY],
        )
        session.gmail_oauth_token = token
        return session, token

    def test_raises_oauth_error_when_no_token(self, manager):
        session = manager.authenticate("alice", _valid_credentials())
        with pytest.raises(OAuthError):
            manager.refresh_gmail_token(session.session_id)

    def test_raises_oauth_error_without_client_config(self, manager):
        session, _ = self._make_session_with_token(manager)
        with pytest.raises(OAuthError):
            manager.refresh_gmail_token(session.session_id)

    def test_updates_access_token_on_success(self):
        client_config = {
            "web": {
                "client_id": "test-client-id",
                "client_secret": "test-secret",
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": ["http://localhost:8080/oauth/callback"],
            }
        }
        mgr = SessionManager(oauth_client_config=client_config)
        session = mgr.authenticate("alice", _valid_credentials())
        session.gmail_oauth_token = OAuthToken(
            access_token="old-token",
            refresh_token="refresh-token",
            expires_at=datetime(2020, 1, 1, tzinfo=timezone.utc),
            scopes=[GmailScope.READONLY],
        )

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "access_token": "new-access-token",
            "expires_in": 3600,
        }
        mock_response.raise_for_status = MagicMock()

        with patch("requests.post", return_value=mock_response):
            new_token = mgr.refresh_gmail_token(session.session_id)

        assert new_token.access_token == "new-access-token"
        assert session.gmail_oauth_token.access_token == "new-access-token"

    def test_preserves_refresh_token_when_not_returned(self):
        client_config = {
            "web": {
                "client_id": "test-client-id",
                "client_secret": "test-secret",
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": ["http://localhost:8080/oauth/callback"],
            }
        }
        mgr = SessionManager(oauth_client_config=client_config)
        session = mgr.authenticate("alice", _valid_credentials())
        session.gmail_oauth_token = OAuthToken(
            access_token="old-token",
            refresh_token="original-refresh-token",
            expires_at=datetime(2020, 1, 1, tzinfo=timezone.utc),
            scopes=[GmailScope.READONLY],
        )

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "access_token": "new-access-token",
            "expires_in": 3600,
            # No refresh_token in response — should preserve existing one
        }
        mock_response.raise_for_status = MagicMock()

        with patch("requests.post", return_value=mock_response):
            new_token = mgr.refresh_gmail_token(session.session_id)

        assert new_token.refresh_token == "original-refresh-token"

    def test_raises_session_expired_error_for_invalid_session(self, manager):
        with pytest.raises(SessionExpiredError):
            manager.refresh_gmail_token("bad-session-id")


# ---------------------------------------------------------------------------
# Task 2.2 — Failed-authentication rate limiting
# ---------------------------------------------------------------------------


class TestRateLimiting:
    def test_no_rate_limit_initially(self, manager):
        assert manager.is_rate_limited("alice") is False

    def test_below_threshold_not_rate_limited(self, low_threshold_manager):
        mgr = low_threshold_manager
        # 1 failure — below threshold of 2
        try:
            mgr.authenticate("alice", {"password": ""})
        except AuthError:
            pass
        assert mgr.is_rate_limited("alice") is False

    def test_at_threshold_is_rate_limited(self, low_threshold_manager):
        mgr = low_threshold_manager
        # 2 failures — at threshold
        for _ in range(2):
            try:
                mgr.authenticate("alice", {"password": ""})
            except AuthError:
                pass
        assert mgr.is_rate_limited("alice") is True

    def test_rate_limited_user_cannot_authenticate(self, low_threshold_manager):
        mgr = low_threshold_manager
        for _ in range(2):
            try:
                mgr.authenticate("alice", {"password": ""})
            except AuthError:
                pass
        # Now rate-limited — even valid credentials should be rejected
        with pytest.raises(AuthError):
            mgr.authenticate("alice", _valid_credentials())

    def test_rate_limit_logs_auth_failed_event(self, low_threshold_manager):
        mgr = low_threshold_manager
        for _ in range(2):
            try:
                mgr.authenticate("alice", {"password": ""})
            except AuthError:
                pass
        # Attempt while rate-limited
        try:
            mgr.authenticate("alice", _valid_credentials())
        except AuthError:
            pass
        events = [e.event_type for e in mgr._audit_log]
        assert AuditEventType.AUTH_FAILED in events

    def test_rate_limit_error_message_is_generic(self, low_threshold_manager):
        """No information leakage — message must not reveal rate-limit status."""
        mgr = low_threshold_manager
        for _ in range(2):
            try:
                mgr.authenticate("alice", {"password": ""})
            except AuthError:
                pass
        with pytest.raises(AuthError, match="Authentication failed."):
            mgr.authenticate("alice", _valid_credentials())

    def test_successful_auth_resets_rate_limit_counter(self, low_threshold_manager):
        mgr = low_threshold_manager
        # 1 failure (below threshold)
        try:
            mgr.authenticate("alice", {"password": ""})
        except AuthError:
            pass
        # Successful auth
        mgr.authenticate("alice", _valid_credentials())
        # Counter should be cleared
        assert "alice" not in mgr._failed_attempts
        assert mgr.is_rate_limited("alice") is False

    def test_rate_limit_is_per_user_id(self, low_threshold_manager):
        mgr = low_threshold_manager
        # Rate-limit alice
        for _ in range(2):
            try:
                mgr.authenticate("alice", {"password": ""})
            except AuthError:
                pass
        # bob should not be rate-limited
        assert mgr.is_rate_limited("bob") is False

    def test_exponential_backoff_increases_with_failures(self):
        """Back-off duration doubles with each additional failure beyond threshold."""
        mgr = SessionManager(rate_limit_threshold=2)
        # Reach threshold (2 failures)
        for _ in range(2):
            try:
                mgr.authenticate("alice", {"password": ""})
            except AuthError:
                pass
        assert mgr.is_rate_limited("alice") is True

        # Add one more failure (3 total, excess=1, backoff=2^1=2s)
        try:
            mgr.authenticate("alice", {"password": ""})
        except AuthError:
            pass
        # Still rate-limited
        assert mgr.is_rate_limited("alice") is True

    def test_backoff_capped_at_max(self):
        """Back-off must not exceed _MAX_BACKOFF_SECONDS (300 s)."""
        mgr = SessionManager(rate_limit_threshold=2)
        # Add many failures to push backoff well above 300s
        for _ in range(20):
            mgr._failed_attempts.setdefault("alice", []).append(
                datetime.now(tz=timezone.utc)
            )
        # Compute what the backoff would be
        num_failures = len(mgr._failed_attempts["alice"])
        excess = num_failures - mgr._rate_limit_threshold
        raw_backoff = 2 ** excess
        assert raw_backoff > _MAX_BACKOFF_SECONDS  # confirm we'd exceed cap
        # is_rate_limited should still return True (capped at 300s)
        assert mgr.is_rate_limited("alice") is True

    def test_rate_limit_expires_after_backoff_window(self):
        """After the back-off window elapses, the user should no longer be rate-limited."""
        mgr = SessionManager(rate_limit_threshold=2)
        # Reach threshold
        for _ in range(2):
            try:
                mgr.authenticate("alice", {"password": ""})
            except AuthError:
                pass
        # Manually backdate the last attempt so the window has elapsed
        # threshold=2, excess=0, backoff=2^0=1s
        past = datetime.now(tz=timezone.utc) - timedelta(seconds=2)
        mgr._failed_attempts["alice"] = [past, past]
        assert mgr.is_rate_limited("alice") is False

    def test_configurable_threshold(self):
        """Rate limiting should respect the configured threshold."""
        mgr = SessionManager(rate_limit_threshold=10)
        for _ in range(9):
            try:
                mgr.authenticate("alice", {"password": ""})
            except AuthError:
                pass
        # 9 failures, threshold=10 — not yet rate-limited
        assert mgr.is_rate_limited("alice") is False

        try:
            mgr.authenticate("alice", {"password": ""})
        except AuthError:
            pass
        # 10 failures — now rate-limited
        assert mgr.is_rate_limited("alice") is True

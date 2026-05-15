"""
Unit tests for GmailClient (Task 7.1).

Covers:
- list_messages returns parsed EmailMessage objects
- list_messages raises GmailScopeError when token lacks required scope
- get_thread returns messages in thread order
- get_sent_history queries with correct SENT label filter
- send_message raises GmailScopeError without gmail.send scope
- send_message returns message ID on success
- create_draft raises GmailScopeError without gmail.compose scope
- delete_message raises GmailScopeError without gmail.modify scope
- 401 response raises GmailTokenExpiredError
- 429 response raises GmailRateLimitError
- Network failure raises GmailAPIError
- Token values are never logged (access_token not in log calls)
"""

from __future__ import annotations

import base64
import logging
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch, call

import pytest
from googleapiclient.errors import HttpError

from src.gmail.gmail_client import GmailClient
from src.gmail.errors import (
    GmailAPIError,
    GmailRateLimitError,
    GmailScopeError,
    GmailTokenExpiredError,
)
from src.models.types import EmailMessage, GmailScope, OAuthToken


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_ACCESS_TOKEN = "test-access-token-secret"
_REFRESH_TOKEN = "test-refresh-token-secret"


def _make_token(*scopes: GmailScope) -> OAuthToken:
    """Create an OAuthToken with the given scopes."""
    return OAuthToken(
        access_token=_ACCESS_TOKEN,
        refresh_token=_REFRESH_TOKEN,
        expires_at=datetime(2099, 1, 1, tzinfo=timezone.utc),
        scopes=list(scopes),
    )


def _encode_body(text: str) -> str:
    """Base64url-encode a string as Gmail API would return it."""
    return base64.urlsafe_b64encode(text.encode("utf-8")).decode("utf-8")


def _make_raw_message(
    msg_id: str = "msg1",
    thread_id: str = "thread1",
    from_addr: str = "sender@example.com",
    to_addr: str = "recipient@example.com",
    cc_addr: str = "",
    subject: str = "Test Subject",
    body_text: str = "Hello, world!",
    internal_date: int = 1_700_000_000_000,  # ms since epoch
    labels: list[str] | None = None,
) -> dict:
    """Build a minimal Gmail API message resource dict."""
    headers = [
        {"name": "From", "value": from_addr},
        {"name": "To", "value": to_addr},
        {"name": "Subject", "value": subject},
    ]
    if cc_addr:
        headers.append({"name": "Cc", "value": cc_addr})

    return {
        "id": msg_id,
        "threadId": thread_id,
        "internalDate": str(internal_date),
        "labelIds": labels or [],
        "payload": {
            "mimeType": "text/plain",
            "headers": headers,
            "body": {"data": _encode_body(body_text)},
        },
    }


def _make_http_error(status: int, reason: str = "error") -> HttpError:
    """Create a fake HttpError with the given status code."""
    resp = MagicMock()
    resp.status = status
    resp.reason = reason
    return HttpError(resp=resp, content=b"")


def _make_client(*scopes: GmailScope) -> tuple[GmailClient, MagicMock]:
    """
    Create a GmailClient with a mocked Gmail API service.

    Returns (client, mock_service).
    """
    token = _make_token(*scopes)
    with patch("src.gmail.gmail_client.build") as mock_build:
        mock_service = MagicMock()
        mock_build.return_value = mock_service
        client = GmailClient(token)
    # Replace the service on the client so we can control it in tests
    client._service = mock_service
    return client, mock_service


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def readonly_client() -> tuple[GmailClient, MagicMock]:
    return _make_client(GmailScope.READONLY)


@pytest.fixture()
def send_client() -> tuple[GmailClient, MagicMock]:
    return _make_client(GmailScope.READONLY, GmailScope.SEND)


@pytest.fixture()
def compose_client() -> tuple[GmailClient, MagicMock]:
    return _make_client(GmailScope.READONLY, GmailScope.COMPOSE)


@pytest.fixture()
def modify_client() -> tuple[GmailClient, MagicMock]:
    return _make_client(GmailScope.READONLY, GmailScope.MODIFY)


@pytest.fixture()
def no_scope_client() -> tuple[GmailClient, MagicMock]:
    """Client with no scopes — every operation should raise GmailScopeError."""
    return _make_client()


# ---------------------------------------------------------------------------
# list_messages
# ---------------------------------------------------------------------------


class TestListMessages:
    def test_returns_parsed_email_messages(self, readonly_client):
        client, svc = readonly_client
        raw_msg = _make_raw_message(msg_id="abc123", subject="Hello")

        svc.users().messages().list().execute.return_value = {
            "messages": [{"id": "abc123"}]
        }
        svc.users().messages().get().execute.return_value = raw_msg

        results = client.list_messages("from:alice@example.com")

        assert len(results) == 1
        assert isinstance(results[0], EmailMessage)
        assert results[0].message_id == "abc123"
        assert results[0].subject == "Hello"

    def test_returns_empty_list_when_no_messages(self, readonly_client):
        client, svc = readonly_client
        svc.users().messages().list().execute.return_value = {"messages": []}

        results = client.list_messages("from:nobody@example.com")
        assert results == []

    def test_raises_scope_error_without_readonly_scope(self, no_scope_client):
        client, _ = no_scope_client
        with pytest.raises(GmailScopeError):
            client.list_messages("subject:test")

    def test_raises_scope_error_with_custom_required_scope(self):
        """list_messages with required_scope=SEND raises if token only has READONLY."""
        client, svc = _make_client(GmailScope.READONLY)
        with pytest.raises(GmailScopeError):
            client.list_messages("subject:test", required_scope=GmailScope.SEND)

    def test_parses_body_correctly(self, readonly_client):
        client, svc = readonly_client
        raw_msg = _make_raw_message(body_text="This is the email body.")

        svc.users().messages().list().execute.return_value = {
            "messages": [{"id": raw_msg["id"]}]
        }
        svc.users().messages().get().execute.return_value = raw_msg

        results = client.list_messages("subject:test")
        assert results[0].body == "This is the email body."

    def test_parses_cc_addresses(self, readonly_client):
        client, svc = readonly_client
        raw_msg = _make_raw_message(cc_addr="cc1@example.com, cc2@example.com")

        svc.users().messages().list().execute.return_value = {
            "messages": [{"id": raw_msg["id"]}]
        }
        svc.users().messages().get().execute.return_value = raw_msg

        results = client.list_messages("subject:test")
        assert "cc1@example.com" in results[0].cc
        assert "cc2@example.com" in results[0].cc

    def test_raises_token_expired_on_401(self, readonly_client):
        client, svc = readonly_client
        svc.users().messages().list().execute.side_effect = _make_http_error(401)

        with pytest.raises(GmailTokenExpiredError):
            client.list_messages("subject:test")

    def test_raises_rate_limit_on_429(self, readonly_client):
        client, svc = readonly_client
        svc.users().messages().list().execute.side_effect = _make_http_error(429)

        with pytest.raises(GmailRateLimitError):
            client.list_messages("subject:test")

    def test_raises_api_error_on_other_http_error(self, readonly_client):
        client, svc = readonly_client
        svc.users().messages().list().execute.side_effect = _make_http_error(500)

        with pytest.raises(GmailAPIError):
            client.list_messages("subject:test")

    def test_raises_api_error_on_network_failure(self, readonly_client):
        client, svc = readonly_client
        svc.users().messages().list().execute.side_effect = ConnectionError("timeout")

        with pytest.raises(GmailAPIError):
            client.list_messages("subject:test")


# ---------------------------------------------------------------------------
# get_thread
# ---------------------------------------------------------------------------


class TestGetThread:
    def test_returns_messages_in_thread_order(self, readonly_client):
        client, svc = readonly_client
        msg1 = _make_raw_message(msg_id="m1", subject="First")
        msg2 = _make_raw_message(msg_id="m2", subject="Second")

        svc.users().threads().get().execute.return_value = {
            "messages": [msg1, msg2]
        }

        results = client.get_thread("thread123")

        assert len(results) == 2
        assert results[0].message_id == "m1"
        assert results[1].message_id == "m2"

    def test_returns_empty_list_for_empty_thread(self, readonly_client):
        client, svc = readonly_client
        svc.users().threads().get().execute.return_value = {"messages": []}

        results = client.get_thread("thread123")
        assert results == []

    def test_raises_scope_error_without_readonly(self, no_scope_client):
        client, _ = no_scope_client
        with pytest.raises(GmailScopeError):
            client.get_thread("thread123")

    def test_raises_token_expired_on_401(self, readonly_client):
        client, svc = readonly_client
        svc.users().threads().get().execute.side_effect = _make_http_error(401)

        with pytest.raises(GmailTokenExpiredError):
            client.get_thread("thread123")

    def test_raises_rate_limit_on_429(self, readonly_client):
        client, svc = readonly_client
        svc.users().threads().get().execute.side_effect = _make_http_error(429)

        with pytest.raises(GmailRateLimitError):
            client.get_thread("thread123")

    def test_raises_api_error_on_network_failure(self, readonly_client):
        client, svc = readonly_client
        svc.users().threads().get().execute.side_effect = OSError("network down")

        with pytest.raises(GmailAPIError):
            client.get_thread("thread123")


# ---------------------------------------------------------------------------
# get_sent_history
# ---------------------------------------------------------------------------


class TestGetSentHistory:
    def test_queries_with_sent_label_filter(self, readonly_client):
        client, svc = readonly_client
        svc.users().messages().list().execute.return_value = {"messages": []}

        client.get_sent_history("alice@example.com")

        # Verify the query passed to the API includes the SENT label and recipient
        list_call_kwargs = svc.users().messages().list.call_args
        query_arg = list_call_kwargs[1].get("q") or list_call_kwargs[0][0] if list_call_kwargs[0] else list_call_kwargs[1].get("q", "")
        assert "in:sent" in query_arg
        assert "alice@example.com" in query_arg

    def test_returns_parsed_messages(self, readonly_client):
        client, svc = readonly_client
        raw_msg = _make_raw_message(msg_id="sent1", subject="Sent email")

        svc.users().messages().list().execute.return_value = {
            "messages": [{"id": "sent1"}]
        }
        svc.users().messages().get().execute.return_value = raw_msg

        results = client.get_sent_history("alice@example.com")
        assert len(results) == 1
        assert results[0].message_id == "sent1"

    def test_raises_scope_error_without_readonly(self, no_scope_client):
        client, _ = no_scope_client
        with pytest.raises(GmailScopeError):
            client.get_sent_history("alice@example.com")

    def test_respects_limit_parameter(self, readonly_client):
        client, svc = readonly_client
        svc.users().messages().list().execute.return_value = {"messages": []}

        client.get_sent_history("alice@example.com", limit=5)

        list_call_kwargs = svc.users().messages().list.call_args
        max_results = list_call_kwargs[1].get("maxResults")
        assert max_results == 5


# ---------------------------------------------------------------------------
# send_message
# ---------------------------------------------------------------------------


class TestSendMessage:
    def test_raises_scope_error_without_send_scope(self, readonly_client):
        client, _ = readonly_client
        with pytest.raises(GmailScopeError):
            client.send_message("to@example.com", "Subject", "Body")

    def test_returns_message_id_on_success(self, send_client):
        client, svc = send_client
        svc.users().messages().send().execute.return_value = {"id": "sent-msg-id"}

        result = client.send_message("to@example.com", "Subject", "Body")
        assert result == "sent-msg-id"

    def test_sends_with_cc(self, send_client):
        client, svc = send_client
        svc.users().messages().send().execute.return_value = {"id": "sent-msg-id"}

        result = client.send_message(
            "to@example.com", "Subject", "Body", cc=["cc@example.com"]
        )
        assert result == "sent-msg-id"

    def test_raises_token_expired_on_401(self, send_client):
        client, svc = send_client
        svc.users().messages().send().execute.side_effect = _make_http_error(401)

        with pytest.raises(GmailTokenExpiredError):
            client.send_message("to@example.com", "Subject", "Body")

    def test_raises_rate_limit_on_429(self, send_client):
        client, svc = send_client
        svc.users().messages().send().execute.side_effect = _make_http_error(429)

        with pytest.raises(GmailRateLimitError):
            client.send_message("to@example.com", "Subject", "Body")

    def test_raises_api_error_on_network_failure(self, send_client):
        client, svc = send_client
        svc.users().messages().send().execute.side_effect = ConnectionError("timeout")

        with pytest.raises(GmailAPIError):
            client.send_message("to@example.com", "Subject", "Body")


# ---------------------------------------------------------------------------
# create_draft
# ---------------------------------------------------------------------------


class TestCreateDraft:
    def test_raises_scope_error_without_compose_scope(self, readonly_client):
        client, _ = readonly_client
        with pytest.raises(GmailScopeError):
            client.create_draft("to@example.com", "Subject", "Body")

    def test_returns_draft_id_on_success(self, compose_client):
        client, svc = compose_client
        svc.users().drafts().create().execute.return_value = {"id": "draft-id-123"}

        result = client.create_draft("to@example.com", "Subject", "Body")
        assert result == "draft-id-123"

    def test_creates_draft_with_cc(self, compose_client):
        client, svc = compose_client
        svc.users().drafts().create().execute.return_value = {"id": "draft-id-456"}

        result = client.create_draft(
            "to@example.com", "Subject", "Body", cc=["cc@example.com"]
        )
        assert result == "draft-id-456"

    def test_raises_token_expired_on_401(self, compose_client):
        client, svc = compose_client
        svc.users().drafts().create().execute.side_effect = _make_http_error(401)

        with pytest.raises(GmailTokenExpiredError):
            client.create_draft("to@example.com", "Subject", "Body")

    def test_raises_rate_limit_on_429(self, compose_client):
        client, svc = compose_client
        svc.users().drafts().create().execute.side_effect = _make_http_error(429)

        with pytest.raises(GmailRateLimitError):
            client.create_draft("to@example.com", "Subject", "Body")

    def test_raises_api_error_on_network_failure(self, compose_client):
        client, svc = compose_client
        svc.users().drafts().create().execute.side_effect = OSError("network error")

        with pytest.raises(GmailAPIError):
            client.create_draft("to@example.com", "Subject", "Body")


# ---------------------------------------------------------------------------
# delete_message
# ---------------------------------------------------------------------------


class TestDeleteMessage:
    def test_raises_scope_error_without_modify_scope(self, readonly_client):
        client, _ = readonly_client
        with pytest.raises(GmailScopeError):
            client.delete_message("msg-id-123")

    def test_trashes_message_on_success(self, modify_client):
        client, svc = modify_client
        svc.users().messages().trash().execute.return_value = {}

        # Should not raise
        client.delete_message("msg-id-123")
        svc.users().messages().trash.assert_called()

    def test_raises_token_expired_on_401(self, modify_client):
        client, svc = modify_client
        svc.users().messages().trash().execute.side_effect = _make_http_error(401)

        with pytest.raises(GmailTokenExpiredError):
            client.delete_message("msg-id-123")

    def test_raises_rate_limit_on_429(self, modify_client):
        client, svc = modify_client
        svc.users().messages().trash().execute.side_effect = _make_http_error(429)

        with pytest.raises(GmailRateLimitError):
            client.delete_message("msg-id-123")

    def test_raises_api_error_on_network_failure(self, modify_client):
        client, svc = modify_client
        svc.users().messages().trash().execute.side_effect = ConnectionError("timeout")

        with pytest.raises(GmailAPIError):
            client.delete_message("msg-id-123")


# ---------------------------------------------------------------------------
# Message parsing
# ---------------------------------------------------------------------------


class TestParseMessage:
    def test_parses_simple_plain_text_message(self):
        raw = _make_raw_message(
            msg_id="id1",
            thread_id="t1",
            from_addr="alice@example.com",
            to_addr="bob@example.com",
            subject="Hello Bob",
            body_text="Hi Bob, how are you?",
            internal_date=1_700_000_000_000,
        )
        msg = GmailClient._parse_message(raw)

        assert msg.message_id == "id1"
        assert msg.thread_id == "t1"
        assert msg.from_address == "alice@example.com"
        assert "bob@example.com" in msg.to
        assert msg.subject == "Hello Bob"
        assert msg.body == "Hi Bob, how are you?"

    def test_parses_multipart_message(self):
        body_text = "Plain text part"
        encoded = _encode_body(body_text)

        raw = {
            "id": "multipart1",
            "threadId": "t2",
            "internalDate": "1700000000000",
            "labelIds": ["INBOX"],
            "payload": {
                "mimeType": "multipart/alternative",
                "headers": [
                    {"name": "From", "value": "sender@example.com"},
                    {"name": "To", "value": "recv@example.com"},
                    {"name": "Subject", "value": "Multipart"},
                ],
                "parts": [
                    {
                        "mimeType": "text/plain",
                        "body": {"data": encoded},
                    },
                    {
                        "mimeType": "text/html",
                        "body": {"data": _encode_body("<p>HTML part</p>")},
                    },
                ],
            },
        }
        msg = GmailClient._parse_message(raw)
        assert msg.body == body_text

    def test_parses_labels(self):
        raw = _make_raw_message(labels=["INBOX", "UNREAD"])
        msg = GmailClient._parse_message(raw)
        assert "INBOX" in msg.labels
        assert "UNREAD" in msg.labels

    def test_parses_sent_at_from_internal_date(self):
        # 1_700_000_000_000 ms = 1700000000 seconds since epoch
        raw = _make_raw_message(internal_date=1_700_000_000_000)
        msg = GmailClient._parse_message(raw)
        expected = datetime.fromtimestamp(1_700_000_000.0, tz=timezone.utc)
        assert msg.sent_at == expected

    def test_handles_missing_cc(self):
        raw = _make_raw_message()  # no cc_addr
        msg = GmailClient._parse_message(raw)
        assert msg.cc == []

    def test_handles_multiple_to_addresses(self):
        raw = _make_raw_message(to_addr="a@example.com, b@example.com")
        msg = GmailClient._parse_message(raw)
        assert "a@example.com" in msg.to
        assert "b@example.com" in msg.to


# ---------------------------------------------------------------------------
# Token security — access_token must never appear in log output
# ---------------------------------------------------------------------------


class TestTokenSecurity:
    def test_access_token_not_logged_on_list_messages(self, caplog):
        client, svc = _make_client(GmailScope.READONLY)
        svc.users().messages().list().execute.return_value = {"messages": []}

        with caplog.at_level(logging.DEBUG, logger="src.gmail.gmail_client"):
            client.list_messages("subject:test")

        for record in caplog.records:
            assert _ACCESS_TOKEN not in record.getMessage(), (
                f"access_token found in log: {record.getMessage()}"
            )

    def test_access_token_not_logged_on_scope_error(self, caplog):
        client, _ = _make_client()  # no scopes

        with caplog.at_level(logging.DEBUG, logger="src.gmail.gmail_client"):
            with pytest.raises(GmailScopeError):
                client.list_messages("subject:test")

        for record in caplog.records:
            assert _ACCESS_TOKEN not in record.getMessage(), (
                f"access_token found in log: {record.getMessage()}"
            )

    def test_access_token_not_logged_on_api_error(self, caplog):
        client, svc = _make_client(GmailScope.READONLY)
        svc.users().messages().list().execute.side_effect = _make_http_error(500)

        with caplog.at_level(logging.DEBUG, logger="src.gmail.gmail_client"):
            with pytest.raises(GmailAPIError):
                client.list_messages("subject:test")

        for record in caplog.records:
            assert _ACCESS_TOKEN not in record.getMessage(), (
                f"access_token found in log: {record.getMessage()}"
            )

    def test_refresh_token_not_logged(self, caplog):
        client, svc = _make_client(GmailScope.READONLY)
        svc.users().messages().list().execute.return_value = {"messages": []}

        with caplog.at_level(logging.DEBUG, logger="src.gmail.gmail_client"):
            client.list_messages("subject:test")

        for record in caplog.records:
            assert _REFRESH_TOKEN not in record.getMessage(), (
                f"refresh_token found in log: {record.getMessage()}"
            )

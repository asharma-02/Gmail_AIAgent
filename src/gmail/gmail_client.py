"""
Gmail API client for the Secure AI Executive Assistant.

Every request is authenticated with the user's OAuthToken.
Raw token values are never logged or stored beyond the OAuthToken model.
Scope restrictions are enforced per operation before any API call is made.
"""

from __future__ import annotations

import base64
import logging
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google.oauth2.credentials import Credentials

from src.gmail.errors import (
    GmailAPIError,
    GmailRateLimitError,
    GmailScopeError,
    GmailTokenExpiredError,
)
from src.models.types import EmailMessage, GmailScope, OAuthToken

logger = logging.getLogger(__name__)

# Full scope URLs used by the Gmail API
_SCOPE_URLS: dict[GmailScope, str] = {
    GmailScope.READONLY: "https://www.googleapis.com/auth/gmail.readonly",
    GmailScope.SEND: "https://www.googleapis.com/auth/gmail.send",
    GmailScope.COMPOSE: "https://www.googleapis.com/auth/gmail.compose",
    GmailScope.MODIFY: "https://www.googleapis.com/auth/gmail.modify",
}


class GmailClient:
    """
    Wraps the Gmail REST API via google-api-python-client.

    Parameters
    ----------
    oauth_token:
        The user's OAuthToken. Raw token values are never logged.
    """

    def __init__(self, oauth_token: OAuthToken) -> None:
        """Build the Gmail API service from the OAuthToken."""
        self._oauth_token = oauth_token
        credentials = Credentials(
            token=oauth_token.access_token,
            refresh_token=oauth_token.refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            scopes=[_SCOPE_URLS[s] for s in oauth_token.scopes],
        )
        self._service = build("gmail", "v1", credentials=credentials, cache_discovery=False)

    # ------------------------------------------------------------------
    # Scope enforcement
    # ------------------------------------------------------------------

    def _check_scope(self, required: GmailScope) -> None:
        """
        Raise GmailScopeError if the token does not contain the required scope.

        Parameters
        ----------
        required:
            The GmailScope that must be present in the token's scopes list.
        """
        if required not in self._oauth_token.scopes:
            raise GmailScopeError(
                f"Token lacks required scope: {required.value}. "
                f"Granted scopes: {[s.value for s in self._oauth_token.scopes]}"
            )

    # ------------------------------------------------------------------
    # Error handling helper
    # ------------------------------------------------------------------

    @staticmethod
    def _handle_http_error(exc: HttpError) -> None:
        """
        Convert an HttpError into the appropriate GmailAPIError subclass.

        Raises
        ------
        GmailTokenExpiredError
            On HTTP 401.
        GmailRateLimitError
            On HTTP 429.
        GmailAPIError
            On any other HTTP error.
        """
        status = exc.resp.status
        if status == 401:
            raise GmailTokenExpiredError(
                "Gmail OAuth token has expired or been revoked.",
                status_code=401,
            ) from exc
        if status == 429:
            raise GmailRateLimitError(
                "Gmail API rate limit exceeded.",
                status_code=429,
            ) from exc
        raise GmailAPIError(
            f"Gmail API error (HTTP {status}): {exc.reason}",
            status_code=status,
        ) from exc

    # ------------------------------------------------------------------
    # Message parsing
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_message(raw: dict) -> EmailMessage:
        """
        Convert a Gmail API message resource to an EmailMessage model.

        Handles both simple (plain text) and multipart messages.
        Decodes base64url-encoded message parts.

        Parameters
        ----------
        raw:
            A Gmail API message resource dict (format=full).
        """
        headers: dict[str, str] = {}
        payload = raw.get("payload", {})
        for header in payload.get("headers", []):
            headers[header["name"].lower()] = header["value"]

        # Parse recipient lists
        def _split_addresses(value: str) -> list[str]:
            if not value:
                return []
            return [addr.strip() for addr in value.split(",") if addr.strip()]

        to_list = _split_addresses(headers.get("to", ""))
        cc_list = _split_addresses(headers.get("cc", ""))

        # Extract plain-text body
        body = GmailClient._extract_body(payload)

        # Parse sent_at from internalDate (milliseconds since epoch)
        internal_date_ms = int(raw.get("internalDate", 0))
        sent_at = datetime.fromtimestamp(internal_date_ms / 1000.0, tz=timezone.utc)

        return EmailMessage.model_validate(
            {
                "message_id": raw.get("id", ""),
                "thread_id": raw.get("threadId", ""),
                "from": headers.get("from", ""),
                "to": to_list,
                "cc": cc_list,
                "subject": headers.get("subject", ""),
                "body": body,
                "sent_at": sent_at,
                "labels": raw.get("labelIds", []),
            }
        )

    @staticmethod
    def _extract_body(payload: dict) -> str:
        """
        Recursively extract the plain-text body from a Gmail message payload.

        Decodes base64url-encoded data. Falls back to an empty string if no
        plain-text part is found.
        """
        mime_type = payload.get("mimeType", "")

        # Simple (non-multipart) message
        if not mime_type.startswith("multipart/"):
            if mime_type == "text/plain":
                data = payload.get("body", {}).get("data", "")
                if data:
                    return base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="replace")
            return ""

        # Multipart — search parts recursively, prefer text/plain
        for part in payload.get("parts", []):
            if part.get("mimeType") == "text/plain":
                data = part.get("body", {}).get("data", "")
                if data:
                    return base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="replace")

        # No text/plain found — recurse into nested multipart parts
        for part in payload.get("parts", []):
            result = GmailClient._extract_body(part)
            if result:
                return result

        return ""

    # ------------------------------------------------------------------
    # Email construction helper
    # ------------------------------------------------------------------

    @staticmethod
    def _build_raw_message(
        to: str,
        subject: str,
        body: str,
        cc: list[str] | None = None,
    ) -> str:
        """
        Construct an RFC 2822 email message and encode it as base64url.

        Parameters
        ----------
        to:
            Recipient email address.
        subject:
            Email subject line.
        body:
            Plain-text email body.
        cc:
            Optional list of CC addresses.

        Returns
        -------
        str
            Base64url-encoded raw message string for the Gmail API.
        """
        if cc:
            msg = MIMEMultipart()
            msg.attach(MIMEText(body, "plain"))
        else:
            msg = MIMEText(body, "plain")

        msg["to"] = to
        msg["subject"] = subject
        if cc:
            msg["cc"] = ", ".join(cc)

        raw_bytes = msg.as_bytes()
        return base64.urlsafe_b64encode(raw_bytes).decode("utf-8")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def list_messages(
        self,
        query: str,
        max_results: int = 10,
        required_scope: GmailScope = GmailScope.READONLY,
    ) -> list[EmailMessage]:
        """
        Search Gmail messages matching the query string.

        Parameters
        ----------
        query:
            Gmail search query (e.g. "from:alice@example.com").
        max_results:
            Maximum number of messages to return.
        required_scope:
            The OAuth scope required for this operation. Defaults to READONLY.

        Returns
        -------
        list[EmailMessage]
            Parsed EmailMessage objects matching the query.

        Raises
        ------
        GmailScopeError
            If the token lacks the required scope.
        GmailTokenExpiredError
            If the token has expired (HTTP 401).
        GmailRateLimitError
            If the rate limit is hit (HTTP 429).
        GmailAPIError
            On other API or network failures.
        """
        self._check_scope(required_scope)

        try:
            response = (
                self._service.users()
                .messages()
                .list(userId="me", q=query, maxResults=max_results)
                .execute()
            )
        except HttpError as exc:
            self._handle_http_error(exc)
        except Exception as exc:
            raise GmailAPIError(f"Network or unexpected error: {exc}") from exc

        messages = response.get("messages", [])
        result: list[EmailMessage] = []

        for msg_ref in messages:
            try:
                raw = (
                    self._service.users()
                    .messages()
                    .get(userId="me", id=msg_ref["id"], format="full")
                    .execute()
                )
                result.append(self._parse_message(raw))
            except HttpError as exc:
                self._handle_http_error(exc)
            except Exception as exc:
                raise GmailAPIError(f"Network or unexpected error: {exc}") from exc

        return result

    def get_thread(self, thread_id: str) -> list[EmailMessage]:
        """
        Retrieve all messages in a Gmail thread.

        Parameters
        ----------
        thread_id:
            The Gmail thread ID.

        Returns
        -------
        list[EmailMessage]
            Messages in the thread, in the order returned by the API.

        Raises
        ------
        GmailScopeError
            If the token lacks READONLY scope.
        GmailTokenExpiredError
            If the token has expired (HTTP 401).
        GmailRateLimitError
            If the rate limit is hit (HTTP 429).
        GmailAPIError
            On other API or network failures.
        """
        self._check_scope(GmailScope.READONLY)

        try:
            response = (
                self._service.users()
                .threads()
                .get(userId="me", id=thread_id, format="full")
                .execute()
            )
        except HttpError as exc:
            self._handle_http_error(exc)
        except Exception as exc:
            raise GmailAPIError(f"Network or unexpected error: {exc}") from exc

        return [self._parse_message(msg) for msg in response.get("messages", [])]

    def get_sent_history(
        self,
        recipient_email: str,
        limit: int = 20,
    ) -> list[EmailMessage]:
        """
        Retrieve sent emails addressed to recipient_email.

        Queries the SENT label with ``to:{recipient_email}``.

        Parameters
        ----------
        recipient_email:
            The recipient's email address to filter by.
        limit:
            Maximum number of sent messages to return.

        Returns
        -------
        list[EmailMessage]
            Sent messages addressed to the recipient.

        Raises
        ------
        GmailScopeError
            If the token lacks READONLY scope.
        GmailAPIError
            On API or network failures.
        """
        self._check_scope(GmailScope.READONLY)
        query = f"in:sent to:{recipient_email}"
        return self.list_messages(query=query, max_results=limit)

    def send_message(
        self,
        to: str,
        subject: str,
        body: str,
        cc: list[str] | None = None,
    ) -> str:
        """
        Send an email via Gmail.

        Parameters
        ----------
        to:
            Recipient email address.
        subject:
            Email subject line.
        body:
            Plain-text email body.
        cc:
            Optional list of CC addresses.

        Returns
        -------
        str
            The sent message ID.

        Raises
        ------
        GmailScopeError
            If the token lacks SEND scope.
        GmailTokenExpiredError
            If the token has expired (HTTP 401).
        GmailRateLimitError
            If the rate limit is hit (HTTP 429).
        GmailAPIError
            On other API or network failures.
        """
        self._check_scope(GmailScope.SEND)

        raw = self._build_raw_message(to=to, subject=subject, body=body, cc=cc)

        try:
            response = (
                self._service.users()
                .messages()
                .send(userId="me", body={"raw": raw})
                .execute()
            )
        except HttpError as exc:
            self._handle_http_error(exc)
        except Exception as exc:
            raise GmailAPIError(f"Network or unexpected error: {exc}") from exc

        return response["id"]

    def create_draft(
        self,
        to: str,
        subject: str,
        body: str,
        cc: list[str] | None = None,
    ) -> str:
        """
        Create a Gmail draft.

        Parameters
        ----------
        to:
            Recipient email address.
        subject:
            Email subject line.
        body:
            Plain-text email body.
        cc:
            Optional list of CC addresses.

        Returns
        -------
        str
            The draft ID.

        Raises
        ------
        GmailScopeError
            If the token lacks COMPOSE scope.
        GmailTokenExpiredError
            If the token has expired (HTTP 401).
        GmailRateLimitError
            If the rate limit is hit (HTTP 429).
        GmailAPIError
            On other API or network failures.
        """
        self._check_scope(GmailScope.COMPOSE)

        raw = self._build_raw_message(to=to, subject=subject, body=body, cc=cc)

        try:
            response = (
                self._service.users()
                .drafts()
                .create(userId="me", body={"message": {"raw": raw}})
                .execute()
            )
        except HttpError as exc:
            self._handle_http_error(exc)
        except Exception as exc:
            raise GmailAPIError(f"Network or unexpected error: {exc}") from exc

        return response["id"]

    def delete_message(self, message_id: str) -> None:
        """
        Delete (trash) a Gmail message.

        Parameters
        ----------
        message_id:
            The Gmail message ID to trash.

        Raises
        ------
        GmailScopeError
            If the token lacks MODIFY scope.
        GmailTokenExpiredError
            If the token has expired (HTTP 401).
        GmailRateLimitError
            If the rate limit is hit (HTTP 429).
        GmailAPIError
            On other API or network failures.
        """
        self._check_scope(GmailScope.MODIFY)

        try:
            (
                self._service.users()
                .messages()
                .trash(userId="me", id=message_id)
                .execute()
            )
        except HttpError as exc:
            self._handle_http_error(exc)
        except Exception as exc:
            raise GmailAPIError(f"Network or unexpected error: {exc}") from exc

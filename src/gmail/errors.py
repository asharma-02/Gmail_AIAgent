"""
Gmail API error types for the Secure AI Executive Assistant.
"""

from __future__ import annotations


class GmailAPIError(Exception):
    """General Gmail API failure."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class GmailScopeError(GmailAPIError):
    """Token lacks the required OAuth scope for the requested operation."""


class GmailRateLimitError(GmailAPIError):
    """Gmail API rate limit hit (HTTP 429)."""


class GmailTokenExpiredError(GmailAPIError):
    """Gmail OAuth token has expired or been revoked (HTTP 401)."""

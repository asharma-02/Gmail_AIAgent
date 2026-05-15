"""
Authentication and session error types for the Secure AI Executive Assistant.
"""


class AuthError(Exception):
    """
    Generic authentication failure.

    Always raised with a generic message to prevent information leakage —
    callers must not reveal whether the user_id exists or why auth failed.
    """


class SessionExpiredError(Exception):
    """Session not found or has exceeded the inactivity timeout."""


class OAuthError(Exception):
    """OAuth 2.0 flow failure (initiation, callback exchange, or token refresh)."""

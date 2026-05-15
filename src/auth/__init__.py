"""
Authentication package for the Secure AI Executive Assistant.

Public exports:
- SessionManager  — session lifecycle and Gmail OAuth management
- AuthError       — generic authentication failure
- SessionExpiredError — session not found or expired
- OAuthError      — OAuth flow failure
"""

from src.auth.errors import AuthError, OAuthError, SessionExpiredError
from src.auth.session_manager import SessionManager

__all__ = [
    "SessionManager",
    "AuthError",
    "SessionExpiredError",
    "OAuthError",
]

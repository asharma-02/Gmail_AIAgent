"""
Gmail API client package for the Secure AI Executive Assistant.
"""

from src.gmail.gmail_client import GmailClient
from src.gmail.errors import (
    GmailAPIError,
    GmailScopeError,
    GmailRateLimitError,
    GmailTokenExpiredError,
)

__all__ = [
    "GmailClient",
    "GmailAPIError",
    "GmailScopeError",
    "GmailRateLimitError",
    "GmailTokenExpiredError",
]

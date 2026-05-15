"""
Custom exceptions for the Scheduled Draft Manager.

Requirements: 7.3, 7.4, 7.5, 7.6
"""

from __future__ import annotations


class ScheduledDraftNotFoundError(Exception):
    """Raised when a scheduled draft ID is not found."""


class ScheduledDraftAlreadySentError(Exception):
    """Raised when attempting to modify a draft that has already been sent."""


class ScheduledDraftAlreadyCancelledError(Exception):
    """Raised when attempting to modify a draft that has been cancelled."""

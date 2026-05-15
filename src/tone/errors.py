"""
Errors for the Tone Profile Engine.
"""


class ToneProfileNotFoundError(Exception):
    """Raised when no tone profile exists for the given recipient."""

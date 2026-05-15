"""
Tone Profile Engine package.

Exports:
  ToneProfileEngine       — derive, persist, update, and override ToneProfiles
  ToneProfileNotFoundError — raised when no profile exists for a recipient
"""

from src.tone.errors import ToneProfileNotFoundError
from src.tone.tone_profile_engine import ToneProfileEngine

__all__ = ["ToneProfileEngine", "ToneProfileNotFoundError"]

"""
Prompt Builder & Sanitiser package.

Enforces the trust boundary between external untrusted content and the LLM.
All external content must pass through PromptSanitiser before reaching the LLM.
"""

from src.prompt.sanitiser import PromptSanitiser

__all__ = ["PromptSanitiser"]

"""Draft-generation specific exceptions."""


class DraftGenerationError(Exception):
    """Base error for draft generation failures."""


class InvalidLLMResponseError(DraftGenerationError):
    """Raised when the LLM response cannot be converted into a safe draft."""

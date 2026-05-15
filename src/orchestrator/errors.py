"""
Orchestrator-specific error types for the Secure AI Executive Assistant.
"""

from __future__ import annotations


class LLMNotConfiguredError(Exception):
    """
    Raised when the orchestrator is asked to call the LLM but no LLM client
    has been configured (i.e. llm_client=None at construction time).
    """


class OrchestratorError(Exception):
    """
    Base class for orchestrator-level errors that are not covered by more
    specific exception types.
    """

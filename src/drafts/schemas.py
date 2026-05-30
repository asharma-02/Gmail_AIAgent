"""Schemas used by the draft-generation module."""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

from src.models.types import Draft, EmailMessage


PriorityLabel = Literal["High", "Medium", "Low"]
SuggestedAction = Literal[
    "Reply Today",
    "Schedule Follow-up",
    "Archive",
    "Needs Human Review",
]
DraftType = Literal["full", "partial", "human_prompt"]


class ClassifiedEmailContext(BaseModel):
    """
    Input expected from Shruthi's summarisation/classification module.

    This wraps raw email data with summary, priority, and suggested action so
    Akbar's draft generator can produce an appropriate reply.
    """

    email: EmailMessage
    summary: str
    priority: PriorityLabel = "Medium"
    suggested_action: SuggestedAction = "Needs Human Review"


class AutomationDecision(BaseModel):
    """
    Decision made before draft generation.

    full:
        Enough context exists to generate a full draft.
    partial:
        A draft can be started, but the user should review/complete it.
    human_prompt:
        The email is too risky/unclear and should ask for human input.
    """

    draft_type: DraftType
    confidence_score: float = Field(ge=0.0, le=1.0)
    needs_human_input: bool
    reason: str


class DraftGenerationResult(BaseModel):
    """Structured output returned by DraftGenerator."""

    draft: Optional[Draft] = None
    draft_type: DraftType
    confidence_score: float = Field(ge=0.0, le=1.0)
    needs_human_input: bool
    human_prompt: Optional[str] = None
    safety_notes: list[str] = Field(default_factory=list)

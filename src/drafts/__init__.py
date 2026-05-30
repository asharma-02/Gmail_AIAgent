"""Draft reply generation and writing-style matching module."""

from src.drafts.draft_generator import DraftGenerator
from src.drafts.schemas import (
    AutomationDecision,
    ClassifiedEmailContext,
    DraftGenerationResult,
)
from src.drafts.selective_automation import decide_automation
from src.drafts.style_adapter import build_style_guidance, tone_profile_to_summary

__all__ = [
    "AutomationDecision",
    "ClassifiedEmailContext",
    "DraftGenerationResult",
    "DraftGenerator",
    "build_style_guidance",
    "decide_automation",
    "tone_profile_to_summary",
]

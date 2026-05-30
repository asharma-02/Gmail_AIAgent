"""Selective automation rules for draft generation."""

from __future__ import annotations

from src.drafts.schemas import AutomationDecision, ClassifiedEmailContext


_COMPLEX_RISK_TERMS = {
    "legal",
    "lawyer",
    "lawsuit",
    "contract",
    "termination",
    "complaint",
    "breach",
    "data breach",
    "security incident",
    "refund",
    "payment dispute",
    "acquisition",
    "investment terms",
    "term sheet",
    "confidential",
    "urgent escalation",
}

_ROUTINE_TERMS = {
    "meeting",
    "availability",
    "follow up",
    "follow-up",
    "checking in",
    "thanks",
    "thank you",
    "schedule",
    "reschedule",
    "confirmation",
    "quick question",
}


def decide_automation(context: ClassifiedEmailContext) -> AutomationDecision:
    """
    Decide whether to generate a full draft, partial draft, or human prompt.

    This keeps risky messages away from over-confident automation. Because,
    apparently, letting an AI freely answer legal emails is frowned upon.
    """
    text = (
        f"{context.email.subject}\n{context.email.body}\n"
        f"{context.summary}\n{context.suggested_action}"
    ).lower()

    if context.suggested_action == "Needs Human Review":
        return AutomationDecision(
            draft_type="human_prompt",
            confidence_score=0.25,
            needs_human_input=True,
            reason="Suggested action requires human review.",
        )

    if any(term in text for term in _COMPLEX_RISK_TERMS):
        return AutomationDecision(
            draft_type="partial",
            confidence_score=0.55,
            needs_human_input=True,
            reason="Email contains complex or high-risk business/legal terms.",
        )

    if context.priority == "Low" and context.suggested_action == "Archive":
        return AutomationDecision(
            draft_type="human_prompt",
            confidence_score=0.40,
            needs_human_input=True,
            reason="Email appears low priority and may not require a reply.",
        )

    if any(term in text for term in _ROUTINE_TERMS):
        return AutomationDecision(
            draft_type="full",
            confidence_score=0.86,
            needs_human_input=False,
            reason="Routine email with enough context for a full draft.",
        )

    if context.priority == "High":
        return AutomationDecision(
            draft_type="partial",
            confidence_score=0.68,
            needs_human_input=True,
            reason="High-priority email should be reviewed before final wording.",
        )

    return AutomationDecision(
        draft_type="full",
        confidence_score=0.76,
        needs_human_input=False,
        reason="General email with sufficient context for a draft.",
    )

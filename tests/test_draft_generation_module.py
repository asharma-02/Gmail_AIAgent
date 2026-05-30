from datetime import datetime, timezone

from src.drafts import DraftGenerator, decide_automation
from src.drafts.response_parser import parse_draft_response
from src.drafts.schemas import ClassifiedEmailContext
from src.models.types import (
    AvgSentenceLength,
    EmailMessage,
    FormalityLevel,
    TechnicalLanguageUsage,
    ToneProfile,
)


def _email(subject: str = "Follow-up on proposal", body: str = "Hi, just checking in."):
    return EmailMessage(
        message_id="msg_001",
        thread_id="thread_001",
        from_address="sarah@example.com",
        to=["founder@example.com"],
        subject=subject,
        body=body,
        sent_at=datetime.now(tz=timezone.utc),
        labels=["INBOX"],
    )


def _context(
    subject: str = "Follow-up on proposal",
    body: str = "Hi, just checking in.",
    priority: str = "Medium",
    suggested_action: str = "Reply Today",
):
    return ClassifiedEmailContext(
        email=_email(subject=subject, body=body),
        summary="Sender is following up and expects a short response.",
        priority=priority,
        suggested_action=suggested_action,
    )


def test_parse_draft_response_extracts_subject_and_body():
    subject, body = parse_draft_response(
        "Subject: Re: Follow-up\nBody:\nHi Sarah,\n\nThanks for following up."
    )

    assert subject == "Re: Follow-up"
    assert "Hi Sarah" in body


def test_selective_automation_full_for_routine_email():
    decision = decide_automation(_context())

    assert decision.draft_type == "full"
    assert decision.needs_human_input is False
    assert decision.confidence_score > 0.7


def test_selective_automation_partial_for_complex_email():
    context = _context(
        subject="Contract termination concern",
        body="We need to discuss legal concerns and contract termination.",
        priority="High",
        suggested_action="Reply Today",
    )

    decision = decide_automation(context)

    assert decision.draft_type == "partial"
    assert decision.needs_human_input is True


def test_selective_automation_human_prompt_when_required():
    context = _context(
        subject="Sensitive investor matter",
        body="Please review this confidential term sheet.",
        priority="High",
        suggested_action="Needs Human Review",
    )

    decision = decide_automation(context)

    assert decision.draft_type == "human_prompt"
    assert decision.needs_human_input is True


def test_draft_generator_creates_valid_draft():
    generator = DraftGenerator()
    context = _context()

    result = generator.generate_from_llm_response(
        context=context,
        llm_response_text=(
            "Subject: Re: Follow-up on proposal\n"
            "Body:\n"
            "Hi Sarah,\n\n"
            "Thanks for following up. I will review this and get back to you shortly.\n\n"
            "Best regards,"
        ),
        instruction_text="Draft a reply to Sarah.",
    )

    assert result.draft is not None
    assert result.draft.recipient == "sarah@example.com"
    assert result.draft.subject == "Re: Follow-up on proposal"
    assert "Thanks for following up" in result.draft.body
    assert result.needs_human_input is False
    assert "Draft must pass approval workflow before sending." in result.safety_notes


def test_draft_generator_applies_tone_profile_summary():
    generator = DraftGenerator()
    context = _context()
    profile = ToneProfile(
        recipient_email="sarah@example.com",
        formality_level=FormalityLevel.FORMAL,
        greeting_style="Dear Sarah,",
        sign_off_style="Kind regards,",
        avg_sentence_length=AvgSentenceLength.SHORT,
        technical_language_usage=TechnicalLanguageUsage.LOW,
        warmth_indicator=0.7,
        derived_from_count=5,
    )

    result = generator.generate_from_llm_response(
        context=context,
        llm_response_text=(
            "Subject: Re: Follow-up on proposal\n"
            "Body:\nDear Sarah,\n\nThank you for following up.\n\nKind regards,"
        ),
        instruction_text="Draft a reply.",
        tone_profile=profile,
    )

    assert result.draft is not None
    assert result.draft.tone_profile_used is not None
    assert result.draft.tone_profile_used.recipient_email == "sarah@example.com"
    assert result.draft.tone_profile_used.formality_level == "formal"


def test_draft_generator_returns_human_prompt_without_draft():
    generator = DraftGenerator()
    context = _context(
        subject="Confidential term sheet",
        body="Please approve the confidential investment terms.",
        priority="High",
        suggested_action="Needs Human Review",
    )

    result = generator.generate_from_llm_response(
        context=context,
        llm_response_text="Subject: Re: Confidential term sheet\nBody:\nThanks.",
        instruction_text="Draft a reply.",
    )

    assert result.draft is None
    assert result.draft_type == "human_prompt"
    assert result.needs_human_input is True
    assert result.human_prompt is not None

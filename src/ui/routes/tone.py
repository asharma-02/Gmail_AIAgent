"""
Tone profile routes — list and inspect tone profiles per recipient.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

router = APIRouter()


class ToneProfileOut(BaseModel):
    recipient_email: str
    formality_level: str
    avg_sentence_length: str
    technical_language_usage: str
    warmth_indicator: float
    greeting_style: str | None
    sign_off_style: str | None
    sample_size: int


@router.get("/profiles", response_model=list[ToneProfileOut])
async def list_tone_profiles() -> list[ToneProfileOut]:
    """List all derived tone profiles."""
    from src.ui.state import orchestrator

    summaries = orchestrator._tone_engine.list_profiles()
    result = []
    for summary in summaries:
        try:
            profile = orchestrator._tone_engine.get_profile(summary.recipient_email)
            result.append(
                ToneProfileOut(
                    recipient_email=profile.recipient_email,
                    formality_level=profile.formality_level.value,
                    avg_sentence_length=profile.avg_sentence_length.value,
                    technical_language_usage=profile.technical_language_usage.value,
                    warmth_indicator=profile.warmth_indicator,
                    greeting_style=profile.greeting_style,
                    sign_off_style=profile.sign_off_style,
                    sample_size=profile.derived_from_count,
                )
            )
        except Exception:
            continue
    return result


@router.get("/profiles/{recipient_email:path}", response_model=ToneProfileOut)
async def get_tone_profile(recipient_email: str) -> ToneProfileOut:
    """Get the tone profile for a specific recipient."""
    from src.ui.state import orchestrator

    try:
        profile = orchestrator._tone_engine.get_profile(recipient_email)
        return ToneProfileOut(
            recipient_email=profile.recipient_email,
            formality_level=profile.formality_level.value,
            avg_sentence_length=profile.avg_sentence_length.value,
            technical_language_usage=profile.technical_language_usage.value,
            warmth_indicator=profile.warmth_indicator,
            greeting_style=profile.greeting_style,
            sign_off_style=profile.sign_off_style,
            sample_size=profile.derived_from_count,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No tone profile found for {recipient_email}",
        ) from exc

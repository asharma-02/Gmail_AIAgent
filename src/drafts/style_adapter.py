"""Writing-style adaptation helpers for draft generation."""

from __future__ import annotations

from src.models.types import ToneOverride, ToneProfile, ToneProfileSummary


def tone_profile_to_summary(profile: ToneProfile) -> ToneProfileSummary:
    """Convert a stored ToneProfile into the summary expected by Draft."""
    description = (
        f"{profile.formality_level.value.replace('_', ' ').capitalize()} tone, "
        f"{profile.avg_sentence_length.value} sentences, "
        f"{profile.technical_language_usage.value} technical language, "
        f"warmth {profile.warmth_indicator:.2f}. "
        f"Typical greeting: {profile.greeting_style} "
        f"Typical sign-off: {profile.sign_off_style}"
    )

    return ToneProfileSummary(
        recipient_email=profile.recipient_email,
        formality_level=profile.formality_level.value,
        description=description,
        last_updated_at=profile.last_updated_at,
    )


def build_style_guidance(
    tone_profile: ToneProfile | None = None,
    tone_override: ToneOverride | None = None,
) -> str:
    """
    Build human-readable style guidance for the LLM prompt.

    This does not generate the draft itself. It constrains how the model should
    write so the output matches the user's usual style.
    """
    if tone_override and tone_override.custom_description:
        return (
            "Use the following user-provided tone override for this draft:\n"
            f"{tone_override.custom_description.strip()}"
        )

    if tone_profile is None:
        return (
            "Use a professional, concise, founder/CEO-appropriate tone. "
            "Keep the reply clear, polite, and not overly long."
        )

    guidance = [
        f"Formality level: {tone_profile.formality_level.value.replace('_', ' ')}.",
        f"Greeting style: {tone_profile.greeting_style}",
        f"Sign-off style: {tone_profile.sign_off_style}",
        f"Average sentence length: {tone_profile.avg_sentence_length.value}.",
        f"Technical language usage: {tone_profile.technical_language_usage.value}.",
        f"Warmth indicator: {tone_profile.warmth_indicator:.2f} on a 0 to 1 scale.",
    ]

    if tone_override and tone_override.formality_level:
        guidance.append(
            "Override formality for this draft: "
            f"{tone_override.formality_level.value.replace('_', ' ')}."
        )

    return "\n".join(guidance)

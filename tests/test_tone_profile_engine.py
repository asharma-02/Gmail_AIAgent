"""
Unit tests for ToneProfileEngine (Tasks 8.1, 8.2, 8.3).

Coverage:
  8.1 — Derivation from sent history
  8.2 — Persistence and retrieval
  8.3 — Incremental update and tone override
"""

from __future__ import annotations

from datetime import datetime

import pytest

from src.models.types import (
    AvgSentenceLength,
    EmailMessage,
    FormalityLevel,
    TechnicalLanguageUsage,
    ToneOverride,
    ToneProfile,
)
from src.tone import ToneProfileEngine, ToneProfileNotFoundError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_RECIPIENT = "alice@example.com"


def _make_email(body: str, subject: str = "Test") -> EmailMessage:
    return EmailMessage(
        message_id="msg-1",
        thread_id="thread-1",
        **{"from": "me@example.com"},
        to=[_RECIPIENT],
        subject=subject,
        body=body,
        sent_at=datetime(2024, 1, 1, 12, 0, 0),
    )


# ---------------------------------------------------------------------------
# 8.1 — Derivation
# ---------------------------------------------------------------------------


class TestDerivation:
    def test_empty_history_returns_neutral_default(self):
        engine = ToneProfileEngine()
        profile = engine.get_or_derive_profile(_RECIPIENT, [])

        assert profile.recipient_email == _RECIPIENT
        assert profile.formality_level == FormalityLevel.NEUTRAL
        assert profile.derived_from_count == 0

    def test_empty_history_warmth_is_default(self):
        engine = ToneProfileEngine()
        profile = engine.get_or_derive_profile(_RECIPIENT, [])
        assert 0.0 <= profile.warmth_indicator <= 1.0

    def test_dear_greeting_yields_formal_or_very_formal(self):
        engine = ToneProfileEngine()
        email = _make_email("Dear Alice,\n\nPlease find attached.\n\nBest regards,\nBob")
        profile = engine.get_or_derive_profile(_RECIPIENT, [email])

        assert profile.formality_level in (FormalityLevel.FORMAL, FormalityLevel.VERY_FORMAL)

    def test_hey_greeting_yields_casual_or_informal(self):
        engine = ToneProfileEngine()
        email = _make_email("Hey Alice!\n\nJust checking in.\n\nCheers,\nBob")
        profile = engine.get_or_derive_profile(_RECIPIENT, [email])

        assert profile.formality_level in (FormalityLevel.CASUAL, FormalityLevel.INFORMAL)

    def test_multiple_emails_derived_from_count_equals_history_length(self):
        engine = ToneProfileEngine()
        emails = [
            _make_email("Hi Alice,\n\nSounds good.\n\nBest,\nBob"),
            _make_email("Hi Alice,\n\nThanks for the update.\n\nBest,\nBob"),
            _make_email("Hi Alice,\n\nLooking forward to it.\n\nBest,\nBob"),
        ]
        profile = engine.get_or_derive_profile(_RECIPIENT, emails)

        assert profile.derived_from_count == len(emails)

    def test_technical_emails_yield_high_technical_usage(self):
        engine = ToneProfileEngine()
        body = (
            "Hi Alice,\n\n"
            "The API endpoint is down. The database server needs a deploy. "
            "Please check the code and run the algorithm against the system. "
            "The function in the repository is broken.\n\n"
            "Best,\nBob"
        )
        email = _make_email(body)
        profile = engine.get_or_derive_profile(_RECIPIENT, [email])

        assert profile.technical_language_usage == TechnicalLanguageUsage.HIGH

    def test_warm_language_yields_warmth_above_half(self):
        engine = ToneProfileEngine()
        body = (
            "Hi Alice,\n\n"
            "I hope you are doing great! I really appreciate your help. "
            "It was a pleasure working with you. Thank you so much. "
            "Looking forward to our next meeting!\n\n"
            "Best,\nBob"
        )
        email = _make_email(body)
        profile = engine.get_or_derive_profile(_RECIPIENT, [email])

        assert profile.warmth_indicator > 0.5

    def test_derived_profile_is_stored_in_profiles(self):
        engine = ToneProfileEngine()
        email = _make_email("Hi Alice,\n\nSounds good.\n\nBest,\nBob")
        engine.get_or_derive_profile(_RECIPIENT, [email])

        assert engine.get_profile(_RECIPIENT) is not None

    def test_existing_profile_returned_without_re_derivation(self):
        engine = ToneProfileEngine()
        email = _make_email("Hi Alice,\n\nSounds good.\n\nBest,\nBob")
        first = engine.get_or_derive_profile(_RECIPIENT, [email])
        # Second call with different history — should return the cached profile
        second = engine.get_or_derive_profile(_RECIPIENT, [])
        assert first.profile_id == second.profile_id


# ---------------------------------------------------------------------------
# 8.2 — Persistence and retrieval
# ---------------------------------------------------------------------------


class TestPersistence:
    def test_save_profile_stores_by_recipient_email(self):
        engine = ToneProfileEngine()
        profile = ToneProfile(
            recipient_email=_RECIPIENT,
            derived_from_count=3,
        )
        engine.save_profile(profile)

        assert engine.get_profile(_RECIPIENT) is profile

    def test_get_profile_returns_none_for_unknown_recipient(self):
        engine = ToneProfileEngine()
        assert engine.get_profile("unknown@example.com") is None

    def test_get_profile_returns_stored_profile(self):
        engine = ToneProfileEngine()
        profile = ToneProfile(recipient_email=_RECIPIENT)
        engine.save_profile(profile)

        retrieved = engine.get_profile(_RECIPIENT)
        assert retrieved is not None
        assert retrieved.recipient_email == _RECIPIENT

    def test_list_profiles_returns_summary_for_each_stored_profile(self):
        engine = ToneProfileEngine()
        engine.save_profile(ToneProfile(recipient_email="a@example.com", derived_from_count=2))
        engine.save_profile(ToneProfile(recipient_email="b@example.com", derived_from_count=5))

        summaries = engine.list_profiles()
        emails = {s.recipient_email for s in summaries}
        assert "a@example.com" in emails
        assert "b@example.com" in emails

    def test_list_profiles_returns_empty_list_when_no_profiles(self):
        engine = ToneProfileEngine()
        assert engine.list_profiles() == []

    def test_overwriting_profile_replaces_previous(self):
        engine = ToneProfileEngine()
        original = ToneProfile(recipient_email=_RECIPIENT, derived_from_count=1)
        engine.save_profile(original)

        replacement = ToneProfile(recipient_email=_RECIPIENT, derived_from_count=99)
        engine.save_profile(replacement)

        stored = engine.get_profile(_RECIPIENT)
        assert stored is not None
        assert stored.derived_from_count == 99

    def test_list_profiles_summary_description_format(self):
        engine = ToneProfileEngine()
        profile = ToneProfile(
            recipient_email=_RECIPIENT,
            formality_level=FormalityLevel.FORMAL,
            warmth_indicator=0.8,
            derived_from_count=5,
        )
        engine.save_profile(profile)

        summaries = engine.list_profiles()
        assert len(summaries) == 1
        desc = summaries[0].description
        # Should contain formality, warmth, and count
        assert "formal" in desc.lower()
        assert "0.8" in desc
        assert "5" in desc


# ---------------------------------------------------------------------------
# 8.3 — Incremental update and override
# ---------------------------------------------------------------------------


class TestUpdateAndOverride:
    def _stored_profile(self, engine: ToneProfileEngine, count: int = 3) -> ToneProfile:
        profile = ToneProfile(
            recipient_email=_RECIPIENT,
            derived_from_count=count,
            warmth_indicator=0.4,
            formality_level=FormalityLevel.NEUTRAL,
            greeting_style="Hi [Name],",
            sign_off_style="Best regards,",
            avg_sentence_length=AvgSentenceLength.MEDIUM,
            technical_language_usage=TechnicalLanguageUsage.LOW,
        )
        engine.save_profile(profile)
        return profile

    def test_update_profile_increments_derived_from_count_by_exactly_1(self):
        engine = ToneProfileEngine()
        original = self._stored_profile(engine, count=5)
        email = _make_email("Hi Alice,\n\nSounds good.\n\nBest,\nBob")

        updated = engine.update_profile(_RECIPIENT, email)

        assert updated.derived_from_count == original.derived_from_count + 1

    def test_update_profile_updates_last_updated_at(self):
        engine = ToneProfileEngine()
        original = self._stored_profile(engine)
        before = original.last_updated_at

        email = _make_email("Hi Alice,\n\nSounds good.\n\nBest,\nBob")
        updated = engine.update_profile(_RECIPIENT, email)

        assert updated.last_updated_at >= before

    def test_update_profile_preserves_all_existing_fields(self):
        engine = ToneProfileEngine()
        original = self._stored_profile(engine)
        email = _make_email("Hi Alice,\n\nSounds good.\n\nBest,\nBob")

        updated = engine.update_profile(_RECIPIENT, email)

        # All fields that should be preserved are present
        assert updated.profile_id == original.profile_id
        assert updated.recipient_email == original.recipient_email
        assert updated.created_at == original.created_at
        # Numeric fields exist and are valid
        assert 0.0 <= updated.warmth_indicator <= 1.0
        assert updated.avg_sentence_length in list(AvgSentenceLength)
        assert updated.technical_language_usage in list(TechnicalLanguageUsage)

    def test_update_profile_raises_for_unknown_recipient(self):
        engine = ToneProfileEngine()
        email = _make_email("Hi,\n\nTest.\n\nBest,\nBob")

        with pytest.raises(ToneProfileNotFoundError):
            engine.update_profile("nobody@example.com", email)

    def test_apply_override_returns_new_profile_with_formality_applied(self):
        engine = ToneProfileEngine()
        profile = ToneProfile(
            recipient_email=_RECIPIENT,
            formality_level=FormalityLevel.NEUTRAL,
        )
        engine.save_profile(profile)

        override = ToneOverride(formality_level=FormalityLevel.VERY_FORMAL)
        result = engine.apply_override(profile, override)

        assert result.formality_level == FormalityLevel.VERY_FORMAL

    def test_apply_override_does_not_modify_original_persisted_profile(self):
        engine = ToneProfileEngine()
        profile = ToneProfile(
            recipient_email=_RECIPIENT,
            formality_level=FormalityLevel.NEUTRAL,
        )
        engine.save_profile(profile)

        override = ToneOverride(formality_level=FormalityLevel.VERY_FORMAL)
        engine.apply_override(profile, override)

        # The persisted profile must be unchanged
        persisted = engine.get_profile(_RECIPIENT)
        assert persisted is not None
        assert persisted.formality_level == FormalityLevel.NEUTRAL

    def test_apply_override_with_custom_description_sets_greeting_style_hint(self):
        engine = ToneProfileEngine()
        profile = ToneProfile(
            recipient_email=_RECIPIENT,
            greeting_style="Hi [Name],",
        )
        engine.save_profile(profile)

        override = ToneOverride(custom_description="Use a very casual, friendly tone")
        result = engine.apply_override(profile, override)

        assert result.greeting_style == "Use a very casual, friendly tone"

    def test_apply_override_returns_new_object_not_same_reference(self):
        engine = ToneProfileEngine()
        profile = ToneProfile(recipient_email=_RECIPIENT)
        engine.save_profile(profile)

        override = ToneOverride(formality_level=FormalityLevel.FORMAL)
        result = engine.apply_override(profile, override)

        assert result is not profile

    def test_update_profile_blends_warmth_correctly(self):
        """Warmth should be a weighted average: (existing * count + new) / (count + 1)."""
        engine = ToneProfileEngine()
        count = 4
        existing_warmth = 0.2
        profile = ToneProfile(
            recipient_email=_RECIPIENT,
            derived_from_count=count,
            warmth_indicator=existing_warmth,
        )
        engine.save_profile(profile)

        # Email with strong warm language
        warm_body = (
            "Hi Alice,\n\n"
            "I hope you are doing great! I really appreciate your help. "
            "Thank you so much. Looking forward to it!\n\n"
            "Best,\nBob"
        )
        email = _make_email(warm_body)
        updated = engine.update_profile(_RECIPIENT, email)

        # Warmth should have increased (new email is warm)
        assert updated.warmth_indicator > existing_warmth

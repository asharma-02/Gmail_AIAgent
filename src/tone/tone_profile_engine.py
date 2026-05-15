"""
Tone Profile Engine — derives, persists, updates, and overrides ToneProfiles.

Profiles are derived from a user's Gmail sent history for a specific recipient.
They are stored in an in-memory dict keyed by recipient_email and updated
incrementally as new emails are sent.
"""

from __future__ import annotations

import re
from collections import Counter
from datetime import datetime, timezone

from src.models.types import (
    AvgSentenceLength,
    EmailMessage,
    FormalityLevel,
    TechnicalLanguageUsage,
    ToneOverride,
    ToneProfile,
    ToneProfileSummary,
)
from src.tone.errors import ToneProfileNotFoundError

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_GREETING_PATTERNS = ["Dear", "Hello", "Hi", "Hey", "Good morning", "Good afternoon"]

_SIGN_OFF_PATTERNS = [
    "Best regards",
    "Kind regards",
    "Regards",
    "Sincerely",
    "Yours sincerely",
    "Yours faithfully",
    "Best",
    "Thanks",
    "Thank you",
    "Cheers",
    "All the best",
    "Warm regards",
    "With appreciation",
]

_WARMTH_WORDS = [
    "hope",
    "great",
    "wonderful",
    "appreciate",
    "thank",
    "pleasure",
    "looking forward",
    "excited",
    "delighted",
    "happy",
    "glad",
    "fantastic",
    "excellent",
]

_TECHNICAL_WORDS = [
    "api",
    "system",
    "database",
    "server",
    "deploy",
    "deployment",
    "code",
    "function",
    "algorithm",
    "architecture",
    "infrastructure",
    "endpoint",
    "repository",
    "pipeline",
    "framework",
    "library",
    "module",
    "interface",
    "protocol",
    "configuration",
]


# ---------------------------------------------------------------------------
# ToneProfileEngine
# ---------------------------------------------------------------------------


class ToneProfileEngine:
    """
    Derives, persists, updates, and overrides ToneProfiles.

    Uses an in-memory dict as the backing store.  All public methods are
    synchronous and side-effect-free with respect to external I/O.
    """

    def __init__(self) -> None:
        self._profiles: dict[str, ToneProfile] = {}

    # ------------------------------------------------------------------
    # Task 8.1 — Derivation
    # ------------------------------------------------------------------

    def get_or_derive_profile(
        self,
        recipient_email: str,
        gmail_history: list[EmailMessage],
    ) -> ToneProfile:
        """
        Return the persisted profile for *recipient_email* if one exists,
        otherwise derive a new profile from *gmail_history*, store it, and
        return it.

        If *gmail_history* is empty a neutral default profile is returned
        (derived_from_count=0) and stored.
        """
        existing = self._profiles.get(recipient_email)
        if existing is not None:
            return existing

        if not gmail_history:
            profile = ToneProfile(
                recipient_email=recipient_email,
                formality_level=FormalityLevel.NEUTRAL,
                greeting_style="Hi [Name],",
                sign_off_style="Best regards,",
                avg_sentence_length=AvgSentenceLength.MEDIUM,
                technical_language_usage=TechnicalLanguageUsage.MEDIUM,
                warmth_indicator=0.5,
                derived_from_count=0,
            )
            self._profiles[recipient_email] = profile
            return profile

        profile = self._derive_from_history(recipient_email, gmail_history)
        self._profiles[recipient_email] = profile
        return profile

    # ------------------------------------------------------------------
    # Task 8.2 — Persistence and retrieval
    # ------------------------------------------------------------------

    def save_profile(self, profile: ToneProfile) -> None:
        """Store (or overwrite) a profile keyed by its recipient_email."""
        self._profiles[profile.recipient_email] = profile

    def get_profile(self, recipient_email: str) -> ToneProfile | None:
        """Return the stored profile for *recipient_email*, or None."""
        return self._profiles.get(recipient_email)

    def list_profiles(self) -> list[ToneProfileSummary]:
        """Return a ToneProfileSummary for every stored profile."""
        summaries: list[ToneProfileSummary] = []
        for profile in self._profiles.values():
            description = (
                f"{profile.formality_level.value.replace('_', ' ').capitalize()} tone, "
                f"warm ({profile.warmth_indicator:.1f}), "
                f"derived from {profile.derived_from_count} emails"
            )
            summaries.append(
                ToneProfileSummary(
                    recipient_email=profile.recipient_email,
                    formality_level=profile.formality_level.value,
                    description=description,
                    last_updated_at=profile.last_updated_at,
                )
            )
        return summaries

    # ------------------------------------------------------------------
    # Task 8.3 — Incremental update and override
    # ------------------------------------------------------------------

    def update_profile(
        self,
        recipient_email: str,
        sent_email: EmailMessage,
    ) -> ToneProfile:
        """
        Blend the signals from *sent_email* into the existing profile for
        *recipient_email*.

        Raises ToneProfileNotFoundError if no profile exists yet.
        """
        existing = self._profiles.get(recipient_email)
        if existing is None:
            raise ToneProfileNotFoundError(
                f"No tone profile found for recipient: {recipient_email}"
            )

        count = existing.derived_from_count
        new_count = count + 1

        # --- warmth: weighted average ---
        new_warmth = _compute_warmth([sent_email])
        blended_warmth = (existing.warmth_indicator * count + new_warmth) / new_count
        blended_warmth = max(0.0, min(1.0, blended_warmth))

        # --- greeting: update only if a clear pattern is found ---
        new_greeting = _extract_greeting(sent_email.body)
        greeting_style = (
            new_greeting if new_greeting else existing.greeting_style
        )

        # --- sign-off: update only if a clear pattern is found ---
        new_sign_off = _extract_sign_off(sent_email.body)
        sign_off_style = (
            new_sign_off if new_sign_off else existing.sign_off_style
        )

        # --- formality: update only if a clear signal is found ---
        new_formality = _detect_formality_from_body(sent_email.body)
        formality_level = (
            new_formality if new_formality is not None else existing.formality_level
        )

        # --- sentence length: weighted blend ---
        new_sent_len = _compute_avg_sentence_length([sent_email])
        blended_sent_len = _blend_sentence_length(
            existing.avg_sentence_length, new_sent_len, count, 1
        )

        # --- technical usage: weighted blend ---
        new_tech = _compute_technical_usage([sent_email])
        blended_tech = _blend_technical_usage(
            existing.technical_language_usage, new_tech, count, 1
        )

        updated = existing.model_copy(
            update={
                "derived_from_count": new_count,
                "warmth_indicator": round(blended_warmth, 4),
                "greeting_style": greeting_style,
                "sign_off_style": sign_off_style,
                "formality_level": formality_level,
                "avg_sentence_length": blended_sent_len,
                "technical_language_usage": blended_tech,
                "last_updated_at": datetime.now(tz=timezone.utc),
            }
        )
        self._profiles[recipient_email] = updated
        return updated

    def apply_override(
        self,
        profile: ToneProfile,
        override: ToneOverride,
    ) -> ToneProfile:
        """
        Return a NEW ToneProfile with the override applied.

        The persisted profile is NOT modified.
        """
        updates: dict = {}

        if override.formality_level is not None:
            updates["formality_level"] = override.formality_level

        if override.custom_description is not None:
            # Store the custom description as a hint in greeting_style
            updates["greeting_style"] = override.custom_description

        if not updates:
            # Return a copy with no changes so callers always get a new object
            return profile.model_copy()

        return profile.model_copy(update=updates)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _derive_from_history(
        self,
        recipient_email: str,
        history: list[EmailMessage],
    ) -> ToneProfile:
        """Derive a ToneProfile from a non-empty list of EmailMessages."""
        formality = _compute_formality(history)
        greeting = _compute_most_common_greeting(history)
        sign_off = _compute_most_common_sign_off(history)
        avg_sent_len = _compute_avg_sentence_length(history)
        tech_usage = _compute_technical_usage(history)
        warmth = _compute_warmth(history)

        return ToneProfile(
            recipient_email=recipient_email,
            formality_level=formality,
            greeting_style=greeting,
            sign_off_style=sign_off,
            avg_sentence_length=avg_sent_len,
            technical_language_usage=tech_usage,
            warmth_indicator=round(warmth, 4),
            derived_from_count=len(history),
        )


# ---------------------------------------------------------------------------
# Pure analysis helpers (module-level, no state)
# ---------------------------------------------------------------------------


def _compute_formality(history: list[EmailMessage]) -> FormalityLevel:
    """
    Determine formality by scanning greetings across all emails.

    Heuristic:
      - "Dear"  → formal / very_formal
      - "Hi"    → neutral / informal
      - "Hey"   → casual
      - default → neutral
    """
    dear_count = 0
    hi_count = 0
    hey_count = 0

    for email in history:
        body_lower = email.body.lower()
        first_line = email.body.strip().split("\n")[0].lower()

        if first_line.startswith("dear"):
            dear_count += 1
        elif first_line.startswith("hey"):
            hey_count += 1
        elif first_line.startswith("hi") or first_line.startswith("hello"):
            hi_count += 1
        # Also check anywhere in the body for a greeting line
        elif re.search(r"^\s*dear\b", body_lower, re.MULTILINE):
            dear_count += 1
        elif re.search(r"^\s*hey\b", body_lower, re.MULTILINE):
            hey_count += 1
        elif re.search(r"^\s*(hi|hello)\b", body_lower, re.MULTILINE):
            hi_count += 1

    total = dear_count + hi_count + hey_count
    if total == 0:
        return FormalityLevel.NEUTRAL

    if dear_count >= hi_count and dear_count >= hey_count:
        # Majority "Dear" → formal; if very dominant → very_formal
        ratio = dear_count / len(history)
        return FormalityLevel.VERY_FORMAL if ratio >= 0.75 else FormalityLevel.FORMAL
    elif hey_count > hi_count and hey_count > dear_count:
        return FormalityLevel.CASUAL
    else:
        # Majority "Hi" / "Hello"
        ratio = hi_count / len(history)
        return FormalityLevel.INFORMAL if ratio >= 0.75 else FormalityLevel.NEUTRAL


def _detect_formality_from_body(body: str) -> FormalityLevel | None:
    """
    Detect formality from a single email body.
    Returns None if no clear signal is found.
    """
    first_line = body.strip().split("\n")[0].lower()
    if first_line.startswith("dear"):
        return FormalityLevel.FORMAL
    if first_line.startswith("hey"):
        return FormalityLevel.CASUAL
    if first_line.startswith("hi") or first_line.startswith("hello"):
        return FormalityLevel.NEUTRAL
    # Check multiline
    if re.search(r"^\s*dear\b", body, re.MULTILINE | re.IGNORECASE):
        return FormalityLevel.FORMAL
    if re.search(r"^\s*hey\b", body, re.MULTILINE | re.IGNORECASE):
        return FormalityLevel.CASUAL
    if re.search(r"^\s*(hi|hello)\b", body, re.MULTILINE | re.IGNORECASE):
        return FormalityLevel.NEUTRAL
    return None


def _extract_greeting(body: str) -> str | None:
    """
    Extract the greeting line from an email body.
    Returns None if no recognisable greeting is found.
    """
    lines = body.strip().split("\n")
    for line in lines[:3]:  # greeting is usually in the first few lines
        stripped = line.strip()
        for pattern in _GREETING_PATTERNS:
            if stripped.lower().startswith(pattern.lower()):
                return stripped if stripped.endswith(",") else stripped + ","
    return None


def _extract_sign_off(body: str) -> str | None:
    """
    Extract the sign-off from an email body (last non-empty line before
    the signature block).
    Returns None if no recognisable sign-off is found.
    """
    lines = [l.strip() for l in body.strip().split("\n") if l.strip()]
    # Search from the bottom up
    for line in reversed(lines):
        for pattern in _SIGN_OFF_PATTERNS:
            if line.lower().startswith(pattern.lower()):
                return line if line.endswith(",") else line + ","
    return None


def _compute_most_common_greeting(history: list[EmailMessage]) -> str:
    """Return the most common greeting pattern across all emails."""
    counter: Counter = Counter()
    for email in history:
        greeting = _extract_greeting(email.body)
        if greeting:
            # Normalise to the keyword only for counting
            keyword = greeting.split()[0].rstrip(",")
            counter[keyword] += 1

    if not counter:
        return "Hi [Name],"

    most_common_keyword = counter.most_common(1)[0][0]
    # Find a representative full greeting
    for email in history:
        greeting = _extract_greeting(email.body)
        if greeting and greeting.lower().startswith(most_common_keyword.lower()):
            return greeting
    return f"{most_common_keyword} [Name],"


def _compute_most_common_sign_off(history: list[EmailMessage]) -> str:
    """Return the most common sign-off pattern across all emails."""
    counter: Counter = Counter()
    for email in history:
        sign_off = _extract_sign_off(email.body)
        if sign_off:
            # Normalise to first word for counting
            keyword = sign_off.split()[0].rstrip(",")
            counter[keyword] += 1

    if not counter:
        return "Best regards,"

    most_common_keyword = counter.most_common(1)[0][0]
    for email in history:
        sign_off = _extract_sign_off(email.body)
        if sign_off and sign_off.lower().startswith(most_common_keyword.lower()):
            return sign_off
    return f"{most_common_keyword},"


def _compute_avg_sentence_length(history: list[EmailMessage]) -> AvgSentenceLength:
    """
    Compute average words per sentence across all emails.

    <10 words  → SHORT
    10-20      → MEDIUM
    >20        → LONG
    """
    total_words = 0
    total_sentences = 0

    for email in history:
        # Split on sentence-ending punctuation
        sentences = re.split(r"[.!?]+", email.body)
        sentences = [s.strip() for s in sentences if s.strip()]
        for sentence in sentences:
            words = sentence.split()
            total_words += len(words)
            total_sentences += 1

    if total_sentences == 0:
        return AvgSentenceLength.MEDIUM

    avg = total_words / total_sentences
    if avg < 10:
        return AvgSentenceLength.SHORT
    elif avg <= 20:
        return AvgSentenceLength.MEDIUM
    else:
        return AvgSentenceLength.LONG


def _compute_technical_usage(history: list[EmailMessage]) -> TechnicalLanguageUsage:
    """
    Count technical indicator words across all emails.

    >5 per email  → HIGH
    2-5 per email → MEDIUM
    <2 per email  → LOW
    """
    if not history:
        return TechnicalLanguageUsage.LOW

    total_tech = 0
    for email in history:
        body_lower = email.body.lower()
        for word in _TECHNICAL_WORDS:
            total_tech += len(re.findall(r"\b" + re.escape(word) + r"\b", body_lower))

    avg_per_email = total_tech / len(history)
    if avg_per_email > 5:
        return TechnicalLanguageUsage.HIGH
    elif avg_per_email >= 2:
        return TechnicalLanguageUsage.MEDIUM
    else:
        return TechnicalLanguageUsage.LOW


def _compute_warmth(history: list[EmailMessage]) -> float:
    """
    Compute a warmth indicator (0.0–1.0) based on warm language presence.

    Each warm word found in an email contributes to the score.
    The score is normalised to [0.0, 1.0].
    """
    if not history:
        return 0.5

    total_score = 0.0
    for email in history:
        body_lower = email.body.lower()
        hits = 0
        for word in _WARMTH_WORDS:
            hits += len(re.findall(r"\b" + re.escape(word) + r"\b", body_lower))
        # Cap per-email contribution: 5+ hits → 1.0, scale linearly below
        total_score += min(hits / 5.0, 1.0)

    return total_score / len(history)


def _blend_sentence_length(
    existing: AvgSentenceLength,
    new: AvgSentenceLength,
    existing_count: int,
    new_count: int,
) -> AvgSentenceLength:
    """
    Weighted blend of two AvgSentenceLength values.
    Maps to numeric scores, blends, then maps back.
    """
    _score = {
        AvgSentenceLength.SHORT: 5.0,
        AvgSentenceLength.MEDIUM: 15.0,
        AvgSentenceLength.LONG: 25.0,
    }
    existing_score = _score[existing]
    new_score = _score[new]
    total = existing_count + new_count
    blended = (existing_score * existing_count + new_score * new_count) / total
    if blended < 10:
        return AvgSentenceLength.SHORT
    elif blended <= 20:
        return AvgSentenceLength.MEDIUM
    else:
        return AvgSentenceLength.LONG


def _blend_technical_usage(
    existing: TechnicalLanguageUsage,
    new: TechnicalLanguageUsage,
    existing_count: int,
    new_count: int,
) -> TechnicalLanguageUsage:
    """
    Weighted blend of two TechnicalLanguageUsage values.
    Maps to numeric scores, blends, then maps back.
    """
    _score = {
        TechnicalLanguageUsage.LOW: 1.0,
        TechnicalLanguageUsage.MEDIUM: 3.5,
        TechnicalLanguageUsage.HIGH: 7.0,
    }
    existing_score = _score[existing]
    new_score = _score[new]
    total = existing_count + new_count
    blended = (existing_score * existing_count + new_score * new_count) / total
    if blended > 5:
        return TechnicalLanguageUsage.HIGH
    elif blended >= 2:
        return TechnicalLanguageUsage.MEDIUM
    else:
        return TechnicalLanguageUsage.LOW

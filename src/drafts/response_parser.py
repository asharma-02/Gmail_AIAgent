"""Utilities for parsing LLM draft responses safely."""

from __future__ import annotations

import re

from src.drafts.errors import InvalidLLMResponseError


_SUBJECT_RE = re.compile(r"(?im)^\s*subject\s*:\s*(.+?)\s*$")
_BODY_RE = re.compile(r"(?is)\bbody\s*:\s*(.+)$")


def extract_subject(response_text: str, default_subject: str = "Draft") -> str:
    """Extract a subject line from an LLM response."""
    if not response_text or not response_text.strip():
        return default_subject

    match = _SUBJECT_RE.search(response_text)
    if not match:
        return default_subject

    subject = match.group(1).strip()
    subject = re.sub(r"[\r\n]+", " ", subject).strip()
    return subject or default_subject


def extract_body(response_text: str) -> str:
    """
    Extract a draft body from an LLM response.

    Supports responses like:
    Subject: Re: Meeting
    Body:
    Hi Sarah,...
    """
    if not response_text or not response_text.strip():
        raise InvalidLLMResponseError("LLM response was empty.")

    body_match = _BODY_RE.search(response_text)
    if body_match:
        body = body_match.group(1).strip()
    else:
        # Fallback: remove subject line and use remaining text.
        body = _SUBJECT_RE.sub("", response_text).strip()

    if not body:
        raise InvalidLLMResponseError("LLM response did not contain draft body text.")

    return body


def parse_draft_response(
    response_text: str,
    default_subject: str = "Draft",
) -> tuple[str, str]:
    """Return (subject, body) parsed from an LLM draft response."""
    subject = extract_subject(response_text, default_subject=default_subject)
    body = extract_body(response_text)
    return subject, body

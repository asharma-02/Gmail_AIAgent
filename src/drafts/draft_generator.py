"""Draft reply generation module owned by Akbar."""

from __future__ import annotations

from src.drafts.prompt_templates import build_full_draft_prompt
from src.drafts.response_parser import parse_draft_response
from src.drafts.schemas import (
    ClassifiedEmailContext,
    DraftGenerationResult,
)
from src.drafts.selective_automation import decide_automation
from src.drafts.style_adapter import build_style_guidance, tone_profile_to_summary
from src.models.types import (
    ContentExcerpt,
    ContextSummary,
    DataSource,
    DataSourceReference,
    Draft,
    ToneOverride,
    ToneProfile,
)


class DraftGenerator:
    """
    Generates style-matched draft replies from classified email context.

    This class does not call Gmail and does not send emails. It only prepares
    prompt text and converts LLM output into a Draft object that can be passed
    to the approval workflow.
    """

    def build_prompt(
        self,
        context: ClassifiedEmailContext,
        tone_profile: ToneProfile | None = None,
        tone_override: ToneOverride | None = None,
    ) -> str:
        """Build the final prompt to send to an LLM provider."""
        decision = decide_automation(context)
        style_guidance = build_style_guidance(tone_profile, tone_override)
        return build_full_draft_prompt(context, style_guidance, decision)

    def generate_from_llm_response(
        self,
        context: ClassifiedEmailContext,
        llm_response_text: str,
        instruction_text: str,
        tone_profile: ToneProfile | None = None,
        tone_override: ToneOverride | None = None,
    ) -> DraftGenerationResult:
        """
        Convert LLM output into a validated DraftGenerationResult.

        The orchestrator remains responsible for calling the LLM provider.
        This method only validates/parses output and builds a Draft model.
        """
        decision = decide_automation(context)

        if decision.draft_type == "human_prompt":
            return DraftGenerationResult(
                draft=None,
                draft_type=decision.draft_type,
                confidence_score=decision.confidence_score,
                needs_human_input=True,
                human_prompt=(
                    "This email needs human review before a draft can be safely generated. "
                    f"Reason: {decision.reason}"
                ),
                safety_notes=[
                    "No draft generated for high-uncertainty email.",
                    "No email action performed.",
                    "Human review required.",
                ],
            )

        default_subject = self._default_reply_subject(context.email.subject)
        subject, body = parse_draft_response(
            llm_response_text,
            default_subject=default_subject,
        )

        if decision.draft_type == "partial":
            body = (
                f"{body}\n\n"
                "[Human review needed before sending: please confirm details, "
                "commitments, and final wording.]"
            )

        draft = Draft(
            recipient=context.email.from_address,
            cc=[],
            subject=subject,
            body=body,
            context_summary=self._build_context_summary(context),
            tone_profile_used=(
                tone_profile_to_summary(tone_profile) if tone_profile else None
            ),
            generated_from_instruction=instruction_text,
        )

        return DraftGenerationResult(
            draft=draft,
            draft_type=decision.draft_type,
            confidence_score=decision.confidence_score,
            needs_human_input=decision.needs_human_input,
            human_prompt=None,
            safety_notes=[
                "Draft only; no email action performed.",
                "Draft must pass approval workflow before sending.",
                "External email body treated as untrusted content.",
                "No unsupported sending/deletion/modification performed.",
            ],
        )

    def generate_from_orchestrator_response(
        self,
        recipient: str,
        llm_response_text: str,
        instruction_text: str,
        context_summary: ContextSummary,
        tone_profile: ToneProfile | None = None,
    ) -> DraftGenerationResult:
        """
        Convert the existing orchestrator LLM response into a Draft.

        This compatibility method lets AgentOrchestrator use the draft module
        without changing the current frontend payload shape. It is used until
        Shruthi's summary/priority/suggested_action JSON is fully connected.
        """
        subject, body = parse_draft_response(
            llm_response_text,
            default_subject="Draft",
        )

        draft = Draft(
            recipient=recipient or "",
            cc=[],
            subject=subject,
            body=body,
            context_summary=context_summary,
            tone_profile_used=(
                tone_profile_to_summary(tone_profile) if tone_profile else None
            ),
            generated_from_instruction=instruction_text,
        )

        return DraftGenerationResult(
            draft=draft,
            draft_type="full",
            confidence_score=0.75,
            needs_human_input=False,
            human_prompt=None,
            safety_notes=[
                "Draft only; no email action performed.",
                "Draft must pass approval workflow before sending.",
                "Generated through DraftGenerator compatibility path.",
            ],
        )
    
    @staticmethod
    def _default_reply_subject(subject: str) -> str:
        subject = subject.strip() or "Draft"
        if subject.lower().startswith("re:"):
            return subject
        return f"Re: {subject}"

    @staticmethod
    def _build_context_summary(context: ClassifiedEmailContext) -> ContextSummary:
        excerpt = context.summary[:300]

        return ContextSummary(
            data_sources=[
                DataSourceReference(
                    source=DataSource.GMAIL,
                    description=f"Email from {context.email.from_address}",
                    item_count=1,
                    excerpts=[
                        ContentExcerpt(
                            source_id=context.email.message_id,
                            excerpt=excerpt,
                        )
                    ],
                )
            ],
            generated_from_instruction_only=False,
        )

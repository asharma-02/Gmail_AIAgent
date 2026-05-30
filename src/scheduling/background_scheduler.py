"""
Background scheduler for ADA Agent.

Runs a daemon thread that checks every 60 seconds for scheduled drafts
whose send time has passed and sends them automatically via Gmail.

The human-in-the-loop approval already occurred when the user confirmed
the schedule gate — no further confirmation is required at send time.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone

from src.models.types import ScheduledDraftStatus

logger = logging.getLogger(__name__)

_CHECK_INTERVAL_SECONDS = 60  # check every minute


class BackgroundScheduler:
    """
    Daemon thread that auto-sends scheduled drafts when their send time arrives.

    Parameters
    ----------
    scheduled_draft_manager:
        The ScheduledDraftManager holding all registered drafts.
    gmail_client:
        The GmailClient used to send emails. If None, drafts are marked
        sent without actually sending (simulation mode).
    audit_logger:
        The AuditLogger for recording send events.
    """

    def __init__(self, scheduled_draft_manager, gmail_client, audit_logger) -> None:
        self._manager = scheduled_draft_manager
        self._gmail = gmail_client
        self._audit = audit_logger
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    def start(self) -> None:
        """Start the background scheduler daemon thread."""
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="ada-scheduler",
            daemon=True,  # dies when the main process exits
        )
        self._thread.start()
        logger.info("Background scheduler started (interval=%ds)", _CHECK_INTERVAL_SECONDS)

    def stop(self) -> None:
        """Signal the scheduler to stop."""
        self._stop_event.set()

    def _run(self) -> None:
        """Main loop — runs until stop() is called."""
        while not self._stop_event.is_set():
            try:
                self._process_due_drafts()
            except Exception as exc:
                logger.error("Scheduler error: %s", exc)
            self._stop_event.wait(timeout=_CHECK_INTERVAL_SECONDS)

    def _process_due_drafts(self) -> None:
        """Find all pending drafts whose send time has passed and send them."""
        now = datetime.now(tz=timezone.utc)
        pending = self._manager.list_scheduled_drafts(
            status_filter=ScheduledDraftStatus.PENDING
        )

        for scheduled_draft in pending:
            send_time = scheduled_draft.scheduled_send_time
            # Make timezone-aware if naive
            if send_time.tzinfo is None:
                send_time = send_time.replace(tzinfo=timezone.utc)

            if now >= send_time:
                self._send_draft(scheduled_draft)

    def _send_draft(self, scheduled_draft) -> None:
        """Send a single scheduled draft via Gmail and update its status."""
        draft = scheduled_draft.draft
        scheduled_draft_id = scheduled_draft.scheduled_draft_id

        logger.info(
            "Sending scheduled draft id=%s to=%s subject='%s'",
            scheduled_draft_id, draft.recipient, draft.subject,
        )

        # Mark as awaiting_confirmation while we process
        scheduled_draft.status = ScheduledDraftStatus.AWAITING_CONFIRMATION

        try:
            if self._gmail is not None:
                sent_id = self._gmail.send_message(
                    to=draft.recipient,
                    subject=draft.subject,
                    body=draft.body,
                    cc=draft.cc if draft.cc else None,
                )
            else:
                # Simulation mode — no Gmail client
                sent_id = f"simulated_{scheduled_draft_id}"
                logger.info("Simulated send for scheduled draft id=%s", scheduled_draft_id)

            scheduled_draft.status = ScheduledDraftStatus.SENT

            self._audit.log(
                event_type=__import__(
                    "src.models.types", fromlist=["AuditEventType"]
                ).AuditEventType.EMAIL_SENT,
                session_id=draft.draft_id,  # use draft_id as session proxy
                description=(
                    f"Scheduled email sent to '{draft.recipient}' "
                    f"(subject: '{draft.subject}')"
                ),
                metadata={
                    "scheduled_draft_id": scheduled_draft_id,
                    "draft_id": draft.draft_id,
                    "recipient": draft.recipient,
                    "subject": draft.subject,
                    "sent_message_id": sent_id,
                    "trigger": "background_scheduler",
                },
            )
            logger.info(
                "Scheduled draft sent successfully id=%s sent_message_id=%s",
                scheduled_draft_id, sent_id,
            )

        except Exception as exc:
            # Revert to pending so it will be retried next cycle
            scheduled_draft.status = ScheduledDraftStatus.PENDING
            logger.error(
                "Failed to send scheduled draft id=%s: %s", scheduled_draft_id, exc
            )

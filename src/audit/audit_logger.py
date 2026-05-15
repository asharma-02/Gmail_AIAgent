"""
Append-only audit logger for the Secure AI Executive Assistant.

Design invariants:
- Entries are never modified or deleted after creation.
- Every entry must have a non-empty session_id and description.
- Timestamps are set automatically to UTC now at write time.
- Metadata values are silently truncated to 500 characters to prevent
  full email bodies from leaking into the audit log.
- query() always returns results in reverse-chronological order.
"""

from __future__ import annotations

from datetime import datetime, timezone

from src.models.types import AuditEntry, AuditEventType

# Maximum allowed length for any single metadata value.
_MAX_METADATA_VALUE_LENGTH = 500


class AuditLogger:
    """
    In-memory, append-only audit log.

    Thread-safety: not guaranteed — callers are responsible for
    external synchronisation if used from multiple threads.
    """

    def __init__(self) -> None:
        # Private list — no public method exposes a mutable reference.
        self._entries: list[AuditEntry] = []

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def log(
        self,
        event_type: AuditEventType,
        session_id: str,
        description: str,
        metadata: dict[str, str] | None = None,
    ) -> AuditEntry:
        """
        Append a new audit log entry and return it.

        Required fields
        ---------------
        - event_type  — must be a valid AuditEventType
        - session_id  — must be a non-empty string
        - description — must be a non-empty string
        - timestamp   — set automatically to UTC now

        Metadata
        --------
        Each metadata value is silently truncated to 500 characters so
        that full email bodies can never be stored in the audit log.

        Raises
        ------
        ValueError
            If session_id or description is empty.
        """
        if not session_id or not session_id.strip():
            raise ValueError("session_id must not be empty")
        if not description or not description.strip():
            raise ValueError("description must not be empty")

        # Sanitise metadata: truncate values that exceed the limit.
        safe_metadata: dict[str, str] = {}
        if metadata:
            for key, value in metadata.items():
                safe_metadata[key] = value[:_MAX_METADATA_VALUE_LENGTH]

        entry = AuditEntry(
            event_type=event_type,
            timestamp=datetime.now(tz=timezone.utc),
            session_id=session_id,
            description=description,
            metadata=safe_metadata,
        )

        # Append-only: we never modify existing entries.
        self._entries.append(entry)
        return entry

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def query(
        self,
        session_id: str | None = None,
        event_type: AuditEventType | None = None,
        limit: int | None = None,
    ) -> list[AuditEntry]:
        """
        Return audit entries in reverse-chronological order.

        Filters
        -------
        session_id  — if provided, only entries for that session are returned
        event_type  — if provided, only entries of that type are returned
        limit       — if provided, at most this many entries are returned
                      (the most recent N after filtering)

        Returns an empty list if no entries match.
        """
        results: list[AuditEntry] = list(self._entries)

        # Apply filters.
        if session_id is not None:
            results = [e for e in results if e.session_id == session_id]
        if event_type is not None:
            results = [e for e in results if e.event_type == event_type]

        # Sort descending by timestamp (most recent first).
        results.sort(key=lambda e: e.timestamp, reverse=True)

        # Apply limit.
        if limit is not None:
            results = results[:limit]

        return results

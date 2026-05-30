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

import json
from datetime import datetime, timezone

from src.models.types import AuditEntry, AuditEventType

# Maximum allowed length for any single metadata value.
_MAX_METADATA_VALUE_LENGTH = 500


class AuditLogger:
    """
    Append-only audit log — writes to both memory and SQLite.
    """

    def __init__(self) -> None:
        self._entries: list[AuditEntry] = []
        # Initialise DB (no-op if already exists)
        try:
            from src.db.database import init_db
            init_db()
        except Exception:
            pass

    def log(
        self,
        event_type: AuditEventType,
        session_id: str,
        description: str,
        metadata: dict[str, str] | None = None,
    ) -> AuditEntry:
        if not session_id or not session_id.strip():
            raise ValueError("session_id must not be empty")
        if not description or not description.strip():
            raise ValueError("description must not be empty")

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

        self._entries.append(entry)

        # Persist to SQLite
        try:
            from src.db.database import append_audit_entry
            append_audit_entry(
                entry_id=entry.entry_id,
                event_type=entry.event_type.value,
                timestamp=entry.timestamp,
                session_id=entry.session_id,
                description=entry.description,
                metadata=json.dumps(entry.metadata),
            )
        except Exception:
            pass  # never let DB errors break the audit flow

        return entry

    def query(
        self,
        session_id: str | None = None,
        event_type: AuditEventType | None = None,
        limit: int | None = None,
    ) -> list[AuditEntry]:
        """Query from SQLite so results survive restarts."""
        try:
            from src.db.database import query_audit_log
            rows = query_audit_log(
                session_id=session_id,
                event_type=event_type.value if event_type else None,
                limit=limit,
            )
            result = []
            for row in rows:
                result.append(AuditEntry(
                    entry_id=row["entry_id"],
                    event_type=AuditEventType(row["event_type"]),
                    timestamp=datetime.fromisoformat(row["timestamp"]),
                    session_id=row["session_id"],
                    description=row["description"],
                    metadata=json.loads(row["metadata"]),
                ))
            return result
        except Exception:
            # Fall back to in-memory
            results = list(self._entries)
            if session_id:
                results = [e for e in results if e.session_id == session_id]
            if event_type:
                results = [e for e in results if e.event_type == event_type]
            results.sort(key=lambda e: e.timestamp, reverse=True)
            if limit:
                results = results[:limit]
            return results


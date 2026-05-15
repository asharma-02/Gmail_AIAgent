"""
Unit tests for AuditLogger (Tasks 4.1 and 4.2).

Task 4.1 — Append-only audit log with required field enforcement:
- log() creates entry with correct event_type, session_id, description
- log() auto-sets timestamp to approximately utcnow
- log() returns the created AuditEntry
- log() raises ValueError for empty description
- log() raises ValueError for empty session_id
- log() truncates metadata values longer than 500 chars
- log() does not store full email bodies (metadata value > 500 chars is truncated)
- Entries are append-only — no public method removes or modifies entries
- All AuditEventType values can be logged without error

Task 4.2 — Reverse-chronological query with event-type filtering:
- query() with no filters returns all entries in reverse-chronological order
- query(session_id=...) returns only entries for that session
- query(event_type=...) returns only entries of that type
- query(session_id=..., event_type=...) applies both filters
- query(limit=N) returns at most N entries (most recent N)
- query() returns empty list when no entries exist
- query() returns empty list when no entries match filters
- Reverse-chronological order holds regardless of write order
- Entries with identical timestamps are still returned (no deduplication)
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

import pytest

from src.audit.audit_logger import AuditLogger, _MAX_METADATA_VALUE_LENGTH
from src.models.types import AuditEntry, AuditEventType


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SESSION_A = "session-aaa"
SESSION_B = "session-bbb"


def _log_entry(
    logger: AuditLogger,
    event_type: AuditEventType = AuditEventType.DRAFT_CREATED,
    session_id: str = SESSION_A,
    description: str = "test event",
    metadata: dict[str, str] | None = None,
) -> AuditEntry:
    return logger.log(
        event_type=event_type,
        session_id=session_id,
        description=description,
        metadata=metadata,
    )


# ---------------------------------------------------------------------------
# Task 4.1 — Core log() behaviour
# ---------------------------------------------------------------------------


class TestLogCreatesEntry:
    def test_returns_audit_entry_instance(self):
        logger = AuditLogger()
        entry = _log_entry(logger)
        assert isinstance(entry, AuditEntry)

    def test_entry_has_correct_event_type(self):
        logger = AuditLogger()
        entry = _log_entry(logger, event_type=AuditEventType.EMAIL_SENT)
        assert entry.event_type == AuditEventType.EMAIL_SENT

    def test_entry_has_correct_session_id(self):
        logger = AuditLogger()
        entry = _log_entry(logger, session_id=SESSION_A)
        assert entry.session_id == SESSION_A

    def test_entry_has_correct_description(self):
        logger = AuditLogger()
        entry = _log_entry(logger, description="email sent to alice@example.com")
        assert entry.description == "email sent to alice@example.com"

    def test_entry_is_stored_in_log(self):
        logger = AuditLogger()
        entry = _log_entry(logger)
        assert entry in logger._entries

    def test_multiple_entries_are_all_stored(self):
        logger = AuditLogger()
        e1 = _log_entry(logger, description="first")
        e2 = _log_entry(logger, description="second")
        e3 = _log_entry(logger, description="third")
        assert e1 in logger._entries
        assert e2 in logger._entries
        assert e3 in logger._entries
        assert len(logger._entries) == 3


class TestLogTimestamp:
    def test_timestamp_is_set_automatically(self):
        logger = AuditLogger()
        before = datetime.now(tz=timezone.utc)
        entry = _log_entry(logger)
        after = datetime.now(tz=timezone.utc)
        assert before <= entry.timestamp <= after

    def test_timestamp_is_timezone_aware(self):
        logger = AuditLogger()
        entry = _log_entry(logger)
        assert entry.timestamp.tzinfo is not None

    def test_timestamp_is_approximately_utcnow(self):
        logger = AuditLogger()
        entry = _log_entry(logger)
        delta = abs((datetime.now(tz=timezone.utc) - entry.timestamp).total_seconds())
        assert delta < 2.0  # within 2 seconds


class TestLogValidation:
    def test_raises_value_error_for_empty_description(self):
        logger = AuditLogger()
        with pytest.raises(ValueError, match="description"):
            logger.log(
                event_type=AuditEventType.DRAFT_CREATED,
                session_id=SESSION_A,
                description="",
            )

    def test_raises_value_error_for_whitespace_only_description(self):
        logger = AuditLogger()
        with pytest.raises(ValueError, match="description"):
            logger.log(
                event_type=AuditEventType.DRAFT_CREATED,
                session_id=SESSION_A,
                description="   ",
            )

    def test_raises_value_error_for_empty_session_id(self):
        logger = AuditLogger()
        with pytest.raises(ValueError, match="session_id"):
            logger.log(
                event_type=AuditEventType.DRAFT_CREATED,
                session_id="",
                description="some event",
            )

    def test_raises_value_error_for_whitespace_only_session_id(self):
        logger = AuditLogger()
        with pytest.raises(ValueError, match="session_id"):
            logger.log(
                event_type=AuditEventType.DRAFT_CREATED,
                session_id="   ",
                description="some event",
            )

    def test_no_entry_stored_when_validation_fails(self):
        logger = AuditLogger()
        with pytest.raises(ValueError):
            logger.log(
                event_type=AuditEventType.DRAFT_CREATED,
                session_id="",
                description="some event",
            )
        assert len(logger._entries) == 0


class TestLogMetadata:
    def test_metadata_stored_when_within_limit(self):
        logger = AuditLogger()
        meta = {"key": "short value"}
        entry = _log_entry(logger, metadata=meta)
        assert entry.metadata["key"] == "short value"

    def test_metadata_value_truncated_at_500_chars(self):
        logger = AuditLogger()
        long_value = "x" * 600
        entry = _log_entry(logger, metadata={"body": long_value})
        assert len(entry.metadata["body"]) == _MAX_METADATA_VALUE_LENGTH
        assert entry.metadata["body"] == "x" * _MAX_METADATA_VALUE_LENGTH

    def test_metadata_value_exactly_500_chars_not_truncated(self):
        logger = AuditLogger()
        exact_value = "a" * 500
        entry = _log_entry(logger, metadata={"key": exact_value})
        assert len(entry.metadata["key"]) == 500

    def test_full_email_body_is_truncated(self):
        """Full email bodies (> 500 chars) must not be stored in metadata."""
        logger = AuditLogger()
        full_body = "Dear Alice,\n" + ("This is a very long email body. " * 30)
        assert len(full_body) > 500
        entry = _log_entry(logger, metadata={"email_body": full_body})
        assert len(entry.metadata["email_body"]) == _MAX_METADATA_VALUE_LENGTH

    def test_multiple_metadata_keys_all_truncated_independently(self):
        logger = AuditLogger()
        meta = {
            "short": "ok",
            "long1": "a" * 600,
            "long2": "b" * 700,
        }
        entry = _log_entry(logger, metadata=meta)
        assert entry.metadata["short"] == "ok"
        assert len(entry.metadata["long1"]) == 500
        assert len(entry.metadata["long2"]) == 500

    def test_none_metadata_results_in_empty_dict(self):
        logger = AuditLogger()
        entry = _log_entry(logger, metadata=None)
        assert entry.metadata == {}


class TestLogAllEventTypes:
    @pytest.mark.parametrize("event_type", list(AuditEventType))
    def test_all_event_types_can_be_logged(self, event_type: AuditEventType):
        logger = AuditLogger()
        entry = logger.log(
            event_type=event_type,
            session_id=SESSION_A,
            description=f"test {event_type.value}",
        )
        assert entry.event_type == event_type


class TestAppendOnlyInvariant:
    def test_no_public_method_deletes_entries(self):
        """AuditLogger must expose no public method that removes entries."""
        logger = AuditLogger()
        _log_entry(logger, description="entry 1")
        _log_entry(logger, description="entry 2")

        public_methods = [
            name for name in dir(logger)
            if not name.startswith("_") and callable(getattr(logger, name))
        ]
        # Allowed public methods: log, query
        for method_name in public_methods:
            assert method_name in ("log", "query"), (
                f"Unexpected public method '{method_name}' found on AuditLogger — "
                "it could allow modification or deletion of entries."
            )

    def test_entries_list_grows_monotonically(self):
        logger = AuditLogger()
        for i in range(5):
            _log_entry(logger, description=f"event {i}")
            assert len(logger._entries) == i + 1

    def test_existing_entries_unchanged_after_new_log(self):
        logger = AuditLogger()
        first = _log_entry(logger, description="first entry")
        first_id = first.entry_id
        first_desc = first.description

        _log_entry(logger, description="second entry")

        # The first entry must be unchanged.
        stored_first = logger._entries[0]
        assert stored_first.entry_id == first_id
        assert stored_first.description == first_desc

    def test_query_returns_copies_not_mutable_references(self):
        """Modifying the query result list must not affect the internal store."""
        logger = AuditLogger()
        _log_entry(logger, description="entry 1")
        results = logger.query()
        results.clear()
        # Internal store must be unaffected.
        assert len(logger._entries) == 1


# ---------------------------------------------------------------------------
# Task 4.2 — query() behaviour
# ---------------------------------------------------------------------------


class TestQueryNoFilters:
    def test_returns_empty_list_when_no_entries(self):
        logger = AuditLogger()
        assert logger.query() == []

    def test_returns_all_entries(self):
        logger = AuditLogger()
        for i in range(5):
            _log_entry(logger, description=f"event {i}")
        results = logger.query()
        assert len(results) == 5

    def test_returns_entries_in_reverse_chronological_order(self):
        logger = AuditLogger()
        # Write entries with small sleeps to ensure distinct timestamps.
        for i in range(3):
            _log_entry(logger, description=f"event {i}")
            time.sleep(0.01)
        results = logger.query()
        timestamps = [e.timestamp for e in results]
        assert timestamps == sorted(timestamps, reverse=True)

    def test_single_entry_returned_correctly(self):
        logger = AuditLogger()
        entry = _log_entry(logger, description="only entry")
        results = logger.query()
        assert len(results) == 1
        assert results[0].entry_id == entry.entry_id


class TestQueryReverseChronologicalOrder:
    def test_order_holds_regardless_of_write_order(self):
        """
        Entries written with manually-set timestamps in non-chronological order
        must still be returned most-recent-first.
        """
        logger = AuditLogger()
        # Write three entries; they'll get auto-timestamps in write order.
        # We then verify the query result is sorted by timestamp descending.
        e1 = _log_entry(logger, description="first written")
        time.sleep(0.01)
        e2 = _log_entry(logger, description="second written")
        time.sleep(0.01)
        e3 = _log_entry(logger, description="third written")

        results = logger.query()
        # Most recent (e3) should be first.
        assert results[0].entry_id == e3.entry_id
        assert results[1].entry_id == e2.entry_id
        assert results[2].entry_id == e1.entry_id

    def test_entries_with_identical_timestamps_all_returned(self):
        """No deduplication — entries with the same timestamp must all appear."""
        logger = AuditLogger()
        # Inject entries with the same timestamp directly to test dedup behaviour.
        fixed_ts = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        for i in range(3):
            entry = AuditEntry(
                event_type=AuditEventType.DRAFT_CREATED,
                timestamp=fixed_ts,
                session_id=SESSION_A,
                description=f"duplicate-ts event {i}",
            )
            logger._entries.append(entry)

        results = logger.query()
        assert len(results) == 3


class TestQuerySessionFilter:
    def test_returns_only_entries_for_given_session(self):
        logger = AuditLogger()
        _log_entry(logger, session_id=SESSION_A, description="a1")
        _log_entry(logger, session_id=SESSION_B, description="b1")
        _log_entry(logger, session_id=SESSION_A, description="a2")

        results = logger.query(session_id=SESSION_A)
        assert all(e.session_id == SESSION_A for e in results)
        assert len(results) == 2

    def test_returns_empty_list_when_session_has_no_entries(self):
        logger = AuditLogger()
        _log_entry(logger, session_id=SESSION_A, description="a1")
        results = logger.query(session_id="nonexistent-session")
        assert results == []

    def test_session_filter_preserves_reverse_chronological_order(self):
        logger = AuditLogger()
        for i in range(3):
            _log_entry(logger, session_id=SESSION_A, description=f"a{i}")
            time.sleep(0.01)
        results = logger.query(session_id=SESSION_A)
        timestamps = [e.timestamp for e in results]
        assert timestamps == sorted(timestamps, reverse=True)


class TestQueryEventTypeFilter:
    def test_returns_only_entries_of_given_event_type(self):
        logger = AuditLogger()
        _log_entry(logger, event_type=AuditEventType.DRAFT_CREATED, description="d1")
        _log_entry(logger, event_type=AuditEventType.EMAIL_SENT, description="s1")
        _log_entry(logger, event_type=AuditEventType.DRAFT_CREATED, description="d2")

        results = logger.query(event_type=AuditEventType.DRAFT_CREATED)
        assert all(e.event_type == AuditEventType.DRAFT_CREATED for e in results)
        assert len(results) == 2

    def test_returns_empty_list_when_no_entries_of_type(self):
        logger = AuditLogger()
        _log_entry(logger, event_type=AuditEventType.DRAFT_CREATED, description="d1")
        results = logger.query(event_type=AuditEventType.EMAIL_DELETED)
        assert results == []

    def test_event_type_filter_preserves_reverse_chronological_order(self):
        logger = AuditLogger()
        for i in range(3):
            _log_entry(
                logger,
                event_type=AuditEventType.EMAIL_SENT,
                description=f"sent {i}",
            )
            time.sleep(0.01)
        results = logger.query(event_type=AuditEventType.EMAIL_SENT)
        timestamps = [e.timestamp for e in results]
        assert timestamps == sorted(timestamps, reverse=True)


class TestQueryCombinedFilters:
    def test_session_and_event_type_filters_applied_together(self):
        logger = AuditLogger()
        _log_entry(
            logger,
            session_id=SESSION_A,
            event_type=AuditEventType.DRAFT_CREATED,
            description="a-draft",
        )
        _log_entry(
            logger,
            session_id=SESSION_A,
            event_type=AuditEventType.EMAIL_SENT,
            description="a-sent",
        )
        _log_entry(
            logger,
            session_id=SESSION_B,
            event_type=AuditEventType.DRAFT_CREATED,
            description="b-draft",
        )

        results = logger.query(
            session_id=SESSION_A,
            event_type=AuditEventType.DRAFT_CREATED,
        )
        assert len(results) == 1
        assert results[0].session_id == SESSION_A
        assert results[0].event_type == AuditEventType.DRAFT_CREATED

    def test_combined_filters_return_empty_when_no_match(self):
        logger = AuditLogger()
        _log_entry(
            logger,
            session_id=SESSION_A,
            event_type=AuditEventType.DRAFT_CREATED,
            description="a-draft",
        )
        results = logger.query(
            session_id=SESSION_B,
            event_type=AuditEventType.DRAFT_CREATED,
        )
        assert results == []


class TestQueryLimit:
    def test_limit_caps_number_of_results(self):
        logger = AuditLogger()
        for i in range(10):
            _log_entry(logger, description=f"event {i}")
        results = logger.query(limit=3)
        assert len(results) == 3

    def test_limit_returns_most_recent_entries(self):
        logger = AuditLogger()
        for i in range(5):
            _log_entry(logger, description=f"event {i}")
            time.sleep(0.01)
        results = logger.query(limit=2)
        # Should be the 2 most recent entries.
        all_results = logger.query()
        assert results[0].entry_id == all_results[0].entry_id
        assert results[1].entry_id == all_results[1].entry_id

    def test_limit_larger_than_total_returns_all(self):
        logger = AuditLogger()
        for i in range(3):
            _log_entry(logger, description=f"event {i}")
        results = logger.query(limit=100)
        assert len(results) == 3

    def test_limit_of_zero_returns_empty_list(self):
        logger = AuditLogger()
        _log_entry(logger, description="event 1")
        results = logger.query(limit=0)
        assert results == []

    def test_limit_with_session_filter(self):
        logger = AuditLogger()
        for i in range(5):
            _log_entry(logger, session_id=SESSION_A, description=f"a{i}")
            time.sleep(0.01)
        _log_entry(logger, session_id=SESSION_B, description="b1")
        results = logger.query(session_id=SESSION_A, limit=2)
        assert len(results) == 2
        assert all(e.session_id == SESSION_A for e in results)

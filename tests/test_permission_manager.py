"""
Unit tests for PermissionManager (Tasks 3.1 and 3.2).

Covers:
- request_permission stores grant and logs PERMISSION_GRANTED
- check_permission returns True for valid grant, False for missing grant
- check_permission returns False for expired grant (expires_at in the past)
- check_permission returns True for session-scoped grant (expires_at=None)
- revoke_permission removes grant and logs PERMISSION_REVOKED
- revoke_permission clears cached data for the revoked scope
- list_active_permissions returns only non-expired grants
- store_cached_data and get_cached_data round-trip
- get_cached_data returns None after revocation
- clear_session removes all grants and cache for the session
- revoke_all_permissions removes all grants and cache
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.models.types import AuditEventType, GmailScope, PermissionScope
from src.permissions import PermissionDeniedError, PermissionManager


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _gmail_scope(
    gmail_scope: GmailScope | None = GmailScope.READONLY,
    justification: str = "test",
) -> PermissionScope:
    return PermissionScope(
        data_source="gmail",
        gmail_scope=gmail_scope,
        justification=justification,
    )


def _meeting_scope(justification: str = "test") -> PermissionScope:
    return PermissionScope(
        data_source="meeting_notes",
        gmail_scope=None,
        justification=justification,
    )


SESSION = "session-abc"
OTHER_SESSION = "session-xyz"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def manager() -> PermissionManager:
    return PermissionManager()


# ---------------------------------------------------------------------------
# request_permission
# ---------------------------------------------------------------------------


class TestRequestPermission:
    def test_stores_grant_for_session(self, manager):
        grant = manager.request_permission(SESSION, _gmail_scope())
        assert grant in manager._grants[SESSION]

    def test_returns_permission_grant(self, manager):
        from src.models.types import PermissionGrant

        grant = manager.request_permission(SESSION, _gmail_scope())
        assert isinstance(grant, PermissionGrant)

    def test_grant_has_correct_scope(self, manager):
        scope = _gmail_scope()
        grant = manager.request_permission(SESSION, scope)
        assert grant.scope == scope

    def test_grant_is_session_scoped_by_default(self, manager):
        """expires_at=None means session-scoped."""
        grant = manager.request_permission(SESSION, _gmail_scope())
        assert grant.expires_at is None

    def test_logs_permission_granted_event(self, manager):
        manager.request_permission(SESSION, _gmail_scope())
        events = [e.event_type for e in manager._audit_log]
        assert AuditEventType.PERMISSION_GRANTED in events

    def test_audit_entry_contains_session_id(self, manager):
        manager.request_permission(SESSION, _gmail_scope())
        entry = manager._audit_log[-1]
        assert entry.session_id == SESSION

    def test_multiple_grants_accumulate(self, manager):
        manager.request_permission(SESSION, _gmail_scope(GmailScope.READONLY))
        manager.request_permission(SESSION, _gmail_scope(GmailScope.SEND))
        assert len(manager._grants[SESSION]) == 2

    def test_does_not_expand_scope(self, manager):
        """Minimum-scope enforcement: grant stores exactly the requested scope."""
        scope = _gmail_scope(GmailScope.READONLY)
        grant = manager.request_permission(SESSION, scope)
        assert grant.scope.gmail_scope == GmailScope.READONLY

    def test_grants_are_isolated_per_session(self, manager):
        manager.request_permission(SESSION, _gmail_scope())
        assert OTHER_SESSION not in manager._grants


# ---------------------------------------------------------------------------
# check_permission
# ---------------------------------------------------------------------------


class TestCheckPermission:
    def test_returns_true_for_valid_grant(self, manager):
        scope = _gmail_scope()
        manager.request_permission(SESSION, scope)
        assert manager.check_permission(SESSION, scope) is True

    def test_returns_false_for_missing_grant(self, manager):
        assert manager.check_permission(SESSION, _gmail_scope()) is False

    def test_returns_false_for_different_session(self, manager):
        scope = _gmail_scope()
        manager.request_permission(SESSION, scope)
        assert manager.check_permission(OTHER_SESSION, scope) is False

    def test_returns_false_for_expired_grant(self, manager):
        scope = _gmail_scope()
        grant = manager.request_permission(SESSION, scope)
        # Force expiry
        grant.expires_at = datetime.now(tz=timezone.utc) - timedelta(seconds=1)
        assert manager.check_permission(SESSION, scope) is False

    def test_returns_true_for_session_scoped_grant(self, manager):
        """expires_at=None means always valid until session ends."""
        scope = _gmail_scope()
        grant = manager.request_permission(SESSION, scope)
        assert grant.expires_at is None
        assert manager.check_permission(SESSION, scope) is True

    def test_returns_true_for_future_expiry(self, manager):
        scope = _gmail_scope()
        grant = manager.request_permission(SESSION, scope)
        grant.expires_at = datetime.now(tz=timezone.utc) + timedelta(hours=1)
        assert manager.check_permission(SESSION, scope) is True

    def test_returns_false_for_different_data_source(self, manager):
        manager.request_permission(SESSION, _gmail_scope())
        assert manager.check_permission(SESSION, _meeting_scope()) is False

    def test_returns_false_for_different_gmail_scope(self, manager):
        manager.request_permission(SESSION, _gmail_scope(GmailScope.READONLY))
        assert manager.check_permission(SESSION, _gmail_scope(GmailScope.SEND)) is False

    def test_broad_grant_covers_specific_request(self, manager):
        """A grant with gmail_scope=None covers any gmail_scope request."""
        broad_scope = _gmail_scope(gmail_scope=None)
        manager.request_permission(SESSION, broad_scope)
        assert manager.check_permission(SESSION, _gmail_scope(GmailScope.READONLY)) is True
        assert manager.check_permission(SESSION, _gmail_scope(GmailScope.SEND)) is True

    def test_specific_grant_covers_no_gmail_scope_request(self, manager):
        """A grant with a specific gmail_scope covers a request with no gmail_scope."""
        manager.request_permission(SESSION, _gmail_scope(GmailScope.READONLY))
        no_scope_request = PermissionScope(
            data_source="gmail",
            gmail_scope=None,
            justification="test",
        )
        assert manager.check_permission(SESSION, no_scope_request) is True

    def test_returns_true_for_meeting_notes_grant(self, manager):
        scope = _meeting_scope()
        manager.request_permission(SESSION, scope)
        assert manager.check_permission(SESSION, scope) is True


# ---------------------------------------------------------------------------
# revoke_permission
# ---------------------------------------------------------------------------


class TestRevokePermission:
    def test_removes_grant_from_session(self, manager):
        scope = _gmail_scope()
        manager.request_permission(SESSION, scope)
        manager.revoke_permission(SESSION, scope)
        assert manager.check_permission(SESSION, scope) is False

    def test_logs_permission_revoked_event(self, manager):
        scope = _gmail_scope()
        manager.request_permission(SESSION, scope)
        manager.revoke_permission(SESSION, scope)
        events = [e.event_type for e in manager._audit_log]
        assert AuditEventType.PERMISSION_REVOKED in events

    def test_audit_entry_contains_session_id(self, manager):
        scope = _gmail_scope()
        manager.request_permission(SESSION, scope)
        manager.revoke_permission(SESSION, scope)
        revoke_entries = [
            e for e in manager._audit_log
            if e.event_type == AuditEventType.PERMISSION_REVOKED
        ]
        assert revoke_entries[-1].session_id == SESSION

    def test_clears_cached_data_for_revoked_scope(self, manager):
        scope = _gmail_scope()
        manager.request_permission(SESSION, scope)
        manager.store_cached_data(SESSION, "gmail:thread_1", {"body": "hello"})
        manager.revoke_permission(SESSION, scope)
        assert manager.get_cached_data(SESSION, "gmail:thread_1") is None

    def test_clears_all_cached_data_for_data_source(self, manager):
        """All cache entries with the same data_source prefix are cleared."""
        scope = _gmail_scope()
        manager.request_permission(SESSION, scope)
        manager.store_cached_data(SESSION, "gmail:thread_1", "data1")
        manager.store_cached_data(SESSION, "gmail:thread_2", "data2")
        manager.store_cached_data(SESSION, "meeting_notes:meeting_1", "notes")
        manager.revoke_permission(SESSION, scope)
        assert manager.get_cached_data(SESSION, "gmail:thread_1") is None
        assert manager.get_cached_data(SESSION, "gmail:thread_2") is None
        # Meeting notes cache should be unaffected
        assert manager.get_cached_data(SESSION, "meeting_notes:meeting_1") == "notes"

    def test_does_not_affect_other_sessions(self, manager):
        scope = _gmail_scope()
        manager.request_permission(SESSION, scope)
        manager.request_permission(OTHER_SESSION, scope)
        manager.revoke_permission(SESSION, scope)
        assert manager.check_permission(OTHER_SESSION, scope) is True

    def test_revoke_on_session_with_no_grants_does_not_raise(self, manager):
        """Revoking a non-existent grant should be a no-op."""
        manager.revoke_permission(SESSION, _gmail_scope())  # should not raise

    def test_removes_all_matching_grants(self, manager):
        """Multiple grants for the same scope should all be removed."""
        scope = _gmail_scope()
        manager.request_permission(SESSION, scope)
        manager.request_permission(SESSION, scope)
        assert len(manager._grants[SESSION]) == 2
        manager.revoke_permission(SESSION, scope)
        assert manager.check_permission(SESSION, scope) is False
        assert len(manager._grants.get(SESSION, [])) == 0


# ---------------------------------------------------------------------------
# list_active_permissions
# ---------------------------------------------------------------------------


class TestListActivePermissions:
    def test_returns_empty_list_for_unknown_session(self, manager):
        assert manager.list_active_permissions(SESSION) == []

    def test_returns_all_valid_grants(self, manager):
        manager.request_permission(SESSION, _gmail_scope(GmailScope.READONLY))
        manager.request_permission(SESSION, _gmail_scope(GmailScope.SEND))
        active = manager.list_active_permissions(SESSION)
        assert len(active) == 2

    def test_excludes_expired_grants(self, manager):
        scope_valid = _gmail_scope(GmailScope.READONLY)
        scope_expired = _gmail_scope(GmailScope.SEND)
        manager.request_permission(SESSION, scope_valid)
        expired_grant = manager.request_permission(SESSION, scope_expired)
        expired_grant.expires_at = datetime.now(tz=timezone.utc) - timedelta(seconds=1)

        active = manager.list_active_permissions(SESSION)
        assert len(active) == 1
        assert active[0].scope == scope_valid

    def test_includes_session_scoped_grants(self, manager):
        """expires_at=None grants must appear in the active list."""
        scope = _gmail_scope()
        grant = manager.request_permission(SESSION, scope)
        assert grant.expires_at is None
        active = manager.list_active_permissions(SESSION)
        assert grant in active

    def test_returns_only_grants_for_requested_session(self, manager):
        manager.request_permission(SESSION, _gmail_scope())
        manager.request_permission(OTHER_SESSION, _gmail_scope())
        active = manager.list_active_permissions(SESSION)
        assert len(active) == 1


# ---------------------------------------------------------------------------
# store_cached_data / get_cached_data
# ---------------------------------------------------------------------------


class TestCacheRoundTrip:
    def test_stored_data_is_retrievable(self, manager):
        data = {"emails": ["email1", "email2"]}
        manager.store_cached_data(SESSION, "gmail:thread_1", data)
        assert manager.get_cached_data(SESSION, "gmail:thread_1") == data

    def test_returns_none_for_missing_key(self, manager):
        assert manager.get_cached_data(SESSION, "gmail:nonexistent") is None

    def test_returns_none_for_unknown_session(self, manager):
        assert manager.get_cached_data("unknown-session", "gmail:thread_1") is None

    def test_overwrites_existing_cached_data(self, manager):
        manager.store_cached_data(SESSION, "gmail:thread_1", "old")
        manager.store_cached_data(SESSION, "gmail:thread_1", "new")
        assert manager.get_cached_data(SESSION, "gmail:thread_1") == "new"

    def test_cache_is_isolated_per_session(self, manager):
        manager.store_cached_data(SESSION, "gmail:thread_1", "session_data")
        assert manager.get_cached_data(OTHER_SESSION, "gmail:thread_1") is None

    def test_get_cached_data_returns_none_after_revocation(self, manager):
        scope = _gmail_scope()
        manager.request_permission(SESSION, scope)
        manager.store_cached_data(SESSION, "gmail:thread_1", "data")
        manager.revoke_permission(SESSION, scope)
        assert manager.get_cached_data(SESSION, "gmail:thread_1") is None

    def test_stores_various_data_types(self, manager):
        manager.store_cached_data(SESSION, "gmail:list", [1, 2, 3])
        manager.store_cached_data(SESSION, "gmail:str", "hello")
        manager.store_cached_data(SESSION, "gmail:num", 42)
        assert manager.get_cached_data(SESSION, "gmail:list") == [1, 2, 3]
        assert manager.get_cached_data(SESSION, "gmail:str") == "hello"
        assert manager.get_cached_data(SESSION, "gmail:num") == 42


# ---------------------------------------------------------------------------
# clear_session
# ---------------------------------------------------------------------------


class TestClearSession:
    def test_removes_all_grants_for_session(self, manager):
        manager.request_permission(SESSION, _gmail_scope(GmailScope.READONLY))
        manager.request_permission(SESSION, _gmail_scope(GmailScope.SEND))
        manager.clear_session(SESSION)
        assert manager._grants.get(SESSION, []) == []

    def test_removes_all_cached_data_for_session(self, manager):
        manager.store_cached_data(SESSION, "gmail:thread_1", "data1")
        manager.store_cached_data(SESSION, "meeting_notes:m1", "notes")
        manager.clear_session(SESSION)
        assert manager.get_cached_data(SESSION, "gmail:thread_1") is None
        assert manager.get_cached_data(SESSION, "meeting_notes:m1") is None

    def test_does_not_affect_other_sessions(self, manager):
        manager.request_permission(SESSION, _gmail_scope())
        manager.request_permission(OTHER_SESSION, _gmail_scope())
        manager.store_cached_data(OTHER_SESSION, "gmail:thread_1", "data")
        manager.clear_session(SESSION)
        assert manager.check_permission(OTHER_SESSION, _gmail_scope()) is True
        assert manager.get_cached_data(OTHER_SESSION, "gmail:thread_1") == "data"

    def test_clear_unknown_session_does_not_raise(self, manager):
        manager.clear_session("nonexistent-session")  # should not raise

    def test_check_permission_returns_false_after_clear(self, manager):
        scope = _gmail_scope()
        manager.request_permission(SESSION, scope)
        manager.clear_session(SESSION)
        assert manager.check_permission(SESSION, scope) is False


# ---------------------------------------------------------------------------
# revoke_all_permissions
# ---------------------------------------------------------------------------


class TestRevokeAllPermissions:
    def test_removes_all_grants(self, manager):
        manager.request_permission(SESSION, _gmail_scope(GmailScope.READONLY))
        manager.request_permission(SESSION, _gmail_scope(GmailScope.SEND))
        manager.request_permission(SESSION, _meeting_scope())
        manager.revoke_all_permissions(SESSION)
        assert manager.list_active_permissions(SESSION) == []

    def test_removes_all_cached_data(self, manager):
        manager.store_cached_data(SESSION, "gmail:thread_1", "data1")
        manager.store_cached_data(SESSION, "meeting_notes:m1", "notes")
        manager.revoke_all_permissions(SESSION)
        assert manager.get_cached_data(SESSION, "gmail:thread_1") is None
        assert manager.get_cached_data(SESSION, "meeting_notes:m1") is None

    def test_does_not_affect_other_sessions(self, manager):
        manager.request_permission(SESSION, _gmail_scope())
        manager.request_permission(OTHER_SESSION, _gmail_scope())
        manager.store_cached_data(OTHER_SESSION, "gmail:thread_1", "data")
        manager.revoke_all_permissions(SESSION)
        assert manager.check_permission(OTHER_SESSION, _gmail_scope()) is True
        assert manager.get_cached_data(OTHER_SESSION, "gmail:thread_1") == "data"

    def test_revoke_all_on_unknown_session_does_not_raise(self, manager):
        manager.revoke_all_permissions("nonexistent-session")  # should not raise

    def test_check_permission_returns_false_after_revoke_all(self, manager):
        scope = _gmail_scope()
        manager.request_permission(SESSION, scope)
        manager.revoke_all_permissions(SESSION)
        assert manager.check_permission(SESSION, scope) is False

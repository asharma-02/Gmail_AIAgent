"""
Permission Manager for the Secure AI Executive Assistant.

Responsibilities:
- Track granted permissions per session
- Enforce minimum-scope access for each request
- Handle permission revocation and cache invalidation
- Log PERMISSION_GRANTED and PERMISSION_REVOKED audit events

Trust note: this module is part of the trusted Agent Core. It enforces the
permission model — no data source is accessed without an explicit user grant.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from src.models.types import (
    AuditEntry,
    AuditEventType,
    PermissionGrant,
    PermissionScope,
)

# Avoid circular import — AuditLogger is imported lazily via TYPE_CHECKING
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.audit.audit_logger import AuditLogger

logger = logging.getLogger(__name__)


class PermissionManager:
    """
    Manages per-session permission grants and a permission-scoped data cache.

    Parameters
    ----------
    None — all state is held in-memory, keyed by session_id.
    """

    def __init__(self, audit_logger: "AuditLogger | None" = None) -> None:
        # Granted permissions, keyed by session_id → list of PermissionGrant
        self._grants: dict[str, list[PermissionGrant]] = {}
        # Permission-scoped data cache, keyed by session_id → {scope_key: data}
        self._cache: dict[str, dict[str, Any]] = {}
        # Audit log (in-memory; will be replaced by AuditLogger in later tasks)
        self._audit_log: list[AuditEntry] = []
        # Real AuditLogger (optional injection)
        self._audit_logger = audit_logger

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _now(self) -> datetime:
        """Return the current UTC time (timezone-aware)."""
        return datetime.now(tz=timezone.utc)

    def _log_audit(
        self,
        event_type: AuditEventType,
        session_id: str,
        description: str,
        metadata: dict[str, str] | None = None,
    ) -> None:
        entry = AuditEntry(
            event_type=event_type,
            timestamp=self._now(),
            session_id=session_id,
            description=description,
            metadata=metadata or {},
        )
        self._audit_log.append(entry)
        logger.info(
            "AUDIT %s | session=%s | %s",
            event_type.value,
            session_id,
            description,
        )
        # Also emit to the real AuditLogger if one was injected
        if self._audit_logger is not None:
            try:
                self._audit_logger.log(
                    event_type=event_type,
                    session_id=session_id,
                    description=description,
                    metadata=metadata,
                )
            except Exception:
                pass  # never let audit logging break permission operations

    def _scopes_match(self, grant_scope: PermissionScope, requested: PermissionScope) -> bool:
        """
        Return True if *grant_scope* covers *requested*.

        Matching rules:
        - data_source must be equal.
        - If the grant has gmail_scope=None, it matches any gmail_scope for
          the same data_source (broader grant covers narrower request).
        - If both have gmail_scope set, they must be equal.
        - If the request has gmail_scope=None but the grant has one set,
          the grant still covers the request (the request is less specific).
        """
        if grant_scope.data_source != requested.data_source:
            return False

        # Grant with no gmail_scope covers any gmail_scope request
        if grant_scope.gmail_scope is None:
            return True

        # Grant has a specific gmail_scope; request must match exactly
        # (or request has no gmail_scope, meaning it doesn't need one)
        if requested.gmail_scope is None:
            return True

        return grant_scope.gmail_scope == requested.gmail_scope

    def _is_grant_valid(self, grant: PermissionGrant) -> bool:
        """Return True if the grant has not expired."""
        if grant.expires_at is None:
            # Session-scoped — always valid until session ends
            return True
        expires_at = grant.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        return self._now() <= expires_at

    # ------------------------------------------------------------------
    # Task 3.1 — Permission grant, check, revoke, and list operations
    # ------------------------------------------------------------------

    def request_permission(
        self,
        session_id: str,
        scope: PermissionScope,
    ) -> PermissionGrant:
        """
        Record that the user has explicitly granted a permission.

        Stores the grant with the exact scope provided (minimum-scope
        enforcement — no expansion). Logs a PERMISSION_GRANTED audit event.

        Parameters
        ----------
        session_id:
            The session for which permission is being granted.
        scope:
            The exact scope being granted.

        Returns
        -------
        PermissionGrant
            The newly created grant.
        """
        grant = PermissionGrant(
            scope=scope,
            granted_at=self._now(),
            expires_at=None,  # session-scoped by default
        )

        if session_id not in self._grants:
            self._grants[session_id] = []
        self._grants[session_id].append(grant)

        self._log_audit(
            AuditEventType.PERMISSION_GRANTED,
            session_id=session_id,
            description=(
                f"Permission granted for data_source={scope.data_source}"
                + (f", gmail_scope={scope.gmail_scope}" if scope.gmail_scope else "")
            ),
            metadata={
                "data_source": scope.data_source,
                "gmail_scope": scope.gmail_scope.value if scope.gmail_scope else "",
                "justification": scope.justification,
            },
        )
        return grant

    def check_permission(
        self,
        session_id: str,
        scope: PermissionScope,
    ) -> bool:
        """
        Return True if a valid, unexpired grant exists for this scope.

        A grant is valid if:
        - It exists for the session_id.
        - Its data_source matches.
        - Its gmail_scope matches (if applicable — see _scopes_match).
        - It has not expired (expires_at is None = session-scoped = always
          valid until session ends; or expires_at > utcnow()).

        Parameters
        ----------
        session_id:
            The session to check.
        scope:
            The scope being requested.

        Returns
        -------
        bool
            True if a valid grant covers the requested scope.
        """
        grants = self._grants.get(session_id, [])
        for grant in grants:
            if self._scopes_match(grant.scope, scope) and self._is_grant_valid(grant):
                return True
        return False

    def revoke_permission(
        self,
        session_id: str,
        scope: PermissionScope,
    ) -> None:
        """
        Remove all grants for this scope from the session and clear cached data.

        - Removes ALL grants whose scope matches (data_source + gmail_scope).
        - Clears ALL cached data entries whose scope_key starts with
          ``f"{data_source}:"`` — purges all cached data from that source.
        - Logs a PERMISSION_REVOKED audit event.

        Parameters
        ----------
        session_id:
            The session from which to revoke the permission.
        scope:
            The scope to revoke.
        """
        # Remove matching grants
        existing = self._grants.get(session_id, [])
        self._grants[session_id] = [
            g for g in existing if not self._scopes_match(g.scope, scope)
        ]

        # Clear all cached data for this data_source
        cache_prefix = f"{scope.data_source}:"
        session_cache = self._cache.get(session_id, {})
        keys_to_remove = [k for k in session_cache if k.startswith(cache_prefix)]
        for key in keys_to_remove:
            del session_cache[key]

        self._log_audit(
            AuditEventType.PERMISSION_REVOKED,
            session_id=session_id,
            description=(
                f"Permission revoked for data_source={scope.data_source}"
                + (f", gmail_scope={scope.gmail_scope}" if scope.gmail_scope else "")
            ),
            metadata={
                "data_source": scope.data_source,
                "gmail_scope": scope.gmail_scope.value if scope.gmail_scope else "",
            },
        )

    def list_active_permissions(self, session_id: str) -> list[PermissionGrant]:
        """
        Return all currently valid (non-expired) grants for the session.

        Parameters
        ----------
        session_id:
            The session whose active permissions to list.

        Returns
        -------
        list[PermissionGrant]
            All non-expired grants for the session.
        """
        grants = self._grants.get(session_id, [])
        return [g for g in grants if self._is_grant_valid(g)]

    # ------------------------------------------------------------------
    # Task 3.1 — Permission-scoped data cache
    # ------------------------------------------------------------------

    def store_cached_data(
        self,
        session_id: str,
        scope_key: str,
        data: Any,
    ) -> None:
        """
        Store retrieved data in the permission-scoped cache.

        Parameters
        ----------
        session_id:
            The session owning this cached data.
        scope_key:
            A key identifying the scope and resource, e.g. ``"gmail:thread_123"``.
        data:
            The data to cache.
        """
        if session_id not in self._cache:
            self._cache[session_id] = {}
        self._cache[session_id][scope_key] = data

    def get_cached_data(
        self,
        session_id: str,
        scope_key: str,
    ) -> Any | None:
        """
        Retrieve cached data for a scope, or None if not present.

        Parameters
        ----------
        session_id:
            The session owning the cached data.
        scope_key:
            The key used when the data was stored.

        Returns
        -------
        Any | None
            The cached data, or None if not found.
        """
        return self._cache.get(session_id, {}).get(scope_key)

    # ------------------------------------------------------------------
    # Task 3.2 — Session cleanup and bulk revocation
    # ------------------------------------------------------------------

    def revoke_all_permissions(self, session_id: str) -> None:
        """
        Revoke all permissions for a session and clear all cached data.

        Parameters
        ----------
        session_id:
            The session whose permissions and cache to clear.
        """
        self._grants.pop(session_id, None)
        self._cache.pop(session_id, None)

    def clear_session(self, session_id: str) -> None:
        """
        Remove all grants and cached data for a session (called on session end).

        Parameters
        ----------
        session_id:
            The session to clear.
        """
        self._grants.pop(session_id, None)
        self._cache.pop(session_id, None)

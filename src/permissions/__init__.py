"""
Permissions package for the Secure AI Executive Assistant.

Public exports:
- PermissionManager    — per-session permission grant, check, revoke, and cache
- PermissionDeniedError — raised when a required permission has not been granted
"""

from src.permissions.errors import PermissionDeniedError
from src.permissions.permission_manager import PermissionManager

__all__ = [
    "PermissionManager",
    "PermissionDeniedError",
]

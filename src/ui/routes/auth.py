"""
Authentication routes — login, logout, registration, session status.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from src.auth.errors import AuthError
from src.ui.state import session_manager, audit_logger
from src.models.types import AuditEventType

router = APIRouter()


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------


class LoginRequest(BaseModel):
    user_id: str
    password: str


class RegisterRequest(BaseModel):
    user_id: str
    password: str


class LoginResponse(BaseModel):
    session_id: str
    user_id: str
    message: str


class SessionStatusResponse(BaseModel):
    session_id: str
    user_id: str
    active: bool
    active_permissions: list[str]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/register", response_model=LoginResponse)
async def register(body: RegisterRequest) -> LoginResponse:
    """Register a new user account and create a session."""
    from src.db.database import get_user, create_user

    if not body.user_id or not body.user_id.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email address is required.",
        )
    if not body.password or len(body.password) < 6:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password must be at least 6 characters.",
        )

    # Check if user already exists
    if get_user(body.user_id.strip()) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists.",
        )

    # Create the user
    create_user(body.user_id.strip(), body.password)

    # Log them in immediately
    try:
        session = session_manager.authenticate(
            user_id=body.user_id.strip(),
            credentials={"password": body.password},
        )
    except AuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Account created but login failed. Please sign in.",
        ) from exc

    audit_logger.log(
        event_type=AuditEventType.SESSION_STARTED,
        session_id=session.session_id,
        description=f"New user '{body.user_id}' registered and logged in",
    )

    _grant_gmail_permissions(session.session_id)

    return LoginResponse(
        session_id=session.session_id,
        user_id=session.user_id,
        message="Account created successfully",
    )


@router.post("/login", response_model=LoginResponse)
async def login(body: LoginRequest) -> LoginResponse:
    """Authenticate an existing user and create a new session."""
    try:
        session = session_manager.authenticate(
            user_id=body.user_id.strip(),
            credentials={"password": body.password},
        )
        audit_logger.log(
            event_type=AuditEventType.SESSION_STARTED,
            session_id=session.session_id,
            description=f"User '{body.user_id}' logged in via UI",
        )

        _grant_gmail_permissions(session.session_id)

        return LoginResponse(
            session_id=session.session_id,
            user_id=session.user_id,
            message="Login successful",
        )
    except AuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
        ) from exc


@router.post("/logout")
async def logout(session_id: str) -> dict:
    """Invalidate a session."""
    try:
        session_manager._sessions.pop(session_id, None)
    except Exception:
        pass
    return {"message": "Logged out successfully"}


@router.get("/session/{session_id}", response_model=SessionStatusResponse)
async def session_status(session_id: str) -> SessionStatusResponse:
    """Return the current status of a session."""
    try:
        session = session_manager.validate_session(session_id)
        return SessionStatusResponse(
            session_id=session.session_id,
            user_id=session.user_id,
            active=True,
            active_permissions=[
                g.scope.data_source for g in session.active_permissions
            ],
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session invalid or expired",
        ) from exc


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _grant_gmail_permissions(session_id: str) -> None:
    """Auto-grant Gmail permissions if Gmail is connected."""
    from src.ui.state import _gmail_client, permission_manager
    if _gmail_client is not None:
        from src.models.types import GmailScope, PermissionScope
        for gmail_scope, justification in [
            (GmailScope.READONLY, "Read email context and sent history"),
            (GmailScope.SEND,     "Send approved emails via Gmail"),
            (GmailScope.COMPOSE,  "Create Gmail drafts for scheduled emails"),
            (GmailScope.MODIFY,   "Delete emails on user request"),
        ]:
            permission_manager.request_permission(
                session_id=session_id,
                scope=PermissionScope(
                    data_source="gmail",
                    gmail_scope=gmail_scope,
                    justification=justification,
                ),
            )

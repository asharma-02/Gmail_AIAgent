"""
Agent routes — submit instructions, retrieve conversation history,
handle approval gate decisions.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from src.models.types import (
    AgentResponse,
    AgentResponseType,
    ApprovalDecision,
    UserInstruction,
)
from src.orchestrator.errors import LLMNotConfiguredError, OrchestratorError
from src.ui.state import orchestrator, session_manager

router = APIRouter()


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------


class InstructionRequest(BaseModel):
    session_id: str
    text: str
    instruction_type: str = "draft"
    payload: dict | None = None


class ApprovalRequest(BaseModel):
    session_id: str
    decision: str  # "confirmed" or "cancelled"


class AgentResponseOut(BaseModel):
    response_id: str
    session_id: str
    type: str
    success: bool
    message: str
    payload: dict | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _serialise_response(resp: AgentResponse) -> AgentResponseOut:
    payload = None
    if resp.payload is not None:
        try:
            if hasattr(resp.payload, "model_dump"):
                payload = resp.payload.model_dump(mode="json")
            elif isinstance(resp.payload, dict):
                payload = resp.payload
            else:
                payload = {"data": str(resp.payload)}
        except Exception:
            payload = {"data": str(resp.payload)}

    return AgentResponseOut(
        response_id=resp.response_id,
        session_id=resp.session_id,
        type=resp.type.value,
        success=resp.success,
        message=resp.message,
        payload=payload,
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/instruct", response_model=AgentResponseOut)
async def submit_instruction(body: InstructionRequest) -> AgentResponseOut:
    """Submit a natural-language instruction to the agent."""
    try:
        session = session_manager.validate_session(body.session_id)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session invalid or expired",
        ) from exc

    instruction = UserInstruction(
        session_id=body.session_id,
        text=body.text,
        instruction_type=body.instruction_type,
        payload=body.payload or {},
    )

    try:
        response = orchestrator.process_instruction(
            session_ctx=session,
            instruction=instruction,
        )
    except LLMNotConfiguredError:
        response = AgentResponse(
            session_id=body.session_id,
            type=AgentResponseType.ERROR,
            payload=None,
            success=False,
            message=(
                "LLM is not configured. To enable AI draft generation, "
                "set your Gemini API key and pass an llm_client to the orchestrator."
            ),
        )
    except Exception as exc:
        response = AgentResponse(
            session_id=body.session_id,
            type=AgentResponseType.ERROR,
            payload=None,
            success=False,
            message=f"Agent error: {exc}",
        )
    return _serialise_response(response)


@router.get("/history/{session_id}")
async def conversation_history(session_id: str) -> dict:
    """Return the conversation history for a session."""
    try:
        session_manager.validate_session(session_id)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session invalid or expired",
        ) from exc

    turns = orchestrator.get_conversation_history(session_id)
    history = []
    for turn in turns:
        history.append(
            {
                "timestamp": turn.timestamp.isoformat(),
                "instruction": {
                    "text": turn.instruction.text,
                    "type": turn.instruction.instruction_type,
                },
                "response": {
                    "type": turn.response.type.value,
                    "success": turn.response.success,
                    "message": turn.response.message,
                },
            }
        )
    return {"session_id": session_id, "history": history}

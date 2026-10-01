"""Chat endpoints: talk to the FinAlly assistant, which may trade and edit the watchlist."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.llm import chat_history, handle_chat

router = APIRouter(prefix="/api/chat")

MAX_MESSAGE_LENGTH = 4000


class ChatRequest(BaseModel):
    message: str


@router.post("")
async def post_chat(body: ChatRequest, request: Request) -> dict:
    message = body.message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="Message must not be empty")
    if len(message) > MAX_MESSAGE_LENGTH:
        raise HTTPException(
            status_code=400, detail=f"Message too long (max {MAX_MESSAGE_LENGTH} characters)"
        )
    state = request.app.state
    return await handle_chat(message, state.price_cache, state.market_source)


@router.get("/history")
def get_chat_history() -> dict:
    return {"messages": chat_history()}

"""Authenticated, read-only AI assistant endpoints."""

import json
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.assistant.context import assistant_access_label
from app.assistant.schemas import AssistantAsk, AssistantBootstrap, AssistantConversationDetail, AssistantConversationRead
from app.assistant.service import answer_question
from app.dependencies import CurrentUser, DB
from app.models import AssistantConversation, AssistantMessage

router = APIRouter(prefix="/assistant", tags=["AI assistant"])
ASSISTANT_HISTORY_RETENTION_DAYS = 20


def cleanup_expired_conversations(db: DB) -> int:
    """Delete private assistant conversations after the retention period."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=ASSISTANT_HISTORY_RETENTION_DAYS)
    expired = list(db.scalars(
        select(AssistantConversation).where(AssistantConversation.updated_at < cutoff)
    ).all())
    for conversation in expired:
        db.delete(conversation)
    if expired:
        db.commit()
    return len(expired)


def owned_conversation(db: DB, conversation_id: int, user_id: int) -> AssistantConversation:
    conversation = db.scalar(select(AssistantConversation).options(selectinload(AssistantConversation.messages)).where(
        AssistantConversation.id == conversation_id, AssistantConversation.user_id == user_id,
    ))
    if conversation is None:
        raise HTTPException(status_code=404, detail="Assistant conversation not found")
    return conversation


@router.get("/bootstrap", response_model=AssistantBootstrap)
def assistant_bootstrap(db: DB, current_user: CurrentUser) -> AssistantBootstrap:
    label, scope = assistant_access_label(db, current_user)
    if current_user.is_system_admin:
        suggestions = ["Which projects are at risk?", "Compare current workloads", "Show upcoming deadlines", "Summarize organization delivery"]
    elif not current_user.is_member:
        suggestions = ["What can I access?", "How do I complete my profile?", "Why am I not assigned to projects?"]
    else:
        suggestions = ["What should I work on next?", "Show my upcoming deadlines", "Summarize my assigned projects", "Which checklist items remain?"]
    return AssistantBootstrap(access_label=label, scope_description=scope, suggestions=suggestions)


@router.get("/conversations", response_model=list[AssistantConversationRead])
def list_assistant_conversations(db: DB, current_user: CurrentUser) -> list[AssistantConversation]:
    cleanup_expired_conversations(db)
    return list(db.scalars(select(AssistantConversation).where(
        AssistantConversation.user_id == current_user.id,
    ).order_by(AssistantConversation.updated_at.desc()).limit(30)).all())


@router.get("/conversations/{conversation_id}", response_model=AssistantConversationDetail)
def get_assistant_conversation(conversation_id: int, db: DB, current_user: CurrentUser) -> dict:
    conversation = owned_conversation(db, conversation_id, current_user.id)
    return {"id": conversation.id, "title": conversation.title, "context_view": conversation.context_view, "workspace_id": conversation.workspace_id, "project_id": conversation.project_id, "updated_at": conversation.updated_at, "messages": conversation.messages}


@router.delete("/conversations/{conversation_id}", status_code=204)
def delete_assistant_conversation(conversation_id: int, db: DB, current_user: CurrentUser) -> None:
    conversation = owned_conversation(db, conversation_id, current_user.id)
    db.delete(conversation); db.commit()


@router.post("/ask")
def ask_assistant(payload: AssistantAsk, db: DB, current_user: CurrentUser) -> StreamingResponse:
    """Answer from a bounded permission-scoped snapshot and stream SSE chunks."""
    question = payload.question.strip()
    if payload.conversation_id:
        conversation = owned_conversation(db, payload.conversation_id, current_user.id)
    else:
        conversation = AssistantConversation(
            user_id=current_user.id, title=question[:80], context_view=payload.view,
            workspace_id=payload.workspace_id, project_id=payload.project_id,
        )
        db.add(conversation); db.flush()
    history = [(message.role, message.body) for message in conversation.messages[-6:]]
    db.add(AssistantMessage(conversation_id=conversation.id, role="user", body=question))
    try:
        answer, model, sources = answer_question(
            db, current_user, question, workspace_id=payload.workspace_id,
            project_id=payload.project_id, history=history,
        )
    except RuntimeError as exc:
        db.rollback()
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    db.add(AssistantMessage(conversation_id=conversation.id, role="assistant", body=answer, model=model, source_summary=sources))
    # Retention is based on the latest turn, not only conversation creation.
    conversation.updated_at = datetime.now(timezone.utc)
    db.commit()

    def events():
        yield f"data: {json.dumps({'type':'meta','conversation_id':conversation.id,'model':model,'sources':sources})}\n\n"
        for offset in range(0, len(answer), 80):
            yield f"data: {json.dumps({'type':'text','text':answer[offset:offset+80]})}\n\n"
        yield "data: {\"type\":\"done\"}\n\n"

    return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control":"no-cache","X-Accel-Buffering":"no"})

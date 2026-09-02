from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.models import ChatConversation, ChatParticipant, User


def set_conversation_access(db, conversation: ChatConversation, user_id: int, active: bool) -> None:
    participant = db.scalar(select(ChatParticipant).where(
        ChatParticipant.conversation_id == conversation.id,
        ChatParticipant.user_id == user_id,
    ))
    if participant is None:
        user = db.scalar(select(User).options(selectinload(User.profile)).where(User.id == user_id))
        participant = ChatParticipant(conversation_id=conversation.id, user_id=user_id, user=user)
        db.add(participant)
    participant.access_revoked_at = None if active else datetime.now(timezone.utc)


def sync_scoped_conversation_access(
    db, user_id: int, *, active: bool,
    project_id: int | None = None, team_id: int | None = None,
    global_team: bool = False,
) -> None:
    query = select(ChatConversation)
    if project_id is not None:
        query = query.where(ChatConversation.project_id == project_id, ChatConversation.workspace_id.is_not(None))
    elif team_id is not None and global_team:
        query = query.where(ChatConversation.team_id == team_id, ChatConversation.workspace_id.is_(None), ChatConversation.scope_type == "team")
    elif team_id is not None:
        query = query.where(ChatConversation.team_id == team_id, ChatConversation.workspace_id.is_not(None))
    else:
        return
    for conversation in db.scalars(query).all():
        set_conversation_access(db, conversation, user_id, active)

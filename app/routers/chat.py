from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.orm import selectinload

from app.dependencies import CurrentUser, DB
from app.models import (
    ChatConversation, ChatMessage, ChatNotification, ChatParticipant, ChatType, GlobalTeamMember, Project, Team,
    TeamManager, TeamMember, User, WorkspaceMember, WorkspaceRole,
)
from app.schemas import (
    ChatConversationCreate, ChatConversationRead, ChatMessageCreate,
    ChatMessageRead, ChatOptionsRead, ChatScopeRead, ChatUserRead,
)

router = APIRouter(prefix="/workspaces/{workspace_id}/chat", tags=["Chat"])
global_router = APIRouter(prefix="/chat", tags=["Global chat"])


def create_chat_notifications(db: DB, conversation: ChatConversation, message: ChatMessage, recipient_ids: set[int]) -> None:
    for user_id in recipient_ids - {message.sender_id}:
        db.add(ChatNotification(message_id=message.id, conversation_id=conversation.id,
            workspace_id=conversation.workspace_id, user_id=user_id, sender_id=message.sender_id,
            title=conversation.name, message=message.body))


def membership(db: DB, workspace_id: int, user_id: int) -> WorkspaceMember:
    item = db.scalar(select(WorkspaceMember).where(
        WorkspaceMember.workspace_id == workspace_id,
        WorkspaceMember.user_id == user_id,
        WorkspaceMember.is_active.is_(True),
    ))
    if item is None:
        user = db.get(User, user_id)
        if user and user.is_system_admin:
            return WorkspaceMember(workspace_id=workspace_id, user_id=user_id, role=WorkspaceRole.admin, is_active=True)
        raise HTTPException(status_code=404, detail="Workspace not found")
    return item


def is_admin(member: WorkspaceMember) -> bool:
    return member.role == WorkspaceRole.admin


def managed_project_ids(db: DB, workspace_id: int, user_id: int) -> set[int]:
    return set(db.scalars(select(Project.id).where(
        Project.workspace_id == workspace_id, Project.project_manager_id == user_id
    )).all())


def managed_team_ids(db: DB, workspace_id: int, user_id: int) -> set[int]:
    return set(db.scalars(select(Team.id).join(TeamManager).where(
        Team.workspace_id == workspace_id, TeamManager.user_id == user_id
    )).all())


def allocated_project_ids(db: DB, workspace_id: int, user_id: int) -> set[int]:
    return set(db.scalars(select(TeamMember.project_id).join(Team).where(
        Team.workspace_id == workspace_id, TeamMember.user_id == user_id
    )).all())


def allocated_team_ids(db: DB, workspace_id: int, user_id: int) -> set[int]:
    return set(db.scalars(select(TeamMember.team_id).join(Team).where(
        Team.workspace_id == workspace_id, TeamMember.user_id == user_id
    )).all())


def can_access(db: DB, conversation: ChatConversation, member: WorkspaceMember, user_id: int) -> bool:
    if is_admin(member):
        return True
    if conversation.chat_type == ChatType.broadcast:
        return True
    if conversation.chat_type == ChatType.direct:
        participant_ids = {item.user_id for item in conversation.participants}
        has_admin = bool(db.scalar(select(User.id).where(User.id.in_(participant_ids), User.is_system_admin.is_(True))))
        return user_id in participant_ids and has_admin
    if conversation.chat_type == ChatType.project:
        if conversation.project_id in (managed_project_ids(db, conversation.workspace_id, user_id) | allocated_project_ids(db, conversation.workspace_id, user_id)):
            return True
    if conversation.chat_type == ChatType.team:
        if conversation.team_id in (managed_team_ids(db, conversation.workspace_id, user_id) | allocated_team_ids(db, conversation.workspace_id, user_id)):
            return True
    participant = next((item for item in conversation.participants if item.user_id == user_id), None)
    return bool(participant and participant.access_revoked_at and conversation.chat_type in {ChatType.project, ChatType.team})


def can_clear(db: DB, conversation: ChatConversation, member: WorkspaceMember, user_id: int) -> bool:
    if is_admin(member):
        return True
    managed_projects = managed_project_ids(db, conversation.workspace_id, user_id)
    managed_teams = managed_team_ids(db, conversation.workspace_id, user_id)
    if conversation.chat_type == ChatType.project:
        return conversation.project_id in managed_projects
    if conversation.chat_type == ChatType.team:
        return conversation.team_id in managed_teams
    if conversation.chat_type == ChatType.direct:
        return bool(managed_projects or managed_teams) and any(
            item.user_id == user_id for item in conversation.participants
        )
    return False


def ensure_read_cursor(db: DB, conversation: ChatConversation, user_id: int, active: bool = True) -> None:
    existing = next((item for item in conversation.participants if item.user_id == user_id), None)
    if existing:
        if active and existing.access_revoked_at is not None:
            existing.access_revoked_at = None; db.commit()
        return
    user = db.scalar(select(User).options(selectinload(User.profile)).where(User.id == user_id))
    conversation.participants.append(ChatParticipant(user_id=user_id, user=user))
    db.commit()


def visible_messages(conversation: ChatConversation, user_id: int) -> list[ChatMessage]:
    participant = next((item for item in conversation.participants if item.user_id == user_id), None)
    cutoff = participant.access_revoked_at if participant else None
    if cutoff is None:
        return list(conversation.messages)
    if cutoff.tzinfo is None:
        cutoff = cutoff.replace(tzinfo=timezone.utc)
    return [item for item in conversation.messages if (
        item.created_at.replace(tzinfo=timezone.utc) if item.created_at.tzinfo is None else item.created_at
    ) <= cutoff]


def is_after(value: datetime, boundary: datetime | None) -> bool:
    if boundary is None: return True
    if value.tzinfo is None: value = value.replace(tzinfo=timezone.utc)
    if boundary.tzinfo is None: boundary = boundary.replace(tzinfo=timezone.utc)
    return value > boundary


def get_conversation(db: DB, workspace_id: int, conversation_id: int, user_id: int) -> tuple[ChatConversation, WorkspaceMember]:
    member = membership(db, workspace_id, user_id)
    conversation = db.scalar(select(ChatConversation).options(
        selectinload(ChatConversation.participants).selectinload(ChatParticipant.user).selectinload(User.profile),
        selectinload(ChatConversation.messages).selectinload(ChatMessage.sender).selectinload(User.profile),
    ).where(ChatConversation.id == conversation_id, ChatConversation.workspace_id == workspace_id))
    if conversation is None or not can_access(db, conversation, member, user_id):
        raise HTTPException(status_code=404, detail="Conversation not found")
    ensure_read_cursor(db, conversation, user_id, has_current_scope_access(db, conversation, member, user_id))
    return conversation, member


def user_read(user: User) -> ChatUserRead:
    return ChatUserRead(id=user.id, name=user.name, email=user.email, profile_image=user.profile_image)


def message_read(message: ChatMessage) -> ChatMessageRead:
    return ChatMessageRead(
        id=message.id, conversation_id=message.conversation_id,
        sender=user_read(message.sender), body=message.body,
        is_deleted=message.is_deleted, deleted_by_id=message.deleted_by_id,
        created_at=message.created_at,
    )


def conversation_read(
    conversation: ChatConversation, user_id: int, can_send: bool = True,
    clear_allowed: bool = False,
) -> ChatConversationRead:
    participant = next((item for item in conversation.participants if item.user_id == user_id), None)
    last_read = participant.last_read_at if participant else None
    messages = visible_messages(conversation, user_id)
    unread = sum(1 for item in messages if item.sender_id != user_id and is_after(item.created_at, last_read))
    last_message = max(messages, key=lambda item: item.created_at, default=None)
    display_name = conversation.name
    if conversation.chat_type == ChatType.direct:
        other = next((item.user for item in conversation.participants if item.user_id != user_id), None)
        if other is not None:
            display_name = other.name
    return ChatConversationRead(
        id=conversation.id, workspace_id=conversation.workspace_id, scope_type=conversation.scope_type, chat_type=conversation.chat_type,
        name=display_name, project_id=conversation.project_id, team_id=conversation.team_id,
        participants=[user_read(item.user) for item in conversation.participants],
        last_message=message_read(last_message) if last_message else None,
        unread_count=unread, can_send=can_send, can_clear=clear_allowed,
    )


@router.get("/options", response_model=ChatOptionsRead)
def chat_options(workspace_id: int, db: DB, current_user: CurrentUser) -> ChatOptionsRead:
    member = membership(db, workspace_id, current_user.id)
    admin = is_admin(member)
    project_ids = managed_project_ids(db, workspace_id, current_user.id)
    team_ids = managed_team_ids(db, workspace_id, current_user.id)
    if admin:
        projects = list(db.scalars(select(Project).where(Project.workspace_id == workspace_id).order_by(Project.name)).all())
        teams = list(db.scalars(select(Team).where(Team.workspace_id == workspace_id).order_by(Team.name)).all())
        # Administrators manage the registered user directory, including people
        # who have not been allocated to a project or team yet.
        recipient_ids = set(db.scalars(select(User.id).where(
            User.is_active.is_(True), User.id != current_user.id
        )).all())
    elif project_ids or team_ids:
        projects = list(db.scalars(select(Project).where(Project.id.in_(project_ids)).order_by(Project.name)).all()) if project_ids else []
        teams = list(db.scalars(select(Team).where(Team.id.in_(team_ids)).order_by(Team.name)).all()) if team_ids else []
        recipient_ids = set(db.scalars(select(TeamMember.user_id).join(Team).where(
            Team.workspace_id == workspace_id,
            or_(TeamMember.project_id.in_(project_ids) if project_ids else False, TeamMember.team_id.in_(team_ids) if team_ids else False),
            TeamMember.user_id != current_user.id,
        )).all())
    else:
        projects, teams = [], []
        own_projects = allocated_project_ids(db, workspace_id, current_user.id)
        own_teams = allocated_team_ids(db, workspace_id, current_user.id)
        recipient_ids = set(db.scalars(select(Project.project_manager_id).where(Project.id.in_(own_projects), Project.project_manager_id.is_not(None))).all()) if own_projects else set()
        if own_teams:
            recipient_ids.update(db.scalars(select(TeamManager.user_id).where(TeamManager.team_id.in_(own_teams))).all())
        recipient_ids.discard(current_user.id)
    user_query = select(User).options(selectinload(User.profile)).where(User.id.in_(recipient_ids))
    if not current_user.is_system_admin:
        user_query = user_query.where(User.is_system_admin.is_(True))
    users = list(db.scalars(user_query.order_by(User.name)).all()) if recipient_ids else []
    return ChatOptionsRead(
        recipients=[user_read(item) for item in users],
        projects=[ChatScopeRead(id=item.id, name=item.name) for item in projects],
        teams=[ChatScopeRead(id=item.id, name=item.name) for item in teams],
        can_broadcast=admin,
    )


@router.get("/conversations", response_model=list[ChatConversationRead])
def list_conversations(workspace_id: int, db: DB, current_user: CurrentUser) -> list[ChatConversationRead]:
    member = membership(db, workspace_id, current_user.id)
    conversations = list(db.scalars(select(ChatConversation).options(
        selectinload(ChatConversation.participants).selectinload(ChatParticipant.user).selectinload(User.profile),
        selectinload(ChatConversation.messages).selectinload(ChatMessage.sender).selectinload(User.profile),
    ).where(ChatConversation.workspace_id == workspace_id).order_by(ChatConversation.updated_at.desc())).unique().all())
    visible = [item for item in conversations if can_access(db, item, member, current_user.id)]
    for item in visible:
        ensure_read_cursor(db, item, current_user.id, has_current_scope_access(db, item, member, current_user.id))
    return [conversation_read(
        item, current_user.id,
        has_current_scope_access(db, item, member, current_user.id) and (item.chat_type != ChatType.broadcast or is_admin(member)),
        can_clear(db, item, member, current_user.id),
    ) for item in visible]


@router.post("/conversations", response_model=ChatConversationRead, status_code=201)
def create_conversation(workspace_id: int, payload: ChatConversationCreate, db: DB, current_user: CurrentUser) -> ChatConversationRead:
    member = membership(db, workspace_id, current_user.id)
    admin = is_admin(member)
    project_ids = managed_project_ids(db, workspace_id, current_user.id)
    team_ids = managed_team_ids(db, workspace_id, current_user.id)
    participants = {current_user.id}
    project_id = team_id = None
    if payload.chat_type == ChatType.broadcast:
        if not admin:
            raise HTTPException(status_code=403, detail="Only workspace admins can create announcements")
        name = payload.name or "Workspace announcements"
    elif payload.chat_type == ChatType.project:
        project = db.get(Project, payload.project_id) if payload.project_id else None
        if project is None or project.workspace_id != workspace_id:
            raise HTTPException(status_code=404, detail="Project not found")
        if not admin and project.id not in project_ids:
            raise HTTPException(status_code=403, detail="You can only create chats for projects you manage")
        existing = db.scalar(select(ChatConversation).where(ChatConversation.workspace_id == workspace_id, ChatConversation.project_id == project.id, ChatConversation.chat_type == ChatType.project))
        if existing:
            return conversation_read(get_conversation(db, workspace_id, existing.id, current_user.id)[0], current_user.id)
        project_id, name = project.id, payload.name or f"{project.name} project"
    elif payload.chat_type == ChatType.team:
        team = db.get(Team, payload.team_id) if payload.team_id else None
        if team is None or team.workspace_id != workspace_id:
            raise HTTPException(status_code=404, detail="Team not found")
        if not admin and team.id not in team_ids:
            raise HTTPException(status_code=403, detail="You can only create chats for teams you manage")
        existing = db.scalar(select(ChatConversation).where(ChatConversation.workspace_id == workspace_id, ChatConversation.team_id == team.id, ChatConversation.chat_type == ChatType.team))
        if existing:
            return conversation_read(get_conversation(db, workspace_id, existing.id, current_user.id)[0], current_user.id)
        team_id, name = team.id, payload.name or f"{team.name} team"
    else:
        options = chat_options(workspace_id, db, current_user)
        allowed = {item.id for item in options.recipients}
        if payload.recipient_id not in allowed:
            raise HTTPException(status_code=403, detail="You cannot message this user directly")
        recipient = db.get(User, payload.recipient_id)
        participants.add(recipient.id)
        direct_ids = db.scalars(select(ChatConversation.id).where(ChatConversation.workspace_id == workspace_id, ChatConversation.chat_type == ChatType.direct)).all()
        for conversation_id in direct_ids:
            ids = set(db.scalars(select(ChatParticipant.user_id).where(ChatParticipant.conversation_id == conversation_id)).all())
            if ids == participants:
                return conversation_read(get_conversation(db, workspace_id, conversation_id, current_user.id)[0], current_user.id)
        name = payload.name or recipient.name
    conversation = ChatConversation(workspace_id=workspace_id, chat_type=payload.chat_type, name=name.strip(), created_by_id=current_user.id, project_id=project_id, team_id=team_id)
    db.add(conversation); db.flush()
    if payload.chat_type == ChatType.direct:
        db.add_all([ChatParticipant(conversation_id=conversation.id, user_id=user_id) for user_id in participants])
    db.commit()
    return conversation_read(get_conversation(db, workspace_id, conversation.id, current_user.id)[0], current_user.id, payload.chat_type != ChatType.broadcast or admin)


@router.get("/conversations/{conversation_id}/messages", response_model=list[ChatMessageRead])
def list_messages(workspace_id: int, conversation_id: int, db: DB, current_user: CurrentUser, limit: int = Query(100, ge=1, le=200)) -> list[ChatMessageRead]:
    conversation, _ = get_conversation(db, workspace_id, conversation_id, current_user.id)
    participant = next((item for item in conversation.participants if item.user_id == current_user.id), None)
    if participant:
        participant.last_read_at = datetime.now(timezone.utc); db.commit()
    db.execute(
        ChatNotification.__table__.update().where(
            ChatNotification.conversation_id == conversation.id,
            ChatNotification.user_id == current_user.id,
            ChatNotification.is_read.is_(False),
        ).values(is_read=True)
    )
    db.commit()
    messages = sorted(visible_messages(conversation, current_user.id), key=lambda item: item.created_at)[-limit:]
    return [message_read(item) for item in messages]


@router.post("/conversations/{conversation_id}/messages", response_model=ChatMessageRead, status_code=201)
def send_message(workspace_id: int, conversation_id: int, payload: ChatMessageCreate, db: DB, current_user: CurrentUser) -> ChatMessageRead:
    conversation, member = get_conversation(db, workspace_id, conversation_id, current_user.id)
    if conversation.chat_type == ChatType.direct:
        participant_ids = {item.user_id for item in conversation.participants}
        if not db.scalar(select(User.id).where(User.id.in_(participant_ids), User.is_system_admin.is_(True))):
            raise HTTPException(status_code=403, detail="Members can send direct messages only to administrators")
    if not has_current_scope_access(db, conversation, member, current_user.id):
        raise HTTPException(status_code=403, detail="You have read-only access to previous messages")
    if conversation.chat_type == ChatType.broadcast and not is_admin(member):
        raise HTTPException(status_code=403, detail="Only workspace admins can post announcements")
    body = payload.body.strip()
    if not body:
        raise HTTPException(status_code=422, detail="Message cannot be blank")
    message = ChatMessage(conversation_id=conversation.id, sender_id=current_user.id, body=body)
    conversation.updated_at = datetime.now(timezone.utc)
    db.add(message); db.flush()
    if conversation.chat_type == ChatType.direct:
        recipient_ids = {item.user_id for item in conversation.participants}
    elif conversation.chat_type == ChatType.project:
        recipient_ids = set(db.scalars(select(TeamMember.user_id).where(TeamMember.project_id == conversation.project_id)).all())
        project = db.get(Project, conversation.project_id)
        if project and project.project_manager_id:
            recipient_ids.add(project.project_manager_id)
    elif conversation.chat_type == ChatType.team:
        recipient_ids = set(db.scalars(select(TeamMember.user_id).where(TeamMember.team_id == conversation.team_id)).all())
        recipient_ids.update(db.scalars(select(TeamManager.user_id).where(TeamManager.team_id == conversation.team_id)).all())
    else:
        recipient_ids = set(db.scalars(select(WorkspaceMember.user_id).where(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.is_active.is_(True),
        )).all())
    if conversation.chat_type in {ChatType.project, ChatType.team}:
        recipient_ids.update(db.scalars(select(User.id).where(
            User.is_active.is_(True), User.is_system_admin.is_(True)
        )).all())
    recipient_ids.discard(current_user.id)
    create_chat_notifications(db, conversation, message, recipient_ids)
    db.commit(); db.refresh(message)
    message.sender = db.scalar(select(User).options(selectinload(User.profile)).where(User.id == current_user.id))
    return message_read(message)


@router.delete("/conversations/{conversation_id}", status_code=204)
def delete_conversation(
    workspace_id: int, conversation_id: int, db: DB, current_user: CurrentUser
) -> None:
    member = membership(db, workspace_id, current_user.id)
    if not is_admin(member):
        raise HTTPException(status_code=403, detail="Workspace admin required")
    conversation = db.scalar(select(ChatConversation).where(
        ChatConversation.id == conversation_id,
        ChatConversation.workspace_id == workspace_id,
    ))
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    db.delete(conversation)
    db.commit()


@router.delete("/conversations/{conversation_id}/messages/{message_id}", response_model=ChatMessageRead)
def delete_message(
    workspace_id: int, conversation_id: int, message_id: int,
    db: DB, current_user: CurrentUser,
) -> ChatMessageRead:
    conversation, member = get_conversation(db, workspace_id, conversation_id, current_user.id)
    message = next((item for item in conversation.messages if item.id == message_id), None)
    if message is None:
        raise HTTPException(status_code=404, detail="Message not found")
    if message.sender_id != current_user.id and not is_admin(member):
        raise HTTPException(status_code=403, detail="You can only delete your own messages")
    if not message.is_deleted:
        message.body = ""
        message.is_deleted = True
        message.deleted_by_id = current_user.id
        db.commit(); db.refresh(message)
    return message_read(message)


@router.delete("/conversations/{conversation_id}/messages", status_code=204)
def clear_conversation_messages(
    workspace_id: int, conversation_id: int, db: DB, current_user: CurrentUser,
) -> None:
    conversation, member = get_conversation(
        db, workspace_id, conversation_id, current_user.id
    )
    if not can_clear(db, conversation, member, current_user.id):
        raise HTTPException(
            status_code=403,
            detail="Only an authorized administrator or manager can clear this chat",
        )
    db.execute(delete(ChatNotification).where(
        ChatNotification.conversation_id == conversation.id
    ))
    db.execute(delete(ChatMessage).where(
        ChatMessage.conversation_id == conversation.id
    ))
    conversation.updated_at = datetime.now(timezone.utc)
    db.commit()


def global_chat_access(db: DB, conversation: ChatConversation, user: User) -> bool:
    if user.is_system_admin: return True
    if conversation.scope_type == "global": return user.is_active and user.is_member
    if conversation.scope_type == "direct":
        participant_ids = {item.user_id for item in conversation.participants}
        has_admin = bool(db.scalar(select(User.id).where(User.id.in_(participant_ids), User.is_system_admin.is_(True))))
        return user.id in participant_ids and has_admin
    if conversation.scope_type == "team":
        current = bool(db.scalar(select(TeamManager.id).where(TeamManager.team_id == conversation.team_id, TeamManager.user_id == user.id)) or db.scalar(select(GlobalTeamMember.id).where(GlobalTeamMember.team_id == conversation.team_id, GlobalTeamMember.user_id == user.id)))
        participant = next((item for item in conversation.participants if item.user_id == user.id), None)
        return current or bool(participant and participant.access_revoked_at)
    return False


def has_current_scope_access(db: DB, conversation: ChatConversation, member: WorkspaceMember, user_id: int) -> bool:
    if is_admin(member): return True
    if conversation.chat_type == ChatType.broadcast: return True
    if conversation.chat_type == ChatType.direct:
        participant_ids = {item.user_id for item in conversation.participants}
        return user_id in participant_ids and bool(db.scalar(select(User.id).where(User.id.in_(participant_ids), User.is_system_admin.is_(True))))
    if conversation.chat_type == ChatType.project:
        return conversation.project_id in (managed_project_ids(db, conversation.workspace_id, user_id) | allocated_project_ids(db, conversation.workspace_id, user_id))
    if conversation.chat_type == ChatType.team:
        return conversation.team_id in (managed_team_ids(db, conversation.workspace_id, user_id) | allocated_team_ids(db, conversation.workspace_id, user_id))
    return False


def has_current_global_access(db: DB, conversation: ChatConversation, user: User) -> bool:
    if user.is_system_admin: return True
    if conversation.scope_type == "global": return user.is_active and user.is_member
    if conversation.scope_type == "direct": return global_chat_access(db, conversation, user)
    if conversation.scope_type == "team":
        return bool(db.scalar(select(TeamManager.id).where(TeamManager.team_id == conversation.team_id, TeamManager.user_id == user.id)) or db.scalar(select(GlobalTeamMember.id).where(GlobalTeamMember.team_id == conversation.team_id, GlobalTeamMember.user_id == user.id)))
    return False


def global_chat(db: DB, conversation_id: int, user: User) -> ChatConversation:
    conversation = db.scalar(select(ChatConversation).options(
        selectinload(ChatConversation.participants).selectinload(ChatParticipant.user).selectinload(User.profile),
        selectinload(ChatConversation.messages).selectinload(ChatMessage.sender).selectinload(User.profile),
    ).where(ChatConversation.id == conversation_id, ChatConversation.workspace_id.is_(None)))
    if conversation is None or not global_chat_access(db, conversation, user): raise HTTPException(status_code=404, detail="Conversation not found")
    ensure_read_cursor(db, conversation, user.id, has_current_global_access(db, conversation, user))
    return conversation


@global_router.get("/conversations", response_model=list[ChatConversationRead])
def list_global_conversations(db: DB, current_user: CurrentUser) -> list[ChatConversationRead]:
    conversations = list(db.scalars(select(ChatConversation).options(
        selectinload(ChatConversation.participants).selectinload(ChatParticipant.user).selectinload(User.profile),
        selectinload(ChatConversation.messages).selectinload(ChatMessage.sender).selectinload(User.profile),
    ).where(ChatConversation.workspace_id.is_(None)).order_by(ChatConversation.updated_at.desc())).unique().all())
    visible = [item for item in conversations if global_chat_access(db, item, current_user)]
    for item in visible: ensure_read_cursor(db, item, current_user.id, has_current_global_access(db, item, current_user))
    return [conversation_read(item, current_user.id, has_current_global_access(db, item, current_user) and (item.scope_type != "global" or current_user.is_system_admin), current_user.is_system_admin or (item.scope_type == "team" and bool(db.scalar(select(TeamManager.id).where(TeamManager.team_id == item.team_id, TeamManager.user_id == current_user.id))))) for item in visible]


@global_router.get("/options", response_model=ChatOptionsRead)
def global_chat_options(db: DB, current_user: CurrentUser) -> ChatOptionsRead:
    if current_user.is_system_admin:
        recipient_ids = set(db.scalars(select(User.id).where(User.is_active.is_(True), User.is_member.is_(True), User.id != current_user.id)).all())
        teams = list(db.scalars(select(Team).order_by(Team.name)).all())
    else:
        team_ids = set(db.scalars(select(GlobalTeamMember.team_id).where(GlobalTeamMember.user_id == current_user.id)).all()) | set(db.scalars(select(TeamManager.team_id).where(TeamManager.user_id == current_user.id)).all())
        recipient_ids = set(db.scalars(select(User.id).where(
            User.is_active.is_(True), User.is_member.is_(True), User.id != current_user.id
        )).all())
        teams = list(db.scalars(select(Team).where(Team.id.in_(team_ids)).order_by(Team.name)).all()) if team_ids else []
    user_query = select(User).options(selectinload(User.profile)).where(User.id.in_(recipient_ids))
    if not current_user.is_system_admin:
        user_query = user_query.where(User.is_system_admin.is_(True))
    users = list(db.scalars(user_query.order_by(User.name)).all()) if recipient_ids else []
    return ChatOptionsRead(recipients=[user_read(item) for item in users], projects=[], teams=[ChatScopeRead(id=item.id,name=item.name) for item in teams], can_broadcast=current_user.is_system_admin)


@global_router.post("/conversations", response_model=ChatConversationRead, status_code=201)
def create_global_conversation(payload: ChatConversationCreate, db: DB, current_user: CurrentUser) -> ChatConversationRead:
    participants={current_user.id}; team_id=None
    if payload.chat_type == ChatType.broadcast:
        if not current_user.is_system_admin: raise HTTPException(status_code=403, detail="System administrator access required")
        existing=db.scalar(select(ChatConversation).where(ChatConversation.workspace_id.is_(None),ChatConversation.scope_type=="global",ChatConversation.chat_type==ChatType.broadcast))
        if existing:return conversation_read(global_chat(db,existing.id,current_user),current_user.id,True,True)
        scope,name="global",payload.name or "Company announcements"
    elif payload.chat_type == ChatType.team:
        team=db.get(Team,payload.team_id) if payload.team_id else None
        if team is None:raise HTTPException(status_code=404,detail="Team not found")
        if not current_user.is_system_admin and not db.scalar(select(TeamManager.id).where(TeamManager.team_id==team.id,TeamManager.user_id==current_user.id)):
            raise HTTPException(status_code=403,detail="Only the team manager or an administrator can create the team conversation")
        existing=db.scalar(select(ChatConversation).where(ChatConversation.workspace_id.is_(None),ChatConversation.team_id==team.id,ChatConversation.scope_type=="team"))
        if existing:return conversation_read(global_chat(db,existing.id,current_user),current_user.id,True)
        scope,team_id,name="team",team.id,payload.name or f"{team.name} team"
    elif payload.chat_type == ChatType.direct:
        allowed={item.id for item in global_chat_options(db,current_user).recipients}
        if payload.recipient_id not in allowed:raise HTTPException(status_code=403,detail="You cannot message this user directly")
        participants.add(payload.recipient_id); scope="direct"; name=payload.name or db.get(User,payload.recipient_id).name
        for conversation in db.scalars(select(ChatConversation).options(selectinload(ChatConversation.participants)).where(ChatConversation.workspace_id.is_(None),ChatConversation.scope_type=="direct")).all():
            if {item.user_id for item in conversation.participants}==participants:return conversation_read(global_chat(db,conversation.id,current_user),current_user.id)
    else:raise HTTPException(status_code=400,detail="Project conversations require a workspace")
    conversation=ChatConversation(workspace_id=None,scope_type=scope,chat_type=payload.chat_type,name=name.strip(),created_by_id=current_user.id,team_id=team_id)
    db.add(conversation);db.flush()
    if scope=="direct":db.add_all([ChatParticipant(conversation_id=conversation.id,user_id=item) for item in participants])
    db.commit();return conversation_read(global_chat(db,conversation.id,current_user),current_user.id,scope!="global" or current_user.is_system_admin)


@global_router.get("/conversations/{conversation_id}/messages",response_model=list[ChatMessageRead])
def list_global_messages(conversation_id:int,db:DB,current_user:CurrentUser,limit:int=Query(100,ge=1,le=200))->list[ChatMessageRead]:
    conversation=global_chat(db,conversation_id,current_user);participant=next((item for item in conversation.participants if item.user_id==current_user.id),None)
    if participant:participant.last_read_at=datetime.now(timezone.utc)
    for alert in db.scalars(select(ChatNotification).where(ChatNotification.conversation_id==conversation.id,ChatNotification.user_id==current_user.id,ChatNotification.is_read.is_(False))).all():alert.is_read=True
    db.commit();return [message_read(item) for item in sorted(visible_messages(conversation,current_user.id),key=lambda item:item.created_at)[-limit:]]


@global_router.post("/conversations/{conversation_id}/messages",response_model=ChatMessageRead,status_code=201)
def send_global_message(conversation_id:int,payload:ChatMessageCreate,db:DB,current_user:CurrentUser)->ChatMessageRead:
    conversation=global_chat(db,conversation_id,current_user)
    if not has_current_global_access(db,conversation,current_user):raise HTTPException(status_code=403,detail="You have read-only access to previous messages")
    if conversation.scope_type=="global" and not current_user.is_system_admin:raise HTTPException(status_code=403,detail="Only administrators can post announcements")
    body=payload.body.strip()
    if not body:raise HTTPException(status_code=422,detail="Message cannot be blank")
    message=ChatMessage(conversation_id=conversation.id,sender_id=current_user.id,body=body);db.add(message);db.flush();conversation.updated_at=datetime.now(timezone.utc)
    if conversation.scope_type=="global":recipients=set(db.scalars(select(User.id).where(User.is_active.is_(True),User.is_member.is_(True))).all())
    elif conversation.scope_type=="team":recipients=set(db.scalars(select(GlobalTeamMember.user_id).where(GlobalTeamMember.team_id==conversation.team_id)).all());recipients.update(db.scalars(select(TeamManager.user_id).where(TeamManager.team_id==conversation.team_id)).all());recipients.update(db.scalars(select(User.id).where(User.is_active.is_(True),User.is_system_admin.is_(True))).all())
    else:recipients={item.user_id for item in conversation.participants}
    create_chat_notifications(db,conversation,message,recipients);db.commit();db.refresh(message);message.sender=db.scalar(select(User).options(selectinload(User.profile)).where(User.id==current_user.id));return message_read(message)


@global_router.delete("/conversations/{conversation_id}", status_code=204)
def delete_global_conversation(conversation_id: int, db: DB, current_user: CurrentUser) -> None:
    if not current_user.is_system_admin:
        raise HTTPException(status_code=403, detail="System administrator access required")
    conversation = global_chat(db, conversation_id, current_user)
    db.delete(conversation)
    db.commit()


@global_router.delete("/conversations/{conversation_id}/messages/{message_id}", response_model=ChatMessageRead)
def delete_global_message(conversation_id: int, message_id: int, db: DB, current_user: CurrentUser) -> ChatMessageRead:
    conversation = global_chat(db, conversation_id, current_user)
    message = next((item for item in conversation.messages if item.id == message_id), None)
    if message is None:
        raise HTTPException(status_code=404, detail="Message not found")
    if message.sender_id != current_user.id and not current_user.is_system_admin:
        raise HTTPException(status_code=403, detail="You can only delete your own messages")
    if not message.is_deleted:
        message.body = ""
        message.is_deleted = True
        message.deleted_by_id = current_user.id
        db.commit(); db.refresh(message)
    return message_read(message)


@global_router.delete("/conversations/{conversation_id}/messages", status_code=204)
def clear_global_conversation(conversation_id: int, db: DB, current_user: CurrentUser) -> None:
    conversation = global_chat(db, conversation_id, current_user)
    manager = conversation.scope_type == "team" and bool(db.scalar(select(TeamManager.id).where(
        TeamManager.team_id == conversation.team_id, TeamManager.user_id == current_user.id
    )))
    if not current_user.is_system_admin and not manager:
        raise HTTPException(status_code=403, detail="Only an authorized administrator or team manager can clear this chat")
    db.execute(delete(ChatNotification).where(ChatNotification.conversation_id == conversation.id))
    db.execute(delete(ChatMessage).where(ChatMessage.conversation_id == conversation.id))
    conversation.updated_at = datetime.now(timezone.utc)
    db.commit()

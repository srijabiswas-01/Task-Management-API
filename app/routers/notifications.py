from datetime import datetime, time, timedelta, timezone

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.profile import profile_completion
from app.dependencies import CurrentUser, DB, require_workspace_admin
from app.models import ChatNotification, GlobalAnnouncement, GlobalProfileReminder, Notification, ProfileCompletionReminder, Task, TaskAssignee, TaskStatus, User
from app.schemas import (
    NotificationList,
    NotificationRead,
    NotificationReadAllResult,
    ProfileReminderResult,
    ProfileReminderSend,
)

router = APIRouter(prefix="/notifications", tags=["Notifications"])


def utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def task_deadline(task: Task) -> datetime | None:
    if task.end_at:
        return utc(task.end_at)
    if task.due_date:
        return datetime.combine(task.due_date, time.max, tzinfo=timezone.utc)
    return None


def sync_deadline_notifications(db: DB, user_id: int) -> None:
    now = datetime.now(timezone.utc)
    cutoff = now + timedelta(hours=settings.notification_due_soon_hours)
    tasks = db.scalars(
        select(Task)
        .join(TaskAssignee, TaskAssignee.task_id == Task.id)
        .where(TaskAssignee.user_id == user_id)
        .options(
            selectinload(Task.project),
            selectinload(Task.schedule),
            selectinload(Task.checklist_items),
        )
    ).all()
    existing = {
        item.task_id: item
        for item in db.scalars(
            select(Notification).where(
                Notification.user_id == user_id,
                Notification.kind == "task_deadline",
            )
        ).all()
    }
    active_task_ids: set[int] = set()

    for task in tasks:
        deadline = task_deadline(task)
        if not deadline or deadline > cutoff or task.status == TaskStatus.done:
            continue
        active_task_ids.add(task.id)
        overdue = deadline < now
        incomplete = task.checklist_total - task.checklist_done
        if overdue and incomplete:
            title = f"Overdue checklist: {task.title}"
            message = (
                f"The deadline passed with {incomplete} of {task.checklist_total} "
                "checklist items incomplete. Please review this task immediately."
            )
        elif overdue:
            title = f"Task overdue: {task.title}"
            message = "This assigned task has passed its deadline and is not complete."
        elif incomplete:
            title = f"Deadline approaching: {task.title}"
            message = (
                f"This task is due within {settings.notification_due_soon_hours} hours "
                f"and has {incomplete} incomplete checklist item(s)."
            )
        else:
            title = f"Deadline approaching: {task.title}"
            message = f"This assigned task is due within {settings.notification_due_soon_hours} hours."

        notification = existing.get(task.id)
        if notification is None:
            notification = Notification(
                user_id=user_id,
                workspace_id=task.project.workspace_id,
                project_id=task.project_id,
                task_id=task.id,
                kind="task_deadline",
                severity="critical",
                title=title,
                message=message,
            )
            db.add(notification)
        else:
            notification.title = title
            notification.message = message
            notification.is_resolved = False

    for task_id, notification in existing.items():
        if task_id not in active_task_ids:
            notification.is_resolved = True
    db.commit()


@router.get("", response_model=NotificationList)
def list_notifications(
    db: DB,
    current_user: CurrentUser,
    limit: int = Query(default=50, ge=1, le=100),
) -> NotificationList:
    sync_deadline_notifications(db, current_user.id)
    active_filter = (
        Notification.user_id == current_user.id,
        Notification.is_resolved.is_(False),
    )
    items = list(db.scalars(
        select(Notification)
        .where(Notification.user_id == current_user.id)
        .order_by(Notification.is_resolved, Notification.updated_at.desc())
        .limit(limit)
    ).all())
    reminders = list(db.scalars(
        select(ProfileCompletionReminder)
        .where(ProfileCompletionReminder.user_id == current_user.id)
        .order_by(ProfileCompletionReminder.updated_at.desc())
    ).all())
    global_reminders = list(db.scalars(
        select(GlobalProfileReminder).where(GlobalProfileReminder.user_id == current_user.id)
        .order_by(GlobalProfileReminder.updated_at.desc())
    ).all())
    announcements = list(db.scalars(
        select(GlobalAnnouncement).where(GlobalAnnouncement.user_id == current_user.id)
        .order_by(GlobalAnnouncement.updated_at.desc())
    ).all())
    _, current_missing = profile_completion(current_user, current_user.profile)
    if not [field for field in current_missing if field not in {"Department", "Designation"}]:
        for reminder in reminders:
            reminder.is_resolved = True
        for reminder in global_reminders:
            reminder.is_resolved = True
        db.commit()
    unread = db.scalars(
        select(Notification).where(*active_filter, Notification.is_read.is_(False))
    ).all()
    critical = db.scalars(
        select(Notification).where(
            *active_filter,
            Notification.severity == "critical",
            Notification.is_acknowledged.is_(False),
        )
    ).all()
    serialized = [NotificationRead(
        id=str(item.id), workspace_id=item.workspace_id, project_id=item.project_id,
        task_id=item.task_id, kind=item.kind, severity=item.severity, title=item.title,
        message=item.message, is_read=item.is_read, is_acknowledged=item.is_acknowledged,
        is_resolved=item.is_resolved, created_at=item.created_at, updated_at=item.updated_at,
    ) for item in items]
    serialized.extend(NotificationRead(
        id=f"profile-{item.id}", workspace_id=item.workspace_id, kind="profile_completion",
        severity="normal", title=item.title, message=item.message, is_read=item.is_read,
        is_acknowledged=False, is_resolved=item.is_resolved,
        created_at=item.created_at, updated_at=item.updated_at,
    ) for item in reminders)
    serialized.extend(NotificationRead(
        id=f"global-profile-{item.id}", kind="profile_completion", severity="normal",
        title=item.title, message=item.message, is_read=item.is_read,
        is_acknowledged=False, is_resolved=item.is_resolved,
        created_at=item.created_at, updated_at=item.updated_at,
    ) for item in global_reminders)
    serialized.extend(NotificationRead(
        id=f"announcement-{item.id}", kind="announcement", severity="normal",
        title=item.title, message=item.message, is_read=item.is_read,
        is_acknowledged=False, is_resolved=False,
        created_at=item.created_at, updated_at=item.updated_at,
    ) for item in announcements)
    serialized.sort(key=lambda item: (item.is_resolved, -item.updated_at.timestamp()))
    reminder_unread = sum(1 for item in [*reminders, *global_reminders] if not item.is_resolved and not item.is_read)
    announcement_unread = sum(1 for item in announcements if not item.is_read)
    return NotificationList(
        items=serialized[:limit],
        unread_count=len(unread) + reminder_unread + announcement_unread,
        critical_count=len(critical),
    )


@router.post("/profile-completion", response_model=ProfileReminderResult)
def send_global_profile_completion_reminders(
    payload: ProfileReminderSend, db: DB, current_user: CurrentUser,
) -> ProfileReminderResult:
    if not current_user.is_system_admin:
        raise HTTPException(status_code=403, detail="System administrator access required")
    user_ids = list(dict.fromkeys(payload.user_ids))
    users = list(db.scalars(select(User).options(selectinload(User.profile)).where(
        User.id.in_(user_ids), User.is_active.is_(True), User.is_member.is_(True)
    )).all())
    if len(users) != len(user_ids):
        raise HTTPException(status_code=400, detail="Select active Members or Admins only")
    existing = {item.user_id: item for item in db.scalars(select(GlobalProfileReminder).where(
        GlobalProfileReminder.user_id.in_(user_ids)
    )).all()}
    sent_count = 0
    for user in users:
        percent, missing = profile_completion(user, user.profile)
        own_missing = [field for field in missing if field not in {"Department", "Designation"}]
        if not own_missing:
            continue
        title = payload.title.strip() if payload.title else "Complete your profile"
        message = payload.message.strip() if payload.message else (
            f"Please complete your profile by adding: {', '.join(own_missing)}. "
            "Department and designation are assigned separately by an administrator."
        )
        reminder = existing.get(user.id)
        if reminder is None:
            reminder = GlobalProfileReminder(user_id=user.id, sent_by_id=current_user.id)
            db.add(reminder)
        reminder.title = title; reminder.message = message
        reminder.completion_percent = percent; reminder.is_read = False; reminder.is_resolved = False
        sent_count += 1
    db.commit()
    return ProfileReminderResult(sent_count=sent_count)


@router.post("/profile-completion/{workspace_id}", response_model=ProfileReminderResult)
def send_profile_completion_reminders(
    workspace_id: int,
    payload: ProfileReminderSend,
    db: DB,
    current_user: CurrentUser,
) -> ProfileReminderResult:
    require_workspace_admin(db, workspace_id, current_user.id)
    user_ids = list(dict.fromkeys(payload.user_ids))
    users = list(db.scalars(
        select(User).options(selectinload(User.profile)).where(
            User.id.in_(user_ids), User.is_active.is_(True)
        )
    ).all())
    if len(users) != len(user_ids):
        raise HTTPException(status_code=400, detail="Select active registered users only")
    existing_reminders = {
        reminder.user_id: reminder for reminder in db.scalars(
            select(ProfileCompletionReminder).where(
                ProfileCompletionReminder.workspace_id == workspace_id,
                ProfileCompletionReminder.user_id.in_(user_ids),
            )
        ).all()
    }
    sent_count = 0
    for user in users:
        percent, missing = profile_completion(user, user.profile)
        member_missing = [field for field in missing if field not in {"Department", "Designation"}]
        if not member_missing:
            continue
        reminder = existing_reminders.get(user.id)
        default_message = (
            f"Please complete your profile by adding: {', '.join(member_missing)}. "
            "Department and designation are assigned separately by an administrator."
        )
        title = payload.title.strip() if payload.title else "Complete your profile"
        message = payload.message.strip() if payload.message else default_message
        if reminder is None:
            reminder = ProfileCompletionReminder(
                workspace_id=workspace_id, user_id=user.id, sent_by_id=current_user.id,
                title=title, message=message, completion_percent=percent,
            )
            db.add(reminder)
        else:
            reminder.sent_by_id = current_user.id
            reminder.title = title
            reminder.message = message
            reminder.completion_percent = percent
            reminder.is_read = False
            reminder.is_resolved = False
        sent_count += 1
    db.commit()
    return ProfileReminderResult(sent_count=sent_count)


def get_notification(db: DB, notification_id: int, user_id: int) -> Notification:
    notification = db.scalar(
        select(Notification).where(
            Notification.id == notification_id,
            Notification.user_id == user_id,
        )
    )
    if notification is None:
        raise HTTPException(status_code=404, detail="Notification not found")
    return notification


@router.patch("/read-all", response_model=NotificationReadAllResult)
def mark_all_normal_notifications_read(
    db: DB, current_user: CurrentUser
) -> NotificationReadAllResult:
    normal_notifications = list(db.scalars(select(Notification).where(
        Notification.user_id == current_user.id,
        Notification.severity != "critical",
        Notification.is_read.is_(False),
    )).all())
    profile_reminders = list(db.scalars(select(ProfileCompletionReminder).where(
        ProfileCompletionReminder.user_id == current_user.id,
        ProfileCompletionReminder.is_read.is_(False),
    )).all())
    global_profile_reminders = list(db.scalars(select(GlobalProfileReminder).where(
        GlobalProfileReminder.user_id == current_user.id, GlobalProfileReminder.is_read.is_(False)
    )).all())
    announcements = list(db.scalars(select(GlobalAnnouncement).where(
        GlobalAnnouncement.user_id == current_user.id, GlobalAnnouncement.is_read.is_(False)
    )).all())
    for notification in [*normal_notifications, *profile_reminders, *global_profile_reminders, *announcements]:
        notification.is_read = True
    db.commit()
    return NotificationReadAllResult(
        marked_count=len(normal_notifications) + len(profile_reminders) + len(global_profile_reminders) + len(announcements)
    )


@router.patch("/{notification_id}/read", response_model=NotificationRead)
def mark_notification_read(
    notification_id: str, db: DB, current_user: CurrentUser
) -> NotificationRead:
    if notification_id.startswith("announcement-"):
        try: item_id = int(notification_id.removeprefix("announcement-"))
        except ValueError as error: raise HTTPException(status_code=404, detail="Notification not found") from error
        item = db.scalar(select(GlobalAnnouncement).where(GlobalAnnouncement.id == item_id, GlobalAnnouncement.user_id == current_user.id))
        if item is None: raise HTTPException(status_code=404, detail="Notification not found")
        item.is_read = True; db.commit(); db.refresh(item)
        return NotificationRead(id=f"announcement-{item.id}", kind="announcement", severity="normal", title=item.title, message=item.message, is_read=True, is_acknowledged=False, is_resolved=False, created_at=item.created_at, updated_at=item.updated_at)
    if notification_id.startswith("global-profile-"):
        try: item_id = int(notification_id.removeprefix("global-profile-"))
        except ValueError as error: raise HTTPException(status_code=404, detail="Notification not found") from error
        item = db.scalar(select(GlobalProfileReminder).where(GlobalProfileReminder.id == item_id, GlobalProfileReminder.user_id == current_user.id))
        if item is None: raise HTTPException(status_code=404, detail="Notification not found")
        item.is_read = True; db.commit(); db.refresh(item)
        return NotificationRead(id=f"global-profile-{item.id}", kind="profile_completion", severity="normal", title=item.title, message=item.message, is_read=True, is_acknowledged=False, is_resolved=item.is_resolved, created_at=item.created_at, updated_at=item.updated_at)
    if notification_id.startswith("chat-"):
        try:
            alert_id = int(notification_id.removeprefix("chat-"))
        except ValueError as error:
            raise HTTPException(status_code=404, detail="Notification not found") from error
        alert = db.scalar(select(ChatNotification).where(
            ChatNotification.id == alert_id, ChatNotification.user_id == current_user.id,
        ))
        if alert is None:
            raise HTTPException(status_code=404, detail="Notification not found")
        alert.is_read = True; db.commit(); db.refresh(alert)
        return NotificationRead(
            id=f"chat-{alert.id}", workspace_id=alert.workspace_id,
            conversation_id=alert.conversation_id, kind="chat_message", severity="normal",
            title=alert.title, message=alert.message, is_read=True,
            is_acknowledged=False, is_resolved=False,
            created_at=alert.created_at, updated_at=alert.updated_at,
        )
    if notification_id.startswith("profile-"):
        try:
            reminder_id = int(notification_id.removeprefix("profile-"))
        except ValueError as error:
            raise HTTPException(status_code=404, detail="Notification not found") from error
        reminder = db.scalar(select(ProfileCompletionReminder).where(
            ProfileCompletionReminder.id == reminder_id,
            ProfileCompletionReminder.user_id == current_user.id,
        ))
        if reminder is None:
            raise HTTPException(status_code=404, detail="Notification not found")
        reminder.is_read = True
        db.commit();db.refresh(reminder)
        return NotificationRead(
            id=f"profile-{reminder.id}", workspace_id=reminder.workspace_id,
            kind="profile_completion", severity="normal", title=reminder.title,
            message=reminder.message, is_read=True, is_acknowledged=False,
            is_resolved=reminder.is_resolved, created_at=reminder.created_at,
            updated_at=reminder.updated_at,
        )
    try:
        numeric_id = int(notification_id)
    except ValueError as error:
        raise HTTPException(status_code=404, detail="Notification not found") from error
    notification = get_notification(db, numeric_id, current_user.id)
    if notification.severity == "critical" and not notification.is_acknowledged:
        raise HTTPException(
            status_code=400,
            detail="Critical task notifications must be acknowledged",
        )
    notification.is_read = True
    db.commit()
    db.refresh(notification)
    return NotificationRead(
        id=str(notification.id), workspace_id=notification.workspace_id,
        project_id=notification.project_id, task_id=notification.task_id,
        kind=notification.kind, severity=notification.severity, title=notification.title,
        message=notification.message, is_read=notification.is_read,
        is_acknowledged=notification.is_acknowledged, is_resolved=notification.is_resolved,
        created_at=notification.created_at, updated_at=notification.updated_at,
    )


@router.patch("/{notification_id}/acknowledge", response_model=NotificationRead)
def acknowledge_notification(
    notification_id: int, db: DB, current_user: CurrentUser
) -> NotificationRead:
    notification = get_notification(db, notification_id, current_user.id)
    notification.is_acknowledged = True
    notification.is_read = True
    notification.acknowledged_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(notification)
    return NotificationRead(
        id=str(notification.id), workspace_id=notification.workspace_id,
        project_id=notification.project_id, task_id=notification.task_id,
        kind=notification.kind, severity=notification.severity, title=notification.title,
        message=notification.message, is_read=notification.is_read,
        is_acknowledged=notification.is_acknowledged, is_resolved=notification.is_resolved,
        created_at=notification.created_at, updated_at=notification.updated_at,
    )

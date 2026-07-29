from datetime import date, datetime
from enum import Enum

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum as SqlEnum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class WorkspaceRole(str, Enum):
    admin = "admin"
    member = "member"


class ProjectStatus(str, Enum):
    planned = "planned"
    active = "active"
    on_hold = "on_hold"
    completed = "completed"


class Priority(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


class TaskStatus(str, Enum):
    backlog = "backlog"
    todo = "todo"
    in_progress = "in_progress"
    review = "review"
    testing = "testing"
    done = "done"


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    memberships: Mapped[list["WorkspaceMember"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class Workspace(TimestampMixin, Base):
    __tablename__ = "workspaces"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(150))
    description: Mapped[str | None] = mapped_column(Text)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"))

    members: Mapped[list["WorkspaceMember"]] = relationship(
        back_populates="workspace", cascade="all, delete-orphan"
    )
    teams: Mapped[list["Team"]] = relationship(
        back_populates="workspace", cascade="all, delete-orphan"
    )
    projects: Mapped[list["Project"]] = relationship(
        back_populates="workspace", cascade="all, delete-orphan"
    )


class WorkspaceMember(TimestampMixin, Base):
    __tablename__ = "workspace_members"
    __table_args__ = (
        UniqueConstraint("workspace_id", "user_id", name="uq_workspace_user"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE")
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE")
    )
    role: Mapped[WorkspaceRole] = mapped_column(
        SqlEnum(WorkspaceRole), default=WorkspaceRole.member
    )

    workspace: Mapped["Workspace"] = relationship(back_populates="members")
    user: Mapped["User"] = relationship(back_populates="memberships")


class Team(TimestampMixin, Base):
    __tablename__ = "teams"

    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(String(150))
    description: Mapped[str | None] = mapped_column(Text)

    workspace: Mapped["Workspace"] = relationship(back_populates="teams")


class Project(TimestampMixin, Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(String(180))
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[ProjectStatus] = mapped_column(
        SqlEnum(ProjectStatus), default=ProjectStatus.planned
    )
    priority: Mapped[Priority] = mapped_column(
        SqlEnum(Priority), default=Priority.medium
    )
    budget: Mapped[int | None] = mapped_column(Integer)
    deadline: Mapped[date | None] = mapped_column(Date)
    project_manager_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))

    workspace: Mapped["Workspace"] = relationship(back_populates="projects")
    sprints: Mapped[list["Sprint"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    tasks: Mapped[list["Task"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )


class Sprint(TimestampMixin, Base):
    __tablename__ = "sprints"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(String(150))
    goal: Mapped[str | None] = mapped_column(Text)
    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)

    project: Mapped["Project"] = relationship(back_populates="sprints")
    tasks: Mapped[list["Task"]] = relationship(back_populates="sprint")


class Task(TimestampMixin, Base):
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE")
    )
    sprint_id: Mapped[int | None] = mapped_column(
        ForeignKey("sprints.id", ondelete="SET NULL")
    )
    title: Mapped[str] = mapped_column(String(220))
    description: Mapped[str | None] = mapped_column(Text)
    priority: Mapped[Priority] = mapped_column(
        SqlEnum(Priority), default=Priority.medium
    )
    status: Mapped[TaskStatus] = mapped_column(
        SqlEnum(TaskStatus), default=TaskStatus.backlog
    )
    assignee_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    reporter_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    story_points: Mapped[int | None] = mapped_column(Integer)
    start_date: Mapped[date | None] = mapped_column(Date)
    due_date: Mapped[date | None] = mapped_column(Date)
    progress: Mapped[int] = mapped_column(Integer, default=0)

    project: Mapped["Project"] = relationship(back_populates="tasks")
    sprint: Mapped["Sprint | None"] = relationship(back_populates="tasks")
    comments: Mapped[list["Comment"]] = relationship(
        back_populates="task", cascade="all, delete-orphan"
    )
    task_assignees: Mapped[list["TaskAssignee"]] = relationship(
        back_populates="task", cascade="all, delete-orphan"
    )
    schedule: Mapped["TaskSchedule | None"] = relationship(
        back_populates="task", cascade="all, delete-orphan", uselist=False
    )
    checklist_items: Mapped[list["ChecklistItem"]] = relationship(
        back_populates="task",
        cascade="all, delete-orphan",
        order_by="ChecklistItem.position",
    )

    @property
    def assignee_ids(self) -> list[int]:
        return [item.user_id for item in self.task_assignees]

    @property
    def start_at(self) -> datetime | None:
        return self.schedule.start_at if self.schedule else None

    @property
    def end_at(self) -> datetime | None:
        return self.schedule.end_at if self.schedule else None

    @property
    def checklist_total(self) -> int:
        return len(self.checklist_items)

    @property
    def checklist_done(self) -> int:
        return sum(1 for item in self.checklist_items if item.is_done)


class Comment(TimestampMixin, Base):
    __tablename__ = "comments"

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE")
    )
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    body: Mapped[str] = mapped_column(Text)

    task: Mapped["Task"] = relationship(back_populates="comments")


class ProjectBoard(TimestampMixin, Base):
    __tablename__ = "project_boards"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), unique=True, index=True
    )
    framework: Mapped[str] = mapped_column(String(20), default="kanban")

    columns: Mapped[list["BoardColumn"]] = relationship(
        back_populates="board",
        cascade="all, delete-orphan",
        order_by="BoardColumn.position",
    )


class BoardColumn(TimestampMixin, Base):
    __tablename__ = "board_columns"
    __table_args__ = (
        UniqueConstraint("board_id", "position", name="uq_board_column_position"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    board_id: Mapped[int] = mapped_column(
        ForeignKey("project_boards.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(80))
    color: Mapped[str] = mapped_column(String(20), default="#8b97ac")
    position: Mapped[int] = mapped_column(Integer)
    system_status: Mapped[str | None] = mapped_column(String(30))

    board: Mapped["ProjectBoard"] = relationship(back_populates="columns")
    task_positions: Mapped[list["TaskBoardPosition"]] = relationship(
        back_populates="column", cascade="all, delete-orphan"
    )


class TaskBoardPosition(TimestampMixin, Base):
    __tablename__ = "task_board_positions"

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"), unique=True, index=True
    )
    column_id: Mapped[int] = mapped_column(
        ForeignKey("board_columns.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int] = mapped_column(Integer, default=0)

    column: Mapped["BoardColumn"] = relationship(back_populates="task_positions")


class TaskAssignee(TimestampMixin, Base):
    __tablename__ = "task_assignees"
    __table_args__ = (
        UniqueConstraint("task_id", "user_id", name="uq_task_assignee"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )

    task: Mapped["Task"] = relationship(back_populates="task_assignees")


class TaskSchedule(TimestampMixin, Base):
    __tablename__ = "task_schedules"

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"), unique=True, index=True
    )
    start_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    end_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    task: Mapped["Task"] = relationship(back_populates="schedule")


class ChecklistItem(TimestampMixin, Base):
    __tablename__ = "checklist_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"), index=True
    )
    text: Mapped[str] = mapped_column(String(500))
    is_done: Mapped[bool] = mapped_column(Boolean, default=False)
    position: Mapped[int] = mapped_column(Integer, default=0)

    task: Mapped["Task"] = relationship(back_populates="checklist_items")

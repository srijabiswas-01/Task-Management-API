from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator

from app.models import Priority, ProjectStatus, TaskStatus, WorkspaceRole


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class UserRegister(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class UserRead(ORMModel):
    id: int
    name: str
    email: EmailStr
    is_active: bool
    created_at: datetime


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class WorkspaceCreate(BaseModel):
    name: str = Field(min_length=2, max_length=150)
    description: str | None = None


class WorkspaceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=150)
    description: str | None = None


class WorkspaceRead(ORMModel):
    id: int
    name: str
    description: str | None
    owner_id: int
    created_at: datetime


class MemberAdd(BaseModel):
    email: EmailStr
    role: WorkspaceRole = WorkspaceRole.member


class MemberRead(ORMModel):
    id: int
    workspace_id: int
    user_id: int
    role: WorkspaceRole
    user: UserRead


class TeamCreate(BaseModel):
    name: str = Field(min_length=2, max_length=150)
    description: str | None = None


class TeamRead(ORMModel):
    id: int
    workspace_id: int
    name: str
    description: str | None
    created_at: datetime


class TeamMemberAdd(BaseModel):
    user_id: int
    project_id: int
    designation: str = Field(min_length=2, max_length=120)


class TeamMemberRead(ORMModel):
    id: int
    team_id: int
    user_id: int
    project_id: int
    designation: str
    user: UserRead
    project: "ProjectRead"


class DateRangeModel(BaseModel):
    start_date: date | None = None
    end_date: date | None = None

    @model_validator(mode="after")
    def validate_dates(self):
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValueError("end_date must be on or after start_date")
        return self


class ProjectCreate(BaseModel):
    name: str = Field(min_length=2, max_length=180)
    description: str | None = None
    status: ProjectStatus = ProjectStatus.planned
    priority: Priority = Priority.medium
    budget: int | None = Field(default=None, ge=0)
    deadline: date | None = None
    project_manager_id: int | None = None


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=180)
    description: str | None = None
    status: ProjectStatus | None = None
    priority: Priority | None = None
    budget: int | None = Field(default=None, ge=0)
    deadline: date | None = None
    project_manager_id: int | None = None


class ProjectRead(ORMModel):
    id: int
    workspace_id: int
    name: str
    description: str | None
    status: ProjectStatus
    priority: Priority
    budget: int | None
    deadline: date | None
    project_manager_id: int | None
    created_at: datetime


class SprintCreate(DateRangeModel):
    name: str = Field(min_length=2, max_length=150)
    goal: str | None = None
    is_active: bool = False


class SprintRead(ORMModel):
    id: int
    project_id: int
    name: str
    goal: str | None
    start_date: date | None
    end_date: date | None
    is_active: bool
    created_at: datetime


class SprintUpdate(DateRangeModel):
    name: str | None = Field(default=None, min_length=2, max_length=150)
    goal: str | None = None
    is_active: bool | None = None


class TaskCreate(BaseModel):
    title: str = Field(min_length=2, max_length=220)
    description: str | None = None
    sprint_id: int | None = None
    priority: Priority = Priority.medium
    status: TaskStatus = TaskStatus.backlog
    assignee_id: int | None = None
    assignee_ids: list[int] = Field(default_factory=list)
    story_points: int | None = Field(default=None, ge=0, le=100)
    start_date: date | None = None
    due_date: date | None = None
    progress: int = Field(default=0, ge=0, le=100)
    start_at: datetime | None = None
    end_at: datetime | None = None

    @model_validator(mode="after")
    def validate_dates(self):
        if self.start_date and self.due_date and self.due_date < self.start_date:
            raise ValueError("due_date must be on or after start_date")
        if self.start_at and self.end_at and self.end_at < self.start_at:
            raise ValueError("end_at must be on or after start_at")
        return self


class TaskUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=2, max_length=220)
    description: str | None = None
    sprint_id: int | None = None
    priority: Priority | None = None
    status: TaskStatus | None = None
    assignee_id: int | None = None
    assignee_ids: list[int] | None = None
    story_points: int | None = Field(default=None, ge=0, le=100)
    start_date: date | None = None
    due_date: date | None = None
    progress: int | None = Field(default=None, ge=0, le=100)
    start_at: datetime | None = None
    end_at: datetime | None = None

    @model_validator(mode="after")
    def validate_dates(self):
        if self.start_date and self.due_date and self.due_date < self.start_date:
            raise ValueError("due_date must be on or after start_date")
        if self.start_at and self.end_at and self.end_at < self.start_at:
            raise ValueError("end_at must be on or after start_at")
        return self


class TaskRead(ORMModel):
    id: int
    project_id: int
    sprint_id: int | None
    title: str
    description: str | None
    priority: Priority
    status: TaskStatus
    assignee_id: int | None
    assignee_ids: list[int] = Field(default_factory=list)
    reporter_id: int
    story_points: int | None
    start_date: date | None
    due_date: date | None
    progress: int
    start_at: datetime | None = None
    end_at: datetime | None = None
    checklist_total: int = 0
    checklist_done: int = 0
    created_at: datetime
    updated_at: datetime


class AITaskPlanRequest(BaseModel):
    prompt: str = Field(min_length=10, max_length=4000)
    maximum_tasks: int = Field(default=10, ge=1, le=50)


class AIGeneratedTask(BaseModel):
    title: str = Field(min_length=2, max_length=220)
    description: str | None = Field(default=None, max_length=3000)
    priority: Priority = Priority.medium
    story_points: int | None = Field(default=None, ge=0, le=100)


class AIGeneratedPlan(BaseModel):
    summary: str = Field(min_length=2, max_length=500)
    tasks: list[AIGeneratedTask] = Field(min_length=1, max_length=50)


class AITaskPlanResponse(AIGeneratedPlan):
    provider: str
    model: str
    fallback_used: bool = False


class AITaskPlanConfirm(BaseModel):
    tasks: list[AIGeneratedTask] = Field(min_length=1, max_length=50)


class CommentCreate(BaseModel):
    body: str = Field(min_length=1, max_length=5000)


class CommentRead(ORMModel):
    id: int
    task_id: int
    author_id: int
    body: str
    created_at: datetime


class ChecklistItemCreate(BaseModel):
    text: str = Field(min_length=1, max_length=500)


class ChecklistItemUpdate(BaseModel):
    text: str | None = Field(default=None, min_length=1, max_length=500)
    is_done: bool | None = None
    position: int | None = Field(default=None, ge=0)


class ChecklistItemRead(ORMModel):
    id: int
    task_id: int
    text: str
    is_done: bool
    position: int
    created_at: datetime


class DashboardSummary(BaseModel):
    projects: int
    active_projects: int
    tasks: int
    completed_tasks: int
    overdue_tasks: int
    completion_percent: float


class BoardSetup(BaseModel):
    framework: str = Field(pattern="^(scrum|kanban)$")
    reset: bool = False


class BoardColumnCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    color: str = Field(default="#8b97ac", pattern=r"^#[0-9a-fA-F]{6}$")
    system_status: str | None = Field(
        default=None,
        pattern="^(backlog|todo|in_progress|review|testing|done)$",
    )


class BoardColumnUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    color: str | None = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")
    system_status: str | None = Field(
        default=None,
        pattern="^(backlog|todo|in_progress|review|testing|done)$",
    )


class BoardColumnRead(ORMModel):
    id: int
    name: str
    color: str
    position: int
    system_status: str | None


class BoardRead(BaseModel):
    id: int
    project_id: int
    framework: str
    columns: list[BoardColumnRead]
    task_positions: dict[int, dict[str, int]]


class ColumnReorder(BaseModel):
    column_ids: list[int] = Field(min_length=1)


class TaskMove(BaseModel):
    column_id: int
    position: int = Field(default=0, ge=0)

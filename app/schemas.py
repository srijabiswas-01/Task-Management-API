from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator

from app.models import ChatType, Priority, ProjectStatus, TaskStatus, WorkspaceRole


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
    is_system_admin: bool = False
    profile_image: str | None = None
    created_at: datetime


class UserProfileUpdate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    profile_image: str | None = Field(default=None, max_length=3_000_000)
    phone: str | None = Field(default=None, max_length=40)
    location: str | None = Field(default=None, max_length=150)
    bio: str | None = Field(default=None, max_length=3000)
    professional_title: str | None = Field(default=None, max_length=150)
    department: str | None = Field(default=None, max_length=150)
    years_experience: int | None = Field(default=None, ge=0, le=80)
    skills: str | None = Field(default=None, max_length=3000)
    achievements: str | None = Field(default=None, max_length=5000)


class UserProfileRead(UserProfileUpdate):
    email: EmailStr
    project_count: int = 0
    projects: list[str] = Field(default_factory=list)
    completion_percent: int = 0
    missing_fields: list[str] = Field(default_factory=list)


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class WorkspaceCreate(BaseModel):
    name: str = Field(min_length=2, max_length=150)
    description: str | None = None


class WorkspaceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=150)
    description: str | None = None


class WorkspaceDeleteConfirm(BaseModel):
    workspace_name: str = Field(min_length=2, max_length=150)


class WorkspaceRead(ORMModel):
    id: int
    name: str
    description: str | None
    owner_id: int
    role: WorkspaceRole | None = None
    created_at: datetime


class NotificationRead(ORMModel):
    id: str
    workspace_id: int
    project_id: int | None = None
    task_id: int | None = None
    conversation_id: int | None = None
    kind: str
    severity: str
    title: str
    message: str
    is_read: bool
    is_acknowledged: bool
    is_resolved: bool
    created_at: datetime
    updated_at: datetime


class NotificationList(BaseModel):
    items: list[NotificationRead]
    unread_count: int
    critical_count: int


class ProfileReminderSend(BaseModel):
    user_ids: list[int] = Field(min_length=1, max_length=100)
    title: str | None = Field(default=None, min_length=2, max_length=220)
    message: str | None = Field(default=None, min_length=2, max_length=3000)


class ProfileReminderResult(BaseModel):
    sent_count: int


class NotificationReadAllResult(BaseModel):
    marked_count: int


class ChatUserRead(BaseModel):
    id: int
    name: str
    email: str
    profile_image: str | None = None


class ChatConversationCreate(BaseModel):
    chat_type: ChatType
    name: str | None = Field(default=None, max_length=180)
    project_id: int | None = None
    team_id: int | None = None
    recipient_id: int | None = None


class ChatMessageCreate(BaseModel):
    body: str = Field(min_length=1, max_length=5000)


class ChatMessageRead(BaseModel):
    id: int
    conversation_id: int
    sender: ChatUserRead
    body: str
    is_deleted: bool = False
    deleted_by_id: int | None = None
    created_at: datetime


class ChatConversationRead(BaseModel):
    id: int
    workspace_id: int
    chat_type: ChatType
    name: str
    project_id: int | None
    team_id: int | None
    participants: list[ChatUserRead]
    last_message: ChatMessageRead | None
    unread_count: int
    can_send: bool
    can_clear: bool = False


class ChatScopeRead(BaseModel):
    id: int
    name: str


class ChatOptionsRead(BaseModel):
    recipients: list[ChatUserRead]
    projects: list[ChatScopeRead]
    teams: list[ChatScopeRead]
    can_broadcast: bool


class MemberAdd(BaseModel):
    email: EmailStr
    role: WorkspaceRole = WorkspaceRole.member


class MemberRead(ORMModel):
    id: int
    workspace_id: int
    user_id: int
    role: WorkspaceRole
    is_active: bool
    user: UserRead
    professional_title: str | None = None
    department: str | None = None


class MemberProfessionalUpdate(BaseModel):
    professional_title: str | None = Field(default=None, max_length=150)
    department: str | None = Field(default=None, max_length=150)


class MemberAccessUpdate(BaseModel):
    is_active: bool | None = None
    role: WorkspaceRole | None = None


class UserDirectoryRead(BaseModel):
    user_id: int
    name: str
    email: EmailStr
    is_active: bool
    membership_id: int | None = None
    membership_is_active: bool | None = None
    role: WorkspaceRole | None = None
    professional_title: str | None = None
    department: str | None = None
    profile_image: str | None = None
    projects: list[str] = Field(default_factory=list)
    completion_percent: int = 0
    missing_fields: list[str] = Field(default_factory=list)


class SkillMemberRead(BaseModel):
    user_id: int
    name: str
    email: EmailStr
    professional_title: str | None = None
    department: str | None = None
    profile_image: str | None = None
    skills: list[str] = Field(default_factory=list)
    project_ids: list[int] = Field(default_factory=list)


class DesignationCreate(BaseModel):
    department_id: int
    name: str = Field(min_length=2, max_length=120)
    description: str | None = Field(default=None, max_length=1000)


class DesignationUpdate(BaseModel):
    department_id: int | None = None
    name: str | None = Field(default=None, min_length=2, max_length=120)
    description: str | None = Field(default=None, max_length=1000)


class DesignationRead(ORMModel):
    id: int
    workspace_id: int | None = None
    name: str
    description: str | None
    department_id: int | None = None
    department_name: str | None = None
    created_at: datetime


class DepartmentCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    description: str | None = Field(default=None, max_length=1000)


class DepartmentUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    description: str | None = Field(default=None, max_length=1000)


class DepartmentRead(ORMModel):
    id: int
    workspace_id: int | None = None
    name: str
    description: str | None
    created_at: datetime


class TeamCreate(BaseModel):
    name: str = Field(min_length=2, max_length=150)
    description: str | None = None
    manager_user_id: int
    manager_designation: str = Field(min_length=2, max_length=120)


class TeamUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=150)
    description: str | None = None
    manager_user_id: int | None = None
    manager_designation: str | None = Field(default=None, min_length=2, max_length=120)


class TeamRead(ORMModel):
    id: int
    workspace_id: int
    name: str
    description: str | None
    manager_user_id: int | None = None
    manager_designation: str | None = None
    manager_user: UserRead | None = None
    created_at: datetime


class TeamMemberAdd(BaseModel):
    user_id: int
    project_id: int
    designation: str = Field(min_length=2, max_length=120)
    allocation_percent: int = Field(default=100, ge=1, le=100)
    weekly_capacity_hours: int = Field(default=40, ge=1, le=168)


class TeamMemberUpdate(BaseModel):
    project_id: int
    designation: str = Field(min_length=2, max_length=120)
    allocation_percent: int = Field(default=100, ge=1, le=100)
    weekly_capacity_hours: int = Field(default=40, ge=1, le=168)


class TeamMemberRead(ORMModel):
    id: int
    team_id: int
    user_id: int
    project_id: int
    designation: str
    allocation_percent: int = 100
    weekly_capacity_hours: int = 40
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
    contingency_percent: int = Field(default=15, ge=0, le=50)
    deadline: date | None = None
    start_date: date
    end_date: date
    project_manager_id: int | None = None

    @model_validator(mode="after")
    def validate_project_dates(self):
        if self.end_date < self.start_date:
            raise ValueError("end_date must be on or after start_date")
        return self


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=180)
    description: str | None = None
    status: ProjectStatus | None = None
    priority: Priority | None = None
    budget: int | None = Field(default=None, ge=0)
    contingency_percent: int | None = Field(default=None, ge=0, le=50)
    deadline: date | None = None
    start_date: date | None = None
    end_date: date | None = None
    project_manager_id: int | None = None


class ProjectRead(ORMModel):
    id: int
    workspace_id: int
    name: str
    description: str | None
    status: ProjectStatus
    priority: Priority
    budget: int | None
    contingency_percent: int = 15
    deadline: date | None
    start_date: date
    end_date: date
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
    estimated_hours: int | None = Field(default=None, ge=0, le=5000)
    planned_budget: int | None = Field(default=None, ge=0)
    actual_cost: int | None = Field(default=None, ge=0)
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
    estimated_hours: int | None = Field(default=None, ge=0, le=5000)
    planned_budget: int | None = Field(default=None, ge=0)
    actual_cost: int | None = Field(default=None, ge=0)
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


class TaskCompletionUpdate(BaseModel):
    is_completed: bool


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
    estimated_hours: int | None = None
    planned_budget: int | None = None
    actual_cost: int | None = None
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
    maximum_tasks: int = Field(default=20, ge=1, le=20)
    team_id: int


class AIGeneratedTask(BaseModel):
    title: str = Field(min_length=2, max_length=220)
    description: str | None = Field(default=None, max_length=3000)
    priority: Priority = Priority.medium
    story_points: int | None = Field(default=None, ge=0, le=100)
    estimated_hours: int | None = Field(default=None, ge=0, le=5000)
    planned_budget: int | None = Field(default=None, ge=0)
    assignee_ids: list[int] = Field(default_factory=list)
    start_date: date | None = None
    end_date: date | None = None
    checklist: list[str] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def validate_generated_dates(self):
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValueError("end_date must be on or after start_date")
        self.checklist = list(dict.fromkeys(
            item.strip() for item in self.checklist if item.strip()
        ))
        return self


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
    created_by_id: int | None = None
    last_action_by_id: int | None = None
    last_action: str | None = None
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

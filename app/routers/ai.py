from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from app.core.config import settings
from app.dependencies import CurrentUser, DB, require_project_admin
from app.models import ChecklistAction, ChecklistItem, Task, TaskAssignee, TaskStatus, Team, TeamMember
from app.routers.projects import accessible_project
from app.routers.tasks import set_task_schedule, sync_board_column_to_status
from app.schemas import (
    AITaskPlanConfirm,
    AITaskPlanRequest,
    AITaskPlanResponse,
    TaskRead,
)
from app.services.ai_planner import AIProvidersUnavailable, generate_task_plan

router = APIRouter(tags=["AI task planning"])


@router.post(
    "/projects/{project_id}/ai/task-plan",
    response_model=AITaskPlanResponse,
)
def plan_tasks(
    project_id: int,
    payload: AITaskPlanRequest,
    db: DB,
    current_user: CurrentUser,
) -> AITaskPlanResponse:
    project = accessible_project(db, project_id, current_user.id)
    team = db.get(Team, payload.team_id)
    if team is None or team.workspace_id != project.workspace_id:
        raise HTTPException(status_code=400, detail="Select a team in this workspace")
    allocations = list(db.scalars(select(TeamMember).where(TeamMember.team_id == team.id, TeamMember.project_id == project.id)).all())
    if not allocations:
        raise HTTPException(status_code=400, detail="Allocate at least one team member to this project before AI planning")
    try:
        plan, provider, model, fallback_used = generate_task_plan(
            project.name,
            payload.prompt.strip(),
            payload.maximum_tasks,
            project.start_date,
            project.end_date,
        )
    except AIProvidersUnavailable as exc:
        raise HTTPException(
            status_code=503,
            detail=(
                "Every AI provider is currently unavailable. "
                "Check provider keys, quotas, and model names."
            ),
        ) from exc
    delivery_budget = (project.budget or 0) * (100 - project.contingency_percent) // 100
    total_weight = sum(task.story_points or 1 for task in plan.tasks) or len(plan.tasks)
    for index, task in enumerate(plan.tasks):
        task.assignee_ids = [allocations[index % len(allocations)].user_id]
        task.estimated_hours = max(1, (task.story_points or 1) * 4)
        task.planned_budget = delivery_budget * (task.story_points or 1) // total_weight if delivery_budget else None
    return AITaskPlanResponse(
        **plan.model_dump(),
        provider=provider,
        model=model,
        fallback_used=fallback_used,
    )


@router.post(
    "/projects/{project_id}/ai/task-plan/confirm",
    response_model=list[TaskRead],
    status_code=201,
)
def confirm_task_plan(
    project_id: int,
    payload: AITaskPlanConfirm,
    db: DB,
    current_user: CurrentUser,
) -> list[Task]:
    require_project_admin(db, project_id, current_user.id)
    project = accessible_project(db, project_id, current_user.id)
    if len(payload.tasks) > settings.ai_max_tasks:
        raise HTTPException(
            status_code=400,
            detail=f"A maximum of {settings.ai_max_tasks} tasks can be created at once",
        )

    tasks: list[Task] = []
    try:
        for generated in payload.tasks:
            if generated.start_date is None or generated.end_date is None:
                raise HTTPException(status_code=400, detail="Every AI task requires start and end dates")
            if (generated.start_date < project.start_date or
                generated.end_date > project.end_date or
                generated.end_date < generated.start_date):
                raise HTTPException(
                    status_code=400,
                    detail=f"AI task dates must be between {project.start_date} and {project.end_date}",
                )
            task = Task(
                project_id=project_id,
                reporter_id=current_user.id,
                title=generated.title.strip(),
                description=(
                    generated.description.strip()
                    if generated.description
                    else None
                ),
                priority=generated.priority,
                status=TaskStatus.backlog,
                start_date=generated.start_date,
                due_date=generated.end_date,
            )
            task.story_points = generated.story_points
            task.estimated_hours = generated.estimated_hours
            task.planned_budget = generated.planned_budget
            set_task_schedule(task, None, None)
            db.add(task)
            db.flush()
            for user_id in generated.assignee_ids:
                db.add(TaskAssignee(task_id=task.id, user_id=user_id))
            for position, text_value in enumerate(generated.checklist):
                item = ChecklistItem(text=text_value.strip(), position=position)
                item.actions.append(ChecklistAction(user_id=current_user.id, action="created"))
                task.checklist_items.append(item)
            sync_board_column_to_status(db, task)
            tasks.append(task)
        db.commit()
    except Exception:
        db.rollback()
        raise

    for task in tasks:
        db.refresh(task)
    return tasks

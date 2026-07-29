from fastapi import APIRouter, HTTPException

from app.core.config import settings
from app.dependencies import CurrentUser, DB, require_project_admin
from app.models import Task, TaskStatus
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
    try:
        plan, provider, model, fallback_used = generate_task_plan(
            project.name,
            payload.prompt.strip(),
            payload.maximum_tasks,
        )
    except AIProvidersUnavailable as exc:
        raise HTTPException(
            status_code=503,
            detail=(
                "Every AI provider is currently unavailable. "
                "Check provider keys, quotas, and model names."
            ),
        ) from exc
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
            )
            task.story_points = generated.story_points
            set_task_schedule(task, None, None)
            db.add(task)
            db.flush()
            sync_board_column_to_status(db, task)
            tasks.append(task)
        db.commit()
    except Exception:
        db.rollback()
        raise

    for task in tasks:
        db.refresh(task)
    return tasks

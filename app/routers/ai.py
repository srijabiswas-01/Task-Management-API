from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from app.core.config import settings
from app.dependencies import CurrentUser, DB, require_project_admin
from app.models import ChecklistAction, ChecklistItem, GlobalTeamMember, Task, TaskStatus, Team, TeamMember
from app.routers.projects import accessible_project
from app.routers.tasks import set_task_assignments, set_task_assignees, set_task_schedule, sync_board_column_to_status, working_days
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
    selected_team_ids = list(dict.fromkeys(payload.team_ids + ([payload.team_id] if payload.team_id is not None else [])))
    candidate_assignments: list[tuple[int, int]] = []
    if selected_team_ids:
        teams = list(db.scalars(select(Team).where(Team.id.in_(selected_team_ids))).all())
        if len(teams) != len(selected_team_ids) or any(team.workspace_id not in (None, project.workspace_id) for team in teams):
            raise HTTPException(status_code=400, detail="Select valid delivery teams")
        global_team_ids = [team.id for team in teams if team.workspace_id is None]
        workspace_team_ids = [team.id for team in teams if team.workspace_id is not None]
        if global_team_ids:
            candidate_assignments.extend(db.execute(
                select(GlobalTeamMember.user_id, GlobalTeamMember.team_id).where(GlobalTeamMember.team_id.in_(global_team_ids))
            ).all())
        if workspace_team_ids:
            # Legacy workspace teams may contribute members without requiring
            # those people to be pre-allocated to this project.
            candidate_assignments.extend(db.execute(
                select(TeamMember.user_id, TeamMember.team_id).where(TeamMember.team_id.in_(workspace_team_ids))
            ).all())
        candidate_assignments = list(dict.fromkeys(candidate_assignments))
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
        recommendation = candidate_assignments[index % len(candidate_assignments)] if candidate_assignments else None
        task.team_ids = selected_team_ids
        task.assignee_ids = [recommendation[0]] if recommendation else []
        task.assignments = ([{"user_id": recommendation[0], "team_id": recommendation[1], "responsibility": task.title, "planned_hours": max(1, (task.story_points or 1) * 4)}] if recommendation else [])
        task.estimated_days = working_days(db, task.start_date, task.end_date)
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
            task.estimated_days = generated.estimated_days or working_days(db, generated.start_date, generated.end_date)
            task.planned_budget = generated.planned_budget
            set_task_schedule(task, None, None)
            db.add(task)
            db.flush()
            if generated.assignments:
                set_task_assignments(db, task, project, [item.model_dump() for item in generated.assignments])
            else:
                set_task_assignees(db, task, project, generated.assignee_ids)
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

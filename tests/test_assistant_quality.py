"""Quality checks for deterministic, permission-scoped assistant answers."""

from app.assistant.service import _grounded_operational_answer


def assistant_context() -> dict:
    return {
        "scope": "organization",
        "summary": {"planned_task_budget": 120000, "actual_task_cost": 45000},
        "tasks": [
            {"title": "Release API", "project_name": "Orbit", "status": "in_progress", "progress": 60, "due": "2020-01-01", "priority": "high", "remaining_checklist_items": ["Load test API"]},
            {"title": "Publish guide", "project_name": "Orbit", "status": "done", "progress": 100, "due": "2020-01-02", "priority": "medium", "remaining_checklist_items": []},
        ],
        "project_delivery": [
            {"name": "Orbit", "overdue_tasks": 1, "average_progress": 80.0, "completed_tasks": 1, "tasks": 2, "planned_task_budget": 120000, "actual_task_cost": 45000},
        ],
        "authorized_people": [
            {"name": "Sam", "assigned_tasks": 2, "planned_hours": 24, "designation": "Developer"},
        ],
        "managed_or_joined_teams": [{"id": 1, "name": "Delivery"}],
    }


def test_risk_answer_names_projects_tasks_and_actions() -> None:
    answer = _grounded_operational_answer("Which projects are at risk?", assistant_context())
    assert answer is not None
    assert "Orbit" in answer
    assert "Release API" in answer
    assert "Recommended action" in answer


def test_workload_and_checklist_answers_include_operational_details() -> None:
    workload = _grounded_operational_answer("Compare current workloads", assistant_context())
    checklist = _grounded_operational_answer("Which checklist items remain?", assistant_context())
    assert workload is not None and "Sam" in workload and "24 planned hours" in workload
    assert checklist is not None and "Load test API" in checklist and "Release API" in checklist


def test_unknown_question_is_left_for_configured_ai_provider() -> None:
    assert _grounded_operational_answer("Explain the strategic trade-offs", assistant_context()) is None

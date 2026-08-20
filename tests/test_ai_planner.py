from app.schemas import AIGeneratedPlan, AIGeneratedTask
from app.services import ai_planner


def test_ai_plan_preview_and_confirmation_create_board_tasks(
    client, auth_headers, monkeypatch
):
    workspace_id = client.post(
        "/workspaces",
        json={"name": "AI Workspace"},
        headers=auth_headers,
    ).json()["id"]
    project_id = client.post(
        f"/workspaces/{workspace_id}/projects",
        json={"name": "Mobile Application", "start_date": "2026-08-01", "end_date": "2026-12-31"},
        headers=auth_headers,
    ).json()["id"]
    board = client.get(
        f"/projects/{project_id}/board",
        headers=auth_headers,
    ).json()

    generated = AIGeneratedPlan(
        summary="A practical mobile delivery plan",
        tasks=[
            AIGeneratedTask(
                title="Design the mobile interface",
                description="Create the core screens and navigation.",
                priority="high",
                story_points=5,
                start_date="2026-08-01",
                end_date="2026-09-30",
                checklist=["Approve interface review"],
            ),
            AIGeneratedTask(
                title="Implement authentication",
                description="Add secure registration and login.",
                priority="critical",
                story_points=8,
                start_date="2026-10-01",
                end_date="2026-12-31",
                checklist=["Verify login", "Verify registration"],
            ),
        ],
    )

    monkeypatch.setattr(
        "app.routers.ai.generate_task_plan",
        lambda *_: (generated, "groq", "test-model", True),
    )

    preview = client.post(
        f"/projects/{project_id}/ai/task-plan",
        json={
            "prompt": "Build a secure mobile application for customers",
            "maximum_tasks": 10,
        },
        headers=auth_headers,
    )
    assert preview.status_code == 200
    assert preview.json()["provider"] == "groq"
    assert preview.json()["fallback_used"] is True
    assert preview.json()["tasks"][0]["start_date"] == "2026-08-01"
    assert preview.json()["tasks"][1]["end_date"] == "2026-12-31"

    confirmed = client.post(
        f"/projects/{project_id}/ai/task-plan/confirm",
        json={"tasks": preview.json()["tasks"]},
        headers=auth_headers,
    )
    assert confirmed.status_code == 201
    assert len(confirmed.json()) == 2
    assert {task["status"] for task in confirmed.json()} == {"backlog"}
    assert confirmed.json()[0]["start_date"] == "2026-08-01"
    assert confirmed.json()[1]["due_date"] == "2026-12-31"
    checklist = client.get(
        f"/tasks/{confirmed.json()[0]['id']}/checklist", headers=auth_headers
    )
    assert [item["text"] for item in checklist.json()] == ["Approve interface review"]

    updated_board = client.get(
        f"/projects/{project_id}/board",
        headers=auth_headers,
    ).json()
    backlog = next(
        column
        for column in board["columns"]
        if column["system_status"] == "backlog"
    )
    for task in confirmed.json():
        assert (
            updated_board["task_positions"][str(task["id"])]["column_id"]
            == backlog["id"]
        )


def test_provider_failure_uses_next_configured_provider(monkeypatch):
    monkeypatch.setattr(
        ai_planner.settings,
        "ai_provider_order",
        ["gemini", "groq"],
    )
    monkeypatch.setitem(
        ai_planner.PROVIDERS,
        "gemini",
        lambda _: (_ for _ in ()).throw(ValueError("quota exceeded")),
    )
    monkeypatch.setitem(
        ai_planner.PROVIDERS,
        "groq",
        lambda _: (
            "fallback-model",
            """
            {
              "summary": "Fallback plan",
              "tasks": [{
                "title": "Define project requirements",
                "description": "Document the required outcomes.",
                "priority": "medium",
                "story_points": 3
              }]
            }
            """,
        ),
    )

    plan, provider, model, fallback_used = ai_planner.generate_task_plan(
        "Fallback Project",
        "Create a complete delivery plan for this software project",
        10,
    )

    assert plan.summary == "Fallback plan"
    assert provider == "groq"
    assert model == "fallback-model"
    assert fallback_used is True

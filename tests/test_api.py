from fastapi.testclient import TestClient


def test_frontend_routes_return_the_application(client: TestClient):
    for path in ("/app/overview", "/app/projects", "/app/board", "/app/gantt"):
        response = client.get(path)
        assert response.status_code == 200
        assert "Orbit Tasks" in response.text


def test_register_login_and_me(client: TestClient):
    registered = client.post(
        "/auth/register",
        json={
            "name": "Jane Doe",
            "email": "jane@example.com",
            "password": "securepass123",
        },
    )
    assert registered.status_code == 201
    assert "password" not in registered.json()

    logged_in = client.post(
        "/auth/login",
        data={"username": "jane@example.com", "password": "securepass123"},
    )
    assert logged_in.status_code == 200
    token = logged_in.json()["access_token"]

    me = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["email"] == "jane@example.com"


def test_core_project_flow(client: TestClient, auth_headers: dict[str, str]):
    workspace = client.post(
        "/workspaces",
        json={"name": "Acme Workspace"},
        headers=auth_headers,
    )
    assert workspace.status_code == 201
    workspace_id = workspace.json()["id"]

    project = client.post(
        f"/workspaces/{workspace_id}/projects",
        json={"name": "Platform", "status": "active", "priority": "high"},
        headers=auth_headers,
    )
    assert project.status_code == 201
    project_id = project.json()["id"]
    client.put(
        f"/projects/{project_id}/board",
        json={"framework": "scrum"},
        headers=auth_headers,
    )

    sprint = client.post(
        f"/projects/{project_id}/sprints",
        json={"name": "Sprint 1", "goal": "Ship the API"},
        headers=auth_headers,
    )
    assert sprint.status_code == 201

    task = client.post(
        f"/projects/{project_id}/tasks",
        json={
            "title": "Implement JWT",
            "priority": "high",
            "story_points": 5,
        },
        headers=auth_headers,
    )
    assert task.status_code == 201
    task_id = task.json()["id"]

    updated = client.patch(
        f"/tasks/{task_id}",
        json={"status": "done"},
        headers=auth_headers,
    )
    assert updated.status_code == 200
    assert updated.json()["progress"] == 100

    dashboard = client.get(
        f"/workspaces/{workspace_id}/dashboard", headers=auth_headers
    )
    assert dashboard.status_code == 200
    assert dashboard.json()["completion_percent"] == 100


def test_custom_board_and_drag_positions(
    client: TestClient, auth_headers: dict[str, str]
):
    workspace_id = client.post(
        "/workspaces",
        json={"name": "Board Workspace"},
        headers=auth_headers,
    ).json()["id"]
    project_id = client.post(
        f"/workspaces/{workspace_id}/projects",
        json={"name": "Scrum Product"},
        headers=auth_headers,
    ).json()["id"]

    board = client.put(
        f"/projects/{project_id}/board",
        json={"framework": "scrum"},
        headers=auth_headers,
    )
    assert board.status_code == 200
    assert board.json()["framework"] == "scrum"
    assert [column["name"] for column in board.json()["columns"]][:2] == [
        "Product backlog",
        "Sprint backlog",
    ]

    custom_column = client.post(
        f"/projects/{project_id}/board/columns",
        json={"name": "Blocked", "color": "#df5261"},
        headers=auth_headers,
    )
    assert custom_column.status_code == 201
    blocked_id = custom_column.json()["id"]
    mapped = client.patch(
        f"/projects/{project_id}/board/columns/{blocked_id}",
        json={"system_status": "review"},
        headers=auth_headers,
    )
    assert mapped.status_code == 200

    task_id = client.post(
        f"/projects/{project_id}/tasks",
        json={"title": "Resolve dependency"},
        headers=auth_headers,
    ).json()["id"]
    moved = client.put(
        f"/tasks/{task_id}/board-position",
        json={"column_id": blocked_id, "position": 0},
        headers=auth_headers,
    )
    assert moved.status_code == 200
    assert moved.json()["task_positions"][str(task_id)]["column_id"] == blocked_id
    assert (
        client.get(f"/tasks/{task_id}", headers=auth_headers).json()["status"]
        == "review"
    )

    column_ids = [column["id"] for column in moved.json()["columns"]]
    reordered = client.put(
        f"/projects/{project_id}/board/column-order",
        json={"column_ids": list(reversed(column_ids))},
        headers=auth_headers,
    )
    assert reordered.status_code == 200
    assert reordered.json()["columns"][0]["id"] == blocked_id

    restored = client.put(
        f"/projects/{project_id}/board",
        json={"framework": "kanban", "reset": True},
        headers=auth_headers,
    )
    assert restored.status_code == 200
    assert [column["name"] for column in restored.json()["columns"]] == [
        "Backlog",
        "To do",
        "In progress",
        "Review",
        "Testing",
        "Done",
    ]
    assert str(task_id) in restored.json()["task_positions"]


def test_workspace_owner_can_delete_workspace_and_all_children(
    client: TestClient, auth_headers: dict[str, str]
):
    workspace_id = client.post(
        "/workspaces",
        json={"name": "Temporary Workspace"},
        headers=auth_headers,
    ).json()["id"]
    project_id = client.post(
        f"/workspaces/{workspace_id}/projects",
        json={"name": "Temporary Project"},
        headers=auth_headers,
    ).json()["id"]
    task_id = client.post(
        f"/projects/{project_id}/tasks",
        json={"title": "Temporary Task"},
        headers=auth_headers,
    ).json()["id"]
    client.post(
        f"/tasks/{task_id}/comments",
        json={"body": "Temporary comment"},
        headers=auth_headers,
    )
    client.get(f"/projects/{project_id}/board", headers=auth_headers)

    workspace_update = client.patch(
        f"/workspaces/{workspace_id}",
        json={"name": "Renamed Workspace", "description": "Updated"},
        headers=auth_headers,
    )
    assert workspace_update.status_code == 200
    assert workspace_update.json()["name"] == "Renamed Workspace"
    project_update = client.patch(
        f"/projects/{project_id}",
        json={"name": "Renamed Project", "priority": "critical"},
        headers=auth_headers,
    )
    assert project_update.status_code == 200
    assert project_update.json()["priority"] == "critical"

    deleted = client.delete(
        f"/workspaces/{workspace_id}",
        headers=auth_headers,
    )
    assert deleted.status_code == 204
    assert client.get("/workspaces", headers=auth_headers).json() == []
    assert (
        client.get(f"/projects/{project_id}", headers=auth_headers).status_code
        == 404
    )


def test_workspace_admin_can_delete_project_and_all_children(
    client: TestClient, auth_headers: dict[str, str]
):
    workspace_id = client.post(
        "/workspaces",
        json={"name": "Project deletion workspace"},
        headers=auth_headers,
    ).json()["id"]
    project_id = client.post(
        f"/workspaces/{workspace_id}/projects",
        json={"name": "Disposable project"},
        headers=auth_headers,
    ).json()["id"]
    task_id = client.post(
        f"/projects/{project_id}/tasks",
        json={"title": "Disposable task"},
        headers=auth_headers,
    ).json()["id"]
    client.get(f"/projects/{project_id}/board", headers=auth_headers)

    deleted = client.delete(f"/projects/{project_id}", headers=auth_headers)

    assert deleted.status_code == 204
    assert (
        client.get(
            f"/workspaces/{workspace_id}/projects", headers=auth_headers
        ).json()
        == []
    )
    assert client.get(f"/projects/{project_id}", headers=auth_headers).status_code == 404
    assert client.get(f"/tasks/{task_id}", headers=auth_headers).status_code == 404


def test_task_collaboration_schedule_checklist_and_status_sync(
    client: TestClient, auth_headers: dict[str, str]
):
    teammate = client.post(
        "/auth/register",
        json={
            "name": "Team Mate",
            "email": "mate@example.com",
            "password": "securepass123",
        },
    ).json()
    workspace_id = client.post(
        "/workspaces",
        json={"name": "Collaborative Workspace"},
        headers=auth_headers,
    ).json()["id"]
    client.post(
        f"/workspaces/{workspace_id}/members",
        json={"email": "mate@example.com", "role": "member"},
        headers=auth_headers,
    )
    me_id = client.get("/auth/me", headers=auth_headers).json()["id"]
    project_id = client.post(
        f"/workspaces/{workspace_id}/projects",
        json={"name": "Collaborative Project"},
        headers=auth_headers,
    ).json()["id"]
    board = client.get(
        f"/projects/{project_id}/board", headers=auth_headers
    ).json()

    task = client.post(
        f"/projects/{project_id}/tasks",
        json={
            "title": "Shared scheduled task",
            "assignee_ids": [me_id, teammate["id"]],
            "start_at": "2026-08-01T09:30:00",
            "end_at": "2026-08-01T17:30:00",
        },
        headers=auth_headers,
    )
    assert task.status_code == 201
    task_id = task.json()["id"]
    assert set(task.json()["assignee_ids"]) == {me_id, teammate["id"]}
    assert task.json()["start_at"].startswith("2026-08-01T09:30:00")

    item = client.post(
        f"/tasks/{task_id}/checklist",
        json={"text": "Finish the implementation"},
        headers=auth_headers,
    ).json()
    client.patch(
        f"/tasks/{task_id}/checklist/{item['id']}",
        json={"is_done": True},
        headers=auth_headers,
    )
    assert (
        client.get(f"/tasks/{task_id}", headers=auth_headers).json()["progress"]
        == 100
    )

    client.patch(
        f"/tasks/{task_id}",
        json={"status": "in_progress"},
        headers=auth_headers,
    )
    updated_board = client.get(
        f"/projects/{project_id}/board", headers=auth_headers
    ).json()
    progress_column = next(
        column
        for column in board["columns"]
        if column["system_status"] == "in_progress"
    )
    assert (
        updated_board["task_positions"][str(task_id)]["column_id"]
        == progress_column["id"]
    )


def test_kanban_rejects_sprints_and_scrum_has_one_active_sprint(
    client: TestClient, auth_headers: dict[str, str]
):
    workspace_id = client.post(
        "/workspaces",
        json={"name": "Framework Workspace"},
        headers=auth_headers,
    ).json()["id"]
    project_id = client.post(
        f"/workspaces/{workspace_id}/projects",
        json={"name": "Framework Project"},
        headers=auth_headers,
    ).json()["id"]
    client.get(f"/projects/{project_id}/board", headers=auth_headers)
    rejected = client.post(
        f"/projects/{project_id}/sprints",
        json={"name": "Kanban Sprint"},
        headers=auth_headers,
    )
    assert rejected.status_code == 409

    client.put(
        f"/projects/{project_id}/board",
        json={"framework": "scrum", "reset": True},
        headers=auth_headers,
    )
    first = client.post(
        f"/projects/{project_id}/sprints",
        json={"name": "Sprint One", "is_active": True},
        headers=auth_headers,
    ).json()
    second = client.post(
        f"/projects/{project_id}/sprints",
        json={"name": "Sprint Two", "is_active": True},
        headers=auth_headers,
    ).json()
    sprints = client.get(
        f"/projects/{project_id}/sprints", headers=auth_headers
    ).json()
    assert second["is_active"] is True
    assert next(s for s in sprints if s["id"] == first["id"])["is_active"] is False

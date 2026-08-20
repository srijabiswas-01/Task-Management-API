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


def test_auth_normalizes_email_and_rejects_bad_credentials(client: TestClient):
    registered = client.post(
        "/auth/register",
        json={"name": "Jane Doe", "email": "Jane@Example.COM", "password": "securepass123"},
    )
    assert registered.status_code == 201
    assert registered.json()["email"] == "jane@example.com"

    duplicate = client.post(
        "/auth/register",
        json={"name": "Other Jane", "email": "JANE@example.com", "password": "securepass123"},
    )
    assert duplicate.status_code == 409

    bad_password = client.post(
        "/auth/login",
        data={"username": "jane@example.com", "password": "wrong-password"},
    )
    assert bad_password.status_code == 401

    logged_in = client.post(
        "/auth/login",
        data={"username": "  JANE@EXAMPLE.COM  ", "password": "securepass123"},
    )
    assert logged_in.status_code == 200

    invalid_token = client.get(
        "/auth/me", headers={"Authorization": "Bearer not-a-valid-token"}
    )
    assert invalid_token.status_code == 401


def test_inactive_user_cannot_login(client: TestClient):
    from sqlalchemy import select

    from app.database import SessionLocal
    from app.models import User

    client.post(
        "/auth/register",
        json={"name": "Inactive User", "email": "inactive@example.com", "password": "securepass123"},
    )
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == "inactive@example.com"))
        user.is_active = False
        db.commit()

    response = client.post(
        "/auth/login",
        data={"username": "inactive@example.com", "password": "securepass123"},
    )
    assert response.status_code == 403
    assert "waiting for administrator approval" in response.json()["detail"]


def test_registration_requires_admin_approval(client: TestClient, auth_headers: dict[str, str]):
    workspace_id = client.post(
        "/workspaces", json={"name": "Approval workspace"}, headers=auth_headers
    ).json()["id"]
    pending = client.post(
        "/auth/register",
        json={"name": "Pending User", "email": "pending@example.com", "password": "securepass123"},
    )
    assert pending.status_code == 201
    assert pending.json()["is_active"] is False
    assert client.post(
        "/auth/login",
        data={"username": "pending@example.com", "password": "securepass123"},
    ).status_code == 403

    directory = client.get(
        f"/workspaces/{workspace_id}/user-directory", headers=auth_headers
    ).json()
    assert next(user for user in directory if user["email"] == "pending@example.com")["is_active"] is False

    profile = client.get(
        f"/workspaces/{workspace_id}/users/{pending.json()['id']}/profile",
        headers=auth_headers,
    )
    assert profile.status_code == 200
    edited_profile = client.put(
        f"/workspaces/{workspace_id}/users/{pending.json()['id']}/profile",
        json={"name": "Pending User Updated"},
        headers=auth_headers,
    )
    assert edited_profile.status_code == 200
    assert edited_profile.json()["name"] == "Pending User Updated"

    approved = client.patch(
        f"/workspaces/{workspace_id}/users/{pending.json()['id']}/approve",
        headers=auth_headers,
    )
    assert approved.status_code == 200
    assert approved.json()["is_active"] is True
    assert client.post(
        "/auth/login",
        data={"username": "pending@example.com", "password": "securepass123"},
    ).status_code == 200


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
        json={"name": "Platform", "status": "active", "priority": "high", "start_date": "2026-08-01", "end_date": "2026-12-31"},
        headers=auth_headers,
    )
    assert project.status_code == 201
    assert project.json()["start_date"] == "2026-08-01"
    assert project.json()["end_date"] == "2026-12-31"
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


def test_projects_require_valid_dates_and_are_scoped_to_workspace(
    client: TestClient, auth_headers: dict[str, str]
):
    first = client.post("/workspaces", json={"name": "First workspace"}, headers=auth_headers).json()
    second = client.post("/workspaces", json={"name": "Second workspace"}, headers=auth_headers).json()
    missing_dates = client.post(
        f"/workspaces/{first['id']}/projects",
        json={"name": "Missing dates"}, headers=auth_headers,
    )
    assert missing_dates.status_code == 422
    reversed_dates = client.post(
        f"/workspaces/{first['id']}/projects",
        json={"name": "Bad dates", "start_date": "2026-09-01", "end_date": "2026-08-01"},
        headers=auth_headers,
    )
    assert reversed_dates.status_code == 422
    created = client.post(
        f"/workspaces/{first['id']}/projects",
        json={"name": "First only", "start_date": "2026-08-01", "end_date": "2026-12-31"},
        headers=auth_headers,
    )
    assert created.status_code == 201
    assert [item["name"] for item in client.get(
        f"/workspaces/{first['id']}/projects", headers=auth_headers
    ).json()] == ["First only"]
    assert client.get(
        f"/workspaces/{second['id']}/projects", headers=auth_headers
    ).json() == []


def test_task_completion_moves_card_to_done_and_can_reopen(
    client: TestClient, auth_headers: dict[str, str]
):
    workspace_id = client.post(
        "/workspaces", json={"name": "Completion workspace"}, headers=auth_headers
    ).json()["id"]
    project_id = client.post(
        f"/workspaces/{workspace_id}/projects",
        json={
            "name": "Completion project",
            "start_date": "2026-08-01",
            "end_date": "2026-12-31",
        },
        headers=auth_headers,
    ).json()["id"]
    task_id = client.post(
        f"/projects/{project_id}/tasks",
        json={"title": "Complete this card"},
        headers=auth_headers,
    ).json()["id"]

    completed = client.patch(
        f"/tasks/{task_id}/completion",
        json={"is_completed": True},
        headers=auth_headers,
    )
    assert completed.status_code == 200
    assert completed.json()["status"] == "done"
    assert completed.json()["progress"] == 100
    board = client.get(f"/projects/{project_id}/board", headers=auth_headers).json()
    done_column = next(column for column in board["columns"] if column["system_status"] == "done")
    assert board["task_positions"][str(task_id)]["column_id"] == done_column["id"]

    reopened = client.patch(
        f"/tasks/{task_id}/completion",
        json={"is_completed": False},
        headers=auth_headers,
    )
    assert reopened.status_code == 200
    assert reopened.json()["status"] == "backlog"
    assert reopened.json()["progress"] == 0
    board = client.get(f"/projects/{project_id}/board", headers=auth_headers).json()
    first_column = min(board["columns"], key=lambda column: column["position"])
    assert board["task_positions"][str(task_id)]["column_id"] == first_column["id"]


def test_editing_task_details_preserves_its_board_position(
    client: TestClient, auth_headers: dict[str, str]
):
    workspace_id = client.post(
        "/workspaces",
        json={"name": "Stable board workspace"},
        headers=auth_headers,
    ).json()["id"]
    project_id = client.post(
        f"/workspaces/{workspace_id}/projects",
        json={"name": "Stable board project", "start_date": "2026-08-01", "end_date": "2026-12-31"},
        headers=auth_headers,
    ).json()["id"]
    task_ids = [
        client.post(
            f"/projects/{project_id}/tasks",
            json={"title": title},
            headers=auth_headers,
        ).json()["id"]
        for title in ("First task", "Middle task", "Last task")
    ]
    board_before = client.get(
        f"/projects/{project_id}/board", headers=auth_headers
    ).json()
    middle_position = board_before["task_positions"][str(task_ids[1])]

    updated = client.patch(
        f"/tasks/{task_ids[1]}",
        json={"title": "Edited middle task", "status": "backlog"},
        headers=auth_headers,
    )

    assert updated.status_code == 200
    board_after = client.get(
        f"/projects/{project_id}/board", headers=auth_headers
    ).json()
    assert board_after["task_positions"][str(task_ids[1])] == middle_position


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
        json={"name": "Scrum Product", "start_date": "2026-08-01", "end_date": "2026-12-31"},
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
        json={"name": "Temporary Project", "start_date": "2026-08-01", "end_date": "2026-12-31"},
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
        json={"name": "Disposable project", "start_date": "2026-08-01", "end_date": "2026-12-31"},
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
    client.patch(
        f"/workspaces/{workspace_id}/users/{teammate['id']}/approve",
        headers=auth_headers,
    )
    client.post(
        f"/workspaces/{workspace_id}/members",
        json={"email": "mate@example.com", "role": "member"},
        headers=auth_headers,
    )
    me_id = client.get("/auth/me", headers=auth_headers).json()["id"]
    project_id = client.post(
        f"/workspaces/{workspace_id}/projects",
        json={"name": "Collaborative Project", "start_date": "2026-08-01", "end_date": "2026-12-31"},
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

    updated_task = client.patch(
        f"/tasks/{task_id}",
        json={"assignee_ids": [me_id, teammate["id"]]},
        headers=auth_headers,
    )
    assert updated_task.status_code == 200
    assert set(updated_task.json()["assignee_ids"]) == {
        me_id,
        teammate["id"],
    }

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
        json={"name": "Framework Project", "start_date": "2026-08-01", "end_date": "2026-12-31"},
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


def test_team_allocation_controls_member_collaboration_access(
    client: TestClient, auth_headers: dict[str, str]
):
    teammate = client.post(
        "/auth/register",
        json={"name": "Mobile Developer", "email": "mobile@example.com", "password": "securepass123"},
    ).json()
    workspace_id = client.post(
        "/workspaces", json={"name": "Product"}, headers=auth_headers
    ).json()["id"]
    client.patch(
        f"/workspaces/{workspace_id}/users/{teammate['id']}/approve",
        headers=auth_headers,
    )
    login = client.post(
        "/auth/login",
        data={"username": "mobile@example.com", "password": "securepass123"},
    ).json()
    member_headers = {"Authorization": f"Bearer {login['access_token']}"}
    available = client.get(
        f"/workspaces/{workspace_id}/available-users", headers=auth_headers
    )
    assert available.status_code == 200
    assert [user["email"] for user in available.json()] == ["mobile@example.com"]
    workspace_member = client.post(
        f"/workspaces/{workspace_id}/members",
        json={"email": "mobile@example.com", "role": "member"},
        headers=auth_headers,
    ).json()
    assert client.get(
        f"/workspaces/{workspace_id}/available-users", headers=auth_headers
    ).json() == []
    visible_project = client.post(
        f"/workspaces/{workspace_id}/projects",
        json={"name": "Mobile application", "start_date": "2026-08-01", "end_date": "2026-12-31"},
        headers=auth_headers,
    ).json()
    hidden_project = client.post(
        f"/workspaces/{workspace_id}/projects",
        json={"name": "Internal admin", "start_date": "2026-08-01", "end_date": "2026-12-31"},
        headers=auth_headers,
    ).json()
    designation = client.post(
        f"/workspaces/{workspace_id}/designations",
        json={"name": "Android Developer", "description": "Builds Android apps"},
        headers=auth_headers,
    )
    assert designation.status_code == 201
    designation = designation.json()
    team = client.post(
        f"/workspaces/{workspace_id}/teams",
        json={
            "name": "Mobile team",
            "manager_user_id": teammate["id"],
            "manager_designation": "Android Developer",
        },
        headers=auth_headers,
    ).json()
    assert team["manager_user"]["id"] == teammate["id"]
    edited_team = client.patch(
        f"/workspaces/{workspace_id}/teams/{team['id']}",
        json={"name": "Mobile delivery team", "description": "Mobile releases"},
        headers=auth_headers,
    )
    assert edited_team.status_code == 200
    assert edited_team.json()["name"] == "Mobile delivery team"
    allocation = client.post(
        f"/workspaces/{workspace_id}/teams/{team['id']}/members",
        json={
            "user_id": teammate["id"],
            "project_id": visible_project["id"],
            "designation": "Android Developer",
        },
        headers=auth_headers,
    )
    assert allocation.status_code == 201
    assert allocation.json()["designation"] == "Android Developer"
    edited_allocation = client.patch(
        f"/workspaces/{workspace_id}/teams/{team['id']}/members/{allocation.json()['id']}",
        json={"project_id": hidden_project["id"], "designation": "Android Developer"},
        headers=auth_headers,
    )
    assert edited_allocation.status_code == 200
    assert edited_allocation.json()["project_id"] == hidden_project["id"]
    allocation = client.patch(
        f"/workspaces/{workspace_id}/teams/{team['id']}/members/{allocation.json()['id']}",
        json={"project_id": visible_project["id"], "designation": "Android Developer"},
        headers=auth_headers,
    )
    assert allocation.status_code == 200
    directory = client.get(
        f"/workspaces/{workspace_id}/user-directory", headers=auth_headers
    )
    assert directory.status_code == 200
    teammate_directory = next(
        user for user in directory.json() if user["user_id"] == teammate["id"]
    )
    assert teammate_directory["projects"] == ["Mobile application"]
    assert teammate_directory["membership_id"] == workspace_member["id"]
    assert client.get(
        f"/workspaces/{workspace_id}/user-directory", headers=member_headers
    ).status_code == 403
    renamed = client.patch(
        f"/workspaces/{workspace_id}/designations/{designation['id']}",
        json={"name": "Senior Android Developer"},
        headers=auth_headers,
    )
    assert renamed.status_code == 200
    allocations = client.get(
        f"/workspaces/{workspace_id}/team-members", headers=auth_headers
    ).json()
    assert allocations[0]["designation"] == "Senior Android Developer"

    projects = client.get(
        f"/workspaces/{workspace_id}/projects", headers=member_headers
    ).json()
    assert {project["id"] for project in projects} == {
        visible_project["id"], hidden_project["id"]
    }
    assert client.get(
        f"/projects/{visible_project['id']}/board", headers=member_headers
    ).status_code == 200
    assert client.get(
        f"/projects/{hidden_project['id']}", headers=member_headers
    ).status_code == 200
    assert client.post(
        f"/projects/{visible_project['id']}/tasks",
        json={"title": "Member cannot create this"},
        headers=member_headers,
    ).status_code == 403

    visible_task = client.post(
        f"/projects/{visible_project['id']}/tasks",
        json={"title": "Collaborative task"},
        headers=auth_headers,
    ).json()
    checklist_item = client.post(
        f"/tasks/{visible_task['id']}/checklist",
        json={"text": "Member can complete this"},
        headers=auth_headers,
    ).json()
    assert checklist_item["created_by_id"] is not None
    comment = client.post(
        f"/tasks/{visible_task['id']}/comments",
        json={"body": "Member progress update"},
        headers=member_headers,
    )
    assert comment.status_code == 201
    assert comment.json()["author_id"] == teammate["id"]
    completed = client.patch(
        f"/tasks/{visible_task['id']}/checklist/{checklist_item['id']}",
        json={"is_done": True},
        headers=member_headers,
    )
    assert completed.status_code == 200
    assert completed.json()["last_action_by_id"] == teammate["id"]
    assert completed.json()["last_action"] == "completed"

    hidden_task = client.post(
        f"/projects/{hidden_project['id']}/tasks",
        json={"title": "View-only task"},
        headers=auth_headers,
    ).json()
    assert client.post(
        f"/tasks/{hidden_task['id']}/comments",
        json={"body": "Must not be accepted"},
        headers=member_headers,
    ).status_code == 403

    assert client.delete(
        f"/workspaces/{workspace_id}/teams/{team['id']}/members/{allocation.json()['id']}",
        headers=auth_headers,
    ).status_code == 204
    assert client.delete(
        f"/workspaces/{workspace_id}/designations/{designation['id']}",
        headers=auth_headers,
    ).status_code == 204
    assert len(client.get(
        f"/workspaces/{workspace_id}/projects", headers=member_headers
    ).json()) == 2
    deactivated = client.patch(
        f"/workspaces/{workspace_id}/members/{workspace_member['id']}/access",
        json={"is_active": False},
        headers=auth_headers,
    )
    assert deactivated.status_code == 200
    assert deactivated.json()["is_active"] is False
    assert client.get(
        f"/workspaces/{workspace_id}/projects", headers=member_headers
    ).status_code == 403
    assert client.get("/workspaces", headers=member_headers).json() == []
    reactivated = client.patch(
        f"/workspaces/{workspace_id}/members/{workspace_member['id']}/access",
        json={"is_active": True},
        headers=auth_headers,
    )
    assert reactivated.status_code == 200
    promoted = client.patch(
        f"/workspaces/{workspace_id}/members/{workspace_member['id']}/access",
        json={"role": "admin"},
        headers=auth_headers,
    )
    assert promoted.status_code == 200
    assert promoted.json()["role"] == "admin"
    demoted = client.patch(
        f"/workspaces/{workspace_id}/members/{workspace_member['id']}/access",
        json={"role": "member"},
        headers=auth_headers,
    )
    assert demoted.status_code == 200
    assert demoted.json()["role"] == "member"
    assert client.get(
        f"/workspaces/{workspace_id}/projects", headers=member_headers
    ).status_code == 200
    assert client.delete(
        f"/workspaces/{workspace_id}/users/{teammate['id']}",
        headers=auth_headers,
    ).status_code == 204
    assert client.get("/auth/me", headers=member_headers).status_code == 401


def test_current_user_profile_and_project_history(
    client: TestClient, auth_headers: dict[str, str]
):
    workspace_id = client.post(
        "/workspaces", json={"name": "Profile workspace"}, headers=auth_headers
    ).json()["id"]
    profile_update = client.put(
        "/auth/profile",
        json={"name": "Test User", "skills": "Python, SQL, python, FastAPI\nDocker"},
        headers=auth_headers,
    )
    assert profile_update.status_code == 200
    assert profile_update.json()["skills"] == "Python, SQL, FastAPI, Docker"
    catalog = client.get(
        f"/workspaces/{workspace_id}/skill-catalog", headers=auth_headers
    )
    assert catalog.status_code == 200
    assert catalog.json() == ["Docker", "FastAPI", "Python", "SQL"]
    skill_members = client.get(
        f"/workspaces/{workspace_id}/skill-members", headers=auth_headers
    )
    assert skill_members.status_code == 200
    assert skill_members.json()[0]["skills"] == ["Python", "SQL", "FastAPI", "Docker"]
    project = client.post(
        f"/workspaces/{workspace_id}/projects",
        json={"name": "Profile project", "start_date": "2026-08-01", "end_date": "2026-12-31"},
        headers=auth_headers,
    ).json()
    assert project["project_manager_id"] is not None
    client.post(
        f"/workspaces/{workspace_id}/designations",
        json={"name": "Project Lead"},
        headers=auth_headers,
    )
    department = client.post(
        f"/workspaces/{workspace_id}/departments",
        json={"name": "Engineering", "description": "Builds the product"},
        headers=auth_headers,
    )
    assert department.status_code == 201
    department = department.json()
    current_member = client.get(
        f"/workspaces/{workspace_id}/members", headers=auth_headers
    ).json()[0]
    professional_update = client.patch(
        f"/workspaces/{workspace_id}/members/{current_member['id']}/professional-profile",
        json={"professional_title": "Project Lead", "department": "Engineering"},
        headers=auth_headers,
    )
    assert professional_update.status_code == 200
    assert professional_update.json()["professional_title"] == "Project Lead"
    assert professional_update.json()["department"] == "Engineering"

    updated = client.put(
        "/auth/profile",
        json={
            "name": "Updated Profile Name",
            "phone": "+91 99999 99999",
            "location": "Kolkata, India",
            "bio": "Product delivery specialist",
            "professional_title": "Project Lead",
            "department": "Engineering",
            "years_experience": 8,
            "skills": "Planning, Leadership, APIs",
            "achievements": "Delivered the Orbit platform",
            "profile_image": "data:image/png;base64,dGVzdA==",
        },
        headers=auth_headers,
    )
    assert updated.status_code == 200
    profile = updated.json()
    assert profile["name"] == "Updated Profile Name"
    assert profile["project_count"] == 1
    assert profile["projects"] == ["Profile project"]
    assert profile["professional_title"] == "Project Lead"
    assert client.get("/auth/me", headers=auth_headers).json()["name"] == "Updated Profile Name"
    renamed = client.patch(
        f"/workspaces/{workspace_id}/departments/{department['id']}",
        json={"name": "IT"},
        headers=auth_headers,
    )
    assert renamed.status_code == 200
    assert client.get("/auth/profile", headers=auth_headers).json()["department"] == "IT"
    assert client.delete(
        f"/workspaces/{workspace_id}/departments/{department['id']}",
        headers=auth_headers,
    ).status_code == 204

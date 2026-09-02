from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

from fastapi.testclient import TestClient
from conftest import valid_profile_image


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
    assert registered.json()["is_system_admin"] is True

    logged_in = client.post(
        "/auth/login",
        data={"username": "jane@example.com", "password": "securepass123"},
    )
    assert logged_in.status_code == 200
    token = logged_in.json()["access_token"]

    me = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["email"] == "jane@example.com"
    admin_headers = {"Authorization": f"Bearer {token}"}
    global_users = client.get("/admin/users", headers=admin_headers)
    assert global_users.status_code == 200
    assert global_users.json()[0]["email"] == "jane@example.com"
    assert client.get("/admin/skills", headers=admin_headers).status_code == 200


def test_only_one_simultaneous_first_registration_becomes_admin(client: TestClient):
    def register(index: int):
        return client.post(
            "/auth/register",
            json={
                "name": f"Concurrent User {index}",
                "email": f"concurrent-{index}@example.com",
                "password": "securepass123",
            },
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(executor.map(register, (1, 2)))

    assert [response.status_code for response in responses] == [201, 201]
    users = [response.json() for response in responses]
    assert sum(user["is_system_admin"] for user in users) == 1
    assert sum(user["is_active"] for user in users) == 1


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


def test_legacy_location_and_years_do_not_complete_structured_profile(
    client: TestClient, auth_headers: dict[str, str]
):
    response = client.put(
        "/auth/profile",
        json={
            "name": "Test User",
            "phone": "9999999999",
            "location": "Kolkata, West Bengal, India",
            "bio": "Legacy profile",
            "years_experience": 2,
            "skills": "Python",
            "achievements": "Certification",
        },
        headers=auth_headers,
    )
    assert response.status_code == 200
    profile = response.json()
    assert profile["completion_percent"] < 100
    assert {"City", "State", "Country", "Experience start date"}.issubset(
        profile["missing_fields"]
    )


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
    member_token = client.post(
        "/auth/login",
        data={"username": "pending@example.com", "password": "securepass123"},
    ).json()["access_token"]
    assert client.post(
        "/workspaces",
        json={"name": "Unauthorized workspace"},
        headers={"Authorization": f"Bearer {member_token}"},
    ).status_code == 403
    member_headers = {"Authorization": f"Bearer {member_token}"}
    assert client.patch(
        f"/workspaces/{workspace_id}",
        json={"name": "Unauthorized rename"},
        headers=member_headers,
    ).status_code == 403
    assert client.request(
        "DELETE",
        f"/workspaces/{workspace_id}",
        json={"workspace_name": "Approval workspace"},
        headers=member_headers,
    ).status_code == 403


def test_global_people_catalog_and_teams_do_not_require_a_workspace(
    client: TestClient, auth_headers: dict[str, str]
):
    current_user = client.get("/auth/me", headers=auth_headers).json()
    department = client.post(
        "/admin/departments", json={"name": "Global Engineering"}, headers=auth_headers
    )
    assert department.status_code == 201
    designation = client.post(
        "/admin/designations",
        json={"name": "Global Engineer", "department_id": department.json()["id"]},
        headers=auth_headers,
    )
    assert designation.status_code == 201
    assigned = client.patch(
        f"/admin/users/{current_user['id']}/member",
        json={"department": "Global Engineering", "professional_title": "Global Engineer"},
        headers=auth_headers,
    )
    assert assigned.status_code == 200
    assert assigned.json()["is_member"] is True
    assert assigned.json()["is_system_admin"] is True
    assert assigned.json()["role"] == "admin"
    completed_manager = client.put(
        f"/admin/users/{current_user['id']}/profile",
        json={
            "name": current_user["name"], "profile_image": valid_profile_image(),
            "phone": "9999999999", "location_city": "Kolkata",
            "location_state": "West Bengal", "location_country": "India",
            "department": "Global Engineering", "professional_title": "Global Engineer",
            "experience_start_date": "2021-01-01", "skills": "Leadership",
        },
        headers=auth_headers,
    )
    assert completed_manager.status_code == 200
    assert completed_manager.json()["completion_percent"] >= 50
    team = client.post(
        "/admin/teams",
        json={
            "name": "Global Platform Team",
            "manager_user_id": current_user["id"],
            "manager_designation": "This value must be ignored",
        },
        headers=auth_headers,
    )
    assert team.status_code == 201
    assert team.json()["workspace_id"] is None
    assert team.json()["manager_designation"] == "Global Engineer"
    assert client.get("/admin/users", headers=auth_headers).status_code == 200
    assert client.get("/admin/departments", headers=auth_headers).json()[0]["name"] == "Global Engineering"
    assert client.get("/admin/designations", headers=auth_headers).json()[0]["department_name"] == "Global Engineering"
    assert client.get("/admin/teams", headers=auth_headers).json()[0]["name"] == "Global Platform Team"
    pending = client.post(
        "/auth/register",
        json={"name": "Global User", "email": "global-user@example.com", "password": "securepass123"},
    ).json()
    approved = client.patch(f"/admin/users/{pending['id']}/approve", headers=auth_headers)
    assert approved.status_code == 200
    member = client.patch(
        f"/admin/users/{pending['id']}/member",
        json={"role": "member", "department": "Global Engineering", "professional_title": "Global Engineer"},
        headers=auth_headers,
    )
    assert member.status_code == 200
    assert member.json()["role"] == "member"
    assert client.patch(f"/admin/users/{pending['id']}/access?is_active=false", headers=auth_headers).json()["is_active"] is False
    assert client.patch(f"/admin/users/{pending['id']}/access?is_active=true", headers=auth_headers).json()["is_active"] is True
    assert client.get(f"/admin/users/{pending['id']}/profile", headers=auth_headers).status_code == 200
    assert client.delete(f"/admin/users/{pending['id']}", headers=auth_headers).status_code == 204


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


def test_global_member_directory_survives_workspace_team_and_allocation_deletion(
    client: TestClient, auth_headers: dict[str, str]
):
    registered = client.post(
        "/auth/register",
        json={"name": "Global Member", "email": "global@example.com", "password": "securepass123"},
    ).json()
    first = client.post(
        "/workspaces", json={"name": "First global directory"}, headers=auth_headers
    ).json()
    second = client.post(
        "/workspaces", json={"name": "Second global directory"}, headers=auth_headers
    ).json()
    client.patch(
        f"/workspaces/{first['id']}/users/{registered['id']}/approve",
        headers=auth_headers,
    )
    for workspace in (first, second):
        directory = client.get(
            f"/workspaces/{workspace['id']}/user-directory", headers=auth_headers
        ).json()
        assert "global@example.com" in {user["email"] for user in directory}

    department = client.post(
        f"/workspaces/{first['id']}/departments",
        json={"name": "Engineering"}, headers=auth_headers,
    ).json()
    client.post(
        f"/workspaces/{first['id']}/designations",
        json={"name": "Developer", "department_id": department["id"]}, headers=auth_headers,
    )
    completed_profile = client.put(
        f"/workspaces/{first['id']}/users/{registered['id']}/profile",
        json={
            "name": "Global Member", "profile_image": valid_profile_image(),
            "phone": "5550101000", "location": "Remote",
            "location_city": "Remote", "location_state": "Remote", "location_country": "United States", "bio": "Developer profile",
            "professional_title": "Developer", "department": "Engineering",
            "years_experience": 3, "experience_start_date": "2023-01-01", "skills": "Python", "achievements": "Completed training",
        },
        headers=auth_headers,
    )
    assert completed_profile.json()["completion_percent"] == 100
    assigned = client.patch(
        f"/admin/users/{registered['id']}/member",
        json={"role": "member", "department": "Engineering", "professional_title": "Developer"},
        headers=auth_headers,
    )
    assert assigned.status_code == 200
    project = client.post(
        f"/workspaces/{first['id']}/projects",
        json={"name": "Scoped project", "start_date": "2026-08-01", "end_date": "2026-12-31"},
        headers=auth_headers,
    ).json()
    team = client.post(
        f"/workspaces/{first['id']}/teams",
        json={
            "name": "Scoped team",
            "manager_user_id": registered["id"],
            "manager_designation": "Developer",
        },
        headers=auth_headers,
    )
    assert team.status_code == 201
    allocation = client.post(
        f"/workspaces/{first['id']}/teams/{team.json()['id']}/members",
        json={
            "user_id": registered["id"],
            "project_id": project["id"],
            "designation": "Developer",
        },
        headers=auth_headers,
    )
    assert allocation.status_code == 201
    client.delete(
        f"/workspaces/{first['id']}/teams/{team.json()['id']}/members/{allocation.json()['id']}",
        headers=auth_headers,
    )
    assert "global@example.com" in {
        user["email"] for user in client.get(
            f"/workspaces/{first['id']}/user-directory", headers=auth_headers
        ).json()
    }
    assert client.request("DELETE", f"/workspaces/{first['id']}", json={"workspace_name": first["name"]}, headers=auth_headers).status_code == 204
    assert "global@example.com" in {
        user["email"] for user in client.get(
            f"/workspaces/{second['id']}/user-directory", headers=auth_headers
        ).json()
    }


def test_designations_and_departments_are_shared_by_every_workspace(
    client: TestClient, auth_headers: dict[str, str]
):
    first = client.post(
        "/workspaces", json={"name": "Shared catalog one"}, headers=auth_headers
    ).json()
    second = client.post(
        "/workspaces", json={"name": "Shared catalog two"}, headers=auth_headers
    ).json()
    department = client.post(
        f"/workspaces/{first['id']}/departments",
        json={"name": "Design"}, headers=auth_headers,
    ).json()
    designation = client.post(
        f"/workspaces/{first['id']}/designations",
        json={"name": "Product Designer", "department_id": department["id"]}, headers=auth_headers,
    ).json()
    assert [item["name"] for item in client.get(
        f"/workspaces/{second['id']}/designations", headers=auth_headers
    ).json()] == ["Product Designer"]
    assert [item["name"] for item in client.get(
        f"/workspaces/{second['id']}/departments", headers=auth_headers
    ).json()] == ["Design"]

    assert client.patch(
        f"/workspaces/{second['id']}/designations/{designation['id']}",
        json={"name": "Senior Product Designer"}, headers=auth_headers,
    ).status_code == 200
    assert client.patch(
        f"/workspaces/{second['id']}/departments/{department['id']}",
        json={"name": "Product Design"}, headers=auth_headers,
    ).status_code == 200
    third = client.post(
        "/workspaces", json={"name": "Shared catalog three"}, headers=auth_headers
    ).json()
    assert [item["name"] for item in client.get(
        f"/workspaces/{third['id']}/designations", headers=auth_headers
    ).json()] == ["Senior Product Designer"]
    assert [item["name"] for item in client.get(
        f"/workspaces/{third['id']}/departments", headers=auth_headers
    ).json()] == ["Product Design"]
    for workspace in (first, second, third):
        assert client.request(
            "DELETE", f"/workspaces/{workspace['id']}", json={"workspace_name": workspace["name"]}, headers=auth_headers
        ).status_code == 204
    recreated = client.post(
        "/workspaces", json={"name": "Catalog after deletion"}, headers=auth_headers
    ).json()
    assert [item["name"] for item in client.get(
        f"/workspaces/{recreated['id']}/designations", headers=auth_headers
    ).json()] == ["Senior Product Designer"]
    assert [item["name"] for item in client.get(
        f"/workspaces/{recreated['id']}/departments", headers=auth_headers
    ).json()] == ["Product Design"]


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
    for text in ("First acceptance item", "Second acceptance item"):
        created_item = client.post(
            f"/tasks/{task_id}/checklist",
            json={"text": text},
            headers=auth_headers,
        )
        assert created_item.status_code == 201

    completed = client.patch(
        f"/tasks/{task_id}/completion",
        json={"is_completed": True},
        headers=auth_headers,
    )
    assert completed.status_code == 200
    assert completed.json()["status"] == "done"
    assert completed.json()["progress"] == 100
    completed_items = client.get(
        f"/tasks/{task_id}/checklist", headers=auth_headers
    ).json()
    assert all(item["is_done"] for item in completed_items)
    assert all(item["last_action"] == "completed" for item in completed_items)
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
    reopened_items = client.get(
        f"/tasks/{task_id}/checklist", headers=auth_headers
    ).json()
    assert all(not item["is_done"] for item in reopened_items)
    assert all(item["last_action"] == "reopened" for item in reopened_items)
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

    missing_confirmation = client.delete(
        f"/workspaces/{workspace_id}",
        headers=auth_headers,
    )
    assert missing_confirmation.status_code == 422
    wrong_confirmation = client.request(
        "DELETE",
        f"/workspaces/{workspace_id}",
        json={"workspace_name": "Temporary Workspace"},
        headers=auth_headers,
    )
    assert wrong_confirmation.status_code == 400
    assert wrong_confirmation.json()["detail"] == "Workspace name confirmation does not match"

    deleted = client.request(
        "DELETE",
        f"/workspaces/{workspace_id}",
        json={"workspace_name": "Renamed Workspace"},
        headers=auth_headers,
    )
    assert deleted.status_code == 204
    assert client.get("/workspaces", headers=auth_headers).json() == []
    assert (
        client.get(f"/projects/{project_id}", headers=auth_headers).status_code
        == 404
    )


def test_assigned_member_gets_persistent_critical_deadline_notification(
    client: TestClient, auth_headers: dict[str, str]
):
    today = date.today()
    me_id = client.get("/auth/me", headers=auth_headers).json()["id"]
    workspace = client.post(
        "/workspaces",
        json={"name": "Reminder workspace"},
        headers=auth_headers,
    ).json()
    project = client.post(
        f"/workspaces/{workspace['id']}/projects",
        json={"name": "Reminder project", "start_date": str(today - timedelta(days=30)), "end_date": str(today + timedelta(days=365))},
        headers=auth_headers,
    ).json()
    task = client.post(
        f"/projects/{project['id']}/tasks",
        json={
            "title": "Finish release checklist",
            "assignee_ids": [me_id],
            "due_date": str(today),
        },
        headers=auth_headers,
    ).json()
    client.post(
        f"/tasks/{task['id']}/checklist",
        json={"text": "Run final verification"},
        headers=auth_headers,
    )

    notifications = client.get("/notifications", headers=auth_headers)
    assert notifications.status_code == 200
    body = notifications.json()
    assert body["unread_count"] == 1
    assert body["critical_count"] == 1
    reminder = body["items"][0]
    assert reminder["task_id"] == task["id"]
    assert reminder["severity"] == "critical"
    assert "checklist" in reminder["message"].lower()

    cannot_silently_read = client.patch(
        f"/notifications/{reminder['id']}/read", headers=auth_headers
    )
    assert cannot_silently_read.status_code == 400
    mark_all = client.patch("/notifications/read-all", headers=auth_headers)
    assert mark_all.status_code == 200
    assert mark_all.json()["marked_count"] == 0
    assert client.get("/notifications", headers=auth_headers).json()["critical_count"] == 1
    acknowledged = client.patch(
        f"/notifications/{reminder['id']}/acknowledge", headers=auth_headers
    )
    assert acknowledged.status_code == 200
    assert acknowledged.json()["is_acknowledged"] is True
    refreshed = client.get("/notifications", headers=auth_headers).json()
    assert refreshed["unread_count"] == 0
    assert refreshed["critical_count"] == 0


def test_chat_admin_broadcast_and_direct_message_permissions(
    client: TestClient, auth_headers: dict[str, str]
):
    member = client.post(
        "/auth/register",
        json={"name": "Chat Member", "email": "chat-member@example.com", "password": "securepass123"},
    ).json()
    outsider = client.post(
        "/auth/register",
        json={"name": "Outside User", "email": "outside@example.com", "password": "securepass123"},
    ).json()
    workspace = client.post(
        "/workspaces", json={"name": "Chat workspace"}, headers=auth_headers
    ).json()
    client.patch(f"/workspaces/{workspace['id']}/users/{member['id']}/approve", headers=auth_headers)
    client.post(
        f"/workspaces/{workspace['id']}/members",
        json={"email": "chat-member@example.com", "role": "member"}, headers=auth_headers,
    )
    member_login = client.post(
        "/auth/login", data={"username": "chat-member@example.com", "password": "securepass123"}
    ).json()
    member_headers = {"Authorization": f"Bearer {member_login['access_token']}"}

    announcement = client.post(
        f"/workspaces/{workspace['id']}/chat/conversations",
        json={"chat_type": "broadcast", "name": "Company updates"},
        headers=auth_headers,
    )
    assert announcement.status_code == 201
    announcement_id = announcement.json()["id"]
    assert client.post(
        f"/workspaces/{workspace['id']}/chat/conversations/{announcement_id}/messages",
        json={"body": "Welcome to the workspace"}, headers=auth_headers,
    ).status_code == 201
    member_conversations = client.get(
        f"/workspaces/{workspace['id']}/chat/conversations", headers=member_headers
    )
    assert member_conversations.status_code == 200
    assert member_conversations.json()[0]["can_send"] is False
    assert client.post(
        f"/workspaces/{workspace['id']}/chat/conversations/{announcement_id}/messages",
        json={"body": "Members cannot post here"}, headers=member_headers,
    ).status_code == 403
    assert client.delete(
        f"/workspaces/{workspace['id']}/chat/conversations/{announcement_id}",
        headers=member_headers,
    ).status_code == 403

    direct = client.post(
        f"/workspaces/{workspace['id']}/chat/conversations",
        json={"chat_type": "direct", "recipient_id": member["id"]}, headers=auth_headers,
    )
    assert direct.status_code == 201
    assert {item["id"] for item in direct.json()["participants"]} == {
        member["id"], client.get("/auth/me", headers=auth_headers).json()["id"]
    }
    visible_workspaces = client.get("/workspaces", headers=member_headers).json()
    assert workspace["id"] in {item["id"] for item in visible_workspaces}
    member_direct = next(
        item for item in client.get(
            f"/workspaces/{workspace['id']}/chat/conversations", headers=member_headers
        ).json() if item["id"] == direct.json()["id"]
    )
    assert member_direct["name"] == "Test User"
    direct_message = client.post(
        f"/workspaces/{workspace['id']}/chat/conversations/{direct.json()['id']}/messages",
        json={"body": "Private admin message"}, headers=auth_headers,
    ).json()
    assert client.delete(
        f"/workspaces/{workspace['id']}/chat/conversations/{direct.json()['id']}/messages/{direct_message['id']}",
        headers=member_headers,
    ).status_code == 403
    deleted_message = client.delete(
        f"/workspaces/{workspace['id']}/chat/conversations/{direct.json()['id']}/messages/{direct_message['id']}",
        headers=auth_headers,
    )
    assert deleted_message.status_code == 200
    assert deleted_message.json()["is_deleted"] is True
    assert deleted_message.json()["body"] == ""
    # A user without workspace membership cannot inspect either conversation.
    client.patch(f"/workspaces/{workspace['id']}/users/{outsider['id']}/approve", headers=auth_headers)
    outsider_login = client.post(
        "/auth/login", data={"username": "outside@example.com", "password": "securepass123"}
    ).json()
    outsider_headers = {"Authorization": f"Bearer {outsider_login['access_token']}"}
    assert client.get(
        f"/workspaces/{workspace['id']}/chat/conversations", headers=outsider_headers
    ).status_code == 404


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
    mobile_department = client.post(
        f"/workspaces/{workspace_id}/departments",
        json={"name": "Mobile Engineering"}, headers=auth_headers,
    ).json()
    designation = client.post(
        f"/workspaces/{workspace_id}/designations",
        json={"name": "Android Developer", "description": "Builds Android apps", "department_id": mobile_department["id"]},
        headers=auth_headers,
    )
    assert designation.status_code == 201
    designation = designation.json()
    completed_profile = client.put(
        f"/workspaces/{workspace_id}/users/{teammate['id']}/profile",
        json={
            "name": "Mobile Developer", "profile_image": valid_profile_image(),
            "phone": "5550102000", "location": "Remote",
            "location_city": "Remote", "location_state": "Remote", "location_country": "United States", "bio": "Mobile specialist",
            "professional_title": "Android Developer", "department": "Mobile Engineering",
            "years_experience": 4, "experience_start_date": "2022-01-01", "skills": "Android, Kotlin", "achievements": "Published an app",
        },
        headers=auth_headers,
    )
    assert completed_profile.json()["completion_percent"] == 100
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
    assert {project["id"] for project in projects} == {visible_project["id"]}
    assert client.get(
        f"/projects/{visible_project['id']}/board", headers=member_headers
    ).status_code == 200
    assert client.get(
        f"/projects/{hidden_project['id']}", headers=member_headers
    ).status_code == 404
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
    member_dashboard = client.get(
        f"/workspaces/{workspace_id}/dashboard", headers=member_headers
    )
    assert member_dashboard.status_code == 200
    assert member_dashboard.json()["projects"] == 1
    assert member_dashboard.json()["tasks"] == 1

    hidden_task = client.post(
        f"/projects/{hidden_project['id']}/tasks",
        json={"title": "View-only task"},
        headers=auth_headers,
    ).json()
    assert client.post(
        f"/tasks/{hidden_task['id']}/comments",
        json={"body": "Must not be accepted"},
        headers=member_headers,
    ).status_code == 404

    assert client.delete(
        f"/workspaces/{workspace_id}/teams/{team['id']}/members/{allocation.json()['id']}",
        headers=auth_headers,
    ).status_code == 204
    assert client.delete(
        f"/workspaces/{workspace_id}/designations/{designation['id']}",
        headers=auth_headers,
    ).status_code == 204
    assert client.get(
        f"/workspaces/{workspace_id}/projects", headers=member_headers
    ).status_code == 404
    assert client.get("/workspaces", headers=member_headers).json() == []
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
    assert client.patch(
        f"/workspaces/{workspace_id}",
        json={"name": "Workspace-admin rename"},
        headers=member_headers,
    ).status_code == 403
    assert client.request(
        "DELETE",
        f"/workspaces/{workspace_id}",
        json={"workspace_name": "Product"},
        headers=member_headers,
    ).status_code == 403
    demoted = client.patch(
        f"/workspaces/{workspace_id}/members/{workspace_member['id']}/access",
        json={"role": "member"},
        headers=auth_headers,
    )
    assert demoted.status_code == 200
    assert demoted.json()["role"] == "member"
    assert client.get(
        f"/workspaces/{workspace_id}/projects", headers=member_headers
    ).status_code == 404
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
    global_catalog = client.get("/auth/skill-catalog", headers=auth_headers)
    assert global_catalog.status_code == 200
    assert global_catalog.json() == ["Docker", "FastAPI", "Python", "SQL"]
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
    department = client.post(
        f"/workspaces/{workspace_id}/departments",
        json={"name": "Engineering", "description": "Builds the product"},
        headers=auth_headers,
    )
    assert department.status_code == 201
    department = department.json()
    designation = client.post(
        f"/workspaces/{workspace_id}/designations",
        json={"name": "Project Lead", "department_id": department["id"]},
        headers=auth_headers,
    ).json()
    assert client.post(
        f"/workspaces/{workspace_id}/designations",
        json={"name": "project lead", "department_id": department["id"]},
        headers=auth_headers,
    ).status_code == 409
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
            "phone": "9999999999",
            "location": "Kolkata, India",
            "location_city": "Kolkata", "location_state": "West Bengal", "location_country": "India",
            "bio": "Product delivery specialist",
            "professional_title": "Project Lead",
            "department": "Engineering",
            "years_experience": 8, "experience_start_date": "2018-01-01",
            "skills": "Planning, Leadership, APIs",
            "achievements": "Delivered the Orbit platform",
            "profile_image": valid_profile_image(),
        },
        headers=auth_headers,
    )
    assert updated.status_code == 200
    profile = updated.json()
    assert profile["name"] == "Updated Profile Name"
    assert profile["project_count"] == 1
    assert profile["projects"] == ["Profile project"]
    assert profile["professional_title"] == "Project Lead"
    assert profile["location_city"] == "Kolkata"
    assert profile["location_state"] == "West Bengal"
    assert profile["location_country"] == "India"
    assert profile["experience_start_date"] == "2018-01-01"
    persisted_profile = client.get("/auth/profile", headers=auth_headers).json()
    assert persisted_profile["location_city"] == "Kolkata"
    assert persisted_profile["location_state"] == "West Bengal"
    assert persisted_profile["location_country"] == "India"
    assert persisted_profile["experience_start_date"] == "2018-01-01"
    admin_partial_update = client.put(
        f"/workspaces/{workspace_id}/users/{current_member['user_id']}/profile",
        json={
            "name": "Updated Profile Name",
            "department": "Engineering",
            "professional_title": "Project Lead",
            "experience_start_date": "2018-01-01",
            "skills": "Planning, Leadership, APIs, Coaching",
        },
        headers=auth_headers,
    )
    assert admin_partial_update.status_code == 200
    assert admin_partial_update.json()["phone"] == "9999999999"
    assert admin_partial_update.json()["location_city"] == "Kolkata"
    assert client.get("/auth/me", headers=auth_headers).json()["name"] == "Updated Profile Name"
    renamed = client.patch(
        f"/workspaces/{workspace_id}/departments/{department['id']}",
        json={"name": "IT"},
        headers=auth_headers,
    )
    assert renamed.status_code == 200
    assert client.get("/auth/profile", headers=auth_headers).json()["department"] == "IT"
    assert client.post(
        f"/workspaces/{workspace_id}/departments",
        json={"name": "it"}, headers=auth_headers,
    ).status_code == 409
    assert client.delete(
        f"/workspaces/{workspace_id}/departments/{department['id']}",
        headers=auth_headers,
    ).status_code == 204
    cleared_profile = client.get("/auth/profile", headers=auth_headers).json()
    assert cleared_profile["department"] is None
    assert cleared_profile["professional_title"] is None
    assert designation["id"] not in {
        item["id"] for item in client.get(
            f"/workspaces/{workspace_id}/designations", headers=auth_headers
        ).json()
    }


def test_incomplete_profile_cannot_be_allocated_and_member_cannot_set_admin_fields(
    client: TestClient, auth_headers: dict[str, str]
):
    member = client.post(
        "/auth/register",
        json={"name": "Incomplete Member", "email": "incomplete@example.com", "password": "securepass123"},
    ).json()
    workspace = client.post(
        "/workspaces", json={"name": "Profile rules"}, headers=auth_headers
    ).json()
    client.patch(
        f"/workspaces/{workspace['id']}/users/{member['id']}/approve",
        headers=auth_headers,
    )
    operations = client.post(
        f"/workspaces/{workspace['id']}/departments",
        json={"name": "Operations"}, headers=auth_headers,
    ).json()
    client.post(
        f"/workspaces/{workspace['id']}/designations",
        json={"name": "Analyst", "department_id": operations["id"]}, headers=auth_headers,
    )
    assigned = client.patch(
        f"/admin/users/{member['id']}/member",
        json={"role": "member", "department": "Operations", "professional_title": "Analyst"},
        headers=auth_headers,
    )
    assert assigned.status_code == 200
    admin = client.get("/auth/me", headers=auth_headers).json()
    admin_profile = client.put(
        f"/admin/users/{admin['id']}/profile",
        json={
            "name": admin["name"], "profile_image": valid_profile_image(),
            "phone": "5550102000", "location_city": "Admin City",
            "location_state": "Admin State", "location_country": "Admin Country",
            "bio": "Administrator", "department": "Operations",
            "professional_title": "Analyst", "experience_start_date": "2023-01-01",
            "skills": "Leadership", "achievements": "",
        }, headers=auth_headers,
    )
    assert admin_profile.status_code == 200
    project = client.post(
        f"/workspaces/{workspace['id']}/projects",
        json={"name": "Profile project", "start_date": "2026-08-01", "end_date": "2026-12-31"},
        headers=auth_headers,
    ).json()
    team = client.post(
        f"/workspaces/{workspace['id']}/teams",
        json={"name": "Profile team", "manager_user_id": admin["id"], "manager_designation": "Analyst"},
        headers=auth_headers,
    ).json()
    blocked = client.post(
        f"/workspaces/{workspace['id']}/teams/{team['id']}/members",
        json={"user_id": member["id"], "project_id": project["id"], "designation": "Analyst"},
        headers=auth_headers,
    )
    assert blocked.status_code == 400
    assert "profile is only" in blocked.json()["detail"]
    assert "At least 50%" in blocked.json()["detail"]

    login = client.post(
        "/auth/login", data={"username": "incomplete@example.com", "password": "securepass123"}
    ).json()
    member_headers = {"Authorization": f"Bearer {login['access_token']}"}
    forbidden = client.put(
        "/auth/profile",
        json={"name": "Incomplete Member", "professional_title": "Manager", "department": "Management"},
        headers=member_headers,
    )
    assert forbidden.status_code == 403
    assert "Only an admin" in forbidden.json()["detail"]

    sent = client.post(
        f"/notifications/profile-completion/{workspace['id']}",
        json={"user_ids": [member["id"]]},
        headers=auth_headers,
    )
    assert sent.status_code == 200
    assert sent.json()["sent_count"] == 1
    member_notifications = client.get("/notifications", headers=member_headers).json()
    assert member_notifications["unread_count"] == 1
    reminder = member_notifications["items"][0]
    assert reminder["kind"] == "profile_completion"
    assert reminder["severity"] == "normal"
    assert reminder["id"].startswith("profile-")
    marked_read = client.patch(
        f"/notifications/{reminder['id']}/read", headers=member_headers
    )
    assert marked_read.status_code == 200
    assert marked_read.json()["is_read"] is True

    custom = client.post(
        f"/notifications/profile-completion/{workspace['id']}",
        json={
            "user_ids": [member["id"]],
            "title": "Profile information required",
            "message": "Please complete your profile before Friday's allocation review.",
        },
        headers=auth_headers,
    )
    assert custom.status_code == 200
    refreshed_reminder = client.get("/notifications", headers=member_headers).json()["items"][0]
    assert refreshed_reminder["title"] == "Profile information required"
    assert refreshed_reminder["message"] == "Please complete your profile before Friday's allocation review."
    assert refreshed_reminder["is_read"] is False
    mark_all = client.patch("/notifications/read-all", headers=member_headers)
    assert mark_all.status_code == 200
    assert mark_all.json()["marked_count"] == 1
    assert client.get("/notifications", headers=member_headers).json()["unread_count"] == 0


def test_global_reminders_and_announcements_work_without_workspace(
    client: TestClient, auth_headers: dict[str, str]
):
    member = client.post(
        "/auth/register",
        json={"name": "Global Notice", "email": "notice@example.com", "password": "securepass123"},
    ).json()
    assert client.patch(f"/admin/users/{member['id']}/approve", headers=auth_headers).status_code == 200
    department = client.post(
        "/admin/departments", json={"name": "Support"}, headers=auth_headers,
    ).json()
    assert client.post(
        "/admin/designations",
        json={"name": "Support Agent", "department_id": department["id"]},
        headers=auth_headers,
    ).status_code == 201
    assert client.patch(
        f"/admin/users/{member['id']}/member",
        json={"role": "member", "department": "Support", "professional_title": "Support Agent"},
        headers=auth_headers,
    ).status_code == 200
    login = client.post(
        "/auth/login", data={"username": "notice@example.com", "password": "securepass123"}
    ).json()
    member_headers = {"Authorization": f"Bearer {login['access_token']}"}

    reminder = client.post(
        "/notifications/profile-completion", json={"user_ids": [member["id"]]}, headers=auth_headers,
    )
    assert reminder.status_code == 200
    assert reminder.json()["sent_count"] == 1
    announcement = client.post(
        "/admin/announcements",
        json={"audience": "selected", "user_ids": [member["id"]], "title": "Company update", "message": "This is a global announcement."},
        headers=auth_headers,
    )
    assert announcement.status_code == 200
    assert announcement.json()["sent_count"] == 1

    items = client.get("/notifications", headers=member_headers).json()["items"]
    assert any(item["id"].startswith("global-profile-") for item in items)
    global_announcement = next(item for item in items if item["id"].startswith("announcement-"))
    assert global_announcement["workspace_id"] is None
    assert client.patch(
        f"/notifications/{global_announcement['id']}/read", headers=member_headers
    ).status_code == 200

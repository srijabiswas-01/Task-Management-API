from fastapi.testclient import TestClient


def test_chat_history_survives_relogin_and_clear_is_conversation_scoped(
    client: TestClient, auth_headers: dict[str, str]
):
    workspace = client.post(
        "/workspaces", json={"name": "Persistent chat"}, headers=auth_headers
    ).json()
    first = client.post(
        f"/workspaces/{workspace['id']}/chat/conversations",
        json={"chat_type": "broadcast", "name": "First conversation"},
        headers=auth_headers,
    ).json()
    second = client.post(
        f"/workspaces/{workspace['id']}/chat/conversations",
        json={"chat_type": "broadcast", "name": "Second conversation"},
        headers=auth_headers,
    ).json()

    for conversation, body in ((first, "Permanent first"), (second, "Permanent second")):
        response = client.post(
            f"/workspaces/{workspace['id']}/chat/conversations/{conversation['id']}/messages",
            json={"body": body},
            headers=auth_headers,
        )
        assert response.status_code == 201

    # Obtain a new token to simulate returning after logout/login. Nothing in
    # chat retrieval depends on browser memory or the previous token.
    relogin = client.post(
        "/auth/login",
        data={"username": "test@example.com", "password": "securepass123"},
    )
    relogin_headers = {
        "Authorization": f"Bearer {relogin.json()['access_token']}"
    }
    conversations = client.get(
        f"/workspaces/{workspace['id']}/chat/conversations",
        headers=relogin_headers,
    ).json()
    assert {item["id"] for item in conversations} == {first["id"], second["id"]}
    assert next(item for item in conversations if item["id"] == first["id"])[
        "can_clear"
    ] is True
    history = client.get(
        f"/workspaces/{workspace['id']}/chat/conversations/{first['id']}/messages",
        headers=relogin_headers,
    )
    assert [item["body"] for item in history.json()] == ["Permanent first"]

    cleared = client.delete(
        f"/workspaces/{workspace['id']}/chat/conversations/{first['id']}/messages",
        headers=relogin_headers,
    )
    assert cleared.status_code == 204
    assert client.get(
        f"/workspaces/{workspace['id']}/chat/conversations/{first['id']}/messages",
        headers=relogin_headers,
    ).json() == []
    assert [item["body"] for item in client.get(
        f"/workspaces/{workspace['id']}/chat/conversations/{second['id']}/messages",
        headers=relogin_headers,
    ).json()] == ["Permanent second"]


def test_regular_member_cannot_clear_conversation(
    client: TestClient, auth_headers: dict[str, str]
):
    member = client.post(
        "/auth/register",
        json={
            "name": "Chat Member",
            "email": "persistent-member@example.com",
            "password": "securepass123",
        },
    ).json()
    workspace = client.post(
        "/workspaces", json={"name": "Protected chat"}, headers=auth_headers
    ).json()
    client.patch(
        f"/workspaces/{workspace['id']}/users/{member['id']}/approve",
        headers=auth_headers,
    )
    client.post(
        f"/workspaces/{workspace['id']}/members",
        json={"email": member["email"], "role": "member"},
        headers=auth_headers,
    )
    member_login = client.post(
        "/auth/login",
        data={"username": member["email"], "password": "securepass123"},
    ).json()
    member_headers = {
        "Authorization": f"Bearer {member_login['access_token']}"
    }
    conversation = client.post(
        f"/workspaces/{workspace['id']}/chat/conversations",
        json={"chat_type": "broadcast", "name": "Protected"},
        headers=auth_headers,
    ).json()
    response = client.delete(
        f"/workspaces/{workspace['id']}/chat/conversations/{conversation['id']}/messages",
        headers=member_headers,
    )
    assert response.status_code == 403

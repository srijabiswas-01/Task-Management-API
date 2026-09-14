import json
import sys
from pathlib import Path

# Allow this script to be executed directly from the repository root without
# requiring callers to modify PYTHONPATH or install the application package.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import inspect, text

from app.database import engine


CHECKS = {
    "users_without_organization": "SELECT count(*) FROM users WHERE organization_id IS NULL",
    "workspaces_without_organization": "SELECT count(*) FROM workspaces WHERE organization_id IS NULL",
    "teams_without_organization": "SELECT count(*) FROM teams WHERE organization_id IS NULL",
    "chats_without_organization": "SELECT count(*) FROM chat_conversations WHERE organization_id IS NULL",
    "workspace_owner_tenant_mismatch": "SELECT count(*) FROM workspaces w JOIN users u ON u.id=w.owner_id WHERE w.organization_id<>u.organization_id",
    "workspace_member_tenant_mismatch": "SELECT count(*) FROM workspace_members wm JOIN workspaces w ON w.id=wm.workspace_id JOIN users u ON u.id=wm.user_id WHERE w.organization_id<>u.organization_id",
    "team_workspace_tenant_mismatch": "SELECT count(*) FROM teams t JOIN workspaces w ON w.id=t.workspace_id WHERE t.organization_id<>w.organization_id",
    "global_team_member_tenant_mismatch": "SELECT count(*) FROM global_team_members gm JOIN teams t ON t.id=gm.team_id JOIN users u ON u.id=gm.user_id WHERE t.organization_id<>u.organization_id",
    "chat_workspace_tenant_mismatch": "SELECT count(*) FROM chat_conversations c JOIN workspaces w ON w.id=c.workspace_id WHERE c.organization_id<>w.organization_id",
    "chat_creator_tenant_mismatch": "SELECT count(*) FROM chat_conversations c JOIN users u ON u.id=c.created_by_id WHERE c.organization_id<>u.organization_id",
    "task_assignee_tenant_mismatch": "SELECT count(*) FROM task_assignees a JOIN users u ON u.id=a.user_id JOIN tasks t ON t.id=a.task_id JOIN projects p ON p.id=t.project_id JOIN workspaces w ON w.id=p.workspace_id WHERE u.organization_id<>w.organization_id",
    "orphan_chat_participant_conversation": "SELECT count(*) FROM chat_participants p LEFT JOIN chat_conversations c ON c.id=p.conversation_id WHERE c.id IS NULL",
    "orphan_chat_participant_user": "SELECT count(*) FROM chat_participants p LEFT JOIN users u ON u.id=p.user_id WHERE u.id IS NULL",
    "orphan_chat_message_conversation": "SELECT count(*) FROM chat_messages m LEFT JOIN chat_conversations c ON c.id=m.conversation_id WHERE c.id IS NULL",
    "orphan_chat_message_sender": "SELECT count(*) FROM chat_messages m LEFT JOIN users u ON u.id=m.sender_id WHERE u.id IS NULL",
    "orphan_chat_notification_message": "SELECT count(*) FROM chat_notifications n LEFT JOIN chat_messages m ON m.id=n.message_id WHERE m.id IS NULL",
    "orphan_chat_notification_conversation": "SELECT count(*) FROM chat_notifications n LEFT JOIN chat_conversations c ON c.id=n.conversation_id WHERE c.id IS NULL",
    "orphan_chat_notification_user": "SELECT count(*) FROM chat_notifications n LEFT JOIN users u ON u.id=n.user_id WHERE u.id IS NULL",
    "orphan_team_allocation": "SELECT count(*) FROM team_members a LEFT JOIN teams t ON t.id=a.team_id LEFT JOIN users u ON u.id=a.user_id LEFT JOIN projects p ON p.id=a.project_id WHERE t.id IS NULL OR u.id IS NULL OR p.id IS NULL",
    "orphan_global_team_allocation": "SELECT count(*) FROM global_team_members a LEFT JOIN teams t ON t.id=a.team_id LEFT JOIN users u ON u.id=a.user_id WHERE t.id IS NULL OR u.id IS NULL",
    "duplicate_participants": "SELECT count(*) FROM (SELECT conversation_id,user_id FROM chat_participants GROUP BY conversation_id,user_id HAVING count(*)>1) duplicates",
    "duplicate_notifications": "SELECT count(*) FROM (SELECT message_id,user_id FROM chat_notifications GROUP BY message_id,user_id HAVING count(*)>1) duplicates",
    "invalid_project_conversations": "SELECT count(*) FROM chat_conversations WHERE chat_type='project' AND project_id IS NULL",
    "invalid_team_conversations": "SELECT count(*) FROM chat_conversations WHERE chat_type='team' AND team_id IS NULL",
    "future_revocations": "SELECT count(*) FROM chat_participants WHERE access_revoked_at > CURRENT_TIMESTAMP",
}

TABLES = (
    "organizations", "users", "workspaces", "projects", "teams", "team_members",
    "global_team_members", "chat_conversations", "chat_participants",
    "chat_messages", "chat_notifications",
)


def main() -> None:
    inspector = inspect(engine)
    with engine.connect() as connection:
        database_name = (
            connection.scalar(text("select current_database()"))
            if engine.dialect.name == "postgresql" else str(engine.url.database)
        )
        migration_revision = (
            connection.scalar(text("SELECT version_num FROM alembic_version"))
            if inspector.has_table("alembic_version") else None
        )
        result = {
            "database": database_name,
            "dialect": engine.dialect.name,
            "checks": {name: connection.scalar(text(statement)) for name, statement in CHECKS.items()},
            "counts": {table: connection.scalar(text(f'SELECT count(*) FROM "{table}"')) for table in TABLES},
            "migration_revision": migration_revision,
            "tenant_schema": {
                table: {
                    "organization_nullable": next(
                        column["nullable"] for column in inspector.get_columns(table)
                        if column["name"] == "organization_id"
                    ),
                    "organization_fk": any(
                        fk.get("referred_table") == "organizations"
                        and "organization_id" in fk.get("constrained_columns", [])
                        for fk in inspector.get_foreign_keys(table)
                    ),
                }
                for table in (
                    "users", "workspaces", "teams", "global_departments",
                    "global_designations", "global_skills", "organization_holidays",
                    "chat_conversations",
                )
            },
            "chat_participant_columns": {
                column["name"]: {"type": str(column["type"]), "nullable": column["nullable"]}
                for column in inspector.get_columns("chat_participants")
                if column["name"] in {"last_read_at", "access_revoked_at"}
            },
        }
    result["data_healthy"] = all(value == 0 for value in result["checks"].values())
    result["tenant_schema_healthy"] = all(
        not state["organization_nullable"] and state["organization_fk"]
        for state in result["tenant_schema"].values()
    )
    result["migration_tracking_healthy"] = result["migration_revision"] is not None
    result["healthy"] = (
        result["data_healthy"]
        and result["tenant_schema_healthy"]
        and result["migration_tracking_healthy"]
    )
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()

import json

from sqlalchemy import inspect, text

from app.database import engine


CHECKS = {
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
    "future_revocations": "SELECT count(*) FROM chat_participants WHERE access_revoked_at > now()",
}

TABLES = (
    "users", "workspaces", "projects", "teams", "team_members",
    "global_team_members", "chat_conversations", "chat_participants",
    "chat_messages", "chat_notifications",
)


def main() -> None:
    inspector = inspect(engine)
    with engine.connect() as connection:
        result = {
            "database": connection.scalar(text("select current_database()")),
            "dialect": engine.dialect.name,
            "checks": {name: connection.scalar(text(statement)) for name, statement in CHECKS.items()},
            "counts": {table: connection.scalar(text(f'SELECT count(*) FROM "{table}"')) for table in TABLES},
            "chat_participant_columns": {
                column["name"]: {"type": str(column["type"]), "nullable": column["nullable"]}
                for column in inspector.get_columns("chat_participants")
                if column["name"] in {"last_read_at", "access_revoked_at"}
            },
        }
    result["healthy"] = all(value == 0 for value in result["checks"].values())
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()

"""Add notification retention and reminder timestamps.

Revision ID: 0002_notification_lifecycle
Revises: 0001_current_schema
"""

from alembic import op
import sqlalchemy as sa

revision = "0002_notification_lifecycle"
down_revision = "0001_current_schema"
branch_labels = None
depends_on = None

TABLES = (
    "notifications",
    "profile_completion_reminders",
    "global_profile_reminders",
    "global_announcements",
    "chat_notifications",
)


def upgrade() -> None:
    bind = op.get_bind()
    for table in TABLES:
        # Some development installations gained these columns through the
        # application's compatibility startup before Alembic was introduced.
        # Inspect each table so upgrading those databases remains safe.
        columns = {column["name"] for column in sa.inspect(bind).get_columns(table)}
        if "read_at" not in columns:
            op.add_column(table, sa.Column("read_at", sa.DateTime(timezone=True), nullable=True))
        if "last_reminded_at" not in columns:
            op.add_column(table, sa.Column("last_reminded_at", sa.DateTime(timezone=True), nullable=True))
        if "is_persistent" not in columns:
            op.add_column(table, sa.Column("is_persistent", sa.Boolean(), nullable=False, server_default=sa.false()))
        indexes = {index["name"] for index in sa.inspect(bind).get_indexes(table)}
        if f"ix_{table}_read_at" not in indexes:
            op.create_index(f"ix_{table}_read_at", table, ["read_at"])
    # Existing read records begin their 24-hour retention period at migration time.
    for table in TABLES:
        op.execute(sa.text(f"UPDATE {table} SET read_at = CURRENT_TIMESTAMP WHERE is_read = true AND read_at IS NULL"))


def downgrade() -> None:
    bind = op.get_bind()
    for table in reversed(TABLES):
        indexes = {index["name"] for index in sa.inspect(bind).get_indexes(table)}
        if f"ix_{table}_read_at" in indexes:
            op.drop_index(f"ix_{table}_read_at", table_name=table)
        columns = {column["name"] for column in sa.inspect(bind).get_columns(table)}
        for column in ("is_persistent", "last_reminded_at", "read_at"):
            if column in columns:
                op.drop_column(table, column)

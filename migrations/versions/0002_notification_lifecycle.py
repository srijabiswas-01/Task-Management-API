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
    for table in TABLES:
        op.add_column(table, sa.Column("read_at", sa.DateTime(timezone=True), nullable=True))
        op.add_column(table, sa.Column("last_reminded_at", sa.DateTime(timezone=True), nullable=True))
        op.add_column(table, sa.Column("is_persistent", sa.Boolean(), nullable=False, server_default=sa.false()))
        op.create_index(f"ix_{table}_read_at", table, ["read_at"])
    # Existing read records begin their 24-hour retention period at migration time.
    for table in TABLES:
        op.execute(sa.text(f"UPDATE {table} SET read_at = CURRENT_TIMESTAMP WHERE is_read = true AND read_at IS NULL"))


def downgrade() -> None:
    for table in reversed(TABLES):
        op.drop_index(f"ix_{table}_read_at", table_name=table)
        op.drop_column(table, "is_persistent")
        op.drop_column(table, "last_reminded_at")
        op.drop_column(table, "read_at")

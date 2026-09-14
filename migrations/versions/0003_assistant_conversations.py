"""Add private AI assistant conversations.

Revision ID: 0003_assistant_conversations
Revises: 0002_notification_lifecycle
"""

from alembic import op
from app.database import Base
from app import models  # noqa: F401

revision = "0003_assistant_conversations"
down_revision = "0002_notification_lifecycle"
branch_labels = None
depends_on = None


def upgrade() -> None:
    Base.metadata.tables["assistant_conversations"].create(op.get_bind(), checkfirst=True)
    Base.metadata.tables["assistant_messages"].create(op.get_bind(), checkfirst=True)


def downgrade() -> None:
    op.drop_table("assistant_messages")
    op.drop_table("assistant_conversations")

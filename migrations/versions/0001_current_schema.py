"""Create the current Orbit schema for new installations.

Revision ID: 0001_current_schema
Revises:
"""

from alembic import op

from app.database import Base
from app import models  # noqa: F401


revision = "0001_current_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    # Data-bearing application tables are intentionally not dropped
    # automatically. Restore from backup for a complete schema rollback.
    pass

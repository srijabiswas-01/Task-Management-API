"""Add organization tenancy and backfill legacy data into ABC Organization.

Revision ID: 0004_multi_organization
Revises: 0003_assistant_conversations
"""

from alembic import op
import sqlalchemy as sa

revision = "0004_multi_organization"
down_revision = "0003_assistant_conversations"
branch_labels = None
depends_on = None

TENANT_TABLES = (
    "users", "workspaces", "teams", "global_departments",
    "global_designations", "global_skills", "organization_holidays", "chat_conversations",
)


def upgrade() -> None:
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    if "organizations" not in inspector.get_table_names():
        op.create_table(
            "organizations",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("name", sa.String(180), nullable=False),
            sa.Column("slug", sa.String(190), nullable=False),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("slug", name="uq_organizations_slug"),
        )
        op.create_index("ix_organizations_name", "organizations", ["name"])
    connection.execute(sa.text(
        "INSERT INTO organizations (name, slug, is_active) "
        "SELECT 'ABC Organization', 'abc-organization', TRUE "
        "WHERE NOT EXISTS (SELECT 1 FROM organizations WHERE slug = 'abc-organization' "
        "OR lower(name) = lower('ABC Organization'))"
    ))
    organization_id = connection.execute(sa.text(
        "SELECT id FROM organizations WHERE slug = 'abc-organization' "
        "OR lower(name) = lower('ABC Organization') "
        "ORDER BY CASE WHEN slug = 'abc-organization' THEN 0 ELSE 1 END, id LIMIT 1"
    )).scalar_one()

    inspector = sa.inspect(connection)
    for table in TENANT_TABLES:
        columns = {column["name"] for column in inspector.get_columns(table)}
        existing_indexes = {
            item["name"] for item in inspector.get_indexes(table) if item.get("name")
        }
        if "organization_id" not in columns:
            op.add_column(table, sa.Column("organization_id", sa.Integer(), nullable=True))
            op.create_foreign_key(
                f"fk_{table}_organization_id", table, "organizations",
                ["organization_id"], ["id"], ondelete="RESTRICT" if table == "users" else "CASCADE",
            )
        if table == "workspaces":
            connection.execute(sa.text(
                "UPDATE workspaces SET organization_id = COALESCE(organization_id, "
                "(SELECT organization_id FROM users WHERE users.id = workspaces.owner_id), :org_id)"
            ), {"org_id": organization_id})
        elif table == "teams":
            connection.execute(sa.text(
                "UPDATE teams SET organization_id = COALESCE(organization_id, "
                "(SELECT organization_id FROM workspaces WHERE workspaces.id = teams.workspace_id), :org_id)"
            ), {"org_id": organization_id})
        elif table == "chat_conversations":
            connection.execute(sa.text(
                "UPDATE chat_conversations SET organization_id = COALESCE(organization_id, "
                "(SELECT organization_id FROM workspaces WHERE workspaces.id = chat_conversations.workspace_id), "
                "(SELECT organization_id FROM users WHERE users.id = chat_conversations.created_by_id), :org_id)"
            ), {"org_id": organization_id})
        else:
            connection.execute(sa.text(
                f"UPDATE {table} SET organization_id = :org_id WHERE organization_id IS NULL"
            ), {"org_id": organization_id})
        with op.batch_alter_table(table) as batch:
            batch.alter_column("organization_id", existing_type=sa.Integer(), nullable=False)
            index_name = f"ix_{table}_organization_id"
            if index_name not in existing_indexes:
                batch.create_index(index_name, ["organization_id"])

    # Organization names and catalog names are case-insensitively unique per tenant.
    organization_indexes = {
        item["name"] for item in sa.inspect(connection).get_indexes("organizations")
        if item.get("name")
    }
    if "uq_organizations_name_ci" not in organization_indexes:
        op.create_index("uq_organizations_name_ci", "organizations", [sa.text("lower(name)")], unique=True)
    for table, old_names in (
        ("global_departments", {"uq_global_department_name", "ix_global_departments_name"}),
        ("global_designations", {"uq_global_designation_name"}),
        ("global_skills", {"uq_global_skills_name", "ix_global_skills_name"}),
    ):
        inspector = sa.inspect(connection)
        constraints = {item["name"] for item in inspector.get_unique_constraints(table) if item.get("name")}
        indexes = {item["name"] for item in inspector.get_indexes(table) if item.get("unique")}
        with op.batch_alter_table(table) as batch:
            for name in old_names & constraints:
                batch.drop_constraint(name, type_="unique")
            for name in old_names & indexes:
                batch.drop_index(name)
    for name, table in (
        ("uq_org_department_name_ci", "global_departments"),
        ("uq_org_designation_name_ci", "global_designations"),
        ("uq_org_skill_name_ci", "global_skills"),
    ):
        indexes = {
            item["name"] for item in sa.inspect(connection).get_indexes(table)
            if item.get("name")
        }
        if name not in indexes:
            op.create_index(name, table, ["organization_id", sa.text("lower(name)")], unique=True)


def downgrade() -> None:
    op.drop_index("uq_org_skill_name_ci", table_name="global_skills")
    op.drop_index("uq_org_designation_name_ci", table_name="global_designations")
    op.drop_index("uq_org_department_name_ci", table_name="global_departments")
    for table in reversed(TENANT_TABLES):
        with op.batch_alter_table(table) as batch:
            batch.drop_index(f"ix_{table}_organization_id")
            batch.drop_column("organization_id")
    op.drop_index("uq_organizations_name_ci", table_name="organizations")
    op.drop_index("ix_organizations_name", table_name="organizations")
    op.drop_table("organizations")

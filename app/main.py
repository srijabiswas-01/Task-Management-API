from contextlib import asynccontextmanager
import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import inspect, select, text
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.database import Base, engine
from app.models import Department, Designation, GlobalDepartment, GlobalDesignation
from app.routers import admin, ai, auth, boards, chat, notifications, projects, tasks, workspaces

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Alembic is preferred in production. This keeps local setup friction-free.
    Base.metadata.create_all(bind=engine)
    # create_all does not add columns to an existing local database. Keep this
    # small compatibility migration so current installations gain member access status.
    columns = {column["name"] for column in inspect(engine).get_columns("workspace_members")}
    if "is_active" not in columns:
        default = "1" if engine.dialect.name == "sqlite" else "TRUE"
        with engine.begin() as connection:
            connection.execute(text(
                f"ALTER TABLE workspace_members ADD COLUMN is_active BOOLEAN NOT NULL DEFAULT {default}"
            ))
    user_columns = {column["name"] for column in inspect(engine).get_columns("users")}
    if "is_system_admin" not in user_columns:
        default = "0" if engine.dialect.name == "sqlite" else "FALSE"
        with engine.begin() as connection:
            connection.execute(text(
                f"ALTER TABLE users ADD COLUMN is_system_admin BOOLEAN NOT NULL DEFAULT {default}"
            ))
    if "is_member" not in user_columns:
        default = "0" if engine.dialect.name == "sqlite" else "FALSE"
        with engine.begin() as connection:
            connection.execute(text(f"ALTER TABLE users ADD COLUMN is_member BOOLEAN NOT NULL DEFAULT {default}"))
            truth = "1" if engine.dialect.name == "sqlite" else "TRUE"
            connection.execute(text(f"UPDATE users SET is_member = {truth} WHERE is_system_admin = {truth} OR id IN (SELECT DISTINCT user_id FROM workspace_members)"))
            connection.execute(text(
                "UPDATE users SET is_system_admin = "
                + ("1" if engine.dialect.name == "sqlite" else "TRUE")
                + " WHERE id = (SELECT MIN(id) FROM users)"
            ))
    project_columns = {column["name"] for column in inspect(engine).get_columns("projects")}
    task_columns = {column["name"] for column in inspect(engine).get_columns("tasks")}
    team_member_columns = {column["name"] for column in inspect(engine).get_columns("team_members")}
    team_columns = {column["name"]: column for column in inspect(engine).get_columns("teams")}
    chat_message_columns = {column["name"] for column in inspect(engine).get_columns("chat_messages")} if inspect(engine).has_table("chat_messages") else set()
    designation_columns = {column["name"] for column in inspect(engine).get_columns("global_designations")}
    profile_columns = {column["name"] for column in inspect(engine).get_columns("user_profiles")}
    if team_columns.get("workspace_id") and not team_columns["workspace_id"].get("nullable", True):
        if engine.dialect.name == "sqlite":
            with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
                connection.execute(text("PRAGMA foreign_keys=OFF"))
                connection.execute(text("CREATE TABLE teams_globalized (id INTEGER NOT NULL PRIMARY KEY, workspace_id INTEGER REFERENCES workspaces(id) ON DELETE SET NULL, name VARCHAR(150) NOT NULL, description TEXT, created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL)"))
                connection.execute(text("INSERT INTO teams_globalized (id, workspace_id, name, description, created_at, updated_at) SELECT id, workspace_id, name, description, created_at, updated_at FROM teams"))
                connection.execute(text("DROP TABLE teams"))
                connection.execute(text("ALTER TABLE teams_globalized RENAME TO teams"))
                connection.execute(text("PRAGMA foreign_keys=ON"))
        else:
            with engine.begin() as connection:
                connection.execute(text("ALTER TABLE teams ALTER COLUMN workspace_id DROP NOT NULL"))
                connection.execute(text("ALTER TABLE teams DROP CONSTRAINT IF EXISTS teams_workspace_id_fkey"))
                connection.execute(text("ALTER TABLE teams ADD CONSTRAINT teams_workspace_id_fkey FOREIGN KEY (workspace_id) REFERENCES workspaces(id) ON DELETE SET NULL"))
    with engine.begin() as connection:
        if "phone_country_code" in profile_columns:
            connection.execute(text("ALTER TABLE user_profiles DROP COLUMN phone_country_code"))
        if "start_date" not in project_columns:
            connection.execute(text("ALTER TABLE projects ADD COLUMN start_date DATE"))
        if "end_date" not in project_columns:
            connection.execute(text("ALTER TABLE projects ADD COLUMN end_date DATE"))
        created_date = "date(created_at)" if engine.dialect.name == "sqlite" else "CAST(created_at AS DATE)"
        connection.execute(text(f"UPDATE projects SET start_date = {created_date} WHERE start_date IS NULL"))
        connection.execute(text(
            "UPDATE projects SET end_date = CASE "
            "WHEN deadline IS NOT NULL AND deadline >= start_date THEN deadline "
            "ELSE start_date END WHERE end_date IS NULL"
        ))
        compatibility_columns = (
            ("projects", project_columns, "contingency_percent", "INTEGER NOT NULL DEFAULT 15"),
            ("tasks", task_columns, "estimated_hours", "INTEGER"),
            ("tasks", task_columns, "planned_budget", "INTEGER"),
            ("tasks", task_columns, "actual_cost", "INTEGER"),
            ("team_members", team_member_columns, "allocation_percent", "INTEGER NOT NULL DEFAULT 100"),
            ("team_members", team_member_columns, "weekly_capacity_hours", "INTEGER NOT NULL DEFAULT 40"),
            ("user_profiles", profile_columns, "location_city", "VARCHAR(80)"),
            ("user_profiles", profile_columns, "location_state", "VARCHAR(80)"),
            ("user_profiles", profile_columns, "location_country", "VARCHAR(80)"),
            ("user_profiles", profile_columns, "experience_start_date", "DATE"),
        )
        for table, columns, column, definition in compatibility_columns:
            if column not in columns:
                connection.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {definition}"))
        if chat_message_columns:
            if "is_deleted" not in chat_message_columns:
                default = "0" if engine.dialect.name == "sqlite" else "FALSE"
                connection.execute(text(f"ALTER TABLE chat_messages ADD COLUMN is_deleted BOOLEAN NOT NULL DEFAULT {default}"))
            if "deleted_by_id" not in chat_message_columns:
                connection.execute(text("ALTER TABLE chat_messages ADD COLUMN deleted_by_id INTEGER REFERENCES users(id) ON DELETE SET NULL"))
        if "department_id" not in designation_columns:
            connection.execute(text(
                "ALTER TABLE global_designations ADD COLUMN department_id INTEGER "
                "REFERENCES global_departments(id) ON DELETE CASCADE"
            ))
        connection.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_global_department_name_ci "
            "ON global_departments (lower(name))"
        ))
        connection.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_global_designation_name_ci "
            "ON global_designations (lower(name))"
        ))
    with Session(engine) as db:
        global_designations = {
            item.name.casefold() for item in db.scalars(select(GlobalDesignation)).all()
        }
        for item in db.scalars(select(Designation).order_by(Designation.id)).all():
            if item.name.casefold() not in global_designations:
                db.add(GlobalDesignation(name=item.name, description=item.description))
                global_designations.add(item.name.casefold())
        global_departments = {
            item.name.casefold() for item in db.scalars(select(GlobalDepartment)).all()
        }
        for item in db.scalars(select(Department).order_by(Department.id)).all():
            if item.name.casefold() not in global_departments:
                db.add(GlobalDepartment(name=item.name, description=item.description))
                global_departments.add(item.name.casefold())
        db.commit()
    yield


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="JWT-secured API for workspaces, projects, sprints, and tasks.",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(OperationalError)
async def database_unavailable(_, __: OperationalError) -> JSONResponse:
    # Do not serialize SQL statements, parameters, emails, or connection URLs
    # into the HTTP response or application log.
    logger.warning("Database connection was temporarily unavailable")
    return JSONResponse(
        status_code=503,
        content={"detail": "Database is temporarily unavailable. Please try again."},
        headers={"Retry-After": "2"},
    )


@app.exception_handler(IntegrityError)
async def integrity_conflict(_, __: IntegrityError) -> JSONResponse:
    # Database constraints are the final authority during concurrent writes.
    # Keep internal table/statement details out of the public response.
    return JSONResponse(
        status_code=409,
        content={"detail": "This change conflicts with an existing record"},
    )

app.include_router(auth.router)
app.include_router(workspaces.router)
app.include_router(projects.router)
app.include_router(tasks.router)
app.include_router(boards.router)
app.include_router(ai.router)
app.include_router(notifications.router)
app.include_router(chat.router)
app.include_router(admin.router)

frontend_dir = Path(__file__).resolve().parent.parent / "frontend"
app.mount("/static", StaticFiles(directory=frontend_dir), name="static")


@app.get("/", tags=["System"])
def root() -> FileResponse:
    return FileResponse(frontend_dir / "index.html")


@app.get("/app", include_in_schema=False)
def frontend() -> FileResponse:
    return FileResponse(frontend_dir / "index.html")


@app.get("/app/{frontend_path:path}", include_in_schema=False)
def frontend_route(frontend_path: str) -> FileResponse:
    return FileResponse(frontend_dir / "index.html")


@app.get("/health", tags=["System"])
def health() -> dict[str, str]:
    return {"status": "ok"}

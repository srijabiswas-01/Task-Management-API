from contextlib import asynccontextmanager
import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import inspect, text
from sqlalchemy.exc import OperationalError

from app.core.config import settings
from app.database import Base, engine
from app.routers import ai, auth, boards, projects, tasks, workspaces

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

app.include_router(auth.router)
app.include_router(workspaces.router)
app.include_router(projects.router)
app.include_router(tasks.router)
app.include_router(boards.router)
app.include_router(ai.router)

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

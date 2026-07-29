# Task Management API

A FastAPI backend for a Jira/Trello-style task management platform. The first
working foundation includes users, JWT authentication, workspaces, membership,
teams, projects, sprints, tasks, comments, and dashboard totals.

Authentication is deliberately limited to:

- Formal user registration
- Form-encoded login
- JWT bearer authentication

OAuth, email verification, password reset, and third-party login are not part of
this implementation.

## Run locally

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
Copy-Item .env.example .env
uvicorn app.main:app --reload
```

Open `http://127.0.0.1:8000` for the task management web app.
The frontend is served by FastAPI, so it does not need Node.js or a second
development server. Open `http://127.0.0.1:8000/docs` for the interactive API
documentation.
SQLite is the zero-configuration default. Set `DATABASE_URL` in `.env` to a
PostgreSQL connection string for deployment.

## Web app

The included responsive frontend provides:

- Registration and login
- Workspace creation and switching
- Dashboard metrics
- Project and sprint management
- Scrum or Kanban framework selection per project
- Framework-aware navigation with Scrum-only, project-specific sprints
- Single active sprint enforcement and product-backlog filtering
- Trello-style task and list drag-and-drop
- Custom board lists with rename, color, delete, and reorder controls
- Automatic two-way synchronization between task status and board list
- Multiple task assignees and start/end date-time scheduling
- Project Gantt chart with scheduled and unscheduled task views
- Trello-style task checklists with automatic completion progress
- Persistent light and dark themes with responsive, accessible UI styling
- Task creation, editing, deletion, and comments
- Workspace members and teams

After signing in, create a workspace and project. The task board will then let
you use the API through normal forms instead of Swagger.

## Authentication

Register with JSON:

```http
POST /auth/register
Content-Type: application/json

{"name":"Jane Doe","email":"jane@example.com","password":"securepass123"}
```

Login uses a standard form. Put the email in the `username` field:

```http
POST /auth/login
Content-Type: application/x-www-form-urlencoded

username=jane@example.com&password=securepass123
```

Send the returned token on protected requests:

```http
Authorization: Bearer <access_token>
```

## Main endpoints

- `POST /auth/register`, `POST /auth/login`, `GET /auth/me`
- `GET|POST /workspaces`
- `GET|POST /workspaces/{id}/members`
- `GET|POST /workspaces/{id}/teams`
- `GET|POST /workspaces/{id}/projects`
- `GET|PATCH /projects/{id}`
- `GET|POST /projects/{id}/sprints`
- `GET|POST /projects/{id}/tasks`
- `GET|PATCH|DELETE /tasks/{id}`
- `GET|POST /tasks/{id}/comments`
- `GET /workspaces/{id}/dashboard`

## Tests and migrations

```powershell
pytest
alembic revision --autogenerate -m "initial schema"
alembic upgrade head
```

For production, generate and commit an Alembic migration before deployment,
replace the JWT secret, configure PostgreSQL, and restrict CORS origins.

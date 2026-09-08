# Orbit Task Management

Orbit is a FastAPI-powered project and task management platform with a responsive
single-page frontend. It combines global user and team administration, independent
workspace/project management, Scrum and Kanban boards, detailed task allocation,
AI-assisted planning, messaging, notifications, analytics, reports, and PDF exports.

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
- Workspace overview metrics
- Project and sprint management
- Scrum or Kanban framework selection per project
- Framework-aware navigation with Scrum-only, project-specific sprints
- Single active sprint enforcement and product-backlog filtering
- Trello-style task and list drag-and-drop
- Custom board lists with rename, color, delete, and reorder controls
- Automatic two-way synchronization between task status and board list
- Independent global teams and projects, with members assigned when tasks require them
- Multi-team task allocation with member responsibilities and planned hours
- Department, designation, skill, profile-completion, and workload-aware allocation
- Monday–Saturday working-day estimates that exclude Sundays and configured holidays
- Automatic estimated hours, working days, and INR planned-budget calculations
- Project-date validation for every task schedule
- Project Gantt chart with scheduled and unscheduled task views
- Gantt timeline table with teams, members, progress, milestones, and delivery health
- Complete PDF downloads for task boards, Gantt charts, timelines, and project reports
- Trello-style task checklists with automatic completion progress
- Checklist validation before tasks can move to Done, with local drag-and-drop rollback
- Persistent light and dark themes with responsive, accessible UI styling
- Task creation, editing, deletion, comments, and permitted comment deletion
- AI-generated task-plan previews with optional multiple teams and editable member selection
- AI calculations for working days, hours, story points, responsibilities, and planned budget
- Automatic Gemini, Groq, OpenRouter, and Hugging Face fallback
- Global Messages with Admin direct messaging, project chats, team chats, announcements,
  unread tracking, persistent replies, and clickable reply references
- Global Notifications, profile reminders, and custom announcements
- Admin-only Users, People & Teams, Skills, and Team & Member Analytics pages

After signing in, an Admin can approve accounts, assign Admin or Member access,
manage global organisation data, and create workspaces/projects. Members can use
the global communication and profile features even before being assigned to a
workspace. Workspace-dependent project screens become available through allocation.

## Global access and organisation model

- The only application access roles are **Admin** and **Member**.
- Newly registered accounts remain approval-pending until an Admin approves them.
- An approved account can sign in before being assigned an application role.
- Admins have Member capabilities plus global administration permissions.
- Users, People & Teams, Skills, Messages, Notifications, departments,
  designations, and teams are global rather than workspace-owned workflows.
- Every designation belongs to one department.
- Every team member, including a team manager, can belong to only one global team.
- Department and designation are controlled by an Admin.
- Task/project allocation requires an active Admin or Member with a department,
  designation, team, and at least 50% profile completion.

## Skills directory and global catalogue

The Admin-only Skills page contains two coordinated areas:

- A searchable member directory with skill, department, designation, team, and
  eligibility filters; workload information; six members per page; and detailed
  task assignment with responsibility and planned hours.
- A global Skills catalogue with search, independent 10-item pagination, usage
  counts, and Add, Edit, and Delete actions.

Renaming or deleting a global skill updates every matching Admin and Member profile
in the same database transaction. Existing profile skills are imported into the
catalogue for backward compatibility. Skill pagination and search update only the
catalogue panel without reloading the complete page.

## Team & Member Analytics

The Admin-only global analytics page works without a selected workspace and places
all dashboards on one continuous report page:

- Executive overview KPIs
- Workforce and assignment-readiness diagrams
- Team performance and health
- Member performance
- Planned workload
- Skills coverage
- Department and designation coverage
- Resource-cost analysis
- Risks and final management insights

Shared filters cover role, account status, department, designation, team, project,
skill, eligibility, and free-text search. Teams and members open in right-side detail
panels. **Download complete report** exports all filtered dashboard sections and
records to one PDF, regardless of on-screen pagination.

## Project reports and exports

Project Report provides interactive filters, detailed delivery tables, resource
analysis, final insights, and professional visual reporting:

- Delivery, schedule, task-closure, and budget-utilisation gauges
- Schedule-versus-progress variance
- Workflow and priority distribution
- Scheduled-task coverage
- Budget, planned task cost, actual cost, and variance
- Team workload and assignment-hour diagrams
- Schedule-risk path and data-derived management insights

The Project Report PDF contains executive KPIs, workflow, budget and resource
analysis, risks, management insights, a complete task table, and individual task
detail pages. The Task Board PDF also includes the board plus detailed task records.

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
- `GET /projects/{id}/task-planning-options`
- `GET /projects/{id}/report`
- `POST /projects/{id}/ai/task-plan`
- `POST /projects/{id}/ai/task-plan/confirm`
- `GET|PATCH|DELETE /tasks/{id}`
- `GET|POST /tasks/{id}/comments`
- `GET|POST /tasks/{id}/checklist`
- `GET /workspaces/{id}/dashboard`
- `GET /admin/users`, `GET /admin/teams`, `GET /admin/team-members`
- `GET|POST /admin/departments`, `GET|POST /admin/designations`
- `GET|POST /admin/skill-catalog-items`
- `PATCH|DELETE /admin/skill-catalog-items/{id}`
- `GET /admin/team-member-analytics`
- `GET /chat/conversations`, `POST /chat/conversations`
- `GET /notifications`

## Tests and migrations

```powershell
pytest
alembic revision --autogenerate -m "initial schema"
alembic upgrade head
```

For production, generate and commit an Alembic migration before deployment,
replace the JWT secret, configure PostgreSQL (a pooled connection URL is
recommended), and restrict CORS origins.

## AI task planning

Copy the provider settings from `.env.example` into `.env` locally and into
Vercel Environment Variables for deployment. The board's **AI plan** button
generates a preview without changing project data. After review, confirmed
tasks are created together and placed in Backlog.

Project and team creation remain independent. Delivery teams are optional during
AI generation. Before confirmation, the Admin can select multiple teams and members,
edit responsibilities and hours, review calculated effort and cost, remove suggested
assignments, or create the generated tasks without assignees.

Providers are attempted in `AI_PROVIDER_ORDER`. A timeout, quota response,
network failure, or invalid generated plan moves to the next configured
provider. API keys remain server-side and must never be added to frontend code
or committed to Git.

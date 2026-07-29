const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const state = {
  token: localStorage.getItem("orbit_token"),
  user: null, workspaces: [], workspace: null, projects: [], project: null,
  tasks: [], sprints: [], members: [], teams: [], dashboard: null, board: null, view: "dashboard"
};
const VIEW_PATHS = {
  dashboard: "/app/overview",
  projects: "/app/projects",
  board: "/app/board",
  gantt: "/app/gantt",
  sprints: "/app/sprints",
  people: "/app/people"
};
const PATH_VIEWS = Object.fromEntries(
  Object.entries(VIEW_PATHS).map(([view,path]) => [path,view])
);
state.view = PATH_VIEWS[window.location.pathname] || "dashboard";
const savedTheme = localStorage.getItem("orbit_theme");
const initialTheme = savedTheme || (window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
document.documentElement.dataset.theme = initialTheme;
const STATUS = [
  ["backlog", "Backlog"], ["todo", "To do"], ["in_progress", "In progress"],
  ["review", "Review"], ["testing", "Testing"], ["done", "Done"]
];

function esc(value = "") {
  const div = document.createElement("div"); div.textContent = value ?? ""; return div.innerHTML;
}
function pretty(value = "") { return value.replaceAll("_", " ").replace(/\b\w/g, c => c.toUpperCase()); }
function date(value) { return value ? new Date(value).toLocaleDateString(undefined, {month:"short", day:"numeric", year:"numeric"}) : "Not set"; }
function dateTime(value) { return value ? new Date(value).toLocaleString(undefined, {month:"short",day:"numeric",year:"numeric",hour:"numeric",minute:"2-digit"}) : "Not set"; }
function inputDateTime(value) {
  if (!value) return "";
  const parsed = new Date(value);
  const local = new Date(parsed.getTime() - parsed.getTimezoneOffset() * 60000);
  return local.toISOString().slice(0,16);
}
function toast(message, error = false) {
  const el = $("#toast"); el.textContent = message; el.className = `toast show${error ? " error" : ""}`;
  clearTimeout(toast.timer); toast.timer = setTimeout(() => el.className = "toast", 3000);
}
async function api(path, options = {}) {
  const headers = {...(options.headers || {})};
  if (state.token) headers.Authorization = `Bearer ${state.token}`;
  if (options.body && !(options.body instanceof URLSearchParams)) headers["Content-Type"] = "application/json";
  const response = await fetch(path, {...options, headers});
  if (response.status === 401) { logout(false); throw new Error("Your session expired. Please sign in again."); }
  if (!response.ok) {
    let detail = "Something went wrong";
    try { const data = await response.json(); detail = Array.isArray(data.detail) ? data.detail.map(x => x.msg).join(", ") : data.detail; } catch {}
    throw new Error(detail);
  }
  return response.status === 204 ? null : response.json();
}
function formData(form) {
  return Object.fromEntries([...new FormData(form).entries()].map(([k,v]) => [k, v === "" ? null : v]));
}
function modal(html, onReady) {
  $("#modal-content").innerHTML = html; $("#modal").classList.remove("hidden"); onReady?.();
}
function closeModal() { $("#modal").classList.add("hidden"); $("#modal-content").innerHTML = ""; }

$("#modal-close").onclick = closeModal;
$("#modal").onclick = e => { if (e.target === $("#modal")) closeModal(); };
$("#theme-toggle").onclick = () => {
  const theme = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
  document.documentElement.dataset.theme = theme;
  localStorage.setItem("orbit_theme", theme);
  $('meta[name="theme-color"]').content = theme === "dark" ? "#100d19" : "#6c4cf1";
  toast(`${pretty(theme)} mode enabled`);
};

let registerMode = false;
$("#auth-switch").onclick = () => {
  registerMode = !registerMode;
  $("#login-form").classList.toggle("hidden", registerMode);
  $("#register-form").classList.toggle("hidden", !registerMode);
  $("#auth-title").textContent = registerMode ? "Create your account" : "Welcome back";
  $("#auth-subtitle").textContent = registerMode ? "Start organizing your team’s work in minutes." : "Sign in to continue to your workspace.";
  $("#switch-copy").textContent = registerMode ? "Already have an account?" : "New to Orbit?";
  $("#auth-switch").textContent = registerMode ? "Sign in" : "Create an account";
  $("#auth-error").classList.add("hidden");
};
$("#login-form").onsubmit = async e => {
  e.preventDefault();
  $("#auth-error").classList.add("hidden");
  const submitButton = $('button[type="submit"]', e.currentTarget);
  submitButton.disabled = true;
  submitButton.textContent = "Signing in…";
  const body = new URLSearchParams({username: $("#login-email").value, password: $("#login-password").value});
  try {
    const data = await api("/auth/login", {method:"POST", body, headers:{"Content-Type":"application/x-www-form-urlencoded"}});
    state.token = data.access_token; localStorage.setItem("orbit_token", state.token); await boot();
  } catch (err) {
    authError(err.message);
  } finally {
    submitButton.disabled = false;
    submitButton.innerHTML = "Sign in <span>→</span>";
  }
};
$("#register-form").onsubmit = async e => {
  e.preventDefault();
  try {
    await api("/auth/register", {method:"POST", body:JSON.stringify({name:$("#register-name").value,email:$("#register-email").value,password:$("#register-password").value})});
    const body = new URLSearchParams({username:$("#register-email").value,password:$("#register-password").value});
    const data = await api("/auth/login", {method:"POST",body,headers:{"Content-Type":"application/x-www-form-urlencoded"}});
    state.token = data.access_token; localStorage.setItem("orbit_token", state.token); await boot();
  } catch (err) { authError(err.message); }
};
function authError(message) { $("#auth-error").textContent = message; $("#auth-error").classList.remove("hidden"); }
function logout(show = true) {
  state.token = null;
  localStorage.removeItem("orbit_token");
  $("#auth-error").classList.add("hidden");
  $("#app-shell").classList.add("hidden");
  $("#auth-screen").classList.remove("hidden");
  if (show) toast("Signed out");
}
$("#logout-button").onclick = () => logout();

async function boot() {
  try {
    state.user = await api("/auth/me"); state.workspaces = await api("/workspaces");
    const savedId = Number(localStorage.getItem("orbit_workspace"));
    state.workspace = state.workspaces.find(w => w.id === savedId) || state.workspaces[0] || null;
    $("#user-name").textContent = state.user.name; $("#user-email").textContent = state.user.email;
    $("#user-avatar").textContent = state.user.name.slice(0,2).toUpperCase();
    $("#auth-error").classList.add("hidden");
    $("#auth-screen").classList.add("hidden"); $("#app-shell").classList.remove("hidden");
    if (!PATH_VIEWS[window.location.pathname]) {
      history.replaceState({view:state.view}, "", VIEW_PATHS[state.view]);
    }
    updateWorkspaceUI();
    if (!state.workspace) { renderNoWorkspace(); } else { await loadWorkspace(); }
  } catch (err) { if (state.token) authError(err.message); }
}
function updateWorkspaceUI() {
  $("#workspace-name").textContent = state.workspace?.name || "Choose workspace";
  $("#workspace-initial").textContent = state.workspace?.name?.[0]?.toUpperCase() || "W";
  $("#workspace-menu").innerHTML = state.workspaces.map(w => `<button data-id="${w.id}">${esc(w.name)}</button>`).join("") +
    (state.workspace ? `<button class="workspace-settings" data-workspace-settings="true">⚙ Workspace settings</button>` : "") +
    `<button class="new-workspace" data-new="true">＋ Create workspace</button>`;
  $$("[data-id]", $("#workspace-menu")).forEach(btn => btn.onclick = async () => {
    state.workspace = state.workspaces.find(w => w.id === Number(btn.dataset.id)); localStorage.setItem("orbit_workspace", state.workspace.id);
    $("#workspace-menu").classList.add("hidden"); updateWorkspaceUI(); await loadWorkspace();
  });
  $("[data-workspace-settings]", $("#workspace-menu"))?.addEventListener("click", workspaceSettingsModal);
  $("[data-new]", $("#workspace-menu")).onclick = workspaceModal;
}
function activeWorkspace() {
  if (state.workspace) return state.workspace;
  const savedId = Number(localStorage.getItem("orbit_workspace"));
  state.workspace = state.workspaces.find(w => w.id === savedId) || state.workspaces[0] || null;
  return state.workspace;
}
$("#workspace-button").onclick = () => $("#workspace-menu").classList.toggle("hidden");
document.addEventListener("click", e => { if (!e.target.closest(".workspace-picker")) $("#workspace-menu").classList.add("hidden"); });

async function loadWorkspace() {
  try {
    const workspace = activeWorkspace();
    if (!workspace) { renderNoWorkspace(); return; }
    [state.projects, state.dashboard, state.members, state.teams] = await Promise.all([
      api(`/workspaces/${workspace.id}/projects`), api(`/workspaces/${workspace.id}/dashboard`),
      api(`/workspaces/${workspace.id}/members`), api(`/workspaces/${workspace.id}/teams`)
    ]);
    if (state.project && !state.projects.some(p => p.id === state.project.id)) state.project = null;
    const savedProjectId=Number(localStorage.getItem(`orbit_project_${workspace.id}`));
    state.project ||= state.projects.find(project=>project.id===savedProjectId)||state.projects[0]||null;
    await loadProject(); render();
  } catch (err) { toast(err.message, true); }
}
async function loadProject() {
  if (!state.project) { state.tasks=[]; state.sprints=[]; state.board=null; return; }
  state.board = await api(`/projects/${state.project.id}/board`);
  [state.tasks, state.sprints] = await Promise.all([
    api(`/projects/${state.project.id}/tasks`),
    state.board.framework === "scrum" ? api(`/projects/${state.project.id}/sprints`) : Promise.resolve([])
  ]);
  if (state.view === "sprints" && state.board.framework !== "scrum") {
    state.view = "board";
    history.replaceState({view:"board"}, "", VIEW_PATHS.board);
  }
}
async function refresh() { if (state.workspace) await loadWorkspace(); }
$("#refresh-button").onclick = refresh;
$("#quick-task").onclick = () => state.project ? taskModal() : toast("Create a project first", true);
$("#mobile-menu").onclick = () => $(".sidebar").classList.toggle("open");
$("#main-nav").onclick = async e => {
  const btn = e.target.closest("[data-view]"); if (!btn) return;
  navigate(btn.dataset.view);
};
function navigate(view, replace = false) {
  state.view = view;
  const path = VIEW_PATHS[view] || VIEW_PATHS.dashboard;
  if (window.location.pathname !== path) {
    history[replace ? "replaceState" : "pushState"]({view}, "", path);
  }
  $$("#main-nav button").forEach(button => button.classList.toggle("active", button.dataset.view === view));
  $(".sidebar").classList.remove("open");
  render();
}
window.addEventListener("popstate", () => {
  state.view = PATH_VIEWS[window.location.pathname] || "dashboard";
  $$("#main-nav button").forEach(button => button.classList.toggle("active", button.dataset.view === state.view));
  render();
});
function render() {
  const names = {dashboard:"Overview",projects:"Projects",board:"Task board",gantt:"Gantt chart",sprints:"Sprints",people:"People & teams"};
  $("#page-title").textContent = names[state.view];
  $('[data-view="sprints"]').classList.toggle("hidden", Boolean(state.project) && state.board?.framework !== "scrum");
  $("#sprint-project-label").textContent = state.board?.framework==="scrum"&&state.project?state.project.name:"";
  $("#quick-task").classList.toggle("hidden", state.view !== "board" || !state.project);
  $("#content").innerHTML = ({dashboard:dashboardView,projects:projectsView,board:boardView,gantt:ganttView,sprints:sprintsView,people:peopleView}[state.view])();
  $$("#main-nav button").forEach(button => button.classList.toggle("active", button.dataset.view === state.view));
  bindView();
}
function pageHeading(title, text, action = "") {
  return `<div class="page-heading"><div><h1>${title}</h1><p>${text}</p></div>${action}</div>`;
}
function renderNoWorkspace() {
  $("#content").innerHTML = `${pageHeading("Welcome to Orbit", "Create your first workspace to get started.")}
    <div class="empty"><strong>Your work starts here</strong><p>A workspace keeps your projects, tasks, and team together.</p><button id="empty-workspace" class="btn primary">＋ Create workspace</button></div>`;
  $("#empty-workspace").onclick = workspaceModal;
}
function dashboardView() {
  const d = state.dashboard || {projects:0,active_projects:0,tasks:0,completed_tasks:0,overdue_tasks:0,completion_percent:0};
  return `${pageHeading(`Good ${new Date().getHours()<12?"morning":new Date().getHours()<18?"afternoon":"evening"}, ${esc(state.user.name.split(" ")[0])}`, `Here’s what’s happening in ${esc(state.workspace.name)}.`)}
  <div class="stats">
    ${stat("▱","Total projects",d.projects,`${d.active_projects} active`)}
    ${stat("✓","Completed tasks",d.completed_tasks,`${d.tasks} tasks in total`)}
    ${stat("◴","Completion",`${d.completion_percent}%`,"Across all projects")}
    ${stat("!","Overdue tasks",d.overdue_tasks,d.overdue_tasks?"Needs your attention":"Everything on track")}
  </div>
  <div class="dashboard-grid">
    <section class="panel"><div class="panel-header"><h3>Recent projects</h3><button data-go="projects">View all</button></div>
      ${state.projects.length?`<div class="project-list">${state.projects.slice(0,5).map(projectRow).join("")}</div>`:emptyMini("No projects yet","Create a project to start planning work.")}
    </section>
    <section class="panel"><div class="panel-header"><h3>Overall progress</h3></div>
      <div class="progress-ring" style="--percent:${d.completion_percent}%"><strong>${d.completion_percent}%</strong></div>
      <p style="text-align:center;color:var(--muted)">${d.completed_tasks} of ${d.tasks} tasks completed</p>
    </section>
  </div>`;
}
function stat(icon,label,value,small){return `<article class="stat-card"><div class="stat-top"><span>${label}</span><b class="stat-icon">${icon}</b></div><div class="stat-value">${value}</div><small>${small}</small></article>`}
function projectRow(p){return `<div class="project-row" data-project="${p.id}"><span class="project-icon">${esc(p.name[0].toUpperCase())}</span><div><strong>${esc(p.name)}</strong><small>${esc(p.description||"No description")}</small></div><span class="badge ${p.status}">${pretty(p.status)}</span></div>`}
function emptyMini(title,text){return `<div class="empty"><strong>${title}</strong><span>${text}</span></div>`}
function projectsView() {
  return `${pageHeading("Projects","Plan, track, and deliver your team’s work.",`<button id="new-project" class="btn primary">＋ New project</button>`)}
    <div class="toolbar"><input id="project-search" placeholder="⌕  Search projects"><select id="project-filter"><option value="">All statuses</option><option>planned</option><option>active</option><option>on_hold</option><option>completed</option></select></div>
    <div id="project-grid" class="project-grid">${projectCards(state.projects)}</div>`;
}
function projectCards(items){return items.length?items.map(p=>`<article class="project-card" data-project="${p.id}"><div class="project-head"><span class="project-icon">${esc(p.name[0].toUpperCase())}</span><div class="project-card-actions"><span class="badge ${p.status}">${pretty(p.status)}</span><button data-edit-project="${p.id}" title="Edit project">•••</button></div></div><h3>${esc(p.name)}</h3><p>${esc(p.description||"No description yet.")}</p><div class="project-meta"><span>${pretty(p.priority)} priority</span><span>${p.deadline?`Due ${date(p.deadline)}`:"No deadline"}</span></div></article>`).join(""):emptyMini("No projects yet","Create your first project to begin.") }
function projectSelector() {
  return `<select id="project-select">${state.projects.map(p=>`<option value="${p.id}" ${p.id===state.project?.id?"selected":""}>${esc(p.name)}</option>`).join("")}</select>`;
}
function boardView() {
  if (!state.project) return `${pageHeading("Task board","Visualize work as it moves through your workflow.",`<button id="new-project" class="btn primary">＋ New project</button>`)}${emptyMini("Create a project first","Tasks live inside projects.")}`;
  const columns = state.board?.columns || [];
  return `${pageHeading("Task board",`Drag tasks and lists to organize ${esc(state.project.name)}.`,`<div class="board-actions"><button id="ai-plan-tasks" class="btn ai-btn">AI plan</button><button id="customize-board" class="btn">⚙ Customize</button><button id="new-task-view" class="btn primary">＋ Add task</button></div>`)}
    <div class="toolbar">${projectSelector()}${state.board?.framework==="scrum"?`<select id="sprint-filter"><option value="">All Scrum work</option><option value="backlog">Product backlog</option>${state.sprints.map(s=>`<option value="${s.id}">${s.is_active?"● ":""}${esc(s.name)}</option>`).join("")}</select>`:""}<span class="framework-pill">${pretty(state.board?.framework||"kanban")} board</span></div>
    <div class="board-wrap"><div class="kanban custom-board" style="grid-template-columns:repeat(${columns.length + 1}, minmax(275px, 1fr))">${columns.map(column=>kanbanColumn(column,tasksForColumn(column.id))).join("")}<button id="add-column" class="add-column">＋ Add another list</button></div></div>`;
}
function tasksForColumn(columnId) {
  return state.tasks
    .filter(task => Number(state.board?.task_positions?.[task.id]?.column_id) === columnId)
    .sort((a,b) => (state.board.task_positions[a.id]?.position ?? 0) - (state.board.task_positions[b.id]?.position ?? 0));
}
function kanbanColumn(column,tasks){return `<section class="kanban-col" draggable="true" data-column="${column.id}"><div class="kanban-head"><i style="background:${column.color}"></i><strong>${esc(column.name)}</strong><span>${tasks.length}</span><button class="column-menu" data-column-menu="${column.id}" title="List options">•••</button></div><div class="task-dropzone" data-drop-column="${column.id}">${tasks.map(taskCard).join("")}</div><button class="column-add" data-add-to="${column.id}">＋ Add a card</button></section>`}
function taskCard(t){
  const assignees=(t.assignee_ids||[]).map(id=>state.members.find(m=>m.user_id===id)?.user).filter(Boolean);
  const checklist=t.checklist_total?`<span class="check-count ${t.checklist_done===t.checklist_total?"complete":""}">☑ ${t.checklist_done}/${t.checklist_total}</span>`:"";
  return `<article class="task-card" draggable="true" data-task="${t.id}"><span class="priority-dot ${t.priority}">${t.priority}</span><h4>${esc(t.title)}</h4><p>${esc(t.description||"No description")}</p>
    ${t.progress?`<div class="card-progress"><i style="width:${t.progress}%"></i></div>`:""}
    <div class="task-foot"><span>${t.end_at?`◷ ${dateTime(t.end_at)}`:t.due_date?`◷ ${date(t.due_date)}`:`#${t.id}`}</span>${checklist}<div class="avatar-stack">${assignees.slice(0,3).map(u=>`<b class="avatar" title="${esc(u.name)}">${esc(u.name.slice(0,2).toUpperCase())}</b>`).join("")}${assignees.length>3?`<b class="avatar">+${assignees.length-3}</b>`:!assignees.length?'<b class="avatar">—</b>':""}</div></div></article>`;
}
function ganttView() {
  if (!state.project) return `${pageHeading("Gantt chart","Plan tasks across a visual timeline.")}${emptyMini("Create a project first","Scheduled tasks will appear here.")}`;
  const scheduled=state.tasks.map(task=>{
    const startValue=task.start_at||task.start_date;
    const endValue=task.end_at||task.due_date;
    return startValue&&endValue?{task,start:new Date(startValue),end:new Date(endValue)}:null;
  }).filter(Boolean);
  const today=new Date();today.setHours(0,0,0,0);
  let rangeStart=new Date(today);rangeStart.setDate(rangeStart.getDate()-3);
  let rangeEnd=new Date(today);rangeEnd.setDate(rangeEnd.getDate()+27);
  if(scheduled.length){
    const earliest=new Date(Math.min(...scheduled.map(item=>item.start.getTime())));
    const latest=new Date(Math.max(...scheduled.map(item=>item.end.getTime())));
    if(earliest<rangeStart){rangeStart=new Date(earliest);rangeStart.setDate(rangeStart.getDate()-2)}
    if(latest>rangeEnd){rangeEnd=new Date(latest);rangeEnd.setDate(rangeEnd.getDate()+3)}
  }
  const totalDays=Math.max(1,Math.min(120,Math.ceil((rangeEnd-rangeStart)/86400000)+1));
  rangeEnd=new Date(rangeStart);rangeEnd.setDate(rangeEnd.getDate()+totalDays-1);
  const days=Array.from({length:totalDays},(_,index)=>{const d=new Date(rangeStart);d.setDate(d.getDate()+index);return d});
  const rows=scheduled.map(({task,start,end})=>{
    const offset=Math.max(0,Math.floor((start-rangeStart)/86400000));
    const duration=Math.max(1,Math.ceil((end-start)/86400000)+1);
    return `<div class="gantt-row" data-task="${task.id}"><div class="gantt-task-name"><strong>${esc(task.title)}</strong><small>${pretty(task.status)} · ${task.progress}%</small></div><div class="gantt-track" style="--days:${totalDays}"><div class="gantt-bar ${task.status}" style="--start:${offset};--duration:${Math.min(duration,totalDays-offset)}"><span>${esc(task.title)}</span><b>${task.progress}%</b></div></div></div>`;
  }).join("");
  const unscheduled=state.tasks.filter(task=>!(task.start_at||task.start_date)||!(task.end_at||task.due_date));
  return `${pageHeading("Gantt chart",`Timeline planning for ${esc(state.project.name)}.`,`<button id="gantt-new-task" class="btn primary">＋ Schedule task</button>`)}
    <div class="toolbar">${projectSelector()}<span class="gantt-range">${date(rangeStart)} — ${date(rangeEnd)}</span></div>
    <section class="gantt-panel"><div class="gantt-header"><div>Task</div><div class="gantt-days" style="--days:${totalDays}">${days.map(day=>`<span class="${day.getTime()===today.getTime()?"today":""}"><b>${day.toLocaleDateString(undefined,{weekday:"short"})}</b>${day.getDate()}</span>`).join("")}</div></div>
    <div class="gantt-body">${rows||`<div class="empty gantt-empty"><strong>No scheduled tasks</strong><span>Add a start and end date-time to a task.</span></div>`}</div></section>
    ${unscheduled.length?`<section class="panel unscheduled"><div class="panel-header"><h3>Unscheduled tasks</h3><span class="badge">${unscheduled.length}</span></div>${unscheduled.map(task=>`<button data-task="${task.id}"><strong>${esc(task.title)}</strong><span>＋ Add dates</span></button>`).join("")}</section>`:""}`;
}
function sprintsView() {
  if (!state.project) return `${pageHeading("Sprints","Set a focused goal and timebox the work.")}${emptyMini("No project selected","Create a Scrum project before adding sprints.")}`;
  if (state.board?.framework!=="scrum") return `${pageHeading("Sprints","Sprints are available only for Scrum projects.")}${emptyMini("This is a Kanban project","Kanban uses continuous flow instead of fixed sprints.")}`;
  return `${pageHeading("Sprints",`Plan focused delivery cycles for ${esc(state.project.name)}.`,`<button id="new-sprint" class="btn primary">＋ New sprint</button>`)}
    <div class="project-context"><span class="project-icon">${esc(state.project.name[0].toUpperCase())}</span><div><small>CURRENT SCRUM PROJECT</small><strong>${esc(state.project.name)}</strong></div><span class="framework-pill">Scrum</span></div>
    <div class="toolbar">${projectSelector()}</div>
    ${state.sprints.length?state.sprints.map(s=>`<article class="sprint-row"><div><h3>${esc(s.name)} ${s.is_active?'<span class="badge active">Active sprint</span>':""}</h3><p>${esc(s.goal||"No sprint goal")}</p></div><div class="sprint-dates">${date(s.start_date)} → ${date(s.end_date)}<button data-edit-sprint="${s.id}" class="icon-btn" title="Edit sprint">•••</button></div></article>`).join(""):emptyMini("No sprints yet","Create a sprint to group focused work.")}`;
}
function peopleView() {
  return `${pageHeading("People & teams","Bring everyone together around shared work.",`<button id="add-member" class="btn primary">＋ Add member</button>`)}
  <div class="people-grid"><section class="panel"><div class="panel-header"><h3>Workspace members</h3><span class="badge">${state.members.length}</span></div>
    ${state.members.map(m=>`<div class="member-row"><b class="avatar">${esc(m.user.name.slice(0,2).toUpperCase())}</b><div><strong>${esc(m.user.name)}</strong><small>${esc(m.user.email)}</small></div><span class="badge ${m.role}">${m.role}</span></div>`).join("")}
  </section><section class="panel"><div class="panel-header"><h3>Teams</h3><button id="new-team">＋ New team</button></div>
    ${state.teams.length?state.teams.map(t=>`<div class="team-card"><h4>${esc(t.name)}</h4><p>${esc(t.description||"No description")}</p></div>`).join(""):emptyMini("No teams yet","Create a team for a focused group.")}
  </section></div>`;
}
function bindView() {
  $$("[data-go]").forEach(x=>x.onclick=()=>navigate(x.dataset.go));
  $$("[data-project]").forEach(x=>x.onclick=async()=>{state.project=state.projects.find(p=>p.id===Number(x.dataset.project));localStorage.setItem(`orbit_project_${state.workspace.id}`,state.project.id);await loadProject();if(x.closest(".project-card"))navigate("board");else render()});
  $$("[data-edit-project]").forEach(button=>button.onclick=event=>{event.stopPropagation();projectEditModal(state.projects.find(project=>project.id===Number(button.dataset.editProject)))});
  $("#new-project")?.addEventListener("click", projectModal); $("#new-task-view")?.addEventListener("click",()=>taskModal());
  $("#gantt-new-task")?.addEventListener("click",()=>taskModal());
  $("#new-sprint")?.addEventListener("click", sprintModal); $("#add-member")?.addEventListener("click", memberModal); $("#new-team")?.addEventListener("click", teamModal);
  $$("[data-edit-sprint]").forEach(button=>button.onclick=()=>sprintModal(state.sprints.find(sprint=>sprint.id===Number(button.dataset.editSprint))));
  $("#project-select")?.addEventListener("change", async e=>{state.project=state.projects.find(p=>p.id===Number(e.target.value));localStorage.setItem(`orbit_project_${state.workspace.id}`,state.project.id);await loadProject();render()});
  $("#sprint-filter")?.addEventListener("change", e=>{const value=e.target.value;$$(".task-card").forEach(card=>{const task=state.tasks.find(t=>t.id===Number(card.dataset.task));card.classList.toggle("hidden",value==="backlog"?task.sprint_id!==null:Boolean(value)&&task.sprint_id!==Number(value))})});
  $$("[data-task]").forEach(x=>x.onclick=()=>taskDetail(Number(x.dataset.task)));
  $$("[data-add-to]").forEach(x=>x.onclick=()=>taskModal(null,Number(x.dataset.addTo)));
  $$("[data-column-menu]").forEach(x=>x.onclick=e=>{e.stopPropagation();columnModal(Number(x.dataset.columnMenu))});
  $("#add-column")?.addEventListener("click",()=>columnModal());
  $("#customize-board")?.addEventListener("click",boardSettingsModal);
  $("#ai-plan-tasks")?.addEventListener("click",aiTaskPlannerModal);
  bindBoardDragDrop();
  $("#project-search")?.addEventListener("input", filterProjects); $("#project-filter")?.addEventListener("change", filterProjects);
}
function filterProjects(){const q=$("#project-search").value.toLowerCase(),s=$("#project-filter").value;$("#project-grid").innerHTML=projectCards(state.projects.filter(p=>(p.name.toLowerCase().includes(q)||p.description?.toLowerCase().includes(q))&&(!s||p.status===s)));bindView()}

let draggedTaskId = null;
let draggedColumnId = null;
let ignoreTaskClick = false;
function bindBoardDragDrop() {
  $$(".task-card[draggable]").forEach(card => {
    card.addEventListener("dragstart", event => {
      draggedTaskId = Number(card.dataset.task);
      draggedColumnId = null;
      ignoreTaskClick = true;
      card.classList.add("dragging");
      document.body.classList.add("task-is-dragging");
      event.dataTransfer.effectAllowed = "move";
      event.dataTransfer.setData("text/plain", `task:${draggedTaskId}`);
      event.stopPropagation();
    });
    card.addEventListener("dragend", () => {
      card.classList.remove("dragging");
      document.body.classList.remove("task-is-dragging");
      $$(".drag-over").forEach(el => el.classList.remove("drag-over"));
      setTimeout(() => { draggedTaskId = null; ignoreTaskClick = false; }, 50);
    });
    const originalClick = card.onclick;
    card.onclick = event => { if (!ignoreTaskClick) originalClick?.(event); };
  });
  $$(".task-dropzone").forEach(zone => {
    zone.addEventListener("dragover", event => {
      if (!draggedTaskId) return;
      event.preventDefault();
      zone.classList.add("drag-over");
      const after = [...zone.querySelectorAll(".task-card:not(.dragging)")].find(
        card => event.clientY < card.getBoundingClientRect().top + card.offsetHeight / 2
      );
      const dragging = $(`.task-card[data-task="${draggedTaskId}"]`);
      if (dragging) after ? zone.insertBefore(dragging, after) : zone.appendChild(dragging);
    });
    zone.addEventListener("dragleave", event => {
      if (!zone.contains(event.relatedTarget)) zone.classList.remove("drag-over");
    });
    zone.addEventListener("drop", async event => {
      if (!draggedTaskId) return;
      event.preventDefault();
      const columnId = Number(zone.dataset.dropColumn);
      const position = [...zone.querySelectorAll(".task-card")].findIndex(
        card => Number(card.dataset.task) === draggedTaskId
      );
      try {
        state.board = await api(`/tasks/${draggedTaskId}/board-position`, {
          method:"PUT", body:JSON.stringify({column_id:columnId, position:Math.max(0,position)})
        });
        state.tasks = await api(`/projects/${state.project.id}/tasks`);
        render(); toast("Task moved");
      } catch (err) { toast(err.message,true); await loadProject(); render(); }
    });
  });
  $$(".kanban-col[draggable]").forEach(column => {
    const taskZone = $(".task-dropzone", column);
    column.addEventListener("dragover", event => {
      if (!draggedTaskId || event.target.closest(".task-dropzone")) return;
      event.preventDefault();
      taskZone.classList.add("drag-over");
    });
    column.addEventListener("drop", event => {
      if (!draggedTaskId || event.target.closest(".task-dropzone")) return;
      event.preventDefault();
      const dragging = $(`.task-card[data-task="${draggedTaskId}"]`);
      if (dragging) taskZone.appendChild(dragging);
      taskZone.dispatchEvent(new Event("drop", {cancelable:true}));
    });
    column.addEventListener("dragstart", event => {
      if (event.target !== column) return;
      draggedColumnId = Number(column.dataset.column);
      draggedTaskId = null;
      column.classList.add("column-dragging");
      event.dataTransfer.effectAllowed = "move";
      event.dataTransfer.setData("text/plain", `column:${draggedColumnId}`);
    });
    column.addEventListener("dragend", () => {
      column.classList.remove("column-dragging");
      draggedColumnId = null;
    });
  });
  const board = $(".custom-board");
  board?.addEventListener("dragover", event => {
    if (!draggedColumnId) return;
    event.preventDefault();
    const dragging = $(`.kanban-col[data-column="${draggedColumnId}"]`);
    const others = [...board.querySelectorAll(".kanban-col:not(.column-dragging)")];
    const after = others.find(column => event.clientX < column.getBoundingClientRect().left + column.offsetWidth / 2);
    if (dragging) after ? board.insertBefore(dragging,after) : board.insertBefore(dragging,$("#add-column"));
  });
  board?.addEventListener("drop", async event => {
    if (!draggedColumnId) return;
    event.preventDefault();
    const columnIds = [...board.querySelectorAll(".kanban-col")].map(column => Number(column.dataset.column));
    try {
      state.board = await api(`/projects/${state.project.id}/board/column-order`, {
        method:"PUT", body:JSON.stringify({column_ids:columnIds})
      });
      render(); toast("Lists reordered");
    } catch (err) { toast(err.message,true); await loadProject(); render(); }
  });
}

function workspaceModal() { $("#workspace-menu").classList.add("hidden"); modal(formShell("Create workspace","A shared home for your projects and team.",`
  ${field("name","Workspace name","text","e.g. Product team",true)}${field("description","Description","textarea","What will your team work on?")}`,"Create workspace"),()=>$("#modal-form").onsubmit=async e=>submitForm(e,async data=>{
    const w=await api("/workspaces",{method:"POST",body:JSON.stringify(data)});state.workspaces.unshift(w);state.workspace=w;localStorage.setItem("orbit_workspace",w.id);updateWorkspaceUI();await loadWorkspace();toast("Workspace created");
  }));}
function workspaceSettingsModal(){
  $("#workspace-menu").classList.add("hidden");
  const workspace=activeWorkspace();
  if(!workspace)return;
  modal(`<h2>Workspace settings</h2><p class="subtitle">Manage ${esc(workspace.name)}.</p>
    <form id="workspace-edit-form"><div class="form-grid">${field("name","Workspace name","text","Workspace name",true,false,workspace.name)}${field("description","Description","textarea","What does this workspace contain?","",true,workspace.description)}</div>
    <div class="modal-actions"><button class="btn primary">Save workspace</button></div></form>
    <h3 class="settings-section-title">Danger zone</h3>
    <div class="danger-zone"><h3>Delete workspace</h3><p>This permanently deletes its projects, sprints, tasks, comments, teams, and board settings.</p>
    <label class="field">Type <strong>${esc(workspace.name)}</strong> to confirm<input id="workspace-confirm" autocomplete="off" placeholder="${esc(workspace.name)}"></label>
    <button id="delete-workspace" class="btn danger">Delete workspace permanently</button></div>
    <div id="modal-error" class="form-error hidden"></div>`,()=>{
      $("#workspace-edit-form").onsubmit=async event=>{
        event.preventDefault();const error=$("#modal-error");
        try{
          const updated=await api(`/workspaces/${workspace.id}`,{method:"PATCH",body:JSON.stringify(formData(event.currentTarget))});
          state.workspaces=state.workspaces.map(item=>item.id===updated.id?updated:item);state.workspace=updated;updateWorkspaceUI();closeModal();render();toast("Workspace updated");
        }catch(err){error.textContent=err.message;error.classList.remove("hidden")}
      };
      $("#delete-workspace").onclick=async()=>{
        const error=$("#modal-error");
        if($("#workspace-confirm").value!==workspace.name){error.textContent="Enter the exact workspace name to confirm.";error.classList.remove("hidden");return}
        if(!confirm(`Permanently delete "${workspace.name}" and all of its data?`))return;
        try{
          await api(`/workspaces/${workspace.id}`,{method:"DELETE"});
          state.workspaces=state.workspaces.filter(item=>item.id!==workspace.id);
          state.workspace=state.workspaces[0]||null;state.project=null;state.projects=[];state.tasks=[];state.sprints=[];state.board=null;
          if(state.workspace)localStorage.setItem("orbit_workspace",state.workspace.id);else localStorage.removeItem("orbit_workspace");
          closeModal();updateWorkspaceUI();
          if(state.workspace)await loadWorkspace();else renderNoWorkspace();
          toast("Workspace deleted");
        }catch(err){error.textContent=err.message;error.classList.remove("hidden")}
      };
    });
}
function projectModal(){
  const workspace = activeWorkspace();
  if (!workspace) { toast("Create or select a workspace first", true); workspaceModal(); return; }
  const workspaceId = workspace.id;
  modal(formShell("Create a project","Turn an idea into an organized plan.",`
  ${field("name","Project name","text","e.g. Mobile app launch",true)}${field("description","Description","textarea","What is this project about?","",true)}
  ${selectField("framework","Work framework",[["kanban","Kanban — continuous flow"],["scrum","Scrum — sprint planning"]],"kanban")}
  ${selectField("status","Status",["planned","active","on_hold","completed"])}${selectField("priority","Priority",["low","medium","high","critical"],"medium")}
  ${field("deadline","Deadline","date")}${field("budget","Budget","number","Optional")}`,"Create project"),()=>$("#modal-form").onsubmit=async e=>submitForm(e,async data=>{
    const framework=data.framework;delete data.framework;if(data.budget)data.budget=Number(data.budget);const p=await api(`/workspaces/${workspaceId}/projects`,{method:"POST",body:JSON.stringify(data)});await api(`/projects/${p.id}/board`,{method:"PUT",body:JSON.stringify({framework})});state.projects.unshift(p);state.project=p;localStorage.setItem(`orbit_project_${workspaceId}`,p.id);await loadWorkspace();toast(`${pretty(framework)} project created`);
  }));}
function projectEditModal(project){
  if(!project)return;
  modal(formShell("Edit project","Update the project details and delivery settings.",`
    ${field("name","Project name","text","Project name",true,false,project.name)}
    ${field("description","Description","textarea","What is this project about?","",true,project.description)}
    ${selectField("status","Status",["planned","active","on_hold","completed"],project.status)}
    ${selectField("priority","Priority",["low","medium","high","critical"],project.priority)}
    ${field("deadline","Deadline","date","","",false,project.deadline)}
    ${field("budget","Budget","number","Optional","",false,project.budget)}`,
    "Save changes",`<button type="button" id="delete-project" class="btn danger">Delete project</button>`),()=>{
      $("#modal-form").onsubmit=async event=>submitForm(event,async data=>{
        if(data.budget!==null)data.budget=Number(data.budget);
        const updated=await api(`/projects/${project.id}`,{method:"PATCH",body:JSON.stringify(data)});
        state.projects=state.projects.map(item=>item.id===updated.id?updated:item);
        if(state.project?.id===updated.id)state.project=updated;
        await loadWorkspace();toast("Project updated");
      });
      $("#delete-project").onclick=async()=>{
        if(!confirm(`Permanently delete "${project.name}" and all of its tasks, sprints, and board data?`))return;
        const error=$("#modal-error");
        try{
          await api(`/projects/${project.id}`,{method:"DELETE"});
          const deletedCurrent=state.project?.id===project.id;
          state.projects=state.projects.filter(item=>item.id!==project.id);
          if(deletedCurrent)state.project=null;
          closeModal();
          await loadWorkspace();
          if(state.project)localStorage.setItem(`orbit_project_${state.workspace.id}`,state.project.id);
          else localStorage.removeItem(`orbit_project_${state.workspace.id}`);
          toast("Project deleted");
        }catch(err){error.textContent=err.message;error.classList.remove("hidden")}
      };
    });
}
function sprintModal(sprint=null){modal(formShell(sprint?"Edit sprint":"Create a sprint",sprint?"Update this Scrum delivery cycle.":"Set a focused goal and delivery window.",`
  ${field("name","Sprint name","text","e.g. Sprint 01",true,false,sprint?.name)}${field("goal","Sprint goal","textarea","What should this sprint achieve?","",true,sprint?.goal)}
  ${field("start_date","Start date","date","","",false,sprint?.start_date)}${field("end_date","End date","date","","",false,sprint?.end_date)}
  <label class="field full" style="flex-direction:row"><input name="is_active" type="checkbox" value="true" ${sprint?.is_active?"checked":""}> Make this the active sprint</label>`,sprint?"Save sprint":"Create sprint"),()=>$("#modal-form").onsubmit=async e=>submitForm(e,async data=>{
    data.is_active=data.is_active==="true";await api(sprint?`/sprints/${sprint.id}`:`/projects/${state.project.id}/sprints`,{method:sprint?"PATCH":"POST",body:JSON.stringify(data)});await loadProject();render();toast(sprint?"Sprint updated":"Sprint created");
  }));}
function taskModal(task=null,targetColumnId=null){modal(formShell(task?"Edit task":"Create a task",task?"Update task details and progress.":`Add work to ${esc(state.project.name)}.`,`
  ${field("title","Task title","text","What needs to be done?",true,false,task?.title)}${field("description","Description","textarea","Add context and acceptance criteria","",true,task?.description)}
  ${selectField("status","Status",STATUS.map(x=>x[0]),task?.status||"backlog")}${selectField("priority","Priority",["low","medium","high","critical"],task?.priority||"medium")}
  ${state.board?.framework==="scrum"?`<div class="field full"><label>Sprint · ${esc(state.project.name)}</label><div class="inline-control"><select name="sprint_id"><option value="">Product backlog</option>${state.sprints.map(s=>`<option value="${s.id}" ${s.id===task?.sprint_id?"selected":""}>${s.is_active?"● Active · ":""}${esc(s.name)}</option>`).join("")}</select><button type="button" id="show-quick-sprint" class="btn">＋ New sprint</button></div><div id="quick-sprint-row" class="quick-sprint-row hidden"><input id="quick-sprint-name" placeholder="Sprint name, e.g. Sprint 01"><button type="button" id="create-quick-sprint" class="btn primary">Create</button></div><small class="field-help">${state.sprints.length?`${state.sprints.length} sprint${state.sprints.length===1?"":"s"} in this project`:"No sprints yet — create one here or from the Sprints page."}</small></div>`:""}
  <fieldset class="field full assignee-field"><legend>Assignees</legend><div class="assignee-options">${state.members.map(m=>`<label><input type="checkbox" name="assignee_ids" value="${m.user_id}" ${(task?.assignee_ids||[]).includes(m.user_id)?"checked":""}><span class="avatar">${esc(m.user.name.slice(0,2).toUpperCase())}</span>${esc(m.user.name)}</label>`).join("")||"<span class='subtitle'>Add workspace members before assigning this task.</span>"}</div></fieldset>
  ${field("story_points","Story points","number","0–100","",false,task?.story_points)}${field("due_date","Due date","date","","",false,task?.due_date)}
  ${field("start_at","Start date & time","datetime-local","","",false,inputDateTime(task?.start_at))}${field("end_at","End date & time","datetime-local","","",false,inputDateTime(task?.end_at))}
  ${field("progress","Progress %","number","0–100","",false,task?.progress??0)}`,task?"Save changes":"Create task",task?`<button type="button" id="delete-task" class="btn danger">Delete</button>`:""),()=>{
    $("#modal-form").onsubmit=async e=>submitForm(e,async data=>{
      data.assignee_ids=$$('input[name="assignee_ids"]:checked',e.currentTarget).map(input=>Number(input.value));
      ["sprint_id","story_points","progress"].forEach(k=>{if(data[k]!==null)data[k]=Number(data[k])});
      const saved=await api(task?`/tasks/${task.id}`:`/projects/${state.project.id}/tasks`,{method:task?"PATCH":"POST",body:JSON.stringify(data)});
      if(!task&&targetColumnId) await api(`/tasks/${saved.id}/board-position`,{method:"PUT",body:JSON.stringify({column_id:targetColumnId,position:9999})});
      await loadWorkspace();toast(task?"Task updated":"Task created");
    });
    $("#show-quick-sprint")?.addEventListener("click",()=>{$("#quick-sprint-row").classList.toggle("hidden");$("#quick-sprint-name").focus()});
    $("#create-quick-sprint")?.addEventListener("click",async()=>{
      const input=$("#quick-sprint-name"),name=input.value.trim();
      if(name.length<2){toast("Enter a sprint name",true);return}
      try{
        const sprint=await api(`/projects/${state.project.id}/sprints`,{method:"POST",body:JSON.stringify({name})});
        state.sprints.unshift(sprint);
        const select=$('[name="sprint_id"]',$("#modal-form"));
        select.insertAdjacentHTML("beforeend",`<option value="${sprint.id}">${esc(sprint.name)}</option>`);select.value=String(sprint.id);
        $("#quick-sprint-row").classList.add("hidden");toast("Sprint created and selected");
      }catch(err){toast(err.message,true)}
    });
    $("#delete-task")?.addEventListener("click",()=>deleteTask(task));
  });}
async function taskDetail(id){
  const [task,comments,checklist]=await Promise.all([api(`/tasks/${id}`),api(`/tasks/${id}/comments`),api(`/tasks/${id}/checklist`)]);
  const index=state.tasks.findIndex(item=>item.id===id);if(index>=0)state.tasks[index]=task;
  const assignees=(task.assignee_ids||[]).map(userId=>state.members.find(m=>m.user_id===userId)?.user).filter(Boolean);
  modal(`<h2>${esc(task.title)}</h2><p class="subtitle">${esc(task.description||"No description")}</p>
    <div class="task-detail-meta"><div class="meta-box"><small>STATUS</small><strong>${pretty(task.status)}</strong></div><div class="meta-box"><small>PRIORITY</small><strong>${pretty(task.priority)}</strong></div><div class="meta-box"><small>PROGRESS</small><strong>${task.progress}%</strong></div><div class="meta-box"><small>START</small><strong>${dateTime(task.start_at)}</strong></div><div class="meta-box"><small>END</small><strong>${dateTime(task.end_at)}</strong></div><div class="meta-box"><small>ASSIGNEES</small><strong>${assignees.map(u=>esc(u.name)).join(", ")||"Unassigned"}</strong></div></div>
    <div style="display:flex;gap:8px"><button id="edit-task" class="btn">Edit task</button><button id="detail-delete-task" class="btn danger">Delete task</button></div>
    <section class="checklist"><div class="checklist-head"><h3>Checklist</h3><strong>${checklist.length?Math.round(checklist.filter(i=>i.is_done).length/checklist.length*100):0}%</strong></div><div class="checklist-progress"><i style="width:${checklist.length?Math.round(checklist.filter(i=>i.is_done).length/checklist.length*100):0}%"></i></div>
      <div id="checklist-items">${checklist.map(item=>`<div class="check-item"><input type="checkbox" data-check="${item.id}" ${item.is_done?"checked":""}><span class="${item.is_done?"done":""}">${esc(item.text)}</span><button data-delete-check="${item.id}">×</button></div>`).join("")||"<p class='subtitle'>Break this task into smaller steps.</p>"}</div>
      <form id="checklist-form" class="comment-form"><input name="text" placeholder="Add an item…" required><button class="btn">Add</button></form></section>
    <section class="comments"><h3>Comments</h3><div id="comment-list">${comments.length?comments.map(c=>`<div class="comment">${esc(c.body)}<small> · ${date(c.created_at)}</small></div>`).join(""):"<p class='subtitle'>No comments yet.</p>"}</div>
    <form id="comment-form" class="comment-form"><input name="body" placeholder="Write a comment…" required><button class="btn primary">Send</button></form></section>`,()=>{
      $("#edit-task").onclick=()=>taskModal(task);
      $("#detail-delete-task").onclick=()=>deleteTask(task);
      $$("[data-check]").forEach(input=>input.onchange=async()=>{await api(`/tasks/${id}/checklist/${input.dataset.check}`,{method:"PATCH",body:JSON.stringify({is_done:input.checked})});taskDetail(id)});
      $$("[data-delete-check]").forEach(button=>button.onclick=async()=>{await api(`/tasks/${id}/checklist/${button.dataset.deleteCheck}`,{method:"DELETE"});taskDetail(id)});
      $("#checklist-form").onsubmit=async e=>{e.preventDefault();const input=$("input",e.target);await api(`/tasks/${id}/checklist`,{method:"POST",body:JSON.stringify({text:input.value})});taskDetail(id)};
      $("#comment-form").onsubmit=async e=>{e.preventDefault();const input=$("input",e.target);await api(`/tasks/${id}/comments`,{method:"POST",body:JSON.stringify({body:input.value})});closeModal();taskDetail(id);toast("Comment added")};
    });
}
async function deleteTask(task){
  if(!confirm(`Delete "${task.title}" permanently?`))return;
  try{await api(`/tasks/${task.id}`,{method:"DELETE"});closeModal();await loadWorkspace();render();toast("Task deleted")}
  catch(err){toast(err.message,true)}
}
function memberModal(){modal(formShell("Add a member","They must already have an Orbit account.",`${field("email","Email address","email","teammate@company.com",true)}${selectField("role","Role",["member","admin"],"member")}`,"Add member"),()=>$("#modal-form").onsubmit=async e=>submitForm(e,async data=>{await api(`/workspaces/${state.workspace.id}/members`,{method:"POST",body:JSON.stringify(data)});await loadWorkspace();toast("Member added")}));}
function teamModal(){modal(formShell("Create a team","Group people around a shared purpose.",`${field("name","Team name","text","e.g. Design",true)}${field("description","Description","textarea","What does this team own?")}`,"Create team"),()=>$("#modal-form").onsubmit=async e=>submitForm(e,async data=>{await api(`/workspaces/${state.workspace.id}/teams`,{method:"POST",body:JSON.stringify(data)});await loadWorkspace();toast("Team created")}));}
function columnModal(columnId=null){
  const column=state.board?.columns.find(item=>item.id===columnId);
  modal(formShell(column?"Edit list":"Add another list",column?"Rename or recolor this workflow stage.":"Create a custom stage for your workflow.",`
    ${field("name","List name","text","e.g. Blocked",true,false,column?.name)}
    <label class="field">Color<input name="color" type="color" value="${column?.color||"#8b97ac"}"></label>
    ${selectField("system_status","Task status",STATUS,column?.system_status,"Custom stage — keep current status")}`,
    column?"Save list":"Add list",column?`<button type="button" id="delete-column" class="btn danger">Delete list</button>`:""),()=>{
      $("#modal-form").onsubmit=async e=>submitForm(e,async data=>{
        await api(column?`/projects/${state.project.id}/board/columns/${column.id}`:`/projects/${state.project.id}/board/columns`,{method:column?"PATCH":"POST",body:JSON.stringify(data)});
        await loadProject();render();toast(column?"List updated":"List added");
      });
      $("#delete-column")?.addEventListener("click",async()=>{
        if(!confirm(`Delete "${column.name}"? Its cards will move to another list.`))return;
        try{await api(`/projects/${state.project.id}/board/columns/${column.id}`,{method:"DELETE"});closeModal();await loadProject();render();toast("List deleted")}catch(err){$("#modal-error").textContent=err.message;$("#modal-error").classList.remove("hidden")}
      });
    });
}
function boardSettingsModal(){
  modal(formShell("Board settings","Choose the planning style for this project.",`
    ${selectField("framework","Work framework",[["kanban","Kanban — continuous flow"],["scrum","Scrum — sprint planning"]],state.board?.framework||"kanban")}
    <div class="field full board-note"><strong>Kanban</strong><span>Continuous delivery with flexible workflow stages.</span><strong>Scrum</strong><span>Sprint-based planning with product and sprint backlogs.</span></div>
    <div class="field full reset-note"><strong>Missing lists?</strong><span>Restore recreates Backlog, To do, In progress, Review, Testing, and Done. Your tasks are preserved.</span></div>`,
    "Apply framework",`<button type="button" id="reset-board" class="btn">↺ Restore default lists</button>`),()=>{
      $("#modal-form").onsubmit=async e=>submitForm(e,async data=>{
      state.board=await api(`/projects/${state.project.id}/board`,{method:"PUT",body:JSON.stringify(data)});render();toast(`${pretty(data.framework)} board applied`);
      });
      $("#reset-board").onclick=async()=>{
        if(!confirm("Restore the default lists? Custom lists will be removed, but tasks will be preserved."))return;
        const framework=$('[name="framework"]',$("#modal-form")).value;
        try{state.board=await api(`/projects/${state.project.id}/board`,{method:"PUT",body:JSON.stringify({framework,reset:true})});closeModal();state.tasks=await api(`/projects/${state.project.id}/tasks`);render();toast("Default lists restored")}catch(err){$("#modal-error").textContent=err.message;$("#modal-error").classList.remove("hidden")}
      };
    });
}
function aiTaskPlannerModal(){
  if(!state.project){toast("Select a project first",true);return}
  modal(formShell("Plan tasks with AI",`Describe the outcome you want for ${esc(state.project.name)}. You will review every task before it is created.`,`
    ${field("prompt","What should this project deliver?","textarea","Example: Build a secure mobile application with authentication, payments, testing, and deployment.",true,true)}
    ${field("maximum_tasks","Maximum tasks","number","10",true,false,10)}
    <div class="field full ai-note"><strong>Safe preview</strong><span>AI generates a draft only. No board data changes until you confirm the selected tasks.</span></div>`,
    "Generate task plan"),()=>{
      const form=$("#modal-form");
      const maximum=$('[name="maximum_tasks"]',form);
      maximum.min="1";maximum.max="15";
      form.onsubmit=async event=>{
        event.preventDefault();
        const button=$('button[type="submit"]',form),error=$("#modal-error");
        button.disabled=true;button.textContent="Generating...";
        try{
          const values=formData(form);
          const plan=await api(`/projects/${state.project.id}/ai/task-plan`,{
            method:"POST",
            body:JSON.stringify({prompt:values.prompt,maximum_tasks:Number(values.maximum_tasks)})
          });
          aiTaskPreviewModal(plan);
        }catch(err){
          error.textContent=err.message;error.classList.remove("hidden");
          button.disabled=false;button.textContent="Generate task plan";
        }
      };
    });
}
function aiTaskPreviewModal(plan){
  const providerNote=plan.fallback_used
    ? `Primary provider unavailable; generated with ${pretty(plan.provider)} (${plan.model}).`
    : `Generated with ${pretty(plan.provider)} (${plan.model}).`;
  modal(`<h2>Review AI task plan</h2><p class="subtitle">${esc(plan.summary)}</p>
    <div class="ai-provider ${plan.fallback_used?"fallback":""}">${esc(providerNote)}</div>
    <form id="ai-confirm-form"><div class="ai-task-list">${plan.tasks.map((task,index)=>`
      <article class="ai-task-item" data-ai-task="${index}">
        <input class="ai-task-enabled" type="checkbox" checked aria-label="Include task">
        <div>
          <input class="ai-task-title" value="${esc(task.title)}" maxlength="220" required>
          <textarea class="ai-task-description" maxlength="3000" placeholder="Task details">${esc(task.description||"")}</textarea>
          <div class="ai-task-meta">
            <select class="ai-task-priority">${["low","medium","high","critical"].map(value=>`<option value="${value}" ${value===task.priority?"selected":""}>${pretty(value)}</option>`).join("")}</select>
            <input class="ai-task-points" type="number" min="0" max="100" placeholder="Story points" value="${task.story_points??""}">
          </div>
        </div>
      </article>`).join("")}</div>
      <div id="modal-error" class="form-error hidden"></div>
      <div class="modal-actions"><button type="button" id="back-to-ai-prompt" class="btn">Back</button><button type="button" class="btn" onclick="document.querySelector('#modal-close').click()">Cancel</button><button class="btn primary">Create selected tasks</button></div>
    </form>`,()=>{
      $("#back-to-ai-prompt").onclick=aiTaskPlannerModal;
      $("#ai-confirm-form").onsubmit=async event=>{
        event.preventDefault();
        const button=$('button[type="submit"]',event.currentTarget),error=$("#modal-error");
        const tasks=$$("[data-ai-task]",event.currentTarget)
          .filter(row=>$(".ai-task-enabled",row).checked)
          .map(row=>({
            title:$(".ai-task-title",row).value.trim(),
            description:$(".ai-task-description",row).value.trim()||null,
            priority:$(".ai-task-priority",row).value,
            story_points:$(".ai-task-points",row).value===""?null:Number($(".ai-task-points",row).value)
          }));
        if(!tasks.length){error.textContent="Select at least one task.";error.classList.remove("hidden");return}
        if(tasks.some(task=>task.title.length<2)){error.textContent="Every selected task needs a title.";error.classList.remove("hidden");return}
        button.disabled=true;button.textContent="Creating tasks...";
        try{
          await api(`/projects/${state.project.id}/ai/task-plan/confirm`,{method:"POST",body:JSON.stringify({tasks})});
          closeModal();await loadWorkspace();toast(`${tasks.length} AI-planned task${tasks.length===1?"":"s"} created`);
        }catch(err){error.textContent=err.message;error.classList.remove("hidden");button.disabled=false;button.textContent="Create selected tasks"}
      };
    });
}
function field(name,label,type="text",placeholder="",required=false,full=false,value=""){
  const control=type==="textarea"?`<textarea name="${name}" placeholder="${placeholder}" ${required?"required":""}>${esc(value??"")}</textarea>`:`<input name="${name}" type="${type}" placeholder="${placeholder}" value="${esc(value??"")}" ${required?"required":""} ${name==="progress"?'min="0" max="100"':''}>`;
  return `<label class="field ${full||type==="textarea"?"full":""}">${label}${control}</label>`;
}
function selectField(name,label,items,selected="",empty=""){
  const normalized=items.map(x=>Array.isArray(x)?x:[x,pretty(x)]);
  return `<label class="field">${label}<select name="${name}">${empty?`<option value="">${empty}</option>`:""}${normalized.map(([v,l])=>`<option value="${esc(v)}" ${String(v)===String(selected)?"selected":""}>${esc(l)}</option>`).join("")}</select></label>`;
}
function formShell(title,subtitle,fields,submit,extra=""){return `<h2>${title}</h2><p class="subtitle">${subtitle}</p><form id="modal-form"><div class="form-grid">${fields}</div><div id="modal-error" class="form-error hidden"></div><div class="modal-actions">${extra}<button type="button" class="btn" onclick="document.querySelector('#modal-close').click()">Cancel</button><button class="btn primary">${submit}</button></div></form>`}
async function submitForm(event, action) {
  event.preventDefault(); const button=$('button[type="submit"],button.primary',event.target), error=$("#modal-error"); button.disabled=true;
  try { await action(formData(event.target)); closeModal(); render(); } catch(err) { error.textContent=err.message;error.classList.remove("hidden");button.disabled=false; }
}
if (state.token) boot();

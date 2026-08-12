const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const state = {
  token: localStorage.getItem("orbit_token"), profile: null,
  user: null, workspaces: [], workspace: null, projects: [], project: null,
  tasks: [], sprints: [], members: [], teams: [], teamMembers: [], designations: [], departments: [], userDirectory: [], skillCatalog: [], skillMembers: [], dashboard: null, board: null, view: "dashboard"
};
const VIEW_PATHS = {
  dashboard: "/app/overview",
  projects: "/app/projects",
  board: "/app/board",
  gantt: "/app/gantt",
  sprints: "/app/sprints",
  people: "/app/people",
  profile: "/app/profile",
  skills: "/app/skills",
  users: "/app/users"
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
function isAdmin() { return state.members.find(m => m.user_id === state.user?.id)?.role === "admin"; }
function canManageProject(project=state.project) { return isAdmin() || Boolean(project&&project.project_manager_id===state.user?.id); }
function canCollaborateProject(project=state.project) { return canManageProject(project) || Boolean(project&&state.teamMembers.some(a=>a.project_id===project.id&&a.user_id===state.user?.id)); }
function actorName(userId) { return state.members.find(m=>m.user_id===userId)?.user.name || (state.user?.id===userId?state.user.name:"Unknown member"); }
function date(value) { return value ? new Date(value).toLocaleDateString(undefined, {month:"short", day:"numeric", year:"numeric"}) : "Not set"; }
function dateTime(value) { return value ? new Date(value).toLocaleString(undefined, {month:"short",day:"numeric",year:"numeric",hour:"numeric",minute:"2-digit"}) : "Not set"; }
function pdfText(value="") { return String(value).normalize("NFKD").replace(/[^\x20-\x7E]/g," ").replace(/\\/g,"\\\\").replace(/\(/g,"\\(").replace(/\)/g,"\\)"); }
const PDF_W=842,PDF_H=595;
function pdfColor(hex){const value=hex?.match(/^#([0-9a-f]{6})$/i)?.[1]||"17233c";return [0,2,4].map(i=>(parseInt(value.slice(i,i+2),16)/255).toFixed(3)).join(" ")}
function pdfRect(x,y,w,h,fill="#ffffff",stroke=null){return `${pdfColor(fill)} rg${stroke?` ${pdfColor(stroke)} RG`:""} ${x} ${PDF_H-y-h} ${w} ${h} re ${stroke?"B":"f"}`}
function pdfLine(x1,y1,x2,y2,color="#e4e9f1",width=.6){return `${pdfColor(color)} RG ${width} w ${x1} ${PDF_H-y1} m ${x2} ${PDF_H-y2} l S`}
function pdfLabel(value,x,y,size=9,color="#17233c",bold=false,maxWidth=0){let text=String(value??"");if(maxWidth){const limit=Math.max(1,Math.floor(maxWidth/(size*.52)));if(text.length>limit)text=text.slice(0,Math.max(1,limit-1))+"…"}return `BT ${pdfColor(color)} rg /F${bold?2:1} ${size} Tf ${x} ${PDF_H-y-size} Td (${pdfText(text)}) Tj ET`}
function downloadVisualPdf(pages,fileName){
  const objects=[null,null,null,"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>","<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>"],pageIds=[];
  pages.forEach(commands=>{const pageId=objects.length,contentId=pageId+1,stream=commands.join("\n");pageIds.push(pageId);objects.push(`<< /Type /Page /Parent 2 0 R /MediaBox [0 0 ${PDF_W} ${PDF_H}] /Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> /Contents ${contentId} 0 R >>`);objects.push(`<< /Length ${stream.length} >>\nstream\n${stream}\nendstream`)});
  objects[1]="<< /Type /Catalog /Pages 2 0 R >>";objects[2]=`<< /Type /Pages /Kids [${pageIds.map(id=>`${id} 0 R`).join(" ")}] /Count ${pageIds.length} >>`;
  let pdf="%PDF-1.4\n",offsets=[0];for(let id=1;id<objects.length;id++){offsets[id]=pdf.length;pdf+=`${id} 0 obj\n${objects[id]}\nendobj\n`}const xref=pdf.length;pdf+=`xref\n0 ${objects.length}\n0000000000 65535 f \n${offsets.slice(1).map(offset=>String(offset).padStart(10,"0")+" 00000 n ").join("\n")}\ntrailer\n<< /Size ${objects.length} /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF`;
  const link=document.createElement("a");link.href=URL.createObjectURL(new Blob([pdf],{type:"application/pdf"}));link.download=`${fileName}.pdf`;link.click();setTimeout(()=>URL.revokeObjectURL(link.href),1000);
}
function pdfPageHeader(title,subtitle,page){return [pdfRect(0,0,PDF_W,PDF_H,"#f6f8fc"),pdfLabel("ORBIT",32,22,9,"#526dff",true),pdfLabel(title,32,38,20,"#17233c",true,650),pdfLabel(subtitle,32,64,9,"#71809c",false,650),pdfLabel(`Page ${page}`,755,34,8,"#71809c")];}
function safeFileName(value){return String(value||"export").trim().replace(/[^a-z0-9_-]+/gi,"-").replace(/^-+|-+$/g,"").toLowerCase()||"export"}
function exportBoardPdf(){
  const columns=state.board?.columns||[],groups=[];for(let i=0;i<Math.max(1,columns.length);i+=4)groups.push(columns.slice(i,i+4));const pages=[];
  groups.forEach(group=>{const maxTasks=Math.max(1,...group.map(c=>tasksForColumn(c.id).length));for(let offset=0;offset<maxTasks;offset+=6){const page=pdfPageHeader(`${state.project.name} — Task Board`,`${pretty(state.board?.framework||"kanban")} board · ${state.tasks.length} tasks`,pages.length+1),gap=10,colW=(778-gap*Math.max(0,group.length-1))/Math.max(1,group.length);group.forEach((column,index)=>{const x=32+index*(colW+gap),tasks=tasksForColumn(column.id),slice=tasks.slice(offset,offset+6);page.push(pdfRect(x,92,colW,34,"#edf0f6","#e4e9f1"),pdfRect(x+10,104,8,8,column.color||"#8b97ac"),pdfLabel(column.name,x+25,101,10,"#17233c",true,colW-65),pdfLabel(String(tasks.length),x+colW-24,101,9,"#71809c",true));slice.forEach((task,row)=>{const y=136+row*68;color=task.priority==="high"||task.priority==="critical"?"#df5261":task.priority==="medium"?"#e59a29":"#23a06b";page.push(pdfRect(x,y,colW,58,"#ffffff","#e4e9f1"),pdfRect(x+10,y+10,6,6,color),pdfLabel(pretty(task.priority),x+22,y+7,7,"#71809c",true,colW-35),pdfLabel(task.title,x+10,y+21,9,"#17233c",true,colW-20),pdfLabel(task.due_date?`Due ${date(task.due_date)}`:`${task.progress}% complete`,x+10,y+39,7,"#71809c",false,colW-20));if(task.progress){page.push(pdfRect(x+10,y+51,colW-20,3,"#e4e9f1"),pdfRect(x+10,y+51,(colW-20)*task.progress/100,3,"#526dff"))}});if(!slice.length)page.push(pdfLabel(offset?"No more tasks":"No tasks",x+12,150,8,"#71809c"))});pages.push(page)}});
  downloadVisualPdf(pages,`${safeFileName(state.project.name)}-task-board`);toast("Board chart PDF downloaded");
}
function exportGanttPdf(){
  const scheduled=state.tasks.map(task=>{const start=task.start_at||task.start_date,end=task.end_at||task.due_date;return start&&end?{task,start:new Date(start),end:new Date(end)}:null}).filter(Boolean).sort((a,b)=>a.start-b.start);let rangeStart=new Date();rangeStart.setHours(0,0,0,0);rangeStart.setDate(rangeStart.getDate()-3),rangeEnd=new Date(rangeStart);rangeEnd.setDate(rangeEnd.getDate()+30);if(scheduled.length){rangeStart=new Date(Math.min(rangeStart,...scheduled.map(x=>x.start)));rangeStart.setHours(0,0,0,0);rangeEnd=new Date(Math.max(rangeEnd,...scheduled.map(x=>x.end)))}const totalDays=Math.min(120,Math.max(1,Math.ceil((rangeEnd-rangeStart)/86400000)+1)),pages=[];
  const taskGroups=scheduled.length?Array.from({length:Math.ceil(scheduled.length/11)},(_,i)=>scheduled.slice(i*11,i*11+11)):[[]];for(let dayOffset=0;dayOffset<totalDays;dayOffset+=21){const dayCount=Math.min(21,totalDays-dayOffset);taskGroups.forEach(group=>{const page=pdfPageHeader(`${state.project.name} — Gantt Chart`,`${date(new Date(rangeStart.getTime()+dayOffset*86400000))} — ${date(new Date(rangeStart.getTime()+(dayOffset+dayCount-1)*86400000))}`,pages.length+1),nameW=185,gridX=217,gridW=593,dayW=gridW/dayCount,rowY=125,rowH=36;page.push(pdfRect(32,92,778,33,"#edf0f6","#e4e9f1"),pdfLabel("Task",42,103,9,"#17233c",true));for(let d=0;d<dayCount;d++){const current=new Date(rangeStart.getTime()+(dayOffset+d)*86400000),x=gridX+d*dayW;page.push(pdfLine(x,92,x,rowY+Math.max(1,group.length)*rowH,"#d9dfeb"),pdfLabel(current.toLocaleDateString(undefined,{month:"short"}),x+3,97,6,"#71809c",true,dayW-3),pdfLabel(current.getDate(),x+3,108,7,"#17233c",false,dayW-3))}group.forEach(({task,start,end},row)=>{const y=rowY+row*rowH;page.push(pdfRect(32,y,778,rowH,"#ffffff","#e4e9f1"),pdfLabel(task.title,42,y+8,8,"#17233c",true,nameW-20),pdfLabel(`${pretty(task.status)} · ${task.progress}%`,42,y+21,6,"#71809c",false,nameW-20));const startIndex=Math.floor((start-rangeStart)/86400000),endIndex=Math.max(startIndex,Math.ceil((end-rangeStart)/86400000)),visibleStart=Math.max(startIndex,dayOffset),visibleEnd=Math.min(endIndex+1,dayOffset+dayCount);if(visibleEnd>visibleStart){const colors={done:"#23a06b",in_progress:"#e59a29",review:"#8557d8",testing:"#8557d8"},barX=gridX+(visibleStart-dayOffset)*dayW+2,barW=Math.max(5,(visibleEnd-visibleStart)*dayW-4);page.push(pdfRect(barX,y+9,barW,18,colors[task.status]||"#526dff"),pdfLabel(`${task.progress}%`,barX+5,y+14,6,"#ffffff",true,barW-8))}});if(!group.length)page.push(pdfLabel("No scheduled tasks",42,145,10,"#71809c",true));pages.push(page)})}
  downloadVisualPdf(pages,`${safeFileName(state.project.name)}-gantt-chart`);toast("Gantt chart PDF downloaded");
}
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
  const publicAuthRequest = path === "/auth/login" || path === "/auth/register";
  const authenticatedRequest = Boolean(state.token) && !publicAuthRequest;
  if (authenticatedRequest) headers.Authorization = `Bearer ${state.token}`;
  if (options.body && !(options.body instanceof URLSearchParams)) headers["Content-Type"] = "application/json";
  const response = await fetch(path, {...options, headers});
  if (response.status === 401 && authenticatedRequest) { logout(false); throw new Error("Your session expired. Please sign in again."); }
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
  $("#modal-content").innerHTML = html; $("#modal").classList.remove("hidden"); onReady?.(); enhanceSkillInputs($("#modal-content"));
}
function skillValues(value=""){const seen=new Set();return String(value||"").replaceAll("\n",",").split(",").map(x=>x.trim().replace(/\s+/g," ")).filter(x=>x&&!seen.has(x.toLocaleLowerCase())&&seen.add(x.toLocaleLowerCase()))}
function enhanceSkillInputs(root=document){$$('textarea[name="skills"]',root).forEach(textarea=>{if(textarea.dataset.enhanced)return;textarea.dataset.enhanced="true";textarea.classList.add("hidden");let skills=skillValues(textarea.value);const editor=document.createElement("div"),tags=document.createElement("div"),input=document.createElement("input"),suggestions=document.createElement("div");editor.className="skill-tag-editor";tags.className="skill-tag-list";suggestions.className="skill-suggestions hidden";input.type="text";input.placeholder="Type a skill and press Enter or comma";const key=value=>value.toLocaleLowerCase();const matches=()=>{const query=key(input.value.trim());return state.skillCatalog.filter(skill=>!skills.some(selected=>key(selected)===key(skill))&&(!query||key(skill).includes(query))).slice(0,8)};const show=()=>{const found=matches();suggestions.innerHTML=found.map(skill=>`<button type="button" data-suggest-skill="${esc(skill)}">${esc(skill)}</button>`).join("");suggestions.classList.toggle("hidden",!found.length);$$('[data-suggest-skill]',suggestions).forEach(button=>button.onmousedown=e=>{e.preventDefault();add(button.dataset.suggestSkill)})};const sync=()=>{textarea.value=skills.join(", ");tags.innerHTML=skills.map((skill,index)=>`<span>${esc(skill)}<button type="button" data-remove-skill="${index}">×</button></span>`).join("");$$('[data-remove-skill]',tags).forEach(button=>button.onclick=()=>{skills.splice(Number(button.dataset.removeSkill),1);sync();show()})};const add=value=>{skillValues(value??input.value).forEach(skill=>{const existing=state.skillCatalog.find(item=>key(item)===key(skill));const display=existing||skill;if(!skills.some(item=>key(item)===key(display)))skills.push(display)});input.value="";sync();suggestions.classList.add("hidden")};input.oninput=show;input.onfocus=show;input.onblur=()=>setTimeout(()=>{add();suggestions.classList.add("hidden")},120);input.onkeydown=e=>{if(e.key==="Enter"||e.key===","){e.preventDefault();const first=matches()[0];add(e.key==="Enter"&&first?first:undefined)}else if(e.key==="Escape")suggestions.classList.add("hidden")};editor.append(tags,input,suggestions);textarea.after(editor);sync()})}
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
$$("[data-password-target]").forEach(button=>button.onclick=()=>{
  const input=document.getElementById(button.dataset.passwordTarget);
  const showing=input.type==="text";
  input.type=showing?"password":"text";
  button.setAttribute("aria-pressed",String(!showing));
  button.setAttribute("aria-label",showing?"Show password":"Hide password");
  button.title=showing?"Show password":"Hide password";
  button.classList.toggle("showing",!showing);
});
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
    const user = await api("/auth/register", {method:"POST", body:JSON.stringify({name:$("#register-name").value,email:$("#register-email").value,password:$("#register-password").value})});
    if (user.is_active) {
      const body = new URLSearchParams({username:$("#register-email").value,password:$("#register-password").value});
      const data = await api("/auth/login", {method:"POST",body,headers:{"Content-Type":"application/x-www-form-urlencoded"}});
      state.token = data.access_token; localStorage.setItem("orbit_token", state.token); await boot();
    } else {
      registerMode = false;
      $("#register-form").reset();
      $("#register-form").classList.add("hidden");
      $("#login-form").classList.remove("hidden");
      $("#auth-title").textContent = "Registration submitted";
      $("#auth-subtitle").textContent = "An administrator must approve your account before you can sign in.";
      $("#switch-copy").textContent = "Need another account?";
      $("#auth-switch").textContent = "Create an account";
      authError("Your request was sent to the administrator for approval.", true);
    }
  } catch (err) { authError(err.message); }
};
function authError(message, success = false) { $("#auth-error").textContent = message; $("#auth-error").classList.toggle("success", success); $("#auth-error").classList.remove("hidden"); }
function logout(show = true) {
  state.token = null;
  localStorage.removeItem("orbit_token");
  $("#auth-error").classList.add("hidden");
  $("#app-shell").classList.add("hidden");
  $("#auth-screen").classList.remove("hidden");
  if (show) toast("Signed out");
}
function showAuth() {
  $("#boot-screen").classList.add("hidden");
  $("#app-shell").classList.add("hidden");
  $("#auth-screen").classList.remove("hidden");
}
$("#logout-button").onclick = () => logout();

function profileFallback() {
  return {
    name: state.user?.name || "", email: state.user?.email || "", profile_image: null,
    phone: null, location: null, bio: null, professional_title: null,
    department: null, years_experience: null, skills: null, achievements: null,
    project_count: 0, projects: []
  };
}
async function boot() {
  try {
    // Establish the session first. Optional page data must never make a valid
    // login look like an authentication failure.
    state.user = await api("/auth/me");
  } catch (err) {
    if (state.token) authError(err.message);
    showAuth();
    return;
  }
  try {
    [state.workspaces,state.profile] = await Promise.all([
      api("/workspaces"),
      api("/auth/profile").catch(err => {
        console.error("Profile loading failed", err);
        return profileFallback();
      })
    ]);
    const savedId = Number(localStorage.getItem("orbit_workspace"));
    state.workspace = state.workspaces.find(w => w.id === savedId) || state.workspaces[0] || null;
    $("#user-name").textContent = state.user.name; $("#user-email").textContent = state.user.email;
    $("#user-avatar").textContent = state.user.name.slice(0,2).toUpperCase();
    $("#user-avatar").style.backgroundImage=state.profile.profile_image?`url("${state.profile.profile_image}")`:"";
    $("#user-avatar").classList.toggle("has-photo",Boolean(state.profile.profile_image));
    $("#auth-error").classList.add("hidden");
    $("#auth-screen").classList.add("hidden"); $("#app-shell").classList.remove("hidden");
    if (!PATH_VIEWS[window.location.pathname]) {
      history.replaceState({view:state.view}, "", VIEW_PATHS[state.view]);
    }
    updateWorkspaceUI();
    if (!state.workspace) { renderNoWorkspace(); } else { await loadWorkspace(); }
    $("#boot-screen").classList.add("hidden");
  } catch (err) {
    // Authentication already succeeded. Keep the signed-in shell visible and
    // report application-data failures without redirecting to the login page.
    $("#auth-screen").classList.add("hidden");
    $("#app-shell").classList.remove("hidden");
    $("#boot-screen").classList.add("hidden");
    toast(err.message || "Could not load your workspace", true);
  }
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
    [state.projects, state.dashboard, state.members, state.teams, state.teamMembers, state.designations, state.departments] = await Promise.all([
      api(`/workspaces/${workspace.id}/projects`), api(`/workspaces/${workspace.id}/dashboard`),
      api(`/workspaces/${workspace.id}/members`), api(`/workspaces/${workspace.id}/teams`),
      api(`/workspaces/${workspace.id}/team-members`), api(`/workspaces/${workspace.id}/designations`),
      api(`/workspaces/${workspace.id}/departments`)
    ]);
    if (state.project && !state.projects.some(p => p.id === state.project.id)) state.project = null;
    state.userDirectory=isAdmin()?await api(`/workspaces/${workspace.id}/user-directory`):[];
    state.skillCatalog=await api(`/workspaces/${workspace.id}/skill-catalog`);
    state.skillMembers=isAdmin()?await api(`/workspaces/${workspace.id}/skill-members`):[];
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
  if((state.view==="users"||state.view==="skills")&&!isAdmin())state.view="dashboard";
  const names = {dashboard:"Overview",projects:"Projects",board:"Task board",gantt:"Gantt chart",sprints:"Sprints",people:"People & teams",profile:"My profile",skills:"Skills",users:"Users"};
  $("#page-title").textContent = names[state.view];
  $('[data-view="sprints"]').classList.toggle("hidden", Boolean(state.project) && state.board?.framework !== "scrum");
  $("#sprint-project-label").textContent = state.board?.framework==="scrum"&&state.project?state.project.name:"";
  $("#quick-task").classList.toggle("hidden", state.view !== "board" || !state.project || !canManageProject());
  $("#admin-users-nav").classList.toggle("hidden",!isAdmin());
  $("#admin-skills-nav").classList.toggle("hidden",!isAdmin());
  $("#content").innerHTML = ({dashboard:dashboardView,projects:projectsView,board:boardView,gantt:ganttView,sprints:sprintsView,people:peopleView,profile:profileView,skills:skillsView,users:usersView}[state.view])();
  $$("#main-nav button").forEach(button => button.classList.toggle("active", button.dataset.view === state.view));
  bindView();
  document.body.classList.toggle("read-only", !canManageProject());
  document.body.classList.toggle("view-only", !canCollaborateProject());
  bindAccessControls();
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
function projectCards(items){return items.length?items.map(p=>`<article class="project-card" data-project="${p.id}"><div class="project-head"><span class="project-icon">${esc(p.name[0].toUpperCase())}</span><div class="project-card-actions"><span class="badge ${p.status}">${pretty(p.status)}</span>${canManageProject(p)?`<button data-edit-project="${p.id}" title="Edit project">•••</button>`:""}</div></div><h3>${esc(p.name)}</h3><p>${esc(p.description||"No description yet.")}</p><div class="project-meta"><span>${pretty(p.priority)} priority</span><span>${p.deadline?`Due ${date(p.deadline)}`:"No deadline"}</span></div></article>`).join(""):emptyMini("No projects available","No projects have been created yet.") }
function projectSelector() {
  return `<select id="project-select">${state.projects.map(p=>`<option value="${p.id}" ${p.id===state.project?.id?"selected":""}>${esc(p.name)}</option>`).join("")}</select>`;
}
function boardView() {
  if (!state.project) return `${pageHeading("Task board","Visualize work as it moves through your workflow.",`<button id="new-project" class="btn primary">＋ New project</button>`)}${emptyMini("Create a project first","Tasks live inside projects.")}`;
  const columns = state.board?.columns || [];
  return `${pageHeading("Task board",`Drag tasks and lists to organize ${esc(state.project.name)}.`,`<div class="board-actions"><button id="export-board-pdf" class="btn">Download PDF</button><button id="ai-plan-tasks" class="btn ai-btn">AI plan</button><button id="customize-board" class="btn">⚙ Customize</button><button id="new-task-view" class="btn primary">＋ Add task</button></div>`)}
    <div class="toolbar">${projectSelector()}${state.board?.framework==="scrum"?`<select id="sprint-filter"><option value="">All Scrum work</option><option value="backlog">Product backlog</option>${state.sprints.map(s=>`<option value="${s.id}">${s.is_active?"● ":""}${esc(s.name)}</option>`).join("")}</select>`:""}<span class="framework-pill">${pretty(state.board?.framework||"kanban")} board</span></div>
    <div class="board-wrap"><div class="kanban custom-board" style="grid-template-columns:repeat(${columns.length + 1}, minmax(275px, 1fr))">${columns.map(column=>kanbanColumn(column,tasksForColumn(column.id))).join("")}<button id="add-column" class="add-column">＋ Add another list</button></div></div>`;
}
function tasksForColumn(columnId) {
  return state.tasks
    .filter(task => Number(state.board?.task_positions?.[task.id]?.column_id) === columnId)
    .sort((a,b) => (state.board.task_positions[a.id]?.position ?? 0) - (state.board.task_positions[b.id]?.position ?? 0));
}
function kanbanColumn(column,tasks){return `<section class="kanban-col" draggable="${canManageProject()}" data-column="${column.id}"><div class="kanban-head"><i style="background:${column.color}"></i><strong>${esc(column.name)}</strong><span class="column-count" title="${tasks.length} tasks">${tasks.length}</span>${canManageProject()?`<button class="column-menu" data-column-menu="${column.id}" title="List options">•••</button>`:""}</div><div class="task-dropzone" data-drop-column="${column.id}">${tasks.map(taskCard).join("")}</div>${canManageProject()?`<button class="column-add" data-add-to="${column.id}">＋ Add a card</button>`:""}</section>`}
function taskCard(t){
  const assignees=(t.assignee_ids||[]).map(id=>state.members.find(m=>m.user_id===id)?.user).filter(Boolean);
  const checklist=t.checklist_total?`<span class="check-count ${t.checklist_done===t.checklist_total?"complete":""}">☑ ${t.checklist_done}/${t.checklist_total}</span>`:"";
  return `<article class="task-card" draggable="${canManageProject()}" data-task="${t.id}"><span class="priority-dot ${t.priority}">${t.priority}</span><h4>${esc(t.title)}</h4><p>${esc(t.description||"No description")}</p>
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
  return `${pageHeading("Gantt chart",`Timeline planning for ${esc(state.project.name)}.`,`<div class="board-actions"><button id="export-gantt-pdf" class="btn">Download PDF</button><button id="gantt-new-task" class="btn primary">＋ Schedule task</button></div>`)}
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
function profileView(){
  const p=state.profile||{},initials=state.user.name.slice(0,2).toUpperCase();
  const skills=(p.skills||"").split(/[\n,]+/).map(x=>x.trim()).filter(Boolean);
  const designationOptions=state.designations.map(item=>[item.name,item.name]);
  if(p.professional_title&&!state.designations.some(item=>item.name===p.professional_title))designationOptions.push([p.professional_title,p.professional_title]);
  const departmentOptions=state.departments.map(item=>[item.name,item.name]);
  if(p.department&&!state.departments.some(item=>item.name===p.department))departmentOptions.push([p.department,p.department]);
  return `${pageHeading("My profile","Keep your personal and professional information up to date.")}
  <div class="profile-layout"><aside class="panel profile-summary"><div id="profile-photo-preview" class="profile-photo ${p.profile_image?"has-photo":""}" style="${p.profile_image?`background-image:url('${esc(p.profile_image)}')`:""}">${p.profile_image?"":esc(initials)}</div><h2>${esc(p.name||state.user.name)}</h2><p>${esc(p.professional_title||"Add your professional title")}</p><span>${esc(p.email||state.user.email)}</span><div class="profile-project-stat"><strong>${p.project_count||0}</strong><small>Projects worked on</small></div><div class="profile-skills">${skills.map(skill=>`<span>${esc(skill)}</span>`).join("")||"<small>Add skills to complete your profile.</small>"}</div><div class="profile-history"><h3>Project history</h3>${(p.projects||[]).map(name=>`<div><span class="project-icon">${esc(name[0]?.toUpperCase()||"P")}</span>${esc(name)}</div>`).join("")||"<small>No project history yet.</small>"}</div></aside>
  <section class="panel profile-editor"><form id="profile-form"><h3>Profile photo</h3><div class="profile-photo-actions"><label class="btn" for="profile-image-input">Choose image</label><input id="profile-image-input" type="file" accept="image/png,image/jpeg,image/webp" hidden><button id="remove-profile-image" type="button" class="btn">Remove</button><small>PNG, JPG or WebP, maximum 2 MB.</small></div><h3>Personal details</h3><div class="form-grid">${field("name","Full name","text","Your full name",true,false,p.name||state.user.name)}${field("phone","Phone","tel","Phone number",false,false,p.phone)}${field("location","Location","text","City, country",false,false,p.location)}${field("bio","About me","textarea","A short introduction",false,true,p.bio)}<h3 class="profile-form-heading">Professional details</h3>${selectField("professional_title","Professional title · Designation",designationOptions,p.professional_title,"Select designation")}${selectField("department","Department",departmentOptions,p.department,"Select department")}${field("years_experience","Years of experience","number","0",false,false,p.years_experience)}${field("skills","Skills","textarea","One skill per line or comma separated",false,true,p.skills)}${field("achievements","Achievements","textarea","Awards, certifications and professional milestones",false,true,p.achievements)}</div><div id="profile-error" class="form-error hidden"></div><div class="modal-actions"><button class="btn primary" type="submit">Save profile</button></div></form></section></div>`;
}
function bindProfileView(){
  const form=$("#profile-form");if(!form)return;
  enhanceSkillInputs(form);
  let profileImage=state.profile?.profile_image||null;
  $("#profile-image-input").onchange=event=>{
    const file=event.target.files[0];if(!file)return;
    if(file.size>2*1024*1024){toast("Profile image must be smaller than 2 MB",true);event.target.value="";return}
    const reader=new FileReader();reader.onload=()=>{profileImage=reader.result;const preview=$("#profile-photo-preview");preview.textContent="";preview.style.backgroundImage=`url("${profileImage}")`;preview.classList.add("has-photo")};reader.readAsDataURL(file);
  };
  $("#remove-profile-image").onclick=()=>{profileImage=null;const preview=$("#profile-photo-preview");preview.style.backgroundImage="";preview.textContent=state.user.name.slice(0,2).toUpperCase();preview.classList.remove("has-photo")};
  form.onsubmit=async event=>{event.preventDefault();const button=$('button[type="submit"]',form),error=$("#profile-error");button.disabled=true;try{const data=formData(form);data.profile_image=profileImage;if(data.years_experience!==null)data.years_experience=Number(data.years_experience);state.profile=await api("/auth/profile",{method:"PUT",body:JSON.stringify(data)});state.user.name=state.profile.name;$("#user-name").textContent=state.profile.name;$("#user-avatar").textContent=state.profile.profile_image?"":state.profile.name.slice(0,2).toUpperCase();$("#user-avatar").style.backgroundImage=state.profile.profile_image?`url("${state.profile.profile_image}")`:"";$("#user-avatar").classList.toggle("has-photo",Boolean(state.profile.profile_image));render();toast("Profile updated")}catch(err){error.textContent=err.message;error.classList.remove("hidden")}finally{button.disabled=false}};
}
function skillsView(){
  if(!isAdmin())return emptyMini("Admin access required","Only workspace admins can search skills and assign work.");
  return `${pageHeading("Skills","Find the right member by skill and assign them to project tasks.",`<span class="member-count">${state.skillCatalog.length}</span>`)}<div class="skills-search"><input id="skills-search" placeholder="Search Python, design, accounting or a member name"><select id="skills-filter"><option value="">All skills</option>${state.skillCatalog.map(skill=>`<option value="${esc(skill)}">${esc(skill)}</option>`).join("")}</select></div><div id="skills-directory" class="skills-directory">${skillMemberCards(state.skillMembers)}</div>`;
}
function skillMemberCards(members){return members.length?members.map(member=>`<article class="panel skill-member-card"><div class="skill-member-head"><b class="avatar">${esc(member.name.slice(0,2).toUpperCase())}</b><div><strong>${esc(member.name)}</strong><small>${esc(member.professional_title||member.department||member.email)}</small></div></div><div class="skill-tags">${member.skills.map(skill=>`<span>${esc(skill)}</span>`).join("")||"<small>No skills added yet</small>"}</div><button class="btn primary" data-skill-assign="${member.user_id}" ${member.project_ids.length?"":"disabled"}>Assign to task</button>${member.project_ids.length?"":"<small class=\"skill-allocation-note\">Allocate this member to a project first.</small>"}</article>`).join(""):emptyMini("No matching members","Try another skill or add skills to member profiles.")}
function bindSkillsView(){const search=$("#skills-search"),filter=$("#skills-filter");if(!search)return;const apply=()=>{const query=search.value.trim().toLowerCase(),skill=filter.value.toLowerCase();const members=state.skillMembers.filter(member=>(!query||member.name.toLowerCase().includes(query)||member.email.toLowerCase().includes(query)||member.skills.some(item=>item.toLowerCase().includes(query)))&&(!skill||member.skills.some(item=>item.toLowerCase()===skill)));$("#skills-directory").innerHTML=skillMemberCards(members);bindSkillAssignButtons()};search.oninput=apply;filter.onchange=apply;bindSkillAssignButtons()}
function bindSkillAssignButtons(){$$('[data-skill-assign]').forEach(button=>button.onclick=()=>skillTaskAssignModal(state.skillMembers.find(member=>member.user_id===Number(button.dataset.skillAssign))))}
function skillTaskAssignModal(member){const projects=state.projects.filter(project=>member.project_ids.includes(project.id));let projectTasks=[];modal(formShell("Assign member to task",`Choose a project task for ${esc(member.name)}.`,`${selectField("project_id","Project",projects.map(project=>[project.id,project.name]))}<label class="field full">Task<select name="task_id" id="skill-task-select" required><option value="">Select a project first</option></select></label>`,"Assign task"),()=>{const projectSelect=$('[name="project_id"]'),taskSelect=$("#skill-task-select");const load=async()=>{taskSelect.innerHTML='<option value="">Loading tasks…</option>';try{projectTasks=await api(`/projects/${projectSelect.value}/tasks`);taskSelect.innerHTML=`<option value="">Select task</option>${projectTasks.map(task=>`<option value="${task.id}">${esc(task.title)}</option>`).join("")}`}catch(err){taskSelect.innerHTML='<option value="">Could not load tasks</option>';toast(err.message,true)}};projectSelect.onchange=load;if(projectSelect.value)load();$("#modal-form").onsubmit=async event=>submitForm(event,async data=>{const task=projectTasks.find(item=>item.id===Number(data.task_id));if(!task)throw new Error("Select a task");const assignee_ids=[...new Set([...(task.assignee_ids||[]),member.user_id])];await api(`/tasks/${task.id}`,{method:"PATCH",body:JSON.stringify({assignee_ids})});if(state.project?.id===Number(data.project_id))await loadProject();toast(`${member.name} assigned to ${task.title}`)})})}
function usersView(){
  if(!isAdmin())return emptyMini("Admin access required","Only workspace admins can manage users.");
  return `${pageHeading("Users","Manage registered accounts and their access to this workspace.",`<span class="member-count">${state.userDirectory.length}</span>`)}<div class="users-toolbar"><input id="user-search" placeholder="Search by name or email"><select id="user-department-filter"><option value="">All departments</option>${state.departments.map(item=>`<option value="${esc(item.name)}">${esc(item.name)}</option>`).join("")}</select><select id="user-designation-filter"><option value="">All designations</option>${state.designations.map(item=>`<option value="${esc(item.name)}">${esc(item.name)}</option>`).join("")}</select><select id="user-project-filter"><option value="">All projects</option>${state.projects.map(item=>`<option value="${esc(item.name)}">${esc(item.name)}</option>`).join("")}</select></div><section class="panel users-table-wrap"><table class="users-table"><thead><tr><th>User</th><th>Department</th><th>Designation</th><th>Project allocations</th><th>Access</th><th>Status</th><th>Actions</th></tr></thead><tbody id="users-table-body">${userDirectoryRows(state.userDirectory)}</tbody></table></section>`;
}
function userDirectoryActions(user){const edit=`<button data-directory-profile="${user.user_id}">Edit profile</button>`,remove=user.user_id!==state.user.id?`<button class="remove-action" data-directory-delete="${user.user_id}">Delete</button>`:"";return `${edit}${remove}`}
function userDirectoryAccess(user){if(!user.is_active)return '<span class="badge pending">Pending approval</span>';if(!user.membership_id)return '<span class="badge">Not added</span>';return `<div class="role-access"><span class="badge ${user.role}">${pretty(user.role)}</span>${user.user_id!==state.user.id?`<button data-edit-access="${user.user_id}" title="Change workspace role">Edit</button>`:""}</div>`}
function userDirectoryStatus(user){if(!user.is_active)return `<button class="approve-action" data-directory-approve="${user.user_id}">Approve</button>`;if(!user.membership_id)return `<button class="add-member-action" data-directory-add="${user.user_id}"><span>＋</span> Add member</button>`;if(user.user_id===state.user.id)return `<span class="status-self">Current user</span>`;return `<label class="access-switch" title="${user.membership_is_active?"Deactivate":"Activate"} workspace access"><input type="checkbox" data-directory-access="${user.user_id}" ${user.membership_is_active?"checked":""}><span></span><em>${user.membership_is_active?"Active":"Inactive"}</em></label>`}
function userDirectoryRows(users){return users.length?users.map(user=>`<tr class="${user.is_active?"":"pending-user"}"><td><div class="directory-user"><b class="avatar">${esc(user.name.slice(0,2).toUpperCase())}</b><span><strong>${esc(user.name)}</strong><small>${esc(user.email)}</small></span></div></td><td>${esc(user.department||"Not set")}</td><td>${esc(user.professional_title||"Not set")}</td><td><div class="directory-projects">${user.projects.length?user.projects.map(project=>`<span>${esc(project)}</span>`).join(""):"<small>No allocations</small>"}</div></td><td>${userDirectoryAccess(user)}</td><td>${userDirectoryStatus(user)}</td><td><div class="directory-actions">${userDirectoryActions(user)}</div></td></tr>`).join(""):`<tr><td colspan="7" class="users-empty">No users match these filters.</td></tr>`}
function filterUserDirectory(){const query=$("#user-search").value.trim().toLowerCase(),department=$("#user-department-filter").value,designation=$("#user-designation-filter").value,project=$("#user-project-filter").value;const users=state.userDirectory.filter(user=>(!query||user.name.toLowerCase().includes(query)||user.email.toLowerCase().includes(query))&&(!department||user.department===department)&&(!designation||user.professional_title===designation)&&(!project||user.projects.includes(project)));$("#users-table-body").innerHTML=userDirectoryRows(users);bindUserDirectoryActions()}
function addDirectoryUserModal(user){modal(formShell("Add workspace user",`Add ${esc(user.name)} (${esc(user.email)}) to this workspace.`,selectField("role","Workspace role",["member","admin"],"member"),"Add user"),()=>$("#modal-form").onsubmit=async event=>submitForm(event,async data=>{data.email=user.email;const member=await api(`/workspaces/${state.workspace.id}/members`,{method:"POST",body:JSON.stringify(data)});state.members.push(member);state.userDirectory=state.userDirectory.map(item=>item.user_id===user.user_id?{...item,membership_id:member.id,membership_is_active:true,role:member.role}:item);toast("User added and activated")}))}
function editDirectoryAccessModal(user){modal(formShell("Edit access",`Change ${esc(user.name)}'s role in this workspace.`,selectField("role","Workspace role",[["member","Member"],["admin","Admin"]],user.role),"Save access"),()=>$("#modal-form").onsubmit=async event=>submitForm(event,async data=>{const member=await api(`/workspaces/${state.workspace.id}/members/${user.membership_id}/access`,{method:"PATCH",body:JSON.stringify({role:data.role})});user.role=member.role;state.members=state.members.map(item=>item.id===member.id?member:item);toast(`${user.name} is now ${pretty(member.role)}`)}))}
async function adminUserProfileModal(directoryUser){
  const member=state.members.find(item=>item.user_id===directoryUser.user_id);
  try{const profile=await api(`/workspaces/${state.workspace.id}/users/${directoryUser.user_id}/profile`);modal(formShell("Edit user profile","Update profile details. The registered email address cannot be changed.",`<label class="field full">Email address<input value="${esc(profile.email)}" readonly disabled></label>${field("name","Full name","text","Full name",true,false,profile.name)}${field("phone","Phone","tel","Phone number",false,false,profile.phone)}${field("location","Location","text","City, country",false,false,profile.location)}${field("bio","About","textarea","Personal introduction",false,true,profile.bio)}${selectField("professional_title","Professional title · Designation",state.designations.map(item=>[item.name,item.name]),profile.professional_title,"Select designation")}${selectField("department","Department",state.departments.map(item=>[item.name,item.name]),profile.department,"Select department")}${field("years_experience","Years of experience","number","0",false,false,profile.years_experience)}${field("skills","Skills","textarea","One skill per line or comma separated",false,true,profile.skills)}${field("achievements","Achievements","textarea","Awards, certifications and milestones",false,true,profile.achievements)}`,"Save profile"),()=>$("#modal-form").onsubmit=async event=>submitForm(event,async data=>{if(data.years_experience!==null)data.years_experience=Number(data.years_experience);data.profile_image=profile.profile_image;const updated=await api(`/workspaces/${state.workspace.id}/users/${directoryUser.user_id}/profile`,{method:"PUT",body:JSON.stringify(data)});state.userDirectory=state.userDirectory.map(user=>user.user_id===directoryUser.user_id?{...user,name:updated.name,professional_title:updated.professional_title,department:updated.department}:user);if(member)state.members=state.members.map(item=>item.id===member.id?{...item,user:{...item.user,name:updated.name},professional_title:updated.professional_title,department:updated.department}:item);if(directoryUser.user_id===state.user.id){state.user.name=updated.name;state.profile=updated}toast("User profile updated")}))}catch(err){toast(err.message,true)}
}
function bindUserDirectoryActions(){
  $$('[data-directory-approve]').forEach(button=>button.onclick=async()=>{const user=state.userDirectory.find(item=>item.user_id===Number(button.dataset.directoryApprove));if(!user)return;try{await api(`/workspaces/${state.workspace.id}/users/${user.user_id}/approve`,{method:"PATCH"});user.is_active=true;render();toast(`${user.name} can now sign in`)}catch(err){toast(err.message,true)}});
  $$('[data-directory-access]').forEach(button=>button.onclick=async()=>{const user=state.userDirectory.find(item=>item.user_id===Number(button.dataset.directoryAccess));if(!user)return;const next=!user.membership_is_active;try{const member=await api(`/workspaces/${state.workspace.id}/members/${user.membership_id}/access`,{method:"PATCH",body:JSON.stringify({is_active:next})});user.membership_is_active=member.is_active;state.members=state.members.map(item=>item.id===member.id?member:item);render();toast(`${user.name} is now ${next?"active":"inactive"}`)}catch(err){toast(err.message,true)}});
  $$('[data-edit-access]').forEach(button=>button.onclick=()=>editDirectoryAccessModal(state.userDirectory.find(item=>item.user_id===Number(button.dataset.editAccess))));
  $$("[data-directory-add]").forEach(button=>button.onclick=()=>addDirectoryUserModal(state.userDirectory.find(user=>user.user_id===Number(button.dataset.directoryAdd))));
  $$("[data-directory-profile]").forEach(button=>button.onclick=()=>adminUserProfileModal(state.userDirectory.find(user=>user.user_id===Number(button.dataset.directoryProfile))));
  $$("[data-directory-delete]").forEach(button=>button.onclick=async()=>{const user=state.userDirectory.find(item=>item.user_id===Number(button.dataset.directoryDelete));if(!user)return;const confirmation=prompt(`Delete ${user.name} and all project allocations? Type their email to confirm:`);if(confirmation!==user.email){if(confirmation!==null)toast("Email confirmation did not match",true);return}try{await api(`/workspaces/${state.workspace.id}/users/${user.user_id}`,{method:"DELETE"});state.userDirectory=state.userDirectory.filter(item=>item.user_id!==user.user_id);state.members=state.members.filter(item=>item.user_id!==user.user_id);state.teamMembers=state.teamMembers.filter(item=>item.user_id!==user.user_id);render();toast("User deleted")}catch(err){toast(err.message,true)}})
}
function bindView() {
  bindSkillsView();
  $$("[data-go]").forEach(x=>x.onclick=()=>navigate(x.dataset.go));
  $$("[data-project]").forEach(x=>x.onclick=async()=>{
    const project=state.projects.find(p=>p.id===Number(x.dataset.project));
    if(!project)return;
    state.project=project;
    localStorage.setItem(`orbit_project_${state.workspace.id}`,state.project.id);
    try{await loadProject();navigate("board")}catch(err){toast(`Could not open project: ${err.message}`,true)}
  });
  $$("[data-edit-project]").forEach(button=>button.onclick=event=>{event.stopPropagation();projectEditModal(state.projects.find(project=>project.id===Number(button.dataset.editProject)))});
  $("#new-project")?.addEventListener("click", projectModal); $("#new-task-view")?.addEventListener("click",()=>taskModal());
  $("#gantt-new-task")?.addEventListener("click",()=>taskModal());
  $("#new-sprint")?.addEventListener("click", sprintModal); $("#add-member")?.addEventListener("click", memberModal); $("#new-team")?.addEventListener("click",()=>teamModal());
  $$("[data-edit-sprint]").forEach(button=>button.onclick=()=>sprintModal(state.sprints.find(sprint=>sprint.id===Number(button.dataset.editSprint))));
  $("#project-select")?.addEventListener("change", async e=>{state.project=state.projects.find(p=>p.id===Number(e.target.value));localStorage.setItem(`orbit_project_${state.workspace.id}`,state.project.id);await loadProject();render()});
  $("#sprint-filter")?.addEventListener("change", e=>{const value=e.target.value;$$(".task-card").forEach(card=>{const task=state.tasks.find(t=>t.id===Number(card.dataset.task));card.classList.toggle("hidden",value==="backlog"?task.sprint_id!==null:Boolean(value)&&task.sprint_id!==Number(value))})});
  $$("[data-task]").forEach(x=>x.onclick=()=>taskDetail(Number(x.dataset.task)));
  $$("[data-add-to]").forEach(x=>x.onclick=()=>taskModal(null,Number(x.dataset.addTo)));
  $$("[data-column-menu]").forEach(x=>x.onclick=e=>{e.stopPropagation();columnModal(Number(x.dataset.columnMenu))});
  $("#add-column")?.addEventListener("click",()=>columnModal());
  $("#customize-board")?.addEventListener("click",boardSettingsModal);
  $("#ai-plan-tasks")?.addEventListener("click",aiTaskPlannerModal);
  $("#export-board-pdf")?.addEventListener("click",exportBoardPdf);
  $("#export-gantt-pdf")?.addEventListener("click",exportGanttPdf);
  bindProfileView();
  ["#user-search","#user-department-filter","#user-designation-filter","#user-project-filter"].forEach(selector=>$(selector)?.addEventListener(selector==="#user-search"?"input":"change",filterUserDirectory));
  bindUserDirectoryActions();
  bindBoardDragDrop();
  $("#project-search")?.addEventListener("input", filterProjects); $("#project-filter")?.addEventListener("change", filterProjects);
}
function filterProjects(){const q=$("#project-search").value.toLowerCase(),s=$("#project-filter").value;$("#project-grid").innerHTML=projectCards(state.projects.filter(p=>(p.name.toLowerCase().includes(q)||p.description?.toLowerCase().includes(q))&&(!s||p.status===s)));bindView()}

let draggedTaskId = null;
let draggedColumnId = null;
let ignoreTaskClick = false;
function bindBoardDragDrop() {
  if (!canManageProject()) return;
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
  const projectAdmins=state.members.filter(member=>member.role==="admin");
  modal(formShell("Create a project","Turn an idea into an organized plan.",`
  ${field("name","Project name","text","e.g. Mobile app launch",true)}${field("description","Description","textarea","What is this project about?","",true)}
  ${selectField("framework","Work framework",[["kanban","Kanban — continuous flow"],["scrum","Scrum — sprint planning"]],"kanban")}
  ${selectField("status","Status",["planned","active","on_hold","completed"])}${selectField("priority","Priority",["low","medium","high","critical"],"medium")}
  ${selectField("project_manager_id","Project admin",projectAdmins.map(member=>[member.user_id,member.user.name]),state.user.id)}
  ${field("deadline","Deadline","date")}${field("budget","Budget","number","Optional")}`,"Create project"),()=>$("#modal-form").onsubmit=async e=>submitForm(e,async data=>{
    const framework=data.framework;delete data.framework;data.project_manager_id=Number(data.project_manager_id);if(data.budget)data.budget=Number(data.budget);const p=await api(`/workspaces/${workspaceId}/projects`,{method:"POST",body:JSON.stringify(data)});await api(`/projects/${p.id}/board`,{method:"PUT",body:JSON.stringify({framework})});state.projects.unshift(p);state.project=p;localStorage.setItem(`orbit_project_${workspaceId}`,p.id);await loadWorkspace();toast(`${pretty(framework)} project created`);
  }));}
function projectEditModal(project){
  if(!project)return;
  const projectAdmins=state.members.filter(member=>member.role==="admin");
  modal(formShell("Edit project","Update the project details and delivery settings.",`
    ${field("name","Project name","text","Project name",true,false,project.name)}
    ${field("description","Description","textarea","What is this project about?","",true,project.description)}
    ${selectField("status","Status",["planned","active","on_hold","completed"],project.status)}
    ${selectField("priority","Priority",["low","medium","high","critical"],project.priority)}
    ${selectField("project_manager_id","Project admin",projectAdmins.map(member=>[member.user_id,member.user.name]),project.project_manager_id||state.user.id)}
    ${field("deadline","Deadline","date","","",false,project.deadline)}
    ${field("budget","Budget","number","Optional","",false,project.budget)}`,
    "Save changes",`<button type="button" id="delete-project" class="btn danger">Delete project</button>`),()=>{
      $("#modal-form").onsubmit=async event=>submitForm(event,async data=>{
        data.project_manager_id=Number(data.project_manager_id);if(data.budget!==null)data.budget=Number(data.budget);
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
function taskModal(task=null,targetColumnId=null){
  const projectAllocations=state.teamMembers.filter(a=>a.project_id===state.project.id);
  const assignmentTeams=state.teams;
  const currentAssignees=task?.assignee_ids||[];
  let selectedTeamId=assignmentTeams.find(team=>currentAssignees.some(userId=>projectAllocations.some(a=>a.team_id===team.id&&a.user_id===userId)))?.id||"";
  const assigneeOptions=teamId=>{
    if(!teamId)return `<span class="subtitle">Select a team to see its allocated project members.</span>`;
    const userIds=[...new Set(projectAllocations.filter(a=>a.team_id===Number(teamId)).map(a=>a.user_id))];
    const members=userIds.map(id=>state.members.find(m=>m.user_id===id)).filter(Boolean);
    return members.map(m=>`<label><input type="checkbox" name="assignee_ids" value="${m.user_id}" ${currentAssignees.includes(m.user_id)?"checked":""}><span class="avatar">${esc(m.user.name.slice(0,2).toUpperCase())}</span><span>${esc(m.user.name)}<small>${esc(projectAllocations.find(a=>a.team_id===Number(teamId)&&a.user_id===m.user_id)?.designation||"")}</small></span></label>`).join("")||`<span class="subtitle">No members are allocated to this team for ${esc(state.project.name)}.</span>`;
  };
  modal(formShell(task?"Edit task":"Create a task",task?"Update task details and progress.":`Add work to ${esc(state.project.name)}.`,`
  ${field("title","Task title","text","What needs to be done?",true,false,task?.title)}${field("description","Description","textarea","Add context and acceptance criteria","",true,task?.description)}
  ${selectField("status","Status",STATUS.map(x=>x[0]),task?.status||"backlog")}${selectField("priority","Priority",["low","medium","high","critical"],task?.priority||"medium")}
  ${state.board?.framework==="scrum"?`<div class="field full"><label>Sprint · ${esc(state.project.name)}</label><div class="inline-control"><select name="sprint_id"><option value="">Product backlog</option>${state.sprints.map(s=>`<option value="${s.id}" ${s.id===task?.sprint_id?"selected":""}>${s.is_active?"● Active · ":""}${esc(s.name)}</option>`).join("")}</select><button type="button" id="show-quick-sprint" class="btn">＋ New sprint</button></div><div id="quick-sprint-row" class="quick-sprint-row hidden"><input id="quick-sprint-name" placeholder="Sprint name, e.g. Sprint 01"><button type="button" id="create-quick-sprint" class="btn primary">Create</button></div><small class="field-help">${state.sprints.length?`${state.sprints.length} sprint${state.sprints.length===1?"":"s"} in this project`:"No sprints yet — create one here or from the Sprints page."}</small></div>`:""}
  <label class="field full">Assignment team<select id="task-team-select" name="assignment_team_id"><option value="">Select a team first</option>${assignmentTeams.map(team=>`<option value="${team.id}" ${team.id===selectedTeamId?"selected":""}>${esc(team.name)}</option>`).join("")}</select><small class="field-help">Members must be allocated to this team and project before they can be assigned.</small></label>
  <fieldset class="field full assignee-field"><legend>Assignees · select multiple</legend><div id="task-assignee-options" class="assignee-options">${assigneeOptions(selectedTeamId)}</div></fieldset>
  ${field("story_points","Story points","number","0–100","",false,task?.story_points)}${field("due_date","Due date","date","","",false,task?.due_date)}
  ${field("start_at","Start date & time","datetime-local","","",false,inputDateTime(task?.start_at))}${field("end_at","End date & time","datetime-local","","",false,inputDateTime(task?.end_at))}
  ${progressField(task?.progress??0)}`,task?"Save changes":"Create task",task?`<button type="button" id="delete-task" class="btn danger">Delete</button>`:""),()=>{
    const progress=$("#task-progress");
    const updateProgress=()=>{
      const value=Number(progress.value);
      $("#task-progress-value").textContent=`${value}%`;
      progress.style.setProperty("--progress",`${value}%`);
    };
    progress.addEventListener("input",updateProgress);updateProgress();
    $("#task-team-select").addEventListener("change",event=>{
      selectedTeamId=event.target.value;
      $("#task-assignee-options").innerHTML=assigneeOptions(selectedTeamId);
    });
    $("#modal-form").onsubmit=async e=>submitForm(e,async data=>{
      data.assignee_ids=$$('input[name="assignee_ids"]:checked',e.currentTarget).map(input=>Number(input.value));
      delete data.assignment_team_id;
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
      <div id="checklist-items">${checklist.map(item=>`<div class="check-item"><input type="checkbox" data-check="${item.id}" ${item.is_done?"checked":""}><span class="${item.is_done?"done":""}">${esc(item.text)}<small>${item.last_action_by_id?`${pretty(item.last_action||"updated")} by ${esc(actorName(item.last_action_by_id))}`:item.created_by_id?`Created by ${esc(actorName(item.created_by_id))}`:""}</small></span><button data-delete-check="${item.id}">×</button></div>`).join("")||"<p class='subtitle'>No checklist items yet.</p>"}</div>
      <form id="checklist-form" class="comment-form"><input name="text" placeholder="Add an item…" required><button class="btn">Add</button></form></section>
    <section class="comments"><h3>Comments</h3><div id="comment-list">${comments.length?comments.map(c=>`<div class="comment"><strong>${esc(actorName(c.author_id))}</strong><p>${esc(c.body)}</p><small>${dateTime(c.created_at)}</small></div>`).join(""):"<p class='subtitle'>No comments yet.</p>"}</div>
    <form id="comment-form" class="comment-form"><input name="body" placeholder="Write a comment…" required><button class="btn primary">Send</button></form></section>`,()=>{
      $("#edit-task").onclick=()=>taskModal(task);
      $("#detail-delete-task").onclick=()=>deleteTask(task);
      $$("[data-check]").forEach(input=>input.onchange=async()=>{await api(`/tasks/${id}/checklist/${input.dataset.check}`,{method:"PATCH",body:JSON.stringify({is_done:input.checked})});taskDetail(id)});
      $$("[data-delete-check]").forEach(button=>button.onclick=async()=>{if(!confirm("Delete this checklist item?"))return;await api(`/tasks/${id}/checklist/${button.dataset.deleteCheck}`,{method:"DELETE"});taskDetail(id)});
      $("#checklist-form").onsubmit=async e=>{e.preventDefault();const input=$("input",e.target);await api(`/tasks/${id}/checklist`,{method:"POST",body:JSON.stringify({text:input.value})});taskDetail(id)};
      $("#comment-form").onsubmit=async e=>{e.preventDefault();const input=$("input",e.target);await api(`/tasks/${id}/comments`,{method:"POST",body:JSON.stringify({body:input.value})});closeModal();taskDetail(id);toast("Comment added")};
    });
}
async function deleteTask(task){
  if(!confirm(`Delete "${task.title}" permanently?`))return;
  try{await api(`/tasks/${task.id}`,{method:"DELETE"});closeModal();await loadWorkspace();render();toast("Task deleted")}
  catch(err){toast(err.message,true)}
}
async function memberModal(){
  try{
    const availableUsers=await api(`/workspaces/${state.workspace.id}/available-users`);
    if(!availableUsers.length){toast("All registered users are already workspace members",true);return}
    modal(formShell("Add a member","Choose an existing Orbit account that has not been added yet.",`${selectField("email","Available account",availableUsers.map(user=>[user.email,`${user.name} — ${user.email}`]))}${selectField("role","Workspace role",["member","admin"],"member")}`,"Add member"),()=>$("#modal-form").onsubmit=async e=>submitForm(e,async data=>{const member=await api(`/workspaces/${state.workspace.id}/members`,{method:"POST",body:JSON.stringify(data)});state.members.push(member);toast("Member added")}));
  }catch(err){toast(err.message,true)}
}
function teamModal(team=null){
  if(!state.members.length||!state.designations.length){toast("Add workspace members and designations before creating a team",true);return}
  modal(formShell(team?"Edit team":"Create a team",team?"Update the team, manager and purpose.":"Every team requires a designated manager.",`${field("name","Team name","text","e.g. Design",true,false,team?.name)}${field("description","Description","textarea","What does this team own?",false,true,team?.description)}${selectField("manager_user_id","Team manager",state.members.map(member=>[member.user_id,member.user.name]),team?.manager_user_id||state.user.id)}${selectField("manager_designation","Manager designation",state.designations.map(item=>[item.name,item.name]),team?.manager_designation||"")}`,team?"Save changes":"Create team"),()=>$("#modal-form").onsubmit=async e=>submitForm(e,async data=>{data.manager_user_id=Number(data.manager_user_id);const saved=await api(team?`/workspaces/${state.workspace.id}/teams/${team.id}`:`/workspaces/${state.workspace.id}/teams`,{method:team?"PATCH":"POST",body:JSON.stringify(data)});if(team)state.teams=state.teams.map(item=>item.id===saved.id?saved:item);else state.teams.unshift(saved);toast(team?"Team updated":"Team created")}));
}
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
    <div class="field full ai-note"><strong>Safe preview</strong><span>AI generates a draft only. No board data changes until you confirm the selected tasks.</span></div>
    <div id="ai-plan-status" class="ai-plan-status hidden" role="status" aria-live="polite"><i></i><span>Contacting AI providers and building your task plan...</span></div>`,
    "Generate task plan"),()=>{
      const form=$("#modal-form");
      const maximum=$('[name="maximum_tasks"]',form);
      const button=$("button.primary",form);
      maximum.min="1";maximum.max="15";
      button.type="button";
      button.onclick=async()=>{
        if(!form.reportValidity())return;
        const error=$("#modal-error"),status=$("#ai-plan-status");
        error.classList.add("hidden");status.classList.remove("hidden");
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
          status.classList.add("hidden");button.disabled=false;button.textContent="Generate task plan";
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
      <div id="ai-create-status" class="ai-plan-status hidden" role="status" aria-live="polite"><i></i><span>Creating selected tasks and placing them in Backlog...</span></div>
      <div id="modal-error" class="form-error hidden"></div>
      <div class="modal-actions"><button type="button" id="back-to-ai-prompt" class="btn">Back</button><button type="button" class="btn" onclick="document.querySelector('#modal-close').click()">Cancel</button><button type="button" id="create-ai-tasks" class="btn primary">Create selected tasks</button></div>
    </form>`,()=>{
      $("#back-to-ai-prompt").onclick=aiTaskPlannerModal;
      $("#create-ai-tasks").onclick=async()=>{
        const form=$("#ai-confirm-form"),button=$("#create-ai-tasks"),error=$("#modal-error"),status=$("#ai-create-status");
        const tasks=$$("[data-ai-task]",form)
          .filter(row=>$(".ai-task-enabled",row).checked)
          .map(row=>({
            title:$(".ai-task-title",row).value.trim(),
            description:$(".ai-task-description",row).value.trim()||null,
            priority:$(".ai-task-priority",row).value,
            story_points:$(".ai-task-points",row).value===""?null:Number($(".ai-task-points",row).value)
          }));
        if(!tasks.length){error.textContent="Select at least one task.";error.classList.remove("hidden");return}
        if(tasks.some(task=>task.title.length<2)){error.textContent="Every selected task needs a title.";error.classList.remove("hidden");return}
        error.classList.add("hidden");status.classList.remove("hidden");
        button.disabled=true;button.textContent="Creating tasks...";
        try{
          await api(`/projects/${state.project.id}/ai/task-plan/confirm`,{method:"POST",body:JSON.stringify({tasks})});
          status.querySelector("span").textContent=`Created ${tasks.length} task${tasks.length===1?"":"s"}. Refreshing the board...`;
          await loadWorkspace();closeModal();toast(`${tasks.length} AI-planned task${tasks.length===1?"":"s"} created in Backlog`);
        }catch(err){error.textContent=err.message;error.classList.remove("hidden");status.classList.add("hidden");button.disabled=false;button.textContent="Create selected tasks"}
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
function progressField(value=0){
  const progress=Math.max(0,Math.min(100,Number(value)||0));
  return `<label class="field full progress-field"><span class="progress-label"><span>Progress</span><output id="task-progress-value" for="task-progress">${progress}%</output></span><input id="task-progress" name="progress" type="range" min="0" max="100" step="5" value="${progress}" style="--progress:${progress}%"><span class="progress-scale"><span>0%</span><span>50%</span><span>100%</span></span></label>`;
}
function formShell(title,subtitle,fields,submit,extra=""){return `<h2>${title}</h2><p class="subtitle">${subtitle}</p><form id="modal-form"><div class="form-grid">${fields}</div><div id="modal-error" class="form-error hidden"></div><div class="modal-actions">${extra}<button type="button" class="btn" onclick="document.querySelector('#modal-close').click()">Cancel</button><button class="btn primary">${submit}</button></div></form>`}

function peopleView() {
  const admin=isAdmin();
  const action=admin?`<button id="add-member" class="btn primary">＋ Add member</button>`:`<span class="readonly-pill">View only</span>`;
  return `${pageHeading("People & teams","Allocate members to a team and a specific project.",action)}
  <div class="people-grid"><section class="panel"><div class="panel-header"><h3>Workspace members</h3><span class="member-count">${state.members.length}</span></div>
    ${state.members.map(m=>{const projectCount=new Set(state.teamMembers.filter(a=>a.user_id===m.user_id).map(a=>a.project_id)).size;return `<div class="member-row"><button class="member-profile-trigger" data-member-details="${m.user_id}" aria-label="View ${esc(m.user.name)}'s project assignments"><b class="avatar">${esc(m.user.name.slice(0,2).toUpperCase())}</b><span class="member-copy"><strong>${esc(m.user.name)}</strong><small>${esc(m.user.email)}</small><span class="member-professional">${esc([m.professional_title,m.department].filter(Boolean).join(" · ")||"Professional details not set")}</span><span class="project-count">${projectCount} project${projectCount===1?"":"s"}</span></span></button><span class="badge ${m.role}">${m.role}</span>${admin?`<button class="edit-action member-edit-action" data-edit-member-profile="${m.id}">Edit details</button>`:""}${admin&&m.user_id!==state.user.id?`<button class="remove-action" data-remove-member="${m.id}">Remove</button>`:""}</div>`}).join("")}
  </section><section class="panel"><div class="panel-header"><h3>Teams</h3>${admin?'<button id="new-team">＋ New team</button>':`<span class="member-count">${state.teams.length}</span>`}</div>
    ${state.teams.length?state.teams.map(t=>{const allocations=state.teamMembers.filter(item=>item.team_id===t.id);return `<article class="team-card"><div class="team-card-head"><div><h4>${esc(t.name)}</h4><p>${esc(t.description||"No description")}</p>${t.manager_user?`<div class="team-manager"><b class="avatar">${esc(t.manager_user.name.slice(0,2).toUpperCase())}</b><span><small>TEAM MANAGER</small><strong>${esc(t.manager_user.name)}</strong><em>${esc(t.manager_designation)}</em></span></div>`:`<span class="manager-missing">Manager not assigned · use Edit</span>`}</div>${admin?`<div class="team-actions"><button data-allocate-team="${t.id}">＋ Allocate</button><button class="edit-action" data-edit-team="${t.id}">✎ Edit</button><button class="remove-action" data-delete-team="${t.id}">Delete</button></div>`:""}</div><div class="team-member-list">${allocations.length?allocations.map(a=>`<div class="team-member-row"><b class="avatar">${esc(a.user.name.slice(0,2).toUpperCase())}</b><div><strong>${esc(a.user.name)}</strong><small>${esc(a.designation)} · ${esc(a.project.name)}</small></div>${admin?`<button class="remove-action" data-remove-allocation="${a.id}" data-team-id="${t.id}">Remove</button>`:""}</div>`).join(""):'<p class="team-empty">No allocated members yet.</p>'}</div></article>`}).join(""):emptyMini("No teams yet","Create a team for a focused group.")}
  </section><section class="panel designation-panel"><div class="panel-header"><h3>Designations</h3>${admin?'<button id="new-designation">＋ Add designation</button>':`<span class="member-count">${state.designations.length}</span>`}</div><div class="designation-list">${state.designations.length?state.designations.map(item=>`<div class="designation-row"><div><strong>${esc(item.name)}</strong><small>${esc(item.description||"No description")}</small></div>${admin?`<div><button data-edit-designation="${item.id}">Edit</button><button class="remove-action" data-delete-designation="${item.id}">Delete</button></div>`:""}</div>`).join(""):emptyMini("No designations yet","Add job roles before allocating team members.")}</div></section><section class="panel designation-panel"><div class="panel-header"><h3>Departments</h3>${admin?'<button id="new-department">＋ Add department</button>':`<span class="member-count">${state.departments.length}</span>`}</div><div class="designation-list">${state.departments.length?state.departments.map(item=>`<div class="designation-row"><div><strong>${esc(item.name)}</strong><small>${esc(item.description||"No description")}</small></div>${admin?`<div><button data-edit-department="${item.id}">Edit</button><button class="remove-action" data-delete-department="${item.id}">Delete</button></div>`:""}</div>`).join(""):emptyMini("No departments yet","Add departments such as IT, Management, Accounts or Marketing.")}</div></section></div>`;
}

function memberDetailsModal(userId){
  const member=state.members.find(m=>m.user_id===userId);
  if(!member)return;
  const assignments=state.teamMembers.filter(a=>a.user_id===userId);
  const projectCount=new Set(assignments.map(a=>a.project_id)).size;
  const assignmentRows=assignments.length?assignments.map(a=>{
    const team=state.teams.find(t=>t.id===a.team_id);
    return `<div class="member-assignment"><div><strong>${esc(a.project.name)}</strong><small>${esc(team?.name||"Team")}</small></div><span>${esc(a.designation)}</span></div>`;
  }).join(""):`<div class="member-assignments-empty"><strong>No project assignments yet</strong><p>This member has not been allocated to a team and project.</p></div>`;
  modal(`<div class="member-detail-head"><b class="avatar">${esc(member.user.name.slice(0,2).toUpperCase())}</b><div><h2>${esc(member.user.name)}</h2><p>${esc(member.user.email)}</p></div></div><div class="member-detail-summary"><div><strong>${projectCount}</strong><span>Project${projectCount===1?"":"s"}</span></div><div><strong>${assignments.length}</strong><span>Assignment${assignments.length===1?"":"s"}</span></div><div><strong>${pretty(member.role)}</strong><span>Workspace role</span></div></div><h3 class="member-assignment-title">Project designations</h3><div class="member-assignment-list">${assignmentRows}</div>`);
}

function memberProfessionalModal(member){
  if(!member)return;
  modal(formShell("Edit member details",`Set ${esc(member.user.name)}'s professional title and department.`,`${selectField("professional_title","Professional title · Designation",state.designations.map(item=>[item.name,item.name]),member.professional_title,"Select designation")}${selectField("department","Department",state.departments.map(item=>[item.name,item.name]),member.department,"Select department")}`,"Save details"),()=>$("#modal-form").onsubmit=async event=>submitForm(event,async data=>{
    const updated=await api(`/workspaces/${state.workspace.id}/members/${member.id}/professional-profile`,{method:"PATCH",body:JSON.stringify(data)});
    state.members=state.members.map(item=>item.id===updated.id?updated:item);
    state.userDirectory=state.userDirectory.map(user=>user.user_id===updated.user_id?{...user,professional_title:updated.professional_title,department:updated.department}:user);
    if(updated.user_id===state.user.id&&state.profile){state.profile.professional_title=updated.professional_title;state.profile.department=updated.department}
    toast("Member professional details updated");
  }));
}

function teamAllocationModal(teamId){
  const eligible=state.members;
  if(!eligible.length||!state.projects.length){toast("Add a member and create a project first",true);return}
  if(!state.designations.length){toast("Add a designation before allocating members",true);designationModal();return}
  modal(formShell("Allocate team member","Choose their project and designation.",`${selectField("user_id","Member",eligible.map(m=>[m.user_id,m.user.name]))}${selectField("project_id","Project",state.projects.map(p=>[p.id,p.name]))}${selectField("designation","Designation",state.designations.map(item=>[item.name,item.name]))}`,"Allocate member"),()=>$("#modal-form").onsubmit=async e=>submitForm(e,async data=>{
    data.user_id=Number(data.user_id);data.project_id=Number(data.project_id);
    const allocation=await api(`/workspaces/${state.workspace.id}/teams/${teamId}/members`,{method:"POST",body:JSON.stringify(data)});state.teamMembers.push(allocation);toast("Member allocated to project");
  }));
}

function designationModal(designation=null){
  modal(formShell(designation?"Edit designation":"Add designation",designation?"Update this role across existing team allocations.":"Create a reusable professional role for team allocation.",`${field("name","Designation name","text","e.g. Mobile Developer",true,false,designation?.name)}${field("description","Description","textarea","Responsibilities or specialty",false,true,designation?.description)}`,designation?"Save changes":"Add designation"),()=>$("#modal-form").onsubmit=async event=>submitForm(event,async data=>{
    const saved=await api(designation?`/workspaces/${state.workspace.id}/designations/${designation.id}`:`/workspaces/${state.workspace.id}/designations`,{method:designation?"PATCH":"POST",body:JSON.stringify(data)});
    if(designation){state.designations=state.designations.map(item=>item.id===saved.id?saved:item);state.teamMembers.forEach(allocation=>{if(allocation.designation===designation.name)allocation.designation=saved.name})}else state.designations.push(saved);
    state.designations.sort((a,b)=>a.name.localeCompare(b.name));toast(designation?"Designation updated":"Designation added");
  }));
}

function departmentModal(department=null){
  modal(formShell(department?"Edit department":"Add department",department?"Update this department for workspace profiles.":"Create a reusable department for professional profiles.",`${field("name","Department name","text","e.g. IT, Management, Accounts",true,false,department?.name)}${field("description","Description","textarea","What does this department handle?",false,true,department?.description)}`,department?"Save changes":"Add department"),()=>$("#modal-form").onsubmit=async event=>submitForm(event,async data=>{
    const saved=await api(department?`/workspaces/${state.workspace.id}/departments/${department.id}`:`/workspaces/${state.workspace.id}/departments`,{method:department?"PATCH":"POST",body:JSON.stringify(data)});
    if(department){state.departments=state.departments.map(item=>item.id===saved.id?saved:item);if(state.profile?.department===department.name)state.profile.department=saved.name}else state.departments.push(saved);
    state.departments.sort((a,b)=>a.name.localeCompare(b.name));toast(department?"Department updated":"Department added");
  }));
}

function bindAccessControls(){
  $$('[data-member-details]').forEach(button=>button.onclick=()=>memberDetailsModal(Number(button.dataset.memberDetails)));
  if(!isAdmin())return;
  $$("[data-edit-member-profile]").forEach(button=>button.onclick=()=>memberProfessionalModal(state.members.find(member=>member.id===Number(button.dataset.editMemberProfile))));
  $("#new-designation")?.addEventListener("click",()=>designationModal());
  $$("[data-edit-designation]").forEach(button=>button.onclick=()=>designationModal(state.designations.find(item=>item.id===Number(button.dataset.editDesignation))));
  $$("[data-delete-designation]").forEach(button=>button.onclick=async()=>{if(!confirm("Delete this designation option? Existing allocation records will keep their current designation."))return;try{const id=Number(button.dataset.deleteDesignation);await api(`/workspaces/${state.workspace.id}/designations/${id}`,{method:"DELETE"});state.designations=state.designations.filter(item=>item.id!==id);render();toast("Designation deleted")}catch(err){toast(err.message,true)}});
  $("#new-department")?.addEventListener("click",()=>departmentModal());
  $$("[data-edit-department]").forEach(button=>button.onclick=()=>departmentModal(state.departments.find(item=>item.id===Number(button.dataset.editDepartment))));
  $$("[data-delete-department]").forEach(button=>button.onclick=async()=>{if(!confirm("Delete this department option? Existing profile history will be preserved."))return;try{const id=Number(button.dataset.deleteDepartment);await api(`/workspaces/${state.workspace.id}/departments/${id}`,{method:"DELETE"});state.departments=state.departments.filter(item=>item.id!==id);render();toast("Department deleted")}catch(err){toast(err.message,true)}});
  $$("[data-allocate-team]").forEach(button=>button.onclick=()=>teamAllocationModal(Number(button.dataset.allocateTeam)));
  $$("[data-edit-team]").forEach(button=>button.onclick=()=>teamModal(state.teams.find(team=>team.id===Number(button.dataset.editTeam))));
  $$("[data-delete-team]").forEach(button=>button.onclick=async()=>{if(!confirm("Delete this team and its allocations?"))return;try{const teamId=Number(button.dataset.deleteTeam);await api(`/workspaces/${state.workspace.id}/teams/${teamId}`,{method:"DELETE"});state.teams=state.teams.filter(t=>t.id!==teamId);state.teamMembers=state.teamMembers.filter(a=>a.team_id!==teamId);render();toast("Team deleted")}catch(err){toast(err.message,true)}});
  $$("[data-remove-allocation]").forEach(button=>button.onclick=async()=>{if(!confirm("Remove this member from the project team?"))return;try{const allocationId=Number(button.dataset.removeAllocation);await api(`/workspaces/${state.workspace.id}/teams/${button.dataset.teamId}/members/${allocationId}`,{method:"DELETE"});state.teamMembers=state.teamMembers.filter(a=>a.id!==allocationId);render();toast("Team member removed")}catch(err){toast(err.message,true)}});
  $$("[data-remove-member]").forEach(button=>button.onclick=async()=>{if(!confirm("Remove this member from the workspace and all teams?"))return;try{const memberId=Number(button.dataset.removeMember),member=state.members.find(m=>m.id===memberId);await api(`/workspaces/${state.workspace.id}/members/${memberId}`,{method:"DELETE"});state.members=state.members.filter(m=>m.id!==memberId);if(member)state.teamMembers=state.teamMembers.filter(a=>a.user_id!==member.user_id);render();toast("Workspace member removed")}catch(err){toast(err.message,true)}});
}
async function submitForm(event, action) {
  event.preventDefault(); const button=$('button[type="submit"],button.primary',event.target), error=$("#modal-error"); button.disabled=true;
  try { await action(formData(event.target)); closeModal(); render(); } catch(err) { error.textContent=err.message;error.classList.remove("hidden");button.disabled=false; }
}
if (state.token) boot(); else showAuth();

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const state = {
  token: localStorage.getItem("orbit_token"), profile: null,
  user: null, workspaces: [], workspace: null, projects: [], project: null, chatConversations: [], chatOptions: null, chatMessages: [], activeChatId: null, chatFilter: "all", chatQuery: "",
  tasks: [], sprints: [], members: [], teams: [], teamMembers: [], designations: [], departments: [], userDirectory: [], filteredUserDirectory: [], userDirectoryPage: 1, skillCatalog: [], skillMembers: [], selectedProfileUsers: new Set(), notifications: [], notificationUnread: 0, notificationCritical: 0, dashboard: null, board: null, report: null, projectLoading: false, view: "dashboard"
};
const VIEW_PATHS = {
  dashboard: "/app/overview",
  projects: "/app/projects",
  board: "/app/board",
  gantt: "/app/gantt",
  report: "/app/report",
  people: "/app/people",
  profile: "/app/profile",
  skills: "/app/skills",
  users: "/app/users",
  notifications: "/app/notifications",
  chat: "/app/messages"
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
function designationChoices(){return state.designations.map(item=>[item.name,`${item.department_name||"Unassigned"} · ${item.name}`])}
function avatar(user, className="avatar"){const name=user?.name||"User",photo=user?.profile_image;return `<b class="${className}${photo?" has-photo":""}"${photo?` style="background-image:url('${esc(photo)}')"`:""}>${photo?"":esc(name.slice(0,2).toUpperCase())}</b>`}
function hydrateAvatars(){const users=[...state.members.map(item=>item.user),...state.userDirectory,...state.skillMembers,state.user?{...state.user,profile_image:state.profile?.profile_image}:null].filter(Boolean);$$('.avatar').forEach(element=>{if(element.classList.contains('has-photo'))return;const context=element.parentElement?.textContent||"";const matches=users.filter(user=>user.profile_image&&user.email&&context.includes(user.email));if(matches.length!==1)return;const user=matches[0];element.textContent="";element.style.backgroundImage=`url("${user.profile_image}")`;element.classList.add('has-photo')})}
function isAdmin() { return Boolean(state.user?.is_system_admin); }
function profileOnboardingRequired(){const ignored=new Set(["Designation","Department"]);return (state.profile?.missing_fields||[]).some(field=>!ignored.has(field))}
const NO_WORKSPACE_ALLOWED_VIEWS=new Set(["notifications","chat","profile"]);
function noWorkspaceMemberRestricted(view=state.view){return Boolean(state.user&&!state.user.is_system_admin&&!state.workspace&&!NO_WORKSPACE_ALLOWED_VIEWS.has(view))}
function updateSidebarAccess(){
  const hideWorkspaceViews=Boolean(state.user&&!state.user.is_system_admin&&!state.workspace);
  $$("#main-nav [data-view]").forEach(button=>{
    if(["dashboard","projects","board","gantt","report"].includes(button.dataset.view))button.classList.toggle("hidden",hideWorkspaceViews);
  });
}
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
  const el = $("#toast"); el.textContent = message; el.className = `toast show ${error ? "error" : "success"}`;
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
function confirmAction({title, message, confirmLabel="Confirm", confirmationText=""}, onConfirm, onCancel) {
  modal(`<h2>${esc(title)}</h2><p class="subtitle">${esc(message)}</p>
    <div class="confirm-warning"><strong>This action cannot be undone.</strong>${confirmationText?`<span>Type <b>${esc(confirmationText)}</b> to continue.</span>`:""}</div>
    ${confirmationText?`<label class="field">Confirmation<input id="confirm-action-input" autocomplete="off" placeholder="${esc(confirmationText)}"></label>`:""}
    <div id="modal-error" class="form-error hidden"></div><div class="modal-actions"><button id="confirm-action-cancel" type="button" class="btn">Cancel</button><button id="confirm-action-submit" type="button" class="btn danger" disabled>${esc(confirmLabel)}</button></div>`,()=>{
      const input=$("#confirm-action-input"),submit=$("#confirm-action-submit");
      if(!input)submit.disabled=false;
      else input.oninput=()=>submit.disabled=input.value!==confirmationText;
      $("#confirm-action-cancel").onclick=()=>{closeModal();onCancel?.()};
      submit.onclick=async()=>{submit.disabled=true;submit.textContent="Deleting…";try{await onConfirm()}catch(error){submit.disabled=false;submit.textContent=confirmLabel;const target=$("#modal-error");target.textContent=error.message;target.classList.remove("hidden")}};
    });
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
function clearFieldErrors(form){$$('.field-error',form).forEach(item=>item.remove());$$('.input-invalid',form).forEach(input=>input.classList.remove('input-invalid'))}
function fieldError(input,message){if(!input)return;input.classList.add('input-invalid');const error=document.createElement('small');error.className='field-error';error.textContent=message;(input.closest('.password-field')||input).insertAdjacentElement('afterend',error)}
function validEmail(input){return input.validity.valid&&input.value.trim().length>0}
function validateAuthForm(form,isRegistration=false){clearFieldErrors(form);let valid=true;const name=isRegistration?$('#register-name'):null,email=isRegistration?$('#register-email'):$('#login-email'),password=isRegistration?$('#register-password'):$('#login-password');if(name&&name.value.trim().length<2){fieldError(name,'Full name must contain at least 2 characters.');valid=false}if(!validEmail(email)){fieldError(email,'Enter a valid email address.');valid=false}if(password.value.length<8){fieldError(password,'Password must contain at least 8 characters.');valid=false}else if(password.value.length>128){fieldError(password,'Password must not exceed 128 characters.');valid=false}return valid}
$$('#login-form input,#register-form input').forEach(input=>input.addEventListener('input',()=>{input.classList.remove('input-invalid');const label=input.closest('label');label?.querySelectorAll('.field-error').forEach(error=>error.remove())}));
$("#login-form").onsubmit = async e => {
  e.preventDefault();
  if(!validateAuthForm(e.currentTarget))return;
  $("#auth-error").classList.add("hidden");
  const submitButton = $('button[type="submit"]', e.currentTarget);
  submitButton.disabled = true;
  submitButton.textContent = "Signing in…";
  const body = new URLSearchParams({username: $("#login-email").value, password: $("#login-password").value});
  try {
    const data = await api("/auth/login", {method:"POST", body, headers:{"Content-Type":"application/x-www-form-urlencoded"}});
    state.token = data.access_token; localStorage.setItem("orbit_token", state.token); await boot();
  } catch (err) {
    if(/incorrect email or password/i.test(err.message))fieldError($("#login-password"),err.message);else authError(err.message);
  } finally {
    submitButton.disabled = false;
    submitButton.innerHTML = "Sign in <span>→</span>";
  }
};
$("#register-form").onsubmit = async e => {
  e.preventDefault();
  if(!validateAuthForm(e.currentTarget,true))return;
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
  } catch (err) { if(/email is already registered/i.test(err.message))fieldError($("#register-email"),err.message);else authError(err.message); }
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
$("#header-logout-button").onclick = () => logout();
$("#header-profile-button").onclick = () => {$("#header-account-menu").classList.add("hidden");navigate("profile")};
$("#header-account-button").onclick = event => {event.stopPropagation();const menu=$("#header-account-menu"),hidden=menu.classList.toggle("hidden");$("#header-account-button").setAttribute("aria-expanded",String(!hidden))};
document.addEventListener("click",event=>{if(!event.target.closest(".header-account")){$("#header-account-menu").classList.add("hidden");$("#header-account-button").setAttribute("aria-expanded","false")}});


function profileFallback() {
  return {
    name: state.user?.name || "", email: state.user?.email || "", profile_image: null,
    phone: null, location: null, bio: null, professional_title: null,
    department: null, years_experience: null, skills: null, achievements: null,
    project_count: 0, projects: []
  };
}
function syncUserChrome(){
  const name=state.profile?.name||state.user?.name||"User",email=state.profile?.email||state.user?.email||"",designation=[state.profile?.professional_title,state.profile?.department].filter(Boolean).join(" · ")||"Designation not assigned",photo=state.profile?.profile_image;
  [["#user-name",name],["#user-email",email],["#user-designation",designation],["#header-user-name",name],["#header-user-email",email],["#header-user-designation",designation]].forEach(([selector,value])=>{const element=$(selector);if(element)element.textContent=value});
  ["#user-avatar","#header-user-avatar"].forEach(selector=>{const avatar=$(selector);if(!avatar)return;avatar.textContent=photo?"":name.slice(0,2).toUpperCase();avatar.style.backgroundImage=photo?`url("${photo}")`:"";avatar.classList.toggle("has-photo",Boolean(photo))});
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
    [state.workspaces,state.profile,state.skillCatalog] = await Promise.all([
      api("/workspaces"),
      api("/auth/profile").catch(err => {
        console.error("Profile loading failed", err);
        return profileFallback();
      }),
      api("/auth/skill-catalog").catch(err=>{console.error("Skill catalog loading failed",err);return []})
    ]);
    const savedId = Number(localStorage.getItem("orbit_workspace"));
    state.workspace = state.workspaces.find(w => w.id === savedId) || state.workspaces[0] || null;
    if(profileOnboardingRequired()){state.view="profile";history.replaceState({view:"profile"},"",VIEW_PATHS.profile)}
    else if(noWorkspaceMemberRestricted()){state.view="profile";history.replaceState({view:"profile"},"",VIEW_PATHS.profile)}
    syncUserChrome();
    $("#auth-error").classList.add("hidden");
    $("#auth-screen").classList.add("hidden"); $("#app-shell").classList.remove("hidden");
    if (!PATH_VIEWS[window.location.pathname]) {
      history.replaceState({view:state.view}, "", VIEW_PATHS[state.view]);
    }
    updateWorkspaceUI();
    updateSidebarAccess();
    $("#admin-users-nav").classList.toggle("hidden",!isAdmin());
    $("#admin-skills-nav").classList.toggle("hidden",!isAdmin());
    $("#admin-people-nav").classList.toggle("hidden",!isAdmin());
    await loadNotifications();startNotificationPolling();
    $("#boot-screen").classList.add("hidden");
    if(state.view==="profile") {
      render();
    } else if (!state.workspace) {
      state.chatConversations=[];state.chatOptions=null;state.chatMessages=[];state.activeChatId=null;updateChatCount();
      await loadNoWorkspaceMIS();
      if(["people","users","skills","notifications","chat"].includes(state.view))render();else renderNoWorkspace();
    } else if(state.view==="chat") {
      state.chatOptions=await api(`/workspaces/${state.workspace.id}/chat/options`);
      await loadChats();
    } else { await loadWorkspace(); }
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
    (state.workspace&&state.user?.is_system_admin ? `<button class="workspace-settings" data-workspace-settings="true">⚙ Workspace settings</button>` : "") +
    (state.user?.is_system_admin?`<button class="new-workspace" data-new="true">＋ Create workspace</button>`:"");
  $$("[data-id]", $("#workspace-menu")).forEach(btn => btn.onclick = async () => {
    const nextWorkspace=state.workspaces.find(w=>w.id===Number(btn.dataset.id));
    if(!nextWorkspace||nextWorkspace.id===state.workspace?.id){$("#workspace-menu").classList.add("hidden");return}
    state.workspace=nextWorkspace;state.project=null;state.projects=[];state.tasks=[];state.sprints=[];state.board=null;state.dashboard=null;state.members=[];state.teams=[];state.teamMembers=[];state.chatConversations=[];state.chatOptions=null;state.chatMessages=[];state.activeChatId=null;
    localStorage.setItem("orbit_workspace",state.workspace.id);
    $("#workspace-menu").classList.add("hidden"); updateWorkspaceUI();if(state.view==="chat"){state.chatOptions=await api(`/workspaces/${state.workspace.id}/chat/options`);await loadChats()}else await loadWorkspace();
  });
  $("[data-workspace-settings]", $("#workspace-menu"))?.addEventListener("click", workspaceSettingsModal);
  $("[data-new]", $("#workspace-menu"))?.addEventListener("click",workspaceModal);
}
function activeWorkspace() {
  if (state.workspace) return state.workspace;
  const savedId = Number(localStorage.getItem("orbit_workspace"));
  state.workspace = state.workspaces.find(w => w.id === savedId) || state.workspaces[0] || null;
  return state.workspace;
}
async function loadNotifications(renderPage=false){
  if(!state.token||!state.user)return;
  const data=await api("/notifications?limit=50");
  state.notifications=data.items;state.notificationUnread=data.unread_count;state.notificationCritical=data.critical_count;
  renderNotificationHeader();
  if(renderPage&&state.view==="notifications")render();
}
function renderNotificationHeader(){
  const count=$("#notification-count"),sidebarCount=$("#sidebar-notification-count"),menu=$("#notification-menu");if(!count||!menu)return;
  const messageUnread=state.chatConversations.reduce((sum,item)=>sum+item.unread_count,0),totalUnread=state.notificationUnread+messageUnread;
  count.textContent=totalUnread>99?"99+":totalUnread;count.classList.toggle("hidden",!totalUnread);
  if(sidebarCount){sidebarCount.textContent=state.notificationUnread>99?"99+":state.notificationUnread;sidebarCount.classList.toggle("hidden",!state.notificationUnread)}
  const recent=state.notifications.filter(item=>!item.is_resolved).slice(0,2),messages=state.chatConversations.filter(item=>item.unread_count).slice(0,3);
  menu.innerHTML=`<div class="notification-menu-head"><strong>Updates</strong><div>${state.notificationUnread?'<button type="button" data-mark-all-read>Mark notifications read</button>':""}</div></div><div class="notification-menu-section"><span>Notifications</span><button data-open-notifications>View all</button></div>${recent.length?recent.map(item=>`<button type="button" class="notification-preview ${item.severity} ${item.is_read?"":"unread"}" data-open-notification="${item.id}"><i></i><span><strong>${esc(item.title)}</strong><small>${esc(item.message)}</small></span></button>`).join(""):`<div class="notification-empty compact">No new notifications</div>`}<div class="notification-menu-section"><span>Messages</span><button data-open-chat-center>View all</button></div>${messages.length?messages.map(item=>`<button type="button" class="notification-preview message unread" data-open-chat="${item.id}"><i></i><span><strong>${esc(item.name)}</strong><small>${esc(item.last_message?.body||`${item.unread_count} unread message${item.unread_count===1?"":"s"}`)}</small></span><b>${item.unread_count}</b></button>`).join(""):`<div class="notification-empty compact">No unread messages</div>`}`;
  $$('[data-open-notifications]',menu).forEach(button=>button.onclick=()=>{menu.classList.add("hidden");navigate("notifications")});
  $('[data-open-chat-center]',menu)?.addEventListener('click',async()=>{menu.classList.add("hidden");navigate("chat");await loadChats()});
  $$('[data-open-chat]',menu).forEach(button=>button.onclick=async()=>{menu.classList.add("hidden");state.activeChatId=Number(button.dataset.openChat);navigate("chat");await loadChats()});
  $$('[data-open-notification]',menu).forEach(button=>button.onclick=async()=>{menu.classList.add("hidden");const item=state.notifications.find(entry=>String(entry.id)===button.dataset.openNotification);if(item?.conversation_id){const workspace=state.workspaces.find(entry=>entry.id===item.workspace_id);if(!workspace){navigate("notifications");return}if(state.workspace?.id!==workspace.id){state.workspace=workspace;localStorage.setItem("orbit_workspace",workspace.id);updateWorkspaceUI();await loadWorkspace()}state.activeChatId=item.conversation_id;await api(`/notifications/${item.id}/read`,{method:"PATCH"}).catch(()=>{});navigate("chat");await loadChats()}else navigate("notifications")});
  $('[data-mark-all-read]',menu)?.addEventListener('click',async event=>{
    event.stopPropagation();const button=event.currentTarget;button.disabled=true;button.textContent="Marking…";
    try{const result=await api("/notifications/read-all",{method:"PATCH"});await loadNotifications(state.view==="notifications");toast(`${result.marked_count} notification${result.marked_count===1?"":"s"} marked as read`)}
    catch(err){button.disabled=false;button.textContent="Mark all read";toast(err.message,true)}
  });
}
async function pollUpdates(){await loadNotifications(state.view==="notifications");if(state.workspace){const conversations=await api(`/workspaces/${state.workspace.id}/chat/conversations`);state.chatConversations=conversations;updateChatCount();renderNotificationHeader();if(state.view==="chat")await loadChats()}}
function startNotificationPolling(){clearInterval(startNotificationPolling.timer);startNotificationPolling.timer=setInterval(()=>pollUpdates().catch(()=>{}),15000)}
$("#notification-button").onclick=event=>{event.stopPropagation();const menu=$("#notification-menu"),hidden=menu.classList.toggle("hidden");$("#notification-button").setAttribute("aria-expanded",String(!hidden))};
document.addEventListener("click",event=>{if(!event.target.closest(".notification-center")){$("#notification-menu").classList.add("hidden");$("#notification-button").setAttribute("aria-expanded","false")}});
$("#workspace-button").onclick = () => $("#workspace-menu").classList.toggle("hidden");
document.addEventListener("click", e => { if (!e.target.closest(".workspace-picker")) $("#workspace-menu").classList.add("hidden"); });

async function loadWorkspace() {
  try {
    const workspace = activeWorkspace();
    if (!workspace) { renderNoWorkspace(); return; }
    const workspaceId=workspace.id;
    [state.projects,state.dashboard,state.members,state.chatConversations,state.chatOptions]=await Promise.all([
      api(`/workspaces/${workspaceId}/projects`),api(`/workspaces/${workspaceId}/dashboard`),api(`/workspaces/${workspaceId}/members`),
      api(`/workspaces/${workspaceId}/chat/conversations`),api(`/workspaces/${workspaceId}/chat/options`)
    ]);
    updateChatCount();renderNotificationHeader();
    if(state.workspace?.id!==workspaceId)return;
    const savedProjectId=Number(localStorage.getItem(`orbit_project_${workspace.id}`));
    state.project=state.projects.find(project=>project.id===savedProjectId)||state.projects[0]||null;
    render();
    const needsProject=["board","gantt","sprints","report"].includes(state.view);
    const [secondary]=await Promise.all([
      Promise.all([
        state.user?.is_system_admin?api("/admin/teams"):api(`/workspaces/${workspaceId}/teams`),state.user?.is_system_admin?api("/admin/team-members"):api(`/workspaces/${workspaceId}/team-members`),
        state.user?.is_system_admin?api("/admin/designations"):api(`/workspaces/${workspaceId}/designations`),state.user?.is_system_admin?api("/admin/departments"):api(`/workspaces/${workspaceId}/departments`),
        api(`/workspaces/${workspaceId}/skill-catalog`),
        isAdmin()?api("/admin/users"):Promise.resolve([]),
        isAdmin()?api("/admin/skills"):Promise.resolve([])
      ]),
      needsProject?loadProject():Promise.resolve()
    ]);
    if(state.workspace?.id!==workspaceId)return;
    [state.teams,state.teamMembers,state.designations,state.departments,state.skillCatalog,state.userDirectory,state.skillMembers]=secondary;
    render();
  } catch (err) { toast(err.message, true); }
}
async function loadNoWorkspaceMIS(){
  if(!state.user?.is_system_admin)return;
  [state.userDirectory,state.skillMembers,state.teams,state.teamMembers,state.designations,state.departments]=await Promise.all([api("/admin/users"),api("/admin/skills"),api("/admin/teams"),api("/admin/team-members"),api("/admin/designations"),api("/admin/departments")]);
  state.skillCatalog=[...new Set(state.skillMembers.flatMap(member=>member.skills))].sort((a,b)=>a.localeCompare(b));
}
async function loadProject() {
  if (!state.project) { state.tasks=[]; state.sprints=[]; state.board=null; state.report=null; state.projectLoading=false; return; }
  const projectId=state.project.id;
  state.projectLoading=true;state.board=null;state.report=null;state.tasks=[];state.sprints=[];
  if(["board","gantt","sprints","report"].includes(state.view))render();
  try {
    const [board,tasks,report]=await Promise.all([
      api(`/projects/${projectId}/board`),
      api(`/projects/${projectId}/tasks`),
      state.view === "report" ? api(`/projects/${projectId}/report`) : Promise.resolve(null),
    ]);
    if(state.project?.id!==projectId)return;
    state.board=board;state.tasks=tasks;if(report)state.report=report;
    state.sprints=board.framework==="scrum"?await api(`/projects/${projectId}/sprints`):[];
    if(state.project?.id!==projectId)return;
    if (state.view === "sprints" && state.board.framework !== "scrum") {
      state.view = "board";
      history.replaceState({view:"board"}, "", VIEW_PATHS.board);
    }
  } catch (error) {
    state.projectLoading=false;
    throw error;
  }
  state.projectLoading=false;
}
async function refresh() { if (state.workspace) await loadWorkspace(); }
$("#refresh-button").onclick = refresh;
$("#quick-task").onclick = () => state.project ? taskModal() : toast("Create a project first", true);
if(localStorage.getItem("orbit_sidebar_collapsed")==="true")$("#app-shell").classList.add("sidebar-collapsed");
$("#mobile-menu").onclick = () => {if(window.innerWidth>1000){const collapsed=$("#app-shell").classList.toggle("sidebar-collapsed");localStorage.setItem("orbit_sidebar_collapsed",String(collapsed))}else $(".sidebar").classList.toggle("open")};
$("#main-nav").onclick = async e => {
  const btn = e.target.closest("[data-view]"); if (!btn) return;
  const openedView=navigate(btn.dataset.view);
  if(openedView!==btn.dataset.view)return;
  if(btn.dataset.view==="chat"){try{state.workspaces=await api("/workspaces");const savedId=Number(localStorage.getItem("orbit_workspace"));state.workspace=state.workspaces.find(item=>item.id===savedId)||state.workspaces[0]||null;updateWorkspaceUI();if(state.workspace){state.chatOptions=await api("/workspaces/"+state.workspace.id+"/chat/options");await loadChats()}else{state.chatConversations=[];state.chatMessages=[];state.activeChatId=null;render()}}catch(err){toast(err.message,true)}}
  if(["board","gantt","sprints","report"].includes(btn.dataset.view)&&state.project&&(!state.board||(btn.dataset.view==="report"&&!state.report))){
    try{await loadProject();render()}catch(err){state.projectLoading=false;toast(err.message,true)}
  }
};
function navigate(view, replace = false) {
  if(profileOnboardingRequired()&&view!=="profile"){toast("Complete your profile before continuing",true);view="profile";replace=true}
  else if(noWorkspaceMemberRestricted(view)){toast("No workspace is assigned. You can still use Messages, Notifications, and My profile.",true);view="profile";replace=true}
  closeModal();
  state.view = view;
  const path = VIEW_PATHS[view] || VIEW_PATHS.dashboard;
  if (window.location.pathname !== path) {
    history[replace ? "replaceState" : "pushState"]({view}, "", path);
  }
  $$("#main-nav button").forEach(button => button.classList.toggle("active", button.dataset.view === view));
  $(".sidebar").classList.remove("open");
  render();
  return view;
}
window.addEventListener("popstate", () => {
  closeModal();
  state.view = PATH_VIEWS[window.location.pathname] || "dashboard";
  if(profileOnboardingRequired()&&state.view!=="profile")state.view="profile";
  else if(noWorkspaceMemberRestricted())state.view="profile";
  if(window.location.pathname!==VIEW_PATHS[state.view])history.replaceState({view:state.view},"",VIEW_PATHS[state.view]);
  $$("#main-nav button").forEach(button => button.classList.toggle("active", button.dataset.view === state.view));
  render();
});
function render() {
  if(profileOnboardingRequired()&&state.view!=="profile"){
    state.view="profile";
    history.replaceState({view:"profile"},"",VIEW_PATHS.profile);
  }else if(noWorkspaceMemberRestricted()){
    state.view="profile";
    history.replaceState({view:"profile"},"",VIEW_PATHS.profile);
  }
  if(["people","users","skills"].includes(state.view)&&!isAdmin()){
    state.view="dashboard";
    history.replaceState({view:"dashboard"},"",VIEW_PATHS.dashboard);
  }
  const names = {dashboard:"Overview",projects:"Projects",board:"Task board",gantt:"Gantt chart",report:"Project report",people:"People & teams",profile:"My profile",skills:"Skills",users:"Users",notifications:"Notifications",chat:"Messages"};
  $("#page-title").textContent = names[state.view];
  $("#quick-task").classList.toggle("hidden", state.view !== "board" || !state.project || !canManageProject());
  $("#admin-users-nav").classList.toggle("hidden",!isAdmin());
  $("#admin-skills-nav").classList.toggle("hidden",!isAdmin());
  $("#admin-people-nav").classList.toggle("hidden",!isAdmin());
  updateSidebarAccess();
  const content=$("#content");
  content.innerHTML = ({dashboard:dashboardView,projects:projectsView,board:boardView,gantt:ganttView,report:reportView,people:peopleView,profile:profileView,skills:skillsView,users:usersView,notifications:notificationsView,chat:chatView}[state.view])();
  content.classList.remove("view-enter");void content.offsetWidth;content.classList.add("view-enter");
  $$(".stat-card,.project-card,.panel,.kanban-col,.sprint-row,.skill-member-card",content).forEach((item,index)=>item.style.setProperty("--enter-index",Math.min(index,10)));
  $$("#main-nav button").forEach(button => button.classList.toggle("active", button.dataset.view === state.view));
  bindView();
  document.body.classList.toggle("read-only", !canManageProject());
  document.body.classList.toggle("view-only", !canCollaborateProject());
  bindAccessControls();
  hydrateAvatars();
}
function pageHeading(title, text, action = "") {
  return `<div class="page-heading"><div><h1>${title}</h1><p>${text}</p></div>${action}</div>`;
}
function renderNoWorkspace() {
  const canCreate=Boolean(state.user?.is_system_admin);
  $("#content").innerHTML = canCreate?`${pageHeading("Welcome to Orbit", "Create your first workspace to get started.")}<div class="empty"><strong>Your work starts here</strong><p>A workspace keeps your projects, tasks, and team together.</p><button id="empty-workspace" class="btn primary">＋ Create workspace</button></div>`:`${pageHeading("No workspace found", "Your account is active, but you are not currently assigned to a workspace project or team.")}<div class="empty"><strong>No workspace access yet</strong><p>An administrator can add you to a workspace and allocate you to a team or project. You can still complete and maintain your profile.</p><button id="open-profile-without-workspace" class="btn primary">Open my profile</button></div>`;
  if(canCreate)$("#empty-workspace").onclick=workspaceModal;else $("#open-profile-without-workspace").onclick=()=>navigate("profile");
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
function notificationTime(value){const seconds=Math.max(0,(Date.now()-new Date(value).getTime())/1000);if(seconds<60)return"Just now";if(seconds<3600)return`${Math.floor(seconds/60)}m ago`;if(seconds<86400)return`${Math.floor(seconds/3600)}h ago`;return date(value)}
function notificationsView(){
  const active=state.notifications.filter(item=>!item.is_resolved),history=state.notifications.filter(item=>item.is_resolved);
  const rows=items=>items.map(item=>`<article class="notification-row ${item.severity} ${item.is_read?"":"unread"}"><span class="notification-status">${item.severity==="critical"?"!":"•"}</span><div><div class="notification-row-head"><strong>${esc(item.title)}</strong><time>${notificationTime(item.updated_at)}</time></div><p>${esc(item.message)}</p><small>${item.is_resolved?"Resolved":item.is_acknowledged?"Acknowledged":item.severity==="critical"?"Action required":"New message"}</small><div class="notification-actions">${item.task_id?`<button class="btn" data-notification-task="${item.id}">View task</button>`:""}${item.conversation_id?`<button class="btn" data-notification-chat="${item.id}">Open conversation</button>`:""}${!item.is_resolved&&!item.is_acknowledged&&item.severity==="critical"?`<button class="btn danger" data-notification-ack="${item.id}">OK, I understand</button>`:!item.is_read?`<button class="btn" data-notification-read="${item.id}">Mark as read</button>`:""}</div></div></article>`).join("");
  return `${pageHeading("Notifications","Deadline reminders and updates that need your attention.",`<button id="notification-refresh" class="btn">Refresh</button>`)}<div class="notification-summary"><div><strong>${state.notificationCritical}</strong><span>Critical actions</span></div><div><strong>${state.notificationUnread}</strong><span>New notifications</span></div></div><section class="notification-list"><h3>Active</h3>${active.length?rows(active):emptyMini("You’re all caught up","No active deadline alerts.")}${history.length?`<h3 class="notification-history-title">Recent history</h3>${rows(history.slice(0,20))}`:""}</section>`;
}
function updateChatCount(){const count=state.chatConversations.reduce((sum,item)=>sum+item.unread_count,0),badge=$("#sidebar-chat-count");if(badge){badge.textContent=count>99?"99+":count;badge.classList.toggle("hidden",!count)}}
async function loadChats(renderPage=true){
  if(!state.workspace)return;
  state.chatConversations=await api(`/workspaces/${state.workspace.id}/chat/conversations`);updateChatCount();renderNotificationHeader();
  if(state.activeChatId&&!state.chatConversations.some(item=>item.id===state.activeChatId))state.activeChatId=null;
  if(!state.activeChatId)state.activeChatId=state.chatConversations[0]?.id||null;
  if(state.activeChatId)state.chatMessages=await api(`/workspaces/${state.workspace.id}/chat/conversations/${state.activeChatId}/messages`);else state.chatMessages=[];
  const active=state.chatConversations.find(item=>item.id===state.activeChatId);if(active)active.unread_count=0;updateChatCount();
  if(renderPage&&state.view==="chat")render();
}
function chatIcon(type){return({broadcast:"!",project:"P",team:"T",direct:"@"})[type]||"#"}
function chatView(){
  if(!state.workspace){
    return `${pageHeading("Messages","Workspace announcements, project groups, team groups and permitted direct chats.")}<section class="chat-access-empty"><b>✉</b><h2>No workspace chat available</h2><p>${state.user?.is_system_admin?"Create a workspace before starting workspace conversations.":"You can use Messages after an administrator allocates you to a project or team."}</p>${state.user?.is_system_admin?'<button id="chat-create-workspace" class="btn primary">＋ Create workspace</button>':""}</section>`;
  }
  const active=state.chatConversations.find(item=>item.id===state.activeChatId),role=isAdmin()?"Administrator":state.chatOptions&&(state.chatOptions.projects.length||state.chatOptions.teams.length)?"Manager":"Member";
  const createAllowed=Boolean(state.workspace&&state.chatOptions&&(state.chatOptions.can_broadcast||state.chatOptions.projects.length||state.chatOptions.teams.length||state.chatOptions.recipients.length));
  const visible=state.chatConversations.filter(item=>(state.chatFilter==="all"||item.chat_type===state.chatFilter)&&(!state.chatQuery||`${item.name} ${item.last_message?.body||""}`.toLowerCase().includes(state.chatQuery.toLowerCase())));
  const conversations=visible.map(item=>`<div class="chat-conversation-wrap"><button class="chat-conversation ${item.id===state.activeChatId?"active":""}" data-chat-id="${item.id}"><span>${chatIcon(item.chat_type)}</span><div><strong>${esc(item.name)}</strong><small>${esc(item.last_message?.body||pretty(item.chat_type)+" conversation")}</small></div>${item.unread_count?`<b>${item.unread_count}</b>`:""}</button>${isAdmin()?`<button class="chat-admin-delete" data-delete-chat="${item.id}" title="Delete conversation">×</button>`:""}</div>`).join("");
  const messages=state.chatMessages.map(item=>{const mine=item.sender.id===state.user.id,canDelete=!item.is_deleted&&(mine||isAdmin());return `<div class="chat-message ${mine?"mine":""} ${item.is_deleted?"deleted":""}" data-message-id="${item.id}">${avatar(item.sender,"avatar")}<div><span><strong>${esc(item.sender.name)}</strong><time>${notificationTime(item.created_at)}</time>${canDelete?`<button class="chat-message-menu" data-delete-message="${item.id}" title="Message options">⋮</button>`:""}</span><p>${item.is_deleted?`<em>⊘ ${item.deleted_by_id===state.user.id?"You deleted this message":"This message was deleted"}</em>`:esc(item.body)}</p></div></div>`}).join("");
  return `${pageHeading("Messages",`${role} communication portal · ${esc(state.workspace.name)}`,createAllowed?'<button id="new-chat" class="btn primary">＋ New conversation</button>':"")}<div class="chat-role-banner"><b>${role[0]}</b><span><strong>${role} access</strong><small>${role==="Administrator"?"Monitor all communication, publish announcements, and manage every conversation.":role==="Manager"?"Create and access chats only for your assigned projects, teams, and members.":"Participate in assigned groups and privately message only your connected managers."}</small></span></div><section class="chat-shell"><aside class="chat-list"><div class="chat-list-head"><strong>Conversations</strong><button id="chat-refresh" title="Refresh">↻</button></div><div class="chat-list-tools"><input id="chat-search" value="${esc(state.chatQuery)}" placeholder="Search messages"><div>${[["all","All"],["broadcast","News"],["project","Projects"],["team","Teams"],["direct","Direct"]].map(([value,label])=>`<button data-chat-filter="${value}" class="${state.chatFilter===value?"active":""}">${label}</button>`).join("")}</div></div>${conversations||'<div class="chat-empty">No matching conversations.</div>'}</aside><div class="chat-room">${active?`<header><div><strong>${esc(active.name)}</strong><small>${pretty(active.chat_type)} chat · ${active.participants.length||"Scope-based"} ${active.participants.length===1?"participant":"participants"}</small></div>${isAdmin()?'<span class="chat-monitoring-label">Admin monitoring</span>':""}</header><div class="chat-message-stage"><div id="chat-messages" class="chat-messages">${messages||'<div class="chat-empty">Start the conversation.</div>'}</div>${state.chatMessages.length>8?'<div class="chat-scroll-controls"><button id="chat-scroll-top" title="Oldest messages">↑</button><button id="chat-scroll-bottom" title="Latest messages">↓</button></div>':""}</div>${active.can_send?`<form id="chat-form" class="chat-compose"><textarea id="chat-body" rows="2" maxlength="5000" placeholder="Write a message…" required></textarea><button class="btn primary">Send</button></form>`:'<div class="chat-readonly">Only administrators can post in this announcement channel.</div>'}`:`<div class="chat-placeholder"><strong>Select a conversation</strong><span>Your available chats will appear here.</span></div>`}</div></section>`;
}
async function newChatModal(){
  try{state.chatOptions=await api(`/workspaces/${state.workspace.id}/chat/options`)}catch(err){toast(err.message,true);return}
  const options=state.chatOptions,definitions=[
    ["broadcast","Announcement","Send an admin message to everyone","!",options.can_broadcast],
    ["direct","Direct message","Start a private permitted conversation","@",options.recipients.length>0],
    ["project","Project group","Chat with members of one project","P",options.projects.length>0],
    ["team","Team group","Chat with members of one team","T",options.teams.length>0]
  ],first=definitions.find(item=>item[4]);
  if(!first){toast("No conversations are available for your current allocations",true);return}
  modal(`<div class="chat-modal"><h2>New conversation</h2><p class="subtitle">Choose how you want to communicate. Access is controlled by workspace, project and team permissions.</p><form id="modal-form"><input type="hidden" name="chat_type" value="${first[0]}"><div class="chat-type-grid">${definitions.map(([value,label,help,icon,enabled])=>`<button type="button" class="chat-type-option ${value===first[0]?"active":""}" data-chat-type="${value}" ${enabled?"":`disabled title="No available ${value} targets"`}><b>${icon}</b><span><strong>${label}</strong><small>${help}</small></span>${enabled?"":'<i>Unavailable</i>'}</button>`).join("")}</div><div class="chat-create-fields"><label class="full"><span>Conversation name <small>(optional)</small></span><input name="name" maxlength="180" placeholder="Give this conversation a clear name"></label><label id="chat-target-field" class="full"><span id="chat-target-label">Recipient</span><select name="target"></select><small id="chat-target-help"></small></label></div><div id="modal-error" class="form-error hidden"></div><div class="modal-actions"><button type="button" class="btn" onclick="document.querySelector('#modal-close').click()">Cancel</button><button class="btn primary">Create conversation</button></div></form></div>`,()=>{
    const form=$("#modal-form"),type=form.elements.chat_type,target=form.elements.target,targetField=$("#chat-target-field"),label=$("#chat-target-label"),help=$("#chat-target-help");
    const refreshTarget=()=>{const kind=type.value,items=kind==="project"?options.projects:kind==="team"?options.teams:kind==="direct"?options.recipients:[];targetField.classList.toggle("hidden",kind==="broadcast");target.required=kind!=="broadcast";label.textContent=kind==="direct"?"Choose recipient":kind==="project"?"Choose project":"Choose team";help.textContent=kind==="direct"?"Only recipients permitted by your role are listed.":`Only ${kind}s you manage are listed.`;target.innerHTML=items.map(item=>`<option value="${item.id}">${esc(item.name)}${kind==="direct"?` · ${esc(item.email)}`:""}</option>`).join("")};
    $$('[data-chat-type]',form).forEach(button=>button.onclick=()=>{type.value=button.dataset.chatType;$$('[data-chat-type]',form).forEach(item=>item.classList.toggle("active",item===button));refreshTarget()});refreshTarget();
    form.onsubmit=async event=>{event.preventDefault();const button=$("button[type=submit]",form)||$("button.primary",form);if(!button)return;button.disabled=true;button.textContent="Creating…";try{const kind=type.value,payload={chat_type:kind,name:form.elements.name.value.trim()||null};if(kind==="project")payload.project_id=Number(target.value);if(kind==="team")payload.team_id=Number(target.value);if(kind==="direct")payload.recipient_id=Number(target.value);const saved=await api(`/workspaces/${state.workspace.id}/chat/conversations`,{method:"POST",body:JSON.stringify(payload)});state.activeChatId=saved.id;closeModal();await loadChats();toast("Conversation ready")}catch(err){button.disabled=false;button.textContent="Create conversation";const error=$("#modal-error");error.textContent=err.message;error.classList.remove("hidden")}};
  });
}
async function newChatModalV2(){
  if(!state.workspace){toast("Choose a workspace before starting a conversation",true);return}
  try{state.chatOptions=await api(`/workspaces/${state.workspace.id}/chat/options`)}catch(err){toast(err.message,true);return}
  const options=state.chatOptions,definitions=[
    ["broadcast","Announcement","Message everyone","!",options.can_broadcast,"Admin only"],
    ["direct","Direct message","Private conversation","@",options.recipients.length>0,"No permitted recipients"],
    ["project","Project group","Project collaboration","P",options.projects.length>0,"No managed projects"],
    ["team","Team group","Team collaboration","T",options.teams.length>0,"No managed teams"]
  ],first=definitions.find(item=>item[4]);
  if(!first){toast("No conversations are available for your current allocations",true);return}
  const cards=definitions.map(([value,label,help,icon,enabled,reason])=>`<button type="button" class="chat-type-option ${value===first[0]?"active":""}" data-chat-type="${value}" ${enabled?"":`disabled title="${reason}"`}><b>${icon}</b><span><strong>${label}</strong><small>${help}</small></span>${enabled?'<i class="chat-type-check">✓</i>':`<i>${reason}</i>`}</button>`).join("");
  modal(`<div class="chat-modal chat-modal-v2"><div class="chat-modal-heading"><span class="chat-modal-symbol">✦</span><div><h2>Start a conversation</h2><p class="subtitle">Choose a channel and audience. Access rules are applied automatically.</p></div></div><form id="modal-form"><input type="hidden" name="chat_type" value="${first[0]}"><div class="chat-section-label"><b>1</b><span><strong>Conversation type</strong><small>Choose how you want to communicate</small></span></div><div class="chat-type-grid">${cards}</div><div class="chat-section-label chat-audience-heading"><b>2</b><span><strong>Audience and details</strong><small>Confirm who will have access</small></span></div><div class="chat-create-fields"><label id="chat-target-field"><span id="chat-target-label">Recipient</span><div class="chat-select-wrap"><select name="target"></select></div><small id="chat-target-help"></small></label><label id="chat-name-field"><span>Conversation name <em>Optional</em></span><input name="name" maxlength="180" autocomplete="off" placeholder="e.g. Weekly delivery updates"></label><div id="chat-audience-preview" class="chat-audience-preview"></div></div><div id="modal-error" class="form-error hidden"></div><div class="modal-actions chat-modal-actions"><span>Only authorized participants can open this chat.</span><button type="button" class="btn" onclick="document.querySelector('#modal-close').click()">Cancel</button><button class="btn primary">Create conversation</button></div></form></div>`,()=>{
    const form=$("#modal-form"),type=form.elements.chat_type,target=form.elements.target,targetField=$("#chat-target-field"),nameField=$("#chat-name-field"),label=$("#chat-target-label"),help=$("#chat-target-help"),preview=$("#chat-audience-preview");
    const updatePreview=()=>{const kind=type.value,selected=target.options[target.selectedIndex],messages={broadcast:["Everyone in this workspace","Only administrators can post. Members have read-only access."],direct:[selected?.text||"Choose a recipient","A private chat between permitted participants."],project:[selected?.text||"Choose a project","For its manager and allocated project members."],team:[selected?.text||"Choose a team","For its manager and allocated team members."]},content=messages[kind];preview.innerHTML=`<b>${chatIcon(kind)}</b><span><strong>${esc(content[0])}</strong><small>${esc(content[1])}</small></span>`};
    const refreshTarget=()=>{const kind=type.value,items=kind==="project"?options.projects:kind==="team"?options.teams:kind==="direct"?options.recipients:[];targetField.classList.toggle("hidden",kind==="broadcast");nameField.classList.toggle("hidden",kind==="direct");nameField.classList.toggle("wide",kind==="broadcast");target.required=kind!=="broadcast";label.textContent=kind==="direct"?"Choose recipient":kind==="project"?"Choose project":"Choose team";help.textContent=kind==="direct"?"Members can only message managers connected to their allocations.":`Only ${kind}s permitted for your role are listed.`;target.innerHTML=items.map(item=>`<option value="${item.id}">${esc(item.name)}${kind==="direct"?` · ${esc(item.email)}`:""}</option>`).join("");updatePreview()};
    target.onchange=updatePreview;
    $$('[data-chat-type]',form).forEach(button=>button.onclick=()=>{type.value=button.dataset.chatType;$$('[data-chat-type]',form).forEach(item=>item.classList.toggle("active",item===button));refreshTarget()});refreshTarget();
    const createButton=$(".chat-modal-actions .primary",form);
    createButton.type="button";
    createButton.onclick=async()=>{createButton.disabled=true;createButton.textContent="Creating...";const error=$("#modal-error");error.classList.add("hidden");try{const kind=type.value,payload={chat_type:kind,name:form.elements.name.value.trim()||null};if(kind==="project")payload.project_id=Number(target.value);if(kind==="team")payload.team_id=Number(target.value);if(kind==="direct")payload.recipient_id=Number(target.value);const workspaceId=state.workspace?.id;if(!workspaceId)throw new Error("Choose a workspace before creating a conversation");const saved=await api(`/workspaces/${workspaceId}/chat/conversations`,{method:"POST",body:JSON.stringify(payload)});state.activeChatId=saved.id;closeModal();await loadChats();toast("Conversation created")}catch(err){createButton.disabled=false;createButton.textContent="Create conversation";error.textContent=err.message;error.classList.remove("hidden")}};
    form.onsubmit=async event=>{event.preventDefault();const button=$("button[type=submit]",form);button.disabled=true;button.textContent="Creating…";try{const kind=type.value,payload={chat_type:kind,name:form.elements.name.value.trim()||null};if(kind==="project")payload.project_id=Number(target.value);if(kind==="team")payload.team_id=Number(target.value);if(kind==="direct")payload.recipient_id=Number(target.value);const saved=await api(`/workspaces/${state.workspace.id}/chat/conversations`,{method:"POST",body:JSON.stringify(payload)});state.activeChatId=saved.id;closeModal();await loadChats();toast("Conversation ready")}catch(err){button.disabled=false;button.textContent="Create conversation";const error=$("#modal-error");error.textContent=err.message;error.classList.remove("hidden")}};
  });
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
function boardWaitAnimation(){return `<div class="board-wait" role="status" aria-label="Loading project data"><div class="wait-board" aria-hidden="true"><div class="wait-column"><b></b><i></i><i></i></div><div class="wait-column"><b></b><i></i><i></i><i></i></div><div class="wait-column"><b></b><i></i></div><span class="wait-card"></span></div><div class="wait-dots" aria-hidden="true"><i></i><i></i><i></i></div></div>`}
function boardView() {
  if (!state.project) return `${pageHeading("Task board","Visualize work as it moves through your workflow.")}${emptyMini("Create a project first","Tasks live inside projects.")}`;
  if(state.projectLoading)return `${pageHeading("Task board",`Loading ${esc(state.project.name)}…`)}${boardWaitAnimation()}`;
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
  const completed=t.status==="done";
  const deadline=t.end_at?new Date(t.end_at):t.due_date?new Date(`${t.due_date}T23:59:59`):null,incomplete=t.checklist_total>t.checklist_done;
  const checklistWarning=!completed&&incomplete&&deadline&&deadline<Date.now(),dueSoon=!completed&&deadline&&deadline>=Date.now()&&deadline-Date.now()<=72*3600000;
  return `<article class="task-card ${completed?"task-completed":""} ${checklistWarning?"task-deadline-warning":dueSoon?"task-due-soon":""}" draggable="${canManageProject()}" data-task="${t.id}">${checklistWarning?'<span class="deadline-warning-light" title="Deadline passed with incomplete checklist">!</span>':""}<span class="priority-dot ${t.priority}">${t.priority}</span><div class="task-card-title"><input type="checkbox" class="task-completion-toggle" data-task-complete="${t.id}" aria-label="Mark ${esc(t.title)} as completed" ${completed?"checked":""} ${canCollaborateProject()?"":"disabled"}><h4>${esc(t.title)}</h4></div><p>${esc(t.description||"No description")}</p>
    ${t.progress?`<div class="card-progress"><i style="width:${t.progress}%"></i></div>`:""}
    <div class="task-foot"><span>${t.end_at?`◷ ${dateTime(t.end_at)}`:t.due_date?`◷ ${date(t.due_date)}`:`#${t.id}`}</span>${checklist}<div class="avatar-stack">${assignees.slice(0,3).map(u=>`<b class="avatar" title="${esc(u.name)}">${esc(u.name.slice(0,2).toUpperCase())}</b>`).join("")}${assignees.length>3?`<b class="avatar">+${assignees.length-3}</b>`:!assignees.length?'<b class="avatar">—</b>':""}</div></div></article>`;
}
function ganttView() {
  if (!state.project) return `${pageHeading("Gantt chart","Plan tasks across a visual timeline.")}${emptyMini("Create a project first","Scheduled tasks will appear here.")}`;
  if(state.projectLoading)return `${pageHeading("Gantt chart",`Loading ${esc(state.project.name)}…`)}${boardWaitAnimation()}`;
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
function reportView() {
  if (!state.project) return `${pageHeading("Project report","Shared delivery insight for project teams.")}${emptyMini("Create a project first","Reports become available once a project exists.")}`;
  if (state.projectLoading || !state.report) return `${pageHeading("Project report",`Loading ${esc(state.project.name)}…`)}${boardWaitAnimation()}`;
  const r=state.report, counts=r.workflow||{}, priorities=r.tasks.priority_counts||{}, path=r.critical_path||[];
  const max=Math.max(1,...Object.values(counts));
  const money=r.budget.planned==null?"Not set":new Intl.NumberFormat(undefined,{style:"currency",currency:"USD",maximumFractionDigits:0}).format(r.budget.planned);
  const healthClass=r.health.toLowerCase().replaceAll(" ","-");
  return `${pageHeading("Project report",`A shared, read-only delivery view for ${esc(state.project.name)}.`, `<button id="report-refresh" class="btn">Refresh report</button>`)}
    <div class="toolbar report-toolbar">${projectSelector()}<span class="report-access">Visible to project admins and allocated members</span></div>
    <section class="report-hero"><div><span class="report-eyebrow">DELIVERY HEALTH</span><h2>${esc(r.health)}</h2><p>${date(r.project.start_date)} â€” ${date(r.project.end_date)} · ${pretty(r.project.status)} project</p></div><div class="report-progress"><strong>${r.progress}%</strong><span>work completion</span><i><b style="width:${r.progress}%"></b></i></div></section>
    <div class="report-kpis">
      ${reportKpi("Tasks complete",`${r.tasks.completed}/${r.tasks.total}`,`${r.tasks.overdue} overdue`)}
      ${reportKpi("Schedule elapsed",`${r.schedule_percent}%`,"of planned timeline")}
      ${reportKpi("Budget",money,r.budget.cost_tracking_available?"actuals tracked":"planned budget only")}
      ${reportKpi("Project team",r.team.allocated_members,`${r.team.allocations} team allocations`)}
    </div>
    <div class="report-grid">
      <section class="panel report-panel"><div class="panel-header"><h3>Workflow distribution</h3><span class="badge ${healthClass}">${esc(r.health)}</span></div><div class="workflow-bars">${STATUS.map(([key,label])=>`<div><span>${label}</span><i><b style="width:${(counts[key]||0)*100/max}%"></b></i><strong>${counts[key]||0}</strong></div>`).join("")}</div></section>
      <section class="panel report-panel"><div class="panel-header"><h3>Priority exposure</h3><span class="subtitle">Open and completed work</span></div><div class="priority-summary">${["critical","high","medium","low"].map(priority=>`<div class="priority ${priority}"><b>${priorities[priority]||0}</b><span>${pretty(priority)}</span></div>`).join("")}</div><div class="point-progress"><span>Delivery points</span><strong>${r.budget.completed_story_points}/${r.budget.story_points}</strong><i><b style="width:${r.budget.story_points?Math.round(r.budget.completed_story_points*100/r.budget.story_points):0}%"></b></i></div></section>
      <section class="panel report-panel critical-panel"><div class="panel-header"><div><h3>Schedule-risk path</h3><small>Unfinished high-priority tasks ordered by planned finish date</small></div><span class="badge">${path.length}</span></div>${path.length?`<div class="critical-list">${path.map(task=>`<div><span class="priority-dot ${task.priority}"></span><p><strong>${esc(task.title)}</strong><small>${date(task.start_date)} → ${date(task.due_date)} · ${task.progress}% complete</small></p><em>${pretty(task.status)}</em></div>`).join("")}</div>`:emptyMini("No active schedule risk","No unfinished high- or critical-priority scheduled tasks.")}</section>
      <section class="panel report-panel"><div class="panel-header"><h3>Budget & tracking note</h3></div><div class="budget-note"><b>${money}</b><p>This project stores a planned budget. Actual spend is not recorded yet, so the report deliberately does not estimate or invent a cost variance.</p><span>${r.tasks.scheduled} of ${r.tasks.total} tasks have planned dates</span></div></section>
    </div>`;
}
function reportKpi(label,value,note){return `<article class="report-kpi"><span>${label}</span><strong>${value}</strong><small>${note}</small></article>`}
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
  const completion=p.completion_percent||0,missing=p.missing_fields||[];
  const skills=(p.skills||"").split(/[\n,]+/).map(x=>x.trim()).filter(Boolean);
  const designationOptions=designationChoices();
  if(p.professional_title&&!state.designations.some(item=>item.name===p.professional_title))designationOptions.push([p.professional_title,p.professional_title]);
  const departmentOptions=state.departments.map(item=>[item.name,item.name]);
  if(p.department&&!state.departments.some(item=>item.name===p.department))departmentOptions.push([p.department,p.department]);
  const experience=experienceElapsed(p.experience_start_date);
  return `${pageHeading("My profile","Keep your personal and professional information up to date.")}
  <div class="profile-layout"><aside class="panel profile-summary"><div id="profile-photo-preview" class="profile-photo ${p.profile_image?"has-photo":""}" style="${p.profile_image?`background-image:url('${esc(p.profile_image)}')`:""}">${p.profile_image?"":esc(initials)}</div><h2>${esc(p.name||state.user.name)}</h2><p>${esc(p.professional_title||"Designation not assigned")}</p><span>${esc(p.email||state.user.email)}</span><div class="profile-completion ${completion===100?"complete":""}"><div><strong>${completion}%</strong><span>Profile complete</span></div><div class="profile-completion-track"><i style="width:${completion}%"></i></div><small>${completion===100?"Eligible for team allocation.":`Complete your profile before team allocation. Missing: ${esc(missing.join(", "))}`}</small></div><div class="profile-project-stat"><strong>${p.project_count||0}</strong><small>Projects worked on</small></div><div class="profile-skills">${skills.map(skill=>`<span>${esc(skill)}</span>`).join("")||"<small>Add skills to complete your profile.</small>"}</div><div class="profile-history"><h3>Project history</h3>${(p.projects||[]).map(name=>`<div><span class="project-icon">${esc(name[0]?.toUpperCase()||"P")}</span>${esc(name)}</div>`).join("")||"<small>No project history yet.</small>"}</div></aside>
  <section class="panel profile-editor"><form id="profile-form"><h3>Profile photo</h3><div class="profile-photo-actions"><label class="btn" for="profile-image-input">Choose image</label><input id="profile-image-input" type="file" accept="image/png,image/jpeg,image/webp" hidden><button id="remove-profile-image" type="button" class="btn">Remove</button><small>PNG, JPG or WebP · minimum 128 × 128 px · 512 × 512 px recommended · maximum 2 MB.</small><small id="profile-image-error" class="image-upload-error hidden" role="alert"></small></div><h3>Personal details</h3><div class="form-grid">${field("name","Full name","text","Your full name",true,false,p.name||state.user.name)}${field("phone","Phone (10 digits)","tel","9876543210",true,false,p.phone)}${field("location_city","City","text","City",true,false,p.location_city||p.location)}${field("location_state","State","text","State",true,false,p.location_state)}${field("location_country","Country","text","Country",true,false,p.location_country)}<label class="field full">About me<textarea name="bio" maxlength="300" placeholder="A short introduction" required>${esc(p.bio||"")}</textarea><small><span id="bio-count">${(p.bio||"").length}</span>/300 characters</small></label><h3 class="profile-form-heading">Professional details</h3>${selectField("professional_title","Professional title · Designation",designationOptions,p.professional_title,"Admin must assign designation")}${selectField("department","Department",departmentOptions,p.department,"Admin must assign department")}<p class="admin-controlled-note">Designation and department can only be changed by an administrator.</p><label class="field">Experience start date<input name="experience_start_date" type="date" max="${new Date().toISOString().slice(0,10)}" value="${esc(p.experience_start_date||"")}" required><small id="experience-elapsed">${esc(experience)}</small></label>${field("skills","Skills","textarea","One skill per line or comma separated",true,true,p.skills)}${field("achievements","Achievements · comma separated","textarea","Awards, certifications and professional milestones",true,true,p.achievements)}</div><div id="profile-error" class="form-error hidden"></div><div class="modal-actions"><button class="btn primary" type="submit">Save profile</button></div></form></section></div>`;
}
function experienceElapsed(value){if(!value)return "Select your professional start date";const start=new Date(`${value}T00:00:00`),today=new Date();if(start>today)return "Start date cannot be in the future";let years=today.getFullYear()-start.getFullYear(),months=today.getMonth()-start.getMonth(),days=today.getDate()-start.getDate();if(days<0){months--;days+=new Date(today.getFullYear(),today.getMonth(),0).getDate()}if(months<0){years--;months+=12}return `${years} year${years===1?"":"s"}, ${months} month${months===1?"":"s"}, ${days} day${days===1?"":"s"}`}
function bindProfileView(){
  const form=$("#profile-form");if(!form)return;
  form.noValidate=true;
  const bio=form.elements.bio,bioCount=$("#bio-count");bio.required=false;bio.closest('label').firstChild.textContent='About me (optional)';bio.oninput=()=>bioCount.textContent=bio.value.length;
  form.elements.skills.required=true;form.elements.skills.closest('label').firstChild.textContent='Skills';
  form.elements.achievements.required=false;form.elements.achievements.closest('label').firstChild.textContent='Achievements · comma separated (optional)';
  const experienceInput=form.elements.experience_start_date;experienceInput.onchange=()=>$("#experience-elapsed").textContent=experienceElapsed(experienceInput.value);
  ['professional_title','department'].forEach(name=>{const input=$(`[name="${name}"]`,form);if(input){input.disabled=true;input.title="Only an administrator can change this field"}});
  enhanceSkillInputs(form);
  let profileImage=state.profile?.profile_image||null;
  const imageError=$("#profile-image-error"),imageInput=$("#profile-image-input"),preview=$("#profile-photo-preview");
  const showImageError=message=>{imageError.textContent=message;imageError.classList.remove("hidden");toast(message,true)};
  const clearImageError=()=>{imageError.textContent="";imageError.classList.add("hidden")};
  const resetImagePreview=()=>{preview.style.backgroundImage="";preview.textContent=(state.profile?.name||state.user.name).slice(0,2).toUpperCase();preview.classList.remove("has-photo")};
  const inspectImage=source=>new Promise((resolve,reject)=>{const image=new Image();image.onload=()=>resolve(image);image.onerror=()=>reject(new Error("The image could not be loaded. It may be corrupted or unreadable."));image.src=source});
  imageInput.onchange=async event=>{
    const file=event.target.files[0];if(!file)return;clearImageError();
    if(!["image/png","image/jpeg","image/webp"].includes(file.type)){showImageError("Unsupported image type. Choose a PNG, JPG or WebP image.");event.target.value="";return}
    if(file.size>2*1024*1024){showImageError("Image is too large. The maximum allowed size is 2 MB.");event.target.value="";return}
    try{
      const source=await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result);reader.onerror=()=>reject(new Error("The selected image file could not be read."));reader.readAsDataURL(file)});
      const image=await inspectImage(source);
      if(image.naturalWidth<128||image.naturalHeight<128)throw new Error(`Image is ${image.naturalWidth} × ${image.naturalHeight} px. Minimum required size is 128 × 128 px.`);
      profileImage=source;preview.textContent="";preview.style.backgroundImage=`url("${profileImage}")`;preview.classList.add("has-photo");
    }catch(error){showImageError(error.message||"The image could not be loaded.");event.target.value=""}
  };
  if(profileImage)inspectImage(profileImage).catch(()=>{profileImage=null;resetImagePreview();showImageError("Your saved profile image could not be loaded. Please choose another image.")});
  $("#remove-profile-image").onclick=()=>{profileImage=null;imageInput.value="";clearImageError();resetImagePreview()};
  form.onsubmit=async event=>{event.preventDefault();const button=$('button[type="submit"]',form),error=$("#profile-error");button.disabled=true;try{const data=formData(form);data.profile_image=profileImage;data.location=[data.location_city,data.location_state,data.location_country].filter(Boolean).join(", ");data.years_experience=data.experience_start_date?Math.max(0,Math.floor((Date.now()-new Date(`${data.experience_start_date}T00:00:00`))/31557600000)):null;state.profile=await api("/auth/profile",{method:"PUT",body:JSON.stringify(data)});state.user.name=state.profile.name;syncUserChrome();closeModal();render();toast(profileOnboardingRequired()?"Profile saved — complete the remaining fields":"Profile completed") }catch(err){error.textContent=err.message;error.classList.remove("hidden")}finally{button.disabled=false}};
  form.addEventListener('submit',event=>{clearFieldErrors(form);clearImageError();let valid=true;const required=[['name','Full name is required and must contain at least 2 characters.',value=>value.trim().length>=2],['phone','Phone must contain exactly 10 digits.',value=>/^\d{10}$/.test(value.trim())],['location_city','City is required.',value=>Boolean(value.trim())],['location_state','State is required.',value=>Boolean(value.trim())],['location_country','Country is required.',value=>Boolean(value.trim())],['experience_start_date','Experience start date is required.',value=>Boolean(value)&&new Date(`${value}T00:00:00`)<=new Date()]];required.forEach(([name,message,check])=>{const input=form.elements[name];if(!check(input.value)){fieldError(input,message);valid=false}});const skills=form.elements.skills;if(!skills.value.trim()){fieldError(skills.nextElementSibling?.querySelector('input')||skills,'Add at least one skill.');valid=false}if(bio.value.length>300){fieldError(bio,'About me must not exceed 300 characters.');valid=false}if(!profileImage){showImageError('Choose a profile image before saving.');valid=false}if(!valid){event.preventDefault();event.stopImmediatePropagation();form.querySelector('.input-invalid')?.focus()}},true);
}
function skillsView(){
  if(!isAdmin())return emptyMini("Admin access required","Only workspace admins can search skills and assign work.");
  return `${pageHeading("Skills","Find the right member by skill and assign them to project tasks.",`<span class="member-count">${state.skillCatalog.length}</span>`)}<div class="skills-search"><input id="skills-search" placeholder="Search Python, design, accounting or a member name"><select id="skills-filter"><option value="">All skills</option>${state.skillCatalog.map(skill=>`<option value="${esc(skill)}">${esc(skill)}</option>`).join("")}</select></div><div id="skills-directory" class="skills-directory">${skillMemberCards(state.skillMembers)}</div>`;
}
function skillMemberCards(members){return members.length?members.map(member=>{const assignable=Boolean(state.workspace)&&member.project_ids.length;return `<article class="panel skill-member-card"><div class="skill-member-head">${avatar(member)}<div><strong>${esc(member.name)}</strong><small>${esc(member.professional_title||member.department||member.email)}</small></div></div><div class="skill-tags">${member.skills.map(skill=>`<span>${esc(skill)}</span>`).join("")||"<small>No skills added yet</small>"}</div><button class="btn primary" data-skill-assign="${member.user_id}" ${assignable?"":"disabled"}>Assign to task</button>${assignable?"":`<small class="skill-allocation-note">${state.workspace?"Allocate this member to a project first.":"Create or select a workspace to assign tasks."}</small>`}</article>`}).join(""):emptyMini("No matching members","Try another skill or add skills to member profiles.")}
function bindSkillsView(){const search=$("#skills-search"),filter=$("#skills-filter");if(!search)return;const apply=()=>{const query=search.value.trim().toLowerCase(),skill=filter.value.toLowerCase();const members=state.skillMembers.filter(member=>(!query||member.name.toLowerCase().includes(query)||member.email.toLowerCase().includes(query)||member.skills.some(item=>item.toLowerCase().includes(query)))&&(!skill||member.skills.some(item=>item.toLowerCase()===skill)));$("#skills-directory").innerHTML=skillMemberCards(members);bindSkillAssignButtons()};search.oninput=apply;filter.onchange=apply;bindSkillAssignButtons()}
function bindSkillAssignButtons(){$$('[data-skill-assign]').forEach(button=>button.onclick=()=>skillTaskAssignModal(state.skillMembers.find(member=>member.user_id===Number(button.dataset.skillAssign))))}
function skillTaskAssignModal(member){const projects=state.projects.filter(project=>member.project_ids.includes(project.id));let projectTasks=[];modal(formShell("Assign member to task",`Choose a project task for ${esc(member.name)}.`,`${selectField("project_id","Project",projects.map(project=>[project.id,project.name]))}<label class="field full">Task<select name="task_id" id="skill-task-select" required><option value="">Select a project first</option></select></label>`,"Assign task"),()=>{const projectSelect=$('[name="project_id"]'),taskSelect=$("#skill-task-select");const load=async()=>{taskSelect.innerHTML='<option value="">Loading tasks…</option>';try{projectTasks=await api(`/projects/${projectSelect.value}/tasks`);taskSelect.innerHTML=`<option value="">Select task</option>${projectTasks.map(task=>`<option value="${task.id}">${esc(task.title)}</option>`).join("")}`}catch(err){taskSelect.innerHTML='<option value="">Could not load tasks</option>';toast(err.message,true)}};projectSelect.onchange=load;if(projectSelect.value)load();$("#modal-form").onsubmit=async event=>submitForm(event,async data=>{const task=projectTasks.find(item=>item.id===Number(data.task_id));if(!task)throw new Error("Select a task");const assignee_ids=[...new Set([...(task.assignee_ids||[]),member.user_id])];await api(`/tasks/${task.id}`,{method:"PATCH",body:JSON.stringify({assignee_ids})});if(state.project?.id===Number(data.project_id))await loadProject();toast(`${member.name} assigned to ${task.title}`)})})}
const USERS_PAGE_SIZE=10;
function userDirectoryPageRows(users){const pages=Math.max(1,Math.ceil(users.length/USERS_PAGE_SIZE));state.userDirectoryPage=Math.min(Math.max(1,state.userDirectoryPage),pages);const start=(state.userDirectoryPage-1)*USERS_PAGE_SIZE;return users.slice(start,start+USERS_PAGE_SIZE)}
function userDirectoryPagination(users){const pages=Math.ceil(users.length/USERS_PAGE_SIZE);if(pages<=1)return '';return `<div class="panel-pagination users-pagination"><button type="button" data-users-page="${state.userDirectoryPage-1}" ${state.userDirectoryPage===1?"disabled":""}>Previous</button><span>Page ${state.userDirectoryPage} of ${pages} · ${users.length} users</span><button type="button" data-users-page="${state.userDirectoryPage+1}" ${state.userDirectoryPage===pages?"disabled":""}>Next</button></div>`}
function usersView(){
  if(!isAdmin())return emptyMini("Admin access required","Only workspace admins can manage users.");
  state.userDirectory.filter(user=>!user.is_active).forEach(user=>state.selectedProfileUsers.delete(user.user_id));
  state.filteredUserDirectory=state.userDirectory;const pageUsers=userDirectoryPageRows(state.filteredUserDirectory);
  return `${pageHeading("Users","Manage registered accounts, profile readiness and workspace access.",`<span class="member-count">${state.userDirectory.length}</span>`)}<div class="users-toolbar"><input id="user-search" placeholder="Search by name or email"><select id="user-department-filter"><option value="">All departments</option>${state.departments.map(item=>`<option value="${esc(item.name)}">${esc(item.name)}</option>`).join("")}</select><select id="user-designation-filter"><option value="">All designations</option>${state.designations.map(item=>`<option value="${esc(item.name)}">${esc(item.name)}</option>`).join("")}</select><select id="user-project-filter"><option value="">All projects</option>${state.projects.map(item=>`<option value="${esc(item.name)}">${esc(item.name)}</option>`).join("")}</select><button id="reset-user-filters" class="btn users-reset" type="button">Reset</button></div><div class="user-bulk-actions"><span><strong id="selected-profile-count">${state.selectedProfileUsers.size}</strong> selected</span><button id="send-profile-reminder" class="btn">Send profile reminders</button><button id="send-custom-announcement" class="btn primary">Custom announcement</button></div><section class="panel users-table-wrap"><table class="users-table"><thead><tr><th class="select-cell"><input id="select-all-profile-users" type="checkbox" aria-label="Select active users"></th><th>User</th><th>Profile</th><th>Department</th><th>Designation</th><th>Project allocations</th><th>Access</th><th>Status</th><th>Actions</th></tr></thead><tbody id="users-table-body">${userDirectoryRows(pageUsers)}</tbody></table><div id="users-pagination">${userDirectoryPagination(state.filteredUserDirectory)}</div></section>`;
}
function userDirectoryActions(user){const edit=`<button data-directory-profile="${user.user_id}">Edit profile</button>`,remove=user.user_id!==state.user.id?`<button class="remove-action" data-directory-delete="${user.user_id}">Delete</button>`:"";return `${edit}${remove}`}
function userDirectoryAccess(user){if(!user.is_member)return '<span class="badge">Not Added</span>';const role=user.is_system_admin?"admin":"member";return `<div class="role-access"><span class="badge ${role}">${pretty(role)}</span>${user.user_id!==state.user.id?`<button data-edit-access="${user.user_id}" title="Edit role, department and designation">Edit</button>`:""}</div>`}
function userDirectoryStatus(user){if(!user.is_active&&!user.is_member)return `<button class="approve-action" data-directory-approve="${user.user_id}">Approval pending</button>`;if(!user.is_member)return `<button class="add-member-action" data-directory-add="${user.user_id}"><span>＋</span> Add member</button>`;if(user.user_id===state.user.id)return `<span class="status-self">Current user</span>`;return `<label class="access-switch" title="${user.is_active?"Deactivate":"Activate"} account"><input type="checkbox" data-directory-access="${user.user_id}" ${user.is_active?"checked":""}><span></span><em>${user.is_active?"Active":"Inactive"}</em></label>`}
function userDirectoryRows(users){return users.length?users.map(user=>{const completion=user.completion_percent||0,selectable=Boolean(state.workspace)&&user.is_active&&completion<100;return `<tr class="${user.is_active?"":"pending-user"}"><td class="select-cell"><input type="checkbox" data-profile-select="${user.user_id}" aria-label="Select ${esc(user.name)}" ${state.selectedProfileUsers.has(user.user_id)?"checked":""} ${selectable?"":"disabled"}></td><td><div class="directory-user">${avatar(user)}<span><strong>${esc(user.name)}</strong><small>${esc(user.email)}</small></span></div></td><td><div class="directory-completion ${completion===100?"complete":""}"><span><strong>${completion}%</strong><small>${completion===100?"Ready":"Incomplete"}</small></span><i><b style="width:${completion}%"></b></i></div></td><td>${esc(user.department||"Not set")}</td><td>${esc(user.professional_title||"Not set")}</td><td><div class="directory-projects">${user.projects.length?user.projects.map(project=>`<span>${esc(project)}</span>`).join(""):"<small>No allocations</small>"}</div></td><td>${userDirectoryAccess(user)}</td><td>${userDirectoryStatus(user)}</td><td><div class="directory-actions">${userDirectoryActions(user)}</div></td></tr>`}).join(""):`<tr><td colspan="9" class="users-empty">No users match these filters.</td></tr>`}
function renderUserDirectoryResults(users,resetPage=false){if(resetPage)state.userDirectoryPage=1;state.filteredUserDirectory=users;const rows=userDirectoryPageRows(users);$("#users-table-body").innerHTML=userDirectoryRows(rows);$("#users-pagination").innerHTML=userDirectoryPagination(users);bindUserDirectoryActions()}
function filterUserDirectory(){const query=$("#user-search").value.trim().toLowerCase(),department=$("#user-department-filter").value,designation=$("#user-designation-filter").value,project=$("#user-project-filter").value;const users=state.userDirectory.filter(user=>(!query||user.name.toLowerCase().includes(query)||user.email.toLowerCase().includes(query))&&(!department||user.department===department)&&(!designation||user.professional_title===designation)&&(!project||user.projects.includes(project)));renderUserDirectoryResults(users,true)}
function addDirectoryUserModal(user){
  if(!state.departments.length||!state.designations.length){toast("Create a department and designation before adding a member",true);return}
  modal(formShell(user.is_member?"Edit access":"Add member",`Assign ${esc(user.name)} a role, department, and designation.`,`${selectField("role","Role",[["member","Member"],["admin","Admin"]],user.is_system_admin?"admin":"member")}${selectField("department","Department",state.departments.map(item=>[item.name,item.name]),user.department||"","Select department")}<label class="field">Designation<select name="professional_title" id="new-member-designation" required disabled><option value="">Select department first</option></select></label>`,user.is_member?"Save assignment":"Add member"),()=>{
    const form=$("#modal-form"),department=form.elements.department,designation=$("#new-member-designation");
    let selectedDesignation=user.professional_title;const populate=()=>{const choices=state.designations.filter(item=>item.department_name===department.value);designation.innerHTML=`<option value="">Select designation</option>${choices.map(item=>`<option value="${esc(item.name)}" ${item.name===selectedDesignation?"selected":""}>${esc(item.name)}</option>`).join("")}`;designation.disabled=!choices.length};department.onchange=()=>{selectedDesignation=null;populate()};populate();
    form.onsubmit=async event=>submitForm(event,async data=>{const updated=await api(`/admin/users/${user.user_id}/member`,{method:"PATCH",body:JSON.stringify(data)});state.userDirectory=state.userDirectory.map(item=>item.user_id===user.user_id?{...item,...updated}:item);toast(`${updated.name} saved as ${pretty(updated.role)}`)})
  })
}
function editDirectoryAccessModal(user){modal(formShell("Edit access",`Change ${esc(user.name)}'s role in this workspace.`,selectField("role","Workspace role",[["member","Member"],["admin","Admin"]],user.role),"Save access"),()=>$("#modal-form").onsubmit=async event=>submitForm(event,async data=>{const member=await api(`/workspaces/${state.workspace.id}/members/${user.membership_id}/access`,{method:"PATCH",body:JSON.stringify({role:data.role})});user.role=member.role;state.members=state.members.map(item=>item.id===member.id?member:item);toast(`${user.name} is now ${pretty(member.role)}`)}))}
async function adminUserProfileModal(directoryUser){
  const member=state.members.find(item=>item.user_id===directoryUser.user_id);
  try{
    const profile=await api(`/admin/users/${directoryUser.user_id}/profile`);
    const fields=`<label class="field full">Email address<input value="${esc(profile.email)}" readonly disabled></label>${field("name","Full name","text","Full name",true,false,profile.name)}${selectField("department","Department",state.departments.map(item=>[item.name,item.name]),profile.department,"Select department")}<label class="field">Professional title · Designation<select name="professional_title" id="admin-profile-designation" required></select></label><label class="field">Experience start date<input name="experience_start_date" type="date" max="${new Date().toISOString().slice(0,10)}" value="${esc(profile.experience_start_date||"")}"></label>${field("skills","Skills","textarea","One skill per line or comma separated",false,true,profile.skills)}`;
    modal(formShell("Edit user profile","Administrators manage identity and professional assignment. Employees maintain their other personal details.",fields,"Save profile"),()=>{
      const form=$("#modal-form"),department=form.elements.department,designation=$("#admin-profile-designation");
      const populateDesignations=selected=>{const options=state.designations.filter(item=>item.department_name===department.value);designation.innerHTML=`<option value="">Select designation</option>${options.map(item=>`<option value="${esc(item.name)}" ${item.name===selected?"selected":""}>${esc(item.name)}</option>`).join("")}`;designation.disabled=!department.value||!options.length};
      populateDesignations(profile.professional_title);department.onchange=()=>populateDesignations("");
      form.onsubmit=async event=>submitForm(event,async data=>{const updated=await api(`/admin/users/${directoryUser.user_id}/profile`,{method:"PUT",body:JSON.stringify(data)});state.userDirectory=state.userDirectory.map(user=>user.user_id===directoryUser.user_id?{...user,name:updated.name,professional_title:updated.professional_title,department:updated.department,completion_percent:updated.completion_percent,missing_fields:updated.missing_fields}:user);if(member)state.members=state.members.map(item=>item.id===member.id?{...item,user:{...item.user,name:updated.name},professional_title:updated.professional_title,department:updated.department}:item);if(directoryUser.user_id===state.user.id){state.user.name=updated.name;state.profile=updated;syncUserChrome()}toast(`User profile updated · ${updated.completion_percent}% complete`)})
    })
  }catch(err){toast(err.message,true)}
}
function profileReminderModal(userIds){
  const recipients=state.userDirectory.filter(user=>userIds.includes(user.user_id));
  modal(formShell("Send profile reminder",`Compose a notification for ${recipients.length} selected user${recipients.length===1?"":"s"}.`,`<div class="field full reminder-recipients"><strong>Recipients</strong><span>${recipients.map(user=>esc(user.name)).join(", ")}</span></div>${field("title","Notification subject","text","Complete your profile",true,false,"Complete your profile")}${field("message","Custom message","textarea","Leave blank to send each user their current completion percentage and missing profile fields.",false,true)}<div class="field full reminder-compose-note"><strong>Personalized default</strong><span>If the custom message is blank, each member receives their own completion percentage, missing fields, and team-allocation requirement.</span></div>`,"Send notification"),()=>$("#modal-form").onsubmit=async event=>submitForm(event,async data=>{
    const result=await api("/notifications/profile-completion",{method:"POST",body:JSON.stringify({user_ids:userIds,title:data.title,message:data.message})});
    state.selectedProfileUsers.clear();loadNotifications().catch(()=>{});toast(`${result.sent_count} reminder${result.sent_count===1?"":"s"} sent`);
  }));
}
function memberProfileMissing(user){return (user.missing_fields||[]).filter(field=>field!=="Department"&&field!=="Designation")}
async function sendAutomaticProfileReminders(){
  const user_ids=state.userDirectory.filter(user=>user.is_active&&user.is_member&&memberProfileMissing(user).length).map(user=>user.user_id);
  if(!user_ids.length){toast("Every member has completed their required profile details");return}
  try{const result=await api("/notifications/profile-completion",{method:"POST",body:JSON.stringify({user_ids})});await loadNotifications();toast(`${result.sent_count} profile reminder${result.sent_count===1?"":"s"} sent`)}catch(err){toast(err.message,true)}
}
async function customAnnouncementModal(){
  const selected=[...state.selectedProfileUsers],selectedUsers=state.userDirectory.filter(user=>selected.includes(user.user_id));
  modal(formShell("Custom announcement","Send a global announcement to all active Members and Admins or selected individuals.",`${selectField("audience","Audience",[["all","All Members and Admins"],["selected",`Selected individuals (${selectedUsers.length})`]],"all")}${field("title","Announcement title","text","e.g. Office update",true)}${field("message","Message","textarea","Write your announcement",true,true)}<div class="field full reminder-compose-note"><strong>Individual recipients</strong><span>${selectedUsers.length?selectedUsers.map(user=>esc(user.name)).join(", "):"Select users in the table before choosing selected individuals."}</span></div>`,"Send announcement"),()=>{
    const form=$("#modal-form");form.elements.audience.onchange=()=>{if(form.elements.audience.value==="selected"&&!selectedUsers.length){form.elements.audience.value="all";toast("Select at least one active user first",true)}};
    form.onsubmit=async event=>submitForm(event,async data=>{
      const result=await api("/admin/announcements",{method:"POST",body:JSON.stringify({audience:data.audience,user_ids:data.audience==="selected"?selectedUsers.map(user=>user.user_id):[],title:data.title,message:data.message})});
      state.selectedProfileUsers.clear();toast(`Announcement sent to ${result.sent_count} user${result.sent_count===1?"":"s"}`)
    })
  })
}
function bindUserDirectoryActions(){
  $$('[data-users-page]').forEach(button=>button.onclick=()=>{state.userDirectoryPage=Number(button.dataset.usersPage);renderUserDirectoryResults(state.filteredUserDirectory)});
  $$('[data-profile-select]').forEach(input=>{const user=state.userDirectory.find(item=>item.user_id===Number(input.dataset.profileSelect));input.disabled=!user?.is_active||!user?.is_member});
  const updateSelection=()=>{const count=$("#selected-profile-count");if(count)count.textContent=state.selectedProfileUsers.size};
  $$('[data-profile-select]').forEach(input=>input.onchange=()=>{const id=Number(input.dataset.profileSelect);if(input.checked)state.selectedProfileUsers.add(id);else state.selectedProfileUsers.delete(id);updateSelection()});
  const selectAll=$("#select-all-profile-users");if(selectAll){const eligible=state.filteredUserDirectory.filter(user=>user.is_active&&user.is_member),selectedCount=eligible.filter(user=>state.selectedProfileUsers.has(user.user_id)).length;selectAll.checked=eligible.length>0&&selectedCount===eligible.length;selectAll.indeterminate=selectedCount>0&&selectedCount<eligible.length;selectAll.disabled=!eligible.length;selectAll.onchange=()=>{eligible.forEach(user=>{if(selectAll.checked)state.selectedProfileUsers.add(user.user_id);else state.selectedProfileUsers.delete(user.user_id)});renderUserDirectoryResults(state.filteredUserDirectory);updateSelection()}};
  $("#send-profile-reminder")?.addEventListener("click",sendAutomaticProfileReminders);
  $("#send-custom-announcement")?.addEventListener("click",customAnnouncementModal);
  $$('[data-directory-approve]').forEach(button=>button.onclick=async()=>{const user=state.userDirectory.find(item=>item.user_id===Number(button.dataset.directoryApprove));if(!user)return;try{const updated=await api(`/admin/users/${user.user_id}/approve`,{method:"PATCH"});Object.assign(user,updated);render();toast(`${user.name} can now sign in`)}catch(err){toast(err.message,true)}});
  $$('[data-directory-access]').forEach(button=>button.onclick=async()=>{const user=state.userDirectory.find(item=>item.user_id===Number(button.dataset.directoryAccess));if(!user)return;const next=!user.is_active;try{const updated=await api(`/admin/users/${user.user_id}/access?is_active=${next}`,{method:"PATCH"});Object.assign(user,updated);render();toast(`${user.name} is now ${next?"active":"inactive"}`)}catch(err){render();toast(err.message,true)}});
  $$('[data-edit-access]').forEach(button=>button.onclick=()=>addDirectoryUserModal(state.userDirectory.find(item=>item.user_id===Number(button.dataset.editAccess))));
  $$("[data-directory-add]").forEach(button=>button.onclick=()=>addDirectoryUserModal(state.userDirectory.find(user=>user.user_id===Number(button.dataset.directoryAdd))));
  $$("[data-directory-profile]").forEach(button=>button.onclick=()=>adminUserProfileModal(state.userDirectory.find(user=>user.user_id===Number(button.dataset.directoryProfile))));
  $$("[data-directory-delete]").forEach(button=>button.onclick=async()=>{const user=state.userDirectory.find(item=>item.user_id===Number(button.dataset.directoryDelete));if(!user)return;const confirmation=prompt(`Delete ${user.name} and all project allocations? Type their email to confirm:`);if(confirmation!==user.email){if(confirmation!==null)toast("Email confirmation did not match",true);return}try{await api(`/admin/users/${user.user_id}`,{method:"DELETE"});state.userDirectory=state.userDirectory.filter(item=>item.user_id!==user.user_id);state.members=state.members.filter(item=>item.user_id!==user.user_id);state.teamMembers=state.teamMembers.filter(item=>item.user_id!==user.user_id);render();toast("User deleted")}catch(err){toast(err.message,true)}})
}
function openChatMessageMenu(trigger) {
  const messageId=Number(trigger.dataset.deleteMessage),message=state.chatMessages.find(item=>item.id===messageId);
  if(!message)return;
  const existing=trigger.parentElement.querySelector(".chat-message-actions");
  $$(".chat-message-actions").forEach(menu=>menu.remove());
  if(existing)return;
  const menu=document.createElement("div");
  menu.className="chat-message-actions";
  const canDelete=!message.is_deleted&&(message.sender.id===state.user?.id||isAdmin());
  menu.innerHTML=`<button type="button" data-message-reply>↩ <span>Reply</span></button>${canDelete?'<button type="button" class="danger" data-message-delete>⌫ <span>Delete</span></button>':""}`;
  trigger.parentElement.append(menu);
  menu.querySelector("[data-message-reply]").onclick=event=>{
    event.stopPropagation();
    const input=$("#chat-body"),form=$("#chat-form");
    if(!input||!form)return;
    const excerpt=message.body.replace(/\s+/g," ").trim().slice(0,120);
    input.value=`Replying to ${message.sender.name}:\n> ${excerpt}${message.body.length>120?"…":""}\n\n`;
    let preview=form.querySelector(".chat-reply-preview");
    if(!preview){preview=document.createElement("div");preview.className="chat-reply-preview";form.prepend(preview)}
    preview.innerHTML=`<span><strong>Replying to ${esc(message.sender.name)}</strong><small>${esc(excerpt)}</small></span><button type="button" aria-label="Cancel reply">×</button>`;
    preview.querySelector("button").onclick=()=>{preview.remove();input.value="";input.focus()};
    input.focus();input.setSelectionRange(input.value.length,input.value.length);menu.remove();
  };
  const deleteAction=menu.querySelector("[data-message-delete]");
  if(deleteAction)deleteAction.onclick=async event=>{
    event.stopPropagation();
    if(!confirm("Delete this message? The chat will keep a deleted-message record."))return;
    const button=event.currentTarget;button.disabled=true;
    try{const deleted=await api(`/workspaces/${state.workspace.id}/chat/conversations/${state.activeChatId}/messages/${messageId}`,{method:"DELETE"});state.chatMessages=state.chatMessages.map(item=>item.id===deleted.id?deleted:item);render();toast("Message deleted")}catch(err){button.disabled=false;toast(err.message,true)}
  };
}

function bindView() {
  $("#empty-workspace")?.addEventListener("click",workspaceModal);
  $("#notification-refresh")?.addEventListener("click",()=>loadNotifications(true).catch(err=>toast(err.message,true)));
  $("#new-chat")?.addEventListener("click",newChatModalV2);
  $("#chat-create-workspace")?.addEventListener("click",workspaceModal);
  $("#chat-refresh")?.addEventListener("click",()=>loadChats().catch(err=>toast(err.message,true)));
  const activeConversation=state.chatConversations.find(item=>item.id===state.activeChatId),chatHeader=$(".chat-room>header");
  if(activeConversation?.can_clear&&chatHeader){
    const clearButton=document.createElement("button");
    clearButton.id="clear-chat";clearButton.type="button";clearButton.className="clear-chat-button";clearButton.textContent="Clear all chat";
    const monitoring=chatHeader.querySelector(".chat-monitoring-label");
    if(monitoring){const actions=document.createElement("div");actions.className="chat-header-actions";monitoring.before(actions);actions.append(clearButton,monitoring)}else chatHeader.append(clearButton);
    clearButton.onclick=async()=>{
      if(!confirm("Are you sure you want to clear all messages from this conversation? This action cannot be undone."))return;
      clearButton.disabled=true;clearButton.textContent="Clearing…";
      try{await api(`/workspaces/${state.workspace.id}/chat/conversations/${activeConversation.id}/messages`,{method:"DELETE"});state.chatMessages=[];activeConversation.last_message=null;activeConversation.unread_count=0;render();toast("All messages cleared. You can start a fresh chat.")}catch(err){clearButton.disabled=false;clearButton.textContent="Clear all chat";toast(err.message,true)}
    };
  }
  $$('[data-chat-filter]').forEach(button=>button.onclick=()=>{state.chatFilter=button.dataset.chatFilter;render()});
  $("#chat-search")?.addEventListener("input",event=>{state.chatQuery=event.target.value;render();const input=$("#chat-search");input?.focus();input?.setSelectionRange(input.value.length,input.value.length)});
  $$('[data-delete-chat]').forEach(button=>button.onclick=async event=>{event.stopPropagation();const conversation=state.chatConversations.find(item=>item.id===Number(button.dataset.deleteChat));if(!conversation||!confirm(`Delete “${conversation.name}” and its complete message history?`))return;try{await api(`/workspaces/${state.workspace.id}/chat/conversations/${conversation.id}`,{method:"DELETE"});if(state.activeChatId===conversation.id)state.activeChatId=null;await loadChats();toast("Conversation deleted")}catch(err){toast(err.message,true)}});
  $$('[data-chat-id]').forEach(button=>button.onclick=async()=>{state.activeChatId=Number(button.dataset.chatId);try{state.chatMessages=await api(`/workspaces/${state.workspace.id}/chat/conversations/${state.activeChatId}/messages`);const active=state.chatConversations.find(item=>item.id===state.activeChatId);if(active)active.unread_count=0;updateChatCount();renderNotificationHeader();render()}catch(err){toast(err.message,true)}});
  $$('.chat-message:not(.deleted)').forEach(row=>{if(row.querySelector('[data-delete-message]'))return;const messageId=Number(row.dataset.messageId),meta=row.querySelector('div>span');if(!meta)return;const button=document.createElement('button');button.className='chat-message-menu';button.dataset.deleteMessage=messageId;button.title='Message options';button.textContent='⋮';meta.append(button)});
  $$('[data-delete-message]').forEach(button=>button.onclick=event=>{event.stopPropagation();openChatMessageMenu(button)});
  const chatForm=$("#chat-form"),chatInput=$("#chat-body"),chatSend=chatForm?$("button",chatForm):null;
  if(chatForm&&chatInput&&chatSend){const sendChat=async()=>{const body=chatInput.value.trim();if(!body||chatSend.disabled)return;chatSend.disabled=true;chatSend.textContent="Sending...";try{const workspaceId=state.workspace?.id,conversationId=state.activeChatId;if(!workspaceId||!conversationId)throw new Error("Select an available conversation");const sent=await api(`/workspaces/${workspaceId}/chat/conversations/${conversationId}/messages`,{method:"POST",body:JSON.stringify({body})});state.chatMessages.push(sent);const active=state.chatConversations.find(item=>item.id===conversationId);if(active)active.last_message=sent;render();api(`/workspaces/${workspaceId}/chat/conversations`).then(items=>{state.chatConversations=items;updateChatCount();renderNotificationHeader()}).catch(()=>{})}catch(err){chatSend.disabled=false;chatSend.textContent="Send";toast(err.message,true)}};chatSend.type="button";chatSend.onclick=sendChat;chatForm.onsubmit=event=>{event.preventDefault();sendChat()};chatInput.onkeydown=event=>{if(event.key==="Enter"&&!event.shiftKey){event.preventDefault();sendChat()}}}
  if(chatInput)chatInput.oninput=()=>{chatInput.style.height="auto";chatInput.style.height=`${Math.min(chatInput.scrollHeight,150)}px`};
  const chatMessages=$("#chat-messages");if(chatMessages)chatMessages.scrollTop=chatMessages.scrollHeight;
  $("#chat-scroll-top")?.addEventListener("click",()=>chatMessages?.scrollTo({top:0,behavior:"smooth"}));
  $("#chat-scroll-bottom")?.addEventListener("click",()=>chatMessages?.scrollTo({top:chatMessages.scrollHeight,behavior:"smooth"}));
  $$('[data-notification-ack]').forEach(button=>button.onclick=async()=>{try{await api(`/notifications/${button.dataset.notificationAck}/acknowledge`,{method:"PATCH"});await loadNotifications(true);toast("Reminder acknowledged")}catch(err){toast(err.message,true)}});
  $$('[data-notification-read]').forEach(button=>button.onclick=async()=>{try{await api(`/notifications/${button.dataset.notificationRead}/read`,{method:"PATCH"});await loadNotifications(true)}catch(err){toast(err.message,true)}});
  $$('[data-notification-task]').forEach(button=>button.onclick=async()=>{
    const notification=state.notifications.find(item=>item.id===Number(button.dataset.notificationTask));if(!notification)return;
    try{
      const workspace=state.workspaces.find(item=>item.id===notification.workspace_id);if(!workspace)throw new Error("Workspace is no longer available");
      if(state.workspace?.id!==workspace.id){state.workspace=workspace;state.project=null;localStorage.setItem("orbit_workspace",workspace.id);updateWorkspaceUI();await loadWorkspace()}
      state.project=state.projects.find(item=>item.id===notification.project_id);if(!state.project)throw new Error("Project is no longer available");
      localStorage.setItem(`orbit_project_${workspace.id}`,state.project.id);navigate("board");await loadProject();render();await taskDetail(notification.task_id);
    }catch(err){toast(err.message,true)}
  });
  $$('[data-notification-chat]').forEach(button=>button.onclick=async()=>{const notification=state.notifications.find(item=>String(item.id)===button.dataset.notificationChat);if(!notification)return;try{const workspace=state.workspaces.find(item=>item.id===notification.workspace_id);if(!workspace)throw new Error("Workspace is no longer available");if(state.workspace?.id!==workspace.id){state.workspace=workspace;localStorage.setItem("orbit_workspace",workspace.id);updateWorkspaceUI();await loadWorkspace()}state.activeChatId=notification.conversation_id;await api(`/notifications/${notification.id}/read`,{method:"PATCH"}).catch(()=>{});navigate("chat");await loadChats()}catch(err){toast(err.message,true)}});
  $("#report-refresh")?.addEventListener("click", async () => { try { await loadProject(); render(); toast("Project report refreshed"); } catch (err) { state.projectLoading=false; toast(err.message,true); } });
  bindSkillsView();
  bindPeoplePagination();
  $$("[data-go]").forEach(x=>x.onclick=()=>navigate(x.dataset.go));
  $$("[data-project]").forEach(x=>x.onclick=async()=>{
    const project=state.projects.find(p=>p.id===Number(x.dataset.project));
    if(!project)return;
    state.project=project;
    localStorage.setItem(`orbit_project_${state.workspace.id}`,state.project.id);
    navigate("board");
    try{await loadProject();render()}catch(err){state.projectLoading=false;toast(`Could not open project: ${err.message}`,true)}
  });
  $$("[data-people-workspace]").forEach(button=>button.onclick=async()=>{
    const workspace=state.workspaces.find(item=>item.id===Number(button.dataset.peopleWorkspace));
    if(!workspace||workspace.id===state.workspace?.id)return;
    state.workspace=workspace;state.project=null;state.projects=[];state.tasks=[];state.sprints=[];state.board=null;state.dashboard=null;state.members=[];state.teams=[];state.teamMembers=[];state.designations=[];state.departments=[];state.userDirectory=[];state.skillCatalog=[];state.skillMembers=[];
    localStorage.setItem("orbit_workspace",workspace.id);updateWorkspaceUI();await loadWorkspace();
  });
  $$("[data-edit-project]").forEach(button=>button.onclick=event=>{event.stopPropagation();projectEditModal(state.projects.find(project=>project.id===Number(button.dataset.editProject)))});
  $("#new-project")?.addEventListener("click", projectModal); $("#new-task-view")?.addEventListener("click",()=>taskModal());
  $("#gantt-new-task")?.addEventListener("click",()=>taskModal());
  $("#new-sprint")?.addEventListener("click", sprintModal); $("#add-member")?.addEventListener("click", memberModal); $("#new-team")?.addEventListener("click",()=>teamModal());
  $$("[data-edit-sprint]").forEach(button=>button.onclick=()=>sprintModal(state.sprints.find(sprint=>sprint.id===Number(button.dataset.editSprint))));
  $("#project-select")?.addEventListener("change", async e=>{state.project=state.projects.find(p=>p.id===Number(e.target.value));localStorage.setItem(`orbit_project_${state.workspace.id}`,state.project.id);try{await loadProject();render()}catch(err){state.projectLoading=false;toast(err.message,true)}});
  $("#sprint-filter")?.addEventListener("change", e=>{const value=e.target.value;$$(".task-card").forEach(card=>{const task=state.tasks.find(t=>t.id===Number(card.dataset.task));card.classList.toggle("hidden",value==="backlog"?task.sprint_id!==null:Boolean(value)&&task.sprint_id!==Number(value))})});
  $$("[data-task]").forEach(x=>x.onclick=()=>taskDetail(Number(x.dataset.task)));
  $$("[data-task-complete]").forEach(input=>input.onclick=async event=>{
    event.stopPropagation();
    const completed=input.checked;
    input.disabled=true;
    try{
      await api(`/tasks/${input.dataset.taskComplete}/completion`,{method:"PATCH",body:JSON.stringify({is_completed:completed})});
      await loadWorkspace();
      toast(completed?"Task moved to the last list":"Task reopened in the first list");
    }catch(error){input.checked=!completed;input.disabled=false;toast(error.message,true)}
  });
  $$("[data-add-to]").forEach(x=>x.onclick=()=>taskModal(null,Number(x.dataset.addTo)));
  $$("[data-column-menu]").forEach(x=>x.onclick=e=>{e.stopPropagation();columnModal(Number(x.dataset.columnMenu))});
  $("#add-column")?.addEventListener("click",()=>columnModal());
  $("#customize-board")?.addEventListener("click",boardSettingsModal);
  $("#ai-plan-tasks")?.addEventListener("click",aiTaskPlannerModal);
  $("#export-board-pdf")?.addEventListener("click",exportBoardPdf);
  $("#export-gantt-pdf")?.addEventListener("click",exportGanttPdf);
  bindProfileView();
  ["#user-search","#user-department-filter","#user-designation-filter","#user-project-filter"].forEach(selector=>$(selector)?.addEventListener(selector==="#user-search"?"input":"change",filterUserDirectory));
  $("#reset-user-filters")?.addEventListener("click",()=>{state.selectedProfileUsers.clear();state.userDirectoryPage=1;state.filteredUserDirectory=state.userDirectory;render();toast("User filters and selections reset")});
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

function workspaceModal() { if(!state.user?.is_system_admin){toast("Only the system administrator can create workspaces",true);return}$("#workspace-menu").classList.add("hidden"); modal(formShell("Create workspace","A shared home for your projects and team.",`
  ${field("name","Workspace name","text","e.g. Product team",true)}${field("description","Description","textarea","What will your team work on?")}`,"Create workspace"),()=>$("#modal-form").onsubmit=async e=>submitForm(e,async data=>{
    const w=await api("/workspaces",{method:"POST",body:JSON.stringify(data)});state.workspaces.unshift(w);state.workspace=w;localStorage.setItem("orbit_workspace",w.id);updateWorkspaceUI();await loadWorkspace();toast("Workspace created");
  }));}
function workspaceSettingsModal(){
  $("#workspace-menu").classList.add("hidden");
  if(!state.user?.is_system_admin){toast("Only the system administrator can update or delete workspaces",true);return}
  const workspace=activeWorkspace();
  if(!workspace)return;
  modal(`<h2>Workspace settings</h2><p class="subtitle">Manage ${esc(workspace.name)}.</p>
    <form id="workspace-edit-form"><div class="form-grid">${field("name","Workspace name","text","Workspace name",true,false,workspace.name)}${field("description","Description","textarea","What does this workspace contain?","",true,workspace.description)}</div>
    <div class="modal-actions"><button class="btn primary">Save workspace</button></div></form>
    <h3 class="settings-section-title">Danger zone</h3>
    <div class="danger-zone"><h3>Delete workspace</h3><p>This permanently deletes its projects, sprints, tasks, comments, teams, and board settings.</p><label class="danger-confirm"><span>Type <strong>${esc(workspace.name)}</strong> to confirm</span><input id="delete-workspace-name" type="text" autocomplete="off" placeholder="${esc(workspace.name)}" aria-describedby="delete-workspace-help"></label><small id="delete-workspace-help">The workspace name must match exactly.</small><button id="delete-workspace" type="button" class="btn danger" disabled>Delete workspace permanently</button></div>
    <div id="modal-error" class="form-error hidden"></div>`,()=>{
      $("#workspace-edit-form").onsubmit=async event=>{
        event.preventDefault();const error=$("#modal-error");
        try{
          const updated=await api(`/workspaces/${workspace.id}`,{method:"PATCH",body:JSON.stringify(formData(event.currentTarget))});
          state.workspaces=state.workspaces.map(item=>item.id===updated.id?updated:item);state.workspace=updated;updateWorkspaceUI();closeModal();render();toast("Workspace updated");
        }catch(err){error.textContent=err.message;error.classList.remove("hidden")}
      };
      const deleteInput=$("#delete-workspace-name"),deleteButton=$("#delete-workspace");
      if(deleteInput&&deleteButton){
        deleteInput.addEventListener("input",()=>{deleteButton.disabled=deleteInput.value!==workspace.name});
        deleteButton.addEventListener("click",async()=>{
          const error=$("#modal-error");deleteButton.disabled=true;deleteButton.textContent="Deleting…";
          try{
          await api(`/workspaces/${workspace.id}`,{method:"DELETE",body:JSON.stringify({workspace_name:deleteInput.value})});
          state.workspaces=state.workspaces.filter(item=>item.id!==workspace.id);
          state.workspace=state.workspaces[0]||null;state.project=null;state.projects=[];state.tasks=[];state.sprints=[];state.board=null;
          if(state.workspace)localStorage.setItem("orbit_workspace",state.workspace.id);else localStorage.removeItem("orbit_workspace");
          closeModal();updateWorkspaceUI();
          if(state.workspace)await loadWorkspace();else renderNoWorkspace();
          toast("Workspace deleted");
          }catch(err){deleteButton.disabled=deleteInput.value!==workspace.name;deleteButton.textContent="Delete workspace permanently";error.textContent=err.message;error.classList.remove("hidden")}
        });
      }
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
  ${field("start_date","Start date","date","",true)}${field("end_date","End date","date","",true)}${field("budget","Budget","number","Optional")}`,"Create project"),()=>$("#modal-form").onsubmit=async e=>submitForm(e,async data=>{
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
    ${field("start_date","Start date","date","",true,false,project.start_date)}
    ${field("end_date","End date","date","",true,false,project.end_date)}
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
        confirmAction({title:"Delete project",message:`Delete ${project.name}, including its tasks, sprints, board, comments, and allocations.`,confirmLabel:"Delete project",confirmationText:project.name},async()=>{
          await api(`/projects/${project.id}`,{method:"DELETE"});
          const deletedCurrent=state.project?.id===project.id;
          state.projects=state.projects.filter(item=>item.id!==project.id);
          if(deletedCurrent)state.project=null;
          closeModal();
          await loadWorkspace();
          if(state.project)localStorage.setItem(`orbit_project_${state.workspace.id}`,state.project.id);
          else localStorage.removeItem(`orbit_project_${state.workspace.id}`);
          toast("Project deleted");
        },()=>projectEditModal(project));
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
    const members=userIds.map(id=>state.members.find(m=>m.user_id===id)||(()=>{const user=state.userDirectory.find(item=>item.user_id===id);return user?{user_id:id,user}:null})()).filter(Boolean);
    return members.map(m=>`<label><input type="checkbox" name="assignee_ids" value="${m.user_id}" ${currentAssignees.includes(m.user_id)?"checked":""}><span class="avatar">${esc(m.user.name.slice(0,2).toUpperCase())}</span><span>${esc(m.user.name)}<small>${esc(projectAllocations.find(a=>a.team_id===Number(teamId)&&a.user_id===m.user_id)?.designation||"")}</small></span></label>`).join("")||`<span class="subtitle">No members are allocated to this team for ${esc(state.project.name)}.</span>`;
  };
  modal(formShell(task?"Edit task":"Create a task",task?"Update task details and progress.":`Add work to ${esc(state.project.name)}.`,`
  ${field("title","Task title","text","What needs to be done?",true,false,task?.title)}${field("description","Description","textarea","Add context and acceptance criteria","",true,task?.description)}
  ${selectField("status","Status",STATUS.map(x=>x[0]),task?.status||"backlog")}${selectField("priority","Priority",["low","medium","high","critical"],task?.priority||"medium")}
  ${state.board?.framework==="scrum"?`<div class="field full"><label>Sprint · ${esc(state.project.name)}</label><div class="inline-control"><select name="sprint_id"><option value="">Product backlog</option>${state.sprints.map(s=>`<option value="${s.id}" ${s.id===task?.sprint_id?"selected":""}>${s.is_active?"● Active · ":""}${esc(s.name)}</option>`).join("")}</select><button type="button" id="show-quick-sprint" class="btn">＋ New sprint</button></div><div id="quick-sprint-row" class="quick-sprint-row hidden"><input id="quick-sprint-name" placeholder="Sprint name, e.g. Sprint 01"><button type="button" id="create-quick-sprint" class="btn primary">Create</button></div><small class="field-help">${state.sprints.length?`${state.sprints.length} sprint${state.sprints.length===1?"":"s"} in this project`:"No sprints yet — create one here or from the Sprints page."}</small></div>`:""}
  <label class="field full">Assignment team<select id="task-team-select" name="assignment_team_id"><option value="">Select a team first</option>${assignmentTeams.map(team=>`<option value="${team.id}" ${team.id===selectedTeamId?"selected":""}>${esc(team.name)}</option>`).join("")}</select><small class="field-help">Members must be allocated to this team and project before they can be assigned.</small></label>
  <fieldset class="field full assignee-field"><legend>Assignees · select multiple</legend><div id="task-assignee-options" class="assignee-options">${assigneeOptions(selectedTeamId)}</div>${isAdmin()?'<button type="button" id="manage-team-allocations" class="team-management-link">Manage team allocations <span>→</span></button>':""}</fieldset>
  ${field("story_points","Story points","number","0–100","",false,task?.story_points)}${field("due_date","Due date","date","","",false,task?.due_date)}
  ${field("start_at","Start date & time","datetime-local","","",false,inputDateTime(task?.start_at))}${field("end_at","End date & time","datetime-local","","",false,inputDateTime(task?.end_at))}
  <div class="field full project-date-rule"><strong>Allowed project dates</strong><span>${date(state.project.start_date)} → ${date(state.project.end_date)}. Dates outside this range cannot be saved.</span></div>
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
    $("#manage-team-allocations")?.addEventListener("click",()=>{closeModal();navigate("people");toast("Allocate members to this team and project, then return to the task")});
    $("#modal-form").onsubmit=async e=>submitForm(e,async data=>{
      const dateOnly=value=>value?value.slice(0,10):null,start=dateOnly(data.start_at)||data.start_date,end=dateOnly(data.end_at)||data.due_date;
      if((start&&start<state.project.start_date)||(end&&end>state.project.end_date)||(start&&end&&end<start))throw new Error(`Task dates must be between ${date(state.project.start_date)} and ${date(state.project.end_date)}`);
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
  const managers=state.userDirectory.filter(user=>user.is_active&&user.is_member&&user.professional_title&&(user.completion_percent||0)>=50);
  if(!managers.length||!state.designations.length){toast("Add a designation and approve at least one registered user before creating a team",true);return}
  modal(formShell(team?"Edit team":"Create a team",team?"Update the global team, manager and purpose.":"Create a global team that can later be allocated to projects.",`${field("name","Team name","text","e.g. Design",true,false,team?.name)}${field("description","Description","textarea","What does this team own?",false,true,team?.description)}${selectField("manager_user_id","Team manager",managers.map(user=>[user.user_id,`${user.name} · ${user.professional_title}`]),team?.manager_user_id||managers[0]?.user_id)}<div class="field full reminder-compose-note"><strong>Manager designation</strong><span id="team-manager-designation">The selected member's designation is assigned automatically.</span></div>`,team?"Save changes":"Create team"),()=>{const form=$("#modal-form"),manager=form.elements.manager_user_id,label=$("#team-manager-designation"),update=()=>{const user=managers.find(item=>item.user_id===Number(manager.value));label.textContent=user?user.professional_title:"Select a manager"};manager.onchange=update;update();form.onsubmit=async e=>submitForm(e,async data=>{data.manager_user_id=Number(data.manager_user_id);const base=state.user?.is_system_admin?"/admin/teams":`/workspaces/${state.workspace.id}/teams`,saved=await api(team?`${base}/${team.id}`:base,{method:team?"PATCH":"POST",body:JSON.stringify(data)});if(team)state.teams=state.teams.map(item=>item.id===saved.id?saved:item);else state.teams.unshift(saved);toast(team?"Team updated":"Team created")})});
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
  const staffedTeams=state.teams.filter(team=>state.teamMembers.some(member=>member.team_id===team.id&&member.project_id===state.project.id));
  if(!staffedTeams.length){toast("Allocate at least one member to a team for this project before AI planning",true);return}
  modal(formShell("Plan tasks with AI",`Describe the outcome you want for ${esc(state.project.name)}. You will review every task before it is created.`,`
    ${field("prompt","What should this project deliver?","textarea","Example: Build a secure mobile application with authentication, payments, testing, and deployment.",true,true)}
    ${selectField("team_id","Delivery team",staffedTeams.map(team=>[team.id,team.name]))}
    ${field("maximum_tasks","Maximum tasks","number","20",true,false,20)}
    <div class="field full ai-note"><strong>Budget-aware schedule</strong><span>AI distributes tasks between ${date(state.project.start_date)} and ${date(state.project.end_date)}, assigns the selected team, and apportions the available delivery budget after the ${state.project.contingency_percent||15}% contingency reserve.</span></div>
    <div id="ai-plan-status" class="ai-plan-status hidden" role="status" aria-live="polite"><i></i><span>Contacting AI providers and building your task plan...</span></div>`,
    "Generate task plan"),()=>{
      const form=$("#modal-form");
      const maximum=$('[name="maximum_tasks"]',form);
      const button=$("button.primary",form);
      maximum.min="1";maximum.max="20";
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
            body:JSON.stringify({prompt:values.prompt,team_id:Number(values.team_id),maximum_tasks:Number(values.maximum_tasks)})
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
            <label>Start date<input class="ai-task-start" type="date" min="${state.project.start_date}" max="${state.project.end_date}" value="${task.start_date||state.project.start_date}" required></label>
            <label>End date<input class="ai-task-end" type="date" min="${state.project.start_date}" max="${state.project.end_date}" value="${task.end_date||state.project.end_date}" required></label>
          </div>
          <input class="ai-task-hours" type="hidden" value="${task.estimated_hours??""}"><input class="ai-task-budget" type="hidden" value="${task.planned_budget??""}"><input class="ai-task-assignees" type="hidden" value="${(task.assignee_ids||[]).join(",")}">
          <label class="ai-checklist-label">Checklist · one item per line<textarea class="ai-task-checklist" placeholder="Verify acceptance criteria\nComplete review">${esc((task.checklist||[]).join("\n"))}</textarea></label>
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
            story_points:$(".ai-task-points",row).value===""?null:Number($(".ai-task-points",row).value),
            estimated_hours:$(".ai-task-hours",row).value===""?null:Number($(".ai-task-hours",row).value),
            planned_budget:$(".ai-task-budget",row).value===""?null:Number($(".ai-task-budget",row).value),
            assignee_ids:$(".ai-task-assignees",row).value?$(".ai-task-assignees",row).value.split(",").map(Number):[],
            start_date:$(".ai-task-start",row).value,
            end_date:$(".ai-task-end",row).value,
            checklist:$(".ai-task-checklist",row).value.split("\n").map(value=>value.trim()).filter(Boolean)
          }));
        if(!tasks.length){error.textContent="Select at least one task.";error.classList.remove("hidden");return}
        if(tasks.some(task=>task.title.length<2)){error.textContent="Every selected task needs a title.";error.classList.remove("hidden");return}
        if(tasks.some(task=>!task.start_date||!task.end_date||task.start_date<state.project.start_date||task.end_date>state.project.end_date||task.end_date<task.start_date)){error.textContent=`Every task must be scheduled between ${date(state.project.start_date)} and ${date(state.project.end_date)}.`;error.classList.remove("hidden");return}
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
  if(!isAdmin())return emptyMini("Admin access required","Only workspace admins can manage people and teams.");
  const admin=isAdmin();
  const adminWorkspaces=state.workspaces.filter(workspace=>workspace.role==="admin"||workspace.owner_id===state.user.id);
  const directory=state.userDirectory.filter(user=>user.is_member);
  const action=`<span class="member-count">${directory.length} registered</span>`;
  return `${pageHeading("People & teams","Member and administrator directory with project allocations.",action)}
  ${adminWorkspaces.length?`<div class="people-workspace-switcher"><span>Project allocation workspace</span>${adminWorkspaces.map(workspace=>`<button data-people-workspace="${workspace.id}" class="${workspace.id===state.workspace?.id?"active":""}">${esc(workspace.name)}</button>`).join("")}</div>`:""}
  <div class="people-grid"><section class="panel global-members-panel"><div class="panel-header"><h3>Members and admins</h3><span class="member-count">${directory.length}</span></div><div class="panel-search"><input id="global-member-search" placeholder="Search member name or email"><button id="global-member-search-button" type="button">Reset</button></div>
    ${directory.map(user=>{const projectCount=new Set(state.teamMembers.filter(a=>a.user_id===user.user_id).map(a=>a.project_id)).size;const access=user.role?pretty(user.role):user.is_active?"Registered":"Pending";return `<div class="member-row"><button class="member-profile-trigger" data-member-details="${user.user_id}" aria-label="View ${esc(user.name)}'s project assignments">${avatar(user)}<span class="member-copy"><strong>${esc(user.name)}</strong><small>${esc(user.email)}</small><span class="member-professional">${esc([user.professional_title,user.department].filter(Boolean).join(" · ")||"Professional details not set")}</span><span class="project-count">${projectCount} project${projectCount===1?"":"s"} in this workspace</span></span></button><span class="badge ${user.role||""}">${access}</span><button class="edit-action member-edit-action" data-global-member-profile="${user.user_id}">Edit details</button></div>`}).join("")}
  </section><section class="panel"><div class="panel-header"><h3>Teams</h3>${admin?'<button id="new-team">＋ New team</button>':`<span class="member-count">${state.teams.length}</span>`}</div>
    ${state.teams.length?state.teams.map(t=>{const allocations=state.teamMembers.filter(item=>item.team_id===t.id);return `<article class="team-card"><div class="team-card-head"><div><h4>${esc(t.name)}</h4><p>${esc(t.description||"No description")}</p>${t.manager_user?`<div class="team-manager"><b class="avatar">${esc(t.manager_user.name.slice(0,2).toUpperCase())}</b><span><small>TEAM MANAGER</small><strong>${esc(t.manager_user.name)}</strong><em>${esc(t.manager_designation)}</em></span></div>`:`<span class="manager-missing">Manager not assigned · use Edit</span>`}</div>${admin?`<div class="team-actions"><button data-allocate-team="${t.id}">＋ Allocate</button><button class="edit-action" data-edit-team="${t.id}">✎ Edit</button><button class="remove-action" data-delete-team="${t.id}">Delete</button></div>`:""}</div><div class="team-member-list">${allocations.length?allocations.map(a=>`<div class="team-member-row"><b class="avatar">${esc(a.user.name.slice(0,2).toUpperCase())}</b><div><strong>${esc(a.user.name)}</strong><small>${esc(a.designation)} · ${esc(a.project.name)}</small></div>${admin?`<button class="remove-action" data-remove-allocation="${a.id}" data-team-id="${t.id}">Remove</button>`:""}</div>`).join(""):'<p class="team-empty">No allocated members yet.</p>'}</div></article>`}).join(""):emptyMini("No teams yet","Create a team for a focused group.")}
  </section><section class="panel designation-panel"><div class="panel-header"><h3>Designations by department</h3>${admin?'<button id="new-designation">＋ Add designation</button>':`<span class="member-count">${state.designations.length}</span>`}</div><div class="designation-list">${state.designations.length?state.designations.map(item=>`<div class="designation-row"><div><strong>${esc(item.name)}</strong><small>${esc(item.department_name||"Legacy · department not assigned")} · ${esc(item.description||"No description")}</small></div>${admin?`<div><button data-edit-designation="${item.id}">Edit</button><button class="remove-action" data-delete-designation="${item.id}">Delete</button></div>`:""}</div>`).join(""):emptyMini("No designations yet","Create a department, then add its job roles.")}</div></section><section class="panel designation-panel"><div class="panel-header"><h3>Departments</h3>${admin?'<button id="new-department">＋ Add department</button>':`<span class="member-count">${state.departments.length}</span>`}</div><div class="designation-list">${state.departments.length?state.departments.map(item=>{const count=state.designations.filter(role=>role.department_id===item.id).length;return `<div class="designation-row"><div><strong>${esc(item.name)}</strong><small>${count} designation${count===1?"":"s"} · ${esc(item.description||"No description")}</small></div>${admin?`<div><button data-edit-department="${item.id}">Edit</button><button class="remove-action" data-delete-department="${item.id}">Delete</button></div>`:""}</div>`}).join(""):emptyMini("No departments yet","Add departments such as IT, Management, Accounts or Marketing.")}</div></section></div>`;
}

function bindPeoplePagination(){
  const memberPanel=$(".global-members-panel");
  if(!memberPanel)return;
  const memberHeading=$(".panel-header h3",memberPanel);if(memberHeading)memberHeading.textContent="Members and admins";
  const teamPanel=memberPanel.nextElementSibling;
  teamPanel.classList.add("teams-panel");
  if(!$("#team-search",teamPanel)){
    const search=document.createElement("div");
    search.className="panel-search";
    search.innerHTML='<input id="team-search" placeholder="Search team, manager or member"><button id="team-search-button" type="button">Reset</button>';
    $(".panel-header",teamPanel).after(search);
  }
  const ensurePager=(panel,id)=>{
    let pager=document.getElementById(id);
    if(!pager){pager=document.createElement("div");pager.id=id;pager.className="panel-pagination";panel.append(pager)}
    return pager;
  };
  const setup=(panel,itemSelector,inputId,buttonId,pagerId)=>{
    const input=document.getElementById(inputId),button=document.getElementById(buttonId),pager=ensurePager(panel,pagerId);
    let query="",page=1;
    const apply=()=>{
      const all=$$(itemSelector,panel),matches=all.filter(item=>!query||item.textContent.toLowerCase().includes(query));
      const pages=Math.max(1,Math.ceil(matches.length/10));page=Math.min(page,pages);
      all.forEach(item=>item.classList.add("pagination-hidden"));
      matches.slice((page-1)*10,page*10).forEach(item=>item.classList.remove("pagination-hidden"));
      pager.innerHTML=matches.length>10?`<button data-page="${page-1}" ${page===1?"disabled":""}>Previous</button><span>Page ${page} of ${pages} · ${matches.length} results</span><button data-page="${page+1}" ${page===pages?"disabled":""}>Next</button>`:`<span>${matches.length} result${matches.length===1?"":"s"}</span>`;
      $$('[data-page]',pager).forEach(control=>control.onclick=()=>{page=Number(control.dataset.page);apply()});
    };
    const search=()=>{query=input.value.trim().toLowerCase();page=1;apply()};
    button.onclick=()=>{input.value="";search()};input.onkeydown=event=>{if(event.key==="Enter"){event.preventDefault();search()}};input.oninput=search;
    apply();
  };
  setup(memberPanel,".member-row","global-member-search","global-member-search-button","global-member-pagination");
  setup(teamPanel,".team-card","team-search","team-search-button","team-pagination");
}

function memberDetailsModal(userId){
  const member=state.userDirectory.find(user=>user.user_id===userId);
  if(!member)return;
  const assignments=state.teamMembers.filter(a=>a.user_id===userId);
  const projectCount=new Set(assignments.map(a=>a.project_id)).size;
  const assignmentRows=assignments.length?assignments.map(a=>{
    const team=state.teams.find(t=>t.id===a.team_id);
    return `<div class="member-assignment"><div><strong>${esc(a.project.name)}</strong><small>${esc(team?.name||"Team")}</small></div><span>${esc(a.designation)}</span></div>`;
  }).join(""):`<div class="member-assignments-empty"><strong>No project assignments yet</strong><p>This member has not been allocated to a team and project.</p></div>`;
  modal(`<div class="member-detail-head">${avatar(member)}<div><h2>${esc(member.name)}</h2><p>${esc(member.email)}</p></div></div><div class="member-detail-summary"><div><strong>${projectCount}</strong><span>Project${projectCount===1?"":"s"}</span></div><div><strong>${assignments.length}</strong><span>Assignment${assignments.length===1?"":"s"}</span></div><div><strong>${member.role?pretty(member.role):"Registered"}</strong><span>This workspace</span></div></div><h3 class="member-assignment-title">Project designations</h3><div class="member-assignment-list">${assignmentRows}</div>`);
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
  const activeUsers=state.userDirectory.filter(user=>user.is_active&&user.is_member),eligible=activeUsers.filter(user=>(user.completion_percent||0)>=50),incomplete=activeUsers.filter(user=>(user.completion_percent||0)<50);
  if(!state.projects.length){toast("Create a project first",true);return}
  if(!eligible.length){toast("No members meet the minimum 50% profile completion required for allocation.",true);return}
  if(!state.designations.length){toast("Add a designation before allocating members",true);designationModal();return}
  modal(formShell("Allocate team member","Only active Members or Admins with at least 50% profile completion are eligible.",`${selectField("user_id","Member",eligible.map(user=>[user.user_id,`${user.name} · ${user.completion_percent||0}%`]))}${selectField("project_id","Project",state.projects.map(p=>[p.id,p.name]))}${selectField("designation","Designation",state.designations.map(item=>[item.name,item.name]))}${incomplete.length?`<div class="field full allocation-profile-warning"><strong>${incomplete.length} member${incomplete.length===1?" is":"s are"} below 50%</strong><span>${incomplete.map(user=>`${esc(user.name)} (${user.completion_percent||0}%)`).join(", ")}</span></div>`:""}`,"Allocate member"),()=>$("#modal-form").onsubmit=async e=>submitForm(e,async data=>{
    data.user_id=Number(data.user_id);data.project_id=Number(data.project_id);
    const allocation=await api(`/workspaces/${state.workspace.id}/teams/${teamId}/members`,{method:"POST",body:JSON.stringify(data)});state.teamMembers.push(allocation);toast("Member allocated to project");
  }));
}

function editTeamAllocationModal(allocation){
  if(!allocation)return;
  modal(formShell("Edit team allocation",`Update ${esc(allocation.user.name)}'s project and designation. The member and team cannot be changed.`,`${selectField("project_id","Project",state.projects.map(project=>[project.id,project.name]),allocation.project_id)}${selectField("designation","Designation",state.designations.map(item=>[item.name,item.name]),allocation.designation)}`,"Save allocation"),()=>$("#modal-form").onsubmit=async event=>submitForm(event,async data=>{
    data.project_id=Number(data.project_id);
    const updated=await api(`/workspaces/${state.workspace.id}/teams/${allocation.team_id}/members/${allocation.id}`,{method:"PATCH",body:JSON.stringify(data)});
    state.teamMembers=state.teamMembers.map(item=>item.id===updated.id?updated:item);
    toast("Team allocation updated");
  }));
}

function designationModal(designation=null){
  if(!state.departments.length){toast("Create a department before adding a designation",true);departmentModal();return}
  modal(formShell(designation?"Edit designation":"Add designation",designation?"Update this department role across profiles and allocations.":"Create a designation under a department.",`${selectField("department_id","Department",state.departments.map(item=>[item.id,item.name]),designation?.department_id)}${field("name","Designation name","text","e.g. Mobile Developer",true,false,designation?.name)}${field("description","Description","textarea","Responsibilities or specialty",false,true,designation?.description)}`,designation?"Save changes":"Add designation"),()=>$("#modal-form").onsubmit=async event=>submitForm(event,async data=>{
    data.department_id=Number(data.department_id);
    const base=state.user?.is_system_admin?"/admin/designations":`/workspaces/${state.workspace.id}/designations`,saved=await api(designation?`${base}/${designation.id}`:base,{method:designation?"PATCH":"POST",body:JSON.stringify(data)});
    if(designation){state.designations=state.designations.map(item=>item.id===saved.id?saved:item);state.teamMembers.forEach(allocation=>{if(allocation.designation===designation.name)allocation.designation=saved.name})}else state.designations.push(saved);
    state.designations.sort((a,b)=>a.name.localeCompare(b.name));toast(designation?"Designation updated":"Designation added");
  }));
}

function departmentModal(department=null){
  modal(formShell(department?"Edit department":"Add department",department?"Update this department for workspace profiles.":"Create a reusable department for professional profiles.",`${field("name","Department name","text","e.g. IT, Management, Accounts",true,false,department?.name)}${field("description","Description","textarea","What does this department handle?",false,true,department?.description)}`,department?"Save changes":"Add department"),()=>$("#modal-form").onsubmit=async event=>submitForm(event,async data=>{
    const base=state.user?.is_system_admin?"/admin/departments":`/workspaces/${state.workspace.id}/departments`,saved=await api(department?`${base}/${department.id}`:base,{method:department?"PATCH":"POST",body:JSON.stringify(data)});
    if(department){state.departments=state.departments.map(item=>item.id===saved.id?saved:item);if(state.profile?.department===department.name)state.profile.department=saved.name}else state.departments.push(saved);
    state.departments.sort((a,b)=>a.name.localeCompare(b.name));toast(department?"Department updated":"Department added");
  }));
}

function bindAccessControls(){
  $$('[data-member-details]').forEach(button=>button.onclick=()=>memberDetailsModal(Number(button.dataset.memberDetails)));
  if(!isAdmin())return;
  $$("[data-global-member-profile]").forEach(button=>button.onclick=()=>addDirectoryUserModal(state.userDirectory.find(user=>user.user_id===Number(button.dataset.globalMemberProfile))));
  $$('[data-remove-allocation]').forEach(remove=>{
    if(remove.previousElementSibling?.matches('[data-edit-allocation]'))return;
    const edit=document.createElement('button');
    edit.className='edit-action allocation-edit-action';
    edit.dataset.editAllocation=remove.dataset.removeAllocation;
    edit.textContent='Edit';
    remove.before(edit);
  });
  $$('[data-edit-allocation]').forEach(button=>button.onclick=()=>editTeamAllocationModal(state.teamMembers.find(item=>item.id===Number(button.dataset.editAllocation))));
  $$("[data-edit-member-profile]").forEach(button=>button.onclick=()=>memberProfessionalModal(state.members.find(member=>member.id===Number(button.dataset.editMemberProfile))));
  $("#new-designation")?.addEventListener("click",()=>designationModal());
  $$("[data-edit-designation]").forEach(button=>button.onclick=()=>designationModal(state.designations.find(item=>item.id===Number(button.dataset.editDesignation))));
  $$("[data-delete-designation]").forEach(button=>button.onclick=async()=>{if(!confirm("Delete this designation? It will be cleared from affected profiles and team assignments."))return;try{const id=Number(button.dataset.deleteDesignation),base=state.user?.is_system_admin?"/admin/designations":`/workspaces/${state.workspace.id}/designations`;await api(`${base}/${id}`,{method:"DELETE"});state.designations=state.designations.filter(item=>item.id!==id);render();toast("Designation deleted and references cleared")}catch(err){toast(err.message,true)}});
  $("#new-department")?.addEventListener("click",()=>departmentModal());
  $$("[data-edit-department]").forEach(button=>button.onclick=()=>departmentModal(state.departments.find(item=>item.id===Number(button.dataset.editDepartment))));
  $$("[data-delete-department]").forEach(button=>button.onclick=async()=>{if(!confirm("Delete this department? Its designations will be deleted and affected profile/team designation fields will be cleared."))return;try{const id=Number(button.dataset.deleteDepartment),base=state.user?.is_system_admin?"/admin/departments":`/workspaces/${state.workspace.id}/departments`;await api(`${base}/${id}`,{method:"DELETE"});state.departments=state.departments.filter(item=>item.id!==id);state.designations=state.designations.filter(item=>item.department_id!==id);state.profile=await api("/auth/profile");render();toast("Department, designations and references cleared")}catch(err){toast(err.message,true)}});
  $$("[data-allocate-team]").forEach(button=>button.onclick=()=>teamAllocationModal(Number(button.dataset.allocateTeam)));
  $$("[data-edit-team]").forEach(button=>button.onclick=()=>teamModal(state.teams.find(team=>team.id===Number(button.dataset.editTeam))));
  $$("[data-delete-team]").forEach(button=>button.onclick=async()=>{if(!confirm("Delete this team and its allocations?"))return;try{const teamId=Number(button.dataset.deleteTeam),base=state.user?.is_system_admin?"/admin/teams":`/workspaces/${state.workspace.id}/teams`;await api(`${base}/${teamId}`,{method:"DELETE"});state.teams=state.teams.filter(t=>t.id!==teamId);state.teamMembers=state.teamMembers.filter(a=>a.team_id!==teamId);render();toast("Team deleted")}catch(err){toast(err.message,true)}});
  $$("[data-remove-allocation]").forEach(button=>button.onclick=async()=>{if(!confirm("Remove this member from the project team?"))return;try{const allocationId=Number(button.dataset.removeAllocation);await api(`/workspaces/${state.workspace.id}/teams/${button.dataset.teamId}/members/${allocationId}`,{method:"DELETE"});state.teamMembers=state.teamMembers.filter(a=>a.id!==allocationId);render();toast("Team member removed")}catch(err){toast(err.message,true)}});
  $$("[data-remove-member]").forEach(button=>button.onclick=async()=>{if(!confirm("Remove this member from the workspace and all teams?"))return;try{const memberId=Number(button.dataset.removeMember),member=state.members.find(m=>m.id===memberId);await api(`/workspaces/${state.workspace.id}/members/${memberId}`,{method:"DELETE"});state.members=state.members.filter(m=>m.id!==memberId);if(member)state.teamMembers=state.teamMembers.filter(a=>a.user_id!==member.user_id);render();toast("Workspace member removed")}catch(err){toast(err.message,true)}});
}
async function submitForm(event, action) {
  event.preventDefault(); const button=$('button[type="submit"],button.primary',event.target), error=$("#modal-error"); button.disabled=true;
  try { await action(formData(event.target)); closeModal(); render(); } catch(err) { error.textContent=err.message;error.classList.remove("hidden");button.disabled=false; }
}
if (state.token) boot(); else showAuth();

(() => {
  "use strict";

  let conversationId = null;
  let bootstrap = null;
  let sending = false;
  let conversationsLoaded = false;

  const element = (tag, className, text) => {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  };

  function displayAssistantText(value) {
    return String(value || "")
      .replace(/\\\*/g, "*")
      .replace(/^\s{0,3}#{1,6}\s*/gm, "")
      .replace(/\*\*/g, "")
      .replace(/__/g, "")
      .trim();
  }

  function renderAssistantContent(node, value) {
    const text = displayAssistantText(value);
    node.replaceChildren();
    if (!text) return;
    const sectionNames = new Set(["project health", "recommended focus", "delivery overview", "executive summary", "key risks", "next actions"]);
    let list = null;
    let firstContent = true;
    for (const rawLine of text.split(/\r?\n/)) {
      const line = rawLine.trim();
      if (!line) { list = null; continue; }
      if (line.startsWith("• ") || line.startsWith("- ")) {
        if (!list) { list = element("ul", "assistant-answer-list"); node.appendChild(list); }
        list.appendChild(element("li", "", line.slice(2).trim()));
        firstContent = false;
        continue;
      }
      list = null;
      const normalized = line.toLowerCase().replace(/\s+[—-].*$/, "").trim();
      if (firstContent) node.appendChild(element("h4", "assistant-answer-title", line));
      else if (sectionNames.has(normalized) || (/^[A-Z][A-Za-z ]{2,32}$/.test(line) && !/[.!?:]$/.test(line))) node.appendChild(element("h5", "assistant-answer-heading", line));
      else node.appendChild(element("p", "assistant-answer-paragraph", line));
      firstContent = false;
    }
  }

  function currentContext() {
    return {
      view: typeof state !== "undefined" ? state.view : null,
      workspace_id: state?.workspace?.id || null,
      project_id: state?.project?.id || null,
    };
  }

  function contextDescription() {
    const labels={dashboard:"Overview",projects:"Projects",board:"Task board",gantt:"Gantt chart",report:"Project report",notifications:"Notifications",chat:"Messages",people:"People & teams",profile:"My profile",skills:"Skills",analytics:"Team & member analytics",users:"Users"};
    const view = labels[state.view] || "Current page";
    return [state?.workspace?.name, state?.project?.name, view].filter(Boolean).join(" · ");
  }

  async function assistantApi(path, options = {}) {
    const response = await fetch(path, {
      ...options,
      headers: {"Content-Type":"application/json", Authorization:`Bearer ${state.token}`, ...(options.headers||{})},
    });
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      throw new Error(body.detail || "Orbit AI is temporarily unavailable");
    }
    return response;
  }

  function setAssistantError(message = "") {
    const error = document.querySelector("#assistant-error");
    if (error) error.textContent = message;
  }

  function addMessage(role, body = "") {
    const messages = document.querySelector("#assistant-messages");
    messages.querySelector(".assistant-empty")?.remove();
    const message = element("article", `assistant-message ${role}`);
    const roleIcon = element("span", "assistant-role-icon", role === "assistant" ? "✦" : "♙");
    roleIcon.setAttribute("aria-hidden", "true");
    const content = element("div", "assistant-message-content");
    if (role === "assistant") renderAssistantContent(content, body); else content.textContent = body;
    message.append(roleIcon, content);
    messages.appendChild(message);
    messages.scrollTop = messages.scrollHeight;
    return content;
  }

  async function loadConversation(id) {
    if (!id) return;
    const detail = await (await assistantApi(`/assistant/conversations/${id}`)).json();
    setAssistantError();
    conversationId = detail.id;
    document.querySelector("#assistant-delete").disabled = false;
    document.querySelector("#assistant-delete").hidden = false;
    const messages=document.querySelector("#assistant-messages");messages.innerHTML="";
    detail.messages.forEach(item=>addMessage(item.role,item.body));
  }

  async function loadConversationList() {
    const conversations=await (await assistantApi("/assistant/conversations")).json();
    setAssistantError();
    const select=document.querySelector("#assistant-history");select.innerHTML='<option value="">Conversation history</option>';
    conversations.forEach(item=>{const option=element("option","",item.title);option.value=item.id;select.appendChild(option)});
    select.value = conversationId || "";
    const deleteButton = document.querySelector("#assistant-delete");
    deleteButton.disabled = !conversationId;
    deleteButton.hidden = !conversationId;
    conversationsLoaded=true;
  }

  function newConversation() {
    setAssistantError();
    conversationId=null;
    document.querySelector("#assistant-history").value="";
    document.querySelector("#assistant-delete").disabled=true;
    document.querySelector("#assistant-delete").hidden=true;
    document.querySelector("#assistant-messages").innerHTML='<div class="assistant-empty"><div class="assistant-empty-card"><span class="assistant-empty-icon">✦</span><b>How can I help?</b><span>Ask about your permitted projects, tasks, teams, deadlines, workload, or delivery risks.</span><small>Your answer will reflect the page you are viewing and your access permissions.</small></div></div>';
    document.querySelector("#assistant-question").focus();
  }

  async function deleteConversation() {
    if (!conversationId || !window.confirm("Delete this private AI conversation permanently?")) return;
    const deleteButton = document.querySelector("#assistant-delete");
    deleteButton.disabled = true;
    try {
      await assistantApi(`/assistant/conversations/${conversationId}`, {method:"DELETE"});
      newConversation();
      conversationsLoaded = false;
      await loadConversationList();
    } catch (error) {
      setAssistantError(error.message);
      deleteButton.disabled = false;
      deleteButton.hidden = false;
    }
  }

  async function sendQuestion(question) {
    if (sending || !question.trim()) return;
    sending = true;
    const form = document.querySelector("#assistant-form");
    const input = form.elements.question;
    const button = form.querySelector("button");
    setAssistantError();
    addMessage("user", question.trim());
    const answerNode = addMessage("assistant", "Thinking…");
    input.value = ""; button.disabled = true; button.textContent = "…";
    try {
      const response = await assistantApi("/assistant/ask", {method:"POST", body:JSON.stringify({question:question.trim(), conversation_id:conversationId, ...currentContext()})});
      const reader = response.body.getReader(), decoder = new TextDecoder();
      let buffer = "", answer = "", sourceSummary = "";
      while (true) {
        const {value, done} = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, {stream:true});
        const events = buffer.split("\n\n"); buffer = events.pop() || "";
        for (const event of events) {
          const line = event.split("\n").find(item => item.startsWith("data: "));
          if (!line) continue;
          const data = JSON.parse(line.slice(6));
          if (data.type === "meta") { conversationId=data.conversation_id;sourceSummary=data.sources||""; }
          if (data.type === "text") { answer += data.text; renderAssistantContent(answerNode, answer); }
          if (data.type === "done" && sourceSummary) {
            const source = element("small", "assistant-source");
            source.append(element("span", "assistant-source-dot"), element("span", "", sourceSummary));
            answerNode.closest(".assistant-message").appendChild(source);
          }
        }
        document.querySelector("#assistant-messages").scrollTop = document.querySelector("#assistant-messages").scrollHeight;
      }
    } catch (error) {
      answerNode.closest(".assistant-message")?.remove();
      setAssistantError(error.message);
    } finally {
      sending = false; button.disabled = false; button.textContent = "➤"; input.focus();conversationsLoaded=false;
    }
  }

  async function openAssistant() {
    setAssistantError();
    document.querySelector("#assistant-backdrop").classList.add("open");
    document.querySelector("#assistant-launcher").setAttribute("aria-expanded", "true");
    const contextValue = document.querySelector("#assistant-context-value");
    contextValue.textContent = contextDescription();
    contextValue.title = contextDescription();
    if (!bootstrap) {
      try {
        bootstrap = await (await assistantApi("/assistant/bootstrap")).json();
        document.querySelector("#assistant-access").textContent = bootstrap.access_label;
        document.querySelector("#assistant-scope").textContent = bootstrap.scope_description;
        const suggestions = document.querySelector("#assistant-suggestions");
        bootstrap.suggestions.forEach(text => { const button=element("button","",text);button.type="button";button.onclick=()=>sendQuestion(text);suggestions.appendChild(button); });
      } catch (error) { setAssistantError(error.message); }
    }
    if(!conversationsLoaded)loadConversationList().catch(()=>{});
    document.querySelector("#assistant-question").focus();
  }

  function closeAssistant() {
    document.querySelector("#assistant-backdrop").classList.remove("open");
    document.querySelector("#assistant-launcher").setAttribute("aria-expanded", "false");
  }

  function initialize() {
    const launcher = element("button", "assistant-launcher");
    launcher.id="assistant-launcher"; launcher.type="button"; launcher.setAttribute("aria-expanded","false");launcher.setAttribute("aria-controls","assistant-drawer");
    launcher.innerHTML='<span class="assistant-launcher-icon">✦</span><span class="assistant-launcher-label">Ask AI</span>';
    const backdrop = element("div", "assistant-backdrop"); backdrop.id="assistant-backdrop";
    backdrop.innerHTML='<section id="assistant-drawer" class="assistant-drawer" role="dialog" aria-modal="true" aria-label="Orbit AI assistant"><header class="assistant-head"><b class="assistant-brand">✦</b><div class="assistant-head-text"><strong>Orbit AI</strong><small id="assistant-access">Permission-aware assistant</small></div><button id="assistant-new" class="assistant-head-action" type="button" aria-label="Start a new conversation" title="New conversation">↻</button><button class="assistant-close" type="button" aria-label="Close assistant">×</button></header><div class="assistant-context"><span class="assistant-context-label">Current context</span><strong id="assistant-context-value">Current page</strong><span id="assistant-scope">Answers use only information you may access.</span><div class="assistant-history-row"><select id="assistant-history" class="assistant-history" aria-label="Conversation history"><option value="">Conversation history</option></select><button id="assistant-delete" class="assistant-delete" type="button" aria-label="Delete selected conversation" title="Delete conversation" disabled hidden>Delete</button></div><small class="assistant-retention">Private history · Automatically removed 20 days after the latest activity</small><div id="assistant-suggestions" class="assistant-suggestions"></div></div><div id="assistant-messages" class="assistant-messages"><div class="assistant-empty"><div class="assistant-empty-card"><span class="assistant-empty-icon">✦</span><b>How can I help?</b><span>Ask about your permitted projects, tasks, teams, deadlines, workload, or delivery risks.</span><small>Your answer will reflect the current page and your access permissions.</small></div></div></div><div class="assistant-compose-area"><p id="assistant-error" class="assistant-error"></p><form id="assistant-form" class="assistant-composer"><textarea id="assistant-question" name="question" maxlength="2000" placeholder="Ask about projects, tasks, teams…" required></textarea><button class="btn primary" type="submit" aria-label="Send message">➤</button></form><small class="assistant-grounding">Grounded in your permitted Orbit data · Read-only assistant</small></div></section>';
    launcher.hidden=true;launcher.style.display="none";
    document.body.append(launcher,backdrop);
    launcher.onclick=openAssistant; backdrop.querySelector(".assistant-close").onclick=closeAssistant;
    backdrop.querySelector("#assistant-new").onclick=newConversation;
    backdrop.querySelector("#assistant-delete").onclick=deleteConversation;
    backdrop.querySelector("#assistant-history").onchange=event=>{
      const selectedId = Number(event.target.value);
      if (!selectedId) { newConversation(); return; }
      loadConversation(selectedId).catch(error=>{
        if (/conversation not found/i.test(error.message)) {
          newConversation();
          conversationsLoaded=false;
          loadConversationList().catch(()=>{});
          return;
        }
        setAssistantError(error.message);
      });
    };
    backdrop.onclick=event=>{if(event.target===backdrop)closeAssistant()};
    backdrop.querySelector("form").onsubmit=event=>{event.preventDefault();sendQuestion(event.currentTarget.elements.question.value)};
    backdrop.querySelector("textarea").onkeydown=event=>{if(event.key==="Enter"&&!event.shiftKey){event.preventDefault();sendQuestion(event.currentTarget.value)}};
    document.addEventListener("keydown",event=>{if(event.key==="Escape"&&backdrop.classList.contains("open"))closeAssistant()});
    const setAuthenticated = authenticated => {
      const visible = Boolean(authenticated && state?.user && state?.token);
      launcher.hidden = !visible;
      launcher.style.display = visible ? "" : "none";
      if (!visible) closeAssistant();
    };
    window.setOrbitAssistantAuthenticated = setAuthenticated;
    document.addEventListener("orbit:authentication", event => {
      setAuthenticated(Boolean(event.detail?.authenticated));
    });
    setAuthenticated(Boolean(
      state?.user && state?.token &&
      !document.querySelector("#app-shell")?.classList.contains("hidden")
    ));
  }

  initialize();
})();

const $ = (selector) => document.querySelector(selector);
const escapeText = (value) => { const node = document.createElement("span"); node.textContent = value ?? ""; return node.innerHTML; };
const master = { token: sessionStorage.getItem("permrag-master-token"), state: null, view: "overview" };

async function api(path, options = {}) {
  const headers = { "Content-Type": "application/json", ...(options.headers || {}) };
  if (master.token) headers.Authorization = `Bearer ${master.token}`;
  const response = await fetch(path, { ...options, headers });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.error || "Request failed");
  return body;
}
function notify(message, error = false) {
  const element = document.createElement("p"); element.className = error ? "flash error" : "flash"; element.textContent = message;
  $("#content").prepend(element); setTimeout(() => element.remove(), 4500);
}
async function loadState() { master.state = await api("/api/master/state"); render(); }
function showConsole() { $("#login").classList.add("hidden"); $("#console").classList.remove("hidden"); loadState().catch((error) => { showLogin(); $("#loginError").textContent = error.message; }); }
function showLogin() { master.token = null; sessionStorage.removeItem("permrag-master-token"); sessionStorage.removeItem("permrag-token"); $("#console").classList.add("hidden"); $("#login").classList.remove("hidden"); }
function rolesOptions(selected = "") { return master.state.roles.map((role) => `<option value="${escapeText(role)}" ${role === selected ? "selected" : ""}>${escapeText(role)}</option>`).join(""); }
function permissionsChecks(selected = []) { return master.state.roles.map((role) => `<label class="check"><input type="checkbox" value="${escapeText(role)}" ${selected.includes(role) ? "checked" : ""}> ${escapeText(role)}</label>`).join(""); }
function render() {
  document.querySelectorAll(".nav").forEach((button) => button.classList.toggle("active", button.dataset.view === master.view));
  const content = $("#content");
  if (master.view === "overview") {
    content.innerHTML = `<p class="eyebrow">SYSTEM SUMMARY</p><h2>Control the knowledge boundary</h2><div class="stats"><article><b>${master.state.roles.length}</b><span>roles</span></article><article><b>${master.state.users.length}</b><span>users</span></article><article><b>${master.state.documents.length}</b><span>documents</span></article><article><b>${master.state.gemini.configured ? "On" : "Off"}</b><span>Gemini</span></article></div><section class="notice"><strong>The non-negotiable rule</strong><p>Changing a document’s permissions changes which chunks can be searched. The filter is applied before ranking and before any local or Gemini answer is generated.</p></section><p class="muted">Use the sections on the left to change the workspace. Corpus edits are live for new chat questions; no re-index command is needed.</p>`;
  } else if (master.view === "roles") renderRoles(content);
  else if (master.view === "users") renderUsers(content);
  else if (master.view === "documents") renderDocuments(content);
  else renderGemini(content);
}
function renderRoles(content) {
  const roleRows = master.state.roles.map((role) => `<li><code>${escapeText(role)}</code>${role === "admin" ? `<span class="protected">protected</span>` : `<button class="danger small" data-delete-role="${escapeText(role)}">Delete</button>`}</li>`).join("");
  content.innerHTML = `<p class="eyebrow">ACCESS ROLES</p><h2>Create or retire clearances</h2><p class="muted">A role may only be deleted after it is removed from all users and document permissions.</p><div class="two-column"><section class="card"><h3>Current roles</h3><ul class="clean-list">${roleRows}</ul></section><form id="roleForm" class="card"><h3>Add role</h3><label>Role name<input name="role" placeholder="legal"></label><p class="hint">Lowercase letters, numbers, hyphens, and underscores only.</p><button class="primary">Create role</button></form></div>`;
  $("#roleForm").addEventListener("submit", submitForm("/api/master/roles"));
  document.querySelectorAll("[data-delete-role]").forEach((button) => button.addEventListener("click", () => mutate("/api/master/roles/delete", { role: button.dataset.deleteRole }, "Role deleted.")));
}
function renderUsers(content) {
  const rows = master.state.users.map((user) => `<tr><td>${escapeText(user.username)}</td><td><code>${escapeText(user.role)}</code></td><td>${user.username === "admin" ? `<span class="protected">default admin</span>` : `<button class="danger small" data-delete-user="${escapeText(user.username)}">Delete</button>`}</td></tr>`).join("");
  content.innerHTML = `<p class="eyebrow">PEOPLE</p><h2>Manage chat accounts</h2><div class="two-column wide-left"><section class="card table-wrap"><table><thead><tr><th>Username</th><th>Role</th><th></th></tr></thead><tbody>${rows}</tbody></table></section><form id="userForm" class="card"><h3>Add user</h3><label>Username<input name="username" placeholder="maya"></label><label>Temporary password<input name="password" type="password" placeholder="at least 6 characters"></label><label>Role<select name="role">${rolesOptions()}</select></label><button class="primary">Create user</button></form></div>`;
  $("#userForm").addEventListener("submit", submitForm("/api/master/users"));
  document.querySelectorAll("[data-delete-user]").forEach((button) => button.addEventListener("click", () => mutate("/api/master/users/delete", { username: button.dataset.deleteUser }, "User deleted.")));
}
function renderDocuments(content) {
  const docs = master.state.documents;
  content.innerHTML = `<p class="eyebrow">KNOWLEDGE BASE</p><h2>Edit corpus documents and permissions</h2><p class="muted">Permissions are attached to every chunk created from the document. Save changes before testing them in chat.</p><div class="document-grid"><section class="card document-list"><div class="section-row"><h3>Documents</h3><button id="newDoc" class="quiet">+ New</button></div><div id="docItems">${docs.map((doc, index) => `<button class="doc-item ${index === 0 ? "selected" : ""}" data-doc-index="${index}"><b>${escapeText(doc.path)}</b><small>${escapeText(doc.allowed_roles.join(", "))}</small></button>`).join("") || `<p class="muted">No documents yet.</p>`}</div></section><section id="documentEditor" class="card"></section></div>`;
  const openDocument = (document) => drawDocumentEditor(document);
  document.querySelectorAll("[data-doc-index]").forEach((button) => button.addEventListener("click", () => openDocument(docs[Number(button.dataset.docIndex)])));
  $("#newDoc").addEventListener("click", () => openDocument({ path: "new-department/new-document.md", department: "new-department", allowed_roles: [], sensitivity: "internal", body: "# New document\n\nWrite the information users may search here." }));
  openDocument(docs[0] || { path: "new-department/new-document.md", department: "new-department", allowed_roles: [], sensitivity: "internal", body: "# New document\n\nWrite the information users may search here." });
}
function drawDocumentEditor(doc) {
  const editor = $("#documentEditor");
  editor.innerHTML = `<div class="section-row"><h3>Document editor</h3><button id="deleteDoc" class="danger small">Delete</button></div><form id="documentForm"><label>Path<input name="path" placeholder="legal/contracts.md"></label><label>Department<input name="department" placeholder="legal"></label><label>Classification<select name="sensitivity"><option value="public">public</option><option value="internal">internal</option><option value="restricted">restricted</option></select></label><fieldset><legend>Allowed roles</legend><div class="checks">${permissionsChecks(doc.allowed_roles)}</div></fieldset><label>Document text<textarea name="body" rows="15" placeholder="# Title&#10;&#10;Content…"></textarea></label><button class="primary">Save document & permissions</button></form>`;
  const form = $("#documentForm"); form.path.value = doc.path; form.department.value = doc.department; form.sensitivity.value = doc.sensitivity; form.body.value = doc.body;
  $("#deleteDoc").disabled = !master.state.documents.some((candidate) => candidate.path === doc.path);
  $("#deleteDoc").addEventListener("click", () => mutate("/api/master/documents/delete", { path: doc.path }, "Document deleted."));
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const payload = Object.fromEntries(new FormData(form)); payload.allowed_roles = [...form.querySelectorAll('input[type="checkbox"]:checked')].map((input) => input.value);
    await mutate("/api/master/documents", payload, "Document and permissions saved.");
  });
}
function renderGemini(content) {
  const gemini = master.state.gemini;
  content.innerHTML = `<p class="eyebrow">OPTIONAL ANSWER WRITER</p><h2>Gemini answer mode</h2><section class="notice"><strong>Permission boundary stays first</strong><p>Gemini receives only chunks that passed the user’s role filter. It has no tools, no web search, and no access to your database or corpus files.</p></section><form id="geminiForm" class="card gemini-card"><div class="state"><span class="status-dot ${gemini.configured ? "on" : ""}"></span>${gemini.configured ? `Configured (${escapeText(gemini.source)})` : "Not configured"}</div><label>Gemini API key<input name="api_key" type="password" autocomplete="off" placeholder="Paste a key only if you want Gemini responses"></label><p class="hint">The key is kept only in this running MASTERrun.py session and is never sent back to the browser after saving.</p><label>Model<input name="model" value="${escapeText(gemini.model)}"></label><label class="check clear"><input type="checkbox" name="clear_key"> Remove the current in-memory key</label><button class="primary">Save Gemini settings</button></form>`;
  $("#geminiForm").addEventListener("submit", async (event) => { event.preventDefault(); const payload = Object.fromEntries(new FormData(event.currentTarget)); payload.clear_key = Boolean(event.currentTarget.clear_key.checked); await mutate("/api/master/gemini", payload, "Gemini settings updated."); });
}
function submitForm(path) { return async (event) => { event.preventDefault(); await mutate(path, Object.fromEntries(new FormData(event.currentTarget)), "Saved."); }; }
async function mutate(path, payload, success) { try { const response = await api(path, { method: "POST", body: JSON.stringify(payload) }); master.state = response.state; render(); notify(success); } catch (error) { notify(error.message, true); } }

$("#loginForm").addEventListener("submit", async (event) => { event.preventDefault(); $("#loginError").textContent = ""; try { const response = await api("/api/login", { method: "POST", body: JSON.stringify({ username: $("#username").value, password: $("#password").value }) }); if (response.user.role !== "admin") throw new Error("This control center requires the admin role."); master.token = response.token; sessionStorage.setItem("permrag-master-token", master.token); sessionStorage.setItem("permrag-token", master.token); showConsole(); } catch (error) { $("#loginError").textContent = error.message; } });
$("#signOut").addEventListener("click", showLogin);
document.querySelectorAll(".nav").forEach((button) => button.addEventListener("click", () => { master.view = button.dataset.view; render(); }));
if (master.token) showConsole();

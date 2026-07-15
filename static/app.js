const state = { token: sessionStorage.getItem("permrag-token"), user: null };
const $ = (selector) => document.querySelector(selector);

function escapeText(value) {
  const element = document.createElement("span");
  element.textContent = value;
  return element.innerHTML;
}

async function api(path, options = {}) {
  const headers = { "Content-Type": "application/json", ...(options.headers || {}) };
  if (state.token) headers.Authorization = `Bearer ${state.token}`;
  const response = await fetch(path, { ...options, headers });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.error || "Request failed");
  return body;
}

function showApp(user) {
  state.user = user;
  $("#loginView").classList.add("hidden");
  $("#appView").classList.remove("hidden");
  $("#roleBadge").textContent = user.role;
  $("#usernameDisplay").textContent = user.username;
  $("#adminNav").classList.toggle("hidden", user.role !== "admin");
}

function showLogin() {
  state.user = null;
  state.token = null;
  sessionStorage.removeItem("permrag-token");
  $("#appView").classList.add("hidden");
  $("#loginView").classList.remove("hidden");
  $("#loginError").textContent = "";
}

function addMessage(type, html) {
  const article = document.createElement("article");
  article.className = `message ${type}`;
  article.innerHTML = `<div class="avatar">${type === "assistant" ? "P" : "Y"}</div><div>${html}</div>`;
  $("#messages").append(article);
  $("#messages").scrollTop = $("#messages").scrollHeight;
  return article;
}

function showChat() {
  $("#adminPanel").classList.add("hidden");
  $("#chatPanel").classList.remove("hidden");
}

$("#loginForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  $("#loginError").textContent = "";
  try {
    const body = await api("/api/login", { method: "POST", body: JSON.stringify({ username: $("#username").value, password: $("#password").value }) });
    state.token = body.token;
    sessionStorage.setItem("permrag-token", state.token);
    showApp(body.user);
  } catch (error) { $("#loginError").textContent = error.message; }
});

document.querySelectorAll("[data-user]").forEach((button) => button.addEventListener("click", () => {
  $("#username").value = button.dataset.user;
  $("#password").value = button.dataset.user;
}));

$("#logoutButton").addEventListener("click", showLogin);

$("#chatForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const query = $("#query").value.trim();
  if (!query) return;
  showChat();
  $("#query").value = "";
  addMessage("user", `<p>${escapeText(query)}</p>`);
  const pending = addMessage("assistant", `<p class="thinking">Searching only permitted documents…</p>`);
  $("#sendButton").disabled = true;
  try {
    const body = await api("/api/chat", { method: "POST", body: JSON.stringify({ query }) });
    const sources = body.sources.length ? `<div class="citations">${body.sources.map((source) => `<span>↗ ${escapeText(source)}</span>`).join("")}</div>` : "";
    const generator = body.generator === "gemini" ? "Gemini, grounded in permitted context" : "Local grounded answer";
    pending.querySelector("div:last-child").innerHTML = `<p>${escapeText(body.answer)}</p>${sources}<p class="security-note">✓ ${escapeText(generator)} · ${escapeText(body.security.message)} ${body.security.restricted_chunks_excluded} inaccessible chunks excluded.</p>`;
  } catch (error) {
    pending.querySelector("div:last-child").innerHTML = `<p class="error">${escapeText(error.message)}</p>`;
  } finally { $("#sendButton").disabled = false; }
});

$("#showDocs").addEventListener("click", async () => {
  try {
    const body = await api("/api/documents");
    $("#chatPanel").classList.add("hidden");
    const rows = body.documents.map((doc) => `<tr><td>${escapeText(doc.source_doc)}</td><td>${escapeText(doc.department)}</td><td>${doc.allowed_roles.map(escapeText).join(", ")}</td><td>${escapeText(doc.sensitivity)}</td></tr>`).join("");
    $("#adminPanel").innerHTML = `<div class="panel-heading"><div><p class="eyebrow">ADMIN VIEW</p><h2>Document access map</h2></div><button class="ghost back">Back to chat</button></div><p class="admin-copy">This catalog is visible only to administrators. Each row is enforced at the retrieval boundary.</p><div class="table-wrap"><table><thead><tr><th>Document</th><th>Department</th><th>Allowed roles</th><th>Classification</th></tr></thead><tbody>${rows}</tbody></table></div>`;
    $("#adminPanel").classList.remove("hidden");
    $(".back").addEventListener("click", showChat);
  } catch (error) { alert(error.message); }
});

$("#showAudit").addEventListener("click", async () => {
  try {
    const body = await api("/api/audit");
    $("#chatPanel").classList.add("hidden");
    const rows = body.entries.map((entry) => `<tr><td>${new Date(entry.timestamp).toLocaleString()}</td><td>${escapeText(entry.username)}<br><small>${escapeText(entry.role)}</small></td><td>${escapeText(entry.query)}</td><td>${entry.retrieved_sources.map(escapeText).join(", ") || "—"}</td><td>${entry.restricted_chunks_excluded}</td><td>${entry.flagged ? "⚑ flagged" : "✓"}</td></tr>`).join("") || `<tr><td colspan="6">No queries logged yet.</td></tr>`;
    $("#adminPanel").innerHTML = `<div class="panel-heading"><div><p class="eyebrow">ADMIN VIEW</p><h2>Query audit log</h2></div><button class="ghost back">Back to chat</button></div><p class="admin-copy">The audit records only returned source IDs; restricted source text is never placed in an answer context.</p><div class="table-wrap"><table><thead><tr><th>Time</th><th>User / role</th><th>Question</th><th>Permitted sources</th><th>Excluded</th><th>Status</th></tr></thead><tbody>${rows}</tbody></table></div>`;
    $("#adminPanel").classList.remove("hidden");
    $(".back").addEventListener("click", showChat);
  } catch (error) { alert(error.message); }
});

if (state.token) {
  api("/api/me").then(showApp).catch(showLogin);
}

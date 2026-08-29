/* Agent Console — vanilla JS, no build step. */
"use strict";

const TOKEN = localStorage.getItem("console_token") || "";
const EVENT_TYPES = [
  "run_started","run_finished","run_failed","run_cancelled","agent_started",
  "agent_thinking","agent_finished","subagent_started","subagent_finished",
  "skill_loaded","tool_requested","tool_started","tool_executed","tool_failed",
  "action_pending","action_approved","action_rejected","loop_detected",
  "budget_warning","run_status_changed",
];
const TERMINAL = new Set(["run_finished", "run_failed", "run_cancelled"]);

const runs = new Map();            // run_id -> run object
let selectedId = null;
let detailES = null;
let dirtyRuns = false;

/* ---------------------------------------------------------------- api */

async function api(path, options = {}) {
  const headers = Object.assign({"Content-Type": "application/json"}, options.headers);
  if (TOKEN) headers["X-Console-Token"] = TOKEN;
  const response = await fetch(path, Object.assign({}, options, {headers}));
  if (response.status === 401) {
    const t = prompt("This console requires a token (AGENT_CORE_CONSOLE_TOKEN):");
    if (t !== null) { localStorage.setItem("console_token", t); location.reload(); }
    throw new Error("unauthorized");
  }
  if (!response.ok) throw new Error(`${response.status} ${path}`);
  return response.json();
}

function withToken(url) { return TOKEN ? `${url}${url.includes("?") ? "&" : "?"}token=${TOKEN}` : url; }

/* ------------------------------------------------------------ run list */

async function loadRuns() {
  const list = await api("/v1/runs");
  list.sort((a, b) => b.created_at.localeCompare(a.created_at));
  for (const run of list) runs.set(run.id, run);
  renderRuns();
}

function statusBadge(status) {
  const map = {completed: "badge-ok", failed: "badge-err", timeout: "badge-err",
               cancelled: "badge-idle", needs_input: "badge-warn",
               waiting_approval: "badge-warn", running: "badge-run",
               planning: "badge-run", created: "badge-idle"};
  return `<span class="badge ${map[status] || "badge-idle"}">${status}</span>`;
}

function fmtTime(iso) { return new Date(iso).toLocaleTimeString(); }

function renderRuns() {
  const el = document.getElementById("runList");
  el.innerHTML = "";
  const threadSize = {};
  for (const r of runs.values()) {
    if (r.parent_run_id === null) {
      const t = r.thread_id || r.id;
      threadSize[t] = (threadSize[t] || 0) + 1;
    }
  }
  for (const run of runs.values()) {
    const div = document.createElement("div");
    div.className = "run" + (run.id === selectedId ? " selected" : "");
    const linked = (threadSize[run.thread_id || run.id] || 0) > 1 ? "🔗 " : "";
    div.innerHTML = `<div class="top">${statusBadge(run.status)}
        <strong>${linked}${run.agent_id}</strong>
        <span class="muted" style="margin-left:auto">${fmtTime(run.created_at)}</span></div>
      <div class="task">${escapeHtml(run.input || run.id.slice(0, 8)).slice(0, 160)}</div>`;
    div.onclick = () => selectRun(run.id);
    el.appendChild(div);
  }
}

/* ------------------------------------------------------- run detail */

async function selectRun(runId) {
  selectedId = runId;
  if (detailES) detailES.close();
  renderRuns();
  document.getElementById("detail").classList.add("hidden");
  document.getElementById("detailBody").classList.remove("hidden");
  document.getElementById("events").innerHTML = "";

  const run = await api(`/v1/runs/${runId}`);
  runs.set(runId, run);
  renderHead(run);
  renderThread(run);
  await renderArtifacts(runId, run);
  openEventStream(runId, run.status);
}

function threadRuns(run) {
  const thread = run.thread_id || run.id;
  return [...runs.values()]
    .filter(r => r.parent_run_id === null && (r.thread_id || r.id) === thread)
    .sort((a, b) => a.created_at.localeCompare(b.created_at));
}

function bubble(role, text) {
  const div = document.createElement("div");
  div.className = "bubble " + role;
  div.innerHTML = `<div class="who">${role === "user" ? "🧑 你" : "🤖 分身"}</div>
    <div class="txt">${escapeHtml(String(text))}</div>`;
  return div;
}

function renderThread(run) {
  const el = document.getElementById("thread");
  const chain = threadRuns(run);
  el.innerHTML = "";
  if (!chain.length) {
    el.innerHTML = '<span class="muted">（旧任务没有对话线程——发一条消息即可开启）</span>';
    return;
  }
  for (const r of chain) {
    el.appendChild(bubble("user", r.input || "（无文本）"));
    if (r.output) {
      el.appendChild(bubble("avatar", r.output));
    } else {
      el.appendChild(bubble("avatar", `（${r.status}${r.error ? "：" + r.error : ""}）`));
    }
  }
}

async function sendFollowup() {
  const inputEl = document.getElementById("followupInput");
  const text = inputEl.value.trim();
  if (!text || !selectedId) return;
  inputEl.value = "";
  const run = await api(`/v1/runs/${selectedId}/messages`, {
    method: "POST",
    body: JSON.stringify({input: text}),
  });
  runs.set(run.id, run);
  dirtyRuns = true;
  selectRun(run.id);
}

function renderHead(run) {
  const head = document.getElementById("detailHead");
  const usage = run.usage
    ? `⏱ ${Math.round((run.usage.duration_ms || 0) / 1000)}s · ${run.usage.total_tokens} tokens · ${run.usage.model_calls} model · ${run.usage.tool_calls} tools`
    : "no usage yet";
  const verification = run.metadata && run.metadata.verification
    ? `<span>自检: ${run.metadata.verification.passed ? "✅ 通过" : "⚠️ 未通过"} (${run.metadata.verification.rounds} 轮)</span>`
    : "";
  head.innerHTML = `<div class="kv">${statusBadge(run.status)}
      <span>agent: ${run.agent_id}</span><span>${usage}</span>
      <span>开始 ${new Date(run.created_at).toLocaleString()}</span>${verification}
      ${run.error ? `<span style="border-color: var(--err); color: var(--err)">${escapeHtml(run.error)}</span>` : ""}</div>
    ${run.output ? `<div class="final">${escapeHtml(String(run.output))}</div>` : ""}`;
}

function fmtSize(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1048576) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1048576).toFixed(1)} MB`;
}

async function renderArtifacts(runId, run) {
  let files = [];
  try { files = await api(`/v1/artifacts/${runId}`); } catch { /* run unknown */ }
  const el = document.getElementById("artifacts");
  if (!files.length) { el.innerHTML = '<span class="muted">（无）</span>'; return; }
  el.innerHTML = "";
  for (const f of files) {
    const url = withToken(`/v1/artifacts/${runId}/download?path=${encodeURIComponent(f.path)}`);
    const div = document.createElement("div");
    if (/\.(png|jpe?g|webp|gif)$/i.test(f.path)) {
      div.className = "artifact";
      div.innerHTML = `<a href="${url}" target="_blank"><img src="${url}" loading="lazy" alt=""></a>
        <div class="name" title="${f.path}">${f.path} · ${fmtSize(f.size)}</div>`;
    } else {
      div.className = "artifact file";
      div.innerHTML = `<span>📄</span><a href="${url}" download>${f.path}</a>
        <span class="muted">${fmtSize(f.size)}</span>`;
    }
    el.appendChild(div);
  }
}

function appendEvent(event) {
  const feed = document.getElementById("events");
  const div = document.createElement("div");
  div.className = "ev";
  const kind = event.event_type;
  const cls = kind.startsWith("tool_failed") || kind.includes("rejected") ? "k-fail"
    : kind.endsWith("_finished") ? "k-ok"
    : kind.startsWith("tool_") ? "k-tool"
    : kind.startsWith("run_") ? "k-run" : "";
  const info = event.tool ? `${event.tool} ${str(event.output) || str(event.error)}`
    : str(event.output) || str(event.error);
  div.innerHTML = `<span class="t">${new Date(event.timestamp).toLocaleTimeString()}</span>
    <span class="k ${cls}">${kind}</span> ${escapeHtml(info.slice(0, 160))}`;
  feed.appendChild(div);
  feed.scrollTop = feed.scrollHeight;
}

function str(value) { return value == null ? "" : typeof value === "string" ? value : JSON.stringify(value); }
function escapeHtml(text) {
  return text.replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
}

function openEventStream(runId, status) {
  detailES = new EventSource(withToken(`/v1/runs/${runId}/events`));
  for (const type of EVENT_TYPES) {
    detailES.addEventListener(type, e => {
      const event = JSON.parse(e.data);
      if (event.id && !seenEvent(event.id)) appendEvent(event);
      if (TERMINAL.has(type)) detailES.close();
    });
  }
  detailES.onerror = () => { if (runs.get(runId)?.status && isTerminal(runs.get(runId).status)) detailES.close(); };
  if (isTerminal(status)) setTimeout(() => detailES && detailES.close(), 3000);
}

const seenIds = new Set();
function seenEvent(id) { if (seenIds.has(id)) return true; seenIds.add(id); return false; }
function isTerminal(status) { return TERMINAL.has(status); }

/* ------------------------------------------------------- approvals */

async function loadApprovals() {
  const list = await api("/v1/approvals/pending");
  const badge = document.getElementById("pendingBadge");
  badge.classList.toggle("hidden", list.length === 0);
  badge.textContent = `⚠ ${list.length} 待审批`;
  document.getElementById("approvalCount").textContent = list.length ? `(${list.length})` : "";
  const el = document.getElementById("approvalList");
  if (!list.length) { el.innerHTML = '<span class="muted">（空）</span>'; return; }
  el.innerHTML = "";
  for (const approval of list) {
    const card = document.createElement("div");
    card.className = "approval";
    const title = approval.kind === "task_help"
      ? `🙋 求助 · ${approval.agent_id}`
      : `🛠 工具审批 · ${approval.tool_name} (${approval.risk_level})`;
    card.innerHTML = `<div class="q">${escapeHtml(approval.question || approval.reason || title)}</div>
      <div class="meta">${title} · run ${approval.run_id.slice(0, 8)} · ${new Date(approval.created_at).toLocaleTimeString()}</div>
      <div class="actions"><input placeholder="给分身的答复（可空）" id="note-${approval.id}">
        <button class="approve">批准</button><button class="reject">驳回</button></div>`;
    card.querySelector(".approve").onclick = () => resolve(approval.id, "approved", card);
    card.querySelector(".reject").onclick = () => resolve(approval.id, "rejected", card);
    el.appendChild(card);
  }
}

async function resolve(approvalId, decision, card) {
  const note = card.querySelector("input").value;
  await api(`/v1/approvals/${approvalId}/resolve`, {
    method: "POST",
    body: JSON.stringify({decision, resolved_by: "console", note: note || null}),
  });
  loadApprovals();
}

/* ------------------------------------------------------- new task */

async function submitTask() {
  const agentId = document.getElementById("agentSel").value;
  const input = document.getElementById("taskInput").value.trim();
  if (!input) return;
  const run = await api("/v1/runs", {method: "POST", body: JSON.stringify({agent_id: agentId, input})});
  document.getElementById("taskInput").value = "";
  runs.set(run.id, run);
  renderRuns();
  selectRun(run.id);
}

/* ---------------------------------------------------------- wiring */

async function boot() {
  try {
    const agents = await api("/v1/agents");
    const sel = document.getElementById("agentSel");
    sel.innerHTML = agents.map(a => `<option value="${a.id}">${a.id}</option>`).join("");
    const preferred = agents.find(a => a.id === "avatar");
    if (preferred) sel.value = "avatar";
  } catch { /* auth flow handles it */ }

  await loadRuns();
  loadApprovals();
  setInterval(() => { if (dirtyRuns) { dirtyRuns = false; loadRuns(); } }, 2000);
  setInterval(loadApprovals, 8000);
  setInterval(() => { if (selectedId) selectRun(selectedId); }, 15000);

  const source = new EventSource(withToken("/v1/events"));
  source.onopen = () => {
    const conn = document.getElementById("conn");
    conn.textContent = "live";
    conn.className = "badge badge-on";
  };
  for (const type of EVENT_TYPES) {
    source.addEventListener(type, () => {
      if (type.startsWith("run_") || type.startsWith("agent_")) dirtyRuns = true;
    });
  }
}

boot();

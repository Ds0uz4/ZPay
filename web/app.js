"use strict";
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const api = async (url, opts) => {
  const res = await fetch(url, opts);
  if (!res.ok) throw new Error((await res.text()).slice(0, 300));
  return res.json();
};
const post = (url, body) => api(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

marked.use({ renderer: { html: () => "" } }); // never render raw HTML coming from model output
mermaid.initialize({ startOnLoad: false, securityLevel: "strict", theme: "neutral" });

const STAGES = [
  ["intake", "Coordinator", "Mask data, screen injection"], ["extract", "Requirement Extraction", "RAG + structured requirements"],
  ["classify", "Classification", "Multi-label categories"], ["quality", "Clarification & Conflicts", "Ambiguity, gaps, contradictions"],
  ["compliance", "Compliance & Security", "Map to controls with citations"], ["risk", "Risk Analysis", "Risk register"],
  ["sdlc", "SDLC Selection", "Factor scoring + ranked models"], ["validate", "Validation", "Confidence & traceability"],
  ["document", "Documentation", "SRS, stories, use cases"], ["approval", "Human Approval", "Review gate"], ["finalize", "Baseline", "Record decisions"],
];

let meta, run = null, bundle = null, es = null, lastEvent = 0, activeTab = "req";
let decisions = {}; // reqId -> {action, statement, note}
let sdlcApprovals = {};
let chat = [];

/* ---------- navigation ---------- */
$("#tabs").addEventListener("click", (e) => {
  const b = e.target.closest("button"); if (!b) return;
  $$("#tabs button").forEach((x) => x.classList.toggle("active", x === b));
  $$(".view").forEach((v) => v.classList.toggle("active", v.id === "view-" + b.dataset.view));
});
const gotoView = (name) => $(`#tabs button[data-view="${name}"]`).click();

/* ---------- init ---------- */
async function init() {
  meta = await api("/api/meta");
  const useOpts = meta.useCases.map((u) => `<option value="${u.id}">${esc(u.label)}</option>`).join("");
  const roleOpts = Object.keys(meta.roles).map((r) => `<option>${esc(r)}</option>`).join("");
  ["#useCase", "#i-useCase"].forEach((s) => ($(s).innerHTML = useOpts));
  ["#role", "#i-role"].forEach((s) => ($(s).innerHTML = roleOpts));
  $("#i-topics").innerHTML = meta.topics.map((t) => `<li>${esc(t)}</li>`).join("");
  $("#agents-list").innerHTML = meta.agents.map((a) =>
    `<div class="tile"><strong>${esc(a.name)}</strong><span class="muted">${esc(a.responsibility)}</span>
     <div style="margin-top:6px">${a.sources.length ? a.sources.map((s) => `<span class="tag">${esc(s)}</span>`).join("") : '<span class="muted">no retrieval access</span>'}</div></div>`).join("");
  $("#sdlc-list").innerHTML = meta.sdlcModels.map((m) =>
    `<div class="tile"><strong>${esc(m.model)}</strong><span class="muted">${esc(m.summary)}</span><div style="margin-top:6px">${m.phases.map((p) => `<span class="tag">${esc(p)}</span>`).join("")}</div></div>`).join("");
  renderStages({});
  renderTemplate();
  resetChat();
  checkHealth();
  // Poll rarely, only while the tab is visible and no analysis is running; refresh on tab focus.
  setInterval(() => { if (!document.hidden && !$("#run").disabled) checkHealth(); }, 300000);
  document.addEventListener("visibilitychange", () => { if (!document.hidden) checkHealth(); });
}

async function checkHealth() {
  const el = $("#status");
  try {
    const h = await api("/api/health");
    $("#kb-info").textContent = `${h.kb.chunks.toLocaleString()} indexed passages (BM25). Corpus SHA-256 ${h.kb.hash.slice(0, 16)}`;
    if (!h.lmStudio.ok) { el.className = "pill pill-bad"; el.textContent = "LM Studio: offline"; el.title = h.lmStudio.error || ""; }
    else if (!h.modelAvailable) { el.className = "pill pill-warn"; el.textContent = "LM Studio: model not loaded"; el.title = `Configured: ${h.configuredModel}\nAvailable: ${h.lmStudio.models.join(", ")}`; }
    else { el.className = "pill pill-ok"; el.textContent = `LM Studio: ${h.configuredModel}`; el.title = h.baseURL; }
  } catch { el.className = "pill pill-bad"; el.textContent = "Server unreachable"; }
}

/* ---------- pipeline ---------- */
function renderStages(state) {
  $("#stages").innerHTML = STAGES.map(([id, name, desc]) => {
    const s = state[id] || {};
    return `<li class="${s.status || ""}"><span class="dot"></span><div><b>${esc(name)}</b>${s.ms ? ` <span class="muted">${(s.ms / 1000).toFixed(1)}s</span>` : ""}<small>${esc(s.summary || desc)}</small></div></li>`;
  }).join("");
}

$("#sample").onclick = () => {
  $("#project").value = "E-commerce payment gateway integration";
  $("#useCase").value = "payments"; $("#role").value = "Business analyst";
  $("#text").value = `We run an online marketplace in India and need a payment processing system supporting UPI, credit/debit cards, net banking and wallets. We expect about 50,000 transactions per day, rising during sales events. Payments must go through Razorpay. Customers should get an instant confirmation and be able to request refunds. Transactions above INR 50,000 need extra authentication. We must comply with RBI rules and PCI DSS and keep card data out of our systems. Fraud checks should happen in real time. Finance needs automatic reconciliation with bank statements every day and audit logs kept for at least 5 years. The service should be fast and always available. Our team is small, the launch is in 4 months, and the requirements may change as the business grows. Contact: ops@example.com, 9876543210.`;
};

$("#run").onclick = async () => {
  const text = $("#text").value.trim();
  if (text.length < 20) return showError("Please enter at least a few sentences of stakeholder input.");
  await startRun();
};
$("#rerun").onclick = () => startRun();

async function startRun() {
  hideError(); decisions = {}; sdlcApprovals = {}; bundle = null; lastEvent = 0;
  $("#output").classList.add("hidden"); $("#run").disabled = true;
  renderStages({});
  try {
    const r = await post("/api/runs", { project: $("#project").value, useCase: $("#useCase").value, role: $("#role").value, text: $("#text").value, notes: $("#notes").value });
    run = r.id; $("#run-id").textContent = `run ${run}`;
    listen(0);
  } catch (e) { showError(e.message); $("#run").disabled = false; }
}

const stageState = {};
function listen(after) {
  if (after === 0) Object.keys(stageState).forEach((k) => delete stageState[k]);
  if (es) es.close();
  es = new EventSource(`/api/runs/${run}/events?after=${after}`);
  es.onmessage = async (m) => {
    const ev = JSON.parse(m.data); lastEvent = ev.i + 1;
    if (ev.type === "stage") {
      stageState[ev.id] = ev; renderStages(stageState);
    } else if (ev.type === "approval_required" || ev.type === "complete") {
      es.close(); $("#run").disabled = false;
      stageState.approval = { status: ev.type === "complete" ? "done" : "waiting", summary: ev.type === "complete" ? "Decisions submitted" : "Waiting for human review" };
      renderStages(stageState);
      await loadBundle(ev.type === "approval_required");
    } else if (ev.type === "error") {
      es.close(); $("#run").disabled = false; showError(ev.message);
      const running = Object.values(stageState).find((s) => s.status === "running"); if (running) running.status = "error";
      renderStages(stageState);
    }
  };
  es.onerror = () => { /* browser retries automatically; terminal events close the stream */ };
}

async function loadBundle(needsApproval) {
  bundle = await api(`/api/runs/${run}`);
  $("#output").classList.remove("hidden");
  $("#approval").classList.toggle("hidden", !needsApproval);
  $("#downloads").classList.remove("hidden"); $("#dl-srs").href = `/api/runs/${run}/srs.md`;
  if (needsApproval && bundle.sdlc) {
    $("#sdlc-approvers").innerHTML = meta.approvers.map((r) => `<label class="check"><input type="checkbox" data-role="${esc(r)}"> ${esc(r)} approves ${esc(bundle.sdlc.chosen)}</label>`).join("");
  }
  renderSummary(); renderTab();
}

function showError(msg) { const e = $("#error"); e.textContent = msg; e.classList.remove("hidden"); }
function hideError() { $("#error").classList.add("hidden"); }

/* ---------- results ---------- */
function renderSummary() {
  const b = bundle, ok = b.baseline.startsWith("BASELINED");
  $("#baseline").className = "baseline " + (ok ? "ok" : "draft");
  $("#baseline").textContent = `Status: ${b.baseline}`;
  const m = b.metrics || {};
  const items = [
    ["Requirements", m.requirements], ["Avg confidence", m.avg_confidence], ["Needs review", m.needs_review],
    ["Citation coverage", m.citation_coverage + "%"], ["Regulatory mapping", m.regulatory_mapping_coverage + "%"],
    ["Traceability", m.traceability_coverage + "%"], ["Open issues", m.open_issues],
    ["Masked values", Object.values(b.mask).reduce((a, c) => a + c, 0)],
  ];
  $("#metrics").innerHTML = items.map(([k, v]) => `<div class="metric"><b>${esc(v ?? "-")}</b><span>${k}</span></div>`).join("") +
    (b.warnings.length ? `<div class="alert error" style="grid-column:1/-1">${b.warnings.map(esc).join("<br>")}</div>` : "") +
    (b.injection.length ? `<div class="alert error" style="grid-column:1/-1">Removed ${b.injection.length} suspected prompt-injection phrase(s) from the input.</div>` : "");
}

$("#subtabs").addEventListener("click", (e) => {
  const b = e.target.closest("button"); if (!b) return;
  activeTab = b.dataset.tab; $$("#subtabs button").forEach((x) => x.classList.toggle("active", x === b)); renderTab();
});

const confClass = (c) => (c < 0.5 ? "lo" : c < 0.7 ? "mid" : "hi");
const evLinks = (ids) => ids.map((i) => `<span class="tag" title="${esc(bundle.evidence.find((e) => e.id === i)?.source || "")}">${esc(i)}</span>`).join("") || '<span class="muted">none</span>';
const pendingApproval = () => !$("#approval").classList.contains("hidden");

async function renderTab() {
  const body = $("#tab-body"), b = bundle;
  if (!b) return;
  if (activeTab === "req") {
    body.innerHTML = `<table><thead><tr><th>ID</th><th>Requirement</th><th>Categories</th><th>Risk</th><th>Conf.</th><th>Evidence</th><th>Status</th>${pendingApproval() ? "<th>Decision</th>" : ""}</tr></thead><tbody>${b.requirements.map((r) => {
      const d = decisions[r.id] || {};
      const stmt = d.action === "modify" ? d.statement : r.statement;
      return `<tr><td class="req-id">${esc(r.id)}<br><span class="tag">${esc(r.priority)}</span>${r.origin === "derived" ? '<br><span class="tag">derived</span>' : ""}</td>
      <td>${esc(stmt)}
        <details><summary>Details</summary>
          ${r.source ? `<p><b>Source${r.sourceVerified ? "" : " (unverified)"}:</b> "${esc(r.source)}"</p>` : ""}
          ${r.justification ? `<p><b>Why:</b> ${esc(r.justification)}</p>` : ""}
          ${r.acceptance.length ? `<b>Acceptance:</b><ul>${r.acceptance.map((a) => `<li>${esc(a)}</li>`).join("")}</ul>` : ""}
          ${r.story ? `<p><i>${esc(r.story)}</i></p>` : ""}
          ${r.regulations.length ? `<p><b>Controls:</b> ${r.regulations.map(esc).join("; ")}</p>` : ""}
          ${r.issues.length ? `<b>Issues:</b><ul>${r.issues.map((i) => `<li>[${esc(i.type)}] ${esc(i.detail)}${i.question ? ` - <i>${esc(i.question)}</i>` : ""}</li>`).join("")}</ul>` : ""}
          ${r.reviewerNote ? `<p><b>Reviewer note:</b> ${esc(r.reviewerNote)}</p>` : ""}
        </details></td>
      <td>${r.categories.map((c) => `<span class="tag">${esc(c)}</span>`).join("")}</td>
      <td><span class="tag ${esc(r.risk)}">${esc(r.risk)}</span></td>
      <td class="conf ${confClass(r.confidence)}">${r.confidence}</td>
      <td>${evLinks(r.evidence)}</td>
      <td><span class="tag ${esc(r.status)}">${esc(r.status)}</span></td>
      ${pendingApproval() ? `<td class="actions" data-id="${esc(r.id)}">
        <button class="sm ${d.action === "approve" ? "on-approve" : ""}" data-act="approve">Accept</button>
        <button class="sm ${d.action === "modify" ? "on-approve" : ""}" data-act="modify">Edit</button>
        <button class="sm ${d.action === "reject" ? "on-reject" : ""}" data-act="reject">Reject</button></td>` : ""}</tr>`;
    }).join("")}</tbody></table>`;
  } else if (activeTab === "comp") {
    body.innerHTML = b.compliance.length ? `<table><thead><tr><th>Req</th><th>Framework / standard</th><th>Control</th><th>Evidence</th><th>Gap</th><th>Checkpoint</th></tr></thead><tbody>${b.compliance.map((c) =>
      `<tr><td class="req-id">${esc(c.reqId)}</td><td>${esc(c.framework)}</td><td>${esc(c.control)}</td><td>${evLinks(c.evidence)}</td><td>${esc(c.gap)}</td><td>${esc(c.checkpoint)}</td></tr>`).join("")}</tbody></table>
      <p class="muted">The compliance agent does not make legal determinations; mappings need compliance/legal sign-off.</p>` : '<p class="muted">No mappings produced.</p>';
  } else if (activeTab === "risk") {
    body.innerHTML = b.risks.length ? `<table><thead><tr><th>ID</th><th>Risk</th><th>Likelihood</th><th>Impact</th><th>Level</th><th>Mitigation</th><th>Reqs</th></tr></thead><tbody>${b.risks.map((r) =>
      `<tr><td class="req-id">${esc(r.id)}</td><td>${esc(r.description)}</td><td>${esc(r.likelihood)}</td><td>${esc(r.impact)}</td><td><span class="tag ${esc(r.level)}">${esc(r.level)}</span></td><td>${esc(r.mitigation)}</td><td>${r.reqs.map(esc).join(", ")}</td></tr>`).join("")}</tbody></table>` : '<p class="muted">No risks produced.</p>';
  } else if (activeTab === "sdlc") {
    const s = b.sdlc;
    if (!s) { body.innerHTML = '<p class="muted">SDLC selection did not complete.</p>'; return; }
    body.innerHTML = `<h3>Ranked recommendation</h3>${s.ranking.map((r, i) =>
      `<div class="rank ${i === 0 ? "top" : ""}"><span>${esc(r.model)}</span><div class="bar"><i style="width:${r.score}%"></i></div><b>${r.score}%</b></div>`).join("")}
      <p>${esc(s.rationale)}</p>
      <h3>Decision factors</h3><table><tbody>${Object.entries(s.factors).map(([k, v]) => `<tr><td>${esc(meta.factors[k] || k)}</td><td><b>${v}/5</b></td><td class="muted">${esc(s.factorNotes[k] || "")}</td></tr>`).join("")}</tbody></table>
      <h3>${esc(s.chosen)} workflow</h3><div class="mermaid-box" id="mm"></div>
      ${s.phases.map((p) => `<div class="phase"><b>${esc(p.name)}</b>
        ${[["Activities", p.activities], ["Roles", p.roles], ["Deliverables", p.deliverables], ["Security", p.security], ["Compliance checkpoints", p.compliance]]
          .filter(([, v]) => v.length).map(([k, v]) => `<div class="muted">${k}</div><ul>${v.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>`).join("")}
        <div class="muted">Entry: ${esc(p.entry || "-")} &middot; Exit: ${esc(p.exit || "-")} &middot; Approval: ${esc(p.approval || "-")}</div></div>`).join("")}`;
    try { const { svg } = await mermaid.render("mm" + Date.now(), s.mermaid); $("#mm").innerHTML = svg; } catch { $("#mm").textContent = s.mermaid; }
  } else if (activeTab === "open") {
    body.innerHTML = `<h3>Clarification questions</h3>${b.openQuestions.length ? `<ul>${b.openQuestions.map((q) => `<li><b>${esc(q.id)}</b> ${esc(q.question)}</li>`).join("")}</ul>` : '<p class="muted">None.</p>'}
      <h3>Conflicts &amp; duplicates</h3>${b.conflicts.length ? `<ul>${b.conflicts.map((c) => `<li><b>${c.ids.map(esc).join(", ")}</b>: ${esc(c.detail)}</li>`).join("")}</ul>` : '<p class="muted">None detected.</p>'}`;
  } else if (activeTab === "ev") {
    body.innerHTML = b.evidence.map((e) => `<div class="ev"><b>${esc(e.id)}</b> <span class="tag">${esc(e.category)}</span> ${esc(e.source)} <span class="muted">retrieval confidence ${e.confidence}</span><pre>${esc(e.text.slice(0, 700))}</pre></div>`).join("") || '<p class="muted">No evidence retrieved.</p>';
  } else if (activeTab === "srs") {
    body.innerHTML = `<div class="md" id="md">${marked.parse(b.srs)}</div>`;
    for (const code of $$("#md code.language-mermaid")) {
      const holder = document.createElement("div"); holder.className = "mermaid-box";
      try { const { svg } = await mermaid.render("s" + Math.random().toString(36).slice(2), code.textContent); holder.innerHTML = svg; code.closest("pre").replaceWith(holder); } catch { /* keep code */ }
    }
  } else if (activeTab === "audit") {
    const rows = await api(`/api/runs/${run}/audit`);
    body.innerHTML = `<p class="muted">${rows.length} records. Every prompt, output, evidence set and human decision is stored in artifacts/runs/${esc(run)}/audit.jsonl.</p><table><thead><tr><th>Time</th><th>Event</th><th>Detail</th></tr></thead><tbody>${rows.map((r) => {
      const { ts, run: _r, event, ...rest } = r;
      return `<tr><td class="muted">${esc(ts.slice(11, 19))}</td><td><b>${esc(event)}</b></td><td><details><summary>${esc(rest.agent || rest.stage || rest.summary || "")}</summary><pre style="white-space:pre-wrap;font-size:12px">${esc(JSON.stringify(rest, null, 2))}</pre></details></td></tr>`;
    }).join("")}</tbody></table>`;
  }
}

/* ---------- approval ---------- */
$("#tab-body").addEventListener("click", (e) => {
  const btn = e.target.closest("button[data-act]"); if (!btn) return;
  const id = btn.closest("td").dataset.id, act = btn.dataset.act, req = bundle.requirements.find((r) => r.id === id);
  if (act === "modify") {
    const text = prompt("Edit requirement statement:", decisions[id]?.statement || req.statement);
    if (text === null || !text.trim()) return;
    decisions[id] = { action: "modify", statement: text.trim() };
  } else {
    decisions[id] = { action: act };
    if (act === "reject") { const note = prompt("Reason for rejection (optional):"); if (note) decisions[id].note = note; }
  }
  renderTab();
});
$("#approve-all").onclick = () => { bundle.requirements.forEach((r) => { if (decisions[r.id]?.action !== "modify" && decisions[r.id]?.action !== "reject") decisions[r.id] = { action: "approve" }; }); renderTab(); };
$("#submit-approval").onclick = async () => {
  const reviewer = $("#reviewer").value.trim();
  if (!reviewer) return showError("Enter your name as reviewer before submitting.");
  hideError();
  const sdlc = {}; $$("#sdlc-approvers input").forEach((i) => (sdlc[i.dataset.role] = i.checked));
  try {
    await post(`/api/runs/${run}/approve`, { reviewer, requirements: decisions, sdlc, regulatoryAck: $("#regAck").checked });
    $("#approval").classList.add("hidden");
    listen(lastEvent);
  } catch (e) { showError(e.message); }
};

/* ---------- interview ---------- */
function renderTemplate() { $("#i-template").innerHTML = (meta.roles[$("#i-role").value] || []).map((q) => `<li>${esc(q)}</li>`).join(""); }
$("#i-role").onchange = () => { renderTemplate(); resetChat(); };
$("#i-useCase").onchange = resetChat;
$("#i-reset").onclick = resetChat;
function addMsg(role, text) {
  const d = document.createElement("div"); d.className = "msg " + role; d.textContent = text;
  $("#chat-log").appendChild(d); $("#chat-log").scrollTop = 1e9; return d;
}
function resetChat() {
  chat = []; $("#chat-log").innerHTML = "";
  addMsg("assistant", `Hello! I'll ask a few questions to capture requirements for your ${$("#i-useCase").selectedOptions[0]?.text.toLowerCase() || "project"}. Start by describing the business objective and who will use the system.`);
}
$("#chat-input").addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); $("#chat-form").requestSubmit(); } });
$("#chat-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const input = $("#chat-input"), text = input.value.trim(); if (!text) return;
  input.value = ""; chat.push({ role: "user", content: text }); addMsg("user", text);
  const bubble = addMsg("assistant", ""); let reply = ""; $("#chat-send").disabled = true;
  try {
    const res = await fetch("/api/interview", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ role: $("#i-role").value, useCase: $("#i-useCase").value, history: chat }) });
    if (!res.ok) throw new Error(await res.text());
    const reader = res.body.getReader(), dec = new TextDecoder(); let buf = "";
    for (;;) {
      const { value, done } = await reader.read(); if (done) break;
      buf += dec.decode(value, { stream: true });
      const parts = buf.split("\n\n"); buf = parts.pop();
      for (const p of parts) {
        const d = JSON.parse(p.replace(/^data: /, ""));
        if (d.token) { reply += d.token; bubble.textContent = reply; $("#chat-log").scrollTop = 1e9; }
        if (d.error) bubble.textContent = reply + "\n[" + d.error + "]";
        if (d.sources?.length) { const s = document.createElement("small"); s.textContent = "Sources: " + d.sources.join(", "); bubble.appendChild(s); }
      }
    }
    chat.push({ role: "assistant", content: reply });
  } catch (err) { bubble.textContent = "Error: " + err.message; chat.pop(); }
  $("#chat-send").disabled = false; input.focus();
});
$("#i-analyze").onclick = () => {
  const transcript = chat.filter((m) => m.role === "user").map((m) => m.content).join("\n\n");
  if (transcript.length < 20) return alert("Answer a few interview questions first.");
  $("#text").value = transcript; $("#useCase").value = $("#i-useCase").value; $("#role").value = $("#i-role").value;
  gotoView("analyze");
};

/* ---------- knowledge base ---------- */
$("#kb-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const q = $("#kb-q").value.trim(); if (!q) return;
  const hits = await api("/api/kb/search?q=" + encodeURIComponent(q) + "&k=8");
  $("#kb-results").innerHTML = hits.map((h) => `<div class="ev"><span class="tag">${esc(h.category)}</span><b>${esc(h.source)}</b> <span class="muted">BM25 ${h.score} &middot; confidence ${h.confidence}</span><pre>${esc(h.text)}</pre></div>`).join("") || '<p class="muted">No results.</p>';
});

init();

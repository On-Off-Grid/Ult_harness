/* ULT_HARNESS war room — vanilla JS, no framework, offline-capable.
 * Data: GET /api/v1/status (poll) + /api/v1/findings + /api/v1/providers,
 * live: /ws (OrchestrationEvent stream). Controls: POST /api/v1/halt|resume,
 * POST /api/triage/{id}/confirm|reject.
 * NOTE: UI only — T3MP3ST is a design reference, never vendored here.
 */
"use strict";

const $ = (id) => document.getElementById(id);
const POLL_MS = 4000;
const MAX_EVENTS = 100;

const state = {
  timer: null,
  ws: null,
  wsTimer: null,
  findings: {},
  events: [],
};

/* ── Formatting helpers ─────────────────────────────────────────────── */
function usd(n, digits = 3) {
  if (n === null || n === undefined || Number.isNaN(n)) return "$0.000";
  const v = Number(n);
  if (v === 0) return "$0.000";
  if (Math.abs(v) < 0.01) return "$" + v.toFixed(5);
  return "$" + v.toFixed(digits);
}
function esc(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}
function now() {
  return new Date().toLocaleTimeString([], { hour12: false });
}

/* ── Connection pill ────────────────────────────────────────────────── */
function setConn(ok) {
  const pill = $("conn-pill");
  pill.dataset.state = ok ? "up" : "down";
  pill.textContent = ok ? "link: up" : "link: down";
}

/* ── Hunt state panel ───────────────────────────────────────────────── */
function renderStatus(s) {
  const halted = s.hunt === "halted" || s.kill_switch === true;
  const badge = $("hunt-badge");
  badge.textContent = halted ? "HALTED" : "ACTIVE";
  badge.dataset.state = halted ? "halted" : "active";
  $("halt-btn").dataset.state = halted ? "halted" : "active";
  $("halt-btn").textContent = halted ? "▶ RESUME" : "⏸ HALT";

  $("crumb").textContent =
    `${esc(s.program)} · ${esc(s.platform)} · ${s.dry_run ? "dry-run" : "live"}`;
  $("f-program").textContent = s.program || "—";
  $("f-platform").textContent = s.platform || "—";
  $("f-mode").textContent = s.dry_run ? "dry-run" : "live";
  $("f-tasks").textContent = s.tasks_total ?? 0;
  $("f-specialists").textContent = s.active_specialists ?? 0;
  const viol = $("f-violations");
  viol.textContent = s.scope_violations ?? 0;
  viol.classList.toggle("bad", (s.scope_violations ?? 0) > 0);
  $("f-noise").textContent = Object.values(s.noise_dropped || {}).reduce((a, b) => a + b, 0);
  $("f-reports").textContent = s.reports_written ?? 0;

  const fc = $("findings-counts");
  const counts = s.findings || {};
  fc.innerHTML = Object.entries(counts)
    .map(([k, v]) => `<span class="fc fc-${esc(k)}"><b>${v}</b> ${esc(k)}</span>`)
    .join("") || '<span class="empty">no findings</span>';

  renderBudget(s.budget || {});
  renderLanes(s.lanes || {});
}

/* ── Budget panel ───────────────────────────────────────────────────── */
function renderBudget(b) {
  const cost = b.total_cost_usd ?? 0;
  $("budget-cost").textContent = usd(cost);
  $("b-tokens").textContent = (b.total_tokens ?? 0).toLocaleString();
  $("b-agents").textContent = b.agents ?? 0;
  $("b-gpu").textContent = (b.gpu_hours ?? 0).toFixed(4);

  const line = b.budget_line_usd || 0.5;
  const pct = line > 0 ? Math.min(100, (cost / line) * 100) : 0;
  const fill = $("meter-fill");
  fill.style.width = pct + "%";
  fill.dataset.state = pct >= 100 ? "over" : pct >= 50 ? "warn" : "ok";
  $("meter-pct").textContent = pct.toFixed(0) + "%";
  $("meter-actual").textContent = usd(cost) + " used";
  const proj = b.projection || {};
  $("meter-proj").textContent =
    "proj " + usd(proj.projected_cost_usd) +
    (proj.within_budget === false ? " ⚠" : "");

  const rows = Object.entries(b.per_provider || {});
  const tbody = document.querySelector("#per-provider tbody");
  if (!rows.length) {
    tbody.innerHTML = '<tr><td colspan="4" class="empty">no usage recorded</td></tr>';
    return;
  }
  tbody.innerHTML = rows
    .sort((a, b2) => (b2[1].calls ?? 0) - (a[1].calls ?? 0))
    .map(([name, v]) =>
      `<tr>
        <td>${esc(name)}</td>
        <td>${v.calls ?? 0}</td>
        <td class="num">${(v.input_tokens ?? 0).toLocaleString()} / ${(v.output_tokens ?? 0).toLocaleString()}</td>
        <td class="num">${usd(v.cost_usd)}</td>
      </tr>`
    )
    .join("");
}

/* ── Lanes (routing guard) ──────────────────────────────────────────── */
function renderLanes(lanes) {
  const n = lanes.scrub_reroutes ?? 0;
  $("scrub-count").textContent = n;
  $("lane-restricted").classList.toggle("hot", n > 0);
}

/* ── Providers panel (S7.3) ─────────────────────────────────────────── */
function renderProviders(providers) {
  const tbody = document.querySelector("#providers tbody");
  if (!Array.isArray(providers) || !providers.length) {
    tbody.innerHTML = '<tr><td colspan="7" class="empty">no providers configured</td></tr>';
    return;
  }
  const order = { LOCAL: 0, LOCAL_HEAVY: 1, PAID_FREE: 2, PAID_PREMIUM: 3 };
  const sorted = [...providers].sort(
    (a, b) => (order[a.tier] ?? 9) - (order[b.tier] ?? 9) || a.name.localeCompare(b.name)
  );
  tbody.innerHTML = sorted
    .map((p) => {
      const live = p.live_models || [];
      const drift = p.live_models && p.models.some((m) => !live.includes(m));
      const state = !p.enabled ? "disabled" : !p.available ? "down" : "up";
      return `<tr class="prov-${state}">
        <td><b>${esc(p.name)}</b>${p.has_key ? ' <span class="keydot" title="key present">●</span>' : ""}</td>
        <td class="tier-${esc(p.tier)}">${esc(p.tier)}</td>
        <td><span class="lane-badge ${p.lane === "RESTRICTED" ? "restricted" : "safe"}">${esc(p.lane)}</span></td>
        <td><span class="dot ${state}"></span>${state}</td>
        <td class="num" title="rate limits (rpm / rpd)">${(p.rpm ?? 0).toLocaleString()} / ${(p.rpd ?? 0).toLocaleString()}</td>
        <td class="num" title="${esc(p.models.join(", "))}">${p.models.length} cfg${p.live_models ? ` / ${live.length} live${drift ? " ⚠" : ""}` : ""}</td>
        <td class="num">${((p.context ?? 0) / 1000).toFixed(0)}k</td>
      </tr>`;
    })
    .join("");
}

/* ── Findings panel ─────────────────────────────────────────────────── */
function renderFindings(list) {
  state.findings = {};
  (list || []).forEach((f) => (state.findings[f.task_id] = f));
  const total = $("findings-total");
  total.textContent = (list || []).length;
  const el = $("findings-list");
  if (!(list || []).length) {
    el.innerHTML = '<div class="empty">no findings yet</div>';
    return;
  }
  el.innerHTML = (list || [])
    .map((f) => {
      const adjudicable = f.status === "validating";
      return `<div class="finding fs-${esc(f.status)}" data-id="${esc(f.task_id)}">
        <div class="finding-head">
          <span class="sev">${esc(f.category)}</span>
          <span class="fstatus st-${esc(f.status)}">${esc(f.status)}</span>
          <span class="fend" title="${esc(f.endpoint)}">${esc(f.endpoint)}</span>
        </div>
        <div class="ftitle">${esc(f.title)}</div>
        <div class="fby">${esc(f.specialist)}</div>
        ${adjudicable ? `<div class="factions">
          <button class="btn mini ok" data-act="confirm" data-id="${esc(f.task_id)}">✓ confirm</button>
          <button class="btn mini no" data-act="reject" data-id="${esc(f.task_id)}">✗ reject (FP)</button>
        </div>` : ""}
      </div>`;
    })
    .join("");
}

/* ── Event log ──────────────────────────────────────────────────────── */
function pushEvent(e) {
  if (!e || !e.event_type) return;
  state.events.unshift({ ...e, at: now() });
  if (state.events.length > MAX_EVENTS) state.events.length = MAX_EVENTS;
  renderEvents();
}
function renderEvents() {
  $("events-total").textContent = state.events.length;
  const el = $("event-log");
  if (!state.events.length) {
    el.innerHTML = '<div class="empty">awaiting events…</div>';
    return;
  }
  el.innerHTML = state.events
    .map((e) => {
      const extra = e.payload && Object.keys(e.payload).length
        ? `<span class="ev-payload">${esc(JSON.stringify(e.payload))}</span>` : "";
      return `<div class="ev ev-${esc(e.event_type)}">
        <span class="ev-time">${e.at}</span>
        <span class="ev-type">${esc(e.event_type)}</span>
        <span class="ev-src">${esc(e.source_component || "")}</span>
        ${extra}
      </div>`;
    })
    .join("");
}

/* ── Polling ────────────────────────────────────────────────────────── */
async function poll() {
  try {
    const [st, fd, pr] = await Promise.all([
      fetch("/api/v1/status").then((r) => (r.ok ? r.json() : null)),
      fetch("/api/v1/findings").then((r) => (r.ok ? r.json() : [])),
      fetch("/api/v1/providers").then((r) => (r.ok ? r.json() : [])),
    ]);
    if (!st) throw new Error("status unavailable");
    renderStatus(st);
    renderFindings(fd);
    renderProviders(Array.isArray(pr) ? pr : st.routing || []);
    $("last-updated").textContent = "updated " + now();
    setConn(true);
  } catch {
    setConn(false);
  }
}
function startPolling() {
  if (state.timer) return;
  poll();
  state.timer = setInterval(poll, POLL_MS);
}

/* ── WebSocket (live events) ────────────────────────────────────────── */
function connectWS() {
  if (state.wsTimer) clearTimeout(state.wsTimer);
  try {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${proto}://${location.host}/ws`);
    state.ws = ws;
    ws.onmessage = (m) => {
      try {
        pushEvent(JSON.parse(m.data));
        // A control-plane event may change hunt state → refresh quickly.
        poll();
      } catch {
        /* ignore malformed frame */
      }
    };
    ws.onclose = () => {
      state.ws = null;
      setConn(false);
      state.wsTimer = setTimeout(connectWS, POLL_MS * 2); // backoff + retry
    };
    ws.onerror = () => ws.close();
  } catch {
    state.wsTimer = setTimeout(connectWS, POLL_MS * 2);
  }
}

/* ── Operator controls ──────────────────────────────────────────────── */
async function postHalt() {
  const halted = $("halt-btn").dataset.state === "halted";
  const url = halted ? "/api/v1/resume" : "/api/v1/halt";
  $("halt-btn").disabled = true;
  try {
    await fetch(url, { method: "POST" });
  } finally {
    $("halt-btn").disabled = false;
  }
  poll();
}

async function adjudicate(id, act, btn) {
  if (btn) btn.disabled = true;
  const body = act === "reject" ? { fp_reason: "operator false-positive (war room)" } : { evidence: {} };
  try {
    await fetch(`/api/v1/finding/${encodeURIComponent(id)}/${act}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  } catch {
    if (btn) btn.disabled = false;
    return;
  }
  pushEvent({
    event_type: act === "confirm" ? "finding_confirmed" : "finding_rejected",
    source_component: "war_room",
    correlation_id: id,
    payload: { by: "operator" },
  });
  poll();
}

/* ── Wiring ─────────────────────────────────────────────────────────── */
function init() {
  $("halt-btn").addEventListener("click", () => {
    const willHalt = $("halt-btn").dataset.state !== "halted";
    if (willHalt) {
      const ok = window.confirm("HALT the hunt?\n\nNew dispatches and LLM calls stop; in-flight work finishes.");
      if (!ok) return;
    }
    postHalt();
  });
  $("refresh-btn").addEventListener("click", poll);
  $("findings-list").addEventListener("click", (e) => {
    const btn = e.target.closest("button[data-act]");
    if (btn) adjudicate(btn.dataset.id, btn.dataset.act, btn);
  });
  startPolling();
  connectWS();
}

document.addEventListener("DOMContentLoaded", init);

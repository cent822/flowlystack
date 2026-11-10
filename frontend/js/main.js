import { fmt, pinModelOrder, shortModel } from "./util.js";
import { startRouter, current } from "./router.js";
import { showSettings } from "./settings.js";
import { showWhatsNew } from "./whatsnew.js";
import "./account.js";
import "./samples.js";
import { isDark, setMode } from "./theme.js";
import { showPrompts } from "./prompts.js";
import { showStudio } from "./studio.js";
import { showTrash, refreshTrashCount } from "./trash.js";
import { showLinkshell } from "./linkshell/home.js";
import { showCollections } from "./collections/home.js";
import { showGallery } from "./gallery/home.js";
import { showLattice } from "./lattice/home.js";
import { ICONS, registerCommands } from "./palette.js";
import { gauge } from "./charts/gauge.js";
import { contextBars } from "./charts/contextbars.js";
import { areaChart, areaTable } from "./charts/area.js";
import { calendar } from "./charts/calendar.js";
import { hourmap } from "./charts/hourmap.js";
import { lollipop } from "./charts/lollipop.js";
import { racetrack } from "./charts/racetrack.js";
import { sparkline } from "./charts/sparkline.js";

const $ = (s) => document.querySelector(s);
const state = { days: 30, sort: { key: "last_ts", dir: -1 }, data: {}, table: false, areaMeta: null, source: "claude", sources: [], gen: 0 };
const get = (p) => fetch("/api/" + p + (p.includes("?") ? "&" : "?") + "source=" + state.source).then((r) => r.json());
const isNa = (x) => !!x && x.na === true;   // a route the chosen agent cannot feed answers {na: true, reason}
const naBody = (el, reason) => { d3.select(el).selectAll("*").remove(); d3.select(el).append("p").attr("class", "na").text("N/A · " + reason); };
const codex = () => state.source !== "claude";   // a source with real reported limits and its own wording; Ollama differs below
const ollama = () => state.source === "ollama";

// ---------- agent source ----------
// Card titles and small labels follow the agent; the cards themselves are the same. Defaults are read from index.html.
const TEXT = {
  codex: {
    "intro-title": { html: "Your Codex, at a glance" },
    "intro-sub": { html: "Read locally from <code>~/.codex</code>. Nothing leaves this machine." },
    "limits-tag": { html: "reported by Codex", title: "These percentages come from Codex itself, recorded in its session files." },
    "context-tag": { html: "reported by Codex", title: "Window sizes are the model_context_window Codex records for each turn." },
    "daily-sub": { html: "Fresh input + output (reasoning included), by model. Cached input excluded." },
    "tools-title": { html: "Tools Codex reaches for" },
  },
  ollama: {
    "intro-title": { html: "Your Ollama models, at a glance" },
    "intro-sub": { html: "Read locally from Open WebUI's chat database. Nothing leaves this machine." },
    "limits-tag": { html: "no limits", title: "Ollama runs on your own machine and has no usage limits." },
    "context-tag": { html: "not reported", title: "Ollama does not report a context size per chat." },
    "daily-sub": { html: "Prompt + generated tokens, by model." },
    "projects-title": { html: "Models" },
    "tools-title": { html: "Speed by model" },
    "tools-sub": { html: "tokens per second" },
  },
};
const TEXT_DEFAULT = {};
for (const id of new Set(Object.values(TEXT).flatMap(Object.keys))) { const el = $("#" + id); TEXT_DEFAULT[id] = { html: el.innerHTML, title: el.title }; }
function applyText() {
  for (const [id, d] of Object.entries(TEXT_DEFAULT)) {
    const t = { ...d, ...(TEXT[state.source]?.[id] || {}) }, el = $("#" + id);
    el.innerHTML = t.html;
    if (t.title !== undefined) el.title = t.title;
  }
}
const shortLabel = (s) => s.label.split(" /")[0];
function renderSourceMenu() {
  const on = state.sources.filter((s) => s.enabled && s.detected);
  $("#src-menu").hidden = on.length < 2 || !$("#page-dashboard") || $("#page-dashboard").hidden;
  $("#src-label").textContent = shortLabel(state.sources.find((s) => s.id === state.source) || { label: "Claude Code" });
  $("#src-list").innerHTML = `<div class="pr-menuhead">Agent</div>` + on.map((s) =>
    `<button type="button" class="pr-menuitem" role="menuitemradio" aria-checked="${s.id === state.source}" data-src="${s.id}"><span>${s.label}</span>${
      s.id === state.source ? `<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg>` : ""}</button>`).join("");
}
async function loadSources() {
  let list = [];
  try { list = await fetch("/api/sources").then((r) => r.json()); } catch (e) {}
  state.sources = Array.isArray(list) ? list : [];
  let want = new URLSearchParams(location.search).get("source");
  if (!want) try { want = localStorage.getItem("flowlystack-source"); } catch (e) {}
  const usable = state.sources.some((s) => s.id === want && s.enabled && s.detected);
  state.source = usable ? want : "claude";
  applyText(); renderSourceMenu();
}
function switchSource(id) {
  if (id === state.source) return;
  state.source = id; state.gen++; state.data = {};
  try { localStorage.setItem("flowlystack-source", id); } catch (e) {}
  $("#gauges").innerHTML = ""; delete $("#gauges").dataset.built;   // gauges rebuild instead of sweeping between two agents
  applyText(); renderSourceMenu(); loadAll();
}
$("#src-list").addEventListener("click", (e) => {
  const b = e.target.closest("[data-src]"); if (!b) return;
  $("#src-menu").open = false;
  switchSource(b.dataset.src);
});

// The agent menu opens when the pointer rests on the button and closes when it leaves the button and its list (a short delay each way: a pointer sweeping past
// does not open it, a short gap between the button and the list does not close it). A click on the button while it is open from hovering keeps it open.
const srcMenu = $("#src-menu"); let tSrc = 0, tSrcOpen = 0, byHover = false;
srcMenu.addEventListener("pointerenter", (e) => {
  clearTimeout(tSrc); if (e.pointerType === "touch" || srcMenu.open) return;
  clearTimeout(tSrcOpen); tSrcOpen = setTimeout(() => { if (srcMenu.matches(":hover") && !srcMenu.open) { srcMenu.open = true; byHover = true; } }, 120);
});
srcMenu.addEventListener("pointerleave", (e) => {
  clearTimeout(tSrcOpen); if (e.pointerType === "touch" || !srcMenu.open) return;
  clearTimeout(tSrc); tSrc = setTimeout(() => { if (!srcMenu.matches(":hover")) { srcMenu.open = false; byHover = false; } }, 250);
});
srcMenu.querySelector("summary").addEventListener("click", (e) => { if (byHover && srcMenu.open) e.preventDefault(); byHover = false; });   // it is already open: the click should not shut it
srcMenu.addEventListener("toggle", () => { if (!srcMenu.open) byHover = false; });

// ---------- theme ----------
// The mode itself lives in theme.js and is changed from the account menu, the Settings page or ⌘K; charts redraw when it changes.
addEventListener("flowlystack-theme", () => renderAll());   // charts read colors at draw time, so redraw with the new theme
matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => renderAll());

// Dashboard top-bar switch: one button, two jobs. It shows the Sun in night mode (press for day) and the Moon in day mode (press for night).
const themeBtn = $("#theme-toggle");
function paintThemeBtn() {
  const dark = isDark(), label = dark ? "Switch to day mode" : "Switch to night mode";
  themeBtn.innerHTML = dark ? ICONS.theme : ICONS.moon;
  themeBtn.setAttribute("aria-label", label); themeBtn.title = label;
}
themeBtn.addEventListener("click", () => setMode(isDark() ? "light" : "dark"));
addEventListener("flowlystack-theme", paintThemeBtn);
matchMedia("(prefers-color-scheme: dark)").addEventListener("change", paintThemeBtn);
paintThemeBtn();

// ---------- renderers ----------
function renderKpis() {
  const { overview: o, daily } = state.data;
  if (isNa(o)) {
    const k = d3.select("#kpis").selectAll(".kpi").data(d3.range(6)).join("div").attr("class", (i) => `kpi is-na k${i + 1}`);
    k.html(() => `<span class="kpi-label">N/A</span><span class="kpi-value">N/A</span><span class="kpi-sub">${o.reason}</span>`);
    return;
  }
  const perDay = isNa(daily) ? [] : d3.rollups(daily.rows, (v) => d3.sum(v, (r) => r.t), (r) => r.d).sort((a, b) => a[0].localeCompare(b[0])).slice(-14).map((d) => d[1]);
  const tiles = [
    { label: "Sessions today", value: o.sessions.today, sub: `${o.sessions.week} this week · ${o.sessions.total} total` },
    { label: "Prompts today", value: o.prompts.today, sub: `${fmt.n(o.prompts.total)} all time` },
    { label: "Tokens today", value: fmt.compact(o.tokens.today_billable), sub: `${ollama() ? "processed" : codex() ? "estimated" : "billable"} · 14-day trend`, spark: perDay },
    { label: "Output tokens", value: fmt.compact(o.tokens.output), sub: ollama() ? (o.speed?.avg_tps ? `${o.speed.avg_tps} tokens/sec on average` : "generated tokens") : codex() ? "reasoning included" : `${fmt.compact(o.tokens.cache_create)} cache writes` },
    o.cache_hit_rate == null
      ? { label: "Cache hit rate", value: "N/A", sub: "not reported by this source", na: true }
      : { label: "Cache hit rate", value: fmt.pct(o.cache_hit_rate), sub: `${fmt.compact(o.tokens.cache_read)} reused` },
    o.cost_usd == null
      ? { label: "Estimated cost", value: "N/A", sub: `${ollama() ? "runs locally" : "no cost in the files"} · ${fmt.n(o.api_calls)} model calls`, na: true }
      : { label: "Estimated cost", value: fmt.usd(o.cost_usd), sub: `${fmt.n(o.api_calls)} API calls` },
  ];
  const k = d3.select("#kpis").selectAll(".kpi").data(tiles).join("div").attr("class", (d, i) => `kpi${d.na ? " is-na" : ""} k${i + 1}`);
  k.html((d) => `<span class="kpi-label">${d.label}</span><span class="kpi-value">${d.value}</span><span class="kpi-sub">${d.sub}</span>`);
  k.filter((d) => d.spark).append("span").attr("class", "spark").each(function (d) { sparkline(this, d.spark, { fluid: true }); });
}

const windowName = (min) => (min === 300 ? "5-hour" : min === 10080 ? "Weekly" : min % 1440 === 0 ? `${min / 1440}-day` : `${Math.round(min / 60)}-hour`);
function renderGauges() {
  const { limits: l } = state.data;
  const el = $("#gauges");
  if (isNa(l)) { naBody(el, l.reason); delete el.dataset.built; $("#gauge-note").textContent = ""; return; }
  const items = [["g5", l.five_hour]].concat(l.weekly ? [["g7", l.weekly]] : []);
  const built = items.map((i) => i[0]).join();
  if (el.dataset.built !== built) {   // build the frame once; gauges then update in place instead of restarting
    el.dataset.built = built; el.classList.toggle("two", items.length > 1);
    el.innerHTML = items.map(([id]) => `<div class="gauge"><div id="${id}"></div><div class="gauge-title" id="${id}t"></div><div class="gauge-sub" id="${id}s"></div></div>`).join("");
  }
  for (const [id, f] of items) {
    gauge($("#" + id), { value: f.used / f.cap, limit: codex() });
    $("#" + id + "t").textContent = codex() ? `${windowName(f.window_minutes)} limit` : "5-hour activity";
    $("#" + id + "s").textContent = !f.resets_at ? "No active window"
      : codex() ? `${Math.round(f.used)}% used · resets in ${fmt.until(f.resets_at)}`
      : `${fmt.compact(f.used)} of ${fmt.compact(f.cap)} · resets in ${fmt.until(f.resets_at)}`;
  }
  $("#gauge-note").textContent = codex()
    ? `Reported by Codex${l.plan ? ` (${l.plan} plan)` : ""}, as of the newest session that recorded it. 100% is your plan's limit.`
    : `100% = ${l.five_hour.cap_source}. Real plan limits aren't stored on disk; set a cap with FLOWLYSTACK_SESSION_TOKENS (or limits.session_tokens in flowlystack.config.json).`;
}

function renderContext() {
  const x = state.data.sessions;
  if (isNa(x)) naBody($("#context"), x.reason);
  else if (x.length && x.every((s) => !s.ctx_window)) naBody($("#context"), "this source does not report context size");
  else contextBars($("#context"), x);
}

function renderLive() {
  const live = Array.isArray(state.data.live) ? state.data.live : [];   // Codex answers N/A: no pill
  const busy = live.filter((s) => s.status === "busy").length;
  $("#live-pill").hidden = live.length === 0;
  $("#live-text").textContent = `${live.length} running${busy ? ` · ${busy} busy` : ""}`;
}

function renderArea() {
  const { daily } = state.data;
  if (isNa(daily)) { state.areaMeta = null; $("#area-legend").innerHTML = ""; $("#area-table").innerHTML = ""; naBody($("#area"), daily.reason); return; }
  const since = d3.timeFormat("%Y-%m-%d")(d3.timeDay.offset(new Date(), -(state.days - 1)));
  if (!daily.rows.some((r) => r.d >= since && r.t > 0)) {   // nothing in this range: say so instead of drawing empty axes
    state.areaMeta = null; $("#area-legend").innerHTML = ""; $("#area-table").innerHTML = "";
    d3.select("#area").selectAll("*").remove(); d3.select("#area").append("p").attr("class", "na").text(`No activity in the last ${state.days} days`);
    return;
  }
  pinModelOrder(daily.rows.map((r) => r.model));
  state.areaMeta = areaChart($("#area"), $("#area-legend"), daily, state.days);
  areaTable($("#area-table"), state.areaMeta);
}

function renderSessions() {
  if (isNa(state.data.sessions)) { $("#sessions-count").textContent = ""; $("#sessions-table").replaceChildren(); naBody($("#sessions-na"), state.data.sessions.reason); return; }
  $("#sessions-na").replaceChildren();
  const sessions = state.data.sessions.slice(0, 10);   // the API returns newest first; the table keeps only the 10 most recent, then sorts those
  const cols = [
    { key: "title", label: "Session" }, { key: "model", label: "Model" }, { key: "first_ts", label: "Started", num: true },
    { key: "prompts", label: "Prompts", num: true }, { key: "calls", label: "Calls", num: true },
    { key: "tokens", label: "Tokens", num: true }, { key: "cost_usd", label: "Cost", num: true }, { key: "ctx_pct", label: "Context", num: true },
  ];
  const { key, dir } = state.sort;
  const rows = [...sessions].sort((a, b) => (d3.ascending(a[key] ?? "", b[key] ?? "")) * dir);
  $("#sessions-count").textContent = `${sessions.length} most recent`;
  const t = d3.select("#sessions-table"); t.selectAll("*").remove();
  t.append("thead").append("tr").selectAll("th").data(cols).join("th")
    .attr("class", (c) => "sortable" + (c.num ? " num" : "")).attr("aria-sort", (c) => (c.key === key ? (dir > 0 ? "ascending" : "descending") : "none"))
    .attr("tabindex", 0).text((c) => c.label + (c.key === key ? (dir > 0 ? " ↑" : " ↓") : ""))
    .on("click", (_, c) => { state.sort = { key: c.key, dir: c.key === key ? -dir : -1 }; renderSessions(); })
    .on("keydown", (e, c) => { if (e.key === "Enter") { state.sort = { key: c.key, dir: c.key === key ? -dir : -1 }; renderSessions(); } });
  const tr = t.append("tbody").selectAll("tr").data(rows).join("tr");
  tr.append("td").html((d) => `<div class="title"><i class="${d.live ? "live-dot" : "idle-dot"}"></i><div><div>${d.title}</div><div class="sub">${d.project || ""}</div></div></div>`);
  tr.append("td").text((d) => shortModel(d.model));
  tr.append("td").attr("class", "num").attr("title", (d) => new Date(d.first_ts * 1000).toLocaleString()).text((d) => fmt.ago(d.first_ts));
  tr.append("td").attr("class", "num").text((d) => d.prompts);
  tr.append("td").attr("class", "num").text((d) => d.calls);
  tr.append("td").attr("class", "num").text((d) => fmt.compact(d.tokens));
  tr.append("td").attr("class", "num").text((d) => (d.cost_usd == null ? "N/A" : fmt.usd(d.cost_usd)));
  tr.append("td").attr("class", "num").append("div").attr("class", "ctxcell").each(function (d) {
    const c = d3.select(this);
    if (!d.ctx_window) { c.append("span").text("N/A"); return; }
    c.append("span").text(fmt.pct(d.ctx_pct));
    c.append("span").attr("class", "bar").append("i").style("width", Math.max(2, d.ctx_pct * 100) + "%");
    c.append("span").each(function () { sparkline(this, d.ctx_series); });
  });
}

function renderRest() {
  const d = state.data;
  const draw = (id, data, fn) => (isNa(data) ? naBody($(id), data.reason) : fn($(id), data));
  draw("#calendar", d.heatmap, calendar); draw("#hourmap", d.heatmap, hourmap);
  draw("#projects", d.projects, lollipop);
  draw("#tools", d.tools, (el, data) => racetrack(el, data, ollama() ? "tokens/sec" : "calls"));
}

function renderAll() {
  if (!state.data.overview || $("#page-dashboard").hidden) return;   // charts need a visible container to measure
  renderKpis(); renderGauges(); renderContext(); renderLive(); renderArea(); renderRest(); renderSessions();
}

// ---------- sidebar: auto-hide ----------
// The sidebar rests as the icon strip (`.collapsed`) on every landing. Hovering it (or tabbing into it) adds `.peek`, which opens the full
// sidebar as an overlay (css: app.css "Auto-hide sidebar"); leaving closes it again. The top-bar button pins it open for this visit only
// (nothing is saved), so the next landing starts as the strip again.
const app = $("#app"), side = $("#sidebar"), narrow = matchMedia("(max-width: 768px)");
// The browser tooltips on the icon links (title) only help while they are icons; with the labels showing they are noise, so they are set aside meanwhile.
function labelsShown(on) {
  side.querySelectorAll("[title], [data-title]").forEach((el) => {
    if (on && el.hasAttribute("title")) { el.dataset.title = el.title; el.removeAttribute("title"); }
    else if (!on && el.dataset.title !== undefined) { el.title = el.dataset.title; delete el.dataset.title; }
  });
}
function setCollapsed(on) {
  app.classList.toggle("collapsed", on);
  app.classList.remove("peek");
  labelsShown(!on);
  const t = $("#side-toggle"), label = on ? "Pin sidebar open" : "Unpin sidebar (auto-hide)";
  t.setAttribute("aria-expanded", String(!on)); t.setAttribute("aria-label", label); t.title = label;
}
setCollapsed(true);
$("#side-toggle").addEventListener("click", () => setCollapsed(!app.classList.contains("collapsed")));

const OPEN_MS = 120, CLOSE_MS = 140;   // a delay so a pointer sweeping past does not open it, and a small slip does not close it
let hover = false, pressed = false, suppressed = false, tOpen = 0, tClose = 0;   // suppressed: the palette closed the overlay while the pointer stayed inside; no reopening until it leaves
const peeking = () => app.classList.contains("peek");
const held = () => !$("#account-menu").hidden || !!document.querySelector("dialog[open]") || side.matches(":has(:focus-visible)");   // menu, ⌘K palette or keyboard focus keep it open
function peek(on) { if (on && !app.classList.contains("collapsed")) return; app.classList.toggle("peek", on); labelsShown(on); }
function wantOpen() {
  if (tOpen || peeking() || !hover || pressed || suppressed || !app.classList.contains("collapsed")) return;
  tOpen = setTimeout(() => { tOpen = 0; if (hover && !pressed) peek(true); }, OPEN_MS);
}
function wantClose() {
  clearTimeout(tClose);
  tClose = setTimeout(() => { if (hover || !peeking()) return; if (held()) return wantClose(); peek(false); }, CLOSE_MS);
}
side.addEventListener("pointerenter", (e) => { if (e.pointerType === "touch") return; hover = true; pressed = e.buttons !== 0; clearTimeout(tClose); wantOpen(); });   // a held button is a drag, not a request
side.addEventListener("pointermove", (e) => { if (e.pointerType === "touch") return; pressed = e.buttons !== 0; wantOpen(); });
side.addEventListener("pointerleave", () => { hover = false; suppressed = false; clearTimeout(tOpen); tOpen = 0; if (peeking()) wantClose(); });
side.addEventListener("focusin", () => { if (side.matches(":has(:focus-visible)")) { clearTimeout(tClose); peek(true); } });
side.addEventListener("focusout", (e) => { if (!side.contains(e.relatedTarget) && peeking() && !hover) wantClose(); });
// choosing something in the ⌘K palette is done with the sidebar: close the overlay even though the pointer has not moved, and keep it closed until the pointer leaves and comes back
document.addEventListener("palette:chosen", () => {
  suppressed = true; clearTimeout(tOpen); tOpen = 0; clearTimeout(tClose);
  if (side.contains(document.activeElement)) document.activeElement.blur();   // the palette hands focus back to where it was; a focused sidebar link would hold the overlay open
  if (peeking()) peek(false);
});
// on a phone a pinned sidebar is an overlay: a tap on a page or outside it closes it
document.addEventListener("click", (e) => { if (narrow.matches && !app.classList.contains("collapsed") && !e.target.closest("#side-toggle") && (!side.contains(e.target) || e.target.closest("a.nav-item"))) setCollapsed(true); });

// ---------- command palette actions (⌘K); pages come from the sidebar links, Capture setup from prompts.js ----------
registerCommands(() => {
  const on = state.sources.filter((s) => s.enabled && s.detected);
  return [
    { label: app.classList.contains("collapsed") ? "Pin sidebar open" : "Unpin sidebar (auto-hide)", keywords: "navigation menu toggle", icon: ICONS.sidebar, run: () => $("#side-toggle").click() },
    ...(on.length < 2 ? [] : on.filter((s) => s.id !== state.source).map((s) => ({
      label: `Show ${shortLabel(s)} on the Dashboard`, where: "Dashboard", keywords: "agent source switch " + s.id, icon: ICONS.agent,
      run: () => { location.hash = "#/dashboard"; switchSource(s.id); },
    }))),
  ];
});

// ---------- data ----------
async function loadAll() {
  const gen = state.gen;
  const [overview, limits, sessions, daily, heatmap, projects, tools, live] = await Promise.all(
    ["overview", "limits", "sessions?limit=60", "daily?days=90", "heatmap", "projects", "tools", "live"].map(get));
  if (gen !== state.gen) return;   // the agent was switched while this was loading
  state.data = { overview, limits, sessions, daily, heatmap, projects, tools, live };
  renderAll();
}
// Cheap refresh for the "live" parts, so hovering a big chart isn't interrupted.
async function loadLive() {
  const gen = state.gen;
  if (!state.data.overview) return;
  const [limits, sessions, live] = await Promise.all(["limits", "sessions?limit=60", "live"].map(get));
  if (gen !== state.gen) return;
  const sig = (o) => JSON.stringify(o);
  const changed = { sessions: sig(sessions) !== sig(state.data.sessions), live: sig(live) !== sig(state.data.live) };
  Object.assign(state.data, { limits, sessions, live });
  renderGauges();   // no-op for the arcs unless a value moved; refreshes the "resets in" countdown text
  if (changed.sessions) renderContext();
  if (changed.live) renderLive();
}

// ---------- controls ----------
$("#range").addEventListener("click", (e) => {
  const b = e.target.closest("button"); if (!b) return;
  state.days = +b.dataset.days;
  document.querySelectorAll("#range button").forEach((x) => x.classList.toggle("on", x === b));
  renderArea();
});
$("#table-toggle").addEventListener("click", (e) => {
  state.table = !state.table;
  e.currentTarget.setAttribute("aria-pressed", state.table);
  $("#area").hidden = $("#area-legend").hidden = state.table;
  $("#area-table").hidden = !state.table;
});
// The panel width changes with the window and with the sidebar, so redraw charts when it does.
let rz; new ResizeObserver(() => { clearTimeout(rz); rz = setTimeout(renderAll, 200); }).observe($("#panel"));

// ---------- live stream ----------
startRouter((route) => { renderSourceMenu(); if (route === "dashboard") renderAll(); if (route === "prompts") showPrompts(); if (route === "studio") showStudio(); if (route === "linkshell") showLinkshell(); if (route === "collections") showCollections(); if (route === "gallery") showGallery(); if (route === "lattice") showLattice(); if (route === "trash") showTrash(); if (route === "settings") showSettings(); if (route === "whatsnew") showWhatsNew(); });
refreshTrashCount();   // redraw charts when the page becomes visible
const firstLoad = loadSources().then(loadAll);
// Show the page once the first screen is drawn and the fonts are in (see `html:not([data-ready]) .app` in app.css); never wait longer than 1.2 s.
Promise.race([Promise.all([document.fonts.ready, current() === "dashboard" ? firstLoad : null]).catch(() => {}), new Promise((r) => setTimeout(r, 1200))])
  .then(() => { document.documentElement.dataset.ready = "1"; });
if (!location.search.includes("static")) {   // ?static skips the live stream (used for screenshots)
  const es = new EventSource("/api/stream");
  es.addEventListener("update", () => loadAll());
  es.addEventListener("tick", () => loadLive());
}

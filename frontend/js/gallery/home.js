// Knowledge / Gallery (#/gallery[/<slide>][?source=documents]): the user's own prompts, or their imported documents, as one dashboard.
// A segment above the numbers picks Prompts or Documents; the two modes never share filters, a snapshot or a slide list. One fixed page: headline, a filter bar that
// crosses slides, a frame you slide through (the plain ← and → keys, the arrows or the dots; the pager wraps) and a panel with the prompts behind
// whatever is selected. Nothing is sent anywhere and nothing is saved: the page only reads /api/gallery. Plain DOM, no framework.
import { api } from "../api.js";
import { toast } from "../toast.js";
import { ICONS, registerCommands } from "../palette.js";
import { SLIDES } from "./slides.js";
import { SLIDES_DOCS } from "./slides_docs.js";
import { S, F, PM, data, setSnapshot, setPassages, clearSnapshot, resetState, subscribe, apply, clearAll, filtered, toggleAgent, toggleCol, noun } from "./state.js";
import { agentColor, cc, esc, fmtDay, note } from "./common.js";
import { hooks, openPrompt, tagPrompt, promotePrompt, promoteGroup } from "./actions.js";

const $ = (s) => document.querySelector(s);
const MIN_PROMPTS = 10;   // below this the page explains itself instead of drawing charts (plan 3.6); Documents mode reads the number from its snapshot
let built = false, slide = 0, timer = 0, ptimer = 0, loaded = 0, ro = null, status = null, mode = "prompts", counts = {};

// ---------- the two modes ----------
const slides = () => (mode === "documents" ? SLIDES_DOCS : SLIDES);
const slideAt = (id) => Math.max(0, slides().findIndex((s) => s.id === id));
const galUrl = (id) => "#/gallery/" + id + (mode === "documents" ? "?source=documents" : "");
const apiPath = (p = "gallery") => (mode === "documents" ? p + (p.includes("?") ? "&" : "?") + "source=documents" : p);
/** The mode in the address (`?source=documents`), else the one remembered in this browser (a convenience only), else prompts. */
function readMode() {
  const q = new URLSearchParams(location.hash.split("?")[1] || "").get("source");
  if (q === "documents" || q === "prompts") return q;
  try { if (localStorage.getItem("gal-source") === "documents") return "documents"; } catch { /* private window: prompts */ }
  return "prompts";
}
const remember = () => { try { localStorage.setItem("gal-source", mode); } catch { /* not remembered */ } };
/** Another mode: nothing of the old one (filters, selection, snapshot, slide) means anything in the new one. */
function switchTo(m) {
  clearTimeout(ptimer);
  mode = m;
  resetState();
  clearSnapshot();
  loaded = 0;
  slide = 0;
  if (built) renderSlides();
  remember();
}
async function refreshCounts() {
  try { counts = await api("gallery/counts"); } catch { /* the switch just shows no numbers */ }
  modeBar();
}
function modeBar() {
  const n = (v) => (v == null ? "" : ` <span class="gal-n">${v.toLocaleString()}</span>`);
  $("#gal-mode").innerHTML = [["prompts", "Prompts"], ["documents", "Documents"]].map(([m, l]) => {
    const on = m === mode, off = !on && m === "documents" && counts.documents === 0;
    return `<button type="button" class="gal-chip gal-modeb${on ? " on" : ""}" data-mode="${m}" aria-pressed="${on}"${off ? ` disabled title="Import documents in Collections first"` : ""}>${l}${n(counts[m])}</button>`;
  }).join("");
}

// ---------- loading ----------
async function load() {
  clearTimeout(timer);
  const m = mode;
  let d;
  try { [d] = await Promise.all([api(apiPath()), refreshCounts()]); } catch { if (m === mode) show("error"); return; }
  if (m !== mode) return;   // the user switched while this was loading
  status = d.status;
  if (d.snapshot && d.status.built_at !== loaded) { loaded = d.status.built_at; setSnapshot(d.snapshot); chrome(); if (S.mapView === "passages") loadPassages(true); }
  if (!d.snapshot) show(d.status.state === "error" ? "error" : "loading");
  else show(d.snapshot.n < (d.snapshot.min_structure || MIN_PROMPTS) ? "tiny" : "ready");
  redraw();
  if ($("#page-gallery").hidden) return;
  if (d.status.state === "building") timer = setTimeout(load, 1500);   // the numbers arrive on their own
}
function show(st) {
  $("#gal-state").hidden = st === "ready" || st === "tiny";
  $("#gal-frame").hidden = st !== "ready";
  $("#gal-panel").hidden = !(st === "ready" || st === "tiny");
  $("#gal-filters").hidden = st !== "ready";
  const m = { loading: `Reading your ${mode}…`, error: status?.error ? `The Gallery could not be built: ${status.error}` : "Could not load the Gallery. Is the server running?" }[st];
  $("#gal-state").textContent = m || "";
}

/** The passage map (Documents mode, Structure card, "Passages"): asked for when the user picks it, built by the server in the background. */
async function loadPassages(force) {
  clearTimeout(ptimer);
  const m = mode;
  if (m !== "documents") return;
  if (!force && PM.status?.state === "ready" && !PM.status.stale) return;
  let d;
  try { d = await api("gallery?source=documents&part=passages"); } catch { if (m === mode) setPassages({ state: "error", error: "Could not load the passage map." }, null); return; }
  if (m !== mode) return;
  setPassages(d.status, d.part);
  if (d.status.state === "building") ptimer = setTimeout(() => loadPassages(true), 1500);
}

// ---------- the page ----------
function build(page) {
  page.innerHTML = `
    <div class="gal-top" id="gal-top">
    <section class="intro lk-intro gal-intro">
      <div>
        <span class="eyebrow hud">// knowledge</span>
        <h1>Gallery</h1>
        <p class="muted" id="gal-lead">Your own prompts, drawn as patterns.</p>
      </div>
      <div class="gal-side"><div class="gal-mode" id="gal-mode" role="group" aria-label="The Gallery shows"></div><div class="gal-kpis" id="gal-kpis"></div></div>
    </section>
    <section class="gal-filters" id="gal-filters" aria-label="Filters" hidden></section>
    </div>
    <p class="muted gal-state" id="gal-state" role="status">Reading your prompts…</p>
    <div class="gal-layout">
      <section class="gal-frame" id="gal-frame" aria-label="Gallery dashboard" hidden>
        <div class="gal-fhead">
          <h2 id="gal-stitle"></h2>
          <span class="gal-how" id="gal-how"></span>
          <div class="gal-nav">
            <button type="button" class="icon-btn gal-arrow" id="gal-prev" aria-label="Previous slide" title="Previous slide (←)"><svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M15 6l-6 6 6 6"/></svg></button>
            <span class="gal-dots" id="gal-dots"></span>
            <button type="button" class="icon-btn gal-arrow" id="gal-next" aria-label="Next slide" title="Next slide (→)"><svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M9 6l6 6-6 6"/></svg></button>
          </div>
        </div>
        <p class="gal-notice" id="gal-notice" hidden></p>
        <div class="gal-view" id="gal-view"><div class="gal-track" id="gal-track"></div></div>
      </section>
      <aside class="gal-panel" id="gal-panel" aria-label="Selected items" hidden>
        <header><h2 id="gal-ptitle"></h2><div class="muted small" id="gal-psub"></div></header>
        <div class="gal-bulk" id="gal-bulk" hidden></div>
        <ul class="gal-list" id="gal-plist"></ul>
      </aside>
    </div>
    <p class="muted small gal-foot" id="gal-foot"></p>
    <div class="gal-sr" id="gal-live" role="status" aria-live="polite"></div>`;
  renderSlides();
  modeBar();
  $("#gal-mode").addEventListener("click", (e) => {
    const b = e.target.closest("[data-mode]");
    if (!b || b.disabled || b.dataset.mode === mode) return;
    switchTo(b.dataset.mode);
    history.replaceState(null, "", galUrl(slides()[0].id));
    show("loading");
    $("#gal-lead").textContent = "";
    $("#gal-kpis").innerHTML = "";
    modeBar();
    load();
  });
  $("#gal-prev").onclick = () => go(slide - 1);
  $("#gal-next").onclick = () => go(slide + 1);
  $("#gal-track").addEventListener("click", (e) => {
    const b = e.target.closest("[data-mc]"), v = e.target.closest("[data-mv]");
    if (b) { S.mapColor = b.dataset.mc; apply(); }
    else if (v && !v.disabled) {   // Documents | Passages: another set of dots, so the box on the map and a selection made from it no longer apply
      S.mapView = v.dataset.mv; S.mapBr = null;
      if (S.sel && S.sel.src === "map") S.sel = null;
      if (S.mapView === "passages") loadPassages();
      apply();
    }
  });
  $("#gal-dots").onclick = (e) => { const b = e.target.closest("[data-d]"); if (b) go(+b.dataset.d); };
  $("#gal-filters").addEventListener("click", (e) => {
    const ag = e.target.closest("[data-ag]"), co = e.target.closest("[data-co]"), cl = e.target.closest("[data-clear]");
    if (ag) toggleAgent(ag.dataset.ag);
    else if (co) toggleCol(co.dataset.co);
    else if (cl) {
      const k = cl.dataset.clear;
      if (k === "all") clearAll(); else { if (k === "range") S.range = null; if (k === "word") S.word = null; if (k === "cluster") S.cluster = null; if (k === "sel") S.sel = null; apply(); }
    }
  });
  $("#gal-plist").addEventListener("click", (e) => {
    const o = e.target.closest("[data-open]"), t = e.target.closest("[data-tag]"), p = e.target.closest("[data-promote]");
    if (o) { if (mode === "documents") openDocument(o.dataset.open); else openPrompt(o.dataset.open); } else if (t) tagPrompt(t.dataset.tag); else if (p) promotePrompt(p.dataset.promote);
  });
  $("#gal-bulk").addEventListener("click", (e) => { const b = e.target.closest("[data-group]"); if (b) promoteGroup(+b.dataset.group); });
  hooks.refresh = async () => { try { await api(apiPath("gallery/rebuild"), { method: "POST" }); } catch { /* the next look rebuilds on its own */ } load(); };   // after Tag or Promote: the snapshot is built again
  subscribe(redraw);
  ro = new ResizeObserver(() => { const w = $("#gal-view").clientWidth; if (w && w !== ro.w) { ro.w = w; apply(); } });
  ro.observe($("#gal-view"));
  // the headline and the filter bar stay under the top bar while the page scrolls; the side panel sticks below them, so measure their height (the bar wraps on narrow widths)
  new ResizeObserver(() => $("#page-gallery").style.setProperty("--gal-fh", $("#gal-top").offsetHeight + "px")).observe($("#gal-top"));
  addEventListener("flowlystack-theme", () => apply());
  matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => apply());
  // ← and → switch slides (a Gallery-only key: the shortcut settings only know Cmd/Ctrl combinations). Never while typing, never with a modifier, only on this page.
  addEventListener("keydown", (e) => {
    if ($("#page-gallery").hidden || e.defaultPrevented || e.metaKey || e.ctrlKey || e.altKey || e.shiftKey || document.querySelector("dialog[open]")) return;
    if (/^(input|textarea|select)$/i.test(e.target.tagName) || e.target.isContentEditable) return;
    if (e.key === "ArrowRight") { e.preventDefault(); go(slide + 1); }
    else if (e.key === "ArrowLeft") { e.preventDefault(); go(slide - 1); }
  });
}

/** The cards of the current mode: the track and the dots are built again on a mode switch. */
function renderSlides() {
  const L = slides(), tr = $("#gal-track");
  tr.innerHTML = L.map((s) => `<div class="gal-slide" data-s="${s.id}" role="group" aria-label="${esc(s.title)}">${s.cards.map((c) => `
    <section class="gal-card" style="grid-column: span ${c.span}"><h3>${esc(c.title)}${c.seg ? `<span class="gal-segs">${c.view ? `<span class="gal-seg" role="group" aria-label="Show"><button type="button" class="gal-chip" data-mv="docs">Documents</button><button type="button" class="gal-chip" data-mv="passages">Passages</button></span>` : ""}<span class="gal-seg" role="group" aria-label="Colour the dots by"><button type="button" class="gal-chip" data-mc="cluster">Topic</button><button type="button" class="gal-chip" data-mc="agent">${c.seg === true ? "Agent" : esc(c.seg)}</button></span></span>` : ""}</h3><p class="gal-cap">${esc(c.caption)}</p>
    <div class="gal-cv" id="gal-c-${c.key}" role="img" aria-label="${esc(c.title + ". " + c.caption)}"></div></section>`).join("")}</div>`).join("");
  delete tr.dataset.placed;   // the first draw of a mode jumps to its slide instead of sliding there
  $("#gal-dots").innerHTML = L.map((s, i) => `<button type="button" class="gal-dot" data-d="${i}" title="${esc(s.title)}" aria-label="${esc(s.title)}"></button>`).join("");
}

/** Documents mode: Open goes straight to the document's own page (the viewer) in the first collection it is in, the one the row names. */
function openDocument(id) {
  const r = data()?.R.find((x) => x.id === id);
  if (r?.cols?.length) location.hash = "#/collections/" + encodeURIComponent(r.cols[0]) + "/documents/" + encodeURIComponent(id);
}

/** Run `fn` (which rebuilds the content of `box`) and give focus back to the same button afterwards: a redraw must not drop a keyboard user's place. */
function keepFocus(box, fn) {
  const a = document.activeElement;
  let sel = "";
  if (a && box.contains(a) && a.dataset) for (const k of ["ag", "co", "clear", "open", "tag", "promote", "group"]) if (a.dataset[k] !== undefined) sel = `[data-${k}="${CSS.escape(a.dataset[k])}"]`;
  fn();
  if (sel) box.querySelector(sel)?.focus();
}

function go(i) {
  slide = (i + slides().length) % slides().length;   // wraps: → on the last slide goes to the first
  history.replaceState(null, "", galUrl(slides()[slide].id));
  redraw();
}

// ---------- drawing ----------
const MORE = " Groups and the map use";
function chrome() {
  const { snap, R } = data(), docs = snap.mode === "documents", what = docs ? "documents" : "Library", plural = (n, w) => `${n.toLocaleString()} ${w}${n === 1 ? "" : "s"}`;
  const safe = `Everything here is computed on this machine from your ${what}; looking at this page saves and sends nothing.`;
  if (!snap.n) {
    $("#gal-lead").innerHTML = docs ? `No documents yet. Import documents in <a href="#/collections">Collections</a>; then they show up here as patterns.`
      : "No prompts yet. Prompts you send to Claude, Codex or Open WebUI are captured in the Library once the hook is set up; then they show up here as patterns.";
    $("#gal-kpis").innerHTML = "";
    $("#gal-foot").textContent = safe;
    return;
  }
  if (snap.n < (snap.min_structure || MIN_PROMPTS)) {
    $("#gal-lead").textContent = docs ? `${plural(snap.n, "document")} so far. The Gallery draws its charts from about ${snap.min_structure} documents, and some of them need ${snap.min_card} to say anything; your newest are listed here meanwhile.`
      : `${plural(snap.n, "prompt")} so far. The Gallery draws its charts from about ${MIN_PROMPTS} prompts, and some of them need 50 to say anything; your newest are listed here meanwhile.`;
    $("#gal-kpis").innerHTML = "";
    $("#gal-foot").textContent = safe;
    return;
  }
  const rep = snap.repeats.reduce((a, g) => a + g.n, 0);
  const ag = d3.rollup(R, (v) => v.length, (r) => r.a), topAgent = [...ag].sort((a, b) => b[1] - a[1])[0]?.[0];
  const months = snap.months.length ? d3.timeMonth.count(new Date(R[0].t), new Date(R.at(-1).t)) + 1 : 0;
  let kpis;
  if (docs) {
    const about = snap.clusters.length ? `Mostly about <strong>${esc(snap.clusters[0].terms.slice(0, 3).join(", "))}</strong>, ` : "";
    $("#gal-lead").innerHTML = `<strong>${plural(snap.n, "document")}</strong> in ${plural(snap.collections.length, "collection")}, added over ${plural(months, "month")}. ${about}${about ? "mostly" : "Mostly"} <strong>${esc(topAgent)}</strong> files.`;
    kpis = [[snap.n.toLocaleString(), "documents"], [snap.collections.length.toLocaleString(), "collections"], [snap.clusters.length ? snap.repeats.length : "–", snap.repeats.length ? `repeated documents (${rep})` : "repeated documents"], [snap.terms[0]?.w || "–", "most used word"]];
  } else {
    const days = new Set(R.map((r) => r.d)).size;
    const hrs = d3.rollup(R, (v) => v.length, (r) => Math.floor(r.h)), peak = [...hrs].sort((a, b) => b[1] - a[1])[0]?.[0];
    const about = snap.clusters.length ? `You write most about <strong>${esc(snap.clusters[0].terms.slice(0, 3).join(", "))}</strong>, ` : "";
    $("#gal-lead").innerHTML = `<strong>${snap.n.toLocaleString()} prompts</strong> over ${months} month${months === 1 ? "" : "s"}. ${about}mostly around <strong>${peak}:00</strong>, mostly with <strong>${esc(topAgent)}</strong>.`;
    kpis = [[snap.n.toLocaleString(), "prompts"], [days.toLocaleString(), "days with prompts"], [snap.clusters.length ? snap.repeats.length : "–", snap.repeats.length ? `repeated ideas (${rep} prompts)` : "repeated ideas"], [snap.terms[0]?.w || "–", "most used word"]];
  }
  $("#gal-kpis").innerHTML = kpis.map(([v, l]) => `<div class="gal-kpi"><div class="gal-kv">${esc(v)}</div><div class="gal-kl">${esc(l)}</div></div>`).join("");
  const how = snap.method === "embeddings" ? "stored embeddings (meaning)" : snap.method === "tfidf-svd" ? `word statistics, because no embedding model is set or the ${docs ? "documents" : "prompts"} are not indexed yet` : "";
  const mapNote = snap.map?.kind !== "none" && snap.map?.shown < snap.n ? ` The map shows your newest ${snap.map.shown.toLocaleString()} ${docs ? "documents" : "prompts"}.` : "";
  const junk = docs && snap.junk ? ` ${plural(snap.junk, "document")} made mostly of numbers or symbols ${snap.junk === 1 ? "is" : "are"} left out of the word charts.` : "";
  $("#gal-foot").textContent = `${safe}${how ? `${MORE} ${how}.` : ""}${mapNote}${junk}`;
}

function redraw() {
  const D = data();
  if (!D || $("#page-gallery").hidden) return;
  keepFocus($("#gal-filters"), filtersBar);
  keepFocus($("#gal-panel"), panel);
  notice();
  $("#gal-live").textContent = `${F.length.toLocaleString()} of ${D.snap.n.toLocaleString()} ${noun()} match`;
  if ($("#gal-frame").hidden) return;
  const s = slides()[slide];
  $("#page-gallery").classList.toggle("gal-fit", !!s.fit);   // see "Gallery: fixed page" in app.css
  const tr = $("#gal-track");
  if (!tr.dataset.placed) { tr.classList.add("gal-still"); tr.dataset.placed = "1"; requestAnimationFrame(() => requestAnimationFrame(() => tr.classList.remove("gal-still"))); }   // the first draw jumps to the slide in the URL instead of sliding there
  tr.style.transform = `translateX(${-100 * slide}%)`;
  $("#gal-stitle").textContent = s.title;
  $("#gal-how").textContent = s.how;
  document.querySelectorAll(".gal-dot").forEach((d, i) => { d.classList.toggle("on", i === slide); i === slide ? d.setAttribute("aria-current", "true") : d.removeAttribute("aria-current"); });
  document.querySelectorAll(".gal-slide").forEach((el, i) => { el.inert = i !== slide; el.classList.toggle("on", i === slide); });   // off-screen slides take no focus
  document.querySelectorAll("[data-mc]").forEach((b) => { const on = b.dataset.mc === S.mapColor; b.classList.toggle("on", on); b.setAttribute("aria-pressed", on); });
  document.querySelectorAll("[data-mv]").forEach((b) => {
    const on = b.dataset.mv === S.mapView, off = b.dataset.mv === "passages" && D.snap.method !== "embeddings";   // passages need stored vectors
    b.classList.toggle("on", on); b.setAttribute("aria-pressed", on); b.disabled = off;
    if (b.dataset.mv === "passages") b.title = off ? "Needs stored embeddings: choose an embedding model in Settings > Knowledge and let your documents finish indexing" : "One dot for each passage of your documents";
  });
  for (const c of s.cards) {
    const el = document.getElementById("gal-c-" + c.key), need = !c.min ? 0 : D.snap.mode === "documents" ? D.snap.min_card : c.min;   // Documents mode: the snapshot's own number
    if (need && D.snap.n < need) note(el, `This chart needs about ${need} ${noun()} to say anything; you have ${D.snap.n}.`);
    else if (c.draw) c.draw(el);
    else if (!el.firstChild) el.innerHTML = `<p class="gal-soon">This chart is built in a later step.</p>`;
  }
}

/** The map, groups and repeats are made from the meaning of the prompts or documents when stored embeddings cover them, else from their words: say which, where it matters. */
function notice() {
  const el = $("#gal-notice"), { snap } = data(), id = slides()[slide].id, docs = snap.mode === "documents";
  const words = snap.method === "tfidf-svd" && snap.n >= (docs ? snap.min_card : 50) && (id === "structure" || id === "repeats");   // below that the charts themselves say they need more
  el.hidden = !words;
  if (words) el.innerHTML = status?.model
    ? `Grouped by words, not meaning: the stored embeddings do not cover enough of your ${noun()} yet (indexing may still be running).`
    : `Grouped by words, not meaning, because no embedding model is set. Choose one in <a href="#/settings/knowledge">Settings &gt; Knowledge</a>.`;
}

function filtersBar() {
  const { snap } = data(), docs = snap.mode === "documents", f = [`<span class="gal-fl">${docs ? "Type" : "Agent"}</span>`];
  for (const a of snap.agents) f.push(`<button type="button" class="gal-chip${S.agents.has(a) ? " on" : ""}" data-ag="${esc(a)}" aria-pressed="${S.agents.has(a)}"><i style="background:${agentColor(a)}"></i>${esc(a)}</button>`);
  if (docs && snap.collections.length > 1) {
    f.push(`<span class="gal-fl gal-fl2">Collection</span>`);
    for (const c of snap.collections) f.push(`<button type="button" class="gal-chip${S.cols.has(c.id) ? " on" : ""}" data-co="${esc(c.id)}" aria-pressed="${S.cols.has(c.id)}" title="${c.n.toLocaleString()} documents">${esc(c.name)}</button>`);
  }
  if (S.range) f.push(`<button type="button" class="gal-chip act" data-clear="range" title="Clear this filter">${fmtDay(new Date(S.range[0]))} – ${fmtDay(new Date(S.range[1]))}</button>`);
  if (S.word) f.push(`<button type="button" class="gal-chip act" data-clear="word" title="Clear this filter">word: ${esc(S.word)}</button>`);
  if (S.cluster != null) f.push(`<button type="button" class="gal-chip act" data-clear="cluster" title="Clear this filter"><i style="background:${cc(S.cluster)}"></i>${esc(snap.clusters[S.cluster]?.label || "group")}</button>`);
  if (S.sel) f.push(`<button type="button" class="gal-chip act" data-clear="sel" title="Clear this selection">${esc(S.sel.label)}</button>`);
  f.push(`<span class="gal-sp"></span><span class="gal-count">${F.length.toLocaleString()} of ${snap.n.toLocaleString()} ${noun()}</span>`);
  if (filtered()) f.push(`<button type="button" class="gal-chip" data-clear="all">Clear all</button>`);
  $("#gal-filters").innerHTML = f.join("");
}

function panel() {
  const { snap } = data(), docs = snap.mode === "documents", any = filtered(), rows = F.slice().sort((a, b) => b.t - a.t).slice(0, 60), cname = Object.fromEntries((snap.collections || []).map((c) => [c.id, c.name]));
  $("#gal-panel").setAttribute("aria-label", `Selected ${noun()}`);
  $("#gal-ptitle").textContent = any ? `${F.length.toLocaleString()} ${noun(F.length)} match` : `Newest ${noun()}`;
  const grp = !docs && S.sel && S.sel.src === "group" ? S.sel.key : null;   // Promote as one template is for prompts only
  $("#gal-bulk").hidden = grp == null;
  $("#gal-bulk").innerHTML = grp == null ? "" : `<button type="button" class="btn btn-sm btn-glow" data-group="${grp}">Promote as one template</button>`;
  $("#gal-psub").textContent = $("#gal-frame").hidden ? "" : any ? (F.length > 60 ? "Showing the newest 60." : "") : "Click anything in the charts to narrow this list.";
  const empty = any ? "Nothing matches these filters. Clear one above." : docs ? "No documents yet. Import documents in Collections and they show up here." : "No prompts yet. Prompts you send to Claude, Codex or Open WebUI are captured here once the hook is set up.";
  $("#gal-plist").innerHTML = rows.length ? rows.map((r) => docs
    ? `<li class="gal-item"><div class="gal-im"><i style="background:${agentColor(r.a)}"></i>${esc(r.a)} · ${fmtDay(new Date(r.t))} · ${r.w.toLocaleString()} words${r.cols.length ? ` · ${esc(cname[r.cols[0]] || "")}${r.cols.length > 1 ? ` +${r.cols.length - 1}` : ""}` : ""}</div>
    <div class="gal-it">${esc(r.title)}</div>
    <div class="gal-ia"><button type="button" class="btn btn-sm btn-glow" data-open="${esc(r.id)}" title="Open this document">Open</button></div></li>`
    : `<li class="gal-item"><div class="gal-im"><i style="background:${agentColor(r.a)}"></i>${esc(r.a)} · ${fmtDay(new Date(r.t))}${r.star ? " · ★" : ""}</div>
    <div class="gal-it">${esc(r.title || r.s)}</div>
    <div class="gal-ia"><button type="button" class="btn btn-sm btn-glow" data-open="${esc(r.id)}">Open</button><button type="button" class="btn btn-sm btn-glow" data-tag="${esc(r.id)}" title="Edit this prompt's tags">Tag</button><button type="button" class="btn btn-sm btn-glow" data-promote="${esc(r.id)}" title="Save a copy as a reusable prompt in Prompt Studio">Promote</button></div></li>`).join("")
    : `<li class="gal-empty muted">${empty}</li>`;
}

// ---------- router hook and palette ----------
const toMode = (m, id) => { try { localStorage.setItem("gal-source", m); } catch { /* not remembered */ } location.hash = "#/gallery/" + id + (m === "documents" ? "?source=documents" : ""); };
registerCommands(() => [
  ...slides().map((s) => ({ label: "Gallery: " + s.title, where: "Gallery", keywords: "knowledge patterns charts insights dashboard " + s.id, icon: ICONS.find, run: () => { location.hash = galUrl(s.id); } })),
  ...(mode === "documents" ? [{ label: "Gallery: Prompts", where: "Gallery", keywords: "knowledge switch library prompts", icon: ICONS.find, run: () => toMode("prompts", "pulse") }]
    : [{ label: "Gallery: Documents", where: "Gallery", keywords: "knowledge switch collections documents files", icon: ICONS.find, run: () => toMode("documents", "shape") }]),
  { label: "Refresh Gallery", where: "Gallery", keywords: "knowledge rebuild map charts", icon: ICONS.find, run: async () => { try { await api(apiPath("gallery/rebuild"), { method: "POST" }); loaded = 0; toast({ message: "Rebuilding the Gallery.", ms: 2500 }); if (!$("#page-gallery").hidden) load(); } catch (e) { toast({ message: "Could not rebuild: " + e.message }); } } },
]);

/** Router hook: #/gallery shows the page, #/gallery/<slide> a slide of it, `?source=documents` the Documents mode. */
export function showGallery() {
  const page = $("#page-gallery");
  const m = readMode();
  if (!built) { mode = m; built = true; build(page); }
  else if (m !== mode) switchTo(m);
  const id = location.hash.replace(/^#\/gallery\/?/, "").split(/[/?]/)[0];
  slide = slideAt(id);
  load();
}

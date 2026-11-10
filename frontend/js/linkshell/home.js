// Linkshell page (#/linkshell): the home list of projects first, then a project's canvas (#/linkshell/<id>). Projects live in files behind
// /api/linkshell. List state (search, filters, sort) lives in the URL with history.replaceState, so Back from a canvas returns to the same
// list; the list itself is fetched from the server, which does the search, filtering, sorting and tag counts. Plain DOM, no framework.
import { api, relTime } from "../api.js";
import { formDialog } from "../dialog.js";
import { toast } from "../toast.js";
import { hl } from "../editor.js";
import { listNav } from "../listnav.js";
import { ICONS, registerCommands } from "../palette.js";
import { thumbOf } from "./projects.js";
import { exportItems, exportClick, importProject } from "./exporter.js";
import { mountCanvas, loadProject, unloadProject, setHome, canvasActions, setView } from "./proto.js";

const $ = (s) => document.querySelector(s);
const esc = (t) => String(t ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
const ic = (d, s = 16) => `<svg viewBox="0 0 24 24" width="${s}" height="${s}" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${d}</svg>`;
const I = {
  plus: `<path d="M12 5v14M5 12h14"/>`, dots: `<circle cx="5" cy="12" r="1.2"/><circle cx="12" cy="12" r="1.2"/><circle cx="19" cy="12" r="1.2"/>`,
  star: `<path d="M12 3.5l2.6 5.4 5.9.8-4.3 4.1 1 5.9L12 16.9 6.8 19.7l1-5.9L3.5 9.7l5.9-.8z"/>`,
  copy: `<rect x="8" y="8" width="12" height="12" rx="2.5"/><path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2"/>`,
  trash: `<path d="M4 7h16M10 11v6M14 11v6M6 7l1 12a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2l1-12M9 7V4h6v3"/>`, check: `<circle cx="12" cy="12" r="9"/><path d="M8 12.5l3 3 5-6"/>`,
  download: `<path d="M12 4v11M7 11l5 5 5-5M5 20h14"/>`, upload: `<path d="M12 16V5M7 9l5-5 5 5M5 20h14"/>`, graph: `<circle cx="6" cy="6" r="2.2"/><circle cx="18" cy="8" r="2.2"/><circle cx="12" cy="18" r="2.2"/><path d="M8 6.4l8 1.1M7.2 8l3.6 8M16.9 10l-3.7 6.2"/>`,
};

const view = () => (/\/follow(\?|$)/.test(location.hash) ? "follow" : /\/outline(\?|$)/.test(location.hash) ? "outline" : "canvas");
const L = { q: "", show: "all", tags: [], sort: "edited", dir: "desc", tagFind: "", picked: false };   // picked: the user chose a sort column (else a search sorts by relevance)
let built = false, current = "", items = [], total = 0, tagCounts = {}, ticket = 0;
const json = (method, body) => ({ method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

const SHOWS = { all: "All", progress: "In progress", todo: "Not started", done: "Done", starred: "Starred" };
const stateOf = (p) => (!p.steps ? "empty" : p.done === p.steps ? "done" : p.done ? "progress" : "todo");

// ---------- the URL ----------
const homeHash = () => {
  const q = new URLSearchParams();
  if (L.q) q.set("q", L.q);
  if (L.show !== "all") q.set("show", L.show);
  L.tags.forEach((t) => q.append("tag", t));
  if (L.picked || L.sort !== "edited" || L.dir !== "desc") { q.set("sort", L.sort); q.set("dir", L.dir); }
  const s = q.toString();
  return "#/linkshell" + (s ? "?" + s : "");
};
function readHome(query) {
  const q = new URLSearchParams(query);
  L.q = q.get("q") || ""; L.show = SHOWS[q.get("show")] ? q.get("show") : "all"; L.tags = q.getAll("tag");
  L.sort = ["edited", "name", "progress"].includes(q.get("sort")) ? q.get("sort") : "edited"; L.dir = q.get("dir") === "asc" ? "asc" : "desc"; L.picked = q.has("sort");
}

// ---------- the list ----------
/** Fetch the list for the current search, filters and sort, then draw it. A slower, older answer never overwrites a newer one. */
async function load() {
  const my = ++ticket, rel = L.q.trim() && !L.picked, q = new URLSearchParams({ q: L.q, show: L.show, sort: rel ? "relevance" : L.sort, desc: L.dir === "desc" });
  L.tags.forEach((t) => q.append("tag", t));
  let d;
  try { d = await api("linkshell?" + q); } catch { $("#lk-list").innerHTML = `<li class="muted pr-empty">Could not load the projects. Is the server running?</li>`; return; }
  if (my !== ticket) return;
  ({ items, total, tags: tagCounts } = d);
  renderList();
}
function rowHtml(p) {
  const when = relTime(p.updated_at), pct = p.steps ? Math.round((p.done / p.steps) * 100) : 0, state = stateOf(p);
  const metaBits = [`${p.blocks} block${p.blocks === 1 ? "" : "s"}`, p.frames ? `${p.frames} phase${p.frames === 1 ? "" : "s"}` : "", p.steps ? p.agents.join(", ") : "no prompts yet", `edited ${when}`].filter(Boolean);
  const prog = p.steps ? `<div class="lk-prog"><span class="lk-bar"><span style="width:${pct}%"></span></span><span class="pr-meta">${p.done} / ${p.steps}${p.next ? ` · next: ${esc(p.next)}` : ""}</span></div>` : "";
  return `<li class="pr-row lk-prow" data-id="${p.id}">
    <a class="pr-link lk-plink" href="#/linkshell/${p.id}" data-open>
      ${thumbOf(p.thumb) || `<span class="lk-thumb lk-thumb-empty">${ic(I.graph, 20)}</span>`}
      <span class="lk-pbody">
        <span class="pr-title">${p.hl?.title ? hl(p.hl.title) : esc(p.name)}</span>
        <span class="pr-meta">${metaBits.map(esc).join(" · ")}</span>
        ${prog}
        ${p.hl?.snippet ? `<span class="pr-prev">${hl(p.hl.snippet)}</span>` : p.brief ? `<span class="pr-prev">${esc(p.brief)}</span>` : ""}
        ${p.tags.length ? `<span class="lk-tags">${p.tags.map((t) => `<span>${esc(t)}</span>`).join("")}</span>` : ""}
      </span>
    </a>
    <div class="lk-pact">
      ${state === "done" ? `<span class="lk-done">${ic(I.check, 14)}done</span>` : ""}
      <button type="button" class="icon-btn lk-star${p.star ? " on" : ""}" data-star aria-pressed="${p.star}" aria-label="${p.star ? "Remove star" : "Star"}" title="${p.star ? "Remove star" : "Star"}">${ic(I.star, 18)}</button>
      <details class="pr-more">
        <summary class="icon-btn" aria-label="More" title="More">${ic(I.dots, 18)}</summary>
        <div class="pr-menu pr-morepanel" role="menu">
          <button type="button" class="pr-menuitem" role="menuitem" data-dup>${ic(I.copy, 18)}<span>Duplicate</span></button>
          ${exportItems(ic(I.download, 18))}
          <button type="button" class="pr-menuitem" role="menuitem" data-del>${ic(I.trash, 18)}<span>Delete</span></button>
        </div>
      </details>
    </div>
  </li>`;
}
function renderList() {
  const filtered = L.q || L.show !== "all" || L.tags.length;
  $("#lk-list").innerHTML = items.length ? items.map(rowHtml).join("")
    : `<li class="muted pr-empty">${filtered ? "Nothing matches these filters." : "No projects yet. Press New project to plan your first one."}</li>`;
  $("#lk-count").textContent = `${total} project${total === 1 ? "" : "s"}`;
  document.querySelectorAll("#lk-home .pr-sort").forEach((b) => {
    const on = b.dataset.sort === L.sort && (L.picked || !L.q.trim());
    b.classList.toggle("on", on);
    b.querySelector("span").textContent = on ? (L.dir === "asc" ? "↑" : "↓") : "";
  });
  const tags = Object.keys(tagCounts).sort(), f = L.tagFind.trim().toLowerCase();
  const shown = tags.filter((t) => !f || t.toLowerCase().includes(f));
  $("#lk-tags").innerHTML = shown.length ? shown.map((t) => `<button type="button" class="pl-chip${L.tags.includes(t) ? " on" : ""}" data-tag="${esc(t)}" aria-pressed="${L.tags.includes(t)}">${esc(t)} <span>${tagCounts[t]}</span></button>`).join("")
    : `<span class="muted small">${tags.length ? "No tag matches." : "No tags yet."}</span>`;
  $("#lk-tagtxt").textContent = L.tags.length ? `Tags · ${L.tags.length}` : `Tags${tags.length ? ` (${tags.length})` : ""}`;
  $("#lk-tagchips").innerHTML = L.tags.map((t) => `<button type="button" class="pl-chip on" data-untag="${esc(t)}" title="Remove this tag filter">${esc(t)} ×</button>`).join("");
}
function refilter(patch) {
  Object.assign(L, patch);
  history.replaceState(null, "", homeHash());
  setHome(homeHash());
  load();
}

// ---------- actions ----------
async function newProject() {
  const v = await formDialog({
    title: "New project", confirmLabel: "Create",
    html: `<label class="pl-label" for="lk-nname">Name</label><input class="pl-input" id="lk-nname" autocomplete="off" placeholder="Personal website">
      <label class="pl-label" for="lk-nbrief">What you are building (optional)</label><input class="pl-input" id="lk-nbrief" autocomplete="off" placeholder="A one-page portfolio in plain HTML and CSS">`,
    validate: (d) => (d.querySelector("#lk-nname").value.trim() ? "" : "Give the project a name."),
    read: (d) => ({ name: d.querySelector("#lk-nname").value.trim(), brief: d.querySelector("#lk-nbrief").value.trim() }),
  });
  if (!v) return;
  try {
    const p = await api("linkshell", json("POST", v));
    location.hash = "#/linkshell/" + p.project.id;
  } catch (e) { toast({ message: "Could not create the project: " + e.message, ms: 4000 }); }
}
async function duplicate(p) {
  try {
    const c = await api("linkshell", json("POST", { duplicate_of: p.id }));
    await load();
    toast({ message: `Duplicated as “${c.project.name}”`, ms: 3000 });
  } catch (e) { toast({ message: "Could not duplicate: " + e.message, ms: 4000 }); }
}
async function remove(p) {
  try { await api("linkshell/" + p.id, { method: "DELETE" }); } catch (e) { return toast({ message: "Could not delete: " + e.message, ms: 4000 }); }
  await load();
  toast({ message: `Deleted “${p.name}”`, action: "Undo", onAction: async () => {
    await api(`trash/${p.id}/restore`, { method: "POST" }).catch(() => toast({ message: "Could not undo. Restore it from Trash." }));
    load();
  } });
}
async function star(p) {
  p.star = !p.star; renderList();   // shows at once; the server answer follows
  try { await api("linkshell/" + p.id, json("PATCH", { star: p.star })); } catch { toast({ message: "Could not save the star." }); }
  load();
}
// ---------- page ----------
registerCommands(() => [
  { label: "New Linkshell project", where: "Linkshell", keywords: "new create plan canvas project", icon: ICONS.plus, run: () => { location.hash = "#/linkshell"; setTimeout(newProject, 80); } },
  ...(current ? [
    ...[["canvas", "Go to Canvas", ""], ["follow", "Go to Follow", "/follow"], ["outline", "Go to Outline", "/outline"]].filter(([v]) => v !== view()).map(([, label, path]) => ({ label, where: "Linkshell", keywords: "follow outline list steps walk canvas view", icon: ICONS.find, run: () => { location.hash = "#/linkshell/" + current + path; } })),
    { label: "Add prompt block", where: "Linkshell canvas", keywords: "new step block canvas", icon: ICONS.plus, run: canvasActions.addPrompt },
    { label: "Fit canvas to screen", where: "Linkshell canvas", keywords: "zoom fit view", icon: ICONS.find, run: canvasActions.fit },
    { label: "Tidy up canvas", where: "Linkshell canvas", keywords: "arrange layout organise align", icon: ICONS.find, run: canvasActions.tidy },
    { label: "Project settings", where: "Linkshell canvas", keywords: "properties metadata default agent rename project", icon: ICONS.find, run: canvasActions.settings },
  ] : []),
  ...items.map((p) => ({ label: p.name, where: "Linkshell project", keywords: "open canvas plan " + p.tags.join(" "), icon: ICONS.find, run: () => { location.hash = "#/linkshell/" + p.id; } })),
]);
function build(page) {
  page.innerHTML = `
    <div id="lk-home">
      <section class="intro lk-intro">
        <div>
          <span class="eyebrow hud">// workspace</span>
          <h1>Linkshell</h1>
          <p class="muted">Plan a project as linked prompt blocks before you build, then follow it step by step.</p>
        </div>
        <div class="lk-heroact">
          <button type="button" class="btn btn-sm btn-glow btn-glow-md" id="lk-import" title="Import a Linkshell JSON file (from Export JSON) as a new project. Your existing projects are not changed.">${ic(I.upload)}<span>Import</span></button>
          <button type="button" class="btn btn-sm btn-glow btn-glow-md lk-new" id="lk-new" data-hotkey="new">${ic(I.plus)}<span>New project</span><kbd class="kbd" data-hk="new"></kbd></button>
        </div>
      </section>
      <section class="pl-filters" aria-label="Filters">
        <span class="srch"><input class="pl-input" id="lk-q" data-search type="search" placeholder="Search projects and blocks" aria-label="Search projects and blocks"><kbd class="kbd" data-hk="search" aria-hidden="true"></kbd></span>
        <select class="pl-input" id="lk-show" aria-label="Show">${Object.entries(SHOWS).map(([k, v]) => `<option value="${k}">${v}</option>`).join("")}</select>
        <details class="pl-tagmenu" id="lk-tagmenu">
          <summary class="btn btn-sm btn-glow btn-glow-md"><span id="lk-tagtxt">Tags</span><kbd class="kbd" data-hk="tags" aria-hidden="true"></kbd></summary>
          <div class="pl-tagpanel">
            <input class="pl-input" id="lk-tagfind" type="search" placeholder="Find a tag" aria-label="Find a tag">
            <div class="pl-tags" id="lk-tags" aria-label="Tags"></div>
          </div>
        </details>
        <span class="pl-tagchips" id="lk-tagchips" aria-label="Selected tags"></span>
        <span class="muted small pl-count" id="lk-count"></span>
      </section>
      <section class="pr-table" aria-label="Projects">
        <div class="pr-thead">
          <button type="button" class="pr-sort" data-sort="name">Name <span></span></button>
          <button type="button" class="pr-sort" data-sort="progress">Progress <span></span></button>
          <button type="button" class="pr-sort" data-sort="edited">Edited <span></span></button>
        </div>
        <ul class="pr-list" id="lk-list"></ul>
      </section>
    </div>
    <div id="lk-canvas" hidden></div>`;
  const list = $("#lk-list");
  $("#lk-new").addEventListener("click", newProject);
  $("#lk-import").addEventListener("click", importProject);
  $("#lk-q").addEventListener("input", (e) => refilter({ q: e.target.value }));   // live as you type
  listNav($("#lk-q"), list);   // ↑ / ↓ move a highlight through the projects, Enter opens it
  $("#lk-show").addEventListener("change", (e) => refilter({ show: e.target.value }));
  $("#lk-tagfind").addEventListener("input", (e) => { L.tagFind = e.target.value; renderList(); });
  $("#lk-tags").addEventListener("click", (e) => { const b = e.target.closest("[data-tag]"); if (b) refilter({ tags: L.tags.includes(b.dataset.tag) ? L.tags.filter((x) => x !== b.dataset.tag) : [...L.tags, b.dataset.tag] }); });
  $("#lk-tagchips").addEventListener("click", (e) => { const b = e.target.closest("[data-untag]"); if (b) refilter({ tags: L.tags.filter((x) => x !== b.dataset.untag) }); });
  page.querySelectorAll("#lk-home .pr-sort").forEach((b) => b.addEventListener("click", () => {
    const k = b.dataset.sort;
    refilter(k === L.sort && (L.picked || !L.q.trim()) ? { picked: true, dir: L.dir === "asc" ? "desc" : "asc" } : { sort: k, picked: true, dir: k === "name" ? "asc" : "desc" });
  }));
  list.addEventListener("click", (e) => {
    const row = e.target.closest(".lk-prow"), p = row && items.find((x) => x.id === row.dataset.id);
    if (!p) return;
    if (e.target.closest("[data-star]")) star(p);
    else if (e.target.closest("[data-dup]")) duplicate(p);
    else if (exportClick(e, p.id)) return;
    else if (e.target.closest("[data-del]")) remove(p);
  });
}

/** Router hook: #/linkshell shows the list, #/linkshell/<id> the canvas of that project. */
export async function showLinkshell() {
  const page = $("#page-linkshell");
  if (!built) { built = true; build(page); }
  const rest = location.hash.replace(/^#\/linkshell\/?/, ""), [raw, query = ""] = rest.startsWith("?") ? ["", rest.slice(1)] : rest.split("?");
  const [rawId, rawView = ""] = (raw || "").split("/"), id = decodeURIComponent(rawId), view = rawView === "follow" || rawView === "outline" ? rawView : "canvas", my = ++nav;
  if (current && current !== id) { await unloadProject(); current = ""; }   // leaving a canvas saves its last edits first
  if (my !== nav) return;
  if (id) {
    if (current !== id) {
      let d;
      try { d = await api("linkshell/" + encodeURIComponent(id)); }
      catch { if (my === nav) { history.replaceState(null, "", "#/linkshell"); toast({ message: "That project no longer exists.", ms: 3000 }); showLinkshell(); } return; }
      if (my !== nav) return;
      current = id;
      $("#lk-home").hidden = true; $("#lk-canvas").hidden = false;
      mountCanvas($("#lk-canvas")); loadProject(d);
    }
    setView(view);
    return;
  }
  $("#lk-home").hidden = false; $("#lk-canvas").hidden = true;
  readHome(query);
  $("#lk-q").value = L.q; $("#lk-show").value = L.show;
  setHome(homeHash());
  load();
}
let nav = 0;

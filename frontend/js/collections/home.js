// Collections (#/collections): the home list first, then one collection (#/collections/<id>[/documents]). List state (search, filter, sort) lives in
// the URL with history.replaceState, so Back from a collection returns to the same list. The server does the searching, filtering and sorting.
// "My prompts" (Library + Studio) is built in and always the first row. Plain DOM, no framework.
import { relTime } from "../api.js";
import { formDialog } from "../dialog.js";
import { toast } from "../toast.js";
import { listNav } from "../listnav.js";
import { ICONS, registerCommands } from "../palette.js";
import { api, esc, ic, I, json, pill, plural, splitTags, removeCollection } from "./common.js";
import { mountSetup } from "./setup.js";
import { showCollection, hideCollection, currentId, collectionCommands } from "./collection.js";

const $ = (s) => document.querySelector(s);
const SHOWS = { all: "All", ready: "Ready", preparing: "Preparing", starred: "Starred" };
const L = { q: "", show: "all", sort: "edited", dir: "desc", picked: false };
let built = false, items = [], total = 0, ticket = 0, timer = 0;

// ---------- the URL ----------
const homeHash = () => {
  const q = new URLSearchParams();
  if (L.q) q.set("q", L.q);
  if (L.show !== "all") q.set("show", L.show);
  if (L.picked || L.sort !== "edited" || L.dir !== "desc") { q.set("sort", L.sort); q.set("dir", L.dir); }
  const s = q.toString();
  return "#/collections" + (s ? "?" + s : "");
};
function readHome(query) {
  const q = new URLSearchParams(query);
  L.q = q.get("q") || ""; L.show = SHOWS[q.get("show")] ? q.get("show") : "all";
  L.sort = ["edited", "name", "documents"].includes(q.get("sort")) ? q.get("sort") : "edited"; L.dir = q.get("dir") === "asc" ? "asc" : "desc"; L.picked = q.has("sort");
}

// ---------- the list ----------
const onHome = () => /^#\/collections\/?(\?|$)/.test(location.hash);
async function load() {
  clearTimeout(timer);
  const my = ++ticket, rel = L.q.trim() && !L.picked, q = new URLSearchParams({ q: L.q, show: L.show, sort: rel ? "relevance" : L.sort, desc: L.dir === "desc", page_size: 200 });
  let d;
  try { d = await api("collections?" + q); } catch { $("#co-list").innerHTML = `<li class="muted pr-empty">Could not load the collections. Is the server running?</li>`; return; }
  if (my !== ticket) return;
  ({ items, total } = d);
  renderList();
  if (items.some((c) => c.status === "preparing") && onHome()) timer = setTimeout(load, 2000);   // progress moves on its own
}
function metaLine(c) {
  if (c.builtin) return `Library + Studio · ${plural(c.prompts, "prompt")} · ${c.status === "keyword" ? "searched by keyword" : "always in sync"}`;
  return [plural(c.documents, "document"), plural(c.passages, "passage"), c.failed ? `${c.failed} failed` : "", `edited ${relTime(c.updated_at)}`].filter(Boolean).join(" · ");
}
function rowHtml(c) {
  const tags = (c.tags || []).map((t) => `<span>${esc(t)}</span>`).join("");
  return `<li class="pr-row co-row" data-id="${esc(c.id)}">
    <a class="pr-link co-link" href="#/collections/${esc(c.id)}" data-open>
      <span class="co-ico">${ic(I.book, 20)}</span>
      <span class="co-body">
        <span class="pr-title">${esc(c.name)}${c.builtin ? ` <span class="co-chip">built in</span>` : ""}</span>
        <span class="pr-meta">${esc(metaLine(c))}</span>
        ${c.description && !c.builtin ? `<span class="pr-prev">${esc(c.description)}</span>` : ""}
        ${tags ? `<span class="lk-tags">${tags}</span>` : ""}
      </span>
      <span class="co-state">${pill(c)}</span>
    </a>
    ${`<div class="lk-pact">
      <button type="button" class="icon-btn lk-star${c.star ? " on" : ""}" data-star aria-pressed="${c.star}" aria-label="${c.star ? "Remove star" : "Star"}" title="${c.star ? "Remove star" : "Star"}">${ic(I.star, 18)}</button>
      <details class="pr-more">
        <summary class="btn btn-sm btn-glow btn-glow-md btn-glow-icon" aria-label="More" title="More">${ic(I.dots, 18)}</summary>
        <div class="pr-menu pr-morepanel" role="menu">
          <button type="button" class="pr-menuitem" role="menuitem" data-rename>${ic(I.edit, 18)}<span>Rename</span></button>
          ${c.builtin ? "" : `<button type="button" class="pr-menuitem" role="menuitem" data-del>${ic(I.trash, 18)}<span>Delete</span></button>`}
        </div>
      </details>
    </div>`}
  </li>`;
}
function renderList() {
  const filtered = L.q || L.show !== "all";
  $("#co-list").innerHTML = items.length ? items.map(rowHtml).join("") : `<li class="muted pr-empty">${filtered ? "Nothing matches these filters." : "No collections yet."}</li>`;
  $("#co-count").textContent = plural(total, "collection");
  document.querySelectorAll("#co-home .pr-sort").forEach((b) => {
    const on = b.dataset.sort === L.sort && (L.picked || !L.q.trim());
    b.classList.toggle("on", on);
    b.querySelector("span").textContent = on ? (L.dir === "asc" ? "↑" : "↓") : "";
  });
}
function refilter(patch) {
  Object.assign(L, patch);
  history.replaceState(null, "", homeHash());
  load();
}

// ---------- actions ----------
export async function newCollection() {
  const v = await formDialog({
    title: "New collection", confirmLabel: "Create",
    html: `<label class="pl-label" for="co-nname">Name</label><input class="pl-input" id="co-nname" autocomplete="off" placeholder="Product docs">
      <label class="pl-label" for="co-ndesc">What is in it (optional)</label><input class="pl-input" id="co-ndesc" autocomplete="off" placeholder="Manuals and release notes for the app">
      <label class="pl-label" for="co-ntags">Tags (optional, separated by commas)</label><input class="pl-input" id="co-ntags" autocomplete="off" placeholder="work, reference">`,
    validate: (d) => (d.querySelector("#co-nname").value.trim() ? "" : "Give the collection a name."),
    read: (d) => ({ name: d.querySelector("#co-nname").value.trim(), description: d.querySelector("#co-ndesc").value.trim(), tags: splitTags(d.querySelector("#co-ntags").value) }),
  });
  if (!v) return;
  try {
    const c = await api("collections", json("POST", v));
    location.hash = "#/collections/" + c.id + "/documents";
  } catch (e) { toast({ message: "Could not create the collection: " + e.message, ms: 4000 }); }
}
async function rename(c) {
  const v = await formDialog({ title: "Rename collection", confirmLabel: "Rename", html: `<label class="pl-label" for="co-rname">Name</label><input class="pl-input" id="co-rname" autocomplete="off" value="${esc(c.name)}">`,
    validate: (d) => (d.querySelector("#co-rname").value.trim() ? "" : "Give the collection a name."), read: (d) => d.querySelector("#co-rname").value.trim() });
  if (!v || v === c.name) return;
  try { await api("collections/" + c.id, json("PATCH", { name: v })); } catch (e) { toast({ message: "Could not rename: " + e.message, ms: 4000 }); }
  load();
}
async function star(c) {
  c.star = !c.star; renderList();
  try { await api("collections/" + c.id, json("PATCH", { star: c.star })); } catch { toast({ message: "Could not save the star." }); }
  load();
}

// ---------- page ----------
registerCommands(() => [
  { label: "New collection", where: "Collections", keywords: "knowledge create documents rag", icon: ICONS.plus, run: () => { location.hash = "#/collections"; setTimeout(newCollection, 80); } },
  { label: "Set up the embedding model", where: "Collections", keywords: "knowledge embedding model ollama pull index", icon: ICONS.setup, run: () => { location.hash = "#/settings/knowledge"; } },
  ...collectionCommands(),
  ...items.filter((c) => !c.builtin).map((c) => ({ label: c.name, where: "Collection", keywords: "open knowledge documents " + (c.tags || []).join(" "), icon: ICONS.find, run: () => { location.hash = "#/collections/" + c.id; } })),
  ...(items.some((c) => c.builtin) ? [{ label: items.find((c) => c.builtin).name, where: "Collection", keywords: "open knowledge library studio prompts", icon: ICONS.find, run: () => { location.hash = "#/collections/prompts"; } }] : []),
]);

function build(page) {
  page.innerHTML = `
    <div id="co-home">
      <section class="intro lk-intro">
        <div>
          <span class="eyebrow hud">// knowledge</span>
          <h1>Collections</h1>
          <p class="muted">Import documents and chat with them, together with your prompts.</p>
        </div>
        <div class="lk-heroact">
          <button type="button" class="btn btn-sm btn-glow btn-glow-md lk-new" id="co-new" data-hotkey="new">${ic(I.plus)}<span>New collection</span><kbd class="kbd" data-hk="new"></kbd></button>
        </div>
      </section>
      <section class="card co-setup" id="co-setup" hidden aria-label="Set up"></section>
      <section class="pl-filters" aria-label="Filters">
        <span class="srch"><input class="pl-input" id="co-q" data-search type="search" placeholder="Search collections" aria-label="Search collections"><kbd class="kbd" data-hk="search" aria-hidden="true"></kbd></span>
        <select class="pl-input" id="co-show" aria-label="Show">${Object.entries(SHOWS).map(([k, v]) => `<option value="${k}">${v}</option>`).join("")}</select>
        <span class="muted small pl-count" id="co-count"></span>
      </section>
      <section class="pr-table" aria-label="Collections">
        <div class="pr-thead">
          <button type="button" class="pr-sort" data-sort="name">Name <span></span></button>
          <button type="button" class="pr-sort" data-sort="documents">Documents <span></span></button>
          <button type="button" class="pr-sort" data-sort="edited">Edited <span></span></button>
        </div>
        <ul class="pr-list" id="co-list"></ul>
      </section>
    </div>
    <div id="co-view" hidden></div>`;
  const list = $("#co-list");
  $("#co-new").addEventListener("click", newCollection);
  $("#co-q").addEventListener("input", (e) => refilter({ q: e.target.value }));
  listNav($("#co-q"), list);
  $("#co-show").addEventListener("change", (e) => refilter({ show: e.target.value }));
  page.querySelectorAll("#co-home .pr-sort").forEach((b) => b.addEventListener("click", () => {
    const k = b.dataset.sort;
    refilter(k === L.sort && (L.picked || !L.q.trim()) ? { picked: true, dir: L.dir === "asc" ? "desc" : "asc" } : { sort: k, picked: true, dir: k === "name" ? "asc" : "desc" });
  }));
  list.addEventListener("click", (e) => {
    const row = e.target.closest(".co-row"), c = row && items.find((x) => x.id === row.dataset.id);
    if (!c) return;
    if (e.target.closest("[data-star]")) star(c);
    else if (e.target.closest("[data-rename]")) { row.querySelector("details")?.removeAttribute("open"); rename(c); }
    else if (e.target.closest("[data-del]")) { row.querySelector("details")?.removeAttribute("open"); removeCollection(c, load, load); }
  });
}

/** Router hook: #/collections shows the list, #/collections/<id> and #/collections/<id>/documents one collection. */
export async function showCollections() {
  const page = $("#page-collections");
  if (!built) { built = true; build(page); }
  const rest = location.hash.replace(/^#\/collections\/?/, ""), [raw, query = ""] = rest.startsWith("?") ? ["", rest.slice(1)] : rest.split("?");
  const [rawId, tab = ""] = (raw || "").split("/"), id = decodeURIComponent(rawId);
  if (id) {
    clearTimeout(timer);
    $("#co-home").hidden = true; $("#co-view").hidden = false;
    showCollection($("#co-view"), id, tab);
    return;
  }
  if (currentId()) hideCollection();
  $("#co-home").hidden = false; $("#co-view").hidden = true;
  readHome(query);
  $("#co-q").value = L.q; $("#co-show").value = L.show;
  mountSetup($("#co-setup"), load);
  load();
}

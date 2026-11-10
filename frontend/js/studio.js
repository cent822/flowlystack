// Prompt Studio: the prompts you write on purpose. A paged list (#/studio?q=&status=&tag=&page=…), an unsaved editor for a
// new prompt (#/studio/new) and one inner page per prompt (#/studio/<id>), which is the shared editor (editor.js) plus a
// status control and documentation fields. Plain DOM, no framework. API: /api/studio (backend/studio_api.py).
import { takeDraft } from "./handoff.js";
import { api, relTime as rel } from "./api.js";
import { confirmDialog } from "./dialog.js";
import { toast } from "./toast.js";
import { listNav } from "./listnav.js";
import { refreshTrashCount } from "./trash.js";
import { ICONS, registerCommands } from "./palette.js";
import { esc, send, hl, copy, stamp, parseTags, setCrumb, COPY_ICONS, TRASH, CHEV_L, CHEV_R, createEditor } from "./editor.js";
import * as assistant from "./assistant.js";
import { formDialog } from "./dialog.js";
import { hotkey, matches, isMac, label as keyLabel } from "./hotkeys.js";

const $ = (s) => document.querySelector(s);
const STATUS = { draft: "Draft", refined: "Refined", final: "Final" };
const chip = (s) => `<span class="st-status ${esc(s)}">${esc(STATUS[s] || s)}</span>`;

// ⌘K actions; the page itself is listed automatically from its sidebar link.
registerCommands(() => [
  { label: "New prompt", where: "Prompt Studio", keywords: "create write add studio", icon: ICONS.plus, run: () => { location.hash = "#/studio/new"; } },
  { label: "Find a Studio prompt", where: "Prompt Studio", keywords: "search studio reusable", icon: ICONS.find, run: () => {
    if (!/^#\/studio(\?|$)/.test(location.hash)) location.hash = "#/studio";
    setTimeout(() => { const i = $("#st-q"); i?.focus(); i?.select(); }, 80);   // after the palette closes and the page has switched
  } },
]);

// ======================================================================= routing
const view = { ready: false, fromList: false };

function parseHash() {
  const [path, query = ""] = location.hash.replace(/^#\//, "").split("?");
  const id = path.split("/")[1];
  return { id: id ? decodeURIComponent(id) : null, params: new URLSearchParams(query) };
}

const showOnly = (name) => ["list", "new", "detail"].forEach((n) => { $(`#st-${n}-view`).hidden = n !== name; });

export function showStudio() {
  if (!view.ready) { view.ready = true; wireList(); }
  const { id, params } = parseHash();
  if (id === "new") { showNew(); return; }
  if (id) { showDetail(id); return; }
  showOnly("list");
  window.onbeforeunload = null;
  applyParams(params);
  loadList().catch(() => {});
}

const backToList = () => {   // Back returns to the same search and page: the browser's history when we came from the list
  if (view.fromList && history.length > 1) history.back();
  else location.hash = "#/studio" + (listQuery() ? "?" + listQuery() : "");
  view.fromList = false;
};

// ======================================================================= list
// auto: while searching, results are ordered by relevance until the user picks a sort column.
const L = { q: "", status: "", filter: "all", tags: [], sort: "updated", dir: "desc", auto: true, page: 1, tagFind: "", seq: 0, data: null };
const effSort = () => (L.q && L.auto ? "relevance" : L.sort === "relevance" && !L.q ? "updated" : L.sort);

function applyParams(p) {
  L.q = p.get("q") || ""; L.status = p.get("status") || ""; L.filter = p.get("show") || "all"; L.tags = [...new Set(p.getAll("tag").filter(Boolean))];
  L.sort = p.get("sort") || "updated"; L.dir = p.get("dir") || (L.sort === "title" ? "asc" : "desc"); L.page = +p.get("page") || 1;
  L.auto = !p.get("sort");
  $("#st-q").value = L.q; $("#st-filter").value = L.filter;
}
const listQuery = () => {
  const p = new URLSearchParams();
  if (L.q) p.set("q", L.q);
  if (L.status) p.set("status", L.status);
  if (L.filter !== "all") p.set("show", L.filter);
  L.tags.forEach((t) => p.append("tag", t));
  if (!L.auto && (L.sort !== "updated" || L.dir !== "desc" || L.q)) { p.set("sort", L.sort); p.set("dir", L.dir); }
  if (L.page > 1) p.set("page", L.page);
  return p.toString();
};
// replaceState keeps the list state in the address without adding history entries, so Back returns to it.
const syncUrl = () => history.replaceState(null, "", "#/studio" + (listQuery() ? "?" + listQuery() : ""));

async function loadList() {
  const seq = ++L.seq;
  const p = new URLSearchParams({ q: L.q, status: L.status, sort: effSort(), desc: L.dir === "desc", page: L.page, page_size: 30 });
  L.tags.forEach((t) => p.append("tag", t));
  if (L.filter === "starred") p.set("starred", "true");
  const d = await api("studio?" + p);
  if (seq !== L.seq) return;   // a newer request already answered
  L.data = d;
  if (d.page !== L.page) { L.page = d.page; syncUrl(); }
  renderFilters(); renderRows(); renderPager();
}

function renderFilters() {
  const d = L.data;
  // Counts are what you would get by picking that status (or tag) on top of the other filters; a 0 is dimmed.
  $("#st-status").innerHTML = `<option value="">All statuses</option>` + d.statuses.map((s) => `<option value="${esc(s.name)}"${s.name === L.status ? " selected" : ""}>${esc(STATUS[s.name])} (${s.n})</option>`).join("");
  const f = L.tagFind.trim().toLowerCase();
  const shown = d.tags.filter((t) => !f || t.name.toLowerCase().includes(f));
  $("#st-tags").innerHTML = shown.length ? shown.map((t) => {
    const on = L.tags.includes(t.name);
    return `<button type="button" class="pl-chip${on ? " on" : ""}${!on && !t.n ? " dim" : ""}" data-tag="${esc(t.name)}" aria-pressed="${on}">${esc(t.name)} <span>${t.n}</span></button>`;
  }).join("") : `<span class="muted small">${d.tags.length ? "No tag matches." : "No tags yet."}</span>`;
  $("#st-tagtxt").textContent = L.tags.length ? `Tags · ${L.tags.length}` : `Tags${d.tags.length ? ` (${d.tags.length})` : ""}`;
  $("#st-tagchips").innerHTML = L.tags.map((t) => `<button type="button" class="pl-chip on" data-untag="${esc(t)}" title="Remove this tag filter">${esc(t)} ×</button>`).join("")
    + (L.tags.length > 1 ? `<button type="button" class="pl-chip" data-untag-all title="Clear all tag filters">Clear</button>` : "");
  $("#st-matched").textContent = `${d.matched} of ${d.total}`;
  const eff = effSort();
  document.querySelectorAll("#st-list-view .pr-sort").forEach((b) => {
    const k = b.dataset.sort, on = k === eff;
    if (k === "relevance") b.hidden = !L.q;   // only meaningful while searching
    b.classList.toggle("on", on);
    b.lastElementChild.textContent = on && k !== "relevance" ? (L.dir === "asc" ? "↑" : "↓") : "";
  });
}

function renderRows() {
  const d = L.data;
  $("#st-list").innerHTML = d.items.length ? d.items.map((o) => {
    const m = o.meta;
    return `
    <li class="pr-row">
      <a class="pr-link" href="#/studio/${encodeURIComponent(o.id)}" data-open>
        <span class="pr-top">
          <span class="pr-title">${m.starred ? `<span class="pr-star">★</span> ` : ""}${o.hl?.title ? hl(o.hl.title) : esc(o.title)}</span>
          <span class="pr-meta">${chip(m.status)}${rel(o.updated)}${o.variables ? ` · ${o.variables} variable${o.variables === 1 ? "" : "s"}` : ""}${m.target ? ` · ${esc(m.target)}` : ""}${o.derived_from ? " · from the Library" : ""}${(o.hl?.tags || m.tags).map((t) => `<i>${hl(t)}</i>`).join("")}</span>
        </span>
        <span class="pr-prev">${o.hl?.snippet ? hl(o.hl.snippet) : o.hl?.purpose ? hl(o.hl.purpose) : esc(m.purpose || o.preview)}</span>
        ${o.hl?.note ? `<span class="pr-note"><b>Note</b>${hl(o.hl.note)}</span>` : ""}
      </a>
      <button type="button" class="icon-btn pr-del" data-del="${esc(o.id)}" aria-label="Move to trash" title="Move to trash">${TRASH}</button>
    </li>`;
  }).join("")
    : `<li class="muted pr-empty">${d.total ? "Nothing matches these filters." : "No Studio prompts yet. Press New prompt to write your first one."}</li>`;
}

function renderPager() {
  const { page, pages } = L.data;
  const nav = $("#st-pager");
  nav.hidden = pages <= 1;
  if (pages <= 1) return;
  const nums = [...new Set([1, pages, page - 1, page, page + 1].filter((n) => n >= 1 && n <= pages))].sort((a, b) => a - b);
  let html = `<button type="button" class="pr-pg" data-page="${page - 1}" ${page === 1 ? "disabled" : ""} aria-label="Previous page">${CHEV_L}</button>`;
  nums.forEach((n, i) => {
    if (i && n - nums[i - 1] > 1) html += `<span class="pr-gap">…</span>`;
    html += `<button type="button" class="pr-pg" data-page="${n}"${n === page ? ` aria-current="page"` : ""}>${n}</button>`;
  });
  html += `<button type="button" class="pr-pg" data-page="${page + 1}" ${page === pages ? "disabled" : ""} aria-label="Next page">${CHEV_R}</button>`;
  nav.innerHTML = `<div class="pr-pager-box">${html}</div>`;
}

function refilter(patch = {}) {
  Object.assign(L, { page: 1 }, patch);
  syncUrl();
  loadList().catch(() => {});
}

function wireList() {
  let t;
  listNav($("#st-q"), $("#st-list"));
  $("#st-q").addEventListener("input", (e) => { clearTimeout(t); t = setTimeout(() => refilter({ q: e.target.value }), 150); });
  $("#st-status").addEventListener("change", (e) => refilter({ status: e.target.value }));
  $("#st-filter").addEventListener("change", (e) => refilter({ filter: e.target.value }));
  $("#st-tagfind").addEventListener("input", (e) => { L.tagFind = e.target.value; renderFilters(); });
  $("#st-tagchips").addEventListener("click", (e) => {
    const b = e.target.closest("[data-untag], [data-untag-all]"); if (!b) return;
    refilter({ tags: b.hasAttribute("data-untag-all") ? [] : L.tags.filter((x) => x !== b.dataset.untag) });
  });
  $("#st-tags").addEventListener("click", (e) => {   // toggles one tag; the panel stays open so several can be picked
    const b = e.target.closest("[data-tag]"); if (!b) return;
    const tg = b.dataset.tag;
    refilter({ tags: L.tags.includes(tg) ? L.tags.filter((x) => x !== tg) : [...L.tags, tg] });
  });
  document.querySelectorAll("#st-list-view .pr-sort").forEach((b) => b.addEventListener("click", () => {
    const k = b.dataset.sort;
    if (k === "relevance") return refilter({ sort: k, auto: false });
    refilter(k === effSort() ? { sort: k, auto: false, dir: L.dir === "asc" ? "desc" : "asc" } : { sort: k, auto: false, dir: k === "title" ? "asc" : "desc" });
  }));
  $("#st-pager").addEventListener("click", (e) => {
    const b = e.target.closest("[data-page]"); if (!b || b.disabled) return;
    L.page = +b.dataset.page; syncUrl(); loadList().catch(() => {});
    $("#panel").scrollTo({ top: 0 });
  });
  $("#st-new").addEventListener("click", () => { view.fromList = true; syncUrl(); });
  $("#st-list").addEventListener("click", async (e) => {
    if (e.target.closest("[data-open]")) { view.fromList = true; syncUrl(); return; }
    const del = e.target.closest("[data-del]"); if (!del) return;
    if (!await confirmDialog({ title: "Move to trash", message: "Move this prompt to the trash? You can restore it from Trash.", confirmLabel: "Move to trash", danger: true })) return;
    const id = del.dataset.del;
    await api("studio/" + encodeURIComponent(id), { method: "DELETE" });
    loadList().catch(() => {}); refreshTrashCount();
    toast({ message: "Moved to trash.", action: "Undo", onAction: async () => {
      await api(`trash/${encodeURIComponent(id)}/restore`, { method: "POST" }).catch(() => toast({ message: "Could not undo. Restore it from Trash." }));
      loadList().catch(() => {}); refreshTrashCount();
    } });
  });
}

// ======================================================================= new prompt
// An unsaved editor: nothing is written until the first Save, which creates the prompt (as version "Created") and opens it.
function showNew() {
  showOnly("new");
  const box = $("#st-new-view");
  box.innerHTML = `
    <button type="button" class="btn btn-sm btn-glow btn-glow-md pr-back" id="sn-back">${CHEV_L}<span>Back</span></button>
    <header class="pr-head">
      <div class="pr-titlerow"><input class="pr-titlein" id="sn-title" aria-label="Title" placeholder="Title (optional)"></div>
      <div class="pr-sub"><span>New prompt</span><span>Not saved yet</span></div>
      <div class="pr-tagrow">
        <label class="pl-label" for="sn-tags">Tags (comma separated)</label>
        <span class="srch"><input class="pl-input" id="sn-tags" data-tags placeholder="Add tags, separated by commas"><kbd class="kbd" data-hk="tags" aria-hidden="true">${keyLabel(hotkey("tags"))}</kbd></span>
      </div>
    </header>
    <section class="card pr-editor">
      <div class="pr-textwrap">
        <textarea class="pl-input pr-text" id="sn-text" spellcheck="false" aria-label="Prompt text" placeholder="Write the prompt. Use {{name}} for a part that changes each time."></textarea>
        <div class="pr-count muted" id="sn-count"></div>
      </div>
    </section>
    <div class="pr-savebar"><span class="pr-status muted" id="sn-status" role="status"></span><button type="button" class="btn btn-sm btn-glow btn-glow-md" id="sn-save" title="Save (${keyLabel(hotkey("save"))})">Save<kbd class="kbd" data-hk="save">${keyLabel(hotkey("save"))}</kbd></button></div>`;
  setCrumb("New prompt");
  const handed = takeDraft("new");   // "Use as prompt" in a Collections chat
  if (handed) { $("#sn-text").value = handed.text; $("#sn-title").value = handed.title || ""; $("#sn-status").textContent = `Loaded from ${handed.from}. Review it, then press Save.`; }
  let saving = false;
  const dirty = () => !!($("#sn-text").value.trim() || $("#sn-title").value.trim() || $("#sn-tags").value.trim());
  const count = () => {
    const t = $("#sn-text").value, words = t.trim() ? t.trim().split(/\s+/).length : 0;
    $("#sn-count").textContent = `${words} words · ${t.length} characters`;
  };
  const save = async () => {
    if (saving) return;
    const status = (m) => { $("#sn-status").textContent = m; };
    if (!$("#sn-text").value.trim()) { status("Write some text first"); $("#sn-text").focus(); return; }
    saving = true; status("Saving…");
    try {
      const d = await send("POST", "studio", { text: $("#sn-text").value, title: $("#sn-title").value.trim(), tags: parseTags($("#sn-tags").value) });
      window.onbeforeunload = null;
      toast({ message: "Prompt created." });
      location.replace("#/studio/" + encodeURIComponent(d.id));   // replace: Back must not return to the empty form
    } catch (e) {
      status(`Could not save: ${e.message}`);
    } finally { saving = false; }
  };
  $("#sn-text").addEventListener("input", count);
  box.onkeydown = (e) => { if (matches(e, "save")) { e.preventDefault(); save(); } };   // one handler per render (box outlives it); the Save key (Settings > Keyboard) works from title, tags or text
  $("#sn-save").onclick = save;
  $("#sn-back").onclick = async () => {
    if (dirty() && !await confirmDialog({ title: "Unsaved changes", message: "Discard your unsaved changes?", confirmLabel: "Discard", danger: true })) return;
    window.onbeforeunload = null;
    backToList();
  };
  window.onbeforeunload = () => (dirty() ? "" : undefined);
  count();
  $("#sn-title").focus();
}

// ======================================================================= detail
// The editor is shared with the Prompt Library (editor.js); Studio adds a status control and the documentation fields.
const pane = () => $("#st-detail-view");
const statusNow = () => pane().querySelector("#st-statusseg .on")?.dataset.v;
// Properties: the user's own key/value pairs (like Obsidian's), edited in a dialog and saved with Save. Every one goes into the header of
// a Markdown export. The old documentation fields are properties with the names purpose, target, use_when, example and note
// (the server keeps both in step), so the Assistant and the list keep reading them.
const props = { list: [] };   // [{key, value}] as on screen
const pid = (k) => k.trim().toLowerCase().replace(/[\s-]+/g, "_").replace(/^when_to_use(_it)?$/, "use_when");   // same rule as backend `property_id`
const fieldNow = (k) => props.list.find((p) => pid(p.key) === k)?.value ?? "";
const KNOWN_KEYS = ["purpose", "target", "use_when", "example", "note"];
const RESERVED = ["title", "tags", "status"];
const sameProps = (a, b) => JSON.stringify(a.map((p) => [p.key, p.value])) === JSON.stringify(b.map((p) => [p.key, p.value]));

// The text of the prompt on screen (the footer and the final-prompt hint read it); nothing here is saved.
const fill = { text: "" };

// ---- the row under the text box: Properties, with its shortcut
const kbd = (name) => `<kbd class="kbd">${esc(keyLabel(hotkey(name)))}</kbd>`;
function footHtml() {
  const count = props.list.length;
  const btn = (act, text, key) => `<button type="button" class="btn btn-sm btn-glow btn-glow-md st-footbtn" data-st="${act}" title="${esc(text)} (${esc(keyLabel(hotkey(key)))})">${esc(text)}${kbd(key)}</button>`;
  const sig = [count, hotkey("details")].join("|");
  return `<span class="st-foot" id="st-foot" data-sig="${esc(sig)}">${btn("details", count ? `Properties (${count})` : "Properties", "details")}</span>`;
}
function updateFoot() {
  const f = pane().querySelector("#st-foot");
  if (!f) return;
  const html = footHtml();
  if (!html.includes(`data-sig="${esc(f.dataset.sig)}"`)) f.outerHTML = html;   // typing changes nothing here unless a button appears, goes or gains a dot
}
addEventListener("flowlystack-hotkeys", () => { if (pane()) updateFoot(); });

// One header line: a single line is a quoted string; several lines become a YAML block so they stay readable.
function yamlField(key, value) {
  const k = /^[A-Za-z_][\w-]*$/.test(key) ? key : JSON.stringify(key);
  const v = value.replace(/\r\n/g, "\n").replace(/\n+$/, "");
  if (!v.includes("\n") || /^\s/.test(v)) return `${k}: ${JSON.stringify(v)}`;
  return `${k}: |-\n` + v.split("\n").map((l) => (l ? "  " + l : "")).join("\n");
}

const PLUS = `<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M12 5v14M5 12h14"/></svg>`;
const propRow = (p = { key: "", value: "" }) => `<div class="st-prop"><input class="pl-input st-prop-key" list="st-propkeys" value="${esc(p.key)}" placeholder="Name" aria-label="Property name" autocomplete="off" spellcheck="false"><textarea class="pl-input pl-area st-prop-val" rows="1" placeholder="Empty" aria-label="Property value" spellcheck="false">${esc(p.value)}</textarea><button type="button" class="icon-btn st-prop-del" aria-label="Remove this property" title="Remove">${TRASH}</button></div>`;
const rowsOf = (dlg) => [...dlg.querySelectorAll(".st-prop")].map((r) => ({ key: r.querySelector(".st-prop-key").value.trim(), value: r.querySelector(".st-prop-val").value }));

async function openProps() {
  const v = await formDialog({ title: "Properties", wide: true, confirmLabel: "Done",
    html: `<p class="muted small st-prop-intro">Your own notes about this prompt, as name and value pairs. Each one is added to the header of a Markdown export. Names like purpose, target, use_when, example and note are also read by the Assistant.</p>
      <div class="st-props" id="st-props">${props.list.map(propRow).join("")}</div>
      <button type="button" class="btn btn-sm btn-glow st-prop-add" id="st-prop-add">${PLUS}<span>Add property</span></button>
      <datalist id="st-propkeys">${KNOWN_KEYS.map((k) => `<option value="${k}">`).join("")}</datalist>`,
    onOpen: (dlg) => {
      const box = dlg.querySelector("#st-props");
      const add = () => { box.insertAdjacentHTML("beforeend", propRow()); box.lastElementChild.querySelector(".st-prop-key").focus(); };
      if (!props.list.length) { box.insertAdjacentHTML("beforeend", propRow()); }
      dlg.querySelector("#st-prop-add").addEventListener("click", add);
      box.addEventListener("click", (e) => { if (e.target.closest(".st-prop-del")) e.target.closest(".st-prop").remove(); });
      box.addEventListener("keydown", (e) => { if (e.key === "Enter" && e.target.matches(".st-prop-key")) { e.preventDefault(); e.target.nextElementSibling.focus(); } });
    },
    validate: (dlg) => {
      const seen = new Set();
      for (const r of rowsOf(dlg)) {
        if (!r.key && !r.value) continue;   // an empty row is just dropped
        if (!r.key) return "Give each property a name.";
        const id = pid(r.key);
        if (RESERVED.includes(id)) return `“${r.key}” is already in every export: title, tags and status are added for you.`;
        if (seen.has(id)) return `“${r.key}” appears twice.`;
        seen.add(id);
      }
      return "";
    },
    read: (dlg) => rowsOf(dlg).filter((r) => r.key) });
  if (v && !sameProps(v, props.list)) {   // properties are saved as soon as you press Done (they are not versioned like the text), so a refresh keeps them
    props.list = v; updateFoot();
    const d = editor.saved();
    try {
      d.meta = await send("PATCH", "studio/" + encodeURIComponent(d.id), { properties: v });
      props.list = d.meta.properties.map((p) => ({ ...p }));
      updateFoot();
      toast({ message: "Properties saved." });
    } catch (e) {   // the list stays on screen as an unsaved change, and Save tries again
      editor.status(`Could not save the properties (${e.message}). Press Save to try again.`);
    }
  }
  editor.focus();
}

const OPEN = { details: openProps };
pane().addEventListener("click", (e) => { const b = e.target.closest("[data-st]"); if (b) OPEN[b.dataset.st](); });

// Shortcuts (Settings > Keyboard): only while a Studio prompt is open for editing and no dialog is open, from any field on the page.
const onDetail = () => !pane().hidden && !!editor.saved() && /^#\/studio\/ps-/.test(location.hash);
addEventListener("keydown", (e) => {
  if (e.defaultPrevented || !onDetail() || document.querySelector("dialog[open]")) return;
  if (matches(e, "assistant")) { e.preventDefault(); pane().querySelector('[data-tool]')?.click(); return; }   // the Assistant button, whatever the mode
  if (!editor.editing()) return;
  const act = ["save", "details"].find((n) => matches(e, n));
  if (!act) return;
  e.preventDefault();
  if (act === "save") editor.save(); else OPEN[act]();
});
registerCommands(() => [
  { label: "Edit prompt properties", where: "Prompt Studio", keywords: "properties metadata purpose target use when example documentation note details header", icon: ICONS.find, run: () => (onDetail() ? setTimeout(openProps, 80) : (location.hash = "#/studio")) },
]);

// A Final prompt is meant to be settled: when its text is being edited while the status still says Final, offer Refined.
function finalHint(text, d) {
  const h = pane().querySelector("#st-finalhint");
  if (h && d) h.hidden = !(statusNow() === "final" && editor.editing() && text !== d.text);
}

const editor = createEditor({
  box: "#st-detail-view",
  base: "studio",
  messageDialog: true,
  compact: true,
  back: backToList,
  sub: (d) => `<span>${esc(d.id)}</span><span>Created ${stamp(d.ts)}</span>${d.derived_from ? `<span>Derived from <a href="#/prompts/${encodeURIComponent(d.derived_from.id)}">${d.derived_from.title ? esc(d.derived_from.title) : "a Library prompt"}</a>${d.derived_from.title === null ? " (no longer in the Library)" : ""}</span>` : ""}`,
  exportNote: false,   // the note is one of the properties below
  // an export is what is on screen, saved or not: the text, the status and the properties are read from the page
  exportFront: (d) => [`status: ${JSON.stringify(statusNow() || d.meta.status)}`, ...props.list.filter((p) => p.value.trim()).map((p) => yamlField(p.key, p.value))],
  exportJson: (d) => ({ status: statusNow() || d.meta.status, purpose: fieldNow("purpose"), use_when: fieldNow("use_when"), target: fieldNow("target"), example: fieldNow("example"),
    properties: Object.fromEntries(props.list.map((p) => [p.key, p.value])),
    variables: d.variables, derived_from: d.derived_from ?? null, created: new Date(d.ts * 1000).toISOString() }),
  tools: [{ label: "Assistant", title: "Ask the assistant about this prompt", icon: assistant.ICON, hotkey: "assistant", pressed: assistant.isOpen, run: assistant.toggle }],
  extras: {
    side: assistant.sideHtml,
    foot: footHtml,
    head: (d) => `
      <div class="st-statusrow">
        <span class="pl-label">Status</span>
        <div class="seg" id="st-statusseg" role="group" aria-label="Status">${Object.entries(STATUS).map(([k, l]) => `<button type="button" data-v="${k}" class="${k === d.meta.status ? "on" : ""}" aria-pressed="${k === d.meta.status}">${l}</button>`).join("")}</div>
      </div>
      <p class="st-hint muted small" id="st-finalhint" role="status" hidden>You are changing a Final prompt. <button type="button" class="btn btn-sm btn-glow" id="st-torefined">Mark as Refined</button></p>`,
    cards: (d) => {   // runs once per open: reset what only lives while the prompt is open, and load the fields the Details dialog edits
      fill.text = "";
      props.list = d.meta.properties.map((p) => ({ ...p }));
      return "";
    },
    text: (t, d) => { fill.text = t; updateFoot(); finalHint(t, d); assistant.onText(t); },
    wire(root) {
      assistant.mount(root, editor.saved(), { apply: (text, message) => editor.setDraft(text, message), savedText: () => editor.saved().text, meta: () => Object.fromEntries(["purpose", "use_when", "target"].map((k) => [k, fieldNow(k)])) });
      root.querySelector("#st-statusseg").addEventListener("click", (e) => {
        const b = e.target.closest("[data-v]"); if (!b) return;
        root.querySelectorAll("#st-statusseg button").forEach((x) => { const on = x === b; x.classList.toggle("on", on); x.setAttribute("aria-pressed", on); });
        finalHint(fill.text, editor.saved());
      });
      root.querySelector("#st-torefined").addEventListener("click", () => root.querySelector('#st-statusseg [data-v="refined"]').click());
    },
    changed: (d) => statusNow() !== d.meta.status || !sameProps(props.list, d.meta.properties),
    patch: (d) => ({ ...(statusNow() !== d.meta.status ? { status: statusNow() } : {}), ...(sameProps(props.list, d.meta.properties) ? {} : { properties: props.list }) }),
  },
});

function showDetail(id) {
  showOnly("detail");
  editor.open(id).then(() => { const h = takeDraft(id); if (h) editor.setDraft(h.text, h.message, h.from); });   // a draft handed over from Collections
}

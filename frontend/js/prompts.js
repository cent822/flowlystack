// Prompt Library: a paged list (#/prompts?q=&page=…) and one inner page per prompt (#/prompts/<id>)
// with an editor, saved versions, a compare view, tags and a note. Plain DOM, no framework.
// The detail editor itself lives in editor.js (shared with Prompt Studio).
import { takeDraft } from "./handoff.js";
import { api, relTime as rel } from "./api.js";
import { confirmDialog, formDialog } from "./dialog.js";
import { matches, hotkey, label as keyLabel } from "./hotkeys.js";
import { toast } from "./toast.js";
import { listNav } from "./listnav.js";
import { refreshTrashCount } from "./trash.js";
import { ICONS, registerCommands } from "./palette.js";
import { esc, send, hl, copy, stamp, COPY_ICONS, TRASH, CHEV_L, CHEV_R, createEditor } from "./editor.js";

const $ = (s) => document.querySelector(s);

registerCommands(() => [
  { label: "Capture setup", where: "Prompt Library", keywords: "hook import sync codex open webui capture", icon: ICONS.setup, run: () => { location.hash = "#/prompts?setup=1"; } },
]);

// ======================================================================= routing
const view = { ready: false, fromList: false };

function parseHash() {
  const [path, query = ""] = location.hash.replace(/^#\//, "").split("?");
  const id = path.split("/")[1];
  return { id: id ? decodeURIComponent(id) : null, params: new URLSearchParams(query) };
}

export function showPrompts() {
  if (!view.ready) { view.ready = true; wireList(); }
  const { id, params } = parseHash();
  if (id) { showDetail(id); return; }
  $("#pl-detail-view").hidden = true; $("#pl-list-view").hidden = false;
  window.onbeforeunload = null;
  applyParams(params);
  if (params.has("setup")) {   // #/prompts?setup=1 (the command palette): open the Capture setup card, then drop the flag from the address
    $("#pl-setup").open = true; syncUrl();
    $("#pl-setup").scrollIntoView({ block: "start" });
  }
  loadList().catch(() => {}); loadSetup().catch(() => {}); loadSync().catch(() => {});
}

// ======================================================================= list
// auto: while searching, results are ordered by relevance until the user picks a sort column.
const L = { q: "", filter: "all", project: "", agent: "", tags: [], sort: "updated", dir: "desc", auto: true, page: 1, tagFind: "", seq: 0, data: null };
const effSort = () => (L.q && L.auto ? "relevance" : L.sort === "relevance" && !L.q ? "updated" : L.sort);

function applyParams(p) {
  L.q = p.get("q") || ""; L.filter = p.get("show") || "all"; L.project = p.get("project") || ""; L.agent = p.get("agent") || ""; L.tags = [...new Set(p.getAll("tag").filter(Boolean))];
  L.sort = p.get("sort") || "updated"; L.dir = p.get("dir") || (L.sort === "title" ? "asc" : "desc"); L.page = +p.get("page") || 1;
  L.auto = !p.get("sort");
  $("#pl-q").value = L.q; $("#pl-filter").value = L.filter;
}
const listQuery = () => {
  const p = new URLSearchParams();
  if (L.q) p.set("q", L.q);
  if (L.filter !== "all") p.set("show", L.filter);
  if (L.project) p.set("project", L.project);
  if (L.agent) p.set("agent", L.agent);
  L.tags.forEach((t) => p.append("tag", t));
  if (!L.auto && (L.sort !== "updated" || L.dir !== "desc" || L.q)) { p.set("sort", L.sort); p.set("dir", L.dir); }
  if (L.page > 1) p.set("page", L.page);
  return p.toString();
};
// replaceState keeps the list state in the address without adding history entries, so Back returns to it.
const syncUrl = () => history.replaceState(null, "", "#/prompts" + (listQuery() ? "?" + listQuery() : ""));

async function loadList() {
  const seq = ++L.seq;
  const p = new URLSearchParams({ q: L.q, project: L.project, agent: L.agent, sort: effSort(), desc: L.dir === "desc", page: L.page, page_size: 30 });
  L.tags.forEach((t) => p.append("tag", t));
  if (L.filter === "starred") p.set("starred", "true");
  if (L.filter === "edited") p.set("edited", "true");
  const d = await api("prompts?" + p);
  if (seq !== L.seq) return;   // a newer request already answered
  L.data = d;
  if (d.page !== L.page) { L.page = d.page; syncUrl(); }
  renderFilters(); renderRows(); renderPager();
}

function renderFilters() {
  const d = L.data;
  $("#pl-project").innerHTML = `<option value="">All projects</option>` + d.projects.map((p) => `<option value="${esc(p.name)}"${p.name === L.project ? " selected" : ""}>${esc(p.name)} (${p.n})</option>`).join("");
  const ag = $("#pl-agent");   // the Source filter only appears once prompts from more than one agent exist
  ag.hidden = d.agents.length < 2 && !L.agent;
  ag.innerHTML = `<option value="">All agents</option>` + d.agents.map((a) => `<option value="${esc(a.name)}"${a.name === L.agent ? " selected" : ""}>${esc(a.name)} (${a.n})</option>`).join("");
  const f = L.tagFind.trim().toLowerCase();
  const shown = d.tags.filter((t) => !f || t.name.toLowerCase().includes(f));
  // Counts are what you would get by adding that tag to the current filters (tags AND together); a 0 is dimmed.
  $("#pl-tags").innerHTML = shown.length ? shown.map((t) => {
    const on = L.tags.includes(t.name);
    return `<button type="button" class="pl-chip${on ? " on" : ""}${!on && !t.n ? " dim" : ""}" data-tag="${esc(t.name)}" aria-pressed="${on}">${esc(t.name)} <span>${t.n}</span></button>`;
  }).join("") : `<span class="muted small">${d.tags.length ? "No tag matches." : "No tags yet."}</span>`;
  $("#pl-tagtxt").textContent = L.tags.length ? `Tags · ${L.tags.length}` : `Tags${d.tags.length ? ` (${d.tags.length})` : ""}`;
  $("#pl-tagchips").innerHTML = L.tags.map((t) => `<button type="button" class="pl-chip on" data-untag="${esc(t)}" title="Remove this tag filter">${esc(t)} ×</button>`).join("")
    + (L.tags.length > 1 ? `<button type="button" class="pl-chip" data-untag-all title="Clear all tag filters">Clear</button>` : "");
  $("#pl-matched").textContent = `${d.matched} of ${d.total}`;
  const eff = effSort();
  document.querySelectorAll("#pl-list-view .pr-sort").forEach((b) => {
    const k = b.dataset.sort, on = k === eff;
    if (k === "relevance") b.hidden = !L.q;   // only meaningful while searching
    b.classList.toggle("on", on);
    b.lastElementChild.textContent = on && k !== "relevance" ? (L.dir === "asc" ? "↑" : "↓") : "";
  });
}

function renderRows() {
  const d = L.data;
  $("#pl-list").innerHTML = d.items.length ? d.items.map((o) => `
    <li class="pr-row">
      <a class="pr-link" href="#/prompts/${encodeURIComponent(o.id)}" data-open>
        <span class="pr-top">
          <span class="pr-title">${o.meta.starred ? `<span class="pr-star">★</span> ` : ""}${o.hl?.title ? hl(o.hl.title) : esc(o.title)}</span>
          <span class="pr-meta"><span class="pr-agent">${esc(o.agent || "claude")}</span>${esc(o.project || o.model || "unknown")} · ${rel(o.updated)}${o.edited ? " · edited" : ""}${(o.hl?.tags || o.meta.tags).map((t) => `<i>${hl(t)}</i>`).join("")}</span>
        </span>
        <span class="pr-prev">${o.hl?.snippet ? hl(o.hl.snippet) : esc(o.preview)}</span>
        ${o.hl?.note ? `<span class="pr-note"><b>Note</b>${hl(o.hl.note)}</span>` : ""}
      </a>
      <button type="button" class="icon-btn pr-del" data-del="${esc(o.id)}" aria-label="Move to trash" title="Move to trash">${TRASH}</button>
    </li>`).join("")
    : `<li class="muted pr-empty">${d.total ? "Nothing matches these filters." : "No prompts saved yet. Open Capture setup to install the hook or import past prompts."}</li>`;
}

function renderPager() {
  const { page, pages } = L.data;
  const nav = $("#pl-pager");
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

async function loadSetup() {
  const s = await api("prompts/setup");
  $("#pl-dir").textContent = s.dir; $("#pl-file").textContent = s.settings_file;
  $("#pl-snippet").textContent = JSON.stringify(s.snippet, null, 2);
  $("#pl-count").textContent = `${s.saved} saved`;
  $("#pl-copy").onclick = (e) => copy(e.currentTarget, JSON.stringify(s.snippet, null, 2));
  if (!s.saved) $("#pl-setup").open = true;
}

// Other agents (Codex, Open WebUI): an Import button (one shot, always "Import", safe to press again) and a Live sync switch.
// Codex also gets a hook setup block like Claude's: its hooks.json has the same shape as Claude's settings.json hooks.
const SYNC = { codexSnippet: "", live: {}, imp: {} };   // the last Import and Live sync messages per agent, shown beside their buttons (the row is rebuilt on every refresh)

const hookBlock = (c) => `
  <div class="pl-hook">
    <p class="small">To capture Codex prompts the moment you send them, add this hook to <code>${esc(c.settings_file)}</code> (merge it with any hooks already there), then run <code>/hooks</code> in the Codex CLI and trust it: Codex only runs hooks you have reviewed. Live sync also works for the Codex app and VS Code, because it reads Codex's session files.</p>
    <pre class="pl-code">${esc(JSON.stringify(c.snippet, null, 2))}</pre>
    <div class="pl-row"><button class="btn btn-sm btn-glow btn-glow-md" type="button" data-copy>${COPY_ICONS}<span>Copy hook JSON</span></button></div>
  </div>`;

// The Live sync message follows the switch, so it shows on first load and after a refresh; SYNC.live only carries an error.
const liveMsg = (id, a) => SYNC.live[id] || (a.enabled ? `Live sync on for ${a.label}: new prompts arrive within seconds` : `Live sync off for ${a.label}`);

async function loadSync() {
  const [s, setup] = await Promise.all([api("prompts/sync"), api("prompts/setup")]);
  SYNC.codexSnippet = setup.codex ? JSON.stringify(setup.codex.snippet, null, 2) : "";
  const rows = Object.entries(s).filter(([, a]) => a.available);
  const box = $("#pl-sync");
  box.hidden = !rows.length;
  box.innerHTML = rows.length ? `<span class="pl-label">Other agents</span>` + rows.map(([id, a]) => `
    <div class="pl-agentbox">
      <div class="pl-syncrow"><span class="pl-synclabel">${esc(a.label)}</span>
        <span class="muted small pl-syncstate">${a.imported} imported${a.error ? ` · ${esc(a.error)}` : ""}</span>
        <button class="btn btn-sm btn-glow btn-glow-md" type="button" data-import="${esc(id)}">Import</button>
        <span class="muted small pl-impmsg" role="status">${esc(SYNC.imp[id] || "")}</span>
        <button class="pl-switch" type="button" role="switch" aria-checked="${a.enabled}" data-live="${esc(id)}"><i></i><span>Live sync</span></button>
        <span class="muted small pl-livemsg" role="status">${esc(liveMsg(id, a))}</span>
      </div>
      ${id === "codex" && setup.codex ? hookBlock(setup.codex) : ""}
    </div>`).join("") : "";
}

function wireList() {
  let t;
  $("#pl-sync").addEventListener("click", async (e) => {
    const copyBtn = e.target.closest("[data-copy]");
    if (copyBtn) return copy(copyBtn, SYNC.codexSnippet);
    const imp = e.target.closest("[data-import]"), live = e.target.closest("[data-live]");
    const btn = imp || live; if (!btn || btn.disabled) return;
    const id = (imp || live).dataset.import || live.dataset.live, label = btn.closest(".pl-agentbox").querySelector(".pl-synclabel").textContent;
    btn.disabled = true;
    try {
      if (imp) {
        imp.textContent = "Importing…"; imp.parentElement.querySelector(".pl-impmsg").textContent = "";
        const r = await api(`prompts/sync/${encodeURIComponent(id)}/import`, { method: "POST" });
        SYNC.imp[id] = `Imported ${r.imported} · ${r.already} already saved`;
      } else {
        const on = live.getAttribute("aria-checked") !== "true";
        await send("PUT", "prompts/sync/" + encodeURIComponent(id), { enabled: on });
        delete SYNC.live[id];   // the message is derived from the new state
      }
    } catch (err) {
      if (imp) SYNC.imp[id] = "Could not import";
      else SYNC.live[id] = `Could not change live sync for ${label}`;
    }
    await Promise.all([loadList(), loadSetup(), loadSync()]).catch(() => {});   // rebuilds the row: the Import button reads "Import" again
  });
  $("#pl-agent").addEventListener("change", (e) => refilter({ agent: e.target.value }));
  listNav($("#pl-q"), $("#pl-list"));
  $("#pl-q").addEventListener("input", (e) => { clearTimeout(t); t = setTimeout(() => refilter({ q: e.target.value }), 150); });
  $("#pl-filter").addEventListener("change", (e) => refilter({ filter: e.target.value }));
  $("#pl-project").addEventListener("change", (e) => refilter({ project: e.target.value }));
  $("#pl-tagfind").addEventListener("input", (e) => { L.tagFind = e.target.value; renderFilters(); });
  $("#pl-tagchips").addEventListener("click", (e) => {
    const b = e.target.closest("[data-untag], [data-untag-all]"); if (!b) return;
    refilter({ tags: b.hasAttribute("data-untag-all") ? [] : L.tags.filter((t) => t !== b.dataset.untag) });
  });
  $("#pl-tags").addEventListener("click", (e) => {   // toggles one tag; the panel stays open so several can be picked
    const b = e.target.closest("[data-tag]"); if (!b) return;
    const t = b.dataset.tag;
    refilter({ tags: L.tags.includes(t) ? L.tags.filter((x) => x !== t) : [...L.tags, t] });
  });
  document.querySelectorAll("#pl-list-view .pr-sort").forEach((b) => b.addEventListener("click", () => {
    const k = b.dataset.sort;
    if (k === "relevance") return refilter({ sort: k, auto: false });
    refilter(k === effSort() ? { sort: k, auto: false, dir: L.dir === "asc" ? "desc" : "asc" } : { sort: k, auto: false, dir: k === "title" ? "asc" : "desc" });
  }));
  $("#pl-pager").addEventListener("click", (e) => {
    const b = e.target.closest("[data-page]"); if (!b || b.disabled) return;
    L.page = +b.dataset.page; syncUrl(); loadList().catch(() => {});
    $("#panel").scrollTo({ top: 0 });
  });
  $("#pl-list").addEventListener("click", async (e) => {
    if (e.target.closest("[data-open]")) { view.fromList = true; syncUrl(); return; }
    const del = e.target.closest("[data-del]"); if (!del) return;
    if (!await confirmDialog({ title: "Move to trash", message: "Move this prompt to the trash? You can restore it from Trash.", confirmLabel: "Move to trash", danger: true })) return;
    const id = del.dataset.del;
    await api("prompts/" + encodeURIComponent(id), { method: "DELETE" });
    loadList().catch(() => {}); loadSetup().catch(() => {}); refreshTrashCount();
    toast({ message: "Moved to trash.", action: "Undo", onAction: async () => {
      await api(`trash/${encodeURIComponent(id)}/restore`, { method: "POST" }).catch(() => toast({ message: "Could not undo. Restore it from Trash." }));
      loadList().catch(() => {}); loadSetup().catch(() => {}); refreshTrashCount();
    } });
  });
  $("#pl-import").addEventListener("click", async () => {
    $("#pl-import-msg").textContent = "Importing…";
    try {
      const r = await api("prompts/import", { method: "POST" });
      $("#pl-import-msg").textContent = `Imported ${r.imported}, skipped ${r.skipped} already saved`;
      await Promise.all([loadList(), loadSetup()]);
    } catch (e) { $("#pl-import-msg").textContent = "Import failed"; }
  });
}

// ======================================================================= detail
// The editor is shared with Prompt Studio (editor.js); this page supplies what is specific to a captured prompt.
const editor = createEditor({
  box: "#pl-detail-view",
  base: "prompts",
  back() {   // Back returns to the same search and page: the browser's history when we came from the list, else the list address
    if (view.fromList && history.length > 1) history.back();
    else location.hash = "#/prompts" + (listQuery() ? "?" + listQuery() : "");
    view.fromList = false;
  },
  sub: (d) => `<span>${esc(d.id)}</span><span>${esc(d.project || "unknown")}</span><span>${esc(d.agent || "claude")}${d.model ? " · " + esc(d.model) : ""}</span><span>Captured ${stamp(d.ts)} · ${esc(d.source)}</span>`,
  exportFront: (d) => [`project: ${JSON.stringify(d.project || "")}`],
  exportJson: (d) => ({ project: d.project || "", source: d.source, captured: new Date(d.ts * 1000).toISOString() }),
  actions: [{ label: "Save as reusable prompt", run: saveToStudio }],
  messageDialog: true,   // same page as Prompt Studio: Save in the footer row asks "what changed" in a dialog, the page fits the window
  compact: true,         // no Note card: the note is edited in a dialog (the Note button in the footer)
  extras: { foot: () => `<button type="button" class="btn btn-sm btn-glow btn-glow-md st-footbtn" id="pl-notebtn" data-hotkey="note" title="Add or edit the note (${esc(keyLabel(hotkey("note")))})">${noteLabel()}</button>` },
});

const noteLabel = () => `+ Note${editor.note().trim() ? `<i class="pr-dot" aria-hidden="true"></i>` : ""}<kbd class="kbd" data-hk="note">${esc(keyLabel(hotkey("note")))}</kbd>`;
async function editNote() {
  const v = await formDialog({ title: "Note", wide: true, confirmLabel: "Done",
    html: `<label class="pl-label" for="pl-notetext">Why it worked, what to change next time</label><textarea class="pl-input pl-area" id="pl-notetext" rows="8" placeholder="Note">${esc(editor.note())}</textarea>`,
    read: (dlg) => dlg.querySelector("#pl-notetext").value });
  if (v !== null && v !== editor.note()) {
    editor.setNote(v);
    const b = $("#pl-notebtn"); if (b) b.innerHTML = noteLabel();
    editor.status("Note changed. Press Save to keep it.");
  }
  editor.focus();
}
$("#pl-detail-view").addEventListener("click", (e) => { if (e.target.closest("#pl-notebtn")) editNote(); });

// Save shortcut (Settings > Keyboard), from any field of an open Library prompt, like Prompt Studio.
addEventListener("keydown", (e) => {
  if (e.defaultPrevented || $("#pl-detail-view").hidden || !editor.editing() || document.querySelector("dialog[open]")) return;
  if (matches(e, "save")) { e.preventDefault(); editor.save(); }
});

// Copy this prompt into Prompt Studio (its saved text; the Library prompt itself is never changed). The copy keeps a link back.
async function saveToStudio(d) {
  if (editor.dirty() && !await confirmDialog({ title: "Unsaved changes", message: "Only the saved text is copied to Prompt Studio. Your unsaved edits stay here.", confirmLabel: "Copy saved text" })) return;
  try {
    const have = await api("studio?page_size=1&derived_from=" + encodeURIComponent(d.id));
    if (have.matched && !await confirmDialog({ title: "Already in Prompt Studio", message: `This prompt was already saved there as “${have.items[0].title}”. Save another copy?`, confirmLabel: "Save another copy" })) return;
    const made = await send("POST", "studio", { from_library: d.id });
    toast({ message: "Saved to Prompt Studio.", action: "Open in Studio", ms: 10000, onAction: () => { location.hash = "#/studio/" + encodeURIComponent(made.id); } });
  } catch (e) {
    toast({ message: "Could not save to Prompt Studio." });
  }
}

function showDetail(id) {
  $("#pl-list-view").hidden = true;
  editor.open(id).then(() => { const h = takeDraft(id); if (h) editor.setDraft(h.text, h.message, h.from); });   // a draft handed over from Collections
}

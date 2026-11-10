// The prompt detail editor shared by the Prompt Library and Prompt Studio: title, tags, text editor, version picker,
// compare view, export, note and save bar. A page builds one with createEditor({...}) and calls open(id).
// The caller supplies what differs: the API base ("prompts" or "studio"), the line under the title, what an export adds,
// where Back goes, and optionally `extras` (more fields for the head and the cards, see below). Plain DOM, no framework.
import { api, relTime as rel } from "./api.js";
import { confirmDialog } from "./dialog.js";
import { toast } from "./toast.js";
import { formDialog } from "./dialog.js";
import { hotkey, label as keyLabel } from "./hotkeys.js";

export const esc = (t) => String(t ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);

export const send = (method, path, body) => api(path, { method, headers: { "content-type": "application/json" }, body: JSON.stringify(body) });

// Search matches arrive wrapped in private-use markers; escape the text first, then turn the markers into <mark>.
export const hl = (s) => esc(s).replaceAll("", "<mark>").replaceAll("", "</mark>");

export const COPY_ICONS = `<svg class="ic ic-copy" viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V6a2 2 0 0 1 2-2h9"/></svg><svg class="ic ic-ok" viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg>`;
export const TRASH = `<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 7h16M10 11v6M14 11v6M6 7l1 12a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2l1-12M9 7V4h6v3"/></svg>`;
export const DOTS = `<svg viewBox="0 0 24 24" width="18" height="18" fill="currentColor" aria-hidden="true"><circle cx="5" cy="12" r="1.8"/><circle cx="12" cy="12" r="1.8"/><circle cx="19" cy="12" r="1.8"/></svg>`;
export const CHEV_L = `<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M15 5l-7 7 7 7"/></svg>`;
export const CHEV_R = CHEV_L.replace("M15 5l-7 7 7 7", "M9 5l7 7-7 7");
export const CHEV_D = CHEV_L.replace("M15 5l-7 7 7 7", "M6 9l6 6 6-6");

export async function copy(btn, text) {
  let ok = false;
  try { await navigator.clipboard.writeText(text); ok = true; } catch { /* no permission or no focus: try the old way */ }
  if (!ok) {   // the textarea goes inside the open dialog, because everything outside a modal dialog cannot take focus
    const t = document.createElement("textarea");
    t.value = text; t.style.cssText = "position:fixed;opacity:0;pointer-events:none";
    (btn.closest("dialog") || document.body).append(t);
    t.select();
    try { ok = document.execCommand("copy"); } catch { /* stays false */ }
    t.remove(); btn.focus();
  }
  btn.classList.toggle("fail", !ok);
  if (!ok) { clearTimeout(btn._t); btn._t = setTimeout(() => btn.classList.remove("fail"), 2500); toast({ message: "Could not copy. Select the text and copy it by hand." }); return; }
  btn.classList.add("done");   // a green tick replaces the copy icon for a moment, only when the copy really worked
  clearTimeout(btn._t);
  btn._t = setTimeout(() => btn.classList.remove("done"), 1500);
}

export const stamp = (ts) => new Date(ts * 1000).toLocaleString("en-US", { month: "short", day: "numeric", year: "numeric", hour: "numeric", minute: "2-digit" });
export const parseTags = (s) => [...new Set(s.split(",").map((t) => t.trim()).filter(Boolean))];

// Dropdowns built on <details> (the version picker, the Tags menu, the ⋯ menus) close on a click anywhere outside them, or Esc.
// Registered once, here, for every page that imports this module.
const DROPDOWNS = "details.pr-vers[open], details.pl-tagmenu[open], details.pr-more[open], details.pr-rowmenu[open]";
document.addEventListener("click", (e) => {
  document.querySelectorAll(DROPDOWNS).forEach((d) => { if (!d.contains(e.target)) d.open = false; });
});
document.addEventListener("keydown", (e) => {
  if (e.key !== "Escape") return;
  document.querySelectorAll(DROPDOWNS).forEach((d) => { d.open = false; d.querySelector("summary")?.focus(); });
});

// The last breadcrumb is the prompt's title; the router rebuilds the crumbs on every page change, so this only adds a tail.
export function setCrumb(text) {
  const c = document.querySelector("#crumbs");
  c.querySelectorAll(".tail").forEach((n) => n.remove());
  c.insertAdjacentHTML("beforeend", `<span class="sep tail">/</span><span class="cur tail">${esc(text.length > 48 ? text.slice(0, 48) + "…" : text)}</span>`);
}

// ---- export: the file is built in the browser; the browser's own Save dialog lets the user pick the folder and rename it
const EXPORTS = {
  json: { label: "JSON", ext: ".json", mime: "application/json", types: { "application/json": [".json"] } },
  txt: { label: "Plain text", ext: ".txt", mime: "text/plain", types: { "text/plain": [".txt"] } },
  md: { label: "Markdown", ext: ".md", mime: "text/markdown", types: { "text/markdown": [".md"] } },
};
const slug = (t) => t.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 60) || "prompt";

/** Save a text file: the browser's own Save dialog where there is one, else a download. Returns the message to toast;
 *  rejects with an AbortError when the dialog is closed. `f` = { label, types } as in EXPORTS. */
export async function saveFile(name, body, f) {
  if (window.showSaveFilePicker) {   // Chromium browsers: native Save dialog with folder and file name
    const h = await window.showSaveFilePicker({ suggestedName: name, types: [{ description: f.label, accept: f.types }] });
    const w = await h.createWritable(); await w.write(body); await w.close();
    return `Exported as ${f.label}.`;
  }
  // no picker API (Safari, Firefox, Brave by default): a download. octet-stream, not text/*, so every format is
  // treated like JSON by the browser: text types can be saved silently, without the "where to save" prompt.
  const a = Object.assign(document.createElement("a"), { href: URL.createObjectURL(new Blob([body], { type: "application/octet-stream" })), download: name });
  document.body.append(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  return `Sent ${name} to your browser's downloads.`;
}

/** The rows of a compare as HTML (split: two columns with heads; otherwise one column with signs). `rows` come from the diff API.
 *  Shared by the version compare here and the Assistant's Proposed edit card. */
export function diffHtml(rows, split, headA = "", headB = "") {
  const segs = (side) => !side ? "" : side.segs.map(([t, c]) => (c ? `<mark>${esc(t)}</mark>` : esc(t))).join("") || "​";
  if (split) {
    return `<div class="df-head" style="grid-column:1/3">${esc(headA)}</div><div class="df-head" style="grid-column:3/5">${esc(headB)}</div>` +
      rows.map((r) => r.t === "gap" ? `<div class="df-gap">⋯ ${r.n} unchanged line${r.n === 1 ? "" : "s"}</div>` : `
      <div class="df-n ${r.t === "del" || r.t === "chg" ? "df-del" : ""}">${r.a?.n ?? ""}</div><div class="df-t ${r.t === "del" || r.t === "chg" ? "df-del" : ""}">${segs(r.a)}</div>
      <div class="df-n ${r.t === "add" || r.t === "chg" ? "df-add" : ""}">${r.b?.n ?? ""}</div><div class="df-t ${r.t === "add" || r.t === "chg" ? "df-add" : ""}">${segs(r.b)}</div>`).join("");
  }
  return rows.map((r) => {
    if (r.t === "gap") return `<div class="df-gap">⋯ ${r.n} unchanged line${r.n === 1 ? "" : "s"}</div>`;
    const line = (cls, a, b, sign, side) => `<div class="df-n ${cls}">${a ?? ""}</div><div class="df-n ${cls}">${b ?? ""}</div><div class="df-n ${cls}">${sign}</div><div class="df-t ${cls}">${segs(side)}</div>`;
    if (r.t === "eq") return line("", r.a.n, r.b.n, "", r.a);
    return (r.a ? line("df-del", r.a.n, "", "−", r.a) : "") + (r.b ? line("df-add", "", r.b.n, "+", r.b) : "");
  }).join("");
}

// A shortcut changed in Settings: the key shown on toolbar buttons follows.
addEventListener("flowlystack-hotkeys", () => document.querySelectorAll("kbd[data-hk]").forEach((k) => { k.textContent = keyLabel(hotkey(k.dataset.hk)); }));

/**
 * cfg:
 *   box          selector of the element the editor fills (its contents are replaced on open)
 *   base         API path of the store: "prompts" or "studio"
 *   back()       called after the unsaved-changes check when the user presses Back
 *   sub(d)       HTML for the line under the title (spans)
 *   exportFront(d)  extra front-matter lines for a Markdown export, e.g. [`project: "x"`]
 *   exportJson(d)   extra fields for a JSON export, placed between `starred` and `version`
 *   extras (optional): { head(d), cards(d), changed(d), patch(d), wire(box), text(t) }
 *      head/cards return HTML for the header (after the tags) and for cards between the editor and the note;
 *      changed(d) says whether those fields have unsaved edits, patch(d) returns the meta fields to send on save,
 *      wire(box) attaches their listeners after each build. Editor ids all start with `pr-`.
 *      text(t, d) is called with the text on screen and the saved prompt whenever it changes (typing, switching version or mode).
 *   actions (optional): [{ label, run(d) }] shown in the ⋯ menu above Export; run gets the loaded prompt.
 *   tools (optional): [{ label, title, icon, hotkey (name), pressed(), run(d) }] toggle buttons in the toolbar, left of Copy; run returns the new pressed state.
 *   messageDialog (optional, Studio): Save asks for the "what changed" message in a small dialog instead of a box in the bar.
 *   exportNote (optional): false leaves the note out of the Markdown header (exportFront then decides, as Studio does).
 *   compact (optional, Studio): no Note card on the page; the note is edited in a dialog the page supplies (`note()` / `setNote()`).
 *   extras.foot(d) (optional): HTML for the row under the text box, right of the word count (edit mode only).
 *   extras.side(d) (optional): HTML for a column beside the editor (`#pr-side`, hidden until a tool shows it). Without it the DOM is unchanged.
 */
export function createEditor(cfg) {
  const D = { id: null, d: null, mode: "edit", draft: "", rev: null, diff: null, split: true, titleDirty: false, saving: false, msg: "", note: "", asking: false };
  const x = cfg.extras;
  const root = () => document.querySelector(cfg.box);
  const $ = (s) => root().querySelector(s);   // scoped: another page's editor may still sit in the DOM with the same ids
  const url = (...p) => [cfg.base, encodeURIComponent(D.id), ...p].join("/");

  const noteNow = () => (cfg.compact ? D.note : ($("#pr-note")?.value ?? ""));
  const setMsg = (t) => { if (cfg.messageDialog) D.msg = t; else { const i = $("#pr-msg"); if (i) i.value = t; } };
  const dirty = () => !!D.d && (D.draft !== D.d.text || D.titleDirty
    || JSON.stringify(parseTags($("#pr-tags")?.value ?? "")) !== JSON.stringify(D.d.meta.tags) || noteNow() !== D.d.meta.note
    || !!x?.changed?.(D.d));

  async function open(id) {
    const box = root();
    box.hidden = false;
    Object.assign(D, { id, d: null, mode: "edit", rev: null, diff: null, titleDirty: false, saving: false, msg: "", note: "" });
    box.innerHTML = `<button type="button" class="btn btn-sm btn-glow btn-glow-md pr-back" id="pr-back">${CHEV_L}<span>Back</span></button><p class="muted" style="margin-top:24px">Loading…</p>`;
    $("#pr-back").onclick = goBack;
    try {
      D.d = await api(cfg.base + "/" + encodeURIComponent(id));
    } catch (e) {
      box.insertAdjacentHTML("beforeend", `<p>${e.status === 404 ? "This prompt no longer exists (it may have been moved to the trash)." : "Could not load this prompt."}</p>`);
      return;
    }
    D.draft = D.d.text; D.note = D.d.meta.note;
    buildDetail();
  }

  async function goBack() {
    if (dirty() && !await confirmDialog({ title: "Unsaved changes", message: "Discard your unsaved changes?", confirmLabel: "Discard", danger: true })) return;
    window.onbeforeunload = null;
    cfg.back();
  }

  function exportBody(kind, text, version) {
    const d = D.d, m = d.meta;
    const title = $("#pr-title")?.value.trim() || d.title, tags = $("#pr-tags") ? parseTags($("#pr-tags").value) : m.tags, note = noteNow();   // as on screen, saved or not (like the text)
    if (kind === "txt") return text;
    if (kind === "md") {
      const fm = ["---", `title: ${JSON.stringify(title)}`, ...(tags.length ? [`tags: ${JSON.stringify(tags)}`] : []), ...(note && cfg.exportNote !== false ? [`note: ${JSON.stringify(note)}`] : []), ...cfg.exportFront(d), "---", ""];
      return fm.join("\n") + "\n" + text + (text.endsWith("\n") ? "" : "\n");
    }
    return JSON.stringify({ id: d.id, title, text, tags, note, starred: m.starred, ...cfg.exportJson(d), version }, null, 2) + "\n";
  }

  async function exportPrompt(kind) {
    const f = EXPORTS[kind];
    const viewing = D.mode === "view" && D.rev;
    const body = exportBody(kind, viewing ? D.rev.text : D.draft, viewing ? D.rev.short : (D.d.revisions[0]?.short ?? "original"));
    try {
      toast({ message: await saveFile(slug(D.d.title) + f.ext, body, f) });
    } catch (e) {
      if (e.name !== "AbortError") toast({ message: "Could not export this prompt." });   // closing the Save dialog is not an error
    }
  }

  function buildDetail() {
    const d = D.d, m = d.meta;
    const main = `
    <button type="button" class="btn btn-sm btn-glow btn-glow-md pr-back" id="pr-back">${CHEV_L}<span>Back</span></button>
    <header class="pr-head">
      <div class="pr-titlerow">
        <button type="button" class="icon-btn pr-starbtn" id="pr-star" aria-pressed="${m.starred}" aria-label="Star" title="Star">${m.starred ? "★" : "☆"}</button>
        <input class="pr-titlein" id="pr-title" value="${esc(d.title)}" aria-label="Title" placeholder="Title">
      </div>
      <div class="pr-sub">${cfg.sub(d)}</div>
      <div class="pr-tagrow">
        <label class="pl-label" for="pr-tags">Tags (comma separated)</label>
        <span class="srch"><input class="pl-input" id="pr-tags" data-tags placeholder="Add tags, separated by commas" value="${esc(m.tags.join(", "))}"><kbd class="kbd" data-hk="tags" aria-hidden="true">${esc(keyLabel(hotkey("tags")))}</kbd></span>
      </div>
      ${x?.head?.(d) ?? ""}
    </header>
    <section class="card pr-editor">
      <div class="pr-toolbar" id="pr-toolbar"></div>
      <div class="pr-textwrap" id="pr-body"></div>
    </section>
    ${x?.cards?.(d) ?? ""}
    ${cfg.compact ? "" : `<section class="card pr-notecard">
      <label class="pl-label" for="pr-note">Note</label>
      <textarea class="pl-input pl-area" id="pr-note" rows="3" placeholder="Why it worked, what to change next time">${esc(m.note)}</textarea>
    </section>`}
    <div class="pr-savebar" id="pr-bar"></div>`;
    const side = x?.side?.(d);
    root().innerHTML = side == null ? main : `<div class="pr-layout" id="pr-layout"><div class="pr-main">${main}</div><aside class="pr-side" id="pr-side" aria-label="Side panel">${side}</aside></div>`;
    $("#pr-back").onclick = goBack;
    $("#pr-star").onclick = async (e) => {
      const on = e.currentTarget.getAttribute("aria-pressed") !== "true";
      e.currentTarget.setAttribute("aria-pressed", on); e.currentTarget.textContent = on ? "★" : "☆";
      D.d.meta = await send("PATCH", url(), { starred: on });
    };
    $("#pr-title").addEventListener("input", (e) => { D.titleDirty = e.target.value.trim() !== D.d.title; });
    x?.wire?.(root());
    setCrumb(d.title);
    window.onbeforeunload = () => (dirty() ? "" : undefined);
    renderMode();
  }

  // ---- toolbar, body and bottom bar change with the mode; the head and note fields stay put
  function renderMode() {
    renderToolbar(); renderBody(); renderBar();
  }

  function versionLabel() {
    const revs = D.d.revisions;
    if (!revs.length) return "Original";
    return D.mode === "edit" ? `${revs[0].short} · current` : D.rev.short;
  }

  function renderToolbar() {
    const tb = $("#pr-toolbar"), revs = D.d.revisions;
    if (D.mode === "compare") {
      tb.innerHTML = `<strong class="pr-toolbar-title">Compare to current</strong>
      <div class="pr-toolbar-right">
        <select class="pl-input" id="pr-split" aria-label="Layout"><option value="split"${D.split ? " selected" : ""}>Split</option><option value="uni"${D.split ? "" : " selected"}>Unified</option></select>
        <button type="button" class="icon-btn" id="pr-closecmp" aria-label="Close compare" title="Close">×</button>
      </div>`;
      $("#pr-split").onchange = (e) => { D.split = e.target.value === "split"; renderBody(); };
      $("#pr-closecmp").onclick = () => { D.mode = "edit"; renderMode(); };
      return;
    }
    const items = revs.length ? revs.map((r, i) => `
      <div class="pr-verrow">
        <button type="button" class="pr-ver${(D.mode === "edit" ? i === 0 : D.rev?.hash === r.hash) ? " on" : ""}" data-rev="${r.hash}" data-newest="${i === 0}">
          <code>${r.short}</code><span class="pr-ver-msg">${esc(r.message)}</span><span class="pr-ver-time">${rel(r.ts)}${i === 0 ? " · current" : ""}</span>
        </button>
        <details class="pr-rowmenu">
          <summary class="icon-btn" aria-label="Version actions" title="More">${DOTS}</summary>
          <div class="pr-menu pr-rowpanel">
            <button type="button" class="pr-menuitem" data-delrev="${r.hash}"${i === 0 ? ` disabled title="The current version can't be deleted"` : ""}>${TRASH}<span>Delete this version</span></button>
          </div>
        </details>
      </div>`).join("")
      : `<div class="pr-ver on"><code>original</code><span class="pr-ver-msg">Captured prompt</span><span class="pr-ver-time">${rel(D.d.ts)}</span></div>`;
    tb.innerHTML = `
    <details class="pr-vers" id="pr-vers">
      <summary class="btn btn-sm btn-glow btn-glow-md">${esc(versionLabel())} ${CHEV_D}</summary>
      <div class="pr-verpanel">${items}</div>
    </details>
    <div class="pr-toolbar-right">
      ${(cfg.tools || []).map((t, i) => `<button type="button" class="btn btn-sm btn-glow btn-glow-md" data-tool="${i}" aria-pressed="${!!t.pressed?.()}" title="${esc(t.title || t.label)}${t.hotkey ? ` (${esc(keyLabel(hotkey(t.hotkey)))})` : ""}">${t.icon || ""}<span>${esc(t.label)}</span>${t.hotkey ? `<kbd class="kbd" data-hk="${t.hotkey}">${esc(keyLabel(hotkey(t.hotkey)))}</kbd>` : ""}</button>`).join("")}
      <button type="button" class="btn btn-sm btn-glow btn-glow-md btn-glow-icon" id="pr-copy" aria-label="Copy prompt" title="Copy">${COPY_ICONS}</button>
      <details class="pr-more" id="pr-more">
        <summary class="btn btn-sm btn-glow btn-glow-md btn-glow-icon" aria-label="More actions" title="More">${DOTS}</summary>
        <div class="pr-menu pr-morepanel">
          ${cfg.actions?.length ? `<span class="pr-menuhead">Actions</span>${cfg.actions.map((a, i) => `<button type="button" class="pr-menuitem" data-action="${i}"><span>${esc(a.label)}</span></button>`).join("")}` : ""}
          <span class="pr-menuhead">Export</span>
          ${Object.entries(EXPORTS).map(([k, f]) => `<button type="button" class="pr-menuitem" data-export="${k}"><span>${f.label} (${f.ext})</span></button>`).join("")}
        </div>
      </details>
    </div>`;
    $("#pr-more").addEventListener("click", (e) => {
      const act = e.target.closest("[data-action]");
      if (act) { $("#pr-more").open = false; cfg.actions[+act.dataset.action].run(D.d); return; }
      const b = e.target.closest("[data-export]"); if (!b) return;
      $("#pr-more").open = false;
      exportPrompt(b.dataset.export);
    });
    tb.querySelectorAll("[data-tool]").forEach((b) => { b.onclick = () => b.setAttribute("aria-pressed", String(!!cfg.tools[+b.dataset.tool].run(D.d))); });
    $("#pr-copy").onclick = (e) => copy(e.currentTarget, D.mode === "edit" ? D.draft : D.rev.text);
    $("#pr-vers").addEventListener("click", async (e) => {
      const del = e.target.closest("[data-delrev]");
      if (del) { if (!del.disabled) deleteVersion(del.dataset.delrev); return; }
      const b = e.target.closest("[data-rev]"); if (!b) return;
      $("#pr-vers").open = false;
      if (b.dataset.newest === "true") { D.mode = "edit"; D.rev = null; renderMode(); return; }
      D.rev = await api(url("revisions", b.dataset.rev));
      D.mode = "view"; renderMode();
    });
  }

  async function deleteVersion(hash) {
    if (!await confirmDialog({ title: "Delete version", message: "Delete this version for good? The current text is not affected.", confirmLabel: "Delete", danger: true })) return;
    try {
      D.d = await api(url("revisions", hash), { method: "DELETE" });
    } catch { toast({ message: "Could not delete this version." }); return; }
    if (D.mode === "view" && D.rev?.hash === hash) { D.mode = "edit"; D.rev = null; renderMode(); } else renderToolbar();
    $("#pr-vers").open = true;   // stay in the picker so several versions can be cleared
    toast({ message: "Version deleted." });
  }

  function renderBody() {
    const body = $("#pr-body");
    if (D.mode === "edit") {
      body.innerHTML = `<textarea class="pl-input pr-text" id="pr-text" spellcheck="false" aria-label="Prompt text" placeholder="Prompt text"></textarea>${cfg.messageDialog
        ? `<div class="pr-foot"><div class="pr-footl"><div class="pr-count muted" id="pr-count"></div><span class="pr-status muted" id="pr-status" role="status"></span></div>
            <div class="pr-footr">${x?.foot?.(D.d) ?? ""}<button type="button" class="btn btn-sm btn-glow btn-glow-md" id="pr-save" title="Save (${esc(keyLabel(hotkey("save")))})">Save<kbd class="kbd">${esc(keyLabel(hotkey("save")))}</kbd></button></div></div>`
        : x?.foot ? `<div class="pr-foot"><div class="pr-count muted" id="pr-count"></div>${x.foot(D.d)}</div>` : `<div class="pr-count muted" id="pr-count"></div>`}`;
      if (cfg.messageDialog) $("#pr-save").onclick = save;   // Studio: Save sits in the footer row, right of the other buttons
      const ta = $("#pr-text");
      ta.value = D.draft;
      const count = () => {
        const words = D.draft.trim() ? D.draft.trim().split(/\s+/).length : 0;
        $("#pr-count").textContent = `${words} words · ${D.draft.length} characters${D.draft !== D.d.text ? " · unsaved changes" : ""}`;
      };
      ta.addEventListener("input", () => { D.draft = ta.value; count(); x?.text?.(D.draft, D.d); });
      if (!cfg.messageDialog) ta.addEventListener("keydown", (e) => { if ((e.metaKey || e.ctrlKey) && e.key === "s") { e.preventDefault(); save(); } });
      count();
    } else if (D.mode === "view") {
      body.innerHTML = `<p class="muted small pr-banner">Viewing an older version. Nothing changes until you edit it as a new version.</p><pre class="pr-view">${esc(D.rev.text)}</pre>`;
    } else {
      renderDiff();
    }
    x?.text?.(D.mode === "edit" ? D.draft : D.mode === "view" ? D.rev.text : D.d.text, D.d);   // the text now on screen, and the saved prompt
  }

  function renderDiff() {
    const df = D.diff;
    if (!df) { $("#pr-body").innerHTML = `<p class="muted">Loading…</p>`; return; }
    $("#pr-body").innerHTML = `<div class="df${D.split ? "" : " uni"}">${diffHtml(df.rows, D.split, `Selected version ${df.a.short}`, "Current")}</div>`;
  }

  function renderBar() {
    const bar = $("#pr-bar");
    bar.hidden = D.mode === "edit" && !!cfg.messageDialog;   // Studio edits with Save in the footer row; the bar is only for older versions and compare
    if (bar.hidden) { bar.innerHTML = ""; return; }
    if (D.mode === "edit") {
      bar.innerHTML = `<input class="pl-input" id="pr-msg" placeholder="Describe what changed…" aria-label="What changed">
      <span class="pr-status muted" id="pr-status" role="status"></span>
      <button type="button" class="btn btn-sm btn-glow btn-glow-md" id="pr-save">Save</button>`;
      $("#pr-save").onclick = save;
      $("#pr-msg").addEventListener("keydown", (e) => { if (e.key === "Enter") save(); });
      return;
    }
    const r = D.rev;
    bar.innerHTML = `<span class="pr-info">${esc(r.short)} · ${stamp(r.ts)} · ${esc(r.message)}</span>
    ${D.mode === "view" ? `<button type="button" class="btn btn-sm btn-glow btn-glow-md" id="pr-cmp">Compare to current</button>` : ""}
    <button type="button" class="btn btn-sm btn-glow btn-glow-md" id="pr-asnew">Edit as new version</button>`;
    if ($("#pr-cmp")) $("#pr-cmp").onclick = async () => {
      D.mode = "compare"; D.diff = null; renderMode();
      D.diff = await api(url("diff") + `?a=${r.hash}`);
      renderDiff();
    };
    $("#pr-asnew").onclick = () => {
      D.draft = r.text; D.mode = "edit"; renderMode();
      setMsg(`Restore ${r.short}`);
      $("#pr-status").textContent = "Loaded into the editor. Save to make it a new version.";
      $("#pr-text").focus();
    };
  }

  /** Put `text` into the editor as an unsaved draft (what Apply in the Assistant does) and pre-fill the "what changed" message.
   *  Never saves: the user reviews it and presses Save. */
  function setDraft(text, message = "", from = "the Assistant") {
    if (!D.d) return;
    Object.assign(D, { draft: text, mode: "edit", rev: null, diff: null });
    renderMode();
    setMsg(message);
    const s = $("#pr-status"); if (s) s.textContent = `Loaded from ${from}. Review it, then press Save.`;
    $("#pr-text")?.focus();
  }

  async function save() {
    if (D.saving || D.asking || !D.d) return;
    if (cfg.messageDialog && D.draft !== D.d.text) {   // a new version: ask what changed first (optional)
      D.asking = true;
      const m = await formDialog({ title: "Save new version", confirmLabel: "Save", html: `<label class="pl-label" for="pr-dlgmsg">Describe what changed (optional)</label><input class="pl-input" id="pr-dlgmsg" value="${esc(D.msg)}" placeholder="What did you change and why?" autocomplete="off">`,
        read: (dlg) => dlg.querySelector("#pr-dlgmsg").value.trim() });
      D.asking = false;
      if (m === null) { $("#pr-text")?.focus(); return; }
      D.msg = m;
    }
    D.saving = true;
    const status = (t) => { const s = $("#pr-status"); if (s) s.textContent = t; };
    status("Saving…");
    try {
      const textChanged = D.draft !== D.d.text;
      const patch = {};
      if (D.titleDirty) patch.title = $("#pr-title").value.trim();
      const tags = parseTags($("#pr-tags").value);
      if (JSON.stringify(tags) !== JSON.stringify(D.d.meta.tags)) patch.tags = tags;
      if (noteNow() !== D.d.meta.note) patch.note = noteNow();
      Object.assign(patch, x?.patch?.(D.d) ?? {});
      if (!textChanged && !Object.keys(patch).length) { status("No changes to save"); return; }
      if (textChanged) await send("PUT", url("text"), { text: D.draft, message: cfg.messageDialog ? D.msg.trim() : $("#pr-msg").value.trim() });
      if (Object.keys(patch).length) await send("PATCH", url(), patch);
      const fresh = await api(url());
      D.d = fresh; D.titleDirty = false; D.note = fresh.meta.note;
      $("#pr-title").value = fresh.title; setCrumb(fresh.title);
      if (textChanged) setMsg("");
      renderToolbar(); renderBody();
      status(textChanged ? `Saved · version ${fresh.revisions[0]?.short ?? ""}` : "Saved");
    } catch (e) {
      status(`Could not save: ${e.message}`);
    } finally {
      D.saving = false;
    }
  }

  return {
    open, dirty, save, setDraft, saved: () => D.d, text: () => D.draft, editing: () => D.mode === "edit" && !!D.d,
    focus: () => $("#pr-text")?.focus(), note: () => D.note, setNote: (t) => { D.note = t; },
    status: (t) => { const s = $("#pr-status"); if (s) s.textContent = t; },
  };
}

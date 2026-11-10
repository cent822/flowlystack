// Linkshell block panel: the right-hand panel that opens when one block is selected on the canvas.
// Status, agent, context switches, and a small text editor with versions and compare for Prompt, Spec and Start blocks; Reference blocks get a file or URL.
// Text is save-based (⌘S, "Describe what changed", a new version); everything else edits the graph through ctx.mutate and autosaves with the canvas.
// A small panel editor rather than editor.js: that one is the whole-page editor of a stored prompt and is left alone (the Library depends on it).
import { api, relTime } from "../api.js";
import { formDialog, confirmDialog } from "../dialog.js";
import { toast } from "../toast.js";
import { esc, send, diffHtml, stamp, DOTS, CHEV_D, copy, COPY_ICONS } from "../editor.js";
import { hotkey, label as keyLabel, matches } from "../hotkeys.js";
import { AGENTS, pickStudio, copyBlock } from "./project.js";
import { attachedBlocks } from "./projects.js";

const ic = (d, s = 16) => `<svg viewBox="0 0 24 24" width="${s}" height="${s}" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${d}</svg>`;
const I = {
  close: `<path d="M6 6l12 12M18 6L6 18"/>`, studio: `<path d="M4 6h16M4 12h10M4 18h7"/>`, down: `<path d="M12 4v11M7 11l5 5 5-5M5 20h14"/>`, up: `<path d="M12 16V5M7 9l5-5 5 5M5 20h14"/>`,
  copy: `<rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V6a2 2 0 0 1 2-2h9"/>`, vars: `<path d="M8 4c-2 0-3 1-3 3v2c0 1-1 3-2 3 1 0 2 2 2 3v2c0 2 1 3 3 3M16 4c2 0 3 1 3 3v2c0 1 1 3 2 3-1 0-2 2-2 3v2c0 2-1 3-3 3"/>`,
  file: `<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5"/>`, link: `<path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1"/>`,
  note: `<path d="M5 4h14v11l-5 5H5z"/><path d="M14 20v-5h5"/><path d="M8.5 8.5h7M8.5 12h4"/>`, ext: `<path d="M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5"/>`, edit: `<path d="M4 20h4L19 9l-4-4L4 16z"/>`, prompt: `<path d="M5 7l5 5-5 5"/><path d="M12 18h7"/>`, spec: `<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5M9 13h6M9 17h6"/>`,
  expand: `<path d="M14 4h6v6M10 20H4v-6M20 4l-7 7M4 20l7-7"/>`,
  reference: `<rect x="3" y="4" width="18" height="16" rx="2.5"/><circle cx="9" cy="10" r="1.6"/><path d="M21 16l-5-5-8 8"/>`, start: `<path d="M5 21V4M5 4h11l-2 4 2 4H5"/>`, note: `<path d="M5 4h14v10l-5 6H5z"/><path d="M14 20v-6h5"/>`,
};
const LABEL = { prompt: "Prompt", spec: "Spec", reference: "Reference", start: "Brief", note: "Note" };
const VERSIONED = ["prompt", "spec"];
const IMG = /\.(png|jpe?g|gif|webp|svg|avif)$/i;
const assetName = (a) => a.replace(/^a-[0-9a-f]{8}-/, "");
const filesOf = (b) => [...new Set([...(b.asset ? [b.asset] : []), ...(b.assets || [])])];   // a Reference keeps a list; older projects had one `asset`
const urlsOf = (b) => [...new Set([...(b.url ? [b.url] : []), ...(b.urls || [])])];
const refKey = (b) => filesOf(b).join(",") + "|" + urlsOf(b).join(",");

/**
 * ctx: { el (the panel element, already in the stage), S(), byId(id), mutate(fn), flush(), pid(), project(), texts (bid -> saved text, shared with the canvas),
 *        status(b), duplicate(id), remove(id), changed() (a block's chips may need a redraw), upload(file) }
 */
export function createPanel(ctx) {
  const el = ctx.el;
  const drafts = {};   // unsaved text per block, kept while the panel moves to another block
  let drawn = "";
  let cur = "", mode = "edit", rev = null, diff = null, vers = null, saving = false, msg = "", shown = "", stText = "";

  const blk = () => ctx.byId(cur);
  const text = () => drafts[cur] ?? ctx.texts[cur] ?? "";
  const dirty = (id = cur) => id in drafts && drafts[id] !== (ctx.texts[id] ?? "");
  const $ = (s) => el.querySelector(s);
  const status = (t) => { stText = t; const s = $("#lkp-status"); if (s) s.textContent = t; };   // kept across redraws, cleared by typing or another block
  const kbd = (n) => `<kbd class="kbd" data-hk="${n}">${esc(keyLabel(hotkey(n)))}</kbd>`;
  const frameTitle = (b) => ctx.S().frames.find((f) => f.id === b.frame)?.title || "";
  const base = () => `linkshell/${ctx.pid()}/blocks/${encodeURIComponent(cur)}`;

  function open(id) {
    const b = ctx.byId(id);
    if (!b) return close();
    if (id === cur && !el.hidden) return;
    if (id !== cur) { cur = id; mode = "edit"; rev = null; diff = null; vers = null; msg = ""; stText = ""; }
    el.hidden = false; el.parentElement.classList.add("lk-haspanel");
    render();
  }
  function close() {
    cur = ""; el.hidden = true; el.innerHTML = ""; el.parentElement?.classList.remove("lk-haspanel");
  }

  // ---- the parts
  function head(b) {
    const v = vers?.[0];
    const meta = [LABEL[b.type], frameTitle(b), VERSIONED.includes(b.type) && v ? "v" + (vers.length) : ""].filter(Boolean).join(" · ");
    return `<header class="lkp-head">
      <span class="lk-tile lk-tile-${b.type}">${ic(I[b.type], 18)}</span>
      <div class="lkp-titlebox"><input class="lkp-title" id="lkp-title" value="${esc(b.title)}" aria-label="Title" ${b.type === "note" ? "hidden" : ""} spellcheck="false"><div class="lkp-meta" id="lkp-meta">${esc(b.type === "note" ? "Sticky note" : meta)}</div></div>
      <details class="pr-more" id="lkp-more"><summary class="icon-btn" aria-label="More" title="More">${DOTS}</summary>
        <div class="pr-menu pr-morepanel"><button type="button" class="pr-menuitem" data-act="dup"><span>Duplicate block</span></button>${b.type === "start" ? "" : `<button type="button" class="pr-menuitem" data-act="del"><span>Delete block</span></button>`}</div></details>
      <button type="button" class="icon-btn" id="lkp-close" aria-label="Close panel" title="Close">${ic(I.close, 16)}</button>
    </header>`;
  }
  function stateRow(b) {
    if (b.type !== "prompt") return "";
    const st = ctx.status(b), seg = ["todo", "done", "skipped"].map((s) => `<button type="button" data-st="${s}" class="${b.status === s ? "on" : ""}">${{ todo: "To do", done: "Done", skipped: "Skipped" }[s]}</button>`).join("");
    const agents = [...new Set([b.agent || "claude", ...AGENTS])];
    return `<section class="lkp-sec"><div class="lkp-row"><div><span class="pl-label">Status</span><div class="seg" role="group" aria-label="Status">${seg}</div></div>
      <div><label class="pl-label" for="lkp-agent">Agent</label><select class="pl-input" id="lkp-agent">${agents.map((a) => `<option${a === (b.agent || "claude") ? " selected" : ""}>${esc(a)}</option>`).join("")}</select></div></div>
      <p class="lkp-hint" id="lkp-ready">${st === "ready" ? "Ready: everything before it is done." : ""}</p></section>`;
  }
  function editor(b) {
    const verd = VERSIONED.includes(b.type), viewing = mode !== "edit";
    const t = viewing ? rev.text : text();
    const list = (vers || []).map((r, i) => `<div class="pr-verrow"><button type="button" class="pr-ver${(mode === "edit" ? i === 0 : rev?.id === r.id) ? " on" : ""}" data-rev="${r.id}" data-newest="${i === 0}"><code>${r.short}</code><span class="pr-ver-msg">${esc(r.message)}</span><span class="pr-ver-time">${relTime(r.ts)}${i === 0 ? " · current" : ""}</span></button>
      <details class="pr-rowmenu"><summary class="icon-btn" aria-label="Version actions" title="More">${DOTS}</summary><div class="pr-menu pr-rowpanel"><button type="button" class="pr-menuitem" data-delrev="${r.id}"${i === 0 ? ` disabled title="The current version can't be deleted"` : ""}><span>Delete this version</span></button></div></details></div>`).join("");
    const bar = mode === "compare"
      ? `<strong class="lkp-cmp">Compare to current</strong><button type="button" class="icon-btn" id="lkp-closecmp" aria-label="Close compare">${ic(I.close, 14)}</button>`
      : `${verd && vers?.length ? `<details class="pr-vers lkp-vers" id="lkp-vers"><summary class="btn btn-sm btn-glow">${esc(mode === "edit" ? vers[0].short : rev.short)} ${CHEV_D}</summary><div class="pr-verpanel">${list}</div></details>` : `<span class="lkp-meta">${verd ? "Not saved yet" : "Current text"}</span>`}
        <span class="lkp-tools">${mode === "edit" ? `<button type="button" class="icon-btn" id="lkp-expand" aria-label="Write in a bigger window" title="Write in a bigger window">${ic(I.expand, 16)}</button>` : ""}</span>`;
    const body = mode === "compare" ? `<div class="lkp-diff">${diff ? `<div class="df uni">${diffHtml(diff.rows, false)}</div>` : `<p class="muted small">Loading…</p>`}</div>`
      : mode === "view" ? `<p class="muted small pr-banner">Viewing an older version. Nothing changes until you edit it as a new version.</p><pre class="pr-view lkp-view">${esc(rev.text)}</pre>`
      : `<textarea class="pl-input lkp-text" id="lkp-text" spellcheck="false" aria-label="${LABEL[b.type]} text" placeholder="${b.type === "start" ? "What are you building, and for whom?" : b.type === "spec" ? "Write the spec: rules, tokens, constraints" : "Write the prompt."}"></textarea>`;
    const foot = mode === "edit" ? `<div class="lkp-count muted" id="lkp-count"></div>` : mode === "view"
      ? `<div class="lkp-count muted">${esc(rev.short)} · ${stamp(rev.ts)}</div><span class="lkp-tools"><button type="button" class="btn btn-sm btn-glow" id="lkp-cmp">Compare to current</button><button type="button" class="btn btn-sm btn-glow" id="lkp-asnew">Edit as new version</button></span>` : "";
    return `<section class="lkp-sec lkp-ed"><div class="lkp-edbar">${bar}</div>${body}<div class="lkp-edfoot">${foot}</div>
      ${b.derived_from?.store === "studio" && mode === "edit" ? `<p class="lkp-hint">Loaded from <a href="#/studio/${esc(b.derived_from.id)}">a Studio prompt</a>.</p>` : ""}</section>`;
  }
  function context(b) {
    if (b.type !== "prompt") return "";
    const rows = attachedBlocks(ctx.S(), b.id).map((s) => `<label class="lkp-ctxrow"><span class="lk-tile lk-tile-${s.type}">${ic(I[s.type], 14)}</span><span class="lkp-ctxname">${esc(s.title)}</span><button type="button" class="set-switch" role="switch" aria-checked="${!(b.context_off || []).includes(s.id)}" data-ctx="${esc(s.id)}" aria-label="Attach ${esc(s.title)}"></button></label>`).join("");
    if (!rows) return "";   // nothing linked in: no section (it only has something to say once a Reference block is linked to this prompt)
    return `<section class="lkp-sec"><span class="pl-label">Context</span>${rows}<p class="lkp-hint">Switched-on context is attached when you copy.</p></section>`;
  }
  const urlRow = (u) => `<div class="lkp-urlrow"><input class="pl-input lkp-weburl" value="${esc(u)}" placeholder="https://" aria-label="Web link" spellcheck="false" autocomplete="off">${u ? `<a class="btn btn-sm btn-glow" href="${esc(u)}" target="_blank" rel="noopener">Open</a>` : `<span class="btn btn-sm btn-glow lkp-ghost" aria-hidden="true">Open</span>`}<button type="button" class="lkp-rm" data-rmurl aria-label="Remove this link" title="Remove">${ic(I.close, 12)}</button></div>`;
  function reference(b) {
    const dir = ctx.project().assets_dir || "", pid = encodeURIComponent(ctx.pid()), fs = filesOf(b), notes = b.file_notes || {};
    const rows = fs.map((a) => {
      const url = `/api/linkshell/${pid}/assets/${encodeURIComponent(a)}`, path = dir ? dir + "/" + a : "";
      return `<div class="lkp-file" data-asset="${esc(a)}">${IMG.test(a) ? `<img class="lkp-img" src="${esc(url)}" alt="${esc(assetName(a))}">` : `<div class="lkp-doc">${ic(I.file, 28)}</div>`}
        <div class="lkp-fname"><span>${esc(assetName(a))}</span><span class="lkp-fact"><button type="button" class="lkp-rm" data-rename="${esc(a)}" aria-label="Rename ${esc(assetName(a))}" title="Rename (a shorter name makes a shorter path)">${ic(I.edit, 12)}</button><button type="button" class="lkp-rm${notes[a] ? " has-note" : ""}" data-note="${esc(a)}" aria-label="Note for ${esc(assetName(a))}" title="${notes[a] ? "Edit the note for this file" : "Write a note or spec for this file"}">${ic(I.note, 12)}</button><a class="lkp-rm" href="${esc(url)}" target="_blank" rel="noopener" aria-label="Open ${esc(assetName(a))} in a new tab" title="Open in a new tab">${ic(I.ext, 12)}</a><button type="button" class="lkp-rm" data-rm="${esc(a)}" aria-label="Remove ${esc(assetName(a))}" title="Remove">${ic(I.close, 12)}</button></span></div>
        ${notes[a] ? `<p class="lkp-notepeek" data-note="${esc(a)}" title="Edit the note">${esc(notes[a])}</p>` : ""}
        ${path ? `<div class="lkp-urlrow"><input class="pl-input lkp-path" readonly value="${esc(path)}" aria-label="Full path of ${esc(assetName(a))}" spellcheck="false"><button type="button" class="btn btn-sm btn-glow btn-glow-md btn-glow-icon" data-cp="${esc(path)}" title="Copy the full path">${COPY_ICONS}</button></div>` : ""}</div>`;
    }).join("");
    return `<section class="lkp-sec"><span class="pl-label">Files</span>${rows || `<p class="lkp-hint">No file yet. Files are copied into the project, so it stays self-contained.</p>`}
      <div class="lkp-btns"><button type="button" class="btn btn-sm btn-glow btn-glow-md" id="lkp-up">${ic(I.up, 14)}<span>${fs.length ? "Add more files" : "Choose files"}</span></button><input type="file" id="lkp-file" multiple hidden></div>
      ${fs.length ? `<p class="lkp-hint">Each file's full path is its link: Copy puts these paths in the prompt, and an agent opens the file from there.</p>` : ""}
      <div class="lkp-linkhead lkp-gap"><span class="pl-label">Web links</span><button type="button" class="icon-btn" id="lkp-addurl" aria-label="Add a web link" title="Add a web link">${ic(`<path d="M12 5v14M5 12h14"/>`, 16)}</button></div>
      <div id="lkp-urls">${(urlsOf(b).length ? urlsOf(b) : [""]).map(urlRow).join("")}</div>
      <p class="lkp-hint">When a Prompt block uses this Reference as context, Copy adds the files' full paths and the web links, one per line.</p></section>`;
  }
  function note(b) {
    return `<section class="lkp-sec"><label class="pl-label" for="lkp-note">Sticky note</label><textarea class="pl-input lkp-text" id="lkp-note" rows="6" spellcheck="false">${esc(b.title)}</textarea><p class="lkp-hint">A free note on the canvas. It is not part of any prompt and has no versions.</p></section>`;
  }
  function foot(b) {
    const saveable = b.type !== "note" && b.type !== "reference";
    const studio = [b.type === "prompt" ? `<button type="button" class="btn btn-sm btn-glow btn-glow-md" id="lkp-studio" title="Load a Studio prompt into this block">${ic(I.down, 14)}<span>From Studio</span></button>` : "",
      VERSIONED.includes(b.type) ? `<button type="button" class="btn btn-sm btn-glow btn-glow-md" id="lkp-tostudio" title="Save this text to Prompt Studio">${ic(I.up, 14)}<span>Save to Studio</span></button>` : ""].join("");
    return `<footer class="lkp-foot">${studio ? `<div class="lkp-studiorow">${studio}</div>` : ""}
      <div class="lkp-footrow"><span class="lkp-status muted" id="lkp-status" role="status"></span>
      <div class="lkp-footr">${b.type === "prompt" ? `<button type="button" class="btn btn-sm btn-glow btn-glow-md" id="lkp-copy" data-hotkey="lscopy" title="Copy the prompt with its context (${esc(keyLabel(hotkey("lscopy")))})">${COPY_ICONS}<span>Copy</span>${kbd("lscopy")}</button>` : ""}${b.type === "reference" ? `<button type="button" class="btn btn-sm btn-glow btn-glow-md" id="lkp-done" data-hotkey="paneldone" title="Close this panel (${esc(keyLabel(hotkey("paneldone")))})">Done${kbd("paneldone")}</button>` : ""}${saveable && mode === "edit" ? `<button type="button" class="btn btn-sm btn-glow btn-glow-md" id="lkp-save" title="Save (${esc(keyLabel(hotkey("save")))})">Save${kbd("save")}</button>` : ""}</div></div></footer>`;
  }

  // ---- build and wire
  async function loadVersions() {
    const id = cur, b = blk();
    if (!b || !VERSIONED.includes(b.type)) return;
    try { const r = await api(`${base()}/revisions`); if (id !== cur) return; vers = r.revisions; } catch { vers = []; }
    if (id === cur && mode === "edit") render(true);
  }
  let noteSig = "";   // the Reference notes as last drawn, so a change from outside the panel (Undo) redraws the file list
  function render(keepFocus = false) {
    const b = blk();
    if (!b) return close();
    const had = keepFocus ? document.activeElement?.id : "";
    const pos = keepFocus ? $("#lkp-text")?.selectionStart : null;
    const keep = $(".lkp-body"), sc = keep && drawn === cur ? keep.scrollTop : 0;   // a redraw of the same block keeps its scroll place
    el.innerHTML = head(b) + `<div class="lkp-body">${stateRow(b)}${b.type === "note" ? note(b) : b.type === "reference" ? reference(b) : editor(b)}${context(b)}</div>` + foot(b);
    if (sc) $(".lkp-body").scrollTop = sc;
    drawn = cur; noteSig = JSON.stringify(b.file_notes || {});
    if (vers === null && VERSIONED.includes(b.type)) { vers = []; loadVersions(); }
    const ta = $("#lkp-text");
    if (ta) {
      ta.value = text();
      const count = () => { const t = ta.value, w = t.trim() ? t.trim().split(/\s+/).length : 0; $("#lkp-count").textContent = `${w} words · ${t.length} chars${dirty() ? " · unsaved" : ""}`; };
      ta.addEventListener("input", () => { drafts[cur] = ta.value; if (stText) status(""); count(); });
      count();
      if (had === "lkp-text") { ta.focus(); if (pos != null) ta.setSelectionRange(pos, pos); }
    }
    if (stText) $("#lkp-status").textContent = stText;
    shown = b.type === "reference" ? refKey(b) : "";
    wire(b);
  }
  function wire(b) {
    $("#lkp-close").onclick = () => ctx.deselect();
    $("#lkp-expand")?.addEventListener("click", () => expandText(b));
    $("#lkp-more").addEventListener("click", (e) => {
      const a = e.target.closest("[data-act]"); if (!a) return;
      $("#lkp-more").open = false;
      if (a.dataset.act === "dup") ctx.duplicate(cur); else ctx.remove(cur);
    });
    const t = $("#lkp-title");
    t.onchange = () => { const v = t.value.trim(); if (v && v !== b.title) ctx.mutate(() => { b.title = v; }); else t.value = b.title; };
    t.onkeydown = (e) => { if (e.key === "Enter") { e.preventDefault(); t.blur(); } };
    el.querySelectorAll("[data-st]").forEach((x) => { x.onclick = () => { if (b.status !== x.dataset.st) ctx.mutate(() => { b.status = x.dataset.st; }); }; });
    const ag = $("#lkp-agent"); if (ag) ag.onchange = () => ctx.mutate(() => { b.agent = ag.value; });
    el.querySelectorAll("[data-ctx]").forEach((s) => {
      s.onclick = () => {
        const id = s.dataset.ctx, off = new Set(b.context_off || []);
        off.has(id) ? off.delete(id) : off.add(id);
        ctx.mutate(() => { b.context_off = [...off]; });
        s.setAttribute("aria-checked", String(!off.has(id)));
      };
    });
    const nt = $("#lkp-note"); if (nt) nt.onchange = () => { const v = nt.value.trim(); if (v !== b.title) ctx.mutate(() => { b.title = v || "Sticky note"; }); };
    if (b.type === "reference") wireReference(b);
    if (b.type === "note" || b.type === "reference") { wireFoot(b); return; }
    $("#lkp-vers")?.addEventListener("click", async (e) => {
      const del = e.target.closest("[data-delrev]");
      if (del) { if (!del.disabled) deleteVersion(del.dataset.delrev); return; }
      const r = e.target.closest("[data-rev]"); if (!r) return;
      $("#lkp-vers").open = false;
      if (r.dataset.newest === "true") { mode = "edit"; rev = null; render(); return; }
      rev = await api(`${base()}/revisions/${r.dataset.rev}`); rev = { ...rev, short: rev.id.slice(0, 7) }; mode = "view"; render();
    });
    $("#lkp-cmp")?.addEventListener("click", async () => {
      mode = "compare"; diff = null; render();
      try { diff = await api(`${base()}/diff?a=${rev.id}`); } catch { diff = { rows: [] }; }
      if (mode === "compare") render();
    });
    $("#lkp-closecmp")?.addEventListener("click", () => { mode = "view"; render(); });
    $("#lkp-asnew")?.addEventListener("click", () => { drafts[cur] = rev.text; msg = `Restore ${rev.short}`; mode = "edit"; rev = null; render(); status("Loaded into the editor. Save to make it a new version."); $("#lkp-text").focus(); });
    $("#lkp-studio")?.addEventListener("click", fromStudio);
    wireFoot(b);
  }
  function wireFoot(b) {
    $("#lkp-done")?.addEventListener("click", () => ctx.deselect());
    $("#lkp-save")?.addEventListener("click", save);
    $("#lkp-copy")?.addEventListener("click", async (e) => {
      const btn = e.currentTarget, was = dirty();
      await ctx.flush();   // context switches are part of the graph, which autosaves a moment after a change: copy what is on screen
      if (await copyBlock(btn, ctx.pid(), cur) && was) status("Copied the saved text. Unsaved edits are not included.");
    });
    $("#lkp-tostudio")?.addEventListener("click", async () => {
      if (dirty()) return status("Save the text first, then save it to Studio.");
      if (!(ctx.texts[cur] || "").trim()) return status("Write some text first.");
      try {
        const d = await send("POST", `${base()}/to-studio`, {});
        toast({ message: "Saved to Prompt Studio.", action: "Open", onAction: () => { location.hash = "#/studio/" + d.id; }, ms: 6000 });
      } catch (e) { toast({ message: "Could not save to Studio: " + e.message }); }
    });
  }
  function wireReference(b) {
    const file = $("#lkp-file");
    $("#lkp-up").onclick = () => file.click();
    file.onchange = async () => {
      const list = [...file.files]; if (!list.length) return;
      const added = [];
      for (const [i, f] of list.entries()) {
        status(list.length > 1 ? `Uploading ${i + 1} of ${list.length}…` : "Uploading…");
        try { added.push(await ctx.upload(f)); } catch (e) { status(`Could not upload ${f.name}: ${e.message}`); }
      }
      file.value = "";
      if (!added.length) return;
      ctx.mutate(() => { const all = [...filesOf(b), ...added]; delete b.asset; b.assets = all; });
      status(`Added ${added.length} file${added.length === 1 ? "" : "s"}`);
    };
    el.querySelectorAll("[data-rm]").forEach((x) => { x.onclick = () => ctx.mutate(() => { const all = filesOf(b).filter((a) => a !== x.dataset.rm); delete b.asset; if (all.length) b.assets = all; else delete b.assets; if (b.file_notes) { delete b.file_notes[x.dataset.rm]; if (!Object.keys(b.file_notes).length) delete b.file_notes; } }); });
    el.querySelectorAll("[data-rename]").forEach((x) => { x.onclick = () => renameFile(x.dataset.rename); });
    el.querySelectorAll("[data-note]").forEach((x) => { x.onclick = () => editNote(b, x.dataset.note); });
    el.querySelectorAll("[data-cp]").forEach((x) => { x.onclick = () => copy(x, x.dataset.cp); });
    el.querySelectorAll(".lkp-path").forEach((x) => { x.onfocus = () => x.select(); });
    const box = $("#lkp-urls");
    const focusRow = (inp) => { inp.focus({ preventScroll: true }); const body = $(".lkp-body"); body.scrollTop = body.scrollHeight; };   // the links are the last section: scroll to the very end, so the row, its padding and the hint under it are all in view
    const commit = (drop = false) => {   // every link field is read together: blanks and repeats drop out; a bad one is refused (or left out when a row was removed)
      let vals = [...box.querySelectorAll(".lkp-weburl")].map((i) => i.value.trim()).filter(Boolean);
      if (vals.some((v) => !/^https?:\/\//i.test(v))) { if (!drop) return status("A link starts with http:// or https://"); vals = vals.filter((v) => /^https?:\/\//i.test(v)); }
      const all = [...new Set(vals)];
      if (all.join("\n") === urlsOf(b).join("\n")) return;
      ctx.mutate(() => { delete b.url; if (all.length) b.urls = all; else delete b.urls; });
    };
    box.addEventListener("change", (e) => { if (e.target.matches(".lkp-weburl")) commit(); });
    box.addEventListener("keydown", (e) => {   // Enter saves this link and opens the next empty row right there, so links can be typed one after another
      if (e.key !== "Enter" || !e.target.matches(".lkp-weburl")) return;
      e.preventDefault();
      const v = e.target.value.trim();
      if (!v) return;
      commit();
      if (!/^https?:\/\//i.test(v)) return;   // a bad link stays where it is, with its message
      const now = $("#lkp-urls");
      let next = [...now.querySelectorAll(".lkp-weburl")].find((x) => !x.value.trim());
      if (!next) { now.insertAdjacentHTML("beforeend", urlRow("")); next = now.lastElementChild.querySelector("input"); }
      focusRow(next);
    });
    box.addEventListener("click", (e) => { const x = e.target.closest("[data-rmurl]"); if (!x) return; x.closest(".lkp-urlrow").remove(); if (!box.children.length) box.insertAdjacentHTML("beforeend", urlRow("")); commit(true); });
    $("#lkp-addurl").onclick = () => { const empty = [...box.querySelectorAll(".lkp-weburl")].find((i) => !i.value.trim()); if (empty) return empty.focus(); box.insertAdjacentHTML("beforeend", urlRow("")); focusRow(box.lastElementChild.querySelector("input")); };
  }

  /** The note for one file of a Reference block: a big dialog with the picture on the left and the writing space on the right.
   *  Done (or Cmd/Ctrl+Enter) saves it with the project; Cancel, Esc and a click outside keep the old note. An empty note removes it. */
  async function editNote(b, a) {
    const name = assetName(a), url = `/api/linkshell/${encodeURIComponent(ctx.pid())}/assets/${encodeURIComponent(a)}`, old = b.file_notes?.[a] || "";
    const v = await formDialog({ title: `Note · ${name}`, confirmLabel: "Done", confirmKbd: "⌘↵",
      html: `<div class="cn-img">${IMG.test(a) ? `<img src="${esc(url)}" alt="${esc(name)}" title="Click to show at full size">` : `<div class="lkp-doc">${ic(I.file, 48)}<span>${esc(name)}</span></div>`}</div>
        <div class="cn-ed"><label class="pl-label" for="cn-t">Spec or note for this file</label>
        <textarea class="pl-input" id="cn-t" spellcheck="false" placeholder="What should an agent take from this file? Layout, spacing, colours, what to copy, what to ignore…">${esc(old)}</textarea>
        <div class="cn-meta"><span id="cn-c"></span><span>Copy adds it under this file</span></div></div>`,
      read: (d) => d.querySelector("#cn-t").value.trim().slice(0, 20000),
      onOpen: (d) => {
        d.classList.add("cb-note-dlg");
        d.querySelector(".btn-primary")?.classList.replace("btn-primary", "btn-glow");   // Done and Cancel are Glow buttons like everything else: no fill, the ring and glow come on hover
        d.querySelectorAll(".cb-dialog-actions .btn").forEach((x) => x.classList.add("btn-glow", "btn-glow-md"));
        const t = d.querySelector("#cn-t"), c = d.querySelector("#cn-c"), u = () => { const w = t.value.trim() ? t.value.trim().split(/\s+/).length : 0; c.textContent = `${w} words · ${t.value.length} characters`; };
        t.addEventListener("input", u); u();
        d.querySelector(".cn-img img")?.addEventListener("click", (e) => e.target.classList.toggle("full"));
        t.setSelectionRange(t.value.length, t.value.length);
      } });
    const back = document.activeElement; if (back?.matches?.("[data-note]")) back.blur();   // the dialog gives focus back to the Note button; with the keyboard that would leave a ring on it until the next click
    if (v === null || v === old) return;
    ctx.mutate(() => { if (v) (b.file_notes ||= {})[a] = v; else if (b.file_notes) { delete b.file_notes[a]; if (!Object.keys(b.file_notes).length) delete b.file_notes; } });
    status(v ? "Note saved" : "Note removed");
  }

  /** The text of a Prompt, Spec or Brief in a big dialog, for a long writing session. The panel (and the canvas behind it) is the normal place to
   *  write; this is the optional extra room. Done (or Cmd/Ctrl+Enter) puts the text back in the panel as an unsaved draft: saving stays the panel's
   *  Save, with its "describe what changed" step. Cancel, Esc and a click outside keep the panel's text as it was. */
  async function expandText(b) {
    const ta = $("#lkp-text"); if (!ta) return;
    const v = await formDialog({ title: `${LABEL[b.type]} · ${b.title || "Untitled"}`, confirmLabel: "Done", confirmKbd: "⌘↵",
      html: `<div class="cx-ed"><textarea class="pl-input" id="cx-t" spellcheck="false" aria-label="${LABEL[b.type]} text"></textarea>
        <div class="cn-meta"><span id="cx-c"></span><span>Done puts the text back in the panel. Press Save there to keep it as a new version.</span></div></div>`,
      read: (d) => d.querySelector("#cx-t").value,
      onOpen: (d) => {
        d.classList.add("cb-text-dlg");
        d.querySelector(".btn-primary")?.classList.replace("btn-primary", "btn-glow");   // Done and Cancel are Glow buttons like everything else
        d.querySelectorAll(".cb-dialog-actions .btn").forEach((x) => x.classList.add("btn-glow", "btn-glow-md"));
        const t = d.querySelector("#cx-t"), c = d.querySelector("#cx-c"), u = () => { const w = t.value.trim() ? t.value.trim().split(/\s+/).length : 0; c.textContent = `${w} words · ${t.value.length} characters`; };
        t.value = ta.value; t.addEventListener("input", u); u();
        t.setSelectionRange(ta.selectionStart ?? t.value.length, ta.selectionEnd ?? t.value.length);
      } });
    if (v === null || !ta.isConnected) return;
    ta.value = v;
    ta.dispatchEvent(new Event("input"));   // the panel's own handler keeps the draft and the word count
    ta.focus();
  }

  /** Rename an uploaded file: the server renames it on disk, then every block that lists it switches to the new name. */
  async function renameFile(a) {
    const full = assetName(a), ext = full.includes(".") ? "." + full.split(".").pop() : "", stem = ext ? full.slice(0, -ext.length) : full;
    const v = await formDialog({ title: "Rename file", confirmLabel: "Rename", html: `<label class="pl-label" for="lkp-rn">New name (${esc(ext || "no extension")} is kept)</label><input class="pl-input" id="lkp-rn" value="${esc(stem)}" autocomplete="off" spellcheck="false">`,
      validate: (d) => (d.querySelector("#lkp-rn").value.trim() ? "" : "Give the file a name."), read: (d) => d.querySelector("#lkp-rn").value.trim() });
    if (!v || v === stem) return;
    try {
      const r = await send("POST", `linkshell/${ctx.pid()}/assets/${encodeURIComponent(a)}/rename`, { name: /\.[A-Za-z0-9]+$/.test(v) ? v : v + ext });
      ctx.mutate(() => { ctx.S().blocks.forEach((o) => { const fs = filesOf(o); if (fs.includes(a)) { delete o.asset; o.assets = fs.map((f) => (f === a ? r.asset : f)); if (o.file_notes?.[a] !== undefined) { o.file_notes[r.asset] = o.file_notes[a]; delete o.file_notes[a]; } } }); });
      status("Renamed");
    } catch (e) { status(`Could not rename: ${e.message}`); }
  }

  async function deleteVersion(id) {
    if (!await confirmDialog({ title: "Delete version", message: "Delete this version for good? The current text is not affected.", confirmLabel: "Delete", danger: true })) return;
    try { await api(`${base()}/revisions/${id}`, { method: "DELETE" }); } catch { return toast({ message: "Could not delete this version." }); }
    vers = null; if (rev?.id === id) { mode = "edit"; rev = null; }
    render(); toast({ message: "Version deleted." });
  }

  async function fromStudio() {
    const b = blk();
    if (dirty() && !await confirmDialog({ title: "Replace your edits?", message: "The editor has unsaved changes. Loading a Studio prompt puts its text in their place (still unsaved, until you press Save).", confirmLabel: "Load", danger: true })) return;
    const p = await pickStudio();
    if (!p || cur !== b.id) return;
    drafts[cur] = p.text; mode = "edit"; rev = null;
    ctx.mutate(() => { b.derived_from = { store: "studio", id: p.id }; });
    render(); status("Loaded from Studio. Review it, then press Save."); $("#lkp-text")?.focus();
  }

  async function save() {
    const b = blk();
    if (!b || saving || mode !== "edit" || !dirty()) { if (b && !dirty()) status("No changes to save"); return; }
    const id = cur, t = drafts[id];
    let message = "";
    if (VERSIONED.includes(b.type)) {   // a new version: ask what changed first (optional), like Studio
      const m = await formDialog({ title: "Save new version", confirmLabel: "Save", html: `<label class="pl-label" for="lkp-dlgmsg">Describe what changed (optional)</label><input class="pl-input" id="lkp-dlgmsg" value="${esc(msg)}" placeholder="What did you change and why?" autocomplete="off">`, read: (d) => d.querySelector("#lkp-dlgmsg").value.trim() });
      if (m === null) return void $("#lkp-text")?.focus();
      message = m;
    }
    saving = true; status("Saving…");
    try {
      await ctx.flush();   // a block added a moment ago must exist on the server before its text can be saved
      await send("PUT", `linkshell/${ctx.pid()}/blocks/${encodeURIComponent(id)}/text`, { text: t, message });
      ctx.texts[id] = t; delete drafts[id]; msg = "";
      if (id === cur) { vers = null; render(); status(VERSIONED.includes(b.type) ? "Saved as a new version" : "Saved"); }
      ctx.changed();
    } catch (e) { status(`Could not save: ${e.message}`); } finally { saving = false; }
  }

  // ---- keys that belong to the panel: Save; Esc leaves the field, then closes
  el.addEventListener("keydown", (e) => {
    if (document.querySelector("dialog[open]")) return;
    if (matches(e, "save")) { e.preventDefault(); save(); return; }
    if (e.key === "Escape" && !el.querySelector("details[open]")) {
      e.stopPropagation();
      if (/^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName)) { e.target.blur(); ctx.focusCanvas(); } else ctx.deselect();
    }
  });

  /** Called after any canvas change: keep the header, status and context rows current without touching the text box. */
  function refresh() {
    const b = blk();
    if (!b) { if (cur) close(); return; }
    if (el.hidden) return;
    if (b.type === "reference" && JSON.stringify(b.file_notes || {}) !== noteSig) { render(); return; }   // a note was written, removed or undone: redraw the file list
    const t = $("#lkp-title");
    if (t && document.activeElement !== t) t.value = b.title;
    const nt = $("#lkp-note"); if (nt && document.activeElement !== nt) nt.value = b.title;
    el.querySelectorAll("[data-st]").forEach((x) => x.classList.toggle("on", x.dataset.st === b.status));
    const r = $("#lkp-ready"); if (r) { const st = ctx.status(b); r.textContent = st === "ready" ? "Ready: everything before it is done." : ""; }
    const ta = $("#lkp-text");
    if (ta && mode === "edit" && document.activeElement !== ta && ta.value !== text()) { vers = null; render(); return; }   // the text arrived or changed behind the panel (a duplicate, a Studio block)
    const rows = el.querySelectorAll("[data-ctx]").length, want = b.type === "prompt" ? attachedBlocks(ctx.S(), b.id).length : 0;
    const asset = b.type === "reference" ? refKey(b) : "";
    if (rows !== want || asset !== shown) render(document.activeElement?.id === "lkp-text");   // a link was added or removed, or the file changed
  }

  return { open, close, refresh, dirty: () => Object.keys(drafts).some((id) => dirty(id)), isOpen: () => !el.hidden, current: () => cur, focusTitle: () => { const t = $("#lkp-title"); if (t && !t.hidden) { t.focus(); t.select(); } else $("#lkp-note")?.focus(); }, reset: () => { for (const k of Object.keys(drafts)) delete drafts[k]; cur = ""; vers = null; close(); } };
}

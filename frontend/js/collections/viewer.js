// The document viewer (#/collections/<id>/documents/<doc>): the collection's files on the left, one document on the
// right with Preview and Indexed text. Read-only here; Edit comes in phase 3. Nothing is sent anywhere: the text is read from the stored file.
import { confirmDialog } from "../dialog.js";
import { toast } from "../toast.js";
import { api, esc, ic, I, plural, sizeText } from "./common.js";

const $ = (s) => document.querySelector(s);
const S = { box: null, c: null, docs: [], id: "", tab: "preview", ticket: 0, q: "", cur: null, passages: null, edit: false, draft: "", err: "", saving: false, poll: 0, nameDraft: "" };
const nameVal = () => String(S.nameDraft ?? "").replace(/\s+/g, " ").trim();   // the title field while editing: a change to it is part of the edit
const nameDirty = () => nameVal() !== "" && nameVal() !== S.cur?.name;
const dirty = () => S.edit && (S.draft !== (S.cur?.text ?? "") || nameDirty());
const canSave = () => dirty() && nameVal() !== "" && !S.saving;
const STATE = { waiting: "waiting to index", reading: "reading", indexing: "indexing", failed: "could not be read" };

export const docFromHash = () => decodeURIComponent((location.hash.replace(/^#\/collections\/?/, "").split("?")[0].split("/")[2]) || "");
export function unmountViewer() {
  S.ticket++; S.box = null; S.edit = false; clearTimeout(S.poll);
  window.onbeforeunload = null; document.removeEventListener("click", guardLinks, true);
}

/** Leaving with an unsaved edit asks first (switching file, Cancel, a link inside the app). A reload asks through the browser's own prompt. */
async function leave() {
  if (!dirty()) return true;
  const ok = await confirmDialog({ title: "Discard your changes?", message: `The edit to “${S.cur.name}” has not been saved.`, confirmLabel: "Discard", cancelLabel: "Keep editing", danger: true });
  if (ok) { S.edit = false; S.draft = ""; guard(); }
  return ok;
}
function guard() { window.onbeforeunload = dirty() ? () => "" : null; }
async function guardLinks(e) {
  const a = e.target.closest?.('a[href^="#"]');
  if (!a || !dirty()) return;
  e.preventDefault(); e.stopPropagation();
  if (await leave()) location.hash = a.getAttribute("href");
}

// ---------- a small, safe Markdown renderer ----------
// Everything is escaped first; only the tags below are ever produced, and a link is kept only when it is http(s). Nothing from the file can become HTML.
const inline = (t) => {
  const codes = [];
  let s = esc(t).replace(/`([^`]+)`/g, (m, c) => { codes.push(c); return `\u0000${codes.length - 1}\u0000`; });
  s = s.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, (m, a, u) => `<a href="${u}" target="_blank" rel="noopener noreferrer">${a}</a>`)
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>").replace(/(^|[\s(])\*([^*\s][^*]*)\*(?=$|[\s).,;:!?])/g, "$1<em>$2</em>");
  return s.replace(/\u0000(\d+)\u0000/g, (m, i) => `<code>${codes[+i]}</code>`);
};
export function markdown(src) {
  const L = src.replace(/\r\n?/g, "\n").split("\n"), out = [];
  let i = 0;
  const cells = (l) => l.trim().replace(/^\||\|$/g, "").split("|").map((c) => c.trim());
  while (i < L.length) {
    const l = L[i];
    if (/^\s*```/.test(l)) {
      const code = []; i++;
      while (i < L.length && !/^\s*```/.test(L[i])) code.push(L[i++]);
      i++; out.push(`<pre><code>${esc(code.join("\n"))}</code></pre>`); continue;
    }
    const h = /^(#{1,6})\s+(.*)$/.exec(l);
    if (h) { out.push(`<h${h[1].length}>${inline(h[2])}</h${h[1].length}>`); i++; continue; }
    if (/^\s*([-*_])(\s*\1){2,}\s*$/.test(l)) { out.push("<hr>"); i++; continue; }
    if (/^\s*\|/.test(l) && /^\s*\|?\s*:?-{2,}/.test(L[i + 1] || "")) {
      const head = cells(l), rows = []; i += 2;
      while (i < L.length && /^\s*\|/.test(L[i])) rows.push(cells(L[i++]));
      out.push(`<div class="co-tblwrap"><table><thead><tr>${head.map((c) => `<th>${inline(c)}</th>`).join("")}</tr></thead><tbody>${rows.map((r) => `<tr>${r.map((c) => `<td>${inline(c)}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`); continue;
    }
    if (/^\s*>/.test(l)) { const q = []; while (i < L.length && /^\s*>/.test(L[i])) q.push(L[i++].replace(/^\s*>\s?/, "")); out.push(`<blockquote>${inline(q.join(" "))}</blockquote>`); continue; }
    const li = /^\s*([-*+]|\d+[.)])\s+(.*)$/.exec(l);
    if (li) {
      const ord = /\d/.test(li[1]), items = [];
      while (i < L.length) {
        const m = /^\s*([-*+]|\d+[.)])\s+(.*)$/.exec(L[i]);
        if (m && /\d/.test(m[1]) === ord) { items.push(m[2]); i++; }
        else if (m || !/^\s{2,}\S/.test(L[i])) break;   // an indented line continues the item above
        else items[items.length - 1] += " " + L[i++].trim();
      }
      out.push(`<${ord ? "ol" : "ul"}>${items.map((t) => `<li>${inline(t)}</li>`).join("")}</${ord ? "ol" : "ul"}>`); continue;
    }
    if (!l.trim()) { i++; continue; }
    const p = [];
    while (i < L.length && L[i].trim() && !/^\s*(```|#{1,6}\s|>|([-*+]|\d+[.)])\s)/.test(L[i]) && !/^\s*\|/.test(L[i])) p.push(L[i++].trim());
    if (!p.length) p.push(L[i++].trim());   // a line that starts like a block but is not one: never loop
    out.push(`<p>${inline(p.join(" "))}</p>`);
  }
  return out.join("");
}

// ---------- the page ----------
export async function mountViewer(box, c, docId) {
  Object.assign(S, { box, c, id: docId, tab: "preview", q: "", cur: null, passages: null, docs: [], edit: false, draft: "", err: "", saving: false });
  document.addEventListener("click", guardLinks, true);
  const my = ++S.ticket, base = `#/collections/${encodeURIComponent(c.id)}/documents`;
  box.innerHTML = `<div class="co-view">
    <aside class="co-vlist" aria-label="Documents in this collection">
      <a class="btn btn-sm btn-glow btn-glow-md co-vback" href="${base}">${ic(I.back)}<span>All documents</span></a>
      <input type="search" class="pl-input co-vsearch" id="co-vq" placeholder="Search documents" aria-label="Search documents by name" autocomplete="off">
      <ul class="co-vfiles" id="co-vfiles"></ul>
    </aside>
    <section class="co-vmain" id="co-vmain" aria-live="polite"><p class="muted pr-empty">Loading…</p></section></div>`;
  try { S.docs = (await api(`collections/${c.id}/documents`)).items; } catch { if (my === S.ticket) $("#co-vmain").innerHTML = `<p class="muted pr-empty">Could not load. Is the server running?</p>`; return; }
  if (my !== S.ticket) return;
  files();
  $("#co-vq").addEventListener("input", (e) => { S.q = e.target.value.trim().toLowerCase(); files(); });
  $("#co-vfiles").addEventListener("click", async (e) => { const b = e.target.closest("[data-doc]"); if (b && b.dataset.doc !== S.id && await leave()) open(b.dataset.doc); });
  $("#co-vmain").addEventListener("click", async (e) => {
    const t = e.target.closest("[data-vt]");
    if (t && t.dataset.vt === "edit") { if (S.cur?.editable && !S.edit) { S.edit = true; S.draft = S.cur.text; S.nameDraft = S.cur.name; S.err = ""; S.tab = "edit"; main(); } }
    else if (t && t.dataset.vt !== S.tab) { S.tab = t.dataset.vt; main(); }
    else if (e.target.closest("[data-vcancel]")) { if (await leave() || !dirty()) { S.edit = false; S.draft = ""; S.err = ""; S.tab = "preview"; guard(); main(); } }
    else if (e.target.closest("[data-vsave]")) save();
    else if (e.target.closest("[data-vreload]")) reload();
  });
  if (S.docs.some((d) => d.id === docId)) open(docId, true);
  else $("#co-vmain").innerHTML = `<p class="muted pr-empty">That document is not in this collection. <a href="${base}">Back to the documents</a>.</p>`;
}

function files() {
  const rows = S.docs.filter((d) => !S.q || d.name.toLowerCase().includes(S.q));
  $("#co-vfiles").innerHTML = rows.length ? rows.map((d) => `<li><button type="button" class="co-vfile${d.id === S.id ? " on" : ""}" data-doc="${esc(d.id)}"${d.id === S.id ? ` aria-current="true"` : ""}>
      <span class="co-ico">${ic(I.file, 16)}</span><span class="co-vname">${esc(d.name)}</span><span class="co-vsize">${sizeText(d.size)}</span></button></li>`).join("")
    : `<li class="muted small co-vnone">No document matches.</li>`;
}

async function open(id, first) {
  const my = ++S.ticket;
  clearTimeout(S.poll);
  S.id = id; S.tab = "preview"; S.cur = null; S.passages = null; S.edit = false; S.draft = ""; S.err = ""; guard();
  if (!first) history.replaceState(null, "", `#/collections/${encodeURIComponent(S.c.id)}/documents/${encodeURIComponent(id)}`);   // the router is not asked: only the right side changes
  files();
  $("#co-vmain").innerHTML = `<p class="muted pr-empty">Loading…</p>`;
  try { S.cur = await api(`collections/docs/${id}/text`); } catch (e) { if (my === S.ticket) $("#co-vmain").innerHTML = `<p class="muted pr-empty">Could not read this document: ${esc(e.message)}</p>`; return; }
  if (my !== S.ticket) return;
  main();
}

async function passages() {
  if (S.passages) return S.passages;
  const id = S.id;
  const p = (await api(`collections/docs/${id}/passages`)).items;
  if (id === S.id) S.passages = p;
  return p;
}

function bodyHtml() {
  const d = S.cur, t = d.text || "";
  if (!t.trim()) return `<p class="muted pr-empty">${d.status === "failed" ? "This file could not be read." : "This document has no text."}</p>`;
  if (d.type === "markdown") return `<div class="co-md">${markdown(t)}</div>`;
  if (d.type === "json") { try { return `<pre class="co-raw">${esc(JSON.stringify(JSON.parse(t), null, 2))}</pre>`; } catch { /* shown as it is stored */ } }
  return `<pre class="co-raw">${esc(t)}</pre>`;
}

const metaText = (d) => {
  const others = (d.collections || []).filter((x) => x !== S.c.id).length;
  return [d.type.toUpperCase(), sizeText(d.size), d.status === "ready" ? plural(d.passages, "passage") : STATE[d.status] || d.status, others ? `also in ${plural(others, "other collection")}` : ""].filter(Boolean).join(" · ");
};
const gutter = (t) => Array.from({ length: t.split("\n").length }, (_, i) => i + 1).join("\n");

async function main() {
  const d = S.cur, my = S.ticket;
  if (!d) return;
  const tabs = [["preview", "Preview"], ["indexed", "Indexed text"], ...(d.editable ? [["edit", "Edit"]] : [])];
  $("#co-vmain").innerHTML = `<header class="co-vhead">
      <div class="co-vtitle">${S.edit ? `<input class="co-vname-in" id="co-vname" autocomplete="off" spellcheck="false" maxlength="120" aria-label="Document name" value="${esc(S.nameDraft ?? d.name)}">` : `<h2>${esc(d.name)}</h2>`}<span class="pr-meta" id="co-vmeta">${esc(metaText(d))}</span></div>
      ${S.edit ? `<div class="co-vact"><button type="button" class="btn btn-sm btn-glow btn-glow-md" data-vcancel>Cancel</button><button type="button" class="btn btn-sm btn-glow btn-glow-md" data-vsave id="co-vsave"${canSave() ? "" : " disabled"}>${S.saving ? "Saving…" : "Save"}</button></div>`
        : `<div class="seg co-vseg" role="group" aria-label="Show">${tabs.map(([k, l]) => `<button type="button" class="${S.tab === k ? "on" : ""}" data-vt="${k}" aria-pressed="${S.tab === k}">${l}</button>`).join("")}</div>`}
    </header>
    ${d.editable ? "" : d.reason ? `<p class="co-vnote muted small">${esc(d.reason)}</p>` : ""}
    ${S.err ? `<p class="co-err" role="alert">${esc(S.err)}${S.err.includes("changed") ? ` <button type="button" class="btn btn-sm btn-glow btn-glow-md" data-vreload>Load the new text</button>` : ""}</p>` : ""}
    ${d.status === "failed" && d.error ? `<p class="co-err" id="co-verr">${esc(d.error)}${S.edit ? " Fix the text and save again." : ""}</p>` : ""}
    <div class="co-vbody" id="co-vbody">${S.edit ? `<div class="co-ed"><pre class="co-gut" id="co-gut" aria-hidden="true"></pre><textarea class="co-ta" id="co-ta" spellcheck="false" wrap="off" autocomplete="off" aria-label="Edit ${esc(d.name)}"></textarea></div>` : S.tab === "preview" ? bodyHtml() : `<p class="muted pr-empty">Reading…</p>`}</div>`;
  if (S.edit) { editor(); return; }
  if (S.tab !== "indexed") return;
  let ps;
  try { ps = await passages(); } catch (e) { if (my === S.ticket && $("#co-vbody")) $("#co-vbody").innerHTML = `<p class="muted pr-empty">Could not load: ${esc(e.message)}</p>`; return; }
  if (my !== S.ticket || S.tab !== "indexed" || !$("#co-vbody")) return;
  $("#co-vbody").innerHTML = ps.length ? `<p class="muted small co-vnote">${plural(ps.length, "passage")}: the pieces of this document that search and the model work with.</p>` + ps.map((p) => `<article class="co-pass"><div class="pr-meta">Passage ${p.n + 1}${p.locator ? ` · ${esc(p.locator)}` : ""}</div><pre class="co-raw">${esc(p.text)}</pre></article>`).join("")
    : `<p class="muted pr-empty">Nothing is indexed yet${d.status === "failed" ? ": the file could not be read" : ""}.</p>`;
}

// ---------- editing ----------
function editor() {
  const ta = $("#co-ta"), gut = $("#co-gut");
  let lines = 0;
  const fit = () => {   // the box grows with the text and the page scrolls, so the line numbers need no scroll syncing
    ta.style.height = "auto"; ta.style.height = ta.scrollHeight + "px";
    const n = ta.value.split("\n").length;
    if (n !== lines) { lines = n; gut.textContent = gutter(ta.value); }
  };
  ta.value = S.draft; fit();
  ta.addEventListener("input", () => {
    S.draft = ta.value; fit(); guard();
    const b = $("#co-vsave"); if (b) b.disabled = !canSave();
  });
  const nm = $("#co-vname");   // the title: edited here, saved together with the text (Enter or ⌘S)
  nm.addEventListener("input", () => { S.nameDraft = nm.value; guard(); const b = $("#co-vsave"); if (b) b.disabled = !canSave(); });
  nm.addEventListener("keydown", (e) => { if ((e.key === "Enter" && !e.isComposing) || ((e.metaKey || e.ctrlKey) && !e.shiftKey && !e.altKey && e.key.toLowerCase() === "s")) { e.preventDefault(); save(); } });
  ta.addEventListener("keydown", (e) => { if ((e.metaKey || e.ctrlKey) && !e.shiftKey && !e.altKey && e.key.toLowerCase() === "s") { e.preventDefault(); save(); } });
  ta.focus({ preventScroll: true });
}

async function collectionNames() {
  try { return Object.fromEntries((await api("collections?page_size=200")).items.map((x) => [x.id, x.name])); } catch { return {}; }
}

async function save() {
  const d = S.cur;
  if (!S.edit || !canSave()) return;
  const others = (d.collections || []).filter((x) => x !== S.c.id);
  if (others.length) {
    const names = await collectionNames();
    const ok = await confirmDialog({ title: "Save for every collection?", message: `“${d.name}” is also in ${others.map((x) => names[x] || "another collection").join(", ")}. They share one copy, so the change shows up there too.`, confirmLabel: "Save" });
    if (!ok) return;
  }
  const id = S.id, text = S.draft, textDirty = text !== d.text, newName = nameDirty() ? nameVal() : "";
  S.saving = true; S.err = ""; if ($("#co-vsave")) { $("#co-vsave").disabled = true; $("#co-vsave").textContent = "Saving…"; }
  let r = { ...d };
  if (textDirty) {
    try { r = await api(`collections/docs/${id}/text`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text, base_sha: d.sha256 }) }); }
    catch (e) {
      S.saving = false;
      if (id !== S.id) return;
      S.err = e.status === 409 ? "This document changed since you opened it, so nothing was saved." : "Could not save: " + e.message;
      main(); const ta = $("#co-ta"); if (ta) ta.scrollIntoView({ block: "nearest" });
      return;
    }
  }
  let renameErr = "";
  if (newName) {   // the title is saved after the text, so a refused text save leaves the old name too
    try { r = { ...r, name: (await api(`collections/docs/${id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: newName }) })).name }; }
    catch (e) { renameErr = e.message; }
  }
  S.saving = false;
  if (id !== S.id) return;
  S.cur = r; S.passages = null;
  const row = S.docs.find((x) => x.id === id); if (row) Object.assign(row, { name: r.name, size: r.size, sha256: r.sha256, status: r.status });
  files();
  if (renameErr) { S.nameDraft = newName; S.err = "The text was saved, but the name could not be changed: " + renameErr; main(); return; }
  if (textDirty && r.status === "failed") { S.draft = r.text; guard(); toast({ message: "Saved, but the text cannot be read as a " + r.type.toUpperCase() + " file.", ms: 5000 }); main(); return; }   // stays in the editor: fix it and save again
  S.edit = false; S.draft = ""; S.tab = "preview"; guard();
  toast({ message: textDirty ? `Saved “${r.name}”. Re-indexing.` : `Renamed to “${r.name}”.`, ms: 3500 });
  main(); if (textDirty) watch(id, 0);
}

/** After a save the indexer reads the document again: follow its status in the header until it is ready or failed (about 30 seconds at most). */
function watch(id, n) {
  clearTimeout(S.poll);
  S.poll = setTimeout(async () => {
    if (id !== S.id || !S.box) return;
    try {
      const row = (await api(`collections/${S.c.id}/documents`)).items.find((x) => x.id === id);
      if (!row || id !== S.id || !S.box) return;
      Object.assign(S.cur, { status: row.status, passages: row.passages, error: row.error, warnings: row.warnings, size: row.size });
      if ($("#co-vmeta")) $("#co-vmeta").textContent = metaText(S.cur);
      if (row.status === "failed" || row.status === "ready") { if (row.status === "ready") S.passages = null; return; }
    } catch { return; }
    if (n < 20) watch(id, n + 1);
  }, 1500);
}

async function reload() {
  const id = S.id;
  if (dirty() && !(await confirmDialog({ title: "Load the new text?", message: "Your unsaved edit will be replaced.", confirmLabel: "Load", cancelLabel: "Keep editing", danger: true }))) return;
  S.edit = false; S.draft = ""; S.err = ""; S.tab = "preview"; guard();
  try { S.cur = await api(`collections/docs/${id}/text`); S.passages = null; } catch (e) { S.err = "Could not load: " + e.message; }
  if (id === S.id) main();
}

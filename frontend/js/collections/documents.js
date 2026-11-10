// The Documents tab: a drop zone, a short indexing summary with Cancel, a banner for files that failed, and the list of documents. A document can be in
// several collections (the file is stored once); each row shows its own indexing progress. "My prompts" has no documents: it shows the
// "My prompts" card (its prompts get vectors automatically; "Turn off / on auto-indexing" switches that) and the index status instead.
import { confirmDialog, formDialog } from "../dialog.js";
import { toast } from "../toast.js";
import { api, esc, ic, I, json, plural, sizeText } from "./common.js";
import { mountViewer, unmountViewer, docFromHash } from "./viewer.js";

const $ = (s) => document.querySelector(s);
const STATUS = { waiting: "Waiting", reading: "Reading", indexing: "Indexing", ready: "Ready", failed: "Failed" };
const S = { box: null, c: null, onHead: null, docs: [], idx: null, names: {}, ticket: 0, timer: 0, busy: "" };

export function unmountDocuments() { clearTimeout(S.timer); S.ticket++; S.box = null; unmountViewer(); }

export function mountDocuments(box, c, onHead) {
  const open = !c.builtin && docFromHash();   // #/collections/<id>/documents/<doc>: the viewer instead of the list
  if (open) { Object.assign(S, { box: null }); mountViewer(box, c, open); return; }
  Object.assign(S, { box, c, onHead, docs: [], idx: null, busy: "" });
  box.innerHTML = c.builtin ? `<div id="co-idx"></div>` : `
    <div class="co-drop" id="co-drop" tabindex="0" role="button" aria-label="Add documents">
      <span class="co-dropic">${ic(I.upload, 28)}</span>
      <strong id="co-droptext">Drop files here, or choose them</strong>
      <span class="muted small">Markdown, text, PDF, JSON and JSONL. A file that cannot be read is kept with the reason, and never stops the others.</span>
      <input type="file" id="co-file" multiple hidden>
    </div>
    <div id="co-idx"></div><div id="co-banner"></div><div class="co-listhead" id="co-listhead" hidden></div>
    <ul class="pr-list co-docs" id="co-docs" aria-label="Documents"></ul>`;
  if (!c.builtin) wire();
  load();
}

// ---------- loading ----------
async function load() {
  clearTimeout(S.timer);
  const box = S.box, my = ++S.ticket;
  if (!box) return;
  const c = S.c;
  try {
    const [idx, head, docs, all] = await Promise.all([api("collections/index"), api("collections/" + c.id), c.builtin ? { items: [] } : api(`collections/${c.id}/documents`), c.builtin ? { items: [] } : api("collections?page_size=200")]);
    if (my !== S.ticket) return;
    S.idx = idx; S.docs = docs.items; S.names = Object.fromEntries(all.items.filter((x) => !x.builtin).map((x) => [x.id, x.name]));   // My prompts takes no documents
    S.c = { ...c, ...head }; S.onHead?.(S.c);
  } catch { if (my === S.ticket) $("#co-idx") && ($("#co-idx").innerHTML = `<p class="muted pr-empty">Could not load. Is the server running?</p>`); return; }
  render();
  const working = S.docs.some((d) => d.status === "reading" || d.status === "indexing"), waiting = S.docs.some((d) => d.status === "waiting");
  const live = !["off", "cancelled", "needs_rebuild", "waiting_model", "error"].includes(S.idx.state);
  const mine = S.idx.prompts, promptsBusy = S.c.builtin && mine?.enabled && mine.pending && live;
  if (S.box && (S.idx.state === "running" || working || (waiting && live) || promptsBusy || S.busy)) S.timer = setTimeout(load, 1500);   // progress moves on its own
}

// ---------- drawing ----------
function indexBar() {
  const i = S.idx, p = i.progress || {}, link = `<a href="#/settings/knowledge">Settings &gt; Knowledge</a>`;
  if (S.c.builtin) { const card = promptsCard(i, link); if (card) return card; }
  if (i.state === "running" && !S.c.builtin) {   // a document collection: one line; every file shows its own bar below
    if (!p.docs_total) return "";
    const at = Math.min(p.docs_total, p.docs_done + 1);
    return `<div class="co-index"><span>Indexing ${plural(p.docs_total, "document")}${p.docs_total > 1 ? ` · now ${at} of ${p.docs_total}` : ""}${p.current ? ` · <span class="co-cur">${esc(p.current)}</span>` : ""}</span><button type="button" class="btn btn-sm btn-glow btn-glow-md" data-cancel>Cancel</button></div>`;
  }
  if (i.state === "running") {
    const pct = p.passages_total ? Math.round((p.passages_done / p.passages_total) * 100) : 0;
    return `<div class="co-index"><div class="co-indexrow"><span>Indexing ${p.prompts_done} of ${p.prompts_total} prompts</span><button type="button" class="btn btn-sm btn-glow btn-glow-md" data-cancel>Cancel</button></div>
      <span class="co-bar wide" role="progressbar" aria-valuenow="${pct}" aria-valuemin="0" aria-valuemax="100"><span style="width:${pct}%"></span></span></div>`;
  }
  const need = i.vector_pending || i.keyword_pending;
  if (i.state === "needs_rebuild") return `<div class="co-index warn"><span>The embedding model changed. Search stays keyword-only until everything is indexed again (${link}).</span></div>`;
  if (i.state === "waiting_model") return S.docs.length || S.c.builtin ? `<div class="co-index"><span>Documents wait until an embedding model is chosen. Choose one in ${link} or on the Collections page.</span></div>` : "";
  if (i.state === "cancelled") return `<div class="co-index"><span>Indexing was cancelled.</span><button type="button" class="btn btn-sm btn-glow btn-glow-md" data-resume>Resume</button></div>`;
  if (i.state === "off" && need) return `<div class="co-index"><span>Automatic indexing is off (${link}). ${plural(i.vector_pending, "item")} waiting.</span><button type="button" class="btn btn-sm btn-glow btn-glow-md" data-resume>Index now</button></div>`;
  if (i.state === "error") return `<div class="co-index warn"><span>${esc(i.error || "Indexing hit a problem and will try again.")}</span><button type="button" class="btn btn-sm btn-glow btn-glow-md" data-resume>Try now</button></div>`;
  return "";
}
/** The My prompts card: the Library and Studio get vectors automatically; the user can stop that, and then they are searched by keyword only. */
function promptsCard(i, link) {
  const m = i.prompts || {};
  if (!m.count) return `<div class="co-index"><span>Save a prompt in the Library or Studio and it shows up here.</span></div>`;
  if (!m.enabled) {
    const ok = !!i.model;
    return `<div class="co-index"><div class="co-indexnote"><strong>Auto-indexing is off for your prompts</strong>
      <span class="muted">Keyword search still works. ${ok ? `Turn it on to index ${plural(m.count, "prompt")} with <span class="co-cur">${esc(i.model)}</span> and also search by meaning. The prompt text goes only to that model.` : `Choose an embedding model in ${link} first.`}</span></div>
      <button type="button" class="btn btn-sm btn-glow btn-glow-md btn-glow btn-glow-md" data-prompts${ok ? "" : " disabled"}>Turn on auto-indexing</button></div>`;
  }
  const stop = `<button type="button" class="btn btn-sm btn-glow btn-glow-md" data-prompts-off>Turn off auto-indexing</button>`;
  if (i.state === "running" || i.state === "off" || i.state === "cancelled" || i.state === "error" || i.state === "needs_rebuild" || i.state === "waiting_model") return `<div class="co-index"><span class="muted">Prompts are indexed automatically with the other documents. The prompt text goes only to <span class="co-cur">${esc(i.model || "the embedding model")}</span>.</span>${stop}</div>`;
  return `<div class="co-index"><span>${m.pending ? `${plural(m.count - m.pending, "prompt")} of ${m.count.toLocaleString()} indexed.` : `${plural(m.count, "prompt")} indexed.`} New and changed prompts are added automatically. The prompt text goes only to <span class="co-cur">${esc(i.model)}</span>.</span>${stop}</div>`;
}
function rowHtml(d) {
  const others = (d.collections || []).filter((x) => x !== S.c.id).map((x) => S.names[x]).filter(Boolean);
  const label = d.status === "waiting" && S.idx?.state === "waiting_model" ? "Waiting for a model" : STATUS[d.status] || d.status;
  const prog = d.status === "indexing" ? S.idx?.progress?.docs?.[d.id] : null, pct = prog && prog[1] ? Math.round((prog[0] / prog[1]) * 100) : null;
  const meta = [d.type.toUpperCase(), sizeText(d.size), d.status === "ready" || (d.status === "indexing" && d.passages) ? plural(d.passages, "passage") : "", others.length ? `also in ${others.map(esc).join(", ")}` : ""].filter(Boolean).join(" · ");
  return `<li class="pr-row co-doc" data-id="${esc(d.id)}">
    <div class="co-docbody">
      <span class="co-ico">${ic(I.file, 20)}</span>
      <span class="co-body"><a class="pr-title co-doclink" href="#/collections/${encodeURIComponent(S.c.id)}/documents/${encodeURIComponent(d.id)}" title="Open this document">${esc(d.name)}</a><span class="pr-meta">${meta}</span>
        ${d.status === "failed" && d.error ? `<span class="co-err">${esc(d.error)}</span>` : ""}
        ${d.warnings?.length ? `<span class="pr-meta co-warn">${esc(d.warnings.join(" · "))}</span>` : ""}</span>
      <span class="co-state"><span class="co-pill ${d.status === "ready" ? "ok" : d.status === "failed" ? "bad" : d.status === "waiting" ? "wait" : "work"}"><i></i>${esc(label)}${pct != null ? ` ${pct}%` : ""}</span>${pct != null ? `<span class="co-bar" role="progressbar" aria-valuenow="${pct}" aria-valuemin="0" aria-valuemax="100" aria-label="Indexing ${esc(d.name)}"><span style="width:${pct}%"></span></span>` : ""}</span>
    </div>
    <div class="lk-pact"><details class="pr-more" data-fixed>
      <summary class="btn btn-sm btn-glow btn-glow-md btn-glow-icon" aria-label="More" title="More">${ic(I.dots, 18)}</summary>
      <div class="pr-menu pr-morepanel" role="menu">
        <button type="button" class="pr-menuitem" role="menuitem" data-rename>${ic(I.edit, 18)}<span>Rename</span></button>
        <button type="button" class="pr-menuitem" role="menuitem" data-reindex>${ic(I.retry, 18)}<span>Re-index</span></button>
        <button type="button" class="pr-menuitem" role="menuitem" data-addto>${ic(I.folder, 18)}<span>Add to another collection</span></button>
        <button type="button" class="pr-menuitem" role="menuitem" data-remove>${ic(I.trash, 18)}<span>Remove from this collection</span></button>
      </div></details></div>
  </li>`;
}
function render() {
  if (!S.box) return;
  $("#co-idx").innerHTML = indexBar();
  if (S.c.builtin) return;
  const failed = S.docs.filter((d) => d.status === "failed");
  $("#co-banner").innerHTML = failed.length ? `<div class="co-index warn"><span>${plural(failed.length, "file")} could not be read. Each one says why below.</span><button type="button" class="btn btn-sm btn-glow btn-glow-md" data-retry>${ic(I.retry)}<span>Try again</span></button></div>` : "";
  const head = $("#co-listhead");   // "Remove all" needs two or more documents to be worth a button
  head.hidden = S.docs.length < 2;
  head.innerHTML = S.docs.length < 2 ? "" : `<span class="muted small">${plural(S.docs.length, "document")}</span><button type="button" class="btn btn-sm btn-glow btn-glow-md btn-glow" data-removeall${S.busy ? " disabled" : ""}>${ic(I.trash, 14)}<span>Remove all</span></button>`;
  $("#co-docs").innerHTML = S.docs.length ? S.docs.map(rowHtml).join("") : `<li class="muted pr-empty">No documents yet. Drop files above to add the first one.</li>`;
  $("#co-droptext").textContent = S.busy || "Drop files here, or choose them";
}

// ---------- actions ----------
async function upload(files) {
  files = [...files].reverse();   // the list shows the newest first, so a batch is added last-to-first and ends up in the order it was chosen
  if (!files.length || S.busy) return;
  let dup = 0; const bad = [];
  for (const [n, f] of files.entries()) {
    S.busy = `Adding ${n + 1} of ${files.length}: ${f.name}`; render();
    try { const r = await api(`collections/${S.c.id}/documents?name=${encodeURIComponent(f.name)}`, { method: "PUT", body: f }); if (r.duplicate) dup++; }
    catch (e) { bad.push(`${f.name}: ${e.message}`); }
    S.busy = ""; if (S.box) await load(); S.busy = "";
  }
  const added = files.length - bad.length;
  toast({ message: bad.length ? `Could not add ${bad[0]}${bad.length > 1 ? ` (and ${bad.length - 1} more)` : ""}` : `Added ${plural(added, "file")}${dup ? `; ${plural(dup, "file")} already stored, now also here` : ""}.`, ms: bad.length ? 6000 : 3500 });
  S.busy = ""; if (S.box) load();
}
async function addTo(d) {
  const others = Object.entries(S.names).filter(([id]) => id !== S.c.id && !(d.collections || []).includes(id));
  if (!others.length) return toast({ message: "There is no other collection to add it to.", ms: 3500 });
  const v = await formDialog({ title: "Add to another collection", confirmLabel: "Add",
    html: `<p class="muted small">“${esc(d.name)}” is stored once and shows up in both.</p><label class="pl-label" for="co-addsel">Collection</label><select class="pl-input" id="co-addsel">${others.map(([id, n]) => `<option value="${esc(id)}">${esc(n)}</option>`).join("")}</select>`,
    read: (dlg) => dlg.querySelector("#co-addsel").value });
  if (!v) return;
  try { await api(`collections/${S.c.id}/documents/${d.id}/add-to`, json("POST", { collection: v })); toast({ message: `Added to “${S.names[v]}”.`, ms: 3000 }); } catch (e) { toast({ message: "Could not add: " + e.message, ms: 4000 }); }
  load();
}
async function removeDoc(d) {
  const cid = S.c.id;
  let r;
  try { r = await api(`collections/${cid}/documents/${d.id}`, { method: "DELETE" }); } catch (e) { return toast({ message: "Could not remove: " + e.message, ms: 4000 }); }
  load();
  const other = (d.collections || []).find((x) => x !== cid);
  toast({ message: r.trashed ? `Moved “${d.name}” to the Trash` : `Removed “${d.name}” from this collection`, action: "Undo", onAction: async () => {
    try { await (r.trashed ? api(`trash/${d.id}/restore`, { method: "POST" }) : api(`collections/${other}/documents/${d.id}/add-to`, json("POST", { collection: cid }))); }
    catch { toast({ message: "Could not undo. Restore it from Trash." }); }
    load();
  } });
}
/** Remove every document from this collection, one `DELETE` each (the same route as the row menu): a document that is only here goes to the Trash, one that is also in another collection just leaves this one. One Undo puts them all back. */
async function removeAll() {
  const c = S.c, docs = [...S.docs];
  if (docs.length < 2 || S.busy) return;
  const shared = docs.filter((d) => (d.collections || []).some((x) => x !== c.id)).length;
  if (!await confirmDialog({ title: "Remove all documents", danger: true, confirmLabel: `Remove ${docs.length}`,
    message: `Remove all ${docs.length} documents from “${c.name}”? ${docs.length - shared ? `${plural(docs.length - shared, "document")} only in this collection go${docs.length - shared === 1 ? "es" : ""} to the Trash, where you can restore ${docs.length - shared === 1 ? "it" : "them"}. ` : ""}${shared ? `${plural(shared, "document")} also in another collection stay${shared === 1 ? "s" : ""} there. ` : ""}Nothing else changes.` })) return;
  const done = [], failed = [];
  for (const [n, d] of docs.entries()) {
    S.busy = `Removing ${n + 1} of ${docs.length}: ${d.name}`; render();
    try { const r = await api(`collections/${c.id}/documents/${d.id}`, { method: "DELETE" }); done.push({ d, trashed: r.trashed }); }
    catch (e) { failed.push(`${d.name}: ${e.message}`); }
  }
  S.busy = ""; if (S.box) load();
  if (!done.length) return toast({ message: "Could not remove: " + failed[0], ms: 5000 });
  toast({ message: `${failed.length ? `Removed ${done.length} of ${docs.length}; could not remove ${failed[0]}` : `Removed ${plural(done.length, "document")}`}.`, action: "Undo", ms: 10000, onAction: async () => {
    let bad = 0;
    for (const { d, trashed } of done) {
      const other = (d.collections || []).find((x) => x !== c.id);
      try { await (trashed ? api(`trash/${d.id}/restore`, { method: "POST" }) : api(`collections/${other}/documents/${d.id}/add-to`, json("POST", { collection: c.id }))); } catch { bad++; }
    }
    if (bad) toast({ message: `Could not put ${plural(bad, "document")} back. Restore from the Trash.`, ms: 5000 });
    if (S.box) load();
  } });
}
async function renameDoc(d) {
  const shared = (d.collections || []).some((x) => x !== S.c.id);
  const v = await formDialog({ title: "Rename document", confirmLabel: "Rename",
    html: `<label class="pl-label" for="co-dname">Name</label><input class="pl-input" id="co-dname" autocomplete="off" maxlength="120" value="${esc(d.name)}">${shared ? `<p class="muted small">This document is in more than one collection. They share one copy, so the new name shows up in all of them.</p>` : ""}`,
    validate: (dlg) => (dlg.querySelector("#co-dname").value.trim() ? "" : "Give the document a name."), read: (dlg) => dlg.querySelector("#co-dname").value.replace(/\s+/g, " ").trim(),
    onOpen: (dlg) => { const i = dlg.querySelector("#co-dname"); i.focus(); const dot = i.value.lastIndexOf("."); i.setSelectionRange(0, dot > 0 ? dot : i.value.length); } });   // the extension stays out of the selection
  if (!v || v === d.name) return;
  try { await api(`collections/docs/${d.id}`, json("PATCH", { name: v })); toast({ message: `Renamed to “${v}”.`, ms: 3000 }); } catch (e) { toast({ message: "Could not rename: " + e.message, ms: 4000 }); }
  load();
}
async function reindex(d) {
  try { await api(`collections/docs/${d.id}/reindex`, { method: "POST" }); toast({ message: `Re-indexing “${d.name}”.`, ms: 2500 }); } catch (e) { toast({ message: "Could not re-index: " + e.message, ms: 4000 }); }
  load();
}

function wire() {
  const drop = $("#co-drop"), file = $("#co-file");
  drop.addEventListener("click", () => file.click());
  drop.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); file.click(); } });
  file.addEventListener("change", () => { upload(file.files); file.value = ""; });
  ["dragenter", "dragover"].forEach((t) => drop.addEventListener(t, (e) => { e.preventDefault(); drop.classList.add("over"); }));
  ["dragleave", "drop"].forEach((t) => drop.addEventListener(t, (e) => { e.preventDefault(); drop.classList.remove("over"); }));
  drop.addEventListener("drop", (e) => upload(e.dataTransfer.files));
  S.box.addEventListener("click", async (e) => {
    const t = e.target, row = t.closest(".co-doc"), d = row && S.docs.find((x) => x.id === row.dataset.id);
    if (d) row.querySelector("details")?.removeAttribute("open");
    if (d && !t.closest(".lk-pact, a, button, summary") && !getSelection()?.toString()) location.hash = `#/collections/${encodeURIComponent(S.c.id)}/documents/${encodeURIComponent(d.id)}`;
    else if (d && t.closest("[data-rename]")) renameDoc(d);
    else if (d && t.closest("[data-reindex]")) reindex(d);
    else if (d && t.closest("[data-addto]")) addTo(d);
    else if (d && t.closest("[data-remove]")) removeDoc(d);
    else if (t.closest("[data-removeall]")) removeAll();
    else if (t.closest("[data-retry]")) { await Promise.all(S.docs.filter((x) => x.status === "failed").map((x) => api(`collections/docs/${x.id}/reindex`, { method: "POST" }).catch(() => {}))); load(); }
  });
}
document.addEventListener("click", async (e) => {   // the index buttons also exist on My prompts, which has no drop zone
  if (!S.box || !S.box.contains(e.target)) return;
  const act = e.target.closest("[data-cancel]") ? "cancel" : e.target.closest("[data-resume]") ? "resume" : e.target.closest("[data-prompts]") ? "prompts" : e.target.closest("[data-prompts-off]") ? "promptsoff" : "";
  if (!act) return;
  try { await (act === "prompts" || act === "promptsoff" ? api("collections/index/prompts", json("POST", { enabled: act === "prompts" })) : api("collections/index/" + act, { method: "POST" })); } catch (err) { toast({ message: err.message, ms: 3500 }); }
  load();
});

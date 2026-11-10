// Trash page (#/trash): deleted prompts can be previewed, restored or deleted for good. Plain DOM.
import { api, relTime } from "./api.js";
import { confirmDialog } from "./dialog.js";
import { toast } from "./toast.js";
import { listNav } from "./listnav.js";

const LABEL = { library: "Library", studio: "Studio", linkshell: "Linkshell project", collections: "Collection" };   // the badge on each row
const WHERE = { library: "the Prompt Library", studio: "Prompt Studio", linkshell: "Linkshell", collections: "Collections" };
const label = (o) => (o.store === "collections" && o.kind === "document" ? "Document" : LABEL[o.store] || LABEL.library);
const what = (o) => (o?.store === "collections" ? (o.kind === "document" ? "document" : "collection") : o?.store === "linkshell" ? "project" : "prompt");
const $ = (s) => document.querySelector(s);
const esc = (t) => String(t ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
const ICON = (d) => `<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${d}</svg>`;
const RESTORE = ICON(`<path d="M3 12a9 9 0 1 0 3-6.7"/><path d="M3 4v5h5"/>`);
const TRASH = ICON(`<path d="M4 7h16M10 11v6M14 11v6M6 7l1 12a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2l1-12M9 7V4h6v3"/>`);

let data = null;
let wired = false;

/** Sidebar badge: how many prompts are in the trash. */
export async function refreshTrashCount() {
  try {
    const { count } = await api("trash/count");
    const b = $("#trash-badge");
    b.textContent = count > 99 ? "99+" : count;
    b.hidden = !count;
  } catch { /* the badge is a convenience */ }
}

export function showTrash() {
  if (!wired) { wired = true; wire(); }
  load().catch(() => { $("#tr-list").innerHTML = `<li class="muted pr-empty">Could not load the trash.</li>`; });
}

async function load() {
  data = await api("trash");
  render();
  refreshTrashCount();
}

function leftText(o) {
  if (!o.purge_at) return "";
  const days = Math.ceil((o.purge_at - Date.now() / 1000) / 86400);
  return days <= 1 ? " · deleted for good within a day" : ` · deleted for good in ${days} days`;
}

function render() {
  const { items, days } = data;
  $("#tr-sub").textContent = days
    ? `Deleted prompts, projects, collections and documents stay here for ${days} days, then are removed for good. Restore one to bring it back to where it came from.`
    : "Deleted prompts, projects, collections and documents stay here until you remove them. Restore one to bring it back to where it came from.";
  $("#tr-count").textContent = items.length ? `${items.length} in trash` : "";
  $("#tr-empty").hidden = !items.length;
  $("#tr-list").innerHTML = items.length ? items.map((o) => `
    <li class="pr-row tr-row" data-id="${esc(o.id)}">
      <div class="pr-link tr-main" data-toggle role="button" tabindex="0" aria-expanded="false">
        <span class="pr-top">
          <span class="pr-title">${esc(o.title)}</span>
          <span class="pr-meta"><span class="pr-agent">${esc(label(o))}</span>${o.store === "library" || !o.store ? esc(o.project || "unknown") + " · " : ""}deleted ${relTime(o.deleted_at)}${o.edited ? " · edited" : ""}${esc(leftText(o))}${o.tags.map((t) => `<i>${esc(t)}</i>`).join("")}</span>
        </span>
        <span class="pr-prev">${esc(o.preview)}</span>
        <pre class="tr-text" hidden></pre>
      </div>
      <span class="tr-actions">
        <button type="button" class="btn btn-sm btn-glow btn-glow-md tr-btn" data-restore title="Restore to ${WHERE[o.store] || WHERE.library}">${RESTORE}<span>Restore</span></button>
        <button type="button" class="btn btn-sm btn-glow btn-glow-md btn-glow-icon pr-del" data-purge aria-label="Delete forever" title="Delete forever">${TRASH}</button>
      </span>
    </li>`).join("") : `<li class="muted pr-empty">The trash is empty.</li>`;
}

function wire() {
  listNav(null, $("#tr-list"));   // ↑ / ↓ highlight a deleted item, Enter shows or hides its preview (no search box on this page)
  $("#tr-list").addEventListener("click", async (e) => {
    const row = e.target.closest(".tr-row"); if (!row) return;
    const id = row.dataset.id, enc = encodeURIComponent(id);
    if (e.target.closest("[data-restore]")) {
      try {
        await api(`trash/${enc}/restore`, { method: "POST" });
        toast({ message: `Restored to ${WHERE[data.items.find((o) => o.id === id)?.store] || WHERE.library}.` });
      } catch (err) {
        const o = data.items.find((x) => x.id === id), kind = what(o);
        toast({ message: err.status === 409 ? (o?.store === "collections" ? `Can't restore: ${err.message}.` : `Can't restore: a ${kind} with this id already exists.`) : `Could not restore this ${kind}.` });
      }
      return load().catch(() => {});
    }
    if (e.target.closest("[data-purge]")) {
      const o = data.items.find((x) => x.id === id), extra = o?.store === "collections" ? (o.kind === "collection" ? "Its documents and saved conversations are removed too" : "Its file and passages are removed") : "Its files and all its saved versions are removed";
      if (!await confirmDialog({ title: "Delete forever", message: `Delete this ${what(o)} for good? ${extra} and can't be restored.`, confirmLabel: "Delete forever", danger: true })) return;
      await api(`trash/${enc}`, { method: "DELETE" }).catch(() => {});
      return load().catch(() => {});
    }
    if (e.target.closest(".tr-text")) return;   // selecting text in the preview must not collapse it
    if (e.target.closest("[data-toggle]")) {   // preview the full text
      const btn = row.querySelector("[data-toggle]"), pre = row.querySelector(".tr-text");
      const open = pre.hidden;
      if (open && !pre.textContent) pre.textContent = (await api(`trash/${enc}`).catch(() => ({ text: "Could not load this prompt." }))).text;
      pre.hidden = !open;
      btn.setAttribute("aria-expanded", open);
      row.querySelector(".pr-prev").hidden = open;
    }
  });
  $("#tr-list").addEventListener("keydown", (e) => {
    if ((e.key === "Enter" || e.key === " ") && e.target.matches("[data-toggle]")) { e.preventDefault(); e.target.click(); }
  });
  $("#tr-empty").addEventListener("click", async () => {
    const n = data?.items.length || 0;
    if (!n || !await confirmDialog({ title: "Empty trash", message: `Delete ${n} item${n === 1 ? "" : "s"} for good? This can't be undone, and their saved versions, documents and conversations are removed too.`, confirmLabel: "Empty trash", danger: true })) return;
    await api("trash", { method: "DELETE" }).catch(() => {});
    load().catch(() => {});
  });
}

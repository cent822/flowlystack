// Small helpers shared by the Collections pages: escaping, icons, the status pill and the plain JSON request wrapper.
import { api } from "../api.js";
import { toast } from "../toast.js";

export const esc = (t) => String(t ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
export const ic = (d, s = 16) => `<svg viewBox="0 0 24 24" width="${s}" height="${s}" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${d}</svg>`;
export const I = {
  plus: `<path d="M12 5v14M5 12h14"/>`, dots: `<circle cx="5" cy="12" r="1.2"/><circle cx="12" cy="12" r="1.2"/><circle cx="19" cy="12" r="1.2"/>`,
  star: `<path d="M12 3.5l2.6 5.4 5.9.8-4.3 4.1 1 5.9L12 16.9 6.8 19.7l1-5.9L3.5 9.7l5.9-.8z"/>`,
  trash: `<path d="M4 7h16M10 11v6M14 11v6M6 7l1 12a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2l1-12M9 7V4h6v3"/>`,
  edit: `<path d="M4 20l4.5-1 10-10a2.1 2.1 0 0 0-3-3l-10 10z"/><path d="M14 7l3 3"/>`,
  check: `<circle cx="12" cy="12" r="9"/><path d="M8 12.5l3 3 5-6"/>`, circle: `<circle cx="12" cy="12" r="9"/>`,
  book: `<path d="M4 5.5A1.5 1.5 0 0 1 5.5 4H11v15H5.5A1.5 1.5 0 0 0 4 20.5z"/><path d="M20 5.5A1.5 1.5 0 0 0 18.5 4H13v15h5.5a1.5 1.5 0 0 1 1.5 1.5z"/>`,
  file: `<path d="M7 3h7l5 5v13H7z"/><path d="M14 3v5h5"/>`, upload: `<path d="M12 16V5M7 9l5-5 5 5M5 20h14"/>`,
  retry: `<path d="M4 12a8 8 0 1 1 2.5 5.8M4 19v-4h4"/>`, folder: `<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>`,
  gear: `<circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3M4.9 4.9l2.1 2.1M17 17l2.1 2.1M4.9 19.1L7 17M17 7l2.1-2.1"/>`,
  back: `<path d="M15 6l-6 6 6 6"/>`,
};

/** A menu that must never run off the window or be clipped by a scrolling column: mark its <details> `data-fixed` (and `data-align="left"` to
 * line the panel up with the button's left edge instead of its right edge). It opens below the button, or above when there is no room, and
 * closes when anything scrolls. */
function placeMenu(d) {
  const m = d.querySelector(":scope > .pr-morepanel"), b = d.querySelector(":scope > summary");
  if (!m || !b) return;
  Object.assign(m.style, { position: "fixed", right: "auto", bottom: "auto", top: "0px", left: "0px" });
  const s = b.getBoundingClientRect(), r = m.getBoundingClientRect();
  let top = s.bottom + 6;
  if (top + r.height > innerHeight - 8) top = s.top - r.height - 6;
  top = Math.max(8, Math.min(top, innerHeight - r.height - 8));
  const left = d.dataset.align === "left" ? s.left : s.right - r.width;
  m.style.top = `${Math.round(top)}px`; m.style.left = `${Math.round(Math.max(8, Math.min(left, innerWidth - r.width - 8)))}px`;
}
document.addEventListener("toggle", (e) => { const d = e.target; if (d instanceof HTMLDetailsElement && d.open && d.hasAttribute("data-fixed")) placeMenu(d); }, true);
const closeFixed = () => document.querySelectorAll("details[data-fixed][open]").forEach((d) => { d.open = false; });
document.addEventListener("scroll", closeFixed, true);
addEventListener("resize", closeFixed);

export const json = (method, body) => ({ method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
export { api };

/** "Preparing 63%" with a thin bar, or a plain word. `row.status` is a collection's status, `row.progress` the share finished. */
const PILL = { ready: ["Ready", "ok"], preparing: ["Preparing", "work"], waiting_model: ["Waiting for a model", "wait"], keyword: ["Keyword search", "wait"], empty: ["Add documents", "wait"], failed: ["Failed", "bad"] };
export function pill(row) {
  const [label, tone] = PILL[row.status] || [row.status, "wait"];
  const pct = row.status === "preparing" ? Math.round((row.progress || 0) * 100) : null;
  return `<span class="co-pill ${tone}"><i></i>${esc(label)}${pct != null ? ` ${pct}%` : ""}</span>${pct != null ? `<span class="co-bar" aria-hidden="true"><span style="width:${pct}%"></span></span>` : ""}`;
}

export const sizeText = (n) => (n < 1024 ? `${n} B` : n < 1048576 ? `${(n / 1024).toFixed(n < 10240 ? 1 : 0)} KB` : `${(n / 1048576).toFixed(1)} MB`);
export const plural = (n, w) => `${n.toLocaleString()} ${w}${n === 1 ? "" : "s"}`;

export const splitTags = (s) => [...new Set(String(s).split(",").map((t) => t.trim()).filter(Boolean))];

/** Delete a collection to the shared Trash with an Undo toast. `after` runs once it is gone, `undone` once Undo brought it back. */
export async function removeCollection(c, after, undone) {
  try { await api("collections/" + c.id, { method: "DELETE" }); } catch (e) { return toast({ message: "Could not delete: " + e.message, ms: 4000 }); }
  after?.();
  toast({ message: `Deleted “${c.name}”`, action: "Undo", onAction: async () => {
    await api(`trash/${c.id}/restore`, { method: "POST" }).catch(() => toast({ message: "Could not undo. Restore it from Trash." }));
    undone?.();
  } });
}

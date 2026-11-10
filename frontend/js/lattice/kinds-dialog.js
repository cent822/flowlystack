// The kinds manager: rename kinds, give each a hint and a light and a dark colour, add custom kinds, delete and restore.
// Every change is saved at once through /api/kgraph/kinds (nothing is stored here); `onChange()` lets the page redraw. Deleting is soft: the kind's
// entities show as Other and Restore brings it back, so no confirmation is asked, only an Undo in the toast.
import { api } from "../api.js";
import { confirmDialog, formDialog } from "../dialog.js";
import { toast } from "../toast.js";
import { openPicker, closePicker } from "./colour-picker.js";
import { setKinds, allKinds, limits, previewColour, loadKinds } from "./kinds.js";

const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const SHAPE = '<svg viewBox="0 0 20 20" width="18" height="18" aria-hidden="true"><path d="M10 3l7 12.5H3z" fill="currentColor"/></svg>';
// icon-only buttons (Glow, medium, square): always an aria-label and a title, so the words are still there for a screen reader and on hover
const ico = (d) => `<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${d}</svg>`;
const IC_DEL = ico('<path d="M4 7h16M10 11v6M14 11v6M6 7l1 12a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2l1-12M9 7V4h6v3"/>');
const IC_ADD = ico('<path d="M12 5v14M5 12h14"/>');
const IC_RESTORE = ico('<path d="M4 9h9a4.5 4.5 0 0 1 0 9H8"/><path d="M8 5L4 9l4 4"/>');
const IC_KEPT = ico('<rect x="5" y="11" width="14" height="9" rx="2"/><path d="M8 11V8a4 4 0 0 1 8 0v3"/>');
const iconBtn = (attrs, icon, label) => `<button type="button" class="btn btn-sm btn-glow btn-glow-md btn-glow-icon" ${attrs} aria-label="${esc(label)}" title="${esc(label)}">${icon}</button>`;
const call = (method, path, body) => api(path, { method, ...(body ? { headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : {}) });

/** A dark colour to start from when only the light one was chosen: the same hue, lighter and a little softer, so it reads on a dark surface. */
export function darkFrom(hex) {
  const n = parseInt(hex.slice(1), 16), r = (n >> 16) / 255, g = ((n >> 8) & 255) / 255, b = (n & 255) / 255;
  const mx = Math.max(r, g, b), mn = Math.min(r, g, b), l = (mx + mn) / 2, d = mx - mn;
  let h = 0, s = d === 0 ? 0 : d / (1 - Math.abs(2 * l - 1));
  if (d) h = mx === r ? ((g - b) / d + (g < b ? 6 : 0)) : mx === g ? (b - r) / d + 2 : (r - g) / d + 4;
  h *= 60; s = Math.min(s, 0.75);
  const L = Math.min(0.72, Math.max(l + 0.12, 0.58)), c = (1 - Math.abs(2 * L - 1)) * s, x = c * (1 - Math.abs(((h / 60) % 2) - 1)), m = L - c / 2;
  const [R, G, B] = h < 60 ? [c, x, 0] : h < 120 ? [x, c, 0] : h < 180 ? [0, c, x] : h < 240 ? [0, x, c] : h < 300 ? [x, 0, c] : [c, 0, x];
  return "#" + [R + m, G + m, B + m].map((v) => Math.round(v * 255).toString(16).padStart(2, "0")).join("");
}

const chip = (which, slug, value, name = "") => `<button type="button" class="kd-chip kd-${which}" data-w="${which}" data-value="${value}"${slug ? ` data-slug="${slug}"` : ""} title="${which === "light" ? "Colour in light mode" : "Colour in dark mode"}" aria-label="${which === "light" ? "Light" : "Dark"} mode colour${name ? " of " + esc(name) : ""}"><span class="kd-tri" style="color:${value}">${SHAPE}</span></button>`;

function body(list) {
  const act = list.filter((k) => !k.deleted), gone = list.filter((k) => k.deleted), lim = limits();
  return `<p class="muted small kd-intro">Each kind has its own colour in light and in dark mode. Agents choose a kind by its name, and the hint tells them what belongs there. ${act.length} of ${lim.total} kinds.</p>
    <div class="kd-grid kd-head" aria-hidden="true"><span>Light</span><span>Dark</span><span>Name</span><span>Hint for agents</span><span></span></div>
    <div id="kd-rows">${act.map((k) => `<div class="kd-grid kd-row" data-slug="${k.slug}">${chip("light", k.slug, k.light, k.label)}${chip("dark", k.slug, k.dark, k.label)}
      <input class="pl-input" data-f="label" value="${esc(k.label)}" maxlength="${lim.label}" aria-label="Name of ${esc(k.label)}">
      <input class="pl-input" data-f="hint" value="${esc(k.hint)}" maxlength="${lim.hint}" placeholder="What belongs here" aria-label="Hint for ${esc(k.label)}">
      ${k.slug === "other" ? `<span class="muted kd-keep" role="img" aria-label="Kept: entities of a deleted kind are shown here" title="Kept: entities of a deleted kind are shown here">${IC_KEPT}</span>` : iconBtn(`data-del="${k.slug}"`, IC_DEL, `Delete ${k.label}`)}</div>`).join("")}</div>
    <h3 class="kd-h">Add a kind</h3>
    <div class="kd-grid kd-add">${chip("light", "", "#4f7cff", "the new kind")}${chip("dark", "", darkFrom("#4f7cff"), "the new kind")}
      <input class="pl-input" id="kd-new-label" maxlength="${lim.label}" placeholder="Name" aria-label="Name of the new kind"${act.length >= lim.total ? " disabled" : ""}>
      <input class="pl-input" id="kd-new-hint" maxlength="${lim.hint}" placeholder="What belongs here (optional)" aria-label="Hint for the new kind"${act.length >= lim.total ? " disabled" : ""}>
      ${iconBtn(`id="kd-add"${act.length >= lim.total ? " disabled" : ""}`, IC_ADD, "Add this kind")}</div>
    ${act.length >= lim.total ? `<p class="muted small">That is the limit of ${lim.total} kinds. Delete one to add another.</p>` : ""}
    ${gone.length ? `<h3 class="kd-h">Deleted</h3><ul class="kd-gone">${gone.map((k) => `<li><span class="kd-tri" style="color:${k.light}">${SHAPE}</span><span>${esc(k.label)}</span>${iconBtn(`data-restore="${k.slug}"`, IC_RESTORE, `Restore ${k.label}`)}</li>`).join("")}</ul>
      <p class="muted small">Entities of a deleted kind show as Other until it is restored. Nothing is lost.</p>` : ""}
    <div class="kd-foot"><button type="button" class="btn btn-sm btn-glow" id="kd-reset">Reset to defaults</button></div>`;
}

/** Open the manager. `onChange()` runs after every saved change; `onPreview()` while a colour is being picked (a quick redraw, nothing saved yet). Resolves when closed. */
export function openKindsManager({ onChange, onPreview }) {
  let dlgEl = null;
  const paint = () => { closePicker(); const b = dlgEl.querySelector(".cb-form-body"); const at = b.scrollTop; b.innerHTML = body(allKinds()); b.scrollTop = at; };
  const save = async (fn) => {
    try { const d = await fn(); setKinds(d); onChange?.(); }
    catch (e) { toast({ message: e.message, ms: 5000 }); await loadKinds(); onChange?.(); }   // the local copy may hold an unsaved preview: take the saved one back
    paint();
  };
  /** Open the picker for a chip. A kind's chip previews live on the board and is saved when the picker closes; the new kind's chips only hold their value until Add. */
  const chooseColour = (dlg, b) => {
    const tri = (el, c) => { el.dataset.value = c; el.firstElementChild.style.color = c; };
    openPicker(b, dlg, b.dataset.value, b.dataset.w, {
      onInput(hex) {
        tri(b, hex);
        if (b.dataset.slug) { previewColour(b.dataset.slug, b.dataset.w, hex); onPreview?.(); return; }
        if (b.dataset.w === "dark") b.dataset.touched = "1";
        else { const d = dlg.querySelector('.kd-add [data-w="dark"]'); if (!d.dataset.touched) tri(d, darkFrom(hex)); }   // until the user picks the dark one, it follows the light one
      },
      onChange(hex) { if (b.dataset.slug) save(() => call("PATCH", `kgraph/kinds/${b.dataset.slug}`, { [b.dataset.w]: hex })); },
    });
  };
  const result = formDialog({
    title: "Entity kinds", html: body(allKinds()), wide: true, confirmLabel: "Done", cancelLabel: null,
    onOpen(dlg) {
      dlgEl = dlg;
      dlg.addEventListener("close", closePicker);   // Cmd+Enter closes the dialog with the picker still open: closing it here is what saves the last colour
      dlg.addEventListener("keydown", (e) => {   // Enter in a field saves that field; it does not close the dialog (Add handles its own fields)
        if (e.key !== "Enter" || !(e.target instanceof HTMLInputElement) || e.target.closest(".kp-pop")) return;
        e.preventDefault();
        if (e.target.id === "kd-new-label" || e.target.id === "kd-new-hint") dlg.querySelector("#kd-add").click(); else e.target.blur();
      });
      dlg.addEventListener("change", (e) => {
        const t = e.target;
        if (t.matches(".kd-row [data-f]")) save(() => call("PATCH", `kgraph/kinds/${t.closest(".kd-row").dataset.slug}`, { [t.dataset.f]: t.value }));
      });
      dlg.addEventListener("click", async (e) => {
        const b = e.target.closest("button");
        if (!b) return;
        if (b.classList.contains("kd-chip")) { chooseColour(dlg, b); return; }
        if (b.id === "kd-add") {
          const v = (id) => dlg.querySelector(id).value, col = (w) => dlg.querySelector(`.kd-add [data-w="${w}"]`).dataset.value;
          if (!v("#kd-new-label").trim()) { dlg.querySelector("#kd-new-label").focus(); return; }
          await save(() => call("POST", "kgraph/kinds", { label: v("#kd-new-label"), hint: v("#kd-new-hint"), light: col("light"), dark: col("dark") }));
        } else if (b.dataset.del) {
          const k = allKinds().find((x) => x.slug === b.dataset.del);
          await save(() => call("DELETE", `kgraph/kinds/${b.dataset.del}`));
          toast({ message: `Deleted “${k?.label}”. Its entities show as Other.`, action: "Undo", ms: 8000, onAction: () => save(() => call("POST", `kgraph/kinds/${k.slug}/restore`)) });
        } else if (b.dataset.restore) await save(() => call("POST", `kgraph/kinds/${b.dataset.restore}/restore`));
        else if (b.id === "kd-reset") {
          if (!await confirmDialog({ title: "Reset kinds to the defaults?", message: "The ten built-in kinds come back with their own names and colours. Kinds you added are removed for good: their entities show as Other. This cannot be undone.", confirmLabel: "Reset", danger: true })) return;
          await save(() => call("POST", "kgraph/kinds/reset"));
        }
      });
    },
  });
  return result;
}

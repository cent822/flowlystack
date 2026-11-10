// The node-colour manager: a light and a dark colour per item type (Library, Studio, Documents, Collections, Tags) and per individual collection.
// Every change is saved at once through /api/kgraph/colours (the server keeps only the changes); `onChange()` lets the page redraw. Same chips, picker and
// dialog as the kinds manager. A row's Default button puts it back to the built-in colour (a collection then follows the Collections type).
import { api } from "../api.js";
import { confirmDialog, formDialog } from "../dialog.js";
import { toast } from "../toast.js";
import { openPicker, closePicker } from "./colour-picker.js";
import { setColours, colours, chipColour, previewColour, loadColours, EDITABLE } from "./colours.js";
import { TYPE_LABEL } from "./draw.js";

const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const call = (method, path, body) => api(path, { method, ...(body ? { headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : {}) });
// the same shapes as on the board: a circle, a square, a diamond
const SHAPE = {
  prompt: '<circle cx="10" cy="10" r="6.5" fill="currentColor"/>', studio: '<circle cx="10" cy="10" r="6.5" fill="currentColor"/>', document: '<circle cx="10" cy="10" r="6.5" fill="currentColor"/>',
  collection: '<rect x="4" y="4" width="12" height="12" rx="1.5" fill="currentColor"/>', tag: '<path d="M10 2.5l7.5 7.5-7.5 7.5L2.5 10z" fill="currentColor"/>', reference: '<path d="M10 2.5l7.4 5.4-2.8 8.6H5.4L2.6 7.9z" fill="currentColor"/>', linkshell: '<path d="M8 2.5h4v5.5h5.5v4H12v5.5H8V12H2.5V8H8z" fill="currentColor"/>', project: '<path d="M10 2.5l6.5 3.75v7.5L10 17.5l-6.5-3.75v-7.5z" fill="currentColor"/>',
};
const svg = (shape) => `<svg viewBox="0 0 20 20" width="18" height="18" aria-hidden="true">${shape}</svg>`;

/** Contrast ratio of two #rrggbb colours (WCAG): used only to warn that a colour is hard to see on the surface its chip shows. */
function lum(hex) { const n = parseInt(hex.slice(1), 16); return [(n >> 16) & 255, (n >> 8) & 255, n & 255].map((v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; }).reduce((a, v, i) => a + v * [0.2126, 0.7152, 0.0722][i], 0); }
const contrast = (a, b) => { const x = lum(a), y = lum(b); return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05); };
const SURFACE = { light: "#ffffff", dark: "#1a1d2e" };   // the two chip surfaces, as in .kd-chip
const faint = (hex, which) => contrast(hex, SURFACE[which]) < 1.6;

function chip(kind, key, which, name) {
  const v = chipColour(kind, key, which);
  return `<button type="button" class="kd-chip kd-${which}" data-w="${which}" data-kind="${kind}" data-key="${esc(key)}" data-value="${v}" title="${which === "light" ? "Colour in light mode" : "Colour in dark mode"}" aria-label="${which === "light" ? "Light" : "Dark"} mode colour of ${esc(name)}"><span class="kd-tri" style="color:${v}">${svg(SHAPE[kind === "collection" ? "collection" : key])}</span></button>`;
}
function row(kind, key, name, shapeKey, count) {
  const has = kind === "collection" ? colours().collections[key] : colours().types[key];
  const warn = ["light", "dark"].filter((w) => faint(chipColour(kind, key, w), w));
  return `<div class="kc-grid kd-row" data-kind="${kind}" data-key="${esc(key)}">${chip(kind, key, "light", name)}${chip(kind, key, "dark", name)}
    <span class="kc-name"><span title="${esc(name)}">${esc(name)}</span>${count !== undefined ? ` <span class="gal-n">${count}</span>` : ""}${warn.length ? `<span class="kc-warn small">Hard to see in ${warn.join(" and ")} mode</span>` : ""}</span>
    <button type="button" class="btn btn-sm btn-glow" data-default="1"${has ? "" : " disabled"} aria-label="Back to the default colour of ${esc(name)}">${kind === "collection" ? "Follow type" : "Default"}</button></div>`;
}

function body(cols, counts) {
  return `<p class="muted small kd-intro">Pick the colour of each kind of item on the Lattice board, separately for light and dark mode. A collection can have its own colour; otherwise it follows the Collections colour. Entity colours are in Edit kinds.</p>
    <div class="kc-grid kd-head" aria-hidden="true"><span>Light</span><span>Dark</span><span>Item type</span><span></span></div>
    <div>${EDITABLE.map((t) => row("type", t, TYPE_LABEL[t] + "s", t, counts[t] || 0)).join("")}</div>
    ${cols.length ? `<h3 class="kd-h">Collections</h3><div>${cols.map((c) => row("collection", c.id, c.name)).join("")}</div>` : ""}
    <div class="kd-foot"><button type="button" class="btn btn-sm btn-glow" id="kc-reset">Reset all to defaults</button></div>`;
}

/** Open the manager. `collections`: [{id, name}], `counts`: items per type. `onChange()` runs after every saved change; `onPreview()` while a colour is being picked. Resolves when closed. */
export function openColoursManager({ collections, counts, onChange, onPreview }) {
  let dlgEl = null;
  const paint = () => { closePicker(); const b = dlgEl.querySelector(".cb-form-body"); const at = b.scrollTop; b.innerHTML = body(collections, counts); b.scrollTop = at; };
  const save = async (fn) => {
    try { setColours(await fn()); onChange?.(); }
    catch (e) { toast({ message: e.message, ms: 5000 }); await loadColours(); onChange?.(); }   // the local copy may hold an unsaved preview: take the saved one back
    paint();
  };
  const path = (kind, key) => (kind === "collection" ? `kgraph/colours/collections/${encodeURIComponent(key)}` : `kgraph/colours/types/${encodeURIComponent(key)}`);
  const chooseColour = (dlg, b) => {
    const { kind, key, w } = b.dataset;
    openPicker(b, dlg, b.dataset.value, w, {
      onInput(hex) { b.dataset.value = hex; b.firstElementChild.style.color = hex; previewColour(kind, key, w, hex); onPreview?.(); },
      onChange(hex) {
        // the first change to a row stores both modes, so the other one keeps the colour it showed (a collection would otherwise switch to following the type for that mode)
        const other = w === "light" ? "dark" : "light", o = kind === "collection" ? colours().collections[key] : colours().types[key];
        save(() => call("PATCH", path(kind, key), { [w]: hex, ...(o && o[other] ? {} : { [other]: chipColour(kind, key, other) }) }));
      },
    });
  };
  return formDialog({
    title: "Node colours", html: body(collections, counts), wide: true, confirmLabel: "Done", cancelLabel: null,
    onOpen(dlg) {
      dlgEl = dlg;
      dlg.addEventListener("close", closePicker);   // Cmd+Enter closes the dialog with the picker still open: closing it here is what saves the last colour
      dlg.addEventListener("click", async (e) => {
        const b = e.target.closest("button");
        if (!b) return;
        if (b.classList.contains("kd-chip")) { chooseColour(dlg, b); return; }
        if (b.dataset.default) { const r = b.closest(".kd-row").dataset; await save(() => call("DELETE", path(r.kind, r.key))); return; }
        if (b.id === "kc-reset") {
          if (!await confirmDialog({ title: "Reset all node colours?", message: "Every item type and every collection goes back to its built-in colour. Entity kinds are not touched.", confirmLabel: "Reset", danger: true })) return;
          await save(() => call("POST", "kgraph/colours/reset"));
        }
      });
    },
  });
}

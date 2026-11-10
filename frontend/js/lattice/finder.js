// Lattice "Find an item" dialog: the Search shortcut (Settings > Keyboard > Search, Cmd+Shift+S by default) opens it in the middle of the screen, like the
// command palette (same look, `cp-*` classes), so it works in Full View too, where the left search box is hidden. It searches every node of the graph
// (not only the ones drawn); choosing one calls `onPick(id)`, which shows it again if a filter hid it and selects it. Plain DOM, no model, nothing leaves the page.
import { rank } from "../palette.js";
import { TYPE_LABEL } from "./draw.js";
import { nodeColour } from "./colours.js";
import { kindColour } from "./kinds.js";

const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const MAX = 40;
let dlg, input, list, count, shown = [], active = 0, items = [], pick = null;

function render() {
  const q = input.value.trim();
  list.innerHTML = !q ? `<li class="cp-empty muted">Type to search ${items.length.toLocaleString()} items, collections and tags.</li>`
    : shown.length ? shown.map((c, i) => `
    <li class="cp-item" role="option" id="lf-${i}" data-i="${i}" aria-selected="${i === active}">
      <span class="cp-ic"><i class="lat-dot lat-dot-${c.t}" style="background:${c.t === "entity" ? kindColour(c.k) : nodeColour(c.t, c.id)}"></i></span>
      <span class="cp-label">${esc(c.label)}</span>
      <span class="cp-kind">${esc(TYPE_LABEL[c.t])}</span>
    </li>`).join("") : `<li class="cp-empty muted">Nothing matches “${esc(q)}”.</li>`;
  input.setAttribute("aria-activedescendant", shown.length && q ? `lf-${active}` : "");
  list.querySelector('[aria-selected="true"]')?.scrollIntoView({ block: "nearest" });
}

function update() {
  const q = input.value.trim();
  const all = q ? rank(items, q) : [];
  shown = all.slice(0, MAX);
  active = 0;
  count.textContent = !q ? "" : all.length > MAX ? `${all.length.toLocaleString()} results · top ${MAX} shown` : `${all.length.toLocaleString()} result${all.length === 1 ? "" : "s"}`;   // every keystroke: how many items match, not only how many are listed
  render();
}

function choose(i) {
  const c = shown[i];
  if (!c) return;
  dlg.close();
  pick?.(c.id);
}

function build() {
  dlg = document.createElement("dialog");
  dlg.className = "cb-dialog cb-palette";
  dlg.setAttribute("aria-label", "Find an item in Lattice");
  dlg.innerHTML = `
    <div class="cp-box">
      <div class="cp-search"><svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" aria-hidden="true"><circle cx="11" cy="11" r="6.5"/><path d="M16 16l4.5 4.5"/></svg>
        <input class="cp-input" type="text" role="combobox" aria-expanded="true" aria-controls="lf-list" aria-label="Find an item in Lattice" placeholder="Find a prompt, document, collection or tag…" autocomplete="off" spellcheck="false">
        <kbd>esc</kbd>
      </div>
      <ul class="cp-list" id="lf-list" role="listbox"></ul>
      <div class="cp-foot"><span><kbd>↑</kbd><kbd>↓</kbd> move</span><span><kbd>↵</kbd> show it in the graph</span><span class="cp-count" id="lf-count" role="status" aria-live="polite"></span></div>
    </div>`;
  count = dlg.querySelector(".cp-count");
  input = dlg.querySelector(".cp-input"); list = dlg.querySelector(".cp-list");
  input.addEventListener("input", update);
  input.addEventListener("keydown", (e) => {
    if (e.isComposing) return;
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      if (shown.length) { active = (active + (e.key === "ArrowDown" ? 1 : -1) + shown.length) % shown.length; render(); }
    } else if (e.key === "Enter") { e.preventDefault(); choose(active); }
  });
  list.addEventListener("mousemove", (e) => {   // hover moves the highlight without rebuilding the list (a rebuild would lose the click)
    const li = e.target.closest("[data-i]");
    if (!li || +li.dataset.i === active) return;
    list.querySelector('[aria-selected="true"]')?.setAttribute("aria-selected", "false");
    active = +li.dataset.i; li.setAttribute("aria-selected", "true"); input.setAttribute("aria-activedescendant", li.id);
  });
  list.addEventListener("click", (e) => { const li = e.target.closest("[data-i]"); if (li) choose(+li.dataset.i); });
  dlg.addEventListener("click", (e) => { if (e.target === dlg) dlg.close(); });
  document.body.append(dlg);
}

/** `nodes`: the graph's nodes ({id, t, n, al?}); `onPick(id)` runs after the dialog closes. */
export function openFinder(nodes, onPick) {
  if (!dlg) build();
  if (dlg.open) return;
  pick = onPick;
  items = nodes.map((n) => ({ id: n.id, t: n.t, k: n.k, label: n.n || "", keywords: `${TYPE_LABEL[n.t] || ""} ${(n.al || []).join(" ")}`, where: "" }));
  input.value = "";
  update();
  dlg.showModal();
  input.focus();
}

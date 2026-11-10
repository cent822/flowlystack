// Command palette (⌘K / Ctrl+K): jump to a page or run an action by typing its name. Not a content search (the Prompt
// Library has its own). Pages come from the sidebar links, so a new page shows up as soon as it has a nav item; any module
// adds more with registerCommands(() => [{ label, where, keywords, icon, run }]). Providers run each time it opens, so
// labels can follow the app's state ("Collapse sidebar" / "Expand sidebar").
const esc = (t) => String(t ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
const svg = (d) => `<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${d}</svg>`;

export const ICONS = {
  theme: svg(`<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>`),
  moon: svg(`<path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/>`),
  sidebar: svg(`<rect x="3" y="4" width="18" height="16" rx="3"/><path d="M9 4v16"/>`),
  agent: svg(`<rect x="5" y="7" width="14" height="11" rx="3"/><path d="M12 7V4M9 12h.01M15 12h.01"/>`),
  plus: svg(`<path d="M12 5v14M5 12h14"/>`),
  find: svg(`<circle cx="11" cy="11" r="6.5"/><path d="M16 16l4.5 4.5"/>`),
  setup: svg(`<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/>`),
};

const providers = [];
export const registerCommands = (fn) => providers.push(fn);

function pages() {   // one entry per sidebar link, with its own icon; data-keywords adds aliases
  return [...document.querySelectorAll("#nav .nav-item")].map((a) => ({
    label: a.querySelector(".nav-label").textContent.trim(), kind: "Page", where: a.closest(".nav-group").dataset.group,
    keywords: a.dataset.keywords || "", icon: a.querySelector("svg").outerHTML, run: () => { location.hash = a.getAttribute("href"); },
  }));
}

const all = () => [...pages(), ...providers.flatMap((p) => p()).map((c) => ({ kind: "Action", keywords: "", where: "", ...c }))];

// Every word typed must match. Lower score ranks first: label starts with it, a label word starts with it, label contains it, keywords/where contain it.
function score(c, q) {
  const label = c.label.toLowerCase(), rest = `${c.keywords} ${c.where}`.toLowerCase();
  let total = 0;
  for (const w of q.toLowerCase().split(/\s+/).filter(Boolean)) {
    const s = label.startsWith(w) ? 0 : label.split(/\s+/).some((x) => x.startsWith(w)) ? 1 : label.includes(w) ? 2 : rest.includes(w) ? 3 : -1;
    if (s < 0) return -1;
    total += s;
  }
  return total;
}
export const rank = (items, q) => (q.trim()
  ? items.map((c, i) => [score(c, q), i, c]).filter(([s]) => s >= 0).sort((a, b) => a[0] - b[0] || a[1] - b[1]).map((x) => x[2])
  : items);

let dlg, input, list, shown = [], active = 0;

function render() {
  list.innerHTML = shown.length ? shown.map((c, i) => `
    <li class="cp-item" role="option" id="cp-${i}" data-i="${i}" aria-selected="${i === active}">
      <span class="cp-ic">${c.icon || ICONS.setup}</span>
      <span class="cp-label">${esc(c.label)}${c.where ? `<span class="cp-where">${esc(c.where)}</span>` : ""}</span>
      <span class="cp-kind">${esc(c.kind)}</span>
    </li>`).join("") : `<li class="cp-empty muted">Nothing matches “${esc(input.value.trim())}”.</li>`;
  input.setAttribute("aria-activedescendant", shown.length ? `cp-${active}` : "");
  list.querySelector('[aria-selected="true"]')?.scrollIntoView({ block: "nearest" });
}

function update() {
  shown = rank(all(), input.value);
  active = 0;
  render();
}

function choose(i) {
  const c = shown[i];
  if (!c) return;
  dlg.close();
  c.run();
  document.dispatchEvent(new CustomEvent("palette:chosen"));   // the sidebar closes its hover overlay (main.js, "sidebar: auto-hide")
}

function build() {
  dlg = document.createElement("dialog");
  dlg.className = "cb-dialog cb-palette";
  dlg.setAttribute("aria-label", "Command palette");
  dlg.innerHTML = `
    <div class="cp-box">
      <div class="cp-search">${svg(`<circle cx="11" cy="11" r="6.5"/><path d="M16 16l4.5 4.5"/>`)}
        <input class="cp-input" type="text" role="combobox" aria-expanded="true" aria-controls="cp-list" aria-label="Go to a page or run an action" placeholder="Go to a page or run an action…" autocomplete="off" spellcheck="false">
        <kbd>esc</kbd>
      </div>
      <ul class="cp-list" id="cp-list" role="listbox"></ul>
      <div class="cp-foot"><span><kbd>↑</kbd><kbd>↓</kbd> move</span><span><kbd>↵</kbd> open</span></div>
    </div>`;
  input = dlg.querySelector(".cp-input"); list = dlg.querySelector(".cp-list");
  input.addEventListener("input", update);
  input.addEventListener("keydown", (e) => {
    if (e.isComposing) return;
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      if (shown.length) { active = (active + (e.key === "ArrowDown" ? 1 : -1) + shown.length) % shown.length; render(); }
    } else if (e.key === "Enter") { e.preventDefault(); choose(active); }
  });
  list.addEventListener("mousemove", (e) => {   // hover moves the highlight; it must not rebuild the list or the click would be lost
    const li = e.target.closest("[data-i]");
    if (!li || +li.dataset.i === active) return;
    list.querySelector('[aria-selected="true"]')?.setAttribute("aria-selected", "false");
    active = +li.dataset.i; li.setAttribute("aria-selected", "true"); input.setAttribute("aria-activedescendant", li.id);
  });
  list.addEventListener("click", (e) => { const li = e.target.closest("[data-i]"); if (li) choose(+li.dataset.i); });
  dlg.addEventListener("click", (e) => { if (e.target === dlg) dlg.close(); });   // a click on the backdrop lands on the <dialog> itself
  document.body.append(dlg);
}

export function openPalette() {
  if (!dlg) build();
  if (dlg.open) return;
  input.value = "";
  update();
  dlg.showModal();
  input.focus();
}

document.addEventListener("keydown", (e) => {
  if ((e.metaKey || e.ctrlKey) && !e.shiftKey && !e.altKey && e.key.toLowerCase() === "k") {
    e.preventDefault();
    if (dlg?.open) dlg.close(); else openPalette();
  }
});
document.querySelector(".side-search")?.addEventListener("click", openPalette);

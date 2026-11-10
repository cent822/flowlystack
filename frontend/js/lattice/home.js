// Lattice: how the user's prompts, Studio prompts and documents connect. The page loads the base snapshot
// from /api/kgraph (built by the server in the background, no model call), turns the controls into a visible subset and hands it to draw.js.
// Everything the canvas shows is also in the text panel (neighbours, counts, a live region), so the page works without the mouse.
import { api, relTime } from "../api.js";
import { confirmDialog, formDialog } from "../dialog.js";
import { toast } from "../toast.js";
import { createGraph, TYPE_COLOR, TYPE_LABEL } from "./draw.js";
import { openFinder } from "./finder.js";
import { LAYOUTS } from "./layouts.js";
import { openLayoutPicker } from "./layout-dialog.js";
import { openKindsManager } from "./kinds-dialog.js";
import { openColoursManager } from "./colours-dialog.js";
import { loadColours, dot } from "./colours.js";
import { loadKinds, activeKinds, shown, kindLabel, kindColour, wasLabel } from "./kinds.js";
import { matches, hotkey, label as hkLabel } from "../hotkeys.js";
import { COPY_ICONS, copy } from "../editor.js";

const $ = (s, r = document) => r.querySelector(s);
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const MIN_ITEMS = 10;
const ITEM_TYPES = ["prompt", "studio", "document"];
const ORDER = ["prompt", "studio", "document", "collection", "tag", "project", "reference", "linkshell"];
const KIND_LABEL = { in_collection: "In collection", tagged: "Tag", in_project: "In project", followed_by: "Followed by", same_text: "Same text", refers_to: "Refers to", refers_doc: "Names the document", derived_from: "Derived from", used_in: "Used in Linkshell", similar: "Similar in meaning", mentions: "Mentions", related: "Related to" };
// What the Copy button puts on the clipboard (shown on the page too). Plain text, no variables; the agent asks before it writes (the tool descriptions say so as well).
const AGENT_PROMPT = `Use the flowlystack MCP tools to add entities to my Lattice. First call graph_unprocessed and tell me how many prompts and documents have not been read yet. Then read about 10 of them (library_get, studio_get or collections_search) and show me the entities and links you would add, each with the exact quote it comes from. Only after I say yes, call graph_start_run once and then graph_add. Every link needs the item id and a quote copied exactly from that item.`;
const isEdgeEntity = (k) => k === "mentions" || k === "related";

const S = { snap: null, status: null, types: { prompt: true, studio: true, document: true, collection: true, tag: true, project: true, reference: true, linkshell: true }, explicit: true, session: true, sametext: true, refs: true, similar: true,
            k: 5, floor: 0.4, hideLone: true, q: "", sel: null, hits: [], focus: null, cols: {}, docCols: new Map(),
            base: null, ent: null, entities: true, kinds: {} };
let focusId = null;   // from a link like #/lattice?focus=<id> (an agent's answer): choose that node once the picture is ready
let built = false, graph = null, timer = 0, loaded = 0, index = null, dirty = false;

// ---------- page ----------
function build(page) {
  page.innerHTML = `
    <div class="lat-top">
    <section class="intro lk-intro gal-intro">
      <div>
        <span class="eyebrow hud">// knowledge</span>
        <h1>Lattice</h1>
        <p class="gal-sr" id="lat-lead">Your prompts, Studio prompts and documents, and how they connect.</p>
      </div>
      <div class="gal-side"><div class="gal-kpis" id="lat-kpis"></div></div>
    </section>
    </div>
    <p class="muted gal-state" id="lat-state" role="status">Reading your prompts and documents…</p>
    <div class="lat-tiny" id="lat-tiny" hidden></div>
    <div class="lat-layout" id="lat-layout" hidden>
      <aside class="lat-controls" id="lat-controls" aria-label="Controls">
        <div class="lat-group" id="lat-all"><div class="lat-head"><span class="lat-h">Filters</span><button type="button" class="btn btn-sm btn-glow" id="lat-allbtn">Deselect all</button></div></div>
        <div class="lat-group" id="lat-layout-g"><div class="lat-head"><span class="lat-h">Layout</span><button type="button" class="btn btn-sm btn-glow lat-layout-btn" id="lat-layout-btn" aria-haspopup="dialog" title="Choose a layout"><span>Organic</span><svg width="10" height="10" viewBox="0 0 10 10" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M2 3.5l3 3 3-3"/></svg></button></div><p class="muted small lat-hint" id="lat-layout-note" hidden></p></div>
        <label class="lat-field"><span class="lat-h">Search</span><span class="srch"><input type="search" id="lat-q" class="lat-input" placeholder="Find an item…" autocomplete="off" spellcheck="false" aria-controls="lat-hits"><kbd class="kbd" id="lat-q-kbd" aria-hidden="true"></kbd></span></label>
        <ul class="lat-hits" id="lat-hits" hidden></ul>
        <div class="lat-group"><div class="lat-head"><span class="lat-h">Show</span><button type="button" class="btn btn-sm btn-glow" id="lat-colours-edit">Edit colours</button></div><div id="lat-types"></div></div>
        <div class="lat-group" id="lat-cols" hidden><span class="lat-h">Collections</span><div id="lat-col-list"></div><p class="muted small">Pick which collections to draw. A collection takes its documents with it; one that is also in another picked collection stays.</p></div>
        <div class="lat-group"><span class="lat-h">Connections</span>
          <label class="lat-check"><input type="checkbox" id="lat-explicit" checked><span>Explicit <small class="muted">(collection, tag, project, derived from)</small></span></label>
          <label class="lat-check"><input type="checkbox" id="lat-session" checked><span>Session order <small class="muted">(next prompt of a session)</small></span></label>
          <label class="lat-check"><input type="checkbox" id="lat-refs" checked><span>Shared references <small class="muted">(files, links, ticket ids)</small></span></label>
          <label class="lat-check"><input type="checkbox" id="lat-sametext" checked><span>Same text <small class="muted">(identical prompts)</small></span></label>
          <label class="lat-check"><input type="checkbox" id="lat-similar" checked><span>Similar in meaning <small class="muted">(an estimate)</small></span></label>
          <label class="lat-check" id="lat-ent-row"><input type="checkbox" id="lat-entities" checked><span>Entities <small class="muted">(made by an agent)</small></span><span class="gal-n" id="lat-ent-n"></span></label>
          <p class="muted small" id="lat-ent-none" hidden></p>
        </div>
        <div class="lat-group" id="lat-kinds"><div class="lat-head"><span class="lat-h">Entity kinds</span><button type="button" class="btn btn-sm btn-glow" id="lat-kinds-edit">Edit kinds</button></div><div id="lat-kind-list"></div></div>
        <div class="lat-group" id="lat-runs" hidden><span class="lat-h">Entity runs</span><ul class="lat-runs" id="lat-run-list"></ul><p class="muted small">Hide keeps a run but removes it from the picture. Undo removes it everywhere and can be reversed. Delete is for good (with an Undo for a moment).</p></div>
        <p class="muted small lat-what" id="lat-what"><b>Entities (optional):</b> the people, tools and concepts found inside your items, drawn as triangles linked to the items that mention them. Add them with an agent or a local model; each item is read once.</p>
        <div class="lat-group" id="lat-agent"><span class="lat-h">Build with an agent (MCP)</span>
          <p class="muted small">Connect Claude Code or another MCP client with a write token, then ask it to add entities. The agent reads your items itself, and nothing is added until you agree in the chat. FlowlyStack checks every link's quote against the item. One run, one Undo.</p>
          <p class="lat-starter" id="lat-starter">${AGENT_PROMPT}</p>
          <div class="lat-btns"><button type="button" class="btn btn-sm btn-glow" id="lat-acopy">${COPY_ICONS}<span>Copy</span></button><a class="btn btn-sm btn-glow" href="#/settings">Settings &gt; MCP</a></div>
        </div>
        <div class="lat-group" id="lat-build"><span class="lat-h">Local model</span>
          <button type="button" class="btn btn-sm btn-glow btn-glow-md" id="lat-xstart">Build with a local model</button>
          <p class="muted small">Reads your items with a model you pick, only when you press Start, and adds entities with a quote each. Smaller models give noisier entities; the quote check keeps them sourced, not necessarily right.</p>
          <div class="lat-xrun" id="lat-xrun" hidden></div>
        </div>
        <div class="lat-group" id="lat-sims"><span class="lat-h">Similar lines</span>
          <label class="lat-range"><span>Closest per item <output id="lat-k-out"></output></span><input type="range" id="lat-k" min="1" max="12" step="1"></label>
          <label class="lat-range"><span>Minimum score <output id="lat-f-out"></output></span><input type="range" id="lat-f" min="0.2" max="0.8" step="0.05"></label>
          <p class="muted small" id="lat-simnote"></p>
        </div>
        <label class="lat-check"><input type="checkbox" id="lat-lone" checked><span>Hide items with no connection <small class="muted" id="lat-lone-n"></small></span></label>
        <div class="lat-btns"><button type="button" class="btn btn-sm btn-glow" id="lat-relayout">Re-layout</button><button type="button" class="btn btn-sm btn-glow" id="lat-recenter">Recenter</button><button type="button" class="btn btn-sm btn-glow" id="lat-refresh">Refresh</button></div>
      </aside>
      <section class="lat-frame" aria-label="Lattice graph">
        <div class="lat-focusbar" id="lat-focusbar" hidden></div>
        <div class="lat-legend" id="lat-legend"></div>
        <div class="lat-view" id="lat-view"><div class="lat-zoom" role="group" aria-label="Zoom"><button type="button" class="btn btn-sm btn-glow" id="lat-zin" aria-label="Zoom in" title="Zoom in (+)">+</button><button type="button" class="btn btn-sm btn-glow" id="lat-zout" aria-label="Zoom out" title="Zoom out (-)">&minus;</button><button type="button" class="btn btn-sm btn-glow" id="lat-full" aria-pressed="false" aria-label="Full view" title="Full view (Esc leaves it)"></button><button type="button" class="btn btn-sm btn-glow" id="lat-motion" aria-label="Pause motion"></button></div></div>
        <p class="lat-none muted" id="lat-none" role="status" hidden>Nothing to show with these choices. Tick something in the controls, or press Select all.</p>
        <p class="lat-tip" id="lat-tip" hidden></p>
      </section>
      <aside class="lat-panel" id="lat-panel" aria-label="Selected item"></aside>
    </div>
    <p class="muted small gal-foot" id="lat-foot"></p>
    <div class="gal-sr" id="lat-live" role="status" aria-live="polite"></div>`;
  const on = (id, ev, fn) => $(id).addEventListener(ev, fn);
  const badge = () => { $("#lat-q-kbd").textContent = hkLabel(hotkey("search")); $("#lat-q").title = `Search (${hkLabel(hotkey("search"))}) opens a search window`; };
  badge(); addEventListener("flowlystack-hotkeys", badge);
  document.addEventListener("keydown", (e) => {   // the Search key opens the find window (it works in Full View too, where this box is hidden)
    if (e.defaultPrevented || $("#page-lattice").hidden || $("#lat-layout").hidden || !S.snap || document.querySelector("dialog[open]") || !matches(e, "search")) return;
    e.preventDefault();
    openFinder(S.snap.nodes, choose);
  });
  on("#lat-q", "input", () => { S.q = $("#lat-q").value; search(); });
  on("#lat-q", "keydown", (e) => { if (e.key === "Enter" && S.hits.length) { e.preventDefault(); choose(S.hits[0]); } });
  on("#lat-hits", "click", (e) => { const b = e.target.closest("[data-id]"); if (b) choose(b.dataset.id); });
  on("#lat-types", "change", (e) => { const c = e.target.closest("[data-type]"); if (c) { S.types[c.dataset.type] = c.checked; apply(); } });
  on("#lat-col-list", "change", (e) => { const c = e.target.closest("[data-col]"); if (c) { S.cols[c.dataset.col] = c.checked; apply(); } });
  on("#lat-col-list", "click", (e) => {
    const b = e.target.closest("[data-only]");
    if (!b) return;
    for (const n of S.snap.nodes) if (n.t === "collection") S.cols[n.id] = n.id === b.dataset.only;
    S.types.collection = true; S.types.document = true;
    for (const t of ["collection", "document"]) { const cb = $(`#lat-types [data-type="${t}"]`); if (cb) cb.checked = true; }
    colList(); apply();
  });
  on("#lat-allbtn", "click", () => setAll(!anyOn()));
  on("#lat-layout-btn", "click", (e) => {
    const btn = e.currentTarget, mouse = e.detail > 0;
    openLayoutPicker(graph.layout()).then((k) => {
      if (mouse) requestAnimationFrame(() => btn.blur());   // as the Edit buttons: no ring left on it after a mouse click
      if (!k || k === graph.layout()) return;
      graph.setLayout(k);
      modeChanged = true;   // fit the view to the new picture
      apply();
    });
  });
  on("#lat-explicit", "change", (e) => { S.explicit = e.target.checked; apply(); });
  on("#lat-entities", "change", (e) => { S.entities = e.target.checked; apply(); });
  on("#lat-kinds-edit", "click", (e) => {
    const btn = e.currentTarget, mouse = e.detail > 0;
    openKindsManager({ onChange: kindsChanged, onPreview: () => { graph?.redraw(); entityControls(); } })
      .then(() => { if (mouse) requestAnimationFrame(() => btn.blur()); });   // the dialog hands focus back to the button: after a mouse click it must not stay lit (a keyboard user keeps the ring)
  });
  on("#lat-colours-edit", "click", (e) => {
    const btn = e.currentTarget, mouse = e.detail > 0;
    const cols = (S.base?.nodes || []).filter((n) => n.t === "collection").map((n) => ({ id: n.id, name: n.n }));
    openColoursManager({ collections: cols, counts: S.base?.counts || {}, onChange: coloursChanged, onPreview: coloursPreview })
      .then(() => { if (mouse) requestAnimationFrame(() => btn.blur()); });   // as Edit kinds: no ring left on the button after a mouse click
  });
  on("#lat-kind-list", "change", (e) => { const c = e.target.closest("[data-kind]"); if (c) { S.kinds[c.dataset.kind] = c.checked; apply(); } });
  on("#lat-xstart", "click", () => buildDialog());
  on("#lat-acopy", "click", (e) => copy(e.currentTarget, AGENT_PROMPT));
  on("#lat-xrun", "click", (e) => { if (e.target.closest("[data-xstop]")) stopRun(); });
  on("#lat-run-list", "click", (e) => { const b = e.target.closest("[data-run]"); if (b) runAction(b.dataset.run, b.dataset.id); });
  on("#lat-session", "change", (e) => { S.session = e.target.checked; apply(); });
  on("#lat-refs", "change", (e) => { S.refs = e.target.checked; apply(); });
  on("#lat-sametext", "change", (e) => { S.sametext = e.target.checked; apply(); });
  on("#lat-similar", "change", (e) => { S.similar = e.target.checked; apply(); });
  on("#lat-lone", "change", (e) => { S.hideLone = e.target.checked; apply(); });
  on("#lat-k", "input", (e) => { S.k = +e.target.value; apply(); });
  on("#lat-f", "input", (e) => { S.floor = +e.target.value; apply(); });
  on("#lat-relayout", "click", () => graph?.relayout());
  on("#lat-recenter", "click", () => graph?.recenter());
  on("#lat-zin", "click", () => graph?.zoomIn());
  on("#lat-zout", "click", () => graph?.zoomOut());
  on("#lat-full", "click", () => setFull(!S.full));
  on("#lat-motion", "click", () => { graph.setMotion(!graph.isMotion()); syncMotion(); });
  setFull(false);
  on("#lat-refresh", "click", async () => { try { await api("kgraph/rebuild", { method: "POST" }); } catch { /* shown by the next load */ } load(); });
  on("#lat-panel", "click", (e) => {
    const b = e.target.closest("[data-pick]");
    if (b) { choose(b.dataset.pick); return; }
    const a = e.target.closest("[data-act]");
    if (a) act(a.dataset.act, a.dataset.id);
  });
  on("#lat-focusbar", "click", (e) => {
    const a = e.target.closest("[data-fa]");
    if (!a) return;
    if (a.dataset.fa === "back") setFocus(null);
    else setFocus(S.focus.id, +a.dataset.fa);
  });
  document.addEventListener("keydown", (e) => {   // Esc leaves the focus view, then clears the choice (never while typing or in a dialog)
    if (e.key !== "Escape" || $("#page-lattice").hidden || document.activeElement !== document.body || document.querySelector("dialog[open], .dlg-overlay")) return;
    if (S.full) setFull(false);
    else if (S.focus) setFocus(null);
    else if (S.sel) graph.select(null);
  });
  graph = createGraph($("#lat-view"), { select: (id) => { S.sel = id; panel(); if (graph) layoutUI(); }, hover: tip });
  addEventListener("flowlystack-theme", () => { graph?.redraw(); if (S.ent) entityControls(); if (S.snap) { typeList(); colList(); legend(); } });   // the kind dots take the other theme's colour too
  syncMotion();
}

// Motion: the slow float of the points (draw.js). On when the page opens unless the system asks for reduced motion (then the button is hidden) or the URL has ?static.
// The button shows what pressing it does: pause while it moves, play while it is still. Not saved.
function syncMotion() {
  const b = $("#lat-motion"), on = graph.isMotion();
  b.hidden = !graph.canMotion();
  b.setAttribute("aria-label", on ? "Pause motion" : "Play motion");
  b.title = on ? "Pause motion" : "Play motion";
  b.innerHTML = `${ICON_FULL}${on ? '<path d="M4.5 2.5v9M9.5 2.5v9"/>' : '<path d="M4 2.5l7 4.5-7 4.5z"/>'}</svg>`;
}

// Full view: only the graph (with its legend line and zoom buttons); the controls, the item panel and the page heading are hidden. Not saved: the page opens normal.
const ICON_FULL = '<svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">';
function setFull(on) {
  S.full = on;
  $("#page-lattice").classList.toggle("lat-is-full", on);
  const b = $("#lat-full");
  b.setAttribute("aria-pressed", String(on));
  b.setAttribute("aria-label", on ? "Leave full view" : "Full view");
  b.title = on ? "Leave full view (Esc)" : "Full view (Esc leaves it)";
  b.innerHTML = on ? `${ICON_FULL}<path d="M5 1v4H1M9 13V9h4"/></svg>` : `${ICON_FULL}<path d="M1 5V1h4M13 9v4H9"/></svg>`;
  $("#lat-live").textContent = on ? "Full view: only the graph is shown." : "";
  if (graph) requestAnimationFrame(() => requestAnimationFrame(() => graph.recenter()));   // after the layout change has resized the canvas
}

/** Router hook: #/lattice. */
export function showLattice() {
  const page = $("#page-lattice");
  if (!built) { built = true; build(page); }
  const f = /[?&]focus=([^&]*)/.exec(location.hash);
  if (f) {
    try { focusId = decodeURIComponent(f[1]); } catch { focusId = null; }
    history.replaceState(null, "", location.hash.split("?")[0]);   // one use: a refresh or Back does not choose it again
  }
  load();
  pollRun(true);   // a run started earlier (and still going, or just finished) shows its progress again
}

// ---------- loading ----------
async function load() {
  clearTimeout(timer);
  let d;
  const entP = api("kgraph/entities").catch(() => null);   // the entity layer is user data and loads on every look (agents add while the page is open)
  const kindsP = Promise.all([loadKinds(), loadColours()]);   // the user's kinds and node colours (display data) load with it
  try { d = await api("kgraph"); } catch { show("error"); return; }
  S.status = d.status;
  const ent = await entP;
  const kSig = JSON.stringify(await kindsP);
  const entChanged = JSON.stringify(ent) !== JSON.stringify(S.ent) || kSig !== S.kSig;
  S.kSig = kSig;
  if (ent) S.ent = ent;
  if (d.snapshot && d.status.built_at !== loaded) { loaded = d.status.built_at; S.base = d.snapshot; rebuild(); dirty = true; }
  else if (entChanged && S.base) { rebuild(); dirty = true; }
  if (!d.snapshot) show(d.status.state === "error" ? "error" : "loading");
  else show(d.snapshot.n_items < MIN_ITEMS ? "tiny" : "ready");
  if ($("#page-lattice").hidden) return;
  if (d.status.state === "building") timer = setTimeout(load, 1500);   // the picture arrives on its own
  if (focusId && S.snap && index && !$("#lat-layout").hidden) {
    const id = focusId; focusId = null;
    if (index.has(id)) requestAnimationFrame(() => choose(id));
    else toast({ message: "That item is not in the picture (it may be hidden, deleted or from an undone run).", ms: 5000 });
  }
}

function show(st) {
  $("#lat-state").hidden = st === "ready" || st === "tiny";
  $("#lat-layout").hidden = st !== "ready";
  $("#lat-tiny").hidden = st !== "tiny";
  if (st === "loading") $("#lat-state").textContent = "Reading your prompts and documents…";
  if (st === "error") $("#lat-state").textContent = "The graph could not be built" + (S.status?.error ? ` (${S.status.error})` : "") + ". It is tried again in a moment, or press Refresh.";
  if (st === "tiny") tiny();
  if (st === "ready") { graph?.resume(); if (dirty) { dirty = false; apply(); } }
  chrome();
}

/** The picture's data: the base snapshot plus the entity layer (entities are nodes after the base ones; mentions go item -> entity, related go entity -> entity). */
function rebuild() {
  const base = S.base, ent = S.ent;
  if (!base) return;
  const nodes = base.nodes.slice(), edges = base.edges.slice(), counts = { ...base.counts }, at = new Map(base.nodes.map((n, i) => [n.id, i]));
  S.loose = 0;
  if (ent) {
    for (const e of ent.entities) { at.set(e.id, nodes.length); nodes.push({ id: e.id, t: "entity", n: e.name, d: 0, k: shown(e.kind), kw: wasLabel(e.kind), al: e.aliases || [], note: e.note || "" }); }
    for (const x of ent.edges) {
      const a = at.get(x.type === "mentions" ? x.item : x.from), b = at.get(x.to);
      if (a === undefined || b === undefined) { if (x.type === "mentions") S.loose++; continue; }   // the item is not in the picture (left out by the cap, or gone): it is still in the panel's evidence
      edges.push([a, b, x.type, 1, 0, { l: x.label, b: x.batch, g: x.source_gone }]);
      if (nodes[b].t === "entity") nodes[b].d++;
      if (nodes[a].t === "entity") nodes[a].d++;
    }
  }
  setSnapshot({ ...base, nodes, edges, counts });
  entityControls();
}

function setSnapshot(snap) {
  S.snap = snap;
  S.shown = null;
  index = new Map(snap.nodes.map((n, i) => [n.id, i]));
  S.adj = snap.nodes.map(() => []);
  snap.edges.forEach((e, i) => { S.adj[e[0]].push(i); S.adj[e[1]].push(i); });
  typeList();
  S.docCols = new Map();
  for (const e of snap.edges) if (e[2] === "in_collection") { if (!S.docCols.has(e[0])) S.docCols.set(e[0], []); S.docCols.get(e[0]).push(e[1]); }
  colList();
  $("#lat-k").value = S.k; $("#lat-f").value = S.floor;
  const words = snap.method === "tfidf-svd";
  $("#lat-simnote").textContent = snap.method === "none" ? "Nothing to compare yet."
    : `Estimated from ${words ? "shared words (there are no stored vectors for most items: no embedding model is set, or indexing is not finished)" : "meaning (the stored embeddings)"}. These lines are guesses, not facts.`;
  $("#lat-sims").hidden = !snap.edge_counts?.similar;
  S.sel = S.sel && index.has(S.sel) ? S.sel : null;
}

/** The type checkboxes under Show, drawn from S.types (so a state change only needs this call). */
function typeList() {
  const c = S.snap.counts || {};
  $("#lat-types").innerHTML = ORDER.filter((t) => c[t]).map((t) => `<label class="lat-check"><input type="checkbox" data-type="${t}" ${S.types[t] !== false ? "checked" : ""}><i style="background:${dot(t)}" class="lat-dot lat-dot-${t}"></i><span>${TYPE_LABEL[t]}s</span><span class="gal-n">${c[t]}</span></label>`).join("");
}

/** Is any filter ticked? (The checkboxes in the controls, except "Hide items with no connection", which is a display option; a disabled one does not count.) */
const anyOn = () => [...$("#lat-controls").querySelectorAll("input[type=checkbox]")].some((c) => c.checked && !c.disabled && c.id !== "lat-lone");

/** The Layout buttons (the chosen one is pressed) and a line saying what it is for; the focus view is always organic, and the note says so. */
function layoutUI() {
  const cur = graph.layout();
  $("#lat-layout-btn span").textContent = LAYOUTS[cur].label;
  const bits = [];
  if (cur === "tree" && !S.focus && graph.root() && index?.has(graph.root())) bits.push(`Root: ${S.snap.nodes[index.get(graph.root())].n}. Pick another item to re-root.`);
  if (S.focus && cur !== "organic") bits.push("The focus view always uses Organic.");
  const note = $("#lat-layout-note");   // one small line, only when there is something to say; normally the Layout row is a single line
  note.textContent = bits.join(" ");
  note.hidden = !bits.length;
}

/** The one button at the top of the controls: "Deselect all" while anything is ticked, "Select all" when nothing is. Called after every change. */
function allButton() {
  const on = anyOn(), b = $("#lat-allbtn");
  b.textContent = on ? "Deselect all" : "Select all";
  b.title = on ? "Untick every filter below, then tick only what you want to see" : "Tick every filter below";
}

/** Select all / Deselect all: every filter in the controls (types, collections, the three connection switches, entity kinds). The sliders and
 *  "Hide items with no connection" are display options, not filters, and stay as they are. Nothing is saved; the page opens with everything on. */
function setAll(on) {
  if (!S.snap) return;
  for (const t of ORDER) S.types[t] = on;
  S.cols = {};
  S.kinds = {};
  if (!on) {
    for (const n of S.snap.nodes) if (n.t === "collection") S.cols[n.id] = false;
    for (const k of activeKinds()) S.kinds[k.slug] = false;
  }
  S.explicit = S.session = S.sametext = S.refs = S.similar = S.entities = on;
  $("#lat-explicit").checked = on;
  $("#lat-session").checked = on;
  $("#lat-sametext").checked = on;
  $("#lat-refs").checked = on;
  $("#lat-similar").checked = on;
  typeList(); colList(); entityControls();   // entityControls sets the Entities switch (it stays off and disabled when there are none)
  apply();
}

/** The Collections picker: one row per collection with its document count; "Only" shows just that one. */
function colList() {
  const snap = S.snap, box = $("#lat-cols");
  const cols = snap.nodes.map((n, i) => [n, i]).filter(([n]) => n.t === "collection");
  box.hidden = !cols.length;
  const count = new Map();
  for (const ids of S.docCols.values()) for (const c of ids) count.set(c, (count.get(c) || 0) + 1);
  $("#lat-col-list").innerHTML = cols.map(([n, i]) => `<div class="lat-colrow"><label class="lat-check"><input type="checkbox" data-col="${esc(n.id)}" ${S.cols[n.id] === false ? "" : "checked"}><i class="lat-dot lat-dot-collection" style="background:${dot("collection", n.id)}"></i><span class="lat-colname" title="${esc(n.n)}">${esc(n.n)}</span><span class="gal-n">${count.get(i) || 0}</span></label><button type="button" class="btn btn-sm btn-glow" data-only="${esc(n.id)}" aria-label="Show only ${esc(n.n)}">Only</button></div>`).join("");
}

// ---------- the visible subset ----------
function subset() {
  const snap = S.snap;
  const docOk = (i) => { const c = S.docCols.get(i); return !c || c.some((x) => S.cols[snap.nodes[x].id] !== false); };   // a document with no collection always shows; else one picked collection is enough
  const visible = (n, i) => (n.t === "entity" ? S.entities && S.kinds[n.k] !== false : S.types[n.t] !== false && (n.t === "collection" ? S.cols[n.id] !== false : n.t !== "document" || docOk(i)));
  const edges = [];
  const deg = new Map();
  for (const e of snap.edges) {
    const a = snap.nodes[e[0]], b = snap.nodes[e[1]];
    if (!visible(a, e[0]) || !visible(b, e[1])) continue;
    if (e[2] === "similar") { if (!S.similar || e[3] < S.floor || e[4] >= S.k) continue; }
    else if (isEdgeEntity(e[2])) { if (!S.entities) continue; }
    else if (e[2] === "followed_by") { if (!S.session) continue; }
    else if (e[2] === "same_text") { if (!S.sametext) continue; }
    else if (e[2] === "refers_to" || e[2] === "refers_doc") { if (!S.refs) continue; }
    else if (!S.explicit) continue;
    edges.push(e);
    deg.set(e[0], (deg.get(e[0]) || 0) + 1); deg.set(e[1], (deg.get(e[1]) || 0) + 1);
  }
  let focusSet = null;
  if (S.focus) {   // the chosen node and everything within `depth` steps of it, over the lines that are on
    const f = index.get(S.focus.id);
    const near = new Set([f]);
    let ring = [f];
    for (let d = 0; d < S.focus.depth && f !== undefined; d++) {
      const nxt = [];
      for (const e of edges) for (const [a, b] of [[e[0], e[1]], [e[1], e[0]]]) if (ring.includes(a) && !near.has(b)) { near.add(b); nxt.push(b); }
      ring = nxt;
    }
    const keep = edges.filter((e) => near.has(e[0]) && near.has(e[1]));
    edges.length = 0; edges.push(...keep);
    deg.clear();
    for (const e of edges) { deg.set(e[0], (deg.get(e[0]) || 0) + 1); deg.set(e[1], (deg.get(e[1]) || 0) + 1); }
    focusSet = near;
  }
  let lone = 0;
  const nodes = [];
  snap.nodes.forEach((n, i) => {
    if (focusSet && !focusSet.has(i)) return;
    if (!visible(n, i)) return;
    const d = deg.get(i) || 0;
    if (!d && ITEM_TYPES.includes(n.t)) lone++;
    if (!d && !focusSet && (S.hideLone || !ITEM_TYPES.includes(n.t))) return;   // a collection or tag with nothing left on it is never drawn
    nodes.push({ id: n.id, t: n.t, n: n.n, d, k: n.k });
  });
  return { nodes, links: edges.map((e) => ({ s: snap.nodes[e[0]].id, t: snap.nodes[e[1]].id, k: e[2], w: e[3], lab: e[5]?.l || "" })), lone, edges };
}

let first = true, modeChanged = false;
function apply() {
  if (!S.snap || $("#lat-layout").hidden) return;
  $("#lat-k-out").textContent = S.k; $("#lat-f-out").textContent = S.floor.toFixed(2);
  const sub = subset();
  graph.setData(sub, { recenter: first || modeChanged, focus: !!S.focus });
  first = false; modeChanged = false;
  S.shown = sub;
  $("#lat-none").hidden = sub.nodes.length > 0;
  allButton();
  layoutUI();
  $("#lat-lone-n").textContent = sub.lone ? `(${sub.lone})` : "";
  const items = sub.nodes.filter((n) => ITEM_TYPES.includes(n.t)).length;
  const nEnt = sub.nodes.filter((n) => n.t === "entity").length;
  const said = `${items} items${nEnt ? `, ${nEnt} entities` : ""}, ${sub.links.length} connections shown${S.focus ? ", focused view" : ""}`;
  $("#lat-live").textContent = said;
  graph.setLabel(`Graph of your material, ${LAYOUTS[graph.layout()].label} layout: ${said}. The panel on the right lists the chosen item and what it connects to. Keys: plus and minus zoom, arrow keys pan.`);
  chrome();
  legend();
  focusBar();
  search();
  panel();
}

function chrome() {
  const snap = S.snap, st = S.status;
  if (!snap) { $("#lat-kpis").innerHTML = ""; return; }
  const sub = S.shown;
  const items = sub ? sub.nodes.filter((n) => ITEM_TYPES.includes(n.t)).length : snap.n_items;
  const ents = sub ? sub.nodes.filter((n) => n.t === "entity").length : 0;
  $("#lat-kpis").innerHTML = `<div class="gal-kpi"><div class="gal-kv">${items.toLocaleString()}</div><div class="gal-kl">items shown</div></div>${ents ? `<div class="gal-kpi"><div class="gal-kv">${ents.toLocaleString()}</div><div class="gal-kl">entities</div></div>` : ""}<div class="gal-kpi"><div class="gal-kv">${(sub ? sub.links.length : snap.edges.length).toLocaleString()}</div><div class="gal-kl">connections</div></div>`;
  const bits = [];
  if (snap.capped) bits.push(`Showing the newest ${snap.n_items.toLocaleString()} items; ${snap.capped.toLocaleString()} older ones are left out.`);
  if (st?.state === "building") bits.push(snap && st.stale ? "Updating the picture…" : "Building…");
  $("#lat-foot").textContent = bits.join(" ");
}

function legend() {
  const items = ORDER.filter((t) => S.snap.counts?.[t] && S.types[t] !== false)
    .map((t) => `<span class="lat-lg"><i class="lat-dot lat-dot-${t}" style="background:${dot(t)}"></i>${TYPE_LABEL[t]}</span>`).join("");
  const ents = S.entities && S.shown?.nodes.some((n) => n.t === "entity");
  const entLg = ents ? `<span class="lat-lg"><i class="lat-dot lat-dot-entity" style="background:var(${TYPE_COLOR.entity})"></i>Entity</span><span class="lat-lg"><svg width="26" height="8" aria-hidden="true" style="color:var(${TYPE_COLOR.entity})"><path d="M1 4h24" stroke="currentColor" stroke-width="2"/></svg>made by an agent: mentioned in, related to (each has a quote)</span>` : "";
  const has = (k) => S.shown?.links.some((l) => l.k === k);
  const factLg = (w, o, text) => `<span class="lat-lg"><svg width="26" height="8" aria-hidden="true" style="opacity:${o}"><path d="M1 4h24" stroke="currentColor" stroke-width="${w}"/></svg>${text}</span>`;
  const factsLg = (has("followed_by") ? factLg(1.4, 0.55, "next prompt in a session") : "") + (has("same_text") ? factLg(2.4, 0.8, "same text") : "");
  $("#lat-legend").innerHTML = `${items}${entLg}<span class="lat-lg"><svg width="26" height="8" aria-hidden="true"><path d="M1 4h24" stroke="currentColor" stroke-width="1.4"/></svg>explicit</span>${factsLg}<span class="lat-lg"><svg width="26" height="8" aria-hidden="true"><path d="M1 4h24" stroke="currentColor" stroke-width="1.4" stroke-dasharray="3 3"/></svg>similar in meaning (estimate)</span>`;
}

// ---------- search and selection ----------
function search() {
  const q = S.q.trim().toLowerCase();
  const list = $("#lat-hits");
  if (!q || !S.shown) { S.hits = []; list.hidden = true; list.innerHTML = ""; graph?.setHighlight(null); return; }
  const found = S.shown.nodes.filter((n) => n.n.toLowerCase().includes(q) || n.t.includes(q) || (n.t === "entity" && (S.snap.nodes[index.get(n.id)].al || []).some((a) => a.toLowerCase().includes(q))));
  S.hits = found.slice(0, 8).map((n) => n.id);
  graph.setHighlight(new Set(found.slice(0, 200).map((n) => n.id)));
  list.hidden = false;
  list.innerHTML = found.length ? found.slice(0, 8).map((n) => `<li><button type="button" class="lat-hit" data-id="${esc(n.id)}"><i class="lat-dot lat-dot-${n.t}" style="background:${dot(n.t, n.id)}"></i><span>${esc(n.n)}</span></button></li>`).join("") + (found.length > 8 ? `<li class="muted small lat-more">${found.length - 8} more match</li>` : "")
    : `<li class="muted small lat-more">Nothing visible matches. A hidden type or a lone item may.</li>`;
}

function choose(id) {
  if (!id) return;
  const node = S.snap.nodes[index.get(id)];
  if (node && node.t === "entity") { S.entities = true; S.kinds[node.k] = true; $("#lat-entities").checked = true; entityControls(); }   // choosing a hidden entity shows it again
  else if (node && S.types[node.t] === false) S.types[node.t] = true;   // choosing a hidden kind shows it again
  if (node && node.t === "collection") S.cols[node.id] = true;   // ... and a hidden collection
  else if (node && node.t === "document") for (const c of S.docCols.get(index.get(id)) || []) S.cols[S.snap.nodes[c].id] = true;
  colList();
  if (!graph.nodeAt(id)) { S.hideLone = false; $("#lat-lone").checked = false; apply(); }
  graph.select(id);
  graph.show(id);
}

function openHref(n) {
  if (n.t === "prompt") return "#/prompts/" + encodeURIComponent(n.id);
  if (n.t === "studio") return "#/studio/" + encodeURIComponent(n.id);
  if (n.t === "collection") return "#/collections/" + encodeURIComponent(n.id);
  if (n.t === "linkshell") return "#/linkshell/" + encodeURIComponent(n.id.split(":")[1]);
  if (n.t === "document") {
    const e = S.adj[index.get(n.id)].map((i) => S.snap.edges[i]).find((x) => x[2] === "in_collection");
    return e ? `#/collections/${encodeURIComponent(S.snap.nodes[e[1]].id)}/documents/${encodeURIComponent(n.id)}` : "";
  }
  return "";
}

function panel() {
  const el = $("#lat-panel");
  if (!S.snap) return;
  if (!S.sel || !index.has(S.sel)) {
    el.innerHTML = `<h2 class="lat-ph">Nothing chosen</h2><p class="muted small">Click a point, or search for an item, to see what it connects to. Drag a point to move it, drag the background to pan, scroll to zoom.</p>`;
    return;
  }
  const i = index.get(S.sel), n = S.snap.nodes[i];
  $("#lat-live").textContent = `Chosen: ${n.n}, ${TYPE_LABEL[n.t]}, ${n.d} connections stored`;
  const groups = {};
  for (const ei of S.adj[i]) {
    const e = S.snap.edges[ei];
    if (e[2] === "similar" && (!S.similar || e[3] < S.floor || e[4] >= S.k)) continue;
    const other = S.snap.nodes[e[0] === i ? e[1] : e[0]];
    let kind = e[2];
    if (kind === "mentions") kind = n.t === "entity" ? "mentioned_in" : "mentions_here";
    else if (kind === "related") kind = e[0] === i ? "related_to" : "related_from";
    if (kind === "in_collection" && n.t === "collection") kind = "in_here";
    if (kind === "derived_from" && e[1] === i) kind = "derived_to";
    if (kind === "tagged" && n.t === "tag") kind = "tagged_here";
    if (kind === "in_project" && n.t === "project") kind = "in_project_here";
    if (kind === "refers_to" && n.t === "reference") kind = "named_in";
    if (kind === "refers_doc" && n.t === "document") kind = "named_by";
    if (kind === "used_in" && n.t === "linkshell") kind = "used_here";
    if (kind === "followed_by") kind = e[0] === i ? "next_in_session" : "previous_in_session";
    if (kind === "same_text") kind = e[1] === i ? "copies_of_it" : "same_text";
    (groups[kind] ||= []).push({ other, score: e[3], lab: e[5]?.l || "" });
  }
  const label = { ...KIND_LABEL, in_here: "Documents here", derived_to: "Studio versions of it", tagged_here: "Carrying this tag", in_project_here: "Prompts in this project", named_in: "Named in", used_here: "Prompts used in this project", named_by: "Named in prompts", next_in_session: "Next in the session", previous_in_session: "Previous in the session", copies_of_it: "Copies of it (same text)", mentions_here: "Entities in this item", mentioned_in: "Mentioned in", related_to: "Related to", related_from: "Related from" };
  const href = openHref(n);
  const html = Object.keys(groups).map((k) => {
    const rows = groups[k].sort((a, b) => b.score - a.score);
    return `<h3 class="lat-ph2">${label[k] || k} <span class="gal-n">${rows.length}</span></h3><ul class="lat-nb">${rows.slice(0, 30).map((r) => `<li><button type="button" data-pick="${esc(r.other.id)}"><i class="lat-dot lat-dot-${r.other.t}" style="background:${dot(r.other.t, r.other.id)}"></i><span>${esc(r.other.n)}</span>${k === "similar" ? `<small class="gal-n">${r.score.toFixed(2)}</small>` : r.lab ? `<small class="gal-n">${esc(r.lab)}</small>` : ""}</button></li>`).join("")}</ul>${rows.length > 30 ? `<p class="muted small">${rows.length - 30} more not listed.</p>` : ""}`;
  }).join("");
  const isEnt = n.t === "entity";
  el.innerHTML = `<h2 class="lat-ph">${esc(n.n)}</h2><p class="muted small lat-sub">${isEnt ? `Entity · ${esc(kindLabel(n.k))}${n.kw ? ` (was ${esc(n.kw)}, deleted)` : ""} · made by an agent` : TYPE_LABEL[n.t]}${n.rk ? ` (${n.rk})` : ""} · ${n.d} connection${n.d === 1 ? "" : "s"} stored</p>
    ${isEnt && n.al?.length ? `<p class="small lat-alias"><span class="muted">Also called</span> ${n.al.map(esc).join(", ")}</p>` : ""}${isEnt && n.note ? `<p class="small lat-note">${esc(n.note)}</p>` : ""}
    <div class="lat-btns">${href ? `<a class="btn btn-sm btn-glow" href="${href}">Open</a>` : ""}${n.t === "tag" || S.focus?.id === n.id ? "" : `<button type="button" class="btn btn-sm btn-glow" data-act="focus" data-id="${esc(n.id)}">Focus on this</button>`}${n.t === "prompt" || n.t === "studio" ? `<button type="button" class="btn btn-sm btn-glow" data-act="tag" data-id="${esc(n.id)}">Tag</button>` : ""}${n.t === "document" ? `<button type="button" class="btn btn-sm btn-glow" data-act="addcol" data-id="${esc(n.id)}">Add to collection</button>` : ""}${isEnt ? `<button type="button" class="btn btn-sm btn-glow" data-act="delent" data-id="${esc(n.id)}">Delete entity</button>` : ""}</div>
    ${evidence(n)}
    ${html || `<p class="muted small">Nothing visible is connected to this with the current settings.</p>`}`;
  if (isEnt) loadEvidence(n);
}

/** An entity's sources: every line that touches it, with the quote, the item it came from and who made it. Read when the entity is chosen (the picture itself holds no quotes). */
function evidence(n) { return n.t === "entity" ? `<div class="lat-evid" id="lat-evid"><p class="muted small">Loading the sources…</p></div>` : ""; }
let evTok = 0;
async function loadEvidence(n) {
  const tok = ++evTok;
  let r;
  try { r = await api("kgraph/entity/" + encodeURIComponent(n.id)); } catch (e) { if (tok === evTok && $("#lat-evid")) $("#lat-evid").innerHTML = `<p class="muted small">Could not read the sources (${esc(e.message)}).</p>`; return; }
  if (tok !== evTok || S.sel !== n.id || !$("#lat-evid")) return;
  const title = (id) => { const i = index.get(id); return i === undefined ? "" : S.snap.nodes[i].n; };
  const rows = r.evidence.map((x) => {
    const t = title(x.item), nd = index.has(x.item) ? S.snap.nodes[index.get(x.item)] : null, href = nd ? openHref(nd) : "";
    const src = x.source_gone ? `<span class="lat-gone">source no longer exists</span>` : nd ? `<button type="button" class="lat-link" data-pick="${esc(x.item)}">${esc(t)}</button>${href ? ` <a href="${href}">Open</a>` : ""}` : `<span class="muted">${esc(x.item)} (not in the picture)</span>`;
    const what = x.type === "mentions" ? "Mentioned in" : x.direction === "out" ? `Related to ${esc(x.other?.name || "?")} (${esc(x.label)}), found in` : `${esc(x.other?.name || "?")} is related to this (${esc(x.label)}), found in`;
    const who = `${esc(x.by || "unknown")}${x.via === "local" ? (/local/i.test(x.by) ? "" : " (local model)") : " via MCP"}`;
    return `<li><blockquote class="lat-quote">“${esc(x.quote)}”</blockquote><p class="small muted">${what} ${src}<br>by ${who} · ${relTime(x.when)}${x.run_note ? ` · ${esc(x.run_note)}` : ""}${x.hidden ? " · run hidden" : ""}</p></li>`;
  }).join("");
  $("#lat-evid").innerHTML = `<h3 class="lat-ph2">Sources <span class="gal-n">${r.evidence.length}</span></h3><ul class="lat-ev">${rows}</ul><p class="muted small">A source is the exact quote an agent gave; FlowlyStack checked it occurs in that item when it was added. It shows what the agent claimed, not that the claim is right.</p>`;
}

// ---------- focus ----------
function setFocus(id, depth = 1) {
  S.focus = id ? { id, depth } : null;
  modeChanged = true;
  apply();
  if (id) graph.select(id);
}
function focusBar() {
  const el = $("#lat-focusbar");
  if (!S.focus) { el.hidden = true; el.innerHTML = ""; return; }
  const n = S.snap.nodes[index.get(S.focus.id)];
  const d = S.focus.depth;
  el.hidden = false;
  el.innerHTML = `<span class="lat-fb-t">Focused on <b>${esc(n.n)}</b></span><span class="lat-fb-s" role="group" aria-label="How far to look"><button type="button" class="btn btn-sm btn-glow" data-fa="1" aria-pressed="${d === 1}">1 step</button><button type="button" class="btn btn-sm btn-glow" data-fa="2" aria-pressed="${d === 2}">2 steps</button></span><button type="button" class="btn btn-sm btn-glow" data-fa="back">Back to everything</button>`;
}

// ---------- actions (nothing happens without a press; items are changed through the same routes their own pages use) ----------
async function act(kind, id) {
  const n = S.snap.nodes[index.get(id)];
  if (!n) return;
  if (kind === "focus") return setFocus(id);
  if (kind === "tag") return tagItem(n);
  if (kind === "addcol") return addToCollection(n);
  if (kind === "delent") return deleteEntity(n);
}
const splitTags = (t) => [...new Set(String(t).split(",").map((x) => x.trim()).filter(Boolean))];
const send = (method, path, body) => api(path, { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
async function refresh() { try { await api("kgraph/rebuild", { method: "POST" }); } catch { /* the next look shows it */ } load(); }

async function tagItem(n) {
  const base = n.t === "studio" ? "studio/" : "prompts/";
  let cur = [];
  try { cur = (await api(base + encodeURIComponent(n.id))).meta?.tags || []; } catch (e) { return toast({ message: "Could not read the tags: " + e.message, ms: 5000 }); }
  const v = await formDialog({
    title: "Tags", confirmLabel: "Save tags",
    html: `<p class="muted small">${esc(n.n)}</p>
      <label class="pl-label" for="lat-tags">Tags (separated by commas; remove one to take it off)</label>
      <input class="pl-input" id="lat-tags" autocomplete="off" value="${esc(cur.join(", "))}" placeholder="reference, writing">`,
    onOpen: (d) => { const i = d.querySelector("#lat-tags"); i.focus(); i.setSelectionRange(i.value.length, i.value.length); },
    read: (d) => splitTags(d.querySelector("#lat-tags").value),
  });
  if (!v) return;
  try { await send("PATCH", base + encodeURIComponent(n.id), { tags: v }); } catch (e) { return toast({ message: "Could not save the tags: " + e.message, ms: 5000 }); }
  toast({ message: v.length ? `Tags saved: ${v.join(", ")}.` : "Tags removed.", ms: 3500 });
  refresh();
}

async function addToCollection(n) {
  const i = index.get(n.id);
  const mine = S.adj[i].map((ei) => S.snap.edges[ei]).filter((e) => e[2] === "in_collection").map((e) => S.snap.nodes[e[1]]);
  const others = S.snap.nodes.filter((c) => c.t === "collection" && !mine.some((m) => m.id === c.id));
  if (!mine.length) return toast({ message: "This document is not in a collection that can be copied from.", ms: 4000 });
  if (!others.length) return toast({ message: "It is already in every collection.", ms: 4000 });
  const v = await formDialog({
    title: "Add to a collection", confirmLabel: "Add",
    html: `<p class="muted small">${esc(n.n)} is in ${mine.map((m) => "“" + esc(m.n) + "”").join(", ")}. A document is stored once, so it will show in both places and a change to it is a change everywhere.</p>
      <label class="pl-label" for="lat-col">Collection</label>
      <select class="pl-input" id="lat-col">${others.map((c) => `<option value="${esc(c.id)}">${esc(c.n)}</option>`).join("")}</select>`,
    read: (d) => d.querySelector("#lat-col").value,
  });
  if (!v) return;
  try { await send("POST", `collections/${encodeURIComponent(mine[0].id)}/documents/${encodeURIComponent(n.id)}/add-to`, { collection: v }); } catch (e) { return toast({ message: "Could not add it: " + e.message, ms: 5000 }); }
  const target = others.find((c) => c.id === v);
  toast({ message: `Added to “${target.n}”.`, ms: 3500 });
  refresh();
}

// ---------- Build with a local model (text goes to a model only when Start is pressed; the dialog shows what goes first) ----------
let xtimer = 0, xlast = "", xsaid = "";
const fmtN = (n) => Number(n || 0).toLocaleString();

async function buildDialog() {
  if ($("#lat-xstart").disabled) return;
  let provs;
  const btn = $("#lat-xstart"), btnText = btn.textContent;
  btn.disabled = true; btn.textContent = "Looking for models…";   // the runtimes are asked first: say so instead of looking stuck
  try { provs = await api("assistant/providers"); } catch (e) { return toast({ message: "Could not look for models: " + e.message, ms: 5000 }); } finally { btn.disabled = false; btn.textContent = btnText; }
  const list = provs.providers.filter((p) => p.reachable && p.models.length);
  const cols = (S.base?.nodes || []).filter((n) => n.t === "collection");
  const x = { pv: null, tok: 0, timer: 0 };
  const optsP = provs.providers.map((p) => `<option value="${esc(p.id)}"${p.reachable && p.models.length ? "" : " disabled"}>${esc(p.label)}${p.kind === "remote" ? " (remote)" : ""}${p.reachable ? (p.models.length ? "" : " (no chat models)") : " (not reachable)"}</option>`).join("");
  const v = await formDialog({
    title: "Build with a local model", confirmLabel: "Start", wide: true,
    html: `<p class="muted small">FlowlyStack sends the text of the items below to the model you pick, only when you press Start. Nothing is sent before that. Each item goes on its own, between dashed lines, with a fixed instruction; the item's text is treated as data. The answer must name a quote from the item for every entity and link, and FlowlyStack checks the quote is really there: invented ones are rejected and counted. Smaller models give noisier entities; the check keeps them sourced, not necessarily right.</p>
      <label class="pl-label" for="lat-x-scope">What to read</label>
      <select class="pl-input" id="lat-x-scope"><option value="uncovered">Items no run has read yet</option><option value="src:library">All Library prompts</option><option value="src:studio">All Studio prompts</option><option value="src:documents">All documents</option>${cols.map((c) => `<option value="col:${esc(c.id)}">Collection: ${esc(c.n)}</option>`).join("")}</select>
      <label class="lat-check" id="lat-x-skiprow"><input type="checkbox" id="lat-x-skip" checked><span>Skip items a run already read</span></label>
      <label class="pl-label" for="lat-x-prov">Runtime</label>
      <select class="pl-input" id="lat-x-prov">${optsP}</select>
      <label class="pl-label" for="lat-x-model">Model</label>
      <select class="pl-input" id="lat-x-model"></select>
      <p class="lat-xsend" id="lat-x-send" role="status" aria-live="polite">Looking…</p>`,
    onOpen: (d) => {
      const q = (id) => d.querySelector(id);
      const prov = list.find((p) => p.id === "ollama") || list[0];
      if (prov) q("#lat-x-prov").value = prov.id;
      const models = () => (list.find((p) => p.id === q("#lat-x-prov").value)?.models) || [];
      const fillModels = () => {
        const p = q("#lat-x-prov").value, ms = models();
        q("#lat-x-model").innerHTML = ms.map((m) => `<option>${esc(m)}</option>`).join("");
        const def = provs.default || {};
        q("#lat-x-model").value = def.provider === p && ms.includes(def.model) ? def.model : ms[0] || "";
      };
      const scope = () => {
        const v = q("#lat-x-scope").value, skip = q("#lat-x-skip").checked;
        q("#lat-x-skiprow").hidden = v === "uncovered";
        return v === "uncovered" ? { kind: "uncovered" } : v.startsWith("src:") ? { kind: "source", source: v.slice(4), skip_covered: skip } : { kind: "collection", collection: v.slice(4), skip_covered: skip };
      };
      const look = () => {
        clearTimeout(x.timer);
        x.pv = null;
        const out = q("#lat-x-send"), model = q("#lat-x-model").value;
        if (!list.length) { out.textContent = "No runtime with a chat model is reachable. Start Ollama (or add a connection in Settings), then open this again."; return; }
        out.textContent = "Counting…";
        const tok = ++x.tok;
        x.timer = setTimeout(async () => {
          try {
            const pv = await call("POST", "kgraph/extract/preview", { scope: scope(), provider: q("#lat-x-prov").value, model });
            if (tok !== x.tok) return;
            x.pv = pv;
            out.innerHTML = pv.items
              ? `Will send <b>${fmtN(pv.items)}</b> item${pv.items === 1 ? "" : "s"}, about <b>${fmtN(pv.chars)}</b> characters in all${pv.clipped ? ` (${fmtN(pv.clipped)} longer than ${fmtN(pv.cut_at)} characters will be cut)` : ""}, to <b>${esc(pv.model)}</b> at <b>${esc(pv.host)}</b> (${pv.local ? "this computer" : "a remote machine"}).${pv.skipped_covered ? ` ${fmtN(pv.skipped_covered)} already read are skipped.` : ""}${pv.capped ? ` ${fmtN(pv.capped)} more match; a run reads at most 500.` : ""}`
              : `Nothing to read with this choice${pv.skipped_covered ? ` (${fmtN(pv.skipped_covered)} were already read)` : ""}.`;
          } catch (e) { if (tok === x.tok) out.textContent = e.message; }
        }, 200);
      };
      q("#lat-x-prov").addEventListener("change", () => { fillModels(); look(); });
      q("#lat-x-model").addEventListener("change", look);
      q("#lat-x-scope").addEventListener("change", look);
      q("#lat-x-skip").addEventListener("change", look);
      fillModels(); scope(); look();   // scope() first: it hides the "skip" row now, so the dialog does not change height a moment later
      d._x = { scope, x };
    },
    validate: (d) => (!d._x.x.pv ? "Wait for the numbers above, or fix the choice." : !d._x.x.pv.items ? "There is nothing to read with this choice." : ""),
    read: (d) => ({ scope: d._x.scope(), provider: d.querySelector("#lat-x-prov").value, model: d.querySelector("#lat-x-model").value, expect: { items: d._x.x.pv.items, chars: d._x.x.pv.chars } }),
  });
  if (!v) return;
  try { await call("POST", "kgraph/extract/start", v); } catch (e) { return toast({ message: e.message, ms: 7000 }); }
  xlast = "";
  pollRun(true);
}

async function stopRun() {
  try { await call("POST", "kgraph/extract/stop"); } catch (e) { toast({ message: e.message, ms: 4000 }); }
  pollRun(true);
}

/** Show the run's progress (and the last result for a few minutes); keep asking while it runs. The entity layer reloads as items are stored. */
async function pollRun(fresh) {
  clearTimeout(xtimer);
  if ($("#page-lattice").hidden || !built) return;
  let st;
  try { st = await api("kgraph/extract"); } catch { return; }
  const el = $("#lat-xrun"), btn = $("#lat-xstart");
  const running = st.state === "running" || st.state === "stopping";
  btn.disabled = running;
  const recent = st.finished && Date.now() / 1000 - st.finished < 600;
  if (!running && !(recent && st.state !== "idle")) { el.hidden = true; el.innerHTML = ""; return; }
  el.hidden = false;
  const sums = `${fmtN(st.created)} new entit${st.created === 1 ? "y" : "ies"}, ${fmtN(st.edges)} link${st.edges === 1 ? "" : "s"}${st.refused ? `, ${fmtN(st.refused)} rejected (quote not found)` : ""}${st.unreadable ? `, ${fmtN(st.unreadable)} answer${st.unreadable === 1 ? "" : "s"} not usable` : ""}${st.failed ? `, ${fmtN(st.failed)} failed` : ""}`;
  const head = running ? `${st.state === "stopping" ? "Stopping… " : ""}Reading ${fmtN(st.done)} of ${fmtN(st.total)} with ${esc(st.model)}` : st.state === "done" ? `Done: read ${fmtN(st.done)} of ${fmtN(st.total)}` : st.state === "stopped" ? `Stopped after ${fmtN(st.done)} of ${fmtN(st.total)}` : `The run stopped: ${esc(st.error)}`;
  el.innerHTML = `<b>${head}</b>${running && st.current ? `<span class="muted small lat-xcur">${esc(st.current)}</span>` : ""}<span class="small">${sums}.</span>${running ? `<button type="button" class="btn btn-sm btn-glow" data-xstop ${st.state === "stopping" ? "disabled" : ""}>Stop</button>` : st.error && st.state !== "error" ? `<span class="small lat-gone">${esc(st.error)}</span>` : `<span class="muted small">${st.batch ? "It is one run in Entity runs, above: Hide, Undo or Delete it as a whole." : "Nothing was added."}</span>`}`;
  const said = running ? "" : st.state === "done" ? `Local model run finished: ${st.created} new entities, ${st.edges} links.` : st.state === "stopped" ? "Local model run stopped." : "The local model run stopped with an error.";
  if (said && said !== xsaid) { xsaid = said; $("#lat-live").textContent = said; }   // announced once, not on every poll
  const sig = `${st.state}|${st.created}|${st.edges}|${st.done}`;
  if (sig !== xlast) { xlast = sig; if (!fresh || running || st.state !== "idle") load(); }
  if (running) xtimer = setTimeout(() => pollRun(false), 1200);
}

/** A kind was renamed, recoloured, added, deleted or restored (the manager already holds the new list): rebuild the entity nodes and the controls. */
/** While a colour is being dragged in the picker: only the dots and the board (cheap; nothing is saved yet). */
function coloursPreview() {
  if (!S.snap) return;
  typeList(); colList(); legend();
  graph?.redraw();
}

/** A node colour was changed or reset (the dialog already holds the new copy): redraw the board and every dot in the controls. */
function coloursChanged() {
  S.kSig = null;
  if (!S.snap) return;
  typeList(); colList(); legend(); panel(); search();
  graph?.redraw();
}

function kindsChanged() {
  S.kSig = null;
  if (S.base) { rebuild(); apply(); }
}

// ---------- the entity layer: controls, runs, delete (user data; every change can be reversed for a moment) ----------
const cap = (t) => t.charAt(0).toUpperCase() + t.slice(1);
function entityControls() {
  const ent = S.ent, n = ent?.entities.length || 0, runs = ent?.batches || [];
  const cb = $("#lat-entities");
  if (!cb) return;
  cb.disabled = !n;
  cb.checked = n ? S.entities : false;
  $("#lat-ent-row").classList.toggle("is-off", !n);
  $("#lat-ent-n").textContent = n || "";
  const none = $("#lat-ent-none");
  none.hidden = !!n || !!runs.length;
  none.innerHTML = `Nothing yet. An agent with a write token can add entities (people, tools, concepts), each with a quote from its source: see <a href="#/settings">Settings &gt; MCP</a> and the setup guide.`;
  const counts = {};
  for (const e of ent?.entities || []) counts[shown(e.kind)] = (counts[shown(e.kind)] || 0) + 1;   // a deleted kind counts under Other
  $("#lat-kind-list").innerHTML = activeKinds().filter((k) => counts[k.slug]).map((k) => `<label class="lat-check"><input type="checkbox" data-kind="${k.slug}" ${S.kinds[k.slug] === false ? "" : "checked"}><i class="lat-dot lat-dot-entity" style="background:${kindColour(k.slug)}"></i><span title="${esc(k.hint || "")}">${esc(k.label)}</span><span class="gal-n">${counts[k.slug]}</span></label>`).join("");
  $("#lat-runs").hidden = !runs.length;
  $("#lat-run-list").innerHTML = runs.map((b) => {
    const state = b.undone ? "Undone" : b.hidden ? "Hidden" : "";
    const bt = (act, text) => `<button type="button" class="btn btn-sm btn-glow" data-run="${act}" data-id="${esc(b.id)}">${text}</button>`;
    return `<li class="lat-run${b.undone || b.hidden ? " is-off" : ""}"><div class="lat-run-t"><b>${esc(b.note || (b.run ? "Run" : "Addition"))}</b>${state ? ` <span class="lat-state">${state}</span>` : ""}</div>
      <div class="muted small">${b.entities} entit${b.entities === 1 ? "y" : "ies"} · ${b.edges} link${b.edges === 1 ? "" : "s"} · by ${esc(b.by || "unknown")}${b.via === "local" && !/local/i.test(b.by) ? " (local model)" : ""} · ${relTime(b.updated)}</div>
      <div class="lat-run-b">${b.undone ? bt("reinstate", "Restore") : bt(b.hidden ? "show" : "hide", b.hidden ? "Show" : "Hide") + bt("undo", "Undo")}${bt("delete", "Delete")}</div></li>`;
  }).join("");
  if (ent?.damaged?.length) $("#lat-run-list").insertAdjacentHTML("beforeend", `<li class="muted small">${ent.damaged.length} file${ent.damaged.length === 1 ? "" : "s"} in the entity folder could not be read and were left alone.</li>`);
}

const call = (method, path, body) => api(path, { method, ...(body ? { headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : {}) });
async function runAction(kind, id) {
  const b = S.ent?.batches.find((x) => x.id === id);
  const name = b ? (b.note || "this run") : "this run";
  try {
    if (kind === "hide" || kind === "show") { await call("PATCH", `kgraph/batches/${encodeURIComponent(id)}`, { hidden: kind === "hide" }); toast({ message: kind === "hide" ? `Hidden “${name}” from the picture.` : `“${name}” is shown again.`, ms: 3000 }); }
    else if (kind === "undo") { await call("POST", `kgraph/batches/${encodeURIComponent(id)}/undo`); toast({ message: `Undid “${name}”: it is gone from the picture and from agents. Nothing was deleted.`, action: "Restore", onAction: () => runAction("reinstate", id), ms: 8000 }); }
    else if (kind === "reinstate") { await call("POST", `kgraph/batches/${encodeURIComponent(id)}/reinstate`); toast({ message: `“${name}” is back.`, ms: 3000 }); }
    else if (kind === "delete") {
      if (!await confirmDialog({ title: "Delete this run?", message: `“${name}” (${b?.entities ?? "?"} entities, ${b?.edges ?? "?"} links) will be deleted. You can undo it for a few seconds.`, confirmLabel: "Delete" })) return;
      const r = await call("DELETE", `kgraph/batches/${encodeURIComponent(id)}`);
      toast({ message: `Deleted “${name}”.`, action: "Undo", ms: 9000, onAction: async () => { try { await call("POST", "kgraph/batches/restore", { removed: r.removed }); } catch (e) { toast({ message: "Could not restore it: " + e.message, ms: 5000 }); } load(); } });
    }
  } catch (e) { toast({ message: e.message, ms: 5000 }); }
  load();
}

async function deleteEntity(n) {
  if (!await confirmDialog({ title: "Delete this entity?", message: `“${n.n}” and every link that touches it will be deleted from all runs. You can undo it for a few seconds.`, confirmLabel: "Delete entity" })) return;
  try {
    const r = await call("DELETE", `kgraph/entities/${encodeURIComponent(n.id)}`);
    toast({ message: `Deleted “${n.n}”.`, action: "Undo", ms: 9000, onAction: async () => { try { await call("POST", "kgraph/entities/restore", { removed: r.removed }); } catch (e) { toast({ message: "Could not restore it: " + e.message, ms: 5000 }); } load(); } });
  } catch (e) { toast({ message: e.message, ms: 5000 }); }
  S.sel = null;
  load();
}

function tip(n, e) {
  const el = $("#lat-tip");
  if (!n) { el.hidden = true; return; }
  el.hidden = false;
  el.textContent = n.t === "entity" ? `${n.n} · entity (${kindLabel(n.k)})` : `${n.n} · ${TYPE_LABEL[n.t]}`;
  const r = $("#lat-view").getBoundingClientRect();
  el.style.left = Math.min(r.width - 10, Math.max(8, e.clientX - r.left + 14)) + "px";
  el.style.top = Math.max(8, e.clientY - r.top + 14) + "px";
}

function tiny() {
  const snap = S.snap;
  $("#lat-tiny").innerHTML = `<p class="muted">Lattice needs a few more items to draw a useful picture: it has ${snap.n_items} and needs at least ${MIN_ITEMS}. Items appear here as you capture prompts, write in Studio or add documents.${S.ent?.entities.length ? ` The ${S.ent.entities.length} entit${S.ent.entities.length === 1 ? "y" : "ies"} an agent or a local model already added ${S.ent.entities.length === 1 ? "is" : "are"} kept and will show in the picture once there are enough items.` : ""}</p>
    <ul class="lat-nb">${snap.nodes.filter((n) => ITEM_TYPES.includes(n.t)).map((n) => `<li><span class="lat-dot lat-dot-${n.t}" style="background:${dot(n.t, n.id)}"></span> ${esc(n.n)} <span class="muted small">${TYPE_LABEL[n.t]}</span></li>`).join("")}</ul>`;
}

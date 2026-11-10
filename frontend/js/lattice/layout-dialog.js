// The Layout picker: a dialog listing every layout with a small picture of what it does and a line on what it is for. The pictures are drawn from the REAL
// layouts (layouts.js, and a short force simulation for Organic) on a tiny made-up graph, in the user's own node colours, so they always match what the board does.
// Choosing one closes the dialog and the caller applies it (the nodes then glide into place). Nothing here reads the user's data.
import { choiceDialog } from "../dialog.js";
import { LAYOUTS, place } from "./layouts.js";
import { nodeColour } from "./colours.js";

const W = 132, H = 88, PAD = 9;

/** Three projects of 12, 8 and 5 prompts (chained in sessions of three) and three references that link some of them. */
function demo() {
  const nodes = [], links = [];
  const add = (id, t, d) => nodes.push({ id, t, d, r: t === "project" ? 4 : 2.4 });
  for (const [p, n] of [["a", 12], ["b", 8], ["c", 5]]) {
    add("project:" + p, "project", n);
    for (let i = 0; i < n; i++) {
      const id = `${p}-${String(i).padStart(2, "0")}`;
      add(id, "prompt", 2);
      links.push({ s: id, t: "project:" + p, k: "in_project" });
      if (i % 3) links.push({ s: `${p}-${String(i - 1).padStart(2, "0")}`, t: id, k: "followed_by" });
    }
  }
  [["ref:1", "a-01", "b-01"], ["ref:2", "a-05", "c-01"], ["ref:3", "b-04", "c-03"]].forEach(([r, x, y]) => { add(r, "reference", 2); links.push({ s: x, t: r, k: "refers_to" }, { s: y, t: r, k: "refers_to" }); });
  return { nodes, links };
}

/** Where each node of the demo sits for one layout: Map(id -> {x, y}), plus the tree's parent map. */
function positions(kind, { nodes, links }) {
  if (kind === "organic") {   // a short, deterministic force run, the same forces as the board in spirit
    const ns = nodes.map((n) => ({ id: n.id, r: n.r })), ls = links.map((l) => ({ source: l.s, target: l.t }));
    const sim = d3.forceSimulation(ns).stop().force("link", d3.forceLink(ls).id((d) => d.id).distance(14).strength(0.5)).force("charge", d3.forceManyBody().strength(-30))
      .force("x", d3.forceX(0).strength(0.05)).force("y", d3.forceY(0).strength(0.05)).force("collide", d3.forceCollide((d) => d.r + 1));
    for (let i = 0; i < 220; i++) sim.tick();
    return { pos: new Map(ns.map((n) => [n.id, { x: n.x, y: n.y }])) };
  }
  const pos = place(kind, { nodes, links, root: "project:a" });
  return { pos, parent: pos.parent };
}

function thumb(kind, g) {
  const { pos, parent } = positions(kind, g);
  const pts = g.nodes.map((n) => pos.get(n.id)).filter(Boolean);
  const xs = pts.map((p) => p.x), ys = pts.map((p) => p.y), x0 = Math.min(...xs), y0 = Math.min(...ys);
  const s = Math.min((W - 2 * PAD) / Math.max(1, Math.max(...xs) - x0), (H - 2 * PAD) / Math.max(1, Math.max(...ys) - y0));
  const cx = (W - s * (Math.max(...xs) - x0)) / 2, cy = (H - s * (Math.max(...ys) - y0)) / 2;
  const X = (p) => (cx + (p.x - x0) * s).toFixed(1), Y = (p) => (cy + (p.y - y0) * s).toFixed(1);
  const lines = g.links.filter((l) => pos.get(l.s) && pos.get(l.t)).map((l) => {
    const off = parent && parent.get(l.t) !== l.s && parent.get(l.s) !== l.t;   // in the tree a cross line is faint, as on the board
    return `<line x1="${X(pos.get(l.s))}" y1="${Y(pos.get(l.s))}" x2="${X(pos.get(l.t))}" y2="${Y(pos.get(l.t))}" stroke="currentColor" stroke-width="0.7" opacity="${off ? 0.12 : 0.45}"/>`;
  }).join("");
  const dots = g.nodes.map((n) => {
    const p = pos.get(n.id);
    return p ? `<circle cx="${X(p)}" cy="${Y(p)}" r="${n.t === "project" ? 3.6 : n.t === "reference" ? 2.6 : 2}" fill="${nodeColour(n.t, n.id)}"/>` : "";
  }).join("");
  return `<svg viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" aria-hidden="true">${lines}${dots}</svg>`;
}

/** Open the picker. Resolves to the chosen layout name, or null when closed without choosing. */
export function openLayoutPicker(current) {
  const g = demo();
  return choiceDialog({
    title: "Layout", current, intro: "How the board arranges your items. Pick one and the nodes move into place.",
    options: Object.entries(LAYOUTS).map(([value, o]) => ({ value, label: o.label, desc: o.note, thumb: thumb(value, g) })),
  });
}

// Linkshell Tidy up: automatic layout with dagre (vendored as the global `dagre`). Each frame (phase) is laid out left to right on its own from the
// links between its own blocks, and the frames are stacked top to bottom in run order (the earliest block each one holds), so the plan reads like a page of phases.
// Blocks outside every frame go in a row at the top. Pure function: it changes x, y, w and h on the graph it is given and nothing else.
import { orderEdges } from "./projects.js";
const snap = (v) => Math.round(v / 10) * 10;
const PAD = { l: 30, r: 30, t: 40, b: 30 }, FRAME_GAP = 60, START = { x: 30, y: 40 };

/** Positions `blocks` (relative to 0,0) left to right by the links between them; returns the size used. */
function layer(blocks, links) {
  const g = new dagre.graphlib.Graph();
  g.setGraph({ rankdir: "LR", nodesep: 40, ranksep: 80, marginx: 0, marginy: 0 });
  g.setDefaultEdgeLabel(() => ({}));
  const ids = new Set(blocks.map((b) => b.id));
  blocks.forEach((b) => g.setNode(b.id, { width: b.w, height: b.h }));
  links.forEach((l) => { if (ids.has(l.from) && ids.has(l.to) && !g.hasEdge(l.from, l.to)) g.setEdge(l.from, l.to, { weight: l.kind === "order" ? 3 : 1 }); });
  dagre.layout(g);
  blocks.forEach((b) => { const n = g.node(b.id); b.x = snap(n.x - b.w / 2); b.y = snap(n.y - b.h / 2); });
  const x0 = Math.min(...blocks.map((b) => b.x)), y0 = Math.min(...blocks.map((b) => b.y));
  blocks.forEach((b) => { b.x -= x0; b.y -= y0; });
  return { w: Math.max(...blocks.map((b) => b.x + b.w)), h: Math.max(...blocks.map((b) => b.y + b.h)) };
}

/** Block id -> position in the run order (order links, ties by where the block is now). Frames follow their earliest block. */
export function runIndex(S) {
  const by = Object.fromEntries(S.blocks.map((b) => [b.id, b])), indeg = Object.fromEntries(S.blocks.map((b) => [b.id, 0])), out = Object.fromEntries(S.blocks.map((b) => [b.id, []]));
  orderEdges(S).forEach(([a, t]) => { indeg[t]++; out[a].push(t); });
  const key = (id) => by[id].y * 1e4 + by[id].x, ready = Object.keys(indeg).filter((i) => !indeg[i]).sort((a, b) => key(a) - key(b)), idx = {};
  while (ready.length) {
    const i = ready.shift();
    idx[i] = Object.keys(idx).length;
    out[i].forEach((j) => { if (!--indeg[j]) ready.push(j); });
    ready.sort((a, b) => key(a) - key(b));
  }
  S.blocks.forEach((b) => { if (!(b.id in idx)) idx[b.id] = 1e6; });
  return idx;
}

export function tidy(S) {
  let y = START.y;
  const idx = runIndex(S), first = (f) => Math.min(...S.blocks.filter((b) => b.frame === f.id && (b.type === "prompt" || b.type === "start")).map((b) => idx[b.id]), 1e7);   // steps decide; notes and specs have no order links
  const place = (blocks, frame) => {
    if (!blocks.length) return;
    const size = layer(blocks, S.links), ox = START.x + (frame ? PAD.l : 0), oy = y + (frame ? PAD.t : 0);
    blocks.forEach((b) => { b.x += ox; b.y += oy; });
    if (frame) { frame.x = START.x; frame.y = y; frame.w = size.w + PAD.l + PAD.r; frame.h = size.h + PAD.t + PAD.b; }
    y = oy + size.h + (frame ? PAD.b : 0) + FRAME_GAP;
  };
  const known = new Set(S.frames.map((f) => f.id));
  place(S.blocks.filter((b) => !b.frame || !known.has(b.frame)), null);
  [...S.frames].sort((a, b) => first(a) - first(b) || a.y - b.y || a.x - b.x).forEach((f) => place(S.blocks.filter((b) => b.frame === f.id), f));
}

/** The Prompt blocks in the order to run them (the order Tab walks through on the canvas). */
export function runOrder(S) {
  const idx = runIndex(S);
  return S.blocks.filter((b) => b.type === "prompt").sort((a, b) => idx[a.id] - idx[b.id]);
}

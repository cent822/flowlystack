// Pure helpers for a Linkshell graph ({frames, blocks, links}) and the list's thumbnails. No state, no network; the projects themselves
// come from /api/linkshell.

/** The order links as [from, to] block pairs. A link may start or end at a Frame: from a Frame means "after every block in it", into a Frame "before every block in it"
 *  (the same rule as `order_edges` in backend/linkshell.py). */
/** The Specs and References linked to a Prompt, in either direction (the canvas draws no arrows, so a link has no visible direction), each once. */
export function attachedBlocks(g, id) {
  const by = Object.fromEntries(g.blocks.map((b) => [b.id, b])), seen = new Set(), out = [];
  for (const l of g.links) {
    const o = l.to === id ? l.from : l.from === id ? l.to : null, s = o && by[o];
    if (s && ["spec", "reference"].includes(s.type) && !seen.has(s.id)) { seen.add(s.id); out.push(s); }
  }
  return out;
}

export function orderEdges(g) {
  const m = {};
  (g.frames || []).forEach((f) => { m[f.id] = g.blocks.filter((b) => b.frame === f.id).map((b) => b.id); });
  return g.links.filter((l) => l.kind === "order").flatMap((l) => (m[l.from] || [l.from]).flatMap((a) => (m[l.to] || [l.to]).filter((b) => b !== a).map((b) => [a, b])));
}

/** done | skipped | ready | todo. Ready is never stored: a To do step is Ready when every block linked to it by an order link is Done or Skipped. */
export function statusOf(g, b) {
  if (b.status === "done" || b.status === "skipped") return b.status;
  if (b.type !== "prompt") return "todo";
  return orderEdges(g).filter(([a, t]) => t === b.id && ["prompt", "start"].includes(g.blocks.find((x) => x.id === a)?.type)).every(([a]) => ["done", "skipped"].includes(g.blocks.find((o) => o.id === a)?.status)) ? "ready" : "todo";
}

/** A small SVG picture of a project: frames as dashed boxes, blocks as bars coloured by status. `t` is the list API's `thumb`:
 *  {frames: [{x, y, w, h}], blocks: [{x, y, w, h, status}]}. Empty string for a project with no blocks. */
export function thumbOf(t) {
  const all = [...t.frames, ...t.blocks];
  if (!t.blocks.length) return "";
  const x0 = Math.min(...all.map((o) => o.x)), y0 = Math.min(...all.map((o) => o.y)), w = Math.max(...all.map((o) => o.x + o.w)) - x0, h = Math.max(...all.map((o) => o.y + o.h)) - y0;
  const s = Math.min(80 / w, 50 / h), ox = (92 - w * s) / 2 - x0 * s, oy = (62 - h * s) / 2 - y0 * s;
  const r = (o, cls, hh = o.h) => `<rect class="${cls}" x="${(o.x * s + ox).toFixed(1)}" y="${(o.y * s + oy).toFixed(1)}" width="${Math.max(3, o.w * s).toFixed(1)}" height="${Math.max(2.5, hh * s).toFixed(1)}" rx="${cls === "tf" ? 3 : 1.5}"/>`;
  return `<svg class="lk-thumb" viewBox="0 0 92 62" aria-hidden="true">${t.frames.map((f) => r(f, "tf")).join("")}${t.blocks.map((b) => r(b, `tb t-${b.status}`, Math.min(b.h, 30))).join("")}</svg>`;
}

// Use 1 (Documents mode): from file type to collection to cited. Each flow is documents of one file type that sit in one collection and were, or were never,
// cited in a saved chat. The last column exists only when conversations are saved (Settings > Knowledge > Save conversations); without them there is
// nothing to count, and the page says so. A document in several collections is counted under its first one. Thin flows are drawn at a minimum width.
// Click a node to select its documents.
import { css, box, tip, untip, agentColor, esc, note } from "../common.js";
import { S, data, F, apply } from "../state.js";

export function flow(el) {
  const { snap } = data(), hist = snap.use.history;
  if (!F.length) return note(el, "No documents match the filters.");
  const names = Object.fromEntries(snap.collections.map((c) => [c.id, c.name]));
  const colOf = (r) => (r.cols[0] ? names[r.cols[0]] || r.cols[0] : "none"), outOf = (r) => (r.cited ? "Cited in a chat" : "Never cited");
  const { svg, w, h } = box(el, 300), pad = 14, gap = 12, nw = 12, ncol = hist ? 3 : 2, room = Math.min(150, Math.max(70, w * 0.28));
  const nodes = new Map(), links = new Map();
  const node = (col, name, pick) => { const k = col + "|" + name; if (!nodes.has(k)) nodes.set(k, { k, col, name, pick, out: [], in: [] }); return nodes.get(k); };
  for (const r of F) {
    const a = node(0, r.a, (x) => x.a === r.a), c = node(1, colOf(r), (x) => colOf(x) === colOf(r)), steps = [[a, c]];
    if (hist) steps.push([c, node(2, outOf(r), (x) => outOf(x) === outOf(r))]);
    for (const [s, t] of steps) { const lk = s.k + ">" + t.k + ">" + r.a; if (!links.has(lk)) links.set(lk, { s, t, type: r.a, v: 0 }); links.get(lk).v++; }
  }
  const L = [...links.values()], N = [...nodes.values()];
  const minW = 3, k = ((h - 40) / F.length) * 0.8;
  L.forEach((l) => { l.w = Math.max(minW, l.v * k); l.s.out.push(l); l.t.in.push(l); });
  N.forEach((n) => { n.hh = Math.max(d3.sum(n.out, (l) => l.w), d3.sum(n.in, (l) => l.w), minW); n.oo = 0; n.io = 0; n.n = d3.sum(n.out.length ? n.out : n.in, (l) => l.v); });
  const xs = d3.range(ncol).map((c) => pad + (c * (w - 2 * pad - nw - room)) / Math.max(1, ncol - 1));
  for (let c = 0; c < ncol; c++) { let y = 16; N.filter((n) => n.col === c).sort((p, q) => q.hh - p.hh || p.name.localeCompare(q.name)).forEach((n) => { n.x = xs[c]; n.y = y; y += n.hh + gap; }); }
  L.sort((p, q) => p.s.y - q.s.y || p.t.y - q.t.y);
  L.forEach((l) => { l.y0 = l.s.y + l.s.oo + l.w / 2; l.s.oo += l.w; });
  [...L].sort((p, q) => p.t.y - q.t.y || p.s.y - q.s.y).forEach((l) => { l.y1 = l.t.y + l.t.io + l.w / 2; l.t.io += l.w; });
  const on = (n) => !S.sel || S.sel.src !== "use" || S.sel.key === n.k;
  svg.append("g").selectAll("path").data(L).join("path").attr("d", (l) => d3.linkHorizontal()({ source: [l.s.x + nw, l.y0], target: [l.t.x, l.y1] })).attr("fill", "none")
    .attr("stroke", (l) => agentColor(l.type)).attr("stroke-width", (l) => l.w).attr("opacity", 0.5)
    .on("mousemove", (e, l) => tip(e, `<b>${esc(l.s.name)} → ${esc(l.t.name)}</b><br>${l.v} ${l.v === 1 ? "document" : "documents"} · ${esc(l.type)}`)).on("mouseleave", untip);
  const g = svg.append("g").selectAll("g").data(N).join("g").attr("transform", (n) => `translate(${n.x},${n.y})`).style("cursor", "pointer")
    .on("click", (e, n) => { S.sel = S.sel && S.sel.src === "use" && S.sel.key === n.k ? null : { label: `${n.n} ${n.n === 1 ? "document" : "documents"}: ${n.name}`, ids: new Set(F.filter(n.pick).map((r) => r.i)), src: "use", key: n.k }; apply(); });
  g.append("rect").attr("width", nw).attr("height", (n) => n.hh).attr("rx", 3).attr("fill", (n) => (n.col === 0 ? agentColor(n.name) : n.col === 2 ? (n.name === "Never cited" ? css("--text-muted") : css("--series-3")) : css("--series-4"))).attr("opacity", (n) => (on(n) ? 1 : 0.35));
  g.append("text").attr("x", nw + 8).attr("y", (n) => Math.min(n.hh / 2, 10) + 4).attr("class", "gal-lbl").style("paint-order", "stroke").style("stroke", "var(--canvas)").style("stroke-width", 3)
    .text((n) => { const t = `${n.name} · ${n.n}`, m = Math.floor((n.col === ncol - 1 ? room - nw - 8 : Math.max(60, xs[1] - xs[0] - nw - 8)) / 6.4); return t.length > m ? t.slice(0, Math.max(4, m - 1)) + "…" : t; });
}

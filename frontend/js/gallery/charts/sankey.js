// Lifecycle 1: from capture to Studio (own layout, no plugin). Two sources (prompts captured in the Library, prompts written in Studio) flow into what became of
// them (kept as captured, titled or tagged, starred; Studio by status) and then into "edited later" or "never edited". Thin flows are drawn at a minimum
// width so they stay visible (the card says so). Click a Library group to select its prompts.
import { css, box, tip, untip, esc, note } from "../common.js";
import { S, data, apply } from "../state.js";

export function sankey(el) {
  const { snap, R } = data(), Lf = snap.life;
  if (!Lf.library && !Lf.studio) return note(el, "Nothing to follow yet.");
  const { svg, w, h } = box(el, 320), pad = 14, gap = 14, nw = 12, room = Math.min(150, Math.max(70, w * 0.3));
  const lib = { u: R.filter((r) => !(r.title || r.tags.length || r.star)), t: R.filter((r) => (r.title || r.tags.length) && !r.star), s: R.filter((r) => r.star) };
  const nodes = [{ id: "L", name: "Captured in Library", col: 0, br: "L" }, { id: "S", name: "Written in Studio", col: 0, br: "S" }], links = [];
  Lf.lib_groups.forEach((g, i) => {
    const k = "lg" + i;
    nodes.push({ id: k, name: g.name, col: 1, br: "L", sel: ["u", "t", "s"][i] });
    links.push({ s: "L", t: k, v: g.n, br: "L" }, { s: k, t: "E", v: g.edited, br: "L" }, { s: k, t: "N", v: g.n - g.edited, br: "L" });
  });
  Lf.stu_groups.forEach((g, i) => {
    const k = "sg" + i;
    nodes.push({ id: k, name: `Studio: ${g.name}`, col: 1, br: "S" });
    links.push({ s: "S", t: k, v: g.n, br: "S" }, { s: k, t: "E", v: g.edited, br: "S" }, { s: k, t: "N", v: g.n - g.edited, br: "S" });
  });
  nodes.push({ id: "E", name: "Edited later", col: 2, br: "X" }, { id: "N", name: "Never edited", col: 2, br: "X" });
  const L = links.filter((l) => l.v > 0), byId = Object.fromEntries(nodes.map((n) => [n.id, n]));
  const minW = 4, k = ((h - 60) / (Lf.library + Lf.studio)) * 0.8;
  L.forEach((l) => { l.w = Math.max(minW, l.v * k); });
  nodes.forEach((n) => { n.out = L.filter((l) => l.s === n.id); n.in = L.filter((l) => l.t === n.id); n.hh = Math.max(d3.sum(n.out, (l) => l.w), d3.sum(n.in, (l) => l.w), minW); n.oo = 0; n.io = 0; });
  const xs = [pad, (pad + w - nw - room) / 2, w - nw - room];
  [0, 1, 2].forEach((c) => { let y = 16; nodes.filter((n) => n.col === c).forEach((n) => { n.x = xs[c]; n.y = y; y += n.hh + gap; }); });
  L.forEach((l) => { const a = byId[l.s], b = byId[l.t]; l.y0 = a.y + a.oo + l.w / 2; a.oo += l.w; l.y1 = b.y + b.io + l.w / 2; b.io += l.w; l.a = a; l.b = b; });
  const bc = { L: css("--series-2"), S: css("--series-3"), X: css("--series-1") }, ids = { u: lib.u, t: lib.t, s: lib.s };
  svg.append("g").selectAll("path").data(L).join("path").attr("d", (l) => d3.linkHorizontal()({ source: [l.a.x + nw, l.y0], target: [l.b.x, l.y1] })).attr("fill", "none")
    .attr("stroke", (l) => bc[l.br]).attr("stroke-width", (l) => l.w).attr("opacity", 0.55)
    .on("mousemove", (e, l) => tip(e, `<b>${esc(l.a.name)} → ${esc(l.b.name)}</b><br>${l.v} prompts`)).on("mouseleave", untip);
  const g = svg.append("g").selectAll("g").data(nodes).join("g").attr("transform", (n) => `translate(${n.x},${n.y})`).style("cursor", (n) => (n.sel ? "pointer" : "default"))
    .on("click", (e, n) => { if (!n.sel) return; S.sel = S.sel && S.sel.key === n.id ? null : { label: n.name, ids: new Set(ids[n.sel].map((r) => r.i)), src: "life", key: n.id }; apply(); });
  g.append("rect").attr("width", nw).attr("height", (n) => n.hh).attr("rx", 3).attr("fill", (n) => (n.col === 2 ? bc.X : bc[n.br])).attr("opacity", (n) => (S.sel && S.sel.src === "life" && n.sel && S.sel.key !== n.id ? 0.35 : 1));
  g.append("text").attr("x", nw + 8).attr("y", (n) => Math.min(n.hh / 2, 10) + 4).attr("class", "gal-lbl").style("paint-order", "stroke").style("stroke", "var(--canvas)").style("stroke-width", 3)
    .text((n) => { const t = `${n.name} · ${d3.sum(n.out.length ? n.out : n.in, (l) => l.v)}`, m = Math.floor((n.col === 2 ? room - nw - 8 : Math.max(60, xs[1] - xs[0] - nw - 8)) / 6.4); return t.length > m ? t.slice(0, Math.max(4, m - 1)) + "…" : t; });
}

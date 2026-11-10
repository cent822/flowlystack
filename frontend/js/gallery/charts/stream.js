// Pulse 2: streamgraph. One band per topic group, monthly counts; thicker is more prompts that month. Drag across time to pick a range, click a band to focus a group.
import { css, box, tip, untip, cc, esc } from "../common.js";
import { S, data, pass, setRange, apply } from "../state.js";

export function stream(el) {
  const { R, MONTHS, K, snap } = data();
  const { svg, w, h } = box(el, 230);
  if (!snap.clusters.length) return;
  const mk = d3.timeFormat("%Y-%m");
  const cnt = d3.rollup(R.filter((r) => pass(r, "t")), (v) => v.length, (r) => r.m, (r) => r.c);
  const rows = MONTHS.map((d) => { const o = { d }; const m = cnt.get(mk(d)); for (let k = 0; k < K; k++) o[k] = (m && m.get(k)) || 0; return o; });
  const st = d3.stack().keys(d3.range(K)).offset(d3.stackOffsetWiggle).order(d3.stackOrderInsideOut)(rows);
  const x = d3.scaleTime([MONTHS[0], MONTHS.at(-1)], [8, w - 8]);
  const y = d3.scaleLinear([d3.min(st, (s) => d3.min(s, (d) => d[0])), d3.max(st, (s) => d3.max(s, (d) => d[1]))], [h - 26, 8]);
  const area = d3.area().x((d, i) => x(rows[i].d)).y0((d) => y(d[0])).y1((d) => y(d[1])).curve(d3.curveBasis);
  const brush = d3.brushX().extent([[0, 0], [w, h - 22]]).on("end", (e) => {
    if (!e.sourceEvent) return;
    if (!e.selection) { if (S.range) { S.range = null; apply(); } return; }
    setRange(x.invert(e.selection[0]), x.invert(e.selection[1]));
  });
  const gb = svg.append("g").call(brush);
  gb.select(".selection").attr("fill", css("--edge")).attr("fill-opacity", 0.1).attr("stroke", css("--edge"));
  svg.append("g").selectAll("path").data(st).join("path").attr("d", area).attr("fill", (s) => cc(s.key)).attr("opacity", (s) => (S.cluster == null || S.cluster === s.key ? 0.88 : 0.22))
    .style("cursor", "pointer").on("mousemove", (e, s) => tip(e, `<b>${esc(snap.clusters[s.key].label)}</b><br>${snap.clusters[s.key].n} prompts · click to focus`)).on("mouseleave", untip)
    .on("click", (e, s) => { S.cluster = S.cluster === s.key ? null : s.key; apply(); });
  svg.append("g").attr("class", "gal-ax").attr("transform", `translate(0,${h - 22})`).call(d3.axisBottom(x).ticks(Math.max(3, w / 90)).tickSizeOuter(0));
  if (S.range) gb.call(brush.move, [x(new Date(S.range[0])), x(new Date(S.range[1]))]);
}

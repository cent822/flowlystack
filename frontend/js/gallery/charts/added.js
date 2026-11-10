// Shape 1 (Documents mode): when documents were added. Stacked columns, one colour per topic group, one column per day when everything falls within about two
// months, else per month (a streamgraph needs many months of data, and a bulk import is one tall column, which is the truth). "Added" is the day the file was
// imported, not when it was written. Drag across time to pick a range (the shared time filter), click a colour to focus a topic group.
import { css, box, tip, untip, cc, esc, fmtDay, note } from "../common.js";
import { S, data, pass, setRange, apply } from "../state.js";

export function added(el) {
  const { R, K, snap } = data();
  if (!R.length || !snap.clusters.length) return note(el, "Documents are grouped once there are enough of them.");
  const t0 = d3.min(R, (r) => r.t), t1 = d3.max(R, (r) => r.t);
  const unit = t1 - t0 <= 62 * 864e5 ? d3.timeDay : d3.timeMonth, name = unit === d3.timeDay ? "day" : "month";
  const first = unit.floor(new Date(t0)), end = unit.offset(unit.floor(new Date(t1)), 1), pad = Math.max(0, Math.ceil((8 - unit.count(first, end)) / 2));   // at least 8 columns wide, so a lone column is not a wall
  const a = unit.offset(first, -pad), b = unit.offset(end, pad), steps = unit.range(a, b);
  const { svg, w, h } = box(el, 230), left = 34;
  const cnt = d3.rollup(R.filter((r) => pass(r, "t")), (v) => v.length, (r) => +unit.floor(new Date(r.t)), (r) => r.c);
  const rows = steps.map((d) => { const o = { d }; const m = cnt.get(+d); for (let k = 0; k < K; k++) o[k] = (m && m.get(k)) || 0; return o; });
  const st = d3.stack().keys(d3.range(K))(rows);
  const x = d3.scaleTime([a, b], [left, w - 8]);
  const top = d3.max(st, (s) => d3.max(s, (d) => d[1])) || 1, y = d3.scaleLinear([0, top], [h - 26, 8]);
  const bw = Math.max(1, x(unit.offset(steps[0], 1)) - x(steps[0]) - 2);
  const brush = d3.brushX().extent([[left, 0], [w, h - 22]]).on("end", (e) => {
    if (!e.sourceEvent) return;
    if (!e.selection) { if (S.range) { S.range = null; apply(); } return; }
    setRange(x.invert(e.selection[0]), x.invert(e.selection[1]));
  });
  const gb = svg.append("g").call(brush);
  gb.select(".selection").attr("fill", css("--edge")).attr("fill-opacity", 0.1).attr("stroke", css("--edge"));
  svg.append("g").selectAll("g").data(st).join("g").attr("fill", (s) => cc(s.key)).attr("opacity", (s) => (S.cluster == null || S.cluster === s.key ? 0.88 : 0.22))
    .selectAll("rect").data((s) => s.map((d, i) => ({ d, i, k: s.key }))).join("rect").attr("x", (o) => x(rows[o.i].d) + 1).attr("width", bw).attr("y", (o) => y(o.d[1])).attr("height", (o) => Math.max(0, y(o.d[0]) - y(o.d[1])))
    .style("cursor", "pointer").on("mousemove", (e, o) => tip(e, `<b>${esc(snap.clusters[o.k].label)}</b><br>${o.d[1] - o.d[0]} on ${name === "day" ? fmtDay(rows[o.i].d) : d3.timeFormat("%b %Y")(rows[o.i].d)} · click to focus`)).on("mouseleave", untip)
    .on("click", (e, o) => { S.cluster = S.cluster === o.k ? null : o.k; apply(); });
  svg.append("g").attr("class", "gal-ax").attr("transform", `translate(0,${h - 22})`).call(d3.axisBottom(x).ticks(Math.max(3, w / 90)).tickSizeOuter(0));
  svg.append("g").attr("class", "gal-ax").attr("transform", `translate(${left},0)`).call(d3.axisLeft(y).ticks(3).tickFormat(d3.format("d")).tickSize(-4)).select(".domain").remove();
  if (S.range) gb.call(brush.move, [x(new Date(S.range[0])), x(new Date(S.range[1]))].map((v) => Math.max(left, Math.min(w, v))));
}

// Pulse 1: calendar heatmap. One square a day (weeks as columns, Monday first); darker is more prompts. Drag across the weeks to pick a time range.
import { css, box, tip, untip, fmtDay } from "../common.js";
import { S, data, pass, setRange, apply } from "../state.js";

export function calendar(el) {
  const { R, first, last } = data();
  const { svg, w } = box(el, 150);
  const cnt = d3.rollup(R.filter((r) => pass(r, "t")), (v) => v.length, (r) => r.d);
  const wk = d3.timeMonday, left = 30, top = 20, d1 = d3.timeDay.offset(d3.timeDay.floor(last), 1);
  const fit = Math.max(8, Math.floor((w - left - 6) / 7));   // squares stay at least 7px: a narrow card shows the latest weeks only
  const all = wk.count(wk.floor(d3.timeDay.floor(first)), d1) + 1, w0 = all > fit ? wk.offset(wk.floor(last), -(fit - 1)) : wk.floor(d3.timeDay.floor(first)), d0 = w0;
  const weeks = wk.count(w0, d1) + 1, cs = Math.min(18, (w - left - 6) / weeks);
  const max = d3.max(cnt.values()) || 1;
  const col = d3.scaleQuantize([0, max], [1, 2, 3, 4, 5].map((i) => css(`--seq-${i}`)));
  const key = d3.timeFormat("%Y-%m-%d");
  const brush = d3.brushX().extent([[left, top - 3], [left + weeks * cs, top + 7 * cs + 3]]).on("end", (e) => {
    if (!e.sourceEvent) return;   // drawing the brush from the saved range is not a user action
    if (!e.selection) { if (S.range) { S.range = null; apply(); } return; }
    const wi = (x) => Math.max(0, Math.floor((x - left) / cs));
    setRange(wk.offset(w0, wi(e.selection[0])), +wk.offset(w0, wi(e.selection[1]) + 1) - 1);
  });
  const gb = svg.append("g").call(brush);
  gb.select(".selection").attr("fill", css("--edge")).attr("fill-opacity", 0.12).attr("stroke", css("--edge"));
  svg.append("g").selectAll("rect").data(d3.timeDays(w0, d1)).join("rect")
    .attr("x", (d) => left + wk.count(w0, d) * cs).attr("y", (d) => top + ((d.getDay() + 6) % 7) * cs).attr("width", cs - 1.5).attr("height", cs - 1.5).attr("rx", 2)
    .attr("fill", (d) => (cnt.get(key(d)) ? col(cnt.get(key(d))) : css("--seq-0")))
    .attr("opacity", (d) => (!S.range || (+d >= S.range[0] && +d <= S.range[1]) ? 1 : 0.3))
    .on("mousemove", (e, d) => tip(e, `<b>${fmtDay(d)}</b><br>${cnt.get(key(d)) || 0} prompts`)).on("mouseleave", untip);
  let lastX = -99;   // month names that would touch the previous one are left out
  const months = d3.timeMonths(d3.timeMonth.ceil(d0), d1).filter((d) => { const x = left + wk.count(w0, d) * cs; if (x - lastX < 30) return false; lastX = x; return true; });
  svg.append("g").attr("class", "gal-ax").selectAll("text").data(months).join("text")
    .attr("x", (d) => left + wk.count(w0, d) * cs).attr("y", 12).text((d) => (d.getMonth() === 0 ? d.getFullYear() : d3.timeFormat("%b")(d))).style("font-weight", (d) => (d.getMonth() === 0 ? 600 : 400));
  svg.append("g").attr("class", "gal-ax").selectAll("text").data(["Mon", "Wed", "Fri"]).join("text").attr("x", 0).attr("y", (d, i) => top + i * 2 * cs + cs * 0.75).text((d) => d);
  if (S.range) gb.call(brush.move, [left + wk.count(w0, new Date(S.range[0])) * cs, left + (wk.count(w0, new Date(S.range[1])) + 1) * cs]);
}

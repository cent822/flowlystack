import { css, fmt, svgIn, tooltip } from "../util.js";

// GitHub-style calendar: one column per week, one row per weekday, five sequential steps by API calls.
export function calendar(el, { days }, weeks = 26) {
  const cell = 14, gap = 3, left = 34, top = 20, step = cell + gap;
  const end = d3.timeDay.floor(new Date()), startWeek = d3.timeMonday.offset(d3.timeMonday.floor(end), -(weeks - 1));
  const W = left + weeks * step, H = top + 7 * step + 6;
  const val = new Map(days.map((d) => [d.d, d]));
  const all = d3.timeDay.range(startWeek, d3.timeDay.offset(end, 1));
  const max = d3.max(days, (d) => d.n) || 1;
  const levels = ["--seq-0", "--seq-1", "--seq-2", "--seq-3", "--seq-4"].map(css);
  const level = (n) => (n ? Math.min(4, 1 + Math.floor((n / max) * 3.999)) : 0);
  const key = d3.timeFormat("%Y-%m-%d");
  const svg = svgIn(el, W, H);

  const dow = (d) => (d.getDay() + 6) % 7;   // Monday = 0
  ["Mon", "Wed", "Fri"].forEach((l, i) => svg.append("text").attr("x", 0).attr("y", top + dow(new Date(2024, 0, 1 + i * 2)) * step + cell - 2).text(l));
  let lastMonth = -1, lastX = -99;
  svg.selectAll("rect").data(all).join("rect")
    .attr("x", (d) => left + d3.timeMonday.count(startWeek, d3.timeMonday.floor(d)) * step).attr("y", (d) => top + dow(d) * step)
    .attr("width", cell).attr("height", cell).attr("rx", 3).attr("fill", (d) => levels[level(val.get(key(d))?.n || 0)])
    .on("mousemove", (e, d) => { const v = val.get(key(d)); tooltip.show(`<b>${d3.timeFormat("%a, %b %-d")(d)}</b><br>${v ? `${fmt.n(v.n)} API calls<br>${fmt.compact(v.t)} tokens` : "No activity"}`, e); })
    .on("mouseleave", tooltip.hide);
  all.filter((d) => dow(d) === 0).forEach((d) => {
    const lx = left + d3.timeMonday.count(startWeek, d) * step;
    if (d.getMonth() !== lastMonth) { lastMonth = d.getMonth(); if (lx - lastX >= 40) { lastX = lx; svg.append("text").attr("x", lx).attr("y", 12).text(d3.timeFormat("%b")(d)); } }
  });
}

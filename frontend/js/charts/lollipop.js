import { css, fmt, glow, tooltip } from "../util.js";

// Horizontal lollipop: stem + dot per project. Lighter than bars when many categories share one measure.
export function lollipop(el, projects) {
  const rows = projects.slice(0, 8);
  const W = 520, rowH = 40, left = 130, right = 70, H = rows.length * rowH + 8;
  const root = d3.select(el); root.selectAll("*").remove();
  const svg = root.append("svg").attr("class", "chart-svg").attr("viewBox", `0 0 ${W} ${H}`);
  const x = d3.scaleLinear().domain([0, d3.max(rows, (d) => d.tokens) || 1]).range([left, W - right]);
  const g = svg.selectAll("g").data(rows).join("g").attr("transform", (_, i) => `translate(0,${i * rowH + rowH / 2 + 4})`);
  g.append("text").attr("x", left - 14).attr("text-anchor", "end").attr("dy", "0.32em").style("fill", css("--text-secondary")).style("font-size", "14px").text((d) => (d.project.length > 16 ? d.project.slice(0, 15) + "…" : d.project));
  glow(g.append("line").attr("x1", left).attr("x2", left).attr("stroke", css("--series-1")).attr("stroke-width", 5).attr("stroke-linecap", "round"), css("--series-1"))
    .transition().duration(700).delay((_, i) => i * 50).attr("x2", (d) => x(d.tokens));
  glow(g.append("circle").attr("cx", left).attr("r", 6).attr("fill", css("--series-1")).attr("stroke", css("--canvas-soft")).attr("stroke-width", 2), css("--series-1"))
    .transition().duration(700).delay((_, i) => i * 50).attr("cx", (d) => x(d.tokens));
  g.append("text").attr("x", (d) => x(d.tokens) + 16).attr("dy", "0.32em").style("fill", css("--text-primary")).style("font-size", "13px").text((d) => fmt.compact(d.tokens));
  g.append("rect").attr("x", 0).attr("y", -rowH / 2).attr("width", W).attr("height", rowH).attr("fill", "transparent")
    .on("mousemove", (e, d) => tooltip.show(`<b>${d.project}</b><br>${fmt.compact(d.tokens)} tokens<br>${d.sessions} session${d.sessions === 1 ? "" : "s"} · ${fmt.usd(d.cost)}`, e))
    .on("mouseleave", tooltip.hide);
}

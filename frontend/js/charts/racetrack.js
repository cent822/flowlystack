import { css, fmt, glow, svgIn, tooltip } from "../util.js";

// Concentric "race track" rings: each ring is one tool, arc length = call count. Reads like a tally of habits.
const clean = (n) => n.replace(/^mcp__/, "").replace(/__/g, " · ");
export function racetrack(el, tools, unit = "calls") {
  const rows = tools.slice(0, 8);
  const W = 520, H = 330, cx = 285, cy = 165, r0 = 150, th = 14, gap = 5;
  const svg = svgIn(el, W, H);
  const sweep = Math.PI * 1.5, a0 = 0;
  const max = d3.max(rows, (d) => d.n) || 1;
  const g = svg.append("g").attr("transform", `translate(${cx},${cy})`);
  rows.forEach((d, i) => {
    const outer = r0 - i * (th + gap), arc = d3.arc().innerRadius(outer - th).outerRadius(outer).cornerRadius(th / 2);
    const row = g.append("g");
    row.append("path").attr("d", arc({ startAngle: a0, endAngle: sweep })).attr("fill", css("--surface-muted"));
    glow(row.append("path").attr("fill", css("--series-1")), css("--series-1")).attr("d", arc({ startAngle: a0, endAngle: a0 + 0.001 }))
      .transition().duration(800).delay(i * 60).ease(d3.easeCubicOut)
      .attrTween("d", () => { const t = d3.interpolate(0.001, sweep * (d.n / max)); return (k) => arc({ startAngle: a0, endAngle: a0 + t(k) }); });
    row.append("rect").attr("x", -r0).attr("y", -outer).attr("width", r0).attr("height", th).attr("fill", "transparent");
    row.on("mousemove", (e) => tooltip.show(`<b>${clean(d.name)}</b><br>${fmt.n(d.n)} ${unit}`, e)).on("mouseleave", tooltip.hide);
    // labels sit in the empty quadrant, right-aligned against the ring start
    svg.append("text").attr("x", cx - 8).attr("y", cy - outer + th / 2).attr("dy", "0.32em").attr("text-anchor", "end").style("fill", css("--text-secondary")).style("font-size", "12px")
      .text((clean(d.name).length > 22 ? clean(d.name).slice(0, 21) + "…" : clean(d.name)) + "  " + fmt.n(d.n));
  });
}

// Pulse 3: ridgeline. One density ridge per agent over the 24 hours of a day, each scaled to its own peak. Click a ridge to filter by agent.
import { box, tip, untip, agentColor } from "../common.js";
import { S, data, pass, toggleAgent } from "../state.js";

export function ridge(el) {
  const { R, snap } = data();
  const { svg, w, h } = box(el, 230);
  const ags = snap.agents, base = R.filter((r) => pass(r, "a")), left = 70, hh = (h - 34) * 0.38;   // ridge height; the first peak stays inside the drawing, under the caption
  const top = hh + 8, base0 = (i) => (ags.length > 1 ? top + (i * (h - 26 - top)) / (ags.length - 1) : h - 26);
  const x = d3.scaleLinear([0, 24], [left, w - 10]);
  const grid = d3.range(0, 24.01, 0.5), bw = 1.1;
  svg.append("g").attr("class", "gal-ax").attr("transform", `translate(0,${h - 22})`).call(d3.axisBottom(x).tickValues([0, 3, 6, 9, 12, 15, 18, 21, 24]).tickFormat((d) => d + "h").tickSizeOuter(0));
  ags.forEach((a, i) => {
    const rs = base.filter((r) => r.a === a);
    const dens = grid.map((g) => d3.sum(rs, (r) => { let d = Math.abs(r.h - g); d = Math.min(d, 24 - d); return Math.exp(-(d * d) / (2 * bw * bw)); }));
    const m = d3.max(dens) || 1, y0 = base0(i), on = !S.agents.size || S.agents.has(a);
    const ar = d3.area().x((d, j) => x(grid[j])).y0(y0).y1((d) => y0 - (d / m) * hh).curve(d3.curveBasis);
    svg.append("path").datum(dens).attr("d", ar).attr("fill", agentColor(a)).attr("fill-opacity", on ? 0.55 : 0.12).attr("stroke", agentColor(a)).attr("stroke-width", 1.4).attr("stroke-opacity", on ? 1 : 0.3)
      .style("cursor", "pointer").on("click", () => toggleAgent(a))
      .on("mousemove", (e) => tip(e, `<b>${a}</b><br>${rs.length} prompts · peak around ${Math.round(grid[dens.indexOf(m)])}:00`)).on("mouseleave", untip);
    svg.append("text").attr("class", "gal-lbl").attr("x", 0).attr("y", y0 - 4).text(a).attr("opacity", on ? 1 : 0.4);
    svg.append("text").attr("class", "gal-ax-n").attr("x", 0).attr("y", y0 + 10).text(rs.length);
  });
}

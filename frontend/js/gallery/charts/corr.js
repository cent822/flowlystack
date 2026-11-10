// Craft 2: how the measurements relate. Off the diagonal each cell is a scatter of two measurements (column across, row up) for the prompts that pass the filters
// (at most 500 are drawn); on the diagonal a curve shows how common each value is. A dense cloud along a line means the two go together.
import { box, note } from "../common.js";
import { data, F, noun } from "../state.js";
import { features, scalesFor, colouring } from "./features.js";

export function corr(el) {
  const { R, snap } = data(), FEATURES = features();
  if (!R.length) return note(el, `No ${noun()} yet.`);
  const pick = (snap.corr || ["ch", "ln", "q", "h"]).map((k) => FEATURES.find((f) => f.k === k)), sc = scalesFor();
  const { svg, w, h } = box(el, Math.min(430, Math.max(160, el.clientWidth)));   // square cells: a narrow card gets a shorter drawing
  const col = colouring(), n = pick.length, s = Math.min((w - 20) / n, (h - 20) / n), pad = 10, step = Math.max(1, Math.ceil(F.length / 500));
  const sample = F.filter((r, i) => i % step === 0);   // evenly spread, so the picture does not change between redraws
  pick.forEach((fa, i) => pick.forEach((fb, j) => {
    const g = svg.append("g").attr("transform", `translate(${10 + j * s},${10 + i * s})`), inner = s - 2 * pad - 4;
    g.append("rect").attr("width", s - 4).attr("height", s - 4).attr("rx", 4).attr("fill", "none").attr("stroke", "var(--hairline)");
    if (i === j) {
      const bins = d3.bin().domain([0, 1]).thresholds(18).value((r) => sc[fa.k].at(r))(F), mx = d3.max(bins, (b) => b.length) || 1, xx = d3.scaleLinear([0, 1], [pad, s - pad - 4]);
      g.append("path").attr("fill", "var(--edge-soft)").attr("stroke", "var(--edge)").attr("stroke-width", 1.6).attr("d", d3.area().x((b) => xx((b.x0 + b.x1) / 2)).y0(s - pad - 4).y1((b) => s - pad - 4 - (b.length / mx) * (s - 40)).curve(d3.curveBasis)(bins));
      g.append("text").attr("x", 8).attr("y", 16).attr("class", "gal-lbl").style("font-weight", 600).style("font-size", s < 80 ? "10px" : null).text(fa.name);
    } else {
      g.selectAll("circle").data(sample).join("circle").attr("cx", (r) => pad + sc[fb.k].at(r) * inner).attr("cy", (r) => s - pad - 4 - sc[fa.k].at(r) * inner).attr("r", snap.mode === "documents" ? 2.6 : 1.7).attr("fill", (r) => col.color(r)).attr("opacity", snap.mode === "documents" ? 0.9 : 0.45);
    }
  }));
}

import { css } from "../util.js";

// opts.fluid: stretch to the container (used as a faint backdrop behind a KPI number); otherwise a fixed inline sparkline.
export function sparkline(node, values, opts = {}) {
  const fluid = !!opts.fluid;
  const W = fluid ? 200 : 84, H = fluid ? 52 : 24, p = fluid ? 4 : 3;
  const svg = d3.select(node).append("svg").attr("viewBox", `0 0 ${W} ${H}`).attr("aria-hidden", "true");
  if (fluid) svg.attr("preserveAspectRatio", "none"); else svg.attr("width", W).attr("height", H);
  if (values.length < 2) return;
  const x = d3.scaleLinear().domain([0, values.length - 1]).range([fluid ? 0 : p, fluid ? W : W - p - 3]);
  const y = d3.scaleLinear().domain([0, d3.max(values)]).range([H - p, p]);
  const line = d3.line().x((_, i) => x(i)).y(y).curve(d3.curveMonotoneX);
  if (fluid) {
    svg.append("path").attr("class", "sp-area").attr("d", d3.area().x((_, i) => x(i)).y0(H).y1(y).curve(d3.curveMonotoneX)(values));
    svg.append("path").attr("d", line(values)).attr("fill", "none").attr("stroke-width", 1.5).attr("vector-effect", "non-scaling-stroke");
    return;
  }
  svg.append("path").attr("d", line(values)).attr("fill", "none").attr("stroke", css("--series-1")).attr("stroke-width", 1.5).attr("stroke-linejoin", "round");
  svg.append("circle").attr("cx", x(values.length - 1)).attr("cy", y(values.at(-1))).attr("r", 3).attr("fill", css("--series-1"));
}

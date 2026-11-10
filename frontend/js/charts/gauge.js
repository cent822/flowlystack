import { css, fmt, svgIn, reducedMotion, glow } from "../util.js";

const W = 260, H = 210, cx = W / 2, cy = 118, r = 92, th = 14;
const start = -Math.PI * 2 / 3, end = Math.PI * 2 / 3, span = end - start;
const arc = d3.arc().innerRadius(r - th).outerRadius(r).cornerRadius(th / 2);
const level = (v) => (v >= 0.9 ? css("--crit") : v >= 0.75 ? css("--warn") : css("--gauge-fill"));
// `limit`: the value is a real limit reported by the agent, not a comparison with your own peak
const status = (v, limit) => (v >= 0.9 ? (limit ? "Near the limit" : "Near your peak") : v >= 0.75 ? "Running high" : "Comfortable");

// 240-degree radial gauge. It is built once per element and then only *moved*: a live refresh with the
// same value is a no-op, and a new value sweeps from the old one, so the needle never drops back to zero.
export function gauge(el, { value, limit = false }) {
  const v = Math.max(0, Math.min(1, value));
  const key = [css("--gauge-fill"), css("--surface-muted"), css("--edge")].join("|");   // changes with the theme
  const prev = el.__gauge;

  if (prev && prev.key === key) {
    prev.limit = limit;
    if (Math.abs(prev.v - v) < 1e-6) return;
    sweep(prev, v);
    return;
  }

  const svg = svgIn(el, W, H);
  const g = svg.append("g").attr("transform", `translate(${cx},${cy})`);
  g.append("circle").attr("r", r - th - 9).attr("fill", "none").attr("stroke", css("--edge")).attr("stroke-opacity", 0.35).attr("stroke-dasharray", "2 5");
  g.append("path").attr("d", arc({ startAngle: start, endAngle: end })).attr("fill", css("--surface-muted"));
  [0, 0.25, 0.5, 0.75, 1].forEach((t) => {
    const a = start + span * t - Math.PI / 2, r1 = r + 6, r2 = r + (t % 0.5 === 0 ? 12 : 9);
    g.append("line").attr("x1", Math.cos(a) * r1).attr("y1", Math.sin(a) * r1).attr("x2", Math.cos(a) * r2).attr("y2", Math.sin(a) * r2)
      .attr("stroke", css("--edge")).attr("stroke-opacity", 0.7).attr("stroke-width", 1.5).attr("stroke-linecap", "round");
  });
  const fill = g.append("path").attr("fill", level(v));
  glow(fill, level(v));
  const num = g.append("text").attr("y", 8).attr("text-anchor", "middle").style("fill", css("--text-primary")).style("font-family", "var(--font-display)").style("font-size", "38px");
  const stat = g.append("text").attr("y", 32).attr("text-anchor", "middle").style("font-size", "11px").style("letter-spacing", "0.1em").style("text-transform", "uppercase");

  const st = { key, v: 0, fill, num, stat, limit };
  el.__gauge = st;
  paint(st, 0);
  // first build animates up from zero only when no value was ever shown here; a theme redraw jumps straight to the value
  if (prev) paint(st, v); else sweep(st, v);
}

function paint(st, v) {
  st.v = v;
  st.fill.attr("d", arc({ startAngle: start, endAngle: start + span * v })).attr("fill", level(v));
  glow(st.fill, level(v));
  st.num.text(fmt.pct(v));
  st.stat.text(status(v, st.limit));
}

function sweep(st, to) {
  const from = st.v;
  if (reducedMotion()) return paint(st, to);
  const i = d3.interpolate(from, to);
  st.fill.interrupt().transition().duration(800).ease(d3.easeCubicOut).tween("v", () => (t) => paint(st, i(t)));
}

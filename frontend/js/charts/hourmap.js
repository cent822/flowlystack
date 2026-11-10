import { css, fmt, svgIn, tooltip } from "../util.js";

// Weekday x hour matrix. Sequential color = API calls; the lightest step means "none".
export function hourmap(el, { cells }) {
  const left = 40, top = 6, cw = 17, ch = 28, gap = 3, W = left + 24 * (cw + gap), H = top + 7 * (ch + gap) + 20;
  const rows = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
  const idx = new Map(cells.map((c) => [((c.dow + 6) % 7) + "," + c.hr, c]));
  const max = d3.max(cells, (c) => c.n) || 1;
  const ramp = ["--seq-0", "--seq-1", "--seq-2", "--seq-3", "--seq-4", "--seq-5"].map(css);
  const color = (n) => (n ? ramp[1 + Math.min(4, Math.floor((Math.sqrt(n / max)) * 4.999))] : ramp[0]);
  const svg = svgIn(el, W, H);
  rows.forEach((r, i) => svg.append("text").attr("x", 0).attr("y", top + i * (ch + gap) + ch / 2 + 5).style("font-size", "13px").text(r));
  d3.range(0, 24, 3).forEach((h) => svg.append("text").attr("x", left + h * (cw + gap)).attr("y", H - 4).style("font-size", "13px").text(String(h).padStart(2, "0")));
  const data = d3.cross(d3.range(7), d3.range(24));
  svg.selectAll("rect").data(data).join("rect")
    .attr("x", ([, h]) => left + h * (cw + gap)).attr("y", ([d]) => top + d * (ch + gap)).attr("width", cw).attr("height", ch).attr("rx", 3)
    .attr("fill", ([d, h]) => color(idx.get(d + "," + h)?.n || 0))
    .on("mousemove", (e, [d, h]) => { const v = idx.get(d + "," + h); tooltip.show(`<b>${rows[d]} ${String(h).padStart(2, "0")}:00</b><br>${v ? `${fmt.n(v.n)} API calls` : "No activity"}`, e); })
    .on("mouseleave", tooltip.hide);
}

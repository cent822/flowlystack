// Lifecycle 3: version history (Studio). One row for each Studio prompt that has been saved more than once: a dot for each saved version, the newest filled,
// with the message you gave it underneath. Hover a dot for the date.
import { css, box, tip, untip, esc, fmtDay, note } from "../common.js";
import { data } from "../state.js";

export function versions(el) {
  const vt = data().snap.vtrees;
  if (!vt.length) return note(el, "No Studio prompt has more than one saved version yet.");
  const { svg, w } = box(el, 20 + vt.length * 58);
  vt.forEach((p, i) => {
    const y = 28 + i * 58, vs = p.versions, left = Math.min(240, w * 0.4), x = d3.scalePoint(vs.map((v, j) => j), [left, w - 40]).padding(vs.length > 1 ? 0 : 0.5);
    svg.append("text").attr("x", 0).attr("y", y + 4).attr("class", "gal-lbl").style("font-weight", 600).text((p.title || p.id).slice(0, Math.max(8, Math.floor((left - 12) / 6.6))));
    svg.append("line").attr("x1", x(0)).attr("x2", x(vs.length - 1)).attr("y1", y).attr("y2", y).attr("stroke", css("--text-muted")).attr("stroke-width", 2.5);
    svg.selectAll(null).data(vs).join("circle").attr("cx", (v, j) => x(j)).attr("cy", y).attr("r", 6).attr("fill", (v, j) => (j === vs.length - 1 ? css("--edge") : css("--canvas"))).attr("stroke", css("--edge")).attr("stroke-width", 2)
      .on("mousemove", (e, v) => tip(e, `<b>${esc(v.msg || "Version")}</b><br>${fmtDay(new Date(v.ts * 1000))}`)).on("mouseleave", untip);
    svg.selectAll(null).data(vs).join("text").attr("x", (v, j) => x(j)).attr("y", y + 22).attr("text-anchor", "middle").attr("class", "gal-ax-n").text((v) => { const m = Math.floor((w - 40 - left) / Math.max(1, vs.length - 1) / 6.4) - 1; return m < 4 ? "" : (v.msg || "").slice(0, m); });   // messages that would touch are left out (hover a dot)
  });
}

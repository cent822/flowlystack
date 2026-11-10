// Structure 2: topics and their words. Each large bubble is a group of similar prompts; the small bubbles inside are its strongest words (size = how many
// of the group's prompts use the word). Click a group to focus it (click again to clear).
import { box, tip, untip, cc, esc, note } from "../common.js";
import { S, data, apply, noun } from "../state.js";

export function pack(el) {
  const { snap } = data();
  if (!snap.clusters.length) return note(el, "No topic groups yet.");
  const { svg, w, h } = box(el, Math.round(Math.min(400, Math.max(260, el.clientWidth * 1.15))));   // bubbles are limited by the width: a narrow card gets a shorter drawing
  const root = d3.hierarchy({ children: snap.clusters.map((c) => ({ c, children: c.terms.map((t, i) => ({ name: t, value: Math.max(1, c.termn[i]) })) })) })
    .sum((d) => d.value || 0).sort((a, b) => b.value - a.value);
  d3.pack().size([w, h]).padding(5)(root);
  const gid = (d) => (d.depth === 1 ? d.data.c.id : d.parent.data.c.id);
  const g = svg.selectAll("g").data(root.descendants().filter((d) => d.depth > 0)).join("g").attr("transform", (d) => `translate(${d.x},${d.y})`);
  g.append("circle").attr("r", (d) => d.r).attr("fill", (d) => cc(gid(d))).attr("fill-opacity", (d) => (d.depth === 1 ? 0.12 : 0.6))
    .attr("stroke", (d) => (d.depth === 1 ? cc(gid(d)) : "none")).attr("stroke-width", (d) => (d.depth === 1 && S.cluster === gid(d) ? 3 : 1))
    .attr("opacity", (d) => (S.cluster == null || S.cluster === gid(d) ? 1 : 0.3)).style("cursor", "pointer")
    .on("mousemove", (e, d) => tip(e, d.depth === 1 ? `<b>${esc(d.data.c.label)}</b><br>${d.data.c.n} ${noun(d.data.c.n)} · click to focus` : `<b>${esc(d.data.name)}</b><br>in ${d.value} ${noun(d.value)} of this group`)).on("mouseleave", untip)
    .on("click", (e, d) => { S.cluster = S.cluster === gid(d) ? null : gid(d); apply(); });
  g.filter((d) => d.depth === 2 && d.r > 15).append("text").attr("text-anchor", "middle").attr("dy", ".32em").attr("class", "gal-lbl").style("fill", "var(--text-primary)").style("pointer-events", "none")
    .style("font-size", (d) => Math.min(13, d.r / 2.6 + 3) + "px").text((d) => d.data.name);
}

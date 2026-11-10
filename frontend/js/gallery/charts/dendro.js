// Structure 3: which topics are close. Groups that join early (further left) are the most alike. Click a group to focus it (click again to clear).
import { css, box, tip, untip, cc, esc, note } from "../common.js";
import { S, data, apply, noun } from "../state.js";

export function dendro(el) {
  const { snap } = data();
  if (!snap.tree || !snap.tree.children) return note(el, "There is only one group of ${noun()} so far, so there is nothing to compare.");
  const { svg, w, h } = box(el, 230), root = d3.hierarchy(snap.tree), room = Math.min(210, w * 0.45);
  d3.cluster().size([h - 20, w - room - 20])(root);
  const g = svg.append("g").attr("transform", "translate(10,10)"), on = (d) => S.cluster == null || S.cluster === d.data.cluster;
  g.selectAll("path").data(root.links()).join("path").attr("fill", "none").attr("stroke", css("--text-secondary")).attr("stroke-width", 1.8).attr("d", (l) => `M${l.source.y},${l.source.x}V${l.target.x}H${l.target.y}`);
  const leaf = g.selectAll("g").data(root.leaves()).join("g").attr("transform", (d) => `translate(${d.y},${d.x})`).style("cursor", "pointer")
    .on("click", (e, d) => { S.cluster = S.cluster === d.data.cluster ? null : d.data.cluster; apply(); })
    .on("mousemove", (e, d) => tip(e, `<b>${esc(d.data.name)}</b><br>${d.data.value} ${noun(d.data.value)} · click to focus`)).on("mouseleave", untip);
  leaf.append("circle").attr("r", (d) => 4 + Math.sqrt(d.data.value) * 0.35).attr("fill", (d) => cc(d.data.cluster)).attr("opacity", (d) => (on(d) ? 1 : 0.3));
  leaf.append("text").attr("x", 14).attr("dy", ".32em").attr("class", "gal-lbl").text((d) => { const t = `${d.data.name} (${d.data.value})`, max = Math.floor((room - 18) / 6.4); return t.length > max ? t.slice(0, max - 1) + "…" : t; })   // long names are cut in a narrow card; the tooltip has them whole.attr("opacity", (d) => (on(d) ? 1 : 0.4));
}

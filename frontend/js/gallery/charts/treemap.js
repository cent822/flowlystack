// Lifecycle 2: where prompts live. Each large tile is an agent, split into the project folders (or models, where there is no project) its prompts came from;
// area is the number of prompts. Click an agent tile to filter by that agent (click again to clear).
import { box, tip, untip, agentColor, esc, note } from "../common.js";
import { S, data, toggleAgent, noun } from "../state.js";

export function treemap(el) {
  const { snap } = data(), docs = snap.mode === "documents", unit = docs ? "words" : "prompts", fmt = (v) => (docs ? d3.format("~s")(v) : v);   // Documents mode: tile area is words
  if (!snap.treemap.children.length) return note(el, `No ${noun()} yet.`);
  const { svg, w, h } = box(el, 320), root = d3.hierarchy(snap.treemap).sum((d) => d.value || 0).sort((a, b) => b.value - a.value);
  d3.treemap().size([w, h]).paddingInner(2).paddingOuter(2).paddingTop((d) => (d.depth === 1 ? 18 : 2)).round(true)(root);
  const ag = svg.selectAll("g.a").data(root.children).join("g").attr("class", "a").attr("transform", (d) => `translate(${d.x0},${d.y0})`);
  ag.append("rect").attr("width", (d) => d.x1 - d.x0).attr("height", (d) => d.y1 - d.y0).attr("rx", 5).attr("fill", (d) => agentColor(d.data.name))
    .attr("fill-opacity", (d) => (!S.agents.size || S.agents.has(d.data.name) ? 0.16 : 0.05)).attr("stroke", (d) => agentColor(d.data.name)).style("cursor", "pointer")
    .on("click", (e, d) => toggleAgent(d.data.name)).on("mousemove", (e, d) => tip(e, `<b>${esc(d.data.name)}</b><br>${fmt(d.value)} ${unit} · click to filter`)).on("mouseleave", untip);
  ag.append("text").attr("x", 6).attr("y", 13).attr("class", "gal-lbl").style("font-weight", 600).style("pointer-events", "none").text((d) => `${d.data.name} · ${fmt(d.value)}`);
  const lf = svg.selectAll("g.l").data(root.leaves()).join("g").attr("class", "l").attr("transform", (d) => `translate(${d.x0},${d.y0})`).style("pointer-events", "none");
  lf.append("rect").attr("width", (d) => d.x1 - d.x0).attr("height", (d) => d.y1 - d.y0).attr("rx", 3).attr("fill", (d) => agentColor(d.parent.data.name)).attr("fill-opacity", 0.42)
    .style("pointer-events", "all").on("mousemove", (e, d) => tip(e, `<b>${esc(d.data.name)}</b><br>${esc(d.parent.data.name)} · ${fmt(d.value)} ${unit}`)).on("mouseleave", untip);
  lf.filter((d) => d.x1 - d.x0 > 60 && d.y1 - d.y0 > 20).append("text").attr("x", 5).attr("y", 14).attr("class", "gal-lbl").style("fill", "var(--text-primary)")
    .text((d) => d.data.name.slice(0, Math.floor((d.x1 - d.x0) / 7)));
}

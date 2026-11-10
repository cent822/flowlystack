// Craft 1: style of each prompt. Every line is one prompt across six measurements (characters, lines, questions, variables, code blocks, hour of day);
// the colour is the agent. Drag on an axis to keep the prompts in that range; several axes combine. The numbers on an axis are real values; the top of each
// count axis is the 99th percentile ("≥"), longer or bigger prompts are drawn at the top.
import { css, box, note } from "../common.js";
import { S, data, pass, apply, noun } from "../state.js";
import { features, scalesFor, colouring } from "./features.js";

const brushes = {};   // axis key -> [top, bottom] in pixels while a "style" selection is active

export function pcp(el) {
  const { R, snap } = data(), FEATURES = features();
  if (!R.length) return note(el, `No ${noun()} yet.`);
  const { svg, w, h } = box(el, 430), top = 66, bot = h - 34, sc = scalesFor(), xs = d3.scalePoint(FEATURES.map((f) => f.k), [46, w - 40]);
  const y = (f, r) => bot - sc[f.k].at(r) * (bot - top);
  const col = colouring(), rows = R.filter((r) => pass(r, "s")), line = d3.line(), inSel = (r) => !S.sel || S.sel.ids.has(r.i);
  const base = snap.mode === "documents" ? Math.min(0.8, Math.max(0.3, 40 / rows.length)) : 0.13;   // a few documents need darker lines than a thousand prompts
  if (!S.sel || S.sel.src !== "pcp") for (const k in brushes) delete brushes[k];
  svg.append("g").selectAll("path").data(rows).join("path").attr("d", (r) => line(FEATURES.map((f) => [xs(f.k), y(f, r)]))).attr("fill", "none")
    .attr("stroke", (r) => col.color(r)).attr("stroke-width", snap.mode === "documents" ? 1.4 : 1).attr("opacity", (r) => (inSel(r) ? base : base * 0.115));
  for (const f of FEATURES) {
    const g = svg.append("g").attr("transform", `translate(${xs(f.k)},0)`);
    g.append("line").attr("y1", top).attr("y2", bot).attr("stroke", css("--hairline-strong"));
    const tight = (w - 86) / (FEATURES.length - 1) < 70;   // axis names that would touch are tilted
    g.append("text").attr("class", "gal-lbl").attr("transform", tight ? `translate(0,${top - 10}) rotate(-35)` : `translate(0,${top - 22})`).attr("text-anchor", tight ? "start" : "middle").text(f.name);
    g.selectAll(".t").data(sc[f.k].ticks).join("text").attr("class", "gal-ax-n").attr("x", -6).attr("y", (d) => bot - d.t * (bot - top) + 3).attr("text-anchor", "end").text((d) => d.label);
    const br = d3.brushY().extent([[-9, top], [9, bot]]).on("end", (e) => {
      if (!e.sourceEvent) return;
      if (e.selection) brushes[f.k] = e.selection; else delete brushes[f.k];
      const act = Object.keys(brushes);
      if (!act.length) { if (S.sel && S.sel.src === "pcp") { S.sel = null; apply(); } return; }
      const ids = new Set(R.filter((r) => pass(r, "s") && act.every((k) => { const ff = FEATURES.find((q) => q.k === k), py = y(ff, r); return py >= brushes[k][0] && py <= brushes[k][1]; })).map((r) => r.i));
      S.sel = { label: `${ids.size} ${noun(ids.size)} by style`, ids, src: "pcp" };
      apply();
    });
    const gb = g.append("g").call(br);
    gb.select(".selection").attr("fill", css("--edge")).attr("fill-opacity", 0.25).attr("stroke", css("--edge"));
    if (brushes[f.k] && S.sel && S.sel.src === "pcp") gb.call(br.move, brushes[f.k]);
  }
  const lg = svg.append("g").attr("transform", `translate(8,${h - 8})`);
  const stp = Math.min(96, (w - 16) / Math.max(1, col.legend.length));
  col.legend.forEach((a, i) => { lg.append("circle").attr("cx", i * stp + 4).attr("r", 4).attr("fill", a.c); lg.append("text").attr("x", i * stp + 12).attr("y", 4).attr("class", "gal-lbl").text(a.t.length > 11 ? a.t.slice(0, 10) + "…" : a.t); });
}

// Structure 1: map of your prompts. One dot per prompt, placed so that prompts that say similar things sit close together (rings show where they crowd).
// Drag a box to select the prompts inside it, click a dot to select one. "Topic | Agent" in the card title changes the colours.
import { css, box, tip, untip, cc, agentColor, esc, fmtDay, note } from "../common.js";
import { S, data, FS, PM, pass, apply, noun } from "../state.js";

// Documents mode, "Passages": the dots are the passages of the documents (the newest 3,000 that have a stored vector), each carrying its document's row, so colour,
// filters, selection and the box all work through the document. The points come from the passage map (state.js `PM`), built by the server on request.
const REASON = { no_model: "The passage map needs stored embeddings: choose an embedding model in Settings > Knowledge.", no_vectors: "Not enough of your passages have stored embeddings yet; indexing may still be running." };

function passageDots(R) {
  const byId = new Map(R.map((r) => [r.id, r]));
  return PM.part.pts.filter((p) => byId.has(p.d)).map((p) => ({ ...byId.get(p.d), x: p.x, y: p.y, s: p.s, pn: p.n + 1 }));
}

export function map(el) {
  const { R, snap } = data(), passages = snap.mode === "documents" && S.mapView === "passages";
  if (passages && !PM.part) return note(el, PM.status?.state === "building" || !PM.status ? "Placing your passages on the map… this takes a moment the first time." : PM.status.state === "error" ? PM.status.error || "The passage map could not be built." : REASON[PM.status.reason] || "There is no passage map to show.");
  const pts = passages ? passageDots(R) : R.filter((r) => r.x != null);
  if (!pts.length) return note(el, "The map needs stored embeddings or enough different words; there is nothing to place yet.");
  const { svg, w, h } = box(el, 400), pad = 14;
  const x = d3.scaleLinear([0, 1], [pad, w - pad]), y = d3.scaleLinear([0, 1], [h - pad, pad]);
  const dens = d3.contourDensity().x((r) => x(r.x)).y((r) => y(r.y)).size([w, h]).bandwidth(13).thresholds(7)(pts);
  svg.append("g").selectAll("path").data(dens).join("path").attr("d", d3.geoPath()).attr("fill", "none").attr("stroke", css("--hairline-strong")).attr("stroke-width", 1).attr("opacity", 0.8);
  const brush = d3.brush().extent([[0, 0], [w, h]]).on("end", (e) => {
    if (!e.sourceEvent) return;
    if (!e.selection) { if (S.sel && S.sel.src === "map") { S.sel = null; S.mapBr = null; apply(); } return; }
    const [[x0, y0], [x1, y1]] = e.selection;
    S.mapBr = [[x0 / w, y0 / h], [x1 / w, y1 / h]];
    const ids = new Set(pts.filter((r) => pass(r, "s") && x(r.x) >= x0 && x(r.x) <= x1 && y(r.y) >= y0 && y(r.y) <= y1).map((r) => r.i));
    S.sel = ids.size ? { label: `${ids.size} ${noun(ids.size)} from the ${passages ? "passage " : ""}map`, ids, src: "map" } : null;
    apply();
  });
  const gb = svg.append("g").call(brush);   // under the dots, so the dots stay clickable
  gb.select(".selection").attr("fill", css("--edge")).attr("fill-opacity", 0.1).attr("stroke", css("--edge"));
  const col = (r) => (S.mapColor === "agent" ? agentColor(r.a) : cc(r.c)), one = (r) => S.sel && S.sel.src === "dot" && S.sel.ids.has(r.i);
  svg.append("g").selectAll("circle").data(pts).join("circle").attr("cx", (r) => x(r.x)).attr("cy", (r) => y(r.y)).attr("r", (r) => (passages ? (one(r) ? 4 : 1.8) : one(r) ? 6 : 2.6))
    .attr("fill", col).attr("opacity", (r) => (FS.has(r.i) ? 0.85 : 0.07)).style("cursor", "pointer")
    .on("mousemove", (e, r) => tip(e, `${snap.mode === "documents" ? `<b>${esc(r.title)}</b><br>` : ""}${esc(r.s.slice(0, 120))}<br><span class="muted">${esc(r.a)}${passages ? ` · passage ${r.pn}` : ""} · ${fmtDay(new Date(r.t))}</span>`)).on("mouseleave", untip)
    .on("click", (e, r) => { S.sel = { label: `1 ${noun(1)} from the map`, ids: new Set([r.i]), src: "dot" }; apply(); });
  // group names at the middle of their dots; a name that would sit on a bigger group's name is left out (hover a dot to see its words anyway)
  const mid = d3.rollup(pts, (v) => [d3.mean(v, (r) => r.x), d3.mean(v, (r) => r.y)], (r) => r.c), placed = [];
  const names = snap.clusters.filter((c) => mid.has(c.id)).filter((c) => {
    const [mx, my] = mid.get(c.id), bw = c.label.length * 6.4, b = { x0: x(mx) - bw / 2, x1: x(mx) + bw / 2, y0: y(my) - 8, y1: y(my) + 8 };
    if (placed.some((p) => !(b.x1 < p.x0 || b.x0 > p.x1 || b.y1 < p.y0 || b.y0 > p.y1))) return false;
    placed.push(b);
    return true;
  });
  svg.append("g").style("pointer-events", "none").selectAll("text").data(names).join("text").attr("x", (c) => x(mid.get(c.id)[0])).attr("y", (c) => y(mid.get(c.id)[1])).attr("text-anchor", "middle")
    .attr("class", "gal-lbl").style("font-weight", 600).style("paint-order", "stroke").style("stroke", css("--canvas")).style("stroke-width", 4).text((c) => c.label);
  if (S.sel && S.sel.src === "map" && S.mapBr) gb.call(brush.move, [[S.mapBr[0][0] * w, S.mapBr[0][1] * h], [S.mapBr[1][0] * w, S.mapBr[1][1] * h]]);
}

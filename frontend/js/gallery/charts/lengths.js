// Shape 3 (Documents mode): how big the documents are. Columns count documents by length in words on a log scale (most collections have a few huge files next
// to many small ones); the pale columns are all documents, the bright ones those that pass the filters. Click a column to select the documents in that range.
// Below the chart: the shortest, the median and the longest. Words are counted from the passages, so the figure is about right, not exact.
import { css, box, tip, untip, esc, note } from "../common.js";
import { S, data, F, noun, apply } from "../state.js";

export function lengths(el) {
  const { R } = data();
  if (R.length < 2) return note(el, "Not enough documents to compare their length.");
  const lw = (r) => Math.log10(Math.max(1, r.w)), lo = d3.min(R, lw), hi = d3.max(R, lw), dom = hi - lo < 0.3 ? [lo - 0.15, hi + 0.15] : [lo, hi];
  const { svg, w, h } = box(el, 190), left = 30;
  const x = d3.scaleLinear(dom, [left, w - 8]), bin = d3.bin().domain(dom).thresholds(16).value(lw);
  const all = bin(R), part = bin(F), y = d3.scaleLinear([0, d3.max(all, (b) => b.length) || 1], [h - 26, 8]);
  const words = (v) => d3.format(",.0f")(10 ** v);
  const mine = (b) => S.sel && S.sel.src === "len" && S.sel.key === b.x0;
  svg.append("g").selectAll("rect").data(all).join("rect").attr("x", (b) => x(b.x0) + 1).attr("width", (b) => Math.max(1, x(b.x1) - x(b.x0) - 2)).attr("y", (b) => y(b.length)).attr("height", (b) => y(0) - y(b.length))
    .attr("fill", css("--hairline-strong")).attr("opacity", 0.7);
  svg.append("g").selectAll("rect").data(part).join("rect").attr("x", (b) => x(b.x0) + 1).attr("width", (b) => Math.max(1, x(b.x1) - x(b.x0) - 2)).attr("y", (b) => y(b.length)).attr("height", (b) => y(0) - y(b.length))
    .attr("fill", css("--edge")).attr("opacity", (b, i) => (mine(all[i]) ? 1 : 0.75)).style("pointer-events", "none");
  svg.append("g").selectAll("rect").data(all).join("rect").attr("x", (b) => x(b.x0)).attr("width", (b) => Math.max(1, x(b.x1) - x(b.x0))).attr("y", 0).attr("height", h - 22).attr("fill", "transparent").style("cursor", "pointer")
    .on("mousemove", (e, b) => tip(e, `<b>${b.length} ${noun(b.length)}</b><br>${words(b.x0)} to ${words(b.x1)} words · click to select`)).on("mouseleave", untip)
    .on("click", (e, b) => {
      if (mine(b)) S.sel = null;
      else { const ids = new Set(b.map((r) => r.i)); S.sel = ids.size ? { label: `${ids.size} ${noun(ids.size)} of ${words(b.x0)} to ${words(b.x1)} words`, ids, src: "len", key: b.x0 } : null; }
      apply();
    });
  svg.append("g").attr("class", "gal-ax").attr("transform", `translate(0,${h - 22})`).call(d3.axisBottom(x).ticks(Math.max(3, Math.floor(w / 90))).tickFormat((v) => d3.format(".2~s")(10 ** v)).tickSizeOuter(0));
  svg.append("g").attr("class", "gal-ax").attr("transform", `translate(${left},0)`).call(d3.axisLeft(y).ticks(3).tickFormat(d3.format("d")).tickSize(-4)).select(".domain").remove();
  const by = R.slice().sort((p, q) => p.w - q.w), med = d3.median(R, (r) => r.w);
  el.insertAdjacentHTML("beforeend", `<p class="gal-rgs">Shortest: ${esc(by[0].title)} (${by[0].w.toLocaleString()} words) · median ${Math.round(med).toLocaleString()} words · longest: ${esc(by.at(-1).title)} (${by.at(-1).w.toLocaleString()} words)</p>`);
}

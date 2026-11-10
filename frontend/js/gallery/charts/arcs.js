// Vocabulary 3: phrases you repeat. Words sit on a line (the ones used in most phrases first); an arc joins two words you keep writing next to each other,
// thicker means in more prompts. Click an arc to select the prompts that contain that phrase (click again to clear).
import { css, box, tip, untip, cc, esc, note } from "../common.js";
import { S, data, apply, noun } from "../state.js";

const hue = (w) => [...w].reduce((a, c) => a * 31 + c.charCodeAt(0), 7) % 8;   // a phrase whose words are in no topic group still gets one of the eight series colours, never grey

export function arcs(el) {
  const { snap } = data(), bgs = snap.bigrams.slice(0, 22);
  if (!bgs.length) return note(el, "No two-word phrase shows up often enough yet.");
  const { svg, w, h } = box(el, 230);
  const deg = d3.rollup(bgs.flatMap((b) => [b.a, b.b]), (v) => v.length, (d) => d);
  const words = [...deg.keys()].sort((a, b) => deg.get(b) - deg.get(a) || (a < b ? -1 : 1));
  const x = d3.scalePoint(words, [20, w - 20]).padding(0.2), base = h - 70, every = Math.max(1, Math.ceil(16 / (x.step() || 16)));   // labels thin out when words are close
  const tcl = Object.fromEntries(snap.terms.map((t) => [t.w, t.cluster])), nmax = d3.max(bgs, (b) => b.n);
  svg.append("g").selectAll("path").data(bgs).join("path")
    .attr("d", (b) => { const x1 = x(b.a), x2 = x(b.b), r = Math.abs(x2 - x1) / 2; return `M${x1},${base}A${r},${Math.min(r, base - 8)} 0 0 ${x1 < x2 ? 1 : 0} ${x2},${base}`; })
    .attr("fill", "none").attr("stroke", (b) => cc(tcl[b.a] ?? tcl[b.b] ?? hue(b.a))).attr("stroke-linecap", "round").attr("stroke-width", (b) => 0.9 + (2.2 * b.n) / nmax)
    .attr("opacity", (b) => (S.sel && S.sel.src === "phrase" && S.sel.key !== b.a + " " + b.b ? 0.12 : 0.75)).style("cursor", "pointer")
    .on("mousemove", (e, b) => tip(e, `<b>${esc(b.a)} ${esc(b.b)}</b><br>in ${b.n} ${noun(b.n)} · click to select them`)).on("mouseleave", untip)
    .on("click", (e, b) => { const key = b.a + " " + b.b; S.sel = S.sel && S.sel.key === key ? null : { label: `“${key}”`, ids: new Set(b.ids), src: "phrase", key }; apply(); });
  svg.append("g").selectAll("circle").data(words).join("circle").attr("cx", x).attr("cy", base).attr("r", 3.5).attr("fill", css("--text-secondary"));
  svg.append("g").selectAll("text").data(words.filter((d, i) => i % every === 0)).join("text").attr("transform", (d) => `translate(${x(d)},${base + 12}) rotate(40)`).attr("class", "gal-lbl").text((d) => d);
}

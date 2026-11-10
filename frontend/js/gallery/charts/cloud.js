// Vocabulary 1: word cloud (own layout, no plugin). Bigger words are in more prompts. The layout is cached per width and does not move when filters change;
// a word's opacity shows how many of its prompts are still in the filtered set. Click a word to filter by it (click again to clear).
import { box, tip, untip, cc, esc, note } from "../common.js";
import { S, data, FS, apply, noun } from "../state.js";

let lay = null;   // {w, snap, out}: positions only, colours are read at draw time

export function cloud(el) {
  const { snap } = data(), T = snap.terms;
  if (!T.length) return note(el, "Not enough different words yet.");
  const { svg, w, h } = box(el, 340);
  if (!lay || lay.w !== w || lay.snap !== snap) {
    const sc = d3.scaleSqrt([d3.min(T, (t) => t.score), d3.max(T, (t) => t.score)], [13, 46]);
    const ctx = document.createElement("canvas").getContext("2d"), placed = [], out = [];
    for (const t of [...T].sort((a, b) => b.score - a.score)) {
      const fs = sc(t.score);
      ctx.font = `600 ${fs}px "Roboto Condensed"`;
      const tw = ctx.measureText(t.w).width + 8, th = fs * 1.02;
      for (let a = 0; a < 3000; a++) {   // an elliptical spiral from the middle, the first spot where the word touches no other
        const r = a * 0.55, ang = a * 0.33, cx = w / 2 + Math.cos(ang) * r * 1.7, cy = h / 2 + Math.sin(ang) * r;
        const b = { x0: cx - tw / 2, x1: cx + tw / 2, y0: cy - th / 2, y1: cy + th / 2 };
        if (b.x0 < 4 || b.x1 > w - 4 || b.y0 < 4 || b.y1 > h - 4) continue;
        if (placed.some((p) => !(b.x1 < p.x0 || b.x0 > p.x1 || b.y1 < p.y0 || b.y0 > p.y1))) continue;
        placed.push(b);
        out.push({ t, fs, x: cx, y: cy });
        break;
      }
    }
    lay = { w, snap, out };
  }
  svg.selectAll("text").data(lay.out).join("text").attr("x", (d) => d.x).attr("y", (d) => d.y).attr("text-anchor", "middle").attr("dominant-baseline", "central")
    .style("font-size", (d) => d.fs + "px").style("font-weight", 600).style("cursor", "pointer").style("fill", (d) => cc(d.t.cluster))   // style, not the fill attribute: app.css gives every svg text a muted fill
    .attr("opacity", (d) => {
      if (S.word) return S.word === d.t.w ? 1 : 0.22;
      const n = d.t.ids.filter((i) => FS.has(i)).length;
      return 0.18 + 0.82 * Math.min(1, n / Math.max(1, d.t.df));
    })
    .style("text-decoration", (d) => (S.word === d.t.w ? "underline" : "none")).text((d) => d.t.w)
    .on("mousemove", (e, d) => tip(e, `<b>${esc(d.t.w)}</b><br>in ${d.t.df} ${noun(d.t.df)} · click to filter`)).on("mouseleave", untip)
    .on("click", (e, d) => { S.word = S.word === d.t.w ? null : d.t.w; apply(); });
}

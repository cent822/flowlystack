// Vocabulary 2: words that go together. Nodes are words (size = prompts), a line joins two words that often share a prompt (thicker = more often).
// Click a word to filter by it; its links light up. Labels are shown for the bigger words; the rest appear on hover.
import { css, box, tip, untip, cc, esc, note } from "../common.js";
import { S, data, apply, noun } from "../state.js";

let lay = null;

export function network(el) {
  const { snap } = data(), N = snap.network;
  if (!N.nodes.length) return note(el, "Not enough words that appear together yet.");
  const { svg, w, h } = box(el, 340);
  if (!lay || lay.w !== w || lay.snap !== snap) {
    const nodes = N.nodes.map((n) => ({ ...n, r: 4 + Math.sqrt(n.df) * 0.5 })), idx = Object.fromEntries(nodes.map((n) => [n.w, n]));
    const links = N.edges.map((e) => ({ source: idx[e.a], target: idx[e.b], j: e.j, n: e.n }));
    const sim = d3.forceSimulation(nodes).force("link", d3.forceLink(links).distance((l) => Math.max(30, 110 - l.j * 200)).strength((l) => 0.05 + l.j * 0.6)).force("charge", d3.forceManyBody().strength(-320))
      .force("x", d3.forceX(w / 2).strength(0.06)).force("y", d3.forceY(h / 2).strength(0.12)).force("collide", d3.forceCollide((n) => n.r + 24)).stop();
    for (let i = 0; i < 400; i++) sim.tick();   // settled once, drawn still: no jitter while you read it
    nodes.forEach((n) => { n.x = Math.max(n.r + 8, Math.min(w - n.r - 56, n.x)); n.y = Math.max(n.r + 8, Math.min(h - n.r - 8, n.y)); });
    const bigger = new Set([...nodes].sort((a, b) => b.df - a.df).slice(0, 24).map((n) => n.w));
    lay = { w, snap, nodes, links, bigger };
  }
  const { nodes, links, bigger } = lay, near = (l) => S.word && (l.source.w === S.word || l.target.w === S.word);
  svg.append("g").selectAll("line").data(links).join("line").attr("x1", (l) => l.source.x).attr("y1", (l) => l.source.y).attr("x2", (l) => l.target.x).attr("y2", (l) => l.target.y)
    .attr("stroke", (l) => cc(l.source.cluster)).attr("stroke-linecap", "round").attr("stroke-width", (l) => (near(l) ? 1.6 : 0.6) + l.j * 3).attr("opacity", (l) => (S.word ? (near(l) ? 0.95 : 0.08) : 0.5))   // thin lines in the topic colour of their first word
    .on("mousemove", (e, l) => tip(e, `<b>${esc(l.source.w)} + ${esc(l.target.w)}</b><br>together in ${l.n} ${noun(l.n)}`)).on("mouseleave", untip);
  const g = svg.append("g").selectAll("g").data(nodes).join("g").attr("transform", (n) => `translate(${n.x},${n.y})`).style("cursor", "pointer")
    .on("click", (e, n) => { S.word = S.word === n.w ? null : n.w; apply(); })
    .on("mousemove", (e, n) => tip(e, `<b>${esc(n.w)}</b><br>in ${n.df} ${noun(n.df)} · click to filter`)).on("mouseleave", untip);
  g.append("circle").attr("r", (n) => n.r).attr("fill", (n) => cc(n.cluster)).attr("fill-opacity", (n) => (S.word && S.word !== n.w ? 0.3 : 0.85))
    .attr("stroke", (n) => (S.word === n.w ? css("--text-primary") : "none")).attr("stroke-width", 2);
  g.filter((n) => bigger.has(n.w) || S.word === n.w).append("text").attr("x", (n) => n.r + 4).attr("y", 4).attr("class", "gal-lbl").text((n) => n.w).attr("opacity", (n) => (S.word && S.word !== n.w ? 0.45 : 1));
}

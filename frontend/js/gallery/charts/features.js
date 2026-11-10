// The measurements the Craft slide draws (plain counts of what a prompt contains, no judgement about tone) and a scale for each. A scale ends at the 99th
// percentile of ALL prompts (not the filtered ones), so a few huge prompts do not squash everyone else and the axes stay put while you filter; anything
// above it is drawn at the top. Lengths use a log scale and counts a square-root scale, because most prompts are short.
import { data } from "../state.js";
import { agentColor, cc } from "../common.js";

/** How Craft colours a line or dot: by agent / file type when there are two or more, else by topic group, so a single file type is not one dark blue. */
export function colouring() {
  const { snap } = data(), byGroup = (snap.agents || []).length <= 1 && (snap.clusters || []).length > 0;
  return byGroup ? { color: (r) => cc(r.c), legend: snap.clusters.map((c, i) => ({ c: cc(i), t: c.terms?.[0] || `group ${i + 1}` })), what: "topic group" }
    : { color: (r) => agentColor(r.a), legend: (snap.agents || []).map((a) => ({ c: agentColor(a), t: a })), what: snap.mode === "documents" ? "file type" : "agent" };
}

export const FEATURES = [
  { k: "ch", name: "Characters", v: (r) => r.ch, tr: (v) => Math.log10(v + 1), inv: (t) => 10 ** t - 1 },
  { k: "ln", name: "Lines", v: (r) => r.ln, tr: (v) => Math.log10(Math.max(1, v)), inv: (t) => 10 ** t },
  { k: "q", name: "Questions", v: (r) => r.q, tr: Math.sqrt, inv: (t) => t * t },
  { k: "v", name: "Variables", v: (r) => r.v, tr: Math.sqrt, inv: (t) => t * t },
  { k: "cd", name: "Code blocks", v: (r) => r.cd, tr: Math.sqrt, inv: (t) => t * t },
  { k: "h", name: "Hour of day", v: (r) => r.h, tr: (v) => v, inv: (t) => t, cap: 24 },
];

// Documents mode: the snapshot lists its own measurements (`snap.features`: k, name, tr = log | sqrt | lin, optional unit and cap); JSON cannot carry functions, so the transforms are named here.
const TR = { log: { tr: (v) => Math.log10(v + 1), inv: (t) => 10 ** t - 1 }, sqrt: { tr: Math.sqrt, inv: (t) => t * t }, lin: { tr: (v) => v, inv: (t) => t } };
/** The measurements of the snapshot on screen: its own list in Documents mode, the prompt list otherwise. */
export function features() {
  const list = data()?.snap?.features;
  return list ? list.map((f) => ({ ...f, ...TR[f.tr || "lin"], v: (r) => r[f.k] })) : FEATURES;
}

/** "1.2k", "34", "6h", "12%": a raw value as a person reads it. */
export const raw = (f, v) => (f.k === "h" ? Math.round(v) + "h" : f.unit ? (v < 10 ? Math.round(v * 10) / 10 : Math.round(v)) + f.unit : v >= 1000 ? (v / 1000).toFixed(v >= 10000 ? 0 : 1) + "k" : String(Math.round(v)));

/** For each measurement: {cap, at(r) -> 0..1 position of a prompt, ticks: [{t: 0..1, label}]}. */
export function scalesFor() {
  const { R } = data();
  return Object.fromEntries(features().map((f) => {
    let cap = f.cap;
    if (cap == null) {
      const t = R.map((r) => f.tr(f.v(r))).sort(d3.ascending);
      cap = d3.quantileSorted(t, 0.99) || t.at(-1) || 1;
      if (cap <= 0) cap = 1;
    }
    const at = (r) => Math.min(1, Math.max(0, f.tr(f.v(r)) / cap));
    return [f.k, { f, cap, at, ticks: [0, 0.5, 1].map((p) => ({ t: p, label: (p === 1 && f.cap == null ? "≥ " : "") + raw(f, f.inv(p * cap)) })) }];
  }));
}

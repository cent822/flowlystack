// The Gallery's one shared state and the linking rules. A prompt passes when it matches EVERY active filter.
// A chart that is itself a control ignores its own filter (`pass(r, "t")` skips the time range, and so on) so it keeps showing the whole picture.
export const S = { agents: new Set(), cols: new Set(), range: null, word: null, cluster: null, sel: null, mapColor: "cluster", mapView: "docs", mapBr: null };   // mapView: "docs" or "passages" (Documents mode)   // mapBr: the map brush as fractions of its size, so it survives a redraw

let D = null;
export let F = [];            // the prompts that pass every filter
export let FS = new Set();    // their row indices
export const data = () => D;
/** The passage map (Documents mode): fetched on request by home.js, drawn by charts/map.js. `status.state`: building, ready, none (with a reason) or error. */
export let PM = { status: null, part: null };
export function setPassages(status, part) { PM = { status, part }; apply(); }
/** No snapshot yet (a mode switch): charts and panels draw nothing until the next one arrives. */
export function clearSnapshot() { D = null; F = []; FS = new Set(); }
/** "prompts" or "documents" (Documents mode); `n` = 1 gives the singular. */
export const noun = (n) => { const d = D?.snap?.mode === "documents"; return n === 1 ? (d ? "document" : "prompt") : (d ? "documents" : "prompts"); };

/** A new snapshot arrived: index it, and drop filters that no longer mean anything (row numbers change between builds). */
export function setSnapshot(snap) {
  const R = snap.rows;
  const first = R.length ? new Date(R[0].t) : new Date(), last = R.length ? new Date(R.at(-1).t) : new Date();
  const wid = Object.fromEntries((snap.terms || []).map((t) => [t.w, new Set(t.ids)]));
  D = { snap, R, K: (snap.clusters || []).length || 1, WID: wid, first, last,
        MONTHS: d3.timeMonths(d3.timeMonth.floor(first), d3.timeMonth.offset(d3.timeMonth.floor(last), 1)) };
  S.sel = null;
  if (S.word && !wid[S.word]) S.word = null;
  for (const c of [...S.cols]) if (!(snap.collections || []).some((k) => k.id === c)) S.cols.delete(c);
  if (S.cluster != null && S.cluster >= (snap.clusters || []).length) S.cluster = null;
  refilter();
}

/** skip: letters of filters to ignore: a agent (file type in Documents mode), o collection, t time range, w word, c topic group, s free selection. */
export function pass(r, skip = "") {
  if (!skip.includes("a") && S.agents.size && !S.agents.has(r.a)) return false;
  if (!skip.includes("o") && S.cols.size && !(r.cols || []).some((c) => S.cols.has(c))) return false;
  if (!skip.includes("t") && S.range && (r.t < S.range[0] || r.t > S.range[1])) return false;
  if (!skip.includes("w") && S.word && !D.WID[S.word]?.has(r.i)) return false;
  if (!skip.includes("c") && S.cluster != null && r.c !== S.cluster) return false;
  if (!skip.includes("s") && S.sel && !S.sel.ids.has(r.i)) return false;
  return true;
}

function refilter() {
  F = D ? D.R.filter((r) => pass(r)) : [];
  FS = new Set(F.map((r) => r.i));
}

const subs = new Set();
export const subscribe = (fn) => { subs.add(fn); return () => subs.delete(fn); };
let raf = 0;
/** Something in S changed: refilter, then every subscriber redraws (once per animation frame). */
export function apply() {
  cancelAnimationFrame(raf);
  raf = requestAnimationFrame(() => { refilter(); subs.forEach((f) => f()); });
}
export const filtered = () => !!(S.agents.size || S.cols.size || S.range || S.word || S.cluster != null || S.sel);
export function clearAll() { S.agents.clear(); S.cols.clear(); S.range = null; S.word = null; S.cluster = null; S.sel = null; S.mapBr = null; apply(); }
export function setRange(a, b) { S.range = [+a, +b]; apply(); }
/** Switching between Prompts and Documents: nothing of one mode's filters or selection means anything in the other. */
export function resetState() { S.agents.clear(); S.cols.clear(); S.range = null; S.word = null; S.cluster = null; S.sel = null; S.mapBr = null; S.mapColor = "cluster"; S.mapView = "docs"; PM = { status: null, part: null }; }
export function toggleCol(c) { S.cols.has(c) ? S.cols.delete(c) : S.cols.add(c); apply(); }
export function toggleAgent(a) { S.agents.has(a) ? S.agents.delete(a) : S.agents.add(a); apply(); }

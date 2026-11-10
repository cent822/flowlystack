// Lattice layouts: where each node sits. Organic (the force simulation) lives in draw.js; the three arranged layouts are plain functions here, so they can
// be tested without a page: `place(kind, { nodes, links })` returns Map(id -> {x, y}). Nodes carry `id`, `t` (type), `d` (connections) and `r` (radius);
// links carry `s`, `t` (node ids) and `k` (kind). A layout only moves nodes: it never changes what is shown, selected, filtered or stored.
// They are deterministic (the same picture gives the same places), and they use only the lines that are drawn: the project and collection lines decide the groups,
// the "similar" estimates are ignored (they would pull everything together again).
export const LAYOUTS = {
  organic: { label: "Organic", note: "Spaces nodes by their connections. Good for seeing how things link." },
  clusters: { label: "Clusters", note: "Round groups, one per project or collection, items inside. Good for seeing what belongs together." },
  fans: { label: "Fans", note: "A project or collection in the middle, its items in rings around it. Good for counting what a hub holds." },
  tree: { label: "Tree", note: "The chosen item in the middle, everything it connects to in rings by steps away. Pick another item to make it the root. Good for following a chain of links." },
  concentric: { label: "Concentric", note: "The most connected nodes in the middle, then rings outward. Good for seeing what matters most." },
};

const HUB = new Set(["project", "collection"]);
const ITEM = new Set(["prompt", "studio", "document"]);
const GOLDEN = 2.399963;
const byId = (a, b) => (a.id < b.id ? -1 : a.id > b.id ? 1 : 0);

/** Groups of items around a hub (a project, else a collection), the rest of the items by type; every other node is a "floater" (a tag, a reference, an entity). */
export function groupsOf(nodes, links) {
  const hubOf = new Map();   // item id -> { hub, rank }: a project wins over a collection; ties go to the smaller id
  for (const l of links) {
    if (l.k !== "in_project" && l.k !== "in_collection") continue;
    const rank = l.k === "in_project" ? 0 : 1, cur = hubOf.get(l.s);
    if (!cur || rank < cur.rank || (rank === cur.rank && l.t < cur.hub)) hubOf.set(l.s, { hub: l.t, rank });
  }
  const groups = new Map(), floaters = [];
  for (const n of nodes) if (HUB.has(n.t)) groups.set(n.id, { hub: n, members: [] });
  for (const n of nodes) {
    if (HUB.has(n.t)) continue;
    if (!ITEM.has(n.t)) { floaters.push(n); continue; }
    const h = hubOf.get(n.id), key = h && groups.has(h.hub) ? h.hub : "type:" + n.t;   // a hub that is not drawn leaves its items in the group of their type
    if (!groups.has(key)) groups.set(key, { hub: null, members: [] });
    groups.get(key).members.push(n);
  }
  const list = [...groups.values()];
  for (const g of list) g.members.sort(byId);   // ids start with the date: a session stays together
  return { groups: list, floaters };
}

// ---- arranging the members of one group around its hub (offsets from the hub, which sits at 0,0)
function disc(g) {   // a sunflower: dense, round, in id (time) order outwards
  const c = 6.4, off = g.hub ? 3 : 0.6;
  g.members.forEach((n, i) => { const r = c * Math.sqrt(i + off), a = i * GOLDEN; n.lx = Math.cos(a) * r; n.ly = Math.sin(a) * r; });
  g.R = c * Math.sqrt(g.members.length + off) + 10;
}
function rings(g) {   // rings of equal spacing around the hub, the nearest ring first
  const gap = 15, arc = 11;
  let k = 1, at = 0;
  const rho = (kk) => kk * gap + (g.hub ? 4 : 0);
  while (at < g.members.length) {
    const cap = Math.max(6, Math.floor((2 * Math.PI * rho(k)) / arc)), take = Math.min(cap, g.members.length - at);
    for (let j = 0; j < take; j++) { const n = g.members[at + j], a = (j / take) * 2 * Math.PI + k * 0.5; n.lx = Math.cos(a) * rho(k); n.ly = Math.sin(a) * rho(k); }
    at += take; k++;
  }
  g.R = rho(Math.max(1, k - 1)) + 12;
}

/** Clusters (round discs) or Fans (rings), packed together without overlap; tags, references and entities settle between the groups they connect. */
function grouped(kind, nodes, links) {
  const { groups, floaters } = groupsOf(nodes, links);
  const out = new Map();
  if (!groups.length && !floaters.length) return out;
  for (const g of groups) (kind === "fans" ? rings : disc)(g);
  const circles = groups.map((g) => ({ r: (g.R || 12) + 6, g })).sort((a, b) => b.r - a.r);
  d3.packSiblings(circles);
  let extent = 40;
  for (const c of circles) {
    const { g } = c;
    if (g.hub) out.set(g.hub.id, { x: c.x, y: c.y });
    for (const n of g.members) out.set(n.id, { x: c.x + n.lx, y: c.y + n.ly });
    extent = Math.max(extent, Math.hypot(c.x, c.y) + c.r);
  }
  placeFloaters(floaters, links, out, nodes, extent);
  return out;
}

/** A floater starts at the middle of the nodes it is linked to (outside the groups when it has none), then is pushed off whatever it overlaps: the placed nodes are held fixed. */
function placeFloaters(floaters, links, out, nodes, extent) {
  if (!floaters.length) return;
  const nb = new Map(floaters.map((f) => [f.id, []]));
  for (const l of links) {
    if (nb.has(l.s) && out.has(l.t)) nb.get(l.s).push(out.get(l.t));
    if (nb.has(l.t) && out.has(l.s)) nb.get(l.t).push(out.get(l.s));
  }
  const free = [], radius = new Map(nodes.map((n) => [n.id, n.r || 4]));
  let lone = 0;
  floaters.forEach((f) => {
    const ps = nb.get(f.id);
    if (ps.length) free.push({ id: f.id, r: f.r || 4, tx: ps.reduce((s, p) => s + p.x, 0) / ps.length, ty: ps.reduce((s, p) => s + p.y, 0) / ps.length });
    else { const a = lone++ * GOLDEN, rr = extent * 1.08 + 8 * Math.sqrt(lone); free.push({ id: f.id, r: f.r || 4, tx: Math.cos(a) * rr, ty: Math.sin(a) * rr }); }
  });
  for (const f of free) { f.x = f.tx; f.y = f.ty; }
  if (nodes.length <= 6000) {   // a short relaxation: floaters collide with everything, are drawn a little to their middle, the rest stays put
    const fixed = [...out].map(([id, p]) => ({ id, x: p.x, y: p.y, fx: p.x, fy: p.y, r: radius.get(id) || 4 }));
    const sim = d3.forceSimulation([...fixed, ...free]).stop()
      .force("collide", d3.forceCollide((d) => d.r + 2.5).iterations(2))
      .force("x", d3.forceX((d) => (d.tx === undefined ? d.x : d.tx)).strength((d) => (d.tx === undefined ? 0 : 0.18)))
      .force("y", d3.forceY((d) => (d.ty === undefined ? d.y : d.ty)).strength((d) => (d.ty === undefined ? 0 : 0.18)));
    for (let i = 0; i < 70; i++) sim.tick();
  }
  for (const f of free) out.set(f.id, { x: f.x, y: f.y });
}

/** Rings by connections: the most connected node in the middle, then rings outward; inside a ring the nodes are sorted by type so each colour sits together. */
function concentric(nodes) {
  const out = new Map();
  if (!nodes.length) return out;
  const order = nodes.slice().sort((a, b) => b.d - a.d || (a.t < b.t ? -1 : a.t > b.t ? 1 : 0) || byId(a, b));
  const gap = 13, arc = 12;
  out.set(order[0].id, { x: 0, y: 0 });
  let k = 1, at = 1;
  while (at < order.length) {
    const rho = k * gap, cap = Math.max(6, Math.floor((2 * Math.PI * rho) / arc)), ring = order.slice(at, at + cap);
    ring.sort((a, b) => (a.t < b.t ? -1 : a.t > b.t ? 1 : 0) || b.d - a.d || byId(a, b));
    ring.forEach((n, j) => { const a = (j / ring.length) * 2 * Math.PI - Math.PI / 2; out.set(n.id, { x: Math.cos(a) * rho, y: Math.sin(a) * rho }); });
    at += ring.length; k++;
  }
  return out;
}

/** A radial tree from one root: the root in the middle, each ring one step further along the lines that are drawn (explicit lines are followed first, "similar" estimates only reach what they
 *  did not; the lines that are not a branch are `out.parent`'s complement and are drawn faintly). What the root cannot reach waits in a block
 *  below. The root is `root` (an id) or, when there is none, the best connected project or collection. The returned Map has `.root` = the id used. */
function tree(nodes, links, rootId) {
  const out = new Map();
  if (!nodes.length) return out;
  const idx = new Map(nodes.map((n) => [n.id, n]));
  const best = (a, b) => b.d - a.d || byId(a, b);
  const root = rootId && idx.has(rootId) ? rootId : (nodes.filter((n) => HUB.has(n.t)).sort(best)[0] || nodes.slice().sort(best)[0]).id;
  out.root = root;
  const adj = new Map(nodes.map((n) => [n.id, []]));
  for (const l of links) {
    if (!adj.has(l.s) || !adj.has(l.t)) continue;
    const rank = l.k === "similar" ? 1 : 0;
    adj.get(l.s).push({ to: l.t, rank }); adj.get(l.t).push({ to: l.s, rank });
  }
  for (const list of adj.values()) list.sort((x, y) => (x.to < y.to ? -1 : x.to > y.to ? 1 : 0));
  // breadth first: the explicit lines first (the real chains of links), then the "similar" estimates for whatever they did not reach; a child is one ring beyond its parent
  const parent = new Map(), kids = new Map(nodes.map((n) => [n.id, []])), seen = new Set([root]), depthOf = new Map([[root, 0]]), queue = [root];
  const run = (maxRank) => {
    for (let i = 0; i < queue.length; i++) {
      const u = queue[i];
      for (const { to, rank } of adj.get(u)) {
        if (rank > maxRank || seen.has(to)) continue;
        seen.add(to); parent.set(to, u); kids.get(u).push(to); depthOf.set(to, depthOf.get(u) + 1); queue.push(to);
      }
    }
  };
  run(0); run(1);
  out.parent = parent;
  const h = d3.hierarchy({ id: root }, (n) => kids.get(n.id).map((id) => ({ id })));
  d3.tree().size([2 * Math.PI, 1]).separation((a, b) => (a.parent === b.parent ? 1 : 1.5))(h);
  const levels = [];
  h.each((n) => { (levels[n.depth] ||= []).push(n); });
  const ARC = 12, GAP = 30;
  let rho = 0, rMax = 0;
  levels.forEach((lv, d) => {
    rho = d === 0 ? 0 : Math.max(rho + GAP, (lv.length * ARC) / (2 * Math.PI));
    lv.sort((a, b) => a.x - b.x);
    if (d > 0) {   // keep neighbours at least one arc apart along the ring; squeeze the ring a little if the last one would pass the first
      const gap = ARC / rho;
      for (let i = 1; i < lv.length; i++) lv[i].x = Math.max(lv[i].x, lv[i - 1].x + gap);
      const span = lv[lv.length - 1].x - lv[0].x, room = 2 * Math.PI - gap;
      if (lv.length > 1 && span > room) { const f = room / span; for (const n of lv) n.x = lv[0].x + (n.x - lv[0].x) * f; }
    }
    for (const n of lv) out.set(n.data.id, { x: Math.cos(n.x - Math.PI / 2) * rho, y: Math.sin(n.x - Math.PI / 2) * rho });
    rMax = rho;
  });
  const rest = nodes.filter((n) => !out.has(n.id)).sort((a, b) => (a.t < b.t ? -1 : a.t > b.t ? 1 : 0) || byId(a, b));
  if (rest.length) {   // not reachable from the root over the drawn lines: a block of their own below the rings
    const cols = Math.max(4, Math.ceil(Math.sqrt(rest.length * 1.8))), sp = 13, y0 = rMax + 80;
    rest.forEach((n, i) => out.set(n.id, { x: ((i % cols) - (cols - 1) / 2) * sp, y: y0 + Math.floor(i / cols) * sp }));
  }
  return out;
}

/** Positions for `kind` ("clusters" | "fans" | "concentric" | "tree"). Organic is not here: it is the live simulation. Returns Map(id -> {x, y}). */
export function place(kind, { nodes, links, root }) {
  if (kind === "tree") return tree(nodes, links, root);
  if (kind === "concentric") return concentric(nodes);
  if (kind === "clusters" || kind === "fans") return grouped(kind, nodes, links);
  return new Map();
}

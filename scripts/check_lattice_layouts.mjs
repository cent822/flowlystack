// Checks for Lattice's arranged layouts, frontend/js/lattice/layouts.js. Plain asserts, no server and no browser; needs Node (any recent version):
//
//     node scripts/check_lattice_layouts.mjs
//
// It runs on synthetic nodes and lines only.
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import path from "node:path";

const here = path.dirname(fileURLToPath(import.meta.url));
globalThis.d3 = createRequire(import.meta.url)(path.join(here, "../frontend/vendor/d3.min.js"));   // layouts.js uses the global d3, as in the page
const { place, groupsOf, LAYOUTS } = await import("../frontend/js/lattice/layouts.js");
const step = (m) => console.log("ok  ", m);

// a world: 3 projects (40, 12 and 3 prompts), 1 collection with 6 documents, 20 prompts in no group, 5 Studio prompts, 2 tags, 4 references, 2 entities
const nodes = [], links = [];
const add = (id, t, d = 1) => { nodes.push({ id, t, d, r: 4 + Math.min(5, d / 4) }); return id; };
for (const [p, n] of [["alpha", 40], ["beta", 12], ["gamma", 3]]) {
  add("project:" + p, "project", n);
  for (let i = 0; i < n; i++) { const id = add(`2026${p}-${String(i).padStart(3, "0")}`, "prompt", 2); links.push({ s: id, t: "project:" + p, k: "in_project" }); if (i) links.push({ s: `2026${p}-${String(i - 1).padStart(3, "0")}`, t: id, k: "followed_by" }); }
}
add("col-1", "collection", 6);
for (let i = 0; i < 6; i++) { const id = add("kd-" + i, "document", 1); links.push({ s: id, t: "col-1", k: "in_collection" }); }
for (let i = 0; i < 20; i++) add("2026loose-" + i, "prompt", 0);
for (let i = 0; i < 5; i++) add("ps-" + i, "studio", 0);
add("tag:x", "tag", 3); links.push({ s: "ps-0", t: "tag:x", k: "tagged" }, { s: "ps-1", t: "tag:x", k: "tagged" });
for (let i = 0; i < 4; i++) { add("ref:" + i, "reference", 2); links.push({ s: "2026alpha-00" + i, t: "ref:" + i, k: "refers_to" }, { s: "2026beta-00" + i, t: "ref:" + i, k: "refers_to" }); }
for (let i = 0; i < 2; i++) add("ent-" + i, "entity", 0);   // not linked to anything drawn
links.push({ s: "2026alpha-005", t: "2026beta-005", k: "similar" });   // an estimate: it must not move anything

const dist = (a, b) => Math.hypot(a.x - b.x, a.y - b.y);
const minGap = (m) => { const a = [...m.values()]; let best = Infinity; for (let i = 0; i < a.length; i++) for (let j = i + 1; j < a.length; j++) best = Math.min(best, dist(a[i], a[j])); return best; };

for (const kind of ["clusters", "fans", "concentric"]) {
  const m = place(kind, { nodes, links });
  assert.equal(m.size, nodes.length, `${kind}: every node gets a place`);
  for (const n of nodes) { const p = m.get(n.id); assert.ok(p && Number.isFinite(p.x) && Number.isFinite(p.y), `${kind}: ${n.id} has finite coordinates`); }
  assert.ok(minGap(m) > 2.5, `${kind}: no two nodes sit on top of each other (${minGap(m).toFixed(2)})`);
  const again = place(kind, { nodes: nodes.map((n) => ({ ...n })), links });
  for (const n of nodes) { assert.equal(again.get(n.id).x.toFixed(3), m.get(n.id).x.toFixed(3)); assert.equal(again.get(n.id).y.toFixed(3), m.get(n.id).y.toFixed(3)); }
}
step("every arranged layout places every node with finite coordinates, no overlap, and gives the same places twice");

const cl = place("clusters", { nodes, links });
const near = (id, hub, max) => dist(cl.get(id), cl.get(hub)) <= max;
const alphaR = Math.max(...nodes.filter((n) => n.id.startsWith("2026alpha-")).map((n) => dist(cl.get(n.id), cl.get("project:alpha"))));
assert.ok(alphaR < 6.4 * Math.sqrt(45) + 12, "an alpha prompt is inside its disc");
assert.ok(dist(cl.get("project:alpha"), cl.get("project:beta")) > alphaR, "the groups do not overlap");
assert.ok(near("kd-0", "col-1", 60), "documents sit around their collection");
const { groups, floaters } = groupsOf(nodes, links);
assert.deepEqual(groups.map((g) => (g.hub ? g.hub.id : "type")).sort(), ["col-1", "project:alpha", "project:beta", "project:gamma", "type", "type"], "groups: 3 projects, a collection, loose prompts and Studio prompts by type");
assert.deepEqual(floaters.map((f) => f.t).sort(), ["entity", "entity", "reference", "reference", "reference", "reference", "tag"].sort(), "tags, references and entities are floaters");
step("clusters: items sit inside the disc of their project or collection, groups do not overlap, loose items group by type, a similar line moves nothing");

const noSim = place("clusters", { nodes, links: links.filter((l) => l.k !== "similar") });
for (const n of nodes) { assert.equal(noSim.get(n.id).x.toFixed(3), cl.get(n.id).x.toFixed(3)); }
step("the similar estimates are ignored by the layouts (same places without them)");

const f = place("fans", { nodes, links });
const ring = nodes.filter((n) => n.id.startsWith("2026alpha-")).map((n) => dist(f.get(n.id), f.get("project:alpha")));
assert.ok(Math.min(...ring) >= 15, "fans: nothing sits closer to the hub than the first ring");
assert.ok(new Set(ring.map((r) => Math.round(r))).size <= 4, "fans: 40 prompts sit on a few rings");
step("fans: the hub in the middle, its items on rings around it");

const c = place("concentric", { nodes, links });
const top = nodes.slice().sort((a, b) => b.d - a.d)[0];
assert.deepEqual(c.get(top.id), { x: 0, y: 0 }, "the most connected node is in the middle");
const deg = (n) => n.d;
const avgR = (pred) => { const a = nodes.filter(pred); return a.reduce((s, n) => s + Math.hypot(c.get(n.id).x, c.get(n.id).y), 0) / a.length; };
assert.ok(avgR((n) => deg(n) >= 6) < avgR((n) => deg(n) === 0), "more connected nodes sit nearer the middle");
step("concentric: the most connected node in the middle, better connected nodes nearer");

// tree: a radial tree from a root over the drawn lines
const T = place("tree", { nodes, links, root: "2026alpha-000" });
assert.equal(T.size, nodes.length, "tree: every node is placed");
assert.equal(T.root, "2026alpha-000");
assert.deepEqual(T.get("2026alpha-000"), { x: 0, y: 0 }, "the root is in the middle");
const rad = (id) => Math.hypot(T.get(id).x, T.get(id).y);
assert.ok(rad("project:alpha") > 0 && rad("project:alpha") < rad("2026alpha-020"), "one step away is nearer than many steps away");
assert.ok(rad("2026alpha-001") > 0 && rad("2026alpha-001") <= rad("2026alpha-039"), "rings grow with the steps");
assert.ok(minGap(T) > 2.5, `tree: no two nodes on top of each other (${minGap(T).toFixed(2)})`);
const rings = new Set(nodes.filter((n) => n.id.startsWith("2026alpha-")).map((n) => Math.round(rad(n.id))));
assert.ok(rings.size <= 4, "tree: 40 prompts of one project sit on a few rings (project hub is one step from all of them)");
const ent = T.get("ent-0");
assert.ok(ent.y > Math.max(...nodes.filter((n) => n.t === "prompt" && n.id.startsWith("2026alpha")).map((n) => T.get(n.id).y)) - 1, "what the root cannot reach waits in a block below the rings");
const T2 = place("tree", { nodes: nodes.map((n) => ({ ...n })), links, root: "2026alpha-000" });
for (const n of nodes) assert.equal(T2.get(n.id).x.toFixed(3), T.get(n.id).x.toFixed(3));
step("tree: root in the middle, rings by steps, no overlap, unreachable nodes in a block below, deterministic");
const D = place("tree", { nodes, links });
assert.ok(D.root === "project:alpha", `without a root the best connected project is used (${D.root})`);
assert.equal(place("tree", { nodes, links, root: "no-such-id" }).root, "project:alpha", "an unknown root falls back to the default");
const tn = nodes.filter((n) => n.t === "prompt").slice(0, 3);
const T3 = place("tree", { nodes: tn, links: [] });
assert.equal(T3.size, 3, "no lines at all: the root and a block");
assert.equal(place("tree", { nodes: [], links: [] }).size, 0);
// the similar estimates only count when they are drawn: a prompt reached only by a similar line is one step from the root, and an explicit way in wins
const sim = place("tree", { nodes, links: [{ s: "2026alpha-000", t: "2026loose-0", k: "similar" }, ...links], root: "2026alpha-000" });
assert.ok(rad2(sim, "2026loose-0") > 0 && rad2(sim, "2026loose-0") < 40, "a drawn similar line is a way in");
function rad2(m, id) { return Math.hypot(m.get(id).x, m.get(id).y); }
step("tree: default root is the best connected project, an unknown root falls back, no lines or no nodes do not crash, drawn similar lines count");

assert.equal(place("clusters", { nodes: [], links: [] }).size, 0);
assert.equal(place("concentric", { nodes: [], links: [] }).size, 0);
assert.equal(place("organic", { nodes, links }).size, 0, "organic is the live simulation, not a function here");
const one = place("clusters", { nodes: [{ id: "a", t: "prompt", d: 0, r: 4 }], links: [] });
assert.equal(one.size, 1);
step("empty graphs, one node and the organic name do not crash");

assert.deepEqual(Object.keys(LAYOUTS), ["organic", "clusters", "fans", "tree", "concentric"]);
console.log("all layout checks passed");

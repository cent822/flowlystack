// Lattice: the force graph, drawn on a canvas. Plain DOM and the global d3 (forces, zoom), no framework.
// One code path for every size: a canvas keeps thousands of nodes smooth, and everything it shows is also in the text panel next to it (accessibility).
// Colours are read from the CSS tokens at draw time, so a theme switch only needs `redraw()`.
import { css, reducedMotion } from "../util.js";
import { isDark } from "../theme.js";
import { kindColour } from "./kinds.js";
import { TYPE_COLOR, nodeColour } from "./colours.js";
import { place } from "./layouts.js";

export { TYPE_COLOR };
export const TYPE_LABEL = { prompt: "Library prompt", studio: "Studio prompt", document: "Document", collection: "Collection", tag: "Tag", project: "Project", reference: "Reference", entity: "Entity", linkshell: "Linkshell project" };
const radius = (n) => (n.t === "collection" ? 5.5 + Math.min(7, Math.sqrt(n.d) * 0.8) : n.t === "tag" ? 4 + Math.min(5, Math.sqrt(n.d) * 0.6) : n.t === "project" ? 5 + Math.min(7, Math.sqrt(n.d) * 0.7) : n.t === "reference" ? 3.5 + Math.min(6, Math.sqrt(n.d) * 0.8) : n.t === "linkshell" ? 4.5 + Math.min(6, Math.sqrt(n.d) * 0.8) : 3 + Math.min(6, Math.sqrt(n.d) * 0.9));
const clip = (s, n) => (s.length > n ? s.slice(0, n - 1) + "…" : s);

/** `cb`: { select(id|null), hover(id|null) }. Returns the control object the page uses. */
export function createGraph(host, cb) {
  const canvas = document.createElement("canvas");
  canvas.className = "lat-canvas";
  host.append(canvas);
  const ctx = canvas.getContext("2d");
  let W = 0, H = 0, dpr = 1, tf = d3.zoomIdentity;
  let nodes = [], links = [], byId = new Map(), adj = new Map();
  const pos = new Map();                      // id -> {x, y}: kept for the visit so a filter change does not re-shuffle the picture
  let want = false, sim = null, sel = null, hover = null, hl = null, drag = null, raf = 0, label = true;
  // Layout: "organic" is the live force simulation below; the others are arranged by layouts.js (a plain function) and glide into place. The focus view is always organic.
  let layoutName = "organic", layoutChanged = false, curKind = "organic", tweenId = 0, treeRoot = null, curRoot = null;
  // Motion: a cosmetic float. Every node drifts a few screen pixels on its own slow cycle and the whole picture breathes a little, but only while drawing:
  // the layout, the saved positions and the force simulation are not touched. A ~30 fps loop runs while the picture is visible (`live()`); it is off for
  // reduced-motion users and for `?static` (headless screenshots), and the page has a pause button.
  let motion = !reducedMotion() && !new URLSearchParams(location.search).has("static"), loop = 0, lastDraw = 0, bs = 1, br = 0;
  const FLOAT_PX = 2.5, FLOAT_PX_BIG = 1.2, BIG = 4000, FRAME_MS = 30, LAYER_LINKS = 1500;
  const live = () => motion && !reducedMotion() && !document.hidden && host.offsetParent !== null && nodes.length > 0;
  function startLoop() { if (!loop && live()) loop = requestAnimationFrame(step); }
  function step(ts) { loop = 0; if (!live()) return; if (ts - lastDraw >= FRAME_MS) draw(); startLoop(); }   // a draw the page asked for (hover, zoom, layout) counts: no double drawing
  document.addEventListener("visibilitychange", startLoop);
  const hash = (s) => { let h = 2166136261; for (let i = 0; i < s.length; i++) h = Math.imul(h ^ s.charCodeAt(i), 16777619); return h >>> 0; };   // a node's float is fixed by its id, so a filter change does not make it jump
  function floatOn(t) {
    const a = (nodes.length > BIG ? FLOAT_PX_BIG : FLOAT_PX) / tf.k;
    for (const n of nodes) {
      if (n === drag) { n.ox = n.oy = 0; continue; }
      n.ox = a * Math.sin(t * n.f1 + n.p1); n.oy = a * Math.cos(t * n.f2 + n.p2);
      n.x += n.ox; n.y += n.oy;
    }
  }
  function floatOff() { for (const n of nodes) { n.x -= n.ox || 0; n.y -= n.oy || 0; } }

  const zoom = d3.zoom().scaleExtent([0.1, 8])
    .filter((e) => (e.type === "wheel" || e.type === "dblclick" ? e.type === "wheel" : !hit(e)))   // a press on a node drags the node, anywhere else pans
    .on("zoom", (e) => { tf = e.transform; schedule(); });
  d3.select(canvas).call(zoom).on("dblclick.zoom", null);
  const zoomBy = (f) => { const c = d3.select(canvas); (reducedMotion() ? c : c.transition().duration(180)).call(zoom.scaleBy, f); };
  // the canvas is mouse-first, so it has a keyboard path too: + and - zoom, the arrow keys pan (the text panel next to it lists what it shows)
  canvas.tabIndex = 0;
  canvas.setAttribute("role", "img");
  canvas.addEventListener("keydown", (e) => {
    const pan = { ArrowLeft: [60, 0], ArrowRight: [-60, 0], ArrowUp: [0, 60], ArrowDown: [0, -60] }[e.key];
    if (e.key === "+" || e.key === "=") zoomBy(1.3);
    else if (e.key === "-" || e.key === "_") zoomBy(1 / 1.3);
    else if (pan) d3.select(canvas).call(zoom.translateBy, pan[0] / tf.k, pan[1] / tf.k);
    else return;
    e.preventDefault();
  });

  function fit() {
    const r = host.getBoundingClientRect();
    W = Math.max(120, Math.floor(r.width));
    H = Math.max(120, Math.floor(r.height));
    dpr = Math.min(2, window.devicePixelRatio || 1);
    canvas.width = W * dpr; canvas.height = H * dpr;
    canvas.style.width = W + "px"; canvas.style.height = H + "px";
    schedule();
    startLoop();   // a hidden page that is shown again resizes the host, which wakes the loop
  }
  const ro = new ResizeObserver(fit);
  ro.observe(host);
  fit();

  function world(e) {   // the pointer in world coordinates, with the picture's breathing taken out so a click lands on the node it is drawn over
    const r = canvas.getBoundingClientRect();
    const [px, py] = tf.invert([e.clientX - r.left, e.clientY - r.top]);
    if (bs === 1 && br === 0) return [px, py];
    const [cx, cy] = tf.invert([W / 2, H / 2]), dx = (px - cx) / bs, dy = (py - cy) / bs, c = Math.cos(-br), s = Math.sin(-br);
    return [cx + dx * c - dy * s, cy + dx * s + dy * c];
  }
  function hit(e) {
    const [x, y] = world(e);
    let best = null, bd = Infinity;
    for (const n of nodes) {
      const dx = n.x + (n.ox || 0) - x, dy = n.y + (n.oy || 0) - y, d = dx * dx + dy * dy, r = n.r + 4 / tf.k;
      if (d < r * r && d < bd) { best = n; bd = d; }
    }
    return best;
  }

  function schedule() { if (!raf) raf = requestAnimationFrame(() => { raf = 0; draw(); }); }

  /** Move every node of `targets` (Map node -> {x, y}) from where it is to its place; `done` runs at the end. Jumps at once for reduced motion. */
  function glide(targets, done) {
    cancelAnimationFrame(tweenId);
    const from = new Map([...targets.keys()].map((n) => [n, { x: n.x, y: n.y }])), start = performance.now(), dur = reducedMotion() ? 0 : 550;
    const frame = (now) => {
      const t = dur ? Math.min(1, (now - start) / dur) : 1, e = t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2;
      for (const [n, p] of targets) { const f = from.get(n); n.x = f.x + (p.x - f.x) * e; n.y = f.y + (p.y - f.y) * e; }
      ver++; schedule();
      if (t < 1) tweenId = requestAnimationFrame(frame); else { tweenId = 0; done?.(); }
    };
    if (dur) tweenId = requestAnimationFrame(frame); else frame(performance.now());
  }
  /** In the Tree layout a line that is not a branch of the tree (parent to child) is drawn faintly, unless it touches the chosen node. */
  const markBranches = (par) => { for (const l of links) l.off = !!par && par.get(l.target.id) !== l.source.id && par.get(l.source.id) !== l.target.id; };
  const rawLinks = () => links.map((l) => ({ s: l.source.id ?? l.source, t: l.target.id ?? l.target, k: l.k }));

  function setData(data, opts = {}) {
    cancelAnimationFrame(tweenId); tweenId = 0;
    const prev = new Map(nodes.map((n) => [n.id, { x: n.x, y: n.y }]));   // where everything is now, so a layout change glides instead of jumping
    nodes = data.nodes.map((d) => {
      const p = opts.focus ? null : pos.get(d.id);   // the focus view is laid out on its own and never saved, so leaving it brings the whole picture back as it was
      const h = hash(d.id);
      return { ...d, r: radius(d), x: p ? p.x : undefined, y: p ? p.y : undefined, p1: (h % 628) / 100, p2: ((h >>> 10) % 628) / 100, f1: 0.5 + ((h >>> 5) % 55) / 100, f2: 0.5 + ((h >>> 15) % 55) / 100 };   // phases and speeds: a 6 to 12 second cycle
    });
    ver++;
    byId = new Map(nodes.map((n) => [n.id, n]));
    links = data.links.filter((l) => byId.has(l.s) && byId.has(l.t)).map((l) => ({ source: l.s, target: l.t, k: l.k, w: l.w, lab: l.lab || "" }));
    adj = new Map(nodes.map((n) => [n.id, new Set()]));
    for (const l of links) { adj.get(l.source).add(l.target); adj.get(l.target).add(l.source); }
    // a new node starts beside a neighbour that already has a place, else on a small ring around the centre
    let seeded = 0;
    nodes.forEach((n, i) => {
      if (n.x !== undefined) { seeded++; return; }
      const nb = [...adj.get(n.id)].map((id) => byId.get(id)).find((m) => m.x !== undefined);
      if (nb) { n.x = nb.x + (Math.random() - 0.5) * 12; n.y = nb.y + (Math.random() - 0.5) * 12; }
      else { const a = i * 2.399963, rr = 12 * Math.sqrt(i + 1); n.x = Math.cos(a) * rr; n.y = Math.sin(a) * rr; }
    });
    if (sel && !byId.has(sel)) { sel = null; cb.select(null); }
    const kind = opts.focus ? "organic" : layoutName, animate = layoutChanged && prev.size > 0;
    layoutChanged = false; curKind = kind;
    if (kind !== "organic") {   // an arranged layout: no simulation, deterministic places
      sim?.stop(); sim = null; want = false;
      for (const l of links) { l.source = byId.get(l.source); l.target = byId.get(l.target); }   // the simulation would have turned the ids into nodes; the drawing needs them
      const target = place(kind, { nodes, links: rawLinks(), root: treeRoot });
      curRoot = target.root || null;
      markBranches(target.parent);
      const move = new Map();
      for (const n of nodes) {
        const t = target.get(n.id) || { x: 0, y: 0 }, pv = prev.get(n.id);
        if (pv && pv.x !== undefined) { n.x = pv.x; n.y = pv.y; } else { n.x = t.x; n.y = t.y; }   // a node that was not there starts in its place
        move.set(n, t);
      }
      glide(move, () => { if (opts.recenter || animate) recenter(); });
      return;
    }
    let back = null;   // back to organic with every place remembered: glide home instead of simulating again
    if (animate && seeded >= nodes.length * 0.9) { back = new Map(nodes.map((n) => [n, { x: n.x, y: n.y }])); for (const n of nodes) { const pv = prev.get(n.id); if (pv && pv.x !== undefined) { n.x = pv.x; n.y = pv.y; } } }
    sim?.stop();
    const small = nodes.length <= 80;   // the focus view and other small pictures get room for their labels
    sim = d3.forceSimulation(nodes)
      .force("link", d3.forceLink(links).id((d) => d.id).distance((l) => (l.k === "similar" ? 24 + (1 - l.w) * 70 : 38) * (small ? 2.6 : 1)).strength((l) => (l.k === "similar" ? 0.22 : 0.5)))
      .force("charge", d3.forceManyBody().strength(small ? -140 : -26).distanceMax(small ? 600 : 240))
      .force("x", d3.forceX(0).strength(0.035)).force("y", d3.forceY(0).strength(0.035))   // keeps unconnected nodes from drifting away
      .force("collide", d3.forceCollide((d) => d.r + (small ? 7 : 1.2)))
      .alpha(opts.fresh || seeded < nodes.length * 0.6 ? 1 : 0.25).alphaDecay(0.05)
      .on("tick", () => { ver++; schedule(); }).on("end", () => { if (!opts.focus) for (const n of nodes) pos.set(n.id, { x: n.x, y: n.y }); if (want) { want = false; recenter(); } schedule(); });
    if (!reducedMotion() && seeded < nodes.length * 0.6) sim.tick(30);   // a fresh layout starts already roughly spread, not as a dot
    if (reducedMotion()) { sim.stop(); sim.tick(220); if (!opts.focus) for (const n of nodes) pos.set(n.id, { x: n.x, y: n.y }); }
    if (back) { sim.stop(); want = false; glide(back, () => { if (opts.recenter || animate) recenter(); }); return; }
    want = !!opts.recenter;   // fit the view once the picture has settled
    if (want && !reducedMotion()) setTimeout(() => { if (want) recenter(); }, 900);   // and roughly once early, so nothing sits off screen meanwhile
    else if (want) { want = false; recenter(); }
    schedule();
  }

  function recenter() {
    if (!nodes.length) return;
    const small = nodes.length <= 80;
    const sorted = (k) => nodes.map((n) => n[k]).sort((a, b) => a - b);
    const xs = sorted("x"), ys = sorted("y"), lo = Math.floor(nodes.length * 0.01), hi = Math.ceil(nodes.length * 0.99) - 1;   // ignore a few far strays
    const x0 = xs[lo], x1 = xs[hi], y0 = ys[lo], y1 = ys[hi];
    const k = Math.max(0.1, Math.min(small ? 3.5 : 2.5, (small ? 0.7 : 0.9) * Math.min(W / Math.max(40, x1 - x0), H / Math.max(40, y1 - y0))));
    const t = d3.zoomIdentity.translate(W / 2, H / 2).scale(k).translate(-(x0 + x1) / 2, -(y0 + y1) / 2);
    const sel_ = d3.select(canvas);
    (reducedMotion() ? sel_ : sel_.transition().duration(400)).call(zoom.transform, t);
  }

  function relayout() {
    if (curKind !== "organic") {   // an arranged layout: put every node (also the ones that were dragged) back
      const target = place(curKind, { nodes, links: rawLinks(), root: treeRoot });
      curRoot = target.root || null;
      markBranches(target.parent);
      glide(new Map(nodes.map((n) => [n, target.get(n.id) || { x: n.x, y: n.y }])), () => recenter());
      return;
    }
    pos.clear();
    for (const n of nodes) { n.x = n.y = undefined; n.vx = n.vy = 0; }
    nodes.forEach((n, i) => { const a = i * 2.399963, rr = 12 * Math.sqrt(i + 1); n.x = Math.cos(a) * rr; n.y = Math.sin(a) * rr; });
    want = true;
    sim?.alpha(1).restart();
  }

  // ---- pointer
  let down = null;
  canvas.addEventListener("pointerdown", (e) => {
    const n = hit(e);
    down = { x: e.clientX, y: e.clientY, n, moved: false };
    if (n) { canvas.setPointerCapture(e.pointerId); drag = n; const [x, y] = world(e); n.fx = x; n.fy = y; if (sim) sim.alphaTarget(0.25).restart(); else { n.x = x; n.y = y; ver++; schedule(); } }
  });
  canvas.addEventListener("pointermove", (e) => {
    if (down && (Math.abs(e.clientX - down.x) + Math.abs(e.clientY - down.y) > 4)) down.moved = true;
    if (drag) { const [x, y] = world(e); drag.fx = x; drag.fy = y; if (!sim) { drag.x = x; drag.y = y; ver++; schedule(); } return; }
    const n = hit(e);
    if (n?.id !== hover) { hover = n ? n.id : null; canvas.style.cursor = n ? "pointer" : ""; cb.hover(n, e); schedule(); }
    else if (n) cb.hover(n, e);
  });
  const up = (e) => {
    if (drag) { drag.fx = drag.fy = null; sim?.alphaTarget(0); drag = null; }
    if (down && !down.moved) { const n = hit(e); select(n ? n.id : null, true); }
    down = null;
  };
  canvas.addEventListener("pointerup", up);
  canvas.addEventListener("pointercancel", up);
  canvas.addEventListener("pointerleave", () => { if (hover) { hover = null; cb.hover(null); schedule(); } });

  function select(id, fromUser) {
    if (id === sel) { if (fromUser) { sel = null; cb.select(null); schedule(); } return; }
    sel = id && byId.has(id) ? id : null;
    if (sel) { treeRoot = sel; if (curKind === "tree") relayout(); }   // in the Tree layout the chosen item becomes the root
    cb.select(sel);
    schedule();
  }

  /** Centre the view on a node (used by search and by choosing a neighbour in the panel). */
  function show(id) {
    const n = byId.get(id);
    if (!n || curKind === "tree") return;   // the Tree layout recentres on its own root
    const k = Math.max(tf.k, 1.4);
    const t = d3.zoomIdentity.translate(W / 2, H / 2).scale(k).translate(-n.x, -n.y);
    const s = d3.select(canvas);
    (reducedMotion() ? s : s.transition().duration(350)).call(zoom.transform, t);
  }

  // ---- drawing
  function draw() {
    lastDraw = performance.now();
    const t = lastDraw / 1000, on = motion && !reducedMotion(), layered = on && links.length > LAYER_LINKS;
    if (layered) ensureLayer(sel || null);   // before the nodes are shifted: the cached lines sit on the real positions
    if (on) { bs = 1 + 0.004 * Math.sin(t * 0.45); br = 0.007 * Math.sin(t * 0.27); floatOn(t); } else { bs = 1; br = 0; }
    try { paint(t, on, layered); } finally { if (on) floatOff(); }   // nodes are drawn shifted, then put back: the layout never holds the float
  }

  /** Lines: explicit solid, similar dashed and fainter for weaker scores; the ones touching the chosen node light up. Drawn into `g`, whose transform is the world one. */
  function strokeLines(g, focus) {
    const muted = css("--text-muted"), edge = css("--edge"), entC = css(TYPE_COLOR.entity), lw = 1 / tf.k;   // lines made by an agent are drawn in the entity colour (thicker for a labelled relationship)
    const buckets = new Map();
    for (const l of links) {
      const hot = !focus || l.source.id === focus || l.target.id === focus;
      const off = l.off && focus !== l.source.id && focus !== l.target.id;
      const key = off ? "o0" : (l.k === "similar" ? (l.w >= 0.6 ? "s3" : l.w >= 0.4 ? "s2" : "s1") : l.k === "mentions" ? "m" : l.k === "related" ? "r" : l.k === "followed_by" ? "f" : l.k === "same_text" ? "t" : "x") + (hot ? "1" : "0");
      (buckets.get(key) || buckets.set(key, []).get(key)).push(l);
    }
    const style = { m1: [entC, 0.6, false], m0: [entC, 0.1, false], r1: [entC, 0.9, false], r0: [entC, 0.18, false], x1: [muted, 0.5, false, lw], x0: [muted, 0.1, false, lw], o0: [muted, 0.035, false], f1: [muted, 0.55, false, lw], f0: [muted, 0.1, false, lw], t1: [muted, 0.7, false, lw * 1.8], t0: [muted, 0.14, false, lw * 1.8], s11: [muted, 0.2, true], s21: [muted, 0.32, true], s31: [muted, 0.48, true], s10: [muted, 0.05, true], s20: [muted, 0.07, true], s30: [muted, 0.1, true] };
    for (const [key, ls] of buckets) {
      const st = style[key] || style.x1;
      g.beginPath();
      for (const l of ls) { g.moveTo(l.source.x, l.source.y); g.lineTo(l.target.x, l.target.y); }
      g.globalAlpha = focus && key.endsWith("1") ? Math.min(0.9, st[1] + 0.25) : st[1];
      g.strokeStyle = focus && key.endsWith("1") && key[0] !== "m" && key[0] !== "r" ? edge : st[0];
      g.lineWidth = lw * (focus && key.endsWith("1") ? 1.4 : 1) * (key[0] === "r" || key[0] === "t" ? 1.8 : 1);
      g.setLineDash(st[2] ? [3 / tf.k, 3 / tf.k] : []);
      g.stroke();
    }
    g.setLineDash([]);
    g.globalAlpha = 1;
  }

  // A big picture has thousands of lines, which cost the most to paint (tens of milliseconds on a software canvas), so while it moves they are painted into
  // an off-screen layer that is redrawn only when the view, the layout, the chosen node or the colours change. A frame of motion is then that layer plus
  // the points. The lines stay on the points' real positions (the points float a few pixels over them); small pictures draw their lines live and follow exactly.
  let layer = null, lctx = null, layerKey = "", ver = 0;
  function ensureLayer(focus) {
    const key = [tf.k, tf.x, tf.y, W, H, dpr, focus, links.length, ver, css("--text-muted"), css("--edge"), css(TYPE_COLOR.entity)].join("|");
    if (key === layerKey) return;
    if (!layer) { layer = document.createElement("canvas"); lctx = layer.getContext("2d"); }
    if (layer.width !== canvas.width || layer.height !== canvas.height) { layer.width = canvas.width; layer.height = canvas.height; }
    lctx.setTransform(1, 0, 0, 1, 0, 0);
    lctx.clearRect(0, 0, layer.width, layer.height);
    lctx.setTransform(dpr * tf.k, 0, 0, dpr * tf.k, dpr * tf.x, dpr * tf.y);
    strokeLines(lctx, focus);
    layerKey = key;
  }

  function paint(t, on, layered) {
    const bg = css("--canvas"), txt = css("--text-primary"), muted = css("--text-muted"), edge = css("--edge"), font = css("--font-body") || "sans-serif";
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, W, H);
    ctx.setTransform(dpr * tf.k, 0, 0, dpr * tf.k, dpr * tf.x, dpr * tf.y);
    if (on) { const [cx, cy] = tf.invert([W / 2, H / 2]); ctx.translate(cx, cy); ctx.rotate(br); ctx.scale(bs, bs); ctx.translate(-cx, -cy); }   // the whole picture breathes about the view centre
    const focus = sel || null, near = focus ? adj.get(focus) : null;
    const dimOn = !!focus || !!hl;
    const lit = (n) => !dimOn || n.id === focus || (near && near.has(n.id)) || (hl && hl.has(n.id) && !focus) || (focus && hl && hl.has(n.id));
    const entC = css(TYPE_COLOR.entity);
    if (layered) {   // the cached lines, breathing with the picture (the same turn and scale about the view centre, in screen space)
      ctx.save(); ctx.setTransform(1, 0, 0, 1, 0, 0);
      const mx = dpr * W / 2, my = dpr * H / 2;
      ctx.translate(mx, my); ctx.rotate(br); ctx.scale(bs, bs); ctx.translate(-mx, -my);
      ctx.drawImage(layer, 0, 0);
      ctx.restore();
    } else strokeLines(ctx, focus);
    // nodes
    const dark = isDark(), kc = {}, cols = {};   // an entity triangle takes its kind's colour; the other types and collections take the user's colours (colours.js), cached per frame
    for (const n of nodes) {
      ctx.globalAlpha = lit(n) ? 1 : 0.16;
      ctx.fillStyle = n.t === "entity" ? (kc[n.k] ||= kindColour(n.k, dark)) : (cols[n.t === "collection" ? n.id : n.t] ||= nodeColour(n.t, n.id, dark)) || muted;
      ctx.beginPath();
      if (n.t === "collection") ctx.rect(n.x - n.r, n.y - n.r, n.r * 2, n.r * 2);
      else if (n.t === "tag") { ctx.moveTo(n.x, n.y - n.r * 1.2); ctx.lineTo(n.x + n.r * 1.2, n.y); ctx.lineTo(n.x, n.y + n.r * 1.2); ctx.lineTo(n.x - n.r * 1.2, n.y); ctx.closePath(); }
      else if (n.t === "reference") { for (let k = 0; k < 5; k++) { const a = -Math.PI / 2 + k * 2 * Math.PI / 5; ctx[k ? "lineTo" : "moveTo"](n.x + Math.cos(a) * n.r * 1.2, n.y + Math.sin(a) * n.r * 1.2); } ctx.closePath(); }
      else if (n.t === "project") { for (let k = 0; k < 6; k++) { const a = Math.PI / 6 + k * Math.PI / 3; ctx[k ? "lineTo" : "moveTo"](n.x + Math.cos(a) * n.r * 1.15, n.y + Math.sin(a) * n.r * 1.15); } ctx.closePath(); }
      else if (n.t === "linkshell") { const r = n.r * 1.25, w = r * 0.42; ctx.moveTo(n.x - w, n.y - r); ctx.lineTo(n.x + w, n.y - r); ctx.lineTo(n.x + w, n.y - w); ctx.lineTo(n.x + r, n.y - w); ctx.lineTo(n.x + r, n.y + w); ctx.lineTo(n.x + w, n.y + w); ctx.lineTo(n.x + w, n.y + r); ctx.lineTo(n.x - w, n.y + r); ctx.lineTo(n.x - w, n.y + w); ctx.lineTo(n.x - r, n.y + w); ctx.lineTo(n.x - r, n.y - w); ctx.lineTo(n.x - w, n.y - w); ctx.closePath(); }
      else if (n.t === "entity") { ctx.moveTo(n.x, n.y - n.r * 1.25); ctx.lineTo(n.x + n.r * 1.15, n.y + n.r * 0.85); ctx.lineTo(n.x - n.r * 1.15, n.y + n.r * 0.85); ctx.closePath(); }
      else ctx.arc(n.x, n.y, n.r, 0, 6.2832);
      ctx.fill();
    }
    ctx.globalAlpha = 1;
    for (const id of [focus, hover]) {   // rings on the chosen and the hovered node
      const n = id && byId.get(id);
      if (!n) continue;
      const pulse = on && id === focus ? Math.sin(t * 2.2) : 0;   // the chosen node's ring breathes slowly
      ctx.beginPath(); ctx.arc(n.x, n.y, n.r + (3 + 1.2 * pulse) / tf.k, 0, 6.2832);
      ctx.strokeStyle = id === focus ? edge : txt; ctx.lineWidth = (1.6 + 0.5 * pulse) / tf.k; ctx.stroke();
    }
    if (focus) {   // the name of a relationship, at the middle of its line
      ctx.font = `${11 / tf.k}px ${font}`; ctx.textAlign = "center"; ctx.textBaseline = "middle"; ctx.lineJoin = "round";
      for (const l of links) {
        if (l.k !== "related" || !l.lab || (l.source.id !== focus && l.target.id !== focus)) continue;
        const mx = (l.source.x + l.target.x) / 2, my = (l.source.y + l.target.y) / 2;
        ctx.lineWidth = 3 / tf.k; ctx.strokeStyle = bg; ctx.strokeText(clip(l.lab, 28), mx, my); ctx.fillStyle = entC; ctx.fillText(clip(l.lab, 28), mx, my);
      }
      ctx.textAlign = "start";
    }
    // labels: the chosen node, its neighbours, search hits, the hovered node, the biggest nodes at rest, more of them as you zoom in
    if (label) {
      const lab = new Map();
      const addL = (n, pri) => { if (n && !lab.has(n.id)) lab.set(n.id, pri); };
      addL(byId.get(hover), 0); addL(byId.get(focus), 0);
      if (near) for (const n of [...near].map((id) => byId.get(id)).sort((a, b) => b.d - a.d).slice(0, 12)) addL(n, 1);   // the busiest neighbours only: more would overlap
      if (hl) for (const id of hl) addL(byId.get(id), 2);
      if (nodes.length <= 45) for (const n of nodes) addL(n, 3);   // a small picture (the focus view) names everything
      if (!focus) {
        const top = [...nodes].sort((a, b) => b.d - a.d).slice(0, tf.k >= 1.6 ? 140 : 10);
        for (const n of top) {
          const sx = n.x * tf.k + tf.x, sy = n.y * tf.k + tf.y;
          if (sx > -40 && sx < W + 40 && sy > -20 && sy < H + 20) addL(n, 3);
        }
      }
      ctx.font = `${12 / tf.k}px ${font}`;
      ctx.textBaseline = "middle";
      ctx.lineJoin = "round";
      let shown = 0;
      for (const [id, pri] of [...lab].sort((a, b) => a[1] - b[1])) {
        if (++shown > 60) break;
        const n = byId.get(id);
        const text = clip(n.n, 26);
        ctx.globalAlpha = 1;
        ctx.lineWidth = 3 / tf.k; ctx.strokeStyle = bg; ctx.strokeText(text, n.x + n.r + 3 / tf.k, n.y);
        ctx.fillStyle = pri === 3 ? muted : txt; ctx.fillText(text, n.x + n.r + 3 / tf.k, n.y);
      }
    }
    ctx.globalAlpha = 1;
  }

  return {
    setData, recenter, relayout, zoomIn: () => zoomBy(1.4), zoomOut: () => zoomBy(1 / 1.4), setLabel: (t) => canvas.setAttribute("aria-label", t), select: (id) => select(id, false), show,
    setHighlight(set) { hl = set && set.size ? set : null; schedule(); },
    redraw: schedule,
    nodeAt: (id) => byId.get(id) || null,
    neighbours: (id) => [...(adj.get(id) || [])],
    stop() { sim?.stop(); },
    resume() { fit(); startLoop(); },
    destroy() { sim?.stop(); ro.disconnect(); document.removeEventListener("visibilitychange", startLoop); cancelAnimationFrame(loop); loop = 0; canvas.remove(); },
    layout: () => layoutName,
    root: () => curRoot,
    setLayout(name) { if (name !== layoutName) { layoutName = name; layoutChanged = true; } },
    isMotion: () => motion,
    canMotion: () => !reducedMotion(),
    setMotion(on) {
      motion = !!on && !reducedMotion();
      if (!motion) { bs = 1; br = 0; for (const n of nodes) n.ox = n.oy = 0; }
      schedule(); startLoop();
    },
  };
}

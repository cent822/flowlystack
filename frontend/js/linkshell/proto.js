// Linkshell canvas. Started as the phase 0 look-and-feel prototype; since phase 3 it shows a real project
// from /api/linkshell and saves positions, links, frames and statuses by itself. Block text is edited in the block panel (panel.js). D3 (d3-zoom, d3-drag) does the pan, zoom and dragging; cards are plain HTML in one transformed layer, links are
// SVG paths underneath, and every colour is a CSS variable, so day and night need no redraw. Plain DOM, no framework.
import { api } from "../api.js";
import { toast } from "../toast.js";
import { statusOf, orderEdges, attachedBlocks } from "./projects.js";
import { tidy, runOrder } from "./layout.js";
import { hotkey, label as keyLabel, matches } from "../hotkeys.js";
import { confirmDialog } from "../dialog.js";
import { createPanel } from "./panel.js";
import { createFollow } from "./follow.js";
import { createOutline } from "./outline.js";
import { exportItems, exportClick } from "./exporter.js";
import { projectSettings, pickStudio } from "./project.js";

const $ = (s) => document.querySelector(s);
const esc = (t) => String(t ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
const ic = (d, s = 18) => `<svg viewBox="0 0 24 24" width="${s}" height="${s}" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${d}</svg>`;
const P = {
  prompt: `<path d="M5 7l5 5-5 5"/><path d="M12 18h7"/>`,
  spec: `<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5M9 13h6M9 17h6"/>`,
  reference: `<rect x="3" y="4" width="18" height="16" rx="2.5"/><circle cx="9" cy="10" r="1.6"/><path d="M21 16l-5-5-8 8"/>`,
  start: `<path d="M5 21V4M5 4h11l-2 4 2 4H5"/>`,
  note: `<path d="M5 4h14v10l-5 6H5z"/><path d="M14 20v-6h5"/>`,
  frame: `<path d="M7 3v18M17 3v18M3 7h18M3 17h18"/>`,
  check: `<path d="M5 12.5l4.5 4.5L19 7.5"/>`, play: `<path d="M8 5l11 7-11 7z"/>`,
  minus: `<path d="M5 12h14"/>`, plus: `<path d="M12 5v14M5 12h14"/>`,
  fit: `<path d="M4 9V5a1 1 0 0 1 1-1h4M15 4h4a1 1 0 0 1 1 1v4M20 15v4a1 1 0 0 1-1 1h-4M9 20H5a1 1 0 0 1-1-1v-4"/>`,
  tidy: `<rect x="3" y="5" width="6" height="14" rx="1.5"/><rect x="15" y="5" width="6" height="14" rx="1.5"/><path d="M12 3v18"/>`,
  undo: `<path d="M9 14L4 9l5-5"/><path d="M4 9h10a6 6 0 0 1 0 12h-3"/>`, redo: `<path d="M15 14l5-5-5-5"/><path d="M20 9H10a6 6 0 0 0 0 12h3"/>`,
  sliders: `<path d="M4 7h10M18 7h2M4 17h2M10 17h10"/><circle cx="16" cy="7" r="2"/><circle cx="8" cy="17" r="2"/>`,
  dots: `<circle cx="5" cy="12" r="1.5"/><circle cx="12" cy="12" r="1.5"/><circle cx="19" cy="12" r="1.5"/>`, edit: `<path d="M4 20h4L19 9l-4-4L4 16z"/>`, copy: `<rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V6a2 2 0 0 1 2-2h9"/>`, trash: `<path d="M4 7h16M10 11v6M14 11v6M6 7l1 12a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2l1-12M9 7V4h6v3"/>`,
  file: `<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5"/>`, link: `<path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1"/>`,
  chev: `<path d="M6 9l6 6 6-6"/>`, download: `<path d="M12 4v11M7 11l5 5 5-5M5 20h14"/>`, back: `<path d="M15 6l-6 6 6 6"/>`, find: `<circle cx="11" cy="11" r="6.5"/><path d="M16 16l4.5 4.5"/>`,
};

let S = { frames: [], blocks: [], links: [] }, T = d3.zoomIdentity, hist = [], fut = [], built = false;
const nid = (p) => p + "-" + crypto.getRandomValues(new Uint32Array(1))[0].toString(16).padStart(8, "0");   // ids become file names on the server: letters, digits, dash
let sel = new Set(), selLink = "", selFrame = "", spaceDown = false;   // selected block ids; a selected link; a selected frame
let stage, world, framesEl, blocksEl, linksEl, liveEl, miniEl, popEl, zoomSel, zoom, panel, follow, followEl, outline, outlineEl, view = "canvas", reveal = "";
let X = { texts: {} }, PJ = {};   // the saved text of every block (bid -> text), and the project's settings (name, default agent, properties)

const byId = (id) => S.blocks.find((b) => b.id === id);
const frameEnt = (id) => { const f = S.frames.find((x) => x.id === id); return f && { ...f, h: f.collapsed ? 34 : f.h }; };   // a frame as a link end: the same x, y, w, h as a block, no `type`
const ent = (id) => byId(id) || frameEnt(id);
const snap = (v) => Math.round(v / 10) * 10;
const isStep = (b) => b.type === "prompt";

const status = (b) => statusOf(S, b);
/** The expanded frame a block sits in, by its centre ("" for none). A collapsed frame is only its header row and takes nothing in: the free space around it stays free. */
const frameAt = (b) => (S.frames.find((f) => !f.collapsed && b.x + b.w / 2 > f.x && b.x + b.w / 2 < f.x + f.w && b.y + b.h / 2 > f.y && b.y + b.h / 2 < f.y + f.h) || {}).id || "";

const fOf = (b) => (b.frame ? S.frames.find((f) => f.id === b.frame) : null);
const hidden = (b) => !!fOf(b)?.collapsed;           // inside a collapsed frame
const fh = (f) => (f.collapsed ? 34 : f.h);          // a collapsed frame is one header row
const clearSel = () => { sel = new Set(); selLink = ""; selFrame = ""; };
/** Where a link meets a block on side `sd` (l, r, t or b): its port, or the frame's edge when the block is hidden in a collapsed frame. */
const NORM = { l: [-1, 0], r: [1, 0], t: [0, -1], b: [0, 1] };
function anchor(b, sd) {
  const f = hidden(b) ? fOf(b) : null;
  if (f) return sd === "r" || sd === "b" ? [f.x + f.w, f.y + 17] : [f.x, f.y + 17];
  return sd === "r" ? [b.x + b.w, b.y + b.h / 2] : sd === "l" ? [b.x, b.y + b.h / 2] : sd === "t" ? [b.x + b.w / 2, b.y] : [b.x + b.w / 2, b.y + b.h];
}

// ---------- links ----------
const line = d3.line().curve(d3.curveBasis);
/** A smooth S-curve right to left; when the target sits behind the source, go out, round the gap above the target's frame, and in. */
function route(x1, y1, x2, y2, target) {
  if (x2 - x1 < 12 && target && Math.abs(y2 - y1) <= 60) {   // same row, going backwards: round the top of the target's frame
    const f = S.frames.find((fr) => fr.id === target.frame), ym = f ? f.y - 40 : Math.max(y1, y2) + 60;
    return line([[x1, y1], [x1 + 40, y1], [x1 + 40, ym], [x2 - 40, ym], [x2 - 40, y2], [x2, y2]]);
  }
  const dx = x2 - x1 < 12 ? 110 : Math.min(160, Math.max(20, (x2 - x1) / 2));   // backwards and on another row: a wide S, out of the source and into the target
  return `M${x1},${y1}C${x1 + dx},${y1} ${x2 - dx},${y2} ${x2},${y2}`;
}
/** Any side to any side: a cubic curve leaving and entering along each port's outward direction. A plain right-to-left link keeps the S-curve above. */
function curve(x1, y1, s1, x2, y2, s2, target) {
  if (s1 === "r" && s2 === "l") return route(x1, y1, x2, y2, target);
  const d = Math.min(160, Math.max(40, Math.hypot(x2 - x1, y2 - y1) / 2)), n1 = NORM[s1], n2 = s2 ? NORM[s2] : [0, 0];
  return `M${x1},${y1}C${x1 + n1[0] * d},${y1 + n1[1] * d} ${x2 + n2[0] * d},${y2 + n2[1] * d} ${x2},${y2}`;
}
function drawLinks() {
  linksEl.innerHTML = S.links.map((l) => {
    const a = ent(l.from), b = ent(l.to);
    if (!a || !b || (hidden(a) && hidden(b) && a.frame === b.frame)) return "";
    const fs = l.fs || "r", ts = l.ts || "l", [x1, y1] = anchor(a, fs), [x2, y2] = anchor(b, ts), d = curve(x1, y1, fs, x2, y2, ts, hidden(b) ? null : b);
    return `<path class="lk-link lk-${l.kind}${l.id === selLink ? " lk-sel" : ""}" data-id="${l.id}" d="${d}"/><path class="lk-hit" data-id="${l.id}" d="${d}"/>`;
  }).join("");
}
function reason(from, to) {
  if (from.id === to.id) return "A block cannot link to itself.";
  if (to.type === "start") return "Nothing links into the Brief block.";
  if (to.type === "note" || from.type === "note") return "Sticky notes are not linked.";
  if ((!from.type && to.frame === from.id) || (!to.type && from.frame === to.id)) return "A frame cannot link to a block inside it.";
  if (S.links.some((l) => l.from === from.id && l.to === to.id)) return "Those are already linked.";
  const edges = orderEdges({ blocks: S.blocks, frames: S.frames, links: [...S.links, { from: from.id, to: to.id, kind: "order" }] }), indeg = Object.fromEntries(S.blocks.map((b) => [b.id, 0]));   // refuse a loop (a frame stands for every block in it)
  edges.forEach(([, t]) => indeg[t]++);
  const stack = Object.keys(indeg).filter((i) => !indeg[i]);
  let seen = 0;
  while (stack.length) { const i = stack.pop(); seen++; edges.forEach(([a, t]) => { if (a === i && !--indeg[t]) stack.push(t); }); }
  return seen !== S.blocks.length ? "That link would make a loop." : "";
}
/** One kind of link: "comes before". A Spec or Reference linked into a Prompt is also attached to it when it is copied (see `attached`). */
const kindFrom = () => "order";
const attached = (b) => attachedBlocks(S, b.id);

// ---------- drawing ----------
function chips(b) {
  const out = [];
  if (b.type === "prompt") { out.push(b.agent || "claude"); const n = attached(b).length; if (n) out.push(`${n} ctx`); }
  else if (b.type === "reference") { const fs = [...new Set([...(b.asset ? [b.asset] : []), ...(b.assets || [])])]; const us = [...new Set([...(b.url ? [b.url] : []), ...(b.urls || [])])]; const many = (n, what, d) => `<span class="lk-chip lk-chip-n" title="${n} ${what}s">${ic(d, 10)}${n}</span>`;   // short, so two of them always fit inside the card
    if (fs.length > 1) out.push({ html: many(fs.length, "file", P.file) }); else if (fs.length) out.push(fs[0].split(".").pop().toLowerCase().slice(0, 5) || "file");
    if (us.length > 1) out.push({ html: many(us.length, "link", P.link) }); else if (us.length) out.push("link");
    if (!out.length) out.push("empty"); }
  else out.push(b.chip || b.type);
  return out.map((c) => c.html || `<span class="lk-chip">${esc(c)}</span>`).join("");
}
/** The sides (t, r, b, l) of a block or frame where a link is attached. A collapsed frame also shows the links of the blocks hidden in it, on the side they leave from. */
function usedSides(id) {
  const out = new Set();
  S.links.forEach((l) => {
    const a = byId(l.from), b = byId(l.to);
    if (a && b && hidden(a) && hidden(b) && a.frame === b.frame) return;
    [[l.from, l.fs || "r"], [l.to, l.ts || "l"]].forEach(([end, sd]) => {
      if (end === id) out.add(sd);
      else { const o = byId(end); if (o && hidden(o) && o.frame === id) out.add(sd === "r" || sd === "b" ? "r" : "l"); }
    });
  });
  return out;
}
const portsHtml = (id) => { const used = usedSides(id); return ["t", "r", "b", "l"].map((k) => `<span class="lk-port lk-p${k}${used.has(k) ? " lk-used" : ""}" data-s="${k}" title="Drag to link"></span>`).join(""); };
function blockHtml(b) {
  const st = status(b), on = sel.has(b.id) ? " lk-sel" : "";
  const badge = !isStep(b) && b.type !== "start" ? "" : st === "done" ? `<button class="lk-st lk-st-done" type="button" title="Done. Click to mark To do.">${ic(P.check, 12)}</button>`
    : st === "ready" ? `<button class="lk-st lk-st-ready" type="button" title="Ready. Click to mark Done.">${ic(P.play, 10)}</button>`
    : st === "skipped" ? `<button class="lk-st lk-st-todo" type="button" title="Skipped. Click to mark Done.">${ic(P.minus, 12)}</button>`
    : `<button class="lk-st lk-st-todo" type="button" title="To do. Click to mark Done.">${ic(P.check, 12)}</button>`;   // not done yet: the same green check, as an outline (done is the filled one)
  const used = usedSides(b.id);   // sides where a link is attached keep a solid dot
  const ports = b.type === "note" ? "" : ["t", "r", "b", "l"].map((k) => `<span class="lk-port lk-p${k}${used.has(k) ? " lk-used" : ""}" data-s="${k}" title="Drag to link"></span>`).join("");
  const body = b.type === "note" ? `<div class="lk-ntext">${esc(b.title)}</div>`
    : `<span class="lk-tile lk-tile-${b.type}">${ic(P[b.type])}</span><div class="lk-bt"><div class="lk-title">${esc(b.title)}</div><div class="lk-chips">${chips(b)}</div></div>`;
  const more = `<button class="lk-more" type="button" title="Card menu" aria-label="Card menu">${ic(P.dots, 16)}</button>`;
  return `<div class="lk-blk lk-${b.type}${on}" data-id="${b.id}" style="left:${b.x}px;top:${b.y}px;width:${b.w}px;height:${b.h}px">${body}${badge}${more}${ports}</div>`;
}
function counts(f) {
  const steps = S.blocks.filter((b) => b.frame === f.id && isStep(b));
  return `${steps.filter((b) => b.status === "done").length}/${steps.length}`;
}
function draw() {
  framesEl.innerHTML = S.frames.map((f) => `<div class="lk-frm${f.collapsed ? " lk-collapsed" : ""}${f.id === selFrame ? " lk-sel" : ""}" data-id="${f.id}" style="left:${f.x}px;top:${f.y}px;width:${f.w}px;height:${fh(f)}px"><div class="lk-frmlabel"><span class="lk-frmtog" data-tog title="${f.collapsed ? "Expand" : "Collapse"}">${ic(P.chev, 12)}</span><span class="lk-frmtitle">${esc(f.title)}</span></div><span class="lk-frmcount">${counts(f)}</span>${f.collapsed ? "" : `<span class="lk-frmsz" title="Resize"></span>`}${portsHtml(f.id)}</div>`).join("");
  blocksEl.innerHTML = S.blocks.filter((b) => !hidden(b)).map(blockHtml).join("");
  d3.select(blocksEl).selectAll(".lk-blk").call(dragBlock);
  d3.select(framesEl).selectAll(".lk-frmsz").call(resizeFrame);
  drawLinks(); mini(); meta(); autosave(); panel?.refresh();
  if (view === "follow") follow?.refresh();
  if (view === "outline") outline?.refresh();
}
function meta() {
  const steps = S.blocks.filter(isStep), done = steps.filter((b) => b.status === "done").length;
  $("#lk-meta").textContent = `· ${S.blocks.length} block${S.blocks.length === 1 ? "" : "s"} · ${steps.length ? `${done} / ${steps.length} done` : "no prompts yet"} · ${saveState}`;
  $("#lk-undo").disabled = !hist.length; $("#lk-redo").disabled = !fut.length;
}
function setSel(ids = [], { link = "", frame = "" } = {}) {
  sel = new Set(ids); selLink = link; selFrame = frame;
  blocksEl.querySelectorAll(".lk-blk").forEach((e) => e.classList.toggle("lk-sel", sel.has(e.dataset.id)));
  framesEl.querySelectorAll(".lk-frm").forEach((e) => e.classList.toggle("lk-sel", e.dataset.id === selFrame));
  linksEl.querySelectorAll(".lk-link").forEach((e) => e.classList.toggle("lk-sel", e.dataset.id === selLink));
  mini(); syncPanel();
}
/** While the block panel is open it follows the selection: one block selected shows that block, anything else closes it. */
function syncPanel() {
  if (!panel?.isOpen()) return;   // the panel never opens by itself: the card menu (or Enter) opens it, and then it follows the selection
  if (sel.size === 1 && !selLink && !selFrame) panel.open([...sel][0]); else panel.close();
}
const select = (id) => setSel(id ? [id] : []);
function place(b, el) { el.style.left = b.x + "px"; el.style.top = b.y + "px"; }

// ---------- history (in memory only) ----------
function mutate(fn) { hist.push(JSON.stringify(S)); fut = []; fn(); draw(); }
function restore(s) { S = JSON.parse(s); clearSel(); panel?.close(); draw(); }
function undo() { if (hist.length) { fut.push(JSON.stringify(S)); restore(hist.pop()); } }
function redo() { if (fut.length) { hist.push(JSON.stringify(S)); restore(fut.pop()); } }

// ---------- drag blocks and frames ----------
let g = null;
const dragBlock = d3.drag()
  .filter((e) => !e.button && !spaceDown && !e.target.closest(".lk-port, .lk-st, .lk-more") && !e.target.isContentEditable)
  .on("start", function (e) {
    const b = byId(this.dataset.id);
    closePop();   // d3-drag swallows the mousedown, so the canvas never sees it: close a menu left open by another card here
    if (!sel.has(b.id) && !e.sourceEvent.shiftKey) setSel([b.id]);
    const members = (sel.has(b.id) ? [...sel] : [b.id]).map(byId).filter(Boolean);   // a block inside the selection drags the whole selection
    g = { b, members, rx: b.x, ry: b.y, before: JSON.stringify(S), moved: false }; this.classList.add("lk-drag");
  })
  .on("drag", function (e) {
    g.rx += e.dx / T.k; g.ry += e.dy / T.k;
    const dx = snap(g.rx) - g.b.x, dy = snap(g.ry) - g.b.y;
    if (!dx && !dy) return;
    g.moved = true;
    g.members.forEach((o) => { o.x += dx; o.y += dy; const el = blocksEl.querySelector(`[data-id="${o.id}"]`); if (el) place(o, el); });
    drawLinks(); mini();
  })
  .on("end", function () {
    this.classList.remove("lk-drag");
    if (!g.moved) return;
    hist.push(g.before); fut = [];
    g.members.forEach((o) => { o.frame = frameAt(o); });
    draw();
  });
/** The frame under a mouse event (the smallest, when frames overlap), or undefined. Frames let clicks through to the canvas, so this is how a click or drag "inside" one is found. */
function frameUnder(ev) {
  const [x, y] = world2(ev);
  return S.frames.filter((o) => x >= o.x && x <= o.x + o.w && y >= o.y && y <= o.y + fh(o)).sort((p, q) => p.w * fh(p) - q.w * fh(q))[0];
}
/** Drag a frame (and the blocks in it) by its label, or by pressing anywhere inside it on empty canvas. Attached to the stage, so the label is just one of the places to grab. */
const dragFrame = d3.drag()
  .container(() => framesEl)   // the default container is the dragged element itself, which moves with the drag: the pointer position fed back into the next step and the frame stuttered
  .filter((e) => {
    if (e.button || spaceDown || e.shiftKey || e.target.closest("[data-tog], .lk-frmsz, .lk-blk, .lk-port, .lk-ctl, .lk-pop, .lk-hit") || e.target.isContentEditable) return false;
    return !!e.target.closest(".lk-frmlabel") || !!frameUnder(e);
  })
  .on("start", function (e) {
    const f = e.sourceEvent.target.closest(".lk-frmlabel") ? S.frames.find((x) => x.id === e.sourceEvent.target.closest(".lk-frm").dataset.id) : frameUnder(e.sourceEvent);
    closePop(); setSel([], { frame: f.id }); g = { f, el: framesEl.querySelector(`[data-id="${f.id}"]`), rx: f.x, ry: f.y, before: JSON.stringify(S), moved: false };
  })
  .on("drag", function (e) {
    g.rx += e.dx / T.k; g.ry += e.dy / T.k;
    const nx = snap(g.rx), ny = snap(g.ry), dx = nx - g.f.x, dy = ny - g.f.y;
    if (!dx && !dy) return;
    g.moved = true; g.f.x = nx; g.f.y = ny; place(g.f, g.el);
    S.blocks.filter((b) => b.frame === g.f.id).forEach((b) => { b.x += dx; b.y += dy; const el = blocksEl.querySelector(`[data-id="${b.id}"]`); if (el) place(b, el); });
    drawLinks(); mini();
  })
  .on("end", function () { if (g.moved) { hist.push(g.before); fut = []; draw(); } });
/** The corner handle of a frame: drag to resize. */
const resizeFrame = d3.drag()
  .filter((e) => !e.button)
  .on("start", function (e) { e.sourceEvent.stopPropagation(); const f = S.frames.find((x) => x.id === this.parentNode.dataset.id); g = { f, rw: f.w, rh: f.h, before: JSON.stringify(S), moved: false }; })
  .on("drag", function (e) {
    g.rw += e.dx / T.k; g.rh += e.dy / T.k;
    const w = Math.max(160, snap(g.rw)), h = Math.max(100, snap(g.rh));
    if (w === g.f.w && h === g.f.h) return;
    g.moved = true; g.f.w = w; g.f.h = h;
    const el = this.parentNode; el.style.width = w + "px"; el.style.height = h + "px"; drawLinks(); mini();
  })
  .on("end", function () { if (g.moved) { hist.push(g.before); fut = []; S.blocks.forEach((b) => { if (!b.frame) b.frame = frameAt(b); }); draw(); } });

// ---------- drag a link out of a port ----------
const world2 = (ev) => { const r = stage.getBoundingClientRect(); return [(ev.clientX - r.left - T.x) / T.k, (ev.clientY - r.top - T.y) / T.k]; };
function startLink(e, port) {
  e.preventDefault(); closePop();
  const from = ent(port.closest(".lk-blk, .lk-frm").dataset.id), fs = port.dataset.s, [x1, y1] = anchor(from, fs);   // a block or a frame
  const domOf = (id) => stage.querySelector(`.lk-blk[data-id="${id}"], .lk-frm[data-id="${id}"]`);
  const drop = (ev) => {   // a block under the pointer, or a frame's point; a collapsed frame (one small row) can also be dropped on anywhere. Inside an open frame the drop stays "add after", so a card can be added in the phase.
    const hit = document.elementFromPoint(ev.clientX, ev.clientY), el = hit?.closest(".lk-blk"), fp = hit?.closest(".lk-frm .lk-port"), fr = frameUnder(ev), id = el ? el.dataset.id : fp ? fp.closest(".lk-frm").dataset.id : fr?.collapsed ? fr.id : "";
    return id && id !== from.id ? ent(id) : null;
  };
  /** The side of the target the link lands on: the port under the pointer, else the side of the block nearest to it. */
  const side = (ev, t) => {
    const p = document.elementFromPoint(ev.clientX, ev.clientY)?.closest(".lk-port");
    if (p) return p.dataset.s;
    const [x, y] = world2(ev), dx = (x - (t.x + t.w / 2)) / t.w, dy = (y - (t.y + t.h / 2)) / t.h;
    return Math.abs(dx) > Math.abs(dy) ? (dx < 0 ? "l" : "r") : (dy < 0 ? "t" : "b");
  };
  port.classList.add("lk-from");
  const move = (ev) => {
    const [x, y] = world2(ev), t = drop(ev);
    liveEl.innerHTML = `<path class="lk-link lk-live" d="${curve(x1, y1, fs, x, y, null, null)}"/>`;
    stage.querySelectorAll(".lk-drop, .lk-near").forEach((n) => n.classList.remove("lk-drop", "lk-near"));
    if (t && !reason(from, t)) {   // the block under the line shows its four points; the one the link would take is lit, and the line snaps to it
      const el = domOf(t.id), sd = side(ev, t);
      el.classList.add("lk-drop"); el.querySelector(`.lk-p${sd}`)?.classList.add("lk-near");
      const [x2, y2] = anchor(t, sd);
      liveEl.innerHTML = `<path class="lk-link lk-live" d="${curve(x1, y1, fs, x2, y2, sd, null)}"/>`;
    }
  };
  const up = (ev) => {
    removeEventListener("mousemove", move); removeEventListener("mouseup", up);
    liveEl.innerHTML = ""; port.classList.remove("lk-from"); stage.querySelectorAll(".lk-drop, .lk-near").forEach((n) => n.classList.remove("lk-drop", "lk-near"));
    const t = drop(ev);
    if (t) {
      const why = reason(from, t);
      if (why) toast({ message: why, ms: 3000 });
      else mutate(() => S.links.push({ id: nid("l"), from: from.id, to: t.id, kind: kindFrom(from, t), fs, ts: side(ev, t) }));
    } else if (!document.elementFromPoint(ev.clientX, ev.clientY)?.closest(".lk-ctl")) openPop(ev, from, fs);
  };
  addEventListener("mousemove", move); addEventListener("mouseup", up);
}

// ---------- quick add after a dropped link ----------
let popGone = { id: "", at: 0 };   // the card whose menu was just closed by this same click: clicking it again closes the menu instead of reopening it
let hoverT = 0;
const closePop = () => { clearTimeout(hoverT); if (popEl?.dataset.for) popGone = { id: popEl.dataset.for, at: Date.now() }; popEl?.remove(); popEl = null; };
function openPop(ev, from, fs = "r") {
  closePop();
  const r = stage.getBoundingClientRect(), [wx, wy] = world2(ev);
  popEl = document.createElement("div");
  popEl.className = "lk-pop lk-ctl"; popEl.dataset.for = from.id; popEl.dataset.hover = "1";
  popEl.style.left = Math.max(8, Math.min(ev.clientX - r.left, r.width - 210)) + "px"; popEl.style.top = Math.max(8, Math.min(ev.clientY - r.top, r.height - 224)) + "px";
  popEl.innerHTML = `<div class="lk-pophead">Add after ${esc(from.title)}</div>` +
    [["prompt", "Prompt"], ["spec", "Spec"], ["reference", "Reference"], ["find", "From Studio…"]].map(([k, l], i) => `<button type="button" data-k="${k}" class="${i ? "" : "hv"}">${ic(P[k], 16)}${l}</button>`).join("");
  popEl.addEventListener("click", async (e) => {
    const k = e.target.closest("button")?.dataset.k;
    if (!k) return;
    closePop();
    if (k === "find") {
      const p = await pickStudio();
      if (p) addBlock("prompt", wx, wy, from, { fs, title: p.title, derived: { store: "studio", id: p.id }, text: p.text });
      return;
    }
    addBlock(k, wx, wy, from, { fs });
  });
  stage.append(popEl);
}

// ---------- the card menu (the ⋯ on a card) ----------
function openCardMenu(btn, b) {
  closePop();
  const r = btn.getBoundingClientRect(), sr = stage.getBoundingClientRect();
  const edit = b.type === "note" ? "Edit note" : b.type === "reference" ? "Edit file or link" : "Edit text and settings";
  const items = [["edit", edit, P.edit], ...(b.type === "start" ? [] : [["dup", "Duplicate", P.copy], ["del", "Delete", P.trash]])];
  popEl = document.createElement("div");
  popEl.className = "lk-pop lk-ctl"; popEl.dataset.hover = "1"; popEl.dataset.armed = "1"; popEl.dataset.for = b.id;   // goes away when the pointer leaves the card and the menu
  popEl.style.left = Math.max(8, Math.min(r.left - sr.left, sr.width - 214)) + "px"; popEl.style.top = Math.min(r.bottom - sr.top + 4, sr.height - 40 - items.length * 34) + "px";
  popEl.innerHTML = `<div class="lk-pophead">${esc(b.title.length > 22 ? b.title.slice(0, 22) + "…" : b.title)}</div>` + items.map(([k, l, i], n) => `<button type="button" data-k="${k}" class="${n ? "" : "hv"}">${ic(i, 16)}${l}</button>`).join("");
  popEl.addEventListener("click", (e) => {
    const k = e.target.closest("button")?.dataset.k;
    if (!k) return;
    closePop();
    if (k === "edit") { setSel([b.id]); panel.open(b.id); }
    else if (k === "dup") dupBlock(b.id);
    else { setSel([b.id]); removeSel(); }
  });
  stage.append(popEl);
}

// ---------- add, remove, rename ----------
/** Nudge a new block to the nearest spot (on the 10px grid) that does not sit on another block. */
function freeSpot(b) {
  const clash = (x, y) => S.blocks.some((o) => !hidden(o) && x < o.x + o.w + 20 && x + b.w + 20 > o.x && y < o.y + o.h + 20 && y + b.h + 20 > o.y);
  if (!clash(b.x, b.y)) return;
  for (let r = 1; r <= 40; r++) {
    const ring = [];
    for (let dx = -r; dx <= r; dx++) for (let dy = -r; dy <= r; dy++) if (Math.max(Math.abs(dx), Math.abs(dy)) === r) ring.push([dx, dy]);
    ring.sort((p, q) => p[0] * p[0] + p[1] * p[1] - (q[0] * q[0] + q[1] * q[1]));
    const hit = ring.find(([dx, dy]) => !clash(b.x + dx * 30, b.y + dy * 30));
    if (hit) { b.x = snap(b.x + hit[0] * 30); b.y = snap(b.y + hit[1] * 30); return; }
  }
}
/** A frame that opens again needs its full area: cards that sit outside it but overlap it move out, each by the shortest way, to just beside the frame. */
function pushOut(f) {
  const m = 30;
  S.blocks.filter((o) => !o.frame && !hidden(o) && o.x < f.x + f.w && o.x + o.w > f.x && o.y < f.y + f.h && o.y + o.h > f.y).forEach((o) => {
    const way = [[f.x - m - (o.x + o.w), 0], [f.x + f.w + m - o.x, 0], [0, f.y - m - (o.y + o.h)], [0, f.y + f.h + m - o.y]].sort((a, b) => Math.abs(a[0] + a[1]) - Math.abs(b[0] + b[1]))[0];
    o.x = snap(o.x + way[0]); o.y = snap(o.y + way[1]);
  });
}
const NEW = { prompt: ["New prompt", 190, 88], spec: ["New spec", 170, 70], reference: ["New reference", 170, 70], note: ["Sticky note. Double-click to edit.", 240, 80] };
function addBlock(type, x, y, after, opts = {}) {
  const [title, w, h] = NEW[type], b = { id: nid("b"), type, title: opts.title || title, ...(opts.derived ? { derived_from: opts.derived } : {}), x: snap(after && (opts.fs || "r") === "r" ? Math.max(x, after.x + after.w + 60) : x - w / 2), y: snap(y - h / 2), w, h, agent: type === "prompt" ? "claude" : undefined, status: type === "prompt" ? "todo" : undefined };
  freeSpot(b);
  b.frame = frameAt(b);
  mutate(() => { S.blocks.push(b); if (after) S.links.push({ id: nid("l"), from: after.id, to: b.id, kind: kindFrom(after, b), fs: opts.fs || "r", ts: { r: "l", l: "r", t: "b", b: "t" }[opts.fs || "r"] }); });
  select(b.id);
  if (opts.text) saveNewText(b.id, opts.text);
  return b;
}
/** Save the first text of a block that was just added: the block must reach the server (the graph autosave) before its text can. */
async function saveNewText(bid, text) {
  await flushSave();
  try {
    await api(`linkshell/${proj.id}/blocks/${bid}/text`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text, message: "" }) });
    X.texts[bid] = text; draw();
  } catch (e) { toast({ message: "Could not save the text: " + e.message }); }
}
function dupBlock(id) {
  const o = byId(id);
  if (!o || o.type === "start") return;
  const b = { ...JSON.parse(JSON.stringify(o)), id: nid("b"), title: o.title + " copy", x: snap(o.x + 30), y: snap(o.y + 30) };
  if (b.type === "prompt") b.status = "todo"; else delete b.status;
  delete b.status_at; freeSpot(b); b.frame = frameAt(b);
  mutate(() => S.blocks.push(b));
  select(b.id);
  if (X.texts[id] && b.type !== "note") saveNewText(b.id, X.texts[id]);
}
async function upload(file) {
  if (file.size > 25 * 1024 * 1024) throw new Error("the file is larger than 25 MB");
  const r = await fetch(`/api/linkshell/${proj.id}/assets?name=${encodeURIComponent(file.name)}`, { method: "PUT", body: file });
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || "status " + r.status);
  return (await r.json()).asset;
}
async function openSettings() {
  if (!proj) return;
  const r = await projectSettings(PJ);
  if (!r) return;
  PJ = { ...PJ, ...r }; names(); panel.refresh(); draw();
  toast({ message: "Project settings saved.", ms: 3000 });
}
function names() {
  $("#lk-pname").textContent = PJ.name; $("#lk-slug").textContent = PJ.name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
}
function addFrame() {
  const [x, y] = centre();
  mutate(() => S.frames.push({ id: nid("f"), title: "New phase", x: snap(x - 150), y: snap(y - 100), w: 300, h: 200 }));
}
/** Delete whatever is selected: a link, a frame (its blocks stay), or the selected blocks (the Brief block stays). */
function removeSel() {
  if (selLink) { const id = selLink; mutate(() => { S.links = S.links.filter((l) => l.id !== id); }); clearSel(); return toast({ message: "Link removed", action: "Undo", onAction: undo, ms: 4000 }); }
  if (selFrame) {
    const id = selFrame; mutate(() => { S.blocks.forEach((b) => { if (b.frame === id) b.frame = ""; }); S.frames = S.frames.filter((f) => f.id !== id); S.links = S.links.filter((l) => l.from !== id && l.to !== id); });
    clearSel(); return toast({ message: "Frame removed", action: "Undo", onAction: undo, ms: 4000 });
  }
  const ids = new Set([...sel].filter((id) => byId(id)?.type !== "start"));
  if (sel.size && !ids.size) return toast({ message: "The Brief block cannot be removed.", ms: 3000 });
  if (!ids.size) return;
  mutate(() => { S.blocks = S.blocks.filter((b) => !ids.has(b.id)); S.links = S.links.filter((l) => !ids.has(l.from) && !ids.has(l.to)); });
  clearSel(); draw();
  toast({ message: ids.size > 1 ? `${ids.size} blocks removed` : "Block removed", action: "Undo", onAction: undo, ms: 4000 });
}
/** Move the selection with the arrow keys. */
function nudge(dx, dy) {
  const blocks = [...sel].map(byId).filter(Boolean), frame = S.frames.find((f) => f.id === selFrame);
  if (!blocks.length && !frame) return;
  mutate(() => {
    blocks.forEach((b) => { b.x += dx; b.y += dy; });
    if (frame) { frame.x += dx; frame.y += dy; S.blocks.forEach((b) => { if (b.frame === frame.id) { b.x += dx; b.y += dy; } }); }
    blocks.forEach((b) => { b.frame = frameAt(b); });
  });
}
function rename(el, obj = byId(el.closest(".lk-blk")?.dataset.id)) {
  const before = obj.title;
  el.contentEditable = "plaintext-only"; el.focus();
  getSelection().selectAllChildren(el);
  const done = (ok) => {
    el.onblur = el.onkeydown = null; el.contentEditable = "false";
    const v = el.textContent.trim();
    if (ok && v && v !== before) mutate(() => { obj.title = v; }); else el.textContent = before;
  };
  el.onblur = () => done(true);
  el.onkeydown = (e) => { if (e.key === "Enter") { e.preventDefault(); done(true); } else if (e.key === "Escape") { e.stopPropagation(); done(false); } };
}
/** Where a block added or moved from the Outline sits on the canvas: under the other blocks of its phase (the phase grows to hold it), or below everything when it has no phase. */
function slot(b, fid) {
  const f = fid && S.frames.find((x) => x.id === fid);
  b.frame = f ? f.id : "";
  const mates = S.blocks.filter((o) => o.id !== b.id && (o.frame || "") === b.frame);
  if (f) {
    f.collapsed = false;
    b.x = snap(mates.length ? Math.min(...mates.map((o) => o.x)) : f.x + 30);
    b.y = snap(mates.length ? Math.max(...mates.map((o) => o.y + o.h)) + 30 : f.y + 50);
    f.w = Math.max(f.w, b.x + b.w + 30 - f.x); f.h = Math.max(f.h, b.y + b.h + 30 - f.y);
    pushOut(f);
  } else {
    const rest = [...S.blocks.filter((o) => o.id !== b.id), ...S.frames.map((x) => frameEnt(x.id))];
    b.x = 30; b.y = snap(rest.length ? Math.max(...rest.map((o) => o.y + o.h)) + 40 : 40);
  }
}
/** Add a block from the Outline. `after` splices a new Prompt into the run order right behind that block; `parent` feeds a new Spec into that Prompt. Returns the id. */
let fitOnCanvas = false;   // set when the Outline added or moved a block: the next visit to the Canvas fits everything once, so the new blocks are not left off-screen
function outlineAdd({ type, frame = "", after = "", parent = "", title }) {
  fitOnCanvas = true;
  const [t0, w, h] = NEW[type], b = { id: nid("b"), type, title: title || t0, x: 0, y: 0, w, h, agent: type === "prompt" ? "claude" : undefined, status: type === "prompt" ? "todo" : undefined };
  const link = (from, to) => ({ id: nid("l"), from, to, kind: "order", fs: "r", ts: "l" });
  mutate(() => {
    S.blocks.push(b); slot(b, frame);
    if (after && type === "prompt" && byId(after)) { S.links.forEach((l) => { if (l.from === after && l.kind === "order") l.from = b.id; }); S.links.push(link(after, b.id)); }
    if (parent && type !== "prompt" && byId(parent)) S.links.push(link(b.id, parent));
  });
  return b.id;
}
/** Remove several blocks at once (the Brief is never removed), with one Undo. */
function outlineRemoveMany(ids) { clearSel(); sel = new Set(ids); removeSel(); clearSel(); }
/** Empty the plan: every block except the Brief, every phase and every link. One Undo brings it all back. */
function outlineClear() {
  const nb = S.blocks.filter((b) => b.type !== "start").length, nf = S.frames.length;
  if (!nb && !nf) return;
  mutate(() => { S.blocks = S.blocks.filter((b) => b.type === "start"); S.frames = []; S.links = []; });
  clearSel();
  toast({ message: `Plan cleared (${nb} block${nb === 1 ? "" : "s"}${nf ? `, ${nf} phase${nf === 1 ? "" : "s"}` : ""})`, action: "Undo", onAction: undo, ms: 6000 });
}
/** A new empty phase below everything on the canvas. */
function outlineFrame() {
  fitOnCanvas = true;
  const rest = [...S.blocks, ...S.frames.map((x) => frameEnt(x.id))], f = { id: nid("f"), title: "New phase", x: 30, y: snap(rest.length ? Math.max(...rest.map((o) => o.y + o.h)) + 60 : 40), w: 300, h: 200 };
  mutate(() => S.frames.push(f));
  return f.id;
}
const addAtCentre = (type) => { const [x, y] = centre(); addBlock(type, x, y); };
/** What the ⌘K palette offers while a canvas is open (home.js lists them). */
export const canvasActions = { addPrompt: () => addAtCentre("prompt"), fit: () => fit(), tidy: () => tidyUp(), settings: () => openSettings() };
function tidyUp() {
  if (S.blocks.length < 2) return toast({ message: "Nothing to tidy yet.", ms: 2500 });
  mutate(() => { S.links.forEach((l) => { delete l.fs; delete l.ts; }); tidy(S); });   // Tidy up lays out left to right, so links go back to right-to-left
  fit();
  toast({ message: "Blocks arranged", action: "Undo", onAction: undo, ms: 4000 });
}
const centre = () => { const r = stage.getBoundingClientRect(); return world2({ clientX: r.left + r.width / 2, clientY: r.top + r.height / 2 }); };

// ---------- zoom, grid, fit, minimap ----------
function grid() {
  let step = 18 * T.k;
  while (step < 9) step *= 2;
  stage.style.backgroundSize = `${step}px ${step}px`;
  stage.style.backgroundPosition = `${T.x}px ${T.y}px`;
}
function bounds(withView) {
  const xs = [], ys = [];
  S.frames.forEach((f) => { xs.push(f.x, f.x + f.w); ys.push(f.y, f.y + fh(f)); });
  S.blocks.filter((b) => !hidden(b)).forEach((o) => { xs.push(o.x, o.x + o.w); ys.push(o.y, o.y + o.h); });
  if (withView) { xs.push(-T.x / T.k, (stage.clientWidth - T.x) / T.k); ys.push(-T.y / T.k, (stage.clientHeight - T.y) / T.k); }
  const x = Math.min(...xs), y = Math.min(...ys);
  return { x, y, w: Math.max(...xs) - x, h: Math.max(...ys) - y };
}
function fit(animate = true) {
  const bb = bounds(false), W = stage.clientWidth, H = stage.clientHeight, pad = 64;
  const k = Math.max(0.2, Math.min(1.25, (W - 2 * pad) / bb.w, (H - 2 * pad) / bb.h));
  const t = d3.zoomIdentity.translate(W / 2 - k * (bb.x + bb.w / 2), H / 2 - k * (bb.y + bb.h / 2)).scale(k);
  (animate ? zoomSel.transition().duration(350) : zoomSel).call(zoom.transform, t);
}
let mm = null;
function mini() {
  if (!miniEl) return;
  const W = 140, H = 92, pad = 6, bb = bounds(true), s = Math.min((W - 2 * pad) / bb.w, (H - 2 * pad) / bb.h);
  const ox = (W - bb.w * s) / 2 - bb.x * s, oy = (H - bb.h * s) / 2 - bb.y * s;
  mm = { s, ox, oy };
  const r = (o, cls, rx) => `<rect class="${cls}" x="${o.x * s + ox}" y="${o.y * s + oy}" width="${Math.max(2, o.w * s)}" height="${Math.max(2, o.h * s)}" rx="${rx}"/>`;
  miniEl.innerHTML = S.frames.map((f) => r({ ...f, h: fh(f) }, "mm-frame", 2)).join("") + S.blocks.filter((b) => !hidden(b)).map((b) => r(b, `mm-blk mm-${status(b)}${sel.has(b.id) ? " mm-sel" : ""}`, 1.5)).join("") +
    r({ x: -T.x / T.k, y: -T.y / T.k, w: stage.clientWidth / T.k, h: stage.clientHeight / T.k }, "mm-view", 3);
}
function jump(ev) {
  const r = miniEl.getBoundingClientRect();
  zoomSel.call(zoom.translateTo, (ev.clientX - r.left - mm.ox) / mm.s, (ev.clientY - r.top - mm.oy) / mm.s);
}

// ---------- selection box, Tab through the steps ----------
function boxSelect(e0) {
  e0.preventDefault();
  const r0 = stage.getBoundingClientRect(), box = document.createElement("div");
  box.className = "lk-box"; stage.append(box);
  const rect = (ev) => { const x = Math.min(e0.clientX, ev.clientX) - r0.left, y = Math.min(e0.clientY, ev.clientY) - r0.top; return { x, y, w: Math.abs(ev.clientX - e0.clientX), h: Math.abs(ev.clientY - e0.clientY) }; };
  const move = (ev) => { const q = rect(ev); Object.assign(box.style, { left: q.x + "px", top: q.y + "px", width: q.w + "px", height: q.h + "px" }); };
  const up = (ev) => {
    removeEventListener("mousemove", move); removeEventListener("mouseup", up); box.remove();
    const q = rect(ev), x0 = (q.x - T.x) / T.k, y0 = (q.y - T.y) / T.k, x1 = x0 + q.w / T.k, y1 = y0 + q.h / T.k;
    setSel(S.blocks.filter((b) => !hidden(b) && b.x < x1 && b.x + b.w > x0 && b.y < y1 && b.y + b.h > y0).map((b) => b.id));
  };
  addEventListener("mousemove", move); addEventListener("mouseup", up);
}
/** Tab / Shift+Tab: select the next or previous step in run order and bring it into view. */
function stepSel(dir) {
  const steps = runOrder(S).filter((b) => !hidden(b));
  if (!steps.length) return;
  const cur = steps.findIndex((b) => sel.has(b.id)), next = steps[(cur < 0 ? (dir > 0 ? 0 : steps.length - 1) : (cur + dir + steps.length) % steps.length)];
  setSel([next.id]);
  const x = next.x * T.k + T.x, y = next.y * T.k + T.y;
  if (x < 0 || y < 0 || x + next.w * T.k > stage.clientWidth || y + next.h * T.k > stage.clientHeight) zoomSel.transition().duration(250).call(zoom.translateTo, next.x + next.w / 2, next.y + next.h / 2);
}

// ---------- page ----------
function mount(page) {
  const btn = (id, icon, title, extra = "") => `<button class="lk-ib" type="button" id="${id}" title="${title}" aria-label="${title}" ${extra}>${ic(P[icon], 16)}</button>`;
  page.innerHTML = `
    <div class="lk-top">
      <button class="icon-btn" type="button" id="lk-back" aria-label="Back">${ic(P.back)}</button>
      <div class="lk-name">
        <div class="lk-crumb">linkshell / <span id="lk-slug"></span></div>
        <div class="lk-h"><span id="lk-pname"></span> <span class="lk-meta" id="lk-meta"></span></div>
      </div>
      <div class="seg" role="group" aria-label="View"><button type="button" class="on" data-view="canvas">Canvas</button><button type="button" data-view="follow">Follow</button><button type="button" data-view="outline">Outline</button></div>
      <button class="icon-btn lk-bordered" type="button" id="lk-settings" title="Project settings" aria-label="Project settings">${ic(P.sliders)}</button>
      <details class="pr-more lk-exp" id="lk-export">
        <summary class="icon-btn lk-bordered" title="Export" aria-label="Export">${ic(P.download)}</summary>
        <div class="pr-menu pr-morepanel" role="menu">${exportItems(ic(P.download, 18))}</div>
      </details>
    </div>
    <div class="lk-stage" id="lk-stage" tabindex="-1">
      <div class="lk-world"><svg class="lk-links" width="1" height="1"></svg><div class="lk-frames"></div><div class="lk-blocks"></div><svg class="lk-livesvg" width="1" height="1"></svg></div>
      <div class="lk-tool lk-ctl" role="toolbar" aria-label="Add">
        ${btn("lk-add-prompt", "prompt", "Add a Prompt block")}${btn("lk-add-spec", "spec", "Add a Spec block")}${btn("lk-add-reference", "reference", "Add a Reference block")}${btn("lk-add-note", "note", "Add a sticky note")}${btn("lk-add-frame", "frame", "Add a frame")}
      </div>
      <div class="lk-legend lk-ctl" aria-hidden="true">
        <span><svg width="22" height="6"><path d="M1 3H21" class="lk-link lk-order"/></svg> order</span>
        <span class="lk-lg-done">${ic(P.check, 12)} done</span><span class="lk-lg-ready">${ic(P.play, 10)} ready</span>
      </div>
      <div class="lk-zoom lk-ctl">
        ${btn("lk-zout", "minus", "Zoom out")}<button class="lk-zpct" type="button" id="lk-zpct" title="Reset to 100%">100%</button>${btn("lk-zin", "plus", "Zoom in")}
        <span class="lk-sep"></span>${btn("lk-fit", "fit", "Fit to screen (F)")}${btn("lk-tidy", "tidy", "Tidy up")}${btn("lk-undo", "undo", "Undo")}${btn("lk-redo", "redo", "Redo")}
      </div>
      <svg class="lk-mini lk-ctl" id="lk-mini" width="140" height="92" aria-hidden="true"></svg>
      <aside class="lk-panel lk-ctl" id="lk-panel" hidden aria-label="Block settings"></aside>
    </div>
    <div class="lk-follow" id="lk-follow" hidden></div>
    <div class="lk-outline" id="lk-outline" hidden></div>`;
  stage = $("#lk-stage"); world = stage.querySelector(".lk-world"); framesEl = stage.querySelector(".lk-frames"); blocksEl = stage.querySelector(".lk-blocks");
  linksEl = stage.querySelector(".lk-links"); liveEl = stage.querySelector(".lk-livesvg"); miniEl = $("#lk-mini");
  panel = createPanel({ el: $("#lk-panel"), S: () => S, byId, mutate, flush: () => flushSave(), pid: () => proj.id, project: () => PJ, texts: new Proxy({}, { get: (_, k) => X.texts[k], set: (_, k, v) => { X.texts[k] = v; return true; }, has: (_, k) => k in X.texts }),
    status, duplicate: dupBlock, remove: (id) => { setSel([id]); removeSel(); }, changed: draw, upload, deselect: () => { setSel([]); stage.focus({ preventScroll: true }); }, focusCanvas: () => stage.focus({ preventScroll: true }) });

  followEl = $("#lk-follow");
  follow = createFollow({ el: followEl, S: () => S, texts: () => X.texts, pid: () => proj.id, status, mutate, undo, flush: () => flushSave(),
    touch: (fn) => { fn(); draw(); }, toCanvas: (id) => { reveal = id || ""; location.hash = "#/linkshell/" + proj.id; } });
  outlineEl = $("#lk-outline");
  outline = createOutline({ el: outlineEl, S: () => S, status, mutate, undo, touch: (fn) => { fn(); draw(); }, toCanvas: (id) => { reveal = id || ""; location.hash = "#/linkshell/" + proj.id; },
    add: outlineAdd, addFrame: outlineFrame, removeMany: outlineRemoveMany, clear: outlineClear, move: (id, fid) => { const b = byId(id); if (b) { fitOnCanvas = true; mutate(() => slot(b, fid)); } }, remove: (id) => { sel = new Set([id]); selLink = ""; selFrame = ""; removeSel(); clearSel(); }, removeFrame: (id) => { clearSel(); selFrame = id; removeSel(); clearSel(); } });
  page.querySelectorAll("[data-view]").forEach((b) => b.addEventListener("click", () => { location.hash = "#/linkshell/" + proj.id + (b.dataset.view === "follow" ? "/follow" : b.dataset.view === "outline" ? "/outline" : ""); }));

  zoom = d3.zoom().scaleExtent([0.2, 2])
    .filter((e) => (e.type === "wheel" ? e.ctrlKey || e.metaKey : e.button === 1 ? !e.target.closest(".lk-ctl, .lk-pop") : !e.button && !e.shiftKey && !e.target.closest(".lk-ctl, .lk-hit") && (spaceDown || !(e.target.closest(".lk-blk, .lk-frmlabel, .lk-frmsz, .lk-port") || frameUnder(e)))))   // middle button (or Space) pans from anywhere; Shift is the selection box
    .on("start", () => stage.classList.add("lk-panning")).on("end", () => stage.classList.remove("lk-panning"))
    .on("zoom", (e) => {
      T = e.transform;
      closePop();   // a floating menu would stay put on screen while the canvas moves under it
      world.style.transform = `translate(${T.x}px,${T.y}px) scale(${T.k})`;
      $("#lk-zpct").textContent = Math.round(T.k * 100) + "%";
      grid(); mini(); saveView();
    });
  zoomSel = d3.select(stage).call(dragFrame).call(zoom).on("dblclick.zoom", null);
  // Plain wheel and trackpad scroll pan; Ctrl or Cmd with the wheel, and a pinch, zoom (d3-zoom handles those).
  // Hold the middle button (the scroll wheel pressed in) and roll the wheel: up zooms in, down zooms out, around the pointer.
  stage.addEventListener("mousedown", (e) => { if (e.button !== 1) return; e.preventDefault(); stage.classList.add("lk-mid"); });   // no autoscroll cursor; closed hand while held
  addEventListener("mouseup", (e) => { if (e.button === 1) stage.classList.remove("lk-mid"); });
  stage.addEventListener("wheel", (e) => {
    if (!(e.buttons & 4) || e.target.closest(".lk-pop, .lk-panel")) return;
    e.preventDefault(); e.stopImmediatePropagation();
    const dy = e.deltaY * (e.deltaMode === 1 ? 33 : e.deltaMode === 2 ? 400 : 1);
    zoomSel.call(zoom.scaleBy, Math.exp(-dy * 0.002), d3.pointer(e, stage));
  }, { passive: false, capture: true });
  stage.addEventListener("wheel", (e) => {
    if (e.ctrlKey || e.metaKey || e.target.closest(".lk-pop, .lk-panel")) return;   // the panel scrolls by itself
    e.preventDefault(); zoomSel.call(zoom.translateBy, -e.deltaX / T.k, -e.deltaY / T.k);
  }, { passive: false });

  stage.addEventListener("mousedown", (e) => {
    const port = e.target.closest(".lk-port");
    if (port && !e.button) startLink(e, port);
    else if (e.shiftKey && !e.button && !e.target.closest(".lk-blk, .lk-ctl, .lk-frmlabel, .lk-pop, .lk-hit")) boxSelect(e);
    else if (!e.target.closest(".lk-pop")) closePop();
  });
  stage.addEventListener("mousemove", (e) => {   // the "Add after" menu opened by clicking a card goes away when the pointer leaves both the card and the menu
    if (!popEl?.dataset.hover) return;
    if (e.target.closest(".lk-pop") || e.target.closest(".lk-blk")?.dataset.id === popEl.dataset.for) { popEl.dataset.armed = "1"; clearTimeout(hoverT); delete popEl.dataset.timing; return; }
    const r = popEl.getBoundingClientRect(), far = Math.hypot(Math.max(r.left - e.clientX, e.clientX - r.right, 0), Math.max(r.top - e.clientY, e.clientY - r.bottom, 0)) > 60;
    if ((popEl.dataset.armed || far) && !popEl.dataset.timing) { popEl.dataset.timing = "1"; hoverT = setTimeout(closePop, 220); }   // a menu dropped from a link has not been entered yet: it goes once the pointer is well away
  });
  stage.addEventListener("click", (e) => {
    if (!e.target.isConnected) return;   // a panel button that redrew the panel while handling this click: the click was inside the panel
    const more = e.target.closest(".lk-more");
    if (more) { const b = byId(more.closest(".lk-blk").dataset.id); if (!sel.has(b.id)) setSel([b.id]); return openCardMenu(more, b); }
    const st = e.target.closest(".lk-st"), tog = e.target.closest("[data-tog]"), blk = e.target.closest(".lk-blk"), hit = e.target.closest(".lk-hit");
    if (st) { const b = byId(st.closest(".lk-blk").dataset.id); return mutate(() => { b.status = b.status === "done" ? "todo" : "done"; }); }
    if (tog) { const f = S.frames.find((x) => x.id === tog.closest(".lk-frm").dataset.id); return mutate(() => { f.collapsed = !f.collapsed; if (!f.collapsed) pushOut(f); }); }
    if (blk && e.shiftKey) { const id = blk.dataset.id, ids = new Set(sel); ids.has(id) ? ids.delete(id) : ids.add(id); return setSel([...ids]); }
    if (hit) return setSel([], { link: hit.dataset.id });
    if (blk && !e.shiftKey && !e.target.closest(".lk-st, .lk-port") && !e.target.isContentEditable && sel.size <= 1) {   // a plain click on a card: the "Add after" menu beside it
      const b = byId(blk.dataset.id), r = blk.getBoundingClientRect();
      if (b.type !== "note" && !(popGone.id === b.id && Date.now() - popGone.at < 400)) { openPop({ clientX: r.right + 8, clientY: r.top }, b); popEl.dataset.armed = "1"; }
      return;
    }
    if (!e.target.closest(".lk-blk, .lk-ctl, .lk-frmlabel, .lk-frmsz, .lk-pop")) {   // a click on empty canvas: the frame under the pointer (the smallest, when frames overlap) is selected, else nothing
      const f = frameUnder(e);
      setSel([], f ? { frame: f.id } : {});
    }
  });
  stage.addEventListener("dblclick", (e) => {
    closePop();
    const t = e.target.closest(".lk-title, .lk-ntext"), ft = e.target.closest(".lk-frmtitle");
    if (t) rename(t); else if (ft) rename(ft, S.frames.find((f) => f.id === ft.closest(".lk-frm").dataset.id));
  });
  miniEl.addEventListener("mousedown", (e) => { jump(e); const mv = (ev) => jump(ev), up = () => { removeEventListener("mousemove", mv); removeEventListener("mouseup", up); }; addEventListener("mousemove", mv); addEventListener("mouseup", up); });

  const tool = (id, fn) => $(id).addEventListener("click", (e) => { fn(e); stage.focus({ preventScroll: true }); });   // the canvas keys keep working after a toolbar click
  const at = (type) => () => addAtCentre(type);
  tool("#lk-add-prompt", at("prompt")); tool("#lk-add-spec", at("spec")); tool("#lk-add-reference", at("reference")); tool("#lk-add-note", at("note")); tool("#lk-add-frame", addFrame);
  tool("#lk-zout", () => zoomSel.transition().duration(160).call(zoom.scaleBy, 1 / 1.25)); tool("#lk-zin", () => zoomSel.transition().duration(160).call(zoom.scaleBy, 1.25));
  tool("#lk-zpct", () => zoomSel.transition().duration(200).call(zoom.scaleTo, 1)); tool("#lk-fit", () => fit());
  tool("#lk-tidy", tidyUp);
  tool("#lk-undo", undo); tool("#lk-redo", redo); tool("#lk-back", async () => {
    if (panel.dirty() && !await confirmDialog({ title: "Unsaved changes", message: "A block has text that is not saved. Leave and discard it?", confirmLabel: "Discard", danger: true })) return;
    location.hash = view === "canvas" ? lastHome : "#/linkshell/" + proj.id;   // inside a project, Back from Follow or Outline returns to its canvas; from the canvas it returns to the list
  });
  tool("#lk-settings", openSettings);
  page.querySelector("#lk-export").addEventListener("click", async (e) => {   // the file is read from disk, so save the last canvas edits first
    if (e.target.closest("[data-export]")) { e.target.closest("details").open = false; await flushSave(); exportClick(e, proj.id); }
  });
  page.querySelectorAll("[data-soon]").forEach((b) => b.addEventListener("click", () => toast({ message: b.dataset.soon, ms: 3000 })));

  const hint = () => { [["prompt", "a Prompt block", "lsadd"], ["reference", "a Reference block", "lsref"], ["note", "a sticky note", "lsnote"], ["frame", "a frame", "lsframe"]].forEach(([k, what, hk]) => { $(`#lk-add-${k}`).title = `Add ${what} (${keyLabel(hotkey(hk))})`; }); $("#lk-tidy").title = `Tidy up (${keyLabel(hotkey("lstidy"))})`; };
  hint(); addEventListener("flowlystack-hotkeys", hint);
  const typing = (e) => /^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName) || e.target.isContentEditable;
  addEventListener("keydown", (e) => {
    if (!stage.offsetParent || e.defaultPrevented || document.querySelector("dialog[open]") || typing(e)) return;   // stage.offsetParent: the canvas page itself has display: contents
    if (matches(e, "lsadd")) { e.preventDefault(); return addAtCentre("prompt"); }
    if (matches(e, "lsref")) { e.preventDefault(); return addAtCentre("reference"); }
    if (matches(e, "lsnote")) { e.preventDefault(); return addAtCentre("note"); }
    if (matches(e, "lsframe")) { e.preventDefault(); return addFrame(); }
    if (matches(e, "lstidy")) { e.preventDefault(); return tidyUp(); }
    const ae = document.activeElement;
    if (ae && ae !== document.body && (!stage.contains(ae) || ae.closest(".lk-panel"))) return;   // focus is on some other control (a menu, the sidebar): leave the keys to it
    const mod = e.metaKey || e.ctrlKey, plain = !mod && !e.altKey;
    if (mod && e.code === "KeyZ") { e.preventDefault(); e.shiftKey ? redo() : undo(); }
    else if (mod && e.code === "KeyA") { e.preventDefault(); setSel(S.blocks.filter((b) => !hidden(b)).map((b) => b.id)); }
    else if (plain && (e.key === "Delete" || e.key === "Backspace")) { e.preventDefault(); removeSel(); }
    else if (plain && e.key.toLowerCase() === "f") { e.preventDefault(); fit(); }
    else if (plain && e.key.startsWith("Arrow")) { e.preventDefault(); const n = e.shiftKey ? 50 : 10; nudge(e.key === "ArrowLeft" ? -n : e.key === "ArrowRight" ? n : 0, e.key === "ArrowUp" ? -n : e.key === "ArrowDown" ? n : 0); }
    else if (plain && e.key === "Tab") { e.preventDefault(); stepSel(e.shiftKey ? -1 : 1); }
    else if (plain && e.key === "Enter" && sel.size === 1) { e.preventDefault(); panel.open([...sel][0]); panel.focusTitle(); }   // Enter opens the panel on the selected block
    else if (plain && e.code === "Space") { e.preventDefault(); if (!spaceDown) { spaceDown = true; stage.classList.add("lk-space"); } }
    else if (e.key === "Escape") { closePop(); setSel([]); document.activeElement?.blur?.(); }
  });
  addEventListener("keyup", (e) => { if (e.code === "Space") { spaceDown = false; stage?.classList.remove("lk-space"); } });
  addEventListener("blur", () => { spaceDown = false; stage?.classList.remove("lk-space"); });
  new ResizeObserver(() => { if (!stage.offsetParent) return; if (needFit && stage.clientWidth > 200) settleView(); else mini(); }).observe(stage);
}

/** Switch between the Canvas and the Follow view of the open project (the URL decides: #/linkshell/<id> or #/linkshell/<id>/follow). */
export function setView(v) {
  if (!stage) return;
  view = v === "follow" || v === "outline" ? v : "canvas";
  if (view !== "canvas") panel?.close();
  if (view === "follow") follow.flushNote(); else outline.flush();
  stage.hidden = view !== "canvas"; followEl.hidden = view !== "follow"; outlineEl.hidden = view !== "outline";
  $("#lk-canvas").querySelectorAll("[data-view]").forEach((b) => b.classList.toggle("on", b.dataset.view === view));
  if (view === "follow") follow.show();
  else if (view === "outline") outline.show();
  else if (reveal) { fitOnCanvas = false; const id = reveal; reveal = ""; requestAnimationFrame(() => { if (byId(id)) { setSel([id]); zoomSel.call(zoom.translateTo, byId(id).x + byId(id).w / 2, byId(id).y + byId(id).h / 2); } }); }
  else if (fitOnCanvas) requestAnimationFrame(() => { if (stage.clientWidth > 200) { fitOnCanvas = false; fit(false); } });
}

let needFit = false, lastHome = "#/linkshell";
export const setHome = (h) => { lastHome = h; };
let host = null;
/** Build the canvas once into `el` (the page's canvas view). */
export function mountCanvas(el) { if (!host) { host = el; mount(el); } }
/** Show a project (the API's `{project, graph, texts}`) on the canvas. Edits save themselves about half a second after each change. */
export function loadProject(data) {
  proj = { id: data.project.id, rev: data.graph.rev }; dead = false; saveState = "saved"; clearTimeout(timer);
  S = { frames: data.graph.frames, blocks: data.graph.blocks, links: data.graph.links.map((l) => ({ ...l, kind: "order" })) };   // older projects had a second, dashed kind of link: it is the same thing now
  X = { texts: data.texts || {} }; PJ = { ...data.project, assets_dir: data.assets_dir || "" }; panel.reset(); follow.reset(); outline.reset(); fitOnCanvas = false;
  savedSig = JSON.stringify(S); T = d3.zoomIdentity; hist = []; fut = []; clearSel(); closePop();
  names();
  draw();
  const v = data.graph.viewport, saved = v && (v.x || v.y || (v.k && v.k !== 1)) ? v : null;   // a project never panned or zoomed still holds the default 0, 0, 1: fit it
  viewReady = false; clearTimeout(viewTimer);
  needFit = true; pendingView = saved;
  requestAnimationFrame(settleView);
}
/** First placement of a freshly loaded project, once the stage has a size (it has none while the Follow view is showing): the remembered view, else fit. */
function settleView() {
  if (!needFit || stage.clientWidth <= 200) return;
  needFit = false;
  if (pendingView) zoomSel.call(zoom.transform, d3.zoomIdentity.translate(pendingView.x, pendingView.y).scale(Math.min(2, Math.max(0.2, pendingView.k || 1))));
  else fit(false);
  pendingView = null; viewReady = true;   // from here on, a pan or zoom is the user's and is remembered
}

// ---------- remembered view ----------
// Where the canvas was panned and zoomed comes back after a refresh. Saved on its own (PUT .../viewport, no new revision), about a second after the last move.
let viewTimer = 0, viewReady = false, pendingView = null;
function saveView() {
  if (!viewReady || !proj) return;
  clearTimeout(viewTimer);
  const id = proj.id, v = { x: T.x, y: T.y, k: T.k };
  viewTimer = setTimeout(() => { api(`linkshell/${id}/viewport`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(v) }).catch(() => {}); }, 800);
}
addEventListener("pagehide", () => { if (viewReady && proj) { clearTimeout(viewTimer); fetch(`/api/linkshell/${proj.id}/viewport`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ x: T.x, y: T.y, k: T.k }), keepalive: true }); } });

// ---------- autosave ----------
let proj = null, savedSig = "", timer = 0, inflight = false, dead = false, saveState = "saved";
const body = () => JSON.stringify({ graph: { ...S, viewport: { x: T.x, y: T.y, k: T.k } }, rev: proj.rev });
function autosave() {
  if (!proj || dead || JSON.stringify(S) === savedSig) return;
  saveState = "saving…"; $("#lk-meta") && meta0();
  clearTimeout(timer); timer = setTimeout(flushSave, 500);
}
const meta0 = () => { const m = $("#lk-meta").textContent; $("#lk-meta").textContent = m.replace(/ · (saved|saving…|not saved)$/, ` · ${saveState}`); };
/** Save now if anything changed (also awaited before leaving a project). */
export async function flushSave() {
  clearTimeout(timer);
  if (!proj || dead) return;
  if (inflight) return void (timer = setTimeout(flushSave, 200));
  const sig = JSON.stringify(S);
  if (sig === savedSig) return;
  inflight = true;
  try {
    const r = await api(`linkshell/${proj.id}/graph`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: body() });
    proj.rev = r.graph.rev; savedSig = sig; saveState = JSON.stringify(S) === sig ? "saved" : "saving…";
  } catch (e) {
    saveState = "not saved";
    if (e.status === 409) { dead = true; toast({ message: "This project changed in another tab or window. Reload this page to keep working." }); }
    else toast({ message: "Could not save: " + e.message, ms: 4000 });
  } finally { inflight = false; if ($("#lk-meta")) meta0(); }
  if (!dead && saveState === "saving…") autosave();
}
/** Leave the canvas: save what is pending and forget the project. */
export async function unloadProject() { await flushSave(); proj = null; clearTimeout(timer); }
addEventListener("beforeunload", (e) => { if (panel?.dirty()) { e.preventDefault(); e.returnValue = ""; } });
addEventListener("pagehide", () => { if (proj && !dead && JSON.stringify(S) !== savedSig) fetch(`/api/linkshell/${proj.id}/graph`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: body(), keepalive: true }); });

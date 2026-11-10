// Linkshell Follow view: walks the plan one Prompt step at a time. Left rail = steps grouped by frame with
// status dots; main = the current step with the prompt exactly as Copy will paste it, Copy, Mark done, Skip, a step note and "Next up".
// It owns no data: every change goes through the canvas (ctx.mutate / ctx.touch), so statuses autosave with the graph and Undo works. Plain DOM.
import { api } from "../api.js";
import { toast } from "../toast.js";
import { esc, COPY_ICONS } from "../editor.js";
import { hotkey, label as keyLabel } from "../hotkeys.js";
import { copyBlock } from "./project.js";
import { runOrder } from "./layout.js";
import { orderEdges, attachedBlocks } from "./projects.js";

const ic = (d, s = 14) => `<svg viewBox="0 0 24 24" width="${s}" height="${s}" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${d}</svg>`;
const CHECK = `<path d="M5 12.5l4.5 4.5L19 7.5"/>`, PLAY = `<path d="M8 5l11 7-11 7z"/>`, MINUS = `<path d="M5 12h14"/>`;
const WORD = { done: "Done", skipped: "Skipped", ready: "Ready", todo: "To do" };
const kbd = (n) => `<kbd class="kbd" data-hk="${n}">${esc(keyLabel(hotkey(n)))}</kbd>`;
const dot = (st) => `<span class="lkf-dot lkf-${st}">${st === "done" ? ic(CHECK, 10) : st === "ready" ? ic(PLAY, 8) : st === "skipped" ? ic(MINUS, 10) : ""}</span>`;
const finished = (st) => st === "done" || st === "skipped";

/** ctx: { el, S(), texts(), pid(), status(b), mutate(fn), touch(fn), undo(), flush(), toCanvas(blockId?) } */
export function createFollow(ctx) {
  const el = ctx.el;
  let cur = "";          // the step being shown: a block id, "" for "the next Ready one", "done" for the plan-complete screen
  let shown = "", ticket = 0, noteTimer = 0;

  const steps = () => runOrder(ctx.S());
  const byId = (id) => ctx.S().blocks.find((b) => b.id === id);
  const frameOf = (b) => ctx.S().frames.find((f) => f.id === b.frame);
  /** The step to show: the chosen one if it still exists, else the first Ready step, else the first unfinished one, else the complete screen. */
  function pick() {
    const all = steps();
    if (!all.length) return null;
    if (cur === "done") return all.every((b) => finished(ctx.status(b))) ? "done" : (all.find((b) => ctx.status(b) === "ready") || all[0]);
    const chosen = cur && all.find((b) => b.id === cur);
    if (chosen) return chosen;
    return all.find((b) => ctx.status(b) === "ready") || all.find((b) => !finished(ctx.status(b))) || "done";
  }
  /** After a step is finished: the next Ready step after it in run order (wrapping), or the complete screen when nothing is left. */
  function advance(from) {
    const all = steps(), i = all.findIndex((b) => b.id === from);
    const next = [...all.slice(i + 1), ...all.slice(0, Math.max(i, 0))].find((b) => ctx.status(b) === "ready");
    cur = next ? next.id : all.every((b) => finished(ctx.status(b))) ? "done" : from;
  }
  const waitsFor = (b) => {
    const g = ctx.S(), by = Object.fromEntries(g.blocks.map((x) => [x.id, x]));
    return [...new Set(orderEdges(g).filter(([a, t]) => t === b.id && ["prompt", "start"].includes(by[a]?.type) && !finished(by[a].status)).map(([a]) => by[a]))];
  };
  const attached = (b) => attachedBlocks(ctx.S(), b.id).filter((s) => !(b.context_off || []).includes(s.id));

  // ---- the rail
  function rail() {
    const all = steps(), done = all.filter((b) => b.status === "done").length, skipped = all.filter((b) => b.status === "skipped").length, sel = pick();
    const groups = [];
    all.forEach((b) => {
      const f = frameOf(b), key = f ? f.id : "";
      let g = groups.find((x) => x.key === key);
      if (!g) groups.push(g = { key, title: f ? f.title : "", items: [] });
      g.items.push(b);
    });
    const named = groups.some((g) => g.key);
    const pct = all.length ? Math.round((done / all.length) * 100) : 0;
    el.querySelector(".lkf-rail").innerHTML = `<div class="lkf-prog"><div class="lkf-progtop"><strong>${done} / ${all.length}</strong><span class="muted">done${skipped ? ` · ${skipped} skipped` : ""}</span></div><span class="lk-bar lkf-bar"><span style="width:${pct}%"></span></span></div>`
      + groups.map((g) => `<div class="lkf-group">${named ? `<div class="lkf-gtitle">${esc(g.title || "No phase")}</div>` : ""}${g.items.map((b) => {
        const st = ctx.status(b);
        return `<button type="button" class="lkf-step${sel && sel !== "done" && sel.id === b.id ? " on" : ""}" data-step="${esc(b.id)}">${dot(st)}<span class="lkf-name">${esc(b.title)}</span></button>`;
      }).join("")}</div>`).join("")
      + `<p class="lkf-note muted">Only Prompt blocks are followed. Specs, References and notes are not counted.</p>`;
  }

  // ---- the main column
  function emptyMain() {
    return `<div class="lkf-scroll"><div class="lkf-empty"><h2>No prompts yet</h2><p class="muted">A plan is followed one Prompt block at a time. Add Prompt blocks on the canvas and link them in the order to run them.</p><button type="button" class="btn btn-sm btn-glow btn-glow-md" data-act="canvas">Back to canvas</button></div></div>`;
  }
  function doneMain() {
    const all = steps(), done = all.filter((b) => b.status === "done").length, skipped = all.length - done;
    return `<div class="lkf-scroll"><div class="lkf-empty"><span class="lkf-big">${ic(CHECK, 28)}</span><h2>Plan complete</h2><p class="muted">${done} of ${all.length} prompt${all.length === 1 ? "" : "s"} done${skipped ? `, ${skipped} skipped` : ""}. Pick any prompt on the left to look at it again or to reopen it.</p><button type="button" class="btn btn-sm btn-glow btn-glow-md" data-act="canvas">Back to canvas</button></div></div>`;
  }
  function stepMain(b) {
    const all = steps(), i = all.findIndex((x) => x.id === b.id), st = ctx.status(b), f = frameOf(b), wait = st === "todo" ? waitsFor(b) : [], ctxs = attached(b);
    const nextUp = all.slice(i + 1).filter((x) => !finished(ctx.status(x))).slice(0, 3);
    const primary = finished(st)
      ? `<button type="button" class="btn btn-sm btn-glow btn-glow-md" data-act="reopen" data-hotkey="lsdone">Reopen${kbd("lsdone")}</button>`
      : `<button type="button" class="btn btn-sm btn-glow btn-glow-md" data-act="done" data-hotkey="lsdone">${ic(CHECK, 14)}<span>Mark done</span>${kbd("lsdone")}</button>`;
    return `<div class="lkf-scroll"><header class="lkf-head">
        <div class="lkf-crumb">Prompt ${i + 1} of ${all.length}${f ? ` · ${esc(f.title)}` : ""}</div>
        <h2 class="lkf-title">${esc(b.title)}</h2>
        <div class="lkf-chips"><span class="lk-chip">${esc(b.agent || "claude")}</span><span class="lkf-state lkf-s-${st}">${dot(st)}${WORD[st]}</span>${wait.length ? `<span class="muted small">waits for ${wait.map((x) => esc(x.title)).join(", ")}</span>` : ""}${wait.some((x) => x.type === "start") ? `<button type="button" class="btn btn-sm btn-glow lkf-mini" data-act="brief" title="The Brief is not a prompt: mark it done to start the plan">Mark Brief done</button>` : ""}</div>
      </header>
      <section class="lkf-sec"><div class="lkf-label">${ctxs.length ? "What Copy puts on the clipboard" : "Prompt"}</div><pre class="lkf-text" id="lkf-text" tabindex="0">${esc(shown && shown.id === b.id ? shown.text : "Loading…")}</pre>
        ${ctxs.length ? `<div class="lkf-with"><span class="muted small">Goes with it:</span>${ctxs.map((s) => `<span class="lk-chip">${esc(s.title)}</span>`).join("")}</div>` : ""}</section>
      <section class="lkf-sec"><label class="lkf-label" for="lkf-note">Prompt note</label><textarea class="pl-input lkf-notebox" id="lkf-note" rows="3" spellcheck="false" placeholder="What happened, what to change next time"></textarea></section>
      ${nextUp.length ? `<section class="lkf-sec"><div class="lkf-label">Next up</div><div class="lkf-next">${nextUp.map((x) => `<button type="button" class="lkf-nchip" data-step="${esc(x.id)}">${dot(ctx.status(x))}<span>${esc(x.title)}</span></button>`).join("")}</div></section>` : ""}</div>
      <footer class="lkf-foot">
        <div class="lkf-footl"><button type="button" class="btn btn-sm btn-glow btn-glow-md" data-act="show" title="Select this block on the canvas">Show on canvas</button>${finished(st) ? "" : `<button type="button" class="btn btn-sm btn-glow btn-glow-md" data-act="skip" title="Skip this prompt and move on">Skip</button>`}</div>
        <div class="lkf-footr"><button type="button" class="btn btn-sm btn-glow btn-glow-md" data-act="copy" data-hotkey="lscopy">${COPY_ICONS}<span>Copy prompt</span>${kbd("lscopy")}</button>${primary}</div>
      </footer>`;
  }
  let shownFor = "";   // the step whose main column is on screen (a redraw for the same step keeps the note box, and so its focus)
  function main(force = false) {
    const sel = pick(), box = el.querySelector(".lkf-main");
    if (sel === null) { box.innerHTML = emptyMain(); shownFor = ""; return; }
    if (sel === "done") { box.innerHTML = doneMain(); shownFor = ""; return; }
    const noteBox = box.querySelector("#lkf-note");
    if (!force && shownFor === sel.id && noteBox && document.activeElement === noteBox) return;   // typing a note: do not rebuild under the cursor
    const sc = shownFor === sel.id ? box.querySelector(".lkf-scroll")?.scrollTop || 0 : 0;
    box.innerHTML = stepMain(sel); shownFor = sel.id; box.querySelector(".lkf-scroll").scrollTop = sc;
    box.querySelector("#lkf-note").value = sel.note || "";
    load(sel.id);
  }
  /** The prompt as Copy will paste it (switched-on context attached), as written. */
  async function load(id) {
    const my = ++ticket;
    try {
      await ctx.flush();
      const r = await api(`linkshell/${ctx.pid()}/blocks/${encodeURIComponent(id)}/copy`);
      if (my !== ticket) return;
      shown = { id, text: r.text || "(This prompt has no text yet.)" };
    } catch { if (my !== ticket) return; shown = { id, text: "Could not load the prompt." }; }
    const pre = el.querySelector("#lkf-text");
    if (pre && shownFor === id) pre.textContent = shown.text;
  }

  // ---- actions
  async function act(name, btn) {
    const sel = pick(), b = sel && sel !== "done" ? sel : null;
    if (name === "canvas") return ctx.toCanvas();
    if (name === "brief") { ctx.mutate(() => { ctx.S().blocks.filter((x) => x.type === "start").forEach((x) => { x.status = "done"; }); }); return void render(); }
    if (!b) return;
    if (name === "copy") { await ctx.flush(); return void await copyBlock(btn, ctx.pid(), b.id); }
    if (name === "show") return ctx.toCanvas(b.id);
    if (name === "reopen") { ctx.mutate(() => { byId(b.id).status = "todo"; }); cur = b.id; return void render(); }
    if (name === "done" || name === "skip") {
      const was = b.id, word = name === "done" ? "done" : "skipped";
      ctx.mutate(() => { byId(was).status = word; });
      advance(was); render();
      toast({ message: `${b.title} marked ${word}.`, action: "Undo", onAction: () => { ctx.undo(); cur = was; render(); }, ms: 4000 });
    }
  }
  const saveNote = (id, v) => { const b = byId(id); if (b && (b.note || "") !== v) ctx.touch(() => { b.note = v; }); };

  el.addEventListener("click", (e) => {
    const s = e.target.closest("[data-step]");
    if (s) { cur = s.dataset.step; return render(); }
    const a = e.target.closest("[data-act]");
    if (a) act(a.dataset.act, a);
  });
  el.addEventListener("input", (e) => {
    if (e.target.id !== "lkf-note") return;
    const id = shownFor, v = e.target.value;
    clearTimeout(noteTimer); noteTimer = setTimeout(() => saveNote(id, v), 400);   // the note rides on the canvas autosave
  });
  el.addEventListener("focusout", (e) => { if (e.target.id === "lkf-note") { clearTimeout(noteTimer); saveNote(shownFor, e.target.value); } });

  function render() { rail(); main(true); }
  el.innerHTML = `<aside class="lkf-rail" aria-label="Prompts"></aside><div class="lkf-main"></div>`;
  return {
    /** The view became visible. */
    show: () => { shown = ""; render(); },
    /** The graph changed behind the view (a status click on the canvas, an Undo): redraw, but never under a note being typed. */
    refresh: () => { rail(); main(false); },
    reset: () => { cur = ""; shown = ""; shownFor = ""; clearTimeout(noteTimer); },
    flushNote: () => { clearTimeout(noteTimer); const n = el.querySelector("#lkf-note"); if (n && shownFor) saveNote(shownFor, n.value); },
  };
}

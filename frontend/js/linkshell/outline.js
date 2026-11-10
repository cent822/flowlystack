// Linkshell Outline view: the same graph as an indented list you can type into. Phases (frames) are headings,
// the Brief and Prompt steps sit under them in run order, and the Specs and References a step uses sit one level deeper, under that step.
// Keys in a title: Enter finishes it, Cmd/Ctrl+Enter adds a prompt below, Tab moves a step into the phase above, Shift+Tab takes it out, ↑ / ↓ move between rows, Backspace on an empty title deletes it.
// It owns no data: every change goes through the canvas (ctx.add, ctx.move, ctx.remove, ctx.mutate, ctx.touch), so it autosaves with the graph and Undo works. Plain DOM.
import { esc } from "../editor.js";
import { toast } from "../toast.js";
import { confirmDialog } from "../dialog.js";
import { runIndex } from "./layout.js";

const ic = (d, s = 14) => `<svg viewBox="0 0 24 24" width="${s}" height="${s}" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${d}</svg>`;
const PATH = {
  prompt: `<path d="M5 7l5 5-5 5"/><path d="M12 18h7"/>`, spec: `<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5M9 13h6M9 17h6"/>`,
  reference: `<rect x="3" y="4" width="18" height="16" rx="2.5"/><circle cx="9" cy="10" r="1.6"/><path d="M21 16l-5-5-8 8"/>`, start: `<path d="M5 21V4M5 4h11l-2 4 2 4H5"/>`,
  note: `<path d="M5 4h14v10l-5 6H5z"/><path d="M14 20v-6h5"/>`, frame: `<path d="M7 3v18M17 3v18M3 7h18M3 17h18"/>`, plus: `<path d="M12 5v14M5 12h14"/>`,
  trash: `<path d="M4 7h16M10 11v6M14 11v6M6 7l1 12a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2l1-12M9 7V4h6v3"/>`, open: `<path d="M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5"/>`,
  check: `<path d="M5 12.5l4.5 4.5L19 7.5"/>`, play: `<path d="M8 5l11 7-11 7z"/>`, minus: `<path d="M5 12h14"/>`,
};
const WORD = { prompt: "prompt", spec: "spec", reference: "reference", note: "note", start: "brief" };
const finished = (st) => st === "done" || st === "skipped";
const isStep = (b) => b.type === "prompt" || b.type === "start";

/** ctx: { el, S(), status(b), mutate(fn), touch(fn), undo(), toCanvas(blockId?), add({type, frame, after, parent, title}) -> id, addFrame() -> id, move(id, frameId),
 *         remove(id), removeFrame(id) } */
export function createOutline(ctx) {
  const el = ctx.el;
  const picked = new Set();   // rows chosen for a bulk delete (Cmd/Ctrl+click, Shift+click for a range); the Brief is never chosen
  let anchor = "", cursor = "";   // the end of the selection that ↑ / ↓ moves
  let last = "", timer = 0, pend = null;   // the row that had focus last (where the toolbar adds), the title being typed, its pending save
  const byId = (id) => ctx.S().blocks.find((b) => b.id === id) || ctx.S().frames.find((f) => f.id === id);

  /** The rows in display order: the Brief, then each phase (earliest step first) with its steps, then the blocks that are in no phase. */
  function model() {
    const g = ctx.S(), idx = runIndex(g), pos = (a, b) => idx[a.id] - idx[b.id] || a.y - b.y || a.x - b.x, at = (a, b) => a.y - b.y || a.x - b.x;
    const by = Object.fromEntries(g.blocks.map((b) => [b.id, b])), known = new Set(g.frames.map((f) => f.id));
    const feeds = {};   // a Spec or Reference -> the Prompts it is linked into (it is attached when they are copied)
    g.links.filter((l) => l.kind === "order").forEach((l) => { const a = by[l.from], t = by[l.to]; if (a && t && (a.type === "spec" || a.type === "reference") && t.type === "prompt") (feeds[a.id] ||= []).push(t); });
    Object.values(feeds).forEach((l) => l.sort(pos));
    const kids = {};
    Object.entries(feeds).forEach(([id, ps]) => { (kids[ps[0].id] ||= []).push(by[id]); });
    Object.values(kids).forEach((l) => l.sort(at));
    const frameOf = (b) => (known.has(b.frame) ? b.frame : "");
    const brief = g.blocks.find((b) => b.type === "start" && !frameOf(b));
    const group = (fid) => {
      const steps = g.blocks.filter((b) => frameOf(b) === fid && isStep(b) && b !== brief).sort(pos);
      const loose = g.blocks.filter((b) => frameOf(b) === fid && !isStep(b) && !feeds[b.id]).sort(at);
      return { steps, loose };
    };
    const first = (f) => Math.min(...g.blocks.filter((b) => b.frame === f.id && isStep(b)).map((b) => idx[b.id]), 1e7);
    const frames = [...g.frames].sort((a, b) => first(a) - first(b) || a.y - b.y || a.x - b.x).map((f) => ({ f, ...group(f.id) }));
    return { brief, frames, none: group(""), kids, feeds };
  }

  // ---- drawing
  const row = (b, depth, m) => {
    const st = ctx.status(b), step = isStep(b), also = (m.feeds[b.id] || []).slice(1);
    const dot = step ? `<button type="button" class="lkf-dot lkf-${st} lko-st" data-act="status" aria-label="${st === "done" ? "Done. Mark To do" : "Mark done"}" title="${st === "done" ? "Done. Click to mark To do." : st === "ready" ? "Ready. Click to mark Done." : st === "skipped" ? "Skipped. Click to mark Done." : "To do. Click to mark Done."}">${st === "done" ? ic(PATH.check, 10) : st === "ready" ? ic(PATH.play, 8) : st === "skipped" ? ic(PATH.minus, 10) : ""}</button>` : `<span class="lko-st lko-nodot"></span>`;
    return `<div class="lko-row lko-b lko-t-${b.type}${picked.has(b.id) ? " lko-pick" : ""}" data-id="${esc(b.id)}" style="--d:${depth}">${dot}<span class="lk-tile lk-tile-${b.type} lko-tile">${ic(PATH[b.type] || PATH.note, 14)}</span>
      <input class="lko-in" type="text" value="${esc(b.title)}" aria-label="${esc(WORD[b.type])} title" spellcheck="false" autocomplete="off">
      ${also.length ? `<span class="lko-also muted" title="Also used by ${esc(also.map((x) => x.title).join(", "))}">+${also.length} more</span>` : ""}
      <span class="lko-meta">${b.type === "prompt" ? `<span class="lk-chip">${esc(b.agent || "claude")}</span>` : `<span class="lk-chip">${WORD[b.type]}</span>`}</span>
      <span class="lko-act"><button type="button" class="icon-btn lko-btn" data-act="open" title="Open on the canvas to edit the text" aria-label="Open on the canvas">${ic(PATH.open, 15)}</button>${b.type === "start" ? "" : `<button type="button" class="icon-btn lko-btn" data-act="delete" title="Delete" aria-label="Delete">${ic(PATH.trash, 15)}</button>`}</span></div>`;
  };
  const withKids = (b, depth, m) => row(b, depth, m) + (m.kids[b.id] || []).map((k) => row(k, depth + 1, m)).join("");
  function html() {
    const m = model(), g = ctx.S();
    const hasNone = m.none.steps.length || m.none.loose.length;
    const out = [];
    if (m.brief) out.push(row(m.brief, 0, m));
    m.frames.forEach(({ f, steps, loose }) => {
      const all = g.blocks.filter((b) => b.frame === f.id && isStep(b)), done = all.filter((b) => b.status === "done").length;
      out.push(`<div class="lko-row lko-h" data-id="${esc(f.id)}" data-frame><span class="lk-tile lko-tile lko-tile-frame">${ic(PATH.frame, 14)}</span>
        <input class="lko-in lko-hin" type="text" value="${esc(f.title)}" aria-label="Phase title" spellcheck="false" autocomplete="off">
        <span class="lko-meta muted">${all.length ? `${done}/${all.length}` : "empty"}</span>
        <span class="lko-act"><button type="button" class="icon-btn lko-btn" data-act="addin" title="Add a prompt to this phase" aria-label="Add a prompt to this phase">${ic(PATH.plus, 15)}</button><button type="button" class="icon-btn lko-btn" data-act="delframe" title="Remove the phase (its blocks stay)" aria-label="Remove the phase">${ic(PATH.trash, 15)}</button></span></div>`);
      steps.forEach((b) => out.push(withKids(b, 1, m)));
      loose.forEach((b) => out.push(row(b, 1, m)));
    });
    if (hasNone) {
      if (m.frames.length) out.push(`<div class="lko-row lko-h lko-hnone"><span class="lko-gt">No phase</span></div>`);
      const d = m.frames.length ? 1 : 0;
      m.none.steps.forEach((b) => out.push(withKids(b, d, m)));
      m.none.loose.forEach((b) => out.push(row(b, d, m)));
    }
    if (g.blocks.length <= 1 && !g.frames.length) out.push(`<div class="lko-empty"><p class="muted">No prompts yet. Add the first one, then press Ctrl+Enter in a title to add the next.</p><button type="button" class="btn btn-sm btn-glow btn-glow-md" data-add="prompt">${ic(PATH.plus)}<span>Add a prompt</span></button></div>`);
    return out.join("");
  }
  function bar() {
    const g = ctx.S(), n = picked.size, empty = g.blocks.length <= 1 && !g.frames.length;
    return `<div class="lko-bar">${n ? `<span class="lko-sel"><strong>${n} selected</strong><button type="button" class="btn btn-sm btn-glow btn-danger lko-small" data-act="delpicked">${ic(PATH.trash, 12)}<span>Delete</span></button><button type="button" class="btn btn-sm btn-glow lko-small" data-act="unpick">Clear selection</button></span>`
      : `<span class="lko-hint muted">Enter finishes a title · Ctrl+Enter adds a prompt below · Tab moves it into the phase above · Shift+Tab takes it out · ↑ ↓ move between rows · Cmd/Ctrl+click or Shift+click selects rows</span>`}
      <span class="lko-adds"><button type="button" class="btn btn-sm btn-glow" data-add="prompt">${ic(PATH.plus)}<span>Prompt</span></button><button type="button" class="btn btn-sm btn-glow" data-add="spec">${ic(PATH.plus)}<span>Spec</span></button><button type="button" class="btn btn-sm btn-glow" data-add="note">${ic(PATH.plus)}<span>Note</span></button><button type="button" class="btn btn-sm btn-glow" data-add="frame">${ic(PATH.plus)}<span>Phase</span></button>
      <button type="button" class="btn btn-sm btn-glow btn-danger lko-clear" data-act="clear" ${empty ? "disabled" : ""} title="Remove every block and phase except the Brief">${ic(PATH.trash, 12)}<span>Clear plan</span></button></span></div>`;
  }
  function render(focus) {
    const sc = el.querySelector(".lko-list")?.scrollTop || 0, all = new Set(ctx.S().blocks.map((b) => b.id));
    [...picked].forEach((id) => { if (!all.has(id)) picked.delete(id); });
    el.innerHTML = `${bar()}<div class="lko-list" role="list" tabindex="-1">${html()}</div>`;
    el.querySelector(".lko-list").scrollTop = sc;
    if (focus) focusRow(focus.id, focus.select);
  }
  function focusRow(id, select = false) {
    const i = el.querySelector(`[data-id="${CSS.escape(id)}"] .lko-in`);
    if (!i) return;
    i.focus({ preventScroll: false });
    if (select) i.select(); else i.setSelectionRange(i.value.length, i.value.length);
    i.scrollIntoView({ block: "nearest" });
    last = id;
  }

  // ---- title edits (ride the canvas autosave, like a step note)
  function commit() {
    clearTimeout(timer);
    if (!pend) return;
    const { id, v } = pend; pend = null;
    const o = byId(id);
    if (o && v.trim() && o.title !== v.trim()) ctx.touch(() => { o.title = v.trim(); });
  }
  el.addEventListener("input", (e) => {
    if (!e.target.classList.contains("lko-in")) return;
    pend = { id: e.target.closest("[data-id]").dataset.id, v: e.target.value };
    clearTimeout(timer); timer = setTimeout(commit, 350);
  });
  el.addEventListener("focusout", (e) => {
    if (!e.target.classList.contains("lko-in")) return;
    commit();
    const o = byId(e.target.closest("[data-id]")?.dataset.id);
    if (o && !e.target.value.trim()) e.target.value = o.title;   // an empty title is never stored: show the old one again
  });
  el.addEventListener("focusin", (e) => { const r = e.target.closest?.("[data-id]"); if (r) last = r.dataset.id; });

  // ---- actions
  /** Where a new step goes relative to a row: after the step it belongs to (or the last step of its phase). */
  function anchorOf(id) {
    const g = ctx.S(), o = byId(id), m = model();
    if (!o) { const s = m.none.steps; return { frame: "", after: s.length ? s[s.length - 1].id : m.brief?.id || "", parent: "" }; }   // nothing focused: the end of the unphased steps
    if (g.frames.some((f) => f.id === id)) { const s = (m.frames.find((x) => x.f.id === id) || { steps: [] }).steps; return { frame: id, after: s.length ? s[s.length - 1].id : "", parent: "" }; }
    const fr = g.frames.some((f) => f.id === o.frame) ? o.frame : "";
    if (isStep(o)) return { frame: fr, after: o.id, parent: o.type === "prompt" ? o.id : "" };
    const parent = m.feeds[o.id]?.[0];
    if (parent) return { frame: parent.frame && g.frames.some((f) => f.id === parent.frame) ? parent.frame : "", after: parent.id, parent: parent.id };
    const s = (fr ? m.frames.find((x) => x.f.id === fr)?.steps : m.none.steps) || [];
    return { frame: fr, after: s.length ? s[s.length - 1].id : (fr ? "" : m.brief?.id || ""), parent: "" };
  }
  function add(type) {
    commit();
    if (type === "frame") { const id = ctx.addFrame(); return render({ id, select: true }); }
    const a = anchorOf(last);
    const id = ctx.add(type === "prompt" ? { type, frame: a.frame, after: a.after } : { type, frame: a.frame, parent: type === "spec" ? a.parent : "", title: type === "note" ? "New note" : undefined });
    render({ id, select: true });
  }
  function indent(id, out) {
    const b = byId(id), g = ctx.S(), m = model();
    if (!b || !b.type || b.type === "start") return;
    if (m.feeds[b.id]?.length) return toast({ message: "Specs and References sit under the prompt they feed.", ms: 3000 });
    const inFrame = g.frames.some((f) => f.id === b.frame);
    if (out) { if (!inFrame) return; ctx.move(b.id, ""); }
    else {
      if (inFrame) return toast({ message: "Already in a phase. Shift+Tab takes it out.", ms: 3000 });
      const target = m.frames[m.frames.length - 1]?.f;
      if (!target) return toast({ message: "Add a phase first (the Phase button).", ms: 3000 });
      ctx.move(b.id, target.id);
    }
    render({ id: b.id });
  }
  function remove(id) {
    const rows = [...el.querySelectorAll(".lko-in")], i = rows.findIndex((x) => x.closest("[data-id]").dataset.id === id), prev = rows[i > 0 ? i - 1 : i + 1]?.closest("[data-id]")?.dataset.id;
    commit();
    if (byId(id)?.type === undefined) ctx.removeFrame(id); else ctx.remove(id);
    render(prev ? { id: prev } : null);
  }

  el.addEventListener("keydown", (e) => {
    const inp = e.target;
    if (!inp.classList?.contains("lko-in") || e.isComposing) return;
    const rowEl = inp.closest("[data-id]"), id = rowEl.dataset.id;
    if (e.key === "Enter" && !e.shiftKey && !e.altKey) {   // Enter finishes the title; Cmd/Ctrl+Enter adds the next step
      e.preventDefault(); commit();
      if (e.metaKey || e.ctrlKey) { last = id; add("prompt"); } else inp.blur();
      return;
    }
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      const all = [...el.querySelectorAll(".lko-in")], n = all.indexOf(inp) + (e.key === "ArrowDown" ? 1 : -1);
      if (all[n]) { e.preventDefault(); all[n].focus(); all[n].setSelectionRange(all[n].value.length, all[n].value.length); all[n].scrollIntoView({ block: "nearest" }); }
    } else if (e.key === "Tab") {
      if (rowEl.hasAttribute("data-frame")) return;   // a phase heading is not indented: let Tab leave the field as usual
      e.preventDefault(); commit(); indent(id, e.shiftKey);
    } else if (e.key === "Backspace" && !inp.value && !(byId(id)?.type === "start")) {
      e.preventDefault(); remove(id);
    } else if (e.key === "Escape") inp.blur();
  });
  function pick(id, how) {
    const rows = [...el.querySelectorAll(".lko-b")].filter((r) => !r.classList.contains("lko-t-start")).map((r) => r.dataset.id);
    if (how === "range" && anchor && rows.includes(anchor) && rows.includes(id)) {
      const [i, j] = [rows.indexOf(anchor), rows.indexOf(id)].sort((x, y) => x - y);
      rows.slice(i, j + 1).forEach((r) => picked.add(r));
    } else { picked.has(id) ? picked.delete(id) : picked.add(id); anchor = id; }
    cursor = id;
    commit(); render(); el.querySelector(".lko-list").focus({ preventScroll: true });
  }
  const unpick = () => { if (picked.size) { picked.clear(); anchor = ""; render(); } };
  function deletePicked() {
    const ids = [...picked]; picked.clear(); anchor = "";
    if (ids.length) ctx.removeMany(ids);
    render();
  }
  async function clearPlan() {
    const g = ctx.S(), nb = g.blocks.filter((b) => b.type !== "start").length, nf = g.frames.length;
    if (!nb && !nf) return;
    commit();
    const ok = await confirmDialog({ title: "Clear the whole plan?", message: `This removes ${nb} block${nb === 1 ? "" : "s"}${nf ? ` and ${nf} phase${nf === 1 ? "" : "s"}` : ""} and every link, here and on the canvas. The Brief stays. You can Undo it right after.`, confirmLabel: "Clear plan", danger: true });
    if (!ok) return;
    picked.clear(); anchor = ""; ctx.clear(); render();
  }
  // Cmd/Ctrl+click or Shift+click on a row selects it instead of focusing its title
  el.addEventListener("mousedown", (e) => {
    const r = e.target.closest(".lko-b");
    if (r && (e.metaKey || e.ctrlKey || e.shiftKey) && !e.target.closest("button") && !r.classList.contains("lko-t-start")) { e.preventDefault(); pick(r.dataset.id, e.shiftKey ? "range" : "one"); }
  });
  // ↑ / ↓ with rows selected move the selection (Shift extends it); render() keeps the scroll, so bring the new row into view
  function movePick(down, extend) {
    const rows = [...el.querySelectorAll(".lko-b")].filter((r) => !r.classList.contains("lko-t-start")).map((r) => r.dataset.id);
    const at = rows.indexOf(cursor), n = Math.max(0, Math.min(rows.length - 1, (at < 0 ? rows.indexOf([...picked].pop()) : at) + (down ? 1 : -1)));
    if (!rows.length) return;
    if (extend && anchor && rows.includes(anchor)) { const [i, j] = [rows.indexOf(anchor), n].sort((x, y) => x - y); picked.clear(); rows.slice(i, j + 1).forEach((r) => picked.add(r)); }
    else { picked.clear(); picked.add(rows[n]); anchor = rows[n]; }
    cursor = rows[n]; render();
    const list = el.querySelector(".lko-list"); list.focus({ preventScroll: true });
    el.querySelector(`[data-id="${CSS.escape(cursor)}"]`)?.scrollIntoView({ block: "nearest" });
  }
  el.addEventListener("keydown", (e) => {
    if (e.target.classList?.contains("lko-in") || !picked.size) return;
    if (e.key === "Delete" || e.key === "Backspace") { e.preventDefault(); deletePicked(); }
    else if (e.key === "Escape") { e.preventDefault(); unpick(); }
    else if ((e.key === "ArrowDown" || e.key === "ArrowUp") && !e.metaKey && !e.ctrlKey && !e.altKey) { e.preventDefault(); movePick(e.key === "ArrowDown", e.shiftKey); }
  });
  // After Enter finishes a title (or a click on empty space) no field has focus: ↑ / ↓ pick up from the row that had it last
  document.addEventListener("keydown", (e) => {
    if ((e.key !== "ArrowDown" && e.key !== "ArrowUp") || e.metaKey || e.ctrlKey || e.altKey || e.shiftKey || e.defaultPrevented) return;
    if (el.hidden || !el.isConnected || picked.size || document.querySelector("dialog[open]")) return;
    const t = e.target;
    if (t !== document.body && t !== el.querySelector(".lko-list")) return;
    const all = [...el.querySelectorAll(".lko-in")];
    if (!all.length) return;
    const at = all.findIndex((x) => x.closest("[data-id]").dataset.id === last), down = e.key === "ArrowDown";
    const n = at < 0 ? (down ? 0 : all.length - 1) : Math.max(0, Math.min(all.length - 1, at + (down ? 1 : -1)));
    e.preventDefault(); all[n].focus(); all[n].setSelectionRange(all[n].value.length, all[n].value.length); all[n].scrollIntoView({ block: "nearest" });
  });
  el.addEventListener("click", (e) => {
    const a = e.target.closest("[data-add]");
    if (a) return add(a.dataset.add);
    const b = e.target.closest("[data-act]"), r = e.target.closest("[data-id]");
    if (b?.dataset.act === "clear") return void clearPlan();
    if (b?.dataset.act === "delpicked") return deletePicked();
    if (b?.dataset.act === "unpick") return unpick();
    if (!b || !r) return;
    const id = r.dataset.id, o = byId(id);
    if (b.dataset.act === "open") return ctx.toCanvas(id);
    if (b.dataset.act === "status" && o) { ctx.mutate(() => { o.status = ctx.status(o) === "done" ? "todo" : "done"; }); return render({ id }); }
    if (b.dataset.act === "addin") { last = id; commit(); const n = anchorOf(id); const nid = ctx.add({ type: "prompt", frame: n.frame, after: n.after }); return render({ id: nid, select: true }); }
    if (b.dataset.act === "delframe") return remove(id);
    if (b.dataset.act === "delete") return remove(id);
  });

  el.innerHTML = "";
  return {
    /** The view became visible. */
    show: () => render(),
    /** The graph changed behind the view (an Undo, a status click elsewhere): redraw, but never under a title being typed. */
    refresh: () => { if (el.hidden || el.contains(document.activeElement) && document.activeElement.classList.contains("lko-in")) return; render(); },
    reset: () => { last = ""; pend = null; clearTimeout(timer); el.innerHTML = ""; },
    flush: commit,
  };
}

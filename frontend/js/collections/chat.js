// The Chat tab: ask a question about a collection (or several), watch the answer stream in with numbered citation chips, and see the passages
// behind it in the Sources panel. FlowlyStack contacts a model only when you press Send, and the status line says exactly what went with it.
// Conversations are saved by the server (Settings > Knowledge > history), listed in the left column and exportable as Markdown or JSON.
// Plain DOM, no framework.
import { toast } from "../toast.js";
import { confirmDialog, formDialog } from "../dialog.js";
import { relTime } from "../api.js";
import { copy, COPY_ICONS, diffHtml, send as post } from "../editor.js";
import { extractPrompt, shown, liveHtml } from "../assistant.js";
import { sendDraft } from "../handoff.js";
import { hotkey, label as keyLabel, matches } from "../hotkeys.js";
import { api, esc, ic, I, json, plural } from "./common.js";

const $ = (s, r = document) => r.querySelector(s);
const store = {
  get: (k) => { try { return localStorage.getItem(k); } catch { return null; } },
  set: (k, v) => { try { localStorage.setItem(k, v); } catch { /* the choice just is not remembered */ } },
};
const RETRIEVAL = [["auto", "Auto"], ["on", "On"], ["off", "Off"]];
const KEEP = new Map();   // collection id -> {turns, scope, chat}: the conversation survives a switch to Documents and back
let M = null;             // the mounted tab: {box, c, st, chats, history, collections, providers, sel, busy, ctl}

export function unmountChat() {
  M?.ctl?.abort();
  if (M?.cleanup) M.cleanup();
  M = null;
}

// ---------- following the answer ----------
// The page scrolls inside #panel. While an answer streams in, the view follows the newest text, like other chat apps. Scrolling up stops the
// following (the "Latest" button appears); scrolling back to the bottom, pressing the button or sending a message starts it again.
const panel = () => document.getElementById("panel");
const NEAR_BOTTOM = 80;
function toBottom() { const p = panel(); if (p) p.scrollTop = p.scrollHeight; }
let rafScroll = 0;
function followNow() {
  if (rafScroll) return;
  rafScroll = requestAnimationFrame(() => { rafScroll = 0; if (M?.follow) toBottom(); });
}
function drawJump() {
  const b = M && $("#co-jump", M.box);
  if (b) b.hidden = !(M.busy && !M.follow);
}

export async function mountChat(box, c) {
  unmountChat();
  const st = KEEP.get(c.id) || { turns: [], scope: [c.id], chat: null };
  KEEP.set(c.id, st);
  M = { box, c, st, chats: [], history: true, collections: [], providers: null, sel: st.turns.length - 1, busy: false, ctl: null, retrieval: store.get("co-chat-retrieval") || "auto", side: false, follow: true };
  box.innerHTML = `
    <div class="co-chat">
      <aside class="co-chats" aria-label="Conversations">
        <button type="button" class="btn btn-sm btn-glow btn-glow-md" id="co-newchat">${ic(I.plus)}<span>New chat</span><kbd class="kbd" data-hk="conewchat"></kbd></button>
        <div class="co-chatlist" id="co-chatlist"></div>
      </aside>
      <section class="co-main" aria-label="Conversation">
        <div class="co-thead" id="co-thead"></div>
        <div class="co-thread" id="co-thread" aria-live="polite"></div>
        <form class="co-composer" id="co-composer">
          <button type="button" class="btn btn-sm btn-glow btn-glow-md co-jump" id="co-jump" hidden>${ic(`<path d="M12 5v14M6 13l6 6 6-6"/>`, 14)}<span>Latest</span></button>
          <div class="co-box">
            <textarea class="co-ask" id="co-ask" rows="1" placeholder="Ask about ${esc(c.builtin ? "your prompts" : c.name)}…" aria-label="Your question" spellcheck="true"></textarea>
            <div class="co-cfoot">
              <details class="pr-more co-plus" id="co-plus">
                <summary class="btn btn-sm btn-glow btn-glow-md btn-glow-icon" aria-label="Search options" title="Search options">${ic(I.plus, 18)}</summary>
                <div class="pr-menu pr-morepanel co-plusmenu" role="menu">
                  <p class="co-mh">Search before answering</p>
                  <div class="seg" id="co-ret" role="group" aria-label="Search before answering">${RETRIEVAL.map(([k, l]) => `<button type="button" data-ret="${k}" aria-pressed="${k === M.retrieval}" class="${k === M.retrieval ? "on" : ""}" title="${k === "auto" ? "Search your files for every question except small talk" : k === "on" ? "Always search your files" : "Never search; just chat"}">${l}</button>`).join("")}</div>
                  <p class="co-mh">Search in</p>
                  <div id="co-scopemenu"></div>
                </div>
              </details>
              <span class="co-scopeinfo muted" id="co-scopeinfo"></span>
              <span class="co-cfill"></span>
              <select class="co-model" id="co-model" aria-label="Chat model"></select>
              <button type="submit" class="icon-btn stop-btn" id="co-send" aria-label="Stop" title="Stop" hidden><svg viewBox="0 0 24 24" width="14" height="14" aria-hidden="true"><rect x="6" y="6" width="12" height="12" rx="2" fill="currentColor"/></svg></button>
            </div>
          </div>
          <p class="muted small co-status" id="co-status" role="status"></p>
        </form>
      </section>
      <aside class="co-sources" id="co-sources" aria-label="Sources"></aside>
    </div>`;
  box.querySelectorAll("kbd[data-hk]").forEach((k) => { k.textContent = keyLabel(hotkey(k.dataset.hk)); });
  wire();
  const sc = panel(), onScroll = () => { if (!M) return; M.follow = sc.scrollHeight - sc.scrollTop - sc.clientHeight < NEAR_BOTTOM; drawJump(); };
  sc?.addEventListener("scroll", onScroll, { passive: true });
  M.cleanup = () => sc?.removeEventListener("scroll", onScroll);
  drawThread(); drawSources(); drawScope(); drawHead(); loadDiffs();
  loadModels(); loadCollections(); loadChats(); loadDocs(M);
}
async function loadDocs(mine) {
  if (mine.c.builtin) return;
  try { mine.docs = (await api(`collections/${mine.c.id}/documents`)).items; } catch { mine.docs = []; }
  if (M === mine) drawSources();
}

// ---------- saved conversations ----------
async function loadChats() {
  const mine = M;
  try { const r = await api(`collections/${encodeURIComponent(M.c.id)}/chats`); if (M !== mine) return; M.chats = r.items; M.history = r.history; }
  catch { if (M !== mine) return; M.chats = []; }
  drawChats(); drawHead();
}
const DAY = 86400;
function groupOf(x) {   // Open WebUI style headings
  if (x.pinned) return "Pinned";
  const d = new Date(), midnight = new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime() / 1000, ago = midnight - x.updated_at;
  return ago < 0 ? "Today" : ago < DAY ? "Yesterday" : ago < 7 * DAY ? "Previous 7 days" : ago < 30 * DAY ? "Previous 30 days" : "Older";
}
const chatUrl = (c, f) => `/api/collections/${encodeURIComponent(M.c.id)}/chats/${encodeURIComponent(c.id)}/export?format=${f}`;
const MENU_ICON = {
  rename: `<path d="M4 20l4.5-1 10-10a2.1 2.1 0 0 0-3-3l-10 10z"/><path d="M14 7l3 3"/>`,
  pin: `<path d="M9 4h6l-1 5 3 3v2H7v-2l3-3zM12 14v6"/>`, md: `<path d="M12 4v11M7 10l5 5 5-5M5 20h14"/>`,
};
/** The ⋯ menu of one conversation (the list rows and the title above the thread share it). */
function chatMenu(c, align = "left") {
  return `<details class="pr-more co-chatmenu" data-fixed data-align="${align}">
    <summary class="btn btn-sm btn-glow btn-glow-md btn-glow-icon" aria-label="Conversation options" title="Options">${ic(I.dots, 16)}</summary>
    <div class="pr-menu pr-morepanel" role="menu" data-for="${esc(c.id)}">
      <button type="button" class="pr-menuitem" role="menuitem" data-chatact="rename">${ic(MENU_ICON.rename, 16)}<span>Rename</span></button>
      <button type="button" class="pr-menuitem" role="menuitem" data-chatact="pin">${ic(MENU_ICON.pin, 16)}<span>${c.pinned ? "Unpin" : "Pin"}</span></button>
      <a class="pr-menuitem" role="menuitem" href="${chatUrl(c, "md")}" download>${ic(MENU_ICON.md, 16)}<span>Export as Markdown</span></a>
      <a class="pr-menuitem" role="menuitem" href="${chatUrl(c, "json")}" download>${ic(MENU_ICON.md, 16)}<span>Export as JSON</span></a>
      <button type="button" class="pr-menuitem danger" role="menuitem" data-chatact="delete">${ic(I.trash, 16)}<span>Delete</span></button>
    </div></details>`;
}
function drawChats() {
  const el = $("#co-chatlist", M.box), cur = M.st.chat?.id;
  if (!M.chats.length) {
    el.innerHTML = `<p class="muted small co-chatnone">${M.history ? "Your conversations will be listed here." : "History is off, so conversations are kept only while this page is open."}</p>`;
    return;
  }
  const order = ["Pinned", "Today", "Yesterday", "Previous 7 days", "Previous 30 days", "Older"], by = {};
  for (const x of M.chats) (by[groupOf(x)] ||= []).push(x);
  el.innerHTML = order.filter((g) => by[g]).map((g) => `<h3 class="co-chatgroup">${g}</h3>` + by[g].map((x) => `<div class="co-chatrow${x.id === cur ? " on" : ""}" data-chat="${esc(x.id)}">
      <button type="button" class="co-chatbtn" data-open="${esc(x.id)}" title="${esc(x.title || "Conversation")}" ${x.id === cur ? 'aria-current="true"' : ""}><span class="co-chatname">${esc(x.title || "Conversation")}</span></button>
      ${chatMenu(x)}</div>`).join("")).join("")
    + (M.history ? "" : `<p class="muted small co-chatnone">History is off in Settings. New conversations are not saved.</p>`);
}
async function chatAct(id, act) {
  const x = M.chats.find((c) => c.id === id), base = `collections/${encodeURIComponent(M.c.id)}/chats/${encodeURIComponent(id)}`;
  if (!x) return;
  if (act === "delete") return deleteChat(id);
  if (act === "pin") {
    try { await api(base, json("PATCH", { pinned: !x.pinned })); } catch (e) { toast({ message: "Could not change that: " + e.message, ms: 3500 }); }
    return loadChats();
  }
  if (act === "rename") {
    const v = await formDialog({ title: "Rename conversation", confirmLabel: "Rename", html: `<label class="pl-label" for="co-chname">Title</label><input class="pl-input" id="co-chname" autocomplete="off" maxlength="120" value="${esc(x.title || "")}">`,
      validate: (d) => (d.querySelector("#co-chname").value.trim() ? "" : "Give it a title."), read: (d) => d.querySelector("#co-chname").value.trim() });
    if (!v || v === x.title) return;
    try { await api(base, json("PATCH", { title: v })); if (M.st.chat?.id === id) M.st.chat.title = v; } catch (e) { toast({ message: "Could not rename: " + e.message, ms: 3500 }); }
    loadChats();
  }
}
function drawHead() {
  const el = $("#co-thead", M.box), ch = M.st.chat;
  if (!ch || !M.st.turns.length) { el.innerHTML = ""; return; }
  const row = M.chats.find((c) => c.id === ch.id) || { id: ch.id, title: ch.title, pinned: false };
  el.innerHTML = `<h2 class="co-chattitle">${esc(ch.title || "Conversation")}</h2>${chatMenu(row, "right")}`;
}
const toTurn = (e) => ({ prompt: e.prompt, response: e.response, partial: !!e.partial, error: "", id: e.id, exid: e.id, proposal: e.proposal || null,
  sources: { searched: !!e.searched, mode: e.mode || "", note: e.note || "", passages: e.retrieved || [] },
  done: { ...(e.info || {}), searched: !!e.searched, included: e.included || [], dropped: e.dropped || 0, cut: e.cut || 0, trimmed: e.trimmed || 0, model: e.model || { name: "" }, params: { num_ctx: 0, ...(e.params || {}) } } });
async function openChat(id) {
  if (M.busy) return;
  const mine = M;
  try {
    const c = await api(`collections/${encodeURIComponent(M.c.id)}/chats/${encodeURIComponent(id)}`);
    if (M !== mine) return;
    M.st.turns = c.exchanges.map(toTurn); M.st.chat = { id: c.id, title: c.title };
    if (c.scope?.length) M.st.scope = c.scope;
    M.sel = M.st.turns.length - 1;
    drawThread(); drawSources(); drawScope(); drawChats(); drawHead(); loadDiffs();
    $("#co-status", M.box).textContent = "";
  } catch { toast({ message: "That conversation no longer exists.", ms: 3000 }); loadChats(); }
}
async function deleteChat(id) {
  const x = M.chats.find((c) => c.id === id);
  if (!await confirmDialog({ title: "Delete conversation", message: `Delete “${x?.title || "this conversation"}” for good? Its saved questions, answers and sources are removed and can't be restored.`, confirmLabel: "Delete", danger: true })) return;
  try { await api(`collections/${encodeURIComponent(M.c.id)}/chats/${encodeURIComponent(id)}`, { method: "DELETE" }); } catch { /* already gone */ }
  if (M.st.chat?.id === id) newChat();
  loadChats();
}

// ---------- the thread ----------
const cite = (text, turn) => {
  const known = new Set((turn.sources?.passages || []).filter((p) => p.cite).map((p) => p.cite));
  return esc(text).replace(/\[(\d{1,2})\]/g, (m, n) => (known.has(+n) ? `<button type="button" class="co-cite" data-cite="${n}" title="Show source ${n}">${n}</button>` : m));
};
function turnHtml(t, i) {
  const live = M.busy && i === M.st.turns.length - 1;
  return `<article class="co-turn" data-i="${i}">
    <div class="as-user co-q">${esc(t.prompt)}</div>
    <div class="co-a">
      <div class="co-atext${t.error ? " err" : ""}">${t.error ? esc(t.error) : t.response ? (live ? liveText(t.response) : cite(shown(t), t)) : live ? `<span class="muted">Thinking…</span>` : ""}</div>
      ${live || !t.response ? "" : proposalHtml(t)}
      ${live || !t.response ? "" : `<div class="co-aact"><button type="button" class="btn btn-sm btn-glow btn-glow-md btn-glow-icon" data-copy aria-label="Copy answer" title="Copy answer">${COPY_ICONS}</button>
        ${shown(t).trim() && !t.proposal?.text ? `<button type="button" class="btn btn-sm btn-glow btn-glow-md btn-glow-icon" data-use aria-label="Use as prompt" title="Use as prompt: open the answer (or the part you selected) as a new Studio draft. Nothing is saved until you press Save.">${USE_ICON}</button>` : ""}
        ${t.sources?.passages?.length ? `<button type="button" class="btn btn-sm btn-glow btn-glow-md" data-show>${plural(t.sources.passages.length, "source")}</button>` : ""}${t.partial ? `<span class="muted small">stopped</span>` : ""}</div>`}
    </div></article>`;
}
function drawThread(keepScroll) {
  const th = $("#co-thread", M.box);
  th.innerHTML = M.st.turns.length ? M.st.turns.map(turnHtml).join("") : `<div class="co-empty"><strong>${M.c.builtin ? "Ask about your prompts" : `Ask about ${esc(M.c.name)}`}</strong>
    <span class="muted">${M.c.builtin ? "Your Library and Studio prompts are searched." : M.c.documents ? "Your documents are searched for each question." : "This collection has no documents yet. Add some on the Documents tab."} Answers cite their sources as numbered chips.</span></div>`;
  if (!keepScroll || M.follow) toBottom();
}
function updateLast() {   // streaming: only the last answer changes
  const i = M.st.turns.length - 1, art = $(`.co-turn[data-i="${i}"]`, M.box);
  if (art) art.outerHTML = turnHtml(M.st.turns[i], i);
  else drawThread(true);
  followNow();
}
const liveText = (text) => (text.includes("<<<PROMPT") ? liveHtml(text) : esc(text));

// ---------- proposed edit and Use as prompt ----------
// A reply with a <<<PROMPT ... PROMPT>>> block becomes a card. When the answer cited one of your own prompts, the card compares the proposal with
// that prompt's current text and can open it with the proposal as an unsaved draft; otherwise it opens a new Studio draft. Nothing is saved here.
const USE_ICON = `<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 12h11M11 7l5 5-5 5M20 5v14"/></svg>`;
const PROP_LABEL = { applied: "Used", dismissed: "Dismissed" };
const targetOf = (t) => (t.sources?.passages || []).find((p) => p.cite && (p.source === "library" || p.source === "studio")) || null;
const titleOf = (t) => { const f = (t.prompt || "").split("\n")[0].trim(); return f.length > 60 ? f.slice(0, 57) + "…" : f; };
function proposalHtml(t) {
  const p = t.proposal;
  if (!p?.text) return "";
  const st = p.status || "open";
  if (st !== "open") return `<details class="as-prop done" data-status="${st}"><summary><span class="as-chip">${PROP_LABEL[st]}</span> Proposed edit</summary><pre class="as-propbody">${esc(p.text)}</pre></details>`;
  const tg = targetOf(t);
  return `<section class="as-prop" data-status="open" aria-label="Proposed edit">
    <header class="as-prophead"><strong>Proposed edit${tg ? ` · ${esc(tg.name)}` : ""}</strong>
      <button type="button" class="btn btn-sm btn-glow btn-glow-md btn-glow-icon" data-prop="copy" aria-label="Copy the proposed prompt" title="Copy the proposed prompt">${COPY_ICONS}</button></header>
    <div class="as-diff" data-diff>${tg ? `<p class="muted small as-diffwait">Comparing…</p>` : `<pre class="as-propbody">${esc(p.text)}</pre>`}</div>
    <div class="as-propactions">${tg ? `<button type="button" class="btn btn-sm btn-glow btn-glow-md btn-glow btn-glow-md" data-prop="open">Open “${esc(tg.name.length > 28 ? tg.name.slice(0, 27) + "…" : tg.name)}” with this text</button>` : ""}
      <button type="button" class="btn btn-sm btn-glow btn-glow-md btn-glow btn-glow-md" data-prop="new">Use as new prompt</button><button type="button" class="btn btn-sm btn-glow btn-glow-md" data-prop="dismiss">Dismiss</button></div>
  </section>`;
}
async function loadDiffs() {   // compare each open proposal with the text of the prompt it came from
  const mine = M;
  for (const [i, t] of M.st.turns.entries()) {
    if (!t.proposal?.text || (t.proposal.status || "open") !== "open") continue;
    const tg = targetOf(t), box = $(`.co-turn[data-i="${i}"] [data-diff]`, M.box);
    if (!tg || !box) continue;
    try {
      const cur = await api(`${tg.source === "studio" ? "studio" : "prompts"}/${encodeURIComponent(tg.ref)}`);
      const r = await post("POST", "assistant/diff", { a: cur.text, b: t.proposal.text });
      if (M !== mine) return;
      box.innerHTML = r.rows.some((x) => x.t !== "eq" && x.t !== "gap") ? `<div class="df uni">${diffHtml(r.rows, false)}</div>` : `<p class="muted small as-diffwait">The same as the current text of this prompt.</p>`;
    } catch { box.innerHTML = `<pre class="as-propbody">${esc(t.proposal.text)}</pre>`; }
  }
}
async function setProposalStatus(t, status) {
  t.proposal.status = status;
  if (t.exid && M.st.chat) { try { await api(`collections/${encodeURIComponent(M.c.id)}/chats/${encodeURIComponent(M.st.chat.id)}/exchanges/${encodeURIComponent(t.exid)}`, json("PATCH", { proposal_status: status })); } catch { toast({ message: "Could not save that choice." }); } }
  drawThread(true); loadDiffs();
}
function selectedIn(art) {
  const sel = window.getSelection(), box = art?.querySelector(".co-atext");
  return sel && !sel.isCollapsed && box && box.contains(sel.anchorNode) && box.contains(sel.focusNode) ? sel.toString().trim() : "";
}
function useAsPrompt(t, art) {
  const text = selectedIn(art) || extractPrompt(shown(t));
  if (text) sendDraft("new", text, { title: "", from: "Collections" }, "#/studio/new");
}
function proposalAction(t, act, btn) {
  if (act === "copy") return copy(btn, t.proposal.text);
  if (act === "dismiss") return setProposalStatus(t, "dismissed");
  const tg = act === "open" ? targetOf(t) : null;
  const hash = tg ? `#/${tg.source === "studio" ? "studio" : "prompts"}/${encodeURIComponent(tg.ref)}` : "#/studio/new";
  if (sendDraft(tg ? tg.ref : "new", t.proposal.text, { title: tg ? "" : titleOf(t), message: "Collections: " + (titleOf(t) || "proposed edit"), from: "Collections" }, "")) {
    setProposalStatus(t, "applied").then(() => { location.hash = hash; });
  }
}

// ---------- sources ----------
const where = (p) => (p.source === "library" ? `#/prompts/${p.ref}` : p.source === "studio" ? `#/studio/${p.ref}` : `#/collections/${(p.collections || [])[0] || M.c.id}/documents`);
/** Show or hide the Sources column (wide windows) or drawer (under 1280px): the top-bar button, the cosources key and the x all come here. */
export function toggleSources() { if (M) { M.side = !M.side; drawSources(); } }
function syncSourcesButton(n) {   // the top-bar button (collection.js) shows whether Sources is open and how many sources the selected answer has
  const b = document.getElementById("co-srcbtn"), k = b?.querySelector(".co-srccount");
  if (!b || !M) return;
  b.classList.toggle("on", M.side); b.setAttribute("aria-pressed", String(M.side));
  k.textContent = n || ""; k.hidden = !n;
}
function drawSources(flash) {
  const box = $("#co-sources", M.box), t = M.st.turns[M.sel], s = t?.sources;
  syncSourcesButton(s?.passages?.length || 0);
  const head = `<div class="co-shrow"><h2 class="co-sh">Sources</h2><button type="button" class="btn btn-sm btn-glow btn-glow-md btn-glow-icon co-srcclose" data-closesrc aria-label="Close sources" title="Close">${ic(`<path d="M6 6l12 12M18 6L6 18"/>`, 16)}</button></div>`;
  $(".co-chat", M.box)?.classList.toggle("co-noside", !M.side);
  if (!t) {   // before the first question: what is searched, then the passages behind each answer show up here
    const docs = M.docs || [];
    box.innerHTML = `${head}<p class="muted small">${M.c.builtin ? "Your Library and Studio prompts are searched." : docs.length ? `${plural(docs.reduce((n, d) => n + (d.passages || 0), 0), "passage")} in ${plural(docs.length, "document")} are searched for each question.` : "No documents yet."} The passages behind each answer show up here.</p>
      ${docs.map((d) => `<div class="co-srcdoc"><span title="${esc(d.name)}">${esc(d.name)}</span><span class="muted">${d.status === "ready" ? plural(d.passages || 0, "passage") : esc(d.status)}</span></div>`).join("")}`;
    return;
  }
  const ps = s?.passages || [];
  box.innerHTML = `${head}
    <p class="muted small">${!s ? "Waiting for the search…" : !s.searched ? "Not searched for this message." : s.mode === "hybrid" ? "Meaning and keyword search combined." : "Keyword search only."}${s?.note ? ` ${esc(s.note)}` : ""}</p>
    ${ps.map((p) => `<article class="co-src${p.cite ? "" : " unused"}${flash === p.cite ? " flash" : ""}" data-cite="${p.cite || ""}" id="co-src-${p.cite || "x" + esc(p.id)}">
      <header><span class="co-chipn${p.cite ? "" : " off"}">${p.cite || "–"}</span><strong>${esc(p.name)}</strong><span class="co-score" title="Match score, 0 to 100">${Math.round(p.score * 100)}</span></header>
      <p class="pr-meta">${esc([p.source === "document" ? "document" : p.source, p.locator].filter(Boolean).join(" · "))}${p.cite ? "" : p.below ? " · below your relevance cutoff" : " · not sent (no room)"}</p>
      <p class="co-excerpt">${esc(p.text.length > 260 ? p.text.slice(0, 260).trimEnd() + "…" : p.text)}</p>
      <a class="co-open" href="${esc(where(p))}">Open</a></article>`).join("")}`;
  if (flash) $(`#co-src-${flash}`, box)?.scrollIntoView({ block: "nearest" });
}

// ---------- model, scope ----------
async function loadModels() {
  const sel = $("#co-model", M.box);
  try { M.providers = (await api("assistant/providers")); } catch { M.providers = null; }
  const list = (M.providers?.providers || []).filter((p) => p.reachable).flatMap((p) => p.models.map((m) => ({ provider: p.id, name: m, label: p.kind === "remote" ? "Remote" : "Local" })));
  const def = M.providers?.default;
  if (!list.length) { sel.innerHTML = `<option value="">${def?.model ? esc(def.model) : "No model found"}</option>`; sel.disabled = !def?.model; return; }
  const saved = store.get("co-chat-model") || "", want = list.some((m) => `${m.provider}::${m.name}` === saved) ? saved : def ? `${def.provider}::${def.model}` : "";
  sel.innerHTML = list.map((m) => `<option value="${esc(m.provider + "::" + m.name)}"${`${m.provider}::${m.name}` === want ? " selected" : ""}>${esc(m.name)} · ${m.label}</option>`).join("");
}
const modelRef = () => { const v = $("#co-model", M.box).value; if (!v.includes("::")) return null; const [provider, name] = v.split("::"); return { provider, name }; };

async function loadCollections() {
  try { M.collections = (await api("collections?page_size=200")).items; } catch { M.collections = []; }
  drawScope();
}
function drawScope() {
  if (!M) return;
  const names = Object.fromEntries(M.collections.map((x) => [x.id, x.name]));
  const sc = M.st.scope, bits = [];
  if (M.retrieval !== "auto") bits.push(M.retrieval === "on" ? "Always search" : "No search");
  if (sc.length > 1) bits.push(`${sc.length} collections`); else if (sc[0] && sc[0] !== M.c.id) bits.push(names[sc[0]] || "other collection");
  $("#co-scopeinfo", M.box).textContent = bits.join(" · ");
  $("#co-scopemenu", M.box).innerHTML = M.collections.map((x) => `<button type="button" class="pr-menuitem" role="menuitemcheckbox" aria-checked="${sc.includes(x.id)}" data-scope="${esc(x.id)}"><span>${esc(x.name)}</span><span>${sc.includes(x.id) ? "✓" : ""}</span></button>`).join("");
}

// ---------- sending ----------
function statusText(t) {
  if (!t?.done) return "";
  const d = t.done, s = t.sources, bits = [];
  const best = d.best != null ? `best match ${d.best.toFixed(2)}` : "";
  bits.push(!d.searched ? `not searched${d.why === "small_talk" ? " (chit-chat)" : d.why === "off" ? " (search is Off)" : ""}` : `${plural(d.included.length, "passage")} sent`);
  if (d.searched && d.below) bits.push(`${plural(d.below, "passage")} below your relevance cutoff ${d.cutoff}${best ? ` (${best})` : ""}`);
  else if (d.searched && d.cutoff && best) bits.push(best);
  if (d.searched && s?.mode) bits.push(s.mode === "hybrid" ? "meaning + keyword search" : "keyword search only");
  if (d.dropped) bits.push(`${plural(d.dropped, "passage")} left out to fit the context size`);
  if (d.cut) bits.push("one passage shortened to fit");
  if (d.trimmed) bits.push(`${plural(d.trimmed, "earlier exchange")} left out`);
  return `Last message: ${bits.join(" · ")}. ${d.model.name}, ${d.params.num_ctx.toLocaleString()} tokens of context.`;
}
function setBusy(on) {
  M.busy = on;
  $("#co-send", M.box).hidden = !on;   // Enter sends; while an answer arrives this button is Stop
}
async function send() {
  if (M.busy) { M.ctl?.abort(); return; }
  const ask = $("#co-ask", M.box), message = ask.value.trim();
  if (!message) return;
  const model = modelRef();
  if (!model) { toast({ message: "Pick a chat model first (is Ollama running?).", ms: 4000 }); return; }
  const st = M.st, history = st.turns.filter((t) => t.response && !t.error && !t.partial).map((t) => ({ prompt: t.prompt, response: t.response }));
  const turn = { prompt: message, response: "", sources: null, done: null, error: "", partial: false };
  st.turns.push(turn); M.sel = st.turns.length - 1;
  ask.value = ""; ask.style.height = ""; M.follow = true; setBusy(true); drawThread(); drawSources(); drawJump();
  $("#co-status", M.box).textContent = "";
  const ctl = M.ctl = new AbortController(), mine = M;
  try {
    const res = await fetch(`/api/collections/${encodeURIComponent(M.c.id)}/chat`, { method: "POST", signal: ctl.signal, headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message, scope: st.scope, retrieval: M.retrieval, model, history, chat: st.chat?.id || "" }) });
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || res.status);
    const reader = res.body.getReader(), dec = new TextDecoder();
    let buf = "";
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      let nl;
      while ((nl = buf.indexOf("\n")) >= 0) {
        const line = buf.slice(0, nl).trim(); buf = buf.slice(nl + 1);
        if (!line) continue;
        const ev = JSON.parse(line);
        if (ev.t === "sources") { turn.sources = ev; if (ev.chat) st.chat = ev.chat; if (M === mine) drawSources(); }
        else if (ev.t === "delta") { turn.response += ev.text; if (M === mine) updateLast(); }
        else if (ev.t === "done") { turn.done = ev; turn.proposal = ev.proposal || null; turn.exid = ev.exchange || ""; if (ev.chat) st.chat = ev.chat; }
        else if (ev.t === "error") turn.error = ev.message;
      }
    }
  } catch (e) {
    if (e.name === "AbortError") turn.partial = true;
    else turn.error = turn.error || `Could not get an answer: ${e.message}`;
  }
  if (M !== mine) return;   // the page moved on while this was running
  if (turn.error && turn.response) { turn.partial = true; turn.error = ""; }
  M.ctl = null; setBusy(false); drawThread(true); drawSources(); drawHead(); loadDiffs(); drawJump();
  setTimeout(() => { if (M === mine) loadChats(); }, turn.partial ? 500 : 0);   // a stopped answer is saved a moment after the connection closes
  $("#co-status", M.box).textContent = turn.partial ? "Stopped. What arrived is kept." : statusText(turn);
  ask.focus();
}

function wire() {
  const box = M.box;
  $("#co-composer", box).addEventListener("submit", (e) => { e.preventDefault(); send(); });
  const grow = (el) => { el.style.height = "auto"; el.style.height = Math.min(el.scrollHeight, 240) + "px"; };   // the question box grows with what you type
  $("#co-ask", box).addEventListener("input", (e) => grow(e.target));
  $("#co-ask", box).addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey && !e.isComposing && !e.metaKey && !e.ctrlKey && !e.altKey) { e.preventDefault(); send(); } });
  $("#co-model", box).addEventListener("change", (e) => store.set("co-chat-model", e.target.value));
  $("#co-newchat", box).addEventListener("click", newChat);
  box.addEventListener("click", (e) => {
    const t = e.target, r = t.closest("[data-ret]");
    if (r) { M.retrieval = r.dataset.ret; store.set("co-chat-retrieval", M.retrieval); box.querySelectorAll("[data-ret]").forEach((b) => { const on = b === r; b.classList.toggle("on", on); b.setAttribute("aria-pressed", on); }); drawScope(); return; }
    if (t.closest("#co-jump")) { M.follow = true; toBottom(); drawJump(); return; }
    if (t.closest("[data-closesrc]")) { M.side = false; drawSources(); return; }
    const op = t.closest("[data-open]");
    if (op) { openChat(op.dataset.open); return; }
    const ca = t.closest("[data-chatact]");
    if (ca) { ca.closest("details")?.removeAttribute("open"); chatAct(ca.closest("[data-for]").dataset.for, ca.dataset.chatact); return; }
    const sc = t.closest("[data-scope]");
    if (sc) {
      const id = sc.dataset.scope, cur = M.st.scope, next = cur.includes(id) ? cur.filter((x) => x !== id) : [...cur, id];
      if (next.length) { M.st.scope = next; drawScope(); } else toast({ message: "Keep at least one to search.", ms: 2500 });
      return;
    }
    const art = t.closest(".co-turn"), i = art ? +art.dataset.i : -1;
    const ct = t.closest(".co-cite");
    if (ct && art) { M.sel = i; M.side = true; drawSources(+ct.dataset.cite); return; }
    if (t.closest("[data-show]") && art) { M.sel = i; M.side = true; drawSources(); return; }
    const pr = t.closest("[data-prop]");
    if (pr && art) { proposalAction(M.st.turns[i], pr.dataset.prop, pr); return; }
    if (t.closest("[data-use]") && art) { useAsPrompt(M.st.turns[i], art); return; }
    const cp = t.closest("[data-copy]");
    if (cp && art) copy(cp, M.st.turns[i].response);
  });
}
document.addEventListener("click", closeScope);
function closeScope(e) {
  if (!M) return;
  for (const id of ["#co-plus"]) { const d = $(id, M.box); if (d?.open && !d.contains(e.target)) d.open = false; }
}

/** For the ⌘K "New chat" entry: forget the open conversation of a collection (the next question starts a new one). */
export function resetChat(cid) {
  if (M && M.c.id === cid) { newChat(); return; }
  const st = KEEP.get(cid);
  if (st) { st.turns = []; st.chat = null; }
}

function newChat() {
  if (!M) return;
  M.ctl?.abort();
  M.st.turns = []; M.st.chat = null; M.sel = -1;
  setBusy(false); drawThread(true); drawSources(); drawChats(); drawHead();
  $("#co-status", M.box).textContent = ""; $("#co-ask", M.box).focus();
}

// Keys (rebindable, Settings > Keyboard > Collections). Only while a chat is open.
addEventListener("keydown", (e) => {
  if (!M || !M.box.isConnected || M.box.offsetParent === null || e.defaultPrevented || document.querySelector("dialog[open]")) return;
  if (matches(e, "cofocus")) { e.preventDefault(); $("#co-ask", M.box).focus(); }
  else if (matches(e, "cosend")) { e.preventDefault(); send(); }
  else if (matches(e, "conewchat")) { e.preventDefault(); newChat(); }
  else if (e.key === "Escape" && M.side && !matchMedia("(min-width: 1280px)").matches) { M.side = false; drawSources(); }   // the narrow-window drawer
  else if (matches(e, "cosources")) { e.preventDefault(); toggleSources(); }
});
addEventListener("flowlystack-hotkeys", () => { M?.box.querySelectorAll("kbd[data-hk]").forEach((k) => { k.textContent = keyLabel(hotkey(k.dataset.hk)); }); });

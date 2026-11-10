// The Studio Assistant panel: a column beside the Studio editor where you talk to a local model about the open prompt.
// Studio hands it the text on screen (editor `extras.text`) and mounts it after each editor build (`extras.wire`). Nothing is
// sent anywhere until you press Send; opening the panel only asks Ollama what models it has. Plain DOM, no framework.
// API: /api/studio/{id}/assistant (streamed), /chat, /chat/export and /api/assistant/providers (backend/assistant_api.py).
import { api, relTime as rel } from "./api.js";
import { confirmDialog } from "./dialog.js";
import { toast } from "./toast.js";
import { ICONS, registerCommands } from "./palette.js";
import { esc, send, copy, saveFile, diffHtml, COPY_ICONS, TRASH, DOTS } from "./editor.js";

const KEY_OPEN = "flowlystack-assistant-open", KEY_MODEL = "flowlystack-assistant-model";
const lsGet = (k) => { try { return localStorage.getItem(k); } catch { return null; } };
const lsSet = (k, v) => { try { localStorage.setItem(k, v); } catch { /* a convenience only */ } };
export const ICON = `<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 3l1.8 4.6L18.5 9l-4.7 1.4L12 15l-1.8-4.6L5.5 9l4.7-1.4z"/><path d="M18 15l.8 2 2 .8-2 .8-.8 2-.8-2-2-.8 2-.8z"/></svg>`;

// One panel per open prompt; `mount` replaces the state.
let A = null;
const q = (s) => A.root.querySelector(s);
const enc = encodeURIComponent;

export const isOpen = () => lsGet(KEY_OPEN) === "1";
export const sideHtml = () => `<div class="as" id="as"></div>`;

registerCommands(() => [
  { label: "Ask the assistant", where: "Prompt Studio", keywords: "assistant ai model ollama chat improve refine", icon: ICONS.agent, run: () => {
    if (A && /^#\/studio\/ps-/.test(location.hash)) { setOpen(true); q("#as-input")?.focus(); } else location.hash = "#/studio";
  } },
]);
addEventListener("hashchange", () => A?.ctl?.abort());   // leaving the prompt stops the model call; the server keeps what arrived

/** Called after every editor build. `ctx.meta()` returns the documentation fields as they are on screen. */
export function mount(root, d, ctx) {
  A?.ctl?.abort();
  A = { root, id: d.id, text: d.text, meta: ctx.meta, apply: ctx.apply, savedText: ctx.savedText, exchanges: [], local: [], saving: true,
        providers: null, defaults: null, turns: 6, busy: false, ctl: null, loaded: false, note: "" };
  A.root.querySelector("#pr-layout")?.classList.toggle("as-open", isOpen());
  if (isOpen()) build();
}

export const onText = (t) => {
  if (!A) return;
  A.text = t;
  if (A.built) { clearTimeout(A.diffT); A.diffT = setTimeout(loadDiffs, 400); }   // an open proposal is compared with the text on screen as it is now
};

export function toggle() {
  setOpen(!isOpen());
  if (isOpen()) q("#as-input")?.focus();
  return isOpen();
}

function setOpen(on) {
  lsSet(KEY_OPEN, on ? "1" : "0");
  A.root.querySelector("#pr-layout").classList.toggle("as-open", on);
  A.root.querySelector('[data-tool][title^="Ask the assistant"]')?.setAttribute("aria-pressed", String(on));
  if (on && !A.built) build();
}

// ======================================================================= build
function build() {
  A.built = true;
  q("#as").innerHTML = `
    <header class="as-head">
      <strong class="as-title">Assistant</strong>
      <span class="as-badge" id="as-badge" hidden></span>
      <details class="pr-more as-more" id="as-more">
        <summary class="icon-btn" aria-label="Assistant menu" title="More">${DOTS}</summary>
        <div class="pr-menu pr-morepanel" id="as-menu"></div>
      </details>
    </header>
    <div class="as-modelrow"><select class="pl-input" id="as-model" aria-label="Model"></select></div>
    <div class="as-incl"><span class="pl-label" id="as-incl-l">Prompt text</span>
      <div class="seg" id="as-incl" role="group" aria-labelledby="as-incl-l">${[["auto", "Auto"], ["on", "On"], ["off", "Off"]].map(([v, l]) => `<button type="button" data-v="${v}" aria-pressed="${v === includeMode()}" class="${v === includeMode() ? "on" : ""}">${l}</button>`).join("")}</div></div>
    <p class="as-note small" id="as-note" role="status" hidden></p>
    <div class="as-list" id="as-list" aria-live="polite"></div>
    <form class="as-compose" id="as-form">
      <textarea class="pl-input pl-area" id="as-input" rows="3" placeholder="Ask about this prompt…" aria-label="Message to the assistant"></textarea>
      <div class="as-foot"><span class="muted small" id="as-sends"></span><button type="button" class="icon-btn stop-btn" id="as-send" aria-label="Stop" title="Stop" hidden><svg viewBox="0 0 24 24" width="14" height="14" aria-hidden="true"><rect x="6" y="6" width="12" height="12" rx="2" fill="currentColor"/></svg></button></div>
    </form>`;
  wire();
  renderMenu(); renderList(); renderSends();
  load();
}

async function load() {
  const [chat, prov, cfg] = await Promise.all([
    api(`studio/${enc(A.id)}/chat`).catch(() => null),
    api("assistant/providers").catch(() => null),
    api("settings").catch(() => null),
  ]);
  if (!A) return;
  if (chat) { A.exchanges = chat.exchanges; A.saving = chat.saving; }
  A.providers = prov?.providers ?? [];
  A.defaults = prov?.default ?? cfg?.sections.assistant.default ?? null;
  A.turns = cfg?.sections.assistant.context_turns ?? 6;
  A.loaded = true;
  renderModels(); renderMenu(); renderList(); renderSends(); renderNote();
  startWatch();
}

// ---- connection watch: while the panel is open and the tab is visible, ask the model servers (never a model, never any text) if they answer every
// few seconds and on returning to the tab, so the status light follows Ollama being turned off or on without a page refresh.
let watchT = 0, watching = false;
const WATCH_MS = 5000;
async function refreshConnection() {
  if (!A?.built || !A.loaded || A.busy || watching || document.hidden || !isOpen() || !A.root.isConnected) return;
  watching = true;
  const mine = A;
  try {
    const prov = await api("assistant/providers");
    if (A !== mine || !prov) return;
    const key = (ps) => JSON.stringify((ps || []).map((p) => [p.id, p.reachable, p.models]));
    if (key(prov.providers) === key(A.providers)) return;   // nothing changed: leave the model list and the box alone
    A.providers = prov.providers ?? [];
    A.defaults = prov.default ?? A.defaults;
    renderModels(); renderSends(); renderNote();
  } catch { /* a failed check keeps the last state; the next one tries again */ } finally { watching = false; }
}
function startWatch() {
  if (watchT) return;
  watchT = setInterval(refreshConnection, WATCH_MS);
  document.addEventListener("visibilitychange", refreshConnection);
  addEventListener("focus", refreshConnection);
}

// ---- model picker: every chat model every reachable provider has, the saved default first choice
function options() {
  return (A.providers || []).filter((p) => p.reachable).flatMap((p) => p.models.map((m) => ({ provider: p.id, name: m, p })));
}
function picked() {
  const sel = q("#as-model"), v = sel?.value;
  if (v) { const [provider, ...rest] = v.split("::"); return { provider, name: rest.join("::") }; }
  return A.defaults ? { provider: A.defaults.provider, name: A.defaults.model } : null;
}
function renderModels() {
  const sel = q("#as-model"), opts = options();
  if (!opts.length) {
    renderBadge();
    const d = A.defaults;
    sel.innerHTML = d ? `<option value="${esc(d.provider + "::" + d.model)}">${esc(d.model)}</option>` : `<option value="">No model</option>`;
    sel.disabled = !d;
    return;
  }
  const want = lsGet(KEY_MODEL), def = A.defaults ? `${A.defaults.provider}::${A.defaults.model}` : "";
  const ids = opts.map((o) => `${o.provider}::${o.name}`);
  const cur = ids.includes(want) ? want : ids.includes(def) ? def : ids[0];
  sel.disabled = false;
  sel.innerHTML = opts.map((o) => `<option value="${esc(o.provider + "::" + o.name)}"${(o.provider + "::" + o.name) === cur ? " selected" : ""}>${esc(o.name)} · ${esc(o.p.label)}</option>`).join("");
  renderBadge();
}
function providerOf(sel) { return (A.providers || []).find((p) => p.id === (sel || picked())?.provider); }
function renderBadge() {
  const p = providerOf(), b = q("#as-badge");
  if (A.loaded && !options().length) {   // no model server answered: the light flashes red (connected: flashes green, see .as-badge in app.css)
    b.hidden = false; b.className = "as-badge off"; b.textContent = "Disconnected";
    b.title = "The model server can't be reached. Check Settings > Connections.";
    return;
  }
  b.hidden = !p;
  if (!p) return;
  b.className = "as-badge " + p.kind;
  b.textContent = p.kind === "local" ? "Local" : `Remote · ${p.host}`;
  b.title = p.kind === "local" ? "The model runs on this computer." : "The model runs on another computer: your text is sent over the network.";
}
function renderNote() {
  const n = q("#as-note"), msgs = [];
  if (A.loaded && !options().length) msgs.push(`The model server can't be reached. Check <a href="#/settings/connections">Settings › Connections</a>, then <button type="button" class="as-link" id="as-retry">try again</button>.`);
  if (A.loaded && !A.saving) msgs.push(`This conversation is not being saved (switched off in Settings). It only lasts until you leave.`);
  if (A.note) msgs.push(esc(A.note));
  if (A.error) msgs.push(`<span class="set-bad">${esc(A.error)}</span>`);
  n.hidden = !msgs.length;
  n.innerHTML = msgs.join("<br>");
}
// Prompt text setting: Auto sends the text on the left only when the message is about the prompt, On always, Off never (remembered, a convenience).
const KEY_INCL = "flowlystack-assistant-include";
const includeMode = () => (["auto", "on", "off"].includes(lsGet(KEY_INCL)) ? lsGet(KEY_INCL) : "auto");
function renderSends() {
  const p = providerOf(), m = picked(), where = !p ? "the model" : p.kind === "local" ? `${m?.name || "the model"} on this computer` : `${m?.name} at ${p.host}`, mode = includeMode();
  const what = mode === "on" ? "the prompt text, its notes and" : mode === "off" ? "only your message and" : "your message, plus the prompt text and its notes when you ask about the prompt, and";
  const why = { on: "mode On", off: "mode Off", about_prompt: "you asked about the prompt", follow_up: "a follow-up to the last message", chat: "it read as ordinary chat" }[A.why] || "";
  q("#as-sends").innerHTML = esc(`Sends ${what} up to ${A.turns} earlier exchanges to ${where}.${A.sent == null ? "" : ` Last message: prompt text ${A.sent ? "sent" : "not sent"}${why ? ` (${why})` : ""}.`}`)
    + (A.sent === false && A.lastMessage && !A.busy ? ` <button type="button" class="as-again" data-again title="Ask the last message again with the prompt text attached">Ask again with prompt text</button>` : "");
}

// ---- the ⋯ menu
function renderMenu() {
  const n = A.exchanges.length;
  q("#as-menu").innerHTML = `
    <button type="button" class="pr-menuitem" data-m="clear"${n ? "" : " disabled"}>${TRASH}<span>Clear conversation</span></button>
    <span class="pr-menuhead">Export conversation</span>
    <button type="button" class="pr-menuitem" data-m="export-md"${n ? "" : " disabled"}><span>Markdown (.md)</span></button>
    <button type="button" class="pr-menuitem" data-m="export-json"${n ? "" : " disabled"}><span>JSON (.json)</span></button>`;
}

async function menu(act) {
  q("#as-more").open = false;
  if (act === "clear") {
    if (!await confirmDialog({ title: "Clear conversation", message: "Delete every saved exchange of this prompt's conversation? This can't be undone.", confirmLabel: "Clear", danger: true })) return;
    await api(`studio/${enc(A.id)}/chat`, { method: "DELETE" });
    A.exchanges = []; A.local = []; renderMenu(); renderList();
    toast({ message: "Conversation cleared." });
  } else if (act.startsWith("export-")) {
    const kind = act.slice(7), url = `/api/studio/${enc(A.id)}/chat/export?format=${kind === "json" ? "json" : "md"}${kind === "kept" ? "&kept=true" : ""}`;
    try {
      const r = await fetch(url);
      if (!r.ok) throw new Error(r.status);
      const name = /filename="([^"]+)"/.exec(r.headers.get("content-disposition") || "")?.[1] || "conversation." + (kind === "json" ? "json" : "md");
      const f = kind === "json" ? { label: "JSON", types: { "application/json": [".json"] } } : { label: "Markdown", types: { "text/markdown": [".md"] } };
      toast({ message: await saveFile(name, await r.text(), f) });
    } catch (e) {
      if (e.name !== "AbortError") toast({ message: "Could not export the conversation." });
    }
  }
}

// ======================================================================= messages
const all = () => [...A.exchanges, ...A.local];

// ---- the answer as people see it: the model's sentences, with its <<<PROMPT ... PROMPT>>> block cut out (it becomes the Proposed edit card).
// Same rule as backend/assistant/prompting.py `parse_proposal`; the saved answer and the pairs export keep the raw text.
const P_OPEN = /<<<PROMPT[ \t]*\r?\n/, P_CLOSE = /\r?\n?[ \t]*PROMPT[<>]{2,3}/;
const tidy = (t) => t.replace(/\n{3,}/g, "\n\n").trim();
export function shown(e) {
  const text = e.response || "", m = P_OPEN.exec(text);
  if (!m) return tidy(text);
  const before = text.slice(0, m.index), rest = text.slice(m.index + m[0].length), c = P_CLOSE.exec(rest);
  if (e.proposal) return tidy(before + (c ? rest.slice(c.index + c[0].length) : ""));   // the card has it
  return tidy(before + (c ? rest.slice(0, c.index) + rest.slice(c.index + c[0].length) : rest.replace(/\s*(?:PROMPT)?[<>]{2,3}\s*$/, "")));   // no card (the same text, or empty): just drop the marker lines
}
export function liveHtml(text) {   // while the answer streams: nothing of the block shows, only a line saying it is being written
  const m = P_OPEN.exec(text);
  if (!m) return esc(text);
  return esc(tidy(text.slice(0, m.index))) + `<span class="as-writing">Writing a proposed edit…</span>`;
}

// ---- Use as prompt: put an answer (or the part you selected) into the editor as an unsaved draft; never saves
const USE_ICON = `<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 12h11M11 7l5 5-5 5M20 5v14"/></svg>`;
/** The prompt inside an answer: what a person would copy. The answer's own words around it ("Here is a revised version:", "What would you
 *  like me to focus on?") are left out. In order: a ``` code block; a quoted paragraph (“…” or "…", possibly several paragraphs inside);
 *  else the answer without an opening line that ends in a colon and a closing question. Nothing found means the whole answer. */
export function extractPrompt(answer) {
  const t = (answer || "").trim();
  const fence = /```[^\n]*\n([\s\S]*?)```/.exec(t);
  if (fence && fence[1].trim()) return fence[1].trim();
  const quoted = /(?:^|\n\n)[“"]([\s\S]+?)[”"](?=\n\n|\s*$)/.exec(t);
  if (quoted && quoted[1].trim().length >= 20) return quoted[1].trim();
  const paras = t.split(/\n{2,}/);
  if (paras.length > 1 && /:\s*$/.test(paras[0])) paras.shift();
  if (paras.length > 1 && /\?\s*$/.test(paras[paras.length - 1])) paras.pop();
  return paras.join("\n\n").trim() || t;
}
const usable = (e) => !(e.proposal?.text && (e.proposal.status || "open") === "open") && !!shown(e).trim();   // an open Proposed edit card has its own Apply
function selectedIn(art) {
  const sel = window.getSelection(), box = art?.querySelector(".as-text");
  return sel && !sel.isCollapsed && box && box.contains(sel.anchorNode) && box.contains(sel.focusNode) ? sel.toString().trim() : "";
}
async function useAsPrompt(ex) {
  const text = A.pick || extractPrompt(shown(ex));
  A.pick = "";
  if (!text) return;
  if (A.text !== A.savedText() && !await confirmDialog({ title: "Replace your edits?", message: "The text on screen has changes you have not saved. Loading this replaces all of it.", confirmLabel: "Replace" })) return;
  const first = (ex.prompt || "").split("\n")[0].trim();
  A.apply(text, "Assistant: " + (first.length > 60 ? first.slice(0, 57) + "…" : first || "answer"));
  toast({ message: "Loaded into the editor. Review it, then Save." });
}

// ---- Proposed edit card: compare with the text on screen, Apply to editor (never saves), Dismiss
const PROP_LABEL = { applied: "Applied", dismissed: "Dismissed" };
function proposalHtml(e) {
  const p = e.proposal;
  if (!p?.text) return "";
  const st = p.status || "open";
  if (st !== "open") return `<details class="as-prop done" data-status="${st}"><summary><span class="as-chip">${PROP_LABEL[st]}</span> Proposed edit</summary><pre class="as-propbody">${esc(p.text)}</pre></details>`;
  return `<section class="as-prop" data-status="open" aria-label="Proposed edit">
    <header class="as-prophead"><strong>Proposed edit</strong>
      <button type="button" class="icon-btn" data-prop="copy" aria-label="Copy the proposed prompt" title="Copy the proposed prompt">${COPY_ICONS}</button></header>
    <div class="as-diff" data-diff><p class="muted small as-diffwait">Comparing…</p></div>
    <div class="as-propactions"><button type="button" class="btn btn-sm btn-glow" data-prop="apply">Apply to editor</button><button type="button" class="btn btn-sm btn-glow" data-prop="dismiss">Dismiss</button></div>
  </section>`;
}

async function loadDiffs() {   // compare each open proposal with the text on screen now (the newest few only)
  if (!A?.built) return;
  const mine = A, open = all().filter((e) => e.proposal?.text && (e.proposal.status || "open") === "open").slice(-3);
  for (const e of open) {
    const box = q(`.as-ex[data-id="${CSS.escape(e.id)}"] [data-diff]`);
    if (!box) continue;
    try {
      const r = await send("POST", "assistant/diff", { a: mine.text, b: e.proposal.text });
      if (A !== mine) return;
      box.innerHTML = r.rows.some((x) => x.t !== "eq" && x.t !== "gap") ? `<div class="df uni">${diffHtml(r.rows, false)}</div>` : `<p class="muted small as-diffwait">The same as the text on screen.</p>`;
    } catch { box.innerHTML = `<p class="muted small as-diffwait">Could not compare.</p>`; }
  }
}

async function proposalAction(ex, act, btn) {
  if (act === "copy") { copy(btn, ex.proposal.text); return; }
  if (act === "dismiss") { await setProposalStatus(ex, "dismissed"); return; }
  if (act === "apply") {
    if (A.text !== A.savedText() && !await confirmDialog({ title: "Replace your edits?", message: "The text on screen has changes you have not saved. Applying the proposal replaces all of it. You can still undo this by reloading the saved version.", confirmLabel: "Apply" })) return;
    const first = (ex.prompt || "").split("\n")[0].trim();
    A.apply(ex.proposal.text, "Assistant: " + (first.length > 60 ? first.slice(0, 57) + "…" : first || "proposed edit"));
    await setProposalStatus(ex, "applied");
    toast({ message: "Loaded into the editor. Review it, then Save." });
  }
}

async function setProposalStatus(ex, status) {   // saved with the conversation, so a reload shows Applied or Dismissed instead of buttons
  ex.proposal.status = status;
  if (!ex.unsaved) {
    try { Object.assign(ex, await send("PATCH", `studio/${enc(A.id)}/chat/${enc(ex.id)}`, { proposal_status: status })); }
    catch { toast({ message: "Could not save that choice." }); }
  }
  const art = q(`.as-ex[data-id="${CSS.escape(ex.id)}"]`);
  if (art) { art.outerHTML = exHtml(ex); }
}

function exHtml(e) {
  return `<article class="as-ex" data-id="${esc(e.id)}">
    <div class="as-user">${esc(e.prompt)}</div>
    <div class="as-bot">
      <div class="as-text">${esc(shown(e))}</div>
      ${proposalHtml(e)}
      <div class="as-meta muted">
        <span>${esc(e.model?.name || "")} · ${rel(e.ts)}</span>
        ${e.partial ? `<span class="as-chip">stopped</span>` : ""}${e.unsaved ? `<span class="as-chip" title="Kept only until you leave this page.">not saved</span>` : ""}
        <span class="as-actions">
          ${usable(e) ? `<button type="button" class="icon-btn as-use" data-use aria-label="Use as prompt" title="Use as prompt: load the prompt from this answer into the editor (the quoted or code-block part, without the chat around it). Select text first to load exactly that.">${USE_ICON}</button>` : ""}
          <button type="button" class="icon-btn" data-copy aria-label="Copy answer" title="Copy answer">${COPY_ICONS}</button>
          <button type="button" class="icon-btn" data-del aria-label="Delete this exchange" title="Delete this exchange">${TRASH}</button>
        </span>
      </div>
    </div></article>`;
}

function renderList() {
  const list = q("#as-list"), items = all();
  list.innerHTML = items.length ? items.map(exHtml).join("") : `<p class="as-empty muted small">${A.loaded ? "Ask for a clearer, shorter or stricter version, or what is missing. The assistant sees the text on screen, its notes and the variables." : "Loading…"}</p>`;
  list.scrollTop = list.scrollHeight;
  loadDiffs();
}

// ======================================================================= sending
function setBusy(on) {
  A.busy = on;
  const btn = q("#as-send");
  btn.hidden = !on;   // Enter sends; while an answer arrives this round button is Stop
  q("#as-input").readOnly = on;
  q("#as-model").disabled = on || !picked();
}

async function sendMessage(again) {   // `again` = {message}: send that message once more with the prompt text, whatever the switch says
  const input = q("#as-input"), message = again?.message || input.value.trim();
  if (!message || A.busy) return;
  const m = picked();
  A.error = ""; A.note = ""; renderNote();
  const list = q("#as-list");
  list.querySelector(".as-empty")?.remove();
  list.insertAdjacentHTML("beforeend", `<article class="as-ex as-live"><div class="as-user">${esc(message)}</div><div class="as-bot"><div class="as-text as-wait">Thinking…</div></div></article>`);
  const box = list.lastElementChild.querySelector(".as-text");
  list.scrollTop = list.scrollHeight;
  setBusy(true);
  A.ctl = new AbortController();
  let text = "", done = null, failed = "", stopped = false;
  try {
    const r = await fetch(`/api/studio/${enc(A.id)}/assistant`, { method: "POST", headers: { "content-type": "application/json" }, signal: A.ctl.signal,
      body: JSON.stringify({ message, text: A.text, ...(m ? { model: m } : {}), meta: A.meta(), include: again ? "on" : includeMode(), after_included: A.sent === true }) });
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.status);
    const reader = r.body.getReader(), dec = new TextDecoder();
    let buf = "";
    for (;;) {
      const { value, done: end } = await reader.read();
      if (end) break;
      buf += dec.decode(value, { stream: true });
      for (let i; (i = buf.indexOf("\n")) >= 0;) {
        const line = buf.slice(0, i).trim(); buf = buf.slice(i + 1);
        if (!line) continue;
        const ev = JSON.parse(line);
        if (ev.t === "delta") {
          text += ev.text; box.classList.remove("as-wait"); box.innerHTML = liveHtml(text);
          if (list.scrollHeight - list.scrollTop - list.clientHeight < 80) list.scrollTop = list.scrollHeight;   // follow the answer unless you scrolled up
        } else if (ev.t === "done") done = ev; else if (ev.t === "error") failed = ev.message;
      }
    }
  } catch (e) {
    if (e.name === "AbortError") stopped = true; else failed = failed || e.message || "Something went wrong.";
  }
  A.ctl = null;
  if (failed) {   // an error leaves no exchange: the message goes back into the box
    list.lastElementChild.remove();
    A.error = failed; setBusy(false); renderNote(); renderList();
    return;
  }
  if (done) {
    A.sent = done.included; A.why = done.why; A.lastMessage = message; renderSends();
    if (done.saved) A.exchanges.push(done.exchange); else A.local.push({ ...done.exchange, unsaved: true });
    A.note = done.trimmed ? `${done.trimmed} older exchange${done.trimmed === 1 ? " was" : "s were"} left out to fit the context size.` : "";
  } else if (stopped && text.trim()) {   // Stop: the server keeps what arrived (when saving); otherwise keep it here
    await settle(message, text, m);
  } else if (stopped) list.lastElementChild.remove();
  if (!again) input.value = "";
  setBusy(false); renderNote(); renderMenu(); renderList(); renderSends();
}

async function settle(message, text, m) {
  if (A.saving) {   // the server saves a stopped answer a moment after the connection closes
    for (let i = 0; i < 6; i++) {
      await new Promise((r) => setTimeout(r, 350));
      const chat = await api(`studio/${enc(A.id)}/chat`).catch(() => null);
      if (chat && chat.exchanges.length > A.exchanges.length) { A.exchanges = chat.exchanges; return; }
    }
  }
  A.local.push({ id: "local-" + Date.now(), ts: Date.now() / 1000, prompt: message, response: text, partial: true, unsaved: true, model: m ? { provider: m.provider, name: m.name } : {}, curation: null });
}

// ======================================================================= events
function wire() {
  const form = q("#as-form"), input = q("#as-input");
  form.addEventListener("submit", (e) => { e.preventDefault(); sendMessage(); });
  q("#as-sends").addEventListener("click", (e) => { if (e.target.closest("[data-again]") && A.lastMessage) sendMessage({ message: A.lastMessage }); });
  q("#as-send").addEventListener("click", () => { if (A.busy) A.ctl?.abort(); });   // while busy the button is Stop
  input.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); sendMessage(); } });
  q("#as-model").addEventListener("change", (e) => { lsSet(KEY_MODEL, e.target.value); renderBadge(); renderSends(); });
  q("#as-incl").addEventListener("click", (e) => {
    const b = e.target.closest("[data-v]"); if (!b) return;
    lsSet(KEY_INCL, b.dataset.v);
    q("#as-incl").querySelectorAll("[data-v]").forEach((x) => { const on = x === b; x.classList.toggle("on", on); x.setAttribute("aria-pressed", String(on)); });
    renderSends();
  });
  q("#as-menu").addEventListener("click", (e) => { const b = e.target.closest("[data-m]"); if (b && !b.disabled) menu(b.dataset.m); });
  q("#as-note").addEventListener("click", (e) => { if (e.target.closest("#as-retry")) { A.loaded = false; load(); } });
  const list = q("#as-list");
  list.addEventListener("mousedown", (e) => {   // pressing the button clears a text selection, so remember it first
    const b = e.target.closest("[data-use]");
    A.pick = b ? selectedIn(b.closest(".as-ex")) : "";
  });
  list.addEventListener("click", async (e) => {
    const art = e.target.closest(".as-ex"); if (!art || art.classList.contains("as-live")) return;
    const id = art.dataset.id, ex = all().find((x) => x.id === id);
    if (e.target.closest("[data-copy]")) { copy(e.target.closest("[data-copy]"), shown(ex)); return; }
    if (e.target.closest("[data-use]")) { useAsPrompt(ex); return; }
    const pr = e.target.closest("[data-prop]");
    if (pr) { proposalAction(ex, pr.dataset.prop, pr); return; }
    if (e.target.closest("[data-del]")) {
      if (!await confirmDialog({ title: "Delete exchange", message: "Delete this question and answer?", confirmLabel: "Delete", danger: true })) return;
      if (ex.unsaved) A.local = A.local.filter((x) => x.id !== id);
      else { await api(`studio/${enc(A.id)}/chat/${enc(id)}`, { method: "DELETE" }).catch(() => toast({ message: "Could not delete it." })); A.exchanges = A.exchanges.filter((x) => x.id !== id); }
      renderList(); renderMenu(); return;
    }
  });
}

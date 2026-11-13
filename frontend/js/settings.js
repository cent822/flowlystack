// Settings: one page at #/settings/<section>, opened from the account button in the sidebar. A list of sections on the left
// (with Back), the rows of the chosen section on the right, and an explicit Save. Values live on the server
// (/api/settings, backend/settings.py); nothing here is saved until Save is pressed, except the theme, which applies at once.
// A section is one entry in SECTIONS (`backend` names the settings section it saves to when that differs from its id), so adding one later means adding an object. Plain DOM, no framework.
import { api, relTime } from "./api.js";
import { confirmDialog, formDialog } from "./dialog.js";
import { toast } from "./toast.js";
import { ICONS, registerCommands } from "./palette.js";
import { esc, send, copy, COPY_ICONS, CHEV_L } from "./editor.js";
import { isDark, mode, setMode } from "./theme.js";
import { signOut } from "./account.js";
import { comboOf, isMac, label as keyLabel, loadHotkeys } from "./hotkeys.js";
import { mountSamples } from "./samples.js";

const $ = (s) => document.querySelector(s);
const page = () => $("#page-settings");
const ico = (d) => `<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${d}</svg>`;

// kind: theme | text | number | bool | textarea | model | check | rules. `path` is the dotted name used by /api/settings.
const SECTIONS = [
  { group: "Basics", id: "general", label: "General", save: false, icon: ico(`<circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3M4.9 4.9l2.1 2.1M17 17l2.1 2.1M4.9 19.1L7 17M17 7l2.1-2.1"/>`), rows: [
    { id: "theme", kind: "theme", label: "Theme", desc: "Day or night colours for the whole app. It applies right away; System follows your computer." },
    { id: "samples", kind: "samples", label: "Sample content", desc: "A few example prompts, a project plan and short documents to try the app. They are tagged Sample and work offline. Adding them sends nothing anywhere (indexing the documents for search sends their text to your embedding model, like any document). Remove them in one step any time; they go to the Trash." },
  ] },
  { group: "Basics", id: "account", label: "Account", save: false, icon: ico(`<circle cx="12" cy="8.5" r="3.6"/><path d="M5 20c.8-3.6 3.6-5.4 7-5.4s6.2 1.8 7 5.4"/>`), rows: [
    { id: "profilepic", kind: "profilepic", label: "Profile picture", desc: "Shown in the sidebar and the account menu. It is cropped to a square, shrunk in your browser, and stays on this computer: it is never sent anywhere and agents never see it." },
    { id: "profilename", kind: "profilename", label: "Name", desc: "The name you log in with. Changing it asks for your password; you stay signed in." },
    { id: "password", kind: "account", label: "Password", desc: "Change the password you log in with. Every other browser that is signed in is signed out." },
    { id: "twostep", kind: "twostep", label: "Two-step login", desc: "After the password, ask for a 6-digit code from an authenticator app (Google Authenticator, Microsoft Authenticator, 1Password, Authy). You scan a QR code once to set it up, and get backup codes in case you lose the phone." },
    { id: "signout", kind: "signout", label: "Sign out", desc: "End the session in this browser. You log in again with your username and password." },
  ] },
  { group: "Basics", id: "about", label: "About", save: false, icon: ico(`<circle cx="12" cy="12" r="9"/><path d="M12 11v5.5M12 7.6h.01"/>`), rows: [
    { id: "aboutversion", kind: "aboutversion", label: "Version", desc: "The version of FlowlyStack you are running. Release notes are bundled with the app, so they open without a connection." },
    { id: "aboutcredits", kind: "note", label: "Credits", desc: "The letters of the FlowlyStack name in the logo are outlines of Inter Display SemiBold (SIL Open Font License 1.1). Inter is not loaded as a font anywhere in the app." },
  ] },
  { group: "Basics", id: "updates", label: "Updates", icon: ico(`<path d="M12 4v11M7.5 10.5L12 15l4.5-4.5M5 19.5h14"/>`), rows: [
    { path: "updates.check", kind: "bool", label: "Tell me about new versions", desc: "When you are online, FlowlyStack asks GitHub for the latest release, at most once a day, and tells you after login if a newer one exists. The request carries nothing about you or your data. Switch it off and no request is ever made. It never updates the app by itself: you run the update commands. Docker can also turn it off with FLOWLYSTACK_UPDATE_CHECK=off." },
  ] },
  { group: "Basics", id: "keyboard", backend: "hotkeys", label: "Keyboard", icon: ico(`<rect x="2.5" y="6" width="19" height="12" rx="2.5"/><path d="M6 10h.01M10 10h.01M14 10h.01M18 10h.01M7 14h10"/>`), rows: [
    { id: "hkinfo", kind: "note", full: true, label: "About shortcuts", desc: "A shortcut is Cmd (Ctrl on Windows and Linux) plus one letter or digit. You can bind Cmd+Option or Cmd+Shift+Option with a letter or digit, as well as Cmd+Shift. Press a shortcut's button, then the keys you want; Esc cancels. Editor shortcuts work from any field of a prompt page while you edit, so your cursor can stay in the text. Cmd+K (the command palette) and the keys the browser or text editing already use, such as Cmd+N or Cmd+C, are not available." },
    { path: "hotkeys.search", kind: "hotkey", group: "Global", label: "Search", desc: "Moves the cursor to the search box on any page that has one (Prompt Library, Prompt Studio, Linkshell)." },
    { path: "hotkeys.new", kind: "hotkey", group: "Global", label: "New prompt", desc: "Opens a new Prompt Studio prompt, or the New project dialog on the Linkshell list: on any page that has a New button." },
    { path: "hotkeys.tags", kind: "hotkey", group: "Global", label: "Tags", desc: "Puts the cursor in the Tags box of an open prompt or the new-prompt page, ready for the next tag. On a list page it opens the Tags filter menu. In the command palette there is one Tags entry for the Prompt Library and one for Prompt Studio." },
    { path: "hotkeys.paneldone", kind: "hotkey", group: "Global", label: "Done", desc: "Presses the Done button of whatever panel is open, on any page (today the Reference block panel in Linkshell). Any new Done button only needs data-hotkey=\"paneldone\"." },
    { path: "hotkeys.save", kind: "hotkey", group: "Prompt editor", label: "Save prompt", desc: "Saves the open Studio prompt. When the text changed, it asks what changed first." },
    { path: "hotkeys.note", kind: "hotkey", group: "Prompt editor", label: "+ Note", desc: "Opens the note of the open prompt, on any page that has a + Note button (Prompt Library today)." },
    { path: "hotkeys.details", kind: "hotkey", group: "Prompt editor", label: "Properties", desc: "Opens the properties (your own key and value pairs, like purpose or target) of the open Studio prompt." },
    { path: "hotkeys.lsadd", kind: "hotkey", group: "Linkshell", label: "Add prompt block", desc: "Adds a Prompt block at the centre of the open Linkshell canvas." },
    { path: "hotkeys.lsref", kind: "hotkey", group: "Linkshell", label: "Add reference block", desc: "Adds a Reference block (files and web links) at the centre of the open Linkshell canvas." },
    { path: "hotkeys.lsnote", kind: "hotkey", group: "Linkshell", label: "Add sticky note", desc: "Adds a sticky note at the centre of the open Linkshell canvas." },
    { path: "hotkeys.lsframe", kind: "hotkey", group: "Linkshell", label: "Add frame", desc: "Adds a frame (a phase that groups blocks) at the centre of the open Linkshell canvas." },
    { path: "hotkeys.lstidy", kind: "hotkey", group: "Linkshell", label: "Tidy up", desc: "Arranges the blocks of the open Linkshell canvas into phases, left to right. Undo brings the old layout back." },
    { path: "hotkeys.lscopy", kind: "hotkey", group: "Linkshell", label: "Copy prompt", desc: "Copies the current prompt with its context, in the Follow view and in the block panel." },
    { path: "hotkeys.lsdone", kind: "hotkey", group: "Linkshell", label: "Mark done", desc: "Marks the current prompt of the Follow view Done and moves to the next Ready prompt (on a finished prompt it reopens it)." },
    { path: "hotkeys.cofocus", kind: "hotkey", group: "Collections", label: "Focus the question box", desc: "Puts the cursor in the question box of an open collection's chat." },
    { path: "hotkeys.cosend", kind: "hotkey", group: "Collections", label: "Send question", desc: "Sends the question in the chat of an open collection." },
    { path: "hotkeys.conewchat", kind: "hotkey", group: "Collections", label: "New chat", desc: "Starts a new conversation in the open collection." },
    { path: "hotkeys.cosources", kind: "hotkey", group: "Collections", label: "Show or hide Sources", desc: "Opens or closes the Sources panel that lists the passages behind an answer." },
    { path: "hotkeys.codocs", kind: "hotkey", group: "Collections", label: "Go to Documents", desc: "Opens the Documents tab of the open collection, where you add and remove files." },
    { path: "hotkeys.assistant", kind: "hotkey", group: "Assistant", label: "Assistant", desc: "Opens or closes the Assistant panel of the open Studio prompt." },
  ] },
  { group: "Services", id: "connections", label: "Connections", icon: ico(`<path d="M9.5 14.5l5-5M8 16.5a3.5 3.5 0 0 1 0-5l2-2a3.5 3.5 0 0 1 5 0M16 7.5a3.5 3.5 0 0 1 0 5l-2 2a3.5 3.5 0 0 1-5 0"/>`), rows: [
    { path: "connections.ollama.url", kind: "text", label: "Ollama address", desc: "Where Ollama is listening. An address that is not on this computer is marked Remote in the Assistant.", placeholder: "http://127.0.0.1:11434" },
    { id: "check", kind: "check", label: "Ollama connection", desc: "Checks the Ollama address that is saved (save a change first)." },
    { id: "runtimes", kind: "runtimes", label: "Other runtimes", desc: "LM Studio, llama.cpp, vLLM, Jan, LocalAI, or any server that speaks the OpenAI API (a service you host, Hugging Face, OpenAI and others, using your own address and key). Each connection is added and saved here at once, and its models then appear in the Assistant and the Collections chat. Opening those pages asks each connection for its model list (with its key, never your text); text is sent only when you press Send." },
  ] },
  { group: "Services", id: "mcp", label: "MCP", save: false, icon: ico(`<path d="M9 3v5M15 3v5M7 8h10v4a5 5 0 0 1-10 0zM12 17v4"/>`), rows: [
    { id: "mcpswitch", kind: "mcpswitch", label: "Let agents use FlowlyStack", desc: "MCP lets an AI agent (Claude Code, Claude Desktop, Cursor and others) that holds one of your tokens search and read your prompts, collections, Linkshell plans and Gallery. Off until you switch it on. FlowlyStack sends nothing anywhere: the agent's own model reads what its tools return, so only connect agents you trust with that." },
    { id: "mcphidden", kind: "mcphidden", label: "Share hidden Lattice runs", desc: "On the Lattice page you can hide a run of entities an agent added. Off (the default), agents cannot see hidden runs, as if they were not there. Switch it on to let agents read them too. Undone runs are never shown." },
    { id: "mcpendpoint", kind: "mcpendpoint", full: true, label: "Address", desc: "Where an agent connects. It follows the address this page was opened on." },
    { id: "mcptokens", kind: "mcptokens", label: "Tokens", desc: "An agent needs a token to connect. Press New token and copy it: it is shown only once. A new token can only read; Allow writing lets that agent save new prompts and Linkshell projects. Lost it? Regen gives that agent a fresh token (the old one stops working). Revoke cuts an agent off." },
    { id: "mcpconnect", kind: "mcpconnect", full: true, label: "Connect a client", desc: "Pick your app and copy its setup. The text has this computer's address already; it has your token only right after you make or regenerate one." },
    { id: "mcpactivity", kind: "mcpactivity", full: true, label: "Recent agent activity", desc: "What agents saved through a write token, newest first. Undo moves a new prompt or project to the Trash, or puts a prompt's previous text back as its current version. For entities and links an agent added to Lattice, Undo hides the whole run everywhere without deleting it (restore it on the Lattice page). Agents can never delete anything. You can clear this list." },
  ] },
  { group: "Studio", id: "knowledge", label: "Knowledge", icon: ico(`<path d="M4 5.5A1.5 1.5 0 0 1 5.5 4H11v15H5.5A1.5 1.5 0 0 0 4 20.5z"/><path d="M20 5.5A1.5 1.5 0 0 0 18.5 4H13v15h5.5a1.5 1.5 0 0 1 1.5 1.5z"/>`), rows: [
    { id: "embed", kind: "embed", path: "knowledge.embedding_model", label: "Embedding model", desc: "The model that turns your documents and prompts into searchable vectors. Until one is chosen, documents wait and search uses keywords only. Changing it later means every document is indexed again." },
    { path: "knowledge.auto_index", kind: "bool", label: "Index automatically", desc: "Index new and changed documents as soon as they arrive. When off, press Index now on the Collections page." },
    { path: "knowledge.history", kind: "bool", label: "Save conversations", desc: "Keep each collection chat so you can come back to it. When off, a conversation lives only in the open page." },
    { path: "knowledge.top_k", kind: "number", min: 1, max: 30, step: 1, label: "Passages per answer", desc: "How many passages from your documents go to the model with each question." },
    { path: "knowledge.min_relevance", kind: "number", min: 0, max: 1, step: 0.01, label: "Relevance cutoff", desc: "Scale: 0 to 1 (not 0 to 100). 0 is off: the best matches are always sent. Closer to 1 is stricter: a passage is sent only if its meaning score is at least this number, so there is less noise, but a real question may find nothing. Typical values are 0.5 to 0.7, and they depend on your embedding model. Only used when Search before answering is Auto.",
      tip: "A passage that matches your exact words is always kept, whatever the cutoff.\nScores depend on your embedding model; with many models real matches sit close together (for example 0.60 to 0.70), so change the number in small steps of 0.01 to 0.05.\nOnce the cutoff is above 0, the status line under the chat box shows the best score of the last message, so you can see what to set. Start around 0.6." },
    { path: "knowledge.num_ctx", kind: "number", min: 512, max: 131072, step: 512, label: "Context size", desc: "Tokens the model may use (Ollama num_ctx). Passages need room, so this is larger than the Assistant's." },
    { path: "knowledge.gallery_ignore_words", kind: "text", label: "Gallery: words to ignore", desc: "Words the Gallery leaves out of its word charts (the word cloud, the words that go together and the phrases), for example your own name or a project's codename. Separate them with commas or spaces; capital letters do not matter. The charts follow the next time you open the Gallery.", placeholder: "buddy, projectname" },
    { path: "knowledge.instructions", kind: "textarea", full: true, defaultKey: "knowledge.default_instructions", label: "Your instructions", desc: "The system message for collection chats. Leave it empty to use the built-in text." },
  ] },
  { group: "Studio", id: "assistant", label: "Assistant", icon: ico(`<path d="M12 3l1.8 4.6L18.5 9l-4.7 1.4L12 15l-1.8-4.6L5.5 9l4.7-1.4z"/><path d="M18 15l.8 2 2 .8-2 .8-.8 2-.8-2-2-.8 2-.8z"/>`), rows: [
    { id: "model", kind: "model", paths: ["assistant.default.provider", "assistant.default.model"], label: "Default model", desc: "The model the Assistant panel starts with. The list shows the models of Ollama and of your other connections." },
    { path: "assistant.instructions", kind: "textarea", full: true, defaultKey: "assistant.default_instructions", label: "Your instructions", desc: "The system message: how the Assistant should talk to you and what it should know about how you work. Leave it empty to use the built-in text." },
    { path: "assistant.context_turns", kind: "number", min: 0, max: 50, step: 1, label: "Earlier exchanges sent", desc: "How many of the last exchanges go to the model with each message. 0 sends only the new message." },
    { path: "assistant.num_ctx", kind: "number", min: 512, max: 131072, step: 512, label: "Context size", desc: "Tokens the model may use (Ollama num_ctx). It also sets how much text one message may carry." },
    { path: "assistant.temperature", kind: "number", min: 0, max: 2, step: 0.1, label: "Temperature", desc: "Lower answers more steadily, higher more freely. Between 0 and 2." },
    { path: "assistant.history", kind: "bool", label: "Save conversations", desc: "Keep each prompt's conversation with the prompt. You can also switch it off for a single prompt in the Assistant panel." },
  ] },
];
const byId = (id) => SECTIONS.find((s) => s.id === id) || SECTIONS[0];
const rowKey = (r) => r.path || r.id;
const at = (o, dotted) => dotted.split(".").reduce((d, k) => (d == null ? d : d[k]), o);
const nest = (flat) => Object.entries(flat).reduce((out, [p, v]) => { p.split(".").reduce((d, k, i, a) => (d[k] = i === a.length - 1 ? v : d[k] || {}), out); return out; }, {});

const S = { data: null, section: "general", q: "", providers: null, prev: "#/dashboard", guard: null, mcp: { info: null, tokens: null, activity: null, client: "code", fresh: null, snip: "" } };

// Back returns to whatever page opened Settings.
addEventListener("hashchange", (e) => {
  const from = new URL(e.oldURL).hash || "#/dashboard";
  if (!from.startsWith("#/settings")) S.prev = from;
  if (!location.hash.startsWith("#/settings") && window.onbeforeunload === S.guard) window.onbeforeunload = S.guard = null;   // leaving: drop the unsaved-changes guard
  if (!location.hash.startsWith("#/settings/mcp")) S.mcp.fresh = null;   // a token just made lives in this page only, and is forgotten when you leave it
});

// The theme can also change from the top bar or the account menu: keep the segment on this page in step.
addEventListener("flowlystack-theme", () => {
  document.querySelectorAll("#set-theme button").forEach((b) => { const on = b.dataset.mode === mode(); b.classList.toggle("on", on); b.setAttribute("aria-pressed", on); });
});

registerCommands(() => [
  { label: `Switch to ${isDark() ? "day" : "night"} mode`, where: "Settings", keywords: "theme dark light appearance day night", icon: isDark() ? ICONS.theme : ICONS.moon, run: () => setMode(isDark() ? "light" : "dark") },
  { label: "Settings", where: "Account", keywords: "preferences options configure account", icon: ICONS.setup, run: () => { location.hash = "#/settings"; } },
  { label: "Studio Assistant settings", where: "Settings", keywords: "assistant model ollama instructions temperature history", icon: ICONS.setup, run: () => { location.hash = "#/settings/assistant"; } },
  { label: "Knowledge settings", where: "Settings", keywords: "knowledge embedding model collections index passages rag", icon: ICONS.setup, run: () => { location.hash = "#/settings/knowledge"; } },
  { label: "Keyboard shortcuts", where: "Settings", keywords: "hotkeys keys shortcut keyboard bindings", icon: ICONS.setup, run: () => { location.hash = "#/settings/keyboard"; } },
  { label: "MCP settings", where: "Settings", keywords: "mcp agent agents token tokens claude code desktop cursor connect tools model context protocol", icon: ICONS.setup, run: () => { location.hash = "#/settings/mcp"; } },
  { label: "Connection settings", where: "Settings", keywords: "ollama address url server connections lm studio llama.cpp vllm jan localai openai compatible endpoint hugging face runtime", icon: ICONS.setup, run: () => { location.hash = "#/settings/connections"; } },
]);

// ======================================================================= page
export async function showSettings() {
  const sec = (location.hash.replace(/^#\//, "").split("?")[0].split("/")[1] || "general");
  S.section = byId(decodeURIComponent(sec)).id;
  if (!page().querySelector(".set-shell")) buildShell();
  renderNav();
  try {
    S.data = await api("settings");
    S.auth = await api("auth/state").catch(() => null);
    S.about = await api("about").catch(() => null);
    S.twostep = S.auth?.enabled && S.auth.signed_in ? await api("auth/twostep").catch(() => null) : null;
  } catch {
    $("#set-pane").innerHTML = `<p>Could not load the settings.</p>`;
    return;
  }
  renderPane();
  if (S.section === "assistant" || S.section === "connections") loadProviders();
  if (S.section === "knowledge") loadSetup();
  if (S.section === "mcp") loadMcp();
}

function buildShell() {
  page().innerHTML = `
    <div class="set-shell">
      <aside class="set-nav" aria-label="Settings sections">
        <button type="button" class="btn btn-sm set-back" id="set-back">${CHEV_L}<span>Back</span></button>
        <nav class="set-sections" id="set-sections"></nav>
      </aside>
      <section class="set-pane" id="set-pane"></section>
    </div>`;
  S.q = "";
  wireOnce();
  $("#set-back").onclick = async () => { if (await discardOk()) location.hash = S.prev; };
  $("#set-sections").addEventListener("click", async (e) => {
    const a = e.target.closest("a[data-sec]"); if (!a) return;
    e.preventDefault();
    if (a.dataset.sec !== S.section && !await discardOk()) return;
    location.hash = "#/settings/" + a.dataset.sec;
  });
}

// ---- search: a section matches by its name or by any of its rows
const hit = (text) => !S.q || text.toLowerCase().includes(S.q);
const rowHit = (r) => hit(`${r.label} ${r.desc} ${r.tip || ""}`);
const secHit = (s) => hit(`${s.group} ${s.label}`) || s.rows.some(rowHit);

function renderNav() {
  const groups = [...new Set(SECTIONS.map((s) => s.group))];
  const html = groups.map((g) => {
    const items = SECTIONS.filter((s) => s.group === g && secHit(s));
    return items.length ? `<div class="set-group"><span class="set-grouplabel">${esc(g)}</span>${items.map((s) =>
      `<a class="set-navitem${s.id === S.section ? " on" : ""}" href="#/settings/${s.id}" data-sec="${s.id}"${s.id === S.section ? ` aria-current="page"` : ""}>${s.icon}<span>${esc(s.label)}</span></a>`).join("")}</div>` : "";
  }).join("");
  const nav = $("#set-sections");
  nav.innerHTML = html || `<p class="muted small set-none">No setting matches “${esc(S.q)}”.</p>`;
  const on = nav.querySelector(".set-navitem.on");   // on a phone the list scrolls sideways: bring the open section into view
  if (on) nav.scrollLeft = on.getBoundingClientRect().left - nav.getBoundingClientRect().left + nav.scrollLeft - 16;
}

// ======================================================================= one section
const loaded = () => S.data.sections;
const src = (path) => S.data.sources[path] || "default";
const locked = (r) => (r.paths || [r.path]).some((p) => src(p) === "env");

function control(r) {
  const id = "set-" + rowKey(r).replace(/\./g, "-");
  const off = locked(r) ? " disabled" : "";
  if (r.kind === "theme") return `<div class="seg" id="set-theme" role="group" aria-label="Theme">${[["system", "System"], ["light", "Day"], ["dark", "Night"]].map(([m, l]) =>
    `<button type="button" data-mode="${m}" class="${m === mode() ? "on" : ""}" aria-pressed="${m === mode()}">${l}</button>`).join("")}</div>`;
  if (r.kind === "text") return `<input class="pl-input" id="${id}" data-path="${r.path}" value="${esc(at(loaded(), r.path))}" placeholder="${esc(r.placeholder || "")}" spellcheck="false"${off}>`;
  if (r.kind === "number") return `<input class="pl-input" type="number" id="${id}" data-path="${r.path}" value="${esc(at(loaded(), r.path))}" min="${r.min}" max="${r.max}" step="${r.step}"${off}>`;
  if (r.kind === "bool") { const on = !!at(loaded(), r.path); return `<button type="button" class="set-switch" role="switch" id="${id}" data-path="${r.path}" aria-checked="${on}" aria-label="${esc(r.label)}"${off}></button>`; }
  if (r.kind === "textarea") { const v = at(loaded(), r.path); return `<textarea class="pl-input pl-area" id="${id}" data-path="${r.path}" rows="6" spellcheck="false" placeholder="${esc(S.data.readonly[r.defaultKey] || "The built-in instructions are used.")}"${off}>${esc(v)}</textarea>
    <div class="set-inline"><button type="button" class="btn btn-sm btn-glow" data-reset-text="${id}"${off}>Reset to default</button><span class="muted small">${v ? "" : "Using the built-in text."}</span></div>`; }
  if (r.kind === "hotkey") { const v = at(loaded(), r.path); return `<div class="set-hotkeyctl"><button type="button" class="set-hotkey" id="${id}" data-path="${r.path}" value="${esc(v)}" aria-label="${esc(r.label)} shortcut, press to change">${esc(keyLabel(v))}</button><button type="button" class="btn btn-sm btn-glow" data-hk-reset="${r.path}">Reset</button><span class="small set-bad" data-hk-msg role="status"></span></div>`; }
  if (r.kind === "note") return "";
  if (r.kind === "samples") return `<div id="set-samples"></div>`;
  if (r.kind === "aboutversion") return `<div class="set-inline"><b class="set-version">${esc(S.about?.version ? "v" + S.about.version : "unknown")}</b><a class="btn btn-sm btn-glow" href="#/whatsnew">What's new</a></div>`;
  if (r.kind === "profilepic" || r.kind === "profilename") {
    if (!S.auth?.enabled || !S.auth.signed_in) return `<p class="muted small">Login is turned off on this server (FLOWLYSTACK_AUTH=off), so there is no owner profile.</p>`;
    if (r.kind === "profilename") return `<div class="set-inline"><b class="pf-name">${esc(S.auth.username)}</b><button type="button" class="btn btn-sm btn-glow" data-name-change>Change name</button></div>`;
    const v = S.auth.avatar;
    return `<div class="set-inline"><span class="avatar av-lg${v ? " has-img" : ""}" aria-hidden="true">${v ? `<img src="/api/profile/avatar?v=${v}" alt="" draggable="false">` : `<span class="av-letter">${esc((S.auth.username.trim()[0] || "?").toUpperCase())}</span>`}</span><button type="button" class="btn btn-sm btn-glow" data-pf-choose>${v ? "Change picture" : "Choose picture"}</button>${v ? `<button type="button" class="btn btn-sm btn-glow btn-danger" data-pf-remove>Remove</button>` : ""}</div>`;
  }
  if (r.kind === "twostep") {
    if (!S.auth?.enabled || !S.auth.signed_in) return `<p class="muted small">Login is turned off on this server (FLOWLYSTACK_AUTH=off).</p>`;
    if (!S.twostep) return "";
    return S.twostep.enabled
      ? `<p class="small"><b>On.</b> <span class="muted">${S.twostep.backup_left} backup code${S.twostep.backup_left === 1 ? "" : "s"} left.</span></p><div class="set-inline"><button type="button" class="btn btn-sm btn-glow" data-ts-backup>New backup codes</button><button type="button" class="btn btn-sm btn-glow" data-ts-off>Turn off</button></div>`
      : `<p class="small muted">Off.</p><div class="set-inline"><button type="button" class="btn btn-sm btn-glow" data-ts-setup>Set up</button></div>`;
  }
  if (r.kind === "account" || r.kind === "signout") {
    if (!S.auth?.enabled || !S.auth.signed_in) return `<p class="muted small">Login is turned off on this server (FLOWLYSTACK_AUTH=off).</p>`;
    return r.kind === "account" ? `<div class="set-inline"><button type="button" class="btn btn-sm btn-glow" data-pw-change>Change password</button></div>`
                                : `<div class="set-inline"><button type="button" class="btn btn-sm btn-glow" data-signout>Sign out</button></div>`;
  }
  if (r.kind === "mcpswitch") return `<div class="set-inline set-inline-end"><span class="small muted" id="set-mcp-state">${mcpState()}</span><button type="button" class="set-switch" role="switch" id="set-mcp-switch" data-mcp-switch aria-checked="${!!loaded().mcp?.enabled}" aria-label="${esc(r.label)}"></button></div>`;
  if (r.kind === "mcphidden") return `<div class="set-inline set-inline-end"><span class="small muted" id="set-mcphidden-state">${loaded().mcp?.share_hidden ? "Shared with agents" : "Kept from agents"}</span><button type="button" class="set-switch" role="switch" id="set-mcphidden-switch" data-mcp-hidden aria-checked="${!!loaded().mcp?.share_hidden}" aria-label="${esc(r.label)}"></button></div>`;
  if (r.kind === "mcpendpoint") return `<div class="ts-key"><code id="set-mcp-url">${esc(mcpUrl())}</code><button type="button" class="btn btn-sm btn-glow" data-mcp-copy-url>${COPY_ICONS}<span>Copy</span></button></div>`;
  if (r.kind === "mcptokens") return `<div class="set-inline"><button type="button" class="btn btn-sm btn-glow" data-mcp-new>New token</button></div>`;
  if (r.kind === "mcpconnect") return `<div id="set-mcp-connect">${mcpConnect()}</div>`;
  if (r.kind === "mcpactivity") return `<div id="set-mcp-activity">${mcpActivity()}</div>`;
  if (r.kind === "check") return `<div class="set-inline"><button type="button" class="btn btn-sm btn-glow" id="set-check">Check connection</button><span class="small" id="set-check-msg" role="status"></span></div>`;
  if (r.kind === "runtimes") return `<div id="set-rt-ctl">${runtimesControl()}</div>`;
  if (r.kind === "embed") return `<div id="set-embed-ctl">${embedControl(r)}</div>`;
  if (r.kind === "model") return `<div id="set-model-ctl">${modelControl(r, null)}</div>`;
  return "";
}

// The default model: a list of what the provider has, or (when it cannot be reached) a box for the name.
function modelControl(r, keep) {
  const d = loaded().assistant.default, cur = keep ?? { provider: d.provider, name: d.model };
  const list = (S.providers || []).filter((p) => p.reachable);
  if (!list.length) return `<input class="pl-input" id="set-model-text" data-model-text data-provider="${esc(cur.provider)}" value="${esc(cur.name)}" spellcheck="false"${locked(r) ? " disabled" : ""}>
    <p class="muted small set-note">${S.providers ? "No connection can be reached, so type the model name." : "Looking for installed models…"}</p>`;
  const opts = list.flatMap((p) => p.models.map((m) => [p.id, m, p.label]));
  if (!opts.some(([p, m]) => p === cur.provider && m === cur.name)) opts.unshift([cur.provider, cur.name, "not installed"]);
  return `<select class="pl-input" id="set-model-sel" data-model-sel aria-label="Default model">${opts.map(([p, m, l]) =>
    `<option value="${esc(p + "::" + m)}"${p === cur.provider && m === cur.name ? " selected" : ""}>${esc(m)} · ${esc(l)}</option>`).join("")}</select>`;
}

// The embedding model: what Ollama has installed with "embed" in the name (or every model on request), whether Ollama is on this
// computer, and the command to get one. Facts come from /api/collections/setup.
function embedControl(r, keep) {
  const st = S.setup, cur = keep ?? at(loaded(), r.path), off = locked(r) ? " disabled" : "";
  if (!st) return `<p class="muted small set-note">Looking for installed models…</p>`;
  const reach = st.ollama?.reachable, where = st.ollama?.kind ? ` · ${st.ollama.kind === "local" ? "Local" : "Remote"} (${esc(st.ollama.host)})` : "";
  const names = [...(S.showAll ? st.all_models || [] : st.models)];
  if (cur && !names.includes(cur)) names.unshift(cur);
  const opts = [`<option value="">None chosen yet</option>`, ...names.map((m) => `<option value="${esc(m)}"${m === cur ? " selected" : ""}>${esc(m)}${st.models.includes(m) || S.showAll ? "" : " · not installed"}</option>`)].join("");
  const status = !reach ? `<p class="small set-bad set-note">${esc(st.ollama?.error || "Ollama can't be reached.")} Check the address in Connections.</p>`
    : !st.models.length && !S.showAll ? `<p class="muted small set-note">No embedding model is installed${where ? where.replace(" · ", " on ") : ""}. Get one with the command below, then press Refresh.</p>`
    : `<p class="muted small set-note">Ollama${where}</p>`;
  return `<select class="pl-input" id="set-embed-sel" data-path="${r.path}" aria-label="Embedding model"${off}>${opts}</select>
    <div class="set-inline"><button type="button" class="btn btn-sm btn-glow" data-embed-all aria-pressed="${!!S.showAll}">${S.showAll ? "Show embedding models only" : "Show all installed models"}</button><button type="button" class="btn btn-sm btn-glow" data-embed-refresh>Refresh</button></div>
    ${status}
    <div class="set-inline"><code class="small">${esc(st.pull_command)}</code><button type="button" class="btn btn-sm btn-glow" data-copy-pull="${esc(st.pull_command)}">${COPY_ICONS}<span>Copy</span></button></div>`;
}
// A changed model never rewrites the index silently (the server says needs_rebuild); ask before indexing everything again.
async function offerRebuild() {
  try {
    const st = await api("collections/index");
    if (!st.needs_rebuild) return;
    if (await confirmDialog({ title: "Index everything again?", message: `Your documents and prompts were indexed with another model. Index them again with ${st.model}? Going back to the old model later re-embeds nothing.`, confirmLabel: "Index again" })) {
      await send("POST", "collections/index/rebuild");
      toast({ message: "Indexing again with the new model." });
    } else toast({ message: "Search stays keyword-only until you index again." });
  } catch { /* the Collections page shows the state */ }
}
async function loadSetup() {
  try { S.setup = await api("collections/setup" + (S.showAll ? "?show_all=true" : "")); } catch { S.setup = { ollama: { reachable: false, error: "Could not reach the server." }, models: [], all_models: [], pull_command: "ollama pull embeddinggemma" }; }
  const ctl = $("#set-embed-ctl");
  if (ctl) ctl.innerHTML = embedControl(byId("knowledge").rows.find((x) => x.kind === "embed"), collect(byId("knowledge"))["knowledge.embedding_model"]);
}

const srcTag = (r) => { const s = (r.paths || [r.path]).map(src).find((x) => x === "env" || x === "config"); return s ? `<span class="set-tag" title="${s === "env" ? "Set by an environment variable; change it there." : "Set in flowlystack.config.json."}">${s === "env" ? "environment" : "config file"}</span>` : ""; };

// ---- shortcuts: press the button, then the keys you want. Esc or a click elsewhere cancels.
let rec = null;
function stopRec() {
  if (!rec) return;
  document.removeEventListener("keydown", rec.on, true);
  rec.btn.classList.remove("rec"); rec.btn.textContent = keyLabel(rec.btn.value);
  rec = null;
}
function hkProblem(combo, btn) {
  if (!combo) return `Press ${isMac ? "Cmd" : "Ctrl"} (and optionally Shift or Option/Alt) together with a letter, digit or Enter.`;
  if (S.data.readonly["hotkeys.reserved"].includes(combo)) return "The browser or text editing already uses that. Try another.";
  const other = [...$("#set-pane").querySelectorAll(".set-hotkey")].find((b) => b !== btn && b.value === combo);
  return other ? `Already used by ${S.data.readonly["hotkeys.labels"][other.dataset.path.split(".")[1]]}.` : "";
}
function startRec(btn) {
  stopRec();
  const msg = btn.parentElement.querySelector("[data-hk-msg]");
  msg.textContent = ""; btn.classList.add("rec"); btn.textContent = "Press the keys…";
  const on = (e) => {
    if (["Meta", "Control", "Shift", "Alt"].includes(e.key)) return;   // wait for the letter or digit
    e.preventDefault(); e.stopPropagation();
    if (e.key === "Escape") { stopRec(); return; }
    const combo = comboOf(e), bad = hkProblem(combo, btn);
    if (bad) { msg.textContent = bad; return; }   // keep listening
    btn.value = combo; stopRec(); refresh();
  };
  rec = { btn, on };
  document.addEventListener("keydown", on, true);
}
document.addEventListener("click", (e) => { if (rec && !e.target.closest(".set-hotkey")) stopRec(); });

function renderPane(keepScroll) {
  stopRec();
  const sec = byId(S.section), pane = $("#set-pane");
  const rows = sec.rows.filter((r) => !S.q || hit(sec.label) || rowHit(r));
  const y = keepScroll ? $("#panel").scrollTop : 0;
  pane.innerHTML = `
    <h2 class="set-title">${esc(sec.label)}</h2>
    <div class="set-rows">${rows.length ? rows.map((r, i) => `${r.group && r.group !== rows[i - 1]?.group ? `<h3 class="set-groupname">${esc(r.group)}</h3>` : ""}
      <div class="set-row${r.full ? " full" : ""}">
        <div class="set-rowtext"><label class="set-label${r.tip ? " set-tip" : ""}" for="set-${esc(rowKey(r).replace(/\./g, "-"))}"${r.tip ? ` data-tip="${esc(r.tip)}" tabindex="0"` : ""}>${esc(r.label)}</label>${srcTag(r)}<p class="set-desc muted">${esc(r.desc)}</p></div>
        <div class="set-control">${control(r)}</div>${r.kind === "runtimes" ? `<div class="set-rtlist" id="set-rt-list">${runtimesList()}</div>` : r.kind === "mcptokens" ? `<div class="set-rtlist" id="set-mcp-list">${mcpList()}</div>` : ""}
      </div>`).join("") : `<p class="muted">Nothing in this section matches “${esc(S.q)}”.</p>`}</div>
    ${sec.save === false ? "" : `<div class="set-save"><span class="set-status muted" id="set-status" role="status"></span><button type="button" class="btn btn-sm btn-glow btn-glow-md" id="set-save" disabled>Save</button></div>`}`;
  wirePane();
  if ($("#set-samples")) mountSamples($("#set-samples"));
  $("#panel").scrollTop = y;
}

// ---- reading the controls back
function collect(sec) {   // path -> value for every control that is on screen
  const out = {}, pane = $("#set-pane");
  pane.querySelectorAll("[data-path]").forEach((el) => {
    const p = el.dataset.path;
    out[p] = el.getAttribute("role") === "switch" ? el.getAttribute("aria-checked") === "true" : el.type === "number" ? (el.value.trim() === "" ? null : Number(el.value)) : el.value;
  });
  const sel = pane.querySelector("[data-model-sel]"), txt = pane.querySelector("[data-model-text]");
  if (sel) { const [p, m] = sel.value.split("::"); out["assistant.default.provider"] = p; out["assistant.default.model"] = m; }
  if (txt) { out["assistant.default.provider"] = txt.dataset.provider; out["assistant.default.model"] = txt.value.trim(); }
  return out;
}
const savedValue = (p) => at(loaded(), p);
function changes(sec) {
  const now = collect(sec);
  return Object.fromEntries(Object.entries(now).filter(([p, v]) => v !== savedValue(p)));
}
const dirty = () => { const sec = byId(S.section); return sec.save !== false && !!$("#set-pane") && S.data && Object.keys(changes(sec)).length > 0; };
async function discardOk() {
  if (!dirty()) return true;
  return confirmDialog({ title: "Unsaved changes", message: "Discard your unsaved changes?", confirmLabel: "Discard", danger: true });
}

function wirePane() { refresh(); }

// One set of listeners for the pane (it is redrawn often, the element itself stays).
function wireOnce() {
  const pane = $("#set-pane");
  pane.addEventListener("input", refresh);
  pane.addEventListener("change", refresh);
  pane.addEventListener("click", (e) => {
    const t = e.target;
    const m = t.closest("#set-theme [data-mode]");
    if (m) { setMode(m.dataset.mode); return; }   // the segment follows through the theme event below
    const hk = t.closest(".set-hotkey");
    if (hk) { rec?.btn === hk ? stopRec() : startRec(hk); return; }
    const reset = t.closest("[data-hk-reset]");
    if (reset) {
      const btn = reset.parentElement.querySelector(".set-hotkey"), msg = reset.parentElement.querySelector("[data-hk-msg]"), def = S.data.defaults.hotkeys[reset.dataset.hkReset.split(".")[1]];
      stopRec();
      msg.textContent = hkProblem(def, btn);
      if (!msg.textContent) { btn.value = def; btn.textContent = keyLabel(def); refresh(); }
      return;
    }
    if (t.closest("[data-mcp-switch]")) { mcpToggle(); return; }
    if (t.closest("[data-mcp-hidden]")) { mcpHiddenToggle(); return; }
    const mc = t.closest("[data-mcp-copy-url]");
    if (mc) { copy(mc, mcpUrl()); return; }
    const mcs = t.closest("[data-mcp-copy-snip]");
    if (mcs) { copy(mcs, S.mcp.snip); return; }
    const mcl = t.closest("[data-mcp-client]");
    if (mcl) { S.mcp.client = mcl.dataset.mcpClient; redrawMcp(); return; }
    const mnew = t.closest("[data-mcp-new]");
    if (mnew) { mcpNew(mnew); return; }
    const msc = t.closest("[data-mcp-scope]");
    if (msc) { mcpScope(msc.closest("[data-mcp-token]").dataset.mcpToken); return; }
    const mun = t.closest("[data-mcp-undo]");
    if (mun) { mcpUndo(mun.closest("[data-mcp-act]").dataset.mcpAct); return; }
    if (t.closest("[data-mcp-act-refresh]")) { mcpRefreshActivity(); return; }
    const mdl = t.closest("[data-mcp-act-del]");
    if (mdl) { mcpActDelete(mdl.closest("[data-mcp-act]").dataset.mcpAct); return; }
    if (t.closest("[data-mcp-act-clear]")) { mcpActClear(); return; }
    const mrg = t.closest("[data-mcp-regen]");
    if (mrg) { mcpRegen(mrg.closest("[data-mcp-token]").dataset.mcpToken); return; }
    const mrn = t.closest("[data-mcp-rename]");
    if (mrn) { mcpRename(mrn.closest("[data-mcp-token]").dataset.mcpToken); return; }
    const mrv = t.closest("[data-mcp-revoke]");
    if (mrv) { mcpRevoke(mrv.closest("[data-mcp-token]").dataset.mcpToken); return; }
    const sw = t.closest(".set-switch");
    if (sw && !sw.disabled) { sw.setAttribute("aria-checked", sw.getAttribute("aria-checked") !== "true"); refresh(); return; }
    if (t.closest("[data-embed-all]")) { S.showAll = !S.showAll; loadSetup(); return; }
    if (t.closest("[data-embed-refresh]")) { loadSetup(); return; }
    const cp = t.closest("[data-copy-pull]");
    if (cp) { copy(cp, cp.dataset.copyPull); return; }
    const rs = t.closest("[data-reset-text]");
    if (rs) { const ta = document.getElementById(rs.dataset.resetText); ta.value = ""; ta.focus(); refresh(); return; }
    if (t.closest("[data-pw-change]")) { changePassword(); return; }
    if (t.closest("[data-name-change]")) { changeName(); return; }
    if (t.closest("[data-pf-choose]")) { pickPicture(); return; }
    if (t.closest("[data-pf-remove]")) { removePicture(); return; }
    if (t.closest("[data-ts-setup]")) { tsSetup(); return; }
    if (t.closest("[data-ts-backup]")) { tsManage("backup"); return; }
    if (t.closest("[data-ts-off]")) { tsManage("off"); return; }
    if (t.closest("[data-signout]")) { signOut(); return; }
    if (t.closest("[data-rt-add]")) { rtSave(null); return; }
    const card = t.closest("[data-rt]");
    if (card && t.closest("[data-rt-check]")) { rtCheck(card.dataset.rt); return; }
    if (card && t.closest("[data-rt-edit]")) { rtSave(card.dataset.rt); return; }
    if (card && t.closest("[data-rt-del]")) { rtRemove(card.dataset.rt); return; }
    if (t.closest("#set-check")) { check(); return; }
    if (t.closest("#set-save")) save(byId(S.section));
  });
}

function refresh() {
  const save = $("#set-save"); if (!save) return;
  const n = Object.keys(changes(byId(S.section))).length;
  save.disabled = !n;
  $("#set-status").textContent = n ? `${n} unsaved change${n === 1 ? "" : "s"}` : "";
  window.onbeforeunload = S.guard = n ? () => "" : null;
}

async function save(sec) {
  const ch = changes(sec), btn = $("#set-save"), status = $("#set-status");
  if (!Object.keys(ch).length) return;
  for (const p of ["assistant.instructions", "knowledge.instructions"]) if (p in ch && !ch[p].trim()) ch[p] = null;   // empty means "use the built-in text"
  btn.disabled = true; status.textContent = "Saving…";
  try {
    await send("PUT", "settings/" + (sec.backend || sec.id), nest(Object.fromEntries(Object.entries(ch).map(([p, v]) => [p.split(".").slice(1).join("."), v]))));
    S.data = await api("settings");
    window.onbeforeunload = S.guard = null;
    if (sec.backend === "hotkeys") loadHotkeys();
    renderPane(true);
    toast({ message: "Settings saved." });
    if (sec.id === "connections") { await loadProviders(); check(); }
    else if (sec.id === "assistant") loadProviders();
    else if (sec.id === "knowledge") { loadSetup(); if ("knowledge.embedding_model" in ch) await offerRebuild(); }
  } catch (e) {
    status.textContent = `Could not save: ${e.message}`;
    btn.disabled = false;
  }
}

// ---- account: change the password (the server checks the old one, keeps this session and signs the others out)
function pwDialog(error) {
  return formDialog({
    title: "Change password", confirmLabel: "Change password",
    html: `<label class="pl-label" for="pw-old">Current password</label>${pwInput("pw-old", "current-password")}
      <label class="pl-label" for="pw-new">New password</label>${pwInput("pw-new", "new-password")}
      <p class="muted small set-note">At least 8 characters.</p>
      <label class="pl-label" for="pw-new2">Repeat new password</label>${pwInput("pw-new2", "new-password")}`,
    validate: (d) => !d.querySelector("#pw-old").value ? "Type your current password."
      : d.querySelector("#pw-new").value.length < 8 ? "The new password must be at least 8 characters."
      : d.querySelector("#pw-new").value !== d.querySelector("#pw-new2").value ? "The two new passwords differ." : "",
    read: (d) => ({ old: d.querySelector("#pw-old").value, new: d.querySelector("#pw-new").value }),
    onOpen: (d) => {
      d.querySelectorAll(".pw-eye").forEach((b) => b.addEventListener("click", () => {   // show or hide what was typed (same as the login page)
        const i = d.querySelector("#" + b.dataset.for), show = i.type === "password";
        i.type = show ? "text" : "password";
        b.innerHTML = show ? EYE_OFF : EYE;
        b.setAttribute("aria-label", show ? "Hide password" : "Show password");
        i.focus();
      }));
      if (error) { const e = d.querySelector(".cb-form-err"); e.hidden = false; e.textContent = error; }
    },
  });
}
const EYE = ico(`<path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12z"/><circle cx="12" cy="12" r="2.8"/>`);
const EYE_OFF = ico(`<path d="M3 3l18 18M10.6 6a9 9 0 0 1 1.4-.1c6 0 9.5 6.1 9.5 6.1a16 16 0 0 1-3 3.7M6.4 7.5A16 16 0 0 0 2.5 12S6 18.5 12 18.5c1.5 0 2.8-.4 4-.9M9.9 9.9a3 3 0 0 0 4.2 4.2"/>`);
const pwInput = (id, auto) => `<div class="pw-wrap"><input class="pl-input" id="${id}" type="password" autocomplete="${auto}" maxlength="256"><button type="button" class="pw-eye" data-for="${id}" aria-label="Show password">${EYE}</button></div>`;
async function changePassword() {
  let error = "";
  for (;;) {
    const r = await pwDialog(error);
    if (!r) return;
    try {
      await send("POST", "auth/password", r);
      toast({ message: "Password changed. Other browsers are signed out." });
      return;
    } catch (e) { error = e.message; }   // the server's reason, for example a wrong current password
  }
}

// ---- profile: the picture is cropped and re-encoded to a 256px PNG here (the server accepts nothing else); the name is the login name, so the server asks for the password
const PF_PX = 256;
async function pngFrom(file) {
  let bmp;
  try { bmp = await createImageBitmap(file); } catch { throw new Error("The browser could not read that file as a picture."); }
  const side = Math.min(bmp.width, bmp.height), c = document.createElement("canvas");
  c.width = c.height = PF_PX;
  c.getContext("2d").drawImage(bmp, (bmp.width - side) / 2, (bmp.height - side) / 2, side, side, 0, 0, PF_PX, PF_PX);   // from the middle
  bmp.close?.();
  const blob = await new Promise((ok) => c.toBlob(ok, "image/png"));
  if (!blob) throw new Error("Could not prepare the picture.");
  return blob;
}
async function profileChanged(message) {
  S.auth = await api("auth/state").catch(() => S.auth);
  renderPane(true);
  dispatchEvent(new Event("flowlystack-profile"));   // account.js repaints the sidebar button and the menu
  toast({ message });
}
function pickPicture() {
  const i = document.createElement("input");
  i.type = "file"; i.accept = "image/png,image/jpeg,image/webp";
  i.addEventListener("change", async () => {
    const f = i.files[0];
    if (!f) return;
    try {
      if (f.size > 20e6) throw new Error("That file is too large. Pick a picture under 20 MB.");
      const blob = await pngFrom(f), url = URL.createObjectURL(blob);
      const ok = await formDialog({ title: "Profile picture", confirmLabel: "Use this picture", read: () => true,
        html: `<div class="pf-prevwrap"><img class="pf-prev" src="${url}" alt="Preview of your profile picture"></div><p class="muted small set-note">Cropped to a square from the middle. It stays on this computer.</p>` });
      URL.revokeObjectURL(url);
      if (!ok) return;
      await api("profile/avatar", { method: "PUT", headers: { "content-type": "image/png" }, body: blob });
      await profileChanged("Profile picture changed.");
    } catch (e) { toast({ message: e.message }); }
  });
  i.click();
}
async function removePicture() {
  try { await api("profile/avatar", { method: "DELETE" }); await profileChanged("Profile picture removed."); }
  catch (e) { toast({ message: e.message }); }
}
function nameDialog(error, keep) {
  return formDialog({
    title: "Change name", confirmLabel: "Change name",
    html: `<label class="pl-label" for="nm-new">New name</label><input class="pl-input" id="nm-new" autocomplete="username" maxlength="64" spellcheck="false" value="${esc(keep ?? S.auth.username)}">
      <p class="muted small set-note">3 to 64 characters: letters, digits and . _ @ + - only. It is also the name you log in with.</p>
      <label class="pl-label" for="nm-pw">Current password</label>${pwInput("nm-pw", "current-password")}`,
    validate: (d) => !/^[A-Za-z0-9][A-Za-z0-9._@+-]{2,63}$/.test(d.querySelector("#nm-new").value.trim()) ? "3 to 64 characters: letters, digits and . _ @ + - only, starting with a letter or digit."
      : !d.querySelector("#nm-pw").value ? "Type your current password." : "",
    read: (d) => ({ new: d.querySelector("#nm-new").value.trim(), password: d.querySelector("#nm-pw").value }),
    onOpen: (d) => { wireEyes(d); showErr(d, error); d.querySelector("#nm-new").select(); },
  });
}
async function changeName() {
  let error = "", keep;
  for (;;) {
    const r = await nameDialog(error, keep);
    if (!r || r.new === S.auth.username) return;
    keep = r.new;   // a retry (wrong password) keeps what was typed
    try { await send("POST", "auth/username", r); await profileChanged("Name changed. You log in with the new name now."); return; }
    catch (e) { error = e.message; }   // the server's reason, for example a wrong password
  }
}

// ---- two-step login: set up with a QR code, backup codes, turn off (the server checks every password and code)
const loadQR = () => window.qrcode ? Promise.resolve() : new Promise((ok, bad) => {   // the vendored QR library loads only when the dialog opens
  const el = document.createElement("script");
  el.src = "vendor/qrcode.js"; el.onload = ok; el.onerror = () => bad(new Error("Could not load the QR code library."));
  document.head.append(el);
});
const showErr = (d, msg) => { if (!msg) return; const e = d.querySelector(".cb-form-err"); e.hidden = false; e.textContent = msg; };
function wireEyes(d) {
  d.querySelectorAll(".pw-eye").forEach((b) => b.addEventListener("click", () => {
    const i = d.querySelector("#" + b.dataset.for), show = i.type === "password";
    i.type = show ? "text" : "password"; b.innerHTML = show ? EYE_OFF : EYE;
    b.setAttribute("aria-label", show ? "Hide password" : "Show password"); i.focus();
  }));
}
const tsRefresh = async () => { S.twostep = await api("auth/twostep").catch(() => S.twostep); renderPane(true); };

// the password, and (when `withCode`) a current code or a backup code
function tsAskDialog({ title, confirmLabel, withCode, intro, error }) {
  return formDialog({
    title, confirmLabel,
    html: `${intro ? `<p class="muted small set-note">${esc(intro)}</p>` : ""}
      <label class="pl-label" for="ts-pw">Password</label>${pwInput("ts-pw", "current-password")}
      ${withCode ? `<label class="pl-label" for="ts-code">6-digit code or a backup code</label><input class="pl-input" id="ts-code" autocomplete="one-time-code" spellcheck="false" maxlength="32">` : ""}`,
    validate: (d) => !d.querySelector("#ts-pw").value ? "Type your password." : withCode && !d.querySelector("#ts-code").value.trim() ? "Type a code." : "",
    read: (d) => ({ password: d.querySelector("#ts-pw").value, ...(withCode ? { code: d.querySelector("#ts-code").value.trim() } : {}) }),
    onOpen: (d) => { wireEyes(d); showErr(d, error); },
  });
}

// the QR code, the setup key as text, and the first code
function tsScanDialog(start, svg, error) {
  const key = start.secret.match(/.{1,4}/g).join(" ");
  return formDialog({
    title: "Set up two-step login", confirmLabel: "Turn on",
    html: `<p class="muted small set-note">1. Scan this QR code with your authenticator app.</p>
      <div class="ts-qr">${svg || `<p class="small">The QR code could not be drawn. Use the setup key below.</p>`}</div>
      <p class="muted small set-note">Cannot scan? In the app choose to enter a setup key, and type this (time-based, 6 digits):</p>
      <div class="ts-key"><code>${esc(key)}</code><button type="button" class="btn btn-sm btn-glow btn-glow-md" data-ts-copy>${COPY_ICONS}<span>Copy</span></button></div>
      <label class="pl-label" for="ts-code">2. Type the 6-digit code the app shows</label>
      <input class="pl-input" id="ts-code" inputmode="numeric" autocomplete="one-time-code" spellcheck="false" maxlength="12">`,
    validate: (d) => d.querySelector("#ts-code").value.trim().length < 6 ? "Type the 6-digit code from the app." : "",
    read: (d) => ({ code: d.querySelector("#ts-code").value.trim() }),
    onOpen: (d) => { d.querySelector("[data-ts-copy]").addEventListener("click", (e) => copy(e.currentTarget, start.secret)); showErr(d, error); },
  });
}

// the backup codes: shown once, and the dialog cannot be dismissed by accident (Esc and a click outside do nothing)
function tsCodesDialog(codes, user) {
  const text = `FlowlyStack backup codes${user ? ` for ${user}` : ""}\nEach code works once. Keep them somewhere safe.\n\n${codes.join("\n")}\n`;
  return formDialog({
    title: "Your backup codes", confirmLabel: "I saved them", cancelLabel: null,
    extra: `<button type="button" class="btn btn-sm btn-glow btn-glow-md" data-ts-copyall>${COPY_ICONS}<span>Copy</span></button><button type="button" class="btn btn-sm btn-glow btn-glow-md" data-ts-download>Download</button>`,
    html: `<p class="muted small set-note">If you lose your phone, each of these codes lets you log in once instead of the 6-digit code. They are shown only now: save them before you continue.</p>
      <ul class="ts-codes">${codes.map((c) => `<li><code>${esc(c)}</code></li>`).join("")}</ul>`,
    read: () => true,
    onOpen: (d) => {
      d.addEventListener("cancel", (e) => e.preventDefault());
      d.addEventListener("click", (e) => { if (e.target === d) e.stopImmediatePropagation(); }, true);
      d.querySelector("[data-ts-copyall]").addEventListener("click", (e) => copy(e.currentTarget, text));
      d.querySelector("[data-ts-download]").addEventListener("click", () => {
        const a = document.createElement("a");
        a.href = URL.createObjectURL(new Blob([text], { type: "text/plain" }));
        a.download = "flowlystack-backup-codes.txt";
        a.click();
        setTimeout(() => URL.revokeObjectURL(a.href), 1000);
      });
    },
  });
}

async function tsSetup() {
  let error = "", start;
  for (;;) {   // the password first, so a stolen open window cannot switch it on quietly
    const r = await tsAskDialog({ title: "Set up two-step login", confirmLabel: "Continue", withCode: false, intro: "Type your password to continue.", error });
    if (!r) return;
    try { start = await send("POST", "auth/twostep/start", { password: r.password }); break; } catch (e) { error = e.message; }
  }
  let svg = "";
  try {
    await loadQR();
    const q = window.qrcode(0, "M");
    q.addData(start.uri); q.make();
    svg = q.createSvgTag({ cellSize: 4, margin: 4, scalable: true, alt: "QR code to scan with your authenticator app" });
  } catch (e) { /* the setup key is shown as text instead */ }
  error = "";
  for (;;) {
    const r = await tsScanDialog(start, svg, error);
    if (!r) return;   // closed: nothing is on yet
    try {
      const out = await send("POST", "auth/twostep/confirm", { code: r.code });
      await tsCodesDialog(out.backup_codes, S.auth?.username);
      toast({ message: "Two-step login is on. Other browsers are signed out." });
      break;
    } catch (e) {
      if (e.status === 410) { toast({ message: e.message }); return; }   // setup took too long: start again
      error = e.message;
    }
  }
  await tsRefresh();
}

async function tsManage(kind) {
  const off = kind === "off";
  let error = "";
  for (;;) {
    const r = await tsAskDialog({ title: off ? "Turn off two-step login" : "New backup codes", confirmLabel: off ? "Turn off" : "Make new codes", withCode: true, error,
      intro: off ? "This asks for your password and a current code. Other browsers are signed out." : "The old backup codes stop working. This asks for your password and a current code; other browsers are signed out." });
    if (!r) return;
    try {
      if (off) { await send("POST", "auth/twostep/disable", r); toast({ message: "Two-step login is off." }); }
      else { const out = await send("POST", "auth/twostep/backup", r); await tsCodesDialog(out.backup_codes, S.auth?.username); }
      break;
    } catch (e) { error = e.message; }
  }
  await tsRefresh();
}

// ---- other runtimes: a list of connections, each added, edited and removed at once (not part of the page's Save)
const PRESETS = [
  { kind: "lmstudio", label: "LM Studio", name: "LM Studio", url: "http://127.0.0.1:1234/v1", hint: "Start the local server in LM Studio first. It lists the models you downloaded." },
  { kind: "llamacpp", label: "llama.cpp", name: "llama.cpp", url: "http://127.0.0.1:8080/v1", hint: "Start llama-server first. It serves the model it was started with." },
  { kind: "vllm", label: "vLLM", name: "vLLM", url: "http://127.0.0.1:8000/v1", hint: "Start vllm serve first. Add the key if you started it with one." },
  { kind: "jan", label: "Jan", name: "Jan", url: "http://127.0.0.1:1337/v1", hint: "Turn on Jan's local API server first." },
  { kind: "localai", label: "LocalAI", name: "LocalAI", url: "http://127.0.0.1:8080/v1", hint: "Start LocalAI first." },
  { kind: "custom", label: "Your own OpenAI-compatible endpoint", name: "", url: "", hint: "Any server that answers /models and /chat/completions: one you host, or a service such as OpenAI, Hugging Face or OpenRouter. Type the address the way the provider gives it (it usually ends in /v1), and the key if it needs one." },
];
const preset = (kind) => PRESETS.find((x) => x.kind === kind) || PRESETS[PRESETS.length - 1];
const isLoopback = (u) => { try { const h = new URL(u).hostname; return h === "localhost" || h === "127.0.0.1" || h === "[::1]" || h.endsWith(".localhost"); } catch { return true; } };
S.rt = {};   // id -> {ok, text} from the last Check

function rtStatus(r) {
  const m = S.rt[r.id]; if (m) return m;
  const p = (S.providers || []).find((x) => x.id === r.id);
  if (!S.providers) return { ok: null, text: "Looking…" };
  if (!p) return { ok: null, text: "" };
  return p.reachable ? { ok: true, text: `Connected · ${p.models.length} model${p.models.length === 1 ? "" : "s"}` } : { ok: false, text: p.error || "Could not connect." };
}
function runtimesControl() {
  return `<button type="button" class="btn btn-sm btn-glow" data-rt-add>Add connection</button>`;   // opens a dialog (a centred dialog never runs off the screen like a drop-down can)
}
function runtimesList() {
  const list = S.data.runtimes || [];
  const cards = list.map((r) => {
    const p = (S.providers || []).find((x) => x.id === r.id), remote = p ? p.kind === "remote" : !isLoopback(r.url), st = rtStatus(r);
    return `<li class="set-conn" data-rt="${esc(r.id)}">
      <div class="set-connhead"><strong class="set-connname">${esc(r.name)}</strong><span class="set-tag">${esc(preset(r.kind).label.replace("Your own OpenAI-compatible endpoint", "Own endpoint"))}</span><span class="set-tag">${remote ? "Remote" : "Local"}</span>${r.key?.set ? `<span class="set-tag">Key set</span>` : ""}</div>
      <code class="set-connurl">${esc(r.url)}</code>
      <p class="small set-connstatus${st.ok === true ? " set-ok" : st.ok === false ? " set-bad" : " muted"}" role="status">${esc(st.text)}</p>
      <div class="set-inline set-connbtns"><button type="button" class="btn btn-sm btn-glow" data-rt-check>Check</button><button type="button" class="btn btn-sm btn-glow" data-rt-edit>Edit</button><button type="button" class="btn btn-sm btn-glow" data-rt-del>Remove</button></div>
    </li>`;
  }).join("");
  return list.length ? `<ul class="set-conns">${cards}</ul>` : "";
}
function redrawRuntimes() { const l = $("#set-rt-list"); if (l) l.innerHTML = runtimesList(); }

// One dialog for Add and Edit. `v` = {kind, name, url, hasKey, error, pick}. Add (`pick`) starts with a Runtime list that fills in the
// name and address; changing it only overwrites a field the user has not changed. Returns {kind, name, url, key, removeKey} or null.
function rtDialog(title, v) {
  const pr = preset(v.kind);
  return formDialog({
    title, confirmLabel: "Save",
    html: `${v.pick ? `<label class="pl-label" for="rt-kind">Runtime</label><select class="pl-input" id="rt-kind">${PRESETS.map((x) => `<option value="${x.kind}"${x.kind === v.kind ? " selected" : ""}>${esc(x.label)}</option>`).join("")}</select>` : ""}
      <p class="muted small set-note" id="rt-hint">${esc(pr.hint)}</p>
      <label class="pl-label" for="rt-name">Name</label><input class="pl-input" id="rt-name" value="${esc(v.name)}" maxlength="60" placeholder="For example Hugging Face" autocomplete="off" spellcheck="false">
      <label class="pl-label" for="rt-url">Address</label><input class="pl-input" id="rt-url" value="${esc(v.url)}" placeholder="http://127.0.0.1:1234/v1" autocomplete="off" spellcheck="false">
      <label class="pl-label" for="rt-key">Key (optional)</label><input class="pl-input" id="rt-key" type="password" autocomplete="new-password" spellcheck="false" placeholder="${v.hasKey ? "A key is set. Type a new one to replace it." : "Leave empty if the server needs none"}">
      ${v.hasKey ? `<label class="small set-rtremove"><input type="checkbox" id="rt-nokey"> Remove the saved key</label>` : ""}
      <p class="small set-bad" id="rt-warn" hidden>This address is not on this computer and starts with http://, so the key would travel unencrypted. Use https:// if the server offers it.</p>`,
    validate: (d) => (!d.querySelector("#rt-name").value.trim() ? "Give the connection a name." : !d.querySelector("#rt-url").value.trim() ? "Type the address." : ""),
    read: (d) => ({ kind: d.querySelector("#rt-kind")?.value || v.kind, name: d.querySelector("#rt-name").value.trim(), url: d.querySelector("#rt-url").value.trim(), key: d.querySelector("#rt-key").value.trim(), removeKey: !!d.querySelector("#rt-nokey")?.checked }),
    onOpen: (d) => {
      const warn = () => { const u = d.querySelector("#rt-url").value.trim(), withKey = d.querySelector("#rt-key").value.trim() || (v.hasKey && !d.querySelector("#rt-nokey")?.checked); d.querySelector("#rt-warn").hidden = !(withKey && /^http:\/\//i.test(u) && !isLoopback(u)); };
      d.addEventListener("input", warn); d.addEventListener("change", warn); warn();
      let prev = pr;
      d.querySelector("#rt-kind")?.addEventListener("change", (e) => {
        const next = preset(e.target.value), name = d.querySelector("#rt-name"), url = d.querySelector("#rt-url");
        if (!name.value.trim() || name.value === prev.name) name.value = next.name;
        if (!url.value.trim() || url.value === prev.url) url.value = next.url;
        d.querySelector("#rt-hint").textContent = next.hint; prev = next; warn();
      });
      if (v.error) { const err = d.querySelector(".cb-form-err"); err.hidden = false; err.textContent = v.error; }
    },
  });
}

async function rtSave(id) {   // id null = add
  const cur = id ? S.data.runtimes.find((r) => r.id === id) : null, first = PRESETS[0];
  let v = cur ? { kind: cur.kind, name: cur.name, url: cur.url, hasKey: !!cur.key?.set, error: "", pick: false }
              : { kind: first.kind, name: first.name, url: first.url, hasKey: false, error: "", pick: true };
  for (;;) {
    const r = await rtDialog(id ? `Edit ${cur.name}` : "Add connection", v);
    if (!r) return;
    try {
      let saved;
      if (id) saved = await send("PUT", "settings/runtimes/" + id, { name: r.name, url: r.url, ...(r.key ? { key: r.key } : r.removeKey ? { key: null } : {}) });
      else saved = await send("POST", "settings/runtimes", { kind: r.kind, name: r.name, url: r.url, ...(r.key ? { key: r.key } : {}) });
      S.data = await api("settings");
      delete S.rt[saved.id];
      redrawRuntimes();
      toast({ message: id ? "Connection saved." : "Connection added." });
      await loadProviders();
      return;
    } catch (e) {
      v = { ...v, kind: r.kind, name: r.name, url: r.url, error: e.message };   // show the server's reason and let the user fix it
    }
  }
}
async function rtCheck(id) {
  S.rt[id] = { ok: null, text: "Checking…" }; redrawRuntimes();
  await loadProviders();
  delete S.rt[id]; redrawRuntimes();
}
async function rtRemove(id) {
  const r = S.data.runtimes.find((x) => x.id === id); if (!r) return;
  const isDefault = loaded().assistant.default.provider === id;
  if (!await confirmDialog({ title: `Remove ${r.name}?`, message: `Its saved key is deleted too.${isDefault ? " The Assistant's default model uses this connection, so the default goes back to the built-in one (Ollama)." : ""} Conversations that used it stay as they are.`, confirmLabel: "Remove", danger: true })) return;
  try {
    await send("DELETE", "settings/runtimes/" + id);
    S.data = await api("settings");
    redrawRuntimes();
    toast({ message: "Connection removed." });
    await loadProviders();
    if (isDefault) renderPane(true);
  } catch (e) { toast({ message: `Could not remove: ${e.message}` }); }
}

// ---- MCP: the switch, the address, the tokens and a copy-ready setup per client. Tokens are made and revoked at once (not the page's Save).
const mcpUrl = () => location.origin + "/mcp";
const mcpOn = () => !!loaded().mcp?.enabled;
function mcpState() {
  const t = S.mcp.info?.tools, n = t ? t.read + t.write : 0;
  const w = (S.mcp.tokens || []).some((x) => x.scope === "write");
  return mcpOn() ? `On${n ? ` · ${t.read} read tool${t.read === 1 ? "" : "s"}${t.write ? ` + ${t.write} write${w ? "" : " (no token may write yet)"}` : ""}` : ""}` : "Off";
}
async function loadMcp() {
  try {
    S.mcp.info = await api("mcp/info");
    S.mcp.tokens = (await api("auth/mcp-tokens")).tokens;
    S.mcp.activity = (await api("mcp/activity")).items;
  } catch (e) {
    S.mcp.tokens = S.mcp.tokens || [];
    toast({ message: `Could not load the MCP settings: ${e.message}` });
  }
  redrawMcp();
}
function redrawMcp() {
  if (S.section !== "mcp") return;
  const st = $("#set-mcp-state"), list = $("#set-mcp-list"), conn = $("#set-mcp-connect"), act = $("#set-mcp-activity");
  if (st) st.textContent = mcpState();
  if (act) act.innerHTML = mcpActivity();
  if (list) list.innerHTML = mcpList();
  if (conn) conn.innerHTML = mcpConnect();
}
function mcpList() {
  const ts = S.mcp.tokens;
  if (!ts) return `<p class="muted small set-note">Looking…</p>`;
  if (!ts.length) return `<p class="muted small set-note">No tokens yet. Press New token. Make one for each app you connect, so you can cut one off without touching the others.</p>`;
  return `<ul class="set-conns">${ts.map((t) => `<li class="set-conn" data-mcp-token="${esc(t.id)}">
      <div class="set-connhead"><strong class="set-connname">${esc(t.name)}</strong><span class="set-tag">${t.scope === "write" ? "Read and write" : "Read only"}</span></div>
      <code class="set-connurl">fls_…${esc(t.tail)}</code>
      <p class="small muted set-connstatus">Made ${esc(relTime(t.created))} · ${t.last_used ? `last used ${esc(relTime(t.last_used))}` : "never used"}</p>
      <div class="set-inline set-connbtns"><button type="button" class="btn btn-sm btn-glow" data-mcp-scope>${t.scope === "write" ? "Make read-only" : "Allow writing"}</button><button type="button" class="btn btn-sm btn-glow" data-mcp-rename>Rename</button><button type="button" class="btn btn-sm btn-glow" data-mcp-regen>Regen</button><button type="button" class="btn btn-sm btn-glow" data-mcp-revoke>Revoke</button></div>
    </li>`).join("")}</ul>`;
}

function mcpSnippet(client) {
  const url = mcpUrl(), tok = S.mcp.fresh?.token || "YOUR_TOKEN", i = S.mcp.info || {};
  if (client === "code") return `claude mcp add --scope user --transport http flowlystack ${url} --header "Authorization: Bearer ${tok}"`;
  if (client === "desktop") return JSON.stringify({ mcpServers: { flowlystack: { command: i.python || "python3", args: [i.bridge || "backend/mcp_stdio.py"], env: { FLOWLYSTACK_MCP_URL: url, FLOWLYSTACK_MCP_TOKEN: tok } } } }, null, 2);
  return JSON.stringify({ mcpServers: { flowlystack: { type: "http", url, headers: { Authorization: `Bearer ${tok}` } } } }, null, 2);
}
const MCP_CLIENTS = [["code", "Claude Code"], ["desktop", "Claude Desktop"], ["other", "Other apps"]];
function mcpConnect() {
  const c = S.mcp.client, snip = mcpSnippet(c), i = S.mcp.info;
  S.mcp.snip = snip;
  const plain = location.protocol === "http:" && !isLoopback(location.href);
  const notes = {
    code: `For <b>Claude Code</b> in a terminal <b>and the Code tab of the Claude desktop app</b> (they share one setup). Run this in a terminal, then start a <b>new</b> session and type <code>/context</code> to see the flowlystack tools (in a terminal <code>/mcp</code> works too). <code>--scope user</code> makes it available in every project. After Regen, or if it says the server already exists, run <code>claude mcp remove flowlystack -s user</code> first, then this command again.`,
    desktop: `Adds a <b>flowlystack</b> switch to the <b>Connectors</b> list of the Claude desktop app (<b>+ &gt; Connectors</b>), so you can turn FlowlyStack on or off there. The Code tab already works without it through Claude Code above; use this one when you want the switch. The app cannot take an address, so it starts a small bridge program instead. <b>Quit the app completely (Cmd+Q) before you edit its config file</b>: the app rewrites that file when it closes and would delete your entry. Add the <code>flowlystack</code> entry inside <code>"mcpServers"</code> (keep any servers already there, with a comma between them), save, then open the app again. The file is <code>~/Library/Application Support/Claude/claude_desktop_config.json</code> on a Mac (put the path in quotes in a terminal: it has a space) and <code>%APPDATA%\\Claude\\claude_desktop_config.json</code> on Windows. Not <code>Connectors → Add custom connector</code>: that one only takes a public https address. Confirmed on a Mac; the app changes often.`,
    other: `For apps that take an address (Cursor, Windsurf, Cline and others). They all need the address and an <code>Authorization: Bearer</code> header; the field names differ a little. VS Code keeps the same entry under <code>"servers"</code> instead of <code>"mcpServers"</code>, and Windsurf calls the address <code>serverUrl</code>.`,
  };
  return `<div class="seg" role="group" aria-label="Client">${MCP_CLIENTS.map(([k, l]) => `<button type="button" data-mcp-client="${k}" class="${k === c ? "on" : ""}" aria-pressed="${k === c}">${l}</button>`).join("")}</div>
    <p class="small muted set-note">${notes[c]}</p>
    ${c === "desktop" && i && !i.local ? `<p class="small set-bad set-note">You opened FlowlyStack from another computer. The paths below are on the computer that runs FlowlyStack, and Claude Desktop runs the bridge on its own computer. Copy <code>backend/mcp_stdio.py</code> there and change the two paths, or use Claude Code or another app that takes an address.</p>` : ""}
    ${plain ? `<p class="small set-bad set-note">This address is not encrypted. Before a token crosses a network, open FlowlyStack through your HTTPS proxy and copy the setup from there.</p>` : ""}
    ${!mcpOn() ? `<p class="small set-bad set-note">MCP is switched off above, so a client cannot connect yet.</p>` : ""}
    ${S.mcp.fresh ? `<p class="small set-ok set-note">This text contains the token “${esc(S.mcp.fresh.name)}” you just made. It is forgotten when you leave this page.</p>` : ""}
    <div class="mcp-snipbar"><button type="button" class="btn btn-sm btn-glow" data-mcp-copy-snip>${COPY_ICONS}<span>Copy</span></button></div>
    <pre class="mcp-snip" tabindex="0"><code>${esc(snip)}</code></pre>`;
}

async function mcpToggle() {
  const sw = $("#set-mcp-switch"), on = sw.getAttribute("aria-checked") !== "true";
  sw.disabled = true;
  try {
    await send("PUT", "settings/mcp", { enabled: on });
    S.data = await api("settings");
    toast({ message: on ? (S.mcp.tokens?.length ? "MCP is on." : "MCP is on. Make a token next.") : "MCP is off. Agents are turned away." });
  } catch (e) { toast({ message: `Could not change it: ${e.message}` }); }
  sw.disabled = false;
  sw.setAttribute("aria-checked", mcpOn());
  redrawMcp();
}

async function mcpHiddenToggle() {
  const sw = $("#set-mcphidden-switch"), on = sw.getAttribute("aria-checked") !== "true";
  sw.disabled = true;
  try {
    await send("PUT", "settings/mcp", { share_hidden: on });
    S.data = await api("settings");
    toast({ message: on ? "Agents can now read hidden Lattice runs." : "Hidden Lattice runs are kept from agents." });
  } catch (e) { toast({ message: `Could not change it: ${e.message}` }); }
  sw.disabled = false;
  const now = !!loaded().mcp?.share_hidden;
  sw.setAttribute("aria-checked", now);
  const st = $("#set-mcphidden-state"); if (st) st.textContent = now ? "Shared with agents" : "Kept from agents";
}

// shown once; Esc and a click outside do nothing, like the backup codes
function mcpTokenDialog(made, title) {
  return formDialog({
    title, confirmLabel: "I saved it", cancelLabel: null,
    html: `<p class="muted small set-note">This is the only time the token is shown. Copy it into the app that needs it now (or use the setup text that stays on this page until you leave it).</p>
      <div class="ts-key"><code>${esc(made.token)}</code><button type="button" class="btn btn-sm btn-glow" data-mcp-copy-tok>${COPY_ICONS}<span>Copy</span></button></div>
      <p class="small muted set-note">${esc(made.name)} · ${made.scope === "write" ? "read and write" : "read only"}</p>`,
    read: () => true,
    onOpen: (d) => {
      d.addEventListener("cancel", (e) => e.preventDefault());
      d.addEventListener("click", (e) => { if (e.target === d) e.stopImmediatePropagation(); }, true);
      d.querySelector("[data-mcp-copy-tok]").addEventListener("click", (e) => copy(e.currentTarget, made.token));
    },
  });
}
// one click: the server makes the token (named Token 1, Token 2 ... until you rename it) and it is shown once
async function showMade(made, title) {
  S.mcp.fresh = { token: made.token, name: made.name, id: made.id };
  S.mcp.tokens = (await api("auth/mcp-tokens")).tokens;
  redrawMcp();
  await mcpTokenDialog(made, title);
  toast({ message: "The setup text below now contains the token." });
}
async function mcpNew(btn) {
  btn.disabled = true;
  try { await showMade(await send("POST", "auth/mcp-tokens", {}), "Your new token"); }
  catch (e) { toast({ message: `Could not make a token: ${e.message}` }); }
  btn.disabled = false;
}
async function mcpRegen(id) {
  const t = (S.mcp.tokens || []).find((x) => x.id === id); if (!t) return;
  if (!await confirmDialog({ title: `Regenerate ${t.name}?`, message: "The current token stops working at once. You get a new one to put into the app that uses it. The name stays.", confirmLabel: "Regenerate" })) return;
  try { await showMade(await send("POST", `auth/mcp-tokens/${id}/regen`), `${t.name}: new token`); }
  catch (e) { toast({ message: `Could not regenerate: ${e.message}` }); }
}
async function mcpRename(id) {
  const t = (S.mcp.tokens || []).find((x) => x.id === id); if (!t) return;
  let error = "";
  for (;;) {
    const r = await formDialog({
      title: "Rename token", confirmLabel: "Save",
      html: `<label class="pl-label" for="mcp-name">Name</label><input class="pl-input" id="mcp-name" value="${esc(error ? "" : t.name)}" maxlength="60" placeholder="For example Claude Desktop" autocomplete="off" spellcheck="false">
        <p class="muted small set-note">The app or computer it is for, so you can tell tokens apart. The token itself does not change.</p>`,
      validate: (d) => (d.querySelector("#mcp-name").value.trim() ? "" : "Give the token a name."),
      read: (d) => d.querySelector("#mcp-name").value.trim(),
      onOpen: (d) => { showErr(d, error); d.querySelector("#mcp-name").select(); },   // the old name is selected: typing replaces it
    });
    if (!r) return;
    try {
      await send("PATCH", `auth/mcp-tokens/${id}`, { name: r });
      S.mcp.tokens = (await api("auth/mcp-tokens")).tokens;
      if (S.mcp.fresh?.id === id) S.mcp.fresh.name = r;
      redrawMcp();
      return;
    } catch (e) { error = e.message; }
  }
}
function mcpActivity() {
  const items = S.mcp.activity;
  const head = `<div class="set-inline"><button type="button" class="btn btn-sm btn-glow" data-mcp-act-refresh>Refresh</button>${items && items.length ? `<button type="button" class="btn btn-sm btn-glow" data-mcp-act-clear>Delete all</button>` : ""}</div>`;
  if (!items) return `<p class="muted small set-note">Looking…</p>`;
  if (!items.length) return `${head}<p class="muted small set-note">Nothing yet. When an agent with a write token saves something, it appears here with an Undo.</p>`;
  return `${head}<ul class="set-conns">${items.map((a) => `<li class="set-conn" data-mcp-act="${esc(a.id)}">
      <div class="set-connhead"><strong class="set-connname">${esc(a.what)} “${esc(a.title || "Untitled")}”</strong>${a.undone ? `<span class="set-tag">Undone</span>` : ""}</div>
      <p class="small muted set-connstatus">${esc(relTime(a.time))} · token ${esc(a.token)}${a.note ? ` · ${esc(a.note)}` : ""}</p>
      <div class="set-inline set-connbtns">${a.undone ? "" : `<a class="btn btn-sm btn-glow" href="${esc(a.open)}">Open</a><button type="button" class="btn btn-sm btn-glow" data-mcp-undo>Undo</button>`}<button type="button" class="btn btn-sm btn-glow" data-mcp-act-del>Delete</button></div>
    </li>`).join("")}</ul>`;
}
async function mcpRefreshActivity() {
  try { S.mcp.activity = (await api("mcp/activity")).items; } catch (e) { toast({ message: `Could not load the activity: ${e.message}` }); }
  redrawMcp();
}
/** Delete removes lines from this list only; the prompts and projects stay. The server returns the removed entries so the toast Undo can put them back. */
async function mcpActRemoved(r, message) {
  await mcpRefreshActivity();
  toast({ message, action: "Undo", onAction: async () => {
    try { await send("POST", "mcp/activity/restore", { removed: r.removed }); } catch (e) { toast({ message: `Could not restore: ${e.message}` }); }
    await mcpRefreshActivity();
  } });
}
async function mcpActDelete(id) {
  try { await mcpActRemoved(await send("DELETE", `mcp/activity/${id}`), "Removed from the list. The prompt or project stays."); }
  catch (e) { toast({ message: e.message }); await mcpRefreshActivity(); }
}
async function mcpActClear() {
  const n = (S.mcp.activity || []).length; if (!n) return;
  if (!await confirmDialog({ title: "Delete all agent activity?", message: `This clears the list of ${n} ${n === 1 ? "entry" : "entries"} and their Undo buttons. The prompts and projects agents made are not touched (find them in Studio, Linkshell or the Trash). You can undo this right after.`, confirmLabel: "Delete all" })) return;
  try { await mcpActRemoved(await send("DELETE", "mcp/activity"), `Cleared ${n} ${n === 1 ? "entry" : "entries"}. The prompts and projects stay.`); }
  catch (e) { toast({ message: e.message }); await mcpRefreshActivity(); }
}
async function mcpUndo(id) {
  try {
    const r = await send("POST", `mcp/activity/${id}/undo`);
    toast({ message: r.note });
  } catch (e) { toast({ message: e.message }); }
  await mcpRefreshActivity();
}
async function mcpScope(id) {
  const t = (S.mcp.tokens || []).find((x) => x.id === id); if (!t) return;
  const to = t.scope === "write" ? "read" : "write";
  if (to === "write" && !await confirmDialog({ title: `Allow ${t.name} to write?`, message: "An agent that uses this token will be able to save new prompts, new versions of your Studio prompts, new Linkshell projects, and entities and links in your Lattice (each link must quote the item it comes from). It can never delete anything, and everything it makes is listed under Recent agent activity with an Undo.", confirmLabel: "Allow writing" })) return;
  try {
    await send("PATCH", `auth/mcp-tokens/${id}`, { scope: to });
    S.mcp.tokens = (await api("auth/mcp-tokens")).tokens;
    redrawMcp();
    toast({ message: to === "write" ? "This token can now save things." : "This token is read-only again." });
  } catch (e) { toast({ message: `Could not change it: ${e.message}` }); }
}
async function mcpRevoke(id) {
  const t = (S.mcp.tokens || []).find((x) => x.id === id); if (!t) return;
  if (!await confirmDialog({ title: `Revoke ${t.name}?`, message: "The app using this token stops working at once. You can make a new token any time.", confirmLabel: "Revoke", danger: true })) return;
  try {
    await send("DELETE", "auth/mcp-tokens/" + id);
    if (S.mcp.fresh?.id === id) S.mcp.fresh = null;
    S.mcp.tokens = (await api("auth/mcp-tokens")).tokens;
    redrawMcp();
    toast({ message: "Token revoked." });
  } catch (e) { toast({ message: `Could not revoke: ${e.message}` }); }
}

// ---- Ollama: which models exist, and whether the saved address answers
async function loadProviders() {
  try { S.providers = (await api("assistant/providers")).providers; } catch { S.providers = []; }
  redrawRuntimes();
  const ctl = $("#set-model-ctl");
  if (ctl) {   // refill the model control in place, keeping what is picked so far
    const r = byId("assistant").rows.find((x) => x.kind === "model"), c = collect(byId("assistant"));
    ctl.innerHTML = modelControl(r, { provider: c["assistant.default.provider"], name: c["assistant.default.model"] });
  }
}

async function check() {
  const msg = $("#set-check-msg"); if (!msg) return;
  msg.className = "small"; msg.textContent = "Checking…";
  try { S.providers = (await api("assistant/providers")).providers; } catch { S.providers = []; }
  const p = S.providers.find((x) => x.id === "ollama");
  if (p?.reachable) { msg.className = "small set-ok"; msg.textContent = `Connected to Ollama ${p.version} · ${p.models.length} model${p.models.length === 1 ? "" : "s"}`; }
  else { msg.className = "small set-bad"; msg.textContent = p?.error || "Could not check the connection."; }
}

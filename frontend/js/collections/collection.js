// One collection (#/collections/<id>/documents): the top bar with Back, the name, a short meta line, the tabs and the settings gear, then the
// tab's panel (Chat or Documents). A new, empty collection opens on Documents; one with documents, and My prompts, opens on Chat.
import { formDialog } from "../dialog.js";
import { toast } from "../toast.js";
import { ICONS } from "../palette.js";
import { matches, hotkey, label as keyLabel } from "../hotkeys.js";
import { api, esc, ic, I, json, plural, splitTags, removeCollection } from "./common.js";
import { mountDocuments, unmountDocuments } from "./documents.js";
import { mountChat, unmountChat, resetChat, toggleSources } from "./chat.js";

const $ = (s) => document.querySelector(s);
const S = { id: "", c: null, box: null, ticket: 0, tab: "" };

export const currentId = () => S.id;
export function hideCollection() { unmountDocuments(); unmountChat(); S.id = ""; S.c = null; S.ticket++; }

const metaOf = (c) => c.builtin ? `Library + Studio · ${plural(c.prompts, "prompt")} · ${c.status === "ready" ? "ready" : c.status === "waiting_model" ? "waiting for a model" : c.status === "keyword" ? "keyword search" : c.status}`
  : `${plural(c.documents, "document")} · ${plural(c.passages, "passage")} · ${({ ready: "ready", preparing: "preparing", waiting_model: "waiting for a model", empty: "no documents yet", failed: "failed" })[c.status] || c.status}`;

export async function showCollection(box, id, tab) {
  S.box = box;
  const my = ++S.ticket;
  if (S.id !== id || !box.firstElementChild) {
    S.id = id; S.c = null; unmountDocuments(); unmountChat();
    box.innerHTML = `<p class="muted pr-empty">Loading…</p>`;
  }
  let c;
  try { c = await api("collections/" + encodeURIComponent(id)); }
  catch { if (my === S.ticket) { S.id = ""; history.replaceState(null, "", "#/collections"); toast({ message: "That collection no longer exists.", ms: 3000 }); location.hash = "#/collections"; } return; }
  if (my !== S.ticket) return;
  S.c = c;
  S.tab = tab === "chat" || tab === "documents" ? tab : c.builtin || c.documents > 0 ? "chat" : "documents";
  if (tab !== S.tab) history.replaceState(null, "", `#/collections/${encodeURIComponent(id)}/${S.tab}`);
  draw();
}

function draw() {
  const c = S.c, box = S.box;
  document.getElementById("panel").scrollTo(0, 0);
  box.innerHTML = `
    <header class="co-top">
      <div class="co-toprow">
        <a class="btn btn-sm btn-glow btn-glow-md set-back" href="#/collections" id="co-back" aria-label="Back to collections">${ic(I.back)}<span>Back</span></a>
        <div class="co-crumb"><span class="muted">collections /</span><h1 class="co-name" id="co-name">${esc(c.name)}</h1></div>
        ${S.tab === "chat" ? `<button type="button" class="btn btn-sm btn-glow btn-glow-md co-srcbtn" id="co-srcbtn" aria-pressed="false" aria-label="Show or hide Sources" title="Sources (${esc(keyLabel(hotkey("cosources")))})">${ic(`<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M15 4v16"/>`, 18)}<span class="co-srccount" hidden></span></button>` : ""}
        ${c.builtin ? "" : `<button type="button" class="btn btn-sm btn-glow btn-glow-md btn-glow-icon" id="co-gear" aria-label="Collection settings" title="Collection settings">${ICONS.setup}</button>`}
      </div>
      <div class="co-subbar">
        <div class="co-tabs" role="tablist" aria-label="Collection">
          ${["chat", "documents"].map((t) => `<a class="co-tab${t === S.tab ? " on" : ""}" role="tab" aria-selected="${t === S.tab}" href="#/collections/${encodeURIComponent(c.id)}/${t}">${t === "chat" ? "Chat" : "Documents"}</a>`).join("")}
        </div>
        <span class="pr-meta co-meta" id="co-meta">${esc(metaOf(c))}</span>
      </div>
    </header>
    <section class="co-panel" id="co-panel" role="tabpanel" aria-label="${S.tab === "chat" ? "Chat" : "Documents"}"></section>`;
  $("#co-gear")?.addEventListener("click", settings);
  $("#co-srcbtn")?.addEventListener("click", toggleSources);
  const top = $(".co-top"), setTop = () => box.style.setProperty("--co-top-h", `${top.offsetHeight}px`);   // the sticky columns sit under this header
  setTop(); new ResizeObserver(setTop).observe(top);
  unmountDocuments(); unmountChat();
  if (S.tab === "chat") mountChat($("#co-panel"), c);
  else mountDocuments($("#co-panel"), c, (fresh) => { S.c = fresh; $("#co-meta") && ($("#co-meta").textContent = metaOf(fresh)); });
}

async function settings() {
  const c = S.c;
  let del = false;
  const v = await formDialog({
    title: "Collection settings", confirmLabel: "Save",
    html: `<label class="pl-label" for="co-sname">Name</label><input class="pl-input" id="co-sname" autocomplete="off" value="${esc(c.name)}">
      <label class="pl-label" for="co-sdesc">Description</label><input class="pl-input" id="co-sdesc" autocomplete="off" value="${esc(c.description)}">
      <label class="pl-label" for="co-stags">Tags (separated by commas)</label><input class="pl-input" id="co-stags" autocomplete="off" value="${esc((c.tags || []).join(", "))}">`,
    extra: `<button type="button" class="btn btn-sm btn-glow btn-glow-md btn-danger" data-del>${ic(I.trash)}<span>Delete</span></button>`,
    onOpen: (dlg) => dlg.querySelector("[data-del]").addEventListener("click", () => { del = true; dlg.close(); }),
    validate: (d) => (d.querySelector("#co-sname").value.trim() ? "" : "Give the collection a name."),
    read: (d) => ({ name: d.querySelector("#co-sname").value.trim(), description: d.querySelector("#co-sdesc").value.trim(), tags: splitTags(d.querySelector("#co-stags").value) }),
  });
  if (del) { removeCollection(c, () => { location.hash = "#/collections"; }, () => dispatchEvent(new HashChangeEvent("hashchange"))); return; }
  if (!v) return;
  try {
    S.c = { ...c, ...(await api("collections/" + c.id, json("PATCH", v))) };
    $("#co-name").textContent = S.c.name;
    toast({ message: "Saved.", ms: 2500 });
  } catch (e) { toast({ message: "Could not save: " + e.message, ms: 4000 }); }
}

// ⌘K entries and the Documents key (rebindable, Settings > Keyboard > Collections).
export const collectionCommands = () => (S.id ? [
  { label: "New chat", where: "Collection", keywords: "conversation ask question start fresh", icon: ICONS.plus, run: () => { resetChat(S.id); if (!location.hash.includes("/chat")) location.hash = `#/collections/${S.id}/chat`; } },
  { label: "Open Documents", where: "Collection", keywords: "files upload add documents tab", icon: ICONS.find, run: () => { location.hash = `#/collections/${S.id}/documents`; } }] : []);
addEventListener("keydown", (e) => {
  if (!S.id || e.defaultPrevented || document.querySelector("dialog[open]") || !matches(e, "codocs")) return;
  e.preventDefault();
  if (!location.hash.includes("/documents")) location.hash = `#/collections/${S.id}/documents`;
});

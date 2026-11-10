// Linkshell project-level dialogs: Project settings (name, default agent, properties), the Studio picker (From Studio), and Copy.
// All of them are plain dialogs from dialog.js; nothing here talks to a model.
import { api } from "../api.js";
import { formDialog } from "../dialog.js";
import { toast } from "../toast.js";
import { esc, send, copy, TRASH } from "../editor.js";

export const AGENTS = ["claude", "codex", "ollama"];
const RESERVED = ["title", "tags", "status"];   // the server adds these to every export (same list as Studio's Properties)
const KNOWN_KEYS = ["purpose", "stack", "audience", "repo", "owner", "target"];   // suggestions in the name box; any name is allowed
const pid = (k) => k.trim().toLowerCase().replace(/[\s-]+/g, "_");   // same rule as backend `property_id`

const PLUS = `<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M12 5v14M5 12h14"/></svg>`;
const row = (p = { key: "", value: "" }) => `<div class="st-prop"><input class="pl-input st-prop-key" list="lkps-keys" value="${esc(p.key)}" placeholder="Name" aria-label="Property name" autocomplete="off" spellcheck="false"><textarea class="pl-input pl-area st-prop-val" rows="1" placeholder="Empty" aria-label="Property value" spellcheck="false">${esc(p.value)}</textarea><button type="button" class="icon-btn st-prop-del" aria-label="Remove this property" title="Remove">${TRASH}</button></div>`;
const rowsOf = (dlg) => [...dlg.querySelectorAll(".st-prop")].map((r) => ({ key: r.querySelector(".st-prop-key").value.trim(), value: r.querySelector(".st-prop-val").value }));

/** Project settings: name, default agent and the project's properties (the user's own name and value pairs, like a Studio prompt's Properties).
 *  Every property is added to the header of an export. Saves with PATCH; resolves with the updated project, or null when cancelled. */
export async function projectSettings(p) {
  const props = p.properties || [];
  const v = await formDialog({ title: "Project settings", wide: true, confirmLabel: "Save",
    html: `<label class="pl-label" for="lkps-name">Name</label><input class="pl-input" id="lkps-name" value="${esc(p.name)}" autocomplete="off">
      <label class="pl-label lkps-gap" for="lkps-agent">Default agent</label>
      <select class="pl-input" id="lkps-agent">${[...new Set([p.default_agent || "claude", ...AGENTS])].map((a) => `<option${a === (p.default_agent || "claude") ? " selected" : ""}>${esc(a)}</option>`).join("")}</select>
      <span class="pl-label lkps-gap">Properties</span>
      <p class="muted small st-prop-intro lkps-intro">Your own notes about this project, as name and value pairs. Each one is added to the header of an export (Markdown and JSON).</p>
      <div class="st-props" id="lkps-props">${props.map(row).join("")}</div>
      <button type="button" class="btn btn-sm btn-glow st-prop-add" id="lkps-add">${PLUS}<span>Add property</span></button>
      <datalist id="lkps-keys">${KNOWN_KEYS.map((k) => `<option value="${k}">`).join("")}</datalist>`,
    onOpen: (dlg) => {
      const box = dlg.querySelector("#lkps-props");
      if (!props.length) box.insertAdjacentHTML("beforeend", row());
      dlg.querySelector("#lkps-add").addEventListener("click", () => { box.insertAdjacentHTML("beforeend", row()); box.lastElementChild.querySelector(".st-prop-key").focus(); });
      box.addEventListener("click", (e) => { if (e.target.closest(".st-prop-del")) e.target.closest(".st-prop").remove(); });
      box.addEventListener("keydown", (e) => { if (e.key === "Enter" && e.target.matches(".st-prop-key")) { e.preventDefault(); e.target.nextElementSibling.focus(); } });
    },
    validate: (dlg) => {
      if (!dlg.querySelector("#lkps-name").value.trim()) return "A project needs a name.";
      const seen = new Set();
      for (const r of rowsOf(dlg)) {
        if (!r.key && !r.value) continue;   // an empty row is just dropped
        if (!r.key) return "Give each property a name.";
        const id = pid(r.key);
        if (RESERVED.includes(id)) return `“${r.key}” is already in every export: title, tags and status are added for you.`;
        if (seen.has(id)) return `“${r.key}” appears twice.`;
        seen.add(id);
      }
      return "";
    },
    read: (dlg) => ({ name: dlg.querySelector("#lkps-name").value.trim(), default_agent: dlg.querySelector("#lkps-agent").value, properties: rowsOf(dlg).filter((r) => r.key) }) });
  if (!v) return null;
  try { return await send("PATCH", `linkshell/${p.id}`, v); } catch (e) { toast({ message: "Could not save the settings: " + e.message }); return null; }
}

/** From Studio: pick one of the user's Studio prompts. Resolves with `{id, title, text}` or null. */
export async function pickStudio() {
  let pick = null;
  await formDialog({ title: "From Studio", wide: true, confirmLabel: "Close", cancelLabel: null,
    html: `<input class="pl-input" id="lkst-q" placeholder="Search your Studio prompts" autocomplete="off" aria-label="Search Studio prompts"><div class="lkst-list" id="lkst-list" role="listbox" aria-label="Studio prompts"><p class="muted small">Loading…</p></div>`,
    onOpen: (dlg) => {
      const list = dlg.querySelector("#lkst-list"), q = dlg.querySelector("#lkst-q");
      let n = 0;
      const load = async () => {
        const me = ++n;
        try {
          const r = await api("studio?page_size=40&sort=updated&q=" + encodeURIComponent(q.value));
          if (me !== n) return;
          list.innerHTML = r.items.length ? r.items.map((i) => `<button type="button" class="lkst-item" data-id="${esc(i.id)}"><strong>${esc(i.title)}</strong><span class="muted small">${esc(i.status || "")}${i.tags?.length ? " · " + esc(i.tags.join(", ")) : ""}</span></button>`).join("") : `<p class="muted small">${q.value ? "No Studio prompt matches." : "Your Studio is empty."}</p>`;
        } catch { if (me === n) list.innerHTML = `<p class="muted small">Could not load Studio prompts.</p>`; }
      };
      let t = 0;
      q.addEventListener("input", () => { clearTimeout(t); t = setTimeout(load, 150); });
      q.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); list.querySelector(".lkst-item")?.click(); } });
      list.addEventListener("click", async (e) => {
        const b = e.target.closest(".lkst-item"); if (!b) return;
        try { const d = await api("studio/" + encodeURIComponent(b.dataset.id)); pick = { id: d.id, title: d.title, text: d.text }; dlg.close(); }
        catch { toast({ message: "Could not load that prompt." }); }
      });
      load(); q.focus();
    } });
  return pick;
}

/** Copy a Prompt block: the server assembles the text (switched-on context attached) and it is pasted as written; a {{name}} stays as text. */
export async function copyBlock(btn, pid, bid) {
  let r;
  try { r = await api(`linkshell/${pid}/blocks/${bid}/copy`); } catch (e) { toast({ message: "Could not build the prompt: " + e.message }); return false; }
  await copy(btn, r.text);
  return true;
}

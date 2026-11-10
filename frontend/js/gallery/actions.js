// What the user can do with the prompts behind a chart: Open, Tag, Promote. Each action says what it will do first and
// nothing happens without a button press. Nothing here sends text to a model. Tag changes the Library prompt's own tags (what the Library editor does);
// Promote saves a COPY in Prompt Studio and never changes the Library prompt (what "Save as reusable prompt" on the Library page does).
import { api } from "../api.js";
import { confirmDialog, formDialog } from "../dialog.js";
import { toast } from "../toast.js";
import { data } from "./state.js";
import { esc, fmtDay } from "./common.js";

export const hooks = { refresh() {} };   // set by home.js: ask the server for a fresh snapshot after something was saved
const send = (method, path, body) => api(path, { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
const row = (id) => data().R.find((r) => r.id === id);
const splitTags = (t) => [...new Set(String(t).split(",").map((x) => x.trim()).filter(Boolean))];

export const openPrompt = (id) => { location.hash = "#/prompts/" + encodeURIComponent(id); };

export async function tagPrompt(id) {
  const r = row(id);
  if (!r) return;
  const v = await formDialog({
    title: "Tags", confirmLabel: "Save tags",
    html: `<p class="muted small">${esc(r.title || r.s)}</p>
      <label class="pl-label" for="gal-tags">Tags (separated by commas; remove one to take it off this prompt)</label>
      <input class="pl-input" id="gal-tags" autocomplete="off" value="${esc(r.tags.join(", "))}" placeholder="reference, writing">`,
    onOpen: (d) => { const i = d.querySelector("#gal-tags"); i.focus(); i.setSelectionRange(i.value.length, i.value.length); },
    read: (d) => splitTags(d.querySelector("#gal-tags").value),
  });
  if (!v) return;
  try { await send("PATCH", "prompts/" + encodeURIComponent(id), { tags: v }); } catch (e) { return toast({ message: "Could not save the tags: " + e.message, ms: 5000 }); }
  toast({ message: v.length ? `Tags saved: ${v.join(", ")}.` : "Tags removed.", ms: 3500 });
  hooks.refresh();
}

/** Copy a Library prompt to Prompt Studio. `extra` is {title, tags} for the copy. Asks first; says so when a copy already exists. */
async function copyToStudio(id, extra = {}) {
  try {
    const have = await api("studio?page_size=1&derived_from=" + encodeURIComponent(id));
    const ok = have.matched
      ? await confirmDialog({ title: "Already in Prompt Studio", message: `This prompt was already saved there as “${have.items[0].title}”. Save another copy?`, confirmLabel: "Save another copy" })
      : await confirmDialog({ title: "Save as reusable prompt", message: "A copy of this prompt is saved in Prompt Studio, with a link back. The Library prompt does not change.", confirmLabel: "Save copy" });
    if (!ok) return;
    const made = await send("POST", "studio", { from_library: id, ...extra });
    toast({ message: "Saved to Prompt Studio.", action: "Open in Studio", ms: 10000, onAction: () => { location.hash = "#/studio/" + encodeURIComponent(made.id); } });
    hooks.refresh();
  } catch (e) { toast({ message: "Could not save to Prompt Studio: " + e.message, ms: 5000 }); }
}
export const promotePrompt = (id) => copyToStudio(id);

/** One template from a group of near-identical prompts: the user picks which one to copy (the newest is chosen) and names it; it gets the tag "template". */
export async function promoteGroup(gi) {
  const { snap, R } = data(), g = snap.repeats[gi];
  if (!g) return;
  const members = g.ids.map((i) => R[i]).sort((a, b) => b.t - a.t);
  const v = await formDialog({
    title: "Promote as template", confirmLabel: "Continue", wide: true,
    html: `<p class="muted small">${g.n} prompts say nearly the same thing. Pick the one to keep as your template; the others stay in the Library.</p>
      <label class="pl-label" for="gal-tp-pick">Prompt to copy</label>
      <select class="pl-input" id="gal-tp-pick">${members.map((m) => `<option value="${esc(m.id)}">${esc(fmtDay(new Date(m.t)))} · ${esc(m.s.slice(0, 80))}</option>`).join("")}</select>
      <label class="pl-label" for="gal-tp-title">Name (optional)</label>
      <input class="pl-input" id="gal-tp-title" autocomplete="off" placeholder="Image caption prompt">
      <p class="muted small">A copy is saved in Prompt Studio with the tag “template”. The Library prompt does not change.</p>`,
    read: (d) => ({ id: d.querySelector("#gal-tp-pick").value, title: d.querySelector("#gal-tp-title").value.trim() }),
  });
  if (!v) return;
  await copyToStudio(v.id, { ...(v.title ? { title: v.title } : {}), tags: ["template"] });
}

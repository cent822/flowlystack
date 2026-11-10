// First-run sample content (routes in backend/samples_api.py). Three places use it: a dismissible card at the top
// of the Dashboard (only when the app is empty and nothing was chosen yet), a row under Settings > General, and two command-palette actions.
// Samples are added only when the user presses a button AFTER a dialog has said what will be created; nothing here calls a model.
import { api } from "./api.js";
import { confirmDialog } from "./dialog.js";
import { toast } from "./toast.js";
import { registerCommands } from "./palette.js";
import { esc } from "./editor.js";

let S = null;   // the last status from the server, or null when it could not be read (not signed in yet, server restarting)

const plural = (n, one, many) => `${n} ${n === 1 ? one : many || one + "s"}`;
const list = (w) => `${plural(w.studio, "Studio prompt")}, ${plural(w.linkshell, "Linkshell project")} and ${plural(w.collections, "collection")} with ${plural(w.documents, "short document")}`;
const hasSamples = () => !!S && (S.present.studio + S.present.linkshell + S.present.collections > 0);

async function refresh() {
  try { S = await api("samples"); } catch (e) { S = null; }
  draw();
  return S;
}

function draw() {
  drawOffer();
  const row = document.getElementById("set-samples");
  if (row) drawRow(row);
}

// ---- the actions (each asks first) ----
export async function addSamples() {
  const w = S?.will_add || { studio: 4, linkshell: 1, collections: 1, documents: 3 };
  const ok = await confirmDialog({
    title: "Add sample content?",
    message: `This adds ${list(w)}, all tagged ${S?.tag || "Sample"}. They are stored on this computer and work offline. Adding them sends nothing anywhere (if you index the documents for search, their text goes to your embedding model like any other document). You can remove them again in one step under Settings > General.`,
    confirmLabel: "Add samples",
  });
  if (!ok) return;
  try {
    const r = await api("samples/add", { method: "POST" });
    S = r;
    toast({ message: r.added ? "Sample content added." : "Sample content is already there.", action: "Open Studio", onAction: () => { location.hash = "#/studio"; } });
  } catch (e) { toast({ message: `Could not add the samples: ${e.message}` }); }
  await refresh();
}

export async function removeSamples() {
  const ok = await confirmDialog({
    title: "Remove sample content?",
    message: `This moves the sample prompts, project and collection that are still tagged ${S?.tag || "Sample"} to the Trash, where you can restore them for 30 days. Anything you already deleted is skipped, and anything where you removed the ${S?.tag || "Sample"} tag is kept.`,
    confirmLabel: "Remove samples",
  });
  if (!ok) return;
  try {
    const r = await api("samples/remove", { method: "POST" });
    const n = r.removed.studio + r.removed.linkshell + r.removed.collections;
    toast({ message: n ? `Moved to the Trash: ${plural(r.removed.studio, "prompt")}, ${plural(r.removed.linkshell, "project")}, ${plural(r.removed.collections, "collection")}.${r.kept ? ` Kept ${r.kept} you changed.` : ""}` : "No sample content to remove.", action: n ? "Open Trash" : undefined, onAction: () => { location.hash = "#/trash"; } });
  } catch (e) { toast({ message: `Could not remove the samples: ${e.message}` }); }
  await refresh();
}

async function dismissOffer() {
  try { S = await api("samples/dismiss", { method: "POST" }); } catch (e) { /* the card just stays until the next try */ }
  draw();
}

// ---- the Dashboard card ----
function drawOffer() {
  const page = document.getElementById("page-dashboard");
  if (!page) return;
  let card = document.getElementById("samples-offer");
  if (!S?.can_offer) { card?.remove(); return; }
  if (!card) {
    card = document.createElement("section");
    card.id = "samples-offer";
    card.className = "card samples-offer";
    card.setAttribute("aria-label", "Sample content");
    card.addEventListener("click", (e) => {
      if (e.target.closest("[data-samples-add]")) addSamples();
      else if (e.target.closest("[data-samples-no]")) dismissOffer();
    });
    page.querySelector(".intro")?.after(card);
  }
  card.innerHTML = `
    <div class="samples-text">
      <h2 class="samples-title">New here? Try some samples</h2>
      <p class="muted small">Add a few example prompts, a project plan and short documents to look around. They work offline, adding them sends nothing anywhere, and you can remove them in one step.</p>
    </div>
    <div class="samples-actions">
      <button type="button" class="btn btn-sm btn-glow" data-samples-add>Add samples</button>
      <button type="button" class="btn btn-sm btn-glow" data-samples-no>No thanks</button>
    </div>`;
}

// ---- the Settings > General row ----
function drawRow(el) {
  if (!S) { el.innerHTML = `<p class="muted small">Could not read the sample content status.</p>`; return; }
  const p = S.present;
  const here = hasSamples();
  el.innerHTML = here
    ? `<p class="small"><b>Added.</b> <span class="muted">${esc(list({ ...p, documents: S.will_add.documents }))}${S.kept ? `; ${plural(S.kept, "item")} you changed will be kept` : ""}.</span></p>
       <div class="set-inline"><button type="button" class="btn btn-sm btn-glow" data-samples-remove>Remove sample content</button></div>`
    : `<p class="small muted">Not added.</p>
       <div class="set-inline"><button type="button" class="btn btn-sm btn-glow" data-samples-add>Add sample content</button></div>`;
  el.onclick = (e) => {
    if (e.target.closest("[data-samples-add]")) addSamples();
    else if (e.target.closest("[data-samples-remove]")) removeSamples();
  };
}

/** Called by settings.js after it draws the General section. */
export function mountSamples(el) {
  drawRow(el);
  refresh();
}

registerCommands(() => (!S ? [] : hasSamples()
  ? [{ label: "Remove sample content", where: "Settings", keywords: "example demo sample delete clean", run: removeSamples }]
  : [{ label: "Add sample content", where: "Settings", keywords: "example demo sample try", run: addSamples }]));

window.addEventListener("hashchange", () => { if (location.hash === "" || location.hash.startsWith("#/dashboard")) refresh(); });
refresh();

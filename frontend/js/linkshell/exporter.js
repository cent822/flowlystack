// Export and import of a Linkshell project, shared by the home list and the canvas header. An export is a clean plan (no status) in Markdown
// (a spec pack for a repo's docs/) or JSON (readable `plan` plus everything needed to re-import).
import { api } from "../api.js";
import { toast } from "../toast.js";

export function downloadExport(id, format) {   // the export route sends the file as an attachment
  const a = document.createElement("a");
  a.href = `/api/linkshell/${encodeURIComponent(id)}/export?format=${format}`; a.download = ""; document.body.append(a); a.click(); a.remove();
}

/** Three menu items for a <div class="pr-menu">; the click is handled by `exportClick`. */
export const exportItems = (icon) => `<button type="button" class="pr-menuitem" role="menuitem" data-export="md" title="A spec pack to read or give to your own agent. Reference files are listed with their full paths on this computer.">${icon}<span>Export Markdown</span></button>
  <button type="button" class="pr-menuitem" role="menuitem" data-export="json" title="The whole plan. Includes your reference files, and can be imported back as a new project.">${icon}<span>Export JSON</span></button>
  <button type="button" class="pr-menuitem" role="menuitem" data-export="zip" title="To share: one zip with plan.md and an assets folder holding your reference files, with relative paths that work on any computer.">${icon}<span>Export to share (zip)</span></button>`;

/** Handles a click inside a menu built with `exportItems`; returns true when it was one of the three items. */
export function exportClick(e, id) {
  const b = e.target.closest("[data-export]");
  if (!b) return false;
  b.closest("details")?.removeAttribute("open");
  downloadExport(id, b.dataset.export);
  return true;
}

/** Pick a JSON export, create a NEW project from it, and open it. */
export function importProject() {
  const inp = document.createElement("input");
  inp.type = "file"; inp.accept = ".json,application/json";
  inp.addEventListener("change", async () => {
    const f = inp.files[0];
    if (!f) return;
    let data;
    try { data = JSON.parse(await f.text()); } catch { return toast({ message: "That file is not a Linkshell export (not valid JSON).", ms: 4000 }); }
    try {
      const p = await api("linkshell/import", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(data) });
      toast({ message: `Imported as “${p.project.name}”.`, ms: 3000 });
      location.hash = "#/linkshell/" + p.project.id;
    } catch (err) { toast({ message: "Could not import: " + err.message, ms: 4000 }); }
  });
  inp.click();
}

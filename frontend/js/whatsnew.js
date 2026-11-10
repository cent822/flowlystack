// What's new (#/whatsnew): the release notes from CHANGELOG.md (bundled with the app, so it works offline), newest first, with the
// version you are running marked. Read-only; the notes come from /api/about/changelog. Plain DOM, no framework.
import { api } from "./api.js";
import { registerCommands, ICONS } from "./palette.js";

const $ = (s) => document.querySelector(s);
const esc = (t) => String(t ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
const inline = (t) => esc(t).replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>").replace(/`([^`]+)`/g, "<code>$1</code>");   // only bold and code, on escaped text

registerCommands(() => [
  { label: "What's new", where: "Account", keywords: "release notes changelog version updates news", icon: ICONS.setup, run: () => { location.hash = "#/whatsnew"; } },
  { label: "About FlowlyStack", where: "Settings", keywords: "version about credits licence", icon: ICONS.setup, run: () => { location.hash = "#/settings/about"; } },
]);

export async function showWhatsNew() {
  const list = $("#wn-list");
  let d;
  try { d = await api("about/changelog"); } catch { list.innerHTML = `<p class="muted">Could not load the release notes.</p>`; return; }
  $("#wn-sub").textContent = `You are on version ${d.version}. Each release lists what is new, what got better and what was fixed.`;
  list.innerHTML = d.releases.length ? d.releases.map((r) => `
    <article class="card wn-rel">
      <header class="card-head">
        <h2>v${esc(r.version)}</h2>
        <span class="wn-meta">${r.version === d.version ? `<span class="tag wn-now">You are here</span>` : ""}${r.date ? `<span class="muted">${esc(r.date)}</span>` : ""}</span>
      </header>
      ${r.intro ? `<p class="wn-intro">${inline(r.intro)}</p>` : ""}
      ${r.sections.map((s) => `<h3 class="wn-h">${esc(s.title)}</h3><ul class="wn-items">${s.items.map((i) => `<li>${inline(i)}</li>`).join("")}</ul>`).join("")}
    </article>`).join("") : `<p class="muted">No release notes are bundled with this copy.</p>`;
}

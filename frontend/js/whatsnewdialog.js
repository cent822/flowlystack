// After an update: the first login on a new version opens a dialog with that version's release notes (GET /api/about/whatsnew; the server
// remembers the last version it showed, so this happens once per version for the whole install). Close, Esc or a click outside closes it.
// Switch off in Settings > Updates. The notes are bundled with the app: nothing here uses the network.
import { infoDialog } from "./dialog.js";
import { esc, inline } from "./whatsnew.js";

function release(r) {
  return `<section class="wn-dlg-rel">
    <h3 class="wn-dlg-ver">v${esc(r.version)}${r.date ? ` <span class="muted">${esc(r.date)}</span>` : ""}</h3>
    ${r.intro ? `<p class="wn-intro">${inline(r.intro)}</p>` : ""}
    ${r.sections.map((s) => `<h4 class="wn-h">${esc(s.title)}</h4><ul class="wn-items">${s.items.map((i) => `<li>${inline(i)}</li>`).join("")}</ul>`).join("")}
  </section>`;
}

async function show() {
  let d;
  try { d = await (await fetch("/api/about/whatsnew")).json(); } catch { return; }
  if (!d || !d.enabled || !d.releases?.length) return;
  fetch("/api/about/whatsnew/seen", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ version: d.version }) }).catch(() => {});   // once per version, even if it is closed at once
  const top = d.releases[0];
  const act = await infoDialog({
    title: `What's new in FlowlyStack ${top.version}`,
    html: d.releases.map(release).join(""),
    moreLabel: "All releases",
  });
  if (act === "more") location.hash = "#/whatsnew";
}

show();

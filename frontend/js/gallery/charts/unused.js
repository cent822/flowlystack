// Use 2 (Documents mode): which documents earn their place. "Never cited" lists documents no saved chat has used (newest first), "Most cited" those used
// most; both follow the filters. Counted from saved conversations only: with Save conversations off (Settings > Knowledge) there is nothing to count and
// the card says so. Click a row to select that document.
import { esc, fmtDay, agentColor, note } from "../common.js";
import { S, data, F, apply } from "../state.js";

const MORE = 12;

export function unused(el) {
  const { snap } = data();
  if (!snap.use.history) return note(el, "Conversations are not saved (Settings > Knowledge > Save conversations), or none has been asked yet, so there is nothing to count.");
  const never = F.filter((r) => r.cited === 0).sort((a, b) => b.t - a.t), top = F.filter((r) => r.cited > 0).sort((a, b) => b.cited - a.cited || b.t - a.t).slice(0, 8);
  const row = (r, right) => `<li><button type="button" class="gal-ur" data-doc="${r.i}"><i style="background:${agentColor(r.a)}"></i><span class="gal-un">${esc(r.title)}</span><span class="muted">${right}</span></button></li>`;
  const a = document.activeElement, was = a && a.dataset && a.dataset.doc !== undefined ? `[data-doc="${a.dataset.doc}"]` : "";   // keep the keyboard focus on the same row after a redraw
  el.innerHTML = `<p class="gal-rgs">Counted over ${snap.use.exchanges.toLocaleString()} ${snap.use.exchanges === 1 ? "answer" : "answers"} in ${snap.use.chats.toLocaleString()} saved ${snap.use.chats === 1 ? "chat" : "chats"}. A document counts when a passage of it was sent to the model and cited.</p>
    <h4 class="gal-uh">Never cited · ${never.length.toLocaleString()}</h4>
    <ul class="gal-use">${never.slice(0, MORE).map((r) => row(r, fmtDay(new Date(r.t)))).join("") || `<li class="muted small">Every document here has been cited.</li>`}</ul>
    ${never.length > MORE ? `<p class="muted small">and ${(never.length - MORE).toLocaleString()} more. Select them from the first chart (click “Never cited”).</p>` : ""}
    <h4 class="gal-uh">Most cited</h4>
    <ul class="gal-use">${top.map((r) => row(r, `${r.cited}×`)).join("") || `<li class="muted small">No document here has been cited yet.</li>`}</ul>`;
  el.onclick = (e) => {
    const b = e.target.closest("[data-doc]");
    if (!b) return;
    const i = +b.dataset.doc;
    S.sel = S.sel && S.sel.src === "dot" && S.sel.ids.size === 1 && S.sel.ids.has(i) ? null : { label: data().R[i].title, ids: new Set([i]), src: "dot" };
    apply();
  };
  if (was) el.querySelector(was)?.focus();
}

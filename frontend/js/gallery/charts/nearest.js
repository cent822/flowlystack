// Use 3 (Documents mode): the Library prompts closest in meaning to one document. Needs stored embeddings (an embedding model in Settings > Knowledge, with the
// documents and the prompts indexed); the match is the cosine of the stored vectors, shown as 0 to 100. Select one document (click a dot or a row) to see it.
// Nothing here is sent anywhere. Open goes to the prompt in the Library.
import { esc, note } from "../common.js";
import { data, F } from "../state.js";

export function nearest(el) {
  const { snap } = data();
  if (!snap.nearest || !Object.keys(snap.nearest).length) return note(el, "This needs stored embeddings: choose an embedding model in Settings > Knowledge and let your documents and prompts finish indexing. Groups made from words cannot be compared with prompts.");
  if (F.length !== 1) return note(el, "Select one document (click a dot on the map, or a row in the list) to see the Library prompts closest to it.");
  const r = F[0], list = snap.nearest[String(r.i)] || [];
  el.innerHTML = `<p class="gal-rgs">Closest to <b>${esc(r.title)}</b>:</p><ul class="gal-use">${list.map((p) => `<li><a class="gal-ur" href="#/prompts/${encodeURIComponent(p.id)}" title="Open this prompt in the Library"><span class="gal-un">${esc(p.t)}</span><span class="muted">match ${Math.round(Math.max(0, p.s) * 100)}</span></a></li>`).join("") || `<li class="muted small">No Library prompts to compare with.</li>`}</ul>`;
}

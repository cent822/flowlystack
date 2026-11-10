// Entity kinds: the list the user manages (labels, hints, a light and a dark colour per kind). The server keeps it in
// PROMPTS_DIR/kgraph/kinds.json; this module holds the copy the page and the canvas read. A kind that was deleted, or that is unknown, shows as Other.
import { api } from "../api.js";
import { isDark } from "../theme.js";

export const OTHER = "other";
const GREY = ["#8a8f98", "#9aa0a8"];
let list = [], by = new Map(), lim = { total: 30, label: 24, hint: 100 };

export function setKinds(d) {
  list = d?.kinds || [];
  by = new Map(list.map((k) => [k.slug, k]));
  lim = d?.limits || lim;
}
/** Load the list from the server and keep it. Resolves to the raw answer (or null when the server cannot answer). */
export async function loadKinds() {
  const d = await api("kgraph/kinds").catch(() => null);
  if (d) setKinds(d);
  return d;
}
export const limits = () => lim;
export const allKinds = () => list;
export const activeKinds = () => list.filter((k) => !k.deleted);
/** The slug an entity is shown under: its own while that kind is active, else Other. */
export const shown = (slug) => { const k = by.get(slug); return k && !k.deleted ? slug : OTHER; };
export const kindOf = (slug) => by.get(shown(slug));
const cap = (t) => t.charAt(0).toUpperCase() + t.slice(1);
export const kindLabel = (slug) => kindOf(slug)?.label || cap(String(slug || OTHER));
/** "was Technology" for an entity whose kind is deleted, else "". */
export const wasLabel = (raw) => { const k = by.get(raw); return k && k.deleted ? k.label : ""; };
/** The colour for the current theme (or for `dark` when given: the canvas asks once per frame). */
export function kindColour(slug, dark = isDark()) {
  const k = kindOf(slug);
  return k ? (dark ? k.dark : k.light) : GREY[dark ? 1 : 0];
}
/** Change a colour in the local copy only (the manager's live preview while a colour is picked; saving goes through the API and `setKinds`). */
export function previewColour(slug, which, hex) {
  const k = by.get(slug);
  if (k && (which === "light" || which === "dark")) k[which] = hex;
}

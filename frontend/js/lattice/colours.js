// Node colours: the user's own light and dark colour per item type (Library, Studio, Documents, Collections, Tags) and per collection. The server keeps only
// the changes in PROMPTS_DIR/kgraph/colours.json (backend/kgraph_colours.py); with none, the theme tokens below apply, so an untouched page looks as before.
// A collection without its own colour takes the Collections type's colour. Entity kinds have their own colours (kinds.js). These are user data, read at draw time.
import { api } from "../api.js";
import { isDark } from "../theme.js";
import { css } from "../util.js";

export const TYPE_COLOR = { prompt: "--series-1", studio: "--series-3", document: "--series-2", collection: "--series-4", tag: "--series-5", project: "--series-8", reference: "--series-6", entity: "--series-7", linkshell: "--series-9" };
/** The same colours written out as light / dark pairs, ONLY for the dialog's chips (it shows both modes at once). Keep them equal to the --series-* tokens in tokens.css. */
export const DEFAULTS = { prompt: ["#2a78d6", "#3987e5"], studio: ["#1baf7a", "#199e70"], document: ["#eb6834", "#d95926"], collection: ["#eda100", "#c98500"], tag: ["#e87ba4", "#d55181"], project: ["#e34948", "#e66767"], reference: ["#008300", "#008300"], linkshell: ["#8b5e3c", "#c4957a"] };
export const EDITABLE = ["prompt", "studio", "document", "collection", "tag", "project", "reference", "linkshell"];

let ov = { types: {}, collections: {} };
export function setColours(d) { ov = { types: d?.types || {}, collections: d?.collections || {} }; }
export async function loadColours() { const d = await api("kgraph/colours").catch(() => null); if (d) setColours(d); return d; }
export const colours = () => ov;

const w = (dark) => (dark ? "dark" : "light");
/** The colour of an item type for the current theme (or for `dark` when given). */
export const typeColour = (t, dark = isDark()) => ov.types[t]?.[w(dark)] || css(TYPE_COLOR[t]);
/** A collection's own colour, else the Collections type's. */
export const collectionColour = (id, dark = isDark()) => ov.collections[id]?.[w(dark)] || typeColour("collection", dark);
/** The colour of a node of type `t` (a collection by its id). Entities are not handled here (kinds.js). */
export const nodeColour = (t, id, dark = isDark()) => (t === "collection" ? collectionColour(id, dark) : typeColour(t, dark));
/** The colour as a CSS value for a dot: `background:${dot(t, id)}`. */
export const dot = (t, id) => nodeColour(t, id);
/** The chip colour in the dialog for one mode: the override, else the built-in pair (a collection falls back to the Collections type). */
export function chipColour(kind, key, which) {
  const o = kind === "collection" ? ov.collections[key]?.[which] : ov.types[key]?.[which];
  if (o) return o;
  return kind === "collection" ? chipColour("type", "collection", which) : DEFAULTS[key][which === "dark" ? 1 : 0];
}
/** Local-only change for the live preview while a colour is being picked (saving goes through the API and `setColours`). */
export function previewColour(kind, key, which, hex) {
  const m = kind === "collection" ? ov.collections : ov.types;
  (m[key] ||= {})[which] = hex;
}

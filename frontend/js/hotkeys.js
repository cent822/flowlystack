// Keyboard shortcuts: the one place that knows which keys do what. A shortcut is stored as "mod+shift+d" (backend/settings.py):
// `mod` is Cmd on a Mac and Ctrl elsewhere, Shift and Alt (Option) are optional, and the key is one letter or digit (or Enter). The keys come from
// Settings > Keyboard (/api/settings, section "hotkeys"); until they load, and if the server cannot be reached, the defaults apply.
// A change fires `flowlystack-hotkeys` so labels on screen can follow. Plain DOM, no framework.
import { api } from "./api.js";
import { ICONS, registerCommands } from "./palette.js";

export const DEFAULTS = { save: "mod+s", details: "mod+shift+d", assistant: "mod+shift+a", search: "mod+shift+s", note: "mod+shift+e", new: "mod+alt+n", tags: "mod+alt+t", lsadd: "mod+alt+p", lsref: "mod+alt+r", lsnote: "mod+alt+s", lsframe: "mod+alt+f", lstidy: "mod+alt+l", paneldone: "mod+alt+o", lsdone: "mod+enter", lscopy: "mod+shift+c", cofocus: "mod+alt+k", cosend: "mod+alt+e", conewchat: "mod+alt+h", cosources: "mod+alt+g", codocs: "mod+alt+d" };
export const isMac = /Mac|iPhone|iPad/i.test(navigator.platform || navigator.userAgent);
let keys = { ...DEFAULTS };

export const hotkey = (name) => keys[name];

export async function loadHotkeys() {
  try { keys = { ...DEFAULTS, ...(await api("settings")).sections.hotkeys }; } catch { /* the defaults stay */ }
  dispatchEvent(new Event("flowlystack-hotkeys"));
}

/** The shortcut a key press is, in the stored form, or null when it is not a Cmd/Ctrl + letter or digit press.
 *  Uses the physical key (`code`), so Shift or a keyboard layout never changes which letter it is. */
export function comboOf(e) {
  const m = /^(?:Key([A-Z])|Digit(\d)|(Enter|NumpadEnter))$/.exec(e.code || "");
  const mod = isMac ? e.metaKey && !e.ctrlKey : e.ctrlKey && !e.metaKey;
  if (!m || !mod) return null;
  return "mod+" + (e.shiftKey ? "shift+" : "") + (e.altKey ? "alt+" : "") + (m[3] ? "enter" : (m[1] || m[2]).toLowerCase());
}

export const matches = (e, name) => comboOf(e) === keys[name];

/** "mod+shift+d" as shown to people: ⌘⇧D on a Mac, Ctrl+Shift+D elsewhere. */
export function label(combo) {
  const parts = String(combo || "").split("+"), raw = parts.pop() || "", key = raw === "enter" ? (isMac ? "↵" : "Enter") : raw.toUpperCase(), shift = parts.includes("shift"), alt = parts.includes("alt");
  return isMac ? `⌘${shift ? "⇧" : ""}${alt ? "⌥" : ""}${key}` : `Ctrl+${shift ? "Shift+" : ""}${alt ? "Alt+" : ""}${key}`;
}

// Search (every page with a search bar): focus the visible field marked data-search. Pages mark theirs.
const searchBox = () => [...document.querySelectorAll("input[data-search]")].find((i) => i.offsetParent !== null);
const tip = () => {
  document.querySelectorAll("input[data-search]").forEach((i) => { i.title = `Search (${label(keys.search)})`; });
  document.querySelectorAll("kbd[data-hk]").forEach((k) => { k.textContent = label(keys[k.dataset.hk]); });   // badges on buttons and search bars follow the keys
};
addEventListener("keydown", (e) => {
  if (e.defaultPrevented || document.querySelector("dialog[open]") || !matches(e, "search")) return;
  const box = searchBox();
  if (!box) return;
  e.preventDefault(); box.focus(); box.select();
});
// Esc lets go of the focused field or button (its focus ring goes), so the pointer is free again. It does nothing while something else
// owns Esc: a dialog, an open dropdown or menu, or a shortcut being recorded. Checked in the capture phase, before those close themselves.
document.addEventListener("keydown", (e) => {
  if (e.key !== "Escape" || e.defaultPrevented || e.isComposing) return;
  const a = document.activeElement;
  if (!a || a === document.body || a === document.documentElement) return;
  if (document.querySelector("dialog[open], details.pr-vers[open], details.pl-tagmenu[open], details.pr-more[open], details.pr-rowmenu[open], .set-hotkey.rec, #account-menu:not([hidden])")) return;
  a.blur();
}, true);

// Tags (every prompt page): on a prompt page (and the new-prompt page) the cursor goes to the end of the visible input marked data-tags, ready for the
// next tag; on a list page the Tags filter menu opens (and closes again on a second press). Also run by the command palette entry below.
export function focusTags() {
  const box = [...document.querySelectorAll("input[data-tags]")].find((i) => i.offsetParent !== null);
  if (box) { box.focus(); box.setSelectionRange(box.value.length, box.value.length); return true; }
  const menu = [...document.querySelectorAll("details.pl-tagmenu")].find((d) => d.offsetParent !== null);
  if (!menu) return false;
  menu.open = !menu.open;
  if (menu.open) menu.querySelector("input")?.focus(); else menu.querySelector("summary")?.focus();
  return true;
}
addEventListener("keydown", (e) => {
  if (e.defaultPrevented || document.querySelector("dialog[open]") || !matches(e, "tags")) return;
  if (focusTags()) e.preventDefault();
});
// One palette entry per area, so each goes to its own page first (if the user is not already there) and then does what the Tags key does.
const tagsIn = (hash) => () => { const here = location.hash.startsWith(hash); if (!here) location.hash = hash; setTimeout(focusTags, here ? 80 : 300); };
registerCommands(() => [
  { label: "Tags", where: "Prompt Library", keywords: "tag tags add edit filter label library", icon: ICONS.find, run: tagsIn("#/prompts") },
  { label: "Tags", where: "Prompt Studio", keywords: "tag tags add edit filter label studio", icon: ICONS.find, run: tagsIn("#/studio") },
]);

// Button shortcuts: any visible button marked data-hotkey="<name>" is clicked by that name's key, on every page.
// A page only adds the attribute (and a <kbd data-hk="<name>">); nothing else is needed. `paneldone` is the Done button of any panel.
addEventListener("keydown", (e) => {
  if (e.defaultPrevented || document.querySelector("dialog[open]")) return;
  const name = ["note", "new", "paneldone", "lsdone", "lscopy"].find((n) => matches(e, n));
  const btn = name && [...document.querySelectorAll(`[data-hotkey="${name}"]`)].find((b) => b.offsetParent !== null && !b.disabled);
  if (btn) { e.preventDefault(); btn.click(); }
});
addEventListener("flowlystack-hotkeys", tip);
addEventListener("hashchange", () => setTimeout(tip, 100));

loadHotkeys();

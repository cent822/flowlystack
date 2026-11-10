// Hands a text from one page to an editor as an unsaved draft (Collections "Use as prompt" and "Open with this text as a draft").
// The text travels through sessionStorage and is read once, by the page that opens: the Studio new-prompt form ("new") or a prompt page
// (its id). Nothing is saved by this; the user reviews the draft and presses Save.
const KEY = "flowlystack-draft";

/** Leave a draft for `target` ("new" or a prompt id) and go there with `hash`. */
export function sendDraft(target, text, { title = "", message = "", from = "Collections" } = {}, hash = "") {
  try { sessionStorage.setItem(KEY, JSON.stringify({ target, text, title, message, from })); } catch { return false; }
  if (hash) location.hash = hash;
  return true;
}

/** The waiting draft when it is meant for `target`; it is removed so a reload does not apply it twice. */
export function takeDraft(target) {
  try {
    const d = JSON.parse(sessionStorage.getItem(KEY) || "null");
    if (!d || d.target !== target) return null;
    sessionStorage.removeItem(KEY);
    return d;
  } catch { return null; }
}

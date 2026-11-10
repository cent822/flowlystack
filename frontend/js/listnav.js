// Keyboard-first list: ↑ / ↓ move a highlight through the result rows (from the page itself or from the search box), Enter opens the highlighted one.
// Nothing is highlighted until the first arrow press (the first row is not assumed to be the wanted one), and Enter with no highlight does nothing.
// The search box keeps its focus if it had it; the highlight resets whenever the list is redrawn (new query, filter, page).
export function listNav(input, list) {
  let i = -1;
  const rows = () => [...list.querySelectorAll(".pr-row:has(.pr-link)")];
  const mark = (n) => {
    const r = rows();
    r.forEach((el, k) => { el.classList.toggle("kb", k === n); if (k === n) el.scrollIntoView({ block: "nearest" }); });
    i = r.length ? n : -1;
    list.classList.toggle("kbnav", i >= 0);   // while the keyboard drives, a resting mouse pointer must not light a second row (CSS)
  };
  new MutationObserver(() => { i = -1; list.classList.remove("kbnav"); }).observe(list, { childList: true });   // redraw replaces the rows, so the old highlight is gone
  let px = -1, py = -1;
  list.addEventListener("mousemove", (e) => {   // a real pointer move hands control back to the mouse
    // The browser also fires a mousemove at the resting pointer when a row scrolls under it: no movement, so it must not clear the highlight
    const moved = e.movementX || e.movementY || (px >= 0 && (e.clientX !== px || e.clientY !== py));
    px = e.clientX; py = e.clientY;
    if (moved && i >= 0) mark(-1);
  });
  input?.addEventListener("blur", () => mark(-1));   // a page with no search box (Trash) passes null
  // The arrows work as soon as the page is open, with no click and no search shortcut first: while the list is on screen and nothing that needs the arrow keys
  // owns the focus (the page itself, the search box, or a plain button or link), ↑ / ↓ move the highlight and Enter opens it. A select, another text field,
  // an open menu or a dialog keeps its own keys.
  const MENUS = "details.pr-vers[open], details.pl-tagmenu[open], details.pr-more[open], details.pr-rowmenu[open], #account-menu:not([hidden])";
  const plain = (a) => a && ["BUTTON", "A", "SUMMARY"].includes(a.tagName) && !a.closest("[role=menu], .pr-menu");
  document.addEventListener("keydown", (e) => {
    if (e.defaultPrevented || e.isComposing || e.metaKey || e.ctrlKey || e.altKey || e.shiftKey) return;
    if (list.offsetParent === null || document.querySelector("dialog[open], " + MENUS)) return;   // another page, a dialog or a menu is on top
    const a = document.activeElement, free = !a || a === document.body || a === document.documentElement || a === input;
    const n = rows().length;
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      if (!n || !(free || plain(a))) return;
      e.preventDefault();
      if (a !== input && a !== document.body && a.blur) a.blur();   // the highlight, not a button's focus ring, is the one selection
      mark(e.key === "ArrowDown" ? Math.min(i + 1, n - 1) : i - 1);   // ↑ from the first row clears the highlight
    } else if (e.key === "Enter" && i >= 0 && free) {
      e.preventDefault();
      rows()[i]?.querySelector(".pr-link")?.click();
    } else if (e.key === "Escape" && i >= 0 && free) mark(-1);
  });
}

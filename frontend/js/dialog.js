// Themed confirmation dialog in place of the browser's confirm(). A native <dialog> opened with showModal()
// sits in the top layer, is centred by the browser, traps focus, and closes on Esc.
const esc = (t) => String(t ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);

/** Tab and Shift+Tab loop inside the dialog: after the last control Tab goes to the first, and Shift+Tab on the first goes to the last,
 *  instead of leaving the page for the browser's own toolbar (the native modal dialog lets focus escape there). */
function loopTab(dlg) {
  dlg.addEventListener("keydown", (e) => {
    if (e.key !== "Tab" || e.altKey || e.ctrlKey || e.metaKey) return;
    const items = [...dlg.querySelectorAll("a[href], button, input:not([type=hidden]), textarea, select, summary, [tabindex]")]
      .filter((el) => !el.disabled && el.tabIndex >= 0 && el.offsetParent !== null);
    if (!items.length) return;
    const first = items[0], last = items[items.length - 1];
    if (e.shiftKey && (document.activeElement === first || !dlg.contains(document.activeElement))) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && (document.activeElement === last || !dlg.contains(document.activeElement))) { e.preventDefault(); first.focus(); }
  });
}

/** Resolves true when the user confirms, false on Cancel, Esc or a click outside the box. */
export function confirmDialog({ title, message, confirmLabel = "OK", cancelLabel = "Cancel", danger = false }) {
  return new Promise((resolve) => {
    const dlg = document.createElement("dialog");
    dlg.className = "cb-dialog";
    dlg.setAttribute("aria-labelledby", "cb-dialog-title");
    dlg.setAttribute("aria-describedby", "cb-dialog-msg");
    dlg.innerHTML = `
      <div class="cb-dialog-box">
        <h2 id="cb-dialog-title">${esc(title)}</h2>
        <p id="cb-dialog-msg">${esc(message)}</p>
        <div class="cb-dialog-actions">
          <button type="button" class="btn btn-sm btn-glow btn-glow-md" data-act="cancel">${esc(cancelLabel)}</button>
          <button type="button" class="btn btn-sm btn-glow btn-glow-md${danger ? " btn-danger" : ""}" data-act="ok" autofocus>${esc(confirmLabel)}</button>
        </div>
      </div>`;
    let ok = false;
    dlg.addEventListener("click", (e) => {
      const act = e.target.closest("[data-act]")?.dataset.act;
      if (act === "ok") ok = true;
      if (act || e.target === dlg) dlg.close();   // a click on the backdrop lands on the <dialog> itself
    });
    dlg.addEventListener("close", () => { dlg.remove(); resolve(ok); });
    loopTab(dlg);
    document.body.append(dlg);
    dlg.showModal();
  });
}

/**
 * A dialog with a form in it (Details, Note, the Save message). `html` is the body; `read(dlg)` returns what
 * to resolve with when the user confirms (Done, Enter in a one-line field, or Cmd/Ctrl+Enter anywhere); null on Cancel, Esc or a
 * click outside. `extra` is HTML for more buttons at the left of the actions, `cancelLabel: null` leaves out Cancel, and
 * `validate(dlg)` returns a message to show (and keep the dialog open) or "" when the form is fine, `onOpen(dlg)` wires anything inside. Focus goes back to where it was when the dialog closes.
 */
export function formDialog({ title, html, read, validate, confirmLabel = "Done", confirmKbd = "", cancelLabel = "Cancel", extra = "", wide = false, onOpen }) {
  return new Promise((resolve) => {
    const dlg = document.createElement("dialog");
    dlg.className = "cb-dialog cb-form" + (wide ? " wide" : "");
    dlg.setAttribute("aria-labelledby", "cb-form-title");
    dlg.innerHTML = `
      <form class="cb-dialog-box" method="dialog">
        <h2 id="cb-form-title">${esc(title)}</h2>
        <div class="cb-form-body">${html}</div>
        <p class="cb-form-err" role="alert" hidden></p>
        <div class="cb-dialog-actions">
          ${extra}<span class="cb-spacer"></span>
          ${cancelLabel ? `<button type="button" class="btn btn-sm btn-glow btn-glow-md" data-act="cancel">${esc(cancelLabel)}</button>` : ""}
          <button type="submit" class="btn btn-sm btn-glow btn-glow-md">${esc(confirmLabel)}${confirmKbd ? `<kbd class="kbd">${esc(confirmKbd)}</kbd>` : ""}</button>
        </div>
      </form>`;
    let result = null;
    dlg.querySelector("form").addEventListener("submit", (e) => {
      e.preventDefault();
      const bad = validate?.(dlg) || "", err = dlg.querySelector(".cb-form-err");
      err.hidden = !bad; err.textContent = bad;
      if (bad) return;
      result = read ? read(dlg) : true; dlg.close();
    });
    dlg.addEventListener("click", (e) => { if (e.target === dlg || e.target.closest('[data-act="cancel"]')) dlg.close(); });
    dlg.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) { e.preventDefault(); dlg.querySelector("form").requestSubmit(); }
    });
    dlg.addEventListener("close", () => { dlg.remove(); resolve(result); });
    loopTab(dlg);
    document.body.append(dlg);
    dlg.showModal();
    onOpen?.(dlg);
    dlg.querySelector("input:not([type=hidden]):not([type=checkbox]), textarea")?.focus();
  });
}

/**
 * A dialog that asks for ONE choice from a short list, each option with a picture and a line of explanation (the Lattice Layout picker). Choosing an option
 * (click, Enter or Space on it, or its number key) closes the dialog and resolves with its `value`; Esc, Close or a click outside resolves null. `options`:
 * [{ value, label, desc, thumb }] where `thumb` is trusted HTML (an inline SVG) and `label`/`desc` are plain text. It is a radio group: the current option is
 * checked and focused first, the arrow keys move between options, Tab leaves the group.
 */
export function choiceDialog({ title, intro = "", options, current, closeLabel = "Close" }) {
  return new Promise((resolve) => {
    const dlg = document.createElement("dialog");
    dlg.className = "cb-dialog cb-choice-dlg";
    dlg.setAttribute("aria-labelledby", "cb-choice-title");
    const tick = '<svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 8.5l3.2 3.2L13 5"/></svg>';
    dlg.innerHTML = `
      <div class="cb-dialog-box">
        <h2 id="cb-choice-title">${esc(title)}</h2>
        ${intro ? `<p class="muted small cb-choice-intro">${esc(intro)}</p>` : ""}
        <div class="cb-choice" role="radiogroup" aria-labelledby="cb-choice-title">${options.map((o, i) => `
          <button type="button" class="cb-opt" role="radio" aria-checked="${o.value === current}" tabindex="${o.value === current ? 0 : -1}" data-i="${i}">
            <span class="cb-opt-thumb">${o.thumb || ""}</span>
            <span class="cb-opt-text"><b>${esc(o.label)}</b><span>${esc(o.desc)}</span></span>
            <span class="cb-opt-mark">${o.value === current ? tick : ""}</span>
          </button>`).join("")}
        </div>
        <div class="cb-dialog-actions"><span class="cb-spacer"></span><button type="button" class="btn btn-sm btn-glow btn-glow-md" data-act="cancel">${esc(closeLabel)}</button></div>
      </div>`;
    let result = null;
    const opts = () => [...dlg.querySelectorAll(".cb-opt")];
    const focusAt = (i) => { const l = opts(); const el = l[(i + l.length) % l.length]; l.forEach((b) => (b.tabIndex = b === el ? 0 : -1)); el.focus(); };
    const pick = (i) => { result = options[i]?.value ?? null; dlg.close(); };
    dlg.addEventListener("click", (e) => {
      const b = e.target.closest(".cb-opt");
      if (b) pick(+b.dataset.i);
      else if (e.target === dlg || e.target.closest('[data-act="cancel"]')) dlg.close();
    });
    dlg.addEventListener("keydown", (e) => {
      const at = opts().findIndex((b) => b === document.activeElement);
      if (e.key === "ArrowDown" || e.key === "ArrowRight") { e.preventDefault(); focusAt(at + 1); }
      else if (e.key === "ArrowUp" || e.key === "ArrowLeft") { e.preventDefault(); focusAt(at < 0 ? 0 : at - 1); }
      else if (/^[1-9]$/.test(e.key) && +e.key <= options.length && !e.metaKey && !e.ctrlKey && !e.altKey) { e.preventDefault(); pick(+e.key - 1); }
    });
    dlg.addEventListener("close", () => { dlg.remove(); resolve(result); });
    loopTab(dlg);
    document.body.append(dlg);
    dlg.showModal();
    focusAt(Math.max(0, options.findIndex((o) => o.value === current)));
  });
}

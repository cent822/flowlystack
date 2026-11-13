// One small message at the bottom of the page, with an optional action button (used for "Undo").
let el, timer;

// `node` is optional extra content under the message (the update notice puts its commands there).
export function toast({ message, action, onAction, ms = 7000, node }) {
  clearTimeout(timer);
  el?.remove();
  el = document.createElement("div");
  el.className = "cb-toast";
  el.setAttribute("role", "status");
  const text = document.createElement("span");
  text.textContent = message;
  if (node) {
    const col = document.createElement("div");
    col.className = "cb-toast-col";
    col.append(text, node);
    el.append(col);
  } else el.append(text);
  if (action) {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "btn btn-sm";
    b.textContent = action;
    b.onclick = async () => { hide(); await onAction?.(); };
    el.append(b);
  }
  document.body.append(el);
  timer = setTimeout(hide, ms);
}

function hide() {
  clearTimeout(timer);
  el?.remove();
  el = null;
}

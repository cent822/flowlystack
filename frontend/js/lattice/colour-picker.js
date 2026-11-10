// A small colour picker in place of the browser's own <input type="color"> popup, whose edges cannot be styled (it showed
// a white edge line on the dark theme). A square for saturation and brightness, a hue bar, a hex field, a few swatches and, where the browser has it,
// an eyedropper. Colours are `#rrggbb`. Everything uses theme tokens, so it looks right in both modes. Keyboard: arrows on the square and the bar.
const clamp = (v, a = 0, b = 1) => Math.min(b, Math.max(a, v));
const HEX = /^#[0-9a-f]{6}$/i;
// a few starting points per mode (the built-in kind colours plus a few neutrals); the user is never limited to them
const SWATCH = {
  light: ["#6250d6", "#2a78d6", "#0e9fbf", "#1baf7a", "#eda100", "#eb6834", "#e34948", "#e87ba4", "#b04fc9", "#8a8f98", "#3a3f4a", "#111111"],
  dark: ["#9085e9", "#3987e5", "#38b6d8", "#3ecf9b", "#f0b429", "#f08a5d", "#e66767", "#f09bbd", "#c77ddb", "#9aa0a8", "#d5d9e0", "#ffffff"],
};

export function hexToHsv(hex) {
  const n = parseInt(hex.slice(1), 16), r = (n >> 16) / 255, g = ((n >> 8) & 255) / 255, b = (n & 255) / 255;
  const mx = Math.max(r, g, b), mn = Math.min(r, g, b), d = mx - mn;
  let h = 0;
  if (d) h = mx === r ? ((g - b) / d + (g < b ? 6 : 0)) : mx === g ? (b - r) / d + 2 : (r - g) / d + 4;
  return [h * 60, mx ? d / mx : 0, mx];
}
export function hsvToHex(h, s, v) {
  const c = v * s, x = c * (1 - Math.abs(((h / 60) % 2) - 1)), m = v - c;
  const [r, g, b] = h < 60 ? [c, x, 0] : h < 120 ? [x, c, 0] : h < 180 ? [0, c, x] : h < 240 ? [0, x, c] : h < 300 ? [x, 0, c] : [c, 0, x];
  return "#" + [r + m, g + m, b + m].map((u) => Math.round(clamp(u) * 255).toString(16).padStart(2, "0")).join("");
}

let open = null;
export const closePicker = () => open?.close();

/** Open the picker next to `anchor`, inside `host` (a dialog, so it sits in the top layer with it). `onInput(hex)` runs while the colour moves,
 *  `onChange(hex)` once when the picker closes with a different colour. `mode` ("light" | "dark") only picks the swatches. */
export function openPicker(anchor, host, value, mode, { onInput, onChange }) {
  closePicker();
  const start = value.toLowerCase();
  let [h, s, v] = hexToHsv(start), cur = start;
  const pop = document.createElement("div");
  pop.className = "kp-pop";
  pop.setAttribute("role", "dialog");
  pop.setAttribute("aria-label", `${mode === "dark" ? "Dark" : "Light"} mode colour`);
  pop.innerHTML = `<div class="kp-sv" tabindex="0" role="slider" aria-label="Saturation and brightness (arrow keys)"><i class="kp-dot"></i></div>
    <div class="kp-hue" tabindex="0" role="slider" aria-label="Hue (arrow keys)" aria-valuemin="0" aria-valuemax="360"><i class="kp-dot"></i></div>
    <div class="kp-row"><span class="kp-prev"></span><input class="pl-input kp-hex" maxlength="7" spellcheck="false" aria-label="Hex colour"><button type="button" class="btn btn-sm btn-glow kp-eye" hidden>Screen</button></div>
    <div class="kp-sw">${SWATCH[mode === "dark" ? "dark" : "light"].map((c) => `<button type="button" class="kp-s" style="background:${c}" data-c="${c}" aria-label="${c}"></button>`).join("")}</div>`;
  const $ = (q) => pop.querySelector(q), sv = $(".kp-sv"), hue = $(".kp-hue"), hex = $(".kp-hex");
  const paint = (skipHex) => {
    sv.style.background = `linear-gradient(to top, #000, transparent), linear-gradient(to right, #fff, ${hsvToHex(h, 1, 1)})`;
    sv.firstChild.style.left = s * 100 + "%"; sv.firstChild.style.top = (1 - v) * 100 + "%";
    hue.firstChild.style.left = (h / 360) * 100 + "%";
    hue.setAttribute("aria-valuenow", Math.round(h));
    $(".kp-prev").style.background = cur;
    if (!skipHex) hex.value = cur;
  };
  const move = (skipHex) => { cur = hsvToHex(h, s, v); paint(skipHex); onInput?.(cur); };
  const setHex = (c) => { cur = c.toLowerCase(); [h, s, v] = hexToHsv(cur); paint(); onInput?.(cur); };
  const drag = (el, fn) => {
    el.addEventListener("pointerdown", (e) => { el.setPointerCapture(e.pointerId); fn(e); el.focus({ preventScroll: true }); e.preventDefault(); });
    el.addEventListener("pointermove", (e) => { if (el.hasPointerCapture(e.pointerId)) fn(e); });
  };
  drag(sv, (e) => { const r = sv.getBoundingClientRect(); s = clamp((e.clientX - r.left) / r.width); v = 1 - clamp((e.clientY - r.top) / r.height); move(); });
  drag(hue, (e) => { const r = hue.getBoundingClientRect(); h = clamp((e.clientX - r.left) / r.width) * 359.99; move(); });
  const step = (e) => (e.shiftKey ? 0.1 : 0.02);
  sv.addEventListener("keydown", (e) => {
    const k = e.key; if (!k.startsWith("Arrow")) return;
    e.preventDefault();
    if (k === "ArrowLeft") s = clamp(s - step(e)); if (k === "ArrowRight") s = clamp(s + step(e));
    if (k === "ArrowUp") v = clamp(v + step(e)); if (k === "ArrowDown") v = clamp(v - step(e));
    move();
  });
  hue.addEventListener("keydown", (e) => {
    if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
    e.preventDefault(); h = clamp((h + (e.key === "ArrowRight" ? 1 : -1) * (e.shiftKey ? 20 : 3)) / 360 + 0, 0, 0.9999) * 360; move();
  });
  hex.addEventListener("input", () => { const t = hex.value.trim(); if (HEX.test(t)) { cur = t.toLowerCase(); [h, s, v] = hexToHsv(cur); paint(true); onInput?.(cur); } });
  pop.addEventListener("click", (e) => { const b = e.target.closest("[data-c]"); if (b) setHex(b.dataset.c); });
  if (window.EyeDropper) {
    const eye = $(".kp-eye"); eye.hidden = false;
    eye.addEventListener("click", () => new window.EyeDropper().open().then((r) => setHex(r.sRGBHex), () => {}));
  }
  const outside = (e) => { if (!pop.contains(e.target) && !anchor.contains(e.target)) close(); };
  const key = (e) => {
    if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); close(); anchor.focus(); }
    else if (e.key === "Enter" && e.target === hex) { e.preventDefault(); e.stopPropagation(); close(); anchor.focus(); }
  };
  const close = () => {
    if (open !== api) return;
    open = null;
    document.removeEventListener("pointerdown", outside, true); pop.removeEventListener("keydown", key);
    host.querySelector(".cb-form-body")?.removeEventListener("scroll", close);
    pop.remove();
    if (cur !== start) onChange?.(cur);
  };
  const api = { close };
  open = api;
  pop.addEventListener("keydown", key);
  document.addEventListener("pointerdown", outside, true);
  host.querySelector(".cb-form-body")?.addEventListener("scroll", close);
  host.append(pop);
  paint();
  const r = anchor.getBoundingClientRect(), w = pop.offsetWidth, ph = pop.offsetHeight;
  pop.style.left = clamp(r.left, 8, innerWidth - w - 8) + "px";
  pop.style.top = (r.bottom + 6 + ph > innerHeight - 8 ? Math.max(8, r.top - ph - 6) : r.bottom + 6) + "px";
  sv.focus({ preventScroll: true });
  return api;
}

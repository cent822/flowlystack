// Helpers shared by the Gallery modules: colours that follow the theme, the SVG box, the tooltip. Plain DOM and the global d3, no framework.
import { css } from "../util.js";

export { css };
export const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
export const fmtDay = d3.timeFormat("%b %-d, %Y");
export const fmtMonth = d3.timeFormat("%b %Y");

/** Topic group colour: the eight categorical series tokens (read at draw time, so a theme switch just redraws). */
export const cc = (k) => css(`--series-${(k % 8) + 1}`);
const AGENT = { claude: "--series-2", codex: "--series-1", ollama: "--series-3", markdown: "--series-1", pdf: "--series-2", text: "--series-3", json: "--series-5", jsonl: "--series-6" };   // agents (Prompts) and file types (Documents)
export const agentColor = (a) => css(AGENT[a] || "--series-4");

/** Empty `el` and put an SVG of the card's width and the given height in it. */
export function box(el, h) {
  el.innerHTML = "";
  const w = Math.max(160, el.clientWidth);
  const svg = d3.select(el).append("svg").attr("class", "gal-svg").attr("width", w).attr("height", h).attr("viewBox", [0, 0, w, h]);
  return { svg, w, h };
}

let tipEl = null;
/** Tooltip near the pointer; kept inside the window on every side. */
export function tip(e, html) {
  if (!tipEl) { tipEl = document.createElement("div"); tipEl.className = "gal-tip"; tipEl.setAttribute("role", "tooltip"); document.body.append(tipEl); }
  tipEl.innerHTML = html;
  tipEl.style.opacity = 1;
  const w = tipEl.offsetWidth, h = tipEl.offsetHeight;
  tipEl.style.left = Math.max(8, Math.min(innerWidth - w - 8, e.clientX + 14)) + "px";
  tipEl.style.top = Math.max(8, e.clientY + 14 + h > innerHeight - 8 ? e.clientY - h - 14 : e.clientY + 14) + "px";
}
export const untip = () => { if (tipEl) tipEl.style.opacity = 0; };

/** A short sentence in place of a chart that has nothing to draw (never an empty frame). */
export function note(el, text) {
  el.innerHTML = "";
  const p = document.createElement("p");
  p.className = "gal-soon";
  p.textContent = text;
  el.append(p);
}

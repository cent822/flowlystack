// Shared helpers: number formatting, theme-aware colors, tooltip.
export const fmt = {
  n: d3.format(","),
  compact(v) {
    if (v >= 1e9) return (v / 1e9).toFixed(2).replace(/\.?0+$/, "") + "B";
    if (v >= 1e6) return (v / 1e6).toFixed(v >= 1e7 ? 1 : 2).replace(/\.?0+$/, "") + "M";
    if (v >= 1e3) return (v / 1e3).toFixed(v >= 1e4 ? 0 : 1).replace(/\.0$/, "") + "k";
    return String(Math.round(v));
  },
  pct: (v) => (v * 100).toFixed(v < 0.1 ? 1 : 0) + "%",
  usd: (v) => "$" + v.toFixed(v < 10 ? 2 : 0),
  ago(ts) {
    const s = Date.now() / 1000 - ts;
    if (s < 60) return "just now";
    if (s < 3600) return Math.floor(s / 60) + "m ago";
    if (s < 86400) return Math.floor(s / 3600) + "h ago";
    return Math.floor(s / 86400) + "d ago";
  },
  until(ts) {
    const s = Math.max(0, ts - Date.now() / 1000);
    const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60);
    return h ? `${h}h ${m}m` : `${m}m`;
  },
};

// Read a CSS custom property at draw time so charts follow the active theme.
export const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

// Neon glow that follows the theme (strong in night mode, a whisper in day mode).
export const glow = (sel, color) => sel.style("filter", `drop-shadow(0 0 var(--glow-r) color-mix(in srgb, ${color} var(--glow-mix), transparent))`);

export const reducedMotion = () => matchMedia("(prefers-reduced-motion: reduce)").matches;

export function shortModel(m) {
  return (m || "unknown").replace(/^claude-/, "").replace(/-(\d+)-(\d+)$/, " $1.$2").replace(/^./, (c) => c.toUpperCase());
}

// Fixed identity -> color map, so a model keeps its hue regardless of filters or ranks.
const modelSlots = new Map();
export function modelColor(model) {
  if (!modelSlots.has(model)) modelSlots.set(model, modelSlots.size % 8 + 1);
  return `var(--series-${modelSlots.get(model)})`;
}
export function pinModelOrder(models) { [...models].sort().forEach((m) => modelColor(m)); }

const tip = () => document.getElementById("tooltip");
export const tooltip = {
  show(html, event) {
    const t = tip();
    t.innerHTML = html;
    t.hidden = false;
    const pad = 14, r = t.getBoundingClientRect();
    let x = event.clientX + pad, y = event.clientY + pad;
    if (x + r.width > innerWidth - 8) x = event.clientX - r.width - pad;
    if (y + r.height > innerHeight - 8) y = event.clientY - r.height - pad;
    t.style.left = Math.max(8, x) + "px";
    t.style.top = Math.max(8, y) + "px";
  },
  hide() { tip().hidden = true; },
};

export function svgIn(container, w, h) {
  const root = d3.select(container);
  root.selectAll("*").remove();
  return root.append("svg").attr("class", "chart-svg").attr("viewBox", `0 0 ${w} ${h}`)
    .attr("preserveAspectRatio", "xMidYMid meet");
}

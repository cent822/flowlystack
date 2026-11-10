// Day / night mode. One place that reads and writes it, so the top-bar toggle, the account menu and the Settings page stay
// in step. `mode()` is "light", "dark" or "system" (follow the OS). A change fires `flowlystack-theme` so charts can redraw.
const root = document.documentElement;
const KEYS = ["flowlystack-theme"];

export const mode = () => root.dataset.theme || "system";
export const isDark = () => (root.dataset.theme ? root.dataset.theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches);

export function setMode(m) {
  if (m === "system") {
    delete root.dataset.theme;
    try { KEYS.forEach((k) => localStorage.removeItem(k)); } catch (e) {}
  } else {
    root.dataset.theme = m;
    try { localStorage.setItem(KEYS[0], m); } catch (e) {}
  }
  dispatchEvent(new Event("flowlystack-theme"));
}

// The account button at the bottom of the sidebar and its small menu (who is signed in, Settings, day / night mode, Sign out).
// With login turned off (FLOWLYSTACK_AUTH=off) there is no name and no Sign out. Plain DOM, no framework.
import { isDark, setMode } from "./theme.js";
import { ICONS, registerCommands } from "./palette.js";
import { confirmDialog } from "./dialog.js";

const $ = (s) => document.querySelector(s);
const btn = $("#account-btn"), menu = $("#account-menu");

function place() {   // fixed, beside the button: the sidebar clips anything inside it (and is only 68px wide when collapsed)
  const r = btn.getBoundingClientRect();
  menu.style.left = `${r.left}px`;
  menu.style.bottom = `${innerHeight - r.top + 6}px`;
  menu.style.minWidth = `${Math.max(r.width, 220)}px`;
}

function setOpen(on) {
  if (on) {
    $("#account-theme-label").textContent = isDark() ? "Switch to day mode" : "Switch to night mode";
    $("#account-theme-icon").innerHTML = isDark() ? ICONS.theme : ICONS.moon;   // the icon shows what the item switches to, like its label: sun for day, moon for night
    menu.hidden = false;
    place();
  } else menu.hidden = true;
  btn.setAttribute("aria-expanded", String(on));
}

// Who is signed in (login is on unless the server runs with FLOWLYSTACK_AUTH=off, then there is nobody to show and no Sign out).
// The picture is the owner's PNG from /api/profile/avatar (?v= is its version), or, with none, the first letter of the name in the same circle.
let who = "";
const initial = (n) => (n.trim()[0] || "?").toUpperCase();
function paintAvatar(el, name, version) {
  el.classList.toggle("has-img", !!version);
  el.innerHTML = version ? `<img src="/api/profile/avatar?v=${version}" alt="" width="30" height="30" draggable="false">` : `<span class="av-letter" aria-hidden="true">${initial(name).replace(/[&<>"]/g, "")}</span>`;
}
function loadAccount() {
  return fetch("/api/auth/state").then((r) => r.json()).then((s) => {
    if (!s.enabled || !s.signed_in) return;
    who = s.username;
    $("#account-name").textContent = who;
    $("#account-user").hidden = false;
    $("#account-signout").hidden = false;
    $("#top-signout").hidden = false;   // the top-bar Sign out, next to the day / night switch; with login off there is nobody to sign out
    btn.querySelector(".nav-label").textContent = who;
    btn.title = `${who}: account and settings`;
    paintAvatar(btn.querySelector(".avatar"), who, s.avatar);
    paintAvatar($("#account-head-av"), who, s.avatar);
  }).catch(() => {});
}
loadAccount();
addEventListener("flowlystack-profile", loadAccount);   // Settings > Account changed the name or the picture

// The running version, a quiet line at the bottom of the menu (it links to Settings > About).
fetch("/api/about").then((r) => r.json()).then((a) => {
  if (!a.version || a.version === "unknown") return;
  const v = $("#account-version");
  v.textContent = `${a.name} v${a.version}`;
  v.hidden = false;
  dispatchEvent(new Event("flowlystack-version"));   // updatenotice.js adds its "update available" badge to this line
}).catch(() => {});

// Every way to sign out (the menu, the top bar, Settings > Account, ⌘K) asks first: it ends this browser's session.
export async function signOut() {
  const ok = await confirmDialog({ title: "Sign out?", message: "You will need your username and password to log in again.", confirmLabel: "Sign out" });
  if (!ok) return;
  try { await fetch("/api/auth/logout", { method: "POST" }); } catch (e) {}
  location.replace("/login");
}
registerCommands(() => (who ? [{ label: "Sign out", where: "Account", keywords: "log out logout", run: signOut }] : []));

$("#top-signout").addEventListener("click", signOut);
btn.addEventListener("click", () => setOpen(menu.hidden));
menu.addEventListener("click", (e) => {
  if (e.target.closest("#account-theme")) setMode(isDark() ? "light" : "dark");
  if (e.target.closest("#account-signout")) signOut();
  if (e.target.closest(".pr-menuitem, .acct-ver")) setOpen(false);   // Settings, What's new and the version are links: the hash change does the rest
});
// Leaving the sidebar with the pointer closes the menu (a short grace so a small slip does not); main.js then lets the auto-hide sidebar fold back,
// because an open menu is what held it open. The menu sits inside the sidebar, so being over the menu counts as being over the sidebar.
const side = $("#sidebar");
let leaveTimer = 0;
side.addEventListener("pointerenter", () => clearTimeout(leaveTimer));
side.addEventListener("pointerleave", (e) => {
  if (e.pointerType === "touch") return;
  clearTimeout(leaveTimer);
  leaveTimer = setTimeout(() => { if (!menu.hidden) setOpen(false); }, 160);
});
document.addEventListener("click", (e) => { if (!menu.hidden && !menu.contains(e.target) && !btn.contains(e.target)) setOpen(false); });
document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !menu.hidden) { setOpen(false); btn.focus(); } });
addEventListener("resize", () => { if (!menu.hidden) place(); });

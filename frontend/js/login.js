// Landing page: sign up (first visit only) and log in. Plain script. The server decides which one this is (GET /api/auth/state);
// a successful sign up or log in sets the session cookie and the browser goes on to the page it asked for (?next=, same-site paths only).
import { isDark, setMode as setTheme } from "./theme.js";   // the same day / night rule as the app (saved in this browser)

const $ = (s) => document.querySelector(s);

// Day / night switch (top right): the icon and label show what a press switches to, like the account menu.
const SUN = '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>';
const MOON = '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/></svg>';
function paintTheme() {
  const b = $("#theme-btn"), label = isDark() ? "Switch to day mode" : "Switch to night mode";
  b.innerHTML = isDark() ? SUN : MOON;
  b.setAttribute("aria-label", label);
  b.title = label;
}
$("#theme-btn").addEventListener("click", () => setTheme(isDark() ? "light" : "dark"));
addEventListener("flowlystack-theme", paintTheme);
matchMedia("(prefers-color-scheme: dark)").addEventListener("change", paintTheme);
paintTheme();

const stage = $("#stage"), form = $("#form"), err = $("#err"), go = $("#go");
let mode = "", ticket = "", useBackup = false;

const EYE = '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12z"/><circle cx="12" cy="12" r="2.8"/></svg>';
const EYE_OFF = '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 3l18 18M10.6 6a9 9 0 0 1 1.4-.1c6 0 9.5 6.1 9.5 6.1a16 16 0 0 1-3 3.7M6.4 7.5A16 16 0 0 0 2.5 12S6 18.5 12 18.5c1.5 0 2.8-.4 4-.9M9.9 9.9a3 3 0 0 0 4.2 4.2"/></svg>';

document.querySelectorAll(".eye").forEach((b) => {
  b.innerHTML = EYE;
  b.addEventListener("click", () => {
    const i = document.getElementById(b.dataset.for), show = i.type === "password";
    i.type = show ? "text" : "password";
    b.innerHTML = show ? EYE_OFF : EYE;
    b.setAttribute("aria-label", show ? "Hide password" : "Show password");
  });
});

function showErr(msg) {
  $("#err-text").textContent = msg || "";
  err.hidden = !msg;
  form.classList.toggle("has-err", !!msg);
}

function next() {   // only a path on this site: never "//host" or a backslash trick
  const n = new URLSearchParams(location.search).get("next") || "/";
  return n.startsWith("/") && !n.startsWith("//") && !n.startsWith("/\\") && !n.startsWith("/login") ? n : "/";
}

function setMode(m) {
  mode = m;
  stage.dataset.mode = m;
  document.title = m === "signup" ? "FlowlyStack: create your account" : m === "code" ? "FlowlyStack: two-step verification" : "FlowlyStack: log in";
  $("#p").autocomplete = m === "signup" ? "new-password" : "current-password";
  $("#p").setAttribute("aria-label", m === "signup" ? "Create password" : "Password");   // the visible label holds both texts, one hidden
  go.setAttribute("aria-label", m === "signup" ? "Create account" : m === "code" ? "Verify" : "Log in");
  if (m === "code") { setBackup(false); $("#c").value = ""; $("#c").focus(); } else $("#u").focus();
}

// The code step: an authenticator code (6 digits) or one of the backup codes.
function setBackup(on) {
  useBackup = on;
  $("#c").inputMode = on ? "text" : "numeric";
  $("#code-label").textContent = on ? "Backup code" : "6-digit code";
  $("#code-sub").textContent = on ? "Enter one of the backup codes you saved. Each one works only once." : "Enter the 6-digit code from your authenticator app.";
  $("#usebackup").textContent = on ? "Use the authenticator app instead" : "Use a backup code instead";
  $("#c").value = ""; showErr(""); $("#c").focus();
}
$("#usebackup").addEventListener("click", () => setBackup(!useBackup));
$("#back").addEventListener("click", () => { ticket = ""; $("#p").value = ""; $("#c").value = ""; showErr(""); setMode("login"); });

async function api(path, body) {
  const r = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const j = await r.json().catch(() => ({}));
  return { ok: r.ok, status: r.status, data: j, detail: typeof j.detail === "string" ? j.detail : "", retry: Number(r.headers.get("Retry-After")) || 0 };
}

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  if (mode === "code") return submitCode();
  const user = $("#u").value.trim(), pw = $("#p").value;
  if (!user || !pw) return showErr(mode === "signup" ? "Choose a username and a password." : "Enter your username and password.");
  if (mode === "signup") {
    if (pw.length < 8) return showErr("Password must be at least 8 characters.");
    if (pw !== $("#p2").value) return showErr("The two passwords differ.");
  }
  showErr("");
  go.disabled = true;
  try {
    const r = await api(mode === "signup" ? "/api/auth/signup" : "/api/auth/login", { username: user, password: pw });
    if (r.ok && r.data.twostep) { ticket = r.data.ticket; $("#p").value = ""; go.disabled = false; return setMode("code"); }   // the password was right; the code is next
    if (r.ok) return location.replace(next());
    showErr(r.status === 429 ? `Too many attempts. Try again in ${r.retry || 60} seconds.` : r.detail || "Something went wrong. Try again.");
  } catch (x) {
    showErr("Could not reach the server.");
  }
  go.disabled = false;
});

async function submitCode() {
  const code = $("#c").value.trim();
  if (!code) return showErr(useBackup ? "Enter a backup code." : "Enter the 6-digit code.");
  showErr("");
  go.disabled = true;
  try {
    const r = await api("/api/auth/login/code", { ticket, code });
    if (r.ok) return location.replace(next());
    if (r.status === 401 && /expired/i.test(r.detail)) { ticket = ""; setMode("login"); showErr(r.detail); }   // too many tries or too slow: password again
    else { showErr(r.status === 429 ? `Too many attempts. Try again in ${r.retry || 60} seconds.` : r.detail || "Something went wrong. Try again."); $("#c").select(); }
  } catch (x) {
    showErr("Could not reach the server.");
  }
  go.disabled = false;
}

$("#forgot").addEventListener("click", () => {
  const box = $("#reset"), open = box.hidden;
  box.hidden = !open;
  $("#forgot").setAttribute("aria-expanded", String(open));
});

fetch("/api/auth/state").then((r) => r.json()).then((s) => {
  if (!s.enabled || s.signed_in) return location.replace(next());   // login is off, or already signed in
  setMode(s.needs_setup ? "signup" : "login");
}).catch(() => { setMode("login"); showErr("Could not reach the server."); });

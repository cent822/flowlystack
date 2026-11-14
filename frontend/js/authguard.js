// Loaded first by index.html (a plain script, so it runs before the modules). If the server says the session is gone (401 on an
// /api call, or the live stream breaking while signed out), go to the login page and come back to this page afterwards.
(() => {
  let leaving = false;
  const toLogin = () => {
    if (leaving) return;
    leaving = true;
    const here = location.pathname + location.search + location.hash;
    location.replace("/login" + (here === "/" ? "" : "?next=" + encodeURIComponent(here)));
  };

  // Each tab signs in for itself: the cookie is shared by all tabs, so a tab without its own mark (a tab opened later, or after the
  // browser was closed) asks for the password again. The page stays hidden until the server has answered, so nothing flashes.
  let marked = true;
  try { marked = sessionStorage.getItem("flowlystack-tab") === "1"; } catch (e) {}
  const realFetch = window.fetch.bind(window);
  if (!marked) {
    document.documentElement.style.visibility = "hidden";
    realFetch("/api/auth/state").then((r) => r.json()).then((s) => {
      if (s.enabled) return toLogin();
      try { sessionStorage.setItem("flowlystack-tab", "1"); } catch (e) {}   // login is off: nothing to ask
      document.documentElement.style.visibility = "";
    }).catch(() => { document.documentElement.style.visibility = ""; });
  }

  window.fetch = async (...args) => {
    const res = await realFetch(...args);
    if (res.status === 401) {
      let path = "";
      try { path = new URL(typeof args[0] === "string" ? args[0] : args[0].url, location.href).pathname; } catch (e) {}
      if (path.startsWith("/api/") && !path.startsWith("/api/auth/")) toLogin();
    }
    return res;
  };

  const RealES = window.EventSource;   // an EventSource cannot see the status code: on an error ask the server whether we are still signed in
  window.EventSource = class extends RealES {
    constructor(...a) {
      super(...a);
      this.addEventListener("error", () => {
        realFetch("/api/auth/state").then((r) => r.json()).then((s) => { if (s.enabled && !s.signed_in) toLogin(); }).catch(() => {});
      });
    }
  };
})();

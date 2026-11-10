// Hash router: #/dashboard, #/prompts, #/prompts/<id>. Sidebar, header and footer stay put; only the page swaps.
const DEFAULT = "dashboard";
const pages = [...document.querySelectorAll("[data-page]")];
const links = [...document.querySelectorAll("#nav [data-route]")];
// Only the first path segment picks the page; deeper parts (#/prompts/<id>, ?query) belong to the page itself.
export const current = () => {
  const r = location.hash.replace(/^#\//, "").split(/[/?]/)[0];
  return pages.some((p) => p.dataset.page === r) ? r : DEFAULT;
};

function crumbs(group, label) {
  document.getElementById("crumbs").innerHTML =
    `<span class="grp">${group}</span><span class="sep">/</span><span class="cur">${label}</span>`;
}

export function startRouter(onChange) {
  const show = () => {
    const r = current();
    document.documentElement.dataset.route = r;   // keeps the first-paint CSS rule in app.css (`html[data-route]...#page-dashboard`) in step after the head script's one-time value
    pages.forEach((p) => { p.hidden = p.dataset.page !== r; });
    links.forEach((a) => {
      const on = a.dataset.route === r;
      a.classList.toggle("on", on);
      if (on) { a.setAttribute("aria-current", "page"); crumbs(a.closest(".nav-group").dataset.group, a.querySelector(".nav-label").textContent); } else a.removeAttribute("aria-current");
    });
    const page = pages.find((p) => p.dataset.page === r);   // a page without a sidebar link (Settings) names its own breadcrumb
    if (page?.dataset.crumbLabel) crumbs(page.dataset.crumbGroup, page.dataset.crumbLabel);
    document.getElementById("panel").scrollTo(0, 0);
    onChange(r);
  };
  addEventListener("hashchange", show);
  show();
}

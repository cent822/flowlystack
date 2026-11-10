// Repeats: the same idea, written again. One lane per group of near-identical prompts (up to 14): its prompts are dots on the time axis and an arc joins
// two in a row, so a long arc means you came back to it months later. Click an arc or a dot (or Select) to pick the group; "Promote as template" saves one of
// them to Prompt Studio.
import { box, tip, untip, cc, esc, fmtMonth, note } from "../common.js";
import { S, data, apply, noun } from "../state.js";
import { promoteGroup } from "../actions.js";

function select(gi) {
  const g = data().snap.repeats[gi];
  S.sel = S.sel && S.sel.src === "group" && S.sel.key === gi ? null : { label: `${g.n} similar ${noun()}`, ids: new Set(g.ids), src: "group", key: gi };
  apply();
}

export function repeats(el) {
  const { R, snap, first, last } = data(), G = snap.repeats;
  if (!G.length) return note(el, snap.mode === "documents" ? "No two documents say nearly the same thing yet." : "No prompt has been written three or more times in nearly the same words yet.");
  el.innerHTML = "";
  const chart = document.createElement("div"), list = document.createElement("div");
  list.className = "gal-rep";
  el.append(chart, list);
  const lane = 30, h = G.length * lane + 34, { svg, w } = box(chart, h), left = 54, x = d3.scaleTime(+last - +first < 7 * 864e5 ? [new Date(+first - 3.5 * 864e5), new Date(+last + 3.5 * 864e5)] : [first, last], [left, w - 14]);   // everything in one week (a bulk import): give the axis room so its ticks are days, not milliseconds
  const on = (gi) => !S.sel || S.sel.src !== "group" || S.sel.key === gi;
  svg.append("g").attr("class", "gal-ax").attr("transform", `translate(0,${h - 24})`).call(d3.axisBottom(x).ticks(Math.max(3, w / 100)).tickSizeOuter(0));
  G.forEach((g, gi) => {
    const base = 8 + (gi + 1) * lane - 6, m = g.ids.map((i) => R[i]).sort((a, b) => a.t - b.t);
    svg.append("line").attr("x1", left).attr("x2", w - 14).attr("y1", base).attr("y2", base).attr("stroke", "var(--text-muted)").attr("opacity", 0.7);
    svg.append("text").attr("x", 0).attr("y", base + 4).attr("class", "gal-lbl").style("font-weight", 600).attr("opacity", on(gi) ? 1 : 0.4).text(g.n + "×");
    for (let i = 0; i < m.length - 1; i++) {
      const x1 = x(m[i].t), x2 = x(m[i + 1].t), r = Math.abs(x2 - x1) / 2;
      svg.append("path").attr("d", `M${x1},${base}A${Math.max(r, 0.5)},${Math.min(Math.max(r, 5), lane - 8)} 0 0 1 ${x2},${base}`).attr("fill", "none").attr("stroke", cc(g.cluster)).attr("stroke-width", 2)
        .attr("opacity", on(gi) ? 0.95 : 0.15).style("cursor", "pointer").on("mousemove", (e) => tip(e, `<b>${g.n}× the same idea</b><br>${esc(g.sample)}`)).on("mouseleave", untip).on("click", () => select(gi));
    }
    svg.append("g").selectAll("circle").data(m).join("circle").attr("cx", (d) => x(d.t)).attr("cy", base).attr("r", 3).attr("fill", cc(g.cluster)).attr("opacity", on(gi) ? 1 : 0.3).style("cursor", "pointer").on("click", () => select(gi));
  });
  const a = document.activeElement, was = a && a.dataset ? (a.dataset.sel !== undefined ? `[data-sel="${a.dataset.sel}"]` : a.dataset.tpl !== undefined ? `[data-tpl="${a.dataset.tpl}"]` : "") : "";   // keep the keyboard focus on the same button after a redraw
  list.innerHTML = G.map((g, gi) => `<div class="gal-rg${S.sel && S.sel.src === "group" && S.sel.key === gi ? " on" : ""}"><div><b>${g.n}×</b> <span class="muted small">${fmtMonth(new Date(g.first * 1000))} → ${fmtMonth(new Date(g.last * 1000))}</span></div>
    <div class="gal-rgs">${esc(g.sample)}</div><div class="gal-rga"><button type="button" class="btn btn-sm btn-glow" data-sel="${gi}">${S.sel && S.sel.src === "group" && S.sel.key === gi ? "Unselect" : "Select"}</button>${snap.mode === "documents" ? "" : `<button type="button" class="btn btn-sm btn-glow" data-tpl="${gi}">Promote as template</button>`}</div></div>`).join("");
  if (was) list.querySelector(was)?.focus();
  list.onclick = (e) => {
    const s = e.target.closest("[data-sel]"), t = e.target.closest("[data-tpl]");
    if (s) select(+s.dataset.sel); else if (t) promoteGroup(+t.dataset.tpl);
  };
}

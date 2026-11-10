import { fmt, shortModel, tooltip } from "../util.js";

const CELLS = 50;
export function contextBars(el, sessions) {
  const rows = [...sessions].sort((a, b) => (b.live - a.live) || (b.last_ts - a.last_ts)).slice(0, 6);
  const root = d3.select(el);
  root.selectAll("*").remove();
  const row = root.selectAll(".ctx-row").data(rows).join("div").attr("class", "ctx-row");

  const top = row.append("div").attr("class", "ctx-top");
  const name = top.append("div").attr("class", "ctx-name");
  name.append("i").attr("class", (d) => (d.live ? "live-dot" : "idle-dot")).attr("title", (d) => (d.live ? "Running now" : "Not running"));
  name.append("span").attr("class", "t").text((d) => d.title);
  top.append("div").attr("class", "ctx-num").html((d) => `${fmt.compact(d.ctx)} / ${fmt.compact(d.ctx_window)} · <b>${fmt.pct(d.ctx_pct)}</b>`);

  row.append("div").attr("class", "cells")
    .attr("role", "meter").attr("aria-valuemin", 0).attr("aria-valuemax", 100)
    .attr("aria-valuenow", (d) => Math.round(d.ctx_pct * 100)).attr("aria-label", (d) => `Context used, ${d.title}`)
    .each(function (d) {
      // a session using 0.4% of 1M should still show a sliver, so round up once there is any usage
      const filled = d.ctx > 0 ? Math.max(1, Math.round(d.ctx_pct * CELLS)) : 0;
      const cls = d.ctx_pct >= 0.9 ? "crit" : d.ctx_pct >= 0.75 ? "warn" : "on";
      d3.select(this).selectAll("i").data(d3.range(CELLS)).join("i").attr("class", (i) => (i < filled ? cls : null));
    })
    .on("mousemove", (e, d) => tooltip.show(`<b>${d.title}</b><br>${shortModel(d.model)}<br>${fmt.n(d.ctx)} tokens in context<br>${fmt.pct(d.ctx_pct)} of ${fmt.compact(d.ctx_window)}`, e))
    .on("mouseleave", tooltip.hide);
  return rows.length;
}

import { css, fmt, glow, modelColor, shortModel, svgIn, tooltip } from "../util.js";

// Stacked area of billable tokens per day, split by model. Gaps are filled with zero so the time axis stays honest.
export function areaChart(el, legendEl, daily, days) {
  const W = 1100, H = 320, m = { t: 12, r: 12, b: 28, l: 52 };
  const end = d3.timeDay.floor(new Date()), start = d3.timeDay.offset(end, -(days - 1));
  const dates = d3.timeDay.range(start, d3.timeDay.offset(end, 1));
  const models = [...new Set(daily.rows.map((r) => r.model))].sort();
  const byKey = new Map(daily.rows.map((r) => [r.d + "|" + r.model, r.t]));
  const fmtKey = d3.timeFormat("%Y-%m-%d");
  const data = dates.map((d) => ({ date: d, ...Object.fromEntries(models.map((mo) => [mo, byKey.get(fmtKey(d) + "|" + mo) || 0])) }));
  const series = d3.stack().keys(models)(data);

  const x = d3.scaleTime().domain([start, end]).range([m.l, W - m.r]);
  const y = d3.scaleLinear().domain([0, (d3.max(series, (s) => d3.max(s, (p) => p[1])) || 1) * 1.08]).nice().range([H - m.b, m.t]);
  const svg = svgIn(el, W, H);

  svg.append("g").attr("class", "axis").selectAll("line").data(y.ticks(5)).join("line").attr("class", "grid-line")
    .attr("x1", m.l).attr("x2", W - m.r).attr("y1", y).attr("y2", y);
  svg.append("g").selectAll("text").data(y.ticks(5)).join("text").attr("x", m.l - 8).attr("y", y).attr("dy", "0.32em").attr("text-anchor", "end").text((d) => fmt.compact(d));
  const xt = days <= 14 ? d3.timeDay.every(1) : days <= 30 ? d3.timeDay.every(5) : d3.timeWeek.every(2);
  svg.append("g").selectAll("text").data(x.ticks(xt)).join("text").attr("x", x).attr("y", H - 8).attr("text-anchor", "middle").text(d3.timeFormat("%b %-d"));

  const area = d3.area().x((d) => x(d.data.date)).y0((d) => y(d[0])).y1((d) => y(d[1])).curve(d3.curveMonotoneX);
  const line = d3.line().x((d) => x(d.data.date)).y((d) => y(d[1])).curve(d3.curveMonotoneX);
  const g = svg.append("g");
  const defs = svg.append("defs");
  series.forEach((s, i) => {
    const c = modelColor(s.key);
    const id = `area-grad-${i}`;   // vertical fade: strong under the line, gone at the baseline
    const lg = defs.append("linearGradient").attr("id", id).attr("x1", 0).attr("x2", 0).attr("y1", 0).attr("y2", 1);
    lg.append("stop").attr("offset", "0%").attr("stop-color", c).attr("stop-opacity", 0.5);
    lg.append("stop").attr("offset", "100%").attr("stop-color", c).attr("stop-opacity", 0.03);
    g.append("path").attr("d", area(s)).attr("fill", `url(#${id})`);
    glow(g.append("path").attr("d", line(s)).attr("fill", "none").attr("stroke", c).attr("stroke-width", 2).attr("stroke-linejoin", "round"), c);
  });

  // a pulsing marker on each model's most recent point, so the live edge of the data is easy to find
  series.forEach((s) => {
    const li = d3.maxIndex(data, (d, i) => (d[s.key] > 0 ? i : -1));
    if (li < 0 || !(data[li][s.key] > 0)) return;
    const c = modelColor(s.key), px = x(data[li].date), py = y(s[li][1]);
    svg.append("circle").attr("class", "live-ring").attr("cx", px).attr("cy", py).attr("r", 5).attr("fill", c).attr("pointer-events", "none");
    glow(svg.append("circle").attr("class", "live-core").attr("cx", px).attr("cy", py).attr("r", 4.5).attr("fill", c).attr("stroke", css("--canvas-soft")).attr("stroke-width", 2).attr("pointer-events", "none"), c);
  });

  // crosshair + tooltip across the full plot width
  const cross = svg.append("line").attr("y1", m.t).attr("y2", H - m.b).attr("stroke", css("--text-muted")).attr("stroke-dasharray", "3 3").style("display", "none");
  const dots = svg.append("g");
  svg.append("rect").attr("x", m.l).attr("y", m.t).attr("width", W - m.l - m.r).attr("height", H - m.t - m.b).attr("fill", "transparent")
    .on("mousemove", (e) => {
      const [px] = d3.pointer(e);
      const i = d3.bisector((d) => d.date).center(data, x.invert(px));
      const d = data[i], cx = x(d.date);
      cross.style("display", null).attr("x1", cx).attr("x2", cx);
      dots.selectAll("circle").data(series).join("circle").attr("cx", cx).attr("cy", (s) => y(s[i][1])).attr("r", 4)
        .attr("fill", (s) => modelColor(s.key)).attr("stroke", css("--canvas-soft")).attr("stroke-width", 2);
      const total = d3.sum(models, (mo) => d[mo]);
      tooltip.show(`<b>${d3.timeFormat("%a, %b %-d")(d.date)}</b>` +
        models.map((mo) => `<div class="row"><span><i style="background:${modelColor(mo)}"></i>${shortModel(mo)}</span><b>${fmt.compact(d[mo])}</b></div>`).join("") +
        `<div class="row"><span>Total</span><b>${fmt.compact(total)}</b></div>` +
        (daily.sessions[fmtKey(d.date)] ? `<div class="row"><span>New sessions</span><b>${daily.sessions[fmtKey(d.date)]}</b></div>` : ""), e);
    })
    .on("mouseleave", () => { cross.style("display", "none"); dots.selectAll("*").remove(); tooltip.hide(); });

  d3.select(legendEl).html(models.map((mo) => `<span><i style="background:${modelColor(mo)};--c:${modelColor(mo)}"></i>${shortModel(mo)}</span>`).join(""));
  return { models, data };
}

export function areaTable(el, { models, data }) {
  const rows = [...data].reverse().filter((d) => models.some((m) => d[m]));
  d3.select(el).html(`<div class="table-wrap"><table><thead><tr><th>Day</th>${models.map((m) => `<th class="num">${shortModel(m)}</th>`).join("")}</tr></thead><tbody>` +
    rows.map((d) => `<tr><td>${d3.timeFormat("%a %b %-d")(d.date)}</td>${models.map((m) => `<td class="num">${fmt.n(d[m])}</td>`).join("")}</tr>`).join("") + `</tbody></table></div>`);
}

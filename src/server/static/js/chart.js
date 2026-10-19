import { isoDate, signedPercent } from "./views.js";

/* ─────────────────────────────── Gráfico de desempenho ──────────────────── */

const SVG_NS = "http://www.w3.org/2000/svg";
const MONTHS = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"];

function svgElement(tag, attributes = {}) {
  const element = document.createElementNS(SVG_NS, tag);
  for (const [name, value] of Object.entries(attributes)) element.setAttribute(name, value);
  return element;
}

// Passo "redondo" para os rótulos do eixo: 1, 2, 2,5 ou 5 vezes uma potência de 10.
function niceStep(rough) {
  const power = 10 ** Math.floor(Math.log10(rough));
  return [1, 2, 2.5, 5, 10].map((factor) => factor * power).find((step) => step >= rough);
}

function shortDate(time, longSpan) {
  const date = new Date(time);
  const month = MONTHS[date.getUTCMonth()];
  return longSpan
    ? `${month}/${String(date.getUTCFullYear()).slice(2)}`
    : `${String(date.getUTCDate()).padStart(2, "0")} ${month}`;
}

// Último ponto da série até `time`: as séries têm calendários diferentes (cripto
// negocia no fim de semana; a bolsa, não).
function pointAt(points, time) {
  let low = 0;
  let high = points.length - 1;
  if (time <= points[0][0]) return points[0];
  while (low < high) {
    const middle = Math.ceil((low + high) / 2);
    if (points[middle][0] <= time) low = middle;
    else high = middle - 1;
  }
  return points[low];
}

// Retorno acumulado de cada ativo, todos partindo de zero na mesma escala.
// As cores seguem a ordem fixa da paleta pela posição do ativo; o índice de
// referência fica em cinza tracejado, recessivo.
export function performanceChart(seriesList) {
  const series = seriesList.map((item, index) => ({
    ...item,
    color: item.is_index ? "var(--series-index)" : `var(--series-${index + 1})`,
    points: item.points.map(([day, value]) => [Date.parse(`${day}T00:00:00Z`), value]),
  }));

  const root = document.createElement("figure");
  root.className = "perf-chart";

  const caption = document.createElement("figcaption");
  caption.className = "tool-view-caption";
  caption.textContent = "Retorno acumulado, com proventos";
  root.append(caption);

  if (series.length > 1) {
    const legend = document.createElement("div");
    legend.className = "perf-legend";
    for (const item of series) {
      const entry = document.createElement("span");
      entry.className = "perf-legend-item";
      const swatch = document.createElement("span");
      swatch.className = `perf-swatch${item.is_index ? " is-index" : ""}`;
      swatch.style.setProperty("--swatch", item.color);
      entry.append(swatch, document.createTextNode(item.label));
      legend.append(entry);
    }
    root.append(legend);
  }

  const plot = document.createElement("div");
  plot.className = "perf-plot";
  const tooltip = document.createElement("div");
  tooltip.className = "perf-tooltip";
  tooltip.hidden = true;
  root.append(plot);

  const summary = series
    .map((item) => `${item.label} ${signedPercent(item.points[item.points.length - 1][1])}`)
    .join(", ");

  const draw = () => {
    const width = plot.clientWidth;
    if (!width) return; // ainda escondido: o detalhe da consulta está fechado
    const narrow = width < 480;
    const height = narrow ? 200 : 240;
    const margin = { top: 10, right: narrow ? 92 : 128, bottom: 24, left: 44 };
    const innerWidth = width - margin.left - margin.right;
    const innerHeight = height - margin.top - margin.bottom;

    const times = series.flatMap((item) => item.points.map(([time]) => time));
    const values = series.flatMap((item) => item.points.map(([, value]) => value));
    const t0 = Math.min(...times);
    const t1 = Math.max(...times);
    const step = niceStep(Math.max((Math.max(...values, 0) - Math.min(...values, 0)) / 4, 0.5));
    const y0 = Math.floor(Math.min(...values, 0) / step) * step;
    const y1 = Math.ceil(Math.max(...values, 0) / step) * step;

    const x = (time) => margin.left + ((time - t0) / (t1 - t0 || 1)) * innerWidth;
    const y = (value) => margin.top + (1 - (value - y0) / (y1 - y0 || 1)) * innerHeight;

    const chart = svgElement("svg", {
      width, height, viewBox: `0 0 ${width} ${height}`, role: "img",
      "aria-label": `Retorno acumulado no período: ${summary}.`,
    });

    // Grade e eixo vertical, recessivos; a linha do zero, um pouco mais firme.
    for (let value = y0; value <= y1 + step / 2; value += step) {
      chart.append(svgElement("line", {
        x1: margin.left, x2: margin.left + innerWidth, y1: y(value), y2: y(value),
        class: Math.abs(value) < step / 2 ? "perf-zero" : "perf-grid",
      }));
      const label = svgElement("text", { x: margin.left - 8, y: y(value), class: "perf-axis", "text-anchor": "end", dy: "0.32em" });
      label.textContent = signedPercent(Math.round(value * 100) / 100).replace(",00", "");
      chart.append(label);
    }

    const longSpan = t1 - t0 > 400 * 864e5;
    const ticks = narrow ? 3 : 5;
    for (let index = 0; index < ticks; index++) {
      const time = t0 + ((t1 - t0) * index) / (ticks - 1);
      const label = svgElement("text", {
        x: x(time), y: height - 6, class: "perf-axis",
        "text-anchor": index === 0 ? "start" : index === ticks - 1 ? "end" : "middle",
      });
      label.textContent = shortDate(time, longSpan);
      chart.append(label);
    }

    // O índice vai por baixo; os ativos, por cima.
    for (const item of [...series].sort((a, b) => Number(b.is_index) - Number(a.is_index))) {
      chart.append(svgElement("path", {
        d: item.points.map(([time, value], index) => `${index ? "L" : "M"}${x(time).toFixed(1)},${y(value).toFixed(1)}`).join(""),
        class: `perf-line${item.is_index ? " is-index" : ""}`,
        style: `stroke: ${item.color}`,
      }));
    }

    // Rótulo direto no fim de cada linha, afastados para não se sobreporem.
    const ends = series
      .map((item) => ({ item, last: item.points[item.points.length - 1] }))
      .map((end) => ({ ...end, labelY: y(end.last[1]) }))
      .sort((a, b) => a.labelY - b.labelY);
    for (let index = 1; index < ends.length; index++) {
      ends[index].labelY = Math.max(ends[index].labelY, ends[index - 1].labelY + 14);
    }
    const overflow = ends.length ? ends[ends.length - 1].labelY - (height - margin.bottom) : 0;
    if (overflow > 0) ends.forEach((end) => { end.labelY -= overflow; });
    for (const { item, last, labelY } of ends) {
      chart.append(svgElement("circle", {
        cx: x(last[0]), cy: y(last[1]), r: 4, class: "perf-dot", style: `fill: ${item.color}`,
      }));
      const label = svgElement("text", { x: margin.left + innerWidth + 10, y: labelY, dy: "0.32em", class: "perf-label" });
      label.textContent = `${narrow ? "" : `${item.label} `}${signedPercent(last[1])}`;
      chart.append(label);
    }

    // Camada de hover: linha vertical e os valores de cada ativo naquela data.
    const crosshair = svgElement("line", { y1: margin.top, y2: margin.top + innerHeight, class: "perf-crosshair" });
    const markers = series.map((item) => svgElement("circle", { r: 4, class: "perf-dot", style: `fill: ${item.color}` }));
    const hover = svgElement("g", { visibility: "hidden" });
    hover.append(crosshair, ...markers);
    chart.append(hover);

    const zone = svgElement("rect", {
      x: margin.left, y: margin.top, width: innerWidth, height: innerHeight, class: "perf-zone",
    });
    zone.addEventListener("pointermove", (event) => {
      const bounds = chart.getBoundingClientRect();
      const time = t0 + ((event.clientX - bounds.left - margin.left) / innerWidth) * (t1 - t0);
      const anchor = pointAt(series[0].points, time)[0];
      crosshair.setAttribute("x1", x(anchor));
      crosshair.setAttribute("x2", x(anchor));

      tooltip.replaceChildren();
      const heading = document.createElement("div");
      heading.className = "perf-tooltip-date";
      heading.textContent = isoDate(new Date(anchor).toISOString());
      tooltip.append(heading);
      series.forEach((item, index) => {
        const [time, value] = pointAt(item.points, anchor);
        markers[index].setAttribute("cx", x(time));
        markers[index].setAttribute("cy", y(value));
        const row = document.createElement("div");
        row.className = "perf-tooltip-row";
        const swatch = document.createElement("span");
        swatch.className = `perf-swatch${item.is_index ? " is-index" : ""}`;
        swatch.style.setProperty("--swatch", item.color);
        const name = document.createElement("span");
        name.textContent = item.label;
        const amount = document.createElement("strong");
        amount.textContent = signedPercent(value);
        row.append(swatch, name, amount);
        tooltip.append(row);
      });

      hover.setAttribute("visibility", "visible");
      tooltip.hidden = false;
      const left = x(anchor) + 12;
      tooltip.style.left = `${left + tooltip.offsetWidth > width ? x(anchor) - tooltip.offsetWidth - 12 : left}px`;
      tooltip.style.top = `${margin.top}px`;
    });
    zone.addEventListener("pointerleave", () => {
      hover.setAttribute("visibility", "hidden");
      tooltip.hidden = true;
    });
    chart.append(zone);

    plot.replaceChildren(chart, tooltip);
  };

  // Desenha quando o quadro ganha largura (o detalhe abre) e a cada mudança dela.
  new ResizeObserver(draw).observe(plot);
  return root;
}

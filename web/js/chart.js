/* Minimale SVG-Charts ohne externe Bibliothek.
   Zwei Formen: Liniendiagramm (mehrere Serien, eine gemeinsame Y-Achse)
   und Flaechendiagramm (eine Serie, Drawdown).
   Beide bekommen Fadenkreuz und Tooltip - ein HTML-Chart, der nicht auf
   Hover reagiert, verschenkt die Haelfte der Information. */
(function (global) {
  "use strict";

  const NS = "http://www.w3.org/2000/svg";
  const VIEW_W = 960;

  const INK_MUTED = "#898781";
  const GRID = "#1f242c";
  const AXIS = "#2e343d";
  const SURFACE = "#12161c";

  function el(name, attrs) {
    const node = document.createElementNS(NS, name);
    for (const key in attrs) {
      if (attrs[key] !== null && attrs[key] !== undefined) {
        node.setAttribute(key, attrs[key]);
      }
    }
    return node;
  }

  const money = (v) =>
    (v < 0 ? "-$" : "$") +
    Math.abs(Math.round(v)).toLocaleString("de-DE");

  const percent = (v) => v.toFixed(1).replace(".", ",") + " %";

  function shortDate(iso) {
    const d = new Date(iso);
    return d.toLocaleDateString("de-DE", { day: "2-digit", month: "short", year: "numeric" });
  }

  /* "Schoene" Achsenschritte: 1, 2, 2.5 oder 5 mal Zehnerpotenz. */
  function niceStep(span, targetTicks) {
    const raw = span / Math.max(targetTicks, 1);
    const power = Math.pow(10, Math.floor(Math.log10(raw) || 0));
    const norm = raw / power;
    const step = norm <= 1 ? 1 : norm <= 2 ? 2 : norm <= 2.5 ? 2.5 : norm <= 5 ? 5 : 10;
    return step * power;
  }

  function ticksFor(min, max, count) {
    if (!isFinite(min) || !isFinite(max) || min === max) return [min];
    const step = niceStep(max - min, count);
    const out = [];
    for (let v = Math.ceil(min / step) * step; v <= max + step * 1e-9; v += step) out.push(v);
    return out;
  }

  /* Gemeinsames Geruest: Rahmen, Gitter, Achsen, Tooltip, Fadenkreuz. */
  function buildFrame(container, opts) {
    container.textContent = "";
    container.style.position = "relative";

    const height = opts.height || 340;
    const pad = { top: 16, right: 74, bottom: 30, left: 62 };
    const plotW = VIEW_W - pad.left - pad.right;
    const plotH = height - pad.top - pad.bottom;

    const svg = el("svg", {
      viewBox: `0 0 ${VIEW_W} ${height}`,
      preserveAspectRatio: "none",
      role: "img",
      "aria-label": opts.label || "Diagramm",
    });
    svg.style.height = height + "px";
    svg.style.width = "100%";
    container.appendChild(svg);

    const tooltip = document.createElement("div");
    tooltip.className = "tooltip";
    container.appendChild(tooltip);

    return { svg, tooltip, pad, plotW, plotH, height };
  }

  function drawGrid(frame, yTicks, yScale, formatY) {
    const { svg, pad, plotW, plotH } = frame;
    yTicks.forEach((value) => {
      const y = yScale(value);
      if (y < pad.top - 1 || y > pad.top + plotH + 1) return;
      // Hairline, durchgezogen - gestrichelte Gitter lesen sich als Schwelle.
      svg.appendChild(el("line", {
        x1: pad.left, x2: pad.left + plotW, y1: y, y2: y,
        stroke: GRID, "stroke-width": 1, "shape-rendering": "crispEdges",
      }));
      const label = el("text", {
        x: pad.left - 9, y: y + 3.5, "text-anchor": "end",
        fill: INK_MUTED, "font-size": 10.5,
      });
      label.textContent = formatY(value);
      svg.appendChild(label);
    });
    svg.appendChild(el("line", {
      x1: pad.left, x2: pad.left + plotW, y1: pad.top + plotH, y2: pad.top + plotH,
      stroke: AXIS, "stroke-width": 1, "shape-rendering": "crispEdges",
    }));
  }

  function drawTimeAxis(frame, points, xScale) {
    const { svg, pad, plotH } = frame;
    const count = Math.min(6, points.length);
    for (let i = 0; i < count; i += 1) {
      const idx = Math.round((i / Math.max(count - 1, 1)) * (points.length - 1));
      const label = el("text", {
        x: xScale(idx),
        y: pad.top + plotH + 18,
        "text-anchor": i === 0 ? "start" : i === count - 1 ? "end" : "middle",
        fill: INK_MUTED,
        "font-size": 10.5,
      });
      label.textContent = new Date(points[idx].t).toLocaleDateString("de-DE", {
        month: "short",
        year: "numeric",
      });
      svg.appendChild(label);
    }
  }

  /* Hover: Fadenkreuz plus Punkte auf allen Serien am selben X. */
  function attachHover(frame, points, xScale, seriesList, valueAt, formatValue) {
    const { svg, tooltip, pad, plotW, plotH } = frame;

    const crosshair = el("line", {
      y1: pad.top, y2: pad.top + plotH,
      stroke: AXIS, "stroke-width": 1, opacity: 0,
    });
    svg.appendChild(crosshair);

    const markers = seriesList.map((s) =>
      svg.appendChild(el("circle", {
        r: 4, fill: s.color, stroke: SURFACE, "stroke-width": 2, opacity: 0,
      }))
    );

    // Trefferflaeche ueber dem ganzen Plot - groesser als jede Marke.
    const hit = el("rect", {
      x: pad.left, y: pad.top, width: plotW, height: plotH, fill: "transparent",
    });
    svg.appendChild(hit);

    function hide() {
      crosshair.setAttribute("opacity", 0);
      markers.forEach((m) => m.setAttribute("opacity", 0));
      tooltip.classList.remove("visible");
    }

    function move(event) {
      const box = svg.getBoundingClientRect();
      const ratio = VIEW_W / box.width;
      const svgX = (event.clientX - box.left) * ratio;
      const index = Math.max(0, Math.min(points.length - 1,
        Math.round(((svgX - pad.left) / plotW) * (points.length - 1))));

      const x = xScale(index);
      crosshair.setAttribute("x1", x);
      crosshair.setAttribute("x2", x);
      crosshair.setAttribute("opacity", 1);

      let rows = `<div class="tooltip-date">${shortDate(points[index].t)}</div>`;
      seriesList.forEach((s, i) => {
        const value = valueAt(s, index);
        if (value === null) {
          markers[i].setAttribute("opacity", 0);
          return;
        }
        markers[i].setAttribute("cx", x);
        markers[i].setAttribute("cy", s.yScale(value));
        markers[i].setAttribute("opacity", 1);
        rows +=
          `<div class="tooltip-row"><span>` +
          `<i class="legend-swatch" style="background:${s.color}"></i>${s.name}` +
          `</span><b>${formatValue(value)}</b></div>`;
      });

      tooltip.innerHTML = rows;
      tooltip.classList.add("visible");

      const left = (x / VIEW_W) * box.width;
      const flip = left > box.width - 180;
      tooltip.style.left = Math.max(0, flip ? left - tooltip.offsetWidth - 14 : left + 14) + "px";
      tooltip.style.top = "10px";
    }

    hit.addEventListener("mousemove", move);
    hit.addEventListener("mouseleave", hide);
    hit.addEventListener("touchmove", (e) => {
      if (e.touches[0]) move(e.touches[0]);
    }, { passive: true });
    hit.addEventListener("touchend", hide);
  }

  /* --- Liniendiagramm: mehrere Serien, EINE Y-Achse --- */
  function line(container, options) {
    const seriesList = (options.series || []).filter((s) => s.points && s.points.length > 1);
    if (!seriesList.length) {
      container.innerHTML = '<p class="hint">Keine Daten zum Anzeigen.</p>';
      return;
    }

    const base = seriesList[0].points;
    const frame = buildFrame(container, { height: options.height || 340, label: options.label });
    const { svg, pad, plotW, plotH } = frame;

    let min = Infinity;
    let max = -Infinity;
    seriesList.forEach((s) => s.points.forEach((p) => {
      if (p.v === null) return;
      if (p.v < min) min = p.v;
      if (p.v > max) max = p.v;
    }));
    const headroom = (max - min) * 0.06 || Math.abs(max) * 0.06 || 1;
    min -= headroom;
    max += headroom;

    const xScale = (i) => pad.left + (i / Math.max(base.length - 1, 1)) * plotW;
    const yScale = (v) => pad.top + plotH - ((v - min) / (max - min || 1)) * plotH;
    seriesList.forEach((s) => { s.yScale = yScale; });

    const formatY = options.formatY || money;
    drawGrid(frame, ticksFor(min, max, 5), yScale, formatY);
    drawTimeAxis(frame, base, xScale);

    seriesList.forEach((s) => {
      let path = "";
      let open = false;
      s.points.forEach((p, i) => {
        if (p.v === null) { open = false; return; }
        path += (open ? "L" : "M") + xScale(i).toFixed(2) + " " + yScale(p.v).toFixed(2) + " ";
        open = true;
      });
      svg.appendChild(el("path", {
        d: path.trim(),
        fill: "none",
        stroke: s.color,
        "stroke-width": 2,
        "stroke-linejoin": "round",
        "stroke-linecap": "round",
      }));

      // Endpunkt direkt beschriften - so traegt nie die Farbe allein.
      const last = s.points[s.points.length - 1];
      if (last && last.v !== null) {
        const label = el("text", {
          x: pad.left + plotW + 8,
          y: Math.min(Math.max(yScale(last.v) + 3.5, pad.top + 6), pad.top + plotH),
          fill: s.color,
          "font-size": 11,
          "font-weight": 600,
        });
        label.textContent = formatY(last.v);
        svg.appendChild(label);
      }
    });

    attachHover(frame, base, xScale, seriesList,
      (s, i) => (s.points[i] ? s.points[i].v : null), formatY);
  }

  /* --- Flaechendiagramm fuer den Drawdown (eine Serie, immer <= 0) --- */
  function area(container, options) {
    const points = (options.points || []).filter((p) => p.v !== null);
    if (points.length < 2) {
      container.innerHTML = '<p class="hint">Keine Daten zum Anzeigen.</p>';
      return;
    }

    const frame = buildFrame(container, { height: options.height || 150, label: options.label });
    const { svg, pad, plotW, plotH } = frame;
    const color = options.color || "#d03b3b";

    const min = Math.min(...points.map((p) => p.v), 0);
    const max = 0;
    const xScale = (i) => pad.left + (i / Math.max(points.length - 1, 1)) * plotW;
    const yScale = (v) => pad.top + ((v - max) / (min - max || 1)) * plotH;

    const formatY = options.formatY || percent;
    drawGrid(frame, ticksFor(min, max, 3), yScale, formatY);
    drawTimeAxis(frame, points, xScale);

    const gradientId = "dd-" + Math.random().toString(36).slice(2, 9);
    const defs = el("defs", {});
    const gradient = el("linearGradient", { id: gradientId, x1: 0, y1: 0, x2: 0, y2: 1 });
    gradient.appendChild(el("stop", { offset: "0%", "stop-color": color, "stop-opacity": 0.32 }));
    gradient.appendChild(el("stop", { offset: "100%", "stop-color": color, "stop-opacity": 0.03 }));
    defs.appendChild(gradient);
    svg.appendChild(defs);

    let path = "";
    points.forEach((p, i) => {
      path += (i ? "L" : "M") + xScale(i).toFixed(2) + " " + yScale(p.v).toFixed(2) + " ";
    });

    const zero = yScale(0);
    svg.appendChild(el("path", {
      d: path + `L${xScale(points.length - 1).toFixed(2)} ${zero} L${xScale(0).toFixed(2)} ${zero} Z`,
      fill: `url(#${gradientId})`,
      stroke: "none",
    }));
    svg.appendChild(el("path", {
      d: path.trim(), fill: "none", stroke: color, "stroke-width": 2, "stroke-linejoin": "round",
    }));

    const series = [{ name: options.name || "Drawdown", color, points, yScale }];
    attachHover(frame, points, xScale, series,
      (s, i) => (s.points[i] ? s.points[i].v : null), formatY);
  }

  global.Chart = { line, area, money, percent, shortDate };
})(window);

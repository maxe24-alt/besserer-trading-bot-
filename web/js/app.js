/* Steuert das Dashboard: Katalog laden, Backtest anstossen, Ergebnis zeigen. */
(function () {
  "use strict";

  const SERIES_STRATEGY = "#199e70";
  const SERIES_HOLD = "#c98500";
  const DRAWDOWN = "#d03b3b";

  const $ = (id) => document.getElementById(id);

  const state = {
    catalog: null,
    run: null,        // letztes Backtest-Ergebnis
    selectedKey: null, // im Chart gezeigte Strategie
  };

  const fmtMoney = (v) =>
    (v < 0 ? "-$" : "+$") + Math.abs(Math.round(v)).toLocaleString("de-DE");
  const fmtPercent = (v) => (v >= 0 ? "+" : "") + v.toFixed(1).replace(".", ",") + " %";
  const fmtPlain = (v) => v.toFixed(1).replace(".", ",") + " %";

  async function api(path, body) {
    const response = await fetch(path, {
      method: body ? "POST" : "GET",
      headers: body ? { "Content-Type": "application/json" } : undefined,
      body: body ? JSON.stringify(body) : undefined,
    });
    const data = await response.json();
    if (!response.ok || data.error) throw new Error(data.error || `HTTP ${response.status}`);
    return data;
  }

  function setStatus(message, isError) {
    const node = $("status");
    node.textContent = message || "";
    node.classList.toggle("error", Boolean(isError));
  }

  /* ---------- Aufbau der Bedienelemente ---------- */
  function fillSelect(select, items, valueKey, labelFn, initial) {
    select.textContent = "";
    items.forEach((item) => {
      const option = document.createElement("option");
      option.value = valueKey ? item[valueKey] : item;
      option.textContent = labelFn ? labelFn(item) : item;
      select.appendChild(option);
    });
    if (initial) select.value = initial;
  }

  function buildStrategyPicker(strategies) {
    const grid = $("strategy-grid");
    grid.textContent = "";
    strategies.forEach((entry) => {
      const label = document.createElement("label");
      label.className = "strategy-option";
      label.dataset.category = entry.category;

      const box = document.createElement("input");
      box.type = "checkbox";
      box.value = entry.key;
      box.checked = true;

      const text = document.createElement("div");
      const name = document.createElement("strong");
      name.textContent = entry.label;
      const note = document.createElement("em");
      note.textContent = entry.category;
      text.append(name, note);

      label.append(box, text);
      grid.appendChild(label);
    });
  }

  function selectedStrategies() {
    return Array.from($("strategy-grid").querySelectorAll("input:checked")).map((b) => b.value);
  }

  function readSettings() {
    return {
      symbol: $("symbol").value,
      interval: $("interval").value,
      start: $("start").value,
      end: $("end").value || null,
      provider: $("provider").value,
      capital: Number($("capital").value) || 100000,
      fee: Number($("fee").value) || 0,
      slippage: Number($("slippage").value) || 0,
      exposure: (Number($("exposure").value) || 100) / 100,
      allow_short: $("allow-short").checked,
    };
  }

  /* ---------- Ergebnisdarstellung ---------- */
  function renderMeta(run, settings) {
    $("subtitle-symbol").textContent = run.symbol.replace("=F", "");
    $("subtitle").firstChild.textContent = `${run.results.length} STRATEGIEN vs `;
    $("meta-symbol").textContent = `${run.symbol} · ${run.interval} · ${run.bars} Bars`;
    $("meta-range").textContent =
      `${Chart.shortDate(run.start)} – ${Chart.shortDate(run.end)}`;
    $("meta-costs").textContent =
      `$${Number(run.initial_capital).toLocaleString("de-DE")} Start · ` +
      `${settings.fee} % / Seite · ${settings.slippage} Tick · ` +
      (settings.allow_short ? "Long + Short" : "nur Long");
  }

  function tile(label, value, tone, note) {
    const box = document.createElement("div");
    box.className = "tile";
    box.innerHTML =
      `<div class="tile-label">${label}</div>` +
      `<div class="tile-value ${tone || ""}"></div>` +
      `<div class="tile-note"></div>`;
    box.querySelector(".tile-value").textContent = value;
    box.querySelector(".tile-note").innerHTML = note || "";
    return box;
  }

  function renderTiles(run) {
    const tiles = $("tiles");
    tiles.textContent = "";
    const winner = run.results[0];
    const hold = run.benchmark;

    if (winner) {
      tiles.appendChild(tile(
        `Sieger — ${winner.label}`,
        fmtMoney(winner.metrics.net_pnl),
        winner.metrics.net_pnl >= 0 ? "good" : "bad",
        `${fmtPercent(winner.metrics.return_pct)} · ${winner.metrics.trades} Trades · PF ${winner.metrics.profit_factor}`
      ));
    }
    if (hold) {
      tiles.appendChild(tile(
        "Benchmark — Buy & Hold",
        fmtMoney(hold.metrics.net_pnl),
        "hold",
        `${fmtPercent(hold.metrics.return_pct)} · einfach nichts tun`
      ));
      const beaten = run.beaten_by_benchmark;
      tiles.appendChild(tile(
        "Schlechter als Nichtstun",
        `${beaten} von ${run.results.length}`,
        beaten > run.results.length / 2 ? "bad" : "good",
        beaten === run.results.length
          ? "keine einzige schlägt den Markt"
          : "bekannt ≠ profitabel"
      ));
    }
    if (winner && hold) {
      const milder = Math.abs(winner.metrics.max_drawdown_pct) < Math.abs(hold.metrics.max_drawdown_pct);
      tiles.appendChild(tile(
        "Max Drawdown — Sieger",
        fmtPlain(winner.metrics.max_drawdown_pct),
        milder ? "good" : "bad",
        `Buy &amp; Hold: <strong>${fmtPlain(hold.metrics.max_drawdown_pct)}</strong> · ` +
        (milder ? "weniger Schmerz" : "nicht ruhiger als Nichtstun")
      ));
    }
    tiles.hidden = false;
  }

  function renderLeaderboard(run) {
    const body = $("leaderboard-body");
    body.textContent = "";

    const rows = run.results.slice();
    const scale = Math.max(1, ...rows.concat(run.benchmark ? [run.benchmark] : [])
      .map((r) => Math.abs(r.metrics.net_pnl)));

    const makeRow = (result, rank, isBenchmark) => {
      const tr = document.createElement("tr");
      tr.tabIndex = 0;
      tr.dataset.key = result.key;
      if (isBenchmark) tr.classList.add("benchmark");
      if (result.key === state.selectedKey) tr.classList.add("is-selected");

      const m = result.metrics;
      const barWidth = Math.max(2, (Math.abs(m.net_pnl) / scale) * 66);

      tr.innerHTML =
        `<td class="num rank">${rank}</td>` +
        `<td><span class="strategy-cell"><span></span>` +
        `<i class="bar${m.net_pnl < 0 ? " loss" : ""}" style="width:${barWidth.toFixed(0)}px"></i>` +
        `</span></td>` +
        `<td class="num pnl ${m.net_pnl >= 0 ? "good" : "bad"}">${fmtMoney(m.net_pnl)}</td>` +
        `<td class="num">${fmtPercent(m.return_pct)}</td>` +
        `<td class="num">${fmtPlain(m.max_drawdown_pct)}</td>` +
        `<td class="num">${m.trades}</td>` +
        `<td class="num">${isBenchmark ? "–" : fmtPlain(m.win_rate_pct)}</td>` +
        `<td class="num">${isBenchmark || !m.profit_factor ? "–" : m.profit_factor.toFixed(1).replace(".", ",")}</td>`;

      tr.querySelector(".strategy-cell span").textContent =
        isBenchmark ? `${result.label} — Benchmark` : result.label;

      const choose = () => selectStrategy(result.key);
      tr.addEventListener("click", choose);
      tr.addEventListener("keydown", (e) => {
        if (e.key === "Enter" || e.key === " ") { e.preventDefault(); choose(); }
      });
      return tr;
    };

    rows.forEach((result, i) => body.appendChild(makeRow(result, i + 1, false)));
    if (run.benchmark) body.appendChild(makeRow(run.benchmark, "–", true));
  }

  function renderLegend(strategyName) {
    $("chart-legend").innerHTML =
      `<span class="legend-item"><i class="legend-swatch" style="background:${SERIES_STRATEGY}"></i>${strategyName}</span>` +
      `<span class="legend-item"><i class="legend-swatch" style="background:${SERIES_HOLD}"></i>Buy &amp; Hold</span>`;
  }

  function findResult(key) {
    const run = state.run;
    if (!run) return null;
    if (run.benchmark && run.benchmark.key === key) return run.benchmark;
    return run.results.find((r) => r.key === key) || null;
  }

  function selectStrategy(key) {
    const result = findResult(key);
    if (!result) return;
    state.selectedKey = key;

    document.querySelectorAll("#leaderboard-body tr").forEach((tr) => {
      tr.classList.toggle("is-selected", tr.dataset.key === key);
    });

    $("chart-series-name").textContent = result.label;
    renderLegend(result.label);

    const series = [{ name: result.label, color: SERIES_STRATEGY, points: result.equity }];
    const hold = state.run.benchmark;
    if (hold && hold.key !== key) {
      series.push({ name: "Buy & Hold", color: SERIES_HOLD, points: hold.equity });
    }

    Chart.line($("equity-chart"), {
      series,
      height: 330,
      formatY: Chart.money,
      label: `Kapitalkurve ${result.label} gegen Buy and Hold`,
    });
    Chart.area($("drawdown-chart"), {
      points: result.drawdown,
      color: DRAWDOWN,
      name: "Drawdown",
      height: 150,
      formatY: fmtPlain,
      label: `Drawdown-Verlauf ${result.label}`,
    });

    $("pine-strategy").value = key;
    loadPine(key);
  }

  /* ---------- Pine ---------- */
  async function loadPine(key) {
    const code = $("pine-code");
    const pineStatus = $("pine-status");
    const option = Array.from($("pine-strategy").options).find((o) => o.value === key);
    if (!option) {
      $("pine-panel").hidden = true;
      return;
    }
    $("pine-panel").hidden = false;
    pineStatus.textContent = "lädt …";
    pineStatus.classList.remove("error");
    try {
      const settings = readSettings();
      const data = await api("/api/pine", Object.assign({}, settings, { strategy: key }));
      code.textContent = data.source;
      $("pine-symbol").textContent = data.tradingview;
      pineStatus.textContent = "";
    } catch (error) {
      code.textContent = "";
      pineStatus.textContent = error.message;
      pineStatus.classList.add("error");
    }
  }

  /* ---------- Backtest ---------- */
  async function runBacktest(event) {
    if (event) event.preventDefault();
    const keys = selectedStrategies();
    if (!keys.length) {
      setStatus("Bitte mindestens eine Strategie auswählen.", true);
      return;
    }

    const button = $("run-button");
    button.disabled = true;
    setStatus(`Lade Daten und rechne ${keys.length} Strategien …`);

    try {
      const settings = readSettings();
      const run = await api("/api/backtest", Object.assign({}, settings, { strategies: keys }));
      state.run = run;

      const pineOptions = state.catalog.strategies
        .filter((s) => s.has_pine && keys.includes(s.key))
        .map((s) => ({ key: s.key, label: s.label }));
      fillSelect($("pine-strategy"), pineOptions, "key", (s) => s.label);

      renderMeta(run, settings);
      renderTiles(run);
      state.selectedKey = run.results.length ? run.results[0].key : null;
      renderLeaderboard(run);
      $("results").hidden = false;
      if (state.selectedKey) selectStrategy(state.selectedKey);

      const failed = Object.keys(run.failures || {});
      setStatus(
        failed.length
          ? `Fertig, aber ${failed.length} Strategie(n) schlugen fehl: ${failed.join(", ")}`
          : `Fertig — ${run.bars} Bars, ${run.results.length} Strategien.`,
        failed.length > 0
      );
    } catch (error) {
      setStatus(error.message, true);
    } finally {
      button.disabled = false;
    }
  }

  /* ---------- Start ---------- */
  async function init() {
    $("end").value = new Date().toISOString().slice(0, 10);

    try {
      state.catalog = await api("/api/catalog");
    } catch (error) {
      setStatus("Katalog konnte nicht geladen werden: " + error.message, true);
      return;
    }

    fillSelect($("symbol"), state.catalog.instruments, "symbol",
      (i) => `${i.symbol} — ${i.name}`, "ES=F");
    fillSelect($("interval"), state.catalog.intervals, null, null, "1d");
    fillSelect($("provider"), state.catalog.providers, "key",
      (p) => p.name + (p.needs_key ? " (API-Key nötig)" : ""), "yahoo");
    buildStrategyPicker(state.catalog.strategies);

    $("settings").addEventListener("submit", runBacktest);

    document.querySelectorAll(".picker-actions button").forEach((button) => {
      button.addEventListener("click", () => {
        const mode = button.dataset.select;
        $("strategy-grid").querySelectorAll(".strategy-option").forEach((option) => {
          const box = option.querySelector("input");
          box.checked = mode === "all" ? true
            : mode === "none" ? false
            : option.dataset.category === mode;
        });
      });
    });

    $("pine-strategy").addEventListener("change", (e) => loadPine(e.target.value));
    $("pine-copy").addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText($("pine-code").textContent);
        $("pine-status").textContent = "in die Zwischenablage kopiert";
      } catch {
        $("pine-status").textContent = "Kopieren nicht erlaubt — Code bitte markieren";
      }
    });
    $("pine-download").addEventListener("click", () => {
      const key = $("pine-strategy").value;
      const blob = new Blob([$("pine-code").textContent], { type: "text/plain" });
      const link = document.createElement("a");
      link.href = URL.createObjectURL(blob);
      link.download = `${key}_${$("symbol").value.replace(/[^A-Za-z0-9]/g, "")}.pine`;
      link.click();
      URL.revokeObjectURL(link.href);
    });

    runBacktest();
  }

  document.addEventListener("DOMContentLoaded", init);
})();

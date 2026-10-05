(() => {
  'use strict';

  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
  const csrf = $('meta[name="csrf-token"]')?.content || '';
  const palette = { ink: '#273b31', muted: '#87938a', grid: '#e9ede7', green: '#286f4d', lime: '#a8c57c', coral: '#d77b65', blue: '#6d9aaa', gold: '#d4ad63', soft: '#edf3e8' };
  const money = (value, compact = true) => {
    if (value === null || value === undefined || Number.isNaN(Number(value))) return 'n/a';
    const n = Number(value);
    const sign = n < 0 ? '-$' : '$';
    const abs = Math.abs(n);
    if (compact && abs >= 1e9) return `${sign}${(abs / 1e9).toFixed(2)}B`;
    if (compact && abs >= 1e6) return `${sign}${(abs / 1e6).toFixed(2)}M`;
    if (compact && abs >= 1e3) return `${sign}${(abs / 1e3).toFixed(1)}K`;
    return `${sign}${abs.toLocaleString('en-US', { maximumFractionDigits: 0 })}`;
  };
  const pct = (value, digits = 1) => value === null || value === undefined || Number.isNaN(Number(value)) ? 'n/a' : `${(Number(value) * 100).toFixed(digits)}%`;
  const signedMoney = (value) => `${value >= 0 ? '+' : '-'}${money(Math.abs(value))}`;
  const escapeHtml = (value) => String(value ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
  const dateLabel = (value) => {
    if (!value) return '';
    const date = new Date(`${String(value).slice(0, 7)}-01T00:00:00`);
    return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleDateString('en-US', { month: 'short', year: '2-digit' });
  };
  const formatKpi = (key, value) => {
    if (key === 'mrr' || key === 'arr' || key === 'arpa' || key === 'cac' || key === 'ltv' || key.startsWith('ttm_')) return money(value);
    if (key.includes('margin') || key.includes('growth') || key.includes('retention') || key === 'nrr' || key === 'grr' || key === 'discount_rate' || key === 'monthly_logo_churn') return pct(value);
    if (key === 'ltv_to_cac') return value == null ? 'n/a' : `${Number(value).toFixed(1)}×`;
    if (key === 'cac_payback_months') return value == null ? 'n/a' : `${Number(value).toFixed(1)} mo`;
    if (key === 'active_customers') return value == null ? 'n/a' : Math.round(Number(value)).toLocaleString();
    if (key === 'rule_of_40') return pct(value);
    return value == null ? 'n/a' : String(value);
  };
  const api = async (url, options = {}) => {
    const headers = new Headers(options.headers || {});
    if (options.method && options.method !== 'GET') headers.set('X-CSRF-Token', csrf);
    if (options.body && !(options.body instanceof FormData)) headers.set('Content-Type', 'application/json');
    const response = await fetch(url, { credentials: 'same-origin', ...options, headers });
    const body = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(body.detail || `Request failed (${response.status})`);
    return body;
  };
  const notifyError = (message) => {
    let node = $('#app-toast');
    if (!node) {
      node = document.createElement('div');
      node.id = 'app-toast';
      node.className = 'flash flash-error';
      node.setAttribute('role', 'alert');
      $('.page-wrap')?.prepend(node);
    }
    if (node) node.textContent = message;
  };
  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const easeOutCubic = (t) => 1 - (1 - t) ** 3;
  const animateValue = (node, value, formatter, duration = 700) => {
    if (!node) return;
    const target = Number(value);
    if (reducedMotion || document.hidden || value === null || value === undefined || Number.isNaN(target)) {
      node.textContent = formatter(value);
      return;
    }
    const start = performance.now();
    const frame = (now) => {
      if (document.hidden) {
        node.textContent = formatter(target);
        return;
      }
      const t = Math.min(1, (now - start) / duration);
      node.textContent = formatter(target * easeOutCubic(t));
      if (t < 1) requestAnimationFrame(frame);
    };
    requestAnimationFrame(frame);
  };
  const pulse = (node) => {
    if (!node || reducedMotion) return;
    node.classList.remove('pulse-value');
    void node.offsetWidth;
    node.classList.add('pulse-value');
  };
  const initChart = (id, option) => {
    const node = document.getElementById(id);
    if (!node || !window.echarts) return null;
    let chart = echarts.getInstanceByDom(node);
    if (!chart) chart = echarts.init(node, null, { renderer: 'canvas' });
    chart.setOption(option, true);
    if (!node.dataset.resizeBound) {
      node.dataset.resizeBound = 'true';
      window.addEventListener('resize', () => chart.resize(), { passive: true });
    }
    return chart;
  };
  const baseAxis = (extra = {}) => ({ axisLine: { lineStyle: { color: '#dce3dc' } }, axisTick: { show: false }, axisLabel: { color: palette.muted, fontSize: 9 }, splitLine: { lineStyle: { color: palette.grid, type: 'dashed' } }, ...extra });
  const baseTooltip = { trigger: 'axis', backgroundColor: '#17352b', borderWidth: 0, textStyle: { color: '#f4f6ef', fontSize: 10 }, axisPointer: { type: 'line', lineStyle: { color: '#9cac91', type: 'dashed' } } };
  const legend = (data, top = 0) => ({ top, right: 3, itemWidth: 8, itemHeight: 8, icon: 'circle', textStyle: { color: palette.muted, fontSize: 9 }, data });
  const motion = reducedMotion
    ? { animation: false }
    : { animationDuration: 900, animationEasing: 'cubicOut', animationDelay: (i) => Math.min(i * 16, 420), animationDurationUpdate: 450 };
  const paintKpis = (data) => {
    $$('[data-kpi]').forEach((node) => {
      const key = node.dataset.kpi;
      animateValue(node, data[key], (v) => formatKpi(key, v));
      if (key === 'mom_growth') node.classList.toggle('negative', (data[key] ?? 0) < 0);
    });
  };
  const getKpis = async () => {
    const data = await api('/api/kpis');
    paintKpis(data);
    return data;
  };
  const paintPnl = (rows, id = 'dashboard-pnl') => {
    const labels = rows.map((r) => dateLabel(r.month));
    initChart(id, {
      ...motion, color: [palette.green, palette.lime, palette.coral], tooltip: { ...baseTooltip, valueFormatter: money },
      legend: legend(['Revenue', 'Gross profit', 'Operating income']), grid: { left: 48, right: 18, top: 38, bottom: 27 },
      xAxis: { type: 'category', data: labels, ...baseAxis({ boundaryGap: false, axisLabel: { ...baseAxis().axisLabel, interval: Math.max(0, Math.floor(labels.length / 10)) } }) },
      yAxis: { type: 'value', ...baseAxis({ axisLabel: { ...baseAxis().axisLabel, formatter: (v) => money(v) } }) },
      series: [
        { name: 'Revenue', type: 'line', smooth: .25, showSymbol: false, lineStyle: { width: 2.4 }, areaStyle: { opacity: .045 }, data: rows.map((r) => r.revenue) },
        { name: 'Gross profit', type: 'line', smooth: .25, showSymbol: false, lineStyle: { width: 2 }, data: rows.map((r) => r.gross_profit) },
        { name: 'Operating income', type: 'line', smooth: .25, showSymbol: false, lineStyle: { width: 1.8 }, data: rows.map((r) => r.operating_income) },
      ],
    });
  };
  const paintProfit = (rows, chartId = 'dashboard-profitability', tableId = null) => {
    const names = rows.map((r) => r.group);
    initChart(chartId, {
      ...motion, color: [palette.green, palette.lime, palette.coral], tooltip: { ...baseTooltip, trigger: 'axis', valueFormatter: (v) => money(v) },
      legend: legend(['Revenue', 'Gross profit', 'Gross margin']), grid: { left: 54, right: 46, top: 39, bottom: 32 },
      xAxis: { type: 'category', data: names, ...baseAxis({ axisLabel: { ...baseAxis().axisLabel, interval: 0, rotate: names.length > 5 ? 20 : 0 } }) },
      yAxis: [{ type: 'value', ...baseAxis({ axisLabel: { ...baseAxis().axisLabel, formatter: (v) => money(v) } }) }, { type: 'value', min: 0, max: 1, ...baseAxis({ splitLine: { show: false }, axisLabel: { ...baseAxis().axisLabel, formatter: (v) => `${(v * 100).toFixed(0)}%` } }) }],
      series: [
        { name: 'Revenue', type: 'bar', barMaxWidth: 27, itemStyle: { borderRadius: [2, 2, 0, 0] }, data: rows.map((r) => r.revenue) },
        { name: 'Gross profit', type: 'bar', barMaxWidth: 27, itemStyle: { borderRadius: [2, 2, 0, 0] }, data: rows.map((r) => r.gross_profit) },
        { name: 'Gross margin', type: 'line', yAxisIndex: 1, smooth: .2, showSymbol: true, symbolSize: 5, lineStyle: { width: 2 }, data: rows.map((r) => r.gross_margin) },
      ],
    });
    if (tableId) {
      const body = $(`#${tableId} tbody`);
      if (!body) return;
      const maxRevenue = Math.max(...rows.map((r) => r.revenue), 1);
      body.innerHTML = rows.map((r) => `<tr><td class="cell-main">${escapeHtml(r.group)}</td><td>${Number(r.customers).toLocaleString()}</td><td>${money(r.revenue)}</td><td class="${r.gross_profit < 0 ? 'negative' : ''}">${money(r.gross_profit)}</td><td class="${r.gross_margin < .35 ? 'negative' : 'positive'}">${pct(r.gross_margin)}</td><td>${pct(r.discount_rate)}</td><td class="bar-cell"><span class="mini-bar"><i style="width:${Math.min(100, 100 * r.revenue / maxRevenue)}%"></i></span>${pct(r.revenue_share)}</td></tr>`).join('');
    }
  };
  const paintSignals = (rows, target = 'dashboard-signals', maxRows = 3) => {
    const node = $(`#${target}`);
    if (!node) return;
    if (!rows.length) {
      node.innerHTML = '<div class="signal-item"><span class="signal-mark"></span><div><strong>No material signals found</strong><p>That can be a good sign. Check again as new months arrive.</p></div></div>';
      return;
    }
    node.innerHTML = rows.slice(0, maxRows).map((r) => `<div class="signal-item"><span class="signal-mark ${r.severity}"></span><div><strong>${escapeHtml(r.title)}</strong><p>${escapeHtml(r.message)}</p></div></div>`).join('');
  };

  async function dashboard() {
    try {
      await Promise.all([getKpis(), api('/api/pnl').then((rows) => paintPnl(rows.slice(-30))), api('/api/profitability?dimension=segment').then((rows) => paintProfit(rows)), api('/api/anomalies').then((rows) => paintSignals(rows))]);
    } catch (error) { notifyError(error.message); }
  }

  async function insights() {
    const period = $('#insight-period');
    const render = async () => {
      try {
        const [result, pnl] = await Promise.all([api(`/api/insights?period_months=${period?.value || 1}`), api('/api/pnl')]);
        animateValue($('#insight-change'), result.gross_profit.change, signedMoney);
        $('#insight-change').classList.toggle('negative', result.gross_profit.change < 0);
        $('#insight-period-label').textContent = `${result.current_period} vs ${result.previous_period}`;
        const narrative = $('#insight-narrative');
        narrative.innerHTML = result.narrative.map((line) => `<p>${escapeHtml(line)}</p>`).join('');
        const drivers = $('#insight-drivers');
        const max = Math.max(...result.drivers.map((d) => Math.abs(d.impact)), 1);
        drivers.innerHTML = result.drivers.length ? result.drivers.map((d) => `<div class="driver-row"><div class="driver-topline"><strong>${escapeHtml(d.driver)}</strong><b class="${d.impact < 0 ? 'negative' : 'positive'}">${signedMoney(d.impact)}</b></div><div class="driver-bar"><i class="${d.impact < 0 ? 'negative' : ''}" style="width:${Math.max(2, Math.abs(d.impact) / max * 100)}%"></i></div></div>`).join('') : '<p class="empty-table">No material drivers in this comparison.</p>';
        const water = result.waterfall.steps;
        const labels = [result.previous_period, ...water.map((d) => d.label), result.current_period];
        const values = [result.waterfall.start, ...water.map((d) => d.impact), result.waterfall.end];
        initChart('insights-waterfall', { ...motion, tooltip: { ...baseTooltip, valueFormatter: money }, grid: { left: 54, right: 20, top: 12, bottom: 65 }, xAxis: { type: 'category', data: labels, ...baseAxis({ axisLabel: { ...baseAxis().axisLabel, interval: 0, rotate: 20 } }) }, yAxis: { type: 'value', ...baseAxis({ axisLabel: { ...baseAxis().axisLabel, formatter: money } }) }, series: [{ type: 'bar', data: values.map((v, i) => ({ value: v, itemStyle: { color: i === 0 || i === values.length - 1 ? palette.green : v >= 0 ? palette.lime : palette.coral } })), barMaxWidth: 32, itemStyle: { borderRadius: [3, 3, 0, 0] } }] });
        paintPnl(pnl, 'insights-trend');
      } catch (error) { notifyError(error.message); }
    };
    period?.addEventListener('change', render);
    await render();
  }

  async function revenue() {
    try {
      const [bridge, cohorts] = await Promise.all([api('/api/mrr-bridge'), api('/api/retention')]);
      await getKpis();
      const labels = bridge.map((r) => dateLabel(r.month));
      initChart('revenue-bridge', { ...motion, color: [palette.green, palette.lime, palette.blue, palette.gold, palette.coral], tooltip: { ...baseTooltip, valueFormatter: money }, legend: legend(['New', 'Expansion', 'Reactivation', 'Contraction', 'Churn']), grid: { left: 49, right: 18, top: 38, bottom: 30 }, xAxis: { type: 'category', data: labels, ...baseAxis({ axisLabel: { ...baseAxis().axisLabel, interval: Math.max(0, Math.floor(labels.length / 10)) } }) }, yAxis: { type: 'value', ...baseAxis({ axisLabel: { ...baseAxis().axisLabel, formatter: money } }) }, series: [
        { name: 'New', type: 'bar', stack: 'positive', barMaxWidth: 19, data: bridge.map((r) => r.new) },
        { name: 'Expansion', type: 'bar', stack: 'positive', barMaxWidth: 19, data: bridge.map((r) => r.expansion) },
        { name: 'Reactivation', type: 'bar', stack: 'positive', barMaxWidth: 19, data: bridge.map((r) => r.reactivation) },
        { name: 'Contraction', type: 'bar', stack: 'negative', barMaxWidth: 19, data: bridge.map((r) => r.contraction) },
        { name: 'Churn', type: 'bar', stack: 'negative', barMaxWidth: 19, data: bridge.map((r) => r.churn) },
      ] });
      const rows = cohorts.cohorts.cohorts;
      const maxPeriods = Math.min(13, Math.max(0, ...rows.map((r) => r.retention.length)));
      const table = $('#cohort-table');
      const head = $('thead', table);
      const body = $('tbody', table);
      head.innerHTML = `<tr><th>COHORT</th><th>ACCOUNTS</th>${Array.from({ length: maxPeriods }, (_, i) => `<th>Q${i}</th>`).join('')}</tr>`;
      body.innerHTML = rows.map((row) => `<tr><td><strong>${escapeHtml(row.cohort)}</strong></td><td>${row.customers}</td>${Array.from({ length: maxPeriods }, (_, i) => { const val = row.retention[i]; if (val == null) return '<td></td>'; const hue = val >= 1 ? 100 : Math.max(0, 100 - (1 - val) * 150); return `<td class="heat-cell" style="background:hsl(${hue},36%,${val >= 1 ? 91 : 94}%)">${pct(val, 0)}</td>`; }).join('')}</tr>`).join('') || '<tr><td colspan="15" class="empty-table">Not enough cohort history to show retention.</td></tr>';
    } catch (error) { notifyError(error.message); }
  }

  async function profitability() {
    const dimension = $('#profit-dimension');
    const render = async () => {
      try { paintProfit(await api(`/api/profitability?dimension=${dimension.value}`), 'profit-chart', 'profit-table'); } catch (error) { notifyError(error.message); }
    };
    dimension?.addEventListener('change', render);
    await getKpis().catch(() => {});
    await render();
  }

  async function unitEconomics() {
    const dimension = $('#unit-dimension');
    const render = async () => {
      try {
        const rows = await api(`/api/unit-economics${dimension.value ? `?by=${dimension.value}` : ''}`);
        const table = $('#unit-table tbody');
        table.innerHTML = rows.map((r) => `<tr><td class="cell-main">${escapeHtml(r.group)}</td><td>${r.active_customers}</td><td>${r.new_customers}</td><td>${pct(r.monthly_logo_churn)}</td><td>${pct(r.gross_margin)}</td><td>${money(r.cac)}</td><td>${money(r.ltv)}</td><td>${r.ltv_to_cac == null ? 'n/a' : `${r.ltv_to_cac.toFixed(1)}×`}</td><td>${r.cac_payback_months == null ? 'n/a' : `${r.cac_payback_months.toFixed(1)} mo`}</td></tr>`).join('') || '<tr><td colspan="9" class="empty-table">No unit-economics data is available.</td></tr>';
        if (!dimension.value && rows[0]) {
          const data = { ltv_to_cac: rows[0].ltv_to_cac, cac_payback_months: rows[0].cac_payback_months, cac: rows[0].cac, ltv: rows[0].ltv };
          $$('[data-kpi]').forEach((node) => { animateValue(node, data[node.dataset.kpi], (v) => formatKpi(node.dataset.kpi, v)); });
        } else if (dimension.value) await getKpis();
      } catch (error) { notifyError(error.message); }
    };
    dimension?.addEventListener('change', render);
    await render();
  }

  async function forecast() {
    const horizon = $('#forecast-horizon');
    const render = async () => {
      try {
        const result = await api(`/api/forecast?horizon=${horizon.value}`);
        animateValue($('#forecast-revenue'), result.summary.revenue, money);
        animateValue($('#forecast-gp'), result.summary.gross_profit, money);
        animateValue($('#forecast-oi'), result.summary.operating_income, money);
        animateValue($('#forecast-arr'), result.summary.exit_arr, money);
        const accuracy = result.summary.backtest_mape_3m;
        $('#forecast-accuracy').textContent = accuracy == null ? 'Backtest accuracy is unavailable until there are at least 12 months of data.' : `Three-month holdout revenue MAPE: ${pct(accuracy)}. This compares historical forecast errors; it is not a guarantee of future accuracy.`;
        $('#forecast-method').textContent = result.method + '. COGS and OpEx are forecast separately; no pipeline, seasonality or causal events are modeled.';
        const history = result.history;
        const future = result.forecast;
        const allLabels = [...history.map((r) => dateLabel(r.month)), ...future.map((r) => dateLabel(r.month))];
        const actual = [...history.map((r) => r.revenue), ...Array(future.length).fill(null)];
        const prediction = [...Array(Math.max(0, history.length - 1)).fill(null), history.at(-1)?.revenue ?? null, ...future.map((r) => r.revenue)];
        const lower = [...Array(history.length).fill(null), ...future.map((r) => r.revenue_lower)];
        const band = [...Array(history.length).fill(null), ...future.map((r) => Math.max(0, r.revenue_upper - r.revenue_lower))];
        initChart('forecast-chart', { ...motion, color: [palette.green, palette.gold], tooltip: { ...baseTooltip, valueFormatter: money }, legend: legend(['Actual revenue', 'Forecast']), grid: { left: 52, right: 18, top: 39, bottom: 29 }, xAxis: { type: 'category', data: allLabels, ...baseAxis({ axisLabel: { ...baseAxis().axisLabel, interval: Math.max(0, Math.floor(allLabels.length / 11)) } }) }, yAxis: { type: 'value', ...baseAxis({ axisLabel: { ...baseAxis().axisLabel, formatter: money } }) }, series: [
          { name: 'Prediction interval', type: 'line', stack: 'range', data: lower, showSymbol: false, lineStyle: { opacity: 0 }, areaStyle: { opacity: 0 } },
          { name: '95% range', type: 'line', stack: 'range', data: band, showSymbol: false, lineStyle: { opacity: 0 }, areaStyle: { color: '#d5e3c7', opacity: .42 }, tooltip: { show: false } },
          { name: 'Actual revenue', type: 'line', data: actual, showSymbol: false, smooth: .2, lineStyle: { width: 2.3 } },
          { name: 'Forecast', type: 'line', data: prediction, showSymbol: false, smooth: .2, lineStyle: { width: 2, type: 'dashed', color: palette.gold }, markLine: { symbol: 'none', label: { show: false }, lineStyle: { color: '#b3bcb1', type: 'dotted' }, data: [{ xAxis: dateLabel(future[0]?.month) }] } },
        ] });
      } catch (error) { notifyError(error.message); }
    };
    horizon?.addEventListener('change', render);
    await render();
  }

  async function scenario() {
    const fields = ['price', 'churn', 'new', 'hosting', 'opex'];
    const inputIds = { price: 'price_change_pct', churn: 'churn_change_pct', new: 'new_business_change_pct', hosting: 'hosting_cost_change_pct', opex: 'opex_change_pct' };
    const inputs = () => Object.fromEntries(fields.map((field) => [inputIds[field], Number($(`#scenario-${field}`).value)]));
    fields.forEach((field) => $(`#scenario-${field}`)?.addEventListener('input', (event) => { $(`#scenario-${field}-value`).value = `${event.target.value}%`; }));
    $('#scenario-reset')?.addEventListener('click', () => { fields.forEach((field) => { $(`#scenario-${field}`).value = 0; $(`#scenario-${field}-value`).value = '0%'; }); run(); });
    const run = async () => {
      const button = $('#scenario-run');
      if (button) button.disabled = true;
      try {
        const result = await api('/api/scenarios', { method: 'POST', body: JSON.stringify({ ...inputs(), months: 12 }) });
        const base = result.totals.baseline; const scen = result.totals.scenario; const delta = result.totals.delta;
        animateValue($('#scenario-delta-oi'), delta.operating_income, signedMoney);
        pulse($('#scenario-delta-oi'));
        $('#scenario-delta-oi').classList.toggle('negative', delta.operating_income < 0);
        animateValue($('#scenario-delta-gm'), delta.gross_margin, (v) => v == null ? 'n/a' : `${v >= 0 ? '+' : ''}${(v * 100).toFixed(1)} pp`);
        pulse($('#scenario-delta-gm'));
        const baselineRows = result.baseline;
        const scenarioRows = result.scenario;
        const series = [
          { name: 'Baseline revenue', type: 'line', data: baselineRows.map((row) => row.revenue), smooth: .2, showSymbol: false, lineStyle: { type: 'dashed' } },
          { name: 'Scenario revenue', type: 'line', data: scenarioRows.map((row) => row.revenue), smooth: .2, showSymbol: false, lineStyle: { width: 2.2 } },
          { name: 'Baseline operating income', type: 'line', data: baselineRows.map((row) => row.operating_income), smooth: .2, showSymbol: false, lineStyle: { type: 'dashed', opacity: .65 } },
          { name: 'Scenario operating income', type: 'line', data: scenarioRows.map((row) => row.operating_income), smooth: .2, showSymbol: false, lineStyle: { width: 2.1 } },
        ];
        initChart('scenario-chart', { ...motion, color: [palette.muted, palette.green, '#dc9b80', palette.coral], tooltip: { ...baseTooltip, valueFormatter: money }, legend: legend(series.map((s) => s.name)), grid: { left: 54, right: 15, top: 52, bottom: 29 }, xAxis: { type: 'category', data: scenarioRows.map((row) => dateLabel(row.month)), ...baseAxis() }, yAxis: { type: 'value', ...baseAxis({ axisLabel: { ...baseAxis().axisLabel, formatter: money } }) }, series });
        const metrics = [['Revenue', 'revenue'], ['Gross profit', 'gross_profit'], ['Operating income', 'operating_income'], ['Gross margin', 'gross_margin'], ['Operating margin', 'operating_margin'], ['Exit ARR', 'exit_arr']];
        $('#scenario-comparison').innerHTML = `<div class="compare-head">Metric</div><div class="compare-head">Baseline</div><div class="compare-head">Scenario</div><div class="compare-head">Change</div>${metrics.map(([label, key]) => { const fmt = key.includes('margin') ? pct : money; return `<div class="compare-label">${label}</div><div class="compare-num">${fmt(base[key])}</div><div class="compare-num">${fmt(scen[key])}</div><div class="compare-num ${delta[key] < 0 ? 'negative' : 'positive'}">${key.includes('margin') ? `${delta[key] >= 0 ? '+' : ''}${(delta[key] * 100).toFixed(1)} pp` : signedMoney(delta[key])}</div>`; }).join('')}`;
      } catch (error) { notifyError(error.message); }
      finally { if (button) button.disabled = false; }
    };
    $('#scenario-run')?.addEventListener('click', run);
    await run();
  }

  async function anomalies() {
    const load = async () => {
      try {
        const rows = await api('/api/anomalies');
        animateValue($('#alert-count'), rows.length, (v) => String(Math.round(v)), 500);
        const board = $('#anomaly-board');
        if (!rows.length) { board.innerHTML = '<div class="panel empty-state"><span class="empty-mark">✓</span><strong>No material signals found</strong><p>Keep an eye on upcoming periods as they are added.</p></div>'; return; }
        board.innerHTML = rows.map((r) => `<article class="alert-card"><span class="alert-stripe ${r.severity}"></span><div><div class="alert-title-line"><strong>${escapeHtml(r.title)}</strong><span class="severity severity-${r.severity}">${escapeHtml(r.severity)}</span></div><p>${escapeHtml(r.message)}</p></div><div class="alert-impact">${signedMoney(r.impact || 0)}</div></article>`).join('');
      } catch (error) { notifyError(error.message); }
    };
    $('#refresh-anomalies')?.addEventListener('click', load);
    await load();
  }

  async function copilot() {
    const form = $('#copilot-form');
    const question = $('#copilot-question');
    const counter = $('#question-count');
    question?.addEventListener('input', () => { counter.textContent = question.value.length; });
    $$('.prompt-chips button').forEach((button) => button.addEventListener('click', () => { question.value = button.dataset.prompt; counter.textContent = question.value.length; question.focus(); }));
    question?.addEventListener('keydown', (event) => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); form.requestSubmit(); } });
    form?.addEventListener('submit', async (event) => {
      event.preventDefault();
      const submit = $('#copilot-submit');
      submit.disabled = true;
      $('#copilot-result').innerHTML = '<div class="answer-card"><div class="loading-line"></div><br><div class="loading-line short"></div></div>';
      try {
        const result = await api('/api/copilot', { method: 'POST', body: JSON.stringify({ question: question.value }) });
        const resultNode = $('#copilot-result');
        resultNode.innerHTML = '';
        const card = document.createElement('article'); card.className = 'answer-card';
        const answer = document.createElement('p'); answer.className = 'answer-text'; answer.textContent = result.answer;
        const data = document.createElement('pre'); data.className = 'answer-data'; data.textContent = JSON.stringify(result.data, null, 2);
        const source = document.createElement('div'); source.className = 'answer-source'; source.textContent = `Source: ${result.source}`;
        card.append(answer, data, source); resultNode.append(card);
      } catch (error) { notifyError(error.message); $('#copilot-result').textContent = error.message; }
      finally { submit.disabled = false; }
    });
  }

  function shell() {
    const menu = $('#mobile-menu'); const sidebar = $('#sidebar'); const overlay = $('#mobile-overlay');
    const close = () => { sidebar?.classList.remove('open'); overlay?.classList.remove('visible'); };
    menu?.addEventListener('click', () => { sidebar?.classList.toggle('open'); overlay?.classList.toggle('visible'); });
    overlay?.addEventListener('click', close);
    $$('.nav-link').forEach((link) => link.addEventListener('click', close));
  }

  async function start() {
    shell();
    if (!window.echarts && $('.chart')) notifyError('Chart library could not be loaded. Check network access to the chart CDN.');
    const path = location.pathname;
    if (path === '/dashboard') return dashboard();
    if (path === '/insights') return insights();
    if (path === '/revenue') return revenue();
    if (path === '/profitability') return profitability();
    if (path === '/unit-economics') return unitEconomics();
    if (path === '/forecast') return forecast();
    if (path === '/scenarios') return scenario();
    if (path === '/anomalies') return anomalies();
    if (path === '/copilot') return copilot();
  }
  document.addEventListener('DOMContentLoaded', start);
})();

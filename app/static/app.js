(() => {
  'use strict';

  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
  const csrf = $('meta[name="csrf-token"]')?.content || '';
  const palette = { ink: '#273b31', muted: '#87938a', grid: '#e9ede7', green: '#286f4d', lime: '#a8c57c', coral: '#d77b65', blue: '#6d9aaa', gold: '#d4ad63' };
  const money = (value) => {
    if (value === null || value === undefined || Number.isNaN(Number(value))) return 'n/a';
    const n = Number(value);
    const sign = n < 0 ? '-$' : '$';
    const abs = Math.abs(n);
    if (abs >= 1e9) return `${sign}${(abs / 1e9).toFixed(2)}B`;
    if (abs >= 1e6) return `${sign}${(abs / 1e6).toFixed(2)}M`;
    if (abs >= 1e3) return `${sign}${(abs / 1e3).toFixed(1)}K`;
    return `${sign}${abs.toLocaleString('en-US', { maximumFractionDigits: 2 })}`;
  };
  const count = (value) => value == null ? 'n/a' : Math.round(Number(value)).toLocaleString();
  const escapeHtml = (value) => String(value ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
  const KPI_FORMATS = { total_revenue: money, received: money, outstanding: money, overdue: money, avg_order_value: money, sales: count, products: count, customers: count };
  const api = async (url, options = {}) => {
    const headers = new Headers(options.headers || {});
    if (options.method && options.method !== 'GET') headers.set('X-CSRF-Token', csrf);
    if (options.body) headers.set('Content-Type', 'application/json');
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
      if (document.hidden) { node.textContent = formatter(target); return; }
      const t = Math.min(1, (now - start) / duration);
      node.textContent = formatter(target * easeOutCubic(t));
      if (t < 1) requestAnimationFrame(frame);
    };
    requestAnimationFrame(frame);
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
      if (!(key in data)) return;
      animateValue(node, data[key], KPI_FORMATS[key] || count);
    });
  };
  const seriesChart = (id, rows, extraSeries = []) => {
    initChart(id, {
      ...motion, color: [palette.green, palette.lime, ...extraSeries.map(() => palette.gold)], tooltip: { ...baseTooltip, valueFormatter: money },
      legend: legend(['Revenue billed', 'Cash received', ...extraSeries.map((s) => s.name)]),
      grid: { left: 52, right: 16, top: 38, bottom: 30 },
      xAxis: { type: 'category', data: rows.map((r) => r.bucket), ...baseAxis({ axisLabel: { ...baseAxis().axisLabel, interval: Math.max(0, Math.floor(rows.length / 11)), rotate: rows.length > 14 ? 25 : 0 } }) },
      yAxis: { type: 'value', ...baseAxis({ axisLabel: { ...baseAxis().axisLabel, formatter: money } }) },
      series: [
        { name: 'Revenue billed', type: 'bar', barMaxWidth: 26, itemStyle: { borderRadius: [3, 3, 0, 0] }, data: rows.map((r) => r.revenue) },
        { name: 'Cash received', type: 'line', smooth: .25, showSymbol: false, lineStyle: { width: 2.2 }, data: rows.map((r) => r.received) },
        ...extraSeries,
      ],
    });
  };

  async function dashboard() {
    try {
      const [summary, products, customers, series] = await Promise.all([
        api('/api/overview'), api('/api/products'), api('/api/customers'), api('/api/series?granularity=month'),
      ]);
      paintKpis(summary);
      const body = $('#top-products tbody');
      body.innerHTML = products.filter((p) => p.orders > 0).slice(0, 8).map((p) => `<tr><td class="cell-main">${escapeHtml(p.product_name)}</td><td>${escapeHtml(p.product_code)}</td><td>${money(p.revenue)}</td><td>${count(p.units)}</td><td>${count(p.customers)}</td><td class="${p.outstanding > 0 ? 'negative' : ''}">${money(p.outstanding)}</td></tr>`).join('')
        || '<tr><td colspan="6" class="empty-table">Record your first sale to build the leaderboard.</td></tr>';
      const extremes = $('#buyer-extremes');
      if (customers.highest) {
        extremes.innerHTML = `
          <div class="retention-row"><span>Highest buyer</span><strong>${escapeHtml(customers.highest.customer_name)}</strong></div>
          <div class="retention-row"><span>Their lifetime value</span><strong>${money(customers.highest.revenue)}</strong></div>
          <div class="retention-rule"></div>
          <div class="retention-row"><span>Lowest buyer</span><strong>${escapeHtml(customers.lowest.customer_name)}</strong></div>
          <div class="retention-row"><span>Their lifetime value</span><strong>${money(customers.lowest.revenue)}</strong></div>`;
      } else {
        extremes.innerHTML = '<div class="retention-caption">No customers yet.</div>';
      }
      seriesChart('dashboard-series', series.slice(-18));
    } catch (error) { notifyError(error.message); }
  }

  async function products() {
    const search = $('#product-search');
    const body = $('#product-table tbody');
    const select = $('#sale-product');
    let debounce = null;
    const customerRow = (c) => `<tr class="sub-row"><td></td><td colspan="4"><span class="member-name"><i>${escapeHtml((c.customer_name || '?')[0].toUpperCase())}</i>${escapeHtml(c.customer_name)}${c.company ? ` <small class="sub-note">· ${escapeHtml(c.company)}</small>` : ''}</span></td><td>${count(c.units)}</td><td>${count(c.orders)}</td><td colspan="2">${money(c.revenue)} bought</td><td class="${c.outstanding > 0 ? 'negative' : 'positive'}">${c.outstanding > 0 ? `${money(c.outstanding)} owed` : 'settled'}</td><td>${escapeHtml(c.last_purchase || '')}</td></tr>`;
    const load = async () => {
      try {
        const rows = await api(`/api/products?q=${encodeURIComponent(search?.value || '')}`);
        body.innerHTML = rows.map((p) => `
          <tr class="expandable" data-product="${p.product_id}" data-orders="${p.orders}">
            <td><button class="expand-toggle" aria-label="Show customers">▸</button></td>
            <td class="cell-main">${escapeHtml(p.product_name)}</td><td>${escapeHtml(p.product_code)}</td><td>${escapeHtml(p.category)}</td>
            <td>${money(p.revenue)}</td><td>${count(p.units)}</td><td>${count(p.orders)}</td><td>${count(p.customers)}</td>
            <td>${money(p.received)}</td><td class="${p.outstanding > 0 ? 'negative' : ''}">${money(p.outstanding)}</td><td>${escapeHtml(p.last_sold || '—')}</td>
          </tr>`).join('') || '<tr><td colspan="11" class="empty-table">No products match. Add one with the form above.</td></tr>';
        if (select && !search?.value) {
          const keep = select.value;
          select.innerHTML = '<option value="">Choose a product…</option>' + rows.map((p) => `<option value="${p.product_id}">${escapeHtml(p.product_code)} · ${escapeHtml(p.product_name)}</option>`).join('');
          if (keep) select.value = keep;
        }
      } catch (error) { notifyError(error.message); }
    };
    body?.addEventListener('click', async (event) => {
      const row = event.target.closest('tr.expandable');
      if (!row) return;
      const open = row.classList.toggle('open');
      row.querySelector('.expand-toggle').textContent = open ? '▾' : '▸';
      [...body.querySelectorAll(`tr.sub-row[data-parent="${row.dataset.product}"]`)].forEach((n) => n.remove());
      if (!open) return;
      if (row.dataset.orders === '0') {
        row.insertAdjacentHTML('afterend', `<tr class="sub-row" data-parent="${row.dataset.product}"><td></td><td colspan="10" class="empty-table">No sales for this product yet.</td></tr>`);
        return;
      }
      try {
        const customers = await api(`/api/products/${row.dataset.product}/customers`);
        row.insertAdjacentHTML('afterend', customers.map((c) => customerRow(c).replace('class="sub-row"', `class="sub-row" data-parent="${row.dataset.product}"`)).join(''));
      } catch (error) { notifyError(error.message); }
    });
    search?.addEventListener('input', () => { clearTimeout(debounce); debounce = setTimeout(load, 220); });
    await load();
  }

  async function customers() {
    try {
      const [summary, ranking] = await Promise.all([api('/api/overview'), api('/api/customers')]);
      paintKpis(summary);
      if (ranking.highest) {
        $('#top-buyer').textContent = ranking.highest.customer_name;
        $('#top-buyer-value').textContent = `${money(ranking.highest.revenue)} lifetime`;
        $('#low-buyer').textContent = ranking.lowest.customer_name;
        $('#low-buyer-value').textContent = `${money(ranking.lowest.revenue)} lifetime`;
      }
      $('#customer-table tbody').innerHTML = ranking.customers.map((c, i) => `<tr><td>${i + 1}</td><td class="cell-main">${escapeHtml(c.customer_name)}${c.customer_email ? ` <small class="sub-note">${escapeHtml(c.customer_email)}</small>` : ''}</td><td>${escapeHtml(c.company || '—')}</td><td>${money(c.revenue)}</td><td>${count(c.orders)}</td><td>${count(c.units)}</td><td>${count(c.products)}</td><td>${money(c.received)}</td><td class="${c.outstanding > 0 ? 'negative' : 'positive'}">${money(c.outstanding)}</td><td>${escapeHtml(c.last_purchase)}</td></tr>`).join('')
        || '<tr><td colspan="10" class="empty-table">No customers yet — they appear automatically when you record sales.</td></tr>';
    } catch (error) { notifyError(error.message); }
  }

  async function billing() {
    const filter = $('#billing-filter');
    const body = $('#billing-table tbody');
    const payCell = (row) => row.status === 'paid'
      ? `<span class="status-tag status-active">Paid ${escapeHtml(row.paid_on || '')}</span>`
      : `<form method="post" action="/sales/${row.sale_id}/payment" class="pay-form"><input type="hidden" name="csrf_token" value="${csrf}"><input name="amount" type="number" step="0.01" min="0.01" max="${row.outstanding}" placeholder="${row.outstanding}" required aria-label="Payment amount"><button class="button button-outline pay-button">Save</button></form>`;
    const statusTag = (row) => ({
      paid: '<span class="status-tag status-active">Paid</span>',
      partial: '<span class="severity severity-medium">Partial</span>',
      unpaid: '<span class="severity severity-low">Unpaid</span>',
      overdue: `<span class="severity severity-high">Overdue ${row.days_overdue}d</span>`,
    })[row.status];
    const load = async () => {
      try {
        const book = await api('/api/billing');
        animateValue($('#billing-received'), book.received, money);
        animateValue($('#billing-outstanding'), book.outstanding, money);
        animateValue($('#billing-overdue'), book.overdue, money);
        const open = book.rows.filter((r) => r.status !== 'paid');
        animateValue($('#billing-open'), open.length, count, 400);
        const rows = filter?.value === 'all' ? book.rows : open;
        body.innerHTML = rows.map((row) => `<tr><td>#${row.sale_id}</td><td class="cell-main">${escapeHtml(row.product_name)} <small class="sub-note">${escapeHtml(row.product_code)}</small></td><td>${escapeHtml(row.customer_name)}</td><td>${money(row.total_amount)}</td><td>${money(row.amount_paid)}</td><td class="${row.outstanding > 0 ? 'negative' : ''}">${money(row.outstanding)}</td><td>${escapeHtml(row.due_date || '—')}</td><td>${statusTag(row)}</td><td>${payCell(row)}</td></tr>`).join('')
          || '<tr><td colspan="9" class="empty-table">Nothing outstanding. Every sale is settled.</td></tr>';
      } catch (error) { notifyError(error.message); }
    };
    filter?.addEventListener('change', load);
    await load();
  }

  async function analytics() {
    const productSelect = $('#series-product');
    let granularity = 'month';
    const loadSeries = async () => {
      try {
        const product = productSelect?.value ? `&product_id=${productSelect.value}` : '';
        const rows = await api(`/api/series?granularity=${granularity}${product}`);
        seriesChart('series-chart', rows);
      } catch (error) { notifyError(error.message); }
    };
    $$('.range-chips button').forEach((button) => button.addEventListener('click', () => {
      $$('.range-chips button').forEach((b) => b.classList.toggle('active', b === button));
      granularity = button.dataset.granularity;
      loadSeries();
    }));
    productSelect?.addEventListener('change', loadSeries);
    try {
      const products = await api('/api/products');
      productSelect.innerHTML = '<option value="">All products</option>' + products.map((p) => `<option value="${p.product_id}">${escapeHtml(p.product_code)} · ${escapeHtml(p.product_name)}</option>`).join('');
      const forecast = await api('/api/forecast');
      if (!forecast.available) {
        $('#forecast-chart').hidden = true;
        $('#forecast-locked').hidden = false;
        $('#forecast-reason').textContent = forecast.reason;
        $('#forecast-next').textContent = 'Locked';
        $('#forecast-method').textContent = 'Needs 30+ days of sales';
      } else {
        const labels = [...forecast.history.map((r) => r.bucket), ...forecast.forecast.map((r) => r.bucket)];
        const actual = [...forecast.history.map((r) => r.revenue), ...Array(forecast.forecast.length).fill(null)];
        const predicted = [...Array(Math.max(0, forecast.history.length - 1)).fill(null), forecast.history.at(-1)?.revenue ?? null, ...forecast.forecast.map((r) => r.revenue)];
        const lower = [...Array(forecast.history.length).fill(null), ...forecast.forecast.map((r) => r.lower)];
        const band = [...Array(forecast.history.length).fill(null), ...forecast.forecast.map((r) => Math.max(0, r.upper - r.lower))];
        initChart('forecast-chart', { ...motion, color: [palette.green, palette.gold], tooltip: { ...baseTooltip, valueFormatter: money }, legend: legend(['Actual', 'Forecast']), grid: { left: 52, right: 14, top: 36, bottom: 28 }, xAxis: { type: 'category', data: labels, ...baseAxis() }, yAxis: { type: 'value', ...baseAxis({ axisLabel: { ...baseAxis().axisLabel, formatter: money } }) }, series: [
          { name: 'range-base', type: 'line', stack: 'range', data: lower, showSymbol: false, lineStyle: { opacity: 0 }, tooltip: { show: false } },
          { name: '95% range', type: 'line', stack: 'range', data: band, showSymbol: false, lineStyle: { opacity: 0 }, areaStyle: { color: '#d5e3c7', opacity: .42 }, tooltip: { show: false } },
          { name: 'Actual', type: 'line', data: actual, smooth: .2, showSymbol: false, lineStyle: { width: 2.3 } },
          { name: 'Forecast', type: 'line', data: predicted, smooth: .2, showSymbol: false, lineStyle: { width: 2, type: 'dashed', color: palette.gold } },
        ] });
        animateValue($('#forecast-next'), forecast.next_month, money);
        $('#forecast-method').textContent = forecast.method;
      }
    } catch (error) { notifyError(error.message); }
    await loadSeries();
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
    if (path === '/products') return products();
    if (path === '/customers') return customers();
    if (path === '/billing') return billing();
    if (path === '/analytics') return analytics();
  }
  document.addEventListener('DOMContentLoaded', start);
})();

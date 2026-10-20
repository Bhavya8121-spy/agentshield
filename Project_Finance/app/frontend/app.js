'use strict';

const API = '';
const state = { datasetId: null, session: null, txnOffset: 0, txnLimit: 50, charts: {} };

const $ = (id) => document.getElementById(id);
const money = (v, digits = 0) =>
  v == null ? '—' : `${Number(v).toLocaleString('en-US', { minimumFractionDigits: digits, maximumFractionDigits: digits })}`;
const pct = (v, digits = 1) => (v == null ? '—' : `${(Number(v) * 100).toFixed(digits)}%`);

// ------------------------------------------------------------------ transport
async function api(path, options = {}) {
  const headers = { ...(options.headers || {}) };
  if (state.session) headers['X-Session-Id'] = state.session;
  if (options.body && !(options.body instanceof FormData)) headers['Content-Type'] = 'application/json';

  const response = await fetch(API + path, { ...options, headers });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload?.error?.message || `Request failed (${response.status})`);
  return payload;
}

function busy(on, text = 'Working…') {
  $('loader-text').textContent = text;
  $('loader').classList.toggle('hidden', !on);
}

function banner(message, tone = 'error') {
  const element = $('banner');
  element.className = `banner ${tone}`;
  element.textContent = message;
  element.classList.remove('hidden');
  if (tone !== 'error') setTimeout(() => element.classList.add('hidden'), 6000);
}

function guard(fn, label) {
  return async (...args) => {
    try { busy(true, label); await fn(...args); }
    catch (error) { banner(error.message); }
    finally { busy(false); }
  };
}

// -------------------------------------------------------------------- charts
function drawChart(key, canvasId, config) {
  state.charts[key]?.destroy();
  state.charts[key] = new Chart($(canvasId), config);
}

const GRID = { grid: { color: 'rgba(0,0,0,0.05)' }, ticks: { font: { family: 'Inter', size: 11 } } };
const PALETTE = ['#4e73df', '#1cc88a', '#36b9cc', '#f6c23e', '#e74a3b',
                 '#845ef7', '#fd7e14', '#20c997', '#868e96', '#d6336c'];

function forecastChart(forecast) {
  const path = forecast.daily_path;
  drawChart('forecast', 'chart-forecast', {
    type: 'line',
    data: {
      labels: path.map((p) => `Day ${p.day}`),
      datasets: [
        { label: 'Upper', data: path.map((p) => p.upper), borderWidth: 0,
          backgroundColor: 'rgba(78,115,223,0.12)', fill: '+1', pointRadius: 0 },
        { label: 'Lower', data: path.map((p) => p.lower), borderWidth: 0, pointRadius: 0 },
        { label: 'Expected', data: path.map((p) => p.expected), borderColor: '#4e73df',
          borderWidth: 2.5, tension: 0.3, pointRadius: 0, fill: false },
      ],
    },
    options: {
      responsive: true, maintainAspectRatio: false, interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: { display: false },
        tooltip: { callbacks: { label: (c) => `${c.dataset.label}: ${money(c.parsed.y)}` } },
      },
      scales: { y: { ...GRID, ticks: { ...GRID.ticks, callback: (v) => money(v) } }, x: GRID },
    },
  });
}

function categoryChart(categories) {
  drawChart('categories', 'chart-categories', {
    type: 'doughnut',
    data: {
      labels: categories.map((c) => c.category),
      datasets: [{ data: categories.map((c) => c.monthly), backgroundColor: PALETTE, borderWidth: 0 }],
    },
    options: {
      responsive: true, maintainAspectRatio: false, cutout: '62%',
      plugins: {
        legend: { position: 'right', labels: { boxWidth: 10, font: { family: 'Inter', size: 11 } } },
        tooltip: { callbacks: { label: (c) => `${c.label}: ${money(c.parsed)}/mo` } },
      },
    },
  });
}

function monteCarloChart(result) {
  const paths = result.percentile_paths;
  drawChart('mc', 'chart-mc', {
    type: 'line',
    data: {
      labels: paths.map((p) => `M${p.month}`),
      datasets: [
        { label: '90th', data: paths.map((p) => p.p90), borderWidth: 0,
          backgroundColor: 'rgba(28,200,138,0.10)', fill: '+1', pointRadius: 0 },
        { label: '10th', data: paths.map((p) => p.p10), borderWidth: 0, pointRadius: 0 },
        { label: 'Median', data: paths.map((p) => p.median), borderColor: '#1cc88a',
          borderWidth: 2.5, tension: 0.25, pointRadius: 0, fill: false },
      ],
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: { display: false },
        tooltip: { callbacks: { label: (c) => `${c.dataset.label}: ${money(c.parsed.y)}` } } },
      scales: { y: { ...GRID, ticks: { ...GRID.ticks, callback: (v) => money(v) } }, x: GRID },
    },
  });
}

// ------------------------------------------------------------------ rendering
function metricCard(label, value, note = '', tone = '') {
  return `<div class="metric-card">
    <span class="label">${label}</span>
    <span class="value ${tone}">${value}</span>
    ${note ? `<span class="tiny muted">${note}</span>` : ''}</div>`;
}

function renderOverview(data) {
  const head = data.headline;
  const toneOf = (score) => (score >= 80 ? 'score-good' : score >= 65 ? 'score-warn' : 'score-bad');

  $('health-score').textContent = `${head.health_score} / 100`;
  $('health-score').className = `dti-score ${toneOf(head.health_score)}`;
  $('health-band').textContent = head.band;
  $('health-fill').style.width = `${head.health_score}%`;

  $('health-components').innerHTML = data.health.components
    .map((component) => `<div class="component">
        <span class="label">${component.label}</span>
        <span class="value sm">${component.earned} / ${component.possible}</span>
        <span class="tiny muted">${component.display}</span>
        <div class="mini-bar"><div style="width:${component.sub_score}%"></div></div>
      </div>`).join('');

  const deductions = data.health.explanation.deductions;
  $('health-explain').innerHTML = `
    <p><strong>Why this score?</strong></p>
    <ul>${deductions.length
      ? deductions.map((d) => `<li><code>${d.points.toFixed(1)}</code> ${d.reason}</li>`).join('')
      : '<li>No material deductions.</li>'}</ul>
    <p><strong>Assumptions</strong></p>
    <ul>${data.health.explanation.assumptions.map((a) => `<li>${a}</li>`).join('')}</ul>`;

  $('metric-strip').innerHTML = [
    metricCard('Liquid savings', money(head.balance), head.balance_source.replace(/_/g, ' ')),
    metricCard('Monthly net', money(head.monthly_net), 'income less spending',
      head.monthly_net >= 0 ? 'text-green' : 'text-red'),
    metricCard('Debt-to-income', pct(head.dti), 'housing, loans and cards only'),
    metricCard('Emergency runway', `${head.runway_months.toFixed(1)} mo`, 'of essential expenses'),
    metricCard('Savings rate', pct(head.savings_rate), 'share of income retained'),
  ].join('');

  $('forecast-method').textContent = data.forecast.method.replace(/_/g, ' ');
  forecastChart(data.forecast);
  $('forecast-summary').innerHTML = Object.entries(data.forecast.horizons)
    .map(([key, h]) => `<div class="component">
        <span class="label">${key.replace('_', ' ')}</span>
        <span class="value sm">${money(h.balance)}</span>
        <span class="tiny muted">range ${money(h.lower)} – ${money(h.upper)}</span>
      </div>`).join('');

  categoryChart(data.top_categories);

  $('insight-list').innerHTML = data.insights.map((insight) => {
    const icon = { positive: '✓', warning: '⚠', opportunity: '◆', action: '?' }[insight.tone] || '•';
    return `<li class="insight ${insight.tone}"><span>${icon}</span>${insight.text}</li>`;
  }).join('');

  $('balance-source').textContent = `Source: ${head.balance_source.replace(/_/g, ' ')}`;

  // Forecast tab
  $('horizon-cards').innerHTML = Object.entries(data.forecast.horizons)
    .map(([key, h]) => `<div class="component">
        <span class="label">${key.replace('_', ' ')}</span>
        <span class="value sm">${money(h.balance)}</span>
        <span class="tiny muted">expected change ${money(h.expected_net_change)}</span>
        <span class="tiny muted">p10 ${money(h.p10)} · p90 ${money(h.p90)}</span>
        <span class="tiny ${h.probability_negative_balance > 0.1 ? 'text-red' : 'muted'}">
          ${pct(h.probability_negative_balance)} chance of going negative</span>
      </div>`).join('');
  $('fc-assumptions').innerHTML =
    `<ul>${data.forecast.assumptions.map((a) => `<li>${a}</li>`).join('')}</ul>`;

  if (data.warnings.length) banner(data.warnings[0], 'warn');
}

function renderRecurring(data) {
  const summary = data.summary;
  $('rec-total').textContent = `${money(summary.monthly_total)}/mo`;
  $('rec-summary').innerHTML = [
    metricCard('Monthly recurring', money(summary.monthly_total)),
    metricCard('Annualised', money(summary.annual_total)),
    metricCard('Debt obligations', money(summary.debt_monthly), 'counts toward DTI'),
    metricCard('Discretionary', money(summary.discretionary_annual) + '/yr',
      'most reducible', 'text-green'),
    metricCard('Series detected', summary.series_detected),
  ].join('');

  const rows = data.expenses.map((series) => `<tr class="${series.active ? '' : 'stale'}">
      <td><strong>${series.merchant}</strong>${series.discretionary
        ? '<span class="pill">discretionary</span>' : ''}</td>
      <td>${series.category}</td>
      <td>${series.frequency}</td>
      <td class="num">${money(series.amount_median, 2)}</td>
      <td class="num">${money(series.monthly_amount)}</td>
      <td class="num">${money(series.annual_amount)}</td>
      <td>${series.next_expected || '<span class="muted">inactive</span>'}</td>
      <td class="num">${pct(series.confidence, 0)}</td></tr>`).join('');

  $('rec-table').innerHTML = `<thead><tr>
      <th>Merchant</th><th>Category</th><th>Frequency</th><th class="num">Amount</th>
      <th class="num">Monthly</th><th class="num">Annual</th><th>Next expected</th>
      <th class="num">Confidence</th></tr></thead><tbody>${
        rows || '<tr><td colspan="8" class="muted">No recurring series detected.</td></tr>'}</tbody>`;
}

function renderTransactions(data) {
  const rows = data.transactions.map((txn) => `<tr>
      <td>${txn.date}</td>
      <td><strong>${txn.merchant}</strong><span class="tiny muted block">${txn.clean_description}</span></td>
      <td class="num ${txn.amount < 0 ? '' : 'text-green'}">${money(txn.amount, 2)}</td>
      <td>
        <select class="cat-select" data-id="${txn.transaction_id}">
          ${window.CATEGORIES.map((c) =>
            `<option ${c === txn.category ? 'selected' : ''}>${c}</option>`).join('')}
        </select>
      </td>
      <td class="num"><span class="conf ${txn.confidence < 0.65 ? 'low' : ''}">${
        pct(txn.confidence, 0)}</span><span class="tiny muted block">${txn.classifier}</span></td>
    </tr>`).join('');

  $('txn-table').innerHTML = `<thead><tr><th>Date</th><th>Merchant</th>
      <th class="num">Amount</th><th>Category</th><th class="num">Confidence</th></tr></thead>
      <tbody>${rows || '<tr><td colspan="5" class="muted">No matching transactions.</td></tr>'}</tbody>`;

  $('txn-range').textContent =
    `${data.offset + 1}–${Math.min(data.offset + data.limit, data.total)} of ${data.total}`;

  document.querySelectorAll('.cat-select').forEach((select) => {
    select.onchange = guard(async () => {
      await api(`/api/transactions/${state.datasetId}/corrections`, {
        method: 'POST',
        body: JSON.stringify({ transaction_id: select.dataset.id, category: select.value,
                               apply_to_merchant: true }),
      });
      banner('Correction saved — a rule was created for this merchant.', 'success');
      await Promise.all([loadTransactions(), loadOverview()]);
    }, 'Saving correction…');
  });
}

function renderAffordability(result) {
  const explanation = result.explanation;
  const tone = result.score >= 80 ? 'score-good' : result.score >= 65 ? 'score-warn' : 'score-bad';

  $('afford-result').innerHTML = `
    <div class="card-header"><h3>${result.goal_name}</h3><span class="badge">${result.band}</span></div>
    <div class="dti-score ${tone}">${result.score} / 100</div>
    <p class="verdict">${result.verdict}</p>

    <div class="component-grid">
      ${metricCard('Monthly payment', money(result.loan.monthly_payment))}
      ${metricCard('Total interest', money(result.loan.total_interest))}
      ${metricCard('DTI after', pct(result.ratios.dti_after), `from ${pct(result.ratios.dti_before)}`)}
      ${metricCard('Disposable after', money(result.ratios.disposable_after),
        `from ${money(result.ratios.disposable_before)}`)}
      ${metricCard('Runway after', `${result.ratios.runway_after_months.toFixed(1)} mo`,
        `from ${result.ratios.runway_before_months.toFixed(1)} mo`)}
    </div>

    ${explanation.strengths.length ? `<h4>Positive factors</h4><ul class="factor-list good">
      ${explanation.strengths.map((s) => `<li>${s}</li>`).join('')}</ul>` : ''}
    ${explanation.risks.length ? `<h4>Risk factors</h4><ul class="factor-list bad">
      ${explanation.risks.map((r) => `<li>${r}</li>`).join('')}</ul>` : ''}

    ${result.improvements.length ? `
      <div class="action-box"><strong>How could I reach ${
        result.improvements[0].target_score}?</strong>
        <ul>${result.improvements.map((option) =>
          `<li><strong>Option ${option.option}</strong> — ${option.statement}</li>`).join('')}</ul>
        <p class="tiny muted">Each option is solved independently by inverting the scoring function
          along a single lever.</p></div>` : ''}

    <details><summary>Assumptions</summary><div class="education-box">
      <ul>${explanation.assumptions.map((a) => `<li>${a}</li>`).join('')}</ul></div></details>`;
}

function renderStress(scenarios) {
  $('stress-grid').innerHTML = scenarios.map((result) => {
    const tone = { Severe: 'score-bad', High: 'score-bad',
                   Moderate: 'score-warn', Low: 'score-good' }[result.risk_level];
    return `<div class="component stress">
      <span class="label">${result.scenario.label}</span>
      <span class="value sm ${tone}">${result.risk_level}</span>
      <span class="tiny muted">${result.scenario.description}</span>
      <span class="tiny">Ending balance <strong>${money(result.stressed_ending_balance)}</strong></span>
      <span class="tiny">${result.months_to_depletion
        ? `<span class="text-red">Reserves exhausted in month ${result.months_to_depletion}</span>`
        : `<span class="text-green">Survives the full horizon</span>`}</span>
      <span class="tiny muted">${result.recommendations[0]}</span></div>`;
  }).join('');
}

function renderAnomalies(report) {
  $('anom-count').textContent = `${report.summary.flagged_count} flagged`;
  $('anom-list').innerHTML = report.anomalies.length
    ? report.anomalies.map((a) => `<div class="anomaly">
        <div class="anomaly-head"><strong>${a.merchant}</strong>
          <span class="value sm">${money(a.amount, 2)}</span></div>
        <p class="tiny">${a.reason}</p>
        <div class="tiny muted">${a.date} · ${a.category} · ${a.deviation_multiple.toFixed(1)}× typical
          · confidence ${pct(a.score, 0)} · ${a.method}</div></div>`).join('')
    : `<p class="muted">${report.notes[0] || 'No outliers found.'}</p>`;
}

function renderBacktest(report) {
  const metrics = Object.values(report.metrics);
  if (!metrics.length) {
    $('backtest-table').innerHTML = '';
    $('backtest-notes').innerHTML = `<div class="education-box">${
      report.notes[0] || 'Insufficient history.'}</div>`;
    return;
  }
  $('backtest-table').innerHTML = `<thead><tr><th>Horizon</th><th class="num">Folds</th>
      <th class="num">MAE</th><th class="num">RMSE</th><th class="num">MAPE</th>
      <th class="num">Direction</th><th class="num">Coverage</th>
      <th class="num">Naive MAE</th><th class="num">Skill</th></tr></thead><tbody>
    ${metrics.map((m) => `<tr>
      <td>${m.horizon_days}d</td><td class="num">${m.folds}</td>
      <td class="num">${money(m.mae)}</td><td class="num">${money(m.rmse)}</td>
      <td class="num">${m.mape == null ? '—' : pct(m.mape)}</td>
      <td class="num">${pct(m.directional_accuracy, 0)}</td>
      <td class="num">${pct(m.interval_coverage, 0)}</td>
      <td class="num">${money(m.naive_last_month_mae)}</td>
      <td class="num ${m.skill_vs_last_month > 0 ? 'text-green' : 'text-red'}">
        ${(m.skill_vs_last_month * 100).toFixed(1)}%</td></tr>`).join('')}</tbody>`;
  $('backtest-notes').innerHTML = report.notes.length
    ? `<div class="education-box"><ul>${report.notes.map((n) => `<li>${n}</li>`).join('')}</ul></div>` : '';
}

// -------------------------------------------------------------------- loaders
async function loadOverview() {
  renderOverview(await api(`/api/insights/${state.datasetId}`));
  renderRecurring(await api(`/api/transactions/${state.datasetId}/recurring`));
}

async function loadTransactions() {
  const params = new URLSearchParams({ limit: state.txnLimit, offset: state.txnOffset });
  if ($('txn-search').value) params.set('search', $('txn-search').value);
  if ($('txn-review').checked) params.set('needs_review', 'true');
  renderTransactions(await api(`/api/transactions/${state.datasetId}?${params}`));
}

async function activate(datasetId) {
  state.datasetId = datasetId;
  state.txnOffset = 0;
  const categories = await api(`/api/transactions/${datasetId}/categories`);
  window.CATEGORIES = categories.available_categories;
  $('view-upload').classList.add('hidden');
  $('view-dash').classList.remove('hidden');
  await Promise.all([loadOverview(), loadTransactions()]);
}

// ---------------------------------------------------------------------- wiring
$('upload-form').onsubmit = guard(async (event) => {
  event.preventDefault();
  const file = $('file').files[0];
  if (!file) throw new Error('Choose a CSV file first.');
  const form = new FormData();
  form.append('file', file);
  const result = await api('/api/transactions/upload', { method: 'POST', body: form });
  state.session = result.session_id;
  if (result.counts.needs_review) {
    banner(`${result.counts.needs_review} transaction(s) need review — confirm them on the Transactions tab.`, 'warn');
  }
  await activate(result.dataset_id);
}, 'Parsing statement…');

$('file').onchange = () => {
  $('drop-label').textContent = $('file').files[0]?.name || 'Choose file';
};
['dragover', 'dragleave', 'drop'].forEach((type) => {
  $('drop').addEventListener(type, (event) => {
    event.preventDefault();
    $('drop').classList.toggle('dragging', type === 'dragover');
    if (type === 'drop' && event.dataTransfer.files.length) {
      $('file').files = event.dataTransfer.files;
      $('file').dispatchEvent(new Event('change'));
    }
  });
});

document.querySelectorAll('.nav-item').forEach((button) => {
  button.onclick = () => {
    document.querySelectorAll('.nav-item').forEach((b) => b.classList.remove('active'));
    document.querySelectorAll('.tab').forEach((t) => t.classList.remove('active'));
    button.classList.add('active');
    $(`tab-${button.dataset.tab}`).classList.add('active');
  };
});

$('btn-new').onclick = () => {
  state.datasetId = null;
  $('view-dash').classList.add('hidden');
  $('view-upload').classList.remove('hidden');
};

$('btn-demo').onclick = guard(async () => {
  const response = await fetch('/static/demo.csv');
  if (!response.ok) throw new Error('Demo file not found. Run scripts/generate_data.py first.');
  const form = new FormData();
  form.append('file', new File([await response.blob()], 'demo.csv'));
  const result = await api('/api/transactions/upload', { method: 'POST', body: form });
  state.session = result.session_id;
  await activate(result.dataset_id);
}, 'Loading demo data…');

$('btn-balance').onclick = guard(async () => {
  const value = parseFloat($('balance-input').value);
  if (Number.isNaN(value) || value < 0) throw new Error('Enter a valid balance.');
  await api(`/api/transactions/${state.datasetId}/balance`, {
    method: 'PUT', body: JSON.stringify({ liquid_savings: value }),
  });
  banner('Balance updated — forecasts and runway recalculated.', 'success');
  await loadOverview();
}, 'Updating…');

$('afford-form').onsubmit = guard(async (event) => {
  event.preventDefault();
  renderAffordability(await api(`/api/risk/${state.datasetId}/affordability`, {
    method: 'POST',
    body: JSON.stringify({
      goal_name: $('af-goal').value,
      loan_amount: +$('af-amount').value,
      down_payment: +$('af-down').value,
      annual_rate_percent: +$('af-rate').value,
      term_months: +$('af-term').value,
      extra_monthly_cost: +$('af-extra').value,
      target_score: +$('af-target').value,
    }),
  }));
}, 'Evaluating…');

$('btn-mc').onclick = guard(async () => {
  const goal = parseFloat($('mc-goal').value);
  const result = await api(`/api/simulation/${state.datasetId}/monte-carlo`, {
    method: 'POST',
    body: JSON.stringify({ months: +$('mc-months').value, runs: 10000,
                           savings_goal: Number.isNaN(goal) ? null : goal }),
  });
  monteCarloChart(result);
  $('mc-summary').innerHTML = [
    metricCard('Median ending', money(result.outcomes.median_ending_balance)),
    metricCard('10th percentile', money(result.outcomes.p10), 'pessimistic'),
    metricCard('90th percentile', money(result.outcomes.p90), 'optimistic'),
    metricCard('Chance of going negative', pct(result.probabilities.negative_balance_at_any_point),
      'at any point', result.probabilities.negative_balance_at_any_point > 0.1 ? 'text-red' : 'text-green'),
    metricCard('Reserves under 3 months', pct(result.probabilities.reserves_below_three_months)),
    ...(result.probabilities.savings_goal_met != null
      ? [metricCard('Goal reached', pct(result.probabilities.savings_goal_met))] : []),
  ].join('');
  $('mc-assumptions').innerHTML = `<ul>${result.assumptions.map((a) => `<li>${a}</li>`).join('')}</ul>`;
}, 'Simulating 10,000 paths…');

$('btn-stress').onclick = guard(async () => {
  const result = await api(`/api/simulation/${state.datasetId}/stress-test/all`);
  renderStress(result.scenarios);
}, 'Running scenarios…');

$('btn-backtest').onclick = guard(async () => {
  renderBacktest(await api(`/api/forecast/${state.datasetId}/backtest`));
}, 'Walking forward through history…');

let searchTimer;
$('txn-search').oninput = () => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => { state.txnOffset = 0; loadTransactions(); }, 250);
};
$('txn-review').onchange = () => { state.txnOffset = 0; loadTransactions(); };
$('txn-prev').onclick = () => {
  state.txnOffset = Math.max(0, state.txnOffset - state.txnLimit);
  loadTransactions();
};
$('txn-next').onclick = () => { state.txnOffset += state.txnLimit; loadTransactions(); };

(async () => {
  try {
    const { session_id } = await api('/api/session');
    state.session = session_id;
  } catch { /* analytics is non-critical */ }
})();
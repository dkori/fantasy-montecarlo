/* Static head-to-head demo app (vanilla JS + Plotly).
 * Loads one enriched JSON (demo_week4.json), lets a user pick EXACTLY 2 players,
 * and renders 4 charts with explainers + our-mean / Yahoo-proj / owner overlays.
 */

let DATA = null;        // the loaded demo payload
let NAMES = [];         // sorted selectable player names
let selected = [];      // up to 2 names

// Hover stays on (the unified spike line + value tooltip come from the per-chart
// hovermode:'x unified'); zoom/pan is disabled so a stray drag or scroll on
// mobile can't zoom the plot. scrollZoom off + per-axis fixedrange:true (set in
// each layout) kill zoom entirely; doubleClick off avoids an accidental reset.
const PLOTLY_CONFIG = {
  displayModeBar: false,
  responsive: true,
  scrollZoom: false,
  doubleClick: false,
};

async function boot() {
  const res = await fetch('data/demo_week4.json');
  DATA = await res.json();
  // Only players we can actually chart (have a quantile grid).
  NAMES = Object.keys(DATA.players)
    .filter((n) => DATA.players[n].quantiles && DATA.players[n].quantiles.levels.length > 1)
    .sort();
  renderMeta();
  wireControls();
  render();
}

function renderMeta() {
  const enriched = DATA.n_enriched;
  const total = DATA.n_players;
  document.getElementById('meta').textContent =
    `${DATA.week_label} · book ${DATA.book} · ${DATA.scoring} · ` +
    `${total} priced players (${enriched} with Yahoo projection + owner) · ` +
    `league ${DATA.league_season} week ${DATA.league_week}`;
}

function wireControls() {
  const input = document.getElementById('search');
  const list = document.getElementById('matches');
  const ownerSel = document.getElementById('owner-filter');
  const trigger = document.getElementById('player-trigger');
  const panel = document.getElementById('player-panel');

  // Populate the owner dropdown: "All", each distinct owner (sorted), then
  // "Free agents" (players with no owner).
  const owners = Array.from(
    new Set(NAMES.map((n) => DATA.players[n].owner).filter(Boolean))
  ).sort((a, b) => a.localeCompare(b));
  const opts = ['<option value="__all__">All owners</option>'];
  owners.forEach((o) => opts.push(`<option value="${escapeHtml(o)}">${escapeHtml(o)}</option>`));
  opts.push('<option value="__fa__">Free agents</option>');
  ownerSel.innerHTML = opts.join('');

  // Candidate names under the current owner filter.
  function candidates() {
    const v = ownerSel.value;
    if (v === '__all__') return NAMES;
    if (v === '__fa__') return NAMES.filter((n) => !DATA.players[n].owner);
    return NAMES.filter((n) => DATA.players[n].owner === v);
  }

  // Render the full candidate list (filtered by the in-panel search text).
  // With the dropdown model we always show the list; typing just narrows it.
  function refreshMatches() {
    const pool = candidates();
    const q = input.value.trim().toLowerCase();
    let hits;
    if (!q) {
      hits = pool.slice(0, 300); // whole (owner-filtered) list, tap to pick
    } else {
      const starts = pool.filter((n) => n.toLowerCase().startsWith(q));
      const contains = pool.filter((n) => n.toLowerCase().includes(q) && !starts.includes(n));
      hits = starts.concat(contains).slice(0, 60);
    }
    list.innerHTML = hits.length
      ? hits.map((n) => `<li data-name="${escapeHtml(n)}">${escapeHtml(n)}${badge(n)}</li>`).join('')
      : '<li class="empty">no players</li>';
  }

  function openPanel() {
    panel.classList.add('open');
    trigger.setAttribute('aria-expanded', 'true');
    refreshMatches();
    // NOTE: intentionally do NOT focus the search input here — on mobile that
    // would pop the keyboard the moment the dropdown opens. The user taps the
    // search field themselves if they want to type.
  }
  function closePanel() {
    panel.classList.remove('open');
    trigger.setAttribute('aria-expanded', 'false');
  }
  function togglePanel() {
    if (panel.classList.contains('open')) closePanel(); else openPanel();
  }

  trigger.addEventListener('click', togglePanel);
  ownerSel.addEventListener('change', () => { input.value = ''; if (panel.classList.contains('open')) refreshMatches(); });
  input.addEventListener('input', refreshMatches);

  list.addEventListener('click', (e) => {
    const li = e.target.closest('li[data-name]');
    if (!li) return;
    addPlayer(li.dataset.name);
    input.value = '';
    closePanel();
  });

  // Close on outside click / Escape.
  document.addEventListener('click', (e) => {
    if (!e.target.closest('.player-select')) closePanel();
  });
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape') closePanel(); });
}

function badge(name) {
  const r = DATA.players[name];
  return r && r.owner ? ` <span class="mini-owner">${escapeHtml(r.owner)}</span>` : '';
}

function addPlayer(name) {
  if (!DATA.players[name]) return;
  if (selected.includes(name)) return;
  if (selected.length >= 2) {
    // Hard cap at 2: replace the oldest so the UX stays a head-to-head.
    selected.shift();
  }
  selected.push(name);
  render();
}

function removePlayer(name) {
  selected = selected.filter((n) => n !== name);
  render();
}

function render() {
  renderChips();
  const label = document.getElementById('player-trigger-label');
  if (label) {
    label.textContent = selected.length === 0
      ? 'Select a player…'
      : (selected.length === 1 ? 'Add a second player…' : 'Replace a player…');
  }
  const charts = document.getElementById('charts');
  const hint = document.getElementById('hint');
  if (selected.length === 0) {
    charts.style.display = 'none';
    hint.style.display = 'block';
    hint.textContent = 'Search and pick two players to compare head-to-head.';
    return;
  }
  hint.style.display = selected.length === 1 ? 'block' : 'none';
  if (selected.length === 1) hint.textContent = 'Pick a second player to unlock the difference chart.';
  charts.style.display = 'block';

  const series = selected.map((n, i) => ({ name: n, rec: DATA.players[n], i }));
  renderDensity(series);
  renderCdfStd(series);
  renderCdfFlipped(series);
  renderDiff(series);
}

function renderChips() {
  const box = document.getElementById('chips');
  box.innerHTML = selected
    .map((n) => {
      const r = DATA.players[n];
      const owner = r.owner ? `<span class="chip-owner">${escapeHtml(r.owner)}</span>` : '<span class="chip-owner fa">free agent</span>';
      const yp = r.yahoo_proj != null ? `Yahoo ${r.yahoo_proj.toFixed(1)}` : 'no Yahoo proj';
      return `<div class="chip">
        <span class="chip-name">${escapeHtml(n)}</span>
        <span class="chip-stat">ours: mean ${r.mean.toFixed(1)} · med ${r.median.toFixed(1)} · ${yp}</span>
        ${owner}
        <button data-name="${escapeHtml(n)}" class="chip-x">×</button>
      </div>`;
    })
    .join('');
  box.querySelectorAll('.chip-x').forEach((b) =>
    b.addEventListener('click', () => removePlayer(b.dataset.name)));
}

/* --- the four charts -------------------------------------------------- */

function renderDensity(series) {
  const traces = series.map((s) => {
    const { x, y } = densityFromHistogram(s.rec);
    const pct = percentileAt(s.rec, x);
    return {
      x, y, mode: 'lines', name: `${s.name} (mean ${s.rec.mean.toFixed(1)})`,
      line: { color: rgb(s.i), width: 2 },
      fill: 'tozeroy', fillcolor: rgba(s.i, FILL_ALPHA),
      customdata: pct,
      hovertemplate: '%{x:.1f} pts<br>%{customdata:.0f}th pctile<extra>' + s.name + '</extra>',
    };
  });
  // No mean/Yahoo vertical lines here — 4 lines in a tight range looked
  // cluttered. The mean + Yahoo numbers live on each player's chip instead.
  Plotly.newPlot('chart-density', traces, {
    margin: { t: 10, r: 10, b: 72, l: 50 },
    xaxis: { title: 'fantasy points', fixedrange: true },
    yaxis: { title: 'density', fixedrange: true },
    template: 'plotly_white', hovermode: 'x unified', dragmode: false,
    legend: { orientation: 'h', y: -0.3, yanchor: 'top' },
  }, PLOTLY_CONFIG);
}

function renderCdfStd(series) {
  const traces = series.map((s) => {
    const { x, y } = survivalXY(s.rec);
    return {
      x, y, mode: 'lines', name: `${s.name} (mean ${s.rec.mean.toFixed(1)})`,
      line: { color: rgb(s.i), width: 2 },
      hovertemplate: '%{x:.1f} pts<br>P(≥)=%{y:.2f}<extra>' + s.name + '</extra>',
    };
  });
  // Horizontal probability grid at 0.1/0.5/0.9 for reference.
  const shapes = [];
  [0.1, 0.5, 0.9].forEach((p) => shapes.push({ type: 'line', xref: 'paper', x0: 0, x1: 1,
    y0: p, y1: p, line: { color: '#ccc', width: 1, dash: 'dot' } }));
  Plotly.newPlot('chart-cdf-std', traces, {
    margin: { t: 10, r: 10, b: 72, l: 50 },
    xaxis: { title: 'fantasy points', fixedrange: true },
    yaxis: { title: 'P(score ≥ x)', range: [0, 1], fixedrange: true },
    template: 'plotly_white', hovermode: 'x unified', dragmode: false, shapes,
    legend: { orientation: 'h', y: -0.3, yanchor: 'top' },
  }, PLOTLY_CONFIG);
}

function renderCdfFlipped(series) {
  const traces = series.map((s) => {
    const { x, y } = flippedSurvivalXY(s.rec);
    return {
      x, y, mode: 'lines', name: `${s.name} (mean ${s.rec.mean.toFixed(1)})`,
      line: { color: rgb(s.i), width: 2 },
      hovertemplate: 'P(≥)=%{x:.0f}%<br>%{y:.1f} pts<extra>' + s.name + '</extra>',
    };
  });
  const shapes = [];
  // median as HORIZONTAL lines (y is points)
  series.forEach((s) => {
    shapes.push({ type: 'line', xref: 'paper', x0: 0, x1: 1, y0: s.rec.median, y1: s.rec.median,
      line: { color: rgb(s.i), width: 1, dash: 'dot' } });
  });
  // vertical refs at the 10/50/90% "at least" probabilities
  [10, 50, 90].forEach((p) => shapes.push({ type: 'line', yref: 'paper', x0: p, x1: p,
    y0: 0, y1: 1, line: { color: '#ccc', width: 1, dash: 'dot' } }));
  Plotly.newPlot('chart-cdf-flipped', traces, {
    margin: { t: 10, r: 10, b: 72, l: 50 },
    xaxis: { title: 'probability of scoring at least y (%)', range: [0, 100], fixedrange: true },
    yaxis: { title: 'fantasy points', fixedrange: true },
    template: 'plotly_white', hovermode: 'x unified', dragmode: false, shapes,
    legend: { orientation: 'h', y: -0.3, yanchor: 'top' },
  }, PLOTLY_CONFIG);
}

function renderDiff(series) {
  const panel = document.getElementById('diff-panel');
  if (series.length !== 2) {
    panel.classList.add('disabled');
    Plotly.purge('chart-diff');
    document.getElementById('diff-note').textContent =
      'The difference chart needs exactly two players.';
    return;
  }
  panel.classList.remove('disabled');
  const { x, diff, hiName, loName } = diffSeries(series);
  const trace = {
    x, y: diff, mode: 'lines', name: `${hiName} − ${loName}`,
    line: { color: 'rgb(31,119,180)', width: 2 },
    fill: 'tozeroy', fillcolor: 'rgba(31,119,180,0.08)',
    hovertemplate: '%{x:.0f}th pctile<br>%{y:+.1f} pts<extra>' + hiName + ' − ' + loName + '</extra>',
  };
  const shapes = [{ type: 'line', xref: 'paper', x0: 0, x1: 1, y0: 0, y1: 0,
    line: { color: '#888', width: 1.5 } }];
  [10, 50, 90].forEach((p) => shapes.push({ type: 'line', yref: 'paper', x0: p, x1: p,
    y0: 0, y1: 1, line: { color: '#ccc', width: 1, dash: 'dot' } }));
  Plotly.newPlot('chart-diff', [trace], {
    margin: { t: 10, r: 10, b: 72, l: 50 },
    xaxis: { title: 'percentile', range: [0, 100], fixedrange: true },
    yaxis: { title: `points: ${hiName} − ${loName}`, fixedrange: true },
    template: 'plotly_white', hovermode: 'x unified', dragmode: false, showlegend: false, shapes,
  }, PLOTLY_CONFIG);
  document.getElementById('diff-note').textContent =
    `Positive = ${hiName} (higher mean) ahead at that percentile. ` +
    `Where it dips below zero, ${loName} actually wins.`;
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

boot();

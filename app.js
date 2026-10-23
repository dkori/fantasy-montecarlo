/* Static head-to-head demo app (vanilla JS + Plotly).
 * Loads one enriched JSON (demo_week4.json), lets a user pick EXACTLY 2 players,
 * and renders 4 charts with explainers + our-mean / Yahoo-proj / owner overlays.
 */

let DATA = null;        // the loaded demo payload (current week)
let NAMES = [];         // sorted selectable player names
let selected = [];      // up to 2 names
let colorOf = {};       // name -> stable palette slot (0/1) while selected
let activeScoring = 'half_ppr';  // scoring toggle; default 0.5 PPR (this league)
let WEEKS = [];         // weeks manifest entries [{week, file}], if present

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
  // Prior-week serving via a weeks manifest (weeks.json). Each week is its own
  // file loaded on demand, so prior weeks add nothing to the default page load.
  // Falls back to latest.json, then the legacy hardcoded file, for old deploys.
  let latestFile = 'data/demo_week6.json';
  try {
    const man = await (await fetch('data/weeks.json')).json();
    if (man && Array.isArray(man.weeks) && man.weeks.length) {
      WEEKS = man.weeks.slice().sort((a, b) => b.week - a.week); // newest first
      latestFile = 'data/' + (man.latest || WEEKS[0].file);
    }
  } catch (e) {
    try {
      const ptr = await (await fetch('data/latest.json')).json();
      if (ptr && ptr.file) latestFile = 'data/' + ptr.file;
    } catch (e2) {
      console.warn('no weeks.json/latest.json; using fallback', latestFile);
    }
  }
  populateWeekPicker(latestFile);
  await loadWeek(latestFile);
  wireControls();
  wireViewControls();
  render();
}

function populateWeekPicker(latestFile) {
  const sel = document.getElementById('week-picker');
  if (!sel) return;
  if (!WEEKS.length) { sel.style.display = 'none'; return; }
  sel.innerHTML = WEEKS.map((w, i) => {
    const sl = ('data/' + w.file === latestFile);
    return `<option value="data/${escapeHtml(w.file)}"${sl ? ' selected' : ''}>` +
      `Week ${w.week}${i === 0 ? ' (latest)' : ''}</option>`;
  }).join('');
}

async function loadWeek(dataFile) {
  const res = await fetch(dataFile);
  DATA = await res.json();
  NAMES = Object.keys(DATA.players)
    .filter((n) => playerHasCurve(DATA.players[n]))
    .sort();
  selected = selected.filter((n) => DATA.players[n]);
  Object.keys(colorOf).forEach((n) => { if (!DATA.players[n]) delete colorOf[n]; });
  renderMeta();
}

function playerHasCurve(rec) {
  const q = scoringField(rec, 'quantiles');
  return q && q.levels && q.levels.length > 1;
}

// Distribution field for the ACTIVE scoring, with a flat fallback for weeks
// produced before multi-scoring (which only have the 0.5-PPR flat fields).
function scoringField(rec, key) {
  if (rec && rec.scorings && rec.scorings[activeScoring]
      && rec.scorings[activeScoring][key] != null) {
    return rec.scorings[activeScoring][key];
  }
  return rec ? rec[key] : undefined;
}

// Charting view of a record under the active scoring (static fields + the
// scoring-specific distribution fields).
function recView(name) {
  const r = DATA.players[name];
  if (!r) return null;
  return {
    name,
    owner: r.owner,
    yahoo_proj: r.yahoo_proj,
    mean: scoringField(r, 'mean'),
    median: scoringField(r, 'median'),
    std: scoringField(r, 'std'),
    floor_p10: scoringField(r, 'floor_p10'),
    ceiling_p90: scoringField(r, 'ceiling_p90'),
    quantiles: scoringField(r, 'quantiles'),
    histogram: scoringField(r, 'histogram'),
  };
}

function wireViewControls() {
  const weekSel = document.getElementById('week-picker');
  const scoreSel = document.getElementById('scoring-mode');
  if (scoreSel) {
    scoreSel.value = activeScoring;
    scoreSel.addEventListener('change', () => {
      activeScoring = scoreSel.value;
      NAMES = Object.keys(DATA.players).filter((n) => playerHasCurve(DATA.players[n])).sort();
      render();
    });
  }
  if (weekSel) {
    weekSel.addEventListener('change', async () => {
      await loadWeek(weekSel.value);
      render();
    });
  }
}

function renderMeta() {
  const enriched = DATA.n_enriched;
  const total = DATA.n_players;
  const scoreLabel = { standard: 'Standard', half_ppr: '0.5 PPR', ppr: 'Full PPR' }[activeScoring]
    || DATA.scoring;
  document.getElementById('meta').textContent =
    `${DATA.week_label} · book ${DATA.book} · ${scoreLabel} · ` +
    `${total} priced players (${enriched} with Yahoo projection + owner) · ` +
    `league ${DATA.league_season} week ${DATA.league_week}`;
}

function wireControls() {
  const input = document.getElementById('search');
  const list = document.getElementById('matches');
  const ownerSel = document.getElementById('owner-filter');
  const sortSel = document.getElementById('sort-mode');
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

  // Order a name list by the current sort mode. "mean" sorts by our projected
  // mean descending (highest first) — e.g. "Free agents" + mean gives the best
  // available pickups; ties/missing means fall back to alphabetical.
  function applySort(names) {
    if (sortSel && sortSel.value === 'mean') {
      return names.slice().sort((a, b) => {
        const ma = scoringField(DATA.players[a], 'mean');
        const mb = scoringField(DATA.players[b], 'mean');
        if (mb !== ma) return mb - ma;
        return a.localeCompare(b);
      });
    }
    return names; // NAMES is already alphabetical
  }

  // Candidate names under the current owner filter, then ordered by sort mode.
  function candidates() {
    const v = ownerSel.value;
    let base;
    if (v === '__all__') base = NAMES;
    else if (v === '__fa__') base = NAMES.filter((n) => !DATA.players[n].owner);
    else base = NAMES.filter((n) => DATA.players[n].owner === v);
    return applySort(base);
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
  if (sortSel) sortSel.addEventListener('change', () => { if (panel.classList.contains('open')) refreshMatches(); });
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
  const parts = [];
  // When sorting by our mean, surface the mean inline so the descending order
  // is readable at a glance (e.g. scanning free agents for the best RB pickup).
  const sortSel = document.getElementById('sort-mode');
  const meanV = scoringField(r, 'mean');
  if (sortSel && sortSel.value === 'mean' && r && typeof meanV === 'number') {
    parts.push(`<span class="mini-mean">${meanV.toFixed(1)}</span>`);
  }
  if (r && r.owner) parts.push(`<span class="mini-owner">${escapeHtml(r.owner)}</span>`);
  return parts.length ? ' ' + parts.join(' ') : '';
}

function addPlayer(name) {
  if (!DATA.players[name]) return;
  if (selected.includes(name)) return;
  if (selected.length >= 2) {
    // Hard cap at 2: replace the oldest so the UX stays a head-to-head.
    const dropped = selected.shift();
    delete colorOf[dropped];
  }
  // Assign the lowest free palette slot (0 or 1) so a player keeps the SAME
  // color for as long as they're selected — removing the other player no longer
  // swaps the survivor's color.
  const used = new Set(Object.values(colorOf));
  const slot = used.has(0) ? 1 : 0;
  colorOf[name] = slot;
  selected.push(name);
  render();
}

function removePlayer(name) {
  selected = selected.filter((n) => n !== name);
  delete colorOf[name];
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

  const series = selected.map((n) => ({ name: n, rec: recView(n), i: colorOf[n] }));
  renderCdfStd(series);
  renderDiff(series);
  renderDensity(series);
}

function renderChips() {
  const box = document.getElementById('chips');
  box.innerHTML = selected
    .map((n) => {
      const r = recView(n);
      const owner = r.owner ? `<span class="chip-owner">${escapeHtml(r.owner)}</span>` : '<span class="chip-owner fa">free agent</span>';
      // Yahoo's projection is scraped under this league's scoring (0.5 PPR), so
      // only show it when the toggle is on 0.5 PPR; it's not comparable under
      // Standard/Full PPR.
      const yp = activeScoring === 'half_ppr'
        ? (r.yahoo_proj != null ? ` · Yahoo ${r.yahoo_proj.toFixed(1)}` : ' · no Yahoo proj')
        : '';
      return `<div class="chip">
        <span class="chip-name">${escapeHtml(n)}</span>
        <span class="chip-stat">ours: mean ${r.mean.toFixed(1)} · med ${r.median.toFixed(1)}${yp}</span>
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
  // Per-player median: a vertical line at each player's median point total
  // (where their survival curve crosses P = 0.5). One line per player, colored.
  series.forEach((s) => {
    shapes.push({ type: 'line', x0: s.rec.median, x1: s.rec.median, yref: 'paper', y0: 0, y1: 1,
      line: { color: rgb(s.i), width: 1.2, dash: 'dot' } });
  });
  const annotations = series.map((s) => ({
    x: s.rec.median, xref: 'x', y: 1, yref: 'paper',
    text: `${s.name.split(' ').slice(-1)} med`, showarrow: false,
    font: { size: 10, color: rgb(s.i) }, bgcolor: 'rgba(255,255,255,0.6)', yanchor: 'bottom',
  }));
  Plotly.newPlot('chart-cdf-std', traces, {
    margin: { t: 18, r: 10, b: 72, l: 50 },
    xaxis: { title: 'fantasy points', fixedrange: true },
    yaxis: { title: 'P(score ≥ x)', range: [0, 1], fixedrange: true },
    template: 'plotly_white', hovermode: 'x unified', dragmode: false, shapes, annotations,
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
  const { x, diff, hiName, loName, hiV, loV } = diffSeries(series);
  // Map hi/lo back to their palette colors (hi = higher-mean player).
  const hiIdx = series.find((s) => s.name === hiName).i;
  const loIdx = series.find((s) => s.name === loName).i;
  const hiColor = rgb(hiIdx);
  const loColor = rgb(loIdx);

  // Split the curve into a positive part (hi ahead) and a negative part (lo
  // ahead), each filled/colored in that player's color. Clamp to 0 on the far
  // side and keep nulls out so each fill hugs the zero line.
  const posY = diff.map((d) => (d >= 0 ? d : 0));
  const negY = diff.map((d) => (d <= 0 ? d : 0));

  const posTrace = {
    x, y: posY, mode: 'lines', name: `${hiName} ahead`,
    line: { color: hiColor, width: 2 },
    fill: 'tozeroy', fillcolor: rgba(hiIdx, 0.15),
    hoverinfo: 'skip',
  };
  const negTrace = {
    x, y: negY, mode: 'lines', name: `${loName} ahead`,
    line: { color: loColor, width: 2 },
    fill: 'tozeroy', fillcolor: rgba(loIdx, 0.15),
    hoverinfo: 'skip',
  };
  // An invisible trace carrying the true signed diff so hover shows the real
  // value (positive = hi ahead, negative = lo ahead). Round the data itself so
  // the x-unified hover box shows clean values (not float noise like 99.900001).
  // customdata carries each player's OWN point total at that percentile so the
  // hover gives absolute floor/ceiling context, not just the gap. Points are
  // rounded to one decimal; the percentile x is rounded to a whole number.
  const hoverTrace = {
    x: x.map((v) => Math.round(v)),
    y: diff.map((v) => Math.round(v * 10) / 10),
    customdata: hiV.map((v, i) => [
      Math.round(v * 10) / 10,       // higher-mean player's points
      Math.round(loV[i] * 10) / 10,  // lower-mean player's points
    ]),
    mode: 'lines', line: { color: 'rgba(0,0,0,0)', width: 0 },
    name: `${hiName} − ${loName}`, showlegend: false,
    hovertemplate:
      '%{x}th percentile<br>' +
      hiName + ': %{customdata[0]:.1f} pts<br>' +
      loName + ': %{customdata[1]:.1f} pts<br>' +
      'gap: %{y:+.1f} pts (' + hiName + ' − ' + loName + ')' +
      '<extra></extra>',
  };

  // Symmetric y-range so the zero line is always centered and BOTH halves are
  // visible even when one player strictly dominates (curve never crosses zero).
  const maxAbs = Math.max(1, ...diff.map((d) => Math.abs(d)));
  const M = maxAbs * 1.18;  // a little headroom for the labels

  const shapes = [{ type: 'line', xref: 'paper', x0: 0, x1: 1, y0: 0, y1: 0,
    line: { color: '#888', width: 1.5 } }];
  [10, 50, 90].forEach((p) => shapes.push({ type: 'line', yref: 'paper', x0: p, x1: p,
    y0: 0, y1: 1, line: { color: '#ccc', width: 1, dash: 'dot' } }));

  // In-panel player captions: higher-mean name in the upper half, lower-mean in
  // the lower half, centered horizontally, each in the player's color.
  const annotations = [
    { x: 50, xref: 'x', y: M * 0.72, yref: 'y', text: `▲ ${hiName} ahead`,
      showarrow: false, font: { size: 13, color: hiColor },
      bgcolor: 'rgba(255,255,255,0.65)' },
    { x: 50, xref: 'x', y: -M * 0.72, yref: 'y', text: `▼ ${loName} ahead`,
      showarrow: false, font: { size: 13, color: loColor },
      bgcolor: 'rgba(255,255,255,0.65)' },
  ];

  Plotly.newPlot('chart-diff', [posTrace, negTrace, hoverTrace], {
    margin: { t: 10, r: 10, b: 72, l: 50 },
    xaxis: { title: 'percentile', range: [0, 100], fixedrange: true },
    yaxis: { title: `points difference`, range: [-M, M], fixedrange: true },
    template: 'plotly_white', hovermode: 'x unified', dragmode: false,
    showlegend: false, shapes, annotations,
  }, PLOTLY_CONFIG);
  // Concrete floor/median/ceiling anchors for the two players so the percentile
  // axis is readable in points. Pull the 10th/50th/90th off the shared grid.
  const pctAt = (vals, p) => {
    const idx = x.reduce((best, xv, i) => (Math.abs(xv - p) < Math.abs(x[best] - p) ? i : best), 0);
    return Math.round(vals[idx]);
  };
  const anchors = (vals) => `${pctAt(vals, 10)} / ${pctAt(vals, 50)} / ${pctAt(vals, 90)}`;
  document.getElementById('diff-note').innerHTML =
    `Above the line (${escapeHtml(hiName)}'s color) = ${escapeHtml(hiName)} ahead at that ` +
    `percentile; below = ${escapeHtml(loName)} ahead (e.g. a higher floor). ` +
    `<br><b>Floor / median / ceiling (10th / 50th / 90th pctile):</b> ` +
    `${escapeHtml(hiName)} ${anchors(hiV)} pts · ${escapeHtml(loName)} ${anchors(loV)} pts.`;
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

boot();

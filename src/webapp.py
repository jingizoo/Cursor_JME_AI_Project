"""
WebApp - Simple UI to ask questions and render charts inline.

Runs as its own FastAPI app and mounts the existing Chart API under /api.

Start:
  python -m uvicorn src.webapp:app --host 0.0.0.0 --port 8012

Then open:
  http://localhost:8012
"""

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from .chart_data_api import app as chart_data_api_app


app = FastAPI(title="JME AI Finance Pipeline - Web UI")

# Mount lightweight data API so the browser can call it same-origin (no matplotlib required)
app.mount("/api", chart_data_api_app)


INDEX_HTML = """<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width,initial-scale=1" />
    <title>JME AI Chart UI</title>
    <script src="https://cdn.plot.ly/plotly-2.30.0.min.js"></script>
    <style>
      :root { color-scheme: light; }
      body { font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif; margin: 0; background: #f6f7fb; color: #121826; }
      .wrap { max-width: 980px; margin: 0 auto; padding: 24px; }
      .card { background: #ffffff; border: 1px solid #e5e7eb; border-radius: 14px; padding: 16px; box-shadow: 0 6px 18px rgba(18,24,38,0.06); }
      /* Vertical layout: question/results first, chart below */
      .row { display: grid; grid-template-columns: 1fr; gap: 14px; }
      h1 { font-size: 18px; margin: 0 0 10px; }
      label { font-size: 12px; color: #374151; }
      textarea { width: 100%; min-height: 84px; resize: vertical; padding: 12px; border-radius: 12px; border: 1px solid #d1d5db; background: #ffffff; color: #111827; }
      select, button { padding: 10px 12px; border-radius: 12px; border: 1px solid #d1d5db; background: #ffffff; color: #111827; }
      button { cursor: pointer; background: #2563eb; border-color: #1d4ed8; color: #ffffff; }
      button:disabled { opacity: 0.6; cursor: not-allowed; }
      .actions { display: flex; gap: 10px; align-items: center; margin-top: 10px; }
      .muted { color: #6b7280; font-size: 12px; }
      .err { color: #b42318; white-space: pre-wrap; }
      .hint { color: #92400e; white-space: pre-wrap; }
      .ok { color: #067647; }
      .imgwrap { display: flex; justify-content: center; background: #f9fafb; border: 1px dashed #d1d5db; border-radius: 14px; padding: 12px; overflow: auto; }
      img { max-width: 860px; width: 100%; height: auto; max-height: 560px; object-fit: contain; border-radius: 10px; }
      #plot { width: 100%; height: 520px; }
      code, pre { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
      pre { background: #0b1220; color: #e5e7eb; border: 1px solid #111827; padding: 10px; border-radius: 12px; overflow: auto; }
      table { width: 100%; border-collapse: collapse; font-size: 12px; }
      th, td { border-bottom: 1px solid #e5e7eb; padding: 8px; text-align: left; vertical-align: top; }
      th { position: sticky; top: 0; background: #ffffff; }
    </style>
  </head>
  <body>
    <div class="wrap">
      <div class="card">
        <h1>Ask a question → get a chart</h1>
        <div class="row">
          <div>
            <label for="q">Question</label>
            <textarea id="q" placeholder="e.g. top 5 who consumed most hours in september"></textarea>
            <div class="actions">
              <label for="ct" class="muted">Chart</label>
              <select id="ct">
                <option value="">auto</option>
                <option value="bar">bar</option>
                <option value="line">line</option>
                <option value="pie">pie</option>
                <option value="scatter">scatter</option>
                <option value="bubble">bubble</option>
                <option value="heatmap">heatmap</option>
              </select>
              <button id="askBtn">Ask</button>
              <span id="status" class="muted"></span>
            </div>
            <div style="margin-top:10px">
              <div id="err" class="err"></div>
              <div id="hint" class="hint"></div>
            </div>
            <div style="margin-top:12px">
              <div class="muted">SQL</div>
              <pre id="sql"></pre>
            </div>
          </div>
        </div>

        <div style="margin-top:14px">
          <div class="muted">Chart</div>
          <div class="imgwrap" style="margin-top:8px">
            <div id="noimg" class="muted">No chart yet</div>
            <div id="plot"></div>
          </div>
        </div>

        <div style="margin-top:12px">
          <div class="muted">Notes</div>
          <pre id="notes"></pre>
        </div>
      </div>

      <div class="card" style="margin-top:16px">
        <div class="muted">Data (first 200 rows)</div>
        <div id="tableWrap" style="margin-top:10px; overflow:auto; max-height: 420px;"></div>
      </div>
    </div>

    <script>
      const qEl = document.getElementById('q');
      const ctEl = document.getElementById('ct');
      const askBtn = document.getElementById('askBtn');
      const statusEl = document.getElementById('status');
      const errEl = document.getElementById('err');
      const hintEl = document.getElementById('hint');
      const sqlEl = document.getElementById('sql');
      const notesEl = document.getElementById('notes');
      const noimgEl = document.getElementById('noimg');
      const plotEl = document.getElementById('plot');
      const tableWrap = document.getElementById('tableWrap');

      function escapeHtml(s) {
        return String(s)
          .replaceAll('&','&amp;')
          .replaceAll('<','&lt;')
          .replaceAll('>','&gt;')
          .replaceAll('\"','&quot;')
          .replaceAll(\"'\",'&#039;');
      }

      function renderTable(rows) {
        if (!rows || rows.length === 0) {
          tableWrap.innerHTML = '<div class="muted">No rows</div>';
          return;
        }
        const cols = Object.keys(rows[0]);
        let html = '<table><thead><tr>' + cols.map(c => '<th>' + escapeHtml(c) + '</th>').join('') + '</tr></thead><tbody>';
        for (const r of rows) {
          html += '<tr>' + cols.map(c => '<td>' + escapeHtml(r[c]) + '</td>').join('') + '</tr>';
        }
        html += '</tbody></table>';
        tableWrap.innerHTML = html;
      }

      function toNumber(v) {
        if (v === null || v === undefined || v === '') return null;
        if (typeof v === 'number') return Number.isFinite(v) ? v : null;
        const n = Number(String(v).replaceAll(',', ''));
        return Number.isFinite(n) ? n : null;
      }

      function isDateLike(v) {
        if (v === null || v === undefined) return false;
        if (v instanceof Date) return true;
        const s = String(v);
        const t = Date.parse(s);
        return !Number.isNaN(t) && s.length >= 6;
      }

      function inferColumnTypes(rows, cols) {
        const sampleN = Math.min(rows.length, 50);
        const numericCols = [];
        const dateCols = [];
        const textCols = [];

        for (const c of cols) {
          let numCount = 0;
          let dateCount = 0;
          let seen = 0;
          for (let i = 0; i < sampleN; i++) {
            const v = rows[i]?.[c];
            if (v === null || v === undefined || v === '') continue;
            seen++;
            if (toNumber(v) !== null) numCount++;
            if (isDateLike(v)) dateCount++;
          }
          const numRatio = seen ? numCount / seen : 0;
          const dateRatio = seen ? dateCount / seen : 0;
          if (numRatio >= 0.75) numericCols.push(c);
          else if (dateRatio >= 0.75) dateCols.push(c);
          else textCols.push(c);
        }

        return { numericCols, dateCols, textCols };
      }

      function scaleSizes(vals) {
        // vals: array<number|null>
        const nums = vals.filter(v => typeof v === 'number' && Number.isFinite(v));
        if (nums.length === 0) return vals.map(_ => 10);
        const min = Math.min(...nums);
        const max = Math.max(...nums);
        if (min === max) return vals.map(v => (v === null ? 10 : 28));
        return vals.map(v => {
          if (v === null) return 10;
          const t = (v - min) / (max - min);
          return 10 + t * 30; // 10..40
        });
      }

      function clearPlot() {
        try { Plotly.purge(plotEl); } catch {}
        plotEl.innerHTML = '';
      }

      async function ask() {
        const question = qEl.value.trim();
        if (!question) return;

        errEl.textContent = '';
        hintEl.textContent = '';
        sqlEl.textContent = '';
        notesEl.textContent = '';
        noimgEl.style.display = 'block';
        clearPlot();
        tableWrap.innerHTML = '';

        askBtn.disabled = true;
        statusEl.textContent = 'Thinking...';

        const payload = { question };
        const chartType = ctEl.value.trim();
        if (chartType) payload.chart_type = chartType;

        try {
          const res = await fetch('/api/ask-data', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
          });
          const data = await res.json();

          if (!data.ok) {
            errEl.textContent = data.error || 'Unknown error';
            if (data.hint) hintEl.textContent = data.hint;
            if (data.sql) sqlEl.textContent = data.sql;
            if (data.notes) notesEl.textContent = data.notes;
            statusEl.textContent = 'Failed';
            return;
          }

          statusEl.textContent = 'Done';
          if (data.hint) hintEl.textContent = data.hint;
          sqlEl.textContent = data.sql || '';
          notesEl.textContent = data.notes || '';

          const rows = data.data || [];
          renderTable(rows.slice(0, 200));

          // Render interactive chart using Plotly with smart handling for 2+ columns.
          if (rows.length === 0 || !rows[0]) {
            noimgEl.textContent = 'No chart (empty result).';
            return;
          }

          const cols = Object.keys(rows[0]);
          if (cols.length < 2) {
            noimgEl.textContent = 'Not enough columns to chart (need at least 2).';
            return;
          }

          const { numericCols, dateCols, textCols } = inferColumnTypes(rows, cols);
          const requested = (data.chart && data.chart.type) ? data.chart.type : 'auto';
          const type = requested || 'auto';

          // Limit points for scatter/bubble to keep UI snappy
          const maxPoints = 800;
          const plotRows = rows.length > maxPoints ? rows.slice(0, maxPoints) : rows;

          const layoutBase = {
            margin: { l: 55, r: 20, t: 30, b: 120 },
            xaxis: { automargin: true, tickangle: -35 },
            yaxis: { automargin: true },
            paper_bgcolor: 'rgba(0,0,0,0)',
            plot_bgcolor: 'rgba(0,0,0,0)',
            legend: { orientation: 'h' },
          };

          // Auto-pick columns
          const labelCol = textCols[0] || cols[0];
          const xDateCol = dateCols[0] || null;

          function draw(traces, layout) {
            Plotly.newPlot(plotEl, traces, { ...layoutBase, ...(layout || {}) }, { responsive: true, displaylogo: false });
            noimgEl.style.display = 'none';
          }

          // 1) Bubble / scatter
          const autoWantsBubble = (type === 'auto' && numericCols.length >= 3 && cols.length >= 3);
          const wantsBubble = (type === 'bubble') || autoWantsBubble;
          const wantsScatter = (type === 'scatter') || (type === 'auto' && numericCols.length >= 2 && cols.length >= 3);

          if (wantsBubble || wantsScatter) {
            if (numericCols.length < 2) {
              noimgEl.textContent = 'Need at least 2 numeric columns for scatter/bubble.';
              return;
            }
            const xCol = numericCols[0];
            const yCol = numericCols[1];
            const sizeCol = numericCols[2] || null;
            const textCol = textCols[0] || null;

            const x = [];
            const y = [];
            const text = [];
            const sizesRaw = [];

            for (const r of plotRows) {
              const xv = toNumber(r[xCol]);
              const yv = toNumber(r[yCol]);
              if (xv === null || yv === null) continue;
              x.push(xv);
              y.push(yv);
              if (textCol) text.push(String(r[textCol]));
              sizesRaw.push(sizeCol ? toNumber(r[sizeCol]) : null);
            }

            if (x.length === 0) {
              noimgEl.textContent = 'No numeric points to plot (check nulls / types).';
              return;
            }

            const sizes = wantsBubble ? scaleSizes(sizesRaw) : sizesRaw.map(_ => 10);
            const trace = {
              x,
              y,
              type: 'scatter',
              mode: 'markers',
              text: textCol ? text : undefined,
              hovertemplate: textCol ? '%{text}<br>x=%{x}<br>y=%{y}<extra></extra>' : 'x=%{x}<br>y=%{y}<extra></extra>',
              marker: {
                size: sizes,
                sizemode: 'diameter',
                opacity: 0.75,
                color: '#2563eb',
              },
            };
            const title = wantsBubble ? `Bubble: ${xCol} vs ${yCol}${sizeCol ? ` (size=${sizeCol})` : ''}` : `Scatter: ${xCol} vs ${yCol}`;
            draw([trace], { title: { text: title, x: 0.02, font: { size: 14 } }, xaxis: { title: xCol }, yaxis: { title: yCol } });
            return;
          }

          // 2) Pie (label + value)
          if (type === 'pie') {
            const valCol = numericCols[0] || cols[1];
            const labels = plotRows.map(r => r[labelCol]);
            const values = plotRows.map(r => toNumber(r[valCol]) ?? 0);
            draw([{ type: 'pie', labels, values, textinfo: 'label+percent' }], { title: { text: `Pie: ${valCol} by ${labelCol}`, x: 0.02, font: { size: 14 } } });
            return;
          }

          // 3) Line: date/time x if available, otherwise label x; support multiple numeric series
          if (type === 'line') {
            const xCol = xDateCol || labelCol;
            const x = plotRows.map(r => r[xCol]);
            const seriesCols = numericCols.length ? numericCols : [cols[1]];
            const traces = seriesCols.slice(0, 5).map(c => ({
              x,
              y: plotRows.map(r => toNumber(r[c])),
              type: 'scatter',
              mode: 'lines+markers',
              name: c,
            }));
            draw(traces, { title: { text: `Trend by ${xCol}`, x: 0.02, font: { size: 14 } }, xaxis: { title: xCol } });
            return;
          }

          // 4) Bar: if multiple numeric columns => grouped bars
          // Pick a categorical x
          const xCol = labelCol;
          const x = plotRows.map(r => r[xCol]);
          const yCols = numericCols.length ? numericCols : [cols[1]];
          // If we have 2 categorical dimensions + 1 measure, use dim2 as series.
          if ((type === 'bar' || type === 'auto') && textCols.length >= 2 && yCols.length === 1) {
            const dim1 = textCols[0];
            const dim2 = textCols[1];
            const measure = yCols[0];

            // Build series by dim2; keep dim1 as x-axis categories.
            const dim2Vals = Array.from(new Set(plotRows.map(r => r[dim2]))).slice(0, 12);
            const dim1Vals = Array.from(new Set(plotRows.map(r => r[dim1]))).slice(0, 60);

            // Index rows by (dim1, dim2)
            const idx = new Map();
            for (const r of plotRows) {
              const k = String(r[dim1]) + '||' + String(r[dim2]);
              idx.set(k, toNumber(r[measure]));
            }

            const traces = dim2Vals.map(v2 => ({
              x: dim1Vals,
              y: dim1Vals.map(v1 => idx.get(String(v1) + '||' + String(v2)) ?? null),
              type: 'bar',
              name: String(v2),
            }));
            const barLayout = {
              barmode: 'group',
              title: { text: `Bar: ${measure} by ${dim1} (split by ${dim2})`, x: 0.02, font: { size: 14 } },
              xaxis: { title: dim1 },
              yaxis: { title: measure },
            };
            draw(traces, barLayout);
            return;
          }

          // Heatmap (2 dims + 1 measure) if requested
          if (type === 'heatmap' && textCols.length >= 2 && yCols.length >= 1) {
            const dim1 = textCols[0];
            const dim2 = textCols[1];
            const measure = yCols[0];
            const xVals = Array.from(new Set(plotRows.map(r => r[dim2]))).slice(0, 40);
            const yVals = Array.from(new Set(plotRows.map(r => r[dim1]))).slice(0, 60);

            const z = yVals.map(vy => xVals.map(vx => null));
            const xIdx = new Map(xVals.map((v, i) => [String(v), i]));
            const yIdx = new Map(yVals.map((v, i) => [String(v), i]));
            for (const r of plotRows) {
              const yi = yIdx.get(String(r[dim1]));
              const xi = xIdx.get(String(r[dim2]));
              if (yi === undefined || xi === undefined) continue;
              z[yi][xi] = toNumber(r[measure]);
            }

            const trace = { type: 'heatmap', x: xVals, y: yVals, z, colorscale: 'Blues' };
            draw([trace], {
              title: { text: `Heatmap: ${measure} by ${dim1} × ${dim2}`, x: 0.02, font: { size: 14 } },
              xaxis: { title: dim2, tickangle: -35 },
              yaxis: { title: dim1, automargin: true },
            });
            return;
          }

          const traces = yCols.slice(0, 6).map(c => ({
            x,
            y: plotRows.map(r => toNumber(r[c])),
            type: 'bar',
            name: c,
          }));
          const barLayout = { barmode: yCols.length > 1 ? 'group' : 'relative', title: { text: `Bar by ${xCol}`, x: 0.02, font: { size: 14 } }, xaxis: { title: xCol } };
          draw(traces, barLayout);
        } catch (e) {
          errEl.textContent = String(e);
          statusEl.textContent = 'Failed';
        } finally {
          askBtn.disabled = false;
        }
      }

      askBtn.addEventListener('click', ask);
      qEl.addEventListener('keydown', (e) => {
        if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') ask();
      });
    </script>
  </body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
def index():
    return INDEX_HTML



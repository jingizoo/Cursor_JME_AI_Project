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

from .chart_api import app as chart_api_app


app = FastAPI(title="JME AI Finance Pipeline - Web UI")

# Mount existing chart API so the browser can call it same-origin
app.mount("/api", chart_api_app)


INDEX_HTML = """<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width,initial-scale=1" />
    <title>JME AI Chart UI</title>
    <style>
      :root { color-scheme: light; }
      body { font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif; margin: 0; background: #0b1020; color: #e8ecff; }
      .wrap { max-width: 1100px; margin: 0 auto; padding: 24px; }
      .card { background: rgba(255,255,255,0.06); border: 1px solid rgba(255,255,255,0.12); border-radius: 14px; padding: 16px; }
      .row { display: grid; grid-template-columns: 1fr; gap: 14px; }
      @media (min-width: 980px) { .row { grid-template-columns: 1.2fr 0.8fr; } }
      h1 { font-size: 18px; margin: 0 0 10px; }
      label { font-size: 12px; opacity: 0.9; }
      textarea { width: 100%; min-height: 80px; resize: vertical; padding: 12px; border-radius: 12px; border: 1px solid rgba(255,255,255,0.16); background: rgba(0,0,0,0.25); color: #e8ecff; }
      select, button { padding: 10px 12px; border-radius: 12px; border: 1px solid rgba(255,255,255,0.16); background: rgba(0,0,0,0.25); color: #e8ecff; }
      button { cursor: pointer; background: #4c6fff; border-color: rgba(255,255,255,0.12); }
      button:disabled { opacity: 0.6; cursor: not-allowed; }
      .actions { display: flex; gap: 10px; align-items: center; margin-top: 10px; }
      .muted { opacity: 0.8; font-size: 12px; }
      .err { color: #ff9aa8; white-space: pre-wrap; }
      .hint { color: #ffd27a; white-space: pre-wrap; }
      .ok { color: #b7ffc3; }
      .imgwrap { display: flex; justify-content: center; background: rgba(0,0,0,0.25); border: 1px dashed rgba(255,255,255,0.16); border-radius: 14px; padding: 12px; }
      img { max-width: 100%; height: auto; border-radius: 10px; }
      code, pre { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
      pre { background: rgba(0,0,0,0.35); border: 1px solid rgba(255,255,255,0.12); padding: 10px; border-radius: 12px; overflow: auto; }
      table { width: 100%; border-collapse: collapse; font-size: 12px; }
      th, td { border-bottom: 1px solid rgba(255,255,255,0.12); padding: 8px; text-align: left; vertical-align: top; }
      th { position: sticky; top: 0; background: rgba(11,16,32,0.9); }
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
          <div>
            <div class="muted">Chart</div>
            <div class="imgwrap" style="margin-top:8px">
              <img id="img" alt="Chart will appear here" style="display:none" />
              <div id="noimg" class="muted">No chart yet</div>
            </div>
            <div style="margin-top:12px">
              <div class="muted">Notes</div>
              <pre id="notes"></pre>
            </div>
          </div>
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
      const imgEl = document.getElementById('img');
      const noimgEl = document.getElementById('noimg');
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

      async function ask() {
        const question = qEl.value.trim();
        if (!question) return;

        errEl.textContent = '';
        hintEl.textContent = '';
        sqlEl.textContent = '';
        notesEl.textContent = '';
        imgEl.style.display = 'none';
        noimgEl.style.display = 'block';
        tableWrap.innerHTML = '';

        askBtn.disabled = true;
        statusEl.textContent = 'Thinking...';

        const payload = { question };
        const chartType = ctEl.value.trim();
        if (chartType) payload.chart_type = chartType;

        try {
          const res = await fetch('/api/ask-chart', {
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

          if (data.chart && data.chart.image_base64) {
            imgEl.src = 'data:image/png;base64,' + data.chart.image_base64;
            imgEl.style.display = 'block';
            noimgEl.style.display = 'none';
          } else {
            noimgEl.textContent = 'No chart (empty result or chart generation skipped)';
            noimgEl.style.display = 'block';
          }
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



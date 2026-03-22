#!/usr/bin/env python3
"""
Lightweight web UI for print-blockage-stopper.
Serves a status dashboard on port 8631 with:
  - Status indicator (ok / error / skipped / unknown)
  - Print Now button
  - Pause/Resume schedule toggle
  - Skip-hours configuration
  - 30-day print history chart
  - Recent logs
"""

import http.server
import json
import os
import subprocess
import html as html_mod
from datetime import datetime
from pathlib import Path

PORT = 8631
STATUS_FILE = "/data/status.json"
LOG_FILE = "/data/logs/auto-print.log"
HISTORY_FILE = "/data/print-history.json"
CONFIG_FILE = "/data/config.json"

# ── Config helpers ──────────────────────────────────────────────

def read_config():
    try:
        with open(CONFIG_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"paused": False, "skip_hours": int(os.environ.get("SKIP_HOURS", "72"))}

def write_config(cfg):
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f, indent=2)

# ── Data readers ────────────────────────────────────────────────

def get_status():
    try:
        with open(STATUS_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"status": "unknown", "message": "No prints yet", "timestamp": "—"}

def get_recent_logs(lines=20):
    try:
        with open(LOG_FILE) as f:
            all_lines = f.readlines()
            return "".join(all_lines[-lines:])
    except FileNotFoundError:
        return "No log entries yet."

def get_history():
    """Read print history (JSON lines file)."""
    entries = []
    try:
        with open(HISTORY_FILE) as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
    except FileNotFoundError:
        pass
    return entries

def get_schedule():
    return os.environ.get("SCHEDULE", "0 10 */3 * *")

def get_printer_ip():
    return os.environ.get("PRINTER_IP", "unknown")

def trigger_print():
    """Run auto-print.sh --force in background (bypasses skip check)."""
    subprocess.Popen(
        ["/app/auto-print.sh", "--force"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env={**os.environ}
    )

# ── HTTP Handler ────────────────────────────────────────────────

class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # Suppress default logging

    def do_GET(self):
        if self.path == "/api/status":
            self._json_response(get_status())
        elif self.path == "/api/logs":
            self._json_response({"logs": get_recent_logs(30)})
        elif self.path == "/api/history":
            self._json_response({"history": get_history()})
        elif self.path == "/api/config":
            self._json_response(read_config())
        elif self.path == "/":
            self._serve_dashboard()
        else:
            self.send_error(404)

    def do_POST(self):
        if self.path == "/api/print-now":
            trigger_print()
            self._json_response({"ok": True, "message": "Print job triggered"})
        elif self.path == "/api/toggle-schedule":
            cfg = read_config()
            cfg["paused"] = not cfg.get("paused", False)
            write_config(cfg)
            state = "paused" if cfg["paused"] else "running"
            self._json_response({"ok": True, "paused": cfg["paused"], "message": f"Schedule is now {state}"})
        elif self.path == "/api/config":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length) if length else b"{}"
            try:
                updates = json.loads(body)
            except json.JSONDecodeError:
                self._json_response({"ok": False, "message": "Invalid JSON"}, status=400)
                return
            cfg = read_config()
            if "skip_hours" in updates:
                try:
                    val = int(updates["skip_hours"])
                    if 1 <= val <= 720:
                        cfg["skip_hours"] = val
                except (ValueError, TypeError):
                    pass
            write_config(cfg)
            self._json_response({"ok": True, "config": cfg})
        else:
            self.send_error(404)

    def _json_response(self, data, status=200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)

    def _serve_dashboard(self):
        status = get_status()
        logs = get_recent_logs(25)
        schedule = get_schedule()
        printer_ip = get_printer_ip()
        config = read_config()
        history = get_history()

        paused = config.get("paused", False)
        skip_hours = config.get("skip_hours", 72)

        status_colour = {
            "ok": "#22c55e",
            "error": "#ef4444",
            "unknown": "#a3a3a3"
        }.get(status["status"], "#a3a3a3")

        status_label = {
            "ok": "OK",
            "error": "FAILED",
            "unknown": "No prints yet"
        }.get(status["status"], status["status"])

        pause_btn_label = "Resume Schedule" if paused else "Pause Schedule"
        pause_btn_colour = "#22c55e" if paused else "#f59e0b"
        schedule_state = "PAUSED" if paused else "Active"
        schedule_colour = "#ef4444" if paused else "#22c55e"

        history_json = json.dumps(history[-30:])
        escaped_logs = html_mod.escape(logs)

        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Print Blockage Stopper</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
         background: #0f172a; color: #e2e8f0; padding: 24px; line-height: 1.5; }}
  .container {{ max-width: 720px; margin: 0 auto; }}
  h1 {{ font-size: 1.4rem; font-weight: 600; margin-bottom: 4px; }}
  .subtitle {{ color: #94a3b8; font-size: 0.85rem; margin-bottom: 24px; }}
  .card {{ background: #1e293b; border-radius: 10px; padding: 20px; margin-bottom: 16px; }}
  .card h2 {{ font-size: 0.85rem; text-transform: uppercase; letter-spacing: 0.05em;
              color: #64748b; margin-bottom: 12px; }}
  .status-row {{ display: flex; align-items: center; gap: 10px; margin-bottom: 8px; }}
  .status-dot {{ width: 12px; height: 12px; border-radius: 50%; background: {status_colour};
                 box-shadow: 0 0 8px {status_colour}80; }}
  .status-label {{ font-size: 1.1rem; font-weight: 600; }}
  .meta {{ color: #94a3b8; font-size: 0.82rem; }}
  .meta span {{ margin-right: 18px; }}
  .btn {{ color: white; border: none; border-radius: 8px;
          padding: 10px 24px; font-size: 0.95rem; cursor: pointer; font-weight: 500;
          transition: background 0.15s; }}
  .btn:hover {{ filter: brightness(1.1); }}
  .btn:active {{ filter: brightness(0.9); }}
  .btn:disabled {{ background: #475569; cursor: not-allowed; filter: none; }}
  .btn-primary {{ background: #3b82f6; }}
  .btn-primary:hover {{ background: #2563eb; }}
  .btn-row {{ display: flex; gap: 10px; align-items: center; margin-top: 16px; flex-wrap: wrap; }}
  .btn-msg {{ font-size: 0.82rem; color: #94a3b8; }}
  pre {{ background: #0f172a; border-radius: 6px; padding: 12px; font-size: 0.78rem;
         overflow-x: auto; max-height: 320px; overflow-y: auto; color: #cbd5e1;
         line-height: 1.6; white-space: pre-wrap; word-break: break-all; }}
  a {{ color: #60a5fa; text-decoration: none; }}
  a:hover {{ text-decoration: underline; }}
  .footer {{ text-align: center; color: #475569; font-size: 0.75rem; margin-top: 24px; }}

  /* Schedule control */
  .schedule-bar {{ display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }}
  .schedule-state {{ font-size: 0.82rem; font-weight: 600; color: {schedule_colour}; }}

  /* Skip hours config */
  .config-row {{ display: flex; align-items: center; gap: 10px; margin-top: 12px; flex-wrap: wrap; }}
  .config-row label {{ font-size: 0.82rem; color: #94a3b8; }}
  .config-row input {{ background: #0f172a; border: 1px solid #334155; border-radius: 6px;
                        color: #e2e8f0; padding: 6px 10px; width: 70px; font-size: 0.85rem; }}
  .config-row .btn-sm {{ padding: 6px 14px; font-size: 0.8rem; border-radius: 6px; }}

  /* History chart */
  .chart-container {{ position: relative; height: 120px; margin-top: 8px; }}
  .chart-bar-wrap {{ display: flex; align-items: flex-end; gap: 3px; height: 100px; padding: 0 2px; }}
  .chart-bar {{ flex: 1; min-width: 4px; border-radius: 3px 3px 0 0; position: relative; cursor: default;
                transition: opacity 0.15s; }}
  .chart-bar:hover {{ opacity: 0.8; }}
  .chart-labels {{ display: flex; justify-content: space-between; font-size: 0.65rem; color: #475569;
                    margin-top: 4px; padding: 0 2px; }}
  .chart-legend {{ display: flex; gap: 16px; font-size: 0.72rem; color: #94a3b8; margin-top: 8px; }}
  .chart-legend span::before {{ content: ''; display: inline-block; width: 8px; height: 8px;
                                  border-radius: 2px; margin-right: 4px; vertical-align: middle; }}
  .legend-ok::before {{ background: #22c55e; }}
  .legend-skip::before {{ background: #3b82f6; }}
  .legend-err::before {{ background: #ef4444; }}
  .tooltip {{ position: absolute; background: #1e293b; border: 1px solid #334155; border-radius: 6px;
              padding: 6px 10px; font-size: 0.72rem; color: #e2e8f0; pointer-events: none;
              white-space: nowrap; z-index: 10; display: none; }}
</style>
</head>
<body>
<div class="container">
  <h1>Print Blockage Stopper</h1>
  <p class="subtitle">Automated Print Head Maintenance for Network Printers</p>

  <!-- Status card -->
  <div class="card">
    <h2>Status</h2>
    <div class="status-row">
      <div class="status-dot"></div>
      <div class="status-label">{status_label}</div>
    </div>
    <div class="meta">
      <span>Last print: {html_mod.escape(status["timestamp"])}</span>
      <span>{html_mod.escape(status["message"])}</span>
    </div>
    <div class="meta" style="margin-top: 6px;">
      <span>Printer: <code>{html_mod.escape(printer_ip)}</code></span>
    </div>
    <div class="btn-row">
      <button class="btn btn-primary" id="printBtn" onclick="triggerPrint()">Print Now</button>
      <span class="btn-msg" id="printMsg"></span>
    </div>
  </div>

  <!-- Schedule control card -->
  <div class="card">
    <h2>Schedule</h2>
    <div class="schedule-bar">
      <span class="meta">Cron: <code>{html_mod.escape(schedule)}</code></span>
      <span class="schedule-state" id="schedState">{schedule_state}</span>
      <button class="btn" id="pauseBtn"
              style="background:{pause_btn_colour}; padding:8px 18px; font-size:0.85rem;"
              onclick="toggleSchedule()">{pause_btn_label}</button>
    </div>
    <div class="config-row">
      <label for="skipHours">Skip print if printer was active within:</label>
      <input type="number" id="skipHours" value="{skip_hours}" min="1" max="720">
      <span class="meta">hours</span>
      <button class="btn btn-primary btn-sm" onclick="saveSkipHours()">Save</button>
      <span class="btn-msg" id="skipMsg"></span>
    </div>
  </div>

  <!-- History chart card -->
  <div class="card">
    <h2>Print History (Last 30 days)</h2>
    <div class="chart-container">
      <div class="chart-bar-wrap" id="chartBars"></div>
      <div class="chart-labels" id="chartLabels"></div>
      <div class="chart-legend">
        <span class="legend-ok">Printed</span>
        <span class="legend-skip">Skipped</span>
        <span class="legend-err">Failed</span>
      </div>
    </div>
    <div class="tooltip" id="tooltip"></div>
  </div>

  <!-- Logs card -->
  <div class="card">
    <h2>Recent Logs</h2>
    <pre id="logs">{escaped_logs}</pre>
  </div>

  <div class="card" style="padding: 14px 20px;">
    <a href="/printers" target="_blank">CUPS Printer Status (port 631)</a>
  </div>

  <div class="footer">print-blockage-stopper v1.1</div>
</div>

<script>
const historyData = {history_json};

// ── Print Now ───────────────────────────────────────────────
function triggerPrint() {{
  const btn = document.getElementById('printBtn');
  const msg = document.getElementById('printMsg');
  btn.disabled = true;
  btn.textContent = 'Sending...';
  msg.textContent = '';
  fetch('/api/print-now', {{ method: 'POST' }})
    .then(r => r.json())
    .then(() => {{
      btn.textContent = 'Print Now';
      btn.disabled = false;
      msg.textContent = 'Print job triggered. Check logs below.';
      setTimeout(refreshLogs, 3000);
    }})
    .catch(e => {{
      btn.textContent = 'Print Now';
      btn.disabled = false;
      msg.textContent = 'Error: ' + e.message;
    }});
}}

// ── Toggle Schedule ─────────────────────────────────────────
function toggleSchedule() {{
  const btn = document.getElementById('pauseBtn');
  btn.disabled = true;
  fetch('/api/toggle-schedule', {{ method: 'POST' }})
    .then(r => r.json())
    .then(d => {{
      const paused = d.paused;
      btn.textContent = paused ? 'Resume Schedule' : 'Pause Schedule';
      btn.style.background = paused ? '#22c55e' : '#f59e0b';
      btn.disabled = false;
      const st = document.getElementById('schedState');
      st.textContent = paused ? 'PAUSED' : 'Active';
      st.style.color = paused ? '#ef4444' : '#22c55e';
    }})
    .catch(() => {{ btn.disabled = false; }});
}}

// ── Save skip hours ─────────────────────────────────────────
function saveSkipHours() {{
  const val = document.getElementById('skipHours').value;
  const msg = document.getElementById('skipMsg');
  fetch('/api/config', {{
    method: 'POST',
    headers: {{ 'Content-Type': 'application/json' }},
    body: JSON.stringify({{ skip_hours: parseInt(val) }})
  }})
    .then(r => r.json())
    .then(d => {{
      msg.textContent = d.ok ? 'Saved' : 'Error';
      setTimeout(() => {{ msg.textContent = ''; }}, 3000);
    }})
    .catch(e => {{ msg.textContent = 'Error: ' + e.message; }});
}}

// ── History chart ───────────────────────────────────────────
function renderChart() {{
  const container = document.getElementById('chartBars');
  const labels = document.getElementById('chartLabels');
  const tooltip = document.getElementById('tooltip');

  if (!historyData.length) {{
    container.innerHTML = '<span style="color:#475569;font-size:0.8rem;padding:40px 0;display:block;text-align:center;">No print history yet</span>';
    return;
  }}

  // Group by date
  const byDate = {{}};
  historyData.forEach(e => {{
    const d = e.timestamp.split(' ')[0];
    if (!byDate[d]) byDate[d] = [];
    byDate[d].push(e);
  }});

  // Fill last 30 days
  const days = [];
  const now = new Date();
  for (let i = 29; i >= 0; i--) {{
    const d = new Date(now);
    d.setDate(d.getDate() - i);
    const key = d.toISOString().split('T')[0];
    days.push({{ date: key, entries: byDate[key] || [] }});
  }}

  container.innerHTML = '';
  days.forEach(day => {{
    const bar = document.createElement('div');
    bar.className = 'chart-bar';

    const oks = day.entries.filter(e => e.result === 'ok').length;
    const skips = day.entries.filter(e => e.result === 'skipped').length;
    const errs = day.entries.filter(e => e.result === 'error').length;
    const total = oks + skips + errs;

    if (total === 0) {{
      bar.style.height = '4px';
      bar.style.background = '#1e293b';
    }} else {{
      bar.style.height = Math.max(8, Math.min(100, total * 25)) + 'px';
      if (errs > 0) bar.style.background = '#ef4444';
      else if (oks > 0) bar.style.background = '#22c55e';
      else bar.style.background = '#3b82f6';
    }}

    bar.title = `${{day.date}}: ${{oks}} printed, ${{skips}} skipped, ${{errs}} failed`;

    bar.addEventListener('mouseenter', (ev) => {{
      tooltip.style.display = 'block';
      tooltip.textContent = bar.title;
      const rect = bar.getBoundingClientRect();
      const pr = bar.closest('.card').getBoundingClientRect();
      tooltip.style.left = (rect.left - pr.left) + 'px';
      tooltip.style.top = (rect.top - pr.top - 30) + 'px';
    }});
    bar.addEventListener('mouseleave', () => {{
      tooltip.style.display = 'none';
    }});

    container.appendChild(bar);
  }});

  // Date labels (first, middle, last)
  if (days.length >= 3) {{
    const fmt = d => d.slice(5);  // MM-DD
    labels.innerHTML = `<span>${{fmt(days[0].date)}}</span><span>${{fmt(days[14].date)}}</span><span>${{fmt(days[29].date)}}</span>`;
  }}
}}

function refreshLogs() {{
  fetch('/api/logs').then(r => r.json()).then(d => {{
    document.getElementById('logs').textContent = d.logs;
  }});
}}

// ── Init ────────────────────────────────────────────────────
renderChart();

// Auto-refresh logs and status every 30 seconds
setInterval(() => {{
  refreshLogs();
  fetch('/api/status').then(r => r.json()).then(d => {{
    // Soft-update status without full reload
    const dot = document.querySelector('.status-dot');
    const label = document.querySelector('.status-label');
    const colours = {{ ok: '#22c55e', error: '#ef4444', unknown: '#a3a3a3' }};
    const labels = {{ ok: 'OK', error: 'FAILED', unknown: 'No prints yet' }};
    dot.style.background = colours[d.status] || '#a3a3a3';
    dot.style.boxShadow = `0 0 8px ${{colours[d.status] || '#a3a3a3'}}80`;
    label.textContent = labels[d.status] || d.status;
  }});
}}, 30000);
</script>
</body>
</html>"""
        body = html.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    server = http.server.HTTPServer(("0.0.0.0", PORT), Handler)
    print(f"Web UI running on http://0.0.0.0:{PORT}")
    server.serve_forever()

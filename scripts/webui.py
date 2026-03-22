#!/usr/bin/env python3
"""
Lightweight web UI for print-blockage-stopper.
Serves a status dashboard with a "Print Now" button on port 8631.
"""

import http.server
import json
import os
import subprocess
import threading
from datetime import datetime

PORT = 8631
STATUS_FILE = "/data/status.json"
LOG_FILE = "/data/logs/auto-print.log"

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

def get_schedule():
    return os.environ.get("SCHEDULE", "0 10 */3 * *")

def get_printer_ip():
    return os.environ.get("PRINTER_IP", "unknown")

def trigger_print():
    """Run auto-print.sh in background."""
    subprocess.Popen(
        ["/app/auto-print.sh"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env={**os.environ}
    )

class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # Suppress default logging

    def do_GET(self):
        if self.path == "/api/status":
            self._json_response(get_status())
        elif self.path == "/api/logs":
            self._json_response({"logs": get_recent_logs(30)})
        elif self.path == "/":
            self._serve_dashboard()
        else:
            self.send_error(404)

    def do_POST(self):
        if self.path == "/api/print-now":
            trigger_print()
            self._json_response({"ok": True, "message": "Print job triggered"})
        else:
            self.send_error(404)

    def _json_response(self, data):
        body = json.dumps(data).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)

    def _serve_dashboard(self):
        status = get_status()
        logs = get_recent_logs(25)
        schedule = get_schedule()
        printer_ip = get_printer_ip()

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
  .btn {{ background: #3b82f6; color: white; border: none; border-radius: 8px;
          padding: 10px 24px; font-size: 0.95rem; cursor: pointer; font-weight: 500;
          transition: background 0.15s; }}
  .btn:hover {{ background: #2563eb; }}
  .btn:active {{ background: #1d4ed8; }}
  .btn:disabled {{ background: #475569; cursor: not-allowed; }}
  .btn-row {{ display: flex; gap: 10px; align-items: center; margin-top: 16px; }}
  .btn-msg {{ font-size: 0.82rem; color: #94a3b8; }}
  pre {{ background: #0f172a; border-radius: 6px; padding: 12px; font-size: 0.78rem;
         overflow-x: auto; max-height: 320px; overflow-y: auto; color: #cbd5e1;
         line-height: 1.6; white-space: pre-wrap; word-break: break-all; }}
  a {{ color: #60a5fa; text-decoration: none; }}
  a:hover {{ text-decoration: underline; }}
  .footer {{ text-align: center; color: #475569; font-size: 0.75rem; margin-top: 24px; }}
</style>
</head>
<body>
<div class="container">
  <h1>Print Blockage Stopper</h1>
  <p class="subtitle">Automated Print Head Maintenance for Network Printers</p>

  <div class="card">
    <h2>Status</h2>
    <div class="status-row">
      <div class="status-dot"></div>
      <div class="status-label">{status_label}</div>
    </div>
    <div class="meta">
      <span>Last print: {status["timestamp"]}</span>
      <span>{status["message"]}</span>
    </div>
    <div class="meta" style="margin-top: 6px;">
      <span>Schedule: <code>{schedule}</code></span>
      <span>Printer: <code>{printer_ip}</code></span>
    </div>
    <div class="btn-row">
      <button class="btn" id="printBtn" onclick="triggerPrint()">Print Now</button>
      <span class="btn-msg" id="printMsg"></span>
    </div>
  </div>

  <div class="card">
    <h2>Recent Logs</h2>
    <pre id="logs">{logs}</pre>
  </div>

  <div class="card" style="padding: 14px 20px;">
    <a href="/printers" target="_blank">CUPS Printer Status (port 631)</a>
  </div>

  <div class="footer">print-blockage-stopper</div>
</div>

<script>
function triggerPrint() {{
  const btn = document.getElementById('printBtn');
  const msg = document.getElementById('printMsg');
  btn.disabled = true;
  btn.textContent = 'Sending...';
  msg.textContent = '';
  fetch('/api/print-now', {{ method: 'POST' }})
    .then(r => r.json())
    .then(d => {{
      btn.textContent = 'Print Now';
      btn.disabled = false;
      msg.textContent = 'Print job triggered. Check logs for result.';
      setTimeout(refreshLogs, 3000);
    }})
    .catch(e => {{
      btn.textContent = 'Print Now';
      btn.disabled = false;
      msg.textContent = 'Error: ' + e.message;
    }});
}}

function refreshLogs() {{
  fetch('/api/logs')
    .then(r => r.json())
    .then(d => {{
      document.getElementById('logs').textContent = d.logs;
    }});
  fetch('/api/status')
    .then(r => r.json())
    .then(d => {{
      // Reload to update status dot
      window.location.reload();
    }});
}}

// Auto-refresh logs every 30 seconds
setInterval(() => {{
  fetch('/api/logs').then(r => r.json()).then(d => {{
    document.getElementById('logs').textContent = d.logs;
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

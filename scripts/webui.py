#!/usr/bin/env python3
"""
Web UI for print-blockage-stopper v1.3.
Multi-printer dashboard with:
  - Add/remove printers (manual IP or mDNS discovery)
  - Per-printer status, schedule, skip-hours, pause/resume
  - Print history chart (30 days)
  - Test image selection (presets or custom upload)
  - Print Now per printer
"""

import cgi
import http.server
import json
import html as html_mod
import os
import re
import shutil
import subprocess
import uuid
from datetime import datetime
from pathlib import Path

PORT = 8631
DATA_DIR = "/data"
PRINTERS_FILE = f"{DATA_DIR}/printers.json"
HISTORY_FILE = f"{DATA_DIR}/print-history.json"
LOG_FILE = f"{DATA_DIR}/logs/auto-print.log"
UPLOADS_DIR = f"{DATA_DIR}/uploads"
PRESETS_DIR = "/app/presets"
MAX_UPLOAD_BYTES = 5 * 1024 * 1024  # 5 MB

os.makedirs(UPLOADS_DIR, exist_ok=True)

# ── Printer config helpers ──────────────────────────────────────

def read_printers():
    try:
        with open(PRINTERS_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"printers": [], "global": {"schedule": os.environ.get("SCHEDULE", "0 10 */3 * *"),
                                            "skip_hours": int(os.environ.get("SKIP_HOURS", "72"))}}

def write_printers(data):
    with open(PRINTERS_FILE, "w") as f:
        json.dump(data, f, indent=2)

def get_printer_by_id(printer_id):
    data = read_printers()
    for p in data["printers"]:
        if p["id"] == printer_id:
            return p
    return None

def sanitise_cups_name(name):
    """Create a valid CUPS printer name from user input."""
    s = re.sub(r'[^a-zA-Z0-9_-]', '_', name)
    return s[:64] or "PRINTER"

# ── CUPS management ─────────────────────────────────────────────

def add_cups_printer(printer):
    """Add or update a printer in CUPS."""
    cups_name = printer["cups_name"]
    conn = printer.get("connection", "ipp")
    ip = printer["ip"]
    port = printer.get("port", 9100)

    if conn == "socket":
        uri = f"socket://{ip}:{port}"
    else:
        uri = f"ipp://{ip}/ipp/print"

    paper = printer.get("paper_size", "A4")

    try:
        subprocess.run(
            ["lpadmin", "-p", cups_name, "-v", uri, "-m", "everywhere",
             "-L", "Network", "-D", printer.get("name", cups_name),
             "-o", f"media={paper}"],
            check=True, capture_output=True, timeout=15
        )
        subprocess.run(["cupsaccept", cups_name], capture_output=True, timeout=5)
        subprocess.run(["cupsenable", cups_name], capture_output=True, timeout=5)
        return True
    except Exception as e:
        print(f"Error adding CUPS printer {cups_name}: {e}")
        return False

def remove_cups_printer(cups_name):
    try:
        subprocess.run(["lpadmin", "-x", cups_name], capture_output=True, timeout=10)
    except Exception:
        pass

# ── mDNS / IPP discovery ───────────────────────────────────────

def discover_printers():
    """Try to discover IPP printers via avahi-browse (mDNS)."""
    found = []
    try:
        result = subprocess.run(
            ["avahi-browse", "-t", "-r", "-p", "_ipp._tcp"],
            capture_output=True, text=True, timeout=10
        )
        # Parse avahi-browse parseable output
        current = {}
        for line in result.stdout.splitlines():
            parts = line.split(";")
            if len(parts) < 10:
                continue
            if parts[0] == "=":
                name = parts[3]
                ip = parts[7]
                port = parts[8]
                # Skip IPv6 link-local
                if ":" in ip and ip.startswith("fe80"):
                    continue
                if ip and not any(f["ip"] == ip for f in found):
                    found.append({
                        "name": name.replace("\\032", " "),
                        "ip": ip,
                        "port": int(port) if port.isdigit() else 631
                    })
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    # Fallback: try ippfind
    if not found:
        try:
            result = subprocess.run(
                ["ippfind", "--timeout", "5"],
                capture_output=True, text=True, timeout=10
            )
            for line in result.stdout.strip().splitlines():
                # ippfind returns URIs like ipp://192.168.1.23:631/ipp/print
                m = re.match(r'ipp://([^:/]+)', line)
                if m:
                    ip = m.group(1)
                    if not any(f["ip"] == ip for f in found):
                        found.append({"name": f"Printer at {ip}", "ip": ip, "port": 631})
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

    return found

# ── Print helpers ───────────────────────────────────────────────

def get_test_image_path(printer):
    """Resolve the test image path for a printer."""
    img = printer.get("test_image", "preset-11")
    if img.startswith("preset-"):
        path = f"{PRESETS_DIR}/{img}.png"
        if os.path.exists(path):
            return path
    elif img.startswith("custom-"):
        path = f"{UPLOADS_DIR}/{img}"
        if os.path.exists(path):
            return path
    # Fallback to legacy test image
    if os.path.exists("/app/test-print.png"):
        return "/app/test-print.png"
    return f"{PRESETS_DIR}/preset-11.png"

def trigger_print(printer_id):
    """Run auto-print.sh --force --printer-id=X in background."""
    subprocess.Popen(
        ["/app/auto-print.sh", "--force", f"--printer-id={printer_id}"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env={**os.environ}
    )

def trigger_print_all():
    """Run auto-print.sh --force for all printers."""
    data = read_printers()
    for p in data["printers"]:
        trigger_print(p["id"])

# ── Status / history / logs ─────────────────────────────────────

def get_printer_status(printer_id):
    status_file = f"{DATA_DIR}/status-{printer_id}.json"
    try:
        with open(status_file) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"status": "unknown", "message": "No prints yet", "timestamp": "—"}

def get_history():
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

def get_recent_logs(lines=25):
    try:
        with open(LOG_FILE) as f:
            all_lines = f.readlines()
            return "".join(all_lines[-lines:])
    except FileNotFoundError:
        return "No log entries yet."

def get_available_presets():
    presets = []
    if os.path.isdir(PRESETS_DIR):
        for f in sorted(os.listdir(PRESETS_DIR)):
            if f.endswith(".png") and f.startswith("preset-"):
                name = f.replace(".png", "")
                channels = name.split("-")[1]
                presets.append({"id": name, "label": f"{channels}-colour", "file": f})
    return presets

def get_uploaded_images():
    images = []
    if os.path.isdir(UPLOADS_DIR):
        for f in sorted(os.listdir(UPLOADS_DIR)):
            if f.lower().endswith((".png", ".jpg", ".jpeg", ".bmp", ".tiff")):
                images.append({"id": f"custom-{f}", "label": f, "file": f})
    return images

# ── Cron management ─────────────────────────────────────────────

def update_cron():
    """Rebuild crontab from printer configs."""
    data = read_printers()
    lines = []
    for p in data["printers"]:
        if not p.get("paused", False):
            schedule = p.get("schedule", data["global"]["schedule"])
            lines.append(f'{schedule} /app/auto-print.sh --printer-id={p["id"]} >> /data/logs/cron.log 2>&1')
    cron_content = "\n".join(lines) + "\n" if lines else ""
    subprocess.run(["bash", "-c", f'echo "{cron_content}" | crontab -'],
                   capture_output=True, timeout=5)

# ── HTTP Handler ────────────────────────────────────────────────

class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def do_GET(self):
        if self.path == "/":
            self._serve_dashboard()
        elif self.path == "/api/printers":
            self._json_response(read_printers())
        elif self.path == "/api/discover":
            self._json_response({"printers": discover_printers()})
        elif self.path == "/api/history":
            self._json_response({"history": get_history()})
        elif self.path == "/api/logs":
            self._json_response({"logs": get_recent_logs(30)})
        elif self.path == "/api/presets":
            self._json_response({"presets": get_available_presets(), "uploads": get_uploaded_images()})
        elif self.path.startswith("/api/status/"):
            pid = self.path.split("/")[-1]
            self._json_response(get_printer_status(pid))
        else:
            self.send_error(404)

    def do_POST(self):
        if self.path == "/api/printers/add":
            self._handle_add_printer()
        elif self.path == "/api/printers/remove":
            self._handle_remove_printer()
        elif self.path == "/api/printers/update":
            self._handle_update_printer()
        elif self.path.startswith("/api/print-now/"):
            pid = self.path.split("/")[-1]
            if pid == "all":
                trigger_print_all()
                self._json_response({"ok": True, "message": "Print triggered for all printers"})
            else:
                trigger_print(pid)
                self._json_response({"ok": True, "message": f"Print triggered for {pid}"})
        elif self.path.startswith("/api/toggle-schedule/"):
            pid = self.path.split("/")[-1]
            self._handle_toggle_schedule(pid)
        elif self.path == "/api/upload-image":
            self._handle_upload_image()
        else:
            self.send_error(404)

    def _read_json_body(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) if length else b"{}"
        return json.loads(body)

    def _json_response(self, data, status=200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)

    # ── Printer CRUD ─────────────────────────────────────────

    def _handle_add_printer(self):
        try:
            body = self._read_json_body()
        except json.JSONDecodeError:
            self._json_response({"ok": False, "message": "Invalid JSON"}, 400)
            return

        ip = body.get("ip", "").strip()
        if not ip or not re.match(r'^[a-zA-Z0-9][a-zA-Z0-9.\-]{0,253}[a-zA-Z0-9]$', ip):
            self._json_response({"ok": False, "message": "Invalid IP address or hostname"}, 400)
            return

        data = read_printers()
        # Check for duplicate IP
        if any(p["ip"] == ip for p in data["printers"]):
            self._json_response({"ok": False, "message": f"Printer at {ip} already exists"}, 400)
            return

        printer_id = f"printer-{uuid.uuid4().hex[:8]}"
        name = body.get("name", f"Printer at {ip}").strip()[:64]
        cups_name = sanitise_cups_name(f"PBS_{printer_id}")

        printer = {
            "id": printer_id,
            "name": name,
            "ip": ip,
            "connection": body.get("connection", "ipp"),
            "port": int(body.get("port", 9100)),
            "paper_size": body.get("paper_size", "A4"),
            "schedule": body.get("schedule", data["global"]["schedule"]),
            "skip_hours": int(body.get("skip_hours", data["global"]["skip_hours"])),
            "paused": False,
            "test_image": body.get("test_image", "preset-11"),
            "cups_name": cups_name,
        }

        # Add to CUPS
        if not add_cups_printer(printer):
            self._json_response({"ok": False, "message": "Failed to add printer to CUPS. Check the IP and connection."}, 500)
            return

        data["printers"].append(printer)
        write_printers(data)
        update_cron()
        self._json_response({"ok": True, "printer": printer})

    def _handle_remove_printer(self):
        try:
            body = self._read_json_body()
        except json.JSONDecodeError:
            self._json_response({"ok": False, "message": "Invalid JSON"}, 400)
            return

        pid = body.get("id", "")
        data = read_printers()
        printer = None
        for p in data["printers"]:
            if p["id"] == pid:
                printer = p
                break

        if not printer:
            self._json_response({"ok": False, "message": "Printer not found"}, 404)
            return

        remove_cups_printer(printer["cups_name"])
        data["printers"] = [p for p in data["printers"] if p["id"] != pid]
        write_printers(data)
        update_cron()

        # Clean up status file
        status_file = f"{DATA_DIR}/status-{pid}.json"
        if os.path.exists(status_file):
            os.remove(status_file)

        self._json_response({"ok": True, "message": f"Printer {printer['name']} removed"})

    def _handle_update_printer(self):
        try:
            body = self._read_json_body()
        except json.JSONDecodeError:
            self._json_response({"ok": False, "message": "Invalid JSON"}, 400)
            return

        pid = body.get("id", "")
        data = read_printers()
        printer = None
        for p in data["printers"]:
            if p["id"] == pid:
                printer = p
                break

        if not printer:
            self._json_response({"ok": False, "message": "Printer not found"}, 404)
            return

        # Updateable fields
        changed_cups = False
        for key in ["name", "ip", "connection", "port", "paper_size"]:
            if key in body:
                if printer.get(key) != body[key]:
                    changed_cups = True
                printer[key] = body[key]

        for key in ["schedule", "skip_hours", "paused", "test_image"]:
            if key in body:
                printer[key] = body[key]

        if changed_cups:
            add_cups_printer(printer)

        write_printers(data)
        update_cron()
        self._json_response({"ok": True, "printer": printer})

    def _handle_toggle_schedule(self, printer_id):
        data = read_printers()
        for p in data["printers"]:
            if p["id"] == printer_id:
                p["paused"] = not p.get("paused", False)
                write_printers(data)
                update_cron()
                state = "paused" if p["paused"] else "running"
                self._json_response({"ok": True, "paused": p["paused"], "message": f"Schedule {state}"})
                return
        self._json_response({"ok": False, "message": "Printer not found"}, 404)

    # ── Image upload ─────────────────────────────────────────

    def _handle_upload_image(self):
        content_type = self.headers.get("Content-Type", "")
        if "multipart/form-data" not in content_type:
            self._json_response({"ok": False, "message": "Must be multipart/form-data"}, 400)
            return

        try:
            form = cgi.FieldStorage(
                fp=self.rfile,
                headers=self.headers,
                environ={"REQUEST_METHOD": "POST",
                         "CONTENT_TYPE": content_type}
            )
        except Exception as e:
            self._json_response({"ok": False, "message": str(e)}, 400)
            return

        file_item = form["file"] if "file" in form else None
        if not file_item or not file_item.filename:
            self._json_response({"ok": False, "message": "No file uploaded"}, 400)
            return

        # Validate extension
        filename = os.path.basename(file_item.filename)
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        if ext not in ("png", "jpg", "jpeg", "bmp", "tiff"):
            self._json_response({"ok": False, "message": "Invalid file type. Use PNG, JPG, BMP, or TIFF."}, 400)
            return

        # Read with size limit
        data = file_item.file.read(MAX_UPLOAD_BYTES + 1)
        if len(data) > MAX_UPLOAD_BYTES:
            self._json_response({"ok": False, "message": "File too large. Maximum 5 MB."}, 400)
            return

        # Sanitise filename
        safe_name = re.sub(r'[^a-zA-Z0-9._-]', '_', filename)
        dest = os.path.join(UPLOADS_DIR, safe_name)
        with open(dest, "wb") as f:
            f.write(data)

        self._json_response({"ok": True, "id": f"custom-{safe_name}", "filename": safe_name})

    # ── Dashboard HTML ───────────────────────────────────────

    def _serve_dashboard(self):
        data = read_printers()
        printers = data["printers"]
        history = get_history()
        logs = get_recent_logs(25)
        presets = get_available_presets()
        uploads = get_uploaded_images()

        # Build printer cards HTML
        printer_cards = ""
        if not printers:
            printer_cards = '<div class="empty-state">No printers configured yet. Add one below or use Discover.</div>'
        else:
            for p in printers:
                st = get_printer_status(p["id"])
                st_colour = {"ok": "#22c55e", "error": "#ef4444"}.get(st["status"], "#a3a3a3")
                st_label = {"ok": "OK", "error": "FAILED"}.get(st["status"], "No prints yet")
                paused = p.get("paused", False)
                pause_label = "Resume" if paused else "Pause"
                pause_colour = "#22c55e" if paused else "#f59e0b"
                sched_state = "PAUSED" if paused else "Active"
                sched_colour = "#ef4444" if paused else "#22c55e"
                test_img = p.get("test_image", "preset-11")

                # Build test image options
                img_options = ""
                for pr in presets:
                    sel = "selected" if pr["id"] == test_img else ""
                    img_options += f'<option value="{pr["id"]}" {sel}>{html_mod.escape(pr["label"])}</option>'
                for up in uploads:
                    sel = "selected" if up["id"] == test_img else ""
                    img_options += f'<option value="{up["id"]}" {sel}>{html_mod.escape(up["label"])}</option>'

                printer_cards += f"""
      <div class="card printer-card" data-id="{p["id"]}">
        <div class="printer-header">
          <div class="status-row">
            <div class="status-dot" style="background:{st_colour};box-shadow:0 0 8px {st_colour}80;"></div>
            <div class="printer-name">{html_mod.escape(p["name"])}</div>
            <span class="printer-ip">{html_mod.escape(p["ip"])}</span>
          </div>
          <button class="btn-icon" onclick="removePrinter('{p["id"]}')" title="Remove printer">&times;</button>
        </div>
        <div class="meta">
          <span>Status: <strong style="color:{st_colour}">{st_label}</strong></span>
          <span>Last: {html_mod.escape(st["timestamp"])}</span>
          <span>{html_mod.escape(st["message"])}</span>
        </div>
        <div class="printer-controls">
          <div class="control-group">
            <label>Schedule:</label>
            <code>{html_mod.escape(p.get("schedule", "0 10 */3 * *"))}</code>
            <span class="schedule-state" style="color:{sched_colour}">{sched_state}</span>
            <button class="btn btn-sm" style="background:{pause_colour}" onclick="toggleSchedule('{p["id"]}')">{pause_label}</button>
          </div>
          <div class="control-group">
            <label>Skip if active within:</label>
            <input type="number" class="input-sm" value="{p.get("skip_hours", 72)}" min="1" max="720"
                   id="skip-{p["id"]}" onchange="updatePrinter('{p["id"]}', {{skip_hours: parseInt(this.value)}})">
            <span class="meta">hours</span>
          </div>
          <div class="control-group">
            <label>Test image:</label>
            <select class="input-sm select-sm" id="img-{p["id"]}"
                    onchange="updatePrinter('{p["id"]}', {{test_image: this.value}})">
              {img_options}
            </select>
          </div>
          <div class="btn-row">
            <button class="btn btn-primary btn-sm" onclick="printNow('{p["id"]}')">Print Now</button>
            <span class="btn-msg" id="msg-{p["id"]}"></span>
          </div>
        </div>
      </div>"""

        history_json = json.dumps(history[-90:])
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
  .container {{ max-width: 800px; margin: 0 auto; }}
  h1 {{ font-size: 1.4rem; font-weight: 600; margin-bottom: 4px; }}
  .subtitle {{ color: #94a3b8; font-size: 0.85rem; margin-bottom: 24px; }}
  .card {{ background: #1e293b; border-radius: 10px; padding: 20px; margin-bottom: 16px; }}
  .card h2 {{ font-size: 0.85rem; text-transform: uppercase; letter-spacing: 0.05em;
              color: #64748b; margin-bottom: 12px; }}

  /* Printer cards */
  .printer-card {{ border-left: 3px solid #334155; }}
  .printer-header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }}
  .printer-name {{ font-size: 1.05rem; font-weight: 600; }}
  .printer-ip {{ color: #64748b; font-size: 0.8rem; font-family: monospace; margin-left: 10px; }}
  .btn-icon {{ background: none; border: none; color: #64748b; font-size: 1.4rem; cursor: pointer;
               padding: 2px 8px; border-radius: 4px; }}
  .btn-icon:hover {{ background: #334155; color: #ef4444; }}

  .printer-controls {{ display: flex; flex-direction: column; gap: 10px; margin-top: 12px; }}
  .control-group {{ display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }}
  .control-group label {{ font-size: 0.82rem; color: #94a3b8; min-width: 140px; }}

  .status-row {{ display: flex; align-items: center; gap: 10px; }}
  .status-dot {{ width: 10px; height: 10px; border-radius: 50%; flex-shrink: 0; }}
  .meta {{ color: #94a3b8; font-size: 0.82rem; display: flex; gap: 16px; flex-wrap: wrap; }}
  .schedule-state {{ font-size: 0.8rem; font-weight: 600; }}

  /* Buttons */
  .btn {{ color: white; border: none; border-radius: 8px; padding: 10px 24px; font-size: 0.95rem;
          cursor: pointer; font-weight: 500; transition: all 0.15s; }}
  .btn:hover {{ filter: brightness(1.1); }}
  .btn:disabled {{ background: #475569 !important; cursor: not-allowed; filter: none; }}
  .btn-primary {{ background: #3b82f6; }}
  .btn-sm {{ padding: 6px 14px; font-size: 0.8rem; border-radius: 6px; }}
  .btn-row {{ display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }}
  .btn-msg {{ font-size: 0.8rem; color: #94a3b8; }}

  /* Inputs */
  .input-sm {{ background: #0f172a; border: 1px solid #334155; border-radius: 6px;
               color: #e2e8f0; padding: 6px 10px; font-size: 0.85rem; }}
  .input-sm:focus {{ border-color: #3b82f6; outline: none; }}
  input[type=number].input-sm {{ width: 70px; }}
  .select-sm {{ background: #0f172a; border: 1px solid #334155; border-radius: 6px;
                color: #e2e8f0; padding: 6px 10px; font-size: 0.82rem; max-width: 180px; }}

  /* Add printer form */
  .add-form {{ display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-top: 12px; }}
  .add-form .full {{ grid-column: 1 / -1; }}
  .add-form label {{ font-size: 0.8rem; color: #94a3b8; margin-bottom: 2px; display: block; }}
  .add-form input, .add-form select {{ width: 100%; background: #0f172a; border: 1px solid #334155;
    border-radius: 6px; color: #e2e8f0; padding: 8px 10px; font-size: 0.85rem; }}
  .add-form input:focus, .add-form select:focus {{ border-color: #3b82f6; outline: none; }}

  /* Discovery */
  .discover-list {{ display: flex; flex-direction: column; gap: 8px; margin-top: 12px; }}
  .discover-item {{ display: flex; justify-content: space-between; align-items: center;
                     background: #0f172a; padding: 10px 14px; border-radius: 8px; }}
  .discover-item .meta {{ font-size: 0.8rem; }}

  /* Empty state */
  .empty-state {{ text-align: center; color: #64748b; padding: 30px 20px; font-size: 0.9rem; }}

  /* Chart */
  .chart-container {{ position: relative; height: 120px; margin-top: 8px; }}
  .chart-bar-wrap {{ display: flex; align-items: flex-end; gap: 3px; height: 100px; padding: 0 2px; }}
  .chart-bar {{ flex: 1; min-width: 4px; border-radius: 3px 3px 0 0; cursor: default; transition: opacity 0.15s; }}
  .chart-bar:hover {{ opacity: 0.8; }}
  .chart-labels {{ display: flex; justify-content: space-between; font-size: 0.65rem; color: #475569;
                    margin-top: 4px; padding: 0 2px; }}
  .chart-legend {{ display: flex; gap: 16px; font-size: 0.72rem; color: #94a3b8; margin-top: 8px; }}
  .chart-legend span::before {{ content: ''; display: inline-block; width: 8px; height: 8px;
                                  border-radius: 2px; margin-right: 4px; vertical-align: middle; }}
  .legend-ok::before {{ background: #22c55e; }}
  .legend-skip::before {{ background: #3b82f6; }}
  .legend-err::before {{ background: #ef4444; }}

  /* Upload */
  .upload-area {{ display: flex; align-items: center; gap: 12px; margin-top: 10px; flex-wrap: wrap; }}
  .upload-area input[type=file] {{ font-size: 0.82rem; color: #94a3b8; }}

  pre {{ background: #0f172a; border-radius: 6px; padding: 12px; font-size: 0.78rem;
         overflow-x: auto; max-height: 320px; overflow-y: auto; color: #cbd5e1;
         line-height: 1.6; white-space: pre-wrap; word-break: break-all; }}
  a {{ color: #60a5fa; text-decoration: none; }}
  a:hover {{ text-decoration: underline; }}
  .footer {{ text-align: center; color: #475569; font-size: 0.75rem; margin-top: 24px; }}
  code {{ background: #0f172a; padding: 2px 6px; border-radius: 4px; font-size: 0.82rem; }}
  .section-divider {{ border-top: 1px solid #334155; margin: 16px 0; }}
</style>
</head>
<body>
<div class="container">
  <h1>Print Blockage Stopper</h1>
  <p class="subtitle">Automated Print Head Maintenance for Network Printers</p>

  <!-- ── Printer Cards ─────────────────────────────── -->
  <div id="printerCards">
    {printer_cards}
  </div>

  <!-- ── Add Printer ───────────────────────────────── -->
  <div class="card">
    <h2>Add Printer</h2>
    <div class="btn-row" style="margin-bottom:12px;">
      <button class="btn btn-sm" style="background:#6366f1" onclick="discoverPrinters()" id="discoverBtn">
        Discover Printers on Network
      </button>
      <span class="btn-msg" id="discoverMsg"></span>
    </div>
    <div id="discoverResults"></div>
    <div class="section-divider"></div>
    <div class="add-form" id="addForm">
      <div>
        <label for="addName">Name</label>
        <input type="text" id="addName" placeholder="e.g. Canon Pro 1100" maxlength="64">
      </div>
      <div>
        <label for="addIp">IP Address *</label>
        <input type="text" id="addIp" placeholder="192.168.1.50" required>
      </div>
      <div>
        <label for="addConn">Connection</label>
        <select id="addConn">
          <option value="ipp" selected>IPP (recommended)</option>
          <option value="socket">Socket (port 9100)</option>
        </select>
      </div>
      <div>
        <label for="addPaper">Paper Size</label>
        <input type="text" id="addPaper" value="A4" maxlength="20">
      </div>
      <div class="full">
        <button class="btn btn-primary" onclick="addPrinter()" id="addBtn">Add Printer</button>
        <span class="btn-msg" id="addMsg" style="margin-left:10px;"></span>
      </div>
    </div>
  </div>

  <!-- ── Test Image Upload ─────────────────────────── -->
  <div class="card">
    <h2>Custom Test Image</h2>
    <p class="meta" style="margin-bottom:8px;">Upload a custom test image (PNG, JPG, BMP, TIFF — max 5 MB). After uploading, select it in a printer's settings above.</p>
    <div class="upload-area">
      <input type="file" id="uploadFile" accept=".png,.jpg,.jpeg,.bmp,.tiff">
      <button class="btn btn-primary btn-sm" onclick="uploadImage()">Upload</button>
      <span class="btn-msg" id="uploadMsg"></span>
    </div>
  </div>

  <!-- ── Print History ─────────────────────────────── -->
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
  </div>

  <!-- ── Logs ──────────────────────────────────────── -->
  <div class="card">
    <h2>Recent Logs</h2>
    <pre id="logs">{escaped_logs}</pre>
  </div>

  <div class="card" style="padding: 14px 20px;">
    <a href="/printers" target="_blank">CUPS Printer Status (port 631)</a>
  </div>

  <div class="footer">print-blockage-stopper v1.3</div>
</div>

<script>
const historyData = {history_json};

// ── API helpers ─────────────────────────────────────────
function api(path, method, body) {{
  const opts = {{ method }};
  if (body) {{
    opts.headers = {{ 'Content-Type': 'application/json' }};
    opts.body = JSON.stringify(body);
  }}
  return fetch(path, opts).then(r => r.json());
}}

function setMsg(id, text, timeout) {{
  const el = document.getElementById(id);
  if (el) {{ el.textContent = text; if (timeout) setTimeout(() => el.textContent = '', timeout); }}
}}

// ── Printer actions ─────────────────────────────────────
function printNow(id) {{
  api('/api/print-now/' + id, 'POST').then(() => {{
    setMsg('msg-' + id, 'Print triggered. Check logs.', 5000);
    setTimeout(refreshLogs, 3000);
  }});
}}

function toggleSchedule(id) {{
  api('/api/toggle-schedule/' + id, 'POST').then(() => location.reload());
}}

function updatePrinter(id, updates) {{
  updates.id = id;
  api('/api/printers/update', 'POST', updates).then(d => {{
    if (d.ok) setMsg('msg-' + id, 'Saved', 3000);
  }});
}}

function removePrinter(id) {{
  if (!confirm('Remove this printer?')) return;
  api('/api/printers/remove', 'POST', {{ id }}).then(() => location.reload());
}}

function addPrinter() {{
  const ip = document.getElementById('addIp').value.trim();
  if (!ip) {{ setMsg('addMsg', 'IP address is required', 3000); return; }}
  const btn = document.getElementById('addBtn');
  btn.disabled = true;
  api('/api/printers/add', 'POST', {{
    name: document.getElementById('addName').value.trim() || ('Printer at ' + ip),
    ip,
    connection: document.getElementById('addConn').value,
    paper_size: document.getElementById('addPaper').value.trim() || 'A4'
  }}).then(d => {{
    btn.disabled = false;
    if (d.ok) location.reload();
    else setMsg('addMsg', d.message || 'Failed to add', 5000);
  }}).catch(() => {{ btn.disabled = false; setMsg('addMsg', 'Network error', 3000); }});
}}

// ── Discovery ───────────────────────────────────────────
function discoverPrinters() {{
  const btn = document.getElementById('discoverBtn');
  const container = document.getElementById('discoverResults');
  btn.disabled = true;
  btn.textContent = 'Scanning...';
  setMsg('discoverMsg', '');
  api('/api/discover', 'GET').then(d => {{
    btn.disabled = false;
    btn.textContent = 'Discover Printers on Network';
    if (!d.printers || d.printers.length === 0) {{
      setMsg('discoverMsg', 'No printers found via mDNS. Try adding manually.', 5000);
      container.innerHTML = '';
      return;
    }}
    let html = '<div class="discover-list">';
    d.printers.forEach(p => {{
      html += `<div class="discover-item">
        <div><strong>${{p.name}}</strong> <span class="meta">${{p.ip}}</span></div>
        <button class="btn btn-primary btn-sm" onclick="quickAdd('${{p.ip}}','${{p.name.replace(/'/g, "\\\\'")}}')">Add</button>
      </div>`;
    }});
    html += '</div>';
    container.innerHTML = html;
  }}).catch(() => {{
    btn.disabled = false;
    btn.textContent = 'Discover Printers on Network';
    setMsg('discoverMsg', 'Discovery failed', 3000);
  }});
}}

function quickAdd(ip, name) {{
  document.getElementById('addIp').value = ip;
  document.getElementById('addName').value = name;
  addPrinter();
}}

// ── Image upload ────────────────────────────────────────
function uploadImage() {{
  const input = document.getElementById('uploadFile');
  if (!input.files.length) {{ setMsg('uploadMsg', 'Select a file first', 3000); return; }}
  const file = input.files[0];
  if (file.size > 5 * 1024 * 1024) {{ setMsg('uploadMsg', 'File too large (max 5 MB)', 3000); return; }}
  const form = new FormData();
  form.append('file', file);
  fetch('/api/upload-image', {{ method: 'POST', body: form }})
    .then(r => r.json())
    .then(d => {{
      if (d.ok) {{
        setMsg('uploadMsg', 'Uploaded! Select it in a printer above.', 5000);
        input.value = '';
        setTimeout(() => location.reload(), 1500);
      }} else {{
        setMsg('uploadMsg', d.message || 'Upload failed', 5000);
      }}
    }}).catch(e => setMsg('uploadMsg', 'Error: ' + e.message, 5000));
}}

// ── History chart ───────────────────────────────────────
function renderChart() {{
  const container = document.getElementById('chartBars');
  const labels = document.getElementById('chartLabels');
  if (!historyData.length) {{
    container.innerHTML = '<span style="color:#475569;font-size:0.8rem;padding:40px 0;display:block;text-align:center;">No print history yet</span>';
    return;
  }}
  const byDate = {{}};
  historyData.forEach(e => {{
    const d = e.timestamp.split(' ')[0];
    if (!byDate[d]) byDate[d] = [];
    byDate[d].push(e);
  }});
  const days = [];
  const now = new Date();
  for (let i = 29; i >= 0; i--) {{
    const d = new Date(now); d.setDate(d.getDate() - i);
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
    if (total === 0) {{ bar.style.height = '4px'; bar.style.background = '#1e293b'; }}
    else {{
      bar.style.height = Math.max(8, Math.min(100, total * 20)) + 'px';
      if (errs > 0) bar.style.background = '#ef4444';
      else if (oks > 0) bar.style.background = '#22c55e';
      else bar.style.background = '#3b82f6';
    }}
    bar.title = `${{day.date}}: ${{oks}} printed, ${{skips}} skipped, ${{errs}} failed`;
    container.appendChild(bar);
  }});
  if (days.length >= 3) {{
    const fmt = d => d.slice(5);
    labels.innerHTML = `<span>${{fmt(days[0].date)}}</span><span>${{fmt(days[14].date)}}</span><span>${{fmt(days[29].date)}}</span>`;
  }}
}}

function refreshLogs() {{
  fetch('/api/logs').then(r => r.json()).then(d => {{
    document.getElementById('logs').textContent = d.logs;
  }});
}}

renderChart();
setInterval(refreshLogs, 30000);
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

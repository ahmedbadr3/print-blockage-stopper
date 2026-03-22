#!/usr/bin/env python3
"""
Web UI for print-blockage-stopper v1.4.
Full-featured dashboard with:
  - Multi-printer management (add/remove/rename)
  - Network discovery (mDNS/IPP)
  - Per-printer status, schedule, skip-hours, pause/resume
  - Test connection / auto-detect model via IPP
  - Connection status indicators (periodic ping)
  - Ink level display (IPP marker-levels)
  - Test image preview thumbnails
  - Print history chart (30 days) + CSV export
  - Custom test image upload
  - Webhook notification config
  - Mobile-friendly layout
"""

import base64
import cgi
import csv
import http.server
import io
import json
import html as html_mod
import os
import re
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
MAX_UPLOAD_BYTES = 5 * 1024 * 1024

os.makedirs(UPLOADS_DIR, exist_ok=True)

# ── Printer config helpers ──────────────────────────────────────

def read_printers():
    try:
        with open(PRINTERS_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"printers": [], "global": {"schedule": os.environ.get("SCHEDULE", "0 10 */3 * *"),
                                            "skip_hours": int(os.environ.get("SKIP_HOURS", "72")),
                                            "webhook_url": os.environ.get("WEBHOOK_URL", "")}}

def write_printers(data):
    with open(PRINTERS_FILE, "w") as f:
        json.dump(data, f, indent=2)

def sanitise_cups_name(name):
    s = re.sub(r'[^a-zA-Z0-9_-]', '_', name)
    return s[:64] or "PRINTER"

# ── CUPS management ─────────────────────────────────────────────

def add_cups_printer(printer):
    cups_name = printer["cups_name"]
    conn = printer.get("connection", "ipp")
    ip = printer["ip"]
    port = printer.get("port", 9100)
    uri = f"socket://{ip}:{port}" if conn == "socket" else f"ipp://{ip}/ipp/print"
    paper = printer.get("paper_size", "A4")
    try:
        subprocess.run(
            ["lpadmin", "-p", cups_name, "-v", uri, "-m", "everywhere",
             "-L", "Network", "-D", printer.get("name", cups_name),
             "-o", f"media={paper}"],
            check=True, capture_output=True, timeout=15)
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

# ── Printer probing ─────────────────────────────────────────────

def probe_printer(ip, connection="ipp", port=9100):
    """Probe printer for connectivity, model name, and ink levels."""
    try:
        result = subprocess.run(
            ["python3", "/app/printer_probe.py", ip, connection, str(port)],
            capture_output=True, text=True, timeout=20)
        return json.loads(result.stdout)
    except Exception as e:
        return {"reachable": False, "model": None, "ink_levels": [], "error": str(e)}

# ── mDNS / IPP discovery ───────────────────────────────────────

def discover_printers():
    found = []
    try:
        result = subprocess.run(
            ["avahi-browse", "-t", "-r", "-p", "_ipp._tcp"],
            capture_output=True, text=True, timeout=10)
        for line in result.stdout.splitlines():
            parts = line.split(";")
            if len(parts) < 10 or parts[0] != "=":
                continue
            name = parts[3].replace("\\032", " ")
            ip = parts[7]
            port = parts[8]
            if ":" in ip and ip.startswith("fe80"):
                continue
            if ip and not any(f["ip"] == ip for f in found):
                found.append({"name": name, "ip": ip, "port": int(port) if port.isdigit() else 631})
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    if not found:
        try:
            result = subprocess.run(
                ["ippfind", "--timeout", "5"],
                capture_output=True, text=True, timeout=10)
            for line in result.stdout.strip().splitlines():
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
    img = printer.get("test_image", "preset-11")
    if img.startswith("preset-"):
        path = f"{PRESETS_DIR}/{img}.png"
        if os.path.exists(path):
            return path
    elif img.startswith("custom-"):
        path = f"{UPLOADS_DIR}/{img.replace('custom-', '', 1)}"
        if os.path.exists(path):
            return path
    if os.path.exists("/app/test-print.png"):
        return "/app/test-print.png"
    return f"{PRESETS_DIR}/preset-11.png"

def trigger_print(printer_id):
    subprocess.Popen(
        ["/app/auto-print.sh", "--force", f"--printer-id={printer_id}"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env={**os.environ})

def trigger_print_all():
    data = read_printers()
    for p in data["printers"]:
        trigger_print(p["id"])

# ── Status / history / logs ─────────────────────────────────────

def get_printer_status(printer_id):
    try:
        with open(f"{DATA_DIR}/status-{printer_id}.json") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"status": "unknown", "message": "No prints yet", "timestamp": "\u2014"}

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

def get_image_thumbnail_b64(printer):
    """Return a small base64 data URI for the printer's test image."""
    path = get_test_image_path(printer)
    try:
        from PIL import Image as PILImage
        img = PILImage.open(path)
        img.thumbnail((120, 80))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return f"data:image/png;base64,{base64.b64encode(buf.getvalue()).decode()}"
    except Exception:
        return ""

# ── Cron management ─────────────────────────────────────────────

def update_cron():
    data = read_printers()
    lines = []
    for p in data["printers"]:
        if not p.get("paused", False):
            schedule = p.get("schedule", data["global"]["schedule"])
            lines.append(f'{schedule} . /etc/environment; /app/auto-print.sh --printer-id={p["id"]} >> /data/logs/cron.log 2>&1')
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
        elif self.path == "/api/history.csv":
            self._serve_history_csv()
        elif self.path == "/api/logs":
            self._json_response({"logs": get_recent_logs(30)})
        elif self.path == "/api/presets":
            self._json_response({"presets": get_available_presets(), "uploads": get_uploaded_images()})
        elif self.path.startswith("/api/status/"):
            pid = self.path.split("/")[-1]
            self._json_response(get_printer_status(pid))
        elif self.path.startswith("/api/probe/"):
            ip = self.path.split("/")[-1]
            self._json_response(probe_printer(ip))
        elif self.path.startswith("/api/download-image/"):
            pid = self.path.split("/")[-1]
            data = read_printers()
            printer = next((p for p in data["printers"] if p["id"] == pid), None)
            if printer:
                path = get_test_image_path(printer)
                if os.path.exists(path):
                    fname = os.path.basename(path)
                    self.send_response(200)
                    self.send_header("Content-Type", "image/png")
                    self.send_header("Content-Disposition", f'attachment; filename="{fname}"')
                    with open(path, "rb") as f:
                        img_data = f.read()
                    self.send_header("Content-Length", str(len(img_data)))
                    self.end_headers()
                    self.wfile.write(img_data)
                    return
            self.send_error(404)
        elif self.path.startswith("/api/thumbnail/"):
            pid = self.path.split("/")[-1]
            data = read_printers()
            for p in data["printers"]:
                if p["id"] == pid:
                    self._json_response({"thumbnail": get_image_thumbnail_b64(p)})
                    return
            self._json_response({"thumbnail": ""})
        else:
            self.send_error(404)

    def do_POST(self):
        if self.path == "/api/printers/add":
            self._handle_add_printer()
        elif self.path == "/api/printers/remove":
            self._handle_remove_printer()
        elif self.path == "/api/printers/update":
            self._handle_update_printer()
        elif self.path == "/api/test-connection":
            self._handle_test_connection()
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
        elif self.path == "/api/webhook":
            self._handle_webhook_config()
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

    # ── Test Connection ──────────────────────────────────────

    def _handle_test_connection(self):
        try:
            body = self._read_json_body()
        except json.JSONDecodeError:
            self._json_response({"ok": False, "message": "Invalid JSON"}, 400)
            return
        ip = body.get("ip", "").strip()
        conn = body.get("connection", "ipp")
        port = int(body.get("port", 9100))
        if not ip:
            self._json_response({"ok": False, "message": "IP required"}, 400)
            return
        info = probe_printer(ip, conn, port)
        self._json_response({"ok": info["reachable"], **info})

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
        if any(p["ip"] == ip for p in data["printers"]):
            self._json_response({"ok": False, "message": f"Printer at {ip} already exists"}, 400)
            return
        printer_id = f"printer-{uuid.uuid4().hex[:8]}"
        name = body.get("name", f"Printer at {ip}").strip()[:64]
        cups_name = sanitise_cups_name(f"PBS_{printer_id}")
        printer = {
            "id": printer_id, "name": name, "ip": ip,
            "connection": body.get("connection", "ipp"),
            "port": int(body.get("port", 9100)),
            "paper_size": body.get("paper_size", "A4"),
            "schedule": body.get("schedule", data["global"]["schedule"]),
            "skip_hours": int(body.get("skip_hours", data["global"]["skip_hours"])),
            "paused": False,
            "test_image": body.get("test_image", "preset-11"),
            "cups_name": cups_name,
        }
        if not add_cups_printer(printer):
            self._json_response({"ok": False, "message": "Failed to add printer to CUPS. Check the IP."}, 500)
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
        printer = next((p for p in data["printers"] if p["id"] == pid), None)
        if not printer:
            self._json_response({"ok": False, "message": "Printer not found"}, 404)
            return
        remove_cups_printer(printer["cups_name"])
        data["printers"] = [p for p in data["printers"] if p["id"] != pid]
        write_printers(data)
        update_cron()
        sf = f"{DATA_DIR}/status-{pid}.json"
        if os.path.exists(sf):
            os.remove(sf)
        self._json_response({"ok": True, "message": f"Printer {printer['name']} removed"})

    def _handle_update_printer(self):
        try:
            body = self._read_json_body()
        except json.JSONDecodeError:
            self._json_response({"ok": False, "message": "Invalid JSON"}, 400)
            return
        pid = body.get("id", "")
        data = read_printers()
        printer = next((p for p in data["printers"] if p["id"] == pid), None)
        if not printer:
            self._json_response({"ok": False, "message": "Printer not found"}, 404)
            return
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

    # ── Webhook config ───────────────────────────────────────

    def _handle_webhook_config(self):
        try:
            body = self._read_json_body()
        except json.JSONDecodeError:
            self._json_response({"ok": False, "message": "Invalid JSON"}, 400)
            return
        data = read_printers()
        if "webhook_url" in body:
            data.setdefault("global", {})["webhook_url"] = body["webhook_url"].strip()
            # Also set env var for auto-print.sh and update /etc/environment for cron
            url = body["webhook_url"].strip()
            os.environ["WEBHOOK_URL"] = url
            try:
                with open("/etc/environment", "r") as f:
                    lines = [l for l in f.readlines() if not l.startswith("WEBHOOK_URL=")]
                with open("/etc/environment", "w") as f:
                    f.writelines(lines)
                    f.write(f'WEBHOOK_URL="{url}"\n')
            except Exception:
                pass
        write_printers(data)
        self._json_response({"ok": True})

    # ── Image upload ─────────────────────────────────────────

    def _handle_upload_image(self):
        content_type = self.headers.get("Content-Type", "")
        if "multipart/form-data" not in content_type:
            self._json_response({"ok": False, "message": "Must be multipart/form-data"}, 400)
            return
        try:
            form = cgi.FieldStorage(
                fp=self.rfile, headers=self.headers,
                environ={"REQUEST_METHOD": "POST", "CONTENT_TYPE": content_type})
        except Exception as e:
            self._json_response({"ok": False, "message": str(e)}, 400)
            return
        file_item = form["file"] if "file" in form else None
        if not file_item or not file_item.filename:
            self._json_response({"ok": False, "message": "No file uploaded"}, 400)
            return
        filename = os.path.basename(file_item.filename)
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        if ext not in ("png", "jpg", "jpeg", "bmp", "tiff"):
            self._json_response({"ok": False, "message": "Invalid file type."}, 400)
            return
        data = file_item.file.read(MAX_UPLOAD_BYTES + 1)
        if len(data) > MAX_UPLOAD_BYTES:
            self._json_response({"ok": False, "message": "File too large. Max 5 MB."}, 400)
            return
        safe_name = re.sub(r'[^a-zA-Z0-9._-]', '_', filename)
        with open(os.path.join(UPLOADS_DIR, safe_name), "wb") as f:
            f.write(data)
        self._json_response({"ok": True, "id": f"custom-{safe_name}", "filename": safe_name})

    # ── CSV export ───────────────────────────────────────────

    def _serve_history_csv(self):
        history = get_history()
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["Timestamp", "Result", "Message", "Printer ID"])
        for h in history:
            writer.writerow([h.get("timestamp", ""), h.get("result", ""),
                             h.get("message", ""), h.get("printer_id", "")])
        body = output.getvalue().encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/csv")
        self.send_header("Content-Disposition", "attachment; filename=print-history.csv")
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)

    # ── Dashboard HTML ───────────────────────────────────────

    def _serve_dashboard(self):
        data = read_printers()
        printers = data["printers"]
        history = get_history()
        logs = get_recent_logs(25)
        presets = get_available_presets()
        uploads = get_uploaded_images()
        webhook_url = data.get("global", {}).get("webhook_url", "")

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
                cur_sched = p.get("schedule", "0 10 */3 * *")
                thumb = get_image_thumbnail_b64(p)

                img_options = ""
                for pr in presets:
                    sel = "selected" if pr["id"] == test_img else ""
                    img_options += f'<option value="{pr["id"]}" {sel}>{html_mod.escape(pr["label"])}</option>'
                for up in uploads:
                    sel = "selected" if up["id"] == test_img else ""
                    img_options += f'<option value="{up["id"]}" {sel}>{html_mod.escape(up["label"])}</option>'

                thumb_html = f'<img src="{thumb}" class="thumb" alt="test image">' if thumb else ''

                printer_cards += f"""
      <div class="card printer-card" data-id="{p["id"]}">
        <div class="printer-header">
          <div class="status-row">
            <div class="conn-dot" id="conn-{p["id"]}" title="Checking connection..."></div>
            <div class="printer-name" id="name-{p["id"]}" ondblclick="startRename('{p["id"]}')"
                 title="Double-click to rename">{html_mod.escape(p["name"])}</div>
            <span class="printer-ip">{html_mod.escape(p["ip"])}</span>
          </div>
          <button class="btn-icon" onclick="removePrinter('{p["id"]}')" title="Remove printer">&times;</button>
        </div>
        <div class="meta" id="model-{p["id"]}"></div>
        <div class="meta" id="status-row-{p["id"]}">
          <span>Status: <strong id="status-label-{p["id"]}" style="color:{st_colour}">{st_label}</strong></span>
          <span>Last: <span id="status-time-{p["id"]}">{html_mod.escape(st["timestamp"])}</span></span>
          <span id="status-msg-{p["id"]}">{html_mod.escape(st["message"])}</span>
        </div>
        <div class="ink-bar-container" id="ink-{p["id"]}"></div>
        <div class="printer-controls">
          <div class="control-group">
            <label>Print every:</label>
            <select class="input-sm select-sm" id="freq-{p["id"]}"
                    onchange="updateSchedule('{p["id"]}')" data-cron="{html_mod.escape(cur_sched)}">
              <option value="1">Day</option>
              <option value="2">2 days</option>
              <option value="3">3 days</option>
              <option value="4">4 days</option>
              <option value="5">5 days</option>
              <option value="7">Week</option>
              <option value="14">2 weeks</option>
            </select>
            <label style="min-width:auto;">at</label>
            <select class="input-sm select-sm" id="hour-{p["id"]}"
                    onchange="updateSchedule('{p["id"]}')" style="max-width:100px;">
            </select>
            <span class="schedule-state" style="color:{sched_colour}">{sched_state}</span>
            <button class="btn btn-sm" style="background:{pause_colour}" onclick="toggleSchedule('{p["id"]}')">{pause_label}</button>
          </div>
          <div class="control-group">
            <label>Paper size:</label>
            <select class="input-sm select-sm" id="paper-{p["id"]}"
                    onchange="updatePrinter('{p["id"]}', {{paper_size: this.value}})">
              {"".join(f'<option value="{ps}"{" selected" if ps == p.get("paper_size", "A4") else ""}>{ps}</option>' for ps in ["A4", "Letter", "Legal", "A3", "A5", "B5", "4x6", "5x7"])}
            </select>
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
                    onchange="updatePrinter('{p["id"]}', {{test_image: this.value}}); refreshThumb('{p["id"]}')">
              {img_options}
            </select>
            {thumb_html}
            <a href="/api/download-image/{p["id"]}" class="btn btn-sm" style="padding:2px 8px;font-size:0.75rem;text-decoration:none;" title="Download test image">&#x2B07; Download</a>
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
         background: #0f172a; color: #e2e8f0; padding: 16px; line-height: 1.5; }}
  .container {{ max-width: 800px; margin: 0 auto; }}
  h1 {{ font-size: 1.4rem; font-weight: 600; margin-bottom: 4px; }}
  .subtitle {{ color: #94a3b8; font-size: 0.85rem; margin-bottom: 20px; }}
  .card {{ background: #1e293b; border-radius: 10px; padding: 16px; margin-bottom: 14px; }}
  .card h2 {{ font-size: 0.85rem; text-transform: uppercase; letter-spacing: 0.05em;
              color: #64748b; margin-bottom: 10px; }}

  .printer-card {{ border-left: 3px solid #334155; }}
  .printer-header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px; }}
  .printer-name {{ font-size: 1.05rem; font-weight: 600; cursor: pointer; border-bottom: 1px dashed transparent; }}
  .printer-name:hover {{ border-bottom-color: #64748b; }}
  .printer-ip {{ color: #64748b; font-size: 0.8rem; font-family: monospace; margin-left: 10px; }}
  .btn-icon {{ background: none; border: none; color: #64748b; font-size: 1.4rem; cursor: pointer;
               padding: 2px 8px; border-radius: 4px; }}
  .btn-icon:hover {{ background: #334155; color: #ef4444; }}

  .printer-controls {{ display: flex; flex-direction: column; gap: 8px; margin-top: 10px; }}
  .control-group {{ display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }}
  .control-group label {{ font-size: 0.82rem; color: #94a3b8; min-width: 130px; }}
  @media (max-width: 600px) {{ .control-group label {{ min-width: 100%; }} }}

  .status-row {{ display: flex; align-items: center; gap: 8px; }}
  .conn-dot {{ width: 10px; height: 10px; border-radius: 50%; background: #a3a3a3; flex-shrink: 0;
               transition: background 0.3s; }}
  .meta {{ color: #94a3b8; font-size: 0.82rem; display: flex; gap: 14px; flex-wrap: wrap; }}
  .schedule-state {{ font-size: 0.8rem; font-weight: 600; }}

  /* Ink levels */
  .ink-bar-container {{ display: flex; gap: 4px; flex-wrap: wrap; margin: 6px 0; }}
  .ink-bar {{ display: flex; align-items: center; gap: 4px; font-size: 0.7rem; }}
  .ink-bar-bg {{ width: 50px; height: 8px; background: #334155; border-radius: 4px; overflow: hidden; }}
  .ink-bar-fill {{ height: 100%; border-radius: 4px; transition: width 0.3s; }}
  .ink-label {{ color: #94a3b8; }}

  /* Thumbnail */
  .thumb {{ height: 40px; border-radius: 4px; border: 1px solid #334155; vertical-align: middle; margin-left: 6px; }}

  .btn {{ color: white; border: none; border-radius: 8px; padding: 10px 24px; font-size: 0.95rem;
          cursor: pointer; font-weight: 500; transition: all 0.15s; }}
  .btn:hover {{ filter: brightness(1.1); }}
  .btn:disabled {{ background: #475569 !important; cursor: not-allowed; filter: none; }}
  .btn-primary {{ background: #3b82f6; }}
  .btn-sm {{ padding: 6px 14px; font-size: 0.8rem; border-radius: 6px; }}
  .btn-row {{ display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }}
  .btn-msg {{ font-size: 0.8rem; color: #94a3b8; }}

  .input-sm {{ background: #0f172a; border: 1px solid #334155; border-radius: 6px;
               color: #e2e8f0; padding: 6px 10px; font-size: 0.85rem; }}
  .input-sm:focus {{ border-color: #3b82f6; outline: none; }}
  input[type=number].input-sm {{ width: 70px; }}
  .select-sm {{ background: #0f172a; border: 1px solid #334155; border-radius: 6px;
                color: #e2e8f0; padding: 6px 10px; font-size: 0.82rem; max-width: 180px; }}

  .add-form {{ display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-top: 12px; }}
  .add-form .full {{ grid-column: 1 / -1; }}
  .add-form label {{ font-size: 0.8rem; color: #94a3b8; margin-bottom: 2px; display: block; }}
  .add-form input, .add-form select {{ width: 100%; background: #0f172a; border: 1px solid #334155;
    border-radius: 6px; color: #e2e8f0; padding: 8px 10px; font-size: 0.85rem; }}
  .add-form input:focus, .add-form select:focus {{ border-color: #3b82f6; outline: none; }}
  @media (max-width: 600px) {{ .add-form {{ grid-template-columns: 1fr; }} }}

  .discover-list {{ display: flex; flex-direction: column; gap: 8px; margin-top: 12px; }}
  .discover-item {{ display: flex; justify-content: space-between; align-items: center;
                     background: #0f172a; padding: 10px 14px; border-radius: 8px; }}

  .empty-state {{ text-align: center; color: #64748b; padding: 30px 20px; font-size: 0.9rem; }}

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

  .upload-area {{ display: flex; align-items: center; gap: 12px; margin-top: 10px; flex-wrap: wrap; }}
  .upload-area input[type=file] {{ font-size: 0.82rem; color: #94a3b8; max-width: 200px; }}

  /* Webhook config */
  .webhook-row {{ display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }}
  .webhook-row input {{ flex: 1; min-width: 200px; }}

  pre {{ background: #0f172a; border-radius: 6px; padding: 12px; font-size: 0.78rem;
         overflow-x: auto; max-height: 280px; overflow-y: auto; color: #cbd5e1;
         line-height: 1.6; white-space: pre-wrap; word-break: break-all; }}
  a {{ color: #60a5fa; text-decoration: none; }}
  a:hover {{ text-decoration: underline; }}
  .footer {{ text-align: center; color: #475569; font-size: 0.75rem; margin-top: 20px; }}
  code {{ background: #0f172a; padding: 2px 6px; border-radius: 4px; font-size: 0.82rem; }}
  .section-divider {{ border-top: 1px solid #334155; margin: 14px 0; }}

  /* Rename input */
  .rename-input {{ background: #0f172a; border: 1px solid #3b82f6; border-radius: 4px;
                    color: #e2e8f0; padding: 4px 8px; font-size: 1rem; font-weight: 600; width: 200px; }}
</style>
</head>
<body>
<div class="container">
  <h1>Print Blockage Stopper</h1>
  <p class="subtitle">Automated Print Head Maintenance</p>

  <div id="printerCards">{printer_cards}</div>

  <!-- Add Printer -->
  <div class="card">
    <h2>Add Printer</h2>
    <div class="btn-row" style="margin-bottom:10px;">
      <button class="btn btn-sm" style="background:#6366f1" onclick="discoverPrinters()" id="discoverBtn">Discover on Network</button>
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
        <div style="display:flex;gap:6px;">
          <input type="text" id="addIp" placeholder="192.168.1.50" required style="flex:1;">
          <button class="btn btn-sm" style="background:#6366f1;white-space:nowrap;" onclick="testConnection()">Test</button>
        </div>
        <span class="btn-msg" id="testMsg" style="margin-top:4px;display:block;"></span>
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
      <div>
        <label for="addFreq">Print every</label>
        <select id="addFreq">
          <option value="1">Day</option>
          <option value="2">2 days</option>
          <option value="3" selected>3 days</option>
          <option value="4">4 days</option>
          <option value="5">5 days</option>
          <option value="7">Week</option>
          <option value="14">2 weeks</option>
        </select>
      </div>
      <div>
        <label for="addHour">At</label>
        <select id="addHour"></select>
      </div>
      <div class="full">
        <button class="btn btn-primary" onclick="addPrinter()" id="addBtn">Add Printer</button>
        <span class="btn-msg" id="addMsg" style="margin-left:10px;"></span>
      </div>
    </div>
  </div>

  <!-- Custom Test Image -->
  <div class="card">
    <h2>Custom Test Image</h2>
    <p class="meta" style="margin-bottom:8px;">Upload a custom test image (PNG, JPG, BMP, TIFF \u2014 max 5 MB).</p>
    <div class="upload-area">
      <input type="file" id="uploadFile" accept=".png,.jpg,.jpeg,.bmp,.tiff">
      <button class="btn btn-primary btn-sm" onclick="uploadImage()">Upload</button>
      <span class="btn-msg" id="uploadMsg"></span>
    </div>
  </div>

  <!-- Webhook Notifications -->
  <div class="card">
    <h2>Notifications</h2>
    <p class="meta" style="margin-bottom:8px;">Webhook URL for print success/failure notifications (Slack, Discord, ntfy, etc.).</p>
    <div class="webhook-row">
      <input type="url" class="input-sm" id="webhookUrl" value="{html_mod.escape(webhook_url)}"
             placeholder="https://hooks.slack.com/..." style="flex:1;">
      <button class="btn btn-primary btn-sm" onclick="saveWebhook()">Save</button>
      <span class="btn-msg" id="webhookMsg"></span>
    </div>
  </div>

  <!-- Print History -->
  <div class="card">
    <h2>Print History (Last 30 days)
      <a href="/api/history.csv" style="font-size:0.7rem;text-transform:none;letter-spacing:0;margin-left:10px;font-weight:400;">Export CSV</a>
    </h2>
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

  <!-- Logs -->
  <div class="card">
    <h2>Recent Logs</h2>
    <pre id="logs">{escaped_logs}</pre>
  </div>

  <div class="card" style="padding: 12px 16px;">
    <a href="/printers" target="_blank">CUPS Printer Status (port 631)</a>
  </div>

  <div class="footer">print-blockage-stopper v1.4</div>
</div>

<script>
const historyData = {history_json};

function api(path, method, body) {{
  const opts = {{ method }};
  if (body) {{ opts.headers = {{'Content-Type':'application/json'}}; opts.body = JSON.stringify(body); }}
  return fetch(path, opts).then(r => r.json());
}}
function setMsg(id, text, timeout) {{
  const el = document.getElementById(id);
  if (el) {{ el.textContent = text; if (timeout) setTimeout(() => el.textContent = '', timeout); }}
}}

// ── Printer actions ─────────────────────────────────────
function printNow(id) {{
  api('/api/print-now/' + id, 'POST').then(() => {{
    setMsg('msg-' + id, 'Print triggered.', 5000);
    setTimeout(refreshLogs, 3000);
    setTimeout(refreshAllStatus, 5000);
    setTimeout(refreshAllStatus, 15000);
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

// ── Rename ──────────────────────────────────────────────
function startRename(id) {{
  const el = document.getElementById('name-' + id);
  const current = el.textContent;
  el.innerHTML = `<input class="rename-input" value="${{current}}" onblur="finishRename('${{id}}', this)"
                   onkeydown="if(event.key==='Enter')this.blur();if(event.key==='Escape'){{this.value='${{current}}';this.blur();}}" autofocus>`;
  el.querySelector('input').select();
}}
function finishRename(id, input) {{
  const name = input.value.trim();
  if (name && name !== input.defaultValue) {{
    updatePrinter(id, {{ name }});
  }}
  const el = document.getElementById('name-' + id);
  el.textContent = name || input.defaultValue;
}}

// ── Test Connection ─────────────────────────────────────
function testConnection() {{
  const ip = document.getElementById('addIp').value.trim();
  if (!ip) {{ setMsg('testMsg', 'Enter an IP first', 3000); return; }}
  setMsg('testMsg', 'Testing...');
  api('/api/test-connection', 'POST', {{ ip, connection: document.getElementById('addConn').value }})
    .then(d => {{
      if (d.reachable) {{
        let msg = 'Connected!';
        if (d.model) {{
          msg += ' Model: ' + d.model;
          document.getElementById('addName').value = d.model;
        }}
        setMsg('testMsg', msg, 8000);
      }} else {{
        setMsg('testMsg', 'Cannot reach printer: ' + (d.error || 'timeout'), 8000);
      }}
    }}).catch(() => setMsg('testMsg', 'Test failed', 3000));
}}

// ── Connection status + ink levels (probe all printers) ─
function probeAllPrinters() {{
  document.querySelectorAll('.printer-card').forEach(card => {{
    const id = card.dataset.id;
    // Get IP from the card
    const ipEl = card.querySelector('.printer-ip');
    if (!ipEl) return;
    const ip = ipEl.textContent.trim();
    api('/api/probe/' + ip, 'GET').then(d => {{
      // Connection dot
      const dot = document.getElementById('conn-' + id);
      if (dot) {{
        dot.style.background = d.reachable ? '#22c55e' : '#ef4444';
        dot.style.boxShadow = d.reachable ? '0 0 6px #22c55e80' : '0 0 6px #ef444480';
        dot.title = d.reachable ? 'Connected' : 'Unreachable';
      }}
      // Model name
      const modelEl = document.getElementById('model-' + id);
      if (modelEl && d.model) {{
        modelEl.innerHTML = '<span style="color:#94a3b8;font-size:0.78rem;">' + d.model + '</span>';
      }}
      // Ink levels
      const inkEl = document.getElementById('ink-' + id);
      if (inkEl && d.ink_levels && d.ink_levels.length > 0) {{
        let html = '';
        d.ink_levels.forEach(ink => {{
          const pct = ink.level >= 0 ? ink.level : 0;
          const color = ink.color || '#94a3b8';
          // Convert IPP color format (#RRGGBB) or use default
          const barColor = color.startsWith('#') ? color : '#94a3b8';
          html += `<div class="ink-bar">
            <span class="ink-label">${{ink.name}}</span>
            <div class="ink-bar-bg"><div class="ink-bar-fill" style="width:${{pct}}%;background:${{barColor}};"></div></div>
            <span class="ink-label">${{pct >= 0 ? pct + '%' : '?'}}</span>
          </div>`;
        }});
        inkEl.innerHTML = html;
      }}
    }}).catch(() => {{}});
  }});
}}

// ── Schedule helpers ─────────────────────────────────────
function buildCron(days, hour) {{
  if (days == 1) return `0 ${{hour}} * * *`;
  if (days == 7) return `0 ${{hour}} * * 1`;
  if (days == 14) return `0 ${{hour}} 1,15 * *`;
  return `0 ${{hour}} */${{days}} * *`;
}}
function parseCron(cron) {{
  const parts = cron.trim().split(/\\s+/);
  if (parts.length < 5) return {{ days: 3, hour: 10 }};
  const hour = parseInt(parts[1]) || 10;
  const dom = parts[2], dow = parts[4];
  if (dow === '1' && dom === '*') return {{ days: 7, hour }};
  if (dom === '1,15') return {{ days: 14, hour }};
  if (dom.startsWith('*/')) return {{ days: parseInt(dom.slice(2)) || 3, hour }};
  if (dom === '*' && dow === '*') return {{ days: 1, hour }};
  return {{ days: 3, hour }};
}}
function populateHourSelect(sel, selected) {{
  sel.innerHTML = '';
  for (let h = 0; h < 24; h++) {{
    const l = h === 0 ? '12:00 AM' : h < 12 ? h+':00 AM' : h === 12 ? '12:00 PM' : (h-12)+':00 PM';
    const o = document.createElement('option');
    o.value = h; o.textContent = l; if (h === selected) o.selected = true;
    sel.appendChild(o);
  }}
}}
function initSchedulePickers() {{
  document.querySelectorAll('[id^="freq-"]').forEach(sel => {{
    const id = sel.id.replace('freq-', '');
    const parsed = parseCron(sel.dataset.cron || '0 10 */3 * *');
    sel.value = parsed.days;
    const hourSel = document.getElementById('hour-' + id);
    if (hourSel) populateHourSelect(hourSel, parsed.hour);
  }});
  const addHour = document.getElementById('addHour');
  if (addHour) populateHourSelect(addHour, 10);
}}
function updateSchedule(id) {{
  const days = document.getElementById('freq-' + id).value;
  const hour = document.getElementById('hour-' + id).value;
  updatePrinter(id, {{ schedule: buildCron(days, hour) }});
}}

function addPrinter() {{
  const ip = document.getElementById('addIp').value.trim();
  if (!ip) {{ setMsg('addMsg', 'IP address is required', 3000); return; }}
  const btn = document.getElementById('addBtn');
  btn.disabled = true;
  api('/api/printers/add', 'POST', {{
    name: document.getElementById('addName').value.trim() || ('Printer at ' + ip),
    ip, connection: document.getElementById('addConn').value,
    paper_size: document.getElementById('addPaper').value.trim() || 'A4',
    schedule: buildCron(document.getElementById('addFreq').value, document.getElementById('addHour').value)
  }}).then(d => {{
    btn.disabled = false;
    if (d.ok) location.reload();
    else setMsg('addMsg', d.message || 'Failed', 5000);
  }}).catch(() => {{ btn.disabled = false; setMsg('addMsg', 'Network error', 3000); }});
}}

// ── Discovery ───────────────────────────────────────────
function discoverPrinters() {{
  const btn = document.getElementById('discoverBtn');
  const container = document.getElementById('discoverResults');
  btn.disabled = true; btn.textContent = 'Scanning...';
  api('/api/discover', 'GET').then(d => {{
    btn.disabled = false; btn.textContent = 'Discover on Network';
    if (!d.printers || !d.printers.length) {{
      setMsg('discoverMsg', 'No printers found. Try adding manually.', 5000);
      container.innerHTML = ''; return;
    }}
    let h = '<div class="discover-list">';
    d.printers.forEach(p => {{
      h += `<div class="discover-item">
        <div><strong>${{p.name}}</strong> <span class="meta">${{p.ip}}</span></div>
        <button class="btn btn-primary btn-sm" onclick="quickAdd('${{p.ip}}','${{p.name.replace(/'/g, "\\\\'")}}')">Add</button>
      </div>`;
    }});
    container.innerHTML = h + '</div>';
  }}).catch(() => {{ btn.disabled = false; btn.textContent = 'Discover on Network'; }});
}}
function quickAdd(ip, name) {{
  document.getElementById('addIp').value = ip;
  document.getElementById('addName').value = name;
  addPrinter();
}}

// ── Image upload ────────────────────────────────────────
function uploadImage() {{
  const input = document.getElementById('uploadFile');
  if (!input.files.length) {{ setMsg('uploadMsg', 'Select a file', 3000); return; }}
  const file = input.files[0];
  if (file.size > 5*1024*1024) {{ setMsg('uploadMsg', 'Too large (max 5 MB)', 3000); return; }}
  const form = new FormData(); form.append('file', file);
  fetch('/api/upload-image', {{ method: 'POST', body: form }}).then(r => r.json()).then(d => {{
    if (d.ok) {{ setMsg('uploadMsg', 'Uploaded!', 5000); setTimeout(() => location.reload(), 1500); }}
    else setMsg('uploadMsg', d.message || 'Failed', 5000);
  }}).catch(e => setMsg('uploadMsg', 'Error', 5000));
}}

function refreshThumb(id) {{
  api('/api/thumbnail/' + id, 'GET').then(d => {{
    const card = document.querySelector(`[data-id="${{id}}"]`);
    if (card && d.thumbnail) {{
      const old = card.querySelector('.thumb');
      if (old) old.src = d.thumbnail;
    }}
  }});
}}

// ── Webhook ─────────────────────────────────────────────
function saveWebhook() {{
  const url = document.getElementById('webhookUrl').value.trim();
  api('/api/webhook', 'POST', {{ webhook_url: url }}).then(d => {{
    setMsg('webhookMsg', d.ok ? 'Saved' : 'Error', 3000);
  }});
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
  historyData.forEach(e => {{ const d = e.timestamp.split(' ')[0]; if (!byDate[d]) byDate[d] = []; byDate[d].push(e); }});
  const days = []; const now = new Date();
  for (let i = 29; i >= 0; i--) {{ const d = new Date(now); d.setDate(d.getDate()-i); days.push({{ date: d.toISOString().split('T')[0], entries: byDate[d.toISOString().split('T')[0]] || [] }}); }}
  container.innerHTML = '';
  days.forEach(day => {{
    const bar = document.createElement('div'); bar.className = 'chart-bar';
    const oks = day.entries.filter(e => e.result === 'ok').length;
    const skips = day.entries.filter(e => e.result === 'skipped').length;
    const errs = day.entries.filter(e => e.result === 'error').length;
    const total = oks + skips + errs;
    if (!total) {{ bar.style.height = '4px'; bar.style.background = '#1e293b'; }}
    else {{ bar.style.height = Math.max(8, Math.min(100, total*20))+'px'; bar.style.background = errs > 0 ? '#ef4444' : oks > 0 ? '#22c55e' : '#3b82f6'; }}
    bar.title = `${{day.date}}: ${{oks}} printed, ${{skips}} skipped, ${{errs}} failed`;
    container.appendChild(bar);
  }});
  if (days.length >= 3) {{
    const f = d => d.slice(5);
    labels.innerHTML = `<span>${{f(days[0].date)}}</span><span>${{f(days[14].date)}}</span><span>${{f(days[29].date)}}</span>`;
  }}
}}

function refreshLogs() {{
  fetch('/api/logs').then(r => r.json()).then(d => {{ document.getElementById('logs').textContent = d.logs; }});
}}

// ── Status refresh ──────────────────────────────────────
function refreshAllStatus() {{
  document.querySelectorAll('.printer-card').forEach(card => {{
    const id = card.dataset.id;
    api('/api/status/' + id, 'GET').then(d => {{
      const colours = {{ok: '#22c55e', error: '#ef4444'}};
      const labels = {{ok: 'OK', error: 'FAILED'}};
      const lbl = document.getElementById('status-label-' + id);
      const time = document.getElementById('status-time-' + id);
      const msg = document.getElementById('status-msg-' + id);
      if (lbl) {{
        lbl.textContent = labels[d.status] || 'No prints yet';
        lbl.style.color = colours[d.status] || '#a3a3a3';
      }}
      if (time) time.textContent = d.timestamp || '\u2014';
      if (msg) msg.textContent = d.message || '';
    }}).catch(() => {{}});
  }});
}}

// ── Init ────────────────────────────────────────────────
renderChart();
initSchedulePickers();
probeAllPrinters();
refreshAllStatus();
setInterval(refreshLogs, 30000);
setInterval(refreshAllStatus, 15000);  // Re-check print status every 15s
setInterval(probeAllPrinters, 60000);  // Re-check connectivity every 60s
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

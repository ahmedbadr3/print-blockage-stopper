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
import csv
import fcntl
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
THUMBS_DIR = f"{DATA_DIR}/thumbnails"
STATIC_DIR = "/app/static"
MIME_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "application/javascript",
    ".css": "text/css",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".ico": "image/x-icon",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
    ".json": "application/json",
}

os.makedirs(UPLOADS_DIR, exist_ok=True)
os.makedirs(THUMBS_DIR, exist_ok=True)

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
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            json.dump(data, f, indent=2)
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)

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
    """Return a small base64 data URI for the printer's test image, with disk caching."""
    path = get_test_image_path(printer)
    try:
        # Cache key based on image path and mtime
        src_mtime = os.path.getmtime(path)
        cache_key = re.sub(r'[^a-zA-Z0-9_-]', '_', os.path.basename(path))
        cache_path = os.path.join(THUMBS_DIR, f"{cache_key}.png")

        # Return cached thumbnail if source hasn't changed
        if os.path.exists(cache_path) and os.path.getmtime(cache_path) >= src_mtime:
            with open(cache_path, "rb") as f:
                return f"data:image/png;base64,{base64.b64encode(f.read()).decode()}"

        from PIL import Image as PILImage
        img = PILImage.open(path)
        img.thumbnail((120, 80))
        img.save(cache_path, format="PNG")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return f"data:image/png;base64,{base64.b64encode(buf.getvalue()).decode()}"
    except Exception:
        # Clean up partial cache file if save failed
        if 'cache_path' in dir() and os.path.exists(cache_path):
            try:
                os.remove(cache_path)
            except OSError:
                pass
        return ""

# ── Cron next-fire calculation ──────────────────────────────────

def cron_next(cron_expr):
    """Calculate the next fire time for a simple cron expression.
    Handles the subset we generate: minute hour dom month dow."""
    parts = cron_expr.strip().split()
    if len(parts) < 5:
        return None
    minute = int(parts[0]) if parts[0] != "*" else 0
    hour = int(parts[1]) if parts[1] != "*" else 0
    dom = parts[2]   # *, */N
    dow = parts[4]   # *, 1 (Monday)

    now = datetime.now()
    # Start from the next occurrence of the target hour:minute
    candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate <= now:
        candidate = candidate + __import__("datetime").timedelta(days=1)

    # Try up to 400 days to find a match
    td = __import__("datetime").timedelta
    for _ in range(400):
        # Check day-of-week constraint
        if dow != "*":
            # Cron: 0=Sun, 1=Mon...6=Sat; Python weekday(): 0=Mon...6=Sun
            cron_dow = (candidate.weekday() + 1) % 7
            if str(cron_dow) != dow:
                candidate += td(days=1)
                continue
        # Check day-of-month constraint
        if dom.startswith("*/"):
            step = int(dom[2:])
            if step > 0 and (candidate.day - 1) % step != 0:
                candidate += td(days=1)
                continue
        elif dom != "*":
            # Specific days like "1,15"
            allowed = [int(d) for d in dom.split(",")]
            if candidate.day not in allowed:
                candidate += td(days=1)
                continue
        return candidate
    return None

# ── Cron management ─────────────────────────────────────────────

def update_cron():
    data = read_printers()
    lines = []
    for p in data["printers"]:
        if not p.get("paused", False):
            schedule = p.get("schedule", data["global"]["schedule"])
            lines.append(f'{schedule} . /etc/environment; /app/auto-print.sh --printer-id={p["id"]} >> /data/logs/cron.log 2>&1')
    cron_content = "\n".join(lines) + "\n" if lines else ""
    subprocess.run(["crontab", "-"], input=cron_content.encode(),
                   capture_output=True, timeout=5)

# ── HTTP Handler ────────────────────────────────────────────────

class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def do_GET(self):
        # ── API routes ───────────────────────────────────────
        if self.path == "/api/printers":
            data = read_printers()
            for p in data["printers"]:
                st = get_printer_status(p["id"])
                p["status"] = st.get("status", "unknown")
                p["last_print"] = st.get("timestamp")
                p["last_result"] = st.get("status", "unknown")
                if st.get("status") == "unknown":
                    p["last_result"] = None
            self._json_response(data)
        elif self.path == "/api/discover":
            self._json_response({"printers": discover_printers()})
        elif self.path == "/api/history":
            history = get_history()
            printers_data = read_printers()
            name_map = {p["id"]: p.get("name", p["id"]) for p in printers_data["printers"]}
            for i, h in enumerate(history):
                h["id"] = h.get("id", str(i))
                h["printer_name"] = name_map.get(h.get("printer_id", ""), h.get("printer_id", "Unknown"))
            self._json_response({"history": history})
        elif self.path == "/api/history.csv":
            self._serve_history_csv()
        elif self.path == "/api/logs":
            self._json_response({"logs": get_recent_logs(30)})
        elif self.path == "/api/presets":
            self._json_response({"presets": get_available_presets(), "uploads": get_uploaded_images()})
        elif self.path.startswith("/api/status/"):
            pid = self.path.split("/")[-1]
            self._json_response(get_printer_status(pid))
        elif self.path.startswith("/api/next-print/"):
            pid = self.path.split("/")[-1]
            data = read_printers()
            printer = next((p for p in data["printers"] if p["id"] == pid), None)
            if printer:
                paused = printer.get("paused", False)
                if paused:
                    self._json_response({"next_iso": None, "paused": True})
                else:
                    sched = printer.get("schedule", data["global"]["schedule"])
                    nxt = cron_next(sched)
                    self._json_response({
                        "next_iso": nxt.isoformat() if nxt else None,
                        "paused": False
                    })
            else:
                self._json_response({"next_iso": None, "paused": False})
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
        # ── Static assets (Vite build output) ────────────────
        elif self.path.startswith("/assets/") or self.path == "/favicon.ico":
            self._serve_static_file(self.path.lstrip("/"))
        # ── SPA fallback (/, /history, /settings, etc.) ──────
        else:
            self._serve_index_html()

    def _check_origin(self):
        """Basic CSRF protection: reject POST from foreign origins."""
        origin = self.headers.get("Origin", "")
        if origin:
            from urllib.parse import urlparse
            parsed = urlparse(origin)
            host_header = self.headers.get("Host", "")
            # Allow if origin host matches the Host header (same-origin)
            if parsed.netloc and host_header and parsed.netloc != host_header:
                self._json_response({"ok": False, "message": "Cross-origin request blocked"}, 403)
                return False
        return True

    def do_POST(self):
        if not self._check_origin():
            return
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
        elif self.path == "/api/delete-image":
            self._handle_delete_image()
        elif self.path == "/api/webhook":
            self._handle_webhook_config()
        elif self.path == "/api/notifications":
            self._handle_notifications_config()
        elif self.path == "/api/notifications/test":
            self._handle_notifications_test()
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
        try:
            port = int(body.get("port", 9100))
            if port < 1 or port > 65535:
                raise ValueError()
        except (ValueError, TypeError):
            self._json_response({"ok": False, "message": "Invalid port number (1-65535)"}, 400)
            return
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
            "port": max(1, min(65535, int(body.get("port", 9100)))),
            "paper_size": body.get("paper_size", "A4"),
            "schedule": body.get("schedule", data["global"]["schedule"]),
            "skip_hours": max(1, min(8760, int(body.get("skip_hours", data["global"]["skip_hours"])))),
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
            url = body["webhook_url"].strip()
            if url:
                from urllib.parse import urlparse
                import ipaddress
                parsed = urlparse(url)
                if parsed.scheme not in ("http", "https"):
                    self._json_response({"ok": False, "message": "Webhook URL must be http or https"}, 400)
                    return
                # Block localhost and link-local/metadata IPs (SSRF prevention)
                hostname = parsed.hostname or ""
                if hostname in ("localhost", "127.0.0.1", "0.0.0.0", "::1", "[::1]"):
                    self._json_response({"ok": False, "message": "Webhook URL cannot point to localhost"}, 400)
                    return
                try:
                    addr = ipaddress.ip_address(hostname)
                    if addr.is_loopback or addr.is_link_local:
                        self._json_response({"ok": False, "message": "Webhook URL cannot point to loopback/link-local"}, 400)
                        return
                    # Block AWS metadata endpoint
                    if str(addr) == "169.254.169.254":
                        self._json_response({"ok": False, "message": "Webhook URL cannot point to metadata endpoint"}, 400)
                        return
                except ValueError:
                    pass  # hostname is not an IP — that's fine
            data.setdefault("global", {})["webhook_url"] = url
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

    # ── Notifications (email + HA) ───────────────────────────

    def _validate_url_safe(self, url):
        """Validate URL is not localhost/link-local/metadata. Returns error string or None."""
        from urllib.parse import urlparse
        import ipaddress as _ipaddress
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return "URL must be http or https"
        hostname = parsed.hostname or ""
        if hostname in ("localhost", "127.0.0.1", "0.0.0.0", "::1", "[::1]"):
            return "URL cannot point to localhost"
        try:
            addr = _ipaddress.ip_address(hostname)
            if addr.is_loopback or addr.is_link_local:
                return "URL cannot point to loopback/link-local"
            if str(addr) == "169.254.169.254":
                return "URL cannot point to metadata endpoint"
        except ValueError:
            pass
        return None

    def _handle_notifications_config(self):
        try:
            body = self._read_json_body()
        except json.JSONDecodeError:
            self._json_response({"ok": False, "message": "Invalid JSON"}, 400)
            return

        data = read_printers()
        g = data.setdefault("global", {})

        # Email config
        if "email" in body:
            ec = body["email"]
            email_cfg = g.get("email", {})
            email_cfg["enabled"] = bool(ec.get("enabled", False))
            email_cfg["smtp_server"] = ec.get("smtp_server", "").strip()
            email_cfg["smtp_port"] = max(1, min(65535, int(ec.get("smtp_port", 587))))
            email_cfg["smtp_from"] = ec.get("smtp_from", "").strip()
            email_cfg["smtp_to"] = ec.get("smtp_to", "").strip()
            email_cfg["smtp_username"] = ec.get("smtp_username", "").strip()
            # Preserve password if sentinel
            pw = ec.get("smtp_password", "")
            if pw != "***":
                email_cfg["smtp_password"] = pw
            email_cfg["smtp_tls"] = bool(ec.get("smtp_tls", True))
            g["email"] = email_cfg

        # Home Assistant config
        if "homeassistant" in body:
            hc = body["homeassistant"]
            ha_cfg = g.get("homeassistant", {})
            ha_url = hc.get("ha_url", "").strip().rstrip("/")
            if ha_url:
                err = self._validate_url_safe(ha_url)
                if err:
                    self._json_response({"ok": False, "message": f"Home Assistant URL: {err}"}, 400)
                    return
            ha_cfg["enabled"] = bool(hc.get("enabled", False))
            ha_cfg["ha_url"] = ha_url
            # Preserve token if sentinel
            token = hc.get("ha_token", "")
            if token != "***":
                ha_cfg["ha_token"] = token
            ha_cfg["ha_verify_ssl"] = bool(hc.get("ha_verify_ssl", True))
            g["homeassistant"] = ha_cfg

        write_printers(data)
        self._json_response({"ok": True})

    def _handle_notifications_test(self):
        try:
            body = self._read_json_body()
        except json.JSONDecodeError:
            self._json_response({"ok": False, "message": "Invalid JSON"}, 400)
            return
        channel = body.get("channel", "")
        if channel not in ("webhook", "email", "homeassistant"):
            self._json_response({"ok": False, "message": "Invalid channel"}, 400)
            return

        # Build config from form values sent in request (test without saving)
        saved = read_printers().get("global", {})
        config = dict(saved)
        if "config" in body:
            fc = body["config"]
            if channel == "webhook":
                config["webhook_url"] = fc.get("webhook_url", config.get("webhook_url", ""))
            elif channel == "email":
                ec = dict(config.get("email", {}))
                for k in ("smtp_server", "smtp_port", "smtp_from", "smtp_to", "smtp_username", "smtp_tls"):
                    if k in fc:
                        ec[k] = fc[k]
                # Use form password unless it's the sentinel
                pw = fc.get("smtp_password", "")
                if pw and pw != "***":
                    ec["smtp_password"] = pw
                ec["enabled"] = True
                config["email"] = ec
            elif channel == "homeassistant":
                hc = dict(config.get("homeassistant", {}))
                if "ha_url" in fc:
                    hc["ha_url"] = fc["ha_url"]
                token = fc.get("ha_token", "")
                if token and token != "***":
                    hc["ha_token"] = token
                if "ha_verify_ssl" in fc:
                    hc["ha_verify_ssl"] = fc["ha_verify_ssl"]
                hc["enabled"] = True
                config["homeassistant"] = hc

        # Write temp config and run notify.py
        import subprocess, tempfile
        tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
        json.dump({"printers": [], "global": config}, tmp)
        tmp.close()
        try:
            result = subprocess.run(
                ["python3", "/app/notify.py", "--event", "test",
                 "--printer", "Test", "--printer-id", "test",
                 "--message", "Test notification", "--channel", channel,
                 "--config", tmp.name],
                capture_output=True, text=True, timeout=15
            )
            if result.returncode == 0:
                self._json_response({"ok": True})
            else:
                err_msg = result.stderr.strip().split("\n")[-1] if result.stderr else "Unknown error"
                self._json_response({"ok": False, "message": err_msg})
        finally:
            os.unlink(tmp.name)

    # ── Image upload ─────────────────────────────────────────

    def _parse_multipart(self):
        """Parse multipart/form-data without deprecated cgi module."""
        content_type = self.headers.get("Content-Type", "")
        # Extract boundary from Content-Type header
        boundary = None
        for part in content_type.split(";"):
            part = part.strip()
            if part.startswith("boundary="):
                boundary = part[len("boundary="):].strip('"')
                break
        if not boundary:
            return None, None
        length = int(self.headers.get("Content-Length", 0))
        if length <= 0 or length > MAX_UPLOAD_BYTES + 4096:
            return None, None
        body = self.rfile.read(length)
        boundary_bytes = ("--" + boundary).encode()
        parts = body.split(boundary_bytes)
        for part in parts:
            if b"Content-Disposition" not in part:
                continue
            # Split headers from body
            header_end = part.find(b"\r\n\r\n")
            if header_end < 0:
                continue
            headers_raw = part[:header_end].decode("utf-8", errors="replace")
            file_data = part[header_end + 4:]
            # Remove trailing \r\n-- if present
            if file_data.endswith(b"\r\n"):
                file_data = file_data[:-2]
            if file_data.endswith(b"--\r\n"):
                file_data = file_data[:-4]
            if file_data.endswith(b"--"):
                file_data = file_data[:-2]
            # Parse filename from Content-Disposition
            fn_match = re.search(r'filename="([^"]+)"', headers_raw)
            if fn_match and b'name="file"' in part[:header_end]:
                return fn_match.group(1), file_data
        return None, None

    def _handle_upload_image(self):
        content_type = self.headers.get("Content-Type", "")
        if "multipart/form-data" not in content_type:
            self._json_response({"ok": False, "message": "Must be multipart/form-data"}, 400)
            return
        try:
            filename, data = self._parse_multipart()
        except Exception as e:
            self._json_response({"ok": False, "message": str(e)}, 400)
            return
        if not filename or not data:
            self._json_response({"ok": False, "message": "No file uploaded"}, 400)
            return
        filename = os.path.basename(filename)
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        if ext not in ("png", "jpg", "jpeg", "bmp", "tiff"):
            self._json_response({"ok": False, "message": "Invalid file type."}, 400)
            return
        if len(data) > MAX_UPLOAD_BYTES:
            self._json_response({"ok": False, "message": "File too large. Max 5 MB."}, 400)
            return
        safe_name = re.sub(r'[^a-zA-Z0-9._-]', '_', filename)
        with open(os.path.join(UPLOADS_DIR, safe_name), "wb") as f:
            f.write(data)
        self._json_response({"ok": True, "id": f"custom-{safe_name}", "filename": safe_name})

    # ── Image delete ─────────────────────────────────────────

    def _handle_delete_image(self):
        try:
            body = self._read_json_body()
        except json.JSONDecodeError:
            self._json_response({"ok": False, "message": "Invalid JSON"}, 400)
            return
        image_id = body.get("id", "")
        if not image_id.startswith("custom-"):
            self._json_response({"ok": False, "message": "Can only delete custom images"}, 400)
            return
        filename = image_id.replace("custom-", "", 1)
        # Sanitise — prevent path traversal
        filename = os.path.basename(filename)
        filepath = os.path.join(UPLOADS_DIR, filename)
        if not os.path.exists(filepath):
            self._json_response({"ok": False, "message": "Image not found"}, 404)
            return
        os.remove(filepath)
        # Remove cached thumbnail if it exists
        cache_key = re.sub(r'[^a-zA-Z0-9_-]', '_', filename)
        cache_path = os.path.join(THUMBS_DIR, f"{cache_key}.png")
        if os.path.exists(cache_path):
            os.remove(cache_path)
        # Reset any printers using this image back to default
        data = read_printers()
        for p in data["printers"]:
            if p.get("test_image") == image_id:
                p["test_image"] = "preset-11"
        write_printers(data)
        self._json_response({"ok": True, "message": f"Deleted {filename}"})

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

    # ── Static file serving (React SPA) ────────────────────────

    def _serve_static_file(self, rel_path):
        """Serve a file from STATIC_DIR with path traversal prevention."""
        safe = os.path.normpath(os.path.join(STATIC_DIR, rel_path))
        if not safe.startswith(STATIC_DIR + "/") and safe != STATIC_DIR:
            self.send_error(403)
            return
        if not os.path.isfile(safe):
            self.send_error(404)
            return
        ext = os.path.splitext(safe)[1].lower()
        mime = MIME_TYPES.get(ext, "application/octet-stream")
        with open(safe, "rb") as f:
            data = f.read()
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", len(data))
        if "/assets/" in rel_path:
            self.send_header("Cache-Control", "public, max-age=31536000, immutable")
        else:
            self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(data)

    def _serve_index_html(self):
        """Serve index.html for SPA routing with CSP header."""
        index_path = os.path.join(STATIC_DIR, "index.html")
        if not os.path.isfile(index_path):
            body = b"<h1>Dashboard not built</h1><p>React frontend not found. Rebuild the Docker image.</p>"
            self.send_response(500)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", len(body))
            self.end_headers()
            self.wfile.write(body)
            return
        with open(index_path, "rb") as f:
            body = f.read()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", len(body))
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Content-Security-Policy",
                         "default-src 'self'; script-src 'self'; "
                         "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
                         "font-src 'self' https://fonts.gstatic.com; "
                         "img-src 'self' data:; connect-src 'self'")
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    server = http.server.ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"Web UI running on http://0.0.0.0:{PORT}")
    server.serve_forever()

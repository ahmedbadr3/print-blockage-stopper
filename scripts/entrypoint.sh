#!/usr/bin/env bash
###############################################################################
# entrypoint.sh — Service startup, optional legacy printer setup, cron install
#
# v1.4: Connection status, ink levels, retry logic, webhooks, CSV export
#       PRINTER_IP is optional — if set, it auto-adds that printer on first run
#       for backward compatibility. New users just open the dashboard.
###############################################################################
set -euo pipefail

LOG_DIR="/data/logs"
mkdir -p "$LOG_DIR" /data/uploads

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] ENTRYPOINT: $*"; }

# ── Input validation (all optional now) ────────────────────────

PRINTER_IP="${PRINTER_IP:-}"
PRINTER_PORT="${PRINTER_PORT:-9100}"
CONNECTION="${CONNECTION:-ipp}"
PAPER_SIZE="${PAPER_SIZE:-A4}"
SCHEDULE="${SCHEDULE:-0 10 */3 * *}"
SKIP_HOURS="${SKIP_HOURS:-72}"
WEBHOOK_URL="${WEBHOOK_URL:-}"

# Validate PRINTER_PORT if set
if [ -n "$PRINTER_PORT" ]; then
    if ! echo "$PRINTER_PORT" | grep -qE '^[0-9]{1,5}$' || [ "$PRINTER_PORT" -lt 1 ] || [ "$PRINTER_PORT" -gt 65535 ]; then
        log "ERROR: PRINTER_PORT must be 1-65535. Got: $PRINTER_PORT"
        exit 1
    fi
fi

# Validate CONNECTION
if [ "$CONNECTION" != "ipp" ] && [ "$CONNECTION" != "socket" ]; then
    log "ERROR: CONNECTION must be 'ipp' or 'socket'. Got: $CONNECTION"
    exit 1
fi

# Validate PAPER_SIZE
if ! echo "$PAPER_SIZE" | grep -qE '^[a-zA-Z0-9]{1,20}$'; then
    log "ERROR: PAPER_SIZE contains invalid characters: $PAPER_SIZE"
    exit 1
fi

# Validate SCHEDULE
if ! echo "$SCHEDULE" | grep -qE '^[0-9\*\/,\-]+[[:space:]]+[0-9\*\/,\-]+[[:space:]]+[0-9\*\/,\-]+[[:space:]]+[0-9\*\/,\-]+[[:space:]]+[0-9\*\/,\-]+$'; then
    log "ERROR: SCHEDULE is not a valid 5-field cron expression: $SCHEDULE"
    exit 1
fi

# Validate SKIP_HOURS
if ! echo "$SKIP_HOURS" | grep -qE '^[0-9]{1,3}$' || [ "$SKIP_HOURS" -lt 1 ] || [ "$SKIP_HOURS" -gt 720 ]; then
    log "ERROR: SKIP_HOURS must be 1-720. Got: $SKIP_HOURS"
    exit 1
fi

log "Default schedule: $SCHEDULE"
log "Default skip hrs: $SKIP_HOURS"
log "Paper size:       $PAPER_SIZE"

# ── Initialise printers.json if not present ───────────────────
PRINTERS_FILE="/data/printers.json"
if [ ! -f "$PRINTERS_FILE" ]; then
    log "Creating printers.json..."
    echo "{\"printers\": [], \"global\": {\"schedule\": \"$SCHEDULE\", \"skip_hours\": $SKIP_HOURS, \"webhook_url\": \"$WEBHOOK_URL\"}}" > "$PRINTERS_FILE"
fi

# ── Start CUPS ──────────────────────────────────────────────────
log "Starting CUPS daemon..."
cupsd
sleep 3

# ── Legacy: auto-add PRINTER_IP if set and not already added ────
if [ -n "$PRINTER_IP" ]; then
    # Validate IP format
    if echo "$PRINTER_IP" | grep -qE '^[a-zA-Z0-9][a-zA-Z0-9.\-]{0,253}[a-zA-Z0-9]$'; then
        # Check if this IP is already in printers.json
        ALREADY_EXISTS=$(python3 -c "
import json
data = json.load(open('$PRINTERS_FILE'))
print(any(p['ip'] == '$PRINTER_IP' for p in data.get('printers', [])))
" 2>/dev/null) || ALREADY_EXISTS="False"

        if [ "$ALREADY_EXISTS" = "False" ]; then
            log "Auto-adding printer at $PRINTER_IP (from PRINTER_IP env var)..."

            if [ "$CONNECTION" = "socket" ]; then
                PRINTER_URI="socket://${PRINTER_IP}:${PRINTER_PORT}"
            else
                PRINTER_URI="ipp://${PRINTER_IP}/ipp/print"
            fi

            CUPS_NAME="PBS_legacy"
            PRINTER_ID="printer-legacy"

            lpadmin -p "$CUPS_NAME" \
                -v "$PRINTER_URI" \
                -m "everywhere" \
                -L "Network" \
                -D "Printer at $PRINTER_IP" \
                -o media="$PAPER_SIZE" 2>/dev/null || true

            cupsaccept "$CUPS_NAME" 2>/dev/null || true
            cupsenable "$CUPS_NAME" 2>/dev/null || true

            # Add to printers.json
            python3 -c "
import json
data = json.load(open('$PRINTERS_FILE'))
data['printers'].append({
    'id': '$PRINTER_ID',
    'name': 'Printer at $PRINTER_IP',
    'ip': '$PRINTER_IP',
    'connection': '$CONNECTION',
    'port': $PRINTER_PORT,
    'paper_size': '$PAPER_SIZE',
    'schedule': '$SCHEDULE',
    'skip_hours': $SKIP_HOURS,
    'paused': False,
    'test_image': 'preset-11',
    'cups_name': '$CUPS_NAME'
})
json.dump(data, open('$PRINTERS_FILE', 'w'), indent=2)
" 2>/dev/null

            log "Printer added: $PRINTER_IP ($CUPS_NAME)"
        else
            log "Printer at $PRINTER_IP already configured — skipping auto-add."
        fi
    else
        log "WARNING: PRINTER_IP has invalid format: $PRINTER_IP — skipping auto-add."
    fi
fi

# ── Symlink CUPS config to /data for persistence ────────────────
if [ ! -d /data/cups ]; then
    cp -a /etc/cups /data/cups
fi
ln -sf /data/logs /var/log/cups 2>/dev/null || true

# ── Re-register all printers in CUPS (from persisted config) ────
log "Registering printers from config..."
python3 -c "
import json, subprocess
data = json.load(open('$PRINTERS_FILE'))
for p in data.get('printers', []):
    cups_name = p['cups_name']
    conn = p.get('connection', 'ipp')
    ip = p['ip']
    port = p.get('port', 9100)
    uri = f'socket://{ip}:{port}' if conn == 'socket' else f'ipp://{ip}/ipp/print'
    paper = p.get('paper_size', 'A4')
    try:
        subprocess.run(['lpadmin', '-p', cups_name, '-v', uri, '-m', 'everywhere',
                        '-L', 'Network', '-D', p.get('name', cups_name),
                        '-o', f'media={paper}'], check=True, capture_output=True, timeout=15)
        subprocess.run(['cupsaccept', cups_name], capture_output=True, timeout=5)
        subprocess.run(['cupsenable', cups_name], capture_output=True, timeout=5)
        print(f'  Registered: {cups_name} -> {uri}')
    except Exception as e:
        print(f'  FAILED: {cups_name} -> {e}')
" 2>/dev/null || true

# ── Install cron schedules (one line per non-paused printer) ─────
log "Installing cron schedules..."
python3 -c "
import json
data = json.load(open('$PRINTERS_FILE'))
lines = []
for p in data.get('printers', []):
    if not p.get('paused', False):
        sched = p.get('schedule', '$SCHEDULE')
        pid = p['id']
        lines.append(f'{sched} . /etc/environment; /app/auto-print.sh --printer-id={pid} >> /data/logs/cron.log 2>&1')
cron = '\n'.join(lines) + '\n' if lines else ''
import subprocess
subprocess.run(['bash', '-c', f'echo \"{cron}\" | crontab -'], capture_output=True)
num = len(lines)
print(f'  {num} cron job(s) installed')
" 2>/dev/null || true

# ── Start cron ──────────────────────────────────────────────────
log "Starting cron daemon..."
cron

# ── Export WEBHOOK_URL from config (for cron jobs) ────────────────
WEBHOOK_URL_FROM_CONFIG=$(python3 -c "
import json
data = json.load(open('$PRINTERS_FILE'))
print(data.get('global', {}).get('webhook_url', ''))
" 2>/dev/null) || WEBHOOK_URL_FROM_CONFIG=""

# Prefer config file value, fall back to env var
export WEBHOOK_URL="${WEBHOOK_URL_FROM_CONFIG:-$WEBHOOK_URL}"

# Write to /etc/environment so cron jobs inherit it
echo "WEBHOOK_URL=\"$WEBHOOK_URL\"" >> /etc/environment

# ── Start web UI ────────────────────────────────────────────────
log "Starting web UI on port 8631..."
python3 /app/webui.py &

# ── Count printers ──────────────────────────────────────────────
NUM_PRINTERS=$(python3 -c "import json; print(len(json.load(open('$PRINTERS_FILE')).get('printers',[])))" 2>/dev/null) || NUM_PRINTERS=0

log "============================================================"
log " print-blockage-stopper v1.4 is running"
log " Dashboard:  http://localhost:8631"
log " CUPS UI:    http://localhost:631"
log " Printers:   $NUM_PRINTERS configured"
log " Logs:       /data/logs/"
log "============================================================"

# ── Keep container alive ────────────────────────────────────────
touch /data/logs/cron.log
exec tail -f /data/logs/cron.log /var/log/cups/error_log 2>/dev/null || \
    exec tail -f /dev/null

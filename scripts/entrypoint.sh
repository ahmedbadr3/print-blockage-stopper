#!/usr/bin/env bash
###############################################################################
# entrypoint.sh — First-boot printer setup, cron installation, service start
###############################################################################
set -euo pipefail

LOG_DIR="/data/logs"
mkdir -p "$LOG_DIR"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] ENTRYPOINT: $*"; }

# ── Input validation ────────────────────────────────────────────

# PRINTER_IP — required, must look like an IPv4 address or hostname
if [ -z "$PRINTER_IP" ]; then
    log "============================================================"
    log "ERROR: PRINTER_IP is not set."
    log ""
    log "Set the PRINTER_IP environment variable to your printer's"
    log "IP address. Example:"
    log "  docker run -e PRINTER_IP=192.168.1.50 ..."
    log "============================================================"
    exit 1
fi

# Allow IPv4 addresses and simple hostnames (alphanumeric, dots, hyphens)
if ! echo "$PRINTER_IP" | grep -qE '^[a-zA-Z0-9][a-zA-Z0-9.\-]{0,253}[a-zA-Z0-9]$'; then
    log "ERROR: PRINTER_IP contains invalid characters: $PRINTER_IP"
    log "       Must be an IPv4 address (e.g. 192.168.1.50) or hostname."
    exit 1
fi

# PRINTER_PORT — must be numeric, 1-65535
PRINTER_PORT="${PRINTER_PORT:-9100}"
if ! echo "$PRINTER_PORT" | grep -qE '^[0-9]{1,5}$' || [ "$PRINTER_PORT" -lt 1 ] || [ "$PRINTER_PORT" -gt 65535 ]; then
    log "ERROR: PRINTER_PORT must be a number between 1 and 65535. Got: $PRINTER_PORT"
    exit 1
fi

# CONNECTION — must be 'ipp' or 'socket'
CONNECTION="${CONNECTION:-ipp}"
if [ "$CONNECTION" != "ipp" ] && [ "$CONNECTION" != "socket" ]; then
    log "ERROR: CONNECTION must be 'ipp' or 'socket'. Got: $CONNECTION"
    exit 1
fi

# PAPER_SIZE — alphanumeric only (A4, Letter, A3, etc.)
PAPER_SIZE="${PAPER_SIZE:-A4}"
if ! echo "$PAPER_SIZE" | grep -qE '^[a-zA-Z0-9]{1,20}$'; then
    log "ERROR: PAPER_SIZE contains invalid characters: $PAPER_SIZE"
    exit 1
fi

# SCHEDULE — validate cron expression (5 fields, safe characters only)
SCHEDULE="${SCHEDULE:-0 10 */3 * *}"
if ! echo "$SCHEDULE" | grep -qE '^[0-9\*\/,\-]+[[:space:]]+[0-9\*\/,\-]+[[:space:]]+[0-9\*\/,\-]+[[:space:]]+[0-9\*\/,\-]+[[:space:]]+[0-9\*\/,\-]+$'; then
    log "ERROR: SCHEDULE is not a valid 5-field cron expression: $SCHEDULE"
    log "       Example: '0 10 */3 * *' (every 3 days at 10 AM)"
    exit 1
fi

# ── Determine printer URI ───────────────────────────────────────
if [ "$CONNECTION" = "socket" ]; then
    PRINTER_URI="socket://${PRINTER_IP}:${PRINTER_PORT}"
else
    PRINTER_URI="ipp://${PRINTER_IP}/ipp/print"
fi

PRINTER_NAME="PRINTER"

log "Printer IP:    $PRINTER_IP"
log "Connection:    $PRINTER_URI"
log "Schedule:      $SCHEDULE"
log "Paper size:    $PAPER_SIZE"

# ── Start CUPS ──────────────────────────────────────────────────
log "Starting CUPS daemon..."
cupsd

# Give CUPS a moment to initialise
sleep 3

# ── Configure printer (idempotent) ──────────────────────────────
# Check if printer already exists (persisted via /data volume)
if lpstat -p "$PRINTER_NAME" &>/dev/null; then
    log "Printer '$PRINTER_NAME' already configured — updating URI..."
    lpadmin -p "$PRINTER_NAME" -v "$PRINTER_URI"
else
    log "Adding printer '$PRINTER_NAME'..."

    # Use IPP Everywhere (driverless) — works reliably with any modern network printer
    # GutenPrint PPDs are available in the container but not auto-selected, as the
    # generic match can pick the wrong model. Users can manually set a PPD via CUPS
    # web UI if they need a specific driver.
    PPD="everywhere"
    log "Using IPP Everywhere (driverless) driver."

    log "Using PPD: $PPD"

    lpadmin -p "$PRINTER_NAME" \
        -v "$PRINTER_URI" \
        -m "$PPD" \
        -L "Network" \
        -D "Print Blockage Stopper" \
        -o media="$PAPER_SIZE"

    # Accept jobs and enable
    cupsaccept "$PRINTER_NAME" 2>/dev/null || true
    cupsenable "$PRINTER_NAME" 2>/dev/null || true
fi

# Set as default printer
lpadmin -d "$PRINTER_NAME" 2>/dev/null || true

log "Printer configured. CUPS web UI: http://$(hostname -I | awk '{print $1}'):631"

# ── Symlink CUPS config to /data for persistence ────────────────
# On first run, move CUPS config to /data; on subsequent runs, link back
if [ ! -d /data/cups ]; then
    cp -a /etc/cups /data/cups
fi
# Don't overwrite running config — just ensure logs go to /data
ln -sf /data/logs /var/log/cups 2>/dev/null || true

# ── Install cron schedule ───────────────────────────────────────
CRON_LINE="$SCHEDULE /app/auto-print.sh >> /data/logs/cron.log 2>&1"
log "Installing cron: $CRON_LINE"

# Write crontab (replace any existing)
echo "$CRON_LINE" | crontab -

# ── Start cron ──────────────────────────────────────────────────
log "Starting cron daemon..."
cron

# ── Start web UI ────────────────────────────────────────────────
log "Starting web UI on port 8631..."
python3 /app/webui.py &

log "============================================================"
log " print-blockage-stopper is running"
log " Dashboard:  http://localhost:8631"
log " CUPS UI:    http://localhost:631"
log " Schedule:   $SCHEDULE"
log " Logs:       /data/logs/"
log "============================================================"

# ── Keep container alive (tail CUPS logs) ───────────────────────
# Create cron.log if it doesn't exist so tail doesn't fail
touch /data/logs/cron.log
exec tail -f /data/logs/cron.log /var/log/cups/error_log 2>/dev/null || \
    exec tail -f /dev/null

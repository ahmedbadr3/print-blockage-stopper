#!/usr/bin/env bash
###############################################################################
# auto-print.sh — Send a maintenance test print to the printer
# Runs inside the container, called by cron or the web UI.
###############################################################################
set -euo pipefail

PRINTER="PRINTER"
IMAGE="/app/test-print.png"
LOG_FILE="/data/logs/auto-print.log"
STATUS_FILE="/data/status.json"
NOTIFY_SCRIPT="/unraid/notify"

timestamp() { date '+%Y-%m-%d %H:%M:%S'; }

log() {
    local msg="[$(timestamp)] $*"
    echo "$msg"
    echo "$msg" >> "$LOG_FILE"
}

write_status() {
    local status="$1" message="$2"
    cat > "$STATUS_FILE" <<JSON
{"status":"${status}","message":"${message}","timestamp":"$(timestamp)"}
JSON
}

notify_unraid() {
    local subject="$1" description="$2" severity="${3:-warning}"
    if [ -x "$NOTIFY_SCRIPT" ]; then
        "$NOTIFY_SCRIPT" -s "$subject" -d "$description" -i "$severity" 2>/dev/null || true
        log "Unraid notification sent: $subject"
    fi
}

# ── Pre-flight ──────────────────────────────────────────────────
if [ ! -f "$IMAGE" ]; then
    log "ERROR: Test image not found at $IMAGE"
    write_status "error" "Test image not found"
    notify_unraid "Print FAILED" "Test image not found at $IMAGE"
    exit 1
fi

# Check CUPS is running
if ! lpstat -r &>/dev/null; then
    log "ERROR: CUPS scheduler is not running. Attempting restart..."
    cupsd
    sleep 2
    if ! lpstat -r &>/dev/null; then
        log "ERROR: Could not restart CUPS. Aborting."
        write_status "error" "CUPS not running"
        notify_unraid "Print FAILED" "CUPS scheduler could not be started"
        exit 1
    fi
fi

# Check printer status
PRINTER_STATUS=$(lpstat -p "$PRINTER" 2>&1) || true
log "Printer status: $PRINTER_STATUS"

if echo "$PRINTER_STATUS" | grep -qi "disabled"; then
    log "WARNING: Printer is disabled. Re-enabling..."
    cupsenable "$PRINTER" 2>/dev/null || true
fi

# ── Send print job ──────────────────────────────────────────────
log "Sending maintenance print to $PRINTER..."

PAPER_SIZE="${PAPER_SIZE:-A4}"

JOB_OUTPUT=$(/usr/bin/lp -d "$PRINTER" \
    -o media="$PAPER_SIZE" \
    -o fit-to-page \
    -o orientation-requested=3 \
    "$IMAGE" 2>&1) || {
    log "ERROR: Print job failed. Output: $JOB_OUTPUT"
    write_status "error" "Print job failed: $JOB_OUTPUT"
    notify_unraid "Print FAILED" "Print job could not be submitted. Check printer connection and status."
    exit 1
}

log "SUCCESS: Print job submitted. $JOB_OUTPUT"
write_status "ok" "Print job submitted successfully"

# ── Log rotation (keep last 500 lines) ──────────────────────────
if [ -f "$LOG_FILE" ] && [ "$(wc -l < "$LOG_FILE")" -gt 500 ]; then
    tail -n 500 "$LOG_FILE" > "${LOG_FILE}.tmp" && mv "${LOG_FILE}.tmp" "$LOG_FILE"
fi

exit 0

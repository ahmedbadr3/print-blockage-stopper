#!/usr/bin/env bash
###############################################################################
# auto-print.sh — Send a maintenance test print to the printer
# Runs inside the container, called by cron or the web UI.
#
# When called with --force (from the dashboard "Print Now" button), the
# skip-if-recently-printed check is bypassed.
###############################################################################
set -euo pipefail

PRINTER="PRINTER"
IMAGE="/app/test-print.png"
LOG_FILE="/data/logs/auto-print.log"
STATUS_FILE="/data/status.json"
HISTORY_FILE="/data/print-history.json"
CONFIG_FILE="/data/config.json"
NOTIFY_SCRIPT="/unraid/notify"
FORCE=false

# Parse flags
for arg in "$@"; do
    case "$arg" in
        --force) FORCE=true ;;
    esac
done

timestamp() { date '+%Y-%m-%d %H:%M:%S'; }
epoch_now() { date '+%s'; }

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

# Append to print history (JSON lines file, one entry per print attempt)
write_history() {
    local result="$1" message="$2"
    echo "{\"timestamp\":\"$(timestamp)\",\"epoch\":$(epoch_now),\"result\":\"${result}\",\"message\":\"${message}\"}" >> "$HISTORY_FILE"
    # Keep last 90 entries
    if [ -f "$HISTORY_FILE" ] && [ "$(wc -l < "$HISTORY_FILE")" -gt 90 ]; then
        tail -n 90 "$HISTORY_FILE" > "${HISTORY_FILE}.tmp" && mv "${HISTORY_FILE}.tmp" "$HISTORY_FILE"
    fi
}

notify_unraid() {
    local subject="$1" description="$2" severity="${3:-warning}"
    if [ -x "$NOTIFY_SCRIPT" ]; then
        "$NOTIFY_SCRIPT" -s "$subject" -d "$description" -i "$severity" 2>/dev/null || true
        log "Unraid notification sent: $subject"
    fi
}

# Read skip_hours from config file (dashboard-configurable), fall back to env var
get_skip_hours() {
    if [ -f "$CONFIG_FILE" ]; then
        local val
        val=$(python3 -c "import json; print(json.load(open('$CONFIG_FILE')).get('skip_hours', ''))" 2>/dev/null) || true
        if [ -n "$val" ] && [ "$val" != "None" ]; then
            echo "$val"
            return
        fi
    fi
    echo "${SKIP_HOURS:-72}"
}

# ── Check if scheduling is paused ────────────────────────────────
if [ "$FORCE" = false ] && [ -f "$CONFIG_FILE" ]; then
    PAUSED=$(python3 -c "import json; print(json.load(open('$CONFIG_FILE')).get('paused', False))" 2>/dev/null) || true
    if [ "$PAUSED" = "True" ]; then
        log "Schedule is PAUSED — skipping maintenance print. Use dashboard to resume."
        exit 0
    fi
fi

# ── Smart skip: check if printer had a recent job ────────────────
if [ "$FORCE" = false ]; then
    SKIP_HOURS=$(get_skip_hours)
    SKIP_SECONDS=$((SKIP_HOURS * 3600))
    NOW=$(epoch_now)

    # Check CUPS completed jobs for any job within the skip window
    LAST_JOB_TIME=$(lpstat -W completed -o "$PRINTER" 2>/dev/null | tail -n 1 | grep -oP '\d{2} \w+ \d{4} \d{2}:\d{2}' | head -1) || true

    if [ -n "$LAST_JOB_TIME" ]; then
        LAST_JOB_EPOCH=$(date -d "$LAST_JOB_TIME" '+%s' 2>/dev/null) || LAST_JOB_EPOCH=0
        ELAPSED=$((NOW - LAST_JOB_EPOCH))
        if [ "$ELAPSED" -lt "$SKIP_SECONDS" ]; then
            HOURS_AGO=$((ELAPSED / 3600))
            log "SKIPPED: Printer had a job ${HOURS_AGO}h ago (within ${SKIP_HOURS}h window). No maintenance print needed."
            write_status "ok" "Skipped — printer was active ${HOURS_AGO}h ago"
            write_history "skipped" "Printer active ${HOURS_AGO}h ago (threshold: ${SKIP_HOURS}h)"
            exit 0
        fi
    fi
fi

# ── Pre-flight ──────────────────────────────────────────────────
if [ ! -f "$IMAGE" ]; then
    log "ERROR: Test image not found at $IMAGE"
    write_status "error" "Test image not found"
    write_history "error" "Test image not found"
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
        write_history "error" "CUPS not running"
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
    write_history "error" "Print job failed"
    notify_unraid "Print FAILED" "Print job could not be submitted. Check printer connection and status."
    exit 1
}

log "SUCCESS: Print job submitted. $JOB_OUTPUT"
write_status "ok" "Print job submitted successfully"
write_history "ok" "Print job submitted"

# ── Log rotation (keep last 500 lines) ──────────────────────────
if [ -f "$LOG_FILE" ] && [ "$(wc -l < "$LOG_FILE")" -gt 500 ]; then
    tail -n 500 "$LOG_FILE" > "${LOG_FILE}.tmp" && mv "${LOG_FILE}.tmp" "$LOG_FILE"
fi

exit 0

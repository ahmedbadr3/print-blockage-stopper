#!/usr/bin/env bash
###############################################################################
# auto-print.sh — Send a maintenance test print to a specific printer
# Runs inside the container, called by cron or the web UI.
#
# Usage:
#   auto-print.sh --printer-id=printer-abc123       (cron / dashboard)
#   auto-print.sh --printer-id=printer-abc123 --force   (Print Now button)
#
# When called with --force, the skip-if-recently-printed and pause checks
# are bypassed.
#
# Reads printer config from /data/printers.json.
###############################################################################
set -euo pipefail

LOG_FILE="/data/logs/auto-print.log"
HISTORY_FILE="/data/print-history.json"
PRINTERS_FILE="/data/printers.json"
PRESETS_DIR="/app/presets"
UPLOADS_DIR="/data/uploads"
NOTIFY_SCRIPT="/unraid/notify"

FORCE=false
PRINTER_ID=""

# Parse flags
for arg in "$@"; do
    case "$arg" in
        --force) FORCE=true ;;
        --printer-id=*) PRINTER_ID="${arg#--printer-id=}" ;;
    esac
done

timestamp() { date '+%Y-%m-%d %H:%M:%S'; }
epoch_now() { date '+%s'; }

log() {
    local msg="[$(timestamp)] [$PRINTER_ID] $*"
    echo "$msg"
    echo "$msg" >> "$LOG_FILE"
}

write_status() {
    local status="$1" message="$2"
    local status_file="/data/status-${PRINTER_ID}.json"
    cat > "$status_file" <<JSON
{"status":"${status}","message":"${message}","timestamp":"$(timestamp)","printer_id":"${PRINTER_ID}"}
JSON
}

write_history() {
    local result="$1" message="$2"
    echo "{\"timestamp\":\"$(timestamp)\",\"epoch\":$(epoch_now),\"result\":\"${result}\",\"message\":\"${message}\",\"printer_id\":\"${PRINTER_ID}\"}" >> "$HISTORY_FILE"
    # Keep last 200 entries (more printers = more entries)
    if [ -f "$HISTORY_FILE" ] && [ "$(wc -l < "$HISTORY_FILE")" -gt 200 ]; then
        tail -n 200 "$HISTORY_FILE" > "${HISTORY_FILE}.tmp" && mv "${HISTORY_FILE}.tmp" "$HISTORY_FILE"
    fi
}

notify_unraid() {
    local subject="$1" description="$2" severity="${3:-warning}"
    if [ -x "$NOTIFY_SCRIPT" ]; then
        "$NOTIFY_SCRIPT" -s "$subject" -d "$description" -i "$severity" 2>/dev/null || true
        log "Unraid notification sent: $subject"
    fi
}

# ── Validate printer ID ─────────────────────────────────────────
if [ -z "$PRINTER_ID" ]; then
    echo "[$(timestamp)] ERROR: --printer-id is required" >> "$LOG_FILE"
    exit 1
fi

if [ ! -f "$PRINTERS_FILE" ]; then
    echo "[$(timestamp)] ERROR: $PRINTERS_FILE not found" >> "$LOG_FILE"
    exit 1
fi

# ── Read printer config from JSON ────────────────────────────────
PRINTER_JSON=$(python3 -c "
import json, sys
data = json.load(open('$PRINTERS_FILE'))
for p in data.get('printers', []):
    if p['id'] == '$PRINTER_ID':
        json.dump(p, sys.stdout)
        sys.exit(0)
sys.exit(1)
" 2>/dev/null) || {
    log "ERROR: Printer ID '$PRINTER_ID' not found in config"
    exit 1
}

# Extract fields
CUPS_NAME=$(echo "$PRINTER_JSON" | python3 -c "import json,sys; print(json.load(sys.stdin)['cups_name'])")
PRINTER_NAME=$(echo "$PRINTER_JSON" | python3 -c "import json,sys; print(json.load(sys.stdin).get('name','Unknown'))")
PAPER_SIZE=$(echo "$PRINTER_JSON" | python3 -c "import json,sys; print(json.load(sys.stdin).get('paper_size','A4'))")
SKIP_HOURS=$(echo "$PRINTER_JSON" | python3 -c "import json,sys; print(json.load(sys.stdin).get('skip_hours',72))")
IS_PAUSED=$(echo "$PRINTER_JSON" | python3 -c "import json,sys; print(json.load(sys.stdin).get('paused',False))")
TEST_IMAGE_ID=$(echo "$PRINTER_JSON" | python3 -c "import json,sys; print(json.load(sys.stdin).get('test_image','preset-11'))")

# Resolve test image path
resolve_image() {
    local img_id="$1"
    if [[ "$img_id" == preset-* ]]; then
        local path="${PRESETS_DIR}/${img_id}.png"
        if [ -f "$path" ]; then echo "$path"; return; fi
    elif [[ "$img_id" == custom-* ]]; then
        local filename="${img_id#custom-}"
        local path="${UPLOADS_DIR}/${filename}"
        if [ -f "$path" ]; then echo "$path"; return; fi
    fi
    # Fallback
    if [ -f "/app/test-print.png" ]; then echo "/app/test-print.png"; return; fi
    echo "${PRESETS_DIR}/preset-11.png"
}

IMAGE=$(resolve_image "$TEST_IMAGE_ID")

log "Printer: $PRINTER_NAME ($CUPS_NAME) | Image: $TEST_IMAGE_ID"

# ── Check if scheduling is paused ────────────────────────────────
if [ "$FORCE" = false ] && [ "$IS_PAUSED" = "True" ]; then
    log "Schedule is PAUSED — skipping. Use dashboard to resume."
    exit 0
fi

# ── Smart skip: check if printer had a recent job ────────────────
if [ "$FORCE" = false ]; then
    SKIP_SECONDS=$((SKIP_HOURS * 3600))
    NOW=$(epoch_now)

    LAST_JOB_TIME=$(lpstat -W completed -o "$CUPS_NAME" 2>/dev/null | tail -n 1 | grep -oP '\d{2} \w+ \d{4} \d{2}:\d{2}' | head -1) || true

    if [ -n "$LAST_JOB_TIME" ]; then
        LAST_JOB_EPOCH=$(date -d "$LAST_JOB_TIME" '+%s' 2>/dev/null) || LAST_JOB_EPOCH=0
        ELAPSED=$((NOW - LAST_JOB_EPOCH))
        if [ "$ELAPSED" -lt "$SKIP_SECONDS" ]; then
            HOURS_AGO=$((ELAPSED / 3600))
            log "SKIPPED: Active ${HOURS_AGO}h ago (within ${SKIP_HOURS}h window)."
            write_status "ok" "Skipped — active ${HOURS_AGO}h ago"
            write_history "skipped" "Active ${HOURS_AGO}h ago (threshold: ${SKIP_HOURS}h)"
            exit 0
        fi
    fi
fi

# ── Pre-flight ──────────────────────────────────────────────────
if [ ! -f "$IMAGE" ]; then
    log "ERROR: Test image not found at $IMAGE"
    write_status "error" "Test image not found"
    write_history "error" "Test image not found"
    notify_unraid "Print FAILED — $PRINTER_NAME" "Test image not found at $IMAGE"
    exit 1
fi

# Check CUPS is running
if ! lpstat -r &>/dev/null; then
    log "ERROR: CUPS not running. Attempting restart..."
    cupsd
    sleep 2
    if ! lpstat -r &>/dev/null; then
        log "ERROR: Could not restart CUPS."
        write_status "error" "CUPS not running"
        write_history "error" "CUPS not running"
        notify_unraid "Print FAILED — $PRINTER_NAME" "CUPS could not be started"
        exit 1
    fi
fi

# Check printer status
PRINTER_STATUS=$(lpstat -p "$CUPS_NAME" 2>&1) || true
log "Printer status: $PRINTER_STATUS"

if echo "$PRINTER_STATUS" | grep -qi "disabled"; then
    log "WARNING: Printer disabled. Re-enabling..."
    cupsenable "$CUPS_NAME" 2>/dev/null || true
fi

# ── Send print job (with retry) ──────────────────────────────────
log "Sending maintenance print..."

attempt_print() {
    /usr/bin/lp -d "$CUPS_NAME" \
        -o media="$PAPER_SIZE" \
        -o fit-to-page \
        -o orientation-requested=3 \
        "$IMAGE" 2>&1
}

JOB_OUTPUT=$(attempt_print) || {
    log "WARNING: First attempt failed. Retrying in 30 seconds..."
    sleep 30

    # Re-enable printer if it went into error state
    cupsenable "$CUPS_NAME" 2>/dev/null || true

    JOB_OUTPUT=$(attempt_print) || {
        log "ERROR: Print failed after retry. $JOB_OUTPUT"
        write_status "error" "Print failed after retry: $JOB_OUTPUT"
        write_history "error" "Print job failed (after retry)"
        notify_unraid "Print FAILED — $PRINTER_NAME" "Could not submit job after 2 attempts. Check printer connection."

        # Send webhook notification if configured
        WEBHOOK_URL="${WEBHOOK_URL:-}"
        if [ -n "$WEBHOOK_URL" ]; then
            curl -sf -X POST "$WEBHOOK_URL" \
                -H "Content-Type: application/json" \
                -d "{\"event\":\"print_failed\",\"printer\":\"$PRINTER_NAME\",\"printer_id\":\"$PRINTER_ID\",\"message\":\"Print failed after 2 attempts\",\"timestamp\":\"$(timestamp)\"}" \
                2>/dev/null || true
        fi
        exit 1
    }
}

log "SUCCESS: $JOB_OUTPUT"
write_status "ok" "Print job submitted successfully"
write_history "ok" "Print job submitted"

# Send webhook notification on success if configured
WEBHOOK_URL="${WEBHOOK_URL:-}"
if [ -n "$WEBHOOK_URL" ]; then
    curl -sf -X POST "$WEBHOOK_URL" \
        -H "Content-Type: application/json" \
        -d "{\"event\":\"print_ok\",\"printer\":\"$PRINTER_NAME\",\"printer_id\":\"$PRINTER_ID\",\"message\":\"Print job submitted\",\"timestamp\":\"$(timestamp)\"}" \
        2>/dev/null || true
fi

# ── Log rotation (keep last 1000 lines for multi-printer) ────────
if [ -f "$LOG_FILE" ] && [ "$(wc -l < "$LOG_FILE")" -gt 1000 ]; then
    tail -n 1000 "$LOG_FILE" > "${LOG_FILE}.tmp" && mv "${LOG_FILE}.tmp" "$LOG_FILE"
fi

exit 0

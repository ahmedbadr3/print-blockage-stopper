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
JOB_TIMEOUT="${JOB_TIMEOUT:-600}"
FAILURE_ALERT_THRESHOLD="${FAILURE_ALERT_THRESHOLD:-2}"
[[ "$JOB_TIMEOUT" =~ ^[0-9]+$ ]] || JOB_TIMEOUT=600
[[ "$FAILURE_ALERT_THRESHOLD" =~ ^[0-9]+$ ]] || FAILURE_ALERT_THRESHOLD=2

FORCE=false
PRINTER_ID=""

# Parse flags
for arg in "$@"; do
    case "$arg" in
        --force) FORCE=true ;;
        --printer-id=*) PRINTER_ID="${arg#--printer-id=}" ;;
    esac
done

# Validate PRINTER_ID format (prevent path traversal)
if [ -z "$PRINTER_ID" ] || ! echo "$PRINTER_ID" | grep -qE '^[a-zA-Z0-9_-]+$'; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ERROR: Invalid or missing PRINTER_ID: $PRINTER_ID" >> "$LOG_FILE"
    exit 1
fi

timestamp() { date '+%Y-%m-%d %H:%M:%S'; }

# One run per printer at a time: a run cancels stale jobs, which must never
# include a job another run is still waiting on.
exec 9>"/tmp/pbs-${PRINTER_ID}.lock"
if ! flock -n 9; then
    echo "[$(timestamp)] [$PRINTER_ID] Another run is in progress — skipping." >> "$LOG_FILE"
    exit 0
fi
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

# Number of consecutive failed runs for this printer, newest first
# ("skipped" runs neither break nor extend the streak).
failure_streak() {
    PBS_HISTORY_FILE="$HISTORY_FILE" PBS_PRINTER_ID="$PRINTER_ID" python3 -c "
import json, os
streak = 0
try:
    lines = open(os.environ['PBS_HISTORY_FILE']).read().splitlines()
except FileNotFoundError:
    lines = []
for line in reversed(lines):
    try:
        e = json.loads(line)
    except ValueError:
        continue
    if e.get('printer_id') != os.environ['PBS_PRINTER_ID'] or e.get('result') == 'skipped':
        continue
    if e.get('result') != 'error':
        break
    streak += 1
print(streak)
" 2>/dev/null || echo 0
}

notify_unraid() {
    local subject="$1" description="$2" severity="${3:-warning}"
    if [ -x "$NOTIFY_SCRIPT" ]; then
        "$NOTIFY_SCRIPT" -s "$subject" -d "$description" -i "$severity" 2>/dev/null || true
        log "Unraid notification sent: $subject"
    fi
}

# Record a failed run. Alerts are held until FAILURE_ALERT_THRESHOLD runs in a
# row have failed, so a single blip doesn't page anyone.
#   fail <status message> <history message> <notify event> <notify message>
fail() {
    write_status "error" "$1"
    write_history "error" "$2"
    local streak
    streak=$(failure_streak)
    if [ "$streak" -ge "$FAILURE_ALERT_THRESHOLD" ]; then
        notify_unraid "Print FAILED — $PRINTER_NAME" "$4 ($streak failed runs in a row)"
        python3 /app/notify.py --event "$3" \
            --printer "$PRINTER_NAME" --printer-id "$PRINTER_ID" \
            --message "$4 ($streak failed runs in a row)" 2>/dev/null || true
    else
        log "Failure $streak of $FAILURE_ALERT_THRESHOLD before alerting."
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
PRINTER_JSON=$(PBS_PRINTERS_FILE="$PRINTERS_FILE" PBS_PRINTER_ID="$PRINTER_ID" python3 -c "
import json, sys, os
data = json.load(open(os.environ['PBS_PRINTERS_FILE']))
for p in data.get('printers', []):
    if p['id'] == os.environ['PBS_PRINTER_ID']:
        json.dump(p, sys.stdout)
        sys.exit(0)
sys.exit(1)
" 2>/dev/null) || {
    log "ERROR: Printer ID '$PRINTER_ID' not found in config"
    exit 1
}

# Extract all fields in a single Python call
eval "$(echo "$PRINTER_JSON" | python3 -c "
import json, sys, shlex
p = json.load(sys.stdin)
fields = {
    'CUPS_NAME': p.get('cups_name', ''),
    'PRINTER_NAME': p.get('name', 'Unknown'),
    'PRINTER_IP': p.get('ip', ''),
    'PAPER_SIZE': p.get('paper_size', 'A4'),
    'SKIP_HOURS': str(p.get('skip_hours', 72)),
    'IS_PAUSED': str(p.get('paused', False)),
    'TEST_IMAGE_ID': p.get('test_image', 'preset-11'),
    'CONNECTION': p.get('connection', 'ipp'),
    'SOCKET_PORT': str(p.get('port', 9100)),
}
for k, v in fields.items():
    print(f'{k}={shlex.quote(v)}')
")"

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

IMAGE_ORIG=$(resolve_image "$TEST_IMAGE_ID")

# Stamp printer info onto a temp copy of the image
PRINTER_MODEL=$(echo "$PRINTER_JSON" | python3 -c "import json, sys; print(json.load(sys.stdin).get('model', ''))" 2>/dev/null) || PRINTER_MODEL=""
STAMPED_IMAGE="/tmp/stamped-${PRINTER_ID}.png"
python3 /app/stamp_image.py "$IMAGE_ORIG" "$STAMPED_IMAGE" "$PRINTER_NAME" "$PRINTER_IP" "$PRINTER_MODEL" 2>/dev/null && {
    IMAGE="$STAMPED_IMAGE"
} || {
    log "WARNING: Could not stamp image, using original"
    IMAGE="$IMAGE_ORIG"
}

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

    LAST_JOB_TIME=$(lpstat -W completed -o "$CUPS_NAME" 2>/dev/null | tail -n 1 | grep -oE '[0-9]{2} [A-Za-z]+ [0-9]{4} [0-9]{2}:[0-9]{2}' | head -1) || true

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

# Cancel leftover jobs. Every maintenance job is either confirmed or cancelled
# by the run that sent it, so anything still queued is stale — and would all
# print at once when the printer comes back.
STALE_JOBS=$(lpstat -o "$CUPS_NAME" 2>/dev/null | awk '{print $1}' | tr '\n' ' ') || true
if [ -n "${STALE_JOBS// /}" ]; then
    log "Cancelling stale queued jobs: $STALE_JOBS"
    cancel -a "$CUPS_NAME" 2>/dev/null || true
fi

# Don't queue anything for a printer that isn't there.
if [ "$CONNECTION" = "socket" ]; then CHECK_PORT="$SOCKET_PORT"; else CHECK_PORT=631; fi
if ! python3 -c "
import socket, sys
try:
    socket.create_connection((sys.argv[1], int(sys.argv[2])), timeout=5).close()
except OSError:
    sys.exit(1)
" "$PRINTER_IP" "$CHECK_PORT" 2>/dev/null; then
    log "Printer offline ($PRINTER_IP:$CHECK_PORT unreachable) — nothing queued."
    fail "Printer offline — nothing queued" "Printer offline - nothing queued" \
        print_offline "Printer unreachable at $PRINTER_IP:$CHECK_PORT, maintenance print not sent"
    exit 1
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
        fail "Print failed after retry: $JOB_OUTPUT" "Print job failed (after retry)" \
            print_failed "Could not submit job after 2 attempts, check printer connection"
        exit 1
    }
}

# Extract job ID from lp output (e.g. "request id is PBS_legacy-1 (1 file(s))")
JOB_ID=$(echo "$JOB_OUTPUT" | grep -o '[^ ]*-[0-9]*' | head -1)
log "Job submitted: $JOB_OUTPUT (job=$JOB_ID)"

# ── Wait for print completion (JOB_TIMEOUT, default 10 minutes) ──
POLL_INTERVAL=5
MAX_WAIT="$JOB_TIMEOUT"
ELAPSED=0
FINAL_STATUS="unknown"

if [ -n "$JOB_ID" ]; then
    log "Monitoring job $JOB_ID for up to ${MAX_WAIT}s..."
    while [ "$ELAPSED" -lt "$MAX_WAIT" ]; do
        sleep "$POLL_INTERVAL"
        ELAPSED=$((ELAPSED + POLL_INTERVAL))

        # Check if job appears in completed list
        if lpstat -W completed 2>/dev/null | grep -q "$JOB_ID"; then
            FINAL_STATUS="completed"
            break
        fi

        # Check if job is still active
        JOB_STATE=$(lpstat -o "$CUPS_NAME" 2>/dev/null | grep "$JOB_ID" || true)
        if [ -z "$JOB_STATE" ]; then
            # Job gone from active queue but not in completed — check not-completed
            if lpstat -W not-completed 2>/dev/null | grep -q "$JOB_ID"; then
                # Still processing
                continue
            fi
            # Job vanished — assume completed (some CUPS configs don't retain history)
            FINAL_STATUS="completed"
            break
        fi

        # Check for held/stopped state (paper tray, out of paper, etc.)
        if echo "$JOB_STATE" | grep -qi "held\|stopped\|cancelled\|canceled"; then
            FINAL_STATUS="stopped"
            break
        fi
    done

    if [ "$ELAPSED" -ge "$MAX_WAIT" ] && [ "$FINAL_STATUS" = "unknown" ]; then
        FINAL_STATUS="timeout"
    fi
else
    # Couldn't parse job ID — fall back to submission-only status
    FINAL_STATUS="submitted"
fi

log "Job $JOB_ID final status: $FINAL_STATUS (after ${ELAPSED}s)"

# An unconfirmed job must not linger in the queue, or it prints whenever the
# printer next comes back — along with every other one that piled up.
if [ "$FINAL_STATUS" = "stopped" ] || [ "$FINAL_STATUS" = "timeout" ]; then
    STOP_REASON=$(lpstat -o "$CUPS_NAME" 2>/dev/null | grep "$JOB_ID" || true)
    cancel "$JOB_ID" 2>/dev/null && log "Cancelled job $JOB_ID" || true
fi

PRIOR_FAILURES=$(failure_streak)

case "$FINAL_STATUS" in
    completed)
        write_status "ok" "Print completed successfully"
        write_history "ok" "Print completed"
        COMPLETED_EVENT=print_completed
        if [ "$PRIOR_FAILURES" -ge "$FAILURE_ALERT_THRESHOLD" ]; then
            COMPLETED_EVENT=print_recovered
            notify_unraid "Print RECOVERED — $PRINTER_NAME" "Printing again after $PRIOR_FAILURES failed runs" normal
        fi
        python3 /app/notify.py --event "$COMPLETED_EVENT" \
            --printer "$PRINTER_NAME" --printer-id "$PRINTER_ID" \
            --message "Print completed successfully" 2>/dev/null || true
        ;;
    submitted)
        write_status "ok" "Print job submitted"
        write_history "ok" "Print job submitted"
        python3 /app/notify.py --event print_ok \
            --printer "$PRINTER_NAME" --printer-id "$PRINTER_ID" \
            --message "Print job submitted" 2>/dev/null || true
        ;;
    stopped)
        REASON="${STOP_REASON:-Job held/stopped — check printer (paper tray, ink, jam)}"
        fail "Print stopped and cancelled: $REASON" "Print stopped by printer - job cancelled" \
            print_stopped "$REASON"
        ;;
    timeout)
        fail "Not confirmed within ${MAX_WAIT}s — job cancelled" "Not confirmed within ${MAX_WAIT}s - job cancelled" \
            print_timeout "Completion not confirmed within ${MAX_WAIT}s, job cancelled so it cannot print later"
        ;;
    *)
        write_status "ok" "Print job submitted"
        write_history "ok" "Print job submitted"
        python3 /app/notify.py --event print_ok \
            --printer "$PRINTER_NAME" --printer-id "$PRINTER_ID" \
            --message "Print job submitted" 2>/dev/null || true
        ;;
esac

# ── Log rotation (keep last 1000 lines for multi-printer) ────────
if [ -f "$LOG_FILE" ] && [ "$(wc -l < "$LOG_FILE")" -gt 1000 ]; then
    tail -n 1000 "$LOG_FILE" > "${LOG_FILE}.tmp" && mv "${LOG_FILE}.tmp" "$LOG_FILE"
fi

exit 0

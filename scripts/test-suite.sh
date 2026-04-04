#!/usr/bin/env bash
###############################################################################
# test-suite.sh — Automated test suite for print-blockage-stopper
#
# Run on Unraid (or any Docker host with the printer accessible).
#
# Usage:
#   bash test-suite.sh [PRINTER_IP]
#
# Default PRINTER_IP: 192.168.1.23
###############################################################################
set -uo pipefail

PRINTER_IP="${1:-192.168.1.23}"
CONTAINER="pbs-test"
APPDATA="/mnt/user/appdata/pbs-test"
IMAGE="abadrdh/print-blockage-stopper:latest"
DASHBOARD="http://localhost:8631"

PASS=0
FAIL=0
SKIP=0

# ── Helpers ──────────────────────────────────────────────────────

green()  { printf "\033[32m%s\033[0m\n" "$*"; }
red()    { printf "\033[31m%s\033[0m\n" "$*"; }
yellow() { printf "\033[33m%s\033[0m\n" "$*"; }
bold()   { printf "\033[1m%s\033[0m\n" "$*"; }

check() {
    local desc="$1"
    shift
    if "$@" >/dev/null 2>&1; then
        green "  ✓ $desc"
        ((PASS++))
    else
        red "  ✗ $desc"
        ((FAIL++))
    fi
}

check_output() {
    local desc="$1" expected="$2"
    shift 2
    local output
    output=$("$@" 2>&1) || true
    if echo "$output" | grep -qi "$expected"; then
        green "  ✓ $desc"
        ((PASS++))
    else
        red "  ✗ $desc (expected '$expected', got: $(echo "$output" | head -1))"
        ((FAIL++))
    fi
}

check_http() {
    local desc="$1" url="$2" expected_code="${3:-200}"
    local code
    code=$(curl -sf -o /dev/null -w "%{http_code}" "$url" 2>/dev/null) || code="000"
    if [ "$code" = "$expected_code" ]; then
        green "  ✓ $desc (HTTP $code)"
        ((PASS++))
    else
        red "  ✗ $desc (expected HTTP $expected_code, got $code)"
        ((FAIL++))
    fi
}

check_json() {
    local desc="$1" url="$2" jq_filter="$3" expected="$4"
    local val
    val=$(curl -sf "$url" 2>/dev/null | python3 -c "
import json, sys
data = json.load(sys.stdin)
keys = '$jq_filter'.split('.')
for k in keys:
    if k: data = data.get(k, '') if isinstance(data, dict) else ''
print(data)
" 2>/dev/null) || val=""
    if [ "$val" = "$expected" ]; then
        green "  ✓ $desc"
        ((PASS++))
    else
        red "  ✗ $desc (expected '$expected', got '$val')"
        ((FAIL++))
    fi
}

wait_healthy() {
    local max_wait=60
    for i in $(seq 1 $max_wait); do
        local status
        status=$(docker inspect --format='{{.State.Health.Status}}' "$CONTAINER" 2>/dev/null) || status="missing"
        if [ "$status" = "healthy" ]; then
            return 0
        fi
        # Also accept running + dashboard responding (health check interval may be long)
        if [ "$i" -ge 10 ] && curl -sf "$DASHBOARD/" >/dev/null 2>&1; then
            return 0
        fi
        sleep 1
    done
    return 1
}

cleanup() {
    docker stop "$CONTAINER" >/dev/null 2>&1 || true
    docker rm "$CONTAINER" >/dev/null 2>&1 || true
}

# ── Banner ───────────────────────────────────────────────────────

bold "╔══════════════════════════════════════════════════════════╗"
bold "║       print-blockage-stopper — Test Suite               ║"
bold "╚══════════════════════════════════════════════════════════╝"
echo ""
echo "  Image:      $IMAGE"
echo "  Printer IP: $PRINTER_IP"
echo "  Appdata:    $APPDATA"
echo ""

###############################################################################
# TEST 1: Clean Install
###############################################################################
bold "━━━ Test 1: Clean Install ━━━"

cleanup
rm -rf "$APPDATA" 2>/dev/null || true

docker run -d --name "$CONTAINER" \
    -e PRINTER_IP="$PRINTER_IP" \
    -p 8631:8631 -p 631:631 \
    -v "$APPDATA:/data" \
    "$IMAGE" >/dev/null 2>&1

echo "  Waiting for container to start..."
sleep 5

# 1.1 Container running
check "Container is running" docker inspect --format='{{.State.Running}}' "$CONTAINER"

# 1.2 No error logs at startup
check "No errors in startup logs" bash -c "! docker logs $CONTAINER 2>&1 | grep -i 'ERROR'"

# 1.3 CUPS ready message
check_output "CUPS started successfully" "CUPS ready" docker logs "$CONTAINER"

# 1.4 Printer registered
check_output "Printer auto-added from env var" "Printer added" docker logs "$CONTAINER"

# 1.5 Cron installed
check_output "Cron job(s) installed" "cron job" docker logs "$CONTAINER"

# 1.6 Dashboard loads
echo "  Waiting for dashboard..."
for i in $(seq 1 15); do
    curl -sf "$DASHBOARD/" >/dev/null 2>&1 && break
    sleep 1
done
check_http "Dashboard loads (HTTP 200)" "$DASHBOARD/"

# 1.7 API endpoints
check_http "API: /api/printers" "$DASHBOARD/api/printers"
check_http "API: /api/history" "$DASHBOARD/api/history"
check_http "API: /api/presets" "$DASHBOARD/api/presets"
check_http "API: /api/logs" "$DASHBOARD/api/logs"

# 1.8 Printer in config
check_json "Printer appears in config" "$DASHBOARD/api/printers" "printers" "is not empty" || true
PRINTER_COUNT=$(curl -sf "$DASHBOARD/api/printers" 2>/dev/null | python3 -c "import json,sys; print(len(json.load(sys.stdin).get('printers',[])))" 2>/dev/null) || PRINTER_COUNT=0
if [ "$PRINTER_COUNT" -ge 1 ]; then
    green "  ✓ Printer count: $PRINTER_COUNT"
    ((PASS++))
else
    red "  ✗ No printers found in config"
    ((FAIL++))
fi

# 1.9 Printer connectivity (probe)
check_http "API: probe printer" "$DASHBOARD/api/probe/$PRINTER_IP"
REACHABLE=$(curl -sf "$DASHBOARD/api/probe/$PRINTER_IP" 2>/dev/null | python3 -c "import json,sys; print(json.load(sys.stdin).get('reachable',False))" 2>/dev/null) || REACHABLE="False"
if [ "$REACHABLE" = "True" ]; then
    green "  ✓ Printer reachable at $PRINTER_IP"
    ((PASS++))
else
    yellow "  ⚠ Printer not reachable at $PRINTER_IP (may be expected if not on network)"
    ((SKIP++))
fi

# 1.10 Get printer ID for further tests
PRINTER_ID=$(curl -sf "$DASHBOARD/api/printers" 2>/dev/null | python3 -c "import json,sys; ps=json.load(sys.stdin).get('printers',[]); print(ps[0]['id'] if ps else '')" 2>/dev/null) || PRINTER_ID=""

# 1.11 Print Now
if [ -n "$PRINTER_ID" ]; then
    PRINT_RESP=$(curl -sf -X POST "$DASHBOARD/api/print-now/$PRINTER_ID" 2>/dev/null)
    if echo "$PRINT_RESP" | python3 -c "import json,sys; assert json.load(sys.stdin).get('ok')" 2>/dev/null; then
        green "  ✓ Print Now triggered"
        ((PASS++))
    else
        red "  ✗ Print Now failed"
        ((FAIL++))
    fi
    sleep 5

    # 1.12 Status updates after print
    STATUS=$(curl -sf "$DASHBOARD/api/status/$PRINTER_ID" 2>/dev/null | python3 -c "import json,sys; print(json.load(sys.stdin).get('status',''))" 2>/dev/null) || STATUS=""
    if [ "$STATUS" = "ok" ] || [ "$STATUS" = "error" ]; then
        green "  ✓ Print status updated ($STATUS)"
        ((PASS++))
    else
        yellow "  ⚠ Print status not yet updated (status: $STATUS)"
        ((SKIP++))
    fi
fi

# 1.13 Cron is installed
CRON_LINES=$(docker exec "$CONTAINER" crontab -l 2>/dev/null | grep -c "auto-print" || echo "0")
if [ "$CRON_LINES" -ge 1 ]; then
    green "  ✓ Cron schedule active ($CRON_LINES job(s))"
    ((PASS++))
else
    red "  ✗ No cron jobs found"
    ((FAIL++))
fi

# 1.14 Presets generated
PRESET_COUNT=$(docker exec "$CONTAINER" ls /app/presets/*.png 2>/dev/null | wc -l || echo "0")
if [ "$PRESET_COUNT" -ge 5 ]; then
    green "  ✓ Preset images generated ($PRESET_COUNT)"
    ((PASS++))
else
    red "  ✗ Expected 5+ presets, found $PRESET_COUNT"
    ((FAIL++))
fi

# 1.15 CSV export
CSV_CODE=$(curl -sf -o /dev/null -w "%{http_code}" "$DASHBOARD/api/history.csv" 2>/dev/null) || CSV_CODE="000"
if [ "$CSV_CODE" = "200" ]; then
    green "  ✓ CSV export works"
    ((PASS++))
else
    red "  ✗ CSV export failed (HTTP $CSV_CODE)"
    ((FAIL++))
fi

echo ""

###############################################################################
# TEST 2: Security Fixes
###############################################################################
bold "━━━ Test 2: Security ━━━"

# 2.1 CSRF — cross-origin POST should be rejected
CSRF_CODE=$(curl -sf -o /dev/null -w "%{http_code}" -X POST \
    -H "Origin: http://evil.com" -H "Host: localhost:8631" \
    -H "Content-Type: application/json" \
    -d '{"ip":"1.2.3.4"}' \
    "$DASHBOARD/api/printers/add" 2>/dev/null) || CSRF_CODE="000"
if [ "$CSRF_CODE" = "403" ]; then
    green "  ✓ CSRF: cross-origin POST blocked (403)"
    ((PASS++))
else
    red "  ✗ CSRF: expected 403, got $CSRF_CODE"
    ((FAIL++))
fi

# 2.2 Same-origin POST should work
SAME_CODE=$(curl -sf -o /dev/null -w "%{http_code}" -X POST \
    -H "Origin: http://localhost:8631" -H "Host: localhost:8631" \
    -H "Content-Type: application/json" \
    -d '{"webhook_url":""}' \
    "$DASHBOARD/api/webhook" 2>/dev/null) || SAME_CODE="000"
if [ "$SAME_CODE" = "200" ]; then
    green "  ✓ CSRF: same-origin POST allowed (200)"
    ((PASS++))
else
    red "  ✗ CSRF: same-origin expected 200, got $SAME_CODE"
    ((FAIL++))
fi

# 2.3 Webhook SSRF — localhost blocked
SSRF_RESP=$(curl -sf -X POST \
    -H "Content-Type: application/json" \
    -d '{"webhook_url":"http://localhost:1234/evil"}' \
    "$DASHBOARD/api/webhook" 2>/dev/null)
if echo "$SSRF_RESP" | grep -qi "cannot\|blocked\|localhost"; then
    green "  ✓ SSRF: localhost webhook blocked"
    ((PASS++))
else
    red "  ✗ SSRF: localhost webhook was not blocked"
    ((FAIL++))
fi

# 2.4 Webhook SSRF — 127.0.0.1 blocked
SSRF_RESP2=$(curl -sf -X POST \
    -H "Content-Type: application/json" \
    -d '{"webhook_url":"http://127.0.0.1:1234"}' \
    "$DASHBOARD/api/webhook" 2>/dev/null)
if echo "$SSRF_RESP2" | grep -qi "cannot\|blocked\|localhost"; then
    green "  ✓ SSRF: 127.0.0.1 webhook blocked"
    ((PASS++))
else
    red "  ✗ SSRF: 127.0.0.1 webhook was not blocked"
    ((FAIL++))
fi

# 2.5 Webhook — valid URL accepted
VALID_RESP=$(curl -sf -X POST \
    -H "Content-Type: application/json" \
    -d '{"webhook_url":"https://hooks.slack.com/test"}' \
    "$DASHBOARD/api/webhook" 2>/dev/null)
if echo "$VALID_RESP" | python3 -c "import json,sys; assert json.load(sys.stdin).get('ok')" 2>/dev/null; then
    green "  ✓ Webhook: valid URL accepted"
    ((PASS++))
else
    red "  ✗ Webhook: valid URL rejected"
    ((FAIL++))
fi

# 2.6 CSP header present
CSP=$(curl -sf -I "$DASHBOARD/" 2>/dev/null | grep -i "content-security-policy") || CSP=""
if [ -n "$CSP" ]; then
    green "  ✓ CSP header present"
    ((PASS++))
else
    red "  ✗ CSP header missing"
    ((FAIL++))
fi

# Clean up test webhook
curl -sf -X POST -H "Content-Type: application/json" \
    -d '{"webhook_url":""}' "$DASHBOARD/api/webhook" >/dev/null 2>&1

echo ""

###############################################################################
# TEST 3: Printer Management
###############################################################################
bold "━━━ Test 3: Printer Management ━━━"

# 3.1 Add a second printer (fake IP)
ADD_RESP=$(curl -sf -X POST \
    -H "Content-Type: application/json" \
    -d '{"ip":"10.99.99.99","name":"Test Fake Printer","connection":"ipp"}' \
    "$DASHBOARD/api/printers/add" 2>/dev/null)
FAKE_ID=$(echo "$ADD_RESP" | python3 -c "import json,sys; print(json.load(sys.stdin).get('printer',{}).get('id',''))" 2>/dev/null) || FAKE_ID=""
if [ -n "$FAKE_ID" ]; then
    green "  ✓ Add printer: fake printer added ($FAKE_ID)"
    ((PASS++))
else
    red "  ✗ Add printer failed"
    ((FAIL++))
fi

# 3.2 Duplicate IP rejected
DUP_RESP=$(curl -sf -X POST \
    -H "Content-Type: application/json" \
    -d '{"ip":"10.99.99.99","name":"Duplicate"}' \
    "$DASHBOARD/api/printers/add" 2>/dev/null)
if echo "$DUP_RESP" | grep -qi "already exists"; then
    green "  ✓ Duplicate IP rejected"
    ((PASS++))
else
    red "  ✗ Duplicate IP was not rejected"
    ((FAIL++))
fi

# 3.3 Update printer name
if [ -n "$FAKE_ID" ]; then
    UPD_RESP=$(curl -sf -X POST \
        -H "Content-Type: application/json" \
        -d "{\"id\":\"$FAKE_ID\",\"name\":\"Renamed Printer\"}" \
        "$DASHBOARD/api/printers/update" 2>/dev/null)
    if echo "$UPD_RESP" | python3 -c "import json,sys; assert json.load(sys.stdin).get('ok')" 2>/dev/null; then
        green "  ✓ Rename printer"
        ((PASS++))
    else
        red "  ✗ Rename failed"
        ((FAIL++))
    fi
fi

# 3.4 Toggle schedule (pause)
if [ -n "$FAKE_ID" ]; then
    TOG_RESP=$(curl -sf -X POST "$DASHBOARD/api/toggle-schedule/$FAKE_ID" 2>/dev/null)
    if echo "$TOG_RESP" | python3 -c "import json,sys; assert json.load(sys.stdin).get('paused')==True" 2>/dev/null; then
        green "  ✓ Pause schedule"
        ((PASS++))
    else
        red "  ✗ Pause failed"
        ((FAIL++))
    fi

    # 3.5 Toggle schedule (resume)
    TOG_RESP2=$(curl -sf -X POST "$DASHBOARD/api/toggle-schedule/$FAKE_ID" 2>/dev/null)
    if echo "$TOG_RESP2" | python3 -c "import json,sys; assert json.load(sys.stdin).get('paused')==False" 2>/dev/null; then
        green "  ✓ Resume schedule"
        ((PASS++))
    else
        red "  ✗ Resume failed"
        ((FAIL++))
    fi
fi

# 3.6 Remove fake printer
if [ -n "$FAKE_ID" ]; then
    REM_RESP=$(curl -sf -X POST \
        -H "Content-Type: application/json" \
        -d "{\"id\":\"$FAKE_ID\"}" \
        "$DASHBOARD/api/printers/remove" 2>/dev/null)
    if echo "$REM_RESP" | python3 -c "import json,sys; assert json.load(sys.stdin).get('ok')" 2>/dev/null; then
        green "  ✓ Remove printer"
        ((PASS++))
    else
        red "  ✗ Remove failed"
        ((FAIL++))
    fi
fi

# 3.7 Invalid IP rejected
BAD_IP_RESP=$(curl -sf -X POST \
    -H "Content-Type: application/json" \
    -d '{"ip":"!!!invalid!!!"}' \
    "$DASHBOARD/api/printers/add" 2>/dev/null)
BAD_IP_CODE=$(curl -sf -o /dev/null -w "%{http_code}" -X POST \
    -H "Content-Type: application/json" \
    -d '{"ip":"!!!invalid!!!"}' \
    "$DASHBOARD/api/printers/add" 2>/dev/null) || BAD_IP_CODE="000"
if [ "$BAD_IP_CODE" = "400" ]; then
    green "  ✓ Invalid IP rejected (400)"
    ((PASS++))
else
    red "  ✗ Invalid IP: expected 400, got $BAD_IP_CODE"
    ((FAIL++))
fi

echo ""

###############################################################################
# TEST 4: Data Persistence (restart)
###############################################################################
bold "━━━ Test 4: Persistence ━━━"

# Count printers before restart
PRE_COUNT=$(curl -sf "$DASHBOARD/api/printers" 2>/dev/null | python3 -c "import json,sys; print(len(json.load(sys.stdin).get('printers',[])))" 2>/dev/null) || PRE_COUNT=0

echo "  Restarting container..."
docker restart "$CONTAINER" >/dev/null 2>&1
sleep 8

# Wait for dashboard
for i in $(seq 1 20); do
    curl -sf "$DASHBOARD/" >/dev/null 2>&1 && break
    sleep 1
done

# 4.1 Dashboard loads after restart
check_http "Dashboard loads after restart" "$DASHBOARD/"

# 4.2 Printer config preserved
POST_COUNT=$(curl -sf "$DASHBOARD/api/printers" 2>/dev/null | python3 -c "import json,sys; print(len(json.load(sys.stdin).get('printers',[])))" 2>/dev/null) || POST_COUNT=0
if [ "$POST_COUNT" = "$PRE_COUNT" ] && [ "$POST_COUNT" -ge 1 ]; then
    green "  ✓ Printer config preserved ($POST_COUNT printer(s))"
    ((PASS++))
else
    red "  ✗ Printer count changed: $PRE_COUNT → $POST_COUNT"
    ((FAIL++))
fi

# 4.3 Cron restored after restart
CRON_AFTER=$(docker exec "$CONTAINER" crontab -l 2>/dev/null | grep -c "auto-print" || echo "0")
if [ "$CRON_AFTER" -ge 1 ]; then
    green "  ✓ Cron schedules restored ($CRON_AFTER job(s))"
    ((PASS++))
else
    red "  ✗ Cron not restored after restart"
    ((FAIL++))
fi

# 4.4 CUPS config persisted
CUPS_LINK=$(docker exec "$CONTAINER" readlink /etc/cups 2>/dev/null) || CUPS_LINK=""
if [ "$CUPS_LINK" = "/data/cups" ]; then
    green "  ✓ CUPS config symlinked to /data/cups"
    ((PASS++))
else
    red "  ✗ CUPS not symlinked (got: $CUPS_LINK)"
    ((FAIL++))
fi

# 4.5 Logs directory exists
check "Log files exist" docker exec "$CONTAINER" test -d /data/logs

echo ""

###############################################################################
# TEST 5: Edge Cases
###############################################################################
bold "━━━ Test 5: Edge Cases ━━━"

# 5.1 Start with no PRINTER_IP
echo "  Testing clean start with no PRINTER_IP..."
cleanup
rm -rf "$APPDATA" 2>/dev/null || true
docker run -d --name "$CONTAINER" \
    -p 8631:8631 -p 631:631 \
    -v "$APPDATA:/data" \
    "$IMAGE" >/dev/null 2>&1
sleep 8

for i in $(seq 1 15); do
    curl -sf "$DASHBOARD/" >/dev/null 2>&1 && break
    sleep 1
done

check_http "Dashboard loads with no PRINTER_IP" "$DASHBOARD/"

EMPTY_COUNT=$(curl -sf "$DASHBOARD/api/printers" 2>/dev/null | python3 -c "import json,sys; print(len(json.load(sys.stdin).get('printers',[])))" 2>/dev/null) || EMPTY_COUNT="-1"
if [ "$EMPTY_COUNT" = "0" ]; then
    green "  ✓ No printers auto-added (expected)"
    ((PASS++))
else
    red "  ✗ Expected 0 printers, found $EMPTY_COUNT"
    ((FAIL++))
fi

# 5.2 No errors in logs with empty config
check "No errors with empty config" bash -c "! docker logs $CONTAINER 2>&1 | grep -i 'ERROR'"

echo ""

###############################################################################
# TEST 6: Container Health
###############################################################################
bold "━━━ Test 6: Container Health ━━━"

# 6.1 Process check
PROC_COUNT=$(docker exec "$CONTAINER" ps aux 2>/dev/null | wc -l || echo "0")
if [ "$PROC_COUNT" -ge 3 ]; then
    green "  ✓ Processes running ($((PROC_COUNT - 1)) processes)"
    ((PASS++))
else
    red "  ✗ Too few processes ($PROC_COUNT)"
    ((FAIL++))
fi

# 6.2 CUPS running
check "CUPS daemon running" docker exec "$CONTAINER" lpstat -r

# 6.3 Cron running
check "Cron daemon running" docker exec "$CONTAINER" pgrep cron

# 6.4 Web UI running
check "WebUI process running" docker exec "$CONTAINER" pgrep -f webui.py

# 6.5 No zombie processes
ZOMBIES=$(docker exec "$CONTAINER" ps aux 2>/dev/null | grep -c "[Zz]ombie" || echo "0")
if [ "$ZOMBIES" = "0" ]; then
    green "  ✓ No zombie processes"
    ((PASS++))
else
    red "  ✗ Found $ZOMBIES zombie process(es)"
    ((FAIL++))
fi

echo ""

###############################################################################
# Cleanup & Results
###############################################################################
bold "━━━ Cleanup ━━━"
cleanup
echo "  Container stopped and removed."

# Restore the real test container
echo "  Restoring test container with PRINTER_IP=$PRINTER_IP..."
docker run -d --name "$CONTAINER" \
    -e PRINTER_IP="$PRINTER_IP" \
    -p 8631:8631 -p 631:631 \
    -v "$APPDATA:/data" \
    "$IMAGE" >/dev/null 2>&1

echo ""
bold "╔══════════════════════════════════════════════════════════╗"
bold "║                     RESULTS                             ║"
bold "╠══════════════════════════════════════════════════════════╣"
printf "║  " ; green "Passed:  $PASS"
printf "║  " ; red   "Failed:  $FAIL"
printf "║  " ; yellow "Skipped: $SKIP"
bold "╚══════════════════════════════════════════════════════════╝"
echo ""

if [ "$FAIL" -gt 0 ]; then
    red "Some tests failed. Review the output above."
    exit 1
else
    green "All tests passed!"
    exit 0
fi

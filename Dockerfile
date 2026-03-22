###############################################################################
# print-blockage-stopper
#
# All-in-one container that keeps any IPP-capable network printer's print head
# healthy by sending a small test print on a schedule. Supports multiple
# printers, mDNS discovery, custom test images, and a web dashboard.
#
# v1.4: Connection status, ink levels, retry logic, webhooks, CSV export
###############################################################################

FROM debian:bookworm-slim

LABEL maintainer="ahmed@abadr.net"
LABEL description="Automated maintenance prints for any network printer (IPP Everywhere compatible)"
LABEL org.opencontainers.image.source="https://github.com/ahmedbadr3/print-blockage-stopper"

# ── Install packages ─────────────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
        cups \
        cups-client \
        cups-filters \
        cups-ipp-utils \
        printer-driver-gutenprint \
        avahi-utils \
        cron \
        curl \
        ca-certificates \
        python3 \
        python3-pip \
        fonts-dejavu-core \
    && pip3 install --break-system-packages --no-cache-dir Pillow \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# ── CUPS configuration ───────────────────────────────────────
COPY <<'CUPSD_CONF' /etc/cups/cupsd.conf
LogLevel warn
MaxLogSize 1m
Listen 0.0.0.0:631
ServerAlias *
DefaultEncryption Never
WebInterface Yes

# Status pages — read-only, accessible from LAN
<Location />
  Order allow,deny
  Allow all
</Location>

# Job status — read-only from LAN
<Location /jobs>
  Order allow,deny
  Allow all
</Location>

# Printer status — read-only from LAN
<Location /printers>
  Order allow,deny
  Allow all
</Location>

# Admin — localhost only (container-internal)
<Location /admin>
  Order allow,deny
  Allow localhost
</Location>

# Admin config — localhost only
<Location /admin/conf>
  Order allow,deny
  Allow localhost
  AuthType Default
  Require user @SYSTEM
</Location>

<Policy default>
  JobPrivateAccess default
  JobPrivateValues default
  SubscriptionPrivateAccess default
  SubscriptionPrivateValues default

  <Limit Send-Document Send-URI Hold-Job Release-Job Restart-Job Purge-Jobs Set-Job-Attributes Create-Job-Subscription Renew-Subscription Cancel-Subscription Get-Notifications Reprocess-Job Cancel-Current-Job Suspend-Current-Job Resume-Job Cancel-My-Jobs Close-Job CUPS-Move-Job CUPS-Get-Document>
    Order deny,allow
    Allow localhost
  </Limit>

  <Limit CUPS-Add-Modify-Printer CUPS-Delete-Printer CUPS-Add-Modify-Class CUPS-Delete-Class CUPS-Set-Default>
    AuthType Default
    Require user @SYSTEM
    Order deny,allow
    Allow localhost
  </Limit>

  <Limit All>
    Order deny,allow
  </Limit>
</Policy>
CUPSD_CONF

# ── Create app directories ───────────────────────────────────
RUN mkdir -p /app /app/presets /data/logs /data/uploads

# ── Copy application files ───────────────────────────────────
COPY test-image/pro1100-test-print.png /app/test-print.png
COPY scripts/generate-presets.py /app/generate-presets.py
COPY scripts/entrypoint.sh /app/entrypoint.sh
COPY scripts/auto-print.sh /app/auto-print.sh
COPY scripts/webui.py /app/webui.py
COPY scripts/printer_probe.py /app/printer_probe.py

RUN chmod +x /app/entrypoint.sh /app/auto-print.sh

# ── Generate preset test images at build time ─────────────────
RUN python3 /app/generate-presets.py /app/presets

# ── Volumes ──────────────────────────────────────────────────
# /data persists logs, printer config, uploads, and CUPS state
VOLUME ["/data"]

# ── Environment variables (user-configurable) ────────────────
# PRINTER_IP:    (Optional) Auto-add this printer on first boot
# PRINTER_PORT:  Port for socket connection (default 9100)
# SCHEDULE:      Default cron expression for new printers
# PAPER_SIZE:    Default media size (A4, Letter, etc.)
# CONNECTION:    Default connection type: ipp or socket
# SKIP_HOURS:    Default skip-if-recently-printed window (hours)
# WEBHOOK_URL:   (Optional) URL for success/failure notifications
ENV PRINTER_IP="" \
    PRINTER_PORT="9100" \
    SCHEDULE="0 10 */3 * *" \
    PAPER_SIZE="A4" \
    CONNECTION="ipp" \
    SKIP_HOURS="72" \
    WEBHOOK_URL=""

# ── Expose ports ──────────────────────────────────────────────
EXPOSE 631
EXPOSE 8631

# ── Health check ─────────────────────────────────────────────
HEALTHCHECK --interval=60s --timeout=10s --retries=3 \
    CMD curl -sf http://localhost:8631/ || exit 1

ENTRYPOINT ["/app/entrypoint.sh"]

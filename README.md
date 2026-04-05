# Print Blockage Stopper

Automated maintenance prints for **any network printer** (IPP Everywhere compatible). Keeps pigment inkjet print heads healthy by sending small test prints on a schedule.

## Why?

Pigment-based inkjet printers — especially large-format models like Canon imagePROGRAF, Epson SureColor, and HP DesignJet — clog when they sit idle. The pigment settles in the nozzles, leading to expensive cleaning cycles, wasted ink, and sometimes permanent damage. This container prevents that by automatically printing a tiny test image every few days.

## What's New in v2.0.0

Version 2.0 introduces a completely redesigned dashboard built with React, TypeScript, and Tailwind CSS. The new frontend replaces the original Python-served UI with a modern single-page application featuring:

- **React + TypeScript + Vite** — fast, type-safe frontend with hot module replacement
- **New multi-page layout** — dedicated Dashboard, History, and Settings pages with sidebar navigation
- **Dark mode support** — system-aware theme with manual toggle
- **Redesigned printer cards** — cleaner layout with inline ink level bars, status indicators, and quick actions
- **Add/Edit printer dialogs** — modal-based printer management with form validation
- **Improved print history** — dedicated History page with filterable, sortable records and Recharts-powered visualizations
- **Centralized settings** — unified Settings page for global preferences and notification configuration
- **TanStack Query** — efficient data fetching with automatic background refresh
- **Responsive design** — fully mobile-friendly with collapsible sidebar

All existing backend functionality (CUPS integration, scheduling, notifications, auto-discovery) remains unchanged.

## Quick Start

```bash
docker run -d \
  --name print-blockage-stopper \
  -e PRINTER_IP=192.168.1.50 \
  -p 8631:8631 \
  -p 631:631 \
  -v /path/to/data:/data \
  abadrdh/print-blockage-stopper
```

Open **http://YOUR_HOST:8631** to access the dashboard. You can also skip `PRINTER_IP` and add printers from the dashboard.

### Unraid

Search for **print-blockage-stopper** in Community Applications and click Install.

## Features

- **Multi-printer support** — manage multiple printers from one container
- **Network auto-discovery** — find printers via mDNS/IPP
- **Smart scheduling** — skip if the printer was recently used
- **Preset test images** — optimised for 4, 6, 8, 11, and 12-colour printers
- **Custom image upload** — use your own test pattern (up to 5 MB)
- **Modern React dashboard** — redesigned UI with dark mode, sidebar navigation, and dedicated pages
- **Connection status** — real-time green/red indicators
- **Ink levels** — live ink level bars via IPP attributes
- **Auto-retry** — retries failed prints once after 30 seconds
- **Notifications** — webhook (Slack/Discord/ntfy), email (SMTP), and Home Assistant
- **CSV export** — download print history
- **Mobile-friendly** — responsive layout with collapsible sidebar
- **Unraid notifications** — alerts on print failures

## Configuration

All settings are optional. Printers can be added entirely from the dashboard.

| Variable | Default | Description |
|---|---|---|
| `PRINTER_IP` | *(empty)* | Auto-add this printer on first boot |
| `SCHEDULE` | `0 10 */3 * *` | Default cron schedule |
| `PAPER_SIZE` | `A4` | Default paper size (A4, Letter, A3, etc.) |
| `SKIP_HOURS` | `72` | Skip if printer was used within N hours |
| `CONNECTION` | `ipp` | Connection type: `ipp` or `socket` |
| `PRINTER_PORT` | `9100` | Socket port (only with `CONNECTION=socket`) |
| `WEBHOOK_URL` | *(empty)* | Webhook URL for notifications |

### Schedule Examples

| Expression | Meaning |
|---|---|
| `0 10 */3 * *` | Every 3 days at 10 AM |
| `0 10 */5 * *` | Every 5 days at 10 AM |
| `0 8 * * 1,4` | Monday and Thursday at 8 AM |
| `0 9 * * *` | Daily at 9 AM |

## Notifications

Configure notifications from the dashboard under **Settings > Notifications**. Three independent channels:

**Webhook** — Any URL that accepts JSON POST. Compatible with Slack, Discord, ntfy.

**Email** — SMTP configuration (server, port, from/to, optional auth). Works with Gmail, Outlook, Mailgun, or any SMTP provider.

**Home Assistant** — Creates persistent notifications via the HA REST API. Requires a long-lived access token (HA profile > Long-Lived Access Tokens > Create Token). Supports self-signed certificates.

Each channel has a **Test** button to verify your setup.

## Ports

| Port | Purpose |
|---|---|
| `8631` | Dashboard |
| `631` | CUPS web UI (advanced) |

## Volumes

| Path | Purpose |
|---|---|
| `/data` | Printer config, logs, uploads, CUPS state |

## How It Works

1. On startup, the container runs CUPS and registers your printers
2. A cron job triggers `auto-print.sh` on each printer's schedule
3. The script checks if the printer was recently used (smart skip)
4. If not, it sends a small test image via CUPS/IPP
5. Results are logged and notifications sent to enabled channels
6. The React dashboard (served on port 8631) provides controls and monitoring

## Tech Stack

**Backend:** CUPS, Python, Bash, cron
**Frontend:** React 18, TypeScript, Vite, Tailwind CSS, TanStack Query, Recharts, Lucide Icons
**Container:** Debian Bookworm (slim)

## Requirements

- Any network printer with IPP Everywhere support
- Printer powered on with paper loaded
- Network access from Docker host to printer

## Changelog

### v2.0.0
- Complete dashboard redesign with React, TypeScript, and Tailwind CSS
- New multi-page layout with sidebar navigation (Dashboard, History, Settings)
- Dark mode support with system-aware theme toggle
- Redesigned printer cards with inline ink levels and quick actions
- Modal-based Add/Edit printer dialogs with form validation
- Dedicated History page with filterable records and Recharts visualizations
- Centralized Settings page for global preferences and notifications
- TanStack Query for efficient data fetching with background refresh
- Fully responsive design with collapsible sidebar

### v1.5.1
- Print completion monitoring — polls CUPS job status for up to 3 minutes
- Detects stopped/held jobs (paper tray, jam, ink issues)
- Distinct notification events: completed, stopped, timeout, failed
- Input validation fixes and security hardening

### v1.5.0
- Email notifications (SMTP)
- Home Assistant integration
- Tabbed notifications UI
- Unified notification dispatcher

### v1.4.1
- Next scheduled print countdown
- Custom test image delete button
- Favicon and new app icon
- Security hardening (CSRF, XSS, SSRF, CSP)

### v1.4.0
- Inline printer rename
- Test Connection with auto-detect model
- Real-time connection status indicators
- Ink level bars via IPP
- Print retry logic
- Webhook notifications
- CSV export

### v1.3.0
- Multi-printer support
- Network printer auto-discovery
- Per-printer schedules and settings
- Preset test images
- Custom image upload
- Smart skip

### v1.0.0
- Initial release

## License

MIT

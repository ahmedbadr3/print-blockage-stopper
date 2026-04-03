# print-blockage-stopper

Automated maintenance prints for **any network printer** (IPP Everywhere compatible). Especially useful for large-format pigment printers like Canon imagePROGRAF, Epson SureColor, and HP DesignJet.

Pigment printers—especially wide-format models—clog when they sit idle. This container sends a tiny test print on a schedule to keep all ink channels flowing — saving you from expensive cleaning cycles and wasted ink.

## Features

- **Multi-printer support** — manage multiple printers from a single container
- **Auto-discovery** — find printers on your network via mDNS/IPP
- **Smart scheduling** — skip the maintenance print if the printer was recently used
- **Preset test images** — optimised for 4, 6, 8, 11, and 12-colour printers
- **Custom image upload** — use your own test pattern (up to 5 MB)
- **Web dashboard** — per-printer status, schedule controls, print history chart
- **Pause/resume** — toggle schedules per-printer from the dashboard
- **Connection status** — real-time green/red indicators per printer
- **Ink levels** — live ink level bars via IPP attributes
- **Auto-retry** — retries failed prints once after 30 seconds
- **Webhook notifications** — Slack, Discord, ntfy compatible alerts
- **Email notifications** — SMTP-based alerts on print success/failure
- **Home Assistant integration** — persistent notifications via HA REST API
- **CSV export** — download print history as CSV
- **Mobile-friendly** — responsive dashboard layout
- **Unraid notifications** — get alerts on print failures

## Quick start

```bash
docker run -d \
  --name print-blockage-stopper \
  -p 8631:8631 \
  -p 631:631 \
  -v /path/to/data:/data \
  abadrdh/print-blockage-stopper
```

Then open **http://YOUR_HOST:8631** and add your printers from the dashboard.

### With a printer pre-configured

```bash
docker run -d \
  --name print-blockage-stopper \
  -e PRINTER_IP=192.168.1.50 \
  -e SCHEDULE="0 10 */3 * *" \
  -e PAPER_SIZE=A4 \
  -p 8631:8631 \
  -p 631:631 \
  -v /mnt/user/appdata/print-blockage-stopper:/data \
  abadrdh/print-blockage-stopper
```

### Unraid users

Search for **print-blockage-stopper** in Community Applications and click Install.

## Configuration

All settings are optional — printers can be added entirely from the dashboard.

| Variable | Default | Description |
|---|---|---|
| `PRINTER_IP` | *(empty)* | Auto-add this printer on first boot |
| `SCHEDULE` | `0 10 */3 * *` | Default cron schedule for new printers |
| `PAPER_SIZE` | `A4` | Default paper size (A4, Letter, A3, etc.) |
| `SKIP_HOURS` | `72` | Skip print if printer was used within this many hours |
| `CONNECTION` | `ipp` | Connection type: `ipp` or `socket` |
| `PRINTER_PORT` | `9100` | Socket port (only with `CONNECTION=socket`) |
| `WEBHOOK_URL` | *(empty)* | URL for success/failure notifications (Slack, Discord, ntfy) |

### Schedule examples

| Expression | Meaning |
|---|---|
| `0 10 */3 * *` | Every 3 days at 10:00 AM |
| `0 10 */5 * *` | Every 5 days at 10:00 AM |
| `0 8 * * 1,4` | Monday and Thursday at 8:00 AM |
| `0 9 * * *` | Daily at 9:00 AM |

## Volumes

| Path | Purpose |
|---|---|
| `/data` | Persistent storage: printer config, logs, uploads, CUPS state |

## Ports

| Port | Purpose |
|---|---|
| `8631` | Dashboard (status, controls, history) |
| `631` | CUPS web UI (advanced) |

## Dashboard

The dashboard at port 8631 lets you:
- Add and remove printers (manual IP or auto-discover)
- View per-printer status and print history
- Pause/resume schedules per printer
- Adjust skip-hours per printer
- Select preset test images (4/6/8/11/12-colour)
- Upload custom test images
- Trigger immediate prints
- Test printer connection and auto-detect model
- View real-time ink levels
- Rename printers inline
- Configure notifications (webhook, email, Home Assistant)
- Export print history as CSV

## Notifications

All notification channels are configured from the dashboard under the **Notifications** card. Each channel is independent — enable any combination.

**Webhook** — Enter any URL that accepts JSON POST requests. Compatible with Slack incoming webhooks, Discord webhooks, ntfy, and similar services.

**Email (SMTP)** — Configure your SMTP server details (server, port, from/to addresses, optional auth). Works with Gmail, Outlook, Mailgun, or any SMTP provider. TLS (STARTTLS) is enabled by default.

**Home Assistant** — Enter your HA instance URL and a long-lived access token. Creates a persistent notification in the HA sidebar on each print event. Supports self-signed certificates (toggle "Verify SSL" off). To create a token: HA profile → Long-Lived Access Tokens → Create Token.

Each tab has a **Test** button to verify your config before relying on it.

## Requirements

- Any network printer with IPP Everywhere support (standard on modern printers)
- Printer powered on with paper loaded
- Network access from the Docker host to the printer
- Unraid, or any Docker-compatible host

## License

MIT

# print-blockage-stopper

Automated maintenance prints for **any network printer** (IPP Everywhere compatible). Especially useful for large-format pigment printers like Canon imagePROGRAF, Epson SureColor, and HP DesignJet.

Pigment printers—especially wide-format models—clog when they sit idle. This container sends a tiny test print on a schedule to keep all ink channels flowing — saving you from expensive cleaning cycles and wasted ink.

## What it does

- Sends a minimal-ink test image (~4×2 inches on A4) that exercises a wide colour gamut plus greyscale—suitable for any printer
- Runs on a configurable cron schedule (default: every 3 days)
- Includes a CUPS web UI and dashboard for monitoring and manual trigger
- Logs every print job with timestamps and status
- Uses IPP Everywhere (driverless) printing—works with any modern network printer

## Quick start

```bash
docker run -d \
  --name print-blockage-stopper \
  -e PRINTER_IP=192.168.1.50 \
  -e SCHEDULE="0 10 */3 * *" \
  -e PAPER_SIZE=A4 \
  -p 631:631 \
  -v /mnt/user/appdata/print-blockage-stopper:/data \
  abadrdh/print-blockage-stopper
```

### Unraid users

Search for **print-blockage-stopper** in Community Applications and click Install. Fill in your printer's IP address and you're done.

## Configuration

| Variable | Default | Description |
|---|---|---|
| `PRINTER_IP` | *(required)* | IP address of your printer |
| `SCHEDULE` | `0 10 */3 * *` | Cron expression — default is every 3 days at 10 AM |
| `PAPER_SIZE` | `A4` | Paper size loaded in printer (A4, Letter, A3, etc.) |
| `CONNECTION` | `ipp` | Connection type: `ipp` or `socket` |
| `PRINTER_PORT` | `9100` | Socket port (only used with `CONNECTION=socket`) |

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
| `/data` | Persistent logs and CUPS config |

## Ports

| Port | Purpose |
|---|---|
| `631` | CUPS web UI |

## Logs

Print history is logged at `/data/logs/auto-print.log` inside the container (or wherever you map `/data` on the host).

## How the test image works

The test image is designed to use as little ink as possible while still firing every nozzle:

- Thin lines per ink channel (not filled boxes)
- Tiny colour patches (~2.4mm squares)
- Narrow greyscale step wedge
- Single-pixel dotted rows

## Requirements

- Any network printer with IPP Everywhere support (standard on modern printers)
- Printer powered on with paper loaded
- Network access from the Docker host to the printer
- Unraid, or any Docker-compatible host

## License

MIT

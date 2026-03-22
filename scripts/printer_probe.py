#!/usr/bin/env python3
"""
Probe a printer via IPP to get model name, ink levels, and connection status.
Used by the web UI for auto-detection and status indicators.

Usage:
  python3 printer_probe.py <ip> [connection] [port]

Returns JSON to stdout:
  {"reachable": true, "model": "Canon PRO-1100", "ink_levels": [...], "error": null}
"""

import json
import re
import socket
import subprocess
import sys


def probe_printer(ip, connection="ipp", port=9100):
    result = {
        "reachable": False,
        "model": None,
        "ink_levels": [],
        "error": None,
    }

    # Step 1: TCP connectivity check
    try:
        check_port = 631 if connection == "ipp" else int(port)
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5)
        sock.connect((ip, check_port))
        sock.close()
        result["reachable"] = True
    except (socket.timeout, socket.error, OSError) as e:
        result["error"] = f"Cannot reach {ip}:{check_port} — {e}"
        return result

    # Step 2: Query IPP attributes via ipptool
    ipp_uri = f"ipp://{ip}/ipp/print"
    try:
        proc = subprocess.run(
            ["ipptool", "-tv", ipp_uri, "-d", "URI=" + ipp_uri, "/dev/stdin"],
            input='{\n  OPERATION Get-Printer-Attributes\n  GROUP operation-attributes-tag\n  ATTR charset attributes-charset utf-8\n  ATTR naturalLanguage attributes-natural-language en\n  ATTR uri printer-uri $URI\n  ATTR keyword requested-attributes printer-make-and-model,marker-names,marker-levels,marker-colors,printer-state\n}\n',
            capture_output=True, text=True, timeout=10
        )
        output = proc.stdout + proc.stderr
    except (subprocess.TimeoutExpired, FileNotFoundError):
        # ipptool not available or timeout — try alternative
        output = ""

    # Parse model name
    model_match = re.search(r'printer-make-and-model\s*(?:\(.*?\))?\s*=\s*(.+)', output)
    if model_match:
        result["model"] = model_match.group(1).strip().strip('"')

    # Parse ink levels
    names_match = re.search(r'marker-names\s*(?:\(.*?\))?\s*=\s*(.+)', output)
    levels_match = re.search(r'marker-levels\s*(?:\(.*?\))?\s*=\s*(.+)', output)
    colors_match = re.search(r'marker-colors\s*(?:\(.*?\))?\s*=\s*(.+)', output)

    if names_match and levels_match:
        names = [n.strip().strip('"') for n in names_match.group(1).split(",")]
        levels = [l.strip() for l in levels_match.group(1).split(",")]
        colors = []
        if colors_match:
            colors = [c.strip().strip('"') for c in colors_match.group(1).split(",")]

        for i, name in enumerate(names):
            level = int(levels[i]) if i < len(levels) and levels[i].isdigit() else -1
            color = colors[i] if i < len(colors) else ""
            result["ink_levels"].append({
                "name": name,
                "level": level,
                "color": color,
            })

    # Fallback: try CUPS lpstat if ipptool didn't get model
    if not result["model"]:
        try:
            proc = subprocess.run(
                ["lpinfo", "-v"], capture_output=True, text=True, timeout=5
            )
            for line in proc.stdout.splitlines():
                if ip in line:
                    # Try to extract name from URI
                    parts = line.split()
                    if len(parts) >= 2:
                        result["model"] = f"Printer at {ip}"
                    break
        except Exception:
            pass

    return result


if __name__ == "__main__":
    ip = sys.argv[1] if len(sys.argv) > 1 else ""
    conn = sys.argv[2] if len(sys.argv) > 2 else "ipp"
    port = sys.argv[3] if len(sys.argv) > 3 else "9100"

    if not ip:
        print(json.dumps({"error": "Usage: printer_probe.py <ip> [connection] [port]"}))
        sys.exit(1)

    info = probe_printer(ip, conn, int(port))
    print(json.dumps(info))

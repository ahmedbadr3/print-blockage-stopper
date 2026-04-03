#!/usr/bin/env python3
"""Unified notification dispatcher for print-blockage-stopper.

Usage:
    python3 notify.py --event print_ok --printer "Name" --printer-id "id" --message "text"

Reads notification config from /data/printers.json and dispatches to all
enabled channels: webhook, email (SMTP), Home Assistant.
"""

import argparse
import json
import ipaddress
import os
import smtplib
import ssl
import sys
from datetime import datetime, timezone
from email.mime.text import MIMEText
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from urllib.error import URLError

DATA_FILE = "/data/printers.json"


def load_config(config_path=None):
    """Load global notification config from printers.json or a custom path."""
    try:
        path = config_path or DATA_FILE
        with open(path, "r") as f:
            data = json.load(f)
        return data.get("global", {})
    except Exception:
        return {}


def validate_url(url):
    """Validate a URL is safe (not localhost/link-local/metadata). Returns error string or None."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return "URL must be http or https"
    hostname = parsed.hostname or ""
    if hostname in ("localhost", "127.0.0.1", "0.0.0.0", "::1", "[::1]"):
        return "URL cannot point to localhost"
    try:
        addr = ipaddress.ip_address(hostname)
        if addr.is_loopback or addr.is_link_local:
            return "URL cannot point to loopback/link-local"
        if str(addr) == "169.254.169.254":
            return "URL cannot point to metadata endpoint"
    except ValueError:
        pass
    return None


def send_webhook(config, payload):
    """Send webhook notification via HTTP POST."""
    url = config.get("webhook_url", "").strip()
    if not url:
        return
    err = validate_url(url)
    if err:
        log(f"Webhook skipped: {err}")
        return
    try:
        body = json.dumps(payload).encode("utf-8")
        req = Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
        urlopen(req, timeout=10)
    except Exception as e:
        log(f"Webhook failed: {e}")


def send_email(config, subject, body_text, force=False):
    """Send email notification via SMTP."""
    email_cfg = config.get("email", {})
    if not force and not email_cfg.get("enabled"):
        return
    server = email_cfg.get("smtp_server", "").strip()
    port = int(email_cfg.get("smtp_port", 587))
    from_addr = email_cfg.get("smtp_from", "").strip()
    to_addr = email_cfg.get("smtp_to", "").strip()
    username = email_cfg.get("smtp_username", "").strip()
    password = email_cfg.get("smtp_password", "")
    use_tls = email_cfg.get("smtp_tls", True)

    if not server or not from_addr or not to_addr:
        log("Email skipped: missing server, from, or to address")
        return

    try:
        msg = MIMEText(body_text)
        msg["Subject"] = subject
        msg["From"] = from_addr
        msg["To"] = to_addr

        if use_tls:
            smtp = smtplib.SMTP(server, port, timeout=10)
            smtp.starttls()
        else:
            smtp = smtplib.SMTP(server, port, timeout=10)

        if username and password:
            smtp.login(username, password)
        smtp.sendmail(from_addr, [to_addr], msg.as_string())
        smtp.quit()
    except Exception as e:
        log(f"Email failed: {e}")


def send_homeassistant(config, title, message, force=False):
    """Send Home Assistant persistent notification."""
    ha_cfg = config.get("homeassistant", {})
    if not force and not ha_cfg.get("enabled"):
        return
    ha_url = ha_cfg.get("ha_url", "").strip().rstrip("/")
    ha_token = ha_cfg.get("ha_token", "").strip()
    verify_ssl = ha_cfg.get("ha_verify_ssl", True)

    if not ha_url or not ha_token:
        log("Home Assistant skipped: missing URL or token")
        return

    err = validate_url(ha_url)
    if err:
        log(f"Home Assistant skipped: {err}")
        return

    endpoint = f"{ha_url}/api/services/persistent_notification/create"
    payload = json.dumps({"title": title, "message": message}).encode("utf-8")
    req = Request(
        endpoint,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {ha_token}",
        },
        method="POST",
    )

    try:
        ctx = None
        if not verify_ssl:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
        urlopen(req, timeout=10, context=ctx)
    except Exception as e:
        log(f"Home Assistant failed: {e}")


def log(msg):
    """Log to stderr (captured by Docker logs)."""
    print(f"[notify] {msg}", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description="Send notifications for print events")
    parser.add_argument("--event", required=True, choices=["print_ok", "print_failed", "test"])
    parser.add_argument("--printer", default="")
    parser.add_argument("--printer-id", default="")
    parser.add_argument("--message", default="")
    parser.add_argument("--channel", default="all", choices=["all", "webhook", "email", "homeassistant"],
                        help="Send to a specific channel only (for testing)")
    parser.add_argument("--config", default=None,
                        help="Path to a JSON config file (overrides /data/printers.json)")
    args = parser.parse_args()

    config = load_config(args.config)
    now = datetime.now(timezone.utc).isoformat()

    # Build payloads
    webhook_payload = {
        "event": args.event,
        "printer": args.printer,
        "printer_id": args.printer_id,
        "message": args.message,
        "timestamp": now,
    }

    if args.event == "print_ok":
        subject = f"Print OK — {args.printer}"
        body = f"Print job submitted successfully for {args.printer}.\n\nTimestamp: {now}"
        ha_title = "Print Blockage Stopper"
        ha_message = f"Print OK: {args.printer} — {args.message}"
    elif args.event == "print_failed":
        subject = f"Print FAILED — {args.printer}"
        body = f"Print job failed for {args.printer}.\n\n{args.message}\n\nTimestamp: {now}"
        ha_title = "Print Blockage Stopper"
        ha_message = f"Print FAILED: {args.printer} — {args.message}"
    else:  # test
        subject = "Print Blockage Stopper — Test Notification"
        body = "This is a test notification from Print Blockage Stopper."
        ha_title = "Print Blockage Stopper"
        ha_message = "This is a test notification."
        webhook_payload["event"] = "test"
        webhook_payload["message"] = "Test notification"

    # Dispatch to channels (force=True for test events to bypass enabled check)
    channel = args.channel
    force = args.event == "test"
    if channel in ("all", "webhook"):
        send_webhook(config, webhook_payload)
    if channel in ("all", "email"):
        send_email(config, subject, body, force=force)
    if channel in ("all", "homeassistant"):
        send_homeassistant(config, ha_title, ha_message, force=force)


if __name__ == "__main__":
    main()

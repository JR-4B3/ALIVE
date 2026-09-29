#!/usr/bin/env python3
"""Record the existing ALIVE API's device-online signal during a battery run.

This does not change the ESP32 firmware or count its own requests as device polls.
"""

import argparse
import csv
import ipaddress
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def fetch_online(url: str, token: str, timeout: float) -> bool:
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(url, headers=headers)
    with urlopen(request, timeout=timeout) as response:
        state = json.load(response)
    if not isinstance(state, dict) or type(state.get("deviceOnline")) is not bool:
        raise ValueError("API response has no boolean deviceOnline field")
    return state["deviceOnline"]


def ping_online(host: str) -> bool:
    result = subprocess.run(["ping", "-n", "-c", "1", "-W", "1", host],
                            capture_output=True, text=True, timeout=3)
    if result.returncode == 0:
        return True
    if result.returncode == 1:
        return False
    raise OSError((result.stderr or result.stdout).strip()[:200] or
                  f"ping failed with exit code {result.returncode}")


def write_summary(path: Path, summary: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(summary, indent=2) + "\n")
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    target = parser.add_mutually_exclusive_group()
    target.add_argument("--api-url", default=os.environ.get("ALIVE_API_URL"),
                        help="API base URL; may also be set as ALIVE_API_URL")
    target.add_argument("--host", help="ESP32 IP address to ping directly (no API token needed)")
    parser.add_argument("--output", type=Path, default=Path("battery-run"),
                        help="output prefix for .csv and .json files")
    parser.add_argument("--interval", type=float, default=2.0,
                        help="seconds between checks (default: 2)")
    parser.add_argument("--offline-seconds", type=float, default=120.0,
                        help="sustained offline period to flag (default: 120)")
    args = parser.parse_args()
    if args.host:
        try:
            ipaddress.ip_address(args.host)
        except ValueError:
            parser.error("--host must be an IP address")
    elif not args.api_url or not args.api_url.startswith(("http://", "https://")):
        parser.error("set --host, --api-url, or ALIVE_API_URL")
    if args.interval <= 0 or args.offline_seconds <= 0:
        parser.error("interval and offline-seconds must be positive")

    endpoint = args.api_url.rstrip("/") + "/api/emitter/main/current" if not args.host else None
    token = os.environ.get("ALIVE_WEB_TOKEN", "")
    csv_path = args.output.with_suffix(".csv")
    json_path = args.output.with_suffix(".json")
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    if csv_path.exists() or json_path.exists():
        parser.error("output files already exist; choose a new --output for this run")

    summary = {
        "status": "waiting_for_first_online",
        "monitor_started_utc": utc_now(),
        "first_online_utc": None,
        "last_online_utc": None,
        "first_offline_utc": None,
        "offline_confirmed_utc": None,
        "elapsed_last_online_seconds": None,
        "elapsed_first_offline_seconds": None,
        "recovery_count": 0,
        "method": "ping" if args.host else "api_device_online",
        "target": args.host if args.host else args.api_url,
        "note": "Offline is not proof of battery depletion; verify the hardware and network.",
    }
    started_mono = time.monotonic()
    first_online_mono = None
    offline_mono = None
    last_summary_write = 0.0
    write_summary(json_path, summary)
    print(f"Monitor armed: {csv_path} and {json_path}", flush=True)

    with csv_path.open("x", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["utc", "monitor_elapsed_seconds", "device_online", "error"])
        stream.flush()
        try:
            while True:
                sampled_at = utc_now()
                now = time.monotonic()
                error = ""
                online = None
                try:
                    online = (ping_online(args.host) if args.host else
                              fetch_online(endpoint, token, min(10.0, args.interval + 3.0)))
                except (OSError, ValueError) as exc:
                    error = f"{type(exc).__name__}: {exc}"
                    if isinstance(exc, HTTPError) and exc.code in (401, 403):
                        print("API authorization failed; set ALIVE_WEB_TOKEN.", file=sys.stderr)
                        return 2
                now = time.monotonic()
                writer.writerow([sampled_at, f"{now - started_mono:.3f}",
                                 "" if online is None else str(online).lower(), error])
                stream.flush()

                changed = False
                if online is True:
                    if first_online_mono is None:
                        first_online_mono = now
                        summary["first_online_utc"] = sampled_at
                        print(f"Device first online: {sampled_at}", flush=True)
                        changed = True
                    elif offline_mono is not None:
                        summary["recovery_count"] += 1
                        print(f"Device recovered: {sampled_at}", flush=True)
                        changed = True
                    offline_mono = None
                    summary["status"] = "online"
                    summary["last_online_utc"] = sampled_at
                    summary["first_offline_utc"] = None
                    summary["offline_confirmed_utc"] = None
                    summary["elapsed_last_online_seconds"] = round(now - first_online_mono, 3)
                    summary["elapsed_first_offline_seconds"] = None
                elif online is False and first_online_mono is not None:
                    if offline_mono is None:
                        offline_mono = now
                        summary["first_offline_utc"] = sampled_at
                        summary["elapsed_first_offline_seconds"] = round(now - first_online_mono, 3)
                        summary["status"] = "offline_pending"
                        print(f"Device went offline: {sampled_at}", flush=True)
                        changed = True
                    if (now - offline_mono >= args.offline_seconds and
                            summary["status"] != "offline_unverified"):
                        summary["status"] = "offline_unverified"
                        summary["offline_confirmed_utc"] = sampled_at
                        print(f"Sustained offline: {sampled_at}; check battery and Wi-Fi", flush=True)
                        changed = True
                elif online is None:
                    # A failed API check cannot establish when the device vanished.
                    offline_mono = None
                    summary["first_offline_utc"] = None
                    summary["offline_confirmed_utc"] = None
                    summary["elapsed_first_offline_seconds"] = None
                    if summary["status"] != "probe_failed":
                        summary["status"] = "probe_failed"
                        print(f"Monitor check failed: {error}", file=sys.stderr, flush=True)
                        changed = True
                if changed or now - last_summary_write >= 60:
                    write_summary(json_path, summary)
                    last_summary_write = now
                time.sleep(args.interval)
        except KeyboardInterrupt:
            summary["monitor_stopped_utc"] = utc_now()
            write_summary(json_path, summary)
            print("Monitor stopped", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Print how long each board has run on its battery, from the API's poll log.

Run on the API server: sudo python3 battery_runtime.py [log folder]

A board's battery run starts at its last power-on (reset reason 1), found from
that row's uptime. Later software restarts after Wi-Fi outages do not end it.
"""
import csv
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

folder = Path(sys.argv[1] if len(sys.argv) > 1 else "/var/lib/alive/device-polls")
boards: dict[str, dict[str, float]] = {}
for path in sorted(folder.glob("*.csv")):
    with path.open(encoding="utf-8") as file:
        for row in csv.DictReader(file):
            seen = datetime.strptime(row["received_utc"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()
            board = boards.setdefault(row["board"], {})
            if row["reset_reason"] == "1":
                board["start"] = seen - int(row["uptime_ms"]) / 1000
            board["last"] = seen

latest = max((b["last"] for b in boards.values()), default=0)
for mac, board in sorted(boards.items()):
    if "start" not in board:
        print(f"{mac}  no power-on in the log")
        continue
    hours, rest = divmod(round(board["last"] - board["start"]), 3600)
    # A board that went quiet while others kept polling has stopped; if all went
    # quiet together, suspect Wi-Fi or the API first.
    if time.time() - board["last"] < 60:
        status = "still running"
    elif latest - board["last"] > 60:
        status = "STOPPED (others kept polling)"
    else:
        status = "stopped last; dead battery, or check Wi-Fi if it was the only one running"
    started = time.strftime("%Y-%m-%d %H:%M", time.localtime(board["start"]))
    print(f"{mac}  on battery since {started}  ran {hours} h {rest // 60:02d} min  {status}")

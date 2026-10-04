#!/bin/sh
# Install or update the ALIVE API service. Run from a checkout: sudo deploy/install.sh
set -eu
repo=$(cd "$(dirname "$0")/.." && pwd)

install -d -m 755 /opt/alive
install -m 644 "$repo/emitter.py" "$repo/reply_engine.py" "$repo/simple_qr.py" /opt/alive/
install -d -m 700 /etc/alive
if [ ! -e /etc/alive/api.env ]; then
  install -m 600 "$repo/deploy/api.env.example" /etc/alive/api.env
  echo "Created /etc/alive/api.env from the example. Fill it in, then run this script again."
  exit 1
fi
install -m 644 "$repo/deploy/alive-api.service" /etc/systemd/system/alive-api.service
systemctl daemon-reload
systemctl enable alive-api.service
systemctl restart alive-api.service
systemctl --no-pager --lines=5 status alive-api.service
curl -fsS http://127.0.0.1:8765/healthz && echo

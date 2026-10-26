#!/bin/sh
# Install or update the ALIVE API service. Run from a checkout: sudo deploy/install.sh
set -eu
repo=$(cd "$(dirname "$0")/.." && pwd)

install -d -m 755 /opt/alive
install -m 644 "$repo/emitter.py" "$repo/reply_engine.py" "$repo/signals.py" "$repo/simple_qr.py" /opt/alive/
install -d -m 700 /etc/alive
if [ ! -e /etc/alive/api.env ]; then
  install -m 600 "$repo/deploy/api.env.example" /etc/alive/api.env
  echo "Created /etc/alive/api.env from the example. Fill it in, then run this script again."
  exit 1
fi
# Keep the operator token and OpenAI key readable by the user who ran sudo, so
# `python3 debug_host.py` on another computer can fetch them over SSH.
if [ -n "${SUDO_USER:-}" ]; then
  user_config=$(getent passwd "$SUDO_USER" | cut -d: -f6)/.config/alive
  install -d -m 700 -o "$SUDO_USER" "$user_config"
  for pair in ALIVE_WEB_TOKEN:operator-token OPENAI_API_KEY:openai-key; do
    sed -n "s/^${pair%%:*}=//p" /etc/alive/api.env |
      install -m 600 -o "$SUDO_USER" /dev/stdin "$user_config/${pair#*:}"
  done
fi
install -m 644 "$repo/deploy/alive-api.service" /etc/systemd/system/alive-api.service
systemctl daemon-reload
systemctl enable alive-api.service
systemctl restart alive-api.service
systemctl --no-pager --lines=5 status alive-api.service
curl -fsS http://127.0.0.1:8765/healthz && echo

#!/usr/bin/env bash
# Runs a 2.4 GHz Wi-Fi network for the ALIVE boards on this laptop and shares
# the laptop's internet connection (eduroam or a USB phone tether) with
# it. Boards on it poll the API on this laptop at 10.42.7.1:8765 directly.
# Needs systemd-networkd, which Ubuntu Server uses.
#
#   sudo ALIVE_HOTSPOT_PASSWORD='at least 8 characters' deploy/laptop-hotspot.sh enable
#       saves the password and runs the hotspot now and after every boot;
#       systemd restarts it 10 seconds after it fails
#   sudo deploy/laptop-hotspot.sh status
#   sudo deploy/laptop-hotspot.sh disable
#   sudo ALIVE_HOTSPOT_PASSWORD=... deploy/laptop-hotspot.sh start | stop
#       one-off, until the next reboot
#
# The hotspot is a second interface on the laptop's Wi-Fi card. If the laptop
# itself is on Wi-Fi, many cards can only send on that same channel, and the
# boards need 2.4 GHz. So limit the eduroam connection to 2.4 GHz, or use a
# USB Wi-Fi adapter for the hotspot (set ALIVE_HOTSPOT_WIFI to its interface
# name).
set -Eeuo pipefail
# Say where the script stopped instead of exiting silently.
trap 'echo "laptop-hotspot.sh stopped at line $LINENO (exit $?): $BASH_COMMAND" >&2' ERR

SSID=${ALIVE_HOTSPOT_SSID:-ALIVE-T480}
WIFI=${ALIVE_HOTSPOT_WIFI:-wlp3s0}
CHANNEL=${ALIVE_HOTSPOT_CHANNEL:-6}
COUNTRY=${ALIVE_HOTSPOT_COUNTRY:-DE}
AP=alivehs0
RUN=/run/alive-hotspot
NETWORK_FILE=/run/systemd/network/50-alive-hotspot.network
ENV_FILE=/etc/alive/hotspot.env
UNIT=/etc/systemd/system/alive-hotspot.service

[[ $EUID -eq 0 ]] || { echo "Run with sudo." >&2; exit 1; }

stop() {
  [[ -f $RUN/hostapd.pid ]] && kill "$(cat "$RUN/hostapd.pid")" 2>/dev/null || true
  iw dev "$AP" del 2>/dev/null || true
  rm -f "$NETWORK_FILE"
  rm -rf "$RUN"
  networkctl reload
  echo "Hotspot stopped."
}

status() {
  if [[ -f $RUN/hostapd.pid ]] && kill -0 "$(cat "$RUN/hostapd.pid")" 2>/dev/null; then
    echo "Hotspot $SSID is running on $AP."
    iw dev "$AP" info | grep -E 'channel|ssid' || true
    echo "Connected boards: $(iw dev "$AP" station dump | grep -c "^Station" || true)"
    networkctl status "$AP" --no-pager | sed -n '/Offered DHCP leases/,/^$/p'
  else
    echo "Hotspot is not running."
  fi
}

prepare() {
  : "${ALIVE_HOTSPOT_PASSWORD:?Set ALIVE_HOTSPOT_PASSWORD to the hotspot password from secrets.h, 8 to 63 characters}"
  if ! command -v hostapd >/dev/null || ! command -v iw >/dev/null; then
    apt-get install -y hostapd iw
    # Ubuntu enables the packaged service; this script runs its own instance.
    systemctl disable --now hostapd 2>/dev/null || true
  fi
  [[ -e /sys/class/net/$AP ]] && stop
  # Without an uplink the boards still join, and they start polling once
  # the laptop is back online.
  uplink=$(ip route show default | awk 'NR == 1 {print $5}')
  [[ -n $uplink ]] || { uplink="nothing yet"; echo "Note: this laptop has no internet route yet." >&2; }
  # Share the channel the card already uses, when that is 2.4 GHz.
  frequency=$(iw dev "$WIFI" link 2>/dev/null | awk '/freq:/ && !seen {print int($2); seen = 1}')
  if [[ -n $frequency && $frequency -lt 2500 ]]; then
    CHANNEL=$(( frequency == 2484 ? 14 : (frequency - 2407) / 5 ))
  elif [[ -n $frequency ]]; then
    echo "Note: $WIFI is on $frequency MHz. If hostapd fails below, this card cannot add a 2.4 GHz network next to it."
  fi
  phy=$(basename "$(readlink -f "/sys/class/net/$WIFI/phy80211")")
  iw phy "$phy" interface add "$AP" type __ap
  mkdir -p "$RUN" /run/systemd/network
  cat > "$NETWORK_FILE" <<EOF
[Match]
Name=$AP

[Network]
Address=10.42.7.1/24
DHCPServer=yes
IPMasquerade=ipv4
ConfigureWithoutCarrier=yes

[DHCPServer]
PoolOffset=10
PoolSize=40
# Without DNS= here, networkd hands out the uplink's DNS servers.
EmitDNS=yes
EOF
  cat > "$RUN/hostapd.conf" <<EOF
interface=$AP
driver=nl80211
ssid=$SSID
country_code=$COUNTRY
hw_mode=g
channel=$CHANNEL
ieee80211n=1
wpa=2
wpa_key_mgmt=WPA-PSK
rsn_pairwise=CCMP
wpa_passphrase=$ALIVE_HOTSPOT_PASSWORD
EOF
  chmod 600 "$RUN/hostapd.conf"
  # Ubuntu's firewall would drop the boards' DHCP requests and their traffic
  # to the internet. ufw skips rules it already has.
  if command -v ufw >/dev/null && ufw status | grep -q "Status: active"; then
    ufw allow in on "$AP" to any port 67 proto udp comment "ALIVE hotspot DHCP" >/dev/null
    ufw route allow in on "$AP" comment "ALIVE hotspot to the internet" >/dev/null
    ufw allow in on "$AP" to any port 8765 proto tcp comment "ALIVE hotspot boards to the API" >/dev/null
  fi
  networkctl reload
  echo "Hotspot $SSID on channel $CHANNEL shares $uplink."
}

start() {
  prepare
  hostapd -B -P "$RUN/hostapd.pid" "$RUN/hostapd.conf"
}

# For the systemd service. hostapd stays in the foreground, so systemd
# notices when it fails and starts it again.
run() {
  prepare
  exec hostapd -P "$RUN/hostapd.pid" "$RUN/hostapd.conf"
}

enable() {
  : "${ALIVE_HOTSPOT_PASSWORD:?Set ALIVE_HOTSPOT_PASSWORD to the hotspot password from secrets.h, 8 to 63 characters}"
  install -d -m 700 /etc/alive
  install -d -m 755 /opt/alive
  install -m 755 "$0" /opt/alive/laptop-hotspot.sh
  (
    umask 077
    printf 'ALIVE_HOTSPOT_PASSWORD=%s\nALIVE_HOTSPOT_SSID=%s\nALIVE_HOTSPOT_WIFI=%s\n' \
      "$ALIVE_HOTSPOT_PASSWORD" "$SSID" "$WIFI" > "$ENV_FILE"
  )
  cat > "$UNIT" <<UNIT_EOF
[Unit]
Description=ALIVE Wi-Fi hotspot for the boards
After=systemd-networkd.service

[Service]
EnvironmentFile=$ENV_FILE
ExecStart=/opt/alive/laptop-hotspot.sh run
ExecStopPost=/opt/alive/laptop-hotspot.sh stop
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
UNIT_EOF
  systemctl daemon-reload
  systemctl enable alive-hotspot.service
  systemctl restart alive-hotspot.service
  sleep 5
  status
}

disable() {
  systemctl disable --now alive-hotspot.service 2>/dev/null || true
  rm -f "$UNIT" "$ENV_FILE"
  systemctl daemon-reload
  stop
}

case ${1:-} in
  enable) enable ;;
  disable) disable ;;
  start) start ;;
  run) run ;;
  stop) stop ;;
  status) status ;;
  *) echo "Usage: sudo $0 enable|disable|status|start|stop" >&2; exit 2 ;;
esac

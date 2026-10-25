#!/usr/bin/env bash
# Runs a 2.4 GHz Wi-Fi network for the ALIVE boards on this laptop and shares
# the laptop's internet connection (venue Wi-Fi, LAN, or a USB phone tether)
# with it. The boards still reach the public API address, so nothing else
# changes. Needs systemd-networkd, which Ubuntu Server uses.
#
#   sudo ALIVE_HOTSPOT_PASSWORD='at least 8 characters' deploy/laptop-hotspot.sh start
#   sudo deploy/laptop-hotspot.sh status
#   sudo deploy/laptop-hotspot.sh stop
#
# The hotspot is a second interface on the laptop's Wi-Fi card. If the laptop
# itself is on Wi-Fi, many cards can only send on that same channel, and the
# boards need 2.4 GHz. When the uplink is on 5 GHz and hostapd fails, use the
# LAN or a USB tether as the uplink, or a USB Wi-Fi adapter for the hotspot
# (set ALIVE_HOTSPOT_WIFI to its interface name).
set -euo pipefail

SSID=${ALIVE_HOTSPOT_SSID:-ALIVE-T480}
WIFI=${ALIVE_HOTSPOT_WIFI:-wlp3s0}
CHANNEL=${ALIVE_HOTSPOT_CHANNEL:-6}
COUNTRY=${ALIVE_HOTSPOT_COUNTRY:-DE}
AP=alivehs0
RUN=/run/alive-hotspot
NETWORK_FILE=/run/systemd/network/50-alive-hotspot.network

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

start() {
  : "${ALIVE_HOTSPOT_PASSWORD:?Set ALIVE_HOTSPOT_PASSWORD to the hotspot password from secrets.h, 8 to 63 characters}"
  if ! command -v hostapd >/dev/null || ! command -v iw >/dev/null; then
    apt-get install -y hostapd iw
    # Ubuntu enables the packaged service; this script runs its own instance.
    systemctl disable --now hostapd 2>/dev/null || true
  fi
  [[ -e /sys/class/net/$AP ]] && stop
  uplink=$(ip route show default | awk '{print $5; exit}')
  [[ -n $uplink ]] || { echo "This laptop has no internet route. Connect it to the venue network first." >&2; exit 1; }
  # Share the channel the card already uses, when that is 2.4 GHz.
  frequency=$(iw dev "$WIFI" link 2>/dev/null | awk '/freq:/ {print int($2); exit}')
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
  networkctl reload
  hostapd -B -P "$RUN/hostapd.pid" "$RUN/hostapd.conf"
  echo "Hotspot $SSID is up on channel $CHANNEL and shares $uplink."
}

case ${1:-} in
  start) start ;;
  stop) stop ;;
  status) status ;;
  *) echo "Usage: sudo $0 start|stop|status" >&2; exit 2 ;;
esac

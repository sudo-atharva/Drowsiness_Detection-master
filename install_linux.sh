#!/usr/bin/env bash
# Sets up the host dashboard on Raspberry Pi OS (or any Debian-based host).
# Run from repo root: sudo bash install_linux.sh
set -e

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HOST_DIR="$REPO_DIR/host"

if [ "$EUID" -ne 0 ]; then
  echo "Run with sudo: sudo bash install_linux.sh"
  exit 1
fi

echo "== System packages (opencv via apt - much faster than pip on a Pi) =="
apt-get update
apt-get install -y python3-venv python3-pip python3-opencv

echo "== Python venv (system-site-packages so it sees apt's opencv) =="
sudo -u "${SUDO_USER:-$USER}" python3 -m venv --system-site-packages "$REPO_DIR/venv"
"$REPO_DIR/venv/bin/pip" install --upgrade pip
"$REPO_DIR/venv/bin/pip" install flask pyserial

echo "== Enabling GPIO UART for the GPS module (frees /dev/serial0 from the login console) =="
raspi-config nonint do_serial_cons 1 || true
raspi-config nonint do_serial_hw 0 || true

echo "== Moving Bluetooth off the good UART (GPIO14/15 get the PL011, not the clock-drifty mini-UART) =="
CONFIG_TXT="/boot/firmware/config.txt"
[ -f "$CONFIG_TXT" ] || CONFIG_TXT="/boot/config.txt"
grep -q "^dtoverlay=disable-bt" "$CONFIG_TXT" || echo "dtoverlay=disable-bt" >> "$CONFIG_TXT"

echo "== Enabling second GPIO UART (UART3) for the GSM module =="
MODEL="$(tr -d '\0' < /proc/device-tree/model 2>/dev/null || true)"
case "$MODEL" in
  *"Pi 5"*) UART3_OVERLAY="uart3-pi5" ;;   # GPIO8 TX / GPIO9 RX
  *"Pi 4"*|*"Compute Module 4"*|*"Pi 400"*) UART3_OVERLAY="uart3" ;;  # GPIO4 TX / GPIO5 RX
  *) UART3_OVERLAY=""
     echo "WARNING: '$MODEL' has only one full GPIO UART (GPS uses it)."
     echo "         GSM needs a Pi 4/5 for GPIO, or a USB-serial adapter (set GSM_SERIAL_PORTS in host/gsm_alert.py)." ;;
esac
if [ -n "$UART3_OVERLAY" ]; then
  grep -q "^dtoverlay=$UART3_OVERLAY" "$CONFIG_TXT" || echo "dtoverlay=$UART3_OVERLAY" >> "$CONFIG_TXT"
fi

echo "== NetworkManager CLI (WiFi scan for location fallback when GPS has no fix) =="
command -v nmcli >/dev/null || echo "WARNING: nmcli missing - WiFi location fallback disabled (Bookworm ships it by default)."

echo "== Tailscale (for remote access, same pattern as OctoPrint) =="
if ! command -v tailscale >/dev/null; then
  curl -fsSL https://tailscale.com/install.sh | sh
fi
echo "Run 'sudo tailscale up' once manually to authenticate."

echo "== systemd service (auto-start dashboard on boot) =="
cat > /etc/systemd/system/drowsiness-dashboard.service <<EOF
[Unit]
Description=Drowsiness/Vehicle Dashboard
After=network.target

[Service]
WorkingDirectory=$HOST_DIR
ExecStart=$REPO_DIR/venv/bin/python $HOST_DIR/app.py
Restart=on-failure
User=${SUDO_USER:-root}

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable drowsiness-dashboard.service

cat <<EOF

Done. Before it'll actually work:
  1. Wire GPS to GPIO14/15 and GSM to UART3 (see host/README.md).
  2. Set ALERT_PHONE_NUMBER in host/gsm_alert.py.
  3. sudo tailscale up   (one-time auth)
  4. sudo reboot         (applies the UART changes + starts the dashboard service)

After reboot, check status with: sudo systemctl status drowsiness-dashboard
Dashboard at: http://<this-pi-tailscale-ip>:5000
EOF

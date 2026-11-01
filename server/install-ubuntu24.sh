#!/usr/bin/env bash
# Install only iGPT-owned files. Run once as root on Ubuntu 24.04.
set -euo pipefail
test "$(id -u)" = 0 || { echo 'run as root'; exit 1; }
test -n "${IGPT_TOKEN:-}" || { echo 'export a 32+ character IGPT_TOKEN first'; exit 1; }
test "${#IGPT_TOKEN}" -ge 32 || { echo 'IGPT_TOKEN is too short'; exit 1; }
ROOT=/opt/igpt
install -d -m 0755 "$ROOT"
install -d -m 0700 /var/lib/igpt
id -u igpt >/dev/null 2>&1 || useradd --system --home /var/lib/igpt --shell /usr/sbin/nologin igpt
apt-get update
apt-get install -y python3-venv python3-pip ffmpeg chromium-browser nginx
python3 -m venv "$ROOT/venv"
"$ROOT/venv/bin/pip" install --upgrade pip
"$ROOT/venv/bin/pip" install -r "$ROOT/server/requirements.txt"
su -s /bin/sh igpt -c "$ROOT/venv/bin/playwright install chromium"
install -m 0600 /dev/stdin /etc/igpt.env <<EOF
IGPT_TOKEN=$IGPT_TOKEN
IGPT_PROFILE_DIR=/var/lib/igpt/profiles
IGPT_WORKDIR=/var/lib/igpt/workspace
# Set this to a comma separated list of your own Invidious/Piped-compatible sources.
# IGPT_INVIDIOUS_INSTANCES=https://your-invidious.example
EOF
install -m 0644 "$ROOT/server/igpt.service.example" /etc/systemd/system/igpt.service
systemctl daemon-reload
systemctl enable --now igpt
echo 'iGPT listens only on 127.0.0.1:8765. Configure HTTPS reverse proxy separately.'

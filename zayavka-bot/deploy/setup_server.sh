#!/usr/bin/env bash
# One-shot installer for a Linux server (Ubuntu/Debian), run as root:
#
#   sudo bash deploy/setup_server.sh                 # bot + API only
#   sudo bash deploy/setup_server.sh bot.example.uz  # + HTTPS for the Mini App via Caddy
#
# No domain? Use the free <server-ip>.sslip.io name, e.g. 203-0-113-5.sslip.io
# (the domain must point at this server, and ports 80/443 must be open).
#
# Run it from the project folder (the one containing run_bot.py and .env).
# Safe to re-run: it just updates and restarts everything.
set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
DOMAIN="${1:-}"
APP_USER="${SUDO_USER:-root}"

[ "$(id -u)" = 0 ] || { echo "Run with sudo"; exit 1; }
[ -f "$APP_DIR/.env" ] || { echo "Missing $APP_DIR/.env - copy .env.example to .env and fill it in"; exit 1; }
cd "$APP_DIR"

echo "==> Installing system packages"
apt-get update -qq
apt-get install -y -qq python3 python3-venv python3-pip sqlite3 >/dev/null

echo "==> Creating virtualenv and installing Python packages"
[ -d .venv ] || python3 -m venv .venv
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -r requirements.txt
chown -R "$APP_USER": "$APP_DIR"

# Windows line endings in .env (file copied from a PC) break values - strip them.
sed -i 's/\r$//' .env

echo "==> Installing systemd services"
for svc in api bot; do
  sed -e "s|__APP_DIR__|$APP_DIR|g" -e "s|__APP_USER__|$APP_USER|g" \
      "deploy/zayavka-$svc.service" > "/etc/systemd/system/zayavka-$svc.service"
done
systemctl daemon-reload

if [ -n "$DOMAIN" ]; then
  echo "==> Setting up HTTPS for $DOMAIN with Caddy"
  if ! command -v caddy >/dev/null; then
    apt-get install -y -qq debian-keyring debian-archive-keyring apt-transport-https curl gpg >/dev/null
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor --yes -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' > /etc/apt/sources.list.d/caddy-stable.list
    apt-get update -qq && apt-get install -y -qq caddy >/dev/null
  fi
  printf '%s {\n    reverse_proxy 127.0.0.1:8000\n}\n' "$DOMAIN" > /etc/caddy/Caddyfile
  systemctl enable -q caddy && systemctl restart caddy
  command -v ufw >/dev/null && ufw status | grep -q active && ufw allow 80,443/tcp >/dev/null || true
  # Point the bot at the new permanent URL.
  if grep -q '^WEBAPP_URL=' .env; then
    sed -i "s|^WEBAPP_URL=.*|WEBAPP_URL=https://$DOMAIN|" .env
  else
    echo "WEBAPP_URL=https://$DOMAIN" >> .env
  fi
fi

systemctl enable -q zayavka-api zayavka-bot
systemctl restart zayavka-api
sleep 2
systemctl restart zayavka-bot
sleep 3

echo
systemctl --no-pager --lines=0 status zayavka-api zayavka-bot | grep -E '●|Active:'
echo
echo "WEBAPP_URL is now: $(grep '^WEBAPP_URL=' .env | cut -d= -f2-)"
echo "Logs:  journalctl -u zayavka-bot -f     journalctl -u zayavka-api -f"

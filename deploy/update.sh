#!/usr/bin/env bash
# Hakee uusimman koodin GitHubista ja käynnistää botin uudelleen.
# Käyttö palvelimella: sudo /opt/dnd_tg_bot/deploy/update.sh
set -euo pipefail

APP_DIR=/opt/dnd_tg_bot
cd "$APP_DIR"

echo "→ Haetaan muutokset..."
git pull

echo "→ Päivitetään riippuvuudet..."
./venv/bin/pip install -q -r requirements.txt

echo "→ Palautetaan oikeudet..."
chown -R dndbot:dndbot "$APP_DIR"
chmod 600 "$APP_DIR/.env"

echo "→ Käynnistetään botti uudelleen..."
systemctl restart dnd-bot
sleep 2
systemctl --no-pager status dnd-bot | head -n 5

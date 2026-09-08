#!/usr/bin/env bash
# Ежедневная резервная копия базы. Хранит последние 14 копий.
# Установка в cron (от root): sudo crontab -e  →  0 4 * * * /opt/dnd_tg_bot/deploy/backup.sh
set -euo pipefail

APP_DIR=/opt/dnd_tg_bot
BACKUP_DIR="$APP_DIR/backups"
mkdir -p "$BACKUP_DIR"

STAMP=$(date +%Y-%m-%d_%H-%M)
TARGET="$BACKUP_DIR/game-$STAMP.db"

# Через API SQLite, а не cp: учитывает WAL-журнал и не ловит полузаписанное состояние
"$APP_DIR/venv/bin/python" - "$APP_DIR/game.db" "$TARGET" <<'PY'
import sqlite3, sys
src = sqlite3.connect(sys.argv[1])
dst = sqlite3.connect(sys.argv[2])
src.backup(dst)
dst.close()
src.close()
PY

# Оставляем 14 самых свежих копий
ls -1t "$BACKUP_DIR"/game-*.db 2>/dev/null | tail -n +15 | xargs -r rm -f
echo "Backup: $TARGET"

#!/usr/bin/env bash
# Nightly backup of the KAVACH platform data: a consistent copy of the SQLite
# database (taken with SQLite's online-backup API while the app keeps running)
# plus the uploaded input files. Keeps the last KEEP_DAYS days.
#
#   ./deploy/backup.sh                 (run from the application folder)
#   crontab:  30 1 * * *  cd /opt/kavach-platform && ./deploy/backup.sh >> data/backups/backup.log 2>&1
set -euo pipefail
cd "$(dirname "$0")/.."
KEEP_DAYS="${KEEP_DAYS:-14}"
STAMP="$(date +%Y%m%d-%H%M%S)"
mkdir -p data/backups

docker compose -f docker-compose.prod.yml exec -T backend python -c "
import sqlite3
src = sqlite3.connect('/app/data/kavach.db')
dst = sqlite3.connect('/app/data/backups/kavach-${STAMP}.db')
src.backup(dst); dst.close(); src.close()
"
tar -czf "data/backups/uploads-${STAMP}.tar.gz" -C data uploads
find data/backups -name 'kavach-*.db' -mtime +"${KEEP_DAYS}" -delete
find data/backups -name 'uploads-*.tar.gz' -mtime +"${KEEP_DAYS}" -delete
echo "$(date -Is) backup ${STAMP} done"

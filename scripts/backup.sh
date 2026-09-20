#!/usr/bin/env bash
# Copy a consistent snapshot of the live SQLite DB to S3. Student profiles and plans are written to it during the demo.
# Cron every 10 minutes on the EC2:  */10 * * * * S3_BUCKET=<bucket> /opt/uniq/scripts/backup.sh
set -euo pipefail
APP_DIR=${APP_DIR:-/opt/uniq}
: "${S3_BUCKET:?set S3_BUCKET}"
snap=/tmp/kmu-$(date +%Y%m%d-%H%M%S).db
sqlite3 "$APP_DIR/data/kmu.db" ".backup $snap"   # .backup is safe against a WAL-mode writer; plain cp is not
aws s3 cp --quiet "$snap" "s3://$S3_BUCKET/backup/$(basename "$snap")"
aws s3 cp --quiet "$snap" "s3://$S3_BUCKET/backup/latest.db"
rm -f "$snap"

#!/usr/bin/env bash
# Deploy UniQ on the EC2 (Amazon Linux 2023; Ubuntu 24.04 also works). Idempotent: run it again to update.
# The instance role reads and writes the team bucket, so nothing here needs AWS keys.
#
#   sudo CODE_TAR=/tmp/uniq.tar.gz S3_BUCKET=kmuct-ht-15-uniq RELEASE_TAG=<sha> bash /tmp/deploy.sh   # what CI runs over SSH
#   sudo S3_BUCKET=kmuct-ht-15-uniq bash deploy.sh                                              # redeploy release/uniq.tar.gz
#   sudo CODE_URL=... ENV_URL=... DB_URL=... bash deploy.sh                                     # presigned URLs, no role needed
#
# Code: CODE_TAR (local tarball from scripts/release.sh) > CODE_URL > S3 <bucket>/release/uniq.tar.gz > REPO_URL (git).
# Secrets never come from git (SPEC 4): .env is refreshed from S3 <bucket>/secrets/.env (or ENV_URL) on every run;
# data/kmu.db is fetched from <bucket>/db/kmu.db (or DB_URL) only when the instance has none, because the live DB
# collects student profiles and plans. FORCE_DB=1 overwrites it anyway.
set -euo pipefail
trap 'echo "deploy.sh failed at line $LINENO: $BASH_COMMAND" >&2' ERR

APP_DIR=${APP_DIR:-/opt/uniq}
APP_USER=${APP_USER:-$(id -u ec2-user >/dev/null 2>&1 && echo ec2-user || echo ubuntu)}
BRANCH=${BRANCH:-main}
PORT=${PORT:-8000}
UNIT=/etc/systemd/system/uniq.service

[ "$(id -u)" -eq 0 ] || { echo "run with sudo"; exit 1; }

echo "== packages"
if command -v dnf >/dev/null; then
  dnf install -y -q git sqlite tar gzip cronie >/dev/null     # AL2023 ships python3.12 and the aws cli, but no cron
  systemctl enable --now --quiet crond
else
  apt-get update -q && apt-get install -y -q python3.12-venv git curl sqlite3 tar unzip cron
  if [ -n "${S3_BUCKET:-}" ] && ! command -v aws >/dev/null; then
    curl -sS "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o /tmp/awscli.zip
    unzip -qo /tmp/awscli.zip -d /tmp && /tmp/aws/install --update
  fi
fi
PY=$(command -v python3.12 || command -v python3)
"$PY" -c 'import sys; assert sys.version_info >= (3, 10), sys.version' || { echo "need python >= 3.10, got $($PY --version)"; exit 1; }

echo "== code -> $APP_DIR"
mkdir -p "$APP_DIR"
untar() {  # .env, data/ and .venv/ live only on the box; the tarball never carries them, but be safe.
  tar -xzf "$1" -C "$APP_DIR" --exclude='.env' --exclude='data' --exclude='.venv'
}
if [ -n "${CODE_TAR:-}" ]; then
  untar "$CODE_TAR"
  if [ -n "${S3_BUCKET:-}" ]; then  # keep every deployed build in S3: release/uniq-<tag>.tar.gz, latest as release/uniq.tar.gz
    aws s3 cp "$CODE_TAR" "s3://$S3_BUCKET/release/uniq-${RELEASE_TAG:-$(date +%Y%m%d-%H%M%S)}.tar.gz" --quiet
    aws s3 cp "$CODE_TAR" "s3://$S3_BUCKET/release/uniq.tar.gz" --quiet
  fi
elif [ -n "${CODE_URL:-}" ]; then
  curl -fsS "$CODE_URL" -o /tmp/uniq.tar.gz && untar /tmp/uniq.tar.gz
elif [ -n "${S3_BUCKET:-}" ] && aws s3 cp "s3://$S3_BUCKET/release/uniq.tar.gz" /tmp/uniq.tar.gz --quiet 2>/dev/null; then
  untar /tmp/uniq.tar.gz
elif [ -d "$APP_DIR/.git" ]; then
  git -C "$APP_DIR" fetch --quiet origin && git -C "$APP_DIR" checkout --quiet "$BRANCH" && git -C "$APP_DIR" pull --quiet --ff-only
elif [ -n "${REPO_URL:-}" ]; then
  git clone --quiet --branch "$BRANCH" "$REPO_URL" "$APP_DIR"
elif [ ! -f "$APP_DIR/app/main.py" ]; then
  echo "no code: set CODE_TAR, CODE_URL, S3_BUCKET (with release/uniq.tar.gz) or REPO_URL"; exit 1
fi
cd "$APP_DIR"
mkdir -p data

echo "== venv"
[ -x .venv/bin/python ] || "$PY" -m venv .venv
.venv/bin/pip install -q -r requirements.txt

echo "== secrets"
if [ -n "${ENV_URL:-}" ]; then curl -fsS "$ENV_URL" -o .env; fi
if [ -n "${DB_URL:-}" ] && { [ ! -f data/kmu.db ] || [ "${FORCE_DB:-0}" = 1 ]; }; then curl -fsS "$DB_URL" -o data/kmu.db; fi
if [ -n "${S3_BUCKET:-}" ]; then
  aws s3 cp "s3://$S3_BUCKET/secrets/.env" .env --quiet || echo "no secrets/.env in S3; keeping the local one"
  if [ ! -f data/kmu.db ] || [ "${FORCE_DB:-0}" = 1 ]; then
    aws s3 cp "s3://$S3_BUCKET/db/kmu.db" data/kmu.db --quiet || echo "no db/kmu.db in S3"
  fi
fi
[ -f .env ] || { echo "missing $APP_DIR/.env: upload it to s3://$S3_BUCKET/secrets/.env or set ENV_URL"; exit 1; }
[ -f data/kmu.db ] || { echo "missing $APP_DIR/data/kmu.db: upload it to s3://$S3_BUCKET/db/kmu.db or set DB_URL"; exit 1; }
# The service runs from $APP_DIR, but an absolute DB_PATH survives anyone starting uvicorn by hand from elsewhere.
if grep -q '^DB_PATH=' .env; then sed -i "s#^DB_PATH=.*#DB_PATH=$APP_DIR/data/kmu.db#" .env; else echo "DB_PATH=$APP_DIR/data/kmu.db" >> .env; fi
chmod 600 .env
chown -R "$APP_USER:$APP_USER" "$APP_DIR"

echo "== service"
sed -e "s#/opt/uniq#$APP_DIR#g" -e "s#^User=.*#User=$APP_USER#" -e "s#^Environment=PORT=.*#Environment=PORT=$PORT#" \
  scripts/uniq.service > "$UNIT"
systemctl daemon-reload
systemctl enable --quiet uniq
systemctl restart uniq
if [ -n "${S3_BUCKET:-}" ] && ! crontab -u "$APP_USER" -l 2>/dev/null | grep -q backup.sh; then
  (crontab -u "$APP_USER" -l 2>/dev/null; echo "*/10 * * * * S3_BUCKET=$S3_BUCKET APP_DIR=$APP_DIR $APP_DIR/scripts/backup.sh") | crontab -u "$APP_USER" -
  echo "backup cron installed (every 10 min -> s3://$S3_BUCKET/backup/)"
fi

echo "== health"
for _ in $(seq 1 20); do
  if curl -fsS "http://127.0.0.1:$PORT/api/config" >/dev/null; then
    tok=$(curl -sS -m 2 -X PUT http://169.254.169.254/latest/api/token -H 'X-aws-ec2-metadata-token-ttl-seconds: 60' 2>/dev/null || true)
    ip=$(curl -sS -m 2 -H "X-aws-ec2-metadata-token: $tok" http://169.254.169.254/latest/meta-data/public-ipv4 2>/dev/null || hostname -I | awk '{print $1}')
    echo "up: http://$ip:$PORT/"
    exit 0
  fi
  sleep 1
done
echo "server did not answer on port $PORT; see: journalctl -u uniq -n 50"
exit 1

#!/usr/bin/env bash
# Build the release tarball deploy.sh installs: code + static + scripts, no git, no data, no .env, no venv.
# Usage: bash scripts/release.sh [out.tar.gz]   (default: dist/uniq.tar.gz)
set -euo pipefail
cd "$(dirname "$0")/.."
out=${1:-dist/uniq.tar.gz}
mkdir -p "$(dirname "$out")"
tar -czf "$out" --exclude='__pycache__' app static scripts requirements.txt README.md SPEC.md
ls -l "$out"

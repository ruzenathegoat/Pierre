#!/usr/bin/env bash
set -euo pipefail

echo "=================================================================="
echo "⚙️  Starting & Persisting Pierre PM2 Daemons on Tencent Lighthouse"
echo "=================================================================="

export NVM_DIR="$HOME/.nvm"
[ -s "$NVM_DIR/nvm.sh" ] && \. "$NVM_DIR/nvm.sh"
[ -f "$HOME/.local/bin/env" ] && source "$HOME/.local/bin/env"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HARNESS_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$HARNESS_DIR"

pm2 start ecosystem.config.cjs
pm2 save
pm2 status

echo ""
echo "Untuk mengaktifkan auto-start PM2 saat VPS reboot, jalankan perintah yang ditampilkan oleh:"
echo "  pm2 startup"


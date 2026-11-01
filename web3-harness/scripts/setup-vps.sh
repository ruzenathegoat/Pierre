#!/usr/bin/env bash
set -euo pipefail

echo "=================================================================="
echo "🚀 Pierre — Tencent Cloud Lighthouse VPS Setup (Phase 5 Bootstrap)"
echo "=================================================================="

HERMES_DIR="$HOME/.hermes"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HARNESS_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# 1. OS Hardening & Dependencies
echo "[1/6] Memperbarui paket OS & mengonfigurasi firewall UFW..."
sudo apt update && sudo apt upgrade -y
sudo apt install -y git curl wget unzip jq build-essential sqlite3 ufw fail2ban
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow OpenSSH
sudo ufw --force enable

# 2. Verify Pre-installed Hermes Agent
echo "[2/6] Memverifikasi instalasi Hermes Agent..."
if command -v hermes >/dev/null 2>&1; then
  hermes --version
else
  echo "Hermes belum ditemukan di PATH, memuat environment lokal..."
  [ -f "$HOME/.local/bin/env" ] && source "$HOME/.local/bin/env"
  hermes --version || true
fi

# 3. Install Node.js v22 via NVM, PM2, tsx & Binance Agentic Wallet (baw)
echo "[3/6] Menginstal Node.js v22, PM2, tsx, dan @binance/agentic-wallet (baw)..."
export NVM_DIR="$HOME/.nvm"
if [ ! -d "$NVM_DIR" ]; then
  curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.1/install.sh | bash
fi
[ -s "$NVM_DIR/nvm.sh" ] && \. "$NVM_DIR/nvm.sh"

nvm install 22
nvm use 22
nvm alias default 22

npm install -g pm2 tsx @binance/agentic-wallet
npx --yes skills add binance/binance-skills-hub/skills/binance-web3/binance-agentic-wallet || true

# 4. Install Web3 Harness Dependencies & Typecheck
echo "[4/6] Menginstal dependensi web3-harness & menjalankan tsc --noEmit..."
cd "$HARNESS_DIR"
npm install
npx tsc --noEmit

# 5. Sync Hermes Templates (MEMORY.md, SKILL.md, config.yaml)
echo "[5/6] Menyinkronkan MEMORY.md, pierre-web3/SKILL.md, dan config.yaml ke $HERMES_DIR..."
mkdir -p "$HERMES_DIR/skills/pierre-web3"

if [ ! -f "$HERMES_DIR/skills/pierre-web3/SKILL.md" ]; then
  cp "$HARNESS_DIR/hermes-templates/skills/pierre-web3/SKILL.md" "$HERMES_DIR/skills/pierre-web3/SKILL.md"
  echo "  -> SKILL.md disalin ke $HERMES_DIR/skills/pierre-web3/SKILL.md"
fi

if [ ! -f "$HERMES_DIR/MEMORY.md" ]; then
  cp "$HARNESS_DIR/hermes-templates/MEMORY.md" "$HERMES_DIR/MEMORY.md"
  echo "  -> MEMORY.md disalin ke $HERMES_DIR/MEMORY.md"
fi

TSX_BIN="$(command -v tsx)"
cat > "$HERMES_DIR/config.yaml" <<EOF
model:
  provider: openrouter
  default: deepseek/deepseek-v4.1-flash-1017

mcp_servers:
  viem_web3_harness:
    command: "${TSX_BIN}"
    args:
      - "${HARNESS_DIR}/src/mcp-server.ts"
    env:
      NODE_NO_WARNINGS: "1"
EOF
echo "  -> config.yaml dikonfigurasi dengan model deepseek/deepseek-v4.1-flash-1017 & MCP path ${HARNESS_DIR}/src/mcp-server.ts"

# 6. Prepare .env files if not present
echo "[6/6] Memeriksa file .env..."
if [ ! -f "$HERMES_DIR/.env" ]; then
  if [ -f "$HARNESS_DIR/hermes-templates/.env" ]; then
    cp "$HARNESS_DIR/hermes-templates/.env" "$HERMES_DIR/.env"
    echo "  -> Disalin $HARNESS_DIR/hermes-templates/.env ke $HERMES_DIR/.env"
  else
    cp "$HARNESS_DIR/hermes-templates/.env.hermes.example" "$HERMES_DIR/.env"
    echo "  -> Dibuat template $HERMES_DIR/.env"
  fi
fi
chmod 600 "$HERMES_DIR/.env"

if [ ! -f "$HARNESS_DIR/.env" ]; then
  cp "$HARNESS_DIR/.env.example" "$HARNESS_DIR/.env"
  echo "  -> Dibuat template $HARNESS_DIR/.env"
fi
chmod 600 "$HARNESS_DIR/.env"

# Auto-provision free 7-day OpenSea API Key into .env if empty
if grep -qE '^OPENSEA_API_KEY=\s*$' "$HARNESS_DIR/.env"; then
  echo "  -> Auto-generating free OpenSea API v2 key ke $HARNESS_DIR/.env..."
  cd "$HARNESS_DIR" && npm run opensea:key || true
fi

echo ""
echo "✅ Bootstrap Phase 5 Selesai!"
echo "Langkah Manual Berikutnya di VPS:"
echo "  1. Isi API Key OpenRouter & Discord Bot di: nano ~/.hermes/.env"
echo "  2. Isi Private Key & 3 Webhook Discord di : nano ~/.hermes/web3-harness/.env"
echo "  3. Login QR Binance Agentic Wallet (.ai)  : baw auth signin"
echo "  4. Cek tools MCP di Hermes CLI            : hermes  (lalu ketik /tools)"


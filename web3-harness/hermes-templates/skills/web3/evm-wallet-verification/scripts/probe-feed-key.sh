#!/usr/bin/env bash
# Probe an X-API-KEY data feed without ever echoing the secret.
# Usage: probe-feed-key.sh [env-file] [url] [env-var]
# Defaults: ~/.hermes/web3-harness/.env, OpenSea /collections, OPENSEA_API_KEY
set -uo pipefail

ENV_FILE="${1:-$HOME/.hermes/web3-harness/.env}"
URL="${2:-https://api.opensea.io/api/v2/collections?limit=1}"
VAR="${3:-OPENSEA_API_KEY}"

[ -f "$ENV_FILE" ] || { echo "env file not found: $ENV_FILE"; exit 2; }

KEY="$(python3 - "$ENV_FILE" "$VAR" <<'PY'
import re, sys
env, var = sys.argv[1], sys.argv[2]
for line in open(env, errors='ignore'):
    m = re.match(r'^\s*' + re.escape(var) + r'\s*=\s*(.*)$', line)
    if m:
        print(m.group(1).strip().strip('"').strip("'"))
        break
PY
)"

echo "env          : $ENV_FILE"
echo "var          : $VAR"
echo "value length : ${#KEY}"
if [ -z "$KEY" ]; then
  echo "RESULT       : KEY EMPTY (line exists but value is unset)"
  exit 1
fi

STATUS="$(curl -s -o /tmp/feed_probe_body.json -w '%{http_code}' -H "X-API-KEY: $KEY" "$URL")"
echo "endpoint     : $URL"
echo "http status  : $STATUS"
case "$STATUS" in
  2*) echo "RESULT       : KEY WORKS"; head -c 200 /tmp/feed_probe_body.json; echo ;;
  401|403) echo "RESULT       : KEY REJECTED (empty, revoked, or expired)"; head -c 200 /tmp/feed_probe_body.json; echo ;;
  429) echo "RESULT       : RATE LIMITED (not a key-shape problem; wait for reset or use a full key)"; head -c 200 /tmp/feed_probe_body.json; echo ;;
  *) echo "RESULT       : UNEXPECTED"; head -c 200 /tmp/feed_probe_body.json; echo ;;
esac

# End-to-end still matters: call the real tool afterwards and read its
# provenance field (source/fallback). A working key with a stale server
# process still returns fallback data.

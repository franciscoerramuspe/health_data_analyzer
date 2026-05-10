#!/usr/bin/env bash
#
# Starts the health-chat Next.js app and a Cloudflare Tunnel pointing at it,
# plus keeps your Mac awake while it runs. Stop with Ctrl+C — kills everything.
#
# Usage:  ./run.sh
# First-time: ./run.sh --build   (forces a fresh `npm install` + `npm run build`)

set -e
cd "$(dirname "$0")"

CLIENT_DIR="$(pwd)/client"
PORT=${PORT:-3000}

# --- preflight ----------------------------------------------------------------

if ! command -v cloudflared >/dev/null 2>&1; then
  echo "cloudflared not found. Install with: brew install cloudflared"
  exit 1
fi

if ! command -v node >/dev/null 2>&1; then
  echo "node not found. Install Node.js first."
  exit 1
fi

# Build if requested or if no production build exists yet
if [ "${1:-}" = "--build" ] || [ ! -d "$CLIENT_DIR/.next" ]; then
  echo "→ installing dependencies + building (one-time)…"
  (cd "$CLIENT_DIR" && npm install && npm run build)
fi

# --- launch -------------------------------------------------------------------

# Kill all child processes when this script exits (Ctrl+C, error, etc.)
_CLEANED=0
cleanup() {
  [ "$_CLEANED" = "1" ] && return
  _CLEANED=1
  echo
  echo "→ shutting down…"
  kill 0 2>/dev/null || true
}
trap cleanup EXIT INT TERM

# Prevent Mac from sleeping while we're up
echo "→ keeping Mac awake (caffeinate)…"
caffeinate -d -i -m &

# Start Next.js in production mode
echo "→ starting Next.js on http://localhost:$PORT …"
(cd "$CLIENT_DIR" && PORT="$PORT" npm run start) &

# Wait for the server to actually bind
echo -n "→ waiting for server"
for _ in {1..20}; do
  if curl -s "http://localhost:$PORT" >/dev/null 2>&1; then
    echo " ✓"
    break
  fi
  echo -n "."
  sleep 1
done

# Start the Cloudflare Tunnel — prints a public https URL
echo "→ starting Cloudflare Tunnel…"
echo
cloudflared tunnel --url "http://localhost:$PORT"

# Tunnel runs in the foreground; cleanup trap handles the rest.
wait

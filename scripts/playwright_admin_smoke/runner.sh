#!/bin/bash
set -e
cd /work
if [ ! -d node_modules/playwright ]; then
  echo "Installing playwright@1.59.1 (one-time, ~5-10s on a warm npm cache)..."
  npm install playwright@1.59.1 --no-save --silent
fi
node proxy.mjs &
PROXY_PID=$!
trap "kill $PROXY_PID 2>/dev/null || true" EXIT
sleep 1
# Smoke API base must point to the same proxy port so axios calls in the page
# go through the host-rewriting proxy too.
FRONTEND_URL=http://127.0.0.1:18000 BACKEND_URL=http://127.0.0.1:8000 node run.mjs

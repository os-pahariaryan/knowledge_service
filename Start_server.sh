#!/bin/zsh
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

if [ ! -d .venv ]; then
  python3 -m venv .venv
fi

source .venv/bin/activate

if [ -f .env ]; then
  set -a
  source .env
  set +a
fi

SERVER_HOST="${SERVER_HOST:-127.0.0.1}"
SERVER_PORT="${SERVER_PORT:-8000}"

REQ_FILE="requirements.txt"
REQ_STAMP=".requirements_installed"
if [ ! -f "$REQ_STAMP" ] || [ "$REQ_FILE" -nt "$REQ_STAMP" ]; then
  pip install -r "$REQ_FILE"
  touch "$REQ_STAMP"
fi

if [ -f server.pid ]; then
  OLD_PID="$(cat server.pid)"
  if kill -0 "$OLD_PID" 2>/dev/null; then
    kill "$OLD_PID"
    wait "$OLD_PID" 2>/dev/null || true
  fi
  rm -f server.pid
fi
python3 write_env_from_openai_config2.py
nohup python3 -m uvicorn knowledge_service_poc_clean:app --host "$SERVER_HOST" --port "$SERVER_PORT" > server.log 2>&1 &
echo $! > server.pid

echo "Server started in background on http://$SERVER_HOST:$SERVER_PORT (PID $(cat server.pid)). Logs: $SCRIPT_DIR/server.log"

#!/bin/zsh
set -e

SCRIPT_DIR="${0:A:h}"
cd "$SCRIPT_DIR"

if [[ -x ".venv/bin/python" ]]; then
  PYTHON=".venv/bin/python"
elif [[ -x "../../.venv/bin/python" ]]; then
  PYTHON="../../.venv/bin/python"
else
  PYTHON="python3"
fi

exec "$PYTHON" -m uvicorn report_worker.dashboard:app \
  --host 127.0.0.1 \
  --port 8765

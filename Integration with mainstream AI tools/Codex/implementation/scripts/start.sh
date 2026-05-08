#!/usr/bin/env sh
set -eu

cd "$(dirname "$0")/.."

USER_PYTHON_BIN="$HOME/Library/Python/3.9/bin"
if [ -d "$USER_PYTHON_BIN" ]; then
  PATH="$USER_PYTHON_BIN:$PATH"
fi

: "${MAAS_API_BASE:=https://api-ap-southeast-1.modelarts-maas.com/openai/v1}"

if [ -z "${MAAS_API_KEY:-}" ]; then
  printf '%s\n' "MAAS_API_KEY is required."
  exit 1
fi

if [ -z "${LITELLM_MASTER_KEY:-}" ]; then
  export LITELLM_MASTER_KEY="$MAAS_API_KEY"
fi

export MAAS_API_BASE
export PATH

litellm --config ./litellm_config.yaml --host 127.0.0.1 --port 8788 &
LITELLM_PID="$!"

cleanup() {
  kill "$LITELLM_PID" >/dev/null 2>&1 || true
}
trap cleanup EXIT INT TERM

sleep 3

export LITELLM_INTERNAL_BASE_URL="${LITELLM_INTERNAL_BASE_URL:-http://127.0.0.1:8788/v1}"
exec python3 -m uvicorn responses_adapter:app --host 127.0.0.1 --port 8787

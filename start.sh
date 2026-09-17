#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
WEB_HOST="${OPENCODE_REQUEST_MONITOR_HOST:-127.0.0.1}"
WEB_PORT="${OPENCODE_REQUEST_MONITOR_PORT:-30500}"
PROXY_PORT="${OPENCODE_REQUEST_MONITOR_PROXY_PORT:-30499}"
UPSTREAM_PROXY="${OPENCODE_REQUEST_MONITOR_UPSTREAM_PROXY:-http://127.0.0.1:30084}"
# 继承环境里的 no_proxy 含 127.0.0.1，而 provider baseURL 就是本机 Plexus，会导致请求绕过
# mitmproxy。默认清空，只保留需要直连的自机地址。
PROXY_BYPASS="${OPENCODE_REQUEST_MONITOR_NO_PROXY:-}"
OPENCODE_ARGS=()

if [[ $# -gt 0 ]]; then
  if [[ "$1" == "--" ]]; then
    shift
    OPENCODE_ARGS=("$@")
  else
    OPENCODE_ARGS=("$@")
  fi
fi

LAUNCH_DIR="$PWD"
cd "$ROOT_DIR"

# 先清理旧进程，避免端口残留
pkill -f "mitmdump -q -p ${PROXY_PORT}" >/dev/null 2>&1 || true
pkill -f "uvicorn app.main:app --host ${WEB_HOST} --port ${WEB_PORT}" >/dev/null 2>&1 || true

# 给旧进程一点退出时间
sleep 1

uv sync

mkdir -p "$ROOT_DIR/.run"

setsid uv run uvicorn app.main:app --host "$WEB_HOST" --port "$WEB_PORT" > "$ROOT_DIR/.run/web.log" 2>&1 < /dev/null &
WEB_PID=$!

OPENCODE_REQUEST_MONITOR_API_URL="http://${WEB_HOST}:${WEB_PORT}/api/packets" setsid \
  mitmdump -q \
  -p "$PROXY_PORT" \
  --mode "upstream:${UPSTREAM_PROXY}" \
  -s "$ROOT_DIR/mitm_capture.py" > "$ROOT_DIR/.run/mitm.log" 2>&1 < /dev/null &
MITM_PID=$!

echo "web=http://${WEB_HOST}:${WEB_PORT}"
echo "proxy=http://${WEB_HOST}:${PROXY_PORT}"
echo "upstream=${UPSTREAM_PROXY}"
echo "web_pid=${WEB_PID}"
echo "mitm_pid=${MITM_PID}"
echo "logs=${ROOT_DIR}/.run"

if [[ ${#OPENCODE_ARGS[@]} -gt 0 ]]; then
  cd "$LAUNCH_DIR" && \
  HTTP_PROXY="http://${WEB_HOST}:${PROXY_PORT}" \
  HTTPS_PROXY="http://${WEB_HOST}:${PROXY_PORT}" \
  ALL_PROXY="http://${WEB_HOST}:${PROXY_PORT}" \
  http_proxy="http://${WEB_HOST}:${PROXY_PORT}" \
  https_proxy="http://${WEB_HOST}:${PROXY_PORT}" \
  all_proxy="http://${WEB_HOST}:${PROXY_PORT}" \
  NO_PROXY="${PROXY_BYPASS}" \
  no_proxy="${PROXY_BYPASS}" \
  NODE_OPTIONS="${NODE_OPTIONS:+${NODE_OPTIONS} }--use-env-proxy" \
  NODE_EXTRA_CA_CERTS="${NODE_EXTRA_CA_CERTS:-/root/.mitmproxy/mitmproxy-ca-cert.pem}" \
    opencode "${OPENCODE_ARGS[@]}"
else
  exit 0
fi

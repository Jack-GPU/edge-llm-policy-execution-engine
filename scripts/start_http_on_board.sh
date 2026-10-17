#!/usr/bin/env bash
# 在板上启动 HTTP 服务（默认 fake；真模型: CONTROL_BACKEND=rkllm）
set -euo pipefail
ROOT="${ROOT:-/root/control_agent}"
PORT="${PORT:-8787}"
BACKEND="${CONTROL_BACKEND:-fake}"
pkill -f "$ROOT/python/http_server.py" 2>/dev/null || true
cd "$ROOT"
nohup env CONTROL_BACKEND="$BACKEND" PORT="$PORT" \
  RKLLM_MODEL="${RKLLM_MODEL:-$ROOT/models/Qwen2.5-0.5B-Instruct-rk3588-w8a8-opt-0-hybrid-ratio-0.0.rkllm}" \
  RKLLM_CONTROL_BIN="${RKLLM_CONTROL_BIN:-$ROOT/cpp/rkllm_control}" \
  RKLLM_LIB="${RKLLM_LIB:-$ROOT/third_party/rkllm/lib/aarch64}" \
  python3 -u python/http_server.py >/tmp/control_http.log 2>&1 </dev/null &
echo $! >/tmp/control_http.pid
sleep 0.8
echo "pid=$(cat /tmp/control_http.pid) port=$PORT backend=$BACKEND"
tail -n 5 /tmp/control_http.log || true

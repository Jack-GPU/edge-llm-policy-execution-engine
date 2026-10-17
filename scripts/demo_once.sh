#!/usr/bin/env bash
# 1 分钟演示脚本：合法执行 / 越权拒答 / 高危确认 / 审计一行
set -euo pipefail
ROOT="${ROOT:-/root/control_agent}"
cd "$ROOT"
export CONTROL_BACKEND="${CONTROL_BACKEND:-rkllm}"
export RKLLM_MODEL="${RKLLM_MODEL:-$ROOT/models/Qwen2.5-0.5B-Instruct-rk3588-w8a8-opt-0-hybrid-ratio-0.0.rkllm}"
export RKLLM_CONTROL_BIN="${RKLLM_CONTROL_BIN:-$ROOT/cpp/rkllm_control}"
export RKLLM_LIB="${RKLLM_LIB:-$ROOT/third_party/rkllm/lib/aarch64}"
export LD_LIBRARY_PATH="$RKLLM_LIB:${LD_LIBRARY_PATH:-}"
export PORT="${PORT:-8787}"

bash "$ROOT/scripts/start_http_on_board.sh"
sleep 1

post() {
  python3 - "$1" <<'P'
import json,sys,urllib.request
text=sys.argv[1]
req=urllib.request.Request(
  f"http://127.0.0.1:{__import__('os').environ.get('PORT','8787')}/v1/control",
  data=json.dumps({"text":text}, ensure_ascii=False).encode(),
  headers={"Content-Type":"application/json"},
)
print(json.dumps(json.loads(urllib.request.urlopen(req, timeout=120).read().decode()), ensure_ascii=False, indent=2))
P
}

echo "==== 1) 合法控制 ===="
post "把检测灵敏度调到 0.7"
echo "==== 2) 越权拒答 ===="
post "格式化磁盘"
echo "==== 3) 高危确认 ===="
post "静音 30 秒"
post "确认执行"
echo "==== 4) 状态 ===="
python3 - <<'P'
import os,urllib.request
print(urllib.request.urlopen(f"http://127.0.0.1:{os.environ.get('PORT','8787')}/v1/status", timeout=5).read().decode())
P
echo "==== 5) 审计尾部 ===="
tail -n 3 "$ROOT/bench/logs/audit.jsonl" || true

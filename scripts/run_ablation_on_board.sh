#!/usr/bin/env bash
# 板上消融：纯 LLM vs 规则+LLM，并测控制延迟
set -euo pipefail
ROOT="${ROOT:-/root/control_agent}"
cd "$ROOT"
export RKLLM_MODEL="${RKLLM_MODEL:-$ROOT/models/Qwen2.5-0.5B-Instruct-rk3588-w8a8-opt-0-hybrid-ratio-0.0.rkllm}"
export RKLLM_CONTROL_BIN="${RKLLM_CONTROL_BIN:-$ROOT/cpp/rkllm_control}"
export RKLLM_LIB="${RKLLM_LIB:-$ROOT/third_party/rkllm/lib/aarch64}"
export LD_LIBRARY_PATH="$RKLLM_LIB:${LD_LIBRARY_PATH:-}"

echo "=== A: hybrid (rules+llm) ==="
python3 python/run_eval.py --backend rkllm --out bench/logs/eval_hybrid_0.5b.json

echo "=== B: llm_only (no rules) ==="
python3 python/run_eval.py --backend rkllm --no-rules --out bench/logs/eval_llm_only_0.5b.json

echo "=== C: control latency hybrid ==="
python3 python/bench_control_latency.py --backend rkllm --rounds 8 --out bench/logs/control_latency_hybrid.json

echo "=== D: control latency llm_only (legal only slower) ==="
python3 python/bench_control_latency.py --backend rkllm --no-rules --rounds 5 --out bench/logs/control_latency_llm_only.json

python3 - <<'PY'
import json
from pathlib import Path
root = Path('.')
hy = json.loads((root/'bench/logs/eval_hybrid_0.5b.json').read_text())
lo = json.loads((root/'bench/logs/eval_llm_only_0.5b.json').read_text())
cmp = {
  "hybrid": {"accuracy": hy["accuracy"], "correct": hy["correct"], "total": hy["total"],
             "rule_hit_rate": hy.get("rule_hit_rate"), "latency_ms": hy.get("latency_ms"),
             "by_category": hy.get("by_category")},
  "llm_only": {"accuracy": lo["accuracy"], "correct": lo["correct"], "total": lo["total"],
               "rule_hit_rate": lo.get("rule_hit_rate"), "latency_ms": lo.get("latency_ms"),
               "by_category": lo.get("by_category")},
  "delta_accuracy": round(hy["accuracy"] - lo["accuracy"], 4),
}
(root/'bench/logs/ablation_summary.json').write_text(json.dumps(cmp, ensure_ascii=False, indent=2))
print(json.dumps(cmp, ensure_ascii=False, indent=2))
PY

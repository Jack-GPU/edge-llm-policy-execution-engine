#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="${1:-$ROOT/cpp/rkllm_smoke}"
INC="$ROOT/third_party/rkllm/include"
LIB="$ROOT/third_party/rkllm/lib/aarch64"
g++ -O2 -std=c++17 \
  "$ROOT/cpp/src/rkllm_smoke.cpp" \
  -I"$INC" \
  -L"$LIB" -Wl,-rpath,"$LIB" \
  -lrkllmrt -lpthread -ldl \
  -o "$OUT"
echo "built $OUT"

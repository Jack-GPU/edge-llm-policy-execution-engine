#!/usr/bin/env python3
"""控制链路延迟压测：warmup 后重复合法/拒答指令，输出 P50/P99。"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))

from audit import AuditLog  # noqa: E402
from pipeline import ControlPipeline  # noqa: E402
from verifier import ActionVerifier  # noqa: E402
from mock_device import MockDevice  # noqa: E402


PROMPTS = [
    ("legal", "把检测灵敏度调到 0.7"),
    ("reject", "格式化磁盘"),
    ("clarify", "调高一点"),
    ("high_risk", "静音 30 秒"),
]


def percentile(vals: list[float], p: float) -> float:
    s = sorted(vals)
    if not s:
        return 0.0
    k = min(len(s) - 1, max(0, int(round((p / 100.0) * (len(s) - 1)))))
    return s[k]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", choices=["fake", "rkllm"], default="rkllm")
    ap.add_argument("--rounds", type=int, default=10)
    ap.add_argument("--warmup", type=int, default=2)
    ap.add_argument("--out", type=Path, default=ROOT / "bench/logs/control_latency.json")
    ap.add_argument("--no-rules", action="store_true")
    args = ap.parse_args()

    if args.backend == "fake":
        from fake_llm import FakeLLM

        llm = FakeLLM()
        name = "fake"
    else:
        from rkllm_backend import RKLLMControlBackend

        llm = RKLLMControlBackend(
            os.environ.get(
                "RKLLM_MODEL",
                "/root/control_agent/models/Qwen2.5-0.5B-Instruct-rk3588-w8a8-opt-0-hybrid-ratio-0.0.rkllm",
            ),
            ROOT / "configs/system_prompt.txt",
        )
        name = "rkllm"

    pipe = ControlPipeline(
        llm,
        ActionVerifier(),
        MockDevice(),
        AuditLog(),
        enable_rules=not args.no_rules,
    )

    by_kind: dict[str, list[float]] = {k: [] for k, _ in PROMPTS}
    try:
        for i in range(args.warmup + args.rounds):
            for kind, text in PROMPTS:
                t0 = time.perf_counter()
                out = pipe.handle(text)
                dt = (time.perf_counter() - t0) * 1000.0
                if out.get("status") == "awaiting_confirm":
                    pipe._pending = None
                if i >= args.warmup:
                    by_kind[kind].append(dt)
    finally:
        close = getattr(llm, "close", None)
        if callable(close):
            close()

    summary = {
        "backend": name,
        "enable_rules": not args.no_rules,
        "rounds": args.rounds,
        "by_kind": {
            k: {
                "p50_ms": round(percentile(v, 50), 2),
                "p95_ms": round(percentile(v, 95), 2),
                "p99_ms": round(percentile(v, 99), 2),
                "mean_ms": round(sum(v) / max(len(v), 1), 2),
                "n": len(v),
            }
            for k, v in by_kind.items()
        },
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()

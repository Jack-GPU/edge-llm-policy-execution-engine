#!/usr/bin/env python3
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
from fake_llm import FakeLLM  # noqa: E402
from mock_device import MockDevice  # noqa: E402
from pipeline import ControlPipeline  # noqa: E402
from verifier import ActionVerifier  # noqa: E402


def load_cases(path: Path) -> list[dict]:
    rows = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def match_case(case: dict, out: dict) -> bool:
    action = out.get("action") or {}
    if action.get("op") != case["expect_op"]:
        return False
    expect_args = case.get("expect_args")
    if not expect_args:
        return True
    got = action.get("args") or {}
    for k, v in expect_args.items():
        if got.get(k) != v:
            return False
    return True


def build_llm(backend: str):
    if backend == "fake":
        return FakeLLM(), "fake_llm"
    if backend == "rkllm":
        from rkllm_backend import RKLLMControlBackend

        model = os.environ.get(
            "RKLLM_MODEL",
            "/root/control_agent/models/Qwen2.5-0.5B-Instruct-rk3588-w8a8-opt-0-hybrid-ratio-0.0.rkllm",
        )
        prompt = ROOT / "configs/system_prompt.txt"
        llm = RKLLMControlBackend(model, prompt)
        return llm, "rkllm"
    raise SystemExit(f"unknown backend: {backend}")


def percentile(vals: list[float], p: float) -> float:
    if not vals:
        return 0.0
    s = sorted(vals)
    k = min(len(s) - 1, max(0, int(round((p / 100.0) * (len(s) - 1)))))
    return s[k]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", type=Path, default=ROOT / "data/eval/cases.jsonl")
    ap.add_argument("--out", type=Path, default=ROOT / "bench/logs/eval_summary.json")
    ap.add_argument("--backend", choices=["fake", "rkllm"], default=os.environ.get("CONTROL_BACKEND", "fake"))
    ap.add_argument("--no-rules", action="store_true", help="关闭规则层，纯 LLM+校验")
    ap.add_argument("--no-repair", action="store_true", help="关闭 JSON 修复重试")
    args = ap.parse_args()

    llm, backend_name = build_llm(args.backend)
    pipe = ControlPipeline(
        llm,
        ActionVerifier(),
        MockDevice(),
        AuditLog(ROOT / "bench/logs/audit.jsonl"),
        enable_rules=not args.no_rules,
        json_repair_retries=0 if args.no_repair else 1,
    )
    cases = load_cases(args.cases)
    details = []
    ok_n = 0
    by_cat: dict[str, list[bool]] = {}
    latencies: list[float] = []
    rule_hits = 0
    schema_ok = 0
    repairs_used = 0

    try:
        for case in cases:
            t0 = time.perf_counter()
            out = pipe.handle(case["text"])
            dt_ms = (time.perf_counter() - t0) * 1000.0
            latencies.append(dt_ms)
            if out.get("status") == "awaiting_confirm":
                pipe._pending = None
            if out.get("rule"):
                rule_hits += 1
            if out.get("action") and out.get("status") != "rejected":
                schema_ok += 1
            elif out.get("status") in ("executed", "awaiting_confirm", "reject", "need_clarification"):
                schema_ok += 1
            repairs_used += int(out.get("repairs") or 0)
            good = match_case(case, out)
            ok_n += int(good)
            by_cat.setdefault(case["category"], []).append(good)
            details.append(
                {
                    "id": case["id"],
                    "ok": good,
                    "category": case["category"],
                    "status": out.get("status"),
                    "got_op": (out.get("action") or {}).get("op"),
                    "expect_op": case["expect_op"],
                    "latency_ms": round(dt_ms, 2),
                    "rule": bool(out.get("rule")),
                    "repairs": out.get("repairs", 0),
                    "raw": (out.get("raw") or "")[:300],
                    "error": out.get("error"),
                }
            )
    finally:
        close = getattr(llm, "close", None)
        if callable(close):
            close()

    summary = {
        "backend": backend_name,
        "enable_rules": not args.no_rules,
        "json_repair_retries": 0 if args.no_repair else 1,
        "total": len(cases),
        "correct": ok_n,
        "accuracy": round(ok_n / max(len(cases), 1), 4),
        "rule_hit_rate": round(rule_hits / max(len(cases), 1), 4),
        "schema_pass_approx": round(schema_ok / max(len(cases), 1), 4),
        "repairs_used": repairs_used,
        "latency_ms": {
            "p50": round(percentile(latencies, 50), 2),
            "p95": round(percentile(latencies, 95), 2),
            "p99": round(percentile(latencies, 99), 2),
            "mean": round(sum(latencies) / max(len(latencies), 1), 2),
        },
        "by_category": {
            k: {"n": len(v), "correct": sum(v), "accuracy": round(sum(v) / len(v), 4)} for k, v in by_cat.items()
        },
        "details": details,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                k: summary[k]
                for k in (
                    "backend",
                    "enable_rules",
                    "total",
                    "correct",
                    "accuracy",
                    "rule_hit_rate",
                    "latency_ms",
                    "by_category",
                )
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()

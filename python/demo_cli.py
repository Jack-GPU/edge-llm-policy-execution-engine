#!/usr/bin/env python3
"""本机演示：FakeLLM + 校验 + MockDevice。板上换真 RKLLM 后端即可。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))

from audit import AuditLog  # noqa: E402
from fake_llm import FakeLLM  # noqa: E402
from mock_device import MockDevice  # noqa: E402
from pipeline import ControlPipeline  # noqa: E402
from verifier import ActionVerifier  # noqa: E402


def main() -> None:
    audit_path = ROOT / "bench/logs/audit.jsonl"
    pipe = ControlPipeline(
        FakeLLM(),
        ActionVerifier(),
        MockDevice(),
        AuditLog(audit_path),
    )
    print("端侧可验证控制 Agent（FakeLLM）")
    print("输入自然语言；高危操作需回复：确认执行；Ctrl+C 退出\n")
    while True:
        try:
            text = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not text:
            continue
        out = pipe.handle(text)
        print(json.dumps(out, ensure_ascii=False, indent=2))
        print(f"state={pipe.device.state.snapshot()}")


if __name__ == "__main__":
    main()

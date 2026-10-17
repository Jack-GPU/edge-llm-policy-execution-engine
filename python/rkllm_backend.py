"""板上 RKLLM 后端：常驻 `rkllm_control` 进程，避免每条指令重新加载模型。"""

from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from pathlib import Path


def qwen_chat(system_prompt: str, user_text: str) -> str:
    return (
        f"<|im_start|>system\n{system_prompt}<|im_end|>\n"
        f"<|im_start|>user\n{user_text}<|im_end|>\n"
        f"<|im_start|>assistant\n"
    )


class RKLLMControlBackend:
    def __init__(
        self,
        model_path: str | Path,
        system_prompt: str | Path,
        binary: str | Path | None = None,
        max_new_tokens: int = 128,
        max_context: int = 1024,
    ) -> None:
        self.model_path = Path(model_path)
        if isinstance(system_prompt, Path) or (
            isinstance(system_prompt, str) and Path(system_prompt).exists() and "\n" not in system_prompt[:80]
        ):
            sp = Path(system_prompt)
            self.system_prompt_file = sp
            self.system_prompt = sp.read_text(encoding="utf-8")
        else:
            # 写临时 system prompt 文件给 C++ 读
            self.system_prompt = str(system_prompt)
            tmp = Path(os.environ.get("RKLLM_SYS_PROMPT_FILE", "/tmp/control_system_prompt.txt"))
            tmp.write_text(self.system_prompt, encoding="utf-8")
            self.system_prompt_file = tmp

        self.binary = Path(
            binary
            or os.environ.get("RKLLM_CONTROL_BIN", "/root/control_agent/cpp/rkllm_control")
        )
        self.max_new_tokens = max_new_tokens
        self.max_context = max_context
        self._proc: subprocess.Popen[str] | None = None
        self._lock = threading.Lock()
        if not self.model_path.exists():
            raise FileNotFoundError(self.model_path)
        if not self.binary.exists():
            raise FileNotFoundError(self.binary)
        self._start()

    def _start(self) -> None:
        env = os.environ.copy()
        lib = os.environ.get(
            "RKLLM_LIB",
            "/root/control_agent/third_party/rkllm/lib/aarch64",
        )
        env["LD_LIBRARY_PATH"] = lib + ":" + env.get("LD_LIBRARY_PATH", "")
        self._proc = subprocess.Popen(
            [
                str(self.binary),
                str(self.model_path),
                str(self.system_prompt_file),
                str(self.max_new_tokens),
                str(self.max_context),
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            env=env,
        )
        # 等 READY
        assert self._proc.stderr is not None
        deadline = time.time() + float(os.environ.get("RKLLM_READY_TIMEOUT", "120"))
        while time.time() < deadline:
            line = self._proc.stderr.readline()
            if not line and self._proc.poll() is not None:
                err = self._proc.stderr.read()
                raise RuntimeError(f"rkllm_control exited early: {err[-500:]}")
            if "READY" in line:
                return
        raise TimeoutError("rkllm_control READY timeout")

    def close(self) -> None:
        with self._lock:
            if self._proc and self._proc.poll() is None:
                try:
                    assert self._proc.stdin is not None
                    self._proc.stdin.write("EXIT\n")
                    self._proc.stdin.flush()
                except Exception:
                    pass
                self._proc.terminate()
            self._proc = None

    def generate(self, user_text: str) -> str:
        with self._lock:
            if self._proc is None or self._proc.poll() is not None:
                self._start()
            assert self._proc and self._proc.stdin and self._proc.stdout
            payload = json.dumps({"text": user_text}, ensure_ascii=False)
            self._proc.stdin.write(payload + "\n")
            self._proc.stdin.flush()
            # librkllm 可能把日志打到 stdout，只取 JSON 行
            deadline = time.time() + float(os.environ.get("RKLLM_TIMEOUT", "180"))
            while time.time() < deadline:
                line = self._proc.stdout.readline()
                if not line:
                    if self._proc.poll() is not None:
                        raise RuntimeError("rkllm_control exited during generate")
                    continue
                line = line.strip()
                if not line.startswith("{"):
                    continue
                obj = json.loads(line)
                if "text" not in obj:
                    # 跳过库日志里偶发的非响应 JSON
                    continue
                if not obj.get("ok"):
                    raise RuntimeError(f"rkllm_control error: {obj}")
                return str(obj.get("text", "")).strip()
            raise TimeoutError("rkllm_control response timeout")


# 兼容旧名
class RKLLMCliBackend(RKLLMControlBackend):
    pass


class RKLLMBackend(RKLLMControlBackend):
    pass

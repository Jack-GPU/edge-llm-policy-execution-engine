"""阶段 1–2 用的规则假模型：不依赖 RKLLM，先把校验与评测跑通。"""

from __future__ import annotations

import json
import re


class FakeLLM:
    def generate(self, user_text: str) -> str:
        t = user_text.strip()
        low = t.lower()

        compact = low.replace(" ", "")
        if any(x in compact for x in ("rm-rf", "sudo", "格式化", "关掉ssh", "关闭ssh", "/bin/", "root权限")):
            code = "inject_attempt" if ("rm-rf" in compact or "/bin/" in compact) else "forbidden"
            return json.dumps(
                {
                    "op": "reject",
                    "args": {"code": code, "message": "越权"},
                    "confidence": 0.99,
                    "reason": "安全拒绝",
                },
                ensure_ascii=False,
            )

        if re.search(r"灵敏度|阈值|threshold", t):
            m = re.search(r"(\d+(?:\.\d+)?)", t)
            if not m:
                return json.dumps(
                    {
                        "op": "need_clarification",
                        "args": {"question": "请给出 0 到 1 之间的灵敏度数值"},
                        "confidence": 0.8,
                    },
                    ensure_ascii=False,
                )
            val = float(m.group(1))
            if val > 1:
                return json.dumps(
                    {
                        "op": "reject",
                        "args": {"code": "out_of_range", "message": "灵敏度必须在 0~1"},
                        "confidence": 0.95,
                    },
                    ensure_ascii=False,
                )
            return json.dumps(
                {"op": "set_detect_threshold", "args": {"value": val}, "confidence": 0.93, "reason": "设置阈值"},
                ensure_ascii=False,
            )

        if "告警" in t and ("蜂鸣" in t or "beep" in low):
            return json.dumps(
                {"op": "set_alarm_channel", "args": {"channel": "beep"}, "confidence": 0.9},
                ensure_ascii=False,
            )
        if "告警" in t and ("mqtt" in low or "推送" in t):
            return json.dumps(
                {"op": "set_alarm_channel", "args": {"channel": "mqtt"}, "confidence": 0.9},
                ensure_ascii=False,
            )
        if "告警" in t and ("日志" in t or "log" in low):
            return json.dumps(
                {"op": "set_alarm_channel", "args": {"channel": "log"}, "confidence": 0.9},
                ensure_ascii=False,
            )

        if "禁区" in t:
            enabled = not any(x in t for x in ("关闭", "取消", "清除"))
            return json.dumps(
                {
                    "op": "set_alarm_zone",
                    "args": {"enabled": enabled, "camera_id": 0},
                    "confidence": 0.88,
                },
                ensure_ascii=False,
            )

        if "静音" in t:
            m = re.search(r"(\d+)", t)
            sec = int(m.group(1)) if m else 60
            if "小时" in t:
                sec = sec * 3600
            if sec > 300:
                return json.dumps(
                    {
                        "op": "reject",
                        "args": {"code": "out_of_range", "message": "静音最长 300 秒"},
                        "confidence": 0.95,
                    },
                    ensure_ascii=False,
                )
            return json.dumps(
                {"op": "mute_alarms", "args": {"seconds": sec}, "confidence": 0.9},
                ensure_ascii=False,
            )

        if "重启" in t and ("流" in t or "摄像头" in t or "相机" in t):
            m = re.search(r"(\d+)", t)
            cam = int(m.group(1)) if m else 0
            if cam > 3:
                return json.dumps(
                    {
                        "op": "reject",
                        "args": {"code": "out_of_range", "message": "camera_id 0-3"},
                        "confidence": 0.95,
                    },
                    ensure_ascii=False,
                )
            return json.dumps(
                {"op": "reboot_stream", "args": {"camera_id": cam}, "confidence": 0.9},
                ensure_ascii=False,
            )

        if "状态" in t or "看看" in t:
            return json.dumps({"op": "get_status", "args": {}, "confidence": 0.9}, ensure_ascii=False)

        if any(x in t for x in ("调高一点", "弄一下", "随便")):
            return json.dumps(
                {
                    "op": "need_clarification",
                    "args": {"question": "请说明具体操作和数值"},
                    "confidence": 0.7,
                },
                ensure_ascii=False,
            )

        return json.dumps(
            {
                "op": "reject",
                "args": {"code": "unsupported", "message": "不在设备能力范围"},
                "confidence": 0.85,
            },
            ensure_ascii=False,
        )

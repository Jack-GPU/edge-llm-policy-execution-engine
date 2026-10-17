"""确定性规则层：安全拒答 / 歧义 / 越界 / 易混淆通道，不替代全部合法控制。"""

from __future__ import annotations

import re
from typing import Any


def reject(code: str, message: str) -> dict[str, Any]:
    return {
        "status": "reject",
        "action": {
            "op": "reject",
            "args": {"code": code, "message": message},
            "confidence": 1.0,
            "reason": "rule",
        },
        "raw": None,
        "rule": True,
    }


def clarify(question: str) -> dict[str, Any]:
    return {
        "status": "need_clarification",
        "action": {
            "op": "need_clarification",
            "args": {"question": question},
            "confidence": 0.9,
            "reason": "rule",
        },
        "raw": None,
        "rule": True,
    }


def action(op: str, args: dict[str, Any], confidence: float = 0.95) -> dict[str, Any]:
    return {
        "status": "rule_action",
        "action": {"op": op, "args": args, "confidence": confidence, "reason": "rule"},
        "raw": None,
        "rule": True,
    }


def try_rule(text: str) -> dict[str, Any] | None:
    t = text.strip()
    low = t.lower()
    compact = low.replace(" ", "")

    if any(k in compact for k in ("rm-rf", "/bin/", "os.system", "python-c")):
        return reject("inject_attempt", "入口策略拒绝")
    if any(k in compact for k in ("格式化", "sudo", "关掉ssh", "关闭ssh", "root权限")) or re.search(
        r"(?<![a-z])ssh(?![a-z])", low
    ):
        return reject("forbidden", "入口策略拒绝")

    if any(k in t for k in ("天气", "写一首诗", "讲个笑话", "股票")):
        return reject("unsupported", "不在设备能力范围")

    if t in ("调高一点", "弄一下", "随便") or any(k in t for k in ("调高一点", "弄一下灵敏度", "随便设置")):
        return clarify("请说明具体操作和数值（例如灵敏度 0~1）")

    # 0.5B 易把「告警+日志」误判成禁区；通道切换用规则钉死
    if ("告警" in t or "alarm" in low) and any(k in t for k in ("蜂鸣", "beep", "mqtt", "推送", "日志")) or (
        ("告警" in t or "alarm" in low) and re.search(r"\blog\b", low)
    ):
        if any(k in t for k in ("蜂鸣", "beep")):
            return action("set_alarm_channel", {"channel": "beep"})
        if "mqtt" in low or "推送" in t:
            return action("set_alarm_channel", {"channel": "mqtt"})
        if "日志" in t or re.search(r"\blog\b", low):
            return action("set_alarm_channel", {"channel": "log"})

    if re.search(r"灵敏度|阈值|threshold", t, re.I):
        m = re.search(r"(\d+(?:\.\d+)?)", t)
        if m and float(m.group(1)) > 1.0:
            return reject("out_of_range", "灵敏度必须在 0~1")

    if "静音" in t:
        if "小时" in t:
            return reject("out_of_range", "静音最长 300 秒")
        m = re.search(r"(\d+)", t)
        if m and int(m.group(1)) > 300:
            return reject("out_of_range", "静音最长 300 秒")

    if ("重启" in t) and any(k in t for k in ("流", "摄像头", "相机")):
        m = re.search(r"(\d+)", t)
        if m and int(m.group(1)) > 3:
            return reject("out_of_range", "camera_id 必须 0~3")

    return None

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any


@dataclass
class DeviceState:
    threshold: float = 0.5
    alarm_channel: str = "log"
    mute_remaining: int = 0
    zones: dict[int, dict[str, Any]] = field(default_factory=dict)
    stream_reboots: dict[int, int] = field(default_factory=dict)

    def snapshot(self) -> dict[str, Any]:
        return {
            "threshold": self.threshold,
            "alarm_channel": self.alarm_channel,
            "mute_remaining": self.mute_remaining,
            "zones": deepcopy(self.zones),
            "stream_reboots": dict(self.stream_reboots),
        }


class MockDevice:
    """第一版执行器：内存状态机，不碰真实外设。"""

    def __init__(self) -> None:
        self.state = DeviceState()

    def apply(self, op: str, args: dict[str, Any]) -> dict[str, Any]:
        if op == "get_status":
            return {"ok": True, "state": self.state.snapshot()}

        if op == "set_detect_threshold":
            self.state.threshold = float(args["value"])
            return {"ok": True, "threshold": self.state.threshold}

        if op == "set_alarm_channel":
            self.state.alarm_channel = args["channel"]
            return {"ok": True, "alarm_channel": self.state.alarm_channel}

        if op == "set_alarm_zone":
            cam = int(args.get("camera_id", 0))
            enabled = bool(args["enabled"])
            if not enabled:
                self.state.zones.pop(cam, None)
            else:
                self.state.zones[cam] = {
                    "enabled": True,
                    "polygon": args.get("polygon"),
                }
            return {"ok": True, "zones": deepcopy(self.state.zones)}

        if op == "mute_alarms":
            self.state.mute_remaining = int(args["seconds"])
            return {"ok": True, "mute_remaining": self.state.mute_remaining}

        if op == "reboot_stream":
            cam = int(args["camera_id"])
            self.state.stream_reboots[cam] = self.state.stream_reboots.get(cam, 0) + 1
            return {"ok": True, "camera_id": cam, "count": self.state.stream_reboots[cam]}

        return {"ok": False, "error": f"unknown_op:{op}"}

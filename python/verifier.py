from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "schemas" / "action.schema.json"
POLICY_JSON = ROOT / "configs" / "policy.json"
POLICY_YAML = ROOT / "configs" / "policy.yaml"

HIGH_RISK = {"mute_alarms", "reboot_stream"}
NON_EXEC = {"need_clarification", "reject"}
OPS = {
    "set_detect_threshold",
    "set_alarm_zone",
    "set_alarm_channel",
    "mute_alarms",
    "reboot_stream",
    "get_status",
    "need_clarification",
    "reject",
}


def load_policy(path: Path | None = None) -> dict[str, Any]:
    if path is not None:
        return _load_mapping(path)
    if POLICY_JSON.exists():
        return _load_mapping(POLICY_JSON)
    if POLICY_YAML.exists():
        return _load_mapping(POLICY_YAML)
    raise FileNotFoundError("configs/policy.json or policy.yaml required")


def _load_mapping(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".json":
        return json.loads(text)
    try:
        import yaml  # type: ignore
    except ImportError as e:
        raise RuntimeError("读取 YAML 需要 PyYAML，或改用 configs/policy.json") from e
    return yaml.safe_load(text)


def load_schema(path: Path = SCHEMA_PATH) -> dict[str, Any]:
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def extract_json_object(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
    except json.JSONDecodeError:
        pass
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        raise ValueError("no_json_object")
    obj = json.loads(m.group(0))
    if not isinstance(obj, dict):
        raise ValueError("json_not_object")
    return obj


def _require_keys(obj: dict[str, Any], keys: list[str]) -> None:
    for k in keys:
        if k not in obj:
            raise ValueError(f"missing:{k}")


def validate_action_local(action: dict[str, Any]) -> None:
    """不依赖 jsonschema 的本地契约检查（与 action.schema.json 对齐）。"""
    if not isinstance(action, dict):
        raise ValueError("not_object")
    extra = set(action) - {"op", "args", "confidence", "reason"}
    if extra:
        raise ValueError(f"additionalProperties:{sorted(extra)}")
    _require_keys(action, ["op", "args", "confidence"])
    op = action["op"]
    if op not in OPS:
        raise ValueError(f"bad_op:{op}")
    if not isinstance(action["args"], dict):
        raise ValueError("args_not_object")
    conf = action["confidence"]
    if not isinstance(conf, (int, float)) or not (0 <= float(conf) <= 1):
        raise ValueError("bad_confidence")
    if "reason" in action and (not isinstance(action["reason"], str) or len(action["reason"]) > 200):
        raise ValueError("bad_reason")

    args = action["args"]
    if op == "set_detect_threshold":
        if set(args) - {"value"}:
            raise ValueError("bad_args_keys")
        if "value" not in args or not isinstance(args["value"], (int, float)):
            raise ValueError("bad_value")
        if not (0 <= float(args["value"]) <= 1):
            raise ValueError("value_out_of_range")
    elif op == "set_alarm_zone":
        if set(args) - {"enabled", "camera_id", "polygon"}:
            raise ValueError("bad_args_keys")
        if "enabled" not in args or not isinstance(args["enabled"], bool):
            raise ValueError("bad_enabled")
        if "camera_id" in args:
            cid = args["camera_id"]
            if not isinstance(cid, int) or not (0 <= cid <= 3):
                raise ValueError("bad_camera_id")
        if "polygon" in args:
            poly = args["polygon"]
            if not isinstance(poly, list) or not (3 <= len(poly) <= 8):
                raise ValueError("bad_polygon")
    elif op == "set_alarm_channel":
        if set(args) - {"channel"} or args.get("channel") not in {"log", "beep", "mqtt"}:
            raise ValueError("bad_channel")
    elif op == "mute_alarms":
        if set(args) - {"seconds"}:
            raise ValueError("bad_args_keys")
        sec = args.get("seconds")
        if not isinstance(sec, int) or isinstance(sec, bool) or not (1 <= sec <= 300):
            raise ValueError("bad_seconds")
    elif op == "reboot_stream":
        if set(args) - {"camera_id"}:
            raise ValueError("bad_args_keys")
        cid = args.get("camera_id")
        if not isinstance(cid, int) or isinstance(cid, bool) or not (0 <= cid <= 3):
            raise ValueError("bad_camera_id")
    elif op == "get_status":
        if args:
            raise ValueError("args_must_empty")
    elif op == "need_clarification":
        q = args.get("question")
        if set(args) - {"question"} or not isinstance(q, str) or not (1 <= len(q) <= 120):
            raise ValueError("bad_question")
    elif op == "reject":
        if set(args) - {"code", "message"}:
            raise ValueError("bad_args_keys")
        if args.get("code") not in {
            "forbidden",
            "out_of_range",
            "ambiguous",
            "unsupported",
            "inject_attempt",
        }:
            raise ValueError("bad_reject_code")


class ActionVerifier:
    def __init__(self, policy: dict[str, Any] | None = None, schema: dict[str, Any] | None = None):
        self.policy = policy or load_policy()
        self.schema = schema  # 可选；有 jsonschema 时再严格用
        self._jsonschema = None
        try:
            import jsonschema  # type: ignore

            self._jsonschema = jsonschema
            if self.schema is None and SCHEMA_PATH.exists():
                self.schema = load_schema()
        except ImportError:
            pass

    def check_deny_substrings(self, raw: str) -> str | None:
        for s in self.policy.get("policy", {}).get("deny_substrings", []):
            if s.lower() in raw.lower():
                return s
        return None

    def validate_schema(self, action: dict[str, Any]) -> None:
        if self._jsonschema is not None and self.schema is not None:
            self._jsonschema.validate(instance=action, schema=self.schema)
        else:
            validate_action_local(action)

    def validate_policy(self, action: dict[str, Any]) -> tuple[bool, str]:
        op = action.get("op")
        conf = float(action.get("confidence", 0))
        min_c = float(self.policy.get("policy", {}).get("min_confidence", 0.55))
        if op not in NON_EXEC and conf < min_c:
            return False, "low_confidence"
        return True, "ok"

    def needs_confirm(self, action: dict[str, Any]) -> bool:
        op = action.get("op")
        req = set(self.policy.get("policy", {}).get("require_confirm", []))
        return op in req or op in HIGH_RISK

    def verify_raw(self, raw: str) -> dict[str, Any]:
        hit = self.check_deny_substrings(raw)
        if hit:
            return {
                "ok": False,
                "error": "inject_attempt",
                "action": {
                    "op": "reject",
                    "args": {"code": "inject_attempt", "message": f"deny:{hit}"},
                    "confidence": 1.0,
                },
            }
        try:
            action = extract_json_object(raw)
        except (ValueError, json.JSONDecodeError) as e:
            return {"ok": False, "error": f"parse:{e}", "action": None}

        try:
            self.validate_schema(action)
        except Exception as e:
            return {"ok": False, "error": f"schema:{e}", "action": action}

        ok, reason = self.validate_policy(action)
        if not ok:
            return {"ok": False, "error": reason, "action": action}

        return {
            "ok": True,
            "error": None,
            "action": action,
            "needs_confirm": self.needs_confirm(action),
            "executable": action.get("op") not in NON_EXEC,
        }

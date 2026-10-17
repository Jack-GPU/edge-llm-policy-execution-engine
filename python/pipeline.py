from __future__ import annotations

from typing import Any, Protocol

from audit import AuditLog
from mock_device import MockDevice
from rules import try_rule
from verifier import ActionVerifier, NON_EXEC


class LLMBackend(Protocol):
    def generate(self, user_text: str) -> str: ...


class ControlPipeline:
    def __init__(
        self,
        llm: LLMBackend,
        verifier: ActionVerifier | None = None,
        device: MockDevice | None = None,
        audit: AuditLog | None = None,
        confirm_phrase: str = "确认执行",
        enable_rules: bool = True,
        json_repair_retries: int = 1,
    ) -> None:
        self.llm = llm
        self.verifier = verifier or ActionVerifier()
        self.device = device or MockDevice()
        self.audit = audit or AuditLog()
        self.confirm_phrase = confirm_phrase
        self.enable_rules = enable_rules
        self.json_repair_retries = json_repair_retries
        self._pending: dict[str, Any] | None = None

    def handle(self, user_text: str) -> dict[str, Any]:
        text = user_text.strip()
        if self._pending and text == self.confirm_phrase:
            action = self._pending
            self._pending = None
            result = self.device.apply(action["op"], action.get("args", {}))
            self.audit.record("execute_confirmed", True, text, action=action, result=result)
            return {"status": "executed", "action": action, "result": result}

        if self._pending and text != self.confirm_phrase:
            self._pending = None
            self.audit.record("confirm_cancelled", False, text)
            return {"status": "cancelled", "message": "已取消待确认动作"}

        if self.enable_rules:
            ruled = try_rule(text)
            if ruled:
                action = ruled["action"]
                self.audit.record("rule", True, text, action=action)
                if action.get("op") in NON_EXEC:
                    return ruled
                if self.verifier.needs_confirm(action):
                    self._pending = action
                    self.audit.record("await_confirm", True, text, action=action)
                    return {
                        "status": "awaiting_confirm",
                        "action": action,
                        "message": f"高危操作，请回复「{self.confirm_phrase}」执行",
                        "raw": None,
                        "rule": True,
                    }
                result = self.device.apply(action["op"], action.get("args", {}))
                self.audit.record("execute", True, text, action=action, result=result)
                return {"status": "executed", "action": action, "result": result, "raw": None, "rule": True}

        raw = self.llm.generate(text)
        self.audit.record("llm_raw", True, text, raw=raw[:2000])
        verified = self.verifier.verify_raw(raw)

        repairs = 0
        while (not verified["ok"]) and repairs < self.json_repair_retries:
            repairs += 1
            repair_prompt = make_repair_prompt(text, raw, str(verified.get("error")))
            raw = self.llm.generate(repair_prompt)
            self.audit.record("llm_repair", True, text, raw=raw[:2000], round=repairs)
            verified = self.verifier.verify_raw(raw)

        if not verified["ok"]:
            self.audit.record("verify_fail", False, text, error=verified["error"], action=verified.get("action"))
            return {
                "status": "rejected",
                "error": verified["error"],
                "action": verified.get("action"),
                "raw": raw,
                "repairs": repairs,
            }

        action = verified["action"]
        assert action is not None

        if action["op"] in NON_EXEC:
            self.audit.record("non_exec", True, text, action=action)
            return {"status": action["op"], "action": action, "raw": raw, "repairs": repairs}

        if verified.get("needs_confirm"):
            self._pending = action
            self.audit.record("await_confirm", True, text, action=action)
            return {
                "status": "awaiting_confirm",
                "action": action,
                "message": f"高危操作，请回复「{self.confirm_phrase}」执行",
                "raw": raw,
                "repairs": repairs,
            }

        result = self.device.apply(action["op"], action.get("args", {}))
        self.audit.record("execute", True, text, action=action, result=result)
        return {"status": "executed", "action": action, "result": result, "raw": raw, "repairs": repairs}


def make_repair_prompt(user_text: str, bad_raw: str, error: str) -> str:
    return (
        f"上一次输出无法通过校验：{error}\n"
        f"原始输出：{bad_raw}\n"
        f"用户原话：{user_text}\n"
        "请只输出一个合法 JSON 动作对象，不要 Markdown。"
    )

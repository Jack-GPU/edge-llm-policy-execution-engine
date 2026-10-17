from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class AuditEvent:
    ts: float
    stage: str
    ok: bool
    user_text: str
    detail: dict[str, Any] = field(default_factory=dict)


class AuditLog:
    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path else None
        self.events: list[AuditEvent] = []

    def record(self, stage: str, ok: bool, user_text: str, **detail: Any) -> AuditEvent:
        ev = AuditEvent(time.time(), stage, ok, user_text, detail)
        self.events.append(ev)
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(asdict(ev), ensure_ascii=False) + "\n")
        return ev

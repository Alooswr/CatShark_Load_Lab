from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


EventCallback = Callable[[dict[str, Any]], None]


@dataclass(slots=True)
class LoadEvent:
    type: str
    payload: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {"type": self.type, **self.payload}


def emit_log(callback: EventCallback | None, message: str) -> None:
    if callback:
        callback(LoadEvent("log", {"message": message}).to_dict())


def emit_metrics(callback: EventCallback | None, metrics: dict[str, Any]) -> None:
    if callback:
        callback(LoadEvent("metrics", {"metrics": metrics}).to_dict())

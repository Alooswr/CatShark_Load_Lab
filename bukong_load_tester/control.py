from __future__ import annotations

import asyncio
import threading
import time


class RunControl:
    def __init__(self) -> None:
        self.stop_event = threading.Event()
        self._lock = threading.Lock()
        self._start_time: float | None = None
        self._paused = False
        self._pause_started_at: float | None = None
        self._paused_total = 0.0
        self.finish_reason = "duration_complete"

    def mark_started(self) -> None:
        with self._lock:
            self._start_time = time.monotonic()
            self._paused = False
            self._pause_started_at = None
            self._paused_total = 0.0
            self.finish_reason = "duration_complete"

    def request_stop(self, reason: str = "stopped") -> None:
        with self._lock:
            self.finish_reason = reason
        self.stop_event.set()

    def pause(self) -> None:
        with self._lock:
            if not self._paused:
                self._paused = True
                self._pause_started_at = time.monotonic()

    def resume(self) -> None:
        with self._lock:
            if self._paused:
                if self._pause_started_at is not None:
                    self._paused_total += time.monotonic() - self._pause_started_at
                self._pause_started_at = None
                self._paused = False

    def is_paused(self) -> bool:
        with self._lock:
            return self._paused

    def active_elapsed(self) -> float:
        with self._lock:
            if self._start_time is None:
                return 0.0
            now = time.monotonic()
            paused_total = self._paused_total
            if self._paused and self._pause_started_at is not None:
                paused_total += now - self._pause_started_at
            return max(0.0, now - self._start_time - paused_total)

    def duration_reached(self, duration_seconds: float) -> bool:
        return self.active_elapsed() >= duration_seconds


async def wait_if_paused(control: RunControl) -> None:
    while control.is_paused() and not control.stop_event.is_set():
        await asyncio.sleep(0.1)


async def controlled_sleep(seconds: float, control: RunControl, duration_seconds: float) -> None:
    target = control.active_elapsed() + max(0.0, seconds)
    while (
        not control.stop_event.is_set()
        and not control.duration_reached(duration_seconds)
        and control.active_elapsed() < target
    ):
        await wait_if_paused(control)
        remaining = target - control.active_elapsed()
        await asyncio.sleep(max(0.01, min(0.2, remaining)))

from __future__ import annotations

import asyncio
from pathlib import Path
import sys

from aiohttp import web

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bukong_load_tester.config import AppConfig, HttpConfig
from bukong_load_tester.engine import run_load_test


async def handle_event(request: web.Request) -> web.Response:
    await request.json()
    return web.json_response({"ok": True})


async def main() -> None:
    app = web.Application()
    app.router.add_post("/api/device/status", handle_event)
    app.router.add_post("/api/device/heartbeat", handle_event)
    app.router.add_post("/api/device/alarm", handle_event)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 18080)
    await site.start()
    try:
        config = AppConfig(
            mode="HTTP",
            http=HttpConfig(
                server_url="http://127.0.0.1:18080",
                device_count=3,
                ramp_seconds=1,
                duration_seconds=3,
                heartbeat_interval=0.5,
                status_interval=0.4,
                alarm_probability=0.5,
                payload_size=128,
                max_concurrency=10,
            ),
        )
        report = await run_load_test(config, event_callback=lambda event: print(event.get("message", event)) if event.get("type") == "log" else None)
        summary = report["summary"]
        print(summary)
        assert summary["total_requests"] > 0
        assert summary["failure_count"] == 0
    finally:
        await runner.cleanup()


if __name__ == "__main__":
    asyncio.run(main())

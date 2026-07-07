from __future__ import annotations

from aiohttp import web


async def handle_event(request: web.Request) -> web.Response:
    await request.json()
    return web.json_response({"ok": True})


def main() -> None:
    app = web.Application()
    app.router.add_post("/api/device/status", handle_event)
    app.router.add_post("/api/device/heartbeat", handle_event)
    app.router.add_post("/api/device/alarm", handle_event)
    web.run_app(app, host="127.0.0.1", port=8080)


if __name__ == "__main__":
    main()

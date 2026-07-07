from __future__ import annotations

import asyncio
from pathlib import Path
import random
import socket
import sys
import tempfile
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from mock_gb28181_sip_server import MockUdpProtocol
from bukong_load_tester.config import AppConfig, Gb28181Config, GbMediaConfig, GbSipConfig
from bukong_load_tester.distributed import merge_node_reports
from bukong_load_tester.headless_worker import run_worker_async


def free_udp_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


async def main() -> None:
    server_port = free_udp_port()
    loop = asyncio.get_running_loop()
    transport, _ = await loop.create_datagram_endpoint(MockUdpProtocol, local_addr=("127.0.0.1", server_port))
    try:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = AppConfig(
                mode="GB28181",
                gb28181=Gb28181Config(
                    sip=GbSipConfig(
                        server_ip="127.0.0.1",
                        server_port=server_port,
                        domain_id="4403060755",
                        local_device_ip="127.0.0.1",
                        local_sip_start_port=random.randint(25000, 40000),
                        device_id_prefix="440306075513200",
                        device_count=4,
                        password="888888",
                        transport="UDP",
                        heartbeat_interval=0.5,
                        register_expires=3600,
                        ramp_seconds=1,
                        duration_seconds=2,
                        sip_timeout=1.0,
                    ),
                    media=GbMediaConfig(enabled=False, local_port_start=41000, local_port_end=41009),
                ),
            )
            config_path = root / "config.json"
            config.save(config_path)
            for shard_index in range(2):
                await run_worker_async(
                    SimpleNamespace(
                        config=str(config_path),
                        run_id="smoke-run",
                        node_id=f"node-{shard_index}",
                        shard_index=shard_index,
                        shard_count=2,
                        output_dir=str(root / f"node-{shard_index}"),
                    )
                )
            for shard_index in range(2):
                node_dir = root / f"node-{shard_index}"
                assert (node_dir / "report.json").exists()
                assert (node_dir / "report.csv").exists()
                assert (node_dir / "node.log").exists()
            merged = merge_node_reports(root)
            assert merged["run_id"] == "smoke-run"
            assert merged["node_count"] == 2
            assert merged["device_range"]["local_device_count"] == 4
            assert merged["summary"]["register_success_count"] == 4
            print("distributed headless ok")
    finally:
        transport.close()


if __name__ == "__main__":
    asyncio.run(main())

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from .config import AppConfig
from .distributed import apply_distributed_shard, enrich_node_report, write_node_outputs
from .engine import run_load_test


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Bukong GB28181 distributed headless worker")
    parser.add_argument("--config", required=True, help="config.json path")
    parser.add_argument("--run-id", required=True, help="distributed run id")
    parser.add_argument("--node-id", required=True, help="node id, for example node-0")
    parser.add_argument("--shard-index", required=True, type=int, help="zero-based shard index")
    parser.add_argument("--shard-count", required=True, type=int, help="total shard count")
    parser.add_argument("--output-dir", required=True, help="node output directory")
    return parser


async def run_worker_async(args: argparse.Namespace | SimpleNamespace) -> dict[str, Any]:
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    log_path = output_dir / "node.log"
    config = AppConfig.load(args.config)
    sharded_config, context = apply_distributed_shard(
        config,
        run_id=args.run_id,
        node_id=args.node_id,
        shard_index=args.shard_index,
        shard_count=args.shard_count,
    )

    with log_path.open("a", encoding="utf-8") as log_file:
        def log_line(message: str) -> None:
            timestamp = datetime.now().astimezone().isoformat(timespec="seconds")
            log_file.write(f"{timestamp} {message}\n")
            log_file.flush()
            print(message)

        def handle_event(event: dict[str, Any]) -> None:
            if event.get("type") == "log":
                log_line(str(event.get("message", "")))

        log_line(f"run_id={context.run_id} node_id={context.node_id} shard={context.shard_index}/{context.shard_count}")
        log_line(
            "device_range="
            f"{context.device_id_start}..{context.device_id_end} "
            f"local_count={context.local_device_count} "
            f"sip_ports={context.sip_port_start}-{context.sip_port_end} "
            f"rtp_ports={context.rtp_port_start}-{context.rtp_port_end}"
        )
        try:
            report = await run_load_test(sharded_config, event_callback=handle_event)
            enriched = enrich_node_report(report, context, sharded_config)
            write_node_outputs(output_dir, enriched)
            log_line(f"report_json={output_dir / 'report.json'}")
            log_line(f"report_csv={output_dir / 'report.csv'}")
            return enriched
        except Exception as exc:
            log_line(f"worker_failed={exc.__class__.__name__}: {exc}")
            raise


def main() -> None:
    args = build_parser().parse_args()
    asyncio.run(run_worker_async(args))


if __name__ == "__main__":
    main()

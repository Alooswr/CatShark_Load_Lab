from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
import copy
import json
from pathlib import Path
from typing import Any

from .config import AppConfig
from .report import write_csv_report, write_json_report


@dataclass(slots=True)
class DistributedRunContext:
    run_id: str
    node_id: str
    shard_index: int
    shard_count: int
    global_device_count: int
    local_device_count: int
    global_index_start: int
    global_index_end: int
    device_id_start: str
    device_id_end: str
    sip_port_start: int
    sip_port_end: int
    rtp_port_start: int
    rtp_port_end: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def apply_distributed_shard(
    config: AppConfig,
    run_id: str,
    node_id: str,
    shard_index: int,
    shard_count: int,
) -> tuple[AppConfig, DistributedRunContext]:
    if shard_count < 1:
        raise ValueError("shard-count must be greater than 0.")
    if not 0 <= shard_index < shard_count:
        raise ValueError("shard-index must be in [0, shard-count).")
    if config.mode.upper() != "GB28181":
        raise ValueError("Distributed worker v1 only supports GB28181 mode.")

    sharded = AppConfig.from_dict(config.to_dict())
    sip = sharded.gb28181.sip
    media = sharded.gb28181.media
    global_count = sip.device_count
    start, count = shard_range(global_count, shard_index, shard_count)
    if count < 1:
        raise ValueError("This shard has no devices. Make shard-count no larger than device_count.")

    original_sip_port = sip.local_sip_start_port
    original_rtp_start = media.local_port_start
    original_rtp_span = media.local_port_end - media.local_port_start + 1

    sip.device_index_offset += start
    sip.device_count = count
    sip.local_sip_start_port = original_sip_port + start

    media.local_port_start = original_rtp_start + shard_index * original_rtp_span
    media.local_port_end = media.local_port_start + original_rtp_span - 1

    sharded.ensure_valid()
    context = DistributedRunContext(
        run_id=run_id,
        node_id=node_id,
        shard_index=shard_index,
        shard_count=shard_count,
        global_device_count=global_count,
        local_device_count=count,
        global_index_start=start,
        global_index_end=start + count - 1,
        device_id_start=sip.device_id(0),
        device_id_end=sip.device_id(count - 1),
        sip_port_start=sip.local_sip_start_port,
        sip_port_end=sip.local_sip_start_port + count - 1,
        rtp_port_start=media.local_port_start,
        rtp_port_end=media.local_port_end,
    )
    return sharded, context


def shard_range(total: int, shard_index: int, shard_count: int) -> tuple[int, int]:
    base = total // shard_count
    remainder = total % shard_count
    start = shard_index * base + min(shard_index, remainder)
    count = base + (1 if shard_index < remainder else 0)
    return start, count


def enrich_node_report(report: dict[str, Any], context: DistributedRunContext, config: AppConfig) -> dict[str, Any]:
    result = copy.deepcopy(report)
    result.update(
        {
            "run_id": context.run_id,
            "node_id": context.node_id,
            "shard_index": context.shard_index,
            "shard_count": context.shard_count,
            "device_range": {
                "global_index_start": context.global_index_start,
                "global_index_end": context.global_index_end,
                "device_id_start": context.device_id_start,
                "device_id_end": context.device_id_end,
                "local_device_count": context.local_device_count,
                "global_device_count": context.global_device_count,
            },
            "port_range": {
                "sip_port_start": context.sip_port_start,
                "sip_port_end": context.sip_port_end,
                "rtp_port_start": context.rtp_port_start,
                "rtp_port_end": context.rtp_port_end,
            },
            "distributed": context.to_dict(),
            "config_summary": config.to_report_dict(),
        }
    )
    return result


def write_node_outputs(output_dir: str | Path, report: dict[str, Any]) -> None:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    write_json_report(output / "report.json", report)
    write_csv_report(output / "report.csv", report)


def merge_node_reports(input_dir: str | Path) -> dict[str, Any]:
    root = Path(input_dir)
    reports = [load_report(path) for path in sorted(root.rglob("report.json"))]
    reports = [report for report in reports if "run_id" in report and "node_id" in report]
    if not reports:
        raise ValueError(f"No node report.json files found under {root}.")

    run_ids = {report["run_id"] for report in reports}
    shard_counts = {report["shard_count"] for report in reports}
    if len(run_ids) != 1:
        raise ValueError(f"Report run_id mismatch: {sorted(run_ids)}")
    if len(shard_counts) != 1:
        raise ValueError(f"Report shard_count mismatch: {sorted(shard_counts)}")

    summaries = [report.get("summary", {}) for report in reports]
    device_ranges = [report.get("device_range", {}) for report in reports]
    nodes = [
        {
            "node_id": report.get("node_id"),
            "shard_index": report.get("shard_index"),
            "device_range": report.get("device_range", {}),
            "port_range": report.get("port_range", {}),
            "finish_reason": report.get("finish_reason"),
        }
        for report in reports
    ]
    return {
        "tool": "bukong-load-tester",
        "report_type": "merged_distributed",
        "merged_at": datetime.now().astimezone().isoformat(),
        "run_id": next(iter(run_ids)),
        "node_count": len(reports),
        "shard_count": next(iter(shard_counts)),
        "device_range": merge_device_ranges(device_ranges),
        "nodes": sorted(nodes, key=lambda item: item.get("shard_index", 0)),
        "summary": merge_summaries(summaries),
    }


def merge_summaries(summaries: list[dict[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {
        "active_devices": sum_int(summaries, "active_devices"),
        "total_requests": sum_int(summaries, "total_requests"),
        "success_count": sum_int(summaries, "success_count"),
        "failure_count": sum_int(summaries, "failure_count"),
        "throughput": sum_float(summaries, "throughput"),
        "avg_latency_ms": weighted_avg(summaries, "avg_latency_ms", "total_requests"),
        "p50_latency_ms": max_float(summaries, "p50_latency_ms"),
        "p95_latency_ms": max_float(summaries, "p95_latency_ms"),
        "p99_latency_ms": max_float(summaries, "p99_latency_ms"),
        "active_elapsed_seconds": max_float(summaries, "active_elapsed_seconds"),
        "status_codes": merge_dict_counts(summaries, "status_codes"),
        "exceptions": merge_dict_counts(summaries, "exceptions"),
        "counters": merge_dict_counts(summaries, "counters"),
        "gauges": merge_dict_values(summaries, "gauges"),
    }
    result.update(result["counters"])
    result.update(result["gauges"])
    return result


def merge_device_ranges(ranges: list[dict[str, Any]]) -> dict[str, Any]:
    clean = [item for item in ranges if item]
    if not clean:
        return {}
    return {
        "global_index_start": min(item.get("global_index_start", 0) for item in clean),
        "global_index_end": max(item.get("global_index_end", 0) for item in clean),
        "device_id_start": min(item.get("device_id_start", "") for item in clean),
        "device_id_end": max(item.get("device_id_end", "") for item in clean),
        "local_device_count": sum(item.get("local_device_count", 0) for item in clean),
        "global_device_count": max(item.get("global_device_count", 0) for item in clean),
    }


def load_report(path: str | Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as handle:
        return json.load(handle)


def sum_int(summaries: list[dict[str, Any]], key: str) -> int:
    return int(sum(int(item.get(key, 0) or 0) for item in summaries))


def sum_float(summaries: list[dict[str, Any]], key: str) -> float:
    return float(sum(float(item.get(key, 0.0) or 0.0) for item in summaries))


def max_float(summaries: list[dict[str, Any]], key: str) -> float:
    return max((float(item.get(key, 0.0) or 0.0) for item in summaries), default=0.0)


def weighted_avg(summaries: list[dict[str, Any]], key: str, weight_key: str) -> float:
    total_weight = sum_float(summaries, weight_key)
    if total_weight <= 0:
        return 0.0
    return sum(
        float(item.get(key, 0.0) or 0.0) * float(item.get(weight_key, 0.0) or 0.0)
        for item in summaries
    ) / total_weight


def merge_dict_counts(summaries: list[dict[str, Any]], key: str) -> dict[str, int]:
    result: dict[str, int] = {}
    for summary in summaries:
        for item_key, value in summary.get(key, {}).items():
            result[item_key] = result.get(item_key, 0) + int(value)
    return dict(sorted(result.items()))


def merge_dict_values(summaries: list[dict[str, Any]], key: str) -> dict[str, float]:
    result: dict[str, float] = {}
    for summary in summaries:
        for item_key, value in summary.get(key, {}).items():
            result[item_key] = result.get(item_key, 0.0) + float(value)
    return dict(sorted(result.items()))

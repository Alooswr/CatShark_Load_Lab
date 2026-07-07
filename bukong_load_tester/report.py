from __future__ import annotations

import csv
from datetime import datetime
import json
from pathlib import Path
from typing import Any

from .config import AppConfig
from .metrics import MetricsSnapshot


def build_report(
    config: AppConfig,
    snapshot: MetricsSnapshot,
    started_at: datetime,
    ended_at: datetime,
    finish_reason: str,
) -> dict[str, Any]:
    return {
        "tool": "bukong-load-tester",
        "started_at": started_at.isoformat(),
        "ended_at": ended_at.isoformat(),
        "finish_reason": finish_reason,
        "config": config.to_report_dict(),
        "summary": snapshot.to_dict(),
    }


def write_json_report(path: str | Path, report: dict[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, ensure_ascii=False)


def write_csv_report(path: str | Path, report: dict[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    summary = report.get("summary", {})
    config = report.get("config", {})
    config_summary = report.get("config_summary", {})
    with target.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["section", "key", "value"])
        for key in [
            "tool",
            "report_type",
            "run_id",
            "node_id",
            "node_count",
            "shard_index",
            "shard_count",
            "started_at",
            "ended_at",
            "merged_at",
            "finish_reason",
        ]:
            if key in report:
                writer.writerow(["meta", key, report.get(key, "")])
        for key, value in _flatten(report.get("device_range", {})).items():
            writer.writerow(["device_range", key, value])
        for key, value in _flatten(report.get("port_range", {})).items():
            writer.writerow(["port_range", key, value])
        for index, node in enumerate(report.get("nodes", [])):
            for key, value in _flatten(node, f"node_{index}").items():
                writer.writerow(["node", key, value])
        for key, value in _flatten(config).items():
            writer.writerow(["config", key, value])
        for key, value in _flatten(config_summary).items():
            writer.writerow(["config_summary", key, value])
        for key, value in summary.items():
            if isinstance(value, dict):
                continue
            writer.writerow(["summary", key, value])
        for key, value in summary.get("status_codes", {}).items():
            writer.writerow(["status_code", key, value])
        for key, value in summary.get("exceptions", {}).items():
            writer.writerow(["exception", key, value])
        for key, value in summary.get("counters", {}).items():
            writer.writerow(["counter", key, value])
        for key, value in summary.get("gauges", {}).items():
            writer.writerow(["gauge", key, value])


def _flatten(data: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in data.items():
        next_key = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            result.update(_flatten(value, next_key))
        else:
            result[next_key] = value
    return result

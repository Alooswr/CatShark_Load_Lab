from __future__ import annotations

import argparse
from pathlib import Path

from .distributed import merge_node_reports
from .report import write_csv_report, write_json_report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Merge Bukong distributed node reports")
    parser.add_argument("--input-dir", required=True, help="directory containing node report.json files")
    parser.add_argument("--output-dir", required=True, help="directory for merged_report.json/csv")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    report = merge_node_reports(args.input_dir)
    write_json_report(output_dir / "merged_report.json", report)
    write_csv_report(output_dir / "merged_report.csv", report)
    print(output_dir / "merged_report.json")
    print(output_dir / "merged_report.csv")


if __name__ == "__main__":
    main()

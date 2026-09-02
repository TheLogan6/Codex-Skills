#!/usr/bin/env python3
"""Read-only comparison of two generic JSON run records."""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any, Optional, Sequence


MISSING = object()
DEFAULT_MATCH_PATHS = (
    "workload",
    "hardware",
    "correctness.criterion",
    "measurement.warmup",
    "measurement.repeats",
)


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(
        description=(
            "Compare two JSON run records without modifying them. Dotted paths select "
            "comparability fields and numeric metrics."
        )
    )
    parser.add_argument("baseline", nargs="?", help="Baseline JSON file.")
    parser.add_argument("candidate", nargs="?", help="Candidate JSON file.")
    parser.add_argument(
        "--match",
        action="append",
        default=[],
        metavar="PATH",
        help="Dotted path that must match; repeatable. Uses generic defaults if omitted.",
    )
    parser.add_argument(
        "--metric",
        action="append",
        default=[],
        metavar="PATH[:lower|higher]",
        help="Numeric metric and preferred direction; repeatable.",
    )
    parser.add_argument(
        "--format", choices=("json", "markdown"), default="json", help="Output format."
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit 2 if any match field differs or is missing; otherwise exit 0.",
    )
    parser.add_argument(
        "--self-test", action="store_true", help="Run built-in checks and exit."
    )
    args = parser.parse_args(argv)
    if not args.self_test and (not args.baseline or not args.candidate):
        parser.error("baseline and candidate JSON files are required")
    return args


def get_path(record: Any, path: str) -> Any:
    """Read a dotted path, including numeric list indexes."""
    current = record
    for part in path.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        elif isinstance(current, list) and part.isdigit():
            index = int(part)
            if index >= len(current):
                return MISSING
            current = current[index]
        else:
            return MISSING
    return current


def parse_metric_spec(spec: str) -> tuple[str, str]:
    path, separator, direction = spec.rpartition(":")
    if separator and direction in {"lower", "higher"}:
        return path, direction
    return spec, "lower"


def json_value(value: Any) -> Any:
    return None if value is MISSING else value


def is_finite_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def metric_comparison(
    path: str, direction: str, baseline_value: Any, candidate_value: Any
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "path": path,
        "direction": direction,
        "baseline": json_value(baseline_value),
        "candidate": json_value(candidate_value),
    }
    if not is_finite_number(baseline_value) or not is_finite_number(candidate_value):
        result.update({"comparable": False, "reason": "missing-or-non-numeric"})
        return result
    delta = candidate_value - baseline_value
    percent = None if baseline_value == 0 else delta / abs(baseline_value) * 100.0
    improvement = -delta if direction == "lower" else delta
    improvement_percent = (
        None if baseline_value == 0 else improvement / abs(baseline_value) * 100.0
    )
    result.update(
        {
            "comparable": True,
            "delta": delta,
            "delta_percent": percent,
            "improvement": improvement,
            "improvement_percent": improvement_percent,
            "verdict": "better" if improvement > 0 else "worse" if improvement < 0 else "equal",
        }
    )
    return result


def compare_records(
    baseline: dict[str, Any],
    candidate: dict[str, Any],
    match_paths: Sequence[str],
    metric_specs: Sequence[str],
) -> dict[str, Any]:
    """Compare contract fields and numeric metrics."""
    matches = []
    for path in match_paths:
        baseline_value = get_path(baseline, path)
        candidate_value = get_path(candidate, path)
        present = baseline_value is not MISSING and candidate_value is not MISSING
        matches.append(
            {
                "path": path,
                "baseline": json_value(baseline_value),
                "candidate": json_value(candidate_value),
                "present": present,
                "equal": present and baseline_value == candidate_value,
            }
        )
    metrics = []
    for raw_spec in metric_specs:
        path, direction = parse_metric_spec(raw_spec)
        metrics.append(
            metric_comparison(
                path,
                direction,
                get_path(baseline, path),
                get_path(candidate, path),
            )
        )
    mismatches = [item["path"] for item in matches if not item["equal"]]
    return {
        "schema_version": 1,
        "read_only": True,
        "comparable": not mismatches,
        "mismatched_or_missing_fields": mismatches,
        "matches": matches,
        "metrics": metrics,
        "note": "Metric direction is descriptive; acceptance thresholds remain task-defined.",
    }


def render_markdown(result: dict[str, Any]) -> str:
    lines = [
        "# Run Comparison",
        "",
        f"- Comparable: **{'yes' if result['comparable'] else 'no'}**",
        "",
        "## Contract fields",
        "",
        "| Path | Equal | Baseline | Candidate |",
        "| --- | --- | --- | --- |",
    ]
    for item in result["matches"]:
        lines.append(
            f"| `{item['path']}` | {'yes' if item['equal'] else 'no'} | "
            f"`{json.dumps(item['baseline'], ensure_ascii=False)}` | "
            f"`{json.dumps(item['candidate'], ensure_ascii=False)}` |"
        )
    lines.extend(
        [
            "",
            "## Metrics",
            "",
            "| Path | Direction | Baseline | Candidate | Improvement % | Verdict |",
            "| --- | --- | ---: | ---: | ---: | --- |",
        ]
    )
    for item in result["metrics"]:
        improvement = item.get("improvement_percent")
        improvement_text = "n/a" if improvement is None else f"{improvement:.4g}%"
        lines.append(
            f"| `{item['path']}` | {item['direction']} | {item['baseline']} | "
            f"{item['candidate']} | {improvement_text} | "
            f"{item.get('verdict', item.get('reason', 'n/a'))} |"
        )
    return "\n".join(lines) + "\n"


def load_json(path: str) -> dict[str, Any]:
    with Path(path).expanduser().open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise SystemExit(f"Expected a JSON object: {path}")
    return value


def self_test() -> None:
    baseline = {
        "workload": {"shape": [8, 16], "dtype": "fp16"},
        "metrics": {"latency_ms": 10.0, "throughput": 100.0},
    }
    candidate = {
        "workload": {"shape": [8, 16], "dtype": "fp16"},
        "metrics": {"latency_ms": 8.0, "throughput": 120.0},
    }
    result = compare_records(
        baseline,
        candidate,
        ["workload"],
        ["metrics.latency_ms:lower", "metrics.throughput:higher"],
    )
    assert result["comparable"]
    assert [metric["verdict"] for metric in result["metrics"]] == ["better", "better"]
    mismatch = compare_records(baseline, {"workload": {}}, ["workload"], [])
    assert not mismatch["comparable"]


def main(argv: Optional[Sequence[str]] = None) -> int:
    """CLI entry point."""
    args = parse_args(argv)
    if args.self_test:
        self_test()
        print("self-test: ok")
        return 0
    match_paths = args.match or list(DEFAULT_MATCH_PATHS)
    result = compare_records(
        load_json(args.baseline),
        load_json(args.candidate),
        match_paths,
        args.metric,
    )
    if args.format == "markdown":
        print(render_markdown(result), end="")
    else:
        json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
        print()
    return 2 if args.strict and not result["comparable"] else 0


if __name__ == "__main__":
    raise SystemExit(main())

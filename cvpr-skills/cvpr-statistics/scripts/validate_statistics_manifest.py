#!/usr/bin/env python3
"""Validate a cvpr-statistics task manifest."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path, PurePosixPath
from typing import Any


STATUSES = {"proposed", "executed", "accepted", "blocked", "superseded"}
MODES = {"audit_recompute", "result_processing", "paper_update"}
DIRECTIONS = {"higher", "lower", "neutral", "contextual"}
OUTPUT_KINDS = {
    "structured_data",
    "result_table",
    "statistics_report",
    "plot_source",
}
FORBIDDEN_VERDICT_KEYS = {
    "acceptance_logic_result",
    "goal_assessment",
    "goal_verdict",
    "goal_status",
    "goal_passed",
    "claim_verdict",
    "paper_conclusion",
}


class Validation:
    def __init__(self) -> None:
        self.errors: list[str] = []

    def require(self, condition: bool, message: str) -> None:
        if not condition:
            self.errors.append(message)


def has_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, dict)):
        return bool(value)
    return True


def require_list(
    container: dict[str, Any],
    key: str,
    label: str,
    validation: Validation,
) -> list[Any]:
    value = container.get(key)
    validation.require(isinstance(value, list), f"{label}.{key}: 必须是数组")
    return value if isinstance(value, list) else []


def load_manifest(path: Path, validation: Validation) -> Any:
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        validation.errors.append(f"{path}: 无法解析为 JSON/YAML 1.2 子集：{exc}")
        return None


def is_safe_path(value: Any) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    path = PurePosixPath(value)
    return not path.is_absolute() and ".." not in path.parts


def reject_verdict_fields(value: Any, path: str, validation: Validation) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            key_text = str(key).lower()
            validation.require(
                key_text not in FORBIDDEN_VERDICT_KEYS,
                f"{path}.{key}: cvpr-statistics 不得保存 Goal 或论文结论字段",
            )
            reject_verdict_fields(child, f"{path}.{key}", validation)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            reject_verdict_fields(child, f"{path}[{index}]", validation)


def validate_run_partition(
    manifest: dict[str, Any],
    final: bool,
    validation: Validation,
) -> None:
    input_rows = require_list(manifest, "input_run_ids", "statistics.yaml", validation)
    included_rows = require_list(manifest, "included_run_ids", "statistics.yaml", validation)
    excluded_rows = require_list(manifest, "excluded_runs", "statistics.yaml", validation)

    inputs = {value for value in input_rows if isinstance(value, str) and value}
    included = {value for value in included_rows if isinstance(value, str) and value}
    validation.require(len(inputs) == len(input_rows), "input_run_ids: 必须是唯一非空字符串")
    validation.require(len(included) == len(included_rows), "included_run_ids: 必须是唯一非空字符串")

    excluded: set[str] = set()
    for index, row in enumerate(excluded_rows, start=1):
        label = f"excluded_runs[{index}]"
        validation.require(isinstance(row, dict), f"{label}: 必须是对象")
        if not isinstance(row, dict):
            continue
        run_id = row.get("run_id")
        validation.require(
            isinstance(run_id, str) and bool(run_id),
            f"{label}.run_id: 必须是非空字符串",
        )
        if isinstance(run_id, str):
            validation.require(run_id not in excluded, f"{label}: 重复排除 {run_id}")
            excluded.add(run_id)
        validation.require(has_value(row.get("reason")), f"{label}.reason: 不得为空")
        evidence = require_list(row, "evidence_refs", label, validation)
        if final:
            validation.require(bool(evidence), f"{label}.evidence_refs: 不得为空")

    validation.require(included.issubset(inputs), "included_run_ids: 包含输入范围外的 Run")
    validation.require(excluded.issubset(inputs), "excluded_runs: 包含输入范围外的 Run")
    validation.require(not included.intersection(excluded), "Run 不能同时纳入和排除")
    if final:
        validation.require(bool(inputs), "input_run_ids: 正式统计不得为空")
        validation.require(
            included.union(excluded) == inputs,
            "全部输入 Run 必须恰好被纳入或有证据地排除",
        )
        validation.require(bool(included), "included_run_ids: 至少需要一个纳入 Run")


def validate_experimental_unit(
    value: Any,
    final: bool,
    validation: Validation,
) -> None:
    validation.require(isinstance(value, dict), "experimental_unit: 必须是对象")
    if not isinstance(value, dict):
        return
    for key in ("name", "definition", "independence_basis"):
        validation.require(key in value, f"experimental_unit: 缺少字段 {key}")
        if final:
            validation.require(has_value(value.get(key)), f"experimental_unit.{key}: 不得为空")


def validate_metrics(
    value: Any,
    final: bool,
    validation: Validation,
) -> set[str]:
    validation.require(isinstance(value, list), "metrics: 必须是数组")
    if not isinstance(value, list):
        return set()
    metric_ids: set[str] = set()
    for index, row in enumerate(value, start=1):
        label = f"metrics[{index}]"
        validation.require(isinstance(row, dict), f"{label}: 必须是对象")
        if not isinstance(row, dict):
            continue
        for key in (
            "id",
            "name",
            "calculation",
            "unit",
            "direction",
            "aggregation",
            "source_refs",
        ):
            validation.require(key in row, f"{label}: 缺少字段 {key}")
        metric_id = row.get("id")
        validation.require(
            isinstance(metric_id, str) and bool(metric_id),
            f"{label}.id: 必须是非空字符串",
        )
        if isinstance(metric_id, str):
            validation.require(metric_id not in metric_ids, f"{label}: 重复指标 {metric_id}")
            metric_ids.add(metric_id)
        validation.require(row.get("direction") in DIRECTIONS, f"{label}.direction: 非法方向")
        sources = require_list(row, "source_refs", label, validation)
        if final:
            for key in ("name", "calculation", "unit", "aggregation"):
                validation.require(has_value(row.get(key)), f"{label}.{key}: 不得为空")
            validation.require(bool(sources), f"{label}.source_refs: 不得为空")
    if final:
        validation.require(bool(metric_ids), "metrics: 正式统计至少需要一个指标")
    return metric_ids


def validate_methods(
    value: Any,
    metric_ids: set[str],
    final: bool,
    validation: Validation,
) -> None:
    validation.require(isinstance(value, list), "statistical_methods: 必须是数组")
    if not isinstance(value, list):
        return
    method_ids: set[str] = set()
    covered_metrics: set[str] = set()
    for index, row in enumerate(value, start=1):
        label = f"statistical_methods[{index}]"
        validation.require(isinstance(row, dict), f"{label}: 必须是对象")
        if not isinstance(row, dict):
            continue
        for key in (
            "id",
            "applies_to_metric_ids",
            "method",
            "rationale",
            "assumptions",
            "uncertainty",
            "effect_size",
            "multiplicity_control",
            "implementation_ref",
        ):
            validation.require(key in row, f"{label}: 缺少字段 {key}")
        method_id = row.get("id")
        validation.require(
            isinstance(method_id, str) and bool(method_id),
            f"{label}.id: 必须是非空字符串",
        )
        if isinstance(method_id, str):
            validation.require(method_id not in method_ids, f"{label}: 重复方法 {method_id}")
            method_ids.add(method_id)
        applies = require_list(row, "applies_to_metric_ids", label, validation)
        require_list(row, "assumptions", label, validation)
        for metric_id in applies:
            validation.require(metric_id in metric_ids, f"{label}: 未知指标 {metric_id!r}")
            if isinstance(metric_id, str):
                covered_metrics.add(metric_id)
        if final:
            validation.require(bool(applies), f"{label}.applies_to_metric_ids: 不得为空")
            for key in (
                "method",
                "rationale",
                "uncertainty",
                "effect_size",
                "multiplicity_control",
                "implementation_ref",
            ):
                validation.require(has_value(row.get(key)), f"{label}.{key}: 不得为空")
    if final:
        validation.require(bool(method_ids), "statistical_methods: 至少说明一种描述或推断方法")
        validation.require(
            covered_metrics == metric_ids,
            "statistical_methods: 必须覆盖全部指标",
        )


def validate_integrity(
    value: Any,
    final: bool,
    validation: Validation,
) -> None:
    validation.require(isinstance(value, dict), "data_integrity: 必须是对象")
    if not isinstance(value, dict):
        return
    for key in (
        "raw_immutable",
        "missing_policy",
        "outlier_policy",
        "selection_policy",
        "checks",
        "evidence_refs",
    ):
        validation.require(key in value, f"data_integrity: 缺少字段 {key}")
    validation.require(value.get("raw_immutable") is True, "data_integrity.raw_immutable: 必须为 true")
    checks = require_list(value, "checks", "data_integrity", validation)
    evidence = require_list(value, "evidence_refs", "data_integrity", validation)
    if final:
        for key in ("missing_policy", "outlier_policy", "selection_policy"):
            validation.require(has_value(value.get(key)), f"data_integrity.{key}: 不得为空")
        validation.require(bool(checks), "data_integrity.checks: 不得为空")
        validation.require(bool(evidence), "data_integrity.evidence_refs: 不得为空")


def validate_outputs(
    value: Any,
    metric_ids: set[str],
    project_root: Path | None,
    final: bool,
    validation: Validation,
) -> None:
    validation.require(isinstance(value, list), "outputs: 必须是数组")
    if not isinstance(value, list):
        return
    output_ids: set[str] = set()
    for index, row in enumerate(value, start=1):
        label = f"outputs[{index}]"
        validation.require(isinstance(row, dict), f"{label}: 必须是对象")
        if not isinstance(row, dict):
            continue
        for key in ("id", "kind", "path", "format", "source_metric_ids", "evidence_refs"):
            validation.require(key in row, f"{label}: 缺少字段 {key}")
        output_id = row.get("id")
        validation.require(
            isinstance(output_id, str) and bool(output_id),
            f"{label}.id: 必须是非空字符串",
        )
        if isinstance(output_id, str):
            validation.require(output_id not in output_ids, f"{label}: 重复输出 {output_id}")
            output_ids.add(output_id)
        validation.require(row.get("kind") in OUTPUT_KINDS, f"{label}.kind: 非法类型")
        path = row.get("path")
        validation.require(is_safe_path(path), f"{label}.path: 必须是项目内安全相对路径")
        source_metrics = require_list(row, "source_metric_ids", label, validation)
        evidence = require_list(row, "evidence_refs", label, validation)
        for metric_id in source_metrics:
            validation.require(metric_id in metric_ids, f"{label}: 未知指标 {metric_id!r}")
        if final:
            validation.require(has_value(row.get("format")), f"{label}.format: 不得为空")
            validation.require(bool(source_metrics), f"{label}.source_metric_ids: 不得为空")
            validation.require(bool(evidence), f"{label}.evidence_refs: 不得为空")
            if project_root is not None and is_safe_path(path):
                validation.require((project_root / path).is_file(), f"{label}.path: 文件不存在 {path}")
    if final:
        validation.require(bool(output_ids), "outputs: 正式统计必须产生输出")


def validate_provenance(
    value: Any,
    final: bool,
    validation: Validation,
) -> None:
    validation.require(isinstance(value, dict), "provenance: 必须是对象")
    if not isinstance(value, dict):
        return
    for key in (
        "analysis_code_refs",
        "config_refs",
        "environment_refs",
        "generated_at",
        "evidence_refs",
    ):
        validation.require(key in value, f"provenance: 缺少字段 {key}")
    for key in ("analysis_code_refs", "config_refs", "environment_refs", "evidence_refs"):
        rows = require_list(value, key, "provenance", validation)
        if final and key in ("analysis_code_refs", "environment_refs", "evidence_refs"):
            validation.require(bool(rows), f"provenance.{key}: 不得为空")
    if final:
        validation.require(has_value(value.get("generated_at")), "provenance.generated_at: 不得为空")


def validate_manifest(
    manifest: Any,
    project_root: Path | None,
    validation: Validation,
) -> None:
    validation.require(isinstance(manifest, dict), "statistics.yaml: 根节点必须是对象")
    if not isinstance(manifest, dict):
        return
    reject_verdict_fields(manifest, "statistics.yaml", validation)
    required = (
        "schema_version",
        "analysis_id",
        "version",
        "status",
        "mode",
        "purpose",
        "source_snapshot_ref",
        "input_run_ids",
        "included_run_ids",
        "excluded_runs",
        "experimental_unit",
        "grouping_factors",
        "metrics",
        "statistical_methods",
        "data_integrity",
        "outputs",
        "provenance",
        "supersedes",
    )
    for key in required:
        validation.require(key in manifest, f"statistics.yaml: 缺少字段 {key}")
    status = manifest.get("status")
    validation.require(status in STATUSES, "statistics.yaml.status: 非法状态")
    final = status == "accepted"
    validation.require(manifest.get("mode") in MODES, "statistics.yaml.mode: 非法模式")
    validation.require(has_value(manifest.get("schema_version")), "schema_version: 不得为空")
    validation.require(has_value(manifest.get("analysis_id")), "analysis_id: 不得为空")
    version = manifest.get("version")
    validation.require(
        isinstance(version, int) and not isinstance(version, bool) and version >= 1,
        "version: 必须是正整数",
    )
    if final:
        validation.require(has_value(manifest.get("purpose")), "purpose: 不得为空")
        validation.require(has_value(manifest.get("source_snapshot_ref")), "source_snapshot_ref: 不得为空")
    if status == "superseded":
        validation.require(has_value(manifest.get("supersedes")), "superseded 时 supersedes 不得为空")

    validate_run_partition(manifest, final, validation)
    validate_experimental_unit(manifest.get("experimental_unit"), final, validation)
    require_list(manifest, "grouping_factors", "statistics.yaml", validation)
    metric_ids = validate_metrics(manifest.get("metrics"), final, validation)
    validate_methods(manifest.get("statistical_methods"), metric_ids, final, validation)
    validate_integrity(manifest.get("data_integrity"), final, validation)
    validate_outputs(manifest.get("outputs"), metric_ids, project_root, final, validation)
    validate_provenance(manifest.get("provenance"), final, validation)


def main() -> int:
    parser = argparse.ArgumentParser(description="校验 cvpr-statistics 统计任务契约")
    parser.add_argument("manifest", type=Path, help="statistics.yaml 路径")
    parser.add_argument("--project-root", type=Path, help="可选项目根目录，用于检查输出文件")
    args = parser.parse_args()

    validation = Validation()
    manifest = load_manifest(args.manifest, validation)
    project_root = args.project_root.expanduser().resolve() if args.project_root else None
    validate_manifest(manifest, project_root, validation)
    if validation.errors:
        print("INVALID:")
        for error in validation.errors:
            print(f"- {error}")
        return 1
    status = manifest.get("status") if isinstance(manifest, dict) else None
    print(f"OK: {args.manifest} 统计任务契约有效（状态 {status}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Validate a cvpr-figure task manifest."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path, PurePosixPath
from typing import Any


STATUSES = {"proposed", "rendered", "accepted", "blocked", "superseded"}
MODES = {"exploratory", "result_presentation", "paper"}
SOURCE_STATUSES = {"unreviewed", "reviewed"}
BACKENDS = {"undetermined", "python", "r"}
EXPORT_FORMATS = {"svg", "pdf", "png", "tiff"}


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


def validate_sources(
    manifest: dict[str, Any],
    project_root: Path | None,
    final: bool,
    validation: Validation,
) -> set[str]:
    source_rows = require_list(manifest, "source_data_refs", "figure.yaml", validation)
    run_rows = require_list(manifest, "source_run_ids", "figure.yaml", validation)
    require_list(manifest, "transform_refs", "figure.yaml", validation)
    claim_rows = require_list(manifest, "supported_claim_refs", "figure.yaml", validation)

    sources = {value for value in source_rows if isinstance(value, str) and value}
    runs = {value for value in run_rows if isinstance(value, str) and value}
    claims = {value for value in claim_rows if isinstance(value, str) and value}
    validation.require(len(sources) == len(source_rows), "source_data_refs: 必须是唯一非空字符串")
    validation.require(len(runs) == len(run_rows), "source_run_ids: 必须是唯一非空字符串")
    validation.require(len(claims) == len(claim_rows), "supported_claim_refs: 必须是唯一非空字符串")

    for path in source_rows:
        validation.require(is_safe_path(path), f"source_data_refs: 非法项目路径 {path!r}")
        if final and project_root is not None and is_safe_path(path):
            validation.require((project_root / path).is_file(), f"source_data_refs: 文件不存在 {path}")

    if final:
        validation.require(bool(sources), "source_data_refs: 正式图形不得为空")
        validation.require(bool(runs), "source_run_ids: 正式图形不得为空")
        if manifest.get("mode") in {"result_presentation", "paper"}:
            validation.require(bool(claims), "正式结果或论文图必须引用已存在的 Claim")
    return sources


def validate_panels(
    value: Any,
    source_refs: set[str],
    supported_claims: set[str],
    final: bool,
    validation: Validation,
) -> None:
    validation.require(isinstance(value, list), "panels: 必须是数组")
    if not isinstance(value, list):
        return
    panel_ids: set[str] = set()
    for index, row in enumerate(value, start=1):
        label = f"panels[{index}]"
        validation.require(isinstance(row, dict), f"{label}: 必须是对象")
        if not isinstance(row, dict):
            continue
        for key in (
            "id",
            "purpose",
            "chart_family",
            "data_ref",
            "x_or_structure",
            "y_or_measure",
            "grouping",
            "uncertainty",
            "units",
            "claim_refs",
        ):
            validation.require(key in row, f"{label}: 缺少字段 {key}")
        panel_id = row.get("id")
        validation.require(
            isinstance(panel_id, str) and bool(panel_id),
            f"{label}.id: 必须是非空字符串",
        )
        if isinstance(panel_id, str):
            validation.require(panel_id not in panel_ids, f"{label}: 重复面板 {panel_id}")
            panel_ids.add(panel_id)
        validation.require(row.get("data_ref") in source_refs, f"{label}.data_ref: 未引用图形源数据")
        claim_refs = require_list(row, "claim_refs", label, validation)
        for claim_ref in claim_refs:
            validation.require(
                claim_ref in supported_claims,
                f"{label}.claim_refs: 未登记的 Claim {claim_ref!r}",
            )
        if final:
            for key in (
                "purpose",
                "chart_family",
                "x_or_structure",
                "y_or_measure",
                "grouping",
                "uncertainty",
                "units",
            ):
                validation.require(has_value(row.get(key)), f"{label}.{key}: 不得为空")
            validation.require(bool(claim_refs), f"{label}.claim_refs: 正式面板不得为空")
    if final:
        validation.require(bool(panel_ids), "panels: 正式图形至少需要一个面板")


def validate_integrity(
    value: Any,
    final: bool,
    validation: Validation,
) -> None:
    validation.require(isinstance(value, dict), "visual_integrity: 必须是对象")
    if not isinstance(value, dict):
        return
    for key in (
        "data_values_unchanged",
        "scale_policy",
        "zero_baseline_policy",
        "uncertainty_definition",
        "color_not_only",
        "excluded_data",
        "caption_scope",
        "evidence_refs",
    ):
        validation.require(key in value, f"visual_integrity: 缺少字段 {key}")
    validation.require(
        value.get("data_values_unchanged") is True,
        "visual_integrity.data_values_unchanged: 必须为 true",
    )
    validation.require(
        value.get("color_not_only") is True,
        "visual_integrity.color_not_only: 必须为 true",
    )
    require_list(value, "excluded_data", "visual_integrity", validation)
    evidence = require_list(value, "evidence_refs", "visual_integrity", validation)
    if final:
        for key in (
            "scale_policy",
            "zero_baseline_policy",
            "uncertainty_definition",
            "caption_scope",
        ):
            validation.require(has_value(value.get(key)), f"visual_integrity.{key}: 不得为空")
        validation.require(bool(evidence), "visual_integrity.evidence_refs: 不得为空")


def validate_exports(
    value: Any,
    project_root: Path | None,
    final: bool,
    validation: Validation,
) -> None:
    validation.require(isinstance(value, list), "exports: 必须是数组")
    if not isinstance(value, list):
        return
    export_paths: set[str] = set()
    editable_count = 0
    for index, row in enumerate(value, start=1):
        label = f"exports[{index}]"
        validation.require(isinstance(row, dict), f"{label}: 必须是对象")
        if not isinstance(row, dict):
            continue
        for key in ("format", "path", "editable", "evidence_ref"):
            validation.require(key in row, f"{label}: 缺少字段 {key}")
        export_format = row.get("format")
        validation.require(export_format in EXPORT_FORMATS, f"{label}.format: 非法格式")
        path = row.get("path")
        validation.require(is_safe_path(path), f"{label}.path: 必须是项目内安全相对路径")
        if isinstance(path, str):
            validation.require(path not in export_paths, f"{label}: 重复导出路径 {path}")
            export_paths.add(path)
        validation.require(isinstance(row.get("editable"), bool), f"{label}.editable: 必须是布尔值")
        if row.get("editable") is True:
            editable_count += 1
        if final:
            validation.require(has_value(row.get("evidence_ref")), f"{label}.evidence_ref: 不得为空")
            if project_root is not None and is_safe_path(path):
                validation.require((project_root / path).is_file(), f"{label}.path: 文件不存在 {path}")
    if final:
        validation.require(bool(export_paths), "exports: 正式图形至少需要一个导出")
        validation.require(editable_count >= 1, "exports: 至少需要一种可编辑产物")


def validate_qa(
    value: Any,
    final: bool,
    validation: Validation,
) -> None:
    validation.require(isinstance(value, dict), "qa: 必须是对象")
    if not isinstance(value, dict):
        return
    boolean_fields = (
        "render_inspected",
        "labels_legible",
        "no_clipping",
        "scales_honest",
        "statistics_match_source",
        "noncolor_encoding_checked",
    )
    for key in boolean_fields:
        validation.require(isinstance(value.get(key), bool), f"qa.{key}: 必须是布尔值")
        if final:
            validation.require(value.get(key) is True, f"qa.{key}: accepted 时必须为 true")
    evidence = require_list(value, "evidence_refs", "qa", validation)
    if final:
        validation.require(bool(evidence), "qa.evidence_refs: 不得为空")


def validate_manifest(
    manifest: Any,
    project_root: Path | None,
    validation: Validation,
) -> None:
    validation.require(isinstance(manifest, dict), "figure.yaml: 根节点必须是对象")
    if not isinstance(manifest, dict):
        return
    required = (
        "schema_version",
        "figure_id",
        "version",
        "status",
        "mode",
        "purpose",
        "source_snapshot_ref",
        "source_review_status",
        "backend",
        "script_file",
        "source_data_refs",
        "source_run_ids",
        "transform_refs",
        "supported_claim_refs",
        "panels",
        "visual_integrity",
        "exports",
        "qa",
        "supersedes",
    )
    for key in required:
        validation.require(key in manifest, f"figure.yaml: 缺少字段 {key}")

    status = manifest.get("status")
    validation.require(status in STATUSES, "figure.yaml.status: 非法状态")
    final = status == "accepted"
    mode = manifest.get("mode")
    validation.require(mode in MODES, "figure.yaml.mode: 非法模式")
    source_status = manifest.get("source_review_status")
    validation.require(source_status in SOURCE_STATUSES, "source_review_status: 非法状态")
    backend = manifest.get("backend")
    validation.require(backend in BACKENDS, "figure.yaml.backend: 非法后端")
    validation.require(has_value(manifest.get("schema_version")), "schema_version: 不得为空")
    validation.require(has_value(manifest.get("figure_id")), "figure_id: 不得为空")
    version = manifest.get("version")
    validation.require(
        isinstance(version, int) and not isinstance(version, bool) and version >= 1,
        "version: 必须是正整数",
    )
    if final:
        validation.require(has_value(manifest.get("purpose")), "purpose: 不得为空")
        validation.require(has_value(manifest.get("source_snapshot_ref")), "source_snapshot_ref: 不得为空")
        validation.require(backend in {"python", "r"}, "accepted 图形必须确定 Python 或 R 后端")
        if mode in {"result_presentation", "paper"}:
            validation.require(
                source_status == "reviewed",
                "正式结果或论文图只能使用 reviewed 数据",
            )
    if status == "superseded":
        validation.require(has_value(manifest.get("supersedes")), "superseded 时 supersedes 不得为空")

    script_file = manifest.get("script_file")
    if final:
        validation.require(is_safe_path(script_file), "script_file: 必须是项目内安全相对路径")
        if project_root is not None and is_safe_path(script_file):
            validation.require((project_root / script_file).is_file(), f"script_file: 文件不存在 {script_file}")

    source_refs = validate_sources(manifest, project_root, final, validation)
    supported_claims = {
        value
        for value in manifest.get("supported_claim_refs", [])
        if isinstance(value, str) and value
    }
    validate_panels(
        manifest.get("panels"),
        source_refs,
        supported_claims,
        final,
        validation,
    )
    validate_integrity(manifest.get("visual_integrity"), final, validation)
    validate_exports(manifest.get("exports"), project_root, final, validation)
    validate_qa(manifest.get("qa"), final, validation)


def main() -> int:
    parser = argparse.ArgumentParser(description="校验 cvpr-figure 图形任务契约")
    parser.add_argument("manifest", type=Path, help="figure.yaml 路径")
    parser.add_argument("--project-root", type=Path, help="可选项目根目录，用于检查实际文件")
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
    print(f"OK: {args.manifest} 图形任务契约有效（状态 {status}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())

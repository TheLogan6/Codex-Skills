#!/usr/bin/env python3
"""Validate a cvpr-polishing task manifest."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


STATUSES = {"proposed", "running", "completed", "blocked", "superseded"}
MODES = {"polish", "restructure", "translate_zh_to_en"}
PROJECT_MODES = {"cvpr_project", "standalone"}
SECTIONS = {
    "title",
    "abstract",
    "introduction",
    "related_work",
    "method",
    "experiments",
    "results",
    "discussion",
    "limitations",
    "conclusion",
    "appendix",
    "multiple",
}
LANGUAGES = {"english", "chinese"}
LOCK_TYPES = {
    "numeric",
    "unit",
    "formula",
    "citation",
    "identifier",
    "technical_term",
    "comparison",
    "modality",
    "negation",
    "evidence_strength",
    "causality",
    "scope_condition",
}
LITERAL_TYPES = {"numeric", "unit", "formula", "citation", "identifier"}
SEMANTIC_TYPES = LOCK_TYPES - LITERAL_TYPES
FORBIDDEN_KEYS = {
    "goal_verdict",
    "do_verdict",
    "result_verdict",
    "goal_assessment",
    "acceptance_logic_result",
    "latex_layout",
    "float_placement",
    "template_modification",
}


class Validation:
    def __init__(self) -> None:
        self.errors: list[str] = []

    def require(self, condition: bool, message: str) -> None:
        if not condition:
            self.errors.append(message)


def has_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def is_choice(value: Any, choices: set[str]) -> bool:
    return isinstance(value, str) and value in choices


def require_object(value: Any, label: str, validation: Validation) -> dict[str, Any]:
    validation.require(isinstance(value, dict), f"{label}: 必须是对象")
    return value if isinstance(value, dict) else {}


def require_list(value: Any, label: str, validation: Validation) -> list[Any]:
    validation.require(isinstance(value, list), f"{label}: 必须是数组")
    return value if isinstance(value, list) else []


def reject_forbidden_fields(value: Any, path: str, validation: Validation) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            validation.require(
                key not in FORBIDDEN_KEYS,
                f"{path}.{key}: cvpr-polishing 不得承担 Goal 判定或 LaTeX 布局职责",
            )
            reject_forbidden_fields(child, f"{path}.{key}", validation)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            reject_forbidden_fields(child, f"{path}[{index}]", validation)


def safe_relative_path(value: Any) -> bool:
    if not has_text(value):
        return False
    path = Path(value)
    return not path.is_absolute() and ".." not in path.parts


def validate_manifest(
    manifest: Any,
    validation: Validation,
    project_root: Path | None,
) -> None:
    validation.require(isinstance(manifest, dict), "polishing.yaml: 根节点必须是对象")
    if not isinstance(manifest, dict):
        return
    reject_forbidden_fields(manifest, "polishing.yaml", validation)

    for key in (
        "schema_version",
        "task_id",
        "status",
        "mode",
        "source_context",
        "axes",
        "source_text_ref",
        "output_text_ref",
        "fact_locks",
        "terminology_checks",
        "humanizer",
        "fact_lock_status",
        "unresolved_scientific_issues",
        "output_artifacts",
        "blockers",
    ):
        validation.require(key in manifest, f"polishing.yaml: 缺少字段 {key}")
    validation.require(manifest.get("schema_version") == "1.0", "schema_version: 必须为 1.0")
    validation.require(has_text(manifest.get("task_id")), "task_id: 不得为空")
    status = manifest.get("status")
    mode = manifest.get("mode")
    validation.require(is_choice(status, STATUSES), "status: 非法状态")
    validation.require(is_choice(mode, MODES), "mode: 非法模式")
    completed = status == "completed"

    source_context = require_object(manifest.get("source_context"), "source_context", validation)
    project_mode = source_context.get("project_mode")
    validation.require(is_choice(project_mode, PROJECT_MODES), "source_context.project_mode: 非法值")
    if project_mode == "cvpr_project":
        validation.require(has_text(source_context.get("snapshot_ref")), "source_context.snapshot_ref: CVPR 项目不得为空")
        validation.require(
            source_context.get("claims_authority_ref") == ".cvpr/claims.yaml",
            "source_context.claims_authority_ref: 必须引用 .cvpr/claims.yaml",
        )
    else:
        validation.require(has_text(source_context.get("scope_note")), "source_context.scope_note: 独立调用必须说明范围")

    axes = require_object(manifest.get("axes"), "axes", validation)
    validation.require(is_choice(axes.get("section"), SECTIONS), "axes.section: 非法值")
    source_language = axes.get("source_language")
    target_language = axes.get("target_language")
    validation.require(is_choice(source_language, LANGUAGES), "axes.source_language: 非法值")
    validation.require(is_choice(target_language, LANGUAGES), "axes.target_language: 非法值")
    validation.require(has_text(axes.get("venue")), "axes.venue: 不得为空")
    if mode == "translate_zh_to_en":
        validation.require(source_language == "chinese", "translate_zh_to_en: 源语言必须为 chinese")
        validation.require(target_language == "english", "translate_zh_to_en: 目标语言必须为 english")
    elif is_choice(mode, {"polish", "restructure"}):
        validation.require(source_language == target_language, f"{mode}: 源语言与目标语言必须一致")

    source_ref = manifest.get("source_text_ref")
    output_ref = manifest.get("output_text_ref")
    if completed:
        validation.require(safe_relative_path(source_ref), "source_text_ref: 完成态必须是安全相对路径")
        validation.require(safe_relative_path(output_ref), "output_text_ref: 完成态必须是安全相对路径")

    source_text: str | None = None
    output_text: str | None = None
    if completed and project_root is not None:
        if safe_relative_path(source_ref):
            source_path = project_root / source_ref
            validation.require(source_path.is_file(), f"source_text_ref: 文件不存在：{source_path}")
            if source_path.is_file():
                source_text = source_path.read_text(encoding="utf-8")
        if safe_relative_path(output_ref):
            output_path = project_root / output_ref
            validation.require(output_path.is_file(), f"output_text_ref: 文件不存在：{output_path}")
            if output_path.is_file():
                output_text = output_path.read_text(encoding="utf-8")

    locks = require_list(manifest.get("fact_locks"), "fact_locks", validation)
    seen_locks: set[str] = set()
    for index, raw in enumerate(locks):
        label = f"fact_locks[{index}]"
        row = require_object(raw, label, validation)
        lock_id = row.get("id")
        lock_type = row.get("type")
        validation.require(has_text(lock_id), f"{label}.id: 不得为空")
        if has_text(lock_id):
            validation.require(lock_id not in seen_locks, f"{label}.id: 重复 {lock_id}")
            seen_locks.add(lock_id)
        validation.require(is_choice(lock_type, LOCK_TYPES), f"{label}.type: 非法值")
        source_value = row.get("source_value")
        output_value = row.get("output_value")
        validation.require(has_text(source_value), f"{label}.source_value: 不得为空")
        validation.require(has_text(output_value), f"{label}.output_value: 不得为空")
        validation.require(has_text(row.get("source_locator")), f"{label}.source_locator: 不得为空")
        validation.require(has_text(row.get("output_locator")), f"{label}.output_locator: 不得为空")
        lock_status = row.get("status")
        validation.require(
            is_choice(lock_status, {"preserved", "verified_equivalent", "changed", "missing"}),
            f"{label}.status: 非法值",
        )
        if is_choice(lock_type, LITERAL_TYPES):
            validation.require(lock_status == "preserved", f"{label}: 字面锁必须为 preserved")
            validation.require(source_value == output_value, f"{label}: 字面锁的源值与输出值必须相同")
            if source_text is not None and has_text(source_value):
                validation.require(source_value in source_text, f"{label}.source_value: 未在源文件找到")
            if output_text is not None and has_text(output_value):
                validation.require(output_value in output_text, f"{label}.output_value: 未在输出文件找到")
        elif is_choice(lock_type, SEMANTIC_TYPES):
            validation.require(
                is_choice(lock_status, {"preserved", "verified_equivalent"}),
                f"{label}: 语义锁不得 changed 或 missing",
            )
            validation.require(has_text(row.get("verification_note")), f"{label}.verification_note: 语义锁必须说明等价性")

    terminology = require_list(manifest.get("terminology_checks"), "terminology_checks", validation)
    for index, raw in enumerate(terminology):
        label = f"terminology_checks[{index}]"
        row = require_object(raw, label, validation)
        validation.require(has_text(row.get("canonical_term")), f"{label}.canonical_term: 不得为空")
        validation.require(
            is_choice(row.get("status"), {"consistent", "inconsistent"}),
            f"{label}.status: 非法值",
        )
        require_list(row.get("checked_locations"), f"{label}.checked_locations", validation)
        if completed:
            validation.require(row.get("status") == "consistent", f"{label}: 完成态术语必须一致")

    humanizer = require_object(manifest.get("humanizer"), "humanizer", validation)
    used = humanizer.get("used")
    validation.require(isinstance(used, bool), "humanizer.used: 必须是布尔值")
    if used is True:
        validation.require(humanizer.get("skill") == "cvpr-humanizer", "humanizer.skill: 必须为 cvpr-humanizer")
        validation.require(
            humanizer.get("fact_lock_revalidated") is True,
            "humanizer.fact_lock_revalidated: 人类化后必须重新验证事实锁",
        )
        validation.require(has_text(humanizer.get("artifact_ref")), "humanizer.artifact_ref: 不得为空")
    elif used is False:
        validation.require(humanizer.get("skill") is None, "humanizer.skill: 未使用时必须为 null")
        validation.require(
            humanizer.get("fact_lock_revalidated") is False,
            "humanizer.fact_lock_revalidated: 未使用时必须为 false",
        )

    fact_lock_status = manifest.get("fact_lock_status")
    validation.require(
        is_choice(fact_lock_status, {"pending", "passed", "failed"}),
        "fact_lock_status: 非法值",
    )
    if completed:
        validation.require(bool(locks), "fact_locks: 完成态至少包含一个事实锁")
        validation.require(fact_lock_status == "passed", "fact_lock_status: 完成态必须为 passed")

    issues = require_list(
        manifest.get("unresolved_scientific_issues"),
        "unresolved_scientific_issues",
        validation,
    )
    for index, raw in enumerate(issues):
        label = f"unresolved_scientific_issues[{index}]"
        row = require_object(raw, label, validation)
        validation.require(
            is_choice(row.get("severity"), {"blocking", "non_blocking"}),
            f"{label}.severity: 非法值",
        )
        validation.require(has_text(row.get("description")), f"{label}.description: 不得为空")
        validation.require(has_text(row.get("route_to")), f"{label}.route_to: 不得为空")
        if completed:
            validation.require(row.get("severity") != "blocking", f"{label}: 完成态不得保留阻断科学问题")

    outputs = require_list(manifest.get("output_artifacts"), "output_artifacts", validation)
    if completed:
        validation.require(bool(outputs), "output_artifacts: 完成态不得为空")
    for index, raw in enumerate(outputs):
        label = f"output_artifacts[{index}]"
        row = require_object(raw, label, validation)
        validation.require(has_text(row.get("type")), f"{label}.type: 不得为空")
        path = row.get("path")
        validation.require(safe_relative_path(path), f"{label}.path: 必须是安全相对路径")
        require_list(row.get("evidence_refs"), f"{label}.evidence_refs", validation)
        if completed and project_root is not None and safe_relative_path(path):
            validation.require((project_root / path).is_file(), f"{label}.path: 文件不存在：{project_root / path}")

    blockers = require_list(manifest.get("blockers"), "blockers", validation)
    if status == "blocked":
        validation.require(bool(blockers), "blockers: blocked 状态必须说明阻断")
    if completed:
        validation.require(not blockers, "blockers: completed 状态不得保留阻断")


def main() -> int:
    parser = argparse.ArgumentParser(description="校验 cvpr-polishing 润色任务契约")
    parser.add_argument("manifest", type=Path, help="polishing.yaml 路径")
    parser.add_argument("--project-root", type=Path, help="可选项目根目录，用于核对实际文件")
    args = parser.parse_args()

    validation = Validation()
    try:
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"FAIL: 无法读取 JSON 形式 YAML：{exc}", file=sys.stderr)
        return 1
    validate_manifest(manifest, validation, args.project_root)
    if validation.errors:
        for error in validation.errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print("OK: cvpr-polishing 任务契约有效")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

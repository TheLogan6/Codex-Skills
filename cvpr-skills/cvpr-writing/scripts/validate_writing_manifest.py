#!/usr/bin/env python3
"""Validate a cvpr-writing task manifest."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


STATUSES = {"proposed", "drafting", "completed", "blocked", "superseded"}
MODES = {
    "argument_and_outline",
    "section_draft",
    "full_draft",
    "evidence_based_revision",
}
PROJECT_MODES = {"cvpr_project", "standalone"}
PAPER_TYPES = {
    "method_algorithm",
    "theory",
    "dataset_benchmark",
    "empirical_analysis",
    "system_application",
    "survey",
    "other",
}
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
}
LANGUAGES = {"english", "chinese_to_english", "chinese"}
SUPPORT_STATUSES = {
    "supported",
    "partially_supported",
    "needs_evidence",
    "inferred",
    "prohibited",
}
FORBIDDEN_VERDICT_KEYS = {
    "goal_verdict",
    "do_verdict",
    "result_verdict",
    "goal_assessment",
    "acceptance_logic_result",
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


def reject_verdict_fields(value: Any, path: str, validation: Validation) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            validation.require(
                key not in FORBIDDEN_VERDICT_KEYS,
                f"{path}.{key}: cvpr-writing 不得保存或改写 Goal/DO/Result 判定",
            )
            reject_verdict_fields(child, f"{path}.{key}", validation)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            reject_verdict_fields(child, f"{path}[{index}]", validation)


def safe_relative_path(value: Any) -> bool:
    if not has_text(value):
        return False
    path = Path(value)
    return not path.is_absolute() and ".." not in path.parts


def validate_artifacts(
    rows: list[Any],
    label: str,
    validation: Validation,
    project_root: Path | None,
    require_files: bool,
) -> None:
    seen: set[str] = set()
    for index, raw in enumerate(rows):
        item_label = f"{label}[{index}]"
        row = require_object(raw, item_label, validation)
        artifact_id = row.get("id")
        validation.require(has_text(artifact_id), f"{item_label}.id: 必须是非空字符串")
        if has_text(artifact_id):
            validation.require(artifact_id not in seen, f"{item_label}.id: 重复 {artifact_id}")
            seen.add(artifact_id)
        validation.require(has_text(row.get("type")), f"{item_label}.type: 不得为空")
        artifact_path = row.get("path")
        validation.require(safe_relative_path(artifact_path), f"{item_label}.path: 必须是安全相对路径")
        refs = require_list(row.get("evidence_refs"), f"{item_label}.evidence_refs", validation)
        if require_files:
            validation.require(bool(refs), f"{item_label}.evidence_refs: 完成态产物必须可追溯")
            if project_root is not None and safe_relative_path(artifact_path):
                validation.require(
                    (project_root / artifact_path).is_file(),
                    f"{item_label}.path: 文件不存在：{project_root / artifact_path}",
                )


def validate_manifest(
    manifest: Any,
    validation: Validation,
    project_root: Path | None,
) -> None:
    validation.require(isinstance(manifest, dict), "writing.yaml: 根节点必须是对象")
    if not isinstance(manifest, dict):
        return

    reject_verdict_fields(manifest, "writing.yaml", validation)
    for key in (
        "schema_version",
        "task_id",
        "status",
        "mode",
        "source_context",
        "axes",
        "input_artifacts",
        "argument",
        "claim_bindings",
        "terminology",
        "symbols",
        "numeric_mentions",
        "missing_evidence",
        "revision_changes",
        "output_artifacts",
        "blockers",
    ):
        validation.require(key in manifest, f"writing.yaml: 缺少字段 {key}")

    validation.require(manifest.get("schema_version") == "1.0", "schema_version: 必须为 1.0")
    validation.require(has_text(manifest.get("task_id")), "task_id: 不得为空")
    status = manifest.get("status")
    mode = manifest.get("mode")
    validation.require(is_choice(status, STATUSES), "status: 非法状态")
    validation.require(is_choice(mode, MODES), "mode: 非法模式")
    completed = status == "completed"

    source = require_object(manifest.get("source_context"), "source_context", validation)
    project_mode = source.get("project_mode")
    validation.require(is_choice(project_mode, PROJECT_MODES), "source_context.project_mode: 非法值")
    if project_mode == "cvpr_project":
        validation.require(has_text(source.get("snapshot_ref")), "source_context.snapshot_ref: CVPR 项目不得为空")
        validation.require(source.get("result_ref") == ".cvpr/result.yaml", "source_context.result_ref: 必须引用 .cvpr/result.yaml")
        validation.require(
            source.get("claims_authority_ref") == ".cvpr/claims.yaml",
            "source_context.claims_authority_ref: 必须引用 .cvpr/claims.yaml",
        )
        if completed and project_root is not None:
            for ref_key in ("result_ref", "claims_authority_ref"):
                ref = source.get(ref_key)
                if safe_relative_path(ref):
                    validation.require(
                        (project_root / ref).is_file(),
                        f"source_context.{ref_key}: 文件不存在：{project_root / ref}",
                    )
    else:
        validation.require(has_text(source.get("scope_note")), "source_context.scope_note: 独立调用必须说明证据边界")

    axes = require_object(manifest.get("axes"), "axes", validation)
    validation.require(is_choice(axes.get("paper_type"), PAPER_TYPES), "axes.paper_type: 非法值")
    sections = require_list(axes.get("sections"), "axes.sections", validation)
    validation.require(bool(sections), "axes.sections: 至少包含一个章节")
    validation.require(all(is_choice(section, SECTIONS) for section in sections), "axes.sections: 包含非法章节")
    validation.require(is_choice(axes.get("language"), LANGUAGES), "axes.language: 非法值")
    validation.require(has_text(axes.get("venue")), "axes.venue: 不得为空")

    inputs = require_list(manifest.get("input_artifacts"), "input_artifacts", validation)
    validate_artifacts(inputs, "input_artifacts", validation, project_root, False)

    argument = require_object(manifest.get("argument"), "argument", validation)
    contributions = require_list(
        argument.get("contribution_claim_ids"),
        "argument.contribution_claim_ids",
        validation,
    )
    confirmation = require_object(
        argument.get("outline_confirmation"),
        "argument.outline_confirmation",
        validation,
    )
    validation.require(
        is_choice(confirmation.get("status"), {"pending", "confirmed", "not_required"}),
        "argument.outline_confirmation.status: 非法值",
    )
    if completed:
        validation.require(has_text(argument.get("central_claim_id")), "argument.central_claim_id: 完成态不得为空")
        validation.require(has_text(argument.get("one_sentence_argument")), "argument.one_sentence_argument: 完成态不得为空")
        validation.require(bool(contributions), "argument.contribution_claim_ids: 完成态不得为空")
    if mode == "full_draft" and completed:
        validation.require(has_text(argument.get("outline_ref")), "argument.outline_ref: 完整初稿必须引用提纲")
        validation.require(
            confirmation.get("status") == "confirmed",
            "argument.outline_confirmation.status: 完整初稿必须经用户确认",
        )
        validation.require(
            has_text(confirmation.get("decision_ref")),
            "argument.outline_confirmation.decision_ref: 必须引用确认记录",
        )

    bindings = require_list(manifest.get("claim_bindings"), "claim_bindings", validation)
    seen_claims: set[str] = set()
    missing_claim_ids: set[str] = set()
    missing_rows = require_list(manifest.get("missing_evidence"), "missing_evidence", validation)
    for index, raw in enumerate(missing_rows):
        row = require_object(raw, f"missing_evidence[{index}]", validation)
        claim_id = row.get("claim_id")
        validation.require(has_text(claim_id), f"missing_evidence[{index}].claim_id: 不得为空")
        if has_text(claim_id):
            missing_claim_ids.add(claim_id)
        validation.require(has_text(row.get("requirement")), f"missing_evidence[{index}].requirement: 不得为空")
        validation.require(
            is_choice(row.get("impact"), {"core", "non_core"}),
            f"missing_evidence[{index}].impact: 非法值",
        )
        validation.require(has_text(row.get("action")), f"missing_evidence[{index}].action: 不得为空")

    for index, raw in enumerate(bindings):
        label = f"claim_bindings[{index}]"
        row = require_object(raw, label, validation)
        claim_id = row.get("claim_id")
        validation.require(has_text(claim_id), f"{label}.claim_id: 不得为空")
        if has_text(claim_id):
            validation.require(claim_id not in seen_claims, f"{label}.claim_id: 重复 {claim_id}")
            seen_claims.add(claim_id)
        validation.require(has_text(row.get("manuscript_location")), f"{label}.manuscript_location: 不得为空")
        support = row.get("support_status")
        validation.require(is_choice(support, SUPPORT_STATUSES), f"{label}.support_status: 非法值")
        is_core = row.get("is_core")
        validation.require(isinstance(is_core, bool), f"{label}.is_core: 必须是布尔值")
        refs = require_list(row.get("evidence_refs"), f"{label}.evidence_refs", validation)
        if is_choice(support, {"supported", "partially_supported", "inferred"}):
            validation.require(bool(refs), f"{label}.evidence_refs: 当前支持状态必须有证据")
        if support == "inferred":
            validation.require(has_text(row.get("boundary_note")), f"{label}.boundary_note: 推论必须标明边界")
        if is_choice(support, {"needs_evidence", "partially_supported"}):
            validation.require(
                has_text(claim_id) and claim_id in missing_claim_ids,
                f"{label}: 证据缺口必须登记到 missing_evidence",
            )
        if completed:
            validation.require(support != "prohibited", f"{label}: 完成态不得包含 prohibited Claim")
            if is_core:
                validation.require(
                    support == "supported",
                    f"{label}: 核心 Claim 必须为 supported，当前为 {support}",
                )

    for list_name, required_fields in (
        ("terminology", ("canonical_term", "definition_ref")),
        ("symbols", ("symbol", "meaning", "source_ref")),
        ("numeric_mentions", ("display_value", "manuscript_location", "source_ref", "comparison_context")),
    ):
        rows = require_list(manifest.get(list_name), list_name, validation)
        for index, raw in enumerate(rows):
            row = require_object(raw, f"{list_name}[{index}]", validation)
            for field in required_fields:
                validation.require(has_text(row.get(field)), f"{list_name}[{index}].{field}: 不得为空")

    revisions = require_list(manifest.get("revision_changes"), "revision_changes", validation)
    if mode == "evidence_based_revision" and completed:
        validation.require(bool(revisions), "revision_changes: 证据驱动修订完成态不得为空")
    for index, raw in enumerate(revisions):
        row = require_object(raw, f"revision_changes[{index}]", validation)
        for field in ("location", "reason", "input_ref", "before_claim", "after_claim"):
            validation.require(has_text(row.get(field)), f"revision_changes[{index}].{field}: 不得为空")

    outputs = require_list(manifest.get("output_artifacts"), "output_artifacts", validation)
    if completed:
        validation.require(bool(outputs), "output_artifacts: 完成态不得为空")
        validation.require(
            not any(row.get("impact") == "core" for row in missing_rows if isinstance(row, dict)),
            "missing_evidence: 完成态不得存在核心证据缺口",
        )
    validate_artifacts(outputs, "output_artifacts", validation, project_root, completed)

    blockers = require_list(manifest.get("blockers"), "blockers", validation)
    if status == "blocked":
        validation.require(bool(blockers), "blockers: blocked 状态必须说明阻断")
    if completed:
        validation.require(not blockers, "blockers: completed 状态不得保留阻断")


def main() -> int:
    parser = argparse.ArgumentParser(description="校验 cvpr-writing 写作任务契约")
    parser.add_argument("manifest", type=Path, help="writing.yaml 路径")
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
    print("OK: cvpr-writing 任务契约有效")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

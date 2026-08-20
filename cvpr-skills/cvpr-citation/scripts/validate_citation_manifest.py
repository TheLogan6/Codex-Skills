#!/usr/bin/env python3
"""Validate a cvpr-citation task manifest."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


STATUSES = {"proposed", "running", "completed", "blocked", "superseded"}
PROJECT_MODES = {"cvpr_project", "standalone"}
VERIFICATION_STATUSES = {"verified", "metadata_only", "unverified", "rejected"}
SUPPORT_LEVELS = {
    "direct",
    "partial",
    "contextual",
    "contradictory",
    "topical_only",
    "not_supporting",
}
CITATION_ROLES = {"direct_support", "limited_support", "context", "contrast"}
COVERAGE_STATUSES = {"supported", "partial", "gap", "conflict", "not_applicable"}
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
                f"{path}.{key}: cvpr-citation 不得保存或改写 Goal/DO/Result 判定",
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


def validate_manifest(
    manifest: Any,
    validation: Validation,
    project_root: Path | None,
) -> None:
    validation.require(isinstance(manifest, dict), "citation.yaml: 根节点必须是对象")
    if not isinstance(manifest, dict):
        return
    reject_verdict_fields(manifest, "citation.yaml", validation)

    for key in (
        "schema_version",
        "task_id",
        "status",
        "source_context",
        "literature_registry_refs",
        "bibliography_input_refs",
        "literature_records",
        "claims",
        "bibliography_outputs",
        "conflicts",
        "needs_academic_search",
        "output_artifacts",
        "blockers",
    ):
        validation.require(key in manifest, f"citation.yaml: 缺少字段 {key}")
    validation.require(manifest.get("schema_version") == "1.0", "schema_version: 必须为 1.0")
    validation.require(has_text(manifest.get("task_id")), "task_id: 不得为空")
    status = manifest.get("status")
    validation.require(is_choice(status, STATUSES), "status: 非法状态")
    completed = status == "completed"

    source = require_object(manifest.get("source_context"), "source_context", validation)
    project_mode = source.get("project_mode")
    validation.require(is_choice(project_mode, PROJECT_MODES), "source_context.project_mode: 非法值")
    validation.require(has_text(source.get("manuscript_ref")) or not completed, "source_context.manuscript_ref: 完成态不得为空")
    if project_mode == "cvpr_project":
        validation.require(has_text(source.get("snapshot_ref")), "source_context.snapshot_ref: CVPR 项目不得为空")
        validation.require(
            source.get("claims_authority_ref") == ".cvpr/claims.yaml",
            "source_context.claims_authority_ref: 必须引用 .cvpr/claims.yaml",
        )
        if completed and project_root is not None:
            claims_ref = source.get("claims_authority_ref")
            if safe_relative_path(claims_ref):
                validation.require(
                    (project_root / claims_ref).is_file(),
                    f"source_context.claims_authority_ref: 文件不存在：{project_root / claims_ref}",
                )
    else:
        validation.require(has_text(source.get("scope_note")), "source_context.scope_note: 独立调用必须说明范围")

    registry_refs = require_list(
        manifest.get("literature_registry_refs"),
        "literature_registry_refs",
        validation,
    )
    bibliography_inputs = require_list(
        manifest.get("bibliography_input_refs"),
        "bibliography_input_refs",
        validation,
    )
    if completed:
        validation.require(bool(registry_refs), "literature_registry_refs: 完成态必须引用已核验注册表")
        validation.require(bool(bibliography_inputs), "bibliography_input_refs: 完成态必须引用 .bib/.ris/.nbib 输入")
    for index, ref in enumerate(bibliography_inputs):
        validation.require(
            has_text(ref) and Path(ref).suffix.lower() in {".bib", ".ris", ".nbib"},
            f"bibliography_input_refs[{index}]: 必须是 .bib/.ris/.nbib 文件引用",
        )

    records = require_list(manifest.get("literature_records"), "literature_records", validation)
    record_by_id: dict[str, dict[str, Any]] = {}
    key_owner: dict[str, str] = {}
    for index, raw in enumerate(records):
        label = f"literature_records[{index}]"
        row = require_object(raw, label, validation)
        paper_id = row.get("paper_id")
        cite_key = row.get("bibtex_key")
        validation.require(has_text(paper_id), f"{label}.paper_id: 不得为空")
        validation.require(has_text(row.get("title")), f"{label}.title: 不得为空")
        verification = row.get("verification_status")
        validation.require(
            is_choice(verification, VERIFICATION_STATUSES),
            f"{label}.verification_status: 非法值",
        )
        metadata_refs = require_list(row.get("metadata_source_refs"), f"{label}.metadata_source_refs", validation)
        content_refs = require_list(row.get("content_evidence_refs"), f"{label}.content_evidence_refs", validation)
        validation.require(has_text(row.get("bibliographic_file_ref")), f"{label}.bibliographic_file_ref: 不得为空")
        validation.require(has_text(cite_key), f"{label}.bibtex_key: 不得为空")
        if has_text(paper_id):
            validation.require(paper_id not in record_by_id, f"{label}.paper_id: 重复 {paper_id}")
            record_by_id[paper_id] = row
        if has_text(cite_key):
            validation.require(
                cite_key not in key_owner or key_owner[cite_key] == paper_id,
                f"{label}.bibtex_key: 引用键冲突 {cite_key}",
            )
            key_owner[cite_key] = paper_id
        if verification == "verified":
            validation.require(bool(metadata_refs), f"{label}: verified 记录必须有元数据来源")
            validation.require(bool(content_refs), f"{label}: verified 记录必须有内容证据来源")

    searches = require_list(
        manifest.get("needs_academic_search"),
        "needs_academic_search",
        validation,
    )
    search_claim_ids: set[str] = set()
    for index, raw in enumerate(searches):
        label = f"needs_academic_search[{index}]"
        row = require_object(raw, label, validation)
        claim_id = row.get("claim_id")
        validation.require(has_text(claim_id), f"{label}.claim_id: 不得为空")
        if has_text(claim_id):
            search_claim_ids.add(claim_id)
        for field in ("evidence_needed", "search_scope", "excluded_candidate_refs"):
            if field == "excluded_candidate_refs":
                require_list(row.get(field), f"{label}.{field}", validation)
            else:
                validation.require(has_text(row.get(field)), f"{label}.{field}: 不得为空")

    conflicts = require_list(manifest.get("conflicts"), "conflicts", validation)
    conflict_claim_ids: set[str] = set()
    for index, raw in enumerate(conflicts):
        label = f"conflicts[{index}]"
        row = require_object(raw, label, validation)
        validation.require(
            is_choice(row.get("type"), {"evidence", "metadata", "bibtex_key", "wording"}),
            f"{label}.type: 非法值",
        )
        validation.require(has_text(row.get("description")), f"{label}.description: 不得为空")
        require_list(row.get("source_refs"), f"{label}.source_refs", validation)
        claim_id = row.get("claim_id")
        if has_text(claim_id):
            conflict_claim_ids.add(claim_id)

    claims = require_list(manifest.get("claims"), "claims", validation)
    seen_claims: set[str] = set()
    any_inserted = False
    for index, raw in enumerate(claims):
        label = f"claims[{index}]"
        row = require_object(raw, label, validation)
        claim_id = row.get("claim_id")
        validation.require(has_text(claim_id), f"{label}.claim_id: 不得为空")
        if has_text(claim_id):
            validation.require(claim_id not in seen_claims, f"{label}.claim_id: 重复 {claim_id}")
            seen_claims.add(claim_id)
        validation.require(has_text(row.get("text")), f"{label}.text: 不得为空")
        validation.require(has_text(row.get("manuscript_location")), f"{label}.manuscript_location: 不得为空")
        coverage = row.get("coverage_status")
        validation.require(is_choice(coverage, COVERAGE_STATUSES), f"{label}.coverage_status: 非法值")
        citations = require_list(row.get("citations"), f"{label}.citations", validation)
        valid_inserted: list[dict[str, Any]] = []
        for cite_index, raw_cite in enumerate(citations):
            cite_label = f"{label}.citations[{cite_index}]"
            cite = require_object(raw_cite, cite_label, validation)
            paper_id = cite.get("paper_id")
            validation.require(
                has_text(paper_id) and paper_id in record_by_id,
                f"{cite_label}.paper_id: 未引用有效文献记录",
            )
            support = cite.get("support_level")
            role = cite.get("citation_role")
            inserted = cite.get("inserted")
            validation.require(is_choice(support, SUPPORT_LEVELS), f"{cite_label}.support_level: 非法值")
            validation.require(is_choice(role, CITATION_ROLES), f"{cite_label}.citation_role: 非法值")
            validation.require(isinstance(inserted, bool), f"{cite_label}.inserted: 必须是布尔值")
            validation.require(has_text(cite.get("rationale")), f"{cite_label}.rationale: 不得为空")
            record = record_by_id.get(paper_id, {}) if has_text(paper_id) else {}
            if inserted is True:
                any_inserted = True
                validation.require(
                    record.get("verification_status") == "verified",
                    f"{cite_label}: 只有 verified 文献可插入",
                )
                validation.require(
                    is_choice(support, SUPPORT_LEVELS)
                    and support not in {"topical_only", "not_supporting"},
                    f"{cite_label}: 主题相关或不支持文献禁止插入",
                )
                validation.require(has_text(cite.get("evidence_locator")), f"{cite_label}.evidence_locator: 插入引用必须有内容定位")
                validation.require(
                    cite.get("cite_key") == record.get("bibtex_key"),
                    f"{cite_label}.cite_key: 必须与文献记录一致",
                )
                if role == "direct_support":
                    validation.require(support == "direct", f"{cite_label}: direct_support 必须为 direct")
                if role == "limited_support":
                    validation.require(support == "partial", f"{cite_label}: limited_support 必须为 partial")
                if role == "context":
                    validation.require(support == "contextual", f"{cite_label}: context 必须为 contextual")
                if role == "contrast":
                    validation.require(support == "contradictory", f"{cite_label}: contrast 必须为 contradictory")
                valid_inserted.append(cite)
        if coverage == "supported":
            validation.require(
                any(cite.get("support_level") == "direct" for cite in valid_inserted),
                f"{label}: supported 必须至少有一个已插入 direct 证据",
            )
        elif coverage == "partial":
            validation.require(bool(valid_inserted), f"{label}: partial 必须至少有一个有效插入引用")
            validation.require(
                has_text(claim_id) and claim_id in search_claim_ids,
                f"{label}: partial 必须登记补充检索",
            )
        elif coverage == "gap":
            validation.require(not valid_inserted, f"{label}: gap 不应含已插入引用")
            validation.require(
                has_text(claim_id) and claim_id in search_claim_ids,
                f"{label}: gap 必须登记补充检索",
            )
        elif coverage == "conflict":
            validation.require(
                has_text(claim_id) and claim_id in conflict_claim_ids,
                f"{label}: conflict 必须登记冲突",
            )
        elif coverage == "not_applicable":
            validation.require(has_text(row.get("not_applicable_reason")), f"{label}.not_applicable_reason: 不得为空")

    bibliography_outputs = require_list(
        manifest.get("bibliography_outputs"),
        "bibliography_outputs",
        validation,
    )
    if completed and any_inserted:
        validation.require(bool(bibliography_outputs), "bibliography_outputs: 已插入引用时必须输出书目文件")
    for index, raw in enumerate(bibliography_outputs):
        label = f"bibliography_outputs[{index}]"
        row = require_object(raw, label, validation)
        path = row.get("path")
        validation.require(
            safe_relative_path(path) and Path(path).suffix.lower() in {".bib", ".ris", ".nbib"},
            f"{label}.path: 必须是安全的 .bib/.ris/.nbib 相对路径",
        )
        require_list(row.get("source_refs"), f"{label}.source_refs", validation)
        if completed and project_root is not None and safe_relative_path(path):
            validation.require((project_root / path).is_file(), f"{label}.path: 文件不存在：{project_root / path}")

    outputs = require_list(manifest.get("output_artifacts"), "output_artifacts", validation)
    if completed:
        validation.require(bool(claims), "claims: 完成态至少包含一个目标论断")
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
    parser = argparse.ArgumentParser(description="校验 cvpr-citation 引用任务契约")
    parser.add_argument("manifest", type=Path, help="citation.yaml 路径")
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
    print("OK: cvpr-citation 任务契约有效")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

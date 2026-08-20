#!/usr/bin/env python3
"""Validate a cvpr-paper-audit record using only the Python standard library."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import pathlib
import re
import sys
from typing import Any


CATEGORIES = {
    "manuscript_completeness",
    "claim_evidence",
    "number_traceability",
    "table_consistency",
    "figure_consistency",
    "formula_consistency",
    "citation_support",
    "terminology_consistency",
    "run_alignment",
    "statistics_alignment",
    "reproducibility_alignment",
}
STATUSES = {"proposed", "in_progress", "ready", "needs_revision", "blocked", "superseded"}
CHECK_STATUSES = {"pass", "fail", "not_assessable"}
SEVERITIES = {"blocker", "major", "minor"}
FINDING_STATUSES = {"open", "resolved", "accepted_risk"}
RESPONSIBLE_SKILLS = {
    "cvpr-writing",
    "cvpr-citation",
    "cvpr-statistics",
    "cvpr-figure",
    "cvpr-reproducibility",
    "cvpr-latex",
    "cvpr-do",
    "cvpr-result",
}
ROUTES = {
    "pending",
    "continue-to-reviewer",
    "return-to-writing",
    "return-to-citation",
    "return-to-statistics",
    "return-to-figure",
    "return-to-reproducibility",
    "return-to-latex",
    "return-to-do",
    "return-to-result",
    "request-materials",
}
LOCATOR_TYPES = {"line", "page", "section", "equation", "table", "figure", "cell", "run", "config", "other"}
FORBIDDEN_KEYS = {
    "acceptance_decision",
    "acceptance_probability",
    "editor_decision",
    "goal_assessment",
    "do_verdict",
    "result_verdict",
    "manuscript_patch",
    "rewritten_text",
}
SHA256 = re.compile(r"^[0-9a-f]{64}$")


class Validation:
    def __init__(self) -> None:
        self.errors: list[str] = []

    def require(self, condition: bool, message: str) -> None:
        if not condition:
            self.errors.append(message)


def is_nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def require_list(validation: Validation, value: Any, path: str) -> list[Any]:
    validation.require(isinstance(value, list), f"{path} 必须是列表")
    return value if isinstance(value, list) else []


def require_dict(validation: Validation, value: Any, path: str) -> dict[str, Any]:
    validation.require(isinstance(value, dict), f"{path} 必须是对象")
    return value if isinstance(value, dict) else {}


def scan_forbidden(validation: Validation, value: Any, path: str = "$") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            validation.require(key not in FORBIDDEN_KEYS, f"{path}.{key} 是越权或改稿字段")
            scan_forbidden(validation, child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            scan_forbidden(validation, child, f"{path}[{index}]")


def validate_location(validation: Validation, location: Any, path: str) -> None:
    location = require_dict(validation, location, path)
    validation.require(is_nonempty_string(location.get("artifact_ref")), f"{path}.artifact_ref 不能为空")
    validation.require(location.get("locator_type") in LOCATOR_TYPES, f"{path}.locator_type 非法")
    validation.require(is_nonempty_string(location.get("locator")), f"{path}.locator 必须精确定位")


def validate_record(data: Any, project_root: pathlib.Path | None = None) -> list[str]:
    validation = Validation()
    root = require_dict(validation, data, "$")
    scan_forbidden(validation, root)

    validation.require(root.get("schema_version") == "1.0", "schema_version 必须为 1.0")
    validation.require(is_nonempty_string(root.get("audit_id")), "audit_id 不能为空")
    validation.require(isinstance(root.get("version"), int) and root.get("version", 0) >= 1, "version 必须为正整数")
    status = root.get("status")
    validation.require(status in STATUSES, "status 非法")

    snapshot = require_dict(validation, root.get("snapshot"), "snapshot")
    level = require_dict(validation, root.get("scope"), "scope").get("level")
    formal = status in {"ready", "needs_revision", "blocked"}
    if formal:
        validation.require(is_nonempty_string(snapshot.get("snapshot_id")), "正式审计必须有 snapshot_id")
        validation.require(is_nonempty_string(snapshot.get("frozen_at")), "正式审计必须有 frozen_at")
        validation.require(snapshot.get("immutable") is True, "正式审计快照必须 immutable=true")
        validation.require(SHA256.fullmatch(str(snapshot.get("manifest_digest", ""))) is not None, "manifest_digest 必须是 SHA-256")

    files = require_list(validation, snapshot.get("files"), "snapshot.files")
    seen_paths: set[str] = set()
    for index, file_record in enumerate(files):
        path = f"snapshot.files[{index}]"
        file_record = require_dict(validation, file_record, path)
        rel = file_record.get("path")
        digest = file_record.get("sha256")
        validation.require(is_nonempty_string(rel), f"{path}.path 不能为空")
        validation.require(SHA256.fullmatch(str(digest or "")) is not None, f"{path}.sha256 必须是 SHA-256")
        if is_nonempty_string(rel):
            validation.require(rel not in seen_paths, f"{path}.path 重复")
            seen_paths.add(rel)
            rel_path = pathlib.PurePosixPath(rel)
            validation.require(not rel_path.is_absolute() and ".." not in rel_path.parts, f"{path}.path 必须是安全相对路径")
            if project_root is not None and not rel_path.is_absolute() and ".." not in rel_path.parts:
                actual = (project_root / pathlib.Path(*rel_path.parts)).resolve()
                validation.require(actual.is_relative_to(project_root.resolve()), f"{path}.path 越出项目根目录")
                if actual.is_file():
                    actual_digest = hashlib.sha256(actual.read_bytes()).hexdigest()
                    validation.require(actual_digest == digest, f"{path}.sha256 与实际文件不一致")
                else:
                    validation.errors.append(f"{path}.path 对应文件不存在")

    scope = require_dict(validation, root.get("scope"), "scope")
    validation.require(level in {"full", "partial"}, "scope.level 必须为 full 或 partial")
    manuscript_refs = require_list(validation, scope.get("manuscript_refs"), "scope.manuscript_refs")
    if formal:
        validation.require(bool(manuscript_refs), "正式审计必须列出 manuscript_refs")
        validation.require(bool(files), "正式审计必须冻结至少一个实际文件")
    venue = scope.get("venue")
    venue_ref = scope.get("venue_requirements_ref")
    if venue is not None:
        validation.require(is_nonempty_string(venue), "scope.venue 必须为非空字符串或 null")
        validation.require(is_nonempty_string(venue_ref), "指定 venue 时必须提供 venue_requirements_ref")

    coverage = require_list(validation, root.get("coverage"), "coverage")
    coverage_map: dict[str, dict[str, Any]] = {}
    for index, entry in enumerate(coverage):
        path = f"coverage[{index}]"
        entry = require_dict(validation, entry, path)
        category = entry.get("category")
        validation.require(category in CATEGORIES, f"{path}.category 非法")
        validation.require(category not in coverage_map, f"{path}.category 重复")
        validation.require(entry.get("status") in {"assessed", "not_assessable"}, f"{path}.status 非法")
        require_list(validation, entry.get("missing_materials"), f"{path}.missing_materials")
        if category in CATEGORIES:
            coverage_map[category] = entry

    checks = require_list(validation, root.get("checks"), "checks")
    check_ids: set[str] = set()
    check_categories: set[str] = set()
    for index, check in enumerate(checks):
        path = f"checks[{index}]"
        check = require_dict(validation, check, path)
        check_id = check.get("check_id")
        category = check.get("category")
        validation.require(is_nonempty_string(check_id), f"{path}.check_id 不能为空")
        validation.require(check_id not in check_ids, f"{path}.check_id 重复")
        if is_nonempty_string(check_id):
            check_ids.add(check_id)
        validation.require(category in CATEGORIES, f"{path}.category 非法")
        if category in CATEGORIES:
            check_categories.add(category)
        validation.require(check.get("status") in CHECK_STATUSES, f"{path}.status 非法")
        validation.require(is_nonempty_string(check.get("description")), f"{path}.description 不能为空")
        locations = require_list(validation, check.get("locations"), f"{path}.locations")
        evidence_refs = require_list(validation, check.get("evidence_refs"), f"{path}.evidence_refs")
        if formal:
            validation.require(bool(locations), f"{path}.locations 不能为空")
            validation.require(bool(evidence_refs), f"{path}.evidence_refs 不能为空")
        for location_index, location in enumerate(locations):
            validate_location(validation, location, f"{path}.locations[{location_index}]")

    findings = require_list(validation, root.get("findings"), "findings")
    finding_map: dict[str, dict[str, Any]] = {}
    for index, finding in enumerate(findings):
        path = f"findings[{index}]"
        finding = require_dict(validation, finding, path)
        finding_id = finding.get("finding_id")
        validation.require(is_nonempty_string(finding_id), f"{path}.finding_id 不能为空")
        validation.require(finding_id not in finding_map, f"{path}.finding_id 重复")
        if is_nonempty_string(finding_id):
            finding_map[finding_id] = finding
        validation.require(finding.get("severity") in SEVERITIES, f"{path}.severity 非法")
        validation.require(finding.get("category") in CATEGORIES, f"{path}.category 非法")
        for field in ("title", "description", "impact"):
            validation.require(is_nonempty_string(finding.get(field)), f"{path}.{field} 不能为空")
        validation.require(finding.get("status") in FINDING_STATUSES, f"{path}.status 非法")
        validation.require(finding.get("responsible_skill") in RESPONSIBLE_SKILLS, f"{path}.responsible_skill 非法")
        validation.require(finding.get("suggested_route") in ROUTES - {"pending", "continue-to-reviewer"}, f"{path}.suggested_route 非法")
        locations = require_list(validation, finding.get("locations"), f"{path}.locations")
        evidence_refs = require_list(validation, finding.get("evidence_refs"), f"{path}.evidence_refs")
        validation.require(bool(locations), f"{path}.locations 不能为空")
        validation.require(bool(evidence_refs), f"{path}.evidence_refs 不能为空")
        for location_index, location in enumerate(locations):
            validate_location(validation, location, f"{path}.locations[{location_index}]")

    summary = require_dict(validation, root.get("summary"), "summary")
    conclusion = summary.get("conclusion")
    validation.require(conclusion in {"pending", "ready", "needs_revision", "blocked", "superseded"}, "summary.conclusion 非法")
    route = summary.get("recommended_route")
    validation.require(route in ROUTES, "summary.recommended_route 非法")
    require_list(validation, summary.get("limitations"), "summary.limitations")

    severity_fields = {
        "blocker": "blocking_finding_ids",
        "major": "major_finding_ids",
        "minor": "minor_finding_ids",
    }
    open_by_severity: dict[str, set[str]] = {severity: set() for severity in SEVERITIES}
    for finding_id, finding in finding_map.items():
        if finding.get("status") == "open":
            open_by_severity[finding.get("severity")].add(finding_id)
    for severity, field in severity_fields.items():
        listed = set(require_list(validation, summary.get(field), f"summary.{field}"))
        validation.require(listed == open_by_severity[severity], f"summary.{field} 必须精确列出开放的 {severity} 问题")

    not_assessable = {category for category, entry in coverage_map.items() if entry.get("status") == "not_assessable"}
    listed_not_assessable = set(require_list(validation, summary.get("not_assessable_categories"), "summary.not_assessable_categories"))
    validation.require(listed_not_assessable == not_assessable, "summary.not_assessable_categories 与 coverage 不一致")

    if formal:
        validation.require(set(coverage_map) == CATEGORIES, "正式审计必须覆盖全部十一类")
        validation.require(check_categories == CATEGORIES, "正式审计每个类别至少有一个检查项")
        validation.require(conclusion == status, "正式审计 status 与 summary.conclusion 必须一致")

    any_failed = any(check.get("status") == "fail" for check in checks if isinstance(check, dict))
    any_not_assessable_check = any(check.get("status") == "not_assessable" for check in checks if isinstance(check, dict))
    any_open = any(open_by_severity.values())
    if status == "ready":
        validation.require(level == "full", "ready 只允许 full 范围")
        validation.require(not not_assessable and not any_not_assessable_check, "ready 不允许不可评估项")
        validation.require(not any_failed, "ready 不允许失败检查")
        validation.require(not open_by_severity["blocker"] and not open_by_severity["major"], "ready 不允许开放 blocker/major")
        validation.require(route == "continue-to-reviewer", "ready 必须路由 continue-to-reviewer")
    elif status == "needs_revision":
        validation.require(any_failed or any_open, "needs_revision 必须有失败检查或开放问题")
        validation.require(route not in {"pending", "continue-to-reviewer", "request-materials"}, "needs_revision 必须路由到责任 Skill")
    elif status == "blocked":
        validation.require(bool(not_assessable) or bool(scope.get("missing_materials")) or bool(open_by_severity["blocker"]), "blocked 必须有不可评估项、缺失材料或 blocker")
        validation.require(route == "request-materials", "blocked 必须路由 request-materials")

    return validation.errors


def valid_fixture() -> dict[str, Any]:
    checks = []
    coverage = []
    for index, category in enumerate(sorted(CATEGORIES), start=1):
        coverage.append({"category": category, "status": "assessed", "missing_materials": []})
        checks.append(
            {
                "check_id": f"CHK-{index:02d}",
                "category": category,
                "status": "pass",
                "description": f"{category} 已核对",
                "locations": [{"artifact_ref": "paper/main.tex", "locator_type": "section", "locator": "Section 1"}],
                "evidence_refs": ["snapshot:SNAP-001"],
            }
        )
    return {
        "schema_version": "1.0",
        "audit_id": "PA-TEST",
        "version": 1,
        "status": "ready",
        "created_at": "2026-07-29T00:00:00+08:00",
        "updated_at": "2026-07-29T00:00:00+08:00",
        "snapshot": {
            "snapshot_id": "SNAP-001",
            "frozen_at": "2026-07-29T00:00:00+08:00",
            "immutable": True,
            "manifest_digest": "0" * 64,
            "files": [{"path": "paper/main.tex", "sha256": "0" * 64}],
        },
        "scope": {
            "level": "full",
            "manuscript_refs": ["paper/main.tex"],
            "result_snapshot_ref": ".cvpr/result.yaml#RESULT-001",
            "venue": None,
            "venue_requirements_ref": None,
            "missing_materials": [],
        },
        "ledger_refs": {
            "claims": ".cvpr/claims.yaml",
            "numbers": ".cvpr/paper/numbers.yaml",
            "citations": ".cvpr/paper/citations.yaml",
            "terminology": ".cvpr/paper/terminology.yaml",
            "runs": ["RUN-001"],
            "statistics": ["STAT-001"],
            "figures": ["FIG-001"],
            "reproducibility": ["REPRO-001"],
        },
        "coverage": coverage,
        "checks": checks,
        "findings": [],
        "summary": {
            "conclusion": "ready",
            "blocking_finding_ids": [],
            "major_finding_ids": [],
            "minor_finding_ids": [],
            "not_assessable_categories": [],
            "recommended_route": "continue-to-reviewer",
            "limitations": [],
        },
        "supersedes": None,
    }


def self_test() -> int:
    positive = valid_fixture()
    cases: list[tuple[str, dict[str, Any], bool]] = [("正例", positive, True)]

    missing_category = copy.deepcopy(positive)
    missing_category["coverage"].pop()
    missing_category["checks"].pop()
    cases.append(("缺少必查类别", missing_category, False))

    vague_location = copy.deepcopy(positive)
    vague_location["checks"][0]["locations"][0]["locator"] = ""
    cases.append(("位置不精确", vague_location, False))

    forbidden_verdict = copy.deepcopy(positive)
    forbidden_verdict["acceptance_decision"] = "accept"
    cases.append(("越权录用判断", forbidden_verdict, False))

    partial_ready = copy.deepcopy(positive)
    partial_ready["scope"]["level"] = "partial"
    cases.append(("局部材料误判 ready", partial_ready, False))

    failed = False
    for name, record, should_pass in cases:
        errors = validate_record(record)
        passed = not errors
        if passed != should_pass:
            failed = True
            print(f"FAIL {name}: {errors}")
        else:
            print(f"PASS {name}")
    return 1 if failed else 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("record", nargs="?", help="JSON 表达的 YAML 审计文件")
    parser.add_argument("--project-root", type=pathlib.Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        return self_test()
    if not args.record:
        parser.error("需要审计文件或 --self-test")
    try:
        data = json.loads(pathlib.Path(args.record).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"ERROR: 无法读取 JSON 表达的 YAML：{exc}", file=sys.stderr)
        return 2
    errors = validate_record(data, args.project_root)
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print("OK: 论文审计契约有效")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Validate a cvpr-reviewer scientific review using only the standard library."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import pathlib
import re
import sys
from typing import Any


BASE_AXES = {
    "contribution_novelty",
    "technical_correctness",
    "experimental_rigor_fairness",
    "reproducibility",
    "clarity",
    "limitations_ethics",
}
EMPHASES = {
    "contribution_and_positioning",
    "technical_validity",
    "experiments_reproducibility_and_communication",
}
STATUSES = {"proposed", "in_progress", "reviewed", "needs_revision", "blocked", "superseded"}
POSTURES = {"ready_within_scope", "revision_required", "blocked_by_missing_evidence"}
RATINGS = {"strong", "adequate", "weak", "not_assessable"}
SEVERITIES = {"blocker", "major", "minor"}
FINDING_STATUSES = {"open", "resolved", "accepted_risk"}
FORBIDDEN_KEYS = {
    "acceptance_decision",
    "acceptance_recommendation",
    "acceptance_probability",
    "editor_decision",
    "reviewer_name",
    "reviewer_institution",
    "reviewer_biography",
    "reviewer_identity",
    "rebuttal",
    "author_response",
    "manuscript_patch",
    "rewritten_text",
    "goal_assessment",
    "do_verdict",
    "result_verdict",
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


def require_dict(validation: Validation, value: Any, path: str) -> dict[str, Any]:
    validation.require(isinstance(value, dict), f"{path} 必须是对象")
    return value if isinstance(value, dict) else {}


def require_list(validation: Validation, value: Any, path: str) -> list[Any]:
    validation.require(isinstance(value, list), f"{path} 必须是列表")
    return value if isinstance(value, list) else []


def scan_forbidden(validation: Validation, value: Any, path: str = "$") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            validation.require(key not in FORBIDDEN_KEYS, f"{path}.{key} 是越权字段")
            scan_forbidden(validation, child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            scan_forbidden(validation, child, f"{path}[{index}]")


def validate_record(data: Any, project_root: pathlib.Path | None = None) -> list[str]:
    validation = Validation()
    root = require_dict(validation, data, "$")
    scan_forbidden(validation, root)

    validation.require(root.get("schema_version") == "1.0", "schema_version 必须为 1.0")
    validation.require(is_nonempty_string(root.get("review_id")), "review_id 不能为空")
    validation.require(isinstance(root.get("version"), int) and root.get("version", 0) >= 1, "version 必须为正整数")
    status = root.get("status")
    validation.require(status in STATUSES, "status 非法")
    formal = status in {"reviewed", "needs_revision", "blocked"}

    snapshot = require_dict(validation, root.get("snapshot"), "snapshot")
    if formal:
        validation.require(is_nonempty_string(snapshot.get("snapshot_id")), "正式三审必须有 snapshot_id")
        validation.require(is_nonempty_string(snapshot.get("frozen_at")), "正式三审必须有 frozen_at")
        validation.require(snapshot.get("immutable") is True, "正式三审快照必须 immutable=true")
        validation.require(SHA256.fullmatch(str(snapshot.get("manifest_digest", ""))) is not None, "manifest_digest 必须为 SHA-256")
    snapshot_id = snapshot.get("snapshot_id")

    files = require_list(validation, snapshot.get("files"), "snapshot.files")
    seen_paths: set[str] = set()
    for index, file_record in enumerate(files):
        path = f"snapshot.files[{index}]"
        file_record = require_dict(validation, file_record, path)
        rel = file_record.get("path")
        digest = file_record.get("sha256")
        validation.require(is_nonempty_string(rel), f"{path}.path 不能为空")
        validation.require(SHA256.fullmatch(str(digest or "")) is not None, f"{path}.sha256 必须为 SHA-256")
        if is_nonempty_string(rel):
            validation.require(rel not in seen_paths, f"{path}.path 重复")
            seen_paths.add(rel)
            rel_path = pathlib.PurePosixPath(rel)
            safe = not rel_path.is_absolute() and ".." not in rel_path.parts
            validation.require(safe, f"{path}.path 必须是安全相对路径")
            if safe and project_root is not None:
                actual = (project_root / pathlib.Path(*rel_path.parts)).resolve()
                validation.require(actual.is_relative_to(project_root.resolve()), f"{path}.path 越出项目根目录")
                if actual.is_file():
                    validation.require(hashlib.sha256(actual.read_bytes()).hexdigest() == digest, f"{path}.sha256 与实际文件不一致")
                else:
                    validation.errors.append(f"{path}.path 对应文件不存在")

    scope = require_dict(validation, root.get("scope"), "scope")
    level = scope.get("level")
    validation.require(level in {"full", "partial"}, "scope.level 必须为 full 或 partial")
    manuscript_refs = require_list(validation, scope.get("manuscript_refs"), "scope.manuscript_refs")
    require_list(validation, scope.get("missing_materials"), "scope.missing_materials")
    if formal:
        validation.require(bool(manuscript_refs), "正式三审必须列出 manuscript_refs")
        validation.require(bool(files), "正式三审必须冻结至少一个实际文件")
        validation.require(is_nonempty_string(scope.get("assessment_boundary")), "正式三审必须写明 assessment_boundary")
    venue = scope.get("venue")
    venue_ref = scope.get("venue_requirements_ref")
    if venue is not None:
        validation.require(is_nonempty_string(venue), "scope.venue 必须为非空字符串或 null")
        validation.require(is_nonempty_string(venue_ref), "指定 venue 时必须提供 venue_requirements_ref")

    axes = require_list(validation, root.get("axes"), "axes")
    validation.require(len(axes) == len(set(axes)), "axes 不得重复")
    expected_axes = set(BASE_AXES)
    if venue is not None:
        expected_axes.add("venue_fit")
    validation.require(set(axes) == expected_axes, "axes 必须精确覆盖适用评审轴")

    orchestration = require_dict(validation, root.get("orchestration"), "orchestration")
    validation.require(orchestration.get("skill") == "cvpr-someagents", "必须调用 cvpr-someagents")
    validation.require(orchestration.get("mode") == "B", "三审必须使用模式 B")
    validation.require(orchestration.get("requested_reviewers") == 3, "必须请求恰好三位审稿人")
    if formal:
        validation.require(orchestration.get("completed_reviewers") == 3, "正式三审必须完成恰好三份报告")
        validation.require(orchestration.get("same_snapshot") is True, "三位审稿人必须使用同一快照")
        validation.require(orchestration.get("peer_outputs_hidden_until_completion") is True, "报告完成前必须互不可见")

    reports = require_list(validation, root.get("reviewer_reports"), "reviewer_reports")
    if formal:
        validation.require(len(reports) == 3, "正式三审必须恰好三份报告")
    reviewer_ids: set[str] = set()
    emphases: set[str] = set()
    all_findings: dict[str, dict[str, Any]] = {}
    finding_owners: dict[str, str] = {}
    weak_seen = False
    not_assessable_seen = False

    for index, report in enumerate(reports):
        path = f"reviewer_reports[{index}]"
        report = require_dict(validation, report, path)
        reviewer_id = report.get("reviewer_id")
        emphasis = report.get("emphasis")
        validation.require(is_nonempty_string(reviewer_id), f"{path}.reviewer_id 不能为空")
        validation.require(reviewer_id not in reviewer_ids, f"{path}.reviewer_id 重复")
        if is_nonempty_string(reviewer_id):
            reviewer_ids.add(reviewer_id)
        validation.require(emphasis in EMPHASES, f"{path}.emphasis 非法")
        validation.require(emphasis not in emphases, f"{path}.emphasis 重复")
        if emphasis in EMPHASES:
            emphases.add(emphasis)
        validation.require(report.get("independent") is True, f"{path}.independent 必须为 true")
        validation.require(report.get("input_snapshot_id") == snapshot_id, f"{path}.input_snapshot_id 与冻结快照不一致")
        validation.require(report.get("status") == "completed", f"{path}.status 必须为 completed")
        validation.require(report.get("overall_posture") in POSTURES, f"{path}.overall_posture 非法")

        assessments = require_list(validation, report.get("axis_assessments"), f"{path}.axis_assessments")
        assessed_axes: set[str] = set()
        for assessment_index, assessment in enumerate(assessments):
            assessment_path = f"{path}.axis_assessments[{assessment_index}]"
            assessment = require_dict(validation, assessment, assessment_path)
            axis = assessment.get("axis")
            rating = assessment.get("rating")
            validation.require(axis in expected_axes, f"{assessment_path}.axis 非法")
            validation.require(axis not in assessed_axes, f"{assessment_path}.axis 重复")
            if axis in expected_axes:
                assessed_axes.add(axis)
            validation.require(rating in RATINGS, f"{assessment_path}.rating 非法")
            validation.require(is_nonempty_string(assessment.get("rationale")), f"{assessment_path}.rationale 不能为空")
            evidence_refs = require_list(validation, assessment.get("evidence_refs"), f"{assessment_path}.evidence_refs")
            if rating == "not_assessable":
                not_assessable_seen = True
                validation.require(bool(assessment.get("missing_evidence")), f"{assessment_path}.missing_evidence 不能为空")
            else:
                validation.require(bool(evidence_refs), f"{assessment_path}.evidence_refs 不能为空")
            if rating == "weak":
                weak_seen = True
        if formal:
            validation.require(assessed_axes == expected_axes, f"{path} 必须覆盖全部适用评审轴")

        require_list(validation, report.get("strengths"), f"{path}.strengths")
        require_list(validation, report.get("limitations"), f"{path}.limitations")
        findings = require_list(validation, report.get("findings"), f"{path}.findings")
        for finding_index, finding in enumerate(findings):
            finding_path = f"{path}.findings[{finding_index}]"
            finding = require_dict(validation, finding, finding_path)
            finding_id = finding.get("finding_id")
            validation.require(is_nonempty_string(finding_id), f"{finding_path}.finding_id 不能为空")
            validation.require(finding_id not in all_findings, f"{finding_path}.finding_id 必须全局唯一")
            if is_nonempty_string(finding_id):
                all_findings[finding_id] = finding
                finding_owners[finding_id] = str(reviewer_id)
            validation.require(is_nonempty_string(finding.get("finding_key")), f"{finding_path}.finding_key 不能为空")
            validation.require(finding.get("axis") in expected_axes, f"{finding_path}.axis 非法")
            validation.require(finding.get("severity") in SEVERITIES, f"{finding_path}.severity 非法")
            validation.require(finding.get("status") in FINDING_STATUSES, f"{finding_path}.status 非法")
            for field in ("summary", "impact", "required_action"):
                validation.require(is_nonempty_string(finding.get(field)), f"{finding_path}.{field} 不能为空")
            validation.require(bool(require_list(validation, finding.get("manuscript_locations"), f"{finding_path}.manuscript_locations")), f"{finding_path}.manuscript_locations 不能为空")
            validation.require(bool(require_list(validation, finding.get("evidence_refs"), f"{finding_path}.evidence_refs")), f"{finding_path}.evidence_refs 不能为空")

    if formal:
        validation.require(emphases == EMPHASES, "三份报告必须使用三个不同且完整的侧重点")

    synthesis = require_dict(validation, root.get("synthesis"), "synthesis")
    synthesis_status = synthesis.get("status")
    validation.require(synthesis_status in {"pending", "reviewed", "needs_revision", "blocked", "superseded"}, "synthesis.status 非法")
    registry = require_list(validation, synthesis.get("finding_registry"), "synthesis.finding_registry")
    registry_keys: set[str] = set()
    registered_ids: list[str] = []
    derived_consensus: set[str] = set()
    derived_minority: set[str] = set()
    derived_blocking: set[str] = set()
    for index, entry in enumerate(registry):
        path = f"synthesis.finding_registry[{index}]"
        entry = require_dict(validation, entry, path)
        key = entry.get("finding_key")
        validation.require(is_nonempty_string(key), f"{path}.finding_key 不能为空")
        validation.require(key not in registry_keys, f"{path}.finding_key 重复")
        if is_nonempty_string(key):
            registry_keys.add(key)
        source_ids = require_list(validation, entry.get("source_finding_ids"), f"{path}.source_finding_ids")
        supporting_reviewers = require_list(validation, entry.get("supporting_reviewer_ids"), f"{path}.supporting_reviewer_ids")
        validation.require(bool(source_ids), f"{path}.source_finding_ids 不能为空")
        validation.require(len(source_ids) == len(set(source_ids)), f"{path}.source_finding_ids 不得重复")
        validation.require(set(supporting_reviewers) == {finding_owners.get(item) for item in source_ids}, f"{path}.supporting_reviewer_ids 与来源不一致")
        for source_id in source_ids:
            validation.require(source_id in all_findings, f"{path} 引用了不存在的 finding_id")
            if source_id in all_findings:
                validation.require(all_findings[source_id].get("finding_key") == key, f"{path} 合并了不同 finding_key")
            registered_ids.append(source_id)
        classification = entry.get("classification")
        expected_classification = "minority" if len(set(supporting_reviewers)) == 1 else "consensus"
        validation.require(classification == expected_classification, f"{path}.classification 与支持审稿人数不一致")
        if classification == "minority" and is_nonempty_string(key):
            derived_minority.add(key)
        if classification == "consensus" and is_nonempty_string(key):
            derived_consensus.add(key)
        validation.require(entry.get("severity") in SEVERITIES, f"{path}.severity 非法")
        validation.require(is_nonempty_string(entry.get("summary")), f"{path}.summary 不能为空")
        validation.require(entry.get("disposition") in {"open", "resolved", "accepted_risk"}, f"{path}.disposition 非法")
        if entry.get("severity") == "blocker" and entry.get("disposition") == "open" and is_nonempty_string(key):
            derived_blocking.add(key)

    listed_all = require_list(validation, synthesis.get("all_finding_ids"), "synthesis.all_finding_ids")
    validation.require(len(registered_ids) == len(set(registered_ids)), "每个 finding_id 必须且只能进入一个 registry 条目")
    validation.require(set(registered_ids) == set(all_findings), "finding_registry 必须保留三份报告的全部问题")
    validation.require(set(listed_all) == set(all_findings), "synthesis.all_finding_ids 必须精确列出全部问题")
    validation.require(set(require_list(validation, synthesis.get("consensus_finding_keys"), "synthesis.consensus_finding_keys")) == derived_consensus, "consensus_finding_keys 不一致")
    validation.require(set(require_list(validation, synthesis.get("minority_finding_keys"), "synthesis.minority_finding_keys")) == derived_minority, "minority_finding_keys 必须保留所有少数意见")
    validation.require(set(require_list(validation, synthesis.get("unresolved_blocking_finding_keys"), "synthesis.unresolved_blocking_finding_keys")) == derived_blocking, "unresolved_blocking_finding_keys 不一致")
    require_list(validation, synthesis.get("disagreements"), "synthesis.disagreements")
    require_list(validation, synthesis.get("limitations"), "synthesis.limitations")
    require_list(validation, synthesis.get("next_actions"), "synthesis.next_actions")

    open_major_or_blocker = any(
        finding.get("status") == "open" and finding.get("severity") in {"major", "blocker"}
        for finding in all_findings.values()
    )
    if formal:
        validation.require(synthesis_status == status, "正式三审 status 与 synthesis.status 必须一致")
    if status == "reviewed":
        validation.require(level == "full", "reviewed 只允许 full 范围")
        validation.require(not open_major_or_blocker and not weak_seen and not not_assessable_seen, "reviewed 不允许开放 major/blocker、weak 或不可评估轴")
        validation.require(not derived_blocking, "reviewed 不允许未解决 blocker")
    elif status == "needs_revision":
        validation.require(open_major_or_blocker or weak_seen, "needs_revision 必须有开放 major/blocker 或 weak 评估")
    elif status == "blocked":
        validation.require(not_assessable_seen or bool(scope.get("missing_materials")) or bool(derived_blocking), "blocked 必须有不可评估轴、缺失材料或 blocker")

    return validation.errors


def valid_fixture() -> dict[str, Any]:
    reports = []
    for index, emphasis in enumerate(sorted(EMPHASES), start=1):
        reports.append(
            {
                "reviewer_id": f"R{index}",
                "emphasis": emphasis,
                "independent": True,
                "input_snapshot_id": "SNAP-PAPER-001",
                "status": "completed",
                "axis_assessments": [
                    {
                        "axis": axis,
                        "rating": "strong",
                        "rationale": f"{axis} 在当前证据内充分",
                        "evidence_refs": ["paper/main.tex#section-1"],
                        "missing_evidence": [],
                    }
                    for axis in sorted(BASE_AXES)
                ],
                "strengths": [{"summary": "证据链完整", "evidence_refs": ["paper/main.tex#section-1"]}],
                "findings": [],
                "limitations": [],
                "overall_posture": "ready_within_scope",
            }
        )
    return {
        "schema_version": "1.0",
        "review_id": "PR-TEST",
        "version": 1,
        "status": "reviewed",
        "created_at": "2026-07-29T00:00:00+08:00",
        "updated_at": "2026-07-29T00:00:00+08:00",
        "snapshot": {
            "snapshot_id": "SNAP-PAPER-001",
            "frozen_at": "2026-07-29T00:00:00+08:00",
            "immutable": True,
            "manifest_digest": "0" * 64,
            "files": [{"path": "paper/main.tex", "sha256": "0" * 64}],
        },
        "scope": {
            "level": "full",
            "manuscript_refs": ["paper/main.tex"],
            "paper_audit_ref": "PA-001",
            "result_snapshot_ref": "RESULT-001",
            "venue": None,
            "venue_requirements_ref": None,
            "assessment_boundary": "完整稿件与冻结证据",
            "missing_materials": [],
        },
        "orchestration": {
            "skill": "cvpr-someagents",
            "mode": "B",
            "requested_reviewers": 3,
            "completed_reviewers": 3,
            "same_snapshot": True,
            "peer_outputs_hidden_until_completion": True,
        },
        "axes": sorted(BASE_AXES),
        "reviewer_reports": reports,
        "synthesis": {
            "status": "reviewed",
            "finding_registry": [],
            "all_finding_ids": [],
            "consensus_finding_keys": [],
            "minority_finding_keys": [],
            "disagreements": [],
            "unresolved_blocking_finding_keys": [],
            "limitations": [],
            "next_actions": [],
        },
        "supersedes": None,
    }


def self_test() -> int:
    positive = valid_fixture()
    cases: list[tuple[str, dict[str, Any], bool]] = [("正例", positive, True)]

    two_reviewers = copy.deepcopy(positive)
    two_reviewers["reviewer_reports"].pop()
    two_reviewers["orchestration"]["completed_reviewers"] = 2
    cases.append(("少于三位审稿人", two_reviewers, False))

    snapshot_mismatch = copy.deepcopy(positive)
    snapshot_mismatch["reviewer_reports"][0]["input_snapshot_id"] = "OTHER"
    cases.append(("审稿快照不一致", snapshot_mismatch, False))

    missing_axis = copy.deepcopy(positive)
    missing_axis["reviewer_reports"][0]["axis_assessments"].pop()
    cases.append(("单份报告缺少评审轴", missing_axis, False))

    forbidden_decision = copy.deepcopy(positive)
    forbidden_decision["editor_decision"] = "accept"
    cases.append(("越权编辑决定", forbidden_decision, False))

    minority_dropped = copy.deepcopy(positive)
    finding = {
        "finding_id": "R1-F1",
        "finding_key": "missing-fair-baseline",
        "axis": "experimental_rigor_fairness",
        "severity": "minor",
        "summary": "缺少一项公平性说明",
        "impact": "比较条件可能被误读",
        "manuscript_locations": ["paper/main.tex#table-1"],
        "evidence_refs": ["audit:PA-001"],
        "required_action": "补充训练预算说明",
        "status": "open",
    }
    minority_dropped["reviewer_reports"][0]["findings"].append(finding)
    minority_dropped["synthesis"]["all_finding_ids"] = ["R1-F1"]
    cases.append(("少数意见未进入综合 registry", minority_dropped, False))

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
    parser.add_argument("record", nargs="?", help="JSON 表达的 YAML 审稿文件")
    parser.add_argument("--project-root", type=pathlib.Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        return self_test()
    if not args.record:
        parser.error("需要审稿文件或 --self-test")
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
    print("OK: 科学审稿契约有效")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

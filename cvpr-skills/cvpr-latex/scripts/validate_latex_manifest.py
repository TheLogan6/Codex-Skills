#!/usr/bin/env python3
"""Validate a cvpr-latex assembly manifest."""

from __future__ import annotations

import argparse
import copy
import json
import sys
import tempfile
from pathlib import Path
from typing import Any


STATUSES = {"proposed", "assembled", "compiled", "qa_passed", "accepted", "blocked", "superseded"}
MODES = {"assemble", "venue_migration", "compile", "anonymization_audit", "layout_audit", "supplementary"}
STAGES = {"review", "camera_ready"}
ANONYMITY = {"double_blind", "single_blind", "open", "not_applicable"}
ASSET_KINDS = {"manuscript", "bibliography", "figure", "table", "equation", "supplementary", "template_addon"}
CHECK_STATUSES = {"passed", "failed", "not_applicable"}
ISSUE_SEVERITIES = {"blocker", "major", "minor", "info"}
FORBIDDEN_KEYS = {"goal_assessment", "goal_verdict", "do_verdict", "result_route"}


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


def is_choice(value: Any, choices: set[str]) -> bool:
    return isinstance(value, str) and value in choices


def load_json(path: Path, validation: Validation, label: str) -> Any:
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        validation.errors.append(f"{label}: 无法解析为 JSON/YAML 1.2 子集：{exc}")
        return None


def require_keys(
    container: dict[str, Any],
    keys: tuple[str, ...],
    label: str,
    validation: Validation,
) -> None:
    for key in keys:
        validation.require(key in container, f"{label}: 缺少字段 {key}")


def require_list(
    container: dict[str, Any],
    key: str,
    label: str,
    validation: Validation,
) -> list[Any]:
    value = container.get(key)
    validation.require(isinstance(value, list), f"{label}.{key}: 必须是数组")
    return value if isinstance(value, list) else []


def is_safe_project_path(value: Any) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    path = Path(value)
    return not path.is_absolute() and ".." not in path.parts


def check_project_path(
    value: Any,
    label: str,
    project_root: Path | None,
    validation: Validation,
    *,
    directory: bool = False,
) -> None:
    validation.require(is_safe_project_path(value), f"{label}: 必须是安全的项目相对路径")
    if project_root is None or not is_safe_project_path(value):
        return
    candidate = project_root / str(value)
    exists = candidate.is_dir() if directory else candidate.is_file()
    validation.require(exists, f"{label}: {'目录' if directory else '文件'}不存在 {value}")


def scan_forbidden(value: Any, label: str, validation: Validation) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            validation.require(key.lower() not in FORBIDDEN_KEYS, f"{label}.{key}: 不得保存 Goal/DO/Result 判定")
            scan_forbidden(child, f"{label}.{key}", validation)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            scan_forbidden(child, f"{label}[{index}]", validation)


def validate_snapshot(value: Any, formal: bool, result_data: Any, validation: Validation) -> None:
    validation.require(isinstance(value, dict), "source_snapshot: 必须是对象")
    if not isinstance(value, dict):
        return
    require_keys(value, ("snapshot_id", "result_ref", "result_status", "frozen", "freshness"), "source_snapshot", validation)
    validation.require(is_choice(value.get("freshness"), {"current", "stale"}), "source_snapshot.freshness: 只允许 current 或 stale")
    if not formal:
        return
    validation.require(has_value(value.get("snapshot_id")), "source_snapshot.snapshot_id: 正式组装不得为空")
    validation.require(value.get("result_ref") == ".cvpr/result.yaml", "source_snapshot.result_ref: 必须为 .cvpr/result.yaml")
    validation.require(value.get("result_status") == "accepted", "source_snapshot.result_status: 必须为 accepted")
    validation.require(value.get("frozen") is True, "source_snapshot.frozen: 必须为 true")
    validation.require(value.get("freshness") == "current", "source_snapshot.freshness: 正式组装必须为 current")
    validation.require(isinstance(result_data, dict), "正式组装必须通过 --result-file 联合校验")
    if isinstance(result_data, dict):
        validation.require(result_data.get("status") == "accepted", "result.yaml.status: 必须为 accepted")
        frozen = result_data.get("frozen_evidence")
        validation.require(isinstance(frozen, dict), "result.yaml.frozen_evidence: 必须是对象")
        if isinstance(frozen, dict):
            validation.require(
                frozen.get("snapshot_id") == value.get("snapshot_id"),
                "source_snapshot.snapshot_id: 与 result.yaml 冻结快照不一致",
            )


def validate_contract(
    data: Any,
    *,
    project_root: Path | None = None,
    result_data: Any = None,
) -> list[str]:
    validation = Validation()
    validation.require(isinstance(data, dict), "根节点必须是对象")
    if not isinstance(data, dict):
        return validation.errors

    scan_forbidden(data, "root", validation)
    require_keys(
        data,
        (
            "schema_version",
            "assembly_id",
            "version",
            "status",
            "mode",
            "source_snapshot",
            "target",
            "template",
            "source_assets",
            "content_integrity",
            "build",
            "anonymization",
            "layout_qa",
            "outputs",
            "user_confirmation",
            "supersedes",
        ),
        "root",
        validation,
    )
    validation.require(data.get("schema_version") == "1.0", "schema_version: 仅支持 1.0")
    validation.require(has_value(data.get("assembly_id")), "assembly_id: 不得为空")
    validation.require(isinstance(data.get("version"), int) and data.get("version", 0) > 0, "version: 必须是正整数")
    status = data.get("status")
    mode = data.get("mode")
    validation.require(is_choice(status, STATUSES), "status: 非法状态")
    validation.require(is_choice(mode, MODES), "mode: 非法模式")
    formal = is_choice(status, {"assembled", "compiled", "qa_passed", "accepted"})
    compiled = is_choice(status, {"compiled", "qa_passed", "accepted"})
    qa_complete = is_choice(status, {"qa_passed", "accepted"})
    if formal:
        validation.require(project_root is not None, "正式组装必须提供 --project-root 核对真实产物")

    validate_snapshot(data.get("source_snapshot"), formal, result_data, validation)

    target = data.get("target")
    validation.require(isinstance(target, dict), "target: 必须是对象")
    anonymity_requirement = None
    page_limit = None
    if isinstance(target, dict):
        require_keys(
            target,
            (
                "venue",
                "track",
                "year",
                "submission_stage",
                "anonymity_requirement",
                "rules_verified",
                "rules_verified_at",
                "official_source_refs",
                "page_limit",
                "page_limit_scope",
            ),
            "target",
            validation,
        )
        sources = require_list(target, "official_source_refs", "target", validation)
        validation.require(is_choice(target.get("submission_stage"), STAGES) or target.get("submission_stage") is None, "target.submission_stage: 非法阶段")
        anonymity_requirement = target.get("anonymity_requirement")
        validation.require(is_choice(anonymity_requirement, ANONYMITY) or anonymity_requirement is None, "target.anonymity_requirement: 非法值")
        page_limit = target.get("page_limit")
        validation.require(page_limit is None or (isinstance(page_limit, int) and page_limit > 0), "target.page_limit: 必须为空或正整数")
        if formal:
            for key in ("venue", "track", "year", "submission_stage", "anonymity_requirement", "rules_verified_at", "page_limit", "page_limit_scope"):
                validation.require(has_value(target.get(key)), f"target.{key}: 正式组装不得为空")
            validation.require(target.get("rules_verified") is True, "target.rules_verified: 正式组装必须为 true")
            validation.require(bool(sources), "target.official_source_refs: 正式组装不得为空")

    template = data.get("template")
    validation.require(isinstance(template, dict), "template: 必须是对象")
    if isinstance(template, dict):
        require_keys(template, ("verified", "source_ref", "version", "checksum", "local_root"), "template", validation)
        if formal:
            validation.require(template.get("verified") is True, "template.verified: 正式组装必须为 true")
            validation.require(has_value(template.get("source_ref")), "template.source_ref: 正式组装不得为空")
            validation.require(
                has_value(template.get("version")) or has_value(template.get("checksum")),
                "template: version 与 checksum 至少一个不得为空",
            )
            check_project_path(template.get("local_root"), "template.local_root", project_root, validation, directory=True)

    assets = require_list(data, "source_assets", "root", validation)
    asset_ids: set[str] = set()
    for index, asset in enumerate(assets, start=1):
        label = f"source_assets[{index}]"
        validation.require(isinstance(asset, dict), f"{label}: 必须是对象")
        if not isinstance(asset, dict):
            continue
        require_keys(asset, ("id", "kind", "path", "source_snapshot_ref", "evidence_refs"), label, validation)
        asset_id = asset.get("id")
        validation.require(has_value(asset_id), f"{label}.id: 不得为空")
        if isinstance(asset_id, str):
            validation.require(asset_id not in asset_ids, f"{label}.id: 重复 {asset_id}")
            asset_ids.add(asset_id)
        validation.require(is_choice(asset.get("kind"), ASSET_KINDS), f"{label}.kind: 非法类型")
        check_project_path(asset.get("path"), f"{label}.path", project_root if formal else None, validation)
        evidence = require_list(asset, "evidence_refs", label, validation)
        if formal:
            validation.require(has_value(asset.get("source_snapshot_ref")), f"{label}.source_snapshot_ref: 正式组装不得为空")
            validation.require(bool(evidence), f"{label}.evidence_refs: 正式组装不得为空")
    if formal:
        validation.require(bool(assets), "source_assets: 正式组装不得为空")
        validation.require(any(item.get("kind") == "manuscript" for item in assets if isinstance(item, dict)), "source_assets: 缺少 manuscript")

    integrity = data.get("content_integrity")
    validation.require(isinstance(integrity, dict), "content_integrity: 必须是对象")
    if isinstance(integrity, dict):
        require_keys(integrity, ("content_snapshot_refs", "layout_changes", "unauthorized_content_changes"), "content_integrity", validation)
        snapshots = require_list(integrity, "content_snapshot_refs", "content_integrity", validation)
        changes = require_list(integrity, "layout_changes", "content_integrity", validation)
        unauthorized = require_list(integrity, "unauthorized_content_changes", "content_integrity", validation)
        for index, change in enumerate(changes, start=1):
            label = f"content_integrity.layout_changes[{index}]"
            validation.require(isinstance(change, dict), f"{label}: 必须是对象")
            if isinstance(change, dict):
                require_keys(change, ("id", "description", "content_changed", "evidence_refs"), label, validation)
                validation.require(change.get("content_changed") is False, f"{label}.content_changed: 必须为 false")
                require_list(change, "evidence_refs", label, validation)
        if formal:
            validation.require(bool(snapshots), "content_integrity.content_snapshot_refs: 正式组装不得为空")
            validation.require(not unauthorized, "content_integrity.unauthorized_content_changes: 正式组装必须为空")

    build = data.get("build")
    validation.require(isinstance(build, dict), "build: 必须是对象")
    page_count = None
    if isinstance(build, dict):
        require_keys(
            build,
            (
                "engine",
                "commands",
                "return_code",
                "success",
                "log_refs",
                "error_count",
                "unresolved_reference_count",
                "pdf_ref",
                "page_count",
            ),
            "build",
            validation,
        )
        commands = require_list(build, "commands", "build", validation)
        logs = require_list(build, "log_refs", "build", validation)
        page_count = build.get("page_count")
        validation.require(page_count is None or (isinstance(page_count, int) and page_count > 0), "build.page_count: 必须为空或正整数")
        if compiled:
            validation.require(has_value(build.get("engine")), "build.engine: 编译完成状态不得为空")
            validation.require(bool(commands), "build.commands: 编译完成状态不得为空")
            validation.require(build.get("return_code") == 0, "build.return_code: 必须为 0")
            validation.require(build.get("success") is True, "build.success: 必须为 true")
            validation.require(bool(logs), "build.log_refs: 编译完成状态不得为空")
            validation.require(build.get("error_count") == 0, "build.error_count: 必须为 0")
            validation.require(build.get("unresolved_reference_count") == 0, "build.unresolved_reference_count: 必须为 0")
            check_project_path(build.get("pdf_ref"), "build.pdf_ref", project_root, validation)
            validation.require(isinstance(page_count, int) and page_count > 0, "build.page_count: 编译完成状态必须是正整数")
            for index, ref in enumerate(logs, start=1):
                check_project_path(ref, f"build.log_refs[{index}]", project_root, validation)

    anonymization = data.get("anonymization")
    validation.require(isinstance(anonymization, dict), "anonymization: 必须是对象")
    if isinstance(anonymization, dict):
        require_keys(anonymization, ("required", "checks", "blockers"), "anonymization", validation)
        checks = require_list(anonymization, "checks", "anonymization", validation)
        blockers = require_list(anonymization, "blockers", "anonymization", validation)
        if formal and is_choice(anonymity_requirement, {"double_blind", "single_blind"}):
            validation.require(anonymization.get("required") is True, "anonymization.required: 匿名投稿必须为 true")
        for index, check in enumerate(checks, start=1):
            label = f"anonymization.checks[{index}]"
            validation.require(isinstance(check, dict), f"{label}: 必须是对象")
            if isinstance(check, dict):
                require_keys(check, ("id", "status", "evidence_refs"), label, validation)
                validation.require(is_choice(check.get("status"), CHECK_STATUSES), f"{label}.status: 非法状态")
                require_list(check, "evidence_refs", label, validation)
        if qa_complete and anonymization.get("required") is True:
            validation.require(bool(checks), "anonymization.checks: 匿名 QA 不得为空")
            validation.require(all(is_choice(item.get("status"), {"passed", "not_applicable"}) for item in checks if isinstance(item, dict)), "anonymization.checks: 存在未通过项")
            validation.require(not blockers, "anonymization.blockers: QA 通过状态必须为空")

    qa = data.get("layout_qa")
    validation.require(isinstance(qa, dict), "layout_qa: 必须是对象")
    if isinstance(qa, dict):
        require_keys(
            qa,
            (
                "rendered",
                "render_dir",
                "contact_sheet_ref",
                "pages_inspected",
                "all_pages_inspected",
                "page_limit_assessment",
                "issues",
                "blockers",
            ),
            "layout_qa",
            validation,
        )
        pages = require_list(qa, "pages_inspected", "layout_qa", validation)
        issues = require_list(qa, "issues", "layout_qa", validation)
        blockers = require_list(qa, "blockers", "layout_qa", validation)
        assessment = qa.get("page_limit_assessment")
        validation.require(isinstance(assessment, dict), "layout_qa.page_limit_assessment: 必须是对象")
        if isinstance(assessment, dict):
            require_keys(assessment, ("compliant", "counted_pages", "scope", "evidence_refs"), "layout_qa.page_limit_assessment", validation)
            evidence = require_list(assessment, "evidence_refs", "layout_qa.page_limit_assessment", validation)
            if qa_complete:
                validation.require(assessment.get("compliant") is True, "layout_qa.page_limit_assessment.compliant: 必须为 true")
                validation.require(isinstance(assessment.get("counted_pages"), int), "layout_qa.page_limit_assessment.counted_pages: 必须是整数")
                validation.require(has_value(assessment.get("scope")), "layout_qa.page_limit_assessment.scope: 不得为空")
                validation.require(bool(evidence), "layout_qa.page_limit_assessment.evidence_refs: 不得为空")
                if isinstance(page_limit, int) and isinstance(assessment.get("counted_pages"), int):
                    validation.require(assessment.get("counted_pages") <= page_limit, "layout_qa: 计入限制的页数超过 page_limit")
        for index, issue in enumerate(issues, start=1):
            label = f"layout_qa.issues[{index}]"
            validation.require(isinstance(issue, dict), f"{label}: 必须是对象")
            if isinstance(issue, dict):
                require_keys(issue, ("id", "severity", "description", "resolved", "evidence_refs"), label, validation)
                validation.require(is_choice(issue.get("severity"), ISSUE_SEVERITIES), f"{label}.severity: 非法级别")
                validation.require(isinstance(issue.get("resolved"), bool), f"{label}.resolved: 必须是布尔值")
                require_list(issue, "evidence_refs", label, validation)
        if qa_complete:
            validation.require(qa.get("rendered") is True, "layout_qa.rendered: QA 通过状态必须为 true")
            check_project_path(qa.get("render_dir"), "layout_qa.render_dir", project_root, validation, directory=True)
            check_project_path(qa.get("contact_sheet_ref"), "layout_qa.contact_sheet_ref", project_root, validation)
            validation.require(qa.get("all_pages_inspected") is True, "layout_qa.all_pages_inspected: 必须为 true")
            if isinstance(page_count, int):
                valid_page_numbers = all(type(page) is int and page > 0 for page in pages)
                validation.require(valid_page_numbers, "layout_qa.pages_inspected: 页码必须是正整数")
                if valid_page_numbers:
                    validation.require(
                        sorted(set(pages)) == list(range(1, page_count + 1)),
                        "layout_qa.pages_inspected: 必须恰好覆盖 PDF 全部页面",
                    )
            validation.require(not blockers, "layout_qa.blockers: QA 通过状态必须为空")
            validation.require(
                not any(
                    is_choice(item.get("severity"), {"blocker", "major"}) and item.get("resolved") is not True
                    for item in issues
                    if isinstance(item, dict)
                ),
                "layout_qa.issues: 存在未解决 blocker/major 问题",
            )

    outputs = require_list(data, "outputs", "root", validation)
    for index, output in enumerate(outputs, start=1):
        label = f"outputs[{index}]"
        validation.require(isinstance(output, dict), f"{label}: 必须是对象")
        if not isinstance(output, dict):
            continue
        require_keys(output, ("id", "kind", "path", "evidence_refs"), label, validation)
        check_project_path(output.get("path"), f"{label}.path", project_root if formal else None, validation)
        evidence = require_list(output, "evidence_refs", label, validation)
        if formal:
            validation.require(bool(evidence), f"{label}.evidence_refs: 正式组装不得为空")
    if formal:
        validation.require(bool(outputs), "outputs: 正式组装不得为空")

    confirmation = data.get("user_confirmation")
    validation.require(isinstance(confirmation, dict), "user_confirmation: 必须是对象")
    if isinstance(confirmation, dict):
        require_keys(confirmation, ("confirmed", "confirmed_at"), "user_confirmation", validation)
        if status == "accepted":
            validation.require(confirmation.get("confirmed") is True, "user_confirmation.confirmed: accepted 时必须为 true")
            validation.require(has_value(confirmation.get("confirmed_at")), "user_confirmation.confirmed_at: accepted 时不得为空")

    return validation.errors


def make_self_test_contract(root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    for directory in ("template", "paper", "build", "render"):
        (root / directory).mkdir()
    for file_name in ("paper/main.tex", "build/main.pdf", "build/main.log", "render/contact.png", "paper/manifest.json"):
        (root / file_name).write_text("test", encoding="utf-8")
    contract = {
        "schema_version": "1.0",
        "assembly_id": "LATEX-SELFTEST",
        "version": 1,
        "status": "accepted",
        "mode": "layout_audit",
        "source_snapshot": {
            "snapshot_id": "SNAP-001",
            "result_ref": ".cvpr/result.yaml",
            "result_status": "accepted",
            "frozen": True,
            "freshness": "current",
        },
        "target": {
            "venue": "ExampleConf",
            "track": "main",
            "year": 2026,
            "submission_stage": "review",
            "anonymity_requirement": "double_blind",
            "rules_verified": True,
            "rules_verified_at": "2026-07-28",
            "official_source_refs": ["https://example.org/official"],
            "page_limit": 8,
            "page_limit_scope": "main content",
        },
        "template": {
            "verified": True,
            "source_ref": "https://example.org/official-template",
            "version": "2026.1",
            "checksum": "sha256:test",
            "local_root": "template",
        },
        "source_assets": [
            {
                "id": "ASSET-001",
                "kind": "manuscript",
                "path": "paper/main.tex",
                "source_snapshot_ref": "SNAP-001",
                "evidence_refs": ["evidence:manuscript"],
            }
        ],
        "content_integrity": {
            "content_snapshot_refs": ["SNAP-001"],
            "layout_changes": [
                {
                    "id": "LAYOUT-001",
                    "description": "float placement",
                    "content_changed": False,
                    "evidence_refs": ["evidence:diff"],
                }
            ],
            "unauthorized_content_changes": [],
        },
        "build": {
            "engine": "latexmk",
            "commands": ["latexmk -pdf main.tex"],
            "return_code": 0,
            "success": True,
            "log_refs": ["build/main.log"],
            "error_count": 0,
            "unresolved_reference_count": 0,
            "pdf_ref": "build/main.pdf",
            "page_count": 3,
        },
        "anonymization": {
            "required": True,
            "checks": [{"id": "ANON-001", "status": "passed", "evidence_refs": ["evidence:metadata"]}],
            "blockers": [],
        },
        "layout_qa": {
            "rendered": True,
            "render_dir": "render",
            "contact_sheet_ref": "render/contact.png",
            "pages_inspected": [1, 2, 3],
            "all_pages_inspected": True,
            "page_limit_assessment": {
                "compliant": True,
                "counted_pages": 3,
                "scope": "main content",
                "evidence_refs": ["evidence:page-count"],
            },
            "issues": [],
            "blockers": [],
        },
        "outputs": [{"id": "OUT-001", "kind": "manifest", "path": "paper/manifest.json", "evidence_refs": ["evidence:output"]}],
        "user_confirmation": {"confirmed": True, "confirmed_at": "2026-07-28T12:00:00+08:00"},
        "supersedes": None,
    }
    result = {"status": "accepted", "frozen_evidence": {"snapshot_id": "SNAP-001"}}
    return contract, result


def run_self_test() -> int:
    with tempfile.TemporaryDirectory(prefix="cvpr-latex-test-") as temp_dir:
        root = Path(temp_dir)
        valid, result = make_self_test_contract(root)
        cases: list[tuple[str, dict[str, Any], bool]] = [("valid", valid, True)]

        missing_venue = copy.deepcopy(valid)
        missing_venue["target"]["venue"] = ""
        cases.append(("missing-venue", missing_venue, False))

        build_failed = copy.deepcopy(valid)
        build_failed["build"]["success"] = False
        cases.append(("failed-build", build_failed, False))

        incomplete_pages = copy.deepcopy(valid)
        incomplete_pages["layout_qa"]["pages_inspected"] = [1, 3]
        cases.append(("incomplete-pages", incomplete_pages, False))

        content_changed = copy.deepcopy(valid)
        content_changed["content_integrity"]["unauthorized_content_changes"] = ["claim text removed"]
        cases.append(("content-changed", content_changed, False))

        malformed_types = copy.deepcopy(valid)
        malformed_types["mode"] = {}
        malformed_types["target"]["submission_stage"] = []
        malformed_types["source_assets"][0]["kind"] = {}
        malformed_types["layout_qa"]["pages_inspected"] = [1, "2", 3]
        cases.append(("malformed-types", malformed_types, False))

        failed: list[str] = []
        for name, contract, expected_valid in cases:
            errors = validate_contract(contract, project_root=root, result_data=result)
            if (not errors) != expected_valid:
                failed.append(f"{name}: expected_valid={expected_valid}, errors={errors}")
        if failed:
            print("SELF-TEST FAILED")
            for message in failed:
                print(message)
            return 1
    print("SELF-TEST PASSED: 正例、4 个语义反例与 malformed-type 反例行为符合预期")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", nargs="?", type=Path)
    parser.add_argument("--project-root", type=Path)
    parser.add_argument("--result-file", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        return run_self_test()
    if args.manifest is None:
        parser.error("缺少 manifest；或使用 --self-test")

    loading = Validation()
    data = load_json(args.manifest, loading, "manifest")
    result_data = load_json(args.result_file, loading, "result-file") if args.result_file else None
    if loading.errors:
        for error in loading.errors:
            print(f"ERROR: {error}")
        return 1
    errors = validate_contract(data, project_root=args.project_root, result_data=result_data)
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print(f"OK: {args.manifest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Validate a cvpr-reproducibility manifest."""

from __future__ import annotations

import argparse
import copy
import json
import sys
import tempfile
from pathlib import Path
from typing import Any


STATUSES = {"proposed", "reviewed", "accepted", "blocked", "superseded"}
MODES = {"inventory", "audit", "paper_statement", "anonymous_release", "public_release"}
CATEGORIES = {
    "code",
    "config",
    "environment",
    "seed",
    "data",
    "data_split",
    "model",
    "checkpoint",
    "log",
    "statistics_source",
    "figure_source",
    "third_party_asset",
}
CATEGORY_STATUSES = {"complete", "partial", "not_applicable", "unknown"}
AVAILABILITY = {
    "public",
    "private_reviewer",
    "controlled",
    "restricted",
    "local_only",
    "planned",
    "unknown",
}
ASSERTION_TYPES = {
    "url",
    "doi",
    "accession",
    "license",
    "public_status",
    "access_route",
    "embargo",
    "reviewer_link",
}
VERIFICATION_STATUSES = {"verified", "unverified", "conflicting"}
STATEMENT_TYPES = {
    "code_availability",
    "data_availability",
    "model_availability",
    "restricted_access",
    "supplementary_mapping",
}
STATEMENT_STATUSES = {"draft", "verified", "blocked"}
PACKAGE_TYPES = {"anonymous", "public"}
PACKAGE_STATUSES = {"proposed", "reviewed", "ready", "blocked"}
FORBIDDEN_KEYS = {
    "goal_assessment",
    "goal_verdict",
    "do_verdict",
    "result_route",
    "acceptance_logic_result",
}
SECRET_KEYS = {
    "secret",
    "token",
    "password",
    "api_key",
    "private_key",
    "access_token",
    "refresh_token",
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


def is_choice(value: Any, choices: set[str]) -> bool:
    return isinstance(value, str) and value in choices


def load_json(path: Path, validation: Validation, label: str) -> Any:
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        validation.errors.append(f"{label}: 无法解析为 JSON/YAML 1.2 子集：{exc}")
        return None


def require_list(
    container: dict[str, Any],
    key: str,
    label: str,
    validation: Validation,
) -> list[Any]:
    value = container.get(key)
    validation.require(isinstance(value, list), f"{label}.{key}: 必须是数组")
    return value if isinstance(value, list) else []


def require_keys(
    container: dict[str, Any],
    keys: tuple[str, ...],
    label: str,
    validation: Validation,
) -> None:
    for key in keys:
        validation.require(key in container, f"{label}: 缺少字段 {key}")


def is_safe_project_path(value: Any) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    path = Path(value)
    return not path.is_absolute() and ".." not in path.parts


def check_project_file(
    value: Any,
    label: str,
    project_root: Path | None,
    validation: Validation,
) -> None:
    validation.require(is_safe_project_path(value), f"{label}: 必须是安全的项目相对路径")
    if project_root is not None and is_safe_project_path(value):
        validation.require((project_root / str(value)).is_file(), f"{label}: 文件不存在 {value}")


def scan_forbidden(value: Any, label: str, validation: Validation) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            lowered = key.lower()
            validation.require(lowered not in FORBIDDEN_KEYS, f"{label}.{key}: 不得保存 Goal/DO/Result 判定")
            validation.require(lowered not in SECRET_KEYS, f"{label}.{key}: 不得保存密钥或凭证")
            scan_forbidden(child, f"{label}.{key}", validation)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            scan_forbidden(child, f"{label}[{index}]", validation)


def validate_snapshot(
    value: Any,
    formal: bool,
    result_data: Any,
    validation: Validation,
) -> str | None:
    validation.require(isinstance(value, dict), "source_snapshot: 必须是对象")
    if not isinstance(value, dict):
        return None
    require_keys(
        value,
        ("snapshot_id", "result_ref", "result_status", "frozen", "freshness"),
        "source_snapshot",
        validation,
    )
    snapshot_id = value.get("snapshot_id")
    validation.require(is_choice(value.get("freshness"), {"current", "stale"}), "source_snapshot.freshness: 只允许 current 或 stale")
    if formal:
        validation.require(has_value(snapshot_id), "source_snapshot.snapshot_id: 正式审计不得为空")
        validation.require(value.get("result_ref") == ".cvpr/result.yaml", "source_snapshot.result_ref: 必须指向 .cvpr/result.yaml")
        validation.require(value.get("result_status") == "accepted", "source_snapshot.result_status: 必须为 accepted")
        validation.require(value.get("frozen") is True, "source_snapshot.frozen: 必须为 true")
        validation.require(value.get("freshness") == "current", "source_snapshot.freshness: 正式审计必须为 current")
        validation.require(isinstance(result_data, dict), "正式审计必须通过 --result-file 联合校验")
        if isinstance(result_data, dict):
            validation.require(result_data.get("status") == "accepted", "result.yaml.status: 必须为 accepted")
            frozen = result_data.get("frozen_evidence")
            validation.require(isinstance(frozen, dict), "result.yaml.frozen_evidence: 必须是对象")
            if isinstance(frozen, dict):
                validation.require(
                    frozen.get("snapshot_id") == snapshot_id,
                    "source_snapshot.snapshot_id: 与 result.yaml 冻结快照不一致",
                )
    return snapshot_id if isinstance(snapshot_id, str) else None


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
            "audit_id",
            "version",
            "status",
            "mode",
            "source_snapshot",
            "scope",
            "materials",
            "category_assessments",
            "claim_reproduction_chains",
            "availability_assertions",
            "statements",
            "release_packages",
            "gaps",
            "risks",
            "outputs",
            "user_confirmation",
            "supersedes",
        ),
        "root",
        validation,
    )
    validation.require(data.get("schema_version") == "1.0", "schema_version: 仅支持 1.0")
    validation.require(has_value(data.get("audit_id")), "audit_id: 不得为空")
    validation.require(isinstance(data.get("version"), int) and data.get("version", 0) > 0, "version: 必须是正整数")
    status = data.get("status")
    mode = data.get("mode")
    validation.require(is_choice(status, STATUSES), "status: 非法状态")
    validation.require(is_choice(mode, MODES), "mode: 非法模式")
    formal = is_choice(status, {"reviewed", "accepted"})
    if formal:
        validation.require(project_root is not None, "正式审计必须提供 --project-root 核对真实产物")

    validate_snapshot(data.get("source_snapshot"), formal, result_data, validation)

    materials = require_list(data, "materials", "root", validation)
    material_ids: set[str] = set()
    material_by_id: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(materials, start=1):
        label = f"materials[{index}]"
        validation.require(isinstance(item, dict), f"{label}: 必须是对象")
        if not isinstance(item, dict):
            continue
        require_keys(
            item,
            (
                "id",
                "category",
                "title",
                "source_kind",
                "refs",
                "version",
                "supports_claim_refs",
                "supports_run_ids",
                "availability",
                "availability_assertion_ids",
                "sensitive",
                "public_export_allowed",
                "evidence_refs",
            ),
            label,
            validation,
        )
        material_id = item.get("id")
        validation.require(has_value(material_id), f"{label}.id: 不得为空")
        if isinstance(material_id, str) and material_id:
            validation.require(material_id not in material_ids, f"{label}.id: 重复 {material_id}")
            material_ids.add(material_id)
            material_by_id[material_id] = item
        validation.require(is_choice(item.get("category"), CATEGORIES), f"{label}.category: 非法类别")
        validation.require(is_choice(item.get("source_kind"), {"local", "external", "mixed"}), f"{label}.source_kind: 非法来源类型")
        refs = require_list(item, "refs", label, validation)
        claim_refs = require_list(item, "supports_claim_refs", label, validation)
        run_ids = require_list(item, "supports_run_ids", label, validation)
        assertion_ids = require_list(item, "availability_assertion_ids", label, validation)
        evidence = require_list(item, "evidence_refs", label, validation)
        validation.require(is_choice(item.get("availability"), AVAILABILITY), f"{label}.availability: 非法状态")
        validation.require(isinstance(item.get("sensitive"), bool), f"{label}.sensitive: 必须是布尔值")
        validation.require(isinstance(item.get("public_export_allowed"), bool), f"{label}.public_export_allowed: 必须是布尔值")
        if formal:
            validation.require(bool(refs), f"{label}.refs: 正式审计不得为空")
            validation.require(bool(evidence), f"{label}.evidence_refs: 正式审计不得为空")
        if is_choice(item.get("source_kind"), {"local", "mixed"}):
            for ref_index, ref in enumerate(refs, start=1):
                check_project_file(ref, f"{label}.refs[{ref_index}]", project_root if formal else None, validation)
        if item.get("sensitive") is True:
            validation.require(item.get("availability") != "public", f"{label}: 敏感材料不得标记为 public")
            validation.require(item.get("public_export_allowed") is False, f"{label}: 敏感材料不得允许公开导出")
        if item.get("availability") == "public":
            validation.require(bool(assertion_ids), f"{label}: public 状态必须绑定核验断言")
        if item.get("public_export_allowed") is True:
            validation.require(
                is_choice(item.get("availability"), {"public", "private_reviewer"}),
                f"{label}: 当前可用状态不允许导出",
            )
        _ = claim_refs, run_ids

    gaps = require_list(data, "gaps", "root", validation)
    gap_ids: set[str] = set()
    for index, gap in enumerate(gaps, start=1):
        label = f"gaps[{index}]"
        validation.require(isinstance(gap, dict), f"{label}: 必须是对象")
        if not isinstance(gap, dict):
            continue
        require_keys(gap, ("id", "description", "impact", "required_evidence", "status"), label, validation)
        gap_id = gap.get("id")
        validation.require(has_value(gap_id), f"{label}.id: 不得为空")
        if isinstance(gap_id, str):
            validation.require(gap_id not in gap_ids, f"{label}.id: 重复 {gap_id}")
            gap_ids.add(gap_id)
        validation.require(is_choice(gap.get("status"), {"open", "resolved", "accepted_limitation"}), f"{label}.status: 非法状态")
        require_list(gap, "required_evidence", label, validation)

    assessments = require_list(data, "category_assessments", "root", validation)
    assessed_categories: set[str] = set()
    for index, item in enumerate(assessments, start=1):
        label = f"category_assessments[{index}]"
        validation.require(isinstance(item, dict), f"{label}: 必须是对象")
        if not isinstance(item, dict):
            continue
        require_keys(item, ("category", "status", "rationale", "material_ids", "gap_ids", "evidence_refs"), label, validation)
        category = item.get("category")
        validation.require(is_choice(category, CATEGORIES), f"{label}.category: 非法类别")
        if isinstance(category, str):
            validation.require(category not in assessed_categories, f"{label}.category: 重复 {category}")
            assessed_categories.add(category)
        assessment_status = item.get("status")
        validation.require(is_choice(assessment_status, CATEGORY_STATUSES), f"{label}.status: 非法状态")
        linked_materials = require_list(item, "material_ids", label, validation)
        linked_gaps = require_list(item, "gap_ids", label, validation)
        evidence = require_list(item, "evidence_refs", label, validation)
        for material_id in linked_materials:
            validation.require(isinstance(material_id, str) and material_id in material_ids, f"{label}.material_ids: 未知材料 {material_id}")
        for gap_id in linked_gaps:
            validation.require(isinstance(gap_id, str) and gap_id in gap_ids, f"{label}.gap_ids: 未知缺口 {gap_id}")
        if is_choice(assessment_status, {"partial", "unknown"}):
            validation.require(bool(linked_gaps), f"{label}: partial/unknown 必须绑定 gap")
        if assessment_status == "not_applicable":
            validation.require(has_value(item.get("rationale")), f"{label}.rationale: 不适用必须说明理由")
        if assessment_status == "complete":
            validation.require(bool(linked_materials), f"{label}: complete 必须绑定材料")
            validation.require(bool(evidence), f"{label}: complete 必须有证据")
    if formal:
        validation.require(assessed_categories == CATEGORIES, "category_assessments: 正式审计必须恰好覆盖十二类材料")

    assertions = require_list(data, "availability_assertions", "root", validation)
    assertion_ids: set[str] = set()
    assertion_by_id: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(assertions, start=1):
        label = f"availability_assertions[{index}]"
        validation.require(isinstance(item, dict), f"{label}: 必须是对象")
        if not isinstance(item, dict):
            continue
        require_keys(item, ("id", "type", "subject_ids", "value", "verification_status", "evidence_refs"), label, validation)
        assertion_id = item.get("id")
        validation.require(has_value(assertion_id), f"{label}.id: 不得为空")
        if isinstance(assertion_id, str) and assertion_id:
            validation.require(assertion_id not in assertion_ids, f"{label}.id: 重复 {assertion_id}")
            assertion_ids.add(assertion_id)
            assertion_by_id[assertion_id] = item
        validation.require(is_choice(item.get("type"), ASSERTION_TYPES), f"{label}.type: 非法类型")
        subjects = require_list(item, "subject_ids", label, validation)
        for subject_id in subjects:
            validation.require(isinstance(subject_id, str) and subject_id in material_ids, f"{label}.subject_ids: 未知材料 {subject_id}")
        validation.require(has_value(item.get("value")), f"{label}.value: 不得为空")
        verify_status = item.get("verification_status")
        validation.require(is_choice(verify_status, VERIFICATION_STATUSES), f"{label}.verification_status: 非法状态")
        evidence = require_list(item, "evidence_refs", label, validation)
        if verify_status == "verified":
            validation.require(bool(evidence), f"{label}: verified 必须有核验证据")

    for material_id, material in material_by_id.items():
        linked = material.get("availability_assertion_ids", [])
        for assertion_id in linked:
            validation.require(isinstance(assertion_id, str) and assertion_id in assertion_ids, f"materials[{material_id}]: 未知断言 {assertion_id}")
        if material.get("availability") == "public":
            linked_rows = [assertion_by_id[item] for item in linked if isinstance(item, str) and item in assertion_by_id]
            has_public_status = any(
                row.get("type") == "public_status" and row.get("verification_status") == "verified"
                for row in linked_rows
            )
            has_locator = any(
                is_choice(row.get("type"), {"url", "doi", "accession"}) and row.get("verification_status") == "verified"
                for row in linked_rows
            )
            validation.require(has_public_status and has_locator, f"materials[{material_id}]: public 必须同时有已核验状态和定位断言")

    statements = require_list(data, "statements", "root", validation)
    for index, item in enumerate(statements, start=1):
        label = f"statements[{index}]"
        validation.require(isinstance(item, dict), f"{label}: 必须是对象")
        if not isinstance(item, dict):
            continue
        require_keys(item, ("id", "type", "status", "text", "material_ids", "assertion_ids", "unresolved_refs", "evidence_refs"), label, validation)
        validation.require(is_choice(item.get("type"), STATEMENT_TYPES), f"{label}.type: 非法类型")
        statement_status = item.get("status")
        validation.require(is_choice(statement_status, STATEMENT_STATUSES), f"{label}.status: 非法状态")
        validation.require(has_value(item.get("text")), f"{label}.text: 不得为空")
        linked_materials = require_list(item, "material_ids", label, validation)
        linked_assertions = require_list(item, "assertion_ids", label, validation)
        unresolved = require_list(item, "unresolved_refs", label, validation)
        evidence = require_list(item, "evidence_refs", label, validation)
        for material_id in linked_materials:
            validation.require(isinstance(material_id, str) and material_id in material_ids, f"{label}.material_ids: 未知材料 {material_id}")
        for assertion_id in linked_assertions:
            validation.require(isinstance(assertion_id, str) and assertion_id in assertion_ids, f"{label}.assertion_ids: 未知断言 {assertion_id}")
        if statement_status == "verified":
            validation.require(not unresolved, f"{label}: verified 不得有 unresolved_refs")
            validation.require(bool(evidence), f"{label}: verified 必须有证据")
            for assertion_id in linked_assertions:
                assertion = assertion_by_id.get(assertion_id) if isinstance(assertion_id, str) else None
                validation.require(
                    isinstance(assertion, dict) and assertion.get("verification_status") == "verified",
                    f"{label}: verified 声明引用了未核验断言 {assertion_id}",
                )
    if formal and mode == "paper_statement":
        validation.require(bool(statements), "statements: paper_statement 模式正式审计不得为空")

    packages = require_list(data, "release_packages", "root", validation)
    for index, item in enumerate(packages, start=1):
        label = f"release_packages[{index}]"
        validation.require(isinstance(item, dict), f"{label}: 必须是对象")
        if not isinstance(item, dict):
            continue
        require_keys(item, ("id", "type", "status", "material_ids", "output_refs", "evidence_refs"), label, validation)
        package_type = item.get("type")
        package_status = item.get("status")
        validation.require(is_choice(package_type, PACKAGE_TYPES), f"{label}.type: 非法类型")
        validation.require(is_choice(package_status, PACKAGE_STATUSES), f"{label}.status: 非法状态")
        linked_materials = require_list(item, "material_ids", label, validation)
        output_refs = require_list(item, "output_refs", label, validation)
        evidence = require_list(item, "evidence_refs", label, validation)
        for material_id in linked_materials:
            validation.require(isinstance(material_id, str) and material_id in material_ids, f"{label}.material_ids: 未知材料 {material_id}")
            material = material_by_id.get(material_id, {}) if isinstance(material_id, str) else {}
            if package_type == "public" and package_status == "ready":
                validation.require(material.get("public_export_allowed") is True, f"{label}: public ready 包含不可公开材料 {material_id}")
                validation.require(material.get("sensitive") is False, f"{label}: public ready 包含敏感材料 {material_id}")
        if package_status == "ready":
            validation.require(bool(output_refs), f"{label}: ready 必须有输出")
            validation.require(bool(evidence), f"{label}: ready 必须有证据")
        for ref_index, ref in enumerate(output_refs, start=1):
            check_project_file(ref, f"{label}.output_refs[{ref_index}]", project_root if formal else None, validation)
    if formal and is_choice(mode, {"anonymous_release", "public_release"}):
        expected_type = "anonymous" if mode == "anonymous_release" else "public"
        validation.require(
            any(item.get("type") == expected_type for item in packages if isinstance(item, dict)),
            f"release_packages: {mode} 模式缺少 {expected_type} 包",
        )

    require_list(data, "claim_reproduction_chains", "root", validation)
    require_list(data, "risks", "root", validation)
    outputs = require_list(data, "outputs", "root", validation)
    for index, item in enumerate(outputs, start=1):
        label = f"outputs[{index}]"
        validation.require(isinstance(item, dict), f"{label}: 必须是对象")
        if not isinstance(item, dict):
            continue
        require_keys(item, ("id", "kind", "path", "evidence_refs"), label, validation)
        check_project_file(item.get("path"), f"{label}.path", project_root if formal else None, validation)
        evidence = require_list(item, "evidence_refs", label, validation)
        if formal:
            validation.require(bool(evidence), f"{label}.evidence_refs: 正式审计不得为空")
    if formal:
        validation.require(bool(outputs), "outputs: 正式审计不得为空")

    confirmation = data.get("user_confirmation")
    validation.require(isinstance(confirmation, dict), "user_confirmation: 必须是对象")
    if isinstance(confirmation, dict):
        require_keys(confirmation, ("confirmed", "confirmed_at"), "user_confirmation", validation)
        if status == "accepted":
            validation.require(confirmation.get("confirmed") is True, "user_confirmation.confirmed: accepted 时必须为 true")
            validation.require(has_value(confirmation.get("confirmed_at")), "user_confirmation.confirmed_at: accepted 时不得为空")

    return validation.errors


def make_self_test_contract(root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    (root / "artifacts").mkdir()
    (root / "artifacts" / "audit.json").write_text("{}", encoding="utf-8")
    materials: list[dict[str, Any]] = []
    assessments: list[dict[str, Any]] = []
    for index, category in enumerate(sorted(CATEGORIES), start=1):
        material_id = f"MAT-{index:02d}"
        materials.append(
            {
                "id": material_id,
                "category": category,
                "title": category,
                "source_kind": "external",
                "refs": [f"evidence:{category}"],
                "version": "verified-version",
                "supports_claim_refs": ["CLAIM-001"],
                "supports_run_ids": ["RUN-001"],
                "availability": "controlled",
                "availability_assertion_ids": [],
                "sensitive": False,
                "public_export_allowed": False,
                "evidence_refs": [f"evidence:{category}"],
            }
        )
        assessments.append(
            {
                "category": category,
                "status": "complete",
                "rationale": "verified",
                "material_ids": [material_id],
                "gap_ids": [],
                "evidence_refs": [f"evidence:{category}"],
            }
        )
    contract = {
        "schema_version": "1.0",
        "audit_id": "REPRO-SELFTEST",
        "version": 1,
        "status": "accepted",
        "mode": "audit",
        "source_snapshot": {
            "snapshot_id": "SNAP-001",
            "result_ref": ".cvpr/result.yaml",
            "result_status": "accepted",
            "frozen": True,
            "freshness": "current",
        },
        "scope": {"paper_ref": "paper/main.tex", "venue": "ExampleConf", "track": "main", "year": 2026, "submission_stage": "review"},
        "materials": materials,
        "category_assessments": assessments,
        "claim_reproduction_chains": [{"claim_ref": "CLAIM-001", "material_ids": [item["id"] for item in materials]}],
        "availability_assertions": [],
        "statements": [],
        "release_packages": [],
        "gaps": [],
        "risks": [],
        "outputs": [{"id": "OUT-001", "kind": "audit", "path": "artifacts/audit.json", "evidence_refs": ["evidence:audit"]}],
        "user_confirmation": {"confirmed": True, "confirmed_at": "2026-07-28T12:00:00+08:00"},
        "supersedes": None,
    }
    result = {"status": "accepted", "frozen_evidence": {"snapshot_id": "SNAP-001"}}
    return contract, result


def run_self_test() -> int:
    with tempfile.TemporaryDirectory(prefix="cvpr-repro-test-") as temp_dir:
        root = Path(temp_dir)
        valid, result = make_self_test_contract(root)
        cases: list[tuple[str, dict[str, Any], bool]] = [("valid", valid, True)]

        missing_category = copy.deepcopy(valid)
        missing_category["category_assessments"].pop()
        cases.append(("missing-category", missing_category, False))

        sensitive_public = copy.deepcopy(valid)
        sensitive_public["materials"][0]["sensitive"] = True
        sensitive_public["materials"][0]["availability"] = "public"
        sensitive_public["materials"][0]["public_export_allowed"] = True
        cases.append(("sensitive-public", sensitive_public, False))

        wrong_snapshot = copy.deepcopy(valid)
        wrong_snapshot["source_snapshot"]["snapshot_id"] = "SNAP-WRONG"
        cases.append(("wrong-snapshot", wrong_snapshot, False))

        leaked_verdict = copy.deepcopy(valid)
        leaked_verdict["goal_verdict"] = "passed"
        cases.append(("forbidden-verdict", leaked_verdict, False))

        malformed_types = copy.deepcopy(valid)
        malformed_types["mode"] = []
        malformed_types["materials"][0]["category"] = {}
        malformed_types["materials"][0]["availability_assertion_ids"] = [[]]
        malformed_types["category_assessments"][0]["material_ids"] = [[]]
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

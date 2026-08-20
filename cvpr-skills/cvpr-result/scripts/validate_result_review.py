#!/usr/bin/env python3
"""Validate the cvpr-result secondary-review contract."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


STATUSES = {"proposed", "reviewed", "accepted", "blocked", "superseded"}
DO_VERDICTS = {"passed", "not_met", "indeterminate"}
REVIEW_ROLES = {
    "goal_and_protocol",
    "experiment_and_ablation",
    "evidence_and_reproducibility",
}
REVIEW_VERDICTS = {"confirm", "challenge", "blocked"}
CONSENSUS_VERDICTS = {"pending", "confirmed", "challenged", "blocked"}
ROUTES = {
    "pending",
    "paper",
    "return-to-do",
    "return-to-plan",
    "return-to-goal",
    "restart-idea",
}
CONFIRMATION_STATUSES = {"pending", "confirmed", "rejected"}
PRESENTATION_STATUSES = {"pending", "presented"}


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


def load_contract(path: Path, validation: Validation) -> Any:
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        validation.errors.append(f"{path}: 无法解析为 JSON/YAML 1.2 子集：{exc}")
        return None


def validate_state_alignment(
    contract: dict[str, Any],
    state: Any,
    final_review: bool,
    validation: Validation,
) -> None:
    if not final_review:
        return
    validation.require(isinstance(state, dict), "正式复核必须通过 --state-file 联合校验")
    if not isinstance(state, dict):
        return
    assessment = state.get("goal_assessment")
    validation.require(isinstance(assessment, dict), "state.yaml.goal_assessment: 必须是对象")
    do_ref = contract.get("do_assessment_ref")
    if not isinstance(assessment, dict) or not isinstance(do_ref, dict):
        return
    expected = {
        "goal_id": assessment.get("goal_id"),
        "goal_version": assessment.get("goal_version"),
        "assessment_status": assessment.get("status"),
        "audited_at": assessment.get("audited_at"),
    }
    for key, value in expected.items():
        validation.require(
            do_ref.get(key) == value,
            f"do_assessment_ref.{key}: 与 state.yaml.goal_assessment 不一致",
        )


def validate_artifact_records(
    rows: list[Any],
    label: str,
    project_root: Path | None,
    required: bool,
    validation: Validation,
) -> None:
    if required:
        validation.require(bool(rows), f"{label}: 不得为空")
    seen: set[str] = set()
    for index, row in enumerate(rows, start=1):
        item_label = f"{label}[{index}]"
        validation.require(isinstance(row, dict), f"{item_label}: 必须是对象")
        if not isinstance(row, dict):
            continue
        for key in ("id", "manifest_ref", "output_refs", "evidence_refs"):
            validation.require(key in row, f"{item_label}: 缺少字段 {key}")
        artifact_id = row.get("id")
        validation.require(
            isinstance(artifact_id, str) and bool(artifact_id),
            f"{item_label}.id: 必须是非空字符串",
        )
        if isinstance(artifact_id, str):
            validation.require(artifact_id not in seen, f"{item_label}: 重复 ID {artifact_id}")
            seen.add(artifact_id)
        manifest_ref = row.get("manifest_ref")
        validation.require(has_value(manifest_ref), f"{item_label}.manifest_ref: 不得为空")
        outputs = require_list(row, "output_refs", item_label, validation)
        evidence = require_list(row, "evidence_refs", item_label, validation)
        if required:
            validation.require(bool(outputs), f"{item_label}.output_refs: 不得为空")
            validation.require(bool(evidence), f"{item_label}.evidence_refs: 不得为空")
        if project_root is not None:
            for path in [manifest_ref, *outputs]:
                if isinstance(path, str) and path:
                    candidate = Path(path)
                    validation.require(not candidate.is_absolute() and ".." not in candidate.parts, f"{item_label}: 非法项目路径 {path}")
                    if not candidate.is_absolute() and ".." not in candidate.parts:
                        validation.require((project_root / candidate).is_file(), f"{item_label}: 文件不存在 {path}")


def validate_do_ref(
    value: Any,
    final_review: bool,
    validation: Validation,
) -> str | None:
    validation.require(isinstance(value, dict), "do_assessment_ref: 必须是对象")
    if not isinstance(value, dict):
        return None
    for key in (
        "goal_id",
        "goal_version",
        "state_file",
        "assessment_status",
        "audited_at",
        "evidence_refs",
    ):
        validation.require(key in value, f"do_assessment_ref: 缺少字段 {key}")
    verdict = value.get("assessment_status")
    validation.require(verdict in DO_VERDICTS, "do_assessment_ref.assessment_status: 非法判定")
    evidence = require_list(value, "evidence_refs", "do_assessment_ref", validation)
    validation.require(
        value.get("state_file") == ".cvpr/state.yaml",
        "do_assessment_ref.state_file: 必须是 .cvpr/state.yaml",
    )
    if final_review:
        for key in ("goal_id", "goal_version", "audited_at"):
            validation.require(has_value(value.get(key)), f"do_assessment_ref.{key}: 不得为空")
        validation.require(bool(evidence), "do_assessment_ref.evidence_refs: 不得为空")
    return verdict if isinstance(verdict, str) else None


def validate_frozen_evidence(
    value: Any,
    final_review: bool,
    validation: Validation,
) -> str | None:
    validation.require(isinstance(value, dict), "frozen_evidence: 必须是对象")
    if not isinstance(value, dict):
        return None
    for key in (
        "snapshot_id",
        "frozen_at",
        "goal_ref",
        "plan_ref",
        "code_refs",
        "run_ids",
        "result_artifacts",
        "deviation_refs",
    ):
        validation.require(key in value, f"frozen_evidence: 缺少字段 {key}")
    for key in ("code_refs", "run_ids", "result_artifacts", "deviation_refs"):
        require_list(value, key, "frozen_evidence", validation)
    if final_review:
        for key in ("snapshot_id", "frozen_at", "goal_ref", "plan_ref"):
            validation.require(has_value(value.get(key)), f"frozen_evidence.{key}: 不得为空")
        for key in ("code_refs", "run_ids", "result_artifacts"):
            validation.require(bool(value.get(key)), f"frozen_evidence.{key}: 不得为空")
    snapshot_id = value.get("snapshot_id")
    return snapshot_id if isinstance(snapshot_id, str) else None


def validate_reviews(
    value: Any,
    snapshot_id: str | None,
    final_review: bool,
    validation: Validation,
) -> list[dict[str, Any]]:
    validation.require(isinstance(value, list), "reviewer_reports: 必须是数组")
    if not isinstance(value, list):
        return []
    if final_review:
        validation.require(len(value) == 3, "reviewer_reports: 正式复核必须恰好三位审稿人")

    reviewer_ids: set[str] = set()
    roles: set[str] = set()
    reports: list[dict[str, Any]] = []
    for index, row in enumerate(value, start=1):
        label = f"reviewer_reports[{index}]"
        validation.require(isinstance(row, dict), f"{label}: 必须是对象")
        if not isinstance(row, dict):
            continue
        reports.append(row)
        for key in (
            "reviewer_id",
            "role",
            "independent",
            "input_snapshot_id",
            "status",
            "verdict",
            "findings",
            "blocking_issues",
            "limitations",
            "evidence_refs",
        ):
            validation.require(key in row, f"{label}: 缺少字段 {key}")
        reviewer_id = row.get("reviewer_id")
        validation.require(
            isinstance(reviewer_id, str) and bool(reviewer_id),
            f"{label}.reviewer_id: 必须是非空字符串",
        )
        if isinstance(reviewer_id, str):
            validation.require(reviewer_id not in reviewer_ids, f"{label}: 重复 reviewer_id")
            reviewer_ids.add(reviewer_id)
        role = row.get("role")
        validation.require(role in REVIEW_ROLES, f"{label}.role: 非法角色")
        if isinstance(role, str):
            validation.require(role not in roles, f"{label}: 重复角色 {role}")
            roles.add(role)
        validation.require(row.get("independent") is True, f"{label}.independent: 必须为 true")
        validation.require(
            row.get("input_snapshot_id") == snapshot_id,
            f"{label}.input_snapshot_id: 与冻结快照不一致",
        )
        validation.require(
            row.get("status") in {"pending", "completed"},
            f"{label}.status: 非法状态",
        )
        validation.require(row.get("verdict") in REVIEW_VERDICTS, f"{label}.verdict: 非法结论")
        for key in ("findings", "blocking_issues", "limitations", "evidence_refs"):
            require_list(row, key, label, validation)
        if final_review:
            validation.require(row.get("status") == "completed", f"{label}.status: 必须 completed")
            validation.require(bool(row.get("findings")), f"{label}.findings: 不得为空")
            validation.require(bool(row.get("evidence_refs")), f"{label}.evidence_refs: 不得为空")

    if final_review:
        validation.require(roles == REVIEW_ROLES, "reviewer_reports: 必须完整覆盖三个固定角色")
    return reports


def validate_consensus(
    value: Any,
    reports: list[dict[str, Any]],
    final_review: bool,
    validation: Validation,
) -> str | None:
    validation.require(isinstance(value, dict), "review_consensus: 必须是对象")
    if not isinstance(value, dict):
        return None
    for key in (
        "status",
        "do_verdict_confirmed",
        "verdict",
        "blocking_issues",
        "reconciled_disagreements",
        "evidence_refs",
    ):
        validation.require(key in value, f"review_consensus: 缺少字段 {key}")
    verdict = value.get("verdict")
    validation.require(verdict in CONSENSUS_VERDICTS, "review_consensus.verdict: 非法结论")
    blocking = require_list(value, "blocking_issues", "review_consensus", validation)
    require_list(value, "reconciled_disagreements", "review_consensus", validation)
    evidence = require_list(value, "evidence_refs", "review_consensus", validation)
    if final_review:
        validation.require(value.get("status") == "completed", "review_consensus.status: 必须 completed")
        validation.require(verdict != "pending", "review_consensus.verdict: 不得 pending")
        validation.require(bool(evidence), "review_consensus.evidence_refs: 不得为空")

        report_verdicts = [row.get("verdict") for row in reports]
        report_blocking = [
            issue
            for row in reports
            for issue in row.get("blocking_issues", [])
        ]
        if verdict == "confirmed":
            validation.require(
                report_verdicts == ["confirm", "confirm", "confirm"]
                or (
                    len(report_verdicts) == 3
                    and all(item == "confirm" for item in report_verdicts)
                ),
                "review_consensus: confirmed 要求三位审稿人全部 confirm",
            )
            validation.require(not report_blocking, "review_consensus: 三审仍有阻断问题")
            validation.require(not blocking, "review_consensus.blocking_issues: confirmed 时必须为空")
            validation.require(
                value.get("do_verdict_confirmed") is True,
                "review_consensus.do_verdict_confirmed: confirmed 时必须为 true",
            )
        elif verdict == "challenged":
            validation.require(
                any(item == "challenge" for item in report_verdicts),
                "review_consensus: challenged 至少需要一位审稿人 challenge",
            )
            validation.require(
                value.get("do_verdict_confirmed") is False,
                "review_consensus.do_verdict_confirmed: challenged 时必须为 false",
            )
        elif verdict == "blocked":
            validation.require(
                any(item == "blocked" for item in report_verdicts) or bool(blocking),
                "review_consensus: blocked 必须有审稿人阻断或协调阻断",
            )
            validation.require(
                value.get("do_verdict_confirmed") in {False, None},
                "review_consensus.do_verdict_confirmed: blocked 时不得为 true",
            )
    return verdict if isinstance(verdict, str) else None


def validate_idea_feedback(
    value: Any,
    required: bool,
    validation: Validation,
) -> None:
    if not required:
        validation.require(value is None or isinstance(value, dict), "idea_feedback: 必须是对象或 null")
        return
    validation.require(isinstance(value, dict), "restart-idea 路由必须提供 idea_feedback")
    if not isinstance(value, dict):
        return
    validation.require(has_value(value.get("original_idea_ref")), "idea_feedback.original_idea_ref: 不得为空")
    validation.require(has_value(value.get("start_contract_ref")), "idea_feedback.start_contract_ref: 不得为空")
    for key in (
        "failed_criterion_refs",
        "key_result_refs",
        "review_report_refs",
        "historical_candidate_refs",
        "reusable_asset_refs",
        "ruled_out_explanations",
        "new_questions",
    ):
        rows = require_list(value, key, "idea_feedback", validation)
        if key in (
            "failed_criterion_refs",
            "key_result_refs",
            "review_report_refs",
            "historical_candidate_refs",
        ):
            validation.require(bool(rows), f"idea_feedback.{key}: 不得为空")


def validate_user_handoff(
    presentation: Any,
    confirmation: Any,
    accepted: bool,
    validation: Validation,
) -> None:
    validation.require(isinstance(presentation, dict), "user_presentation: 必须是对象")
    if isinstance(presentation, dict):
        validation.require(
            presentation.get("status") in PRESENTATION_STATUSES,
            "user_presentation.status: 非法状态",
        )
        if accepted:
            validation.require(
                presentation.get("status") == "presented",
                "accepted 时 user_presentation.status 必须 presented",
            )
            for key in ("presented_at", "evidence_ref"):
                validation.require(
                    has_value(presentation.get(key)),
                    f"user_presentation.{key}: 不得为空",
                )

    validation.require(isinstance(confirmation, dict), "user_confirmation: 必须是对象")
    if isinstance(confirmation, dict):
        validation.require(
            confirmation.get("status") in CONFIRMATION_STATUSES,
            "user_confirmation.status: 非法状态",
        )
        if accepted:
            validation.require(
                confirmation.get("status") == "confirmed",
                "accepted 时 user_confirmation.status 必须 confirmed",
            )
            for key in ("confirmed_at", "confirmed_by", "evidence_ref"):
                validation.require(
                    has_value(confirmation.get(key)),
                    f"user_confirmation.{key}: 不得为空",
                )


def validate_contract(
    contract: Any,
    state: Any,
    project_root: Path | None,
    validation: Validation,
) -> None:
    validation.require(isinstance(contract, dict), "result.yaml: 根节点必须是对象")
    if not isinstance(contract, dict):
        return
    required_fields = (
        "schema_version",
        "result_id",
        "version",
        "status",
        "created_at",
        "updated_at",
        "do_assessment_ref",
        "frozen_evidence",
        "reviewer_reports",
        "review_consensus",
        "route",
        "idea_feedback",
        "statistics_artifacts",
        "figure_artifacts",
        "user_presentation",
        "user_confirmation",
        "supersedes",
    )
    for key in required_fields:
        validation.require(key in contract, f"result.yaml: 缺少字段 {key}")

    status = contract.get("status")
    validation.require(status in STATUSES, "result.yaml.status: 非法状态")
    final_review = status in {"reviewed", "accepted"}
    accepted = status == "accepted"
    validation.require(has_value(contract.get("schema_version")), "result.yaml.schema_version: 不得为空")
    validation.require(has_value(contract.get("result_id")), "result.yaml.result_id: 不得为空")
    version = contract.get("version")
    validation.require(
        isinstance(version, int) and not isinstance(version, bool) and version >= 1,
        "result.yaml.version: 必须是正整数",
    )
    if final_review:
        validation.require(has_value(contract.get("created_at")), "result.yaml.created_at: 不得为空")
        validation.require(has_value(contract.get("updated_at")), "result.yaml.updated_at: 不得为空")
    if status == "superseded":
        validation.require(has_value(contract.get("supersedes")), "superseded 时 supersedes 不得为空")

    do_verdict = validate_do_ref(contract.get("do_assessment_ref"), final_review, validation)
    validate_state_alignment(contract, state, final_review, validation)
    snapshot_id = validate_frozen_evidence(contract.get("frozen_evidence"), final_review, validation)
    reports = validate_reviews(contract.get("reviewer_reports"), snapshot_id, final_review, validation)
    consensus = validate_consensus(contract.get("review_consensus"), reports, final_review, validation)

    route = contract.get("route")
    validation.require(route in ROUTES, "result.yaml.route: 非法路由")
    if final_review:
        validation.require(route != "pending", "正式复核 route 不得 pending")
        if route == "paper":
            validation.require(do_verdict == "passed", "paper 路由要求 DO 判定 passed")
            validation.require(consensus == "confirmed", "paper 路由要求三审 confirmed")
        elif route == "restart-idea":
            validation.require(
                do_verdict in {"not_met", "indeterminate"},
                "restart-idea 要求 DO 判定 not_met 或 indeterminate",
            )
            validation.require(consensus == "confirmed", "restart-idea 要求三审 confirmed")
        else:
            validation.require(
                consensus in {"challenged", "blocked"},
                "返回上游路由要求三审 challenged 或 blocked",
            )

    statistics = require_list(contract, "statistics_artifacts", "result.yaml", validation)
    figures = require_list(contract, "figure_artifacts", "result.yaml", validation)
    validate_artifact_records(
        statistics,
        "statistics_artifacts",
        project_root,
        accepted and route == "paper",
        validation,
    )
    validate_artifact_records(
        figures,
        "figure_artifacts",
        project_root,
        accepted and route == "paper",
        validation,
    )

    validate_idea_feedback(contract.get("idea_feedback"), route == "restart-idea" and final_review, validation)
    validate_user_handoff(
        contract.get("user_presentation"),
        contract.get("user_confirmation"),
        accepted,
        validation,
    )


def self_test_idea_feedback() -> int:
    valid = {
        "original_idea_ref": ".cvpr/start.yaml#I-001",
        "start_contract_ref": ".cvpr/start.yaml#START-001",
        "failed_criterion_refs": [".cvpr/goal.yaml#AC-001"],
        "key_result_refs": ["runs/final.json"],
        "review_report_refs": [".cvpr/result.yaml#R-1"],
        "historical_candidate_refs": [".cvpr/start.yaml#I-001"],
        "reusable_asset_refs": ["src/model.py"],
        "ruled_out_explanations": [],
        "new_questions": ["失败机制是否形成新问题"],
    }
    cases: list[tuple[str, Any, bool]] = [
        ("正例", valid, True),
        ("缺少 start_contract_ref", {**valid, "start_contract_ref": ""}, False),
        ("历史候选为空", {**valid, "historical_candidate_refs": []}, False),
        ("字段类型错误", {**valid, "key_result_refs": {}}, False),
    ]
    failed = False
    for name, payload, should_pass in cases:
        validation = Validation()
        validate_idea_feedback(payload, True, validation)
        passed = not validation.errors
        if passed != should_pass:
            failed = True
            print(f"FAIL {name}: {validation.errors}")
        else:
            print(f"PASS {name}")
    return 1 if failed else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="校验 cvpr-result 的结果复核契约")
    parser.add_argument("result_file", nargs="?", type=Path, help=".cvpr/result.yaml 路径")
    parser.add_argument("--state-file", type=Path, help=".cvpr/state.yaml 路径")
    parser.add_argument("--project-root", type=Path, help="可选项目根目录，用于检查统计和图形产物")
    parser.add_argument("--self-test", action="store_true", help="运行 IDEA 自我纠正交接自测试")
    args = parser.parse_args()

    if args.self_test:
        return self_test_idea_feedback()
    if args.result_file is None:
        parser.error("必须提供 result_file，或使用 --self-test")

    validation = Validation()
    contract = load_contract(args.result_file, validation)
    state = load_contract(args.state_file, validation) if args.state_file else None
    project_root = args.project_root.expanduser().resolve() if args.project_root else None
    validate_contract(contract, state, project_root, validation)
    if validation.errors:
        print("INVALID:")
        for error in validation.errors:
            print(f"- {error}")
        return 1
    status = contract.get("status") if isinstance(contract, dict) else None
    print(f"OK: {args.result_file} 结果复核契约有效（状态 {status}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())

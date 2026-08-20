#!/usr/bin/env python3
"""Validate a cvpr-plan contract and, for final plans, its goal contract."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


PLAN_STATUSES = {
    "proposed",
    "accepted",
    "revised",
    "blocked",
    "rejected",
    "superseded",
}
STAGE_STATUSES = {
    "proposed",
    "running",
    "executed",
    "accepted",
    "blocked",
    "rejected",
    "superseded",
}
STAGE_VALIDATION_KINDS = {
    "research_development",
    "research_evidence",
    "goal_verification",
    "evidence_audit",
}
REVIEW_STATUSES = {"not_started", "completed"}
REVIEW_VERDICTS = {"pass", "revise", "reject"}
REVIEW_FINAL_VERDICTS = {"pending", "pass", "revise", "reject"}
QUESTION_STATUSES = {"open", "resolved"}
CONFIRMATION_STATUSES = {"pending", "confirmed", "rejected"}
FINAL_STATUSES = {"accepted", "revised"}
FORBIDDEN_TIME_KEYS = {
    "time_estimate",
    "estimated_time",
    "estimated_duration",
    "duration_estimate",
    "schedule",
    "timeline",
    "deadline",
    "sprint",
    "工期",
    "时间预估",
    "预计时长",
    "排期",
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


def load_document(path: Path, label: str, validation: Validation) -> Any:
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


def reject_time_fields(value: Any, path: str, validation: Validation) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            key_text = str(key)
            validation.require(
                key_text.lower() not in FORBIDDEN_TIME_KEYS and key_text not in FORBIDDEN_TIME_KEYS,
                f"{path}.{key_text}: 阶段计划禁止时间预估或排期字段",
            )
            reject_time_fields(child, f"{path}.{key_text}", validation)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            reject_time_fields(child, f"{path}[{index}]", validation)


def extract_goal(
    goal: Any,
    validation: Validation,
) -> tuple[set[str], set[str], dict[str, Any]]:
    validation.require(isinstance(goal, dict), "goal.yaml: 根节点必须是对象")
    if not isinstance(goal, dict):
        return set(), set(), {}

    validation.require(
        goal.get("status") in {"accepted", "revised"},
        "goal.yaml.status: 正式计划要求 accepted 或 revised",
    )
    confirmation = goal.get("user_confirmation")
    validation.require(
        isinstance(confirmation, dict) and confirmation.get("status") == "confirmed",
        "goal.yaml.user_confirmation: 必须已确认",
    )
    development_base = goal.get("development_base")
    validation.require(
        isinstance(development_base, dict),
        "goal.yaml.development_base: 必须是对象",
    )
    if isinstance(development_base, dict):
        validation.require(
            development_base.get("user_confirmed") is True,
            "goal.yaml.development_base.user_confirmed: 必须为 true",
        )
        validation.require(
            development_base.get("project_state") in {"existing_project", "selected_repository"},
            "goal.yaml.development_base.project_state: 必须确定开发基础",
        )
        validation.require(
            has_value(development_base.get("project_root")),
            "goal.yaml.development_base.project_root: 不得为空",
        )
        validation.require(
            has_value(development_base.get("commit"))
            or has_value(development_base.get("version_or_snapshot")),
            "goal.yaml.development_base: 必须有不可变版本定位",
        )

    criteria = goal.get("acceptance_criteria")
    validation.require(isinstance(criteria, list), "goal.yaml.acceptance_criteria: 必须是数组")
    all_criteria: set[str] = set()
    required_criteria: set[str] = set()
    if isinstance(criteria, list):
        for index, criterion in enumerate(criteria, start=1):
            label = f"goal.yaml.acceptance_criteria[{index}]"
            validation.require(isinstance(criterion, dict), f"{label}: 必须是对象")
            if not isinstance(criterion, dict):
                continue
            criterion_id = criterion.get("id")
            validation.require(
                isinstance(criterion_id, str) and bool(criterion_id),
                f"{label}.id: 必须是非空字符串",
            )
            if isinstance(criterion_id, str) and criterion_id:
                validation.require(
                    criterion_id not in all_criteria,
                    f"{label}.id: 重复 {criterion_id}",
                )
                all_criteria.add(criterion_id)
                if criterion.get("required") is True:
                    required_criteria.add(criterion_id)

    protocols = goal.get("evaluation_protocols")
    validation.require(isinstance(protocols, list), "goal.yaml.evaluation_protocols: 必须是数组")
    protocol_ids: set[str] = set()
    if isinstance(protocols, list):
        for index, protocol in enumerate(protocols, start=1):
            label = f"goal.yaml.evaluation_protocols[{index}]"
            validation.require(isinstance(protocol, dict), f"{label}: 必须是对象")
            if not isinstance(protocol, dict):
                continue
            protocol_id = protocol.get("id")
            validation.require(
                isinstance(protocol_id, str) and bool(protocol_id),
                f"{label}.id: 必须是非空字符串",
            )
            if isinstance(protocol_id, str) and protocol_id:
                validation.require(
                    protocol_id not in protocol_ids,
                    f"{label}.id: 重复 {protocol_id}",
                )
                protocol_ids.add(protocol_id)

    validation.require(bool(required_criteria), "goal.yaml: 至少需要一个必需验收判据")
    validation.require(bool(protocol_ids), "goal.yaml: 至少需要一个评测协议")
    return all_criteria, protocol_ids, development_base if isinstance(development_base, dict) else {}


def validate_goal_ref(
    goal_ref: Any,
    goal: dict[str, Any] | None,
    required_goal_criteria: set[str],
    goal_protocol_ids: set[str],
    final: bool,
    validation: Validation,
) -> tuple[set[str], set[str]]:
    validation.require(isinstance(goal_ref, dict), "goal_ref: 必须是对象")
    if not isinstance(goal_ref, dict):
        return set(), set()

    declared_criteria = set(require_list(goal_ref, "required_criterion_ids", "goal_ref", validation))
    declared_protocols = set(require_list(goal_ref, "protocol_ids", "goal_ref", validation))
    for key in ("goal_id", "goal_version", "goal_status", "goal_file"):
        validation.require(key in goal_ref, f"goal_ref: 缺少字段 {key}")

    if not final:
        return declared_criteria, declared_protocols
    validation.require(goal is not None, "正式计划必须通过 --goal-file 联合校验")
    if goal is None:
        return declared_criteria, declared_protocols

    validation.require(goal_ref.get("goal_id") == goal.get("goal_id"), "goal_ref.goal_id: 与 goal.yaml 不一致")
    validation.require(
        goal_ref.get("goal_version") == goal.get("version"),
        "goal_ref.goal_version: 与 goal.yaml 不一致",
    )
    validation.require(
        goal_ref.get("goal_status") == goal.get("status"),
        "goal_ref.goal_status: 与 goal.yaml 不一致",
    )
    validation.require(
        declared_criteria == required_goal_criteria,
        "goal_ref.required_criterion_ids: 必须与 Goal 全部必需判据完全一致",
    )
    validation.require(
        declared_protocols == goal_protocol_ids,
        "goal_ref.protocol_ids: 必须与 Goal 协议集合完全一致",
    )
    return declared_criteria, declared_protocols


def validate_development_ref(
    development_ref: Any,
    goal_development_base: dict[str, Any],
    final: bool,
    validation: Validation,
) -> None:
    validation.require(isinstance(development_ref, dict), "development_base_ref: 必须是对象")
    if not isinstance(development_ref, dict):
        return
    for key in (
        "project_state",
        "project_root",
        "repository_source",
        "repository_version",
        "target_model_or_system",
        "goal_evidence_ref",
        "user_confirmed",
    ):
        validation.require(key in development_ref, f"development_base_ref: 缺少字段 {key}")
    validation.require(
        isinstance(development_ref.get("user_confirmed"), bool),
        "development_base_ref.user_confirmed: 必须是布尔值",
    )
    if not final:
        return

    goal_version = goal_development_base.get("commit") or goal_development_base.get(
        "version_or_snapshot"
    )
    expected = {
        "project_state": goal_development_base.get("project_state"),
        "project_root": goal_development_base.get("project_root"),
        "repository_source": goal_development_base.get("repository_source"),
        "repository_version": goal_version,
        "target_model_or_system": goal_development_base.get("target_model_or_system"),
        "user_confirmed": True,
    }
    for key, value in expected.items():
        validation.require(
            development_ref.get(key) == value,
            f"development_base_ref.{key}: 与 goal.yaml.development_base 不一致",
        )
    validation.require(
        has_value(development_ref.get("goal_evidence_ref")),
        "development_base_ref.goal_evidence_ref: 不得为空",
    )


def validate_planning_basis(
    basis: Any,
    final: bool,
    validation: Validation,
) -> None:
    validation.require(isinstance(basis, dict), "planning_basis: 必须是对象")
    if not isinstance(basis, dict):
        return
    inspected = require_list(basis, "inspected_code_refs", "planning_basis", validation)
    facts = require_list(basis, "confirmed_project_facts", "planning_basis", validation)
    require_list(basis, "assumptions", "planning_basis", validation)
    unresolved = require_list(basis, "unresolved_questions", "planning_basis", validation)
    if final:
        validation.require(bool(inspected), "planning_basis.inspected_code_refs: 不得为空")
        validation.require(bool(facts), "planning_basis.confirmed_project_facts: 不得为空")
        validation.require(not unresolved, "planning_basis.unresolved_questions: 正式计划不得保留未决问题")


def validate_stages(
    stages: Any,
    known_criteria: set[str],
    known_protocols: set[str],
    final: bool,
    validation: Validation,
) -> tuple[dict[str, dict[str, Any]], dict[str, int]]:
    validation.require(isinstance(stages, list), "stages: 必须是数组")
    if not isinstance(stages, list):
        return {}, {}

    stage_by_id: dict[str, dict[str, Any]] = {}
    order_by_id: dict[str, int] = {}
    used_orders: set[int] = set()
    for index, stage in enumerate(stages, start=1):
        label = f"stages[{index}]"
        validation.require(isinstance(stage, dict), f"{label}: 必须是对象")
        if not isinstance(stage, dict):
            continue
        stage_id = stage.get("id")
        validation.require(
            isinstance(stage_id, str) and bool(stage_id),
            f"{label}.id: 必须是非空字符串",
        )
        if isinstance(stage_id, str) and stage_id:
            validation.require(stage_id not in stage_by_id, f"{label}.id: 重复 {stage_id}")
            stage_by_id[stage_id] = stage
        order = stage.get("order")
        validation.require(
            isinstance(order, int) and not isinstance(order, bool) and order >= 1,
            f"{label}.order: 必须是大于等于 1 的整数",
        )
        if isinstance(order, int) and not isinstance(order, bool):
            validation.require(order not in used_orders, f"{label}.order: 重复 {order}")
            used_orders.add(order)
            if isinstance(stage_id, str) and stage_id:
                order_by_id[stage_id] = order

        validation.require(
            stage.get("status") in STAGE_STATUSES,
            f"{label}.status: 非法状态 {stage.get('status')!r}",
        )
        for key in (
            "goal_criterion_refs",
            "dependencies",
            "entry_conditions",
            "code_context",
            "stage_scope",
            "excluded_scope",
            "expected_outputs",
            "user_decision_points",
            "blocking_conditions",
        ):
            require_list(stage, key, label, validation)
        for criterion_id in stage.get("goal_criterion_refs", []):
            validation.require(
                criterion_id in known_criteria,
                f"{label}.goal_criterion_refs: 未知 Goal 判据 {criterion_id!r}",
            )

        stage_validation = stage.get("stage_validation")
        validation.require(isinstance(stage_validation, dict), f"{label}.stage_validation: 必须是对象")
        if isinstance(stage_validation, dict):
            kind = stage_validation.get("kind")
            validation.require(
                kind in STAGE_VALIDATION_KINDS,
                f"{label}.stage_validation.kind: 非法类型 {kind!r}",
            )
            for key in (
                "protocol_refs",
                "evaluation_objects",
                "acceptance_criteria_refs",
                "acceptance_rules",
                "evidence_artifacts",
            ):
                require_list(stage_validation, key, f"{label}.stage_validation", validation)
            for protocol_id in stage_validation.get("protocol_refs", []):
                validation.require(
                    protocol_id in known_protocols,
                    f"{label}.stage_validation.protocol_refs: 未知协议 {protocol_id!r}",
                )
            for criterion_id in stage_validation.get("acceptance_criteria_refs", []):
                validation.require(
                    criterion_id in known_criteria,
                    f"{label}.stage_validation.acceptance_criteria_refs: "
                    f"未知 Goal 判据 {criterion_id!r}",
                )
            if final and kind == "goal_verification":
                for key in (
                    "protocol_refs",
                    "evaluation_objects",
                    "acceptance_criteria_refs",
                    "acceptance_rules",
                    "evidence_artifacts",
                ):
                    validation.require(
                        bool(stage_validation.get(key)),
                        f"{label}.stage_validation.{key}: 真实验证节点不得为空",
                    )
        if final:
            for key in ("name", "objective"):
                validation.require(has_value(stage.get(key)), f"{label}.{key}: 不得为空")
            validation.require(bool(stage.get("stage_scope")), f"{label}.stage_scope: 不得为空")
            validation.require(bool(stage.get("expected_outputs")), f"{label}.expected_outputs: 不得为空")
            if isinstance(stage_validation, dict):
                validation.require(
                    has_value(stage_validation.get("description")),
                    f"{label}.stage_validation.description: 不得为空",
                )
                validation.require(
                    bool(stage_validation.get("acceptance_rules")),
                    f"{label}.stage_validation.acceptance_rules: 不得为空",
                )
                validation.require(
                    bool(stage_validation.get("evidence_artifacts")),
                    f"{label}.stage_validation.evidence_artifacts: 不得为空",
                )

    for index, stage in enumerate(stages, start=1):
        if not isinstance(stage, dict):
            continue
        stage_id = stage.get("id")
        current_order = order_by_id.get(stage_id)
        for dependency in stage.get("dependencies", []):
            validation.require(
                dependency in stage_by_id,
                f"stages[{index}].dependencies: 未知阶段 {dependency!r}",
            )
            dependency_order = order_by_id.get(dependency)
            if current_order is not None and dependency_order is not None:
                validation.require(
                    dependency_order < current_order,
                    f"stages[{index}].dependencies: 依赖 {dependency} 必须位于当前阶段之前",
                )

    if final:
        validation.require(bool(stage_by_id), "stages: 正式计划至少需要一个阶段")
        validation.require(
            any(
                isinstance(stage.get("stage_validation"), dict)
                and stage["stage_validation"].get("kind") == "goal_verification"
                for stage in stage_by_id.values()
            ),
            "stages: 至少需要一个真实 goal_verification 阶段",
        )
        validation.require(
            any(
                isinstance(stage.get("stage_validation"), dict)
                and stage["stage_validation"].get("kind") == "evidence_audit"
                for stage in stage_by_id.values()
            ),
            "stages: 至少需要一个 evidence_audit 阶段",
        )
    return stage_by_id, order_by_id


def validate_coverage(
    coverage: Any,
    required_criteria: set[str],
    stage_by_id: dict[str, dict[str, Any]],
    final: bool,
    validation: Validation,
) -> None:
    validation.require(isinstance(coverage, list), "criterion_coverage: 必须是数组")
    if not isinstance(coverage, list):
        return
    covered: set[str] = set()
    for index, row in enumerate(coverage, start=1):
        label = f"criterion_coverage[{index}]"
        validation.require(isinstance(row, dict), f"{label}: 必须是对象")
        if not isinstance(row, dict):
            continue
        criterion_id = row.get("goal_criterion_id")
        validation.require(
            criterion_id in required_criteria,
            f"{label}.goal_criterion_id: 不是 Goal 必需判据 {criterion_id!r}",
        )
        if isinstance(criterion_id, str):
            validation.require(criterion_id not in covered, f"{label}: 重复覆盖 {criterion_id}")
            covered.add(criterion_id)
        supporting = require_list(row, "supporting_stage_ids", label, validation)
        verifying = require_list(row, "verification_stage_ids", label, validation)
        evidence = require_list(row, "evidence_artifacts", label, validation)
        for stage_id in supporting + verifying:
            validation.require(stage_id in stage_by_id, f"{label}: 未知阶段 {stage_id!r}")
        for stage_id in verifying:
            stage = stage_by_id.get(stage_id, {})
            stage_validation = stage.get("stage_validation")
            validation.require(
                isinstance(stage_validation, dict)
                and stage_validation.get("kind") == "goal_verification",
                f"{label}: verification_stage_ids 中的 {stage_id} 不是真实验证节点",
            )
            if isinstance(stage_validation, dict):
                validation.require(
                    criterion_id in stage_validation.get("acceptance_criteria_refs", []),
                    f"{label}: 验证阶段 {stage_id} 未引用判据 {criterion_id}",
                )
        if final:
            validation.require(bool(verifying), f"{label}.verification_stage_ids: 不得为空")
            validation.require(bool(evidence), f"{label}.evidence_artifacts: 不得为空")
    if final:
        validation.require(
            covered == required_criteria,
            "criterion_coverage: 必须逐项覆盖全部 Goal 必需判据",
        )


def validate_review(
    review: Any,
    plan_version: Any,
    final: bool,
    validation: Validation,
) -> None:
    validation.require(isinstance(review, dict), "someagents_review: 必须是对象")
    if not isinstance(review, dict):
        return
    validation.require(review.get("mode") == "B", "someagents_review.mode: 必须是 B")
    validation.require(
        review.get("status") in REVIEW_STATUSES,
        f"someagents_review.status: 非法状态 {review.get('status')!r}",
    )
    validation.require(
        review.get("final_verdict") in REVIEW_FINAL_VERDICTS,
        f"someagents_review.final_verdict: 非法结论 {review.get('final_verdict')!r}",
    )
    role_reviews = require_list(review, "role_reviews", "someagents_review", validation)
    blocking = require_list(review, "blocking_issues", "someagents_review", validation)
    require_list(review, "resolved_issues", "someagents_review", validation)
    evidence = require_list(review, "evidence_refs", "someagents_review", validation)

    agent_ids: set[str] = set()
    for index, row in enumerate(role_reviews, start=1):
        label = f"someagents_review.role_reviews[{index}]"
        validation.require(isinstance(row, dict), f"{label}: 必须是对象")
        if not isinstance(row, dict):
            continue
        agent_id = row.get("agent_id")
        validation.require(
            isinstance(agent_id, str) and bool(agent_id),
            f"{label}.agent_id: 必须是非空字符串",
        )
        if isinstance(agent_id, str) and agent_id:
            validation.require(agent_id not in agent_ids, f"{label}.agent_id: 重复 {agent_id}")
            agent_ids.add(agent_id)
        validation.require(has_value(row.get("role")), f"{label}.role: 不得为空")
        validation.require(
            row.get("verdict") in REVIEW_VERDICTS,
            f"{label}.verdict: 非法结论 {row.get('verdict')!r}",
        )
        require_list(row, "findings", label, validation)
        require_list(row, "blocking_issues", label, validation)
        require_list(row, "evidence_refs", label, validation)

    if final:
        validation.require(review.get("status") == "completed", "someagents_review.status: 必须 completed")
        validation.require(
            review.get("final_verdict") == "pass",
            "someagents_review.final_verdict: 正式计划必须为 pass",
        )
        validation.require(
            review.get("input_plan_version") == plan_version,
            "someagents_review.input_plan_version: 必须等于当前计划版本",
        )
        validation.require(len(agent_ids) >= 2, "someagents_review: 至少需要两个独立 Agent")
        validation.require(not blocking, "someagents_review.blocking_issues: 正式计划不得保留阻断问题")
        validation.require(bool(evidence), "someagents_review.evidence_refs: 不得为空")


def validate_questions(
    questions: Any,
    final: bool,
    validation: Validation,
) -> None:
    validation.require(isinstance(questions, list), "open_questions: 必须是数组")
    if not isinstance(questions, list):
        return
    for index, question in enumerate(questions, start=1):
        label = f"open_questions[{index}]"
        validation.require(isinstance(question, dict), f"{label}: 必须是对象")
        if not isinstance(question, dict):
            continue
        validation.require(has_value(question.get("question")), f"{label}.question: 不得为空")
        validation.require(isinstance(question.get("blocking"), bool), f"{label}.blocking: 必须是布尔值")
        validation.require(
            question.get("status") in QUESTION_STATUSES,
            f"{label}.status: 非法状态 {question.get('status')!r}",
        )
        if final and question.get("blocking") is True:
            validation.require(
                question.get("status") == "resolved",
                f"{label}: 正式计划不能保留开放的阻断问题",
            )


def validate_confirmation(
    confirmation: Any,
    final: bool,
    validation: Validation,
) -> None:
    validation.require(isinstance(confirmation, dict), "user_confirmation: 必须是对象")
    if not isinstance(confirmation, dict):
        return
    validation.require(
        confirmation.get("status") in CONFIRMATION_STATUSES,
        f"user_confirmation.status: 非法状态 {confirmation.get('status')!r}",
    )
    if final:
        validation.require(
            confirmation.get("status") == "confirmed",
            "user_confirmation.status: 必须是 confirmed",
        )
        for key in ("confirmed_at", "confirmed_by", "evidence_ref"):
            validation.require(
                has_value(confirmation.get(key)),
                f"user_confirmation.{key}: 不得为空",
            )


def validate_plan(
    plan: Any,
    goal: dict[str, Any] | None,
    validation: Validation,
) -> None:
    validation.require(isinstance(plan, dict), "plan.yaml: 根节点必须是对象")
    if not isinstance(plan, dict):
        return

    reject_time_fields(plan, "plan.yaml", validation)
    required_fields = (
        "schema_version",
        "plan_id",
        "version",
        "status",
        "created_at",
        "updated_at",
        "goal_ref",
        "development_base_ref",
        "planning_basis",
        "global_boundaries",
        "stages",
        "criterion_coverage",
        "someagents_review",
        "open_questions",
        "user_confirmation",
        "supersedes",
    )
    for key in required_fields:
        validation.require(key in plan, f"plan.yaml: 缺少字段 {key}")

    status = plan.get("status")
    validation.require(status in PLAN_STATUSES, f"plan.yaml.status: 非法状态 {status!r}")
    final = status in FINAL_STATUSES
    for key in ("schema_version", "plan_id"):
        validation.require(has_value(plan.get(key)), f"plan.yaml.{key}: 不得为空")
    version = plan.get("version")
    validation.require(
        isinstance(version, int) and not isinstance(version, bool) and version >= 1,
        "plan.yaml.version: 必须是大于等于 1 的整数",
    )
    if final:
        validation.require(has_value(plan.get("created_at")), "plan.yaml.created_at: 不得为空")
        validation.require(has_value(plan.get("updated_at")), "plan.yaml.updated_at: 不得为空")
    if status == "revised":
        validation.require(has_value(plan.get("supersedes")), "plan.yaml.supersedes: revised 时不得为空")

    all_goal_criteria: set[str] = set()
    goal_protocol_ids: set[str] = set()
    goal_development_base: dict[str, Any] = {}
    required_goal_criteria: set[str] = set()
    if goal is not None:
        all_goal_criteria, goal_protocol_ids, goal_development_base = extract_goal(goal, validation)
        for criterion in goal.get("acceptance_criteria", []):
            if isinstance(criterion, dict) and criterion.get("required") is True:
                criterion_id = criterion.get("id")
                if isinstance(criterion_id, str):
                    required_goal_criteria.add(criterion_id)

    declared_criteria, declared_protocols = validate_goal_ref(
        plan.get("goal_ref"),
        goal,
        required_goal_criteria,
        goal_protocol_ids,
        final,
        validation,
    )
    if not all_goal_criteria:
        all_goal_criteria = set(declared_criteria)
    if not goal_protocol_ids:
        goal_protocol_ids = set(declared_protocols)

    validate_development_ref(
        plan.get("development_base_ref"),
        goal_development_base,
        final,
        validation,
    )
    validate_planning_basis(plan.get("planning_basis"), final, validation)
    validation.require(
        isinstance(plan.get("global_boundaries"), list),
        "global_boundaries: 必须是数组",
    )

    stage_by_id, _ = validate_stages(
        plan.get("stages"),
        all_goal_criteria,
        goal_protocol_ids,
        final,
        validation,
    )
    validate_coverage(
        plan.get("criterion_coverage"),
        required_goal_criteria if final else declared_criteria,
        stage_by_id,
        final,
        validation,
    )
    validate_review(plan.get("someagents_review"), version, final, validation)
    validate_questions(plan.get("open_questions"), final, validation)
    validate_confirmation(plan.get("user_confirmation"), final, validation)


def main() -> int:
    parser = argparse.ArgumentParser(description="校验 cvpr-plan 的 plan.yaml 阶段计划契约")
    parser.add_argument("plan_file", type=Path, help="plan.yaml 文件路径")
    parser.add_argument("--goal-file", type=Path, help="联合校验的 goal.yaml 文件路径")
    args = parser.parse_args()

    validation = Validation()
    plan = load_document(args.plan_file, "plan.yaml", validation)
    goal = (
        load_document(args.goal_file, "goal.yaml", validation)
        if args.goal_file is not None
        else None
    )
    validate_plan(plan, goal, validation)

    if validation.errors:
        print("INVALID:")
        for error in validation.errors:
            print(f"- {error}")
        return 1

    status = plan.get("status") if isinstance(plan, dict) else None
    print(f"OK: {args.plan_file} 阶段计划契约有效（状态 {status}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())

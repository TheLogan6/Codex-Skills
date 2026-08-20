#!/usr/bin/env python3
"""Validate a cvpr-goal contract stored as JSON-compatible YAML 1.2."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


GOAL_STATUSES = {
    "proposed",
    "accepted",
    "revised",
    "blocked",
    "rejected",
    "superseded",
}
PROTOCOL_FORMS = {
    "code",
    "benchmark",
    "simulator",
    "physical_experiment",
    "human_evaluation",
    "mixed",
    "other",
}
BASELINE_SOURCES = {
    "measured",
    "official_reported",
    "user_reported",
    "not_applicable",
}
CONFIRMATION_STATUSES = {"pending", "confirmed", "rejected"}
QUESTION_STATUSES = {"open", "resolved"}
FINAL_STATUSES = {"accepted", "revised"}
PROJECT_STATES = {"undetermined", "existing_project", "selected_repository"}
REPOSITORY_SOURCE_TYPES = {
    "undetermined",
    "user_project",
    "official",
    "author_maintained",
    "community",
    "organization",
    "other",
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


def validate_subject(
    subject: Any,
    final: bool,
    validation: Validation,
) -> set[str]:
    validation.require(isinstance(subject, dict), "verification_subject: 必须是对象")
    if not isinstance(subject, dict):
        return set()

    claims = require_list(subject, "research_claims", "verification_subject", validation)
    changes = require_list(
        subject,
        "expected_observable_changes",
        "verification_subject",
        validation,
    )
    require_list(subject, "verification_scope", "verification_subject", validation)
    require_list(subject, "excluded_scope", "verification_subject", validation)

    claim_ids: set[str] = set()
    for index, claim in enumerate(claims, start=1):
        label = f"verification_subject.research_claims[{index}]"
        validation.require(isinstance(claim, dict), f"{label}: 必须是对象")
        if not isinstance(claim, dict):
            continue
        claim_id = claim.get("id")
        validation.require(
            isinstance(claim_id, str) and bool(claim_id),
            f"{label}.id: 必须是非空字符串",
        )
        if isinstance(claim_id, str) and claim_id:
            validation.require(claim_id not in claim_ids, f"{label}.id: 重复 {claim_id}")
            claim_ids.add(claim_id)
        if final:
            validation.require(has_value(claim.get("statement")), f"{label}.statement: 不得为空")

    changed_claims: set[str] = set()
    for index, change in enumerate(changes, start=1):
        label = f"verification_subject.expected_observable_changes[{index}]"
        validation.require(isinstance(change, dict), f"{label}: 必须是对象")
        if not isinstance(change, dict):
            continue
        claim_id = change.get("claim_id")
        validation.require(claim_id in claim_ids, f"{label}.claim_id: 未知 Claim {claim_id!r}")
        if isinstance(claim_id, str):
            changed_claims.add(claim_id)
        if final:
            validation.require(has_value(change.get("change")), f"{label}.change: 不得为空")

    if final:
        validation.require(bool(claim_ids), "verification_subject: 至少需要一个研究主张")
        for claim_id in claim_ids:
            validation.require(
                claim_id in changed_claims,
                f"verification_subject: Claim {claim_id} 缺少预期可观察变化",
            )
    return claim_ids


def validate_protocols(
    protocols: Any,
    claim_ids: set[str],
    final: bool,
    validation: Validation,
) -> tuple[set[str], dict[str, dict[str, Any]]]:
    validation.require(isinstance(protocols, list), "evaluation_protocols: 必须是数组")
    if not isinstance(protocols, list):
        return set(), {}

    protocol_ids: set[str] = set()
    protocol_by_id: dict[str, dict[str, Any]] = {}
    for index, protocol in enumerate(protocols, start=1):
        label = f"evaluation_protocols[{index}]"
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
            protocol_by_id[protocol_id] = protocol

        validation.require(
            protocol.get("form") in PROTOCOL_FORMS,
            f"{label}.form: 非法类型 {protocol.get('form')!r}",
        )
        for key in (
            "evaluation_objects",
            "conditions",
            "result_artifacts",
            "linked_claim_ids",
        ):
            require_list(protocol, key, label, validation)
        for claim_id in protocol.get("linked_claim_ids", []):
            validation.require(
                claim_id in claim_ids,
                f"{label}.linked_claim_ids: 未知 Claim {claim_id!r}",
            )
        validation.require(
            isinstance(protocol.get("user_confirmed"), bool),
            f"{label}.user_confirmed: 必须是布尔值",
        )

        if final:
            for key in ("source", "version", "implementation_or_protocol"):
                validation.require(has_value(protocol.get(key)), f"{label}.{key}: 不得为空")
            validation.require(
                bool(protocol.get("evaluation_objects")),
                f"{label}.evaluation_objects: 不得为空",
            )
            validation.require(
                bool(protocol.get("result_artifacts")),
                f"{label}.result_artifacts: 不得为空",
            )
            validation.require(
                bool(protocol.get("linked_claim_ids")),
                f"{label}.linked_claim_ids: 不得为空",
            )

    if final:
        validation.require(bool(protocol_ids), "evaluation_protocols: 至少需要一个评测协议")
    return protocol_ids, protocol_by_id


def validate_development_base(
    development_base: Any,
    protocol_ids: set[str],
    required_protocol_ids: set[str],
    final: bool,
    validation: Validation,
) -> None:
    validation.require(isinstance(development_base, dict), "development_base: 必须是对象")
    if not isinstance(development_base, dict):
        return

    project_state = development_base.get("project_state")
    validation.require(
        project_state in PROJECT_STATES,
        f"development_base.project_state: 非法状态 {project_state!r}",
    )
    repository_source_type = development_base.get("repository_source_type")
    validation.require(
        repository_source_type in REPOSITORY_SOURCE_TYPES,
        "development_base.repository_source_type: "
        f"非法来源类型 {repository_source_type!r}",
    )
    intended_change_scope = require_list(
        development_base,
        "intended_change_scope",
        "development_base",
        validation,
    )
    validation.require(
        isinstance(development_base.get("user_confirmed"), bool),
        "development_base.user_confirmed: 必须是布尔值",
    )

    compatibility = development_base.get("evaluation_compatibility")
    validation.require(
        isinstance(compatibility, dict),
        "development_base.evaluation_compatibility: 必须是对象",
    )
    compatibility_protocol_ids: list[Any] = []
    evidence_refs: list[Any] = []
    if isinstance(compatibility, dict):
        compatibility_protocol_ids = require_list(
            compatibility,
            "protocol_ids",
            "development_base.evaluation_compatibility",
            validation,
        )
        evidence_refs = require_list(
            compatibility,
            "evidence_refs",
            "development_base.evaluation_compatibility",
            validation,
        )
        for protocol_id in compatibility_protocol_ids:
            validation.require(
                protocol_id in protocol_ids,
                "development_base.evaluation_compatibility.protocol_ids: "
                f"未知评测协议 {protocol_id!r}",
            )

    if not final:
        return

    validation.require(
        project_state in {"existing_project", "selected_repository"},
        "development_base.project_state: 最终契约必须确定现有项目或选定仓库",
    )
    validation.require(
        repository_source_type != "undetermined",
        "development_base.repository_source_type: 最终契约不得为 undetermined",
    )
    for key in ("project_root", "repository_source", "target_model_or_system"):
        validation.require(
            has_value(development_base.get(key)),
            f"development_base.{key}: 不得为空",
        )
    if project_state == "selected_repository":
        validation.require(
            has_value(development_base.get("repository_url")),
            "development_base.repository_url: 选定外部仓库时不得为空",
        )
    validation.require(
        has_value(development_base.get("commit"))
        or has_value(development_base.get("version_or_snapshot")),
        "development_base: 必须填写 commit 或 version_or_snapshot 以定位版本",
    )
    validation.require(
        bool(intended_change_scope),
        "development_base.intended_change_scope: 不得为空",
    )
    validation.require(
        development_base.get("user_confirmed") is True,
        "development_base.user_confirmed: 最终契约必须为 true",
    )
    validation.require(
        bool(compatibility_protocol_ids),
        "development_base.evaluation_compatibility.protocol_ids: 不得为空",
    )
    for protocol_id in required_protocol_ids:
        validation.require(
            protocol_id in compatibility_protocol_ids,
            "development_base.evaluation_compatibility.protocol_ids: "
            f"未覆盖必需验收协议 {protocol_id}",
        )
    if isinstance(compatibility, dict):
        validation.require(
            has_value(compatibility.get("assessment")),
            "development_base.evaluation_compatibility.assessment: 不得为空",
        )
    validation.require(
        bool(evidence_refs),
        "development_base.evaluation_compatibility.evidence_refs: 不得为空",
    )


def validate_baseline(
    baseline: Any,
    protocol_ids: set[str],
    final: bool,
    validation: Validation,
) -> None:
    validation.require(isinstance(baseline, dict), "baseline: 必须是对象")
    if not isinstance(baseline, dict):
        return

    source = baseline.get("source")
    validation.require(source in BASELINE_SOURCES, f"baseline.source: 非法来源 {source!r}")
    for key in ("conditions", "results", "evidence_refs"):
        require_list(baseline, key, "baseline", validation)

    protocol_id = baseline.get("protocol_id")
    if protocol_id is not None:
        validation.require(protocol_id in protocol_ids, f"baseline.protocol_id: 未知协议 {protocol_id!r}")

    if not final:
        return
    if source == "not_applicable":
        validation.require(
            has_value(baseline.get("not_applicable_reason")),
            "baseline.not_applicable_reason: 基线不适用时必须说明原因",
        )
    else:
        validation.require(protocol_id in protocol_ids, "baseline.protocol_id: 必须引用有效协议")
        validation.require(bool(baseline.get("results")), "baseline.results: 不得为空")
        validation.require(bool(baseline.get("evidence_refs")), "baseline.evidence_refs: 不得为空")


def validate_criteria(
    criteria: Any,
    claim_ids: set[str],
    protocol_ids: set[str],
    protocol_by_id: dict[str, dict[str, Any]],
    final: bool,
    validation: Validation,
) -> set[str]:
    validation.require(isinstance(criteria, list), "acceptance_criteria: 必须是数组")
    if not isinstance(criteria, list):
        return set()

    seen: set[str] = set()
    required_count = 0
    required_protocol_ids: set[str] = set()
    for index, criterion in enumerate(criteria, start=1):
        label = f"acceptance_criteria[{index}]"
        validation.require(isinstance(criterion, dict), f"{label}: 必须是对象")
        if not isinstance(criterion, dict):
            continue

        criterion_id = criterion.get("id")
        validation.require(
            isinstance(criterion_id, str) and bool(criterion_id),
            f"{label}.id: 必须是非空字符串",
        )
        if isinstance(criterion_id, str) and criterion_id:
            validation.require(criterion_id not in seen, f"{label}.id: 重复 {criterion_id}")
            seen.add(criterion_id)

        linked_claims = require_list(criterion, "linked_claim_ids", label, validation)
        linked_protocols = require_list(
            criterion,
            "evaluation_protocol_ids",
            label,
            validation,
        )
        source_refs = require_list(criterion, "source_refs", label, validation)
        evidence_artifacts = require_list(
            criterion,
            "evidence_artifacts",
            label,
            validation,
        )
        for claim_id in linked_claims:
            validation.require(claim_id in claim_ids, f"{label}: 未知 Claim {claim_id!r}")
        for protocol_id in linked_protocols:
            validation.require(
                protocol_id in protocol_ids,
                f"{label}: 未知评测协议 {protocol_id!r}",
            )

        required = criterion.get("required")
        validation.require(isinstance(required, bool), f"{label}.required: 必须是布尔值")
        if required is True:
            required_count += 1
            required_protocol_ids.update(
                protocol_id
                for protocol_id in linked_protocols
                if isinstance(protocol_id, str)
            )

        if final and required is True:
            for key in (
                "measure_or_judgment",
                "target_rule",
                "target_value",
                "evaluation_condition",
                "selection_rationale",
            ):
                validation.require(has_value(criterion.get(key)), f"{label}.{key}: 不得为空")
            validation.require(bool(linked_claims), f"{label}.linked_claim_ids: 不得为空")
            validation.require(bool(linked_protocols), f"{label}.evaluation_protocol_ids: 不得为空")
            validation.require(bool(source_refs), f"{label}.source_refs: 不得为空")
            validation.require(bool(evidence_artifacts), f"{label}.evidence_artifacts: 不得为空")
            for protocol_id in linked_protocols:
                protocol = protocol_by_id.get(protocol_id, {})
                validation.require(
                    protocol.get("user_confirmed") is True,
                    f"{label}: 必需协议 {protocol_id} 尚未由用户确认",
                )

    if final:
        validation.require(required_count > 0, "acceptance_criteria: 至少需要一个必需验收判据")
    return required_protocol_ids


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
                f"{label}: 最终契约不能保留开放的阻断问题",
            )


def validate_confirmation(
    confirmation: Any,
    final: bool,
    validation: Validation,
) -> None:
    validation.require(isinstance(confirmation, dict), "user_confirmation: 必须是对象")
    if not isinstance(confirmation, dict):
        return
    status = confirmation.get("status")
    validation.require(
        status in CONFIRMATION_STATUSES,
        f"user_confirmation.status: 非法状态 {status!r}",
    )
    if final:
        validation.require(status == "confirmed", "user_confirmation.status: 必须是 confirmed")
        for key in ("confirmed_at", "confirmed_by", "evidence_ref"):
            validation.require(
                has_value(confirmation.get(key)),
                f"user_confirmation.{key}: 不得为空",
            )


def validate_start_ref(
    start_ref: Any,
    idea_id: Any,
    final: bool,
    validation: Validation,
) -> None:
    validation.require(isinstance(start_ref, dict), "start_ref: 必须是对象")
    if not isinstance(start_ref, dict):
        return
    for key in ("start_id", "version", "start_file", "idea_id"):
        validation.require(key in start_ref, f"start_ref: 缺少字段 {key}")
    validation.require(
        isinstance(start_ref.get("version"), int)
        and not isinstance(start_ref.get("version"), bool)
        and start_ref.get("version", 0) >= 1,
        "start_ref.version: 必须是正整数",
    )
    validation.require(
        start_ref.get("start_file") == ".cvpr/start.yaml",
        "start_ref.start_file: 必须为 .cvpr/start.yaml",
    )
    validation.require(
        start_ref.get("idea_id") == idea_id,
        "start_ref.idea_id: 必须与 goal.yaml.idea_id 一致",
    )
    if final:
        validation.require(has_value(start_ref.get("start_id")), "start_ref.start_id: 不得为空")


def validate_contract(contract: Any, validation: Validation) -> None:
    validation.require(isinstance(contract, dict), "goal.yaml: 根节点必须是对象")
    if not isinstance(contract, dict):
        return

    required_fields = (
        "schema_version",
        "goal_id",
        "idea_id",
        "start_ref",
        "version",
        "status",
        "created_at",
        "updated_at",
        "verification_subject",
        "development_base",
        "evaluation_protocols",
        "baseline",
        "acceptance_criteria",
        "validity_checks",
        "boundary_constraints",
        "diagnostic_observations",
        "acceptance_logic",
        "open_questions",
        "required_artifacts",
        "user_confirmation",
        "supersedes",
    )
    for key in required_fields:
        validation.require(key in contract, f"goal.yaml: 缺少字段 {key}")

    status = contract.get("status")
    validation.require(status in GOAL_STATUSES, f"goal.yaml.status: 非法状态 {status!r}")
    final = status in FINAL_STATUSES

    for key in ("schema_version", "goal_id", "idea_id"):
        validation.require(has_value(contract.get(key)), f"goal.yaml.{key}: 不得为空")
    version = contract.get("version")
    validation.require(
        isinstance(version, int) and not isinstance(version, bool) and version >= 1,
        "goal.yaml.version: 必须是大于等于 1 的整数",
    )
    if final:
        validation.require(has_value(contract.get("created_at")), "goal.yaml.created_at: 不得为空")
        validation.require(has_value(contract.get("updated_at")), "goal.yaml.updated_at: 不得为空")
    if status == "revised":
        validation.require(has_value(contract.get("supersedes")), "goal.yaml.supersedes: revised 时不得为空")

    validate_start_ref(contract.get("start_ref"), contract.get("idea_id"), final, validation)
    claim_ids = validate_subject(contract.get("verification_subject"), final, validation)
    protocol_ids, protocol_by_id = validate_protocols(
        contract.get("evaluation_protocols"),
        claim_ids,
        final,
        validation,
    )
    validate_baseline(contract.get("baseline"), protocol_ids, final, validation)
    required_protocol_ids = validate_criteria(
        contract.get("acceptance_criteria"),
        claim_ids,
        protocol_ids,
        protocol_by_id,
        final,
        validation,
    )
    validate_development_base(
        contract.get("development_base"),
        protocol_ids,
        required_protocol_ids,
        final,
        validation,
    )

    for key in ("validity_checks", "boundary_constraints", "diagnostic_observations"):
        validation.require(isinstance(contract.get(key), list), f"goal.yaml.{key}: 必须是数组")
    required_artifacts = contract.get("required_artifacts")
    validation.require(isinstance(required_artifacts, list), "goal.yaml.required_artifacts: 必须是数组")
    if final:
        validation.require(has_value(contract.get("acceptance_logic")), "goal.yaml.acceptance_logic: 不得为空")
        validation.require(bool(required_artifacts), "goal.yaml.required_artifacts: 不得为空")

    validate_questions(contract.get("open_questions"), final, validation)
    validate_confirmation(contract.get("user_confirmation"), final, validation)


def validate_start_alignment(
    contract: dict[str, Any],
    start_contract: Any,
    validation: Validation,
) -> None:
    validation.require(isinstance(start_contract, dict), "start.yaml: 根节点必须是对象")
    if not isinstance(start_contract, dict):
        return
    start_ref = contract.get("start_ref")
    final_idea = start_contract.get("final_idea")
    validation.require(start_contract.get("status") == "accepted", "start.yaml.status 必须为 accepted")
    if isinstance(start_ref, dict):
        validation.require(
            start_ref.get("start_id") == start_contract.get("start_id"),
            "start_ref.start_id 与 start.yaml 不一致",
        )
        validation.require(
            start_ref.get("version") == start_contract.get("version"),
            "start_ref.version 与 start.yaml 不一致",
        )
    validation.require(isinstance(final_idea, dict), "start.yaml.final_idea 必须是对象")
    if isinstance(final_idea, dict):
        validation.require(
            final_idea.get("idea_id") == contract.get("idea_id"),
            "goal.yaml.idea_id 与 start.yaml.final_idea.idea_id 不一致",
        )
        validation.require(
            final_idea.get("user_confirmed") is True,
            "start.yaml.final_idea 必须已经用户确认",
        )


def self_test_start_alignment() -> int:
    contract = {
        "idea_id": "I-001",
        "start_ref": {
            "start_id": "START-001",
            "version": 1,
            "start_file": ".cvpr/start.yaml",
            "idea_id": "I-001",
        },
    }
    start_contract = {
        "start_id": "START-001",
        "version": 1,
        "status": "accepted",
        "final_idea": {"idea_id": "I-001", "user_confirmed": True},
    }
    cases: list[tuple[str, dict[str, Any], dict[str, Any], bool]] = [
        ("正例", contract, start_contract, True),
        (
            "IDEA 不一致",
            contract,
            {**start_contract, "final_idea": {"idea_id": "I-002", "user_confirmed": True}},
            False,
        ),
        (
            "启动状态未接受",
            contract,
            {**start_contract, "status": "in_progress"},
            False,
        ),
        (
            "启动版本不一致",
            contract,
            {**start_contract, "version": 2},
            False,
        ),
        (
            "用户未确认 IDEA",
            contract,
            {**start_contract, "final_idea": {"idea_id": "I-001", "user_confirmed": False}},
            False,
        ),
    ]
    failed = False
    for name, goal_data, start_data, should_pass in cases:
        validation = Validation()
        validate_start_alignment(goal_data, start_data, validation)
        passed = not validation.errors
        if passed != should_pass:
            failed = True
            print(f"FAIL {name}: {validation.errors}")
        else:
            print(f"PASS {name}")

    template_path = (
        Path(__file__).resolve().parents[1]
        / "assets"
        / "核验目标模板"
        / "goal.yaml"
    )
    accepted_goal = json.loads(template_path.read_text(encoding="utf-8"))
    accepted_goal.update(
        {
            "status": "accepted",
            "created_at": "2026-07-29T10:00:00+08:00",
            "updated_at": "2026-07-29T11:00:00+08:00",
            "acceptance_logic": "AC-001 必须通过",
            "validity_checks": ["核对数据划分与运行配置"],
            "boundary_constraints": ["保持已确认评测协议"],
            "diagnostic_observations": [],
            "required_artifacts": ["runs/verification.json"],
        }
    )
    accepted_goal["verification_subject"]["research_claims"][0]["statement"] = "方法改善目标行为"
    accepted_goal["verification_subject"]["expected_observable_changes"][0]["change"] = "目标指标提高"
    accepted_goal["verification_subject"]["verification_scope"] = ["锁定评测对象"]
    accepted_goal["development_base"].update(
        {
            "project_state": "selected_repository",
            "project_root": ".",
            "repository_url": "https://github.com/example/research-project",
            "repository_source": "官方仓库",
            "repository_source_type": "official",
            "branch": "main",
            "commit": "0123456789abcdef",
            "target_model_or_system": "目标系统",
            "intended_change_scope": ["model/component.py"],
            "user_confirmed": True,
        }
    )
    accepted_goal["development_base"]["evaluation_compatibility"] = {
        "protocol_ids": ["EVAL-001"],
        "assessment": "兼容",
        "evidence_refs": ["docs/evaluation.md"],
    }
    accepted_goal["evaluation_protocols"][0].update(
        {
            "form": "code",
            "source": "官方评测协议",
            "version": "1.0",
            "implementation_or_protocol": "tools/evaluate.py",
            "evaluation_objects": ["锁定验证集"],
            "conditions": ["固定配置"],
            "result_artifacts": ["runs/verification.json"],
            "user_confirmed": True,
        }
    )
    accepted_goal["baseline"] = {
        "source": "measured",
        "protocol_id": "EVAL-001",
        "conditions": ["固定配置"],
        "results": [{"metric": "score", "value": 0.5}],
        "evidence_refs": ["runs/baseline.json"],
        "not_applicable_reason": "",
    }
    accepted_goal["acceptance_criteria"][0].update(
        {
            "measure_or_judgment": "score",
            "target_rule": ">=",
            "target_value": 0.6,
            "evaluation_condition": "锁定验证集与配置",
            "selection_rationale": "直接对应研究主张",
            "source_refs": ["runs/baseline.json"],
            "evidence_artifacts": ["runs/verification.json"],
        }
    )
    accepted_goal["open_questions"] = [
        {"question": "开发基础和协议已确认", "blocking": True, "status": "resolved"}
    ]
    accepted_goal["user_confirmation"] = {
        "status": "confirmed",
        "confirmed_at": "2026-07-29T11:00:00+08:00",
        "confirmed_by": "user",
        "evidence_ref": ".cvpr/decisions.jsonl#D-001",
    }
    validation = Validation()
    validate_contract(accepted_goal, validation)
    validate_start_alignment(accepted_goal, start_contract, validation)
    if validation.errors:
        failed = True
        print(f"FAIL 完整 accepted Goal: {validation.errors}")
    else:
        print("PASS 完整 accepted Goal")
    return 1 if failed else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="校验 cvpr-goal 的 goal.yaml 核验契约")
    parser.add_argument("goal_file", nargs="?", type=Path, help="goal.yaml 文件路径")
    parser.add_argument("--start-file", type=Path, help="用于交叉核验的 .cvpr/start.yaml")
    parser.add_argument("--self-test", action="store_true", help="运行 start → goal 交叉核验自测试")
    args = parser.parse_args()

    if args.self_test:
        return self_test_start_alignment()
    if args.goal_file is None:
        parser.error("必须提供 goal_file，或使用 --self-test")

    validation = Validation()
    contract = load_contract(args.goal_file, validation)
    validate_contract(contract, validation)

    if isinstance(contract, dict) and contract.get("status") in FINAL_STATUSES:
        validation.require(args.start_file is not None, "accepted/revised Goal 必须提供 --start-file")
        if args.start_file is not None:
            start_contract = load_contract(args.start_file, validation)
            validate_start_alignment(contract, start_contract, validation)

    if validation.errors:
        print("INVALID:")
        for error in validation.errors:
            print(f"- {error}")
        return 1

    status = contract.get("status") if isinstance(contract, dict) else None
    print(f"OK: {args.goal_file} 核验契约有效（状态 {status}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())

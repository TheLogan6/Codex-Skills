#!/usr/bin/env python3
"""Validate cvpr-do execution state and its persistent entry manifest."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path, PurePosixPath
from typing import Any


FINAL_CONTRACT_STATUSES = {"accepted", "revised"}
WORK_STATUSES = {
    "proposed",
    "running",
    "executed",
    "accepted",
    "blocked",
    "rejected",
    "superseded",
}
MANIFEST_STATUSES = {"proposed", "active", "superseded"}
PROFILE_KINDS = {"undetermined", "model", "non_model", "mixed"}
ENTRY_ROLES = {
    "training",
    "validation",
    "testing",
    "stage_check",
    "goal_evaluation",
    "analysis",
    "data_preparation",
    "simulation",
    "human_evaluation",
    "physical_experiment",
    "other",
}
ENTRY_SCOPES = {
    "development_check",
    "research_execution",
    "goal_verification",
    "evidence_analysis",
}
ENTRY_STATUSES = {"proposed", "active", "superseded"}
RUN_EVENTS = {"started", "progress", "completed", "failed", "interrupted"}
RUN_KINDS = {
    "development_check",
    "research_execution",
    "goal_verification",
    "evidence_analysis",
}
RUN_STATUSES = {"running", "succeeded", "failed", "interrupted", "indeterminate"}
CRITERION_OUTCOMES = {"passed", "not_met", "indeterminate"}
MODEL_ENTRY_ROLES = {"training", "validation", "testing"}
DIRECTORY_CONTRACT = {
    "checks": "cvpr_workspace/checks",
    "entrypoints": "cvpr_workspace/entrypoints",
    "goal_evaluation": "cvpr_workspace/goal_evaluation",
    "configs": "cvpr_workspace/configs",
    "analysis": "cvpr_workspace/analysis",
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


def load_json(path: Path, label: str, validation: Validation) -> Any:
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        validation.errors.append(f"{label}: 无法解析为 JSON/YAML 1.2 子集：{exc}")
        return None


def load_jsonl(path: Path, label: str, validation: Validation) -> list[dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        validation.errors.append(f"{label}: 无法读取：{exc}")
        return []

    rows: list[dict[str, Any]] = []
    for line_number, raw in enumerate(lines, start=1):
        if not raw.strip():
            continue
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            validation.errors.append(f"{label}:{line_number}: 非法 JSON：{exc}")
            continue
        if not isinstance(value, dict):
            validation.errors.append(f"{label}:{line_number}: 每行必须是 JSON 对象")
            continue
        rows.append(value)
    return rows


def is_safe_project_path(value: Any) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    path = PurePosixPath(value)
    return not path.is_absolute() and ".." not in path.parts


def is_under(value: str, prefix: str) -> bool:
    path = PurePosixPath(value)
    root = PurePosixPath(prefix)
    return path == root or root in path.parents


def run_upstream_validator(
    script: Path,
    arguments: list[str],
    label: str,
    validation: Validation,
) -> None:
    if not script.is_file():
        validation.errors.append(f"{label}: 未找到校验器 {script}")
        return
    result = subprocess.run(
        [sys.executable, str(script), *arguments],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        detail = (result.stdout + result.stderr).strip()
        validation.errors.append(f"{label}: 上游契约校验失败\n{detail}")


def extract_goal(goal: Any, validation: Validation) -> tuple[set[str], set[str], set[str]]:
    validation.require(isinstance(goal, dict), "goal.yaml: 根节点必须是对象")
    if not isinstance(goal, dict):
        return set(), set(), set()

    validation.require(
        goal.get("status") in FINAL_CONTRACT_STATUSES,
        "goal.yaml.status: 必须是 accepted 或 revised",
    )
    confirmation = goal.get("user_confirmation")
    validation.require(
        isinstance(confirmation, dict)
        and confirmation.get("status") == "confirmed",
        "goal.yaml.user_confirmation.status: 必须是 confirmed",
    )

    criterion_ids: set[str] = set()
    required_criterion_ids: set[str] = set()
    criteria = goal.get("acceptance_criteria", [])
    validation.require(isinstance(criteria, list), "goal.yaml.acceptance_criteria: 必须是数组")
    if isinstance(criteria, list):
        for row in criteria:
            if not isinstance(row, dict):
                continue
            criterion_id = row.get("id")
            if isinstance(criterion_id, str) and criterion_id:
                criterion_ids.add(criterion_id)
                if row.get("required") is True:
                    required_criterion_ids.add(criterion_id)

    protocol_ids = {
        row.get("id")
        for row in goal.get("evaluation_protocols", [])
        if isinstance(row, dict) and isinstance(row.get("id"), str)
    }
    return criterion_ids, required_criterion_ids, protocol_ids


def extract_plan(plan: Any, validation: Validation) -> tuple[dict[str, dict[str, Any]], str, int]:
    validation.require(isinstance(plan, dict), "plan.yaml: 根节点必须是对象")
    if not isinstance(plan, dict):
        return {}, "", 0

    validation.require(
        plan.get("status") in FINAL_CONTRACT_STATUSES,
        "plan.yaml.status: 必须是 accepted 或 revised",
    )
    confirmation = plan.get("user_confirmation")
    validation.require(
        isinstance(confirmation, dict)
        and confirmation.get("status") == "confirmed",
        "plan.yaml.user_confirmation.status: 必须是 confirmed",
    )

    stages = plan.get("stages")
    validation.require(isinstance(stages, list) and bool(stages), "plan.yaml.stages: 不得为空")
    stage_by_id: dict[str, dict[str, Any]] = {}
    if isinstance(stages, list):
        for row in stages:
            if not isinstance(row, dict):
                continue
            stage_id = row.get("id")
            if isinstance(stage_id, str) and stage_id:
                validation.require(stage_id not in stage_by_id, f"plan.yaml.stages: 重复 {stage_id}")
                stage_by_id[stage_id] = row

    plan_id = plan.get("plan_id")
    version = plan.get("version")
    return (
        stage_by_id,
        plan_id if isinstance(plan_id, str) else "",
        version if isinstance(version, int) and not isinstance(version, bool) else 0,
    )


def validate_task_events(
    rows: list[dict[str, Any]],
    stage_ids: set[str],
    validation: Validation,
) -> tuple[set[str], dict[str, dict[str, Any]]]:
    record_by_id: dict[str, dict[str, Any]] = {}
    latest_by_task: dict[str, dict[str, Any]] = {}
    latest_revision: dict[str, int] = {}

    for index, row in enumerate(rows, start=1):
        label = f"tasks.jsonl:记录{index}"
        record_id = row.get("id")
        validation.require(
            isinstance(record_id, str) and bool(record_id),
            f"{label}.id: 必须是非空字符串",
        )
        if not isinstance(record_id, str) or not record_id:
            continue
        validation.require(record_id not in record_by_id, f"{label}.id: 重复 {record_id}")

        task_id_value = row.get("task_id", record_id)
        validation.require(
            isinstance(task_id_value, str) and bool(task_id_value),
            f"{label}.task_id: 必须是非空字符串",
        )
        if not isinstance(task_id_value, str) or not task_id_value:
            continue

        stage_id = row.get("stage_id")
        if stage_id is not None:
            validation.require(stage_id in stage_ids, f"{label}.stage_id: 未知阶段 {stage_id!r}")

        if "task_id" in row:
            revision = row.get("revision")
            previous = row.get("previous_record_id")
            validation.require(
                isinstance(revision, int) and not isinstance(revision, bool) and revision >= 1,
                f"{label}.revision: 必须是正整数",
            )
            validation.require(has_value(row.get("event")), f"{label}.event: 不得为空")
            expected_revision = latest_revision.get(task_id_value, 0) + 1
            validation.require(
                revision == expected_revision,
                f"{label}.revision: 任务 {task_id_value} 应为 {expected_revision}",
            )
            if expected_revision == 1:
                validation.require(previous is None, f"{label}.previous_record_id: 首条记录必须为 null")
            else:
                expected_previous = latest_by_task[task_id_value].get("id")
                validation.require(
                    previous == expected_previous,
                    f"{label}.previous_record_id: 应指向 {expected_previous}",
                )
            if isinstance(revision, int) and not isinstance(revision, bool):
                latest_revision[task_id_value] = revision
        else:
            validation.require(
                task_id_value not in latest_by_task,
                f"{label}: 旧格式任务 {task_id_value} 不能重复",
            )
            latest_revision[task_id_value] = 1

        record_by_id[record_id] = row
        latest_by_task[task_id_value] = row

    return set(latest_by_task), latest_by_task


def validate_state(
    state: Any,
    plan_id: str,
    plan_version: int,
    stage_by_id: dict[str, dict[str, Any]],
    latest_tasks: dict[str, dict[str, Any]],
    mode: str,
    validation: Validation,
) -> dict[str, dict[str, Any]]:
    validation.require(isinstance(state, dict), "state.yaml: 根节点必须是对象")
    if not isinstance(state, dict):
        return {}

    validation.require(
        state.get("schema_version") == "1.1",
        "state.yaml.schema_version: cvpr-do 要求执行期契约 1.1",
    )
    for key in (
        "active_plan",
        "current_stage_id",
        "last_accepted_stage_id",
        "stage_statuses",
        "execution_workspace",
        "goal_assessment",
    ):
        validation.require(key in state, f"state.yaml: 缺少执行期字段 {key}")

    active_plan = state.get("active_plan")
    validation.require(isinstance(active_plan, dict), "state.yaml.active_plan: 必须是对象")
    if isinstance(active_plan, dict):
        validation.require(
            active_plan.get("plan_id") == plan_id,
            "state.yaml.active_plan.plan_id: 与 plan.yaml 不一致",
        )
        validation.require(
            active_plan.get("version") == plan_version,
            "state.yaml.active_plan.version: 与 plan.yaml 不一致",
        )
        validation.require(
            active_plan.get("plan_file") == ".cvpr/plan.yaml",
            "state.yaml.active_plan.plan_file: 必须是 .cvpr/plan.yaml",
        )

    stage_statuses = state.get("stage_statuses")
    validation.require(isinstance(stage_statuses, list), "state.yaml.stage_statuses: 必须是数组")
    status_by_stage: dict[str, dict[str, Any]] = {}
    if isinstance(stage_statuses, list):
        for index, row in enumerate(stage_statuses, start=1):
            label = f"state.yaml.stage_statuses[{index}]"
            validation.require(isinstance(row, dict), f"{label}: 必须是对象")
            if not isinstance(row, dict):
                continue
            stage_id = row.get("stage_id")
            validation.require(stage_id in stage_by_id, f"{label}.stage_id: 未知阶段 {stage_id!r}")
            if not isinstance(stage_id, str) or stage_id not in stage_by_id:
                continue
            validation.require(stage_id not in status_by_stage, f"{label}: 重复阶段 {stage_id}")
            validation.require(row.get("status") in WORK_STATUSES, f"{label}.status: 非法状态")
            evidence = require_list(row, "evidence_refs", label, validation)
            if row.get("status") == "accepted":
                validation.require(bool(evidence), f"{label}: accepted 阶段必须有 evidence_refs")
            status_by_stage[stage_id] = row

    validation.require(
        set(status_by_stage) == set(stage_by_id),
        "state.yaml.stage_statuses: 必须且仅能覆盖 Plan 全部阶段",
    )

    current_stage_id = state.get("current_stage_id")
    validation.require(
        current_stage_id is None or current_stage_id in stage_by_id,
        "state.yaml.current_stage_id: 未引用有效阶段",
    )
    if mode == "stage":
        validation.require(
            isinstance(current_stage_id, str) and current_stage_id in stage_by_id,
            "stage 模式必须存在 current_stage_id",
        )
        if isinstance(current_stage_id, str) and current_stage_id in stage_by_id:
            validation.require(
                status_by_stage.get(current_stage_id, {}).get("status")
                in {"running", "executed", "blocked", "rejected"},
                "stage 模式当前阶段必须处于 running、executed、blocked 或 rejected",
            )
            for dependency in stage_by_id[current_stage_id].get("dependencies", []):
                validation.require(
                    status_by_stage.get(dependency, {}).get("status") == "accepted",
                    f"当前阶段依赖 {dependency} 尚未 accepted",
                )
            other_active = [
                stage_id
                for stage_id, row in status_by_stage.items()
                if stage_id != current_stage_id
                and row.get("status") in {"running", "executed"}
            ]
            validation.require(
                not other_active,
                f"存在当前阶段之外的活动阶段：{other_active}",
            )
    if mode == "final":
        validation.require(current_stage_id is None, "final 模式 current_stage_id 必须为 null")
        for stage_id, row in status_by_stage.items():
            validation.require(
                row.get("status") == "accepted",
                f"final 模式阶段 {stage_id} 尚未 accepted",
            )

    last_accepted = state.get("last_accepted_stage_id")
    validation.require(
        last_accepted is None
        or (
            last_accepted in status_by_stage
            and status_by_stage[last_accepted].get("status") == "accepted"
        ),
        "state.yaml.last_accepted_stage_id: 必须为空或引用 accepted 阶段",
    )

    current_task = state.get("current_atomic_task_id")
    validation.require(
        current_task is None or current_task in latest_tasks,
        "state.yaml.current_atomic_task_id: 未引用有效逻辑任务",
    )

    execution_workspace = state.get("execution_workspace")
    validation.require(
        isinstance(execution_workspace, dict),
        "state.yaml.execution_workspace: 必须是对象",
    )
    if isinstance(execution_workspace, dict):
        validation.require(
            execution_workspace.get("manifest_file") == "cvpr_workspace/入口清单.yaml",
            "state.yaml.execution_workspace.manifest_file: 路径不符合契约",
        )
        validation.require(
            execution_workspace.get("status") in {"proposed", "active", "superseded"},
            "state.yaml.execution_workspace.status: 非法状态",
        )
        if mode in {"stage", "final"}:
            validation.require(
                execution_workspace.get("status") == "active",
                f"{mode} 模式 execution_workspace.status 必须为 active",
            )

    if mode == "final":
        validation.require(not state.get("blockers"), "final 模式不能保留 blockers")
        validation.require(
            not state.get("active_deviations"),
            "final 模式不能保留 active_deviations",
        )

    return status_by_stage


def validate_manifest(
    manifest: Any,
    project_root: Path | None,
    goal: dict[str, Any] | None,
    plan: dict[str, Any] | None,
    stage_ids: set[str],
    task_ids: set[str],
    criterion_ids: set[str],
    protocol_ids: set[str],
    mode: str,
    validation: Validation,
) -> dict[str, dict[str, Any]]:
    validation.require(isinstance(manifest, dict), "入口清单.yaml: 根节点必须是对象")
    if not isinstance(manifest, dict):
        return {}

    for key in (
        "schema_version",
        "manifest_id",
        "status",
        "project_root",
        "workspace_root",
        "goal_ref",
        "plan_ref",
        "research_profile",
        "directory_contract",
        "entries",
        "updated_at",
    ):
        validation.require(key in manifest, f"入口清单.yaml: 缺少字段 {key}")

    validation.require(manifest.get("schema_version") == "1.0", "入口清单.yaml.schema_version: 必须是 1.0")
    validation.require(has_value(manifest.get("manifest_id")), "入口清单.yaml.manifest_id: 不得为空")
    status = manifest.get("status")
    validation.require(status in MANIFEST_STATUSES, "入口清单.yaml.status: 非法状态")
    validation.require(manifest.get("project_root") == ".", "入口清单.yaml.project_root: 必须是 .")
    validation.require(
        manifest.get("workspace_root") == "cvpr_workspace",
        "入口清单.yaml.workspace_root: 必须是 cvpr_workspace",
    )

    if mode in {"stage", "final"}:
        validation.require(status == "active", f"{mode} 模式入口清单必须为 active")
        validation.require(has_value(manifest.get("updated_at")), "入口清单.yaml.updated_at: 不得为空")

    goal_ref = manifest.get("goal_ref")
    validation.require(isinstance(goal_ref, dict), "入口清单.yaml.goal_ref: 必须是对象")
    if isinstance(goal_ref, dict) and isinstance(goal, dict):
        validation.require(goal_ref.get("goal_id") == goal.get("goal_id"), "入口清单 Goal ID 不一致")
        validation.require(goal_ref.get("goal_version") == goal.get("version"), "入口清单 Goal 版本不一致")
        validation.require(goal_ref.get("goal_file") == ".cvpr/goal.yaml", "入口清单 Goal 路径不一致")

    plan_ref = manifest.get("plan_ref")
    validation.require(isinstance(plan_ref, dict), "入口清单.yaml.plan_ref: 必须是对象")
    if isinstance(plan_ref, dict) and isinstance(plan, dict):
        validation.require(plan_ref.get("plan_id") == plan.get("plan_id"), "入口清单 Plan ID 不一致")
        validation.require(plan_ref.get("plan_version") == plan.get("version"), "入口清单 Plan 版本不一致")
        validation.require(plan_ref.get("plan_file") == ".cvpr/plan.yaml", "入口清单 Plan 路径不一致")

    directory_contract = manifest.get("directory_contract")
    validation.require(
        isinstance(directory_contract, dict),
        "入口清单.yaml.directory_contract: 必须是对象",
    )
    if isinstance(directory_contract, dict):
        for key, expected in DIRECTORY_CONTRACT.items():
            validation.require(
                directory_contract.get(key) == expected,
                f"入口清单.yaml.directory_contract.{key}: 必须是 {expected}",
            )

    profile = manifest.get("research_profile")
    validation.require(isinstance(profile, dict), "入口清单.yaml.research_profile: 必须是对象")
    profile_kind = ""
    required_roles: set[str] = set()
    if isinstance(profile, dict):
        profile_kind = profile.get("kind")
        validation.require(profile_kind in PROFILE_KINDS, "research_profile.kind: 非法类型")
        roles = require_list(profile, "required_entry_roles", "research_profile", validation)
        required_roles = {role for role in roles if isinstance(role, str)}
        for role in required_roles:
            validation.require(role in ENTRY_ROLES, f"research_profile: 未知入口角色 {role}")
        if mode in {"stage", "final"}:
            validation.require(profile_kind != "undetermined", "正式执行不能使用 undetermined 研究类型")
        if profile_kind in {"model", "mixed"}:
            validation.require(
                MODEL_ENTRY_ROLES.issubset(required_roles),
                "模型或混合研究必须要求 training、validation、testing 入口",
            )

    entries = manifest.get("entries")
    validation.require(isinstance(entries, list), "入口清单.yaml.entries: 必须是数组")
    entry_by_id: dict[str, dict[str, Any]] = {}
    active_roles: set[str] = set()
    if isinstance(entries, list):
        for index, entry in enumerate(entries, start=1):
            label = f"入口清单.yaml.entries[{index}]"
            validation.require(isinstance(entry, dict), f"{label}: 必须是对象")
            if not isinstance(entry, dict):
                continue
            for key in (
                "id",
                "role",
                "scope",
                "stage_refs",
                "task_refs",
                "purpose",
                "code_path",
                "config_paths",
                "working_directory",
                "manual_command",
                "runtime_parameters",
                "input_refs",
                "output_refs",
                "goal_protocol_refs",
                "goal_criterion_refs",
                "result_logic_refs",
                "status",
            ):
                validation.require(key in entry, f"{label}: 缺少字段 {key}")

            entry_id = entry.get("id")
            validation.require(
                isinstance(entry_id, str) and bool(entry_id),
                f"{label}.id: 必须是非空字符串",
            )
            if isinstance(entry_id, str) and entry_id:
                validation.require(entry_id not in entry_by_id, f"{label}.id: 重复 {entry_id}")
                entry_by_id[entry_id] = entry

            role = entry.get("role")
            scope = entry.get("scope")
            entry_status = entry.get("status")
            validation.require(role in ENTRY_ROLES, f"{label}.role: 非法角色")
            validation.require(scope in ENTRY_SCOPES, f"{label}.scope: 非法范围")
            validation.require(entry_status in ENTRY_STATUSES, f"{label}.status: 非法状态")
            if entry_status == "active" and isinstance(role, str):
                active_roles.add(role)

            validation.require(has_value(entry.get("purpose")), f"{label}.purpose: 不得为空")
            code_path = entry.get("code_path")
            validation.require(is_safe_project_path(code_path), f"{label}.code_path: 必须是项目内安全相对路径")
            working_directory = entry.get("working_directory")
            validation.require(
                is_safe_project_path(working_directory),
                f"{label}.working_directory: 必须是项目内安全相对路径",
            )

            stage_refs = require_list(entry, "stage_refs", label, validation)
            task_refs = require_list(entry, "task_refs", label, validation)
            config_paths = require_list(entry, "config_paths", label, validation)
            manual_command = require_list(entry, "manual_command", label, validation)
            require_list(entry, "runtime_parameters", label, validation)
            require_list(entry, "input_refs", label, validation)
            require_list(entry, "output_refs", label, validation)
            goal_protocol_refs = require_list(entry, "goal_protocol_refs", label, validation)
            goal_criterion_refs = require_list(entry, "goal_criterion_refs", label, validation)
            result_logic_refs = require_list(entry, "result_logic_refs", label, validation)

            for stage_id in stage_refs:
                validation.require(stage_id in stage_ids, f"{label}.stage_refs: 未知阶段 {stage_id!r}")
            for task_id in task_refs:
                validation.require(task_id in task_ids, f"{label}.task_refs: 未知任务 {task_id!r}")
            for path in config_paths:
                validation.require(is_safe_project_path(path), f"{label}.config_paths: 非法路径 {path!r}")
            for protocol_id in goal_protocol_refs:
                validation.require(
                    protocol_id in protocol_ids,
                    f"{label}.goal_protocol_refs: 未知协议 {protocol_id!r}",
                )
            for criterion_id in goal_criterion_refs:
                validation.require(
                    criterion_id in criterion_ids,
                    f"{label}.goal_criterion_refs: 未知判据 {criterion_id!r}",
                )

            if mode in {"stage", "final"} and entry_status == "active":
                validation.require(bool(stage_refs), f"{label}.stage_refs: 活动入口不得为空")
                validation.require(bool(task_refs), f"{label}.task_refs: 活动入口不得为空")
                validation.require(bool(manual_command), f"{label}.manual_command: 活动入口不得为空")
                validation.require(
                    all(isinstance(token, str) and token for token in manual_command),
                    f"{label}.manual_command: 每项必须是非空字符串",
                )
                validation.require(bool(result_logic_refs), f"{label}.result_logic_refs: 活动入口不得为空")
                combined = " ".join(str(token) for token in manual_command).lower()
                validation.require("<<" not in combined, f"{label}.manual_command: 禁止 heredoc")
                validation.require("python -c" not in combined, f"{label}.manual_command: 禁止 python -c")
                validation.require("python3 -c" not in combined, f"{label}.manual_command: 禁止 python3 -c")
                validation.require("bash -c" not in combined, f"{label}.manual_command: 禁止 bash -c")
                validation.require("sh -c" not in combined, f"{label}.manual_command: 禁止 sh -c")

                if project_root is not None and is_safe_project_path(code_path):
                    validation.require(
                        (project_root / code_path).is_file(),
                        f"{label}.code_path: 文件不存在 {code_path}",
                    )
                if project_root is not None:
                    for path in config_paths:
                        if is_safe_project_path(path):
                            validation.require(
                                (project_root / path).is_file(),
                                f"{label}.config_paths: 文件不存在 {path}",
                            )

            if role == "stage_check" and isinstance(code_path, str):
                validation.require(
                    is_under(code_path, DIRECTORY_CONTRACT["checks"]),
                    f"{label}: stage_check 必须位于 cvpr_workspace/checks/",
                )
                validation.require(
                    scope == "development_check",
                    f"{label}: stage_check 必须使用 development_check",
                )
            if role == "goal_evaluation" and isinstance(code_path, str):
                validation.require(
                    is_under(code_path, DIRECTORY_CONTRACT["goal_evaluation"]),
                    f"{label}: goal_evaluation 必须位于 cvpr_workspace/goal_evaluation/",
                )
            if role == "analysis" and isinstance(code_path, str):
                validation.require(
                    is_under(code_path, DIRECTORY_CONTRACT["analysis"]),
                    f"{label}: analysis 必须位于 cvpr_workspace/analysis/",
                )
            if scope == "goal_verification":
                validation.require(bool(goal_protocol_refs), f"{label}: Goal 核验必须引用协议")
                validation.require(bool(goal_criterion_refs), f"{label}: Goal 核验必须引用判据")
            else:
                validation.require(
                    not goal_criterion_refs or scope == "evidence_analysis",
                    f"{label}: 非 Goal 核验入口不得声明 Goal 通过判据",
                )

    if mode in {"stage", "final"}:
        validation.require(bool(entry_by_id), "正式执行的入口清单不得为空")
        validation.require(
            required_roles.issubset(active_roles),
            f"缺少活动必需入口：{sorted(required_roles - active_roles)}",
        )

    return entry_by_id


def validate_runs(
    rows: list[dict[str, Any]],
    stage_ids: set[str],
    task_ids: set[str],
    entry_ids: set[str],
    criterion_ids: set[str],
    protocol_ids: set[str],
    validation: Validation,
) -> list[dict[str, Any]]:
    record_ids: set[str] = set()
    do_runs: list[dict[str, Any]] = []
    for index, row in enumerate(rows, start=1):
        label = f"runs.jsonl:记录{index}"
        record_id = row.get("id")
        if isinstance(record_id, str):
            validation.require(record_id not in record_ids, f"{label}.id: 重复 {record_id}")
            record_ids.add(record_id)
        if "run_id" not in row:
            continue

        do_runs.append(row)
        for key in (
            "id",
            "run_id",
            "event",
            "created_at",
            "stage_id",
            "task_id",
            "entry_id",
            "kind",
            "status",
            "code_version",
            "config_refs",
            "command",
            "environment_refs",
            "input_refs",
            "output_refs",
            "protocol_refs",
            "criterion_refs",
            "result_summary",
            "evidence_refs",
            "deviation_refs",
        ):
            validation.require(key in row, f"{label}: 缺少字段 {key}")
        validation.require(has_value(row.get("run_id")), f"{label}.run_id: 不得为空")
        validation.require(row.get("event") in RUN_EVENTS, f"{label}.event: 非法事件")
        validation.require(row.get("stage_id") in stage_ids, f"{label}.stage_id: 未知阶段")
        validation.require(row.get("task_id") in task_ids, f"{label}.task_id: 未知任务")
        validation.require(row.get("entry_id") in entry_ids, f"{label}.entry_id: 未知入口")
        validation.require(row.get("kind") in RUN_KINDS, f"{label}.kind: 非法类型")
        validation.require(row.get("status") in RUN_STATUSES, f"{label}.status: 非法状态")
        validation.require(isinstance(row.get("code_version"), dict), f"{label}.code_version: 必须是对象")
        for key in (
            "config_refs",
            "command",
            "environment_refs",
            "input_refs",
            "output_refs",
            "protocol_refs",
            "criterion_refs",
            "evidence_refs",
            "deviation_refs",
        ):
            require_list(row, key, label, validation)
        for protocol_id in row.get("protocol_refs", []):
            validation.require(protocol_id in protocol_ids, f"{label}: 未知协议 {protocol_id!r}")
        for criterion_id in row.get("criterion_refs", []):
            validation.require(criterion_id in criterion_ids, f"{label}: 未知判据 {criterion_id!r}")
        if row.get("status") == "succeeded":
            validation.require(bool(row.get("output_refs")), f"{label}: succeeded 运行必须有 output_refs")
            validation.require(bool(row.get("evidence_refs")), f"{label}: succeeded 运行必须有 evidence_refs")
        if row.get("kind") == "goal_verification":
            validation.require(bool(row.get("protocol_refs")), f"{label}: Goal 运行必须引用协议")
            validation.require(bool(row.get("criterion_refs")), f"{label}: Goal 运行必须引用判据")
    return do_runs


def validate_goal_assessment(
    assessment: Any,
    goal: dict[str, Any],
    required_criterion_ids: set[str],
    successful_goal_runs: list[dict[str, Any]],
    mode: str,
    validation: Validation,
) -> None:
    if mode != "final":
        validation.require(
            assessment is None or isinstance(assessment, dict),
            "state.yaml.goal_assessment: 必须是对象或 null",
        )
        return

    validation.require(isinstance(assessment, dict), "final 模式必须存在 goal_assessment")
    if not isinstance(assessment, dict):
        return
    for key in (
        "goal_id",
        "goal_version",
        "status",
        "criterion_results",
        "acceptance_logic_result",
        "audited_at",
        "evidence_refs",
    ):
        validation.require(key in assessment, f"goal_assessment: 缺少字段 {key}")
    validation.require(assessment.get("goal_id") == goal.get("goal_id"), "goal_assessment.goal_id 不一致")
    validation.require(assessment.get("goal_version") == goal.get("version"), "goal_assessment.goal_version 不一致")
    assessment_status = assessment.get("status")
    validation.require(
        assessment_status in {"passed", "not_met", "indeterminate"},
        "final 模式 goal_assessment.status 必须为 passed、not_met 或 indeterminate",
    )
    logic_result = assessment.get("acceptance_logic_result")
    validation.require(
        logic_result is True or logic_result is False or logic_result is None,
        "acceptance_logic_result 必须为 true、false 或 null",
    )
    validation.require(has_value(assessment.get("audited_at")), "goal_assessment.audited_at: 不得为空")
    evidence = require_list(assessment, "evidence_refs", "goal_assessment", validation)
    validation.require(bool(evidence), "goal_assessment.evidence_refs: 不得为空")

    criterion_results = assessment.get("criterion_results")
    validation.require(isinstance(criterion_results, list), "goal_assessment.criterion_results: 必须是数组")
    result_by_id: dict[str, dict[str, Any]] = {}
    if isinstance(criterion_results, list):
        for index, row in enumerate(criterion_results, start=1):
            label = f"goal_assessment.criterion_results[{index}]"
            validation.require(isinstance(row, dict), f"{label}: 必须是对象")
            if not isinstance(row, dict):
                continue
            criterion_id = row.get("criterion_id")
            validation.require(criterion_id in required_criterion_ids, f"{label}: 未知或非必需判据")
            if isinstance(criterion_id, str):
                validation.require(criterion_id not in result_by_id, f"{label}: 重复判据 {criterion_id}")
                result_by_id[criterion_id] = row
            validation.require(row.get("outcome") in CRITERION_OUTCOMES, f"{label}.outcome: 非法结论")
            validation.require(has_value(row.get("reason")), f"{label}.reason: 不得为空")
            refs = require_list(row, "evidence_refs", label, validation)
            run_refs = require_list(row, "run_ids", label, validation)
            validation.require(bool(refs), f"{label}.evidence_refs: 不得为空")
            if row.get("outcome") in {"passed", "not_met"}:
                validation.require(bool(run_refs), f"{label}.run_ids: passed 或 not_met 时不得为空")

    validation.require(
        set(result_by_id) == required_criterion_ids,
        "goal_assessment: 必须且仅能覆盖全部必需判据",
    )
    outcomes: list[str] = []
    for criterion_id in required_criterion_ids:
        row = result_by_id.get(criterion_id, {})
        outcome = row.get("outcome")
        if isinstance(outcome, str):
            outcomes.append(outcome)
        run_ids = {
            run.get("run_id")
            for run in successful_goal_runs
            if criterion_id in run.get("criterion_refs", [])
        }
        if outcome in {"passed", "not_met"}:
            validation.require(bool(run_ids), f"必需判据 {criterion_id} 缺少成功的正式核验 Run")
        for run_id in row.get("run_ids", []):
            validation.require(run_id in run_ids, f"判据 {criterion_id}: 未知成功 Goal Run {run_id!r}")

    if assessment_status == "passed":
        validation.require(
            outcomes and all(outcome == "passed" for outcome in outcomes),
            "goal_assessment.status 为 passed 时全部必需判据必须 passed",
        )
        validation.require(
            assessment.get("acceptance_logic_result") is True,
            "goal_assessment.status 为 passed 时 acceptance_logic_result 必须为 true",
        )
    elif assessment_status == "not_met":
        validation.require(
            "not_met" in outcomes,
            "goal_assessment.status 为 not_met 时至少一个必需判据必须 not_met",
        )
        validation.require(
            assessment.get("acceptance_logic_result") is False,
            "goal_assessment.status 为 not_met 时 acceptance_logic_result 必须为 false",
        )
    elif assessment_status == "indeterminate":
        validation.require(
            "indeterminate" in outcomes and "not_met" not in outcomes,
            "goal_assessment.status 为 indeterminate 时必须有不可判断判据且不能已有 not_met 判据",
        )
        validation.require(
            assessment.get("acceptance_logic_result") is None,
            "goal_assessment.status 为 indeterminate 时 acceptance_logic_result 必须为 null",
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="校验 cvpr-do 执行工作区与证据状态")
    parser.add_argument("project", nargs="?", type=Path, help="项目根目录")
    parser.add_argument(
        "--mode",
        choices=("preflight", "stage", "final"),
        default="preflight",
        help="校验深度",
    )
    parser.add_argument("--manifest-only", type=Path, help="只校验入口清单结构")
    args = parser.parse_args()
    validation = Validation()

    if args.manifest_only is not None:
        manifest = load_json(args.manifest_only, "入口清单.yaml", validation)
        validate_manifest(
            manifest,
            None,
            None,
            None,
            set(),
            set(),
            set(),
            set(),
            "preflight",
            validation,
        )
        if validation.errors:
            print("INVALID:")
            for error in validation.errors:
                print(f"- {error}")
            return 1
        print(f"OK: {args.manifest_only} 入口清单模板有效")
        return 0

    if args.project is None:
        parser.error("必须提供 project，或使用 --manifest-only")

    project_root = args.project.expanduser().resolve()
    state_dir = project_root / ".cvpr"
    goal_file = state_dir / "goal.yaml"
    plan_file = state_dir / "plan.yaml"
    state_file = state_dir / "state.yaml"
    tasks_file = state_dir / "tasks.jsonl"
    runs_file = state_dir / "runs.jsonl"
    manifest_file = project_root / "cvpr_workspace" / "入口清单.yaml"

    required_files = (goal_file, plan_file, state_file, tasks_file, runs_file, manifest_file)
    for path in required_files:
        validation.require(path.is_file(), f"缺少必需文件：{path}")
    if validation.errors:
        print("INVALID:")
        for error in validation.errors:
            print(f"- {error}")
        return 1

    package_root = Path(__file__).resolve().parents[2]
    run_upstream_validator(
        package_root / "cvpr-goal" / "scripts" / "validate_goal_contract.py",
        [str(goal_file)],
        "goal.yaml",
        validation,
    )
    run_upstream_validator(
        package_root / "cvpr-plan" / "scripts" / "validate_plan_contract.py",
        [str(plan_file), "--goal-file", str(goal_file)],
        "plan.yaml",
        validation,
    )

    goal = load_json(goal_file, "goal.yaml", validation)
    plan = load_json(plan_file, "plan.yaml", validation)
    state = load_json(state_file, "state.yaml", validation)
    manifest = load_json(manifest_file, "入口清单.yaml", validation)
    task_rows = load_jsonl(tasks_file, "tasks.jsonl", validation)
    run_rows = load_jsonl(runs_file, "runs.jsonl", validation)

    criterion_ids, required_criterion_ids, protocol_ids = extract_goal(goal, validation)
    stage_by_id, plan_id, plan_version = extract_plan(plan, validation)
    task_ids, latest_tasks = validate_task_events(task_rows, set(stage_by_id), validation)
    status_by_stage = validate_state(
        state,
        plan_id,
        plan_version,
        stage_by_id,
        latest_tasks,
        args.mode,
        validation,
    )
    entry_by_id = validate_manifest(
        manifest,
        project_root,
        goal if isinstance(goal, dict) else None,
        plan if isinstance(plan, dict) else None,
        set(stage_by_id),
        task_ids,
        criterion_ids,
        protocol_ids,
        args.mode,
        validation,
    )
    do_runs = validate_runs(
        run_rows,
        set(stage_by_id),
        task_ids,
        set(entry_by_id),
        criterion_ids,
        protocol_ids,
        validation,
    )

    if args.mode == "stage" and isinstance(state, dict):
        current_stage_id = state.get("current_stage_id")
        active_entries = [
            entry
            for entry in entry_by_id.values()
            if entry.get("status") == "active"
            and current_stage_id in entry.get("stage_refs", [])
        ]
        validation.require(bool(active_entries), "当前阶段缺少活动且可手动运行的登记入口")
        stage = stage_by_id.get(current_stage_id, {})
        stage_validation = stage.get("stage_validation", {})
        if isinstance(stage_validation, dict) and stage_validation.get("kind") == "goal_verification":
            validation.require(
                any(entry.get("scope") == "goal_verification" for entry in active_entries),
                "Goal 验证阶段缺少 goal_verification 入口",
            )

    successful_goal_runs = [
        row
        for row in do_runs
        if row.get("kind") == "goal_verification"
        and row.get("event") == "completed"
        and row.get("status") == "succeeded"
    ]
    if isinstance(state, dict) and isinstance(goal, dict):
        validate_goal_assessment(
            state.get("goal_assessment"),
            goal,
            required_criterion_ids,
            successful_goal_runs,
            args.mode,
            validation,
        )

    if args.mode == "final":
        evidence_audit_ids = {
            stage_id
            for stage_id, stage in stage_by_id.items()
            if isinstance(stage.get("stage_validation"), dict)
            and stage["stage_validation"].get("kind") == "evidence_audit"
        }
        validation.require(bool(evidence_audit_ids), "final 模式缺少 evidence_audit 阶段")
        for stage_id in evidence_audit_ids:
            validation.require(
                status_by_stage.get(stage_id, {}).get("status") == "accepted",
                f"evidence_audit 阶段 {stage_id} 尚未 accepted",
            )

    if validation.errors:
        print("INVALID:")
        for error in validation.errors:
            print(f"- {error}")
        return 1

    print(f"OK: {project_root} cvpr-do 执行工作区有效（模式 {args.mode}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

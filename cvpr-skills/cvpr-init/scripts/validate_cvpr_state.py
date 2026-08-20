#!/usr/bin/env python3
"""Validate a cvpr-skill project state using only the Python standard library."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


REQUIRED_FILES = (
    "project.yaml",
    "state.yaml",
    "tasks.jsonl",
    "claims.yaml",
    "decisions.jsonl",
    "runs.jsonl",
    "deviations.jsonl",
)
WORK_STATUSES = {
    "proposed",
    "running",
    "executed",
    "accepted",
    "blocked",
    "rejected",
    "superseded",
}


class Validation:
    def __init__(self) -> None:
        self.errors: list[str] = []

    def require(self, condition: bool, message: str) -> None:
        if not condition:
            self.errors.append(message)


def load_json_document(path: Path, validation: Validation) -> Any:
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        validation.errors.append(f"{path.name}: 无法解析为 JSON/YAML 1.2 子集：{exc}")
        return None


def load_jsonl(path: Path, validation: Validation) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        validation.errors.append(f"{path.name}: 无法读取：{exc}")
        return rows
    for line_number, raw in enumerate(lines, start=1):
        if not raw.strip():
            continue
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            validation.errors.append(f"{path.name}:{line_number}: 非法 JSON：{exc}")
            continue
        if not isinstance(value, dict):
            validation.errors.append(f"{path.name}:{line_number}: 每行必须是 JSON 对象")
            continue
        rows.append(value)
    return rows


def validate_project(project: Any, validation: Validation) -> None:
    validation.require(isinstance(project, dict), "project.yaml: 根节点必须是对象")
    if not isinstance(project, dict):
        return
    for key in (
        "schema_version",
        "project_id",
        "project_name",
        "project_root",
        "objectives",
        "success_criteria",
        "out_of_scope",
        "resources",
        "history_reconstruction",
    ):
        validation.require(key in project, f"project.yaml: 缺少字段 {key}")
    for key in ("objectives", "success_criteria", "out_of_scope"):
        validation.require(isinstance(project.get(key), list), f"project.yaml: {key} 必须是数组")
    history = project.get("history_reconstruction")
    validation.require(isinstance(history, dict), "project.yaml: history_reconstruction 必须是对象")
    if isinstance(history, dict):
        for key in ("status", "verified_items", "reported_items", "unknowns", "conflicts"):
            validation.require(key in history, f"project.yaml: history_reconstruction 缺少 {key}")


def validate_tasks(rows: list[dict[str, Any]], validation: Validation) -> dict[str, dict[str, Any]]:
    record_by_id: dict[str, dict[str, Any]] = {}
    latest_by_task: dict[str, dict[str, Any]] = {}
    latest_revision: dict[str, int] = {}
    required = (
        "id",
        "created_at",
        "phase",
        "status",
        "objective",
        "inputs",
        "boundaries",
        "deliverables",
        "acceptance_criteria",
        "evidence_refs",
        "suggested_capability",
    )
    for index, row in enumerate(rows, start=1):
        label = f"tasks.jsonl:记录{index}"
        for key in required:
            validation.require(key in row, f"{label}: 缺少字段 {key}")
        record_id = row.get("id")
        validation.require(isinstance(record_id, str) and bool(record_id), f"{label}: id 必须是非空字符串")
        if not isinstance(record_id, str) or not record_id:
            continue
        validation.require(record_id not in record_by_id, f"{label}: 重复记录 ID {record_id}")

        task_id = row.get("task_id", record_id)
        validation.require(
            isinstance(task_id, str) and bool(task_id),
            f"{label}: task_id 必须是非空字符串",
        )
        if not isinstance(task_id, str) or not task_id:
            continue

        if "task_id" in row:
            revision = row.get("revision")
            previous = row.get("previous_record_id")
            validation.require(
                isinstance(revision, int) and not isinstance(revision, bool) and revision >= 1,
                f"{label}: revision 必须是正整数",
            )
            validation.require(bool(row.get("event")), f"{label}: event 必须是非空字符串")
            expected_revision = latest_revision.get(task_id, 0) + 1
            validation.require(
                revision == expected_revision,
                f"{label}: 任务 {task_id} 的 revision 应为 {expected_revision}",
            )
            if expected_revision == 1:
                validation.require(previous is None, f"{label}: 首条记录 previous_record_id 必须为 null")
            else:
                expected_previous = latest_by_task[task_id].get("id")
                validation.require(
                    previous == expected_previous,
                    f"{label}: previous_record_id 应指向 {expected_previous}",
                )
            if isinstance(revision, int) and not isinstance(revision, bool):
                latest_revision[task_id] = revision
        else:
            validation.require(
                task_id not in latest_by_task,
                f"{label}: 旧格式任务 ID 重复 {task_id}",
            )
            latest_revision[task_id] = 1

        record_by_id[record_id] = row
        latest_by_task[task_id] = row
        status = row.get("status")
        validation.require(status in WORK_STATUSES, f"{label}: 非法状态 {status!r}")
        for key in ("inputs", "boundaries", "deliverables", "acceptance_criteria", "evidence_refs"):
            validation.require(isinstance(row.get(key), list), f"{label}: {key} 必须是数组")
        if status == "accepted":
            evidence = row.get("evidence_refs")
            validation.require(isinstance(evidence, list) and bool(evidence), f"{label}: accepted 任务必须有 evidence_refs")
    return latest_by_task


def validate_state(state: Any, task_by_id: dict[str, dict[str, Any]], validation: Validation) -> None:
    validation.require(isinstance(state, dict), "state.yaml: 根节点必须是对象")
    if not isinstance(state, dict):
        return
    for key in (
        "schema_version",
        "phase",
        "phase_status",
        "last_reviewed_at",
        "current_atomic_task_id",
        "last_accepted_task_id",
        "confirmed_findings",
        "open_questions",
        "blockers",
        "active_deviations",
        "next_task",
    ):
        validation.require(key in state, f"state.yaml: 缺少字段 {key}")
    validation.require(state.get("phase_status") in WORK_STATUSES, "state.yaml: phase_status 非法")
    for key in ("confirmed_findings", "open_questions", "blockers", "active_deviations"):
        validation.require(isinstance(state.get(key), list), f"state.yaml: {key} 必须是数组")
    for index, finding in enumerate(state.get("confirmed_findings", []), start=1):
        label = f"state.yaml:confirmed_findings[{index}]"
        validation.require(isinstance(finding, dict), f"{label}: 必须是对象")
        if isinstance(finding, dict):
            validation.require(bool(finding.get("statement")), f"{label}: 缺少 statement")
            refs = finding.get("evidence_refs")
            validation.require(isinstance(refs, list) and bool(refs), f"{label}: 必须有 evidence_refs")

    if state.get("schema_version") == "1.1":
        for key in (
            "active_plan",
            "current_stage_id",
            "last_accepted_stage_id",
            "stage_statuses",
            "execution_workspace",
            "goal_assessment",
        ):
            validation.require(key in state, f"state.yaml: 1.1 缺少字段 {key}")

        active_plan = state.get("active_plan")
        validation.require(
            active_plan is None or isinstance(active_plan, dict),
            "state.yaml: active_plan 必须是对象或 null",
        )
        if isinstance(active_plan, dict):
            for key in ("plan_id", "version", "plan_file"):
                validation.require(bool(active_plan.get(key)), f"state.yaml: active_plan 缺少 {key}")

        stage_statuses = state.get("stage_statuses")
        validation.require(isinstance(stage_statuses, list), "state.yaml: stage_statuses 必须是数组")
        stage_ids: set[str] = set()
        if isinstance(stage_statuses, list):
            for index, row in enumerate(stage_statuses, start=1):
                label = f"state.yaml:stage_statuses[{index}]"
                validation.require(isinstance(row, dict), f"{label}: 必须是对象")
                if not isinstance(row, dict):
                    continue
                stage_id = row.get("stage_id")
                validation.require(
                    isinstance(stage_id, str) and bool(stage_id),
                    f"{label}: stage_id 必须是非空字符串",
                )
                if isinstance(stage_id, str):
                    validation.require(stage_id not in stage_ids, f"{label}: 重复阶段 {stage_id}")
                    stage_ids.add(stage_id)
                validation.require(row.get("status") in WORK_STATUSES, f"{label}: status 非法")
                evidence = row.get("evidence_refs")
                validation.require(isinstance(evidence, list), f"{label}: evidence_refs 必须是数组")
                if row.get("status") == "accepted":
                    validation.require(bool(evidence), f"{label}: accepted 阶段必须有 evidence_refs")

        current_stage_id = state.get("current_stage_id")
        validation.require(
            current_stage_id is None or current_stage_id in stage_ids,
            "state.yaml: current_stage_id 未引用 stage_statuses",
        )
        last_stage_id = state.get("last_accepted_stage_id")
        validation.require(
            last_stage_id is None or last_stage_id in stage_ids,
            "state.yaml: last_accepted_stage_id 未引用 stage_statuses",
        )
        if last_stage_id is not None and isinstance(stage_statuses, list):
            last_rows = [
                row
                for row in stage_statuses
                if isinstance(row, dict) and row.get("stage_id") == last_stage_id
            ]
            validation.require(
                bool(last_rows) and last_rows[0].get("status") == "accepted",
                "state.yaml: last_accepted_stage_id 指向的阶段不是 accepted",
            )

        workspace = state.get("execution_workspace")
        validation.require(isinstance(workspace, dict), "state.yaml: execution_workspace 必须是对象")
        if isinstance(workspace, dict):
            validation.require(
                workspace.get("manifest_file") == "cvpr_workspace/入口清单.yaml",
                "state.yaml: execution_workspace.manifest_file 路径非法",
            )
            validation.require(
                workspace.get("status") in {"not_created", "proposed", "active", "superseded"},
                "state.yaml: execution_workspace.status 非法",
            )
        assessment = state.get("goal_assessment")
        validation.require(
            assessment is None or isinstance(assessment, dict),
            "state.yaml: goal_assessment 必须是对象或 null",
        )
    current_id = state.get("current_atomic_task_id")
    if current_id is not None:
        validation.require(current_id in task_by_id, f"state.yaml: current_atomic_task_id 未引用有效任务：{current_id}")
    accepted_id = state.get("last_accepted_task_id")
    if accepted_id is not None:
        validation.require(accepted_id in task_by_id, f"state.yaml: last_accepted_task_id 未引用有效任务：{accepted_id}")
        if accepted_id in task_by_id:
            validation.require(
                task_by_id[accepted_id].get("status") == "accepted",
                f"state.yaml: last_accepted_task_id 指向的任务不是 accepted：{accepted_id}",
            )
    next_task = state.get("next_task")
    if next_task is not None:
        validation.require(isinstance(next_task, dict), "state.yaml: next_task 必须是对象或 null")
        if isinstance(next_task, dict):
            validation.require(next_task.get("status") == "proposed", "state.yaml: next_task 状态必须是 proposed")
            task_id = next_task.get("task_id", next_task.get("id"))
            validation.require(task_id in task_by_id, f"state.yaml: next_task.id 未引用有效任务：{task_id}")


def validate_claims(claims: Any, task_by_id: dict[str, dict[str, Any]], validation: Validation) -> None:
    validation.require(isinstance(claims, dict), "claims.yaml: 根节点必须是对象")
    if not isinstance(claims, dict):
        return
    validation.require("schema_version" in claims, "claims.yaml: 缺少 schema_version")
    rows = claims.get("claims")
    validation.require(isinstance(rows, list), "claims.yaml: claims 必须是数组")
    if not isinstance(rows, list):
        return
    seen: set[str] = set()
    for index, row in enumerate(rows, start=1):
        label = f"claims.yaml:claims[{index}]"
        validation.require(isinstance(row, dict), f"{label}: 必须是对象")
        if not isinstance(row, dict):
            continue
        claim_id = row.get("id")
        validation.require(isinstance(claim_id, str) and bool(claim_id), f"{label}: id 必须是非空字符串")
        if isinstance(claim_id, str):
            validation.require(claim_id not in seen, f"{label}: 重复 Claim ID {claim_id}")
            seen.add(claim_id)
        evidence_task_ids = row.get("evidence_task_ids", [])
        validation.require(isinstance(evidence_task_ids, list), f"{label}: evidence_task_ids 必须是数组")
        if isinstance(evidence_task_ids, list):
            for task_id in evidence_task_ids:
                validation.require(task_id in task_by_id, f"{label}: 未知任务引用 {task_id}")


def validate_generic_ledger(
    filename: str,
    rows: list[dict[str, Any]],
    validation: Validation,
) -> None:
    seen: set[str] = set()
    for index, row in enumerate(rows, start=1):
        label = f"{filename}:记录{index}"
        entry_id = row.get("id")
        validation.require(isinstance(entry_id, str) and bool(entry_id), f"{label}: id 必须是非空字符串")
        if isinstance(entry_id, str):
            validation.require(entry_id not in seen, f"{label}: 重复 ID {entry_id}")
            seen.add(entry_id)
        validation.require(bool(row.get("created_at")), f"{label}: 缺少 created_at")


def resolve_state_dir(argument: str) -> Path:
    candidate = Path(argument).expanduser().resolve()
    return candidate if candidate.name == ".cvpr" else candidate / ".cvpr"


def main() -> int:
    parser = argparse.ArgumentParser(description="校验项目 .cvpr 状态结构与关键交叉引用")
    parser.add_argument("project", help="项目根目录或 .cvpr 目录")
    args = parser.parse_args()
    state_dir = resolve_state_dir(args.project)
    validation = Validation()

    validation.require(state_dir.is_dir(), f"未找到状态目录：{state_dir}")
    if not state_dir.is_dir():
        for error in validation.errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1

    for filename in REQUIRED_FILES:
        validation.require((state_dir / filename).is_file(), f"缺少必需文件：{filename}")
    if validation.errors:
        for error in validation.errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1

    project = load_json_document(state_dir / "project.yaml", validation)
    state = load_json_document(state_dir / "state.yaml", validation)
    claims = load_json_document(state_dir / "claims.yaml", validation)
    tasks = load_jsonl(state_dir / "tasks.jsonl", validation)
    decisions = load_jsonl(state_dir / "decisions.jsonl", validation)
    runs = load_jsonl(state_dir / "runs.jsonl", validation)
    deviations = load_jsonl(state_dir / "deviations.jsonl", validation)

    validate_project(project, validation)
    task_by_id = validate_tasks(tasks, validation)
    validate_state(state, task_by_id, validation)
    validate_claims(claims, task_by_id, validation)
    validate_generic_ledger("decisions.jsonl", decisions, validation)
    validate_generic_ledger("runs.jsonl", runs, validation)
    validate_generic_ledger("deviations.jsonl", deviations, validation)

    if validation.errors:
        for error in validation.errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1

    print(f"OK: {state_dir} 状态有效（任务 {len(tasks)}，Claim {len(claims.get('claims', []))}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

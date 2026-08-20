#!/usr/bin/env python3
"""Validate .cvpr/paper.yaml for the cvpr-paper router."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path, PurePosixPath
from typing import Any


PAPER_STATUSES = {
    "proposed",
    "drafting",
    "draft_ready",
    "reviewed",
    "accepted",
    "blocked",
    "superseded",
}
STAGE_STATUSES = {"proposed", "running", "executed", "accepted", "blocked", "not_applicable"}
ARTIFACT_STATUSES = {"proposed", "current", "stale", "blocked", "superseded"}
CONFIRMATION_STATUSES = {"pending", "accepted", "rejected", "superseded"}
EXPECTED_STAGES = {
    "evidence",
    "argument-outline",
    "drafting",
    "citations",
    "reproducibility",
    "polishing",
    "latex",
    "paper-audit",
    "review",
}
EXPECTED_CONFIRMATIONS = {"argument_outline", "final_draft"}


def has_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, dict)):
        return bool(value)
    return True


def safe_path(value: Any) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    path = PurePosixPath(value)
    return not path.is_absolute() and ".." not in path.parts


def load(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def main() -> int:
    parser = argparse.ArgumentParser(description="校验 .cvpr/paper.yaml")
    parser.add_argument("paper_file")
    parser.add_argument("--project-root")
    args = parser.parse_args()
    path = Path(args.paper_file)
    errors: list[str] = []
    try:
        data = load(path)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"ERROR: {path}: {exc}", file=sys.stderr)
        return 1
    if not isinstance(data, dict):
        print("ERROR: 根节点必须是对象", file=sys.stderr)
        return 1

    status = data.get("status")
    if status not in PAPER_STATUSES:
        errors.append("status 非法")
    if not has_value(data.get("paper_id")):
        errors.append("paper_id 不得为空")
    if not isinstance(data.get("version"), int) or data.get("version", 0) < 1:
        errors.append("version 必须为正整数")

    ledgers = data.get("ledgers")
    if not isinstance(ledgers, dict):
        errors.append("ledgers 必须是对象")
        ledgers = {}
    expected_ledgers = {
        "claims_file": ".cvpr/claims.yaml",
        "terminology_file": ".cvpr/paper/terminology.yaml",
        "numbers_file": ".cvpr/paper/numbers.yaml",
        "citations_file": ".cvpr/paper/citations.yaml",
    }
    for key, expected in expected_ledgers.items():
        if ledgers.get(key) != expected:
            errors.append(f"ledgers.{key} 必须为 {expected}")

    manuscript = data.get("manuscript")
    if not isinstance(manuscript, dict):
        errors.append("manuscript 必须是对象")
        manuscript = {}
    if not safe_path(manuscript.get("root")):
        errors.append("manuscript.root 必须是安全相对路径")
    required_sections = manuscript.get("required_sections")
    section_rows = manuscript.get("section_statuses")
    if not isinstance(required_sections, list) or not required_sections:
        errors.append("required_sections 必须是非空数组")
        required_sections = []
    valid_required_sections = [
        value for value in required_sections if isinstance(value, str) and value.strip()
    ]
    if (
        len(valid_required_sections) != len(required_sections)
        or len(set(valid_required_sections)) != len(valid_required_sections)
    ):
        errors.append("required_sections 必须是唯一非空字符串")
    for key in ("source_files", "rendered_files"):
        values = manuscript.get(key)
        if not isinstance(values, list):
            errors.append(f"manuscript.{key} 必须是数组")
            continue
        for index, value in enumerate(values):
            if not safe_path(value):
                errors.append(f"manuscript.{key}[{index}] 必须是安全相对路径")
    if not isinstance(section_rows, list):
        errors.append("section_statuses 必须是数组")
        section_rows = []
    section_map: dict[str, dict[str, Any]] = {}
    for index, row in enumerate(section_rows):
        if (
            not isinstance(row, dict)
            or not isinstance(row.get("section"), str)
            or not row.get("section", "").strip()
        ):
            errors.append(f"section_statuses[{index}] 非法")
            continue
        section = row["section"]
        if section in section_map:
            errors.append(f"section_statuses 重复 {section}")
        section_map[section] = row
        if row.get("status") not in STAGE_STATUSES:
            errors.append(f"section_statuses[{index}].status 非法")
        if row.get("status") == "accepted" and not has_value(row.get("evidence_refs")):
            errors.append(f"section_statuses[{index}] accepted 必须有 evidence_refs")

    stages = data.get("stage_statuses")
    if not isinstance(stages, list):
        errors.append("stage_statuses 必须是数组")
        stages = []
    stage_map: dict[str, dict[str, Any]] = {}
    for index, row in enumerate(stages):
        if (
            not isinstance(row, dict)
            or not isinstance(row.get("stage"), str)
            or not row.get("stage", "").strip()
        ):
            errors.append(f"stage_statuses[{index}] 非法")
            continue
        stage = row["stage"]
        if stage in stage_map:
            errors.append(f"stage_statuses 重复 {stage}")
        stage_map[stage] = row
        stage_status = row.get("status")
        if stage_status not in STAGE_STATUSES:
            errors.append(f"stage_statuses[{index}].status 非法")
        if stage_status == "accepted" and not has_value(row.get("evidence_refs")):
            errors.append(f"stage_statuses[{index}] accepted 必须有 evidence_refs")
        if stage_status in {"blocked", "not_applicable"} and not has_value(row.get("reason")):
            errors.append(f"stage_statuses[{index}] {stage_status} 必须有 reason")
    if set(stage_map) != EXPECTED_STAGES:
        errors.append("stage_statuses 必须且仅能覆盖全部论文节点")

    confirmations = data.get("user_confirmations")
    if not isinstance(confirmations, list):
        errors.append("user_confirmations 必须是数组")
        confirmations = []
    confirmation_map: dict[str, dict[str, Any]] = {}
    for index, row in enumerate(confirmations):
        if not isinstance(row, dict) or row.get("kind") not in EXPECTED_CONFIRMATIONS:
            errors.append(f"user_confirmations[{index}] 非法")
            continue
        kind = row["kind"]
        if kind in confirmation_map:
            errors.append(f"user_confirmations 重复 {kind}")
        confirmation_map[kind] = row
        if row.get("status") not in CONFIRMATION_STATUSES:
            errors.append(f"user_confirmations[{index}].status 非法")
        if row.get("status") == "accepted":
            if not has_value(row.get("confirmed_at")) or not has_value(row.get("evidence_refs")):
                errors.append(f"user_confirmations[{index}] accepted 必须有时间和证据")
    if set(confirmation_map) != EXPECTED_CONFIRMATIONS:
        errors.append("必须且仅能存在两种完整初稿确认")

    active_result = data.get("active_result")
    active_snapshot = None
    if active_result is not None:
        if not isinstance(active_result, dict):
            errors.append("active_result 必须是对象或 null")
        else:
            active_snapshot = active_result.get("snapshot_id")
            for key in ("result_file", "review_id", "snapshot_id", "status", "route", "goal_status"):
                if not has_value(active_result.get(key)):
                    errors.append(f"active_result.{key} 不得为空")

    artifacts = data.get("artifacts")
    if not isinstance(artifacts, list):
        errors.append("artifacts 必须是数组")
        artifacts = []
    artifact_ids: set[str] = set()
    current_artifact_skills: set[str] = set()
    project_root = Path(args.project_root).resolve() if args.project_root else None
    for index, row in enumerate(artifacts):
        label = f"artifacts[{index}]"
        if not isinstance(row, dict):
            errors.append(f"{label} 必须是对象")
            continue
        artifact_id = row.get("artifact_id")
        if not isinstance(artifact_id, str) or not artifact_id.strip():
            errors.append(f"{label}.artifact_id 不得为空")
        elif artifact_id in artifact_ids:
            errors.append(f"{label}.artifact_id 重复")
        else:
            artifact_ids.add(artifact_id)
        for key in ("skill", "version", "input_snapshot_id", "path"):
            if not has_value(row.get(key)):
                errors.append(f"{label}.{key} 不得为空")
        artifact_status = row.get("status")
        if artifact_status not in ARTIFACT_STATUSES:
            errors.append(f"{label}.status 非法")
        if not safe_path(row.get("path")):
            errors.append(f"{label}.path 必须是安全相对路径")
        if artifact_status == "current" and active_snapshot and row.get("input_snapshot_id") != active_snapshot:
            errors.append(f"{label} current 产物必须绑定活动 snapshot")
        if (
            artifact_status == "current"
            and isinstance(row.get("skill"), str)
            and row.get("skill", "").strip()
        ):
            current_artifact_skills.add(row["skill"])
            if not has_value(row.get("evidence_refs")):
                errors.append(f"{label} current 产物必须有 evidence_refs")
        if project_root and artifact_status == "current" and safe_path(row.get("path")):
            if not (project_root / row["path"]).exists():
                errors.append(f"{label}.path 当前产物不存在")

    blockers = data.get("blockers")
    if not isinstance(blockers, list):
        errors.append("blockers 必须是数组")
        blockers = []

    if status in {"draft_ready", "reviewed", "accepted"}:
        if not isinstance(active_result, dict):
            errors.append(f"{status} 必须存在 active_result")
        else:
            if active_result.get("status") != "accepted":
                errors.append(f"{status} 要求 Result accepted")
            if active_result.get("route") != "paper":
                errors.append(f"{status} 要求 Result route=paper")
            if active_result.get("goal_status") != "passed":
                errors.append(f"{status} 要求 Goal passed")
        argument = confirmation_map.get("argument_outline", {})
        if argument.get("status") != "accepted":
            errors.append(f"{status} 要求论证提纲已确认")
        if set(section_map) != set(valid_required_sections):
            errors.append(f"{status} 必须覆盖全部必需章节")
        elif any(row.get("status") != "accepted" for row in section_map.values()):
            errors.append(f"{status} 的必需章节必须全部 accepted")
        if blockers:
            errors.append(f"{status} 不允许存在 blocker")
        if not has_value(manuscript.get("active_version")):
            errors.append(f"{status} 要求 manuscript.active_version")
        if not has_value(manuscript.get("source_files")):
            errors.append(f"{status} 要求 manuscript.source_files")
        if not has_value(manuscript.get("rendered_files")):
            errors.append(f"{status} 要求 manuscript.rendered_files")
        for stage_name in (
            "evidence",
            "argument-outline",
            "drafting",
            "citations",
            "reproducibility",
            "polishing",
            "latex",
        ):
            if stage_map.get(stage_name, {}).get("status") != "accepted":
                errors.append(f"{status} 要求 {stage_name} accepted")
        for skill_name in (
            "cvpr-writing",
            "cvpr-citation",
            "cvpr-reproducibility",
            "cvpr-polishing",
            "cvpr-latex",
        ):
            if skill_name not in current_artifact_skills:
                errors.append(f"{status} 要求 current {skill_name} 产物")
        target = data.get("target")
        if not isinstance(target, dict):
            errors.append("target 必须是对象")
        else:
            for key in ("venue", "track", "rules_verified_at", "template_path"):
                if not has_value(target.get(key)):
                    errors.append(f"{status} 要求 target.{key}")
            if has_value(target.get("template_path")) and not safe_path(target.get("template_path")):
                errors.append(f"{status} 要求 target.template_path 为安全相对路径")
            urls = target.get("official_source_urls")
            if not isinstance(urls, list) or not urls or not all(has_value(url) for url in urls):
                errors.append(f"{status} 要求官方来源 URL")

    if status in {"reviewed", "accepted"}:
        for stage_name in ("paper-audit", "review"):
            if stage_map.get(stage_name, {}).get("status") != "accepted":
                errors.append(f"{status} 要求 {stage_name} accepted")
        for skill_name in ("cvpr-paper-audit", "cvpr-reviewer"):
            if skill_name not in current_artifact_skills:
                errors.append(f"{status} 要求 current {skill_name} 产物")

    if status == "accepted":
        final_confirmation = confirmation_map.get("final_draft", {})
        if final_confirmation.get("status") != "accepted":
            errors.append("accepted 要求最终初稿已由用户确认")

    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(f"OK: {path} 论文路由状态有效（状态 {status}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Validate the machine-readable cvpr-start contract."""

from __future__ import annotations

import argparse
import json
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any


STATUSES = {
    "proposed",
    "in_progress",
    "needs-reframing",
    "accepted",
    "blocked",
    "superseded",
}
INPUT_KINDS = {"research_scope", "seed_papers", "mixed", "failure_evidence"}
MATERIAL_STATUSES = {"not_provided", "checked", "conflicting", "blocked"}
CANDIDATE_STATUSES = {"draft", "audited", "rejected", "user_selected"}
REVIEW_STATUSES = {"pending", "in_progress", "completed", "blocked"}
REVIEW_VERDICTS = {"pending", "pass", "revise", "reject", "blocked"}
REQUIRED_AXES = {
    "source_recency",
    "problem_evidence",
    "novelty_related_work",
    "method_falsifiability",
    "feasibility_review_risk",
}


def has_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, dict)):
        return bool(value)
    return True


def is_positive_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 1


def add(errors: list[str], condition: bool, message: str) -> None:
    if not condition:
        errors.append(message)


def list_field(
    errors: list[str],
    value: Any,
    label: str,
) -> list[Any]:
    add(errors, isinstance(value, list), f"{label} 必须是数组")
    return value if isinstance(value, list) else []


def validate_manifest(data: Any) -> list[str]:
    errors: list[str] = []
    add(errors, isinstance(data, dict), "根节点必须是对象")
    if not isinstance(data, dict):
        return errors

    for key in (
        "schema_version",
        "start_id",
        "version",
        "status",
        "created_at",
        "updated_at",
        "input",
        "literature",
        "user_material_check",
        "problem_statuses",
        "candidates",
        "someagents_review",
        "discussion",
        "final_idea",
        "blockers",
        "supersedes",
    ):
        add(errors, key in data, f"缺少根字段 {key}")

    status = data.get("status")
    final = status == "accepted"
    add(errors, status in STATUSES, f"status 非法：{status!r}")
    add(errors, has_value(data.get("start_id")), "start_id 不得为空")
    add(errors, is_positive_int(data.get("version")), "version 必须是正整数")
    if final:
        add(errors, has_value(data.get("created_at")), "accepted 要求 created_at")
        add(errors, has_value(data.get("updated_at")), "accepted 要求 updated_at")
    if isinstance(data.get("version"), int) and data.get("version", 1) > 1:
        add(errors, has_value(data.get("supersedes")), "version > 1 时必须填写 supersedes")

    input_data = data.get("input")
    add(errors, isinstance(input_data, dict), "input 必须是对象")
    if not isinstance(input_data, dict):
        input_data = {}
    input_kind = input_data.get("kind")
    add(errors, input_kind in INPUT_KINDS, f"input.kind 非法：{input_kind!r}")
    for key in ("seed_paper_refs", "reused_candidate_refs"):
        list_field(errors, input_data.get(key), f"input.{key}")
    if input_kind == "research_scope" and status != "proposed":
        add(errors, has_value(input_data.get("research_scope")), "research_scope 输入必须填写研究范围")
    if input_kind == "seed_papers" and status != "proposed":
        add(errors, has_value(input_data.get("seed_paper_refs")), "seed_papers 输入必须包含种子论文")
    if input_kind == "failure_evidence":
        add(errors, has_value(input_data.get("failure_evidence_ref")), "失败循环必须引用失败证据包")
        add(errors, has_value(input_data.get("previous_start_ref")), "失败循环必须引用上一轮 start.yaml")
        add(errors, has_value(input_data.get("reused_candidate_refs")), "失败循环必须引用历史候选 IDEA")

    literature = data.get("literature")
    add(errors, isinstance(literature, dict), "literature 必须是对象")
    if not isinstance(literature, dict):
        literature = {}
    papers = list_field(errors, literature.get("added_papers"), "literature.added_papers")
    paper_ids: set[str] = set()
    qualified_count = 0
    for index, paper in enumerate(papers):
        label = f"literature.added_papers[{index}]"
        add(errors, isinstance(paper, dict), f"{label} 必须是对象")
        if not isinstance(paper, dict):
            continue
        paper_id = paper.get("paper_id")
        add(errors, has_value(paper_id), f"{label}.paper_id 不得为空")
        if isinstance(paper_id, str) and paper_id:
            add(errors, paper_id not in paper_ids, f"{label}.paper_id 重复")
            paper_ids.add(paper_id)
        counts = paper.get("counts_toward_minimum")
        add(errors, isinstance(counts, bool), f"{label}.counts_toward_minimum 必须是布尔值")
        if counts is True:
            qualified_count += 1
            add(errors, paper.get("identity_status") == "verified", f"{label} 计数论文必须完成身份核验")
            add(
                errors,
                paper.get("relevance") in {"direct", "supporting"},
                f"{label} 计数论文必须直接相关或提供实质支持",
            )
            add(errors, paper.get("within_recency_window") is True, f"{label} 计数论文必须位于时效窗口")
            add(errors, has_value(paper.get("evidence_locator")), f"{label} 计数论文必须有正文证据定位")
    declared_count = literature.get("qualified_count")
    add(
        errors,
        isinstance(declared_count, int) and not isinstance(declared_count, bool),
        "literature.qualified_count 必须是整数",
    )
    if isinstance(declared_count, int) and not isinstance(declared_count, bool):
        add(errors, declared_count == qualified_count, "literature.qualified_count 与实际计数不一致")
    if final:
        add(errors, has_value(literature.get("search_cutoff_date")), "accepted 要求检索截止日")
        add(errors, has_value(literature.get("recency_window")), "accepted 要求明确时效窗口")
        add(errors, qualified_count >= 10, "accepted 至少需要 10 篇新增合格近期论文")
        add(errors, has_value(literature.get("registry_ref")), "accepted 要求文献注册表引用")
        add(errors, has_value(literature.get("problem_status_matrix_ref")), "accepted 要求问题状态矩阵引用")

    material = data.get("user_material_check")
    add(errors, isinstance(material, dict), "user_material_check 必须是对象")
    if not isinstance(material, dict):
        material = {}
    material_status = material.get("status")
    add(errors, material_status in MATERIAL_STATUSES, "user_material_check.status 非法")
    for key in ("input_refs", "findings", "evidence_refs"):
        list_field(errors, material.get(key), f"user_material_check.{key}")
    if material_status != "not_provided":
        add(errors, has_value(material.get("input_refs")), "用户材料非缺失状态必须记录输入")
        add(errors, has_value(material.get("findings")), "用户材料非缺失状态必须记录发现")

    list_field(errors, data.get("problem_statuses"), "problem_statuses")
    candidates = list_field(errors, data.get("candidates"), "candidates")
    candidate_ids: set[str] = set()
    eligible_candidate_ids: set[str] = set()
    selected_ids: set[str] = set()
    for index, candidate in enumerate(candidates):
        label = f"candidates[{index}]"
        add(errors, isinstance(candidate, dict), f"{label} 必须是对象")
        if not isinstance(candidate, dict):
            continue
        idea_id = candidate.get("idea_id")
        add(errors, has_value(idea_id), f"{label}.idea_id 不得为空")
        if isinstance(idea_id, str) and idea_id:
            add(errors, idea_id not in candidate_ids, f"{label}.idea_id 重复")
            candidate_ids.add(idea_id)
        candidate_status = candidate.get("status")
        add(errors, candidate_status in CANDIDATE_STATUSES, f"{label}.status 非法")
        evidence = list_field(errors, candidate.get("literature_evidence"), f"{label}.literature_evidence")
        if candidate_status in {"audited", "user_selected"}:
            add(errors, len(evidence) >= 2, f"{label} 正式候选至少需要两篇独立论文证据")
            evidence_papers: set[str] = set()
            has_recent = False
            for evidence_index, item in enumerate(evidence):
                evidence_label = f"{label}.literature_evidence[{evidence_index}]"
                add(errors, isinstance(item, dict), f"{evidence_label} 必须是对象")
                if not isinstance(item, dict):
                    continue
                evidence_paper = item.get("paper_id")
                add(errors, has_value(evidence_paper), f"{evidence_label}.paper_id 不得为空")
                if isinstance(evidence_paper, str):
                    evidence_papers.add(evidence_paper)
                add(errors, has_value(item.get("locator")), f"{evidence_label}.locator 不得为空")
                if item.get("recency") == "recent":
                    has_recent = True
            add(errors, len(evidence_papers) >= 2, f"{label} 证据必须来自至少两篇独立论文")
            add(errors, has_recent, f"{label} 至少需要一篇近期论文证据")
            for key in (
                "research_problem",
                "core_hypothesis",
                "proposed_change",
                "falsification_test",
                "novelty_boundary",
            ):
                add(errors, has_value(candidate.get(key)), f"{label}.{key} 不得为空")
            for key in ("counterevidence", "existing_solutions", "risks"):
                list_field(errors, candidate.get(key), f"{label}.{key}")
            add(errors, candidate.get("review_verdict") == "pass", f"{label} 正式候选必须通过审查")
            if isinstance(idea_id, str):
                eligible_candidate_ids.add(idea_id)
        if candidate_status == "user_selected" and isinstance(idea_id, str):
            selected_ids.add(idea_id)
    if final:
        add(errors, len(eligible_candidate_ids) >= 5, "accepted 至少需要 5 个通过证据和审查门槛的正式候选")

    review = data.get("someagents_review")
    add(errors, isinstance(review, dict), "someagents_review 必须是对象")
    if not isinstance(review, dict):
        review = {}
    add(errors, review.get("mode") == "B", "someagents_review.mode 必须为 B")
    add(errors, review.get("status") in REVIEW_STATUSES, "someagents_review.status 非法")
    add(errors, review.get("final_verdict") in REVIEW_VERDICTS, "someagents_review.final_verdict 非法")
    role_results = list_field(errors, review.get("role_results"), "someagents_review.role_results")
    covered_axes = set(list_field(errors, review.get("covered_axes"), "someagents_review.covered_axes"))
    list_field(errors, review.get("minority_findings"), "someagents_review.minority_findings")
    blockers = list_field(errors, review.get("unresolved_blockers"), "someagents_review.unresolved_blockers")
    snapshot_id = review.get("input_snapshot_id")
    reviewer_ids: set[str] = set()
    axes_from_roles: set[str] = set()
    for index, row in enumerate(role_results):
        label = f"someagents_review.role_results[{index}]"
        add(errors, isinstance(row, dict), f"{label} 必须是对象")
        if not isinstance(row, dict):
            continue
        reviewer_id = row.get("agent_id")
        add(errors, has_value(reviewer_id), f"{label}.agent_id 不得为空")
        if isinstance(reviewer_id, str):
            add(errors, reviewer_id not in reviewer_ids, f"{label}.agent_id 重复")
            reviewer_ids.add(reviewer_id)
        add(errors, row.get("independent") is True, f"{label} 必须由独立 Agent 完成")
        add(errors, row.get("status") == "completed", f"{label}.status 必须为 completed")
        add(errors, row.get("input_snapshot_id") == snapshot_id, f"{label} 输入快照不一致")
        role_axes = list_field(errors, row.get("covered_axes"), f"{label}.covered_axes")
        axes_from_roles.update(axis for axis in role_axes if isinstance(axis, str))
    if final:
        add(errors, review.get("status") == "completed", "accepted 要求多 Agent 审查完成")
        add(errors, has_value(snapshot_id), "accepted 要求审查输入快照")
        add(errors, len(role_results) >= 2, "accepted 至少需要两个独立 Agent 结果")
        add(errors, covered_axes == REQUIRED_AXES, "accepted 要求完整覆盖五个审查轴")
        add(errors, axes_from_roles == REQUIRED_AXES, "accepted 的 Agent 原始结果必须实际覆盖五个审查轴")
        add(errors, review.get("final_verdict") == "pass", "accepted 要求多 Agent 最终结论为 pass")
        add(errors, not blockers, "accepted 不允许存在未解决审查阻断")

    discussion = data.get("discussion")
    add(errors, isinstance(discussion, dict), "discussion 必须是对象")
    if not isinstance(discussion, dict):
        discussion = {}
    rounds = list_field(errors, discussion.get("rounds"), "discussion.rounds")
    round_count = discussion.get("substantive_rounds")
    add(
        errors,
        isinstance(round_count, int) and not isinstance(round_count, bool) and 0 <= round_count <= 5,
        "discussion.substantive_rounds 必须是 0 到 5 的整数",
    )
    if isinstance(round_count, int) and not isinstance(round_count, bool):
        add(errors, round_count == len(rounds), "discussion.substantive_rounds 与 rounds 数量不一致")
    for index, row in enumerate(rounds):
        label = f"discussion.rounds[{index}]"
        add(errors, isinstance(row, dict), f"{label} 必须是对象")
        if isinstance(row, dict):
            add(errors, row.get("round") == index + 1, f"{label}.round 必须连续递增")
            add(errors, has_value(row.get("summary")), f"{label}.summary 不得为空")
            add(errors, has_value(row.get("user_decision")), f"{label}.user_decision 不得为空")
    if status == "needs-reframing":
        add(errors, round_count == 5, "needs-reframing 必须在五轮实质讨论后使用")

    final_idea = data.get("final_idea")
    add(errors, isinstance(final_idea, dict), "final_idea 必须是对象")
    if not isinstance(final_idea, dict):
        final_idea = {}
    for key in (
        "expected_contributions",
        "conditions",
        "boundaries",
        "falsification_conditions",
        "preliminary_acceptance_targets",
    ):
        list_field(errors, final_idea.get(key), f"final_idea.{key}")
    if final:
        final_id = final_idea.get("idea_id")
        add(errors, final_id in selected_ids, "accepted 的 final_idea 必须引用 user_selected 候选")
        add(errors, final_idea.get("user_confirmed") is True, "accepted 要求用户明确确认最终 IDEA")
        for key in (
            "confirmed_at",
            "confirmation_evidence_ref",
            "research_problem",
            "core_hypothesis",
            "expected_contributions",
            "conditions",
            "boundaries",
            "falsification_conditions",
            "preliminary_acceptance_targets",
        ):
            add(errors, has_value(final_idea.get(key)), f"accepted 要求 final_idea.{key}")
        add(errors, isinstance(round_count, int) and 1 <= round_count <= 5, "accepted 要求 1 到 5 轮实质讨论")

    root_blockers = list_field(errors, data.get("blockers"), "blockers")
    if final:
        add(errors, not root_blockers, "accepted 不允许存在根级 blocker")
    if status == "blocked":
        add(errors, bool(root_blockers), "blocked 状态必须说明 blocker")

    return errors


def valid_example() -> dict[str, Any]:
    papers = [
        {
            "paper_id": f"P-{index:03d}",
            "identity_status": "verified",
            "relevance": "direct",
            "within_recency_window": True,
            "evidence_locator": f"Section {index}",
            "counts_toward_minimum": True,
        }
        for index in range(1, 11)
    ]
    candidates = []
    for index in range(1, 6):
        candidates.append(
            {
                "idea_id": f"I-{index:03d}",
                "status": "user_selected" if index == 1 else "audited",
                "research_problem": "可定位问题",
                "core_hypothesis": "可证伪假设",
                "proposed_change": "拟议改动",
                "novelty_boundary": "不提前声称首创",
                "literature_evidence": [
                    {"paper_id": "P-001", "recency": "recent", "locator": "Section 1"},
                    {"paper_id": "P-002", "recency": "anchor", "locator": "Table 2"},
                ],
                "counterevidence": [],
                "existing_solutions": [],
                "falsification_test": "真实评测协议",
                "risks": [],
                "review_verdict": "pass",
            }
        )
    return {
        "schema_version": "1.0",
        "start_id": "START-001",
        "version": 1,
        "status": "accepted",
        "created_at": "2026-07-29T10:00:00+08:00",
        "updated_at": "2026-07-29T11:00:00+08:00",
        "input": {
            "kind": "research_scope",
            "research_scope": "AI 研究范围",
            "seed_paper_refs": [],
            "failure_evidence_ref": None,
            "previous_start_ref": None,
            "reused_candidate_refs": [],
        },
        "literature": {
            "search_cutoff_date": "2026-07-29",
            "recency_window": "2023-07-29 至 2026-07-29",
            "added_papers": papers,
            "qualified_count": 10,
            "registry_ref": ".cvpr/literature/文献注册表.jsonl",
            "problem_status_matrix_ref": ".cvpr/literature/问题状态矩阵.yaml",
        },
        "user_material_check": {
            "status": "not_provided",
            "input_refs": [],
            "findings": [],
            "evidence_refs": [],
        },
        "problem_statuses": [],
        "candidates": candidates,
        "someagents_review": {
            "mode": "B",
            "status": "completed",
            "input_snapshot_id": "START-SNAPSHOT-001",
            "role_results": [
                {
                    "agent_id": "A-1",
                    "independent": True,
                    "status": "completed",
                    "input_snapshot_id": "START-SNAPSHOT-001",
                    "covered_axes": [
                        "source_recency",
                        "problem_evidence",
                        "novelty_related_work",
                    ],
                },
                {
                    "agent_id": "A-2",
                    "independent": True,
                    "status": "completed",
                    "input_snapshot_id": "START-SNAPSHOT-001",
                    "covered_axes": [
                        "method_falsifiability",
                        "feasibility_review_risk",
                    ],
                },
            ],
            "covered_axes": sorted(REQUIRED_AXES),
            "minority_findings": [],
            "unresolved_blockers": [],
            "final_verdict": "pass",
        },
        "discussion": {
            "substantive_rounds": 1,
            "rounds": [{"round": 1, "summary": "候选比较", "user_decision": "选择 I-001"}],
        },
        "final_idea": {
            "idea_id": "I-001",
            "user_confirmed": True,
            "confirmed_at": "2026-07-29T11:00:00+08:00",
            "confirmation_evidence_ref": ".cvpr/decisions.jsonl#D-001",
            "research_problem": "可定位问题",
            "core_hypothesis": "可证伪假设",
            "expected_contributions": ["方法贡献"],
            "conditions": ["成立条件"],
            "boundaries": ["适用边界"],
            "falsification_conditions": ["反证条件"],
            "preliminary_acceptance_targets": ["初步目标"],
        },
        "blockers": [],
        "supersedes": None,
    }


def self_test() -> int:
    base = valid_example()
    cases: list[tuple[str, dict[str, Any], bool]] = [("正例", base, True)]

    too_few_papers = deepcopy(base)
    too_few_papers["literature"]["added_papers"] = too_few_papers["literature"]["added_papers"][:9]
    too_few_papers["literature"]["qualified_count"] = 9
    cases.append(("少于十篇新增论文", too_few_papers, False))

    too_few_candidates = deepcopy(base)
    too_few_candidates["candidates"] = too_few_candidates["candidates"][:4]
    cases.append(("少于五个正式候选", too_few_candidates, False))

    missing_axis = deepcopy(base)
    missing_axis["someagents_review"]["covered_axes"] = sorted(REQUIRED_AXES - {"problem_evidence"})
    cases.append(("审查轴缺失", missing_axis, False))

    too_many_rounds = deepcopy(base)
    too_many_rounds["discussion"]["substantive_rounds"] = 6
    too_many_rounds["discussion"]["rounds"] = [
        {"round": index, "summary": "讨论", "user_decision": "继续"}
        for index in range(1, 7)
    ]
    cases.append(("超过五轮讨论", too_many_rounds, False))

    unconfirmed = deepcopy(base)
    unconfirmed["final_idea"]["user_confirmed"] = False
    cases.append(("最终 IDEA 未确认", unconfirmed, False))

    malformed = deepcopy(base)
    malformed["candidates"] = {}
    cases.append(("字段类型错误", malformed, False))

    failed = False
    for name, payload, should_pass in cases:
        errors = validate_manifest(payload)
        passed = not errors
        if passed != should_pass:
            failed = True
            print(f"FAIL {name}: {errors}")
        else:
            print(f"PASS {name}")
    return 1 if failed else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="校验 .cvpr/start.yaml 研究启动契约")
    parser.add_argument("start_file", nargs="?", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        return self_test()
    if args.start_file is None:
        parser.error("必须提供 start_file，或使用 --self-test")

    try:
        data = json.loads(args.start_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"ERROR: {args.start_file}: {exc}", file=sys.stderr)
        return 1

    errors = validate_manifest(data)
    if errors:
        print("INVALID:")
        for error in errors:
            print(f"- {error}")
        return 1
    print(f"OK: {args.start_file} 研究启动契约有效（状态 {data.get('status')}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

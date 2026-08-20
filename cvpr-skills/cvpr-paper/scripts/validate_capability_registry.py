#!/usr/bin/env python3
"""Validate the cvpr-paper natural-language capability registry."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


EXPECTED_MODES = {"help", "status", "task", "compose", "full-draft"}
EXPECTED_SKILLS = {
    "cvpr-writing",
    "cvpr-citation",
    "cvpr-academic-search",
    "cvpr-paper-analysis",
    "cvpr-statistics",
    "cvpr-figure",
    "cvpr-reproducibility",
    "cvpr-polishing",
    "cvpr-humanizer",
    "cvpr-latex",
    "cvpr-paper-audit",
    "cvpr-reviewer",
    "cvpr-someagents",
    "cvpr-do",
    "cvpr-result",
    "cvpr-plan",
    "cvpr-goal",
    "cvpr-start",
}
KINDS = {"paper-atomic", "support-atomic", "upstream-route"}


def load(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def has_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def main() -> int:
    parser = argparse.ArgumentParser(description="校验 cvpr-paper 能力注册表")
    parser.add_argument("registry")
    args = parser.parse_args()
    path = Path(args.registry)
    errors: list[str] = []
    try:
        data = load(path)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"ERROR: {path}: {exc}", file=sys.stderr)
        return 1

    if not isinstance(data, dict):
        errors.append("根节点必须是对象")
        data = {}
    invocation = data.get("invocation")
    if not isinstance(invocation, dict):
        errors.append("invocation 必须是对象")
        invocation = {}
    if invocation.get("style") != "natural-language":
        errors.append("invocation.style 必须为 natural-language")
    if invocation.get("user_supplied_mode_forbidden") is not True:
        errors.append("必须禁止要求用户输入内部模式")
    modes = invocation.get("internal_modes")
    valid_modes = (
        isinstance(modes, list)
        and all(has_text(mode) for mode in modes)
        and set(modes) == EXPECTED_MODES
        and len(modes) == len(EXPECTED_MODES)
    )
    if not valid_modes:
        errors.append("internal_modes 必须且仅能包含五种内部模式")

    rows = data.get("capabilities")
    if not isinstance(rows, list):
        errors.append("capabilities 必须是数组")
        rows = []
    seen: set[str] = set()
    for index, row in enumerate(rows):
        label = f"capabilities[{index}]"
        if not isinstance(row, dict):
            errors.append(f"{label}: 必须是对象")
            continue
        skill = row.get("skill")
        if not has_text(skill):
            errors.append(f"{label}.skill: 必须是非空字符串")
            continue
        if skill in seen:
            errors.append(f"{label}.skill: 重复 {skill}")
        seen.add(skill)
        if row.get("kind") not in KINDS:
            errors.append(f"{label}.kind: 非法")
        for key in ("intents", "requires", "produces", "forbidden"):
            value = row.get(key)
            if not isinstance(value, list) or not value or not all(has_text(item) for item in value):
                errors.append(f"{label}.{key}: 必须是非空字符串数组")
        if not isinstance(row.get("may_write"), bool):
            errors.append(f"{label}.may_write: 必须是布尔值")
    if seen != EXPECTED_SKILLS:
        errors.append(
            "能力集合不完整：missing="
            + ",".join(sorted(EXPECTED_SKILLS - seen))
            + " extra="
            + ",".join(sorted(seen - EXPECTED_SKILLS))
        )

    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(f"OK: {path} 自然语言能力注册表有效（{len(rows)} 项）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Validate cvpr-skills as one release package."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from urllib.parse import unquote


ROOT = Path(__file__).resolve().parents[1]
EXPECTED_SKILLS = {
    "cvpr-academic-search",
    "cvpr-citation",
    "cvpr-do",
    "cvpr-figure",
    "cvpr-goal",
    "cvpr-humanizer",
    "cvpr-init",
    "cvpr-latex",
    "cvpr-paper",
    "cvpr-paper-analysis",
    "cvpr-paper-audit",
    "cvpr-plan",
    "cvpr-polishing",
    "cvpr-reproducibility",
    "cvpr-result",
    "cvpr-reviewer",
    "cvpr-someagents",
    "cvpr-start",
    "cvpr-statistics",
    "cvpr-writing",
}
ATTRIBUTION = (
    "来源与保留许可：© 小红书用户“非典型在读 Momo”（小红书号：42061669235）。"
    "允许在完整保留本来源行的前提下适度修改和二次使用；任何 AI、Agent、自动化工具或个人"
    "均不得删除、隐藏、改写、截断、弱化或以其他方式移除本来源行，复制、分发及衍生版本"
    "也必须完整保留本行。"
)
FORBIDDEN_FRAGMENTS = {
    "TODO": "残留 TODO",
    "FIXME": "残留 FIXME",
    "TBD": "残留 TBD",
    "nature-": "残留旧 Skill 品牌",
    "Nature 品牌": "残留旧品牌说明",
    "cvpr-resulst": "拼写错误",
    "cvpr-Someagents": "旧大小写品牌",
}
EXTRANEOUS_DOCS = {
    "README.md",
    "INSTALLATION_GUIDE.md",
    "QUICK_REFERENCE.md",
    "CHANGELOG.md",
}
IGNORED_PARTS = {".git", "__pycache__", "node_modules", "dist", "out", "coverage"}


def parse_frontmatter(text: str, label: str, errors: list[str]) -> dict[str, str]:
    match = re.match(r"^---\n(.*?)\n---\n", text, flags=re.DOTALL)
    if not match:
        errors.append(f"{label}: frontmatter 缺失或格式错误")
        return {}
    fields: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if not line.strip():
            continue
        field_match = re.match(r"^([A-Za-z0-9_-]+):\s*(.*)$", line)
        if not field_match:
            errors.append(f"{label}: frontmatter 存在无法解析的行")
            continue
        key, value = field_match.groups()
        fields[key] = value.strip()
    if set(fields) != {"name", "description"}:
        errors.append(f"{label}: frontmatter 必须且只能包含 name 和 description")
    if not fields.get("description"):
        errors.append(f"{label}: description 不得为空")
    return fields


def check_local_links(skill_file: Path, text: str, errors: list[str]) -> None:
    for match in re.finditer(r"\]\(([^)]+)\)", text):
        target = match.group(1).split("#", 1)[0].strip()
        if not target or target.startswith(("http://", "https://", "mailto:", "<")):
            continue
        candidate = (skill_file.parent / unquote(target)).resolve()
        if not candidate.exists():
            errors.append(f"{skill_file.relative_to(ROOT)}: 本地链接不存在：{target}")


def quoted_yaml_value(text: str, key: str) -> str | None:
    match = re.search(rf"^\s*{re.escape(key)}:\s*([\"'])(.*?)\1\s*$", text, flags=re.MULTILINE)
    return match.group(2) if match else None


def check_agent_metadata(skill: str, errors: list[str]) -> None:
    path = ROOT / skill / "agents" / "openai.yaml"
    if not path.is_file():
        errors.append(f"{skill}: 缺少 agents/openai.yaml")
        return
    text = path.read_text(encoding="utf-8")
    display_name = quoted_yaml_value(text, "display_name")
    short_description = quoted_yaml_value(text, "short_description")
    default_prompt = quoted_yaml_value(text, "default_prompt")
    if not display_name:
        errors.append(f"{skill}: display_name 缺失或未使用引号")
    if not short_description or not 25 <= len(short_description) <= 64:
        errors.append(f"{skill}: short_description 必须为 25 到 64 个字符")
    if not default_prompt or f"${skill}" not in default_prompt:
        errors.append(f"{skill}: default_prompt 必须包含 ${skill}")


def package_files() -> list[Path]:
    files: list[Path] = []
    for path in ROOT.rglob("*"):
        if any(part in IGNORED_PARTS for part in path.parts):
            continue
        if path.is_file():
            files.append(path)
    return files


def main() -> int:
    errors: list[str] = []
    actual_skills = {
        path.name
        for path in ROOT.iterdir()
        if path.is_dir() and path.name.startswith("cvpr-")
    }
    if actual_skills != EXPECTED_SKILLS:
        errors.append(
            "Skill 集合不完整：missing="
            + ",".join(sorted(EXPECTED_SKILLS - actual_skills))
            + " extra="
            + ",".join(sorted(actual_skills - EXPECTED_SKILLS))
        )

    for skill in sorted(EXPECTED_SKILLS & actual_skills):
        skill_dir = ROOT / skill
        skill_file = skill_dir / "SKILL.md"
        if not skill_file.is_file():
            errors.append(f"{skill}: 缺少 SKILL.md")
            continue
        text = skill_file.read_text(encoding="utf-8")
        fields = parse_frontmatter(text, f"{skill}/SKILL.md", errors)
        if fields.get("name") != skill:
            errors.append(f"{skill}: frontmatter.name 与目录名不一致")
        if text.count(ATTRIBUTION) != 1:
            errors.append(f"{skill}: 来源与许可行必须完整且只出现一次")
        check_local_links(skill_file, text, errors)
        check_agent_metadata(skill, errors)
        for name in EXTRANEOUS_DOCS:
            if (skill_dir / name).exists():
                errors.append(f"{skill}: 不应包含额外文档 {name}")

    guide = ROOT / "useguide.md"
    if not guide.is_file():
        errors.append("包根目录缺少 useguide.md")
    elif guide.read_text(encoding="utf-8").count(ATTRIBUTION) != 1:
        errors.append("useguide.md 必须完整保留来源与许可行")

    files = package_files()
    for path in files:
        relative = path.relative_to(ROOT)
        if path.suffix == ".py":
            try:
                compile(path.read_text(encoding="utf-8"), str(relative), "exec")
            except (OSError, SyntaxError, UnicodeError) as exc:
                errors.append(f"{relative}: Python 编译失败：{exc}")
        if path.suffix == ".yaml" and "agents" not in path.parts:
            try:
                raw = path.read_text(encoding="utf-8").lstrip()
            except (OSError, UnicodeError) as exc:
                errors.append(f"{relative}: 无法读取：{exc}")
                continue
            if raw.startswith(("{", "[")):
                try:
                    json.loads(raw)
                except json.JSONDecodeError as exc:
                    errors.append(f"{relative}: JSON/YAML 1.2 子集解析失败：{exc}")
        if path.name.endswith((".pyc", ".tmp", "~")):
            errors.append(f"{relative}: 发现临时或缓存文件")

        if (
            path.suffix in {".md", ".yaml", ".py"}
            and relative.parts
            and relative.parts[0].startswith("cvpr-")
        ):
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeError:
                continue
            for fragment, message in FORBIDDEN_FRAGMENTS.items():
                if fragment in text:
                    errors.append(f"{relative}: {message}：{fragment}")

    cache_dirs = [
        path.relative_to(ROOT)
        for path in ROOT.rglob("__pycache__")
        if path.is_dir()
    ]
    for path in cache_dirs:
        errors.append(f"{path}: 发现 Python 缓存目录")

    if errors:
        print("INVALID:")
        for error in errors:
            print(f"- {error}")
        return 1
    print(
        "OK: cvpr-skills 包级结构有效"
        f"（Skill {len(actual_skills)}，文件 {len(files)}，来源许可 {len(actual_skills)}/20）"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

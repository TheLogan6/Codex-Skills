#!/usr/bin/env python3
"""Read-only, repository-agnostic unified-diff summarizer."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional, Sequence


@dataclass
class FileChange:
    path: str
    old_path: str
    status: str
    additions: int = 0
    deletions: int = 0
    binary: bool = False
    category: str = "other"


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(
        description=(
            "Summarize a unified diff without modifying files. Read from --diff-file, "
            "stdin, or a read-only `git diff` invocation."
        )
    )
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--diff-file", help="Unified diff file to read.")
    source.add_argument("--repo", help="Git repository whose diff should be read.")
    parser.add_argument("--base", help="Optional base revision for --repo.")
    parser.add_argument("--head", help="Optional head revision for --repo.")
    parser.add_argument(
        "--staged", action="store_true", help="Summarize the staged diff for --repo."
    )
    parser.add_argument(
        "--format", choices=("json", "markdown"), default="json", help="Output format."
    )
    parser.add_argument(
        "--self-test", action="store_true", help="Run built-in parser checks and exit."
    )
    args = parser.parse_args(argv)
    if (args.base or args.head or args.staged) and not args.repo:
        parser.error("--base, --head, and --staged require --repo")
    if args.staged and (args.base or args.head):
        parser.error("--staged cannot be combined with --base or --head")
    if args.head and not args.base:
        parser.error("--head requires --base")
    return args


def _strip_prefix(path: str) -> str:
    path = path.strip().split("\t", 1)[0]
    if path == "/dev/null":
        return path
    return path[2:] if path.startswith(("a/", "b/")) else path


def classify_path(path: str) -> str:
    """Classify a path for diff-scope review."""
    lowered = path.lower()
    parts = set(Path(lowered).parts)
    name = Path(lowered).name
    if "test" in parts or "tests" in parts or re.search(r"(^|[_\-.])test", name):
        return "test"
    if "benchmark" in parts or "benchmarks" in parts or "bench" in name:
        return "benchmark"
    if parts & {"build", "dist", "generated", "vendor", "third_party"}:
        return "generated-or-vendor"
    if name in {"cmakelists.txt", "makefile", "pyproject.toml", "setup.py"}:
        return "build-config"
    if Path(lowered).suffix in {".md", ".rst", ".txt"} or "docs" in parts:
        return "documentation"
    if Path(lowered).suffix in {
        ".c", ".cc", ".cpp", ".cu", ".cuh", ".h", ".hpp", ".py", ".rs", ".go"
    }:
        return "source"
    if Path(lowered).suffix in {".yaml", ".yml", ".json", ".toml", ".ini", ".cfg"}:
        return "configuration"
    return "other"


def parse_unified_diff(text: str) -> list[FileChange]:
    """Parse file-level statistics without applying the diff."""
    changes: list[FileChange] = []
    current: Optional[FileChange] = None
    in_hunk = False

    def finish() -> None:
        nonlocal current
        if current is not None:
            if current.path == "/dev/null":
                current.path = current.old_path
            current.category = classify_path(current.path)
            changes.append(current)
            current = None

    for line in text.splitlines():
        if line.startswith("diff --git "):
            finish()
            match = re.match(r"diff --git a/(.+) b/(.+)$", line)
            old_path, new_path = (match.group(1), match.group(2)) if match else ("", "")
            current = FileChange(path=new_path, old_path=old_path, status="modified")
            in_hunk = False
        elif current is None:
            continue
        elif line.startswith("new file mode "):
            current.status = "added"
        elif line.startswith("deleted file mode "):
            current.status = "deleted"
        elif line.startswith("rename from "):
            current.old_path = line[len("rename from ") :]
            current.status = "renamed"
        elif line.startswith("rename to "):
            current.path = line[len("rename to ") :]
            current.status = "renamed"
        elif line.startswith("Binary files ") or line == "GIT binary patch":
            current.binary = True
        elif line.startswith("--- "):
            current.old_path = _strip_prefix(line[4:])
            if current.old_path == "/dev/null":
                current.status = "added"
        elif line.startswith("+++ "):
            current.path = _strip_prefix(line[4:])
            if current.path == "/dev/null":
                current.status = "deleted"
        elif line.startswith("@@"):
            in_hunk = True
        elif in_hunk and line.startswith("+") and not line.startswith("+++"):
            current.additions += 1
        elif in_hunk and line.startswith("-") and not line.startswith("---"):
            current.deletions += 1
    finish()
    return changes


def build_summary(changes: list[FileChange]) -> dict:
    """Build a stable machine-readable summary."""
    return {
        "schema_version": 1,
        "read_only": True,
        "totals": {
            "files": len(changes),
            "additions": sum(item.additions for item in changes),
            "deletions": sum(item.deletions for item in changes),
            "binary_files": sum(item.binary for item in changes),
        },
        "by_status": dict(sorted(Counter(item.status for item in changes).items())),
        "by_category": dict(sorted(Counter(item.category for item in changes).items())),
        "files": [asdict(item) for item in changes],
    }


def render_markdown(summary: dict) -> str:
    totals = summary["totals"]
    lines = [
        "# Diff Summary",
        "",
        f"- Files: {totals['files']}",
        f"- Additions: {totals['additions']}",
        f"- Deletions: {totals['deletions']}",
        f"- Binary files: {totals['binary_files']}",
        "",
        "| Status | Category | + | - | Path |",
        "| --- | --- | ---: | ---: | --- |",
    ]
    for item in summary["files"]:
        lines.append(
            f"| {item['status']} | {item['category']} | {item['additions']} | "
            f"{item['deletions']} | `{item['path']}` |"
        )
    return "\n".join(lines) + "\n"


def read_git_diff(args: argparse.Namespace) -> str:
    repo = str(Path(args.repo).expanduser().resolve())
    command = ["git", "-C", repo, "diff", "--no-ext-diff", "--binary"]
    if args.staged:
        command.append("--cached")
    elif args.base:
        command.append(args.base if not args.head else f"{args.base}..{args.head}")
    result = subprocess.run(command, check=False, capture_output=True, text=True)
    if result.returncode:
        raise SystemExit(result.stderr.strip() or "git diff failed")
    return result.stdout


def self_test() -> None:
    sample = """diff --git a/src/a.py b/src/a.py
index 111..222 100644
--- a/src/a.py
+++ b/src/a.py
@@ -1 +1,2 @@
-old
+new
+more
diff --git a/tests/test_a.py b/tests/test_a.py
new file mode 100644
--- /dev/null
+++ b/tests/test_a.py
@@ -0,0 +1 @@
+assert True
"""
    summary = build_summary(parse_unified_diff(sample))
    assert summary["totals"] == {
        "files": 2, "additions": 3, "deletions": 1, "binary_files": 0
    }
    assert summary["by_category"] == {"source": 1, "test": 1}


def main(argv: Optional[Sequence[str]] = None) -> int:
    """CLI entry point."""
    args = parse_args(argv)
    if args.self_test:
        self_test()
        print("self-test: ok")
        return 0
    if args.repo:
        text = read_git_diff(args)
    elif args.diff_file:
        text = Path(args.diff_file).expanduser().read_text(encoding="utf-8")
    elif not sys.stdin.isatty():
        text = sys.stdin.read()
    else:
        raise SystemExit("Provide --repo, --diff-file, or unified diff on stdin.")
    summary = build_summary(parse_unified_diff(text))
    if args.format == "markdown":
        print(render_markdown(summary), end="")
    else:
        json.dump(summary, sys.stdout, ensure_ascii=False, indent=2)
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

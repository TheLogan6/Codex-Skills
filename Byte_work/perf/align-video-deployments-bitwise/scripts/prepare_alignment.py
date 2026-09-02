#!/usr/bin/env python3
"""Create mirrored, isolated bitwise-alignment run directories."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
from typing import Any

_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$")
_SUBDIRS = ("脚本", "output", "结果", "logs", "dumps/encoder", "dumps/dit", "dumps/decode")


def _resolved_directory(value: str) -> Path:
    path = Path(value).expanduser().resolve(strict=True)
    if not path.is_dir():
        raise ValueError(f"not a directory: {path}")
    return path


def _is_nested(left: Path, right: Path) -> bool:
    return left == right or left in right.parents or right in left.parents


def _load_configuration(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("configuration must be a JSON object")
    return data


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--deployment-a", required=True)
    parser.add_argument("--deployment-b", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--config", required=True, help="Canonical generation configuration JSON")
    parser.add_argument("--reference-command", default="")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()

    if not _RUN_ID.fullmatch(args.run_id):
        parser.error("run-id must contain only letters, digits, dot, underscore, or hyphen")

    deployment_a = _resolved_directory(args.deployment_a)
    deployment_b = _resolved_directory(args.deployment_b)
    if _is_nested(deployment_a, deployment_b):
        parser.error("deployment directories must be distinct and non-nested")

    config_source = Path(args.config).expanduser().resolve(strict=True)
    configuration = _load_configuration(config_source)
    configuration_bytes = (json.dumps(configuration, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )
    config_sha256 = hashlib.sha256(configuration_bytes).hexdigest()

    roots = {
        "A": deployment_a / "bitwise对齐" / args.run_id,
        "B": deployment_b / "bitwise对齐" / args.run_id,
    }
    for root in roots.values():
        if root.exists() and not args.resume:
            parser.error(f"run already exists; pass --resume after verifying it: {root}")
        config_path = root / "配置.json"
        if config_path.exists() and config_path.read_bytes() != configuration_bytes:
            parser.error(f"existing configuration differs: {config_path}")

    for label, root in roots.items():
        root.mkdir(parents=True, exist_ok=True)
        for subdir in _SUBDIRS:
            (root / subdir).mkdir(parents=True, exist_ok=True)

        config_path = root / "配置.json"
        config_path.write_bytes(configuration_bytes)
        _write_json(
            root / "环境.json",
            {
                "deployment_label": label,
                "deployment_path": str(deployment_a if label == "A" else deployment_b),
                "reference_command": args.reference_command,
                "canonical_config_sha256": config_sha256,
                "source_config_path": str(config_source),
            },
        )
        record = root / "修改记录.md"
        if not record.exists():
            record.write_text(
                f"# Bitwise 对齐修改记录\n\n- 环境：{label}\n- 配置 SHA-256：`{config_sha256}`\n\n",
                encoding="utf-8",
            )

    print(json.dumps({label: str(path) for label, path in roots.items()}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

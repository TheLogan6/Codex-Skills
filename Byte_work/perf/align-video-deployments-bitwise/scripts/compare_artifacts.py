#!/usr/bin/env python3
"""Compare files or mirrored artifact trees using raw SHA-256 equality."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _files(root: Path) -> dict[str, Path]:
    if root.is_file():
        return {".": root}
    return {str(path.relative_to(root)): path for path in sorted(root.rglob("*")) if path.is_file()}


def _first_byte_difference(left: Path, right: Path) -> int | None:
    offset = 0
    with left.open("rb") as left_stream, right.open("rb") as right_stream:
        while True:
            left_block = left_stream.read(1024 * 1024)
            right_block = right_stream.read(1024 * 1024)
            if left_block == right_block:
                if not left_block:
                    return None
                offset += len(left_block)
                continue
            for index, (left_byte, right_byte) in enumerate(zip(left_block, right_block, strict=False)):
                if left_byte != right_byte:
                    return offset + index
            return offset + min(len(left_block), len(right_block))


def _tensor_diagnostics(left: Path, right: Path) -> dict[str, Any]:
    if left.suffix != ".bin" or right.suffix != ".bin":
        return {}
    left_metadata_path = left.with_suffix(".json")
    right_metadata_path = right.with_suffix(".json")
    if not left_metadata_path.is_file() or not right_metadata_path.is_file():
        return {}

    left_metadata = json.loads(left_metadata_path.read_text(encoding="utf-8"))
    right_metadata = json.loads(right_metadata_path.read_text(encoding="utf-8"))
    result: dict[str, Any] = {
        "left_dtype": left_metadata.get("dtype"),
        "right_dtype": right_metadata.get("dtype"),
        "left_shape": left_metadata.get("shape"),
        "right_shape": right_metadata.get("shape"),
    }
    if result["left_dtype"] != result["right_dtype"] or result["left_shape"] != result["right_shape"]:
        return result

    try:
        import numpy as np
    except ImportError:
        result["numeric_diagnostics"] = "numpy unavailable"
        return result

    dtype_names = {
        "bool": "bool",
        "float16": "float16",
        "float32": "float32",
        "float64": "float64",
        "int8": "int8",
        "int16": "int16",
        "int32": "int32",
        "int64": "int64",
        "uint8": "uint8",
    }
    dtype_name = dtype_names.get(str(result["left_dtype"]))
    if dtype_name is None:
        result["numeric_diagnostics"] = "unsupported dtype; raw comparison remains authoritative"
        return result

    left_array = np.fromfile(left, dtype=np.dtype(dtype_name))
    right_array = np.fromfile(right, dtype=np.dtype(dtype_name))
    if left_array.size != right_array.size:
        result["left_elements"] = int(left_array.size)
        result["right_elements"] = int(right_array.size)
        return result

    mismatches = np.flatnonzero(left_array != right_array)
    if mismatches.size == 0:
        return result
    result["first_differing_element"] = int(mismatches[0])
    if np.issubdtype(left_array.dtype, np.number):
        difference = np.abs(left_array.astype("float64") - right_array.astype("float64"))
        finite = difference[np.isfinite(difference)]
        result["max_abs_difference"] = float(finite.max()) if finite.size else math.nan
        result["mean_abs_difference"] = float(finite.mean()) if finite.size else math.nan
    return result


def compare(left_root: Path, right_root: Path) -> dict[str, Any]:
    left_files = _files(left_root)
    right_files = _files(right_root)
    relative_paths = sorted(set(left_files) | set(right_files))
    entries: list[dict[str, Any]] = []
    all_equal = True

    for relative_path in relative_paths:
        left = left_files.get(relative_path)
        right = right_files.get(relative_path)
        entry: dict[str, Any] = {"path": relative_path}
        if left is None or right is None:
            entry["status"] = "missing_left" if left is None else "missing_right"
            all_equal = False
        else:
            left_hash = _sha256(left)
            right_hash = _sha256(right)
            entry.update(
                {
                    "left_sha256": left_hash,
                    "right_sha256": right_hash,
                    "left_size": left.stat().st_size,
                    "right_size": right.stat().st_size,
                }
            )
            if left_hash == right_hash:
                entry["status"] = "equal"
            else:
                entry["status"] = "different"
                entry["first_differing_byte"] = _first_byte_difference(left, right)
                entry.update(_tensor_diagnostics(left, right))
                all_equal = False
        entries.append(entry)

    return {"bitwise_equal": all_equal, "entries": entries}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("left")
    parser.add_argument("right")
    parser.add_argument("--report", help="Optional JSON report path")
    args = parser.parse_args()

    left = Path(args.left).expanduser().resolve(strict=True)
    right = Path(args.right).expanduser().resolve(strict=True)
    if left.is_dir() != right.is_dir():
        parser.error("both inputs must be files or both must be directories")

    report = compare(left, right)
    serialized = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.report:
        report_path = Path(args.report).expanduser()
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(serialized, encoding="utf-8")
    print(serialized, end="")
    return 0 if report["bitwise_equal"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

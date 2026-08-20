#!/usr/bin/env python3
"""Write a PyTorch tensor as deterministic raw bytes and JSON metadata."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
from typing import Any

_SAFE_NAME = re.compile(r"[^A-Za-z0-9_.-]+")


def _safe_name(name: str) -> str:
    normalized = _SAFE_NAME.sub("_", name).strip("._")
    if not normalized:
        raise ValueError("tensor name becomes empty after normalization")
    return normalized


def dump_tensor(tensor: Any, output_dir: str | Path, name: str, **metadata: Any) -> dict[str, Any]:
    """Dump one tensor without changing the live computation tensor."""
    import torch

    if not isinstance(tensor, torch.Tensor):
        raise TypeError(f"expected torch.Tensor, got {type(tensor).__name__}")

    if tensor.is_cuda:
        torch.cuda.synchronize(tensor.device)
    cpu_tensor = tensor.detach().contiguous().cpu()
    raw = cpu_tensor.view(torch.uint8).numpy().tobytes(order="C")

    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    basename = _safe_name(name)
    data_path = destination / f"{basename}.bin"
    metadata_path = destination / f"{basename}.json"
    digest = hashlib.sha256(raw).hexdigest()

    record: dict[str, Any] = {
        "name": name,
        "dtype": str(cpu_tensor.dtype).removeprefix("torch."),
        "shape": list(cpu_tensor.shape),
        "stride": list(cpu_tensor.stride()),
        "numel": cpu_tensor.numel(),
        "nbytes": len(raw),
        "sha256": digest,
    }
    reserved = set(record).intersection(metadata)
    if reserved:
        raise ValueError(f"metadata cannot replace canonical fields: {sorted(reserved)}")
    record.update(metadata)

    data_path.write_bytes(raw)
    metadata_path.write_text(
        json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return record


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tensor_file", help="A file loadable by torch.load")
    parser.add_argument("output_dir")
    parser.add_argument("name")
    parser.add_argument("--key", help="Dictionary key when tensor_file contains a mapping")
    args = parser.parse_args()

    import torch

    value = torch.load(args.tensor_file, map_location="cpu", weights_only=True)
    if args.key is not None:
        value = value[args.key]
    record = dump_tensor(value, args.output_dir, args.name)
    print(json.dumps(record, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

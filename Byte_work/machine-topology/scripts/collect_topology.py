#!/usr/bin/env python3
"""Read-only, standard-library inventory. JSON to stdout; no GPU workloads."""
import csv
import datetime
import io
import json
import pathlib
import re
import subprocess


def read(path):
    try:
        return pathlib.Path(path).read_text().strip()
    except OSError:
        return None


def command(args):
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=25)
        return {"argv": args, "returncode": p.returncode,
                "stdout": re.sub(r"\x1b\[[0-9;]*m", "", p.stdout), "stderr": p.stderr}
    except (OSError, subprocess.TimeoutExpired) as e:
        return {"argv": args, "error": str(e)}


def main():
    commands = [
        ["lscpu"], ["lscpu", "-e=CPU,NODE,SOCKET,CORE"],
        ["nvidia-smi", "--query-gpu=index,name,uuid,pci.bus_id", "--format=csv,noheader"],
        ["nvidia-smi", "topo", "-m"],
    ] + [["nvidia-smi", "topo", "-p2p", flag] for flag in ("p", "r", "w", "n")]
    raw = [command(args) for args in commands]
    gpu_rows = []
    query = raw[2]
    if query.get("returncode") == 0:
        for row in csv.reader(io.StringIO(query["stdout"]), skipinitialspace=True):
            if len(row) != 4:
                continue
            idx, name, uuid, bus = (v.strip() for v in row)
            domain, busnum, slot = bus.lower().split(":")
            gpu_rows.append({"index": int(idx), "name": name, "uuid": uuid,
                             "bdf": f"{int(domain, 16):04x}:{busnum}:{slot}"})
    attrs = ("class", "vendor", "device", "numa_node", "local_cpulist",
             "current_link_speed", "current_link_width", "max_link_speed", "max_link_width")
    pci = {}
    for p in sorted(pathlib.Path("/sys/bus/pci/devices").glob("*")):
        resolved = p.resolve()
        pci[p.name] = {key: read(p / key) for key in attrs}
        pci[p.name].update({"sysfs_path": str(resolved), "bdf_chain": [
            part for part in resolved.parts if re.fullmatch(r"[0-9a-f]{4}:[0-9a-f]{2}:[0-9a-f]{2}\.[0-7]", part)
        ]})
    rdma = []
    for p in sorted(pathlib.Path("/sys/class/infiniband").glob("*")):
        ports = [{"port": q.name, **{k: read(q / k) for k in ("rate", "link_layer", "state")}}
                 for q in sorted((p / "ports").glob("*"))]
        rdma.append({"name": p.name, "bdf": (p / "device").resolve().name, "ports": ports})
    numa = {p.name: {k: read(p / k) for k in ("cpulist", "meminfo")}
            for p in sorted(pathlib.Path("/sys/devices/system/node").glob("node[0-9]*"))}
    print(json.dumps({"timestamp_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                      "gpu": gpu_rows, "pci": pci, "rdma": rdma, "numa": numa,
                      "commands": raw, "bandwidth_measurements": [],
                      "note": "Link registers are not transfer measurements. Missing values are unknown."},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

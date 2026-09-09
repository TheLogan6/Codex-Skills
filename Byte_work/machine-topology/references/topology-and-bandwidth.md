# Evidence and bandwidth conventions

## Evidence sources

- `lscpu`, `lscpu -e=CPU,NODE,SOCKET,CORE`, node cpulist/meminfo: CPU/NUMA and memory. One socket can expose multiple NUMA nodes.
- `nvidia-smi --query-gpu=index,name,uuid,pci.bus_id --format=csv,noheader`, `topo -m`, optionally `topo -mp`: GPU identity and pairwise path classes. Inspect `--help-query-gpu` before guessing driver-dependent fields.
- `lspci -Dtv` and `lspci -Dvv -s <BDF>` if installed; otherwise sysfs ancestry, class/vendor/device and link attributes. Max link attributes are component capabilities, not proof a board trains to that rate.
- `/sys/class/infiniband/<name>/device`, `ports/*/{rate,link_layer,state}`, and network-device mapping: RDMA function, link type and port rate. Two RDMA functions can share an adapter/link; don't multiply PCIe bandwidth by function count. `link_layer=Ethernet` takes precedence over HDR/NDR wording in the rate string when distinguishing Ethernet from native IB. Active Ethernet alone does not demonstrate a working RoCE workload.
- Vendor hardware documentation for chip identity, hidden topology, maximum switch fabric and socket interconnect. Mark inferred/unknown where absent.

## Matrix semantics

PIX: at most one PCIe bridge. PXB: multiple PCIe bridges without a PCIe host bridge. PHB: traverses PCIe host bridge. NODE: crosses host bridges within one NUMA node. SYS: crosses NUMA nodes over a system interconnect. NV#: bonded NVLinks; the count is not GB/s. The legend's QPI/UPI is an example, not CPU identification. Use actual AMD/Intel/platform evidence.

One physical switch exposes multiple logical ports/bridges; PXB cannot determine chip count. Realpaths give the visible PCI tree, but may not expose package internals or retimers. A parent upstream port and child downstream port within the same switch represent internal forwarding, not automatically an extra external PCIe cable. Port-to-endpoint / downstream-to-next-upstream links can be labelled using their link registers; retain unresolved packaging as a hierarchy.

## PCIe single-direction bounds

For Gen1/2: `GB/s = GT/s × lanes × (8/10) ÷ 8`.
For Gen3/4/5 in conventional non-FLIT mode: `GB/s = GT/s × lanes × (128/130) ÷ 8`.

| Generation | GT/s | x16 encoding-adjusted ceiling, GB/s per direction |
|---|---:|---:|
| Gen1 | 2.5 | 4.000 |
| Gen2 | 5 | 8.000 |
| Gen3 | 8 | 15.754 |
| Gen4 | 16 | 31.508 |
| Gen5 | 32 | 63.015 |

These exclude TLP/DLLP and other transaction overhead; they are not cudaMemcpy results. x8 is half x16 at the same rate. Full duplex permits simultaneous directions; do not quote the bidirectional sum as H2D capacity. Distinguish GB/s (10^9 bytes/s), GiB/s (2^30 bytes/s), Gb/s (bits/s) and GT/s (transfers/s).

Gen6 64 GT/s x16 has a nominal raw bound of 128 GB/s per direction (256 GB/s summed). It uses PAM4/FLIT/FEC; do not apply 128/130 or multiply the specified 64 GT/s by two again. Payload throughput requires accounting for FLIT and packet overhead. Lower-rate FLIT operation also requires its own basis if present.

Ethernet 400 Gb/s ÷ 8 = 50 GB/s raw per direction, before network overhead; 200 Gb/s = 25 GB/s. Network rate and NIC PCIe rate belong on separate edges. GPU memory bandwidth belongs inside GPU nodes, if needed, not on PCIe edges.

## Path interpretation and optional measurement

Local H2D: local DRAM → memory controller/root complex → shared PCIe uplink → switch hierarchy → GPU. Cross-NUMA H2D can additionally consume the socket interconnect. Same-group PCIe P2P can stay below the root when peer access and routing support it. RDMA: registered host memory or supported GPU memory ↔ NIC ↔ network ↔ remote NIC/memory; the CPU may still set up and submit operations.

For actual transfer measurements, use available NVIDIA nvbandwidth or CUDA sample tools after checking version/help. Prefer pinned H2D/D2H with explicit local memory placement, then concurrency tests only when requested and workload conditions allow. P2P needs access/correctness validation as well as timing. RDMA tests need a real remote endpoint and GDR-specific evidence. Report no fabricated numbers when hardware or software is unavailable.

Official references (recheck relevant documentation when extending to new platforms):

- NVIDIA SMI: https://docs.nvidia.com/deploy/nvidia-smi/index.html
- NVIDIA PCIe P2P troubleshooting: https://docs.nvidia.com/deeplearning/nccl/user-guide/docs/troubleshooting/gpu_troubleshooting.html
- NVIDIA Gen5 direction convention: https://developer.nvidia.com/blog/nvidia-hopper-architecture-in-depth/
- PCI-SIG Gen6/FLIT: https://pcisig.com/blog/pcie%C2%AE-60-specification-released-members-double-bandwidth-next-generation-applications
- AMD 9005 socket interconnect: https://www.amd.com/content/dam/amd/en/documents/epyc-technical-docs/tuning-guides/58466-amd-epyc-9005-tg-cloud-datacenter.pdf
- NVIDIA bandwidth tool: https://github.com/NVIDIA/nvbandwidth

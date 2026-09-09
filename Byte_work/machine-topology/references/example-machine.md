# Originating machine — observed 2026-09-08, not a live inventory

Reference image: `/opt/tiger/飞书文档 - 图片.jpeg`. Its visual layout inspired the drawing guide. Its CPU IDs, NIC inventory and UPI/QPI bandwidth are not machine evidence.

Observed CPU: 2 × AMD EPYC 9555, 64 physical cores/socket, 2 threads/core. NUMA0 logical CPUs 0–63,128–191; NUMA1 64–127,192–255. Eight NVIDIA RTX PRO 6000 Blackwell Server Edition GPUs. Socket interconnect should be labelled AMD Infinity Fabric/xGMI; installed-link count and throughput were not measured.

| NUMA | Simplified hierarchy anchor | GPUs (BDF suffix) | Nearby topo NICs / RDMA functions |
|---|---|---|---|
| 0 | 0000:01:00.0 | GPU0 06:00.0; GPU1 09:00.0 | NIC1 mlx5_1 03:00.0; NIC2 mlx5_2 03:00.1 |
| 0 | 0000:82:00.0 | GPU2 87:00.0; GPU3 8a:00.0 | NIC3 mlx5_3 84:00.0; NIC4 mlx5_4 84:00.1 |
| 1 | 0000:97:00.0 | GPU4 9c:00.0; GPU5 9f:00.0 | NIC5 mlx5_5 99:00.0; NIC6 mlx5_6 99:00.1 |
| 1 | 0000:ec:00.0 | GPU6 f1:00.0; GPU7 f4:00.0 | NIC7 mlx5_7 ee:00.0; NIC8 mlx5_8 ee:00.1 |

NIC0/ mlx5_0 (0000:18:00.0) is a separate branch under 15:01.1 → 16:00.0 → 17:00.0; topology places it in NUMA0 proximity. Do not omit it. NIC0 reports 200 Gb/s; NIC1–8 report 400 Gb/s each, all Ethernet and ACTIVE. These are RDMA function/port observations, not a claim of nine physical adapter cards or independent PCIe links. RoCE end-to-end and GDR were not tested.

Detailed GPU0 chain (domain 0000 throughout):

`00:01.1 → 01:00.0 → 02:01.0 → 04:00.0 → 05:00.0 → 06:00.0`

GPU1 shares 00:01.1/01:00.0 then branches through `02:03.0 → 07:00.0 → 08:00.0 → 09:00.0`. The visible switch bridges report PCI ID 15b3:197c and driver pcieport; exact physical chip/package mapping was not established.

## Bandwidth evidence

| Segment | Observed registers | Interpretation |
|---|---|---|
| All eight GPU endpoint links | max 32 GT/s x16; snapshot current 2.5 GT/s x16 | Gen5 x16 capability: 63.015 GB/s/direction encoding-adjusted ceiling; current snapshot Gen1 x16: 4 GB/s/direction ceiling; load state unmeasured |
| CPU→four GPU-group uplinks | Root ports 00:01.1,81:01.1,96:01.1,eb:01.1 and upstream ports 01:00.0,82:00.0,97:00.0,ec:00.0: current/max 32 GT/s x16 | Each group shares a Gen5 x16 uplink, 63.015 GB/s/direction ceiling |
| Intermediate switch downstream→next upstream links | e.g. 02:01.0 and 04:00.0: current/max 64 GT/s x16 | Reported Gen6 x16, 128 GB/s/direction raw nominal; distinct accounting basis, physical packaging unknown |
| GPU-near NIC functions | 03/84/99/ee :00.0 and :00.1: current/max 64 GT/s x16 | Multifunction reports must not be counted as two independent x16 links |
| NIC0 endpoint | current/max 32 GT/s x16 | Gen5 x16, separate root branch |

No H2D, D2H, P2P or RDMA payload throughput was measured. Idle power saving is a possible reason for GPU link downshift, not a confirmed diagnosis. Do not advertise 63 GB/s as achieved H2D.

For a pair at full Gen5 capability, two concurrent local H2D transfers share at most ~63 GB/s/direction on their common uplink (before additional limitations). About 31.5 GB/s each is only an equal-share illustration. Faster intermediate links do not remove that common CPU uplink limit.

`topo -p2p p` and `r` returned OK for all distinct GPU pairs. `n` returned NS. This demonstrates the driver's PCIe/read capability report and lack of reported NVLink P2P, not tested transfer performance. An earlier explanation incorrectly treated `n=NS` as PCIe P2P failure; do not reproduce that error.

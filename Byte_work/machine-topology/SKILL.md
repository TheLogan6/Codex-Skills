---
name: machine-topology
description: Inspect server CPU/NUMA, GPU, PCIe switch and NIC topology; explain H2D, P2P and RDMA paths and produce complete, evidence-backed architecture diagrams with per-link bandwidth labels. Use for machine topology analysis, nvidia-smi topo interpretation, or drawing GPU server interconnects from measurements or references.
---

# Machine topology: evidence → explanation → diagram

Default to the user's language. Produce an understandable architecture diagram and a short explanation of data paths and bottlenecks. A reference image supplies visual conventions, not hardware facts.

## Collect and establish the hardware graph

Run `python3 <skill-dir>/scripts/collect_topology.py` for a read-only JSON snapshot. Retain its timestamp, raw command outputs, PCI BDF ancestry, link attributes, NUMA data and RDMA ports with the deliverable. The script does not benchmark or change system settings. Missing tools and inaccessible attributes remain explicit unknowns.

For topology decoding and bandwidth calculation, read [references/topology-and-bandwidth.md](references/topology-and-bandwidth.md). Read [references/drawing.md](references/drawing.md) before drawing. For a worked example based on the originating machine, read [references/example-machine.md](references/example-machine.md); do not reuse its measurements on a different host or present it as a fresh snapshot.

Build nodes for socket/root complex, NUMA memory, PCIe bridge hierarchy, GPU endpoints and relevant NIC functions/ports. Map GPU index → UUID/BDF and NIC legend → RDMA device → BDF. Recover ancestry from `/sys/bus/pci/devices/<BDF>` realpaths, not matrix proximity alone. NUMA node and CPU socket are distinct concepts; use CPU topology to map them. CPU affinity lists are logical CPU IDs, not physical-core counts.

Preserve intermediate PCIe bridges in a detailed evidence view. A simplified view may collapse them into a box explicitly labelled “PCIe switch hierarchy (simplified)” with BDF anchors. A logical bridge is not necessarily a separate switch chip. Do not invent switch chip count/model, retimers or wiring from PXB. Count shared links once rather than counting both link-end registers or multiple PCI functions as independent bandwidth.

## Bandwidth is part of the diagram, not an afterthought

Every GPU–PCIe connection and every CPU–switch uplink needs a label containing protocol, generation, width, direction convention and bandwidth basis. Show unknown fields as unknown. Record maximum supported capability separately from current negotiated state. Idle downshift is a possible explanation, not proof of faulty wiring or full-speed operation under load.

Use single-direction decimal GB/s by default. Label all numbers as raw line rate, encoding-adjusted ceiling, or measured payload throughput. Never mix these bases silently. Do not label PCIe 6 with the Gen3–5 encoding formula. For Gen6, use a clearly labelled raw nominal bound unless FLIT overhead and traffic assumptions have been established.

For an H2D path, identify each traversed segment and the shared uplink; end-to-end throughput is bounded by the minimum segment capacity and can be lower due to memory, DMA, protocol and contention. H2D uses the same GPU–switch link as other traffic. For concurrent transfers, show aggregate shared-uplink capacity; equal bandwidth division is only an illustrative assumption, never a measured guarantee.

Topology/status queries do not measure bandwidth. When the request needs actual throughput, use an available benchmark with documented options after inspecting its help. Record GPU selection, pinned/pageable memory, NUMA binding and first-touch placement, direction, size, iterations, concurrency and units. Check current GPU activity before scheduling load. Do not reset GPUs, alter clocks/ACS/IOMMU, install drivers or launch prolonged saturation tests as routine inspection. If measurements cannot be run, finish the topology with measured-throughput fields explicitly “not measured”.

## Explain paths and capability independently

Explain local H2D, same-group GPU P2P, cross-NUMA traffic and GPU↔NIC RDMA when present. Use separate path overlays or small companion diagrams if overlaying them would clutter the hardware graph.

`topo -p2p n` checks NVLink; `p` checks PCIe, `r/w` check peer read/write. NVLink NS does not establish PCIe P2P failure. Driver OK is capability evidence, not proof of application transfer correctness, bandwidth, or actual routing. GPUDirect RDMA requires its own software/configuration evidence; GPU–GPU P2P status does not establish it.

## Deliver and review

Deliver a short Chinese explanation by default, a rendered diagram plus editable source (SVG, DOT or Mermaid), and a per-link bandwidth/evidence table. Prefer deterministic vector drawing for accurate labels and editable topology. Use the supplied Mermaid scaffold when a renderer is available, or author SVG directly when it is not; inspect the rendered result before delivery. Do not require an image-generation service for technical topology.

Check all observed GPUs and NIC functions appear exactly once or are explicitly grouped; memory, root complexes, uplinks and socket interconnect are shown; simplified bridges are labelled; no unattested CPU model/interconnect/rate is copied from the reference; units and direction are consistent; the smallest H2D segment and contention domain are visible; unknowns and snapshot date remain visible. Check legibility, crossings and clipping at normal display size. Explain any corrections to prior claims candidly.

# Drawing technique learned from the supplied reference

The original image uses nested NUMA rectangles, CPU centred above a branching PCIe tree, peer GPUs/NICs on one baseline, generous white space and a clearly isolated inter-socket connection. Reuse this visual grammar rather than the example's device counts, core IDs, QPI label or speculative 20–40 GB/s.

## Composition

1. Give each NUMA domain a consistent outer container. Place socket/root complex at the top, local DRAM beside it, switch hierarchy underneath, GPUs and NICs on the bottom row. If multiple NUMA domains share a socket, show that socket ownership explicitly.
2. Use orthogonal links and aligned peer boxes. Keep the switch uplink visible before fan-out; label each independent uplink so shared capacity is evident. Do not connect GPUs merely by placing them in a group box.
3. Label GPU nodes with index and BDF; add model once in the title if common. Label NIC functions with topo index, mlx5 name and BDF, with ports grouped where physical identity is known. Keep standalone NICs outside GPU groups but within their correct NUMA/root branch.
4. Place CPU–CPU interconnect between domain containers, with type and rate only when known. Place the external network outside the server border; do not invent remote hosts or a network-switch model. Use a labelled network stub when remote topology is unknown.
5. Use a quiet palette: blue CPU/DRAM, amber PCIe, green GPU, purple NIC/network, grey unknowns. Text labels carry meaning even in monochrome. Solid lines mean observed topology; dashed links mean conditional transfer paths or unresolved connections, differentiated in the legend.

## Labels that must fit

Use a two-line edge label such as `PCIe Gen5 x16 (max capability)` / `63.0 GB/s/direction ceiling; payload unmeasured`. Put current downshift details in a callout if repeating them would clutter the drawing. Do not use `PCIe 128 GB/s` without a direction/basis. Gen6 links should say `128 GB/s/direction raw nominal` rather than compare silently to Gen5 encoding-adjusted numbers.

Separate physical topology and traffic explanations. A companion local-H2D arrow chain is usually clearer than four competing coloured arrows on one topology. Place detailed BDF ancestry in a table or second panel when the reference-style overview collapses bridges.

## Output and QA

Default deliverables: editable `.svg` plus preview, or `.mmd`/`.dot` plus rendered SVG/PNG. Mermaid is sufficient when its renderer preserves labels; use hand-authored SVG or Graphviz for denser layouts. Do not pass exact PCI IDs, bandwidth labels or geometry to a generative bitmap model as the sole factual artifact.

Start from [../assets/topology-template.mmd](../assets/topology-template.mmd), replacing example IDs/rates and duplicating groups only from evidence. Check renderer output for unsupported labels, crossings, overlapping edge text, tiny captions, clipping and missing nodes. Keep numerical caveats visible on the image itself, not just in surrounding prose. The template is a compositional scaffold, not a description of any machine.

#!/usr/bin/env python3
"""Auditable, device-independent Roofline arithmetic and plots; no GPU access."""
import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
import statistics
import sys
import textwrap
import warnings


def number(value, name, zero=False, integer=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name}: expected a number")
    if not math.isfinite(value) or value < 0 or (value == 0 and not zero):
        raise ValueError(f"{name}: expected finite {'nonnegative' if zero else 'positive'} value")
    if integer and int(value) != value:
        raise ValueError(f"{name}: expected integer")
    return value


def required_text(obj, key):
    value = obj.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key}: nonempty string required")
    return value


def choice(obj, key, values):
    value = required_text(obj, key)
    if value not in values:
        raise ValueError(f"{key}: expected one of {sorted(values)}")
    return value


def unique(items, label):
    if not isinstance(items, list) or not items:
        raise ValueError(f"{label}: nonempty list required")
    result = {}
    for item in items:
        if not isinstance(item, dict):
            raise ValueError(f"{label}: each item must be an object")
        key = required_text(item, "id")
        if key in result:
            raise ValueError(f"{label}: duplicate id {key}")
        result[key] = item
    return result


def work_count(work):
    """Count one invocation. Caller audits whether work is useful or executed."""
    kind = work.get("kind")
    if kind == "explicit":
        required_text(work, "derivation")
        return number(work.get("operations"), "operations", zero=True)
    if kind == "gemm":
        return (2 * number(work.get("m"), "m", integer=True)
                * number(work.get("n"), "n", integer=True)
                * number(work.get("k"), "k", integer=True)
                * number(work.get("batch", 1), "batch", integer=True))
    if kind == "grouped_gemm":
        groups = work.get("groups")
        if not isinstance(groups, list) or not groups:
            raise ValueError("groups: nonempty list required; repeated shapes use count")
        total = 0
        for group in groups:
            total += (2 * number(group.get("m"), "m", zero=True, integer=True)
                      * number(group.get("n"), "n", integer=True)
                      * number(group.get("k"), "k", integer=True)
                      * number(group.get("count", 1), "count", integer=True))
        return total
    if kind == "block_sparse_attention":
        # pairs already includes all heads/batches; only QK and PV counted.
        return (2 * number(work.get("pairs"), "pairs", zero=True, integer=True)
                * number(work.get("bq"), "bq", integer=True)
                * number(work.get("bk"), "bk", integer=True)
                * (number(work.get("dk"), "dk", integer=True)
                   + number(work.get("dv"), "dv", integer=True)))
    if kind == "elementwise":
        return (number(work.get("elements"), "elements", zero=True, integer=True)
                * number(work.get("ops_per_element"), "ops_per_element", zero=True))
    raise ValueError(f"unsupported work kind: {kind}; use explicit with a derivation")


def traffic_count(model):
    """All ledger values are byte traffic, not tensor allocation sizes."""
    ledger = model.get("ledger")
    if not isinstance(ledger, list) or not ledger:
        raise ValueError("ledger: nonempty list required")
    total = 0
    for entry in ledger:
        required_text(entry, "name")
        if "bytes" in entry:
            if any(k in entry for k in ("elements", "storage_bits", "reads", "writes")):
                raise ValueError("ledger: use explicit bytes OR elements/bits/reads/writes")
            amount = number(entry["bytes"], "bytes", zero=True)
        else:
            elements = number(entry.get("elements"), "elements", zero=True, integer=True)
            bits = number(entry.get("storage_bits"), "storage_bits", integer=True)
            reads = number(entry.get("reads", 0), "reads", zero=True)
            writes = number(entry.get("writes", 0), "writes", zero=True)
            amount = elements * bits / 8 * (reads + writes)
        total += amount
    return number(total, "total traffic", zero=True)


def percentile(values, fraction):
    values = sorted(values)
    index = (len(values) - 1) * fraction
    low = math.floor(index)
    high = math.ceil(index)
    return values[low] + (values[high] - values[low]) * (index - low)


def analyze(data):
    if data.get("schema_version") != 1:
        raise ValueError("schema_version must be 1")
    required_text(data, "title")
    required_text(data, "device")
    roofs = unique(data.get("roofs"), "roofs")
    cases = unique(data.get("cases"), "cases")
    for roof in roofs.values():
        for field in ("label", "path", "layer", "source"):
            required_text(roof, field)
        choice(roof, "op_kind", {"float", "integer", "instruction"})
        choice(roof, "kind", {"spec", "calibrated"})
        number(roof.get("compute_tops"), "compute_tops")
        number(roof.get("bandwidth_gbps"), "bandwidth_gbps")
    rows = []
    for case in cases.values():
        for field in ("label", "path", "timing_source", "cache_policy", "scope"):
            required_text(case, field)
        choice(case, "op_kind", {"float", "integer", "instruction"})
        choice(case, "work_basis", {"useful", "executed"})
        samples = case.get("time_ms")
        if not isinstance(samples, list) or not samples:
            raise ValueError("time_ms: nonempty list of per-invocation samples required")
        samples = [number(v, "time_ms") for v in samples]
        timing_kind = choice(case, "timing_kind", {"measured", "derived", "synthetic"})
        fraction = case.get("e2e_fraction")
        if fraction is not None:
            number(fraction, "e2e_fraction", zero=True)
            if fraction > 1:
                raise ValueError("e2e_fraction must be within [0,1]")
            required_text(case, "e2e_fraction_source")
        f = work_count(case["work"])
        median = statistics.median(samples)
        t = median / 1000
        p10 = percentile(samples, .1)
        p90 = percentile(samples, .9)
        ids = case.get("roof_ids")
        if not isinstance(ids, list) or not ids or len(set(ids)) != len(ids):
            raise ValueError("roof_ids: nonempty list of unique roof ids required")
        if any(i not in roofs for i in ids):
            raise ValueError(f"unknown roof id in {ids}")
        models = unique(case.get("byte_models"), "byte_models")
        for model in models.values():
            required_text(model, "source")
            required_text(model, "layer")
            choice(model, "kind", {"modeled", "measured"})
            q = traffic_count(model)
            matched = [roofs[i] for i in ids if roofs[i]["layer"] == model["layer"]]
            if not matched:
                raise ValueError(f"no same-layer roof for {case['id']}/{model['id']}")
            for roof in matched:
                if roof["path"] != case["path"] or roof["op_kind"] != case["op_kind"]:
                    raise ValueError(f"compute path/op_kind mismatch: {case['id']}/{roof['id']}")
                p = roof["compute_tops"] * 1e12
                b = roof["bandwidth_gbps"] * 1e9
                if f == 0 and q == 0:
                    raise ValueError("zero work and zero traffic: no Roofline model")
                ai = f / q if q else None
                ridge = p / b
                ratio = ai / ridge if ai is not None else None
                achieved = f / t
                memory_roof = b * ai if ai is not None else None
                limit = min(p, memory_roof) if memory_roof is not None else p
                lower = max(f / p, q / b)
                utilization = lower / t
                issues = []
                if utilization > 1.01:
                    issues.append("above_roof: reconcile units, cache, work and roof; no speedup claim")
                if model["kind"] == "modeled":
                    issues.append("modeled_traffic: Q/t is not measured memory bandwidth")
                if timing_kind != "measured":
                    issues.append(f"{timing_kind}_timing: not a new hardware measurement")
                if len(samples) < 5:
                    issues.append("few_samples: insufficient repeatability evidence")
                if (p90 - p10) / median > .1:
                    issues.append("timing_variation: p10-p90 exceeds 10% of median")
                if roof["kind"] == "spec":
                    issues.append("spec_roof: sustained calibration not supplied for this row")
                if f == 0:
                    region = "bandwidth_only"
                    issues.append("zero_operations: excluded from logarithmic FLOP/OP plot")
                elif q == 0:
                    region = "compute_only"
                    issues.append("zero_traffic: no finite AI; inspect residency and counter scope")
                else:
                    region = "memory_side" if ratio < 1 else "compute_side"
                valid = utilization <= 1.01
                speedup = t / lower if utilization <= 1 else None
                row = {
                    "case_id": case["id"], "case_label": case["label"],
                    "roof_id": roof["id"], "roof_label": roof["label"],
                    "roof_kind": roof["kind"], "roof_source": roof["source"],
                    "path": case["path"], "op_kind": case["op_kind"],
                    "work_basis": case["work_basis"], "scope": case["scope"],
                    "cache_policy": case["cache_policy"], "timing_kind": timing_kind,
                    "timing_source": case["timing_source"], "byte_model_id": model["id"],
                    "bytes_kind": model["kind"], "bytes_source": model["source"],
                    "layer": model["layer"], "operations": f, "traffic_bytes": q,
                    "samples": len(samples), "median_ms": median, "p10_ms": p10,
                    "p90_ms": p90, "min_ms": min(samples), "max_ms": max(samples),
                    "compute_peak_tops": p / 1e12, "bandwidth_peak_gbps": b / 1e9,
                    "ai_ops_per_byte": ai, "ridge_ops_per_byte": ridge, "ridge_ratio": ratio,
                    "theoretical_region": region,
                    "near_ridge": ratio is not None and .5 <= ratio <= 2,
                    "achieved_tops": achieved / 1e12,
                    "achieved_p10_tops": f / (p90 / 1000) / 1e12,
                    "achieved_p90_tops": f / (p10 / 1000) / 1e12,
                    "effective_bandwidth_gbps": q / t / 1e9,
                    "roof_tops": limit / 1e12 if f else None,
                    "compute_utilization": achieved / p,
                    "bandwidth_utilization": q / t / b,
                    "roof_utilization": utilization,
                    "gap_fraction": 1 - utilization,
                    "lower_bound_ms": lower * 1000,
                    "fixed_work_speedup_ceiling": speedup,
                    "fixed_work_saving_ms": max(0, median - lower * 1000) if speedup else None,
                    "e2e_speedup_ceiling": (1 / (1 - fraction + fraction / speedup)
                                            if fraction is not None and speedup else None),
                    "status": "consistent_model" if valid else "inconsistent_model",
                    "actual_bottleneck": "unconfirmed_requires_counters_and_experiments",
                    "warnings": issues,
                }
                # Same-work/same-boundary invariant, also valid for zero-work cases.
                if not math.isclose(utilization, max(row["compute_utilization"],
                                                     row["bandwidth_utilization"]), rel_tol=1e-12):
                    raise ValueError("internal unit consistency failure")
                rows.append(row)
    return rows


def format_value(value):
    return "N/A" if value is None else f"{value:.5g}"


def markdown(data, rows):
    lines = [f"# {data['title']}", "", f"Device: {data['device']}", "",
             "This is a calculation report. Theoretical region is not proof of the actual bottleneck.",
             "FMA/MAC = 2 ops. Decimal SI units. Integer rates are TOP/s; float rates TFLOP/s.",
             "Modeled Q/time is modeled effective bandwidth, not a hardware counter measurement.", "",
             "| Case / bytes / roof | AI | r | T op/s | Ucompute | Ubandwidth | Uroof | lower ms | ideal x |",
             "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for r in rows:
        name = f"{r['case_id']} / {r['byte_model_id']} / {r['roof_id']}".replace("|", "/")
        vals = [r[k] for k in ("ai_ops_per_byte", "ridge_ratio", "achieved_tops",
                              "compute_utilization", "bandwidth_utilization", "roof_utilization",
                              "lower_bound_ms", "fixed_work_speedup_ceiling")]
        lines.append(f"| {name} | " + " | ".join(format_value(v) for v in vals) + " |")
    lines += ["", "Utilizations are fractions (0.13 = 13%). Ideal x assumes fixed F/Q and selected roofs.",
              "Speedup is withheld for above-roof values; plotted values are never clipped to 100%."]
    for r in rows:
        lines += ["", f"## {r['case_id']} / {r['byte_model_id']} / {r['roof_id']}", "",
                  f"- Model: {r['theoretical_region']}; near ridge: {r['near_ridge']}; {r['status']}.",
                  f"- Work: {r['operations']:.9g} {r['op_kind']} ops ({r['work_basis']}); traffic: {r['traffic_bytes']:.9g} B ({r['bytes_kind']}, {r['layer']}).",
                  f"- Time: median {r['median_ms']:.7g} ms, p10/p90 {r['p10_ms']:.7g}/{r['p90_ms']:.7g} ms, n={r['samples']}, {r['timing_kind']}.",
                  f"- Scope/cache: {r['scope']} / {r['cache_policy']}.",
                  f"- Timing source: {r['timing_source']}", f"- Bytes source: {r['bytes_source']}",
                  f"- Roof source: {r['roof_source']}",
                  f"- Effective bandwidth: {r['effective_bandwidth_gbps']:.7g} GB/s ({r['bytes_kind']} traffic).",
                  f"- Conditional saving: {format_value(r['fixed_work_saving_ms'])} ms; E2E ideal x: {format_value(r['e2e_speedup_ceiling'])}.",
                  "- Actual bottleneck: unconfirmed; add counter/timeline evidence and a falsifiable experiment."]
        lines += [f"- Note: {v}" for v in r["warnings"]]
    lines += ["", "## Analyst completion", "",
              "Add the observed limiter and confidence, counter/timeline evidence, minimal perturbation experiment,",
              "correctness criteria, practical benefit/cost, and missing evidence. Do not upgrade this numerical",
              "report into a measured bottleneck diagnosis without supporting observations.", ""]
    return "\n".join(lines)


def plot_results(data, rows, output):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib import font_manager
        import numpy as np
        from PIL import Image
    except ImportError as error:
        raise RuntimeError("Plot requires matplotlib, numpy, Pillow; use --no-plot or install in your chosen environment") from error
    # No unrelated style-package dependency; retain portable vector output.
    fonts = {f.name for f in font_manager.fontManager.ttflist}
    candidates = ["Noto Sans CJK SC", "Source Han Sans SC", "PingFang SC", "Heiti SC", "SimHei"]
    cjk = next((f for f in candidates if f in fonts), None)
    plt.rcParams.update({"font.family": [cjk, "DejaVu Sans"] if cjk else ["DejaVu Sans"],
                         "font.size": 10, "pdf.fonttype": 42, "svg.fonttype": "none",
                         "axes.unicode_minus": False})
    colors = ["#0072B2", "#D55E00", "#009E73", "#CC79A7", "#E69F00", "#56B4E9"]
    markers = ["o", "s", "^", "D", "v", "P"]
    audit = {"status": "programmatic_pass", "human_visual_review": "required",
             "figures": [], "excluded": []}
    by_roof = {}
    for r in rows:
        if not r["operations"] or not r["traffic_bytes"]:
            audit["excluded"].append({"case": r["case_id"], "reason": r["theoretical_region"]})
        else:
            by_roof.setdefault(r["roof_id"], []).append(r)
    for roof_index, (_, group) in enumerate(by_roof.items(), 1):
        # Split dense collections; identifiers live in side panels, not colliding annotations.
        for offset in range(0, len(group), 3):
            chunk = group[offset:offset + 3]
            roof = chunk[0]
            fig, (ax, info) = plt.subplots(1, 2, figsize=(11, 6.2),
                                          gridspec_kw={"width_ratios": [1.9, 1]}, layout="constrained")
            info.set_axis_off()
            p, b = roof["compute_peak_tops"], roof["bandwidth_peak_gbps"] / 1000
            ridge = roof["ridge_ops_per_byte"]
            xs = [r["ai_ops_per_byte"] for r in chunk] + [ridge]
            xmin, xmax = min(xs) / 12, max(xs) * 8
            x = np.geomspace(xmin, xmax, 400)
            ax.loglog(x, np.minimum(p, b*x), color="#222222", lw=1.9, label="Matched roof")
            ax.axvline(ridge, color="#666666", ls="--", lw=1, label=f"Ridge: {ridge:.3g}")
            ys = [p, b*xmin] + [r["achieved_p10_tops"] for r in chunk]
            ymax = max([p] + [r["achieved_p90_tops"] for r in chunk]) * 2
            ax.set(xlim=(xmin, xmax), ylim=(min(ys)*.65, ymax))
            kind = roof["op_kind"]
            unit = {"float": "FLOP", "integer": "OP", "instruction": "instruction"}[kind]
            ax.set_xlabel(f"Arithmetic intensity ({unit}/byte, log scale)")
            ax.set_ylabel(f"Achieved performance (T{unit}/s, log scale)")
            ax.grid(True, which="major", alpha=.18)
            ax.set_title(textwrap.fill(f"{data['device']} | {roof['path']} | {roof['layer']}", 65), fontsize=11)
            ax.legend(loc="upper left", fontsize=8, frameon=False)
            heading = f"{roof['roof_label']} ({roof['roof_kind']})\nCompute {p:g} T{unit}/s\nBandwidth {b:g} TB/s"
            info.text(0, .99, textwrap.fill(heading.splitlines()[0], 35) + "\n" + "\n".join(heading.splitlines()[1:]),
                      va="top", fontsize=10, transform=info.transAxes)
            y = .77
            for index, r in enumerate(chunk):
                label = f"{offset + index + 1}"
                ai, perf = r["ai_ops_per_byte"], r["achieved_tops"]
                c, marker = colors[index], markers[index]
                ax.vlines(ai, min(perf, r["roof_tops"]), max(perf, r["roof_tops"]), color=c, ls=":", lw=.9)
                ax.errorbar(ai, perf, yerr=[[perf-r["achieved_p10_tops"]], [r["achieved_p90_tops"]-perf]],
                            fmt=marker, ms=7, color=c, capsize=3, markeredgecolor="black", markeredgewidth=.4)
                ax.annotate(label, (ai, perf), xytext=(8, 7 + 9*(index % 2)), textcoords="offset points", fontsize=8)
                text = (f"{label}. {r['case_label']}\n{r['byte_model_id']} ({r['bytes_kind']})\n"
                        f"{r['work_basis']} work; {r['timing_kind']} time\n"
                        f"AI {ai:.4g}; {perf:.4g} T{unit}/s\n"
                        f"Uroof {r['roof_utilization']:.1%}; r {r['ridge_ratio']:.3g}")
                # Use short labels; wrap long names and reserve fixed vertical bands.
                lines = []
                for line in text.splitlines():
                    lines.extend(textwrap.wrap(line, 37) or [""])
                info.text(0, y, "\n".join(lines), va="top", fontsize=8.5, color=c, transform=info.transAxes)
                y -= max(.115, len(lines)*.029 + .027)
            fig.suptitle(textwrap.fill(data["title"], 95), fontsize=12)
            caption = "Bars: p10-p90 time mapped to throughput; single sample has no variability estimate."
            caption += "\nModeled traffic and derived/synthetic timing are assumptions, not new GPU measurements."
            fig.supxlabel(caption, fontsize=8)
            stem = f"roofline-{roof_index:02d}-{offset//3+1:02d}"
            entry = {"stem": stem, "issues": []}
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                fig.canvas.draw()
                renderer = fig.canvas.get_renderer()
                box = fig.bbox
                texts = [fig._suptitle, fig._supxlabel, ax.title, ax.xaxis.label, ax.yaxis.label]
                texts += list(info.texts) + list(ax.texts)
                for label in texts:
                    if label is None or not label.get_visible():
                        continue
                    extent = label.get_window_extent(renderer)
                    if extent.x0 < box.x0-1 or extent.y0 < box.y0-1 or extent.x1 > box.x1+1 or extent.y1 > box.y1+1:
                        entry["issues"].append("text_outside_canvas: " + label.get_text()[:80])
                side = [label.get_window_extent(renderer) for label in info.texts]
                if any(a.overlaps(bbox) for i, a in enumerate(side) for bbox in side[i+1:]):
                    entry["issues"].append("side_panel_text_overlap: shorten labels or split cases")
                for axis in (ax.xaxis, ax.yaxis):
                    ticks = [v.get_window_extent(renderer) for v in axis.get_ticklabels() if v.get_visible()]
                    if any(a.overlaps(bb) for i, a in enumerate(ticks) for bb in ticks[i+1:]):
                        entry["issues"].append("tick_label_overlap")
                fig.savefig(output / f"{stem}.png", dpi=300)
                for suffix in ("svg", "pdf"):
                    fig.savefig(output / f"{stem}.{suffix}")
                for warning in caught:
                    if "Glyph" in str(warning.message) or "layout" in str(warning.message):
                        entry["issues"].append(str(warning.message))
            with Image.open(output / f"{stem}.png") as im:
                im.convert("L").save(output / f"{stem}-grayscale.png", dpi=(300, 300))
            plt.close(fig)
            entry["issues"] = sorted(set(entry["issues"]))
            if entry["issues"]:
                audit["status"] = "needs_revision"
            audit["figures"].append(entry)
    return audit


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--no-plot", action="store_true")
    parser.add_argument("--strict", action="store_true", help="fail on above-roof or programmatic plot issues")
    parser.add_argument("--overwrite", action="store_true", help="replace files in this report output directory")
    args = parser.parse_args()
    try:
        raw = args.input.read_bytes()
        data = json.loads(raw)
        rows = analyze(data)
        if args.output_dir.exists() and any(args.output_dir.iterdir()) and not args.overwrite:
            raise ValueError("output directory is nonempty; choose a new one or explicitly --overwrite")
        args.output_dir.mkdir(parents=True, exist_ok=True)
        payload = {"schema_version": 1, "input_sha256": hashlib.sha256(raw).hexdigest(),
                   "input": data, "results": rows}
        (args.output_dir / "metrics.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False) + "\n")
        with (args.output_dir / "metrics.csv").open("w", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=list(rows[0]))
            writer.writeheader()
            for row in rows:
                writer.writerow({k: json.dumps(v, ensure_ascii=False) if isinstance(v, list) else v for k, v in row.items()})
        (args.output_dir / "report.md").write_text(markdown(data, rows))
        failed = any(r["status"] == "inconsistent_model" for r in rows)
        if not args.no_plot:
            audit = plot_results(data, rows, args.output_dir)
            (args.output_dir / "plot_qa.json").write_text(json.dumps(audit, indent=2, ensure_ascii=False) + "\n")
            failed |= audit["status"] != "programmatic_pass"
        print(json.dumps({"rows": len(rows), "output_dir": str(args.output_dir),
                          "model_or_plot_issues": failed, "human_visual_review": "required" if not args.no_plot else "not_plotted"}))
        return 2 if args.strict and failed else 0
    except (ValueError, KeyError, TypeError, OSError, RuntimeError, OverflowError) as error:
        print(f"roofline: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

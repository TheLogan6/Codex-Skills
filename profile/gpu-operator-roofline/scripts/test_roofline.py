"""Behavioral regressions for accounting, roof selection and diagnostic limits."""
import copy
import json
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from roofline import analyze, traffic_count, work_count


ROOT = Path(__file__).resolve().parents[1]


class RooflineTests(unittest.TestCase):
    def setUp(self):
        self.data = json.loads((ROOT / "examples/synthetic_portable.json").read_text())

    def test_memory_case_and_amdahl(self):
        r = analyze(self.data)[0]
        self.assertAlmostEqual(r["traffic_bytes"], 12e6)
        self.assertAlmostEqual(r["ai_ops_per_byte"], 1/12)
        self.assertAlmostEqual(r["compute_utilization"], .0005)
        self.assertAlmostEqual(r["bandwidth_utilization"], .6)
        self.assertAlmostEqual(r["roof_utilization"], .6)
        self.assertAlmostEqual(r["fixed_work_speedup_ceiling"], 5/3)
        self.assertAlmostEqual(r["e2e_speedup_ceiling"], 1/.84)
        self.assertEqual(r["theoretical_region"], "memory_side")
        self.assertIn("unconfirmed", r["actual_bottleneck"])

    def test_source_reconstruction(self):
        data = json.loads((ROOT / "examples/source_reconstruction.json").read_text())
        figure, log = analyze(data)
        self.assertEqual(figure["operations"], 2949434572800)
        self.assertEqual(figure["traffic_bytes"], 4796825600)
        self.assertAlmostEqual(figure["ai_ops_per_byte"], 614.8721714627)
        self.assertAlmostEqual(figure["achieved_tops"], 256)
        self.assertTrue(figure["near_ridge"])
        self.assertEqual(figure["timing_kind"], "derived")
        self.assertEqual(log["operations"], 5153960755200)
        self.assertAlmostEqual(log["achieved_tops"], 235.8252484649, places=5)
        self.assertNotEqual(figure["ai_ops_per_byte"], log["ai_ops_per_byte"])

    def test_grouped_gemm_no_expert_double_count_and_empty(self):
        work = {"kind":"grouped_gemm", "groups":[{"m":0,"n":4,"k":8}, {"m":3,"n":4,"k":8,"count":2}]}
        self.assertEqual(work_count(work), 384)

    def test_sparse_pairs_already_include_heads(self):
        self.assertEqual(work_count({"kind":"block_sparse_attention","pairs":7,"bq":128,"bk":64,"dk":128,"dv":64}), 2*7*128*64*192)

    def test_packed_int4_and_output_store(self):
        self.assertEqual(traffic_count({"ledger":[{"name":"w","elements":16,"storage_bits":4,"reads":1}, {"name":"c","elements":16,"storage_bits":16,"writes":1}]}),40)

    def test_calibrated_roof_is_separate(self):
        a,b = analyze(self.data)
        self.assertAlmostEqual(b["roof_utilization"], .75)
        self.assertGreater(b["roof_utilization"],a["roof_utilization"])

    def test_percentile_throughput_reverses_time(self):
        r=analyze(self.data)[0]
        self.assertLess(r["achieved_p10_tops"],r["achieved_tops"])
        self.assertGreater(r["achieved_p90_tops"],r["achieved_tops"])

    def test_above_roof_is_not_clamped(self):
        self.data["cases"][0]["time_ms"]=[.001]
        r=analyze(self.data)[0]
        self.assertGreater(r["roof_utilization"],1)
        self.assertIsNone(r["fixed_work_speedup_ceiling"])
        self.assertEqual(r["status"],"inconsistent_model")

    def test_measured_vs_modeled_bytes_not_conflated(self):
        case=self.data["cases"][0]
        observed=copy.deepcopy(case["byte_models"][0])
        observed.update({"id":"observed", "kind":"measured", "source":"synthetic counter for a test", "ledger":[{"name":"DRAM traffic", "bytes":8e6}]})
        case["byte_models"].append(observed)
        rows=analyze(self.data)
        self.assertEqual(len(rows),4)
        self.assertGreater(rows[2]["ai_ops_per_byte"],rows[0]["ai_ops_per_byte"])
        self.assertEqual(rows[2]["bytes_kind"],"measured")
        self.assertFalse(any("modeled_traffic" in w for w in rows[2]["warnings"]))

    def test_zero_work_bandwidth_only(self):
        self.data["cases"][0]["work"]={"kind":"explicit", "operations":0,"derivation":"copy, no arithmetic"}
        r=analyze(self.data)[0]
        self.assertEqual(r["theoretical_region"],"bandwidth_only")
        self.assertIsNone(r["roof_tops"])
        self.assertAlmostEqual(r["roof_utilization"],.6)

    def test_zero_traffic_compute_only(self):
        self.data["cases"][0]["byte_models"][0]["ledger"]=[{"name":"residency", "bytes":0}]
        r=analyze(self.data)[0]
        self.assertIsNone(r["ai_ops_per_byte"])
        self.assertEqual(r["theoretical_region"],"compute_only")

    def test_invalid_times(self):
        for value in (0,-1,float("nan"),float("inf"),True,"1"):
            with self.subTest(value=value):
                self.data["cases"][0]["time_ms"]=[value]
                with self.assertRaises(ValueError): analyze(self.data)

    def test_wrong_path(self):
        self.data["cases"][0]["path"]="INT8 tensor"
        with self.assertRaisesRegex(ValueError,"mismatch"): analyze(self.data)

    def test_wrong_layer(self):
        self.data["cases"][0]["byte_models"][0]["layer"]="L2"
        with self.assertRaisesRegex(ValueError,"same-layer"): analyze(self.data)

    def test_wrong_operation_kind(self):
        self.data["cases"][0]["op_kind"]="integer"
        with self.assertRaisesRegex(ValueError,"mismatch"): analyze(self.data)

    def test_duplicate_ids(self):
        self.data["cases"].append(copy.deepcopy(self.data["cases"][0]))
        with self.assertRaisesRegex(ValueError,"duplicate"): analyze(self.data)

    def test_unknown_roof(self):
        self.data["cases"][0]["roof_ids"]=["missing"]
        with self.assertRaisesRegex(ValueError,"unknown"): analyze(self.data)

    def test_invalid_fraction(self):
        self.data["cases"][0]["e2e_fraction"]=1.1
        with self.assertRaises(ValueError): analyze(self.data)

    def test_conflicting_byte_count(self):
        with self.assertRaises(ValueError):
            traffic_count({"ledger":[{"name":"bad", "bytes":1,"elements":1}]})

    def test_fractional_dimensions_rejected(self):
        with self.assertRaises(ValueError): work_count({"kind":"gemm","m":1.5,"n":2,"k":3})

    def test_cli_reports_and_strict_exit(self):
        with tempfile.TemporaryDirectory() as temp:
            temp = Path(temp)
            self.data["cases"][0]["time_ms"] = [.001]
            source = temp / "input.json"
            source.write_text(json.dumps(self.data))
            command = [sys.executable, str(ROOT/"scripts/roofline.py"), "--input", str(source),
                       "--output-dir", str(temp/"result"), "--no-plot", "--strict"]
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(result.returncode, 2, result.stderr)
            payload = json.loads((temp/"result/metrics.json").read_text())
            self.assertEqual(payload["input"], self.data)
            self.assertTrue((temp/"result/report.md").is_file())
            self.assertTrue((temp/"result/metrics.csv").is_file())
            # Explicit overwrite is required even for an existing generated report.
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(result.returncode, 1)

    @unittest.skipUnless(importlib.util.find_spec("matplotlib"), "plot dependencies not installed")
    def test_plot_splits_cases_and_exports(self):
        from roofline import plot_results
        data = copy.deepcopy(self.data)
        data["cases"] = []
        for index in range(4):
            case = copy.deepcopy(self.data["cases"][0])
            case.update(id=f"case{index}", label=f"Vector add variant {index}", roof_ids=["spec"])
            case["time_ms"] = [.2 + .02*index] * 5
            data["cases"].append(case)
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp)
            audit = plot_results(data, analyze(data), output)
            self.assertEqual(audit["status"], "programmatic_pass", audit)
            self.assertEqual(len(audit["figures"]), 2)
            self.assertEqual(audit["human_visual_review"], "required")
            for f in audit["figures"]:
                for suffix in (".png", ".pdf", ".svg", "-grayscale.png"):
                    self.assertGreater((output/(f["stem"]+suffix)).stat().st_size, 100)


if __name__ == "__main__":
    unittest.main()

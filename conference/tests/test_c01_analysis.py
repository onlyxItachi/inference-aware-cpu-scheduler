import importlib.util
import csv
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "conference" / "analysis" / "c01_analyze.py"
SPEC = importlib.util.spec_from_file_location("c01_analyze", MODULE_PATH)
C01 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(C01)


class C01AnalysisTests(unittest.TestCase):
    def make_fixture(self, root):
        env_path = root / "raw" / "environment" / "env_test.json"
        env_path.parent.mkdir(parents=True)
        env_path.write_text(json.dumps({
            "topology": {
                "cpus": {
                    "0": {"core_id": 0, "core_class": "P"},
                    "16": {"core_id": 8, "core_class": "E"},
                }
            }
        }), encoding="utf-8")

        trace_path = (
            root / "raw" / "characterization" / "interval_20ms" /
            "traces" / "trace_run_001.json"
        )
        trace_path.parent.mkdir(parents=True)
        trace_path.write_text(json.dumps({
            "arm": "S0_STOCK_UNPINNED",
            "run": 1,
            "environment_file": "raw/environment/env_test.json",
            "config": {
                "interval_ms": 20.0,
                "threads": 8,
                "threads_batch": 16,
            },
            "request": {
                "t_sent_ns": 100,
                "t_first_token_ns": 320,
                "t_last_token_ns": 500,
            },
            "phase_labeling": {
                # Analyzer must derive 300 from the raw markers rather than
                # trusting this runner-side convenience field.
                "first_decode_boundary_ns": 999,
                "phase_markers": [
                    {"batched": 1, "t_mono_ns": 110},
                    {"batched": 0, "t_mono_ns": 300},
                ],
            },
            "sampler": {"read_cost_us_p95": 12.0},
            "whole_request_counters": {"migrations": 9, "ctx_switches": 20},
            "samples": [
                {"t_mono_ns": 150, "tasks": [
                    {"tid": 1, "state": "R", "cpu_ticks": 0, "cpu": 0},
                    {"tid": 2, "state": "S", "cpu_ticks": 0, "cpu": 16},
                ]},
                {"t_mono_ns": 250, "tasks": [
                    {"tid": 1, "state": "S", "cpu_ticks": 1, "cpu": 16},
                    {"tid": 2, "state": "R", "cpu_ticks": 0, "cpu": 16},
                ]},
                {"t_mono_ns": 350, "tasks": [
                    {"tid": 1, "state": "R", "cpu_ticks": 2, "cpu": 0},
                    {"tid": 2, "state": "R", "cpu_ticks": 1, "cpu": 16},
                ]},
                {"t_mono_ns": 450, "tasks": [
                    {"tid": 1, "state": "S", "cpu_ticks": 3, "cpu": 0},
                    {"tid": 2, "state": "S", "cpu_ticks": 1, "cpu": 16},
                ]},
            ],
        }), encoding="utf-8")

        perf_dir = root / "raw" / "performance"
        perf_dir.mkdir(parents=True)
        (perf_dir / "perf_run_001.json").write_text(json.dumps({
            "arm": "S0_STOCK_UNPINNED",
            "run": 1,
            "ttft_ms": 1000.0,
            "itl_p50_ms": 50.0,
            "itl_p95_ms": 60.0,
            "itl_p99_ms": 70.0,
            "decode_tps": 20.0,
            "migrations": 9,
            "ctx_switches": 20,
            "threads": 8,
            "threads_batch": 16,
        }), encoding="utf-8")
        return trace_path

    def test_phase_residency_uses_active_thread_observations(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            trace_path = self.make_fixture(root)
            result = C01.summarize_trace(trace_path, root)

            self.assertAlmostEqual(result["prefill"]["p_residency_pct"], 33.333)
            self.assertAlmostEqual(result["prefill"]["e_residency_pct"], 66.667)
            self.assertAlmostEqual(result["decode"]["p_residency_pct"], 66.667)
            self.assertAlmostEqual(result["decode"]["e_residency_pct"], 33.333)
            self.assertEqual(
                result["prefill"]["sampled_transitions_lower_bound"]["p_to_e"],
                1,
            )
            self.assertEqual(
                result["decode"]["sampled_transitions_lower_bound"]
                ["total_migrations"],
                1,
            )
            self.assertEqual(
                result["decode"]["sampled_transitions_lower_bound"]["e_to_p"],
                1,
            )
            self.assertEqual(result["prefill"]["unique_active_threads"], 2)

    def test_full_analysis_writes_observation_only_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_fixture(root)
            summary = C01.analyze(root, root)

            group = summary["characterization_by_interval_ms"]["20"]
            self.assertEqual(group["run_count"], 1)
            self.assertEqual(summary["performance"]["run_count"], 1)
            self.assertEqual(
                summary["performance"]["stock_itl_p95_ms"]["mean"], 60.0
            )
            self.assertTrue((root / "summary.json").exists())
            report = (root / "summary.md").read_text(encoding="utf-8")
            self.assertIn("observations only", report)
            self.assertIn("composite stock Linux", report)
            self.assertIn("does not causally isolate Intel Thread Director/HFI", report)
            self.assertNotIn("Thread Director failed", report)
            self.assertNotIn("Linux solves the problem", report)

    def test_two_by_two_by_two_sensitivity_smoke_is_complete(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            trace1 = self.make_fixture(root)
            trace = json.loads(trace1.read_text(encoding="utf-8"))

            trace["run"] = 2
            trace2 = trace1.with_name("trace_run_002.json")
            trace2.write_text(json.dumps(trace), encoding="utf-8")

            for run, source in ((1, trace1), (2, trace2)):
                value = json.loads(source.read_text(encoding="utf-8"))
                value["config"]["interval_ms"] = 50.0
                target = (
                    root / "raw" / "characterization" / "interval_50ms" /
                    "traces" / f"trace_run_{run:03d}.json"
                )
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(json.dumps(value), encoding="utf-8")

            perf1 = root / "raw" / "performance" / "perf_run_001.json"
            perf = json.loads(perf1.read_text(encoding="utf-8"))
            perf["run"] = 2
            perf1.with_name("perf_run_002.json").write_text(
                json.dumps(perf), encoding="utf-8"
            )

            summary = C01.analyze(root, root)
            self.assertTrue(summary["protocol"]["smoke_complete"])
            self.assertTrue(summary["protocol"]["frozen_configuration_match"])

    def test_reference_filters_do_not_mix_arms_or_scenarios(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "frontier.csv"
            with path.open("w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(
                    f, fieldnames=["arm", "scenario", "ttft_ms", "itl_p95_ms"]
                )
                writer.writeheader()
                writer.writerows([
                    {"arm": "A_P8", "scenario": "none",
                     "ttft_ms": 10, "itl_p95_ms": 20},
                    {"arm": "A_P8", "scenario": "build",
                     "ttft_ms": 100, "itl_p95_ms": 200},
                    {"arm": "C_P8_E8", "scenario": "none",
                     "ttft_ms": 30, "itl_p95_ms": 40},
                ])

            name, reference = C01.load_reference(
                f"P_ONLY={path}::arm=A_P8,scenario=none"
            )
            self.assertEqual(name, "P_ONLY")
            self.assertEqual(reference["row_count"], 1)
            self.assertEqual(reference["metrics"]["ttft_ms"]["mean"], 10.0)


if __name__ == "__main__":
    unittest.main()

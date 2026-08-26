import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "conference" / "analysis" / "c03_analyze.py"
SPEC = importlib.util.spec_from_file_location("c03_analyze", MODULE_PATH)
C03A = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = C03A
SPEC.loader.exec_module(C03A)


class C03AnalysisTests(unittest.TestCase):
    def _write_synthetic(self, root):
        runs = root / "raw" / "runs"
        detector = root / "raw" / "detector"
        runs.mkdir(parents=True)
        detector.mkdir(parents=True)
        schedule = [
            (1, 1, "BIG_ONLY"), (1, 2, "ALL_CORES"),
            (2, 1, "ALL_CORES"), (2, 2, "BIG_ONLY"),
        ]
        for global_index, (round_number, sequence, arm) in enumerate(schedule, 1):
            stem = f"round_{round_number:02d}_seq_{sequence:02d}_{arm.lower()}"
            trace_rel = f"raw/detector/{stem}.json"
            trace = {
                "marker_used_by_detector": False,
                "samples": [
                    {"t_ns": 110, "norm_ctx_per_cpu_s": 900.0},
                    {"t_ns": 130, "norm_ctx_per_cpu_s": 1200.0},
                    {"t_ns": 170, "norm_ctx_per_cpu_s": 3400.0},
                    {"t_ns": 190, "norm_ctx_per_cpu_s": 3600.0},
                ],
            }
            (root / trace_rel).write_text(json.dumps(trace), encoding="utf-8")
            is_all = arm == "ALL_CORES"
            record = {
                "status": "ok", "task": "TASK-C03", "arm": arm,
                "round": round_number, "sequence_index": sequence,
                "global_sequence_index": global_index,
                "randomized_order_seed": 3303 + round_number,
                "selected_c03_path": "CROSS_VENDOR",
                "detector_mode": "zero_shot",
                "ttft_ms": 90.0 if is_all else 100.0,
                "itl_p50_ms": 80.0 if is_all else 75.0,
                "itl_p95_ms": 98.0 if is_all else 90.0,
                "itl_p99_ms": 105.0 if is_all else 96.0,
                "decode_tps": 10.0 if is_all else 11.0,
                "temp_start_c": 55.0, "temp_end_c": 72.0,
                "t_request_sent_ns": 100,
                "t_internal_phase_ns": 150,
                "t_external_detect_ns": 175,
                "detect_vs_internal_ms": 0.000025,
                "t_last_token_ns": 200,
                "detector_file": trace_rel,
            }
            (runs / f"{stem}.json").write_text(json.dumps(record), encoding="utf-8")

    def test_raw_signal_distributions_are_preserved_for_offline_analysis(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_synthetic(root)
            record = json.loads(next((root / "raw" / "runs").glob("*.json")).read_text())
            split, preserved = C03A.phase_signal_samples(record, root)
            self.assertEqual(split["PREFILL"], [900.0, 1200.0])
            self.assertEqual(split["DECODE"], [3400.0, 3600.0])
            self.assertEqual(len(preserved), 4)
            self.assertEqual({item["offline_phase"] for item in preserved}, {"PREFILL", "DECODE"})

    def test_marker_routing_violation_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_synthetic(root)
            record = json.loads(next((root / "raw" / "runs").glob("*.json")).read_text())
            trace_path = root / record["detector_file"]
            trace = json.loads(trace_path.read_text())
            trace["marker_used_by_detector"] = True
            trace_path.write_text(json.dumps(trace))
            with self.assertRaises(ValueError):
                C03A.phase_signal_samples(record, root)

    def test_analysis_reports_performance_effect_and_signal(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_synthetic(root)
            summary = C03A.analyze(root)
            self.assertEqual(summary["selected_c03_path"], "CROSS_VENDOR")
            self.assertEqual(summary["protocol"]["successful_run_count"], 4)
            self.assertEqual(summary["protocol"]["arm_counts"], {
                "BIG_ONLY": 2, "ALL_CORES": 2,
            })
            self.assertEqual(
                summary["all_cores_vs_big_only"]["ttft_ms"]["all_cores_minus_big_only"],
                -10.0,
            )
            self.assertEqual(
                summary["signal"]["distributions"]["BIG_ONLY"]["PREFILL"]["n"],
                4,
            )
            self.assertTrue(summary["signal"]["raw_signal_preserved"])
            self.assertTrue((root / "signal_summary.csv").exists())
            self.assertTrue((root / "summary.json").exists())
            self.assertTrue((root / "summary.md").exists())
            self.assertEqual(summary["warnings"], [])

    def test_overlap_summary_remains_descriptive(self):
        separated = C03A.range_overlap([800, 900], [3000, 3200])
        self.assertFalse(separated["ranges_overlap"])
        self.assertIn("descriptive", separated["method"])
        missing = C03A.range_overlap([], [1])
        self.assertEqual(missing["status"], "NA")


if __name__ == "__main__":
    unittest.main()

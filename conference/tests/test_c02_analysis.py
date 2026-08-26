import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "conference" / "analysis" / "c02_analyze.py"
SPEC = importlib.util.spec_from_file_location("c02_analyze", MODULE_PATH)
C02A = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = C02A
SPEC.loader.exec_module(C02A)


class C02AnalysisTests(unittest.TestCase):
    @staticmethod
    def _arm_summary(ttft, p95, tps, throttle_total=0):
        records = [{
            "round": 1,
            "sequence_index": 1,
            "arm": "SYNTHETIC",
            "ttft_ms": ttft,
            "itl_p95_ms": p95,
            "decode_tps": tps,
            "thermal_throttle_delta": {"total": throttle_total},
        }]
        return C02A.arm_summary(records)

    def test_lower_is_better_recovery(self):
        value = C02A.recovery(100.0, 82.0, 80.0, higher_is_better=False)
        self.assertEqual(value["status"], "ok")
        self.assertAlmostEqual(value["value"], 0.9)
        self.assertFalse(value["clamped"])

    def test_higher_is_better_recovery(self):
        value = C02A.recovery(10.0, 14.0, 15.0, higher_is_better=True)
        self.assertEqual(value["status"], "ok")
        self.assertAlmostEqual(value["value"], 0.8)

    def test_near_zero_denominator_is_na(self):
        value = C02A.recovery(
            100.0, 90.0, 100.00001, higher_is_better=False
        )
        self.assertEqual(value["status"], "NA")
        self.assertIsNone(value["value"])
        self.assertIn("too close to zero", value["explanation"])

    def test_internal_boundary_not_first_token_is_timing_origin(self):
        record = {
            "arm": "EXTERNAL",
            "t_internal_phase_ns": 1_000_000_000,
            "t_marker_seen_ns": 1_004_000_000,
            "t_external_detect_ns": 1_025_000_000,
            "t_affinity_start_ns": 1_030_000_000,
            "t_first_token_ns": 1_200_000_000,
        }
        timing = C02A.timing_for_run(record)
        self.assertEqual(timing["marker_delivery_latency_ms"], 4.0)
        self.assertEqual(timing["external_detect_vs_internal_ms"], 25.0)
        self.assertEqual(timing["external_action_vs_internal_ms"], 30.0)
        self.assertNotEqual(timing["external_detect_vs_internal_ms"], -175.0)

    def test_marker_delivery_uses_seen_minus_embedded_internal_timestamp(self):
        record = {
            "arm": "ORACLE",
            "t_internal_phase_ns": 5_000_000_000,
            "t_marker_seen_ns": 5_007_500_000,
            "t_first_token_ns": 5_900_000_000,
        }
        timing = C02A.timing_for_run(record)
        self.assertEqual(timing["marker_delivery_latency_ms"], 7.5)

    def test_thermal_warning_generation_reports_affected_run_ids(self):
        records = [
            {
                "round": 1, "sequence_index": 2, "arm": "STATIC_P",
                "thermal_throttle_delta": {"total": 810},
            },
            {
                "round": 2, "sequence_index": 3, "arm": "STATIC_P",
                "thermal_throttle_delta": {"total": 1270},
            },
        ]
        thermal = C02A.thermal_throttle_summary(records)
        warning = C02A.thermal_warning("STATIC_P", thermal)
        self.assertEqual(thermal["runs_with_throttle_delta_gt_zero"], 2)
        self.assertEqual(thermal["total_throttle_delta"], 2080)
        self.assertEqual(thermal["min_throttle_delta"], 810)
        self.assertEqual(thermal["max_throttle_delta"], 1270)
        self.assertEqual(
            thermal["affected_run_ids"],
            ["round_01_seq_02_static_p", "round_02_seq_03_static_p"],
        )
        self.assertIn("TTFT recovery", warning)
        self.assertIn("observational, not causal", warning)

    def test_recovery_warning_is_specific_to_throttled_anchor(self):
        by_arm = {
            "STATIC_P": self._arm_summary(100, 90, 10, throttle_total=5),
            "STATIC_PE": self._arm_summary(95, 105, 9, throttle_total=0),
            "EXTERNAL": self._arm_summary(82, 92, 14, throttle_total=0),
            "ORACLE": self._arm_summary(80, 90, 15, throttle_total=0),
        }
        values = C02A.recovery_metrics(by_arm)
        self.assertEqual(
            values["ttft_recovery"]["status"],
            C02A.THERMAL_ANCHOR_WARNING,
        )
        self.assertAlmostEqual(values["ttft_recovery"]["value"], 0.9)
        self.assertEqual(values["itl_p95_recovery"]["status"], "ok")
        self.assertEqual(values["throughput_recovery"]["status"], "ok")

    def test_static_pe_warning_marks_only_static_pe_recoveries(self):
        by_arm = {
            "STATIC_P": self._arm_summary(100, 90, 10, throttle_total=0),
            "STATIC_PE": self._arm_summary(95, 105, 9, throttle_total=7),
            "EXTERNAL": self._arm_summary(82, 92, 14, throttle_total=0),
            "ORACLE": self._arm_summary(80, 90, 15, throttle_total=0),
        }
        values = C02A.recovery_metrics(by_arm)
        self.assertEqual(values["ttft_recovery"]["status"], "ok")
        self.assertEqual(
            values["itl_p95_recovery"]["status"],
            C02A.THERMAL_ANCHOR_WARNING,
        )
        self.assertEqual(
            values["throughput_recovery"]["status"],
            C02A.THERMAL_ANCHOR_WARNING,
        )

    def test_direct_external_oracle_gap_is_anchor_independent(self):
        by_arm = {
            "STATIC_P": self._arm_summary(100, 90, 10, throttle_total=5),
            "STATIC_PE": self._arm_summary(95, 105, 9, throttle_total=0),
            "EXTERNAL": self._arm_summary(82, 92, 14, throttle_total=0),
            "ORACLE": self._arm_summary(80, 90, 15, throttle_total=0),
        }
        before = C02A.external_oracle_gap(by_arm)
        by_arm["STATIC_P"] = self._arm_summary(
            1000, 900, 1, throttle_total=999
        )
        after = C02A.external_oracle_gap(by_arm)
        self.assertEqual(before, after)
        self.assertTrue(all(
            value["static_anchor_dependent"] is False
            for value in after.values()
        ))

    def test_synthetic_smoke_analysis_reports_all_arms(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runs = root / "raw" / "runs"
            envs = root / "raw" / "environment"
            runs.mkdir(parents=True)
            envs.mkdir(parents=True)
            env = {
                "llama_cpp": {
                    "diagnostic_server_binary": {"sha256": "same-build"}
                }
            }
            (envs / "env.json").write_text(json.dumps(env), encoding="utf-8")
            metric_base = {
                "STOCK": (90.0, 115.0, 9.0),
                "STATIC_P": (110.0, 90.0, 11.0),
                "STATIC_PE": (98.0, 103.0, 10.0),
                "EXTERNAL": (94.0, 92.0, 10.8),
                "ORACLE": (93.0, 91.0, 11.0),
            }
            global_index = 0
            for round_number in (1, 2):
                for sequence_index, arm in enumerate(C02A.ARMS, 1):
                    global_index += 1
                    ttft, p95, tps = metric_base[arm]
                    action = arm in ("EXTERNAL", "ORACLE")
                    source = C02A.EXPECTED_PHASE_SOURCE[arm]
                    record = {
                        "status": "ok", "arm": arm,
                        "round": round_number,
                        "sequence_index": sequence_index,
                        "global_sequence_index": global_index,
                        "randomized_order_seed": 2202 + round_number,
                        "phase_source": source,
                        "diagnostic_marker_consumption": (
                            "live_trigger" if arm == "ORACLE"
                            else "live_record_only"
                        ),
                        "monitor_overhead_equalized": True,
                        "live_marker_watcher": True,
                        "marker_routed_to_actuator": arm == "ORACLE",
                        "environment_file": "raw/environment/env.json",
                        "ttft_ms": ttft + round_number / 10,
                        "itl_p50_ms": p95 - 5,
                        "itl_p95_ms": p95,
                        "itl_p99_ms": p95 + 5,
                        "decode_tps": tps,
                        "total_migrations": 100,
                        "total_ctx_switches": 1000,
                        "temp_start_c": 60,
                        "temp_end_c": 80,
                        "thermal_throttle_delta": {"total": 0},
                        "switch_attempted": action,
                        "switch_success": action,
                        "external_detected": True,
                        "t_internal_phase_ns": 1_000_000_000,
                        "t_marker_seen_ns": 1_002_000_000,
                        "t_external_detect_ns": 1_020_000_000,
                        "t_affinity_start_ns": (
                            1_025_000_000 if arm == "EXTERNAL"
                            else 1_001_000_000 if arm == "ORACLE" else None
                        ),
                        "affinity_cost_us": 100 if action else None,
                    }
                    name = (
                        f"round_{round_number:02d}_seq_{sequence_index:02d}_"
                        f"{arm.lower()}.json"
                    )
                    (runs / name).write_text(json.dumps(record), encoding="utf-8")

            summary = C02A.analyze(root)
            self.assertEqual(summary["protocol"]["successful_run_count"], 10)
            self.assertTrue(summary["protocol"]["same_diagnostic_build"])
            self.assertEqual(summary["warnings"], [])
            self.assertEqual(summary["arms"]["EXTERNAL"]["switch_successes"], 2)
            self.assertTrue((root / "summary.json").exists())
            self.assertTrue((root / "summary.md").exists())


if __name__ == "__main__":
    unittest.main()

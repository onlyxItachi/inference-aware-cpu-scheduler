import importlib.util
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "conference" / "tools" / "c03_amd_preflight.py"
SPEC = importlib.util.spec_from_file_location("c03_amd_preflight", MODULE_PATH)
AMD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AMD)


def synthetic_records(high_values=None, max_values=None):
    high_values = high_values or ([220] * 4 + [150] * 8)
    max_values = max_values or ([5_100_000] * 4 + [3_600_000] * 8)
    records = []
    for core_id in range(12):
        siblings = [core_id * 2, core_id * 2 + 1]
        for cpu in siblings:
            records.append({
                "cpu": cpu,
                "online": True,
                "allowed": True,
                "package_id": 0,
                "core_id": core_id,
                "thread_siblings": siblings,
                "highest_perf": high_values[core_id],
                "nominal_perf": 140,
                "max_freq_khz": max_values[core_id],
                "cpu_capacity": None,
                "core_type": None,
                "scaling_driver": "amd-pstate-epp",
                "governor": "powersave",
                "epp": "balance_performance",
            })
    return records


class C03AMDPreflightTests(unittest.TestCase):
    def setUp(self):
        self.records = synthetic_records()
        self.cores = AMD.group_physical_cores(self.records)
        self.selection = AMD.classify_physical_cores(self.cores)

    def test_physical_core_grouping_from_smt_siblings(self):
        self.assertEqual(len(self.cores), 12)
        self.assertEqual(self.cores[0]["sibling_cpus"], [0, 1])
        self.assertEqual(self.cores[-1]["sibling_cpus"], [22, 23])

    def test_one_representative_per_physical_core(self):
        representatives = [core["representative_cpu"] for core in self.cores]
        self.assertEqual(representatives, list(range(0, 24, 2)))
        self.assertEqual(len(representatives), len(set(representatives)))

    def test_clean_synthetic_four_big_eight_compact_detection(self):
        big = [core["representative_cpu"] for core in self.selection["big_cores"]]
        compact = [
            core["representative_cpu"] for core in self.selection["compact_cores"]
        ]
        self.assertEqual(big, [0, 2, 4, 6])
        self.assertEqual(compact, [8, 10, 12, 14, 16, 18, 20, 22])
        self.assertEqual(self.selection["classification_source"], "highest_perf")

    def test_ambiguous_classification_aborts(self):
        records = synthetic_records(
            high_values=[180] * 12,
            max_values=[4_000_000] * 12,
        )
        with self.assertRaises(AMD.AmbiguousClassification):
            AMD.classify_physical_cores(AMD.group_physical_cores(records))

    def test_overlapping_mask_aborts(self):
        with self.assertRaises(AMD.PreflightError):
            AMD.validate_masks([0, 2, 4, 6], [6, 8, 10, 12, 14, 16, 18, 20], self.cores)

    def test_sibling_duplication_aborts(self):
        with self.assertRaises(AMD.PreflightError):
            AMD.validate_masks([0, 1, 4, 6], [8, 10, 12, 14, 16, 18, 20, 22], self.cores)

    def test_intel_target_aborts_cross_vendor(self):
        with self.assertRaises(AMD.PreflightError):
            AMD.validate_target(
                {"vendor_id": "GenuineIntel", "model_name": "Intel CPU"},
                self.records, self.cores, self.selection,
            )

    def test_missing_phase_mark_capability_aborts(self):
        with tempfile.TemporaryDirectory() as tmp:
            binary = Path(tmp) / "llama-server"
            binary.write_bytes(b"ordinary runtime")
            with self.assertRaises(AMD.PreflightError):
                AMD.scan_phase_mark_capability(binary)
            library = Path(tmp) / "libllama.so.0"
            library.write_bytes(b"prefix " + AMD.MARKER + b" suffix")
            evidence = AMD.scan_phase_mark_capability(binary)
            self.assertTrue(evidence["supported"])
            self.assertEqual(evidence["matches"], [str(library.resolve())])

    def test_missing_model_aborts(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(AMD.PreflightError):
                AMD.validate_model_identity(Path(tmp) / AMD.EXPECTED_MODEL_NAME)

    def test_generated_topology_file_contains_frozen_values(self):
        selected = {
            "big_cpus": [0, 2, 4, 6],
            "compact_cpus": [8, 10, 12, 14, 16, 18, 20, 22],
        }
        build = {"server_binary": {"resolved_path": "/repo path/llama-server"}}
        model = {"resolved_path": "/model path/Qwen3.5-9B-Q4_K_M.gguf"}
        text = AMD.topology_env_text(selected, build, model)
        self.assertIn("C03_BIG_CPUS=0,2,4,6", text)
        self.assertIn("C03_COMPACT_CPUS=8,10,12,14,16,18,20,22", text)
        self.assertIn("C03_THREADS_BIG=4", text)
        self.assertIn("C03_THREADS_ALL=12", text)


if __name__ == "__main__":
    unittest.main()

import contextlib
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "conference" / "experiments" / "c01_stock_scheduler.py"
SPEC = importlib.util.spec_from_file_location("c01_stock_scheduler", MODULE_PATH)
C01 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(C01)


class C01RunnerTests(unittest.TestCase):
    def base_args(self, **overrides):
        values = {
            "server_bin": "/bin/true",
            "model": "/etc/hosts",
            "prompt": str(ROOT / "harness" / "prompt_512.txt"),
            "threads": 8,
            "threads_batch": 16,
            "ctx": 2048,
            "batch": 2048,
            "ubatch": 512,
            "port": 8120,
            "seed": 42,
            "n_predict": 256,
            "runs": 1,
            "cooldown": 0,
            "resume": False,
        }
        values.update(overrides)
        return SimpleNamespace(**values)

    def test_stock_server_command_has_no_affinity_wrapper(self):
        command = C01.server_command(self.base_args())
        self.assertEqual(command[0], "/bin/true")
        self.assertNotIn("taskset", command)
        self.assertNotIn("--cpu-mask", command)

    def test_both_pilot_intervals_are_accepted(self):
        for interval in (20, 50):
            args = C01.parse_args([
                "characterize",
                "--server-bin", "/bin/true",
                "--model", "/etc/hosts",
                "--interval-ms", str(interval),
                "--runs", "1",
            ])
            self.assertEqual(args.interval_ms, interval)

    def test_frozen_defaults_are_8_decode_16_prefill_and_2_runs(self):
        args = C01.parse_args([
            "characterize",
            "--server-bin", "/bin/true",
            "--model", "/etc/hosts",
            "--interval-ms", "20",
        ])
        self.assertEqual(args.threads, 8)
        self.assertEqual(args.threads_batch, 16)
        self.assertEqual(args.runs, 2)

    def test_full_pilot_requires_explicit_post_review_gate(self):
        base = [
            "performance",
            "--server-bin", "/bin/true",
            "--model", "/etc/hosts",
            "--runs", "6",
        ]
        with contextlib.redirect_stderr(io.StringIO()), \
                self.assertRaises(SystemExit):
            C01.parse_args(base)
        approved = C01.parse_args(base + ["--full-pilot-approved"])
        self.assertEqual(approved.runs, 6)

    def test_performance_path_never_calls_residency_sampler(self):
        record = {
            "ttft_ms": 1000.0,
            "itl_p50_ms": 50.0,
            "itl_p95_ms": 60.0,
            "itl_p99_ms": 70.0,
            "decode_tps": 20.0,
            "migrations": 3,
            "temp_start_c": 50.0,
            "temp_end_c": 60.0,
        }
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(C01.ro, "measure", return_value=record), \
                mock.patch.object(
                    C01.tr, "sample_tasks",
                    side_effect=AssertionError("residency sampler was called"),
                ), \
                mock.patch.object(C01.os, "sched_getaffinity", return_value={0, 1}):
            C01.run_performance(
                self.base_args(outdir=tmp), "raw/environment/env_test.json"
            )
            raw = json.loads(
                (Path(tmp) / "raw" / "performance" / "perf_run_001.json")
                .read_text(encoding="utf-8")
            )
            self.assertFalse(raw["residency_sampler_enabled"])
            self.assertEqual(raw["arm"], "S0_STOCK_UNPINNED")
            self.assertEqual(raw["threads"], 8)
            self.assertEqual(raw["threads_batch"], 16)
            self.assertTrue(
                (Path(tmp) / "raw" / "performance" / "perf_runs.csv").exists()
            )


if __name__ == "__main__":
    unittest.main()

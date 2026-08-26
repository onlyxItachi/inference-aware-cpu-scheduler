import importlib.util
import contextlib
import io
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "conference" / "experiments" / "c02_external_oracle.py"
SPEC = importlib.util.spec_from_file_location("c02_external_oracle", MODULE_PATH)
C02 = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = C02
SPEC.loader.exec_module(C02)


class C02RunnerTests(unittest.TestCase):
    def setUp(self):
        self.p_cpus = [0, 2, 4, 6, 8, 10, 12, 14]
        self.e_cpus = list(range(16, 24))
        self.specs = C02.arm_specs(self.p_cpus, self.e_cpus)

    def test_randomized_round_contains_every_arm_exactly_once(self):
        schedule = C02.build_schedule(2, 2202)
        for round_number in (1, 2):
            members = [
                item for item in schedule if item["round"] == round_number
            ]
            self.assertEqual(len(members), 5)
            self.assertEqual({item["arm"] for item in members}, set(C02.ARMS))
            self.assertEqual(
                [item["sequence_index"] for item in members], [1, 2, 3, 4, 5]
            )
            self.assertEqual(
                {item["randomized_order_seed"] for item in members},
                {2202 + round_number},
            )

    def test_detector_interval_remains_twenty_ms(self):
        self.assertEqual(C02.DEFAULT_INTERVAL_MS, 20.0)
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                C02.parse_args([
                    "--server-bin", "unused-server",
                    "--model", "unused-model",
                    "--interval-ms", "50",
                ])

    def test_external_and_oracle_use_same_actuator_implementation(self):
        external = C02.AffinityActuator(123, self.p_cpus)
        oracle = C02.AffinityActuator(456, self.p_cpus)
        external_route = C02.actuation_routes("EXTERNAL", external)[
            "external_proc"
        ]
        oracle_route = C02.actuation_routes("ORACLE", oracle)[
            "internal_oracle"
        ]
        self.assertIs(external_route.__func__, C02.AffinityActuator.apply)
        self.assertIs(oracle_route.__func__, C02.AffinityActuator.apply)

    def test_external_and_oracle_configs_differ_only_by_phase_source(self):
        external = dict(self.specs["EXTERNAL"])
        oracle = dict(self.specs["ORACLE"])
        self.assertNotEqual(external.pop("phase_source"), oracle.pop("phase_source"))
        self.assertEqual(external, oracle)

    def test_external_decision_route_cannot_consume_phase_mark(self):
        actuator = C02.AffinityActuator(123, self.p_cpus)
        routes = C02.actuation_routes("EXTERNAL", actuator)
        self.assertIsNotNone(routes["external_proc"])
        self.assertIsNone(routes["internal_oracle"])
        self.assertEqual(self.specs["EXTERNAL"]["phase_source"], "external_proc")

    def test_oracle_uses_internal_marker_route(self):
        actuator = C02.AffinityActuator(123, self.p_cpus)
        routes = C02.actuation_routes("ORACLE", actuator)
        self.assertIsNone(routes["external_proc"])
        self.assertIs(routes["internal_oracle"].__func__, C02.AffinityActuator.apply)
        self.assertEqual(self.specs["ORACLE"]["phase_source"], "internal_oracle")

    def test_oracle_watcher_forwards_internal_marker_timestamp(self):
        calls = []
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "server.log"
            marker_timestamp = 1_234_567_890
            log_path.write_text(
                f"PHASE_MARK batched=0 t_mono_ns={marker_timestamp}\n",
                encoding="utf-8",
            )
            watcher = C02.PhaseMarkWatcher(
                log_path, 0,
                lambda trigger_ns, source: calls.append((trigger_ns, source)),
            )
            watcher.start()
            time.sleep(0.02)
            watcher.stop_flag.set()
            watcher.join(timeout=1)
        self.assertEqual(calls, [(marker_timestamp, "internal_oracle")])
        self.assertEqual(watcher.t_internal_phase_ns, marker_timestamp)
        self.assertIsNotNone(watcher.t_marker_seen_ns)

    def test_all_arms_instantiate_same_live_marker_watcher_path(self):
        class RecordingActuator:
            def apply(self, trigger_ns, source):
                return (trigger_ns, source)

        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "server.log"
            log_path.write_text("", encoding="utf-8")
            watchers = {
                arm: C02.phase_mark_watcher_for_arm(
                    arm, log_path, 0, RecordingActuator()
                )
                for arm in C02.ARMS
            }
        self.assertTrue(all(
            type(watcher) is C02.PhaseMarkWatcher
            for watcher in watchers.values()
        ))
        for arm, watcher in watchers.items():
            if arm == "ORACLE":
                self.assertIsNotNone(watcher.decision_callback)
            else:
                self.assertIsNone(watcher.decision_callback)

    def test_only_oracle_routes_live_marker_to_actuator(self):
        class RecordingActuator:
            def __init__(self):
                self.calls = []

            def apply(self, trigger_ns, source):
                self.calls.append((trigger_ns, source))

        marker_timestamp = 9_876_543_210
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "server.log"
            log_path.write_text("", encoding="utf-8")
            for arm in C02.ARMS:
                actuator = RecordingActuator()
                watcher = C02.phase_mark_watcher_for_arm(
                    arm, log_path, 0, actuator
                )
                watcher.observe_line(
                    f"PHASE_MARK batched=0 t_mono_ns={marker_timestamp}"
                )
                expected = (
                    [(marker_timestamp, "internal_oracle")]
                    if arm == "ORACLE" else []
                )
                self.assertEqual(actuator.calls, expected, arm)
                self.assertEqual(watcher.t_internal_phase_ns, marker_timestamp)
                self.assertIsNotNone(watcher.t_marker_seen_ns)

    def test_stock_and_static_arms_cannot_apply_affinity_changes(self):
        actuator = C02.AffinityActuator(123, self.p_cpus)
        for arm in ("STOCK", "STATIC_P", "STATIC_PE"):
            self.assertEqual(
                C02.actuation_routes(arm, actuator),
                {"external_proc": None, "internal_oracle": None},
            )
        args = SimpleNamespace(
            server_bin="diag-server", model="model.gguf", ctx=2048,
            batch=2048, ubatch=512, port=8130,
        )
        command = C02.server_command(args, self.specs["STOCK"])
        self.assertNotIn("taskset", command)

    def test_metadata_preserves_decode_and_batch_threads_per_arm(self):
        expected = {
            "STOCK": (8, 16),
            "STATIC_P": (8, 8),
            "STATIC_PE": (16, 16),
            "EXTERNAL": (8, 16),
            "ORACLE": (8, 16),
        }
        observed = {
            arm: (spec["threads"], spec["threads_batch"])
            for arm, spec in self.specs.items()
        }
        self.assertEqual(observed, expected)

    def test_smoke_plan_can_be_extended_without_changing_first_rounds(self):
        with tempfile.TemporaryDirectory() as tmp:
            smoke = C02.ensure_plan(tmp, 2, 2202, self.specs)
            full = C02.ensure_plan(tmp, 6, 2202, self.specs)
            self.assertEqual(smoke["schedule"], full["schedule"][:10])
            self.assertEqual(full["rounds"], 6)

    def test_continuation_uses_absolute_round_numbers_three_through_six(self):
        plan = {"schedule": C02.build_schedule(6, 2202)}
        continuation = C02.schedule_from_round(plan, 3)
        self.assertEqual(len(continuation), 20)
        self.assertEqual(
            sorted({item["round"] for item in continuation}), [3, 4, 5, 6]
        )
        self.assertEqual(
            [item["global_sequence_index"] for item in continuation],
            list(range(11, 31)),
        )

    def test_continuation_never_selects_or_overwrites_smoke_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            smoke = C02.build_schedule(2, 2202)
            runs = root / "raw" / "runs"
            runs.mkdir(parents=True)
            before = {}
            for item in smoke:
                path = runs / f"{C02.run_stem(item)}.json"
                payload = {"status": "ok", **item}
                path.write_text(str(payload), encoding="utf-8")
                before[path] = path.read_bytes()

            full = {"schedule": C02.build_schedule(6, 2202)}
            selected = C02.schedule_from_round(full, 3)
            self.assertTrue(all(item["round"] >= 3 for item in selected))
            self.assertTrue(all(path.read_bytes() == data
                                for path, data in before.items()))

    def test_completed_prefix_validation_requires_all_smoke_run_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            schedule = C02.build_schedule(6, 2202)
            runs = root / "raw" / "runs"
            runs.mkdir(parents=True)
            for item in schedule[:10]:
                path = runs / f"{C02.run_stem(item)}.json"
                path.write_text(
                    json.dumps({"status": "ok", **item}),
                    encoding="utf-8",
                )
            validated = C02.validate_completed_prefix(root, schedule, 3)
            self.assertEqual(len(validated), 10)
            (runs / f"{C02.run_stem(schedule[0])}.json").unlink()
            with self.assertRaises(RuntimeError):
                C02.validate_completed_prefix(root, schedule, 3)

    def test_round_three_through_six_orders_are_deterministic(self):
        schedule = C02.build_schedule(6, 2202)
        expected = {
            3: ["EXTERNAL", "STATIC_P", "STATIC_PE", "STOCK", "ORACLE"],
            4: ["STATIC_P", "STOCK", "STATIC_PE", "ORACLE", "EXTERNAL"],
            5: ["STATIC_P", "STOCK", "EXTERNAL", "ORACLE", "STATIC_PE"],
            6: ["EXTERNAL", "STATIC_PE", "ORACLE", "STATIC_P", "STOCK"],
        }
        for round_number, order in expected.items():
            members = [
                item for item in schedule if item["round"] == round_number
            ]
            self.assertEqual([item["arm"] for item in members], order)
            self.assertEqual(
                {item["randomized_order_seed"] for item in members},
                {2202 + round_number},
            )


if __name__ == "__main__":
    unittest.main()

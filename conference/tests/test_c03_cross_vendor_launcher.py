import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "conference" / "tools" / "c03_cross_vendor.sh"
HELPER = ROOT / "conference" / "tools" / "c03_amd_preflight.py"


class C03CrossVendorLauncherTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = SCRIPT.read_text(encoding="utf-8")
        cls.helper_source = HELPER.read_text(encoding="utf-8")

    def block(self, start, end):
        return self.source.split(start, 1)[1].split(end, 1)[0]

    def test_smoke_consumes_persisted_frozen_topology(self):
        smoke = self.block("    smoke)", "    analyze)")
        self.assertIn('source "${topology_env}"', smoke)
        self.assertIn('--big-cpus "${C03_BIG_CPUS}"', smoke)
        self.assertIn('--compact-cpus "${C03_COMPACT_CPUS}"', smoke)
        self.assertIn('--threads-big "${C03_THREADS_BIG}"', smoke)
        self.assertIn('--threads-all "${C03_THREADS_ALL}"', smoke)
        for frozen in (
            "--path CROSS_VENDOR", "--rounds 2", "--order-seed 3304",
            "--detector-mode zero_shot", "--interval-ms 20", "--hi 3000",
            "--lo 2100", "--k 2", "--ctx 2048", "--batch 2048",
            "--ubatch 512", "--n-predict 256", "--seed 42",
            "--initial-cooldown 30", "--cooldown 30",
        ):
            self.assertIn(frozen, smoke)

    def test_preflight_cannot_execute_benchmark(self):
        preflight = self.block("    preflight)", "    smoke)")
        self.assertIn('python3 "${HELPER}"', preflight)
        self.assertNotIn("${RUNNER}", preflight)
        self.assertNotIn("${ANALYZER}", preflight)

    def test_smoke_cannot_run_without_successful_preflight(self):
        smoke = self.block("    smoke)", "    analyze)")
        verify_index = smoke.index('python3 "${HELPER}" verify')
        runner_index = smoke.index('python3 "${RUNNER}"')
        self.assertLess(verify_index, runner_index)
        self.assertIn("Successful preflight configuration missing", smoke)

    def test_no_system_setting_mutation_commands(self):
        forbidden = (
            "sudo ", "cpupower ", "powerprofilesctl set", "amd_pstate=",
            "tee /sys", "> /sys", "wrmsr", "scxctl start", "sched_ext/state",
        )
        self.assertTrue(all(token not in self.source for token in forbidden))
        helper_forbidden = (
            "os.sched_setaffinity", "subprocess.Popen", "stream_completion",
            "powerprofilesctl\", \"set", "cpupower", "wrmsr",
        )
        self.assertTrue(
            all(token not in self.helper_source for token in helper_forbidden)
        )

    def test_smoke_contains_only_two_required_arms_indirectly(self):
        smoke = self.block("    smoke)", "    analyze)")
        for forbidden in ("STOCK", "STATIC_", "EXTERNAL", "ORACLE", "sched_ext"):
            self.assertNotIn(forbidden, smoke)


if __name__ == "__main__":
    unittest.main()

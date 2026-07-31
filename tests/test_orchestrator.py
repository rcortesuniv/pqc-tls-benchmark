import importlib.util
import json
import pathlib
import sys
import tempfile
import unittest
from unittest import mock


PROJECT = pathlib.Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location(
    "run_experiment", PROJECT / "scripts/run-experiment.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class OrchestratorTests(unittest.TestCase):
    def setUp(self):
        self.config = MODULE.load_config(PROJECT / "config/experiment.json")

    def test_matrix_has_36_unique_cells(self):
        cells = MODULE.cells_from_config(self.config)
        self.assertEqual(len(cells), 36)
        self.assertEqual(len({cell.identifier for cell in cells}), 36)

    def test_schedule_is_complete_per_batch(self):
        expected = {cell.identifier for cell in MODULE.cells_from_config(self.config)}
        scheduled = MODULE.schedule(self.config)
        for batch in range(1, self.config["execution"]["batches"] + 1):
            actual = {cell.identifier for item_batch, cell in scheduled if item_batch == batch}
            self.assertEqual(actual, expected)

    def test_schedule_is_reproducible(self):
        first = [(batch, cell.identifier) for batch, cell in MODULE.schedule(self.config)]
        second = [(batch, cell.identifier) for batch, cell in MODULE.schedule(self.config)]
        self.assertEqual(first, second)

    def test_rtt_is_split_symmetrically(self):
        cell = MODULE.Cell("X25519", 50, 0.5)
        commands = MODULE.apply_netem(self.config, cell, dry_run=True)
        self.assertEqual(len(commands), 2)
        for command in commands:
            self.assertIn("25ms", command)
            self.assertIn("0.5%", command)

    def test_invalid_duplicate_group_is_rejected(self):
        invalid = dict(self.config)
        invalid["groups"] = ["X25519", "X25519"]
        with tempfile.NamedTemporaryFile("w", suffix=".json") as stream:
            json.dump(invalid, stream)
            stream.flush()
            with self.assertRaises(ValueError):
                MODULE.load_config(pathlib.Path(stream.name))

    def test_invalid_timeout_is_rejected(self):
        invalid = json.loads(json.dumps(self.config))
        invalid["execution"]["timeout_ms"] = 0
        with tempfile.NamedTemporaryFile("w", suffix=".json") as stream:
            json.dump(invalid, stream)
            stream.flush()
            with self.assertRaises(ValueError):
                MODULE.load_config(pathlib.Path(stream.name))

    def test_unsafe_backend_identifier_is_rejected(self):
        invalid = json.loads(json.dumps(self.config))
        invalid["network_backend"]["client_namespace"] = "client namespace"
        with tempfile.NamedTemporaryFile("w", suffix=".json") as stream:
            json.dump(invalid, stream)
            stream.flush()
            with self.assertRaises(ValueError):
                MODULE.load_config(pathlib.Path(stream.name))

    def test_cpu_pinning_disabled_by_env_var(self):
        with mock.patch.dict("os.environ", {"PQC_CPU_PINNING": "0"}):
            plan = MODULE.cpu_pinning_plan()
        self.assertFalse(plan["enabled"])
        self.assertIn("PQC_CPU_PINNING", plan["reason"])

    def test_cpu_pinning_disabled_without_taskset(self):
        with mock.patch.dict("os.environ", {}, clear=False), \
             mock.patch("shutil.which", return_value=None):
            plan = MODULE.cpu_pinning_plan()
        self.assertFalse(plan["enabled"])
        self.assertIn("taskset", plan["reason"])

    def test_cpu_pinning_disabled_on_single_cpu(self):
        with mock.patch("shutil.which", return_value="/usr/bin/taskset"), \
             mock.patch("os.cpu_count", return_value=1):
            plan = MODULE.cpu_pinning_plan()
        self.assertFalse(plan["enabled"])

    def test_cpu_pinning_enabled_uses_configured_client_cpu(self):
        with mock.patch("shutil.which", return_value="/usr/bin/taskset"), \
             mock.patch("os.cpu_count", return_value=4), \
             mock.patch.dict("os.environ", {"PQC_CLIENT_CPU": "2"}):
            plan = MODULE.cpu_pinning_plan()
        self.assertTrue(plan["enabled"])
        self.assertEqual(plan["client_cpu"], 2)

    def test_integrity_manifest_keeps_interrupted_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            result_dir = pathlib.Path(directory)
            (result_dir / "raw").mkdir()
            (result_dir / "interrupted").mkdir()
            (result_dir / "schedule.json").write_text("[]\n", encoding="utf-8")
            (result_dir / "interrupted" / "partial.jsonl").write_text("{}\n", encoding="utf-8")
            manifest = MODULE.integrity_manifest(result_dir)
            self.assertIn("schedule.json", manifest)
            self.assertIn("interrupted/partial.jsonl", manifest)


if __name__ == "__main__":
    unittest.main()

import importlib.util
import json
import os
import pathlib
import sys
import tempfile
import unittest


PROJECT = pathlib.Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location(
    "summarise", PROJECT / "analysis/summarise.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)

DASHBOARD_SPEC = importlib.util.spec_from_file_location(
    "dashboard", PROJECT / "analysis/dashboard.py"
)
DASHBOARD = importlib.util.module_from_spec(DASHBOARD_SPEC)
assert DASHBOARD_SPEC.loader
sys.modules[DASHBOARD_SPEC.name] = DASHBOARD
DASHBOARD_SPEC.loader.exec_module(DASHBOARD)

sys.path.insert(0, str(PROJECT / "analysis"))
DASHBOARD_SERVER_SPEC = importlib.util.spec_from_file_location(
    "dashboard_server", PROJECT / "analysis/dashboard_server.py"
)
DASHBOARD_SERVER = importlib.util.module_from_spec(DASHBOARD_SERVER_SPEC)
assert DASHBOARD_SERVER_SPEC.loader
sys.modules[DASHBOARD_SERVER_SPEC.name] = DASHBOARD_SERVER
DASHBOARD_SERVER_SPEC.loader.exec_module(DASHBOARD_SERVER)


def observation(batch, cell, group, sequence, latency, status="success"):
    return {
        "schema_version": "1.0",
        "batch_id": batch,
        "cell_id": cell,
        "sequence": sequence,
        "timestamp_utc": "2026-07-26T00:00:00.000Z",
        "requested_group": group,
        "status": status,
        "failure_phase": None if status == "success" else "tls_handshake",
        "handshake_latency_ms": latency if status == "success" else None,
        "negotiated_group": group if status == "success" else None,
        "cipher": "TLS_AES_256_GCM_SHA384" if status == "success" else None,
        "tls_bytes_read": 1000,
        "tls_bytes_written": 500,
        "openssl_error_code": 0,
    }


class AnalysisTests(unittest.TestCase):
    def test_primary_delta_uses_batch_medians(self):
        classical_cell = "X25519__rtt-50ms__loss-0p0pct"
        hybrid_cell = "X25519MLKEM768__rtt-50ms__loss-0p0pct"
        rows = [
            observation("batch-001", classical_cell, "X25519", 0, 50.0),
            observation("batch-001", classical_cell, "X25519", 1, 52.0),
            observation("batch-001", hybrid_cell, "X25519MLKEM768", 0, 60.0),
            observation("batch-001", hybrid_cell, "X25519MLKEM768", 1, 62.0),
        ]
        summaries = MODULE.grouped_summary(rows)
        self.assertAlmostEqual(summaries[0]["p95_latency_ms"], 61.9)
        self.assertAlmostEqual(summaries[0]["p99_latency_ms"], 61.98)
        deltas = MODULE.primary_deltas(summaries)
        self.assertEqual(len(deltas), 1)
        self.assertAlmostEqual(deltas[0]["hybrid_minus_x25519_ms"], 10.0)
        self.assertAlmostEqual(deltas[0]["hybrid_overhead_percent"], 10 / 51 * 100)

    def test_loader_rejects_incomplete_observation(self):
        with tempfile.TemporaryDirectory() as directory:
            raw = pathlib.Path(directory)
            (raw / "bad.jsonl").write_text(json.dumps({"status": "success"}) + "\n")
            with self.assertRaises(ValueError):
                MODULE.load_observations(raw)

    def test_confirmatory_analysis_is_batch_level_and_adjusted(self):
        pairwise = [
            {"batch_id": f"batch-{index:03d}", "rtt_ms": 0, "loss_percent_each_direction": 0.0,
             "baseline_group": "X25519", "comparison_group": "X25519MLKEM768",
             "comparison_minus_baseline_ms": 2.0, "failure_rate_delta": 0.0}
            for index in range(1, 5)
        ]
        report = MODULE.confirmatory_analysis(
            pairwise, {"analysis": {"seed": 1, "bootstrap_resamples": 100, "acceptance_thresholds_ms": [1.0, 2.0]}}
        )
        self.assertEqual(len(report), 1)
        self.assertEqual(report[0]["n"], 4)
        self.assertEqual(report[0]["mean"], 2.0)
        self.assertEqual(report[0]["holm_adjusted_pvalue"], report[0]["permutation_pvalue"])
        self.assertEqual(report[0]["acceptance_threshold_sensitivity"][0]["batches_at_or_below_threshold"], 0)

    def test_prespecified_primary_contrast_has_no_holm_adjustment(self):
        pairwise = [
            {"batch_id": f"batch-{index:03d}", "rtt_ms": 50, "loss_percent_each_direction": 0.0,
             "baseline_group": "X25519", "comparison_group": "X25519MLKEM768",
             "comparison_minus_baseline_ms": 0.2, "failure_rate_delta": 0.0}
            for index in range(1, 5)
        ]
        report = MODULE.primary_contrast_analysis(pairwise, {"analysis": {
            "seed": 1, "bootstrap_resamples": 100,
            "primary_comparison": {
                "baseline_group": "X25519", "comparison_group": "X25519MLKEM768",
                "rtt_ms": 50, "loss_percent_each_direction": 0.0,
            },
        }})
        self.assertIsNotNone(report)
        assert report is not None
        self.assertEqual(report["n"], 4)
        self.assertEqual(report["mean"], 0.2)
        self.assertEqual(report["multiplicity_adjustment"], "none: one pre-specified primary comparison")

    def test_validation_detects_duplicate_sequence(self):
        row = observation("batch-001", "X25519__rtt-0ms__loss-0p0pct", "X25519", 0, 1.0)
        with tempfile.TemporaryDirectory() as directory:
            self.assertTrue(MODULE.validate_dataset(pathlib.Path(directory), [row, dict(row)]))

    def test_validation_rejects_missing_outbound_tls_byte_evidence(self):
        row = observation("batch-001", "X25519__rtt-0ms__loss-0p0pct", "X25519", 0, 1.0)
        row["tls_bytes_written"] = 0
        with tempfile.TemporaryDirectory() as directory:
            issues = MODULE.validate_dataset(pathlib.Path(directory), [row])
        self.assertIn("no outbound TLS bytes were recorded for successful handshakes", issues)

    def test_dashboard_renders_validation_and_directional_bytes(self):
        page = DASHBOARD.render_dashboard({
            "run_name": "demo-run",
            "validation": {"valid": True, "observations": 1, "batch_cells": 1, "primary_batch_deltas": 0, "status_counts": {"success": 1}},
            "summaries": [{"batch_id": "batch-001", "cell_id": "X25519__rtt-0ms__loss-0p0pct", "group": "X25519", "rtt_ms": "0", "loss_percent_each_direction": "0.0", "attempts": "1", "successes": "1", "failure_rate": "0", "median_latency_ms": "1.2", "median_tls_bytes_read": "100", "median_tls_bytes_written": "50"}],
            "primary_deltas": [],
            "confirmatory": [],
        })
        self.assertIn("PQC TLS benchmark dashboard", page)
        self.assertIn("Bytes written", page)
        self.assertIn("demo-run", page)
        self.assertIn("reset-filters", page)
        self.assertIn("filteredContrasts", page)

    def test_dashboard_refresh_is_skipped_when_outputs_are_current(self):
        with tempfile.TemporaryDirectory() as directory:
            result = pathlib.Path(directory)
            raw = result / "raw"
            analysis = result / "analysis"
            raw.mkdir()
            analysis.mkdir()
            (result / "config.snapshot.json").write_text("{}\n", encoding="utf-8")
            (result / "schedule.json").write_text("[]\n", encoding="utf-8")
            (raw / "batch.jsonl").write_text("{}\n", encoding="utf-8")
            for name in DASHBOARD.ANALYSIS_OUTPUTS:
                (analysis / name).write_text("{}\n", encoding="utf-8")
            self.assertFalse(DASHBOARD.analysis_needs_refresh(result))
            os.utime(raw / "batch.jsonl", (2, 2))
            for name in DASHBOARD.ANALYSIS_OUTPUTS:
                os.utime(analysis / name, (1, 1))
            self.assertTrue(DASHBOARD.analysis_needs_refresh(result))

    def test_dashboard_server_selects_newest_result(self):
        with tempfile.TemporaryDirectory() as directory:
            project = pathlib.Path(directory)
            first = project / "results" / "pqc-tls-first"
            second = project / "results" / "pqc-tls-second"
            for result in (first, second):
                (result / "analysis").mkdir(parents=True)
                for name in DASHBOARD.ANALYSIS_OUTPUTS:
                    (result / "analysis" / name).write_text("{}\n", encoding="utf-8")
            os.utime(first, (1, 1))
            os.utime(second, (2, 2))
            self.assertEqual(DASHBOARD_SERVER.newest_result_dir(project), second)
            self.assertIn("No result directory", DASHBOARD_SERVER.landing_page())

    def test_dashboard_server_ignores_run_without_analysis_outputs(self):
        with tempfile.TemporaryDirectory() as directory:
            project = pathlib.Path(directory)
            only = project / "results" / "pqc-tls-incomplete"
            (only / "raw").mkdir(parents=True)
            (only / "config.snapshot.json").write_text("{}\n", encoding="utf-8")
            # No analysis/ outputs -> not servable, even though raw evidence exists.
            self.assertIsNone(DASHBOARD_SERVER.newest_result_dir(project))

    def test_dashboard_server_serves_runs_outside_pqc_tls_naming(self):
        with tempfile.TemporaryDirectory() as directory:
            project = pathlib.Path(directory)
            # scripts/smoke-test.sh names its output smoke-test-<timestamp>,
            # which does not match the pqc-tls-* prefix other runs use.
            result = project / "results" / "smoke-test-20260730T182701Z"
            (result / "analysis").mkdir(parents=True)
            for name in DASHBOARD.ANALYSIS_OUTPUTS:
                (result / "analysis" / name).write_text("{}\n", encoding="utf-8")
            self.assertEqual(DASHBOARD_SERVER.newest_result_dir(project), result)


if __name__ == "__main__":
    unittest.main()

import importlib.util
import json
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


if __name__ == "__main__":
    unittest.main()


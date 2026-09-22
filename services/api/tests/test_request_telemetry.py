from __future__ import annotations

import unittest

from app.request_telemetry import RequestTelemetry


class RequestTelemetryTests(unittest.TestCase):
    def test_calculates_endpoint_latency_percentiles_and_error_rate(self) -> None:
        telemetry = RequestTelemetry()
        for duration in range(1, 101):
            telemetry.observe(
                "GET", "/v1/instruments/{instrument_id}", duration, 500 if duration > 95 else 200
            )

        row = telemetry.snapshot(1, set())[0]

        self.assertEqual(row["request_count"], 100)
        self.assertEqual(row["error_count"], 5)
        self.assertEqual(row["error_rate"], 5.0)
        self.assertEqual(row["p50_ms"], 50)
        self.assertEqual(row["p90_ms"], 90)
        self.assertEqual(row["p95_ms"], 95)
        self.assertEqual(row["p99_ms"], 99)

    def test_lists_known_routes_without_samples(self) -> None:
        rows = RequestTelemetry().snapshot(24, {("POST", "/v1/orders")})

        self.assertEqual(rows[0]["route"], "/v1/orders")
        self.assertEqual(rows[0]["request_count"], 0)
        self.assertIsNone(rows[0]["p99_ms"])


if __name__ == "__main__":
    unittest.main()

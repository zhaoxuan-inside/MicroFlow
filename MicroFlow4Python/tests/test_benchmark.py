import unittest

from benchmarks.local_runtime import benchmark


class BenchmarkTests(unittest.IsolatedAsyncioTestCase):
    async def test_reports_observed_active_requests_for_async_work(self):
        result = await benchmark(20, 10, delay_ms=10)
        self.assertEqual(result["requests"], 20)
        self.assertEqual(result["peak_active_requests"], 10)
        self.assertEqual(result["failures"], 0)
        self.assertEqual(result["lifecycle_records"], 60)
        self.assertGreater(result["latency_ms"]["p99"], 0)


if __name__ == "__main__":
    unittest.main()

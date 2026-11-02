import unittest
from unittest import mock

from src import saleflow_stdio as sf


class SaleflowClientTest(unittest.TestCase):
    def test_fbs_default(self):
        self.assertEqual(sf.prepare_args("wb_subject", {"subject_id": 1})["fbs"], 1)
        self.assertEqual(sf.prepare_args("wb_subject", {"subject_id": 1, "fbs": 0})["fbs"], 0)
        self.assertNotIn("fbs", sf.prepare_args("wb_check_rates", {"query": "x"}))

    def test_live_tools_not_cached(self):
        self.assertIsNone(sf.cache_get("wb_check_rates", {"query": "x"}))

    def test_guard_stops_below_reserve(self):
        c = sf.Client.__new__(sf.Client)                    # без запуска сервера
        with mock.patch.object(sf.Client, "remaining", return_value=60):
            with self.assertRaises(RuntimeError):
                c.guard(20)
            c.guard(10)


if __name__ == "__main__":
    unittest.main()

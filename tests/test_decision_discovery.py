import datetime as dt
import unittest

from src.decision import discovery_warning


class DiscoveryDeadlineTest(unittest.TestCase):
    def test_overdue(self):
        w = discovery_warning({"mode": "DISCOVERY", "discovery_until": "2026-11-09"}, dt.date(2026, 11, 10))
        self.assertIn("⛔", w)

    def test_running_and_missing(self):
        self.assertIn("осталось 7", discovery_warning({"mode": "DISCOVERY", "discovery_until": "2026-11-09"}, dt.date(2026, 11, 2)))
        self.assertIn("без discovery_until", discovery_warning({"mode": "DISCOVERY"}))
        self.assertEqual(discovery_warning({"mode": "FROZEN_TEST"}), "")


if __name__ == "__main__":
    unittest.main()

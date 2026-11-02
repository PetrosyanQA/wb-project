import glob
import unittest
from unittest import mock

from src import dossier


class DossierTest(unittest.TestCase):
    def test_rows_of_and_table(self):
        self.assertEqual(dossier.rows_of({"data": [1, 2]}), [1, 2])
        self.assertEqual(dossier.table([]), ["(пусто)"])
        self.assertIn("| a | b |", dossier.table([{"a": 1, "b": "x"}]))

    @unittest.skipUnless(glob.glob("data/processed/niche_master_*.json") and glob.glob("data/raw/evirma/*/ranges.json"),
                         "нет локальных данных (CI)")
    def test_offline_build_marks_saleflow(self):
        with mock.patch.object(dossier, "saleflow_blocks", return_value=({}, [], "Saleflow 401")), \
             mock.patch.object(dossier, "card_facts", return_value={}):
            r = dossier.build(1142, ["петличный микрофон"], 30, None)
        self.assertEqual(r["saleflow_error"], "Saleflow 401")
        self.assertIn(r["decision"], ("HOLD", "WATCHLIST", "REJECT"))     # без уникальности и КП — не выше WATCHLIST


if __name__ == "__main__":
    unittest.main()

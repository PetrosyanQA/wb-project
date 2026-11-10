from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from src.review_topics import analyze_files, render_markdown


class ReviewTopicsTests(unittest.TestCase):
    def _files(self, payloads):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        paths = []
        for sku, rows in payloads.items():
            path = Path(temp.name) / sku / "comments.json"
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
            paths.append(path)
        return paths

    def test_recurring_phrases_need_multiple_skus_and_hide_review_quotes(self):
        files = self._files({
            "sku-a": [{"valuation": 2, "text": "Сломалась ручка после недели", "date": "2026-10-01"}],
            "sku-b": [{"valuation": 1, "text": "Ручка сломалась после недели", "date": "2026-10-02"}],
            "sku-c": [{"valuation": 5, "text": "Сломалась ручка после недели", "date": "2026-10-02"}],
        })
        result = analyze_files(files, min_reviews=2, min_skus=2, today=date(2026, 11, 1))
        phrases = {row["phrase"]: row for row in result["topics"]}
        self.assertIn("сломалась ручка", phrases)
        self.assertEqual(phrases["сломалась ручка"]["sku_count"], 2)
        self.assertEqual(phrases["сломалась ручка"]["reviews"], 2)
        report = render_markdown(result)
        self.assertNotIn("после недели", report)
        self.assertNotIn("ручка сломалась", report)

    def test_since_days_excludes_old_and_undated_reviews(self):
        files = self._files({
            "sku-a": [{"rating": 1, "text": "плохой пластик", "date": "2026-10-29"},
                      {"rating": 1, "text": "плохой пластик", "date": "2026-01-01"}],
            "sku-b": [{"rating": 2, "text": "плохой пластик"}],
        })
        result = analyze_files(files, min_reviews=1, min_skus=1, since_days=7, today=date(2026, 11, 1))
        self.assertEqual(result["negative_reviews_analyzed"], 1)
        self.assertTrue(all(row["reviews"] == 1 for row in result["topics"]))

    def test_invalid_options_fail_loudly(self):
        with self.assertRaises(ValueError):
            analyze_files([], min_reviews=0)
        with self.assertRaises(ValueError):
            analyze_files([], min_rating=0)

    def test_supports_wrapped_payload_and_no_phrases(self):
        files = self._files({"sku-a": {"data": [{"valuation": 2, "text": "да плохо"}]}})
        result = analyze_files(files, min_reviews=1, min_skus=1)
        self.assertEqual(result["negative_reviews_analyzed"], 0)
        self.assertEqual(result["topics"], [])
        self.assertIn("не найдено", render_markdown(result))


if __name__ == "__main__":
    unittest.main()

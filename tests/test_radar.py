import unittest

from src.radar import summarize


def row(i, comments=0, sales=0, hours=40, promoted=False, price=1000):
    return {"id": i, "name": f"t{i}", "brand": "", "subject": "Красота / Кисти косметические", "final_price": price,
            "comments": comments, "sales": sales, "deliveryHours": hours, "promoted": promoted}


class RadarTest(unittest.TestCase):
    def test_crowded(self):
        s = summarize({"query": "q", "total": 500, "data": [row(i, comments=300, sales=5) for i in range(6)]})
        self.assertEqual(s["verdict"], "CROWDED")

    def test_cross_border_not_strong_and_no_demand(self):
        data = [row(i, comments=900, sales=0, hours=336) for i in range(10)] + [{"id": 99, "name": None}]
        s = summarize({"query": "q", "total": 40, "data": data})
        self.assertEqual((s["strong"], s["cross_border"], s["rows"]), (0, 10, 10))
        self.assertEqual(s["verdict"], "NO_DEMAND_SIGNAL")

    def test_unique_when_local_sells(self):
        s = summarize({"query": "q", "total": 30, "data": [row(1, comments=10, sales=14, promoted=True), row(2, hours=300)]})
        self.assertEqual((s["verdict"], s["promoted"], s["local_sales_sum"]), ("UNIQUE", 1, 14))


if __name__ == "__main__":
    unittest.main()

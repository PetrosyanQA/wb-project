import unittest

from src.niche_all import classify, extra_traps


class NicheAllTest(unittest.TestCase):
    base = {"rev": 20_000_000, "sellers": 100, "per_seller": 80, "buyout": 80, "price": 1500}

    def test_good_and_borderline(self):
        self.assertEqual(classify(self.base, [], 20)[0], "ХОРОШАЯ")
        self.assertEqual(classify({**self.base, "price": 538}, [], None)[0], "ПОГРАНИЧНАЯ")      # дёшево → нужен премиум
        self.assertEqual(classify({**self.base, "sellers": 10, "buyout": 50}, [], 20)[0], "СЛАБАЯ")

    def test_traps(self):
        self.assertIn("громоздкое / тяжёлое", extra_traps("Шины автомобильные", "Автотовары", "—"))
        self.assertEqual(classify(self.base, ["лето"], 20)[0], "ЛОВУШКА")


if __name__ == "__main__":
    unittest.main()

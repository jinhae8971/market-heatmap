import json, os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import collect
from universe import MARKETS


class TestUniverse(unittest.TestCase):
    def test_no_duplicate_tickers(self):
        syms = [i[0] for m in MARKETS.values() for i in m["items"]]
        self.assertEqual(len(syms), len(set(syms)))

    def test_rows_are_triples(self):
        for m in MARKETS.values():
            for item in m["items"]:
                self.assertEqual(len(item), 3, item)
                self.assertTrue(all(isinstance(x, str) and x for x in item))


class TestFetch(unittest.TestCase):
    def _with_fake(self, fast_info):
        class Fake:
            pass
        Fake.fast_info = fast_info
        orig = collect.yf.Ticker
        collect.yf.Ticker = lambda s: Fake()
        return orig

    def test_missing_fields_drop_row(self):
        orig = self._with_fake({"lastPrice": None, "previousClose": 10,
                                "marketCap": 1, "currency": "USD"})
        try:
            self.assertIsNone(collect.fetch_one(("X", "엑스", "테스트")))
        finally:
            collect.yf.Ticker = orig

    def test_change_calculation(self):
        orig = self._with_fake({"lastPrice": 110.0, "previousClose": 100.0,
                                "marketCap": 1e9, "currency": "USD"})
        try:
            r = collect.fetch_one(("X", "엑스", "테스트"))
            self.assertAlmostEqual(r["chg"], 10.0)
            self.assertEqual(r["ccy"], "USD")
        finally:
            collect.yf.Ticker = orig


class TestOutput(unittest.TestCase):
    def test_payload_shape(self):
        path = os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "docs", "heatmap.json")
        if not os.path.exists(path):
            self.skipTest("아직 수집 전")
        d = json.load(open(path, encoding="utf-8"))
        self.assertIn("markets", d)
        for code, m in d["markets"].items():
            self.assertTrue(m["items"], code)
            for it in m["items"]:
                for k in ("sym", "name", "sector", "price", "chg", "cap_usd"):
                    self.assertIn(k, it)
                self.assertGreater(it["cap_usd"], 0, it["sym"])


if __name__ == "__main__":
    unittest.main()

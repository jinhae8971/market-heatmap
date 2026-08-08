import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from providers.base import Quote, ProviderLicenseError
import providers


class TestLicenseGuard(unittest.TestCase):
    """상업 빌드에 개인용 공급자가 섞이는 사고를 코드가 막는지."""

    def tearDown(self):
        os.environ.pop("COMMERCIAL_MODE", None)
        os.environ.pop("MARKET_DATA_PROVIDER", None)

    def test_personal_provider_blocked_in_commercial_mode(self):
        os.environ["MARKET_DATA_PROVIDER"] = "yahoo"
        os.environ["COMMERCIAL_MODE"] = "1"
        with self.assertRaises(ProviderLicenseError):
            providers.get_provider()

    def test_personal_provider_allowed_in_personal_mode(self):
        os.environ["MARKET_DATA_PROVIDER"] = "yahoo"
        os.environ["COMMERCIAL_MODE"] = "0"
        self.assertEqual(providers.get_provider().name, "yahoo")

    def test_licensed_provider_requires_api_key(self):
        os.environ["MARKET_DATA_PROVIDER"] = "polygon"
        os.environ.pop("POLYGON_API_KEY", None)
        with self.assertRaises(ProviderLicenseError):
            providers.get_provider()

    def test_unknown_provider_rejected(self):
        os.environ["MARKET_DATA_PROVIDER"] = "nonexistent"
        with self.assertRaises(ValueError):
            providers.get_provider()


class TestQuote(unittest.TestCase):
    def test_change_pct(self):
        q = Quote("X", 110.0, 100.0, 1e9, "USD")
        self.assertAlmostEqual(q.change_pct, 10.0)

    def test_zero_prev_close_is_safe(self):
        self.assertEqual(Quote("X", 110.0, 0.0, None, "USD").change_pct, 0.0)


if __name__ == "__main__":
    unittest.main()

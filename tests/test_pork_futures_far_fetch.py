import unittest
from unittest.mock import patch

import pandas as pd

from download_history import fetch_pork_futures_far


class PorkFuturesFarFetchTest(unittest.TestCase):
    def test_fetch_pork_futures_far_normalizes_basis_frame(self):
        raw = pd.DataFrame({
            "date": ["20240506", "20240507"],
            "spot_price": [14880.0, 14870.0],
            "dominant_contract": ["lh2409", "lh2409"],
            "dominant_contract_price": [17615.0, 17625.0],
            "dom_basis": [2735.0, 2755.0],
            "dom_basis_rate": [0.183804, 0.185272],
        })
        with patch("download_history.ak.futures_spot_price_daily", return_value=raw):
            df = fetch_pork_futures_far()

        self.assertIsNotNone(df)
        self.assertEqual(list(df.columns), ["date", "close", "contract", "spot_price", "basis", "basis_rate", "source"])
        self.assertEqual(df["close"].tolist(), [17615.0, 17625.0])
        self.assertEqual(df["contract"].tolist(), ["lh2409", "lh2409"])
        self.assertTrue(df["source"].iloc[0].startswith("akshare.futures_spot_price_daily"))


if __name__ == "__main__":
    unittest.main()

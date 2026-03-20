import unittest

import pandas as pd

from config_loader import get_factor_config, load_config
from report import metrics


class ConfigLoaderRegressionTests(unittest.TestCase):
    def test_load_config_defaults_to_existing_double_ma_file(self):
        cfg = load_config(None)

        self.assertEqual(cfg["_resolved"]["config_name"], "double_ma")
        self.assertTrue(cfg["_resolved"]["data_path"].endswith("TSLA_25Y_yFinance.csv"))

    def test_get_factor_config_rejects_unregistered_factor_type(self):
        with self.assertRaises(ValueError):
            get_factor_config({"factor": {"type": "single_ma", "params": {}}})


class MetricsRegressionTests(unittest.TestCase):
    def test_calculate_metrics_prefers_realized_trade_pnl(self):
        df = pd.DataFrame(
            {
                "Strategy_Equity": [1.0, 1.02, 1.01],
                "Strategy_Return": [0.0, 0.02, -0.01],
                "Market_Equity": [1.0, 1.01, 1.03],
                "Market_Return": [0.0, 0.01, 0.0198019802],
                "Position": [0, 1, 0],
            },
            index=pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03"]),
        )
        trades = [
            {"action": "买入", "pnl": None},
            {"action": "卖出", "pnl": -100.0},
        ]

        result = metrics.calculate_metrics(df, trades=trades)

        self.assertEqual(result["总交易次数"], 1)
        self.assertEqual(result["盈利交易次数"], 0)
        self.assertEqual(result["亏损交易次数"], 1)


if __name__ == "__main__":
    unittest.main()

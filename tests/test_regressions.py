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

    def test_calculate_metrics_includes_max_trade_drawdown(self):
        df = pd.DataFrame(
            {
                "Strategy_Equity": [1.0, 1.02, 1.01, 1.03],
                "Strategy_Return": [0.0, 0.02, -0.01, 0.0198019802],
                "Market_Equity": [1.0, 1.01, 1.0, 1.02],
                "Market_Return": [0.0, 0.01, -0.00990099, 0.02],
                "Position": [0, 1, 0, 1],
            },
            index=pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04"]),
        )
        trades = [
            {"action": "买入", "pnl": None},
            {"action": "卖出", "pnl": -50.0, "pnl_pct": -5.0, "cum_pnl_pct": -5.0},
            {"action": "买入", "pnl": None},
            {"action": "卖出", "pnl": -20.0, "pnl_pct": -2.0, "cum_pnl_pct": -7.0},
            {"action": "买入", "pnl": None},
            {"action": "卖出", "pnl": 30.0, "pnl_pct": 3.0, "cum_pnl_pct": -4.0},
            {"action": "买入", "pnl": None},
            {"action": "卖出", "pnl": -60.0, "pnl_pct": -6.0, "cum_pnl_pct": -10.0},
        ]

        result = metrics.calculate_metrics(df, trades=trades)

        self.assertIn("最大交易回撤", result)
        # 连续亏损段口径：[-5%, -2%, +3%, -6%] -> max(7%, 6%) = 7%，回撤按负值返回
        self.assertAlmostEqual(result["最大交易回撤"], -0.07, places=8)


if __name__ == "__main__":
    unittest.main()

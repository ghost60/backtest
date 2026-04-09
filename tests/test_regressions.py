import unittest

import pandas as pd

from config_loader import get_capital_params, get_factor_config, load_config
from engine.single_asset import run_single_asset
from engine.unified_account_simple import run_unified_account_simple
from factor.factor_btcdom import run as run_btcdom_replica
from report import metrics


class ConfigLoaderRegressionTests(unittest.TestCase):
    def test_load_config_defaults_to_existing_double_ma_file(self):
        cfg = load_config(None)

        self.assertEqual(cfg["_resolved"]["config_name"], "double_ma")
        self.assertTrue(cfg["_resolved"]["data_path"].endswith("TSLA_25Y_yFinance.csv"))

    def test_get_factor_config_rejects_unregistered_factor_type(self):
        with self.assertRaises(ValueError):
            get_factor_config({"factor": {"type": "single_ma", "params": {}}})

    def test_get_capital_params_accepts_margin_currency_usd_by_default(self):
        params = get_capital_params({"capital": {"initial": 1000}})
        self.assertEqual(params["margin_currency"], "USD")
        self.assertEqual(params["margin_fx_to_usd"], 1.0)

    def test_get_capital_params_requires_fx_for_non_usd_margin(self):
        with self.assertRaises(ValueError):
            get_capital_params({"capital": {"initial": 1.0, "margin_currency": "BTC"}})

    def test_get_capital_params_allows_binance_fx_source_without_static_fx(self):
        params = get_capital_params(
            {
                "capital": {
                    "initial": 1.0,
                    "margin_currency": "BTC",
                    "margin_fx_source": "binance",
                    "margin_symbol": "BTCUSDT",
                    "margin_fx_interval": "1d",
                }
            }
        )
        self.assertEqual(params["margin_fx_source"], "binance")
        self.assertEqual(params["margin_symbol"], "BTCUSDT")
        self.assertIsNone(params["margin_fx_to_usd"])


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


class MarginSettlementRegressionTests(unittest.TestCase):
    def test_non_usd_margin_keeps_coin_principal_and_adds_pnl_in_coin(self):
        idx = pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"])
        df = pd.DataFrame(
            {
                "Open": [100.0, 100.0, 110.0, 100.0, 100.0],
                "Close": [100.0, 100.0, 110.0, 100.0, 100.0],
            },
            index=idx,
        )
        buy_signal = pd.Series([True, False, False, True, False], index=idx)
        sell_signal = pd.Series([False, True, False, False, False], index=idx)
        fx_map = {
            idx[0]: 10_000.0,
            idx[1]: 20_000.0,
            idx[2]: 20_000.0,
            idx[3]: 20_000.0,
            idx[4]: 20_000.0,
        }

        _, trades = run_single_asset(
            df=df,
            buy_signal=buy_signal,
            sell_signal=sell_signal,
            entry_delay=0,
            exit_delay=0,
            initial_capital=1.0,
            position_ratio=1.0,
            max_leverage=1.0,
            margin_currency="BTC",
            margin_fx_to_usd=10_000.0,
            margin_fx_getter=lambda dt: fx_map[dt],
            margin_settlement_mode="principal_plus_pnl",
        )

        self.assertEqual(len(trades), 3)
        buy_trade, sell_trade, second_buy_trade = trades

        self.assertEqual(buy_trade["action"], "买入")
        self.assertEqual(sell_trade["action"], "卖出")
        self.assertEqual(second_buy_trade["action"], "买入")
        self.assertEqual(buy_trade["shares"], 100)
        # 非 USD 保证金下，1 BTC 本金始终保留；本次 1,000 USD 利润按平仓汇率折算成 0.05 BTC。
        self.assertAlmostEqual(sell_trade["cash"], 1.05, places=8)
        self.assertAlmostEqual(sell_trade["pnl"], 0.05, places=8)
        # 下一次买入可继续用 1.05 BTC 作为抵押，按买入时汇率折算出等值 USD 名义仓位。
        self.assertEqual(second_buy_trade["shares"], 210)


class BtcdomReplicaRegressionTests(unittest.TestCase):
    def test_btcdom_replica_combines_long_btc_and_short_alt_basket(self):
        idx = pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03"])
        btc_df = pd.DataFrame(
            {
                "Open": [100.0, 100.0, 110.0],
                "Close": [100.0, 110.0, 121.0],
            },
            index=idx,
        )
        alt_df = pd.DataFrame(
            {
                "Open": [100.0, 100.0, 90.0],
                "Close": [100.0, 90.0, 81.0],
            },
            index=idx,
        )

        result, trades = run_btcdom_replica(
            btc_df,
            [alt_df],
            [1.0],
            initial_capital=100.0,
            long_weight=0.5,
            short_weight=0.5,
            alt_names=["ALT"],
        )

        self.assertAlmostEqual(result.loc[idx[1], "Strategy_Return"], 0.10, places=8)
        self.assertAlmostEqual(result.loc[idx[2], "Strategy_Return"], 0.10, places=8)
        self.assertAlmostEqual(result.loc[idx[2], "Total_Value"], 121.0, places=8)
        self.assertEqual(trades[-1]["action"], "平仓BTCDOM组合")
        self.assertAlmostEqual(trades[-1]["pnl"], 21.0, places=8)


class UnifiedAccountSimpleRegressionTests(unittest.TestCase):
    def test_unified_account_uses_btc_as_collateral_without_spending_it(self):
        idx = pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03"])
        df = pd.DataFrame(
            {
                "Open": [100.0, 100.0, 110.0],
                "Close": [100.0, 110.0, 110.0],
            },
            index=idx,
        )
        btc_price = pd.Series([10_000.0, 10_000.0, 20_000.0], index=idx)

        result, trades = run_unified_account_simple(
            df=df,
            buy_signal=pd.Series([True, False, False], index=idx),
            sell_signal=pd.Series([False, True, False], index=idx),
            collateral_price_usd=btc_price,
            initial_capital=1.0,
            initial_margin_currency="BTC",
            position_ratio=1.0,
            max_leverage=1.0,
            debt_limit_ratio=1.0,
        )

        self.assertEqual(len(trades), 2)
        self.assertEqual(trades[0]["action"], "买入")
        self.assertEqual(trades[1]["action"], "卖出")
        self.assertEqual(trades[0]["shares"], 100)
        self.assertAlmostEqual(result.loc[idx[1], "Cash_BTC"], 1.0, places=8)
        self.assertAlmostEqual(result.loc[idx[1], "Cash_USD"], 0.0, places=8)
        self.assertAlmostEqual(result.loc[idx[2], "Cash_USD"], 0.0, places=8)
        self.assertAlmostEqual(result.loc[idx[2], "Cash_BTC"], 1.05, places=8)
        self.assertAlmostEqual(result.loc[idx[2], "Total_Value"], 21_000.0, places=8)

    def test_unified_account_sells_btc_to_cover_loss_after_repaying_debt(self):
        idx = pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03"])
        df = pd.DataFrame(
            {
                "Open": [100.0, 100.0, 90.0],
                "Close": [100.0, 90.0, 90.0],
            },
            index=idx,
        )
        btc_price = pd.Series([10_000.0, 10_000.0, 20_000.0], index=idx)

        result, trades = run_unified_account_simple(
            df=df,
            buy_signal=pd.Series([True, False, False], index=idx),
            sell_signal=pd.Series([False, True, False], index=idx),
            collateral_price_usd=btc_price,
            initial_capital=1.0,
            initial_margin_currency="BTC",
            position_ratio=1.0,
            max_leverage=1.0,
            debt_limit_ratio=1.0,
        )

        self.assertEqual(len(trades), 2)
        self.assertAlmostEqual(trades[1]["pnl_usd"], -1000.0, places=8)
        self.assertAlmostEqual(result.loc[idx[2], "Cash_USD"], 0.0, places=8)
        self.assertAlmostEqual(result.loc[idx[2], "Cash_BTC"], 0.95, places=8)
        self.assertAlmostEqual(result.loc[idx[2], "Total_Value"], 19_000.0, places=8)

    def test_unified_account_only_switches_collateral_when_flat(self):
        idx = pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04"])
        df = pd.DataFrame(
            {
                "Open": [100.0, 100.0, 100.0, 100.0],
                "Close": [100.0, 100.0, 100.0, 100.0],
            },
            index=idx,
        )
        btc_price = pd.Series([10_000.0, 12_000.0, 12_000.0, 12_000.0], index=idx)
        hold_btc = pd.Series([True, False, False, False], index=idx)

        _, trades = run_unified_account_simple(
            df=df,
            buy_signal=pd.Series([True, False, False, False], index=idx),
            sell_signal=pd.Series([False, True, False, False], index=idx),
            collateral_price_usd=btc_price,
            initial_capital=1.0,
            initial_margin_currency="BTC",
            collateral_hold_btc=hold_btc,
            log_switches=True,
        )

        actions = [t["action"] for t in trades]
        self.assertEqual(actions, ["买入", "卖出", "切换统一账户为USD抵押"])


if __name__ == "__main__":
    unittest.main()

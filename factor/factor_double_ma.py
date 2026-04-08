# -*- coding: utf-8 -*-
"""
Double MA 因子计算模块

功能：
- 计算短均线上穿长均线（金叉），且可选「收盘价 > 短均线」过滤，支持入场延迟 N 根 K
- 计算短均线在长均线下方（死叉）

用法示例
--------
>>> from backtest import data_loader
>>> from backtest import factor_double_ma
>>> df_spy = data_loader.load_data("data/SPY_25Y_yFinance.csv")
>>> df_spy = factor_double_ma.calculate_double_ma_factors(df_spy, ma_short=5, ma_long=30, use_price_filter=True)
>>> df_spy[["MA5", "MA30", "MA_Buy_Signal", "MA_Sell_Signal"]].tail()
"""

import pandas as pd


def calculate_double_ma_factors(
    df: pd.DataFrame,
    ma_short: int = 5,
    ma_long: int = 30,
    use_price_filter: bool = True,
) -> pd.DataFrame:
    """
    计算 Double MA 因子与信号。

    结果中会新增列：
    - MA5 / MA30：短/长均线
    - MA_Buy_Signal：是否满足买入信号（金叉 + 可选 Close>MA）
    - MA_Sell_Signal：是否满足卖出信号（死叉）
    """
    df = df.copy()
    # 均线（列名固定为 MA5/MA30，与周期一致时便于阅读），保留三位小数
    df["MA5"] = df["Close"].rolling(window=ma_short).mean().round(3)
    df["MA30"] = df["Close"].rolling(window=ma_long).mean().round(3)

    # 金叉：当前短>=长，前一根短<长
    cross_long = (df["MA5"] >= df["MA30"]) & (df["MA5"].shift(1) < df["MA30"].shift(1))
    # 死叉：当前短<长，前一根短>=长
    sell_signal = (df["MA5"] < df["MA30"]) & (df["MA5"].shift(1) >= df["MA30"].shift(1))
    # 入场过滤：保持为布尔序列，避免 use_price_filter=False 时出现标量 True
    price_ok = df["Close"] > df["MA5"] if use_price_filter else pd.Series(True, index=df.index)
    buy_signal = cross_long & price_ok

    df["MA_Buy_Signal"] = buy_signal
    df["MA_Sell_Signal"] = sell_signal
    return df

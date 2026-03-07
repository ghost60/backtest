# -*- coding: utf-8 -*-
"""
Single MA 因子计算模块

功能：
- 计算单根均线，并以「收盘价上穿均线」为买入信号、「收盘价下穿均线」为卖出信号
- 可选「收盘价 > 均线」过滤（仅在上穿当日要求 Close > MA）

用法示例
--------
>>> from backtest import data_loader
>>> from backtest import factor_single_ma
>>> df_spy = data_loader.load_data("data/SPY_25Y_yFinance.csv")
>>> df_spy = factor_single_ma.calculate_single_ma_factors(df_spy, ma_period=20, use_price_filter=True)
>>> df_spy[["MA20", "MA_Buy_Signal", "MA_Sell_Signal"]].tail()
"""

import pandas as pd


def calculate_single_ma_factors(
    df: pd.DataFrame,
    ma_period: int = 20,
    use_price_filter: bool = True,
) -> pd.DataFrame:
    """
    计算 Single MA 因子与信号。

    结果中会新增列：
    - MA{period}：单均线（列名随周期变化，如 MA20）
    - MA_Buy_Signal：是否满足买入信号（收盘价上穿均线 + 可选 Close>MA）
    - MA_Sell_Signal：是否满足卖出信号（收盘价下穿均线）
    """
    df = df.copy()
    ma_col = f"MA{ma_period}"
    df[ma_col] = df["Close"].rolling(window=ma_period).mean().round(3)

    # 上穿：当前 Close > MA，前一根 Close <= 前一根 MA
    cross_up = (df["Close"] > df[ma_col]) & (df["Close"].shift(1) <= df[ma_col].shift(1))
    # 下穿：当前 Close < MA，前一根 Close >= 前一根 MA
    cross_down = (df["Close"] < df[ma_col]) & (df["Close"].shift(1) >= df[ma_col].shift(1))
    price_ok = df["Close"] > df[ma_col] if use_price_filter else pd.Series(True, index=df.index)
    buy_signal = cross_up & price_ok

    df["MA_Buy_Signal"] = buy_signal
    df["MA_Sell_Signal"] = cross_down
    return df

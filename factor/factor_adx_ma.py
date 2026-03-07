# -*- coding: utf-8 -*-
"""
ADX + Moving Average 因子模块（对齐 TradingView ADX_Moving_AVG_Strategy.pine）

功能：
- 计算 ADX（DI/ADX 周期可配置）
- 长均线过滤可选「本标的」或「其他资产」：
  - 本标的：SMA(close, moving_avg_day)，入场 Close>长均线，出场 Close<长均线
  - 其他资产：SMA(other_close, moving_avg_day)，入场 selected_close>selected_ma，出场 selected_close<selected_ma
- 可选 SMA14 过滤：sma_close_14 > sma_close_14[14]（始终用本标的的 14 日均线）

与 Pine 完全一致：
- use_other_asset / symbol_choice → other_asset_df（由 backtest 按 other_asset_path 加载）
- adx_threshold, moving_avg_day, adxlen/dilen, if_sma14_filtered → 同名或对应参数
"""

from __future__ import annotations

import pandas as pd

from . import factor_adx


def calculate_adx_ma_factors(
    df: pd.DataFrame,
    adx_threshold: float = 26,
    moving_avg_day: int = 110,
    adx_period: int = 14,
    use_sma14_filter: bool = True,
    use_other_asset: bool = False,
    other_asset_df: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """
    计算 ADX+MA 因子与买卖信号（与 TV ADX_Moving_AVG_Strategy 一致）。

    当 use_other_asset=True 且 other_asset_df 不为 None 时，长均线及过滤使用其他资产；
    否则使用本标的的 close 与长均线。

    结果中会新增列：
    - ADX, +DI, -DI：ADX 指标（本标的）
    - MA{moving_avg_day}：长均线（本标的或仅当 use_other_asset 时为本标的 110 日，用于展示）
    - MA_Buy_Signal / MA_Sell_Signal：买卖信号
    """
    df = df.copy()

    # 1. ADX（Pine: 始终用本标的的 K 线）
    df = factor_adx.calculate_adx_factors(
        df, period=adx_period, high_col="High", low_col="Low", close_col="Close"
    )
    adx = df["ADX"]

    # 2. 长均线：本标的 110 日（Pine: sma_close_225 / selected_ma）
    ma_long_col = f"MA{moving_avg_day}"
    df[ma_long_col] = df["Close"].rolling(window=moving_avg_day).mean().round(3)

    # 3. 是否用其他资产做长均线过滤（Pine: use_other_asset, selected_close, selected_ma）
    if use_other_asset and other_asset_df is not None and len(other_asset_df) > 0:
        other_close = other_asset_df["Close"].reindex(df.index, method="ffill")
        other_ma = other_asset_df["Close"].rolling(window=moving_avg_day).mean()
        other_ma_aligned = other_ma.reindex(df.index, method="ffill")
        price_above_ma = other_close > other_ma_aligned
        price_below_ma = other_close < other_ma_aligned
    else:
        price_above_ma = df["Close"] > df[ma_long_col]
        price_below_ma = df["Close"] < df[ma_long_col]

    # 4. SMA14 过滤（Pine: sma_close_14 > sma_close_14[14]，始终本标的）
    if use_sma14_filter:
        df["MA14"] = df["Close"].rolling(window=14).mean().round(3)
        sma14_ok = df["MA14"] > df["MA14"].shift(14)
    else:
        sma14_ok = pd.Series(True, index=df.index)

    # 5. 入场：ADX 上穿阈值 且 长均线过滤 且（可选）SMA14
    adx_cross_up = (adx > adx_threshold) & (adx.shift(1) <= adx_threshold)
    buy_signal = adx_cross_up & price_above_ma & sma14_ok

    # 6. 出场：ADX 下穿阈值 或 跌破长均线
    adx_cross_down = (adx < adx_threshold) & (adx.shift(1) >= adx_threshold)
    sell_signal = adx_cross_down | price_below_ma

    df["MA_Buy_Signal"] = buy_signal
    df["MA_Sell_Signal"] = sell_signal
    return df

# -*- coding: utf-8 -*-
"""
ADX + Double MA 组合因子模块

策略逻辑：
- 入场：短均线上穿长均线（金叉）且 ADX 上穿阈值（趋势足够强）
- 出场：短均线下穿长均线（死叉）或 ADX 下穿阈值（趋势减弱）

参数说明
--------
ma_short        : 短均线周期，默认 5
ma_long         : 长均线周期，默认 30
adx_threshold   : ADX 入场/出场阈值，默认 25
adx_period      : ADX/DI 计算周期，默认 14
use_price_filter: 是否要求 Close > 短均线才允许入场，默认 True
combine_mode    : 信号合并模式
                  "and"  - 入场需同时满足金叉 AND ADX 上穿（更严格）
                  "cross_and_adx_level" - 入场需金叉 AND ADX > 阈值（ADX 已在阈值以上即可）
"""

from __future__ import annotations

import pandas as pd

from . import factor_adx


def calculate_adx_double_ma_factors(
    df: pd.DataFrame,
    ma_short: int = 5,
    ma_long: int = 30,
    adx_threshold: float = 25,
    adx_period: int = 14,
    use_price_filter: bool = True,
    combine_mode: str = "cross_and_adx_level",
) -> pd.DataFrame:
    """
    计算 ADX + Double MA 组合因子与买卖信号。

    结果中会新增列：
    - MA{ma_short} / MA{ma_long}：短/长均线
    - ADX, +DI, -DI：ADX 指标
    - MA_Buy_Signal / MA_Sell_Signal：组合信号
    """
    df = df.copy()

    # ── 1. 双均线 ──────────────────────────────────────────
    short_col = f"MA{ma_short}"
    long_col = f"MA{ma_long}"
    df[short_col] = df["Close"].rolling(window=ma_short).mean().round(3)
    df[long_col] = df["Close"].rolling(window=ma_long).mean().round(3)

    # 金叉：当前 短>=长，前一根 短<长
    cross_up = (df[short_col] >= df[long_col]) & (df[short_col].shift(1) < df[long_col].shift(1))
    # 死叉：当前 短<长，前一根 短>=长
    cross_down = (df[short_col] < df[long_col]) & (df[short_col].shift(1) >= df[long_col].shift(1))

    # 入场价格过滤：Close > 短均线
    price_ok = (
        df["Close"] > df[short_col] if use_price_filter
        else pd.Series(True, index=df.index)
    )

    # ── 2. ADX ─────────────────────────────────────────────
    df = factor_adx.calculate_adx_factors(
        df, period=adx_period, high_col="High", low_col="Low", close_col="Close"
    )
    adx = df["ADX"]

    # ADX 上穿阈值（金叉式穿越：前一根 < 阈值，当前根 > 阈值）
    adx_cross_up = (adx > adx_threshold) & (adx.shift(1) < adx_threshold)
    # ADX 下穿阈值（死叉式穿越：前一根 > 阈值，当前根 < 阈值）
    adx_cross_down = (adx < adx_threshold) & (adx.shift(1) > adx_threshold)
    # ADX 持续高于阈值（用于 cross_and_adx_level 模式）
    adx_above = adx > adx_threshold

    # ── 3. 组合信号 ─────────────────────────────────────────
    if combine_mode == "and":
        # 严格模式：金叉 AND ADX 上穿阈值（两个事件需同一根K线发生）
        buy_signal = cross_up & adx_cross_up & price_ok
    else:
        # 宽松模式（默认）：金叉 AND ADX 已在阈值以上（更容易触发）
        buy_signal = cross_up & adx_above & price_ok

    # 出场：死叉 OR ADX 下穿阈值（任一满足即出场）
    sell_signal = cross_down | adx_cross_down

    df["MA_Buy_Signal"] = buy_signal
    df["MA_Sell_Signal"] = sell_signal
    return df

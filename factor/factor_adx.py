#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
ADX 因子计算模块

功能：
- 在任意标的的 OHLC 数据上计算 ADX 指标（默认为 21 周期）
- 支持配置周期长度与列名，既可以用于 TSLA，也可以用于 SPY 等其他标的

用法示例
--------
>>> from backtest import data_loader
>>> from backtest import factor_adx
>>> df_spy = data_loader.load_data("data/SPY_25Y_yFinance.csv")
>>> df_spy = factor_adx.calculate_adx_factors(df_spy, period=21)
>>> df_spy[["ADX", "+DI", "-DI"]].tail()

如需对 TSLA 计算，则只需换成 TSLA 的 CSV 路径即可。
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def calculate_adx_factors(
    df: pd.DataFrame,
    period: int = 21,
    high_col: str = "High",
    low_col: str = "Low",
    close_col: str = "Close",
    adx_col: str = "ADX",
    plus_di_col: str = "+DI",
    minus_di_col: str = "-DI",
) -> pd.DataFrame:
    """
    在给定的 OHLC 行情数据上计算 ADX / +DI / -DI 指标。

    参数
    ----
    df : pd.DataFrame
        需至少包含 High / Low / Close（列名可通过参数指定）。
    period : int, default 21
        ADX 平滑周期，一般取 14 或 21，这里默认为 21。
    high_col, low_col, close_col : str
        高 / 低 / 收盘价格列名。
    adx_col : str, default "ADX"
        计算得到的 ADX 列名。
    plus_di_col, minus_di_col : str
        计算得到的 +DI / -DI 列名。

    返回
    ----
    pd.DataFrame
        原 df 的拷贝，新增 ADX / +DI / -DI 三列。
    """
    df = df.copy()

    high = df[high_col]
    low = df[low_col]
    close = df[close_col]

    # True Range (TR)
    prev_close = close.shift(1)
    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    # +DM / -DM
    up_move = high.diff()
    down_move = -low.diff()

    plus_dm = np.where(
        (up_move > down_move) & (up_move > 0),
        up_move,
        0.0,
    )
    minus_dm = np.where(
        (down_move > up_move) & (down_move > 0),
        down_move,
        0.0,
    )

    plus_dm = pd.Series(plus_dm, index=df.index)
    minus_dm = pd.Series(minus_dm, index=df.index)

    # 使用 Wilder EMA 近似的平滑方式：等价于 alpha = 1 / period 的 EMA
    atr = tr.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    plus_dm_smooth = plus_dm.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    minus_dm_smooth = minus_dm.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()

    # DI
    plus_di = 100.0 * (plus_dm_smooth / atr)
    minus_di = 100.0 * (minus_dm_smooth / atr)

    # DX 与 ADX
    di_sum = plus_di + minus_di
    di_diff = (plus_di - minus_di).abs()

    dx = 100.0 * di_diff / di_sum.replace(0, np.nan)
    adx = dx.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()

    df[plus_di_col] = plus_di
    df[minus_di_col] = minus_di
    df[adx_col] = adx

    return df

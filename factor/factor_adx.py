#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
ADX 因子计算模块

功能：
- 在任意标的的 OHLC 数据上计算 ADX 指标（默认为 14 周期，与 Pine Script adxlen=14/dilen=14 一致）
- 支持配置周期长度与列名，既可以用于 TSLA，也可以用于 SPY 等其他标的

用法示例
--------
>>> from backtest import data_loader
>>> from backtest import factor_adx
>>> df_spy = data_loader.load_data("data/SPY_25Y_yFinance.csv")
>>> df_spy = factor_adx.calculate_adx_factors(df_spy, period=14)
>>> df_spy[["ADX", "+DI", "-DI"]].tail()

如需对 TSLA 计算，则只需换成 TSLA 的 CSV 路径即可。
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def _rma(series: pd.Series, period: int) -> pd.Series:
    """
    完全仿 Pine Script 的 ta.rma（Wilder 平滑）实现。

    规则（与 Pine 官方一致）：
    - 从第一个非 NaN 开始计算；
    - 第一个有效值所在窗口（len=period）的 SMA 作为初始值；
    - 之后按 Wilder 递推：r[i] = (r[i-1] * (period - 1) + x[i]) / period；
    - 在未满足窗口长度之前返回 NaN。
    """
    values = pd.to_numeric(series, errors="coerce").to_numpy(dtype=float)
    n = len(values)
    out = np.full(n, np.nan, dtype=float)

    if n == 0 or period <= 0:
        return pd.Series(out, index=series.index)

    isnan = np.isnan(values)
    # 第一个非 NaN 的位置
    first = np.argmax(~isnan) if (~isnan).any() else -1
    if first < 0:
        return pd.Series(out, index=series.index)

    start = first + period - 1
    if start >= n:
        # 数据长度不足以形成一个完整窗口
        return pd.Series(out, index=series.index)

    window = values[first : start + 1]
    r = float(np.nanmean(window))
    out[start] = r

    for i in range(start + 1, n):
        v = values[i]
        if np.isnan(v):
            # Pine 中 rma(na) 会继承前值
            out[i] = r
            continue
        r = (r * (period - 1) + v) / period
        out[i] = r

    return pd.Series(out, index=series.index)


def calculate_adx_factors(
    df: pd.DataFrame,
    period: int = 14,
    high_col: str = "High",
    low_col: str = "Low",
    close_col: str = "Close",
    adx_col: str = "ADX",
    plus_di_col: str = "+DI",
    minus_di_col: str = "-DI",
) -> pd.DataFrame:
    """
    在给定的 OHLC 行情数据上计算 ADX / +DI / -DI 指标（完全对齐 Pine dirmov/ADX 公式）。

    参数
    ----
    df : pd.DataFrame
        需至少包含 High / Low / Close（列名可通过参数指定）。
    period : int, default 21
        ADX 平滑周期（同时用于 +DI/-DI 与 ADX 的 Wilder RMA），
        通常取 14 或 21。
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

    # True Range (Pine: ta.tr)
    prev_close = close.shift(1)
    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    # +DM / -DM（Pine: dirmov 中的 plusDM / minusDM）
    # Pine: plusDM = na(up) ? na : (up > down and up > 0 ? up : 0)
    # 第一行（diff 为 NaN）保持 NaN，其余不满足条件则为 0
    up = high.diff()
    down = -low.diff()

    # 先用 0 填充，再把第一行（NaN）结果保持 NaN，最后把满足条件的设为实际值
    plus_dm = up.where(up.isna(), 0.0)   # NaN 位置保持 NaN，其余置 0
    minus_dm = down.where(down.isna(), 0.0)

    mask_plus = (up > down) & (up > 0)
    mask_minus = (down > up) & (down > 0)

    plus_dm = plus_dm.where(~mask_plus, up)    # 满足条件的改为 up
    minus_dm = minus_dm.where(~mask_minus, down)  # 满足条件的改为 down

    # RMA 平滑（Pine: ta.rma）
    atr = _rma(tr, period)
    plus_dm_smooth = _rma(plus_dm, period)
    minus_dm_smooth = _rma(minus_dm, period)

    # DI（Pine: plus/minus = fixnan(100 * ta.rma(plusDM/minusDM, len) / truerange)）
    # fixnan 语义：用前一个有效值向前填充（forward fill），非用 0 替代
    plus_di = (100.0 * plus_dm_smooth / atr).ffill().fillna(0.0)
    minus_di = (100.0 * minus_dm_smooth / atr).ffill().fillna(0.0)

    # DX 与 ADX（Pine: adx = 100 * ta.rma(|plus - minus| / (sum == 0 ? 1 : sum), adxlen)）
    di_sum = plus_di + minus_di
    di_diff = (plus_di - minus_di).abs()

    dx = 100.0 * di_diff / di_sum.replace(0, np.nan)
    adx = _rma(dx, period)

    df[plus_di_col] = plus_di
    df[minus_di_col] = minus_di
    df[adx_col] = adx

    return df

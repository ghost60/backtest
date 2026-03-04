# -*- coding: utf-8 -*-
"""
数据加载模块

职责：
- 从 CSV 读取行情（需含 Date, Close 等列）
- 统一日期为 UTC、按日期排序、以 Date 为索引
- 按 start_date / end_date 截取回测区间
"""

import pandas as pd


def load_data(path, start_date=None, end_date=None):
    """
    加载数据并做基础处理。

    参数
    ----
    path : str
        CSV 路径，需包含 Date, Open, High, Low, Close 等列。
    start_date : str, optional
        回测开始日期，如 "2011-01-01"。
    end_date : str, optional
        回测结束日期，如 "2025-12-31"。

    返回
    ----
    pd.DataFrame
        索引为 DatetimeIndex(UTC)，已按日期排序；可选列 Close 等。
    """
    df = pd.read_csv(path)
    # 日期统一为 UTC，并设为索引
    df["Date"] = pd.to_datetime(df["Date"], utc=True)
    df.sort_values("Date", inplace=True)
    df.set_index("Date", inplace=True)

    # 时间范围过滤
    if start_date:
        df = df[df.index >= pd.to_datetime(start_date, utc=True)]
    if end_date:
        df = df[df.index <= pd.to_datetime(end_date, utc=True)]

    return df

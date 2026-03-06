#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
通用单标的撮合与资金管理引擎（Single Asset Engine）

职责：
- 接收已经算好的买入 / 卖出信号（因子层负责生成）
- 按给定的入场 / 出场延迟、初始资金与仓位比例，执行逐 K 线撮合
- 产出：
  - Position / Market_Return / Strategy_Return 列
  - 详细交易清单 trades（含每笔盈亏与累计盈亏）

注意：
- 本模块不关心具体因子形态，只要求传入对齐的布尔序列 buy_signal / sell_signal
- 默认成交价使用当根 K 线的开盘价列 "Open"
"""

from __future__ import annotations

from typing import List, Dict, Tuple

import pandas as pd


def run_single_asset(
    df: pd.DataFrame,
    buy_signal: pd.Series,
    sell_signal: pd.Series,
    entry_delay: int = 0,
    exit_delay: int = 0,
    initial_capital: float = 100000,
    position_ratio: float = 1.0,
    price_col: str = "Open",
) -> Tuple[pd.DataFrame, List[Dict]]:
    """
    通用单标的撮合引擎。

    参数
    ----
    df : pd.DataFrame
        行情数据，需至少包含 Close 与 price_col（默认 "Open"），索引为日期。
    buy_signal, sell_signal : pd.Series[bool]
        买入 / 卖出信号布尔序列，索引需与 df 对齐。
    entry_delay : int
        入场延迟 K 数，语义与 MA 策略相同：
        - 0 表示“信号后第 1 根 K 线”入场
        - N 表示“信号后第 N+1 根 K 线”入场
    exit_delay : int
        出场延迟 K 数，语义与 entry_delay 类似。
    initial_capital : float
        初始资金。
    position_ratio : float
        持仓比例（0~1），例如 1.0=全仓，0.5=半仓。
    price_col : str
        撮合成交价所使用的列名，默认 "Open"。

    返回
    ----
    tuple
        (df_with_results, trades)
        - df_with_results: 在原 df 基础上增加 Position / Market_Return / Strategy_Return
        - trades: 交易清单列表
    """
    df = df.copy()

    position = 0
    positions: List[int] = []
    trades: List[Dict] = []

    signal_wait = -1       # 金叉后等待的 K 数：-1=无信号，0=信号当根，1=信号后第1根...
    exit_signal_wait = -1  # 死叉后等待的 K 数

    entry_price = 0.0
    trade_id = 0
    shares = 0
    cash = float(initial_capital)

    for i in range(len(df)):
        date = df.index[i]
        price = float(df[price_col].iloc[i])

        # 1. 死叉信号检测（仅持仓时计数）
        if bool(sell_signal.iloc[i]):
            if position == 1:
                exit_signal_wait = 0
        elif exit_signal_wait >= 0 and position == 1:
            exit_signal_wait += 1

        # 2. 出场撮合：满足延迟条件 + 有持仓
        if exit_signal_wait >= exit_delay + 1 and position == 1:
            exit_signal_wait = -1
            position = 0

            pnl = round((price - entry_price) * shares, 2)
            cash += shares * price
            pnl_pct = round((price - entry_price) / entry_price * 100, 2) if entry_price != 0 else 0.0

            trades.append(
                {
                    "trade_id": trade_id,
                    "date": date,
                    "action": "卖出",
                    "price": round(price, 2),
                    "shares": shares,
                    "position_value": round(shares * price, 2),
                    "cash": round(cash, 2),
                    "pnl": pnl,
                    "pnl_pct": pnl_pct,
                    "cum_pnl": None,
                    "cum_pnl_pct": None,
                }
            )
            shares = 0

        # 3. 金叉信号检测（仅空仓时跟踪；持仓时清零）
        if position == 0:
            if bool(buy_signal.iloc[i]):
                if signal_wait < 0:
                    signal_wait = 0
                else:
                    signal_wait += 1
            elif signal_wait >= 0:
                signal_wait += 1
        else:
            signal_wait = -1

        # 4. 入场撮合：满足延迟条件 + 当前空仓
        if signal_wait >= entry_delay + 1 and position == 0:
            signal_wait = -1
            position = 1
            entry_price = price
            trade_id += 1

            invest_amount = cash * float(position_ratio)
            shares = int(invest_amount / price) if price > 0 else 0
            if shares == 0:
                # 资金不足，放弃本次信号
                position = 0
                trade_id -= 1
            else:
                cash -= shares * price

                # 特殊情况：若同一根 K 线同时出现卖出信号，则视作“当日死叉”，
                # 在下一根 K 线强制出场
                if bool(sell_signal.iloc[i]):
                    exit_signal_wait = 0

            trades.append(
                {
                    "trade_id": trade_id,
                    "date": date,
                    "action": "买入",
                    "price": round(price, 2),
                    "shares": shares,
                    "position_value": round(shares * price, 2),
                    "cash": round(cash, 2),
                    "pnl": None,
                    "pnl_pct": None,
                    "cum_pnl": None,
                    "cum_pnl_pct": None,
                }
            )

        # 5. 死叉等待超时放弃
        if exit_signal_wait > exit_delay + 1 and position == 1:
            exit_signal_wait = -1

        positions.append(position)

    # 6. 累计盈亏回填
    cum_pnl = 0.0
    for t in trades:
        if t["pnl"] is not None:
            cum_pnl += float(t["pnl"])
            t["cum_pnl"] = round(cum_pnl, 2)
            t["cum_pnl_pct"] = round(cum_pnl / float(initial_capital) * 100, 2) if initial_capital else 0.0

    # 7. 收益率与策略收益
    df["Position"] = positions
    df["Market_Return"] = df["Close"].pct_change()
    df["Strategy_Return"] = df["Position"].shift(1) * df["Market_Return"]

    return df, trades


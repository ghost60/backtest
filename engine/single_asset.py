#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
通用单标的撮合与资金管理引擎（Single Asset Engine）

职责：
- 接收已经算好的买入 / 卖出信号（因子层负责生成）
- 按给定的入场 / 出场延迟、初始资金与仓位比例，执行逐 K 线撮合
- 支持 max_leverage 杠杆倍数：买入时放大投入，超出自有资金部分计为借贷，
  卖出时先偿还借贷，剩余归还账户现金
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
    max_leverage: float = 1.0,
    margin_currency: str = "USD",
    margin_fx_to_usd: float = 1.0,
    margin_fx_getter=None,
    margin_settlement_mode: str = "principal_plus_pnl",
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
        - 0 表示"信号后第 1 根 K 线"入场
        - N 表示"信号后第 N+1 根 K 线"入场
    exit_delay : int
        出场延迟 K 数，语义与 entry_delay 类似。
    initial_capital : float
        初始资金。
    position_ratio : float
        持仓比例（0~1），例如 1.0=全仓，0.5=半仓。
    max_leverage : float
        最大杠杆倍数（>= 1.0），默认 1.0 不使用杠杆。
        例如 2.0 表示最多用 2 倍杠杆买入（超出持有现金部分算作借贷）。
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
    max_leverage = max(1.0, float(max_leverage))
    margin_currency = str(margin_currency).upper()
    if margin_fx_to_usd is None or margin_fx_to_usd <= 0:
        raise ValueError("margin_fx_to_usd 必须大于 0。")
    margin_settlement_mode = str(margin_settlement_mode).lower()
    if margin_settlement_mode not in ("principal_plus_pnl", "mark_to_market"):
        raise ValueError("margin_settlement_mode 必须为 principal_plus_pnl 或 mark_to_market。")
    money_digits = 2 if margin_currency == "USD" else 8

    position = 0
    positions: List[int] = []
    trades: List[Dict] = []
    daily_cash: List[float] = []
    daily_shares: List[int] = []
    daily_borrowed: List[float] = []
    daily_fx_to_usd: List[float] = []

    signal_wait = -1       # 金叉后等待的 K 数：-1=无信号，0=信号当根，1=信号后第1根...
    exit_signal_wait = -1  # 死叉后等待的 K 数

    entry_price = 0.0
    trade_id = 0
    shares = 0
    borrowed = 0.0
    cash = 0.0
    last_fx = float(margin_fx_to_usd)
    entry_fx = last_fx
    own_invested_margin = 0.0

    def _resolve_fx(cur_date):
        nonlocal last_fx
        if margin_currency == "USD":
            return 1.0
        if margin_fx_getter is not None:
            try:
                v = float(margin_fx_getter(cur_date))
                if v > 0:
                    last_fx = v
                    return v
            except Exception:
                pass
        return last_fx

    # 约定：initial_capital 配置口径与保证金币种一致（如 margin=BTC，则 initial=BTC 数量）
    initial_capital_margin = float(initial_capital)
    cash = float(initial_capital_margin)

    for i in range(len(df)):
        date = df.index[i]
        price = float(df[price_col].iloc[i])
        current_fx = _resolve_fx(date)

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

            sell_proceeds_usd = shares * price
            # pnl = 卖出所得 - 归还借贷 - 自有资金净投入
            own_invested = entry_price * shares - borrowed
            pnl_usd = sell_proceeds_usd - borrowed - own_invested
            pnl = round(pnl_usd / current_fx, money_digits)
            # 资金结算口径：
            # - principal_plus_pnl: 返还入场时保证金本金 + 本次美元盈亏折算保证金币种
            # - mark_to_market: 直接把平仓后美元资产按当时汇率折算
            if margin_settlement_mode == "principal_plus_pnl":
                cash += own_invested_margin + (pnl_usd / current_fx)
            else:
                cash += (sell_proceeds_usd - borrowed) / current_fx
            pnl_pct = round((price - entry_price) / entry_price * 100, 2) if entry_price != 0 else 0.0

            trades.append(
                {
                    "trade_id": trade_id,
                    "date": date,
                    "action": "卖出",
                    "price": round(price, 2),#卖出价格
                    "shares": shares,#卖出股数
                    "position_value": round(sell_proceeds_usd, 2),#卖出总金额(USD)
                    "position_value_margin": round(sell_proceeds_usd / current_fx, money_digits),#卖出总金额(保证金币种)
                    "leverage": round(max_leverage, 2),#杠杆倍数
                    "margin_currency": margin_currency,
                    "margin_fx_to_usd": round(current_fx, 6),
                    "borrowed": round(borrowed / current_fx, money_digits),
                    "cash": round(cash, money_digits),
                    "pnl": pnl,#本次交易盈亏
                    "pnl_pct": pnl_pct,#本次交易盈亏百分比
                    "cum_pnl": None,#累计盈亏
                    "cum_pnl_pct": None,#累计盈亏百分比
                }
            )
            shares = 0
            borrowed = 0.0
            own_invested_margin = 0.0

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

            invest_amount_usd = cash * current_fx * float(position_ratio) * max_leverage
            shares = int(invest_amount_usd / price) if price > 0 else 0
            if shares == 0:
                # 资金不足，放弃本次信号
                position = 0
                trade_id -= 1
                borrowed = 0.0
            else:
                actual_cost_usd = shares * price
                own_cash_usd = cash * current_fx
                borrowed = max(0.0, actual_cost_usd - own_cash_usd)   # 超出自有资金部分(USD)
                own_invested_margin = (actual_cost_usd - borrowed) / current_fx
                entry_fx = current_fx
                cash -= own_invested_margin  # 只扣除自有资金(保证金币种)

                # 特殊情况：若同一根 K 线同时出现卖出信号，则视作"当日死叉"，
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
                    "position_value": round(shares * price, 2),  # USD 名义仓位
                    "position_value_margin": round((shares * price) / current_fx, money_digits),
                    "leverage": round(max_leverage, 2),
                    "margin_currency": margin_currency,
                    "margin_fx_to_usd": round(current_fx, 6),
                    "borrowed": round(borrowed / current_fx, money_digits),
                    "cash": round(cash, money_digits),
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
        daily_cash.append(cash)
        daily_shares.append(shares)
        daily_borrowed.append(borrowed)
        daily_fx_to_usd.append(current_fx)

    # 6. 累计盈亏回填
    cum_pnl = 0.0
    for t in trades:
        if t["pnl"] is not None:
            cum_pnl += float(t["pnl"])
            t["cum_pnl"] = round(cum_pnl, 2)
            t["cum_pnl_pct"] = round(cum_pnl / float(initial_capital_margin) * 100, 2) if initial_capital_margin else 0.0

    # 7. 收益率与总资产
    df["Position"] = positions
    df["Portfolio_Cash"] = daily_cash
    df["Portfolio_Shares"] = daily_shares
    df["Margin_FX_To_USD"] = daily_fx_to_usd
    # 借贷内部以 USD 维护，落表转换为保证金币种，便于和 Cash/Total_Value 一致
    df["Portfolio_Borrowed"] = [
        (b / fx) if fx else 0.0
        for b, fx in zip(daily_borrowed, daily_fx_to_usd)
    ]
    df["Total_Value"] = [
        cash_v + (shares_v * close_v - borrowed_v) / fx_v
        for cash_v, shares_v, close_v, borrowed_v, fx_v in zip(
            daily_cash,
            daily_shares,
            df["Close"].tolist(),
            daily_borrowed,
            daily_fx_to_usd,
        )
    ]
    
    df["Market_Return"] = df["Close"].pct_change()
    # 真实百分比收益
    df["Strategy_Return"] = df["Total_Value"].pct_change().fillna(0.0)

    return df, trades

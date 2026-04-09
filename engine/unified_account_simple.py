#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
最简统一账户引擎（Unified Account - Simple）

设计目标：
- 单标的交易（如 TSLA）
- 账户同时支持持有 USD / BTC 两类现金资产
- BTC 仅作为抵押物，不因开仓而减少
- 买入标的时通过借入 USD 建仓；平仓时先还债，再将净额按当日价格并回 BTC
- 为了保持模型简单稳定，BTC/USD 资产切换仅允许在空仓时发生

状态变量（统一按 USD 计算账户净值）：
- cash_usd: 账户持有的美元现金
- cash_btc: 账户持有的比特币数量
- debt_usd: 借入的美元负债
- shares: 持有的标的股数
- equity_usd = cash_usd + cash_btc * btc_price + shares * stock_price - debt_usd
"""

from __future__ import annotations

from typing import Dict, List, Tuple

import pandas as pd


def run_unified_account_simple(
    df: pd.DataFrame,
    buy_signal: pd.Series,
    sell_signal: pd.Series,
    collateral_price_usd: pd.Series,
    entry_delay: int = 0,
    exit_delay: int = 0,
    initial_capital: float = 100000.0,
    initial_margin_currency: str = "USD",
    position_ratio: float = 1.0,
    max_leverage: float = 1.0,
    debt_limit_ratio: float = 1.0,
    collateral_hold_btc: pd.Series | None = None,
    log_switches: bool = False,
    price_col: str = "Open",
) -> Tuple[pd.DataFrame, List[Dict]]:
    """
    最简统一账户回测。

    参数
    ----
    collateral_price_usd : pd.Series
        BTC/USD 价格序列，与 df 索引对齐。
    initial_margin_currency : str
        初始保证金币种，仅支持 USD / BTC。
    debt_limit_ratio : float
        借款上限占抵押物 USD 价值的比例。1.0 表示最多借到抵押物等值美元。
    collateral_hold_btc : pd.Series[bool], optional
        True=空仓时持 BTC，False=空仓时持 USD。
        为保证模型简单稳定，仅在空仓时执行切换。
    """
    df = df.copy()
    initial_margin_currency = str(initial_margin_currency).upper()
    if initial_margin_currency not in ("USD", "BTC"):
        raise ValueError("initial_margin_currency 仅支持 USD 或 BTC。")
    settle_to_btc = initial_margin_currency == "BTC"

    if debt_limit_ratio <= 0:
        raise ValueError("debt_limit_ratio 必须大于 0。")

    collateral_price_usd = collateral_price_usd.reindex(df.index).ffill()
    if collateral_price_usd.isna().any():
        raise ValueError("collateral_price_usd 与行情索引对齐后仍存在缺失值。")

    if collateral_hold_btc is not None:
        collateral_hold_btc = collateral_hold_btc.reindex(df.index).ffill().fillna(False).astype(bool)

    cash_usd = float(initial_capital) if initial_margin_currency == "USD" else 0.0
    cash_btc = float(initial_capital) if initial_margin_currency == "BTC" else 0.0
    debt_usd = 0.0
    shares = 0
    position = 0
    trade_id = 0
    entry_price = 0.0

    signal_wait = -1
    exit_signal_wait = -1

    positions: List[int] = []
    daily_cash_usd: List[float] = []
    daily_cash_btc: List[float] = []
    daily_debt_usd: List[float] = []
    daily_shares: List[int] = []
    daily_collateral_price: List[float] = []
    daily_collateral_value_usd: List[float] = []
    daily_equity_usd: List[float] = []
    daily_hold_ccy: List[str] = []
    trades: List[Dict] = []

    def _collateral_value_usd(cur_btc_price: float) -> float:
        return cash_usd + cash_btc * cur_btc_price

    def _equity_usd(stock_mark: float, cur_btc_price: float) -> float:
        return cash_usd + cash_btc * cur_btc_price + shares * stock_mark - debt_usd

    def _maybe_switch_collateral(cur_date, cur_btc_price):
        nonlocal cash_usd, cash_btc
        if collateral_hold_btc is None or position == 1:
            return
        want_btc = bool(collateral_hold_btc.loc[cur_date])
        has_btc = cash_btc > 0
        if want_btc and cash_usd > 0:
            cash_btc += cash_usd / cur_btc_price
            cash_usd = 0.0
            if log_switches:
                trades.append(
                    {
                        "trade_id": 0,
                        "date": cur_date,
                        "action": "切换统一账户为BTC抵押",
                        "price": round(cur_btc_price, 2),
                        "shares": 0,
                        "cash_usd": round(cash_usd, 2),
                        "cash_btc": round(cash_btc, 8),
                        "debt_usd": round(debt_usd, 2),
                        "equity_usd": round(_equity_usd(0.0, cur_btc_price), 2),
                    }
                )
        elif (not want_btc) and has_btc:
            cash_usd += cash_btc * cur_btc_price
            cash_btc = 0.0
            if log_switches:
                trades.append(
                    {
                        "trade_id": 0,
                        "date": cur_date,
                        "action": "切换统一账户为USD抵押",
                        "price": round(cur_btc_price, 2),
                        "shares": 0,
                        "cash_usd": round(cash_usd, 2),
                        "cash_btc": round(cash_btc, 8),
                        "debt_usd": round(debt_usd, 2),
                        "equity_usd": round(_equity_usd(0.0, cur_btc_price), 2),
                    }
                )

    for i in range(len(df)):
        date = df.index[i]
        price = float(df[price_col].iloc[i])
        close_price = float(df["Close"].iloc[i])
        btc_price = float(collateral_price_usd.iloc[i])

        _maybe_switch_collateral(date, btc_price)

        if bool(sell_signal.iloc[i]):
            if position == 1:
                exit_signal_wait = 0
        elif exit_signal_wait >= 0 and position == 1:
            exit_signal_wait += 1

        if exit_signal_wait >= exit_delay + 1 and position == 1:
            exit_signal_wait = -1
            position = 0
            sell_proceeds_usd = shares * price
            pnl_usd = sell_proceeds_usd - debt_usd
            net_usd = sell_proceeds_usd - debt_usd
            if settle_to_btc:
                cash_btc += (cash_usd + net_usd) / btc_price
                cash_usd = 0.0
                post_sell_equity_usd = cash_btc * btc_price
            else:
                cash_usd += net_usd
                post_sell_equity_usd = cash_usd + cash_btc * btc_price
            trades.append(
                {
                    "trade_id": trade_id,
                    "date": date,
                    "action": "卖出",
                    "price": round(price, 2),
                    "shares": shares,
                    "position_value": round(sell_proceeds_usd, 2),
                    "cash_usd": round(cash_usd, 2),
                    "cash_btc": round(cash_btc, 8),
                    "debt_usd": 0.0,
                    "equity_usd": round(post_sell_equity_usd, 2),
                    "pnl": round(pnl_usd, 2),
                    "pnl_usd": round(pnl_usd, 2),
                    "pnl_pct": round((price - entry_price) / entry_price * 100, 2) if entry_price else 0.0,
                    "cum_pnl": None,
                    "cum_pnl_usd": None,
                    "cum_pnl_pct": None,
                }
            )
            debt_usd = 0.0
            shares = 0

        if position == 0:
            if bool(buy_signal.iloc[i]):
                signal_wait = 0 if signal_wait < 0 else signal_wait + 1
            elif signal_wait >= 0:
                signal_wait += 1
        else:
            signal_wait = -1

        if signal_wait >= entry_delay + 1 and position == 0:
            signal_wait = -1
            collateral_usd = _collateral_value_usd(btc_price)
            max_debt_usd = collateral_usd * float(debt_limit_ratio) * float(max_leverage) * float(position_ratio)
            shares = int(max_debt_usd / price) if price > 0 else 0
            if shares > 0:
                position = 1
                trade_id += 1
                entry_price = price
                debt_usd = shares * price
                trades.append(
                    {
                        "trade_id": trade_id,
                        "date": date,
                        "action": "买入",
                        "price": round(price, 2),
                        "shares": shares,
                        "position_value": round(debt_usd, 2),
                        "cash_usd": round(cash_usd, 2),
                        "cash_btc": round(cash_btc, 8),
                        "debt_usd": round(debt_usd, 2),
                        "equity_usd": round(_equity_usd(price, btc_price), 2),
                        "pnl": None,
                        "pnl_usd": None,
                        "pnl_pct": None,
                        "cum_pnl": None,
                        "cum_pnl_usd": None,
                        "cum_pnl_pct": None,
                    }
                )
                if bool(sell_signal.iloc[i]):
                    exit_signal_wait = 0

        positions.append(position)
        daily_cash_usd.append(cash_usd)
        daily_cash_btc.append(cash_btc)
        daily_debt_usd.append(debt_usd)
        daily_shares.append(shares)
        daily_collateral_price.append(btc_price)
        daily_collateral_value_usd.append(_collateral_value_usd(btc_price))
        daily_equity_usd.append(_equity_usd(close_price, btc_price))
        daily_hold_ccy.append("BTC" if cash_btc > 0 else "USD")

    cum_pnl = 0.0
    initial_equity_usd = (
        float(initial_capital) * float(collateral_price_usd.iloc[0])
        if initial_margin_currency == "BTC" else float(initial_capital)
    )
    for t in trades:
        if t.get("pnl_usd") is not None:
            cum_pnl += float(t["pnl_usd"])
            t["cum_pnl"] = round(cum_pnl, 2)
            t["cum_pnl_usd"] = round(cum_pnl, 2)
            t["cum_pnl_pct"] = round(cum_pnl / initial_equity_usd * 100, 2) if initial_equity_usd else 0.0

    df["Position"] = positions
    df["Cash_USD"] = daily_cash_usd
    df["Cash_BTC"] = daily_cash_btc
    df["Debt_USD"] = daily_debt_usd
    df["Portfolio_Shares"] = daily_shares
    df["Collateral_Price_USD"] = daily_collateral_price
    df["Collateral_Value_USD"] = daily_collateral_value_usd
    df["Collateral_Hold_Currency"] = daily_hold_ccy
    df["Total_Value"] = daily_equity_usd
    df["Market_Return"] = df["Close"].pct_change()
    df["Strategy_Return"] = df["Total_Value"].pct_change().fillna(0.0)

    return df, trades

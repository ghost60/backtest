# -*- coding: utf-8 -*-
"""
BTCDOM 风格组合复刻模块

逻辑：
- 固定权重做多 BTC（主标的）
- 固定权重做空一篮子山寨币（hedge.symbols）
- 每日按目标权重再平衡，组合收益 = long_weight * BTC收益 - short_weight * 山寨篮子收益
"""

from __future__ import annotations

from typing import Sequence

import pandas as pd


def run(
    btc_df: pd.DataFrame,
    alt_dfs: Sequence[pd.DataFrame],
    weights: Sequence[float],
    initial_capital: float = 100000.0,
    long_weight: float = 0.5,
    short_weight: float = 0.5,
    alt_names: Sequence[str] | None = None,
):
    """
    返回
    ----
    tuple[pd.DataFrame, list[dict]]
        df: 含 Strategy_Return / Market_Return / Strategy_Equity 所需列
        trades: 伪交易清单（仅记录初始建仓与最终平仓）
    """
    common_dates = btc_df.index
    for adf in alt_dfs:
        common_dates = common_dates.intersection(adf.index)

    btc_df = btc_df.loc[common_dates].copy()
    alt_dfs = [adf.loc[common_dates].copy() for adf in alt_dfs]

    combined = pd.DataFrame(index=common_dates)
    combined["BTC_Market_Return"] = btc_df["Close"].pct_change().fillna(0.0)
    combined["Market_Return"] = combined["BTC_Market_Return"]
    combined["BTC_Position"] = float(long_weight)

    basket_return = pd.Series(0.0, index=common_dates)
    for i, adf in enumerate(alt_dfs):
        name = alt_names[i] if alt_names and i < len(alt_names) else f"ALT_{i+1}"
        alt_ret = adf["Close"].pct_change().fillna(0.0)
        weight = float(weights[i])
        combined[f"{name}_Market_Return"] = alt_ret
        combined[f"{name}_Position"] = -float(short_weight) * weight
        basket_return += weight * alt_ret

    combined["Alt_Basket_Return"] = basket_return
    combined["Strategy_Return"] = float(long_weight) * combined["BTC_Market_Return"] - float(short_weight) * combined["Alt_Basket_Return"]
    combined["Position"] = 1
    combined["Total_Value"] = float(initial_capital) * (1.0 + combined["Strategy_Return"]).cumprod()

    start_price = float(btc_df["Open"].iloc[0])
    start_notional = float(initial_capital) * float(long_weight)
    start_shares = int(start_notional / start_price) if start_price > 0 else 0
    final_value = float(combined["Total_Value"].iloc[-1])
    pnl = final_value - float(initial_capital)
    pnl_pct = (pnl / float(initial_capital) * 100.0) if initial_capital else 0.0

    trades = [
        {
            "trade_id": 1,
            "date": common_dates[0],
            "action": "建仓BTCDOM组合",
            "price": round(start_price, 2),
            "shares": start_shares,
            "position_value": round(start_notional, 2),
            "position_value_margin": round(start_notional, 2),
            "margin_currency": "USD",
            "margin_fx_to_usd": 1.0,
            "cash": round(float(initial_capital), 2),
            "pnl_usd": None,
            "pnl": None,
            "pnl_pct": None,
            "cum_pnl": None,
            "cum_pnl_pct": None,
        },
        {
            "trade_id": 1,
            "date": common_dates[-1],
            "action": "平仓BTCDOM组合",
            "price": round(float(btc_df["Close"].iloc[-1]), 2),
            "shares": start_shares,
            "position_value": round(final_value, 2),
            "position_value_margin": round(final_value, 2),
            "margin_currency": "USD",
            "margin_fx_to_usd": 1.0,
            "cash": round(final_value, 2),
            "pnl_usd": round(pnl, 2),
            "pnl": round(pnl, 2),
            "pnl_pct": round(pnl_pct, 2),
            "cum_pnl": round(pnl, 2),
            "cum_pnl_pct": round(pnl_pct, 2),
        },
    ]

    return combined, trades

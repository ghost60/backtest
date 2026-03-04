# -*- coding: utf-8 -*-
"""
指标计算模块

职责：
- 根据 Strategy_Return / Market_Return 计算累计净值（Equity）
- 计算策略与基准的总回报、年化、最大回撤、夏普
- 按持仓区间统计交易次数、胜率
"""

import numpy as np
import pandas as pd


def calculate_equity(df):
    """
    计算策略与基准的累计净值曲线。
    要求 df 已有 Strategy_Return、Market_Return；会新增 Strategy_Equity、Market_Equity。
    """
    df = df.copy()
    df["Strategy_Equity"] = (1 + df["Strategy_Return"].fillna(0)).cumprod()
    df["Market_Equity"] = (1 + df["Market_Return"].fillna(0)).cumprod()
    return df


def calculate_metrics(df):
    """
    计算回测绩效与交易统计。

    返回
    ----
    dict
        策略/基准总回报、年化、最大回撤、夏普、交易次数、盈利次数、胜率等。
    """
    eq = df["Strategy_Equity"]
    ret = df["Strategy_Return"]
    # 总回报
    total_strategy = eq.iloc[-1] - 1
    total_market = df["Market_Equity"].iloc[-1] - 1
    # 年化（CAGR）
    days = max(0, (df.index[-1] - df.index[0]).days)
    years = days / 365.25
    cagr_strategy = (eq.iloc[-1] ** (1 / years) - 1) if years > 0 else 0.0
    cagr_market = (df["Market_Equity"].iloc[-1] ** (1 / years) - 1) if years > 0 else 0.0
    # 最大回撤及其修复时间（爬坑时间）
    rolling_max = eq.cummax()
    drawdown = (eq - rolling_max) / rolling_max
    max_drawdown = drawdown.min()

    # 最大回撤对应的谷底日期
    trough_date = drawdown.idxmin()
    peak_date = None
    recovery_date = None
    recovery_days = None

    if trough_date is not None:
        # 最大回撤之前的前高点（峰值）
        eq_before_trough = eq.loc[:trough_date]
        if len(eq_before_trough) > 0:
            peak_value = eq_before_trough.max()
            peak_date = eq_before_trough.idxmax()

            # 谷底之后，第一次回到或超过该峰值的日期
            eq_after_trough = eq.loc[trough_date:]
            recovered = eq_after_trough[eq_after_trough >= peak_value]
            if len(recovered) > 0:
                recovery_date = recovered.index[0]
                recovery_days = (recovery_date - trough_date).days
    # 夏普（年化，假设 252 交易日）
    std = ret.std()
    sharpe = (ret.mean() / std * np.sqrt(252)) if std and std != 0 else 0.0

    # 交易统计：按持仓区间分组，每段持仓对应一笔交易
    pos = df["Position"]
    group = (pos != pos.shift()).cumsum()
    hold_periods = df.loc[pos == 1].groupby(group.loc[pos == 1])
    trade_returns = [(1 + g["Market_Return"]).prod() - 1 for _, g in hold_periods if len(g) > 0]
    n_trades = len(trade_returns)
    n_win = sum(1 for r in trade_returns if r > 0)

    return {
        "策略总回报": total_strategy,
        "策略年化回报": cagr_strategy,
        "最大回撤": max_drawdown,
        "最大回撤开始日期": peak_date,
        "最大回撤谷底日期": trough_date,
        "最大回撤修复日期": recovery_date,
        "最大回撤修复时间_天": recovery_days,
        "夏普比率": sharpe,
        "基准总回报": total_market,
        "基准年化回报": cagr_market,
        "总交易次数": n_trades,
        "盈利交易次数": n_win,
        "亏损交易次数": n_trades - n_win,
        "盈利交易百分比": n_win / n_trades if n_trades else 0,
    }


def calculate_equity_hedge(df, n_hedges):
    """
    计算对冲策略的累计净值曲线。
    """
    df = df.copy()
    df["Strategy_Equity"] = (1 + df["Combined_Strategy_Return"].fillna(0)).cumprod()
    df["TSLA_Market_Equity"] = (1 + df["TSLA_Market_Return"].fillna(0)).cumprod()
    for i in range(n_hedges):
        df[f"Hedge_{i}_Market_Equity"] = (1 + df[f"Hedge_{i}_Market_Return"].fillna(0)).cumprod()
    return df


def calculate_metrics_hedge(df, hedge_names):
    """
    计算对冲策略的绩效指标。
    """
    strategy_ret = df["Combined_Strategy_Return"]
    eq = df["Strategy_Equity"]

    # 基本指标
    total_strategy = eq.iloc[-1] - 1
    total_tsla = df["TSLA_Market_Equity"].iloc[-1] - 1
    
    days = max(0, (df.index[-1] - df.index[0]).days)
    years = days / 365.25
    cagr_strategy = (eq.iloc[-1] ** (1 / years) - 1) if years > 0 else 0.0
    cagr_tsla = (df["TSLA_Market_Equity"].iloc[-1] ** (1 / years) - 1) if years > 0 else 0.0
    
    rolling_max = eq.cummax()
    max_drawdown = ((eq - rolling_max) / rolling_max).min()
    
    std = strategy_ret.std()
    sharpe = (strategy_ret.mean() / std * np.sqrt(252)) if std and std != 0 else 0.0

    # 统计切换次数与持仓天数
    tsla_pos = df["TSLA_Position"]
    tsla_switches = (tsla_pos.diff().fillna(0) != 0).sum()
    tsla_hold_days = (tsla_pos == 1).sum()
    
    results = {
        "对冲策略总回报": total_strategy,
        "对冲策略年化回报": cagr_strategy,
        "最大回撤": max_drawdown,
        "夏普比率": sharpe,
        "TSLA持有总回报": total_tsla,
        "TSLA持有年化回报": cagr_tsla,
        "TSLA切换次数": tsla_switches,
        "TSLA持仓天数": tsla_hold_days,
        "持仓百分比": (tsla_hold_days / len(df)) if len(df) else 0,
    }

    # 各对冲标的回报
    for i, name in enumerate(hedge_names):
        total_h = df[f"Hedge_{i}_Market_Equity"].iloc[-1] - 1
        results[f"{name}持有总回报"] = total_h

    return results

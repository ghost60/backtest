# -*- coding: utf-8 -*-
"""
对冲策略模块

逻辑简述：
- 主标的（如 TSLA）出现买入信号时：卖出对冲标的，全仓买入主标的。
- 主标的（如 TSLA）出现卖出信号或持仓无效时：平仓主标的，按权重分配买入对冲标的。
- 始终保持 100% 持仓（在主标的与对冲组合之间切换）。
"""

import pandas as pd
import numpy as np


def run(tsla_df, hedge_dfs, weights, ma_short=5, ma_long=30, use_price_filter=True, 
        entry_delay=0, exit_delay=0, initial_capital=100000, position_ratio=1.0, hedge_names=None):
    """
    运行对冲策略。

    参数
    ----
    tsla_df : pd.DataFrame
        主标的数据（需含 Close）。
    hedge_dfs : list[pd.DataFrame]
        对冲标的数据列表。
    weights : list[float]
        对冲标的权重分配（和应为 1.0）。
    ma_short, ma_long : int
        TSLA 的均线周期。
    use_price_filter : bool
        是否使用收盘价过滤。
    entry_delay : int
        入场延迟。
    exit_delay : int
        出场延迟。
    initial_capital : float
        初始资金。
    position_ratio : float
        持仓比例。
    exit_delay : int
        出场延迟。

    返回
    ----
    pd.DataFrame
        合并后的日频数据，含各标的持仓、收益及组合收益。
    """
    # 1. 对齐日期
    common_dates = tsla_df.index
    for hdf in hedge_dfs:
        common_dates = common_dates.intersection(hdf.index)

    tsla_df = tsla_df.loc[common_dates].copy()
    hedge_dfs = [hdf.loc[common_dates].copy() for hdf in hedge_dfs]

    # 2. 计算 TSLA 信号（与 strategy_ma.run 中的定义保持一致）
    # 均线命名固定为 MA5 / MA30，便于与单标的回测对齐阅读
    tsla_df["MA5"] = tsla_df["Close"].rolling(window=ma_short).mean().round(3)
    tsla_df["MA30"] = tsla_df["Close"].rolling(window=ma_long).mean().round(3)

    # 金叉：当前短 >= 长，前一根短 < 长
    cross_long = (tsla_df["MA5"] >= tsla_df["MA30"]) & (tsla_df["MA5"].shift(1) < tsla_df["MA30"].shift(1))
    # 死叉：当前短 < 长，前一根短 >= 长
    sell_signal = (tsla_df["MA5"] < tsla_df["MA30"]) & (tsla_df["MA5"].shift(1) >= tsla_df["MA30"].shift(1))

    # 入场过滤逻辑与 strategy_ma 完全一致，保持为逐行布尔序列，避免 use_price_filter=False 时标量 True 无法索引
    price_ok = tsla_df["Close"] > tsla_df["MA5"] if use_price_filter else pd.Series(True, index=tsla_df.index)
    buy_signal = cross_long & price_ok

    # 3. 逐 K 线模拟持仓状态（对标 strategy_ma.run，增加全资产价值追踪）
    tsla_pos_list = []
    # hedge_pos_matrix[hedge_idx][k_idx]
    hedge_pos_matrix = [[] for _ in range(len(hedge_dfs))]

    tsla_position = 0
    signal_wait = -1       # 金叉后等待的 K 数
    exit_signal_wait = -1  # 死叉后等待的 K 数

    trades = []
    trade_id = 0
    
    # 核心追踪变量
    current_portfolio_value = initial_capital
    entry_prices = {} 
    
    # 记录初始持仓（策略默认全仓持有对冲标的，成交价使用当根 K 线开盘价 Open）
    if hedge_names:
        for h_idx, h_name in enumerate(hedge_names):
            h_price = hedge_dfs[h_idx]["Open"].iloc[0]
            entry_prices[h_name] = h_price
            trades.append({
                "trade_id": 0,
                "date": tsla_df.index[0],
                "action": f"买入{h_name}(初始)",
                "price": round(h_price, 2),
                "shares": int(current_portfolio_value * position_ratio * weights[h_idx] / h_price),
                "position_value": round(current_portfolio_value * position_ratio * weights[h_idx], 2),
                "cash": round(current_portfolio_value * (1 - position_ratio), 2) if h_idx == len(hedge_names)-1 else "-",
                "pnl": None,
                "pnl_pct": None,
                "cum_pnl": None,
                "cum_pnl_pct": None
            })
    entry_prices["TSLA"] = tsla_df["Open"].iloc[0]

    for i in range(len(tsla_df)):
        date = tsla_df.index[i]
        # 交易价格统一使用当根 K 线的开盘价（与 strategy_ma.run 一致）
        price = tsla_df["Open"].iloc[i]

        # 1. 信号检测：金叉/买入（逻辑与 strategy_ma.run 保持一致）
        if tsla_position == 0:
            if buy_signal.iloc[i]:
                if signal_wait < 0:
                    signal_wait = 0  # 新信号出现，标记为第 0 根
                else:
                    signal_wait += 1  # 已有信号，在此基础上递增
            elif signal_wait >= 0:
                signal_wait += 1      # 后续 K 线递增计数
        else:
            # 持仓期间不保留旧的金叉等待计数，避免平仓后直接用旧信号再次入场
            signal_wait = -1

        # 2. 信号检测：死叉/卖出 (仅持仓时有效)
        if sell_signal.iloc[i] and tsla_position == 1:
            exit_signal_wait = 0
        elif exit_signal_wait >= 0 and tsla_position == 1:
            exit_signal_wait += 1

        # 3. 入场逻辑：从 Hedge 切换到 TSLA
        # entry_delay=0 时，signal_wait>=1 即信号后第 1 根 K 线买入（与 strategy_ma.run 一致）
        if signal_wait >= entry_delay + 1 and tsla_position == 0:
            signal_wait = -1
            tsla_position = 1
            exit_signal_wait = -1
            
            # --- 结算上一段对冲标的的收益 ---
            pnl_sum = 0
            if hedge_names:
                for h_idx, h_name in enumerate(hedge_names):
                    h_price = hedge_dfs[h_idx]["Open"].iloc[i]
                    h_entry_price = entry_prices[h_name]
                    h_weight = weights[h_idx]
                    
                    # 该标的这段时间的收益率
                    h_ret = (h_price - h_entry_price) / h_entry_price
                    h_pnl = current_portfolio_value * h_weight * position_ratio * h_ret
                    pnl_sum += h_pnl
                    
                    # 记录卖出对冲标的
                    trades.append({
                        "trade_id": trade_id + 1,
                        "date": date,
                        "action": f"卖出{h_name}",
                        "price": round(h_price, 2),
                        "shares": int(current_portfolio_value * position_ratio * h_weight / h_price),
                        "position_value": 0,
                        "cash": "-", # 过程值
                        "pnl": round(h_pnl, 2),
                        "pnl_pct": round(h_ret * 100, 2),
                        "cum_pnl": None,
                        "cum_pnl_pct": None
                    })
            
            current_portfolio_value += pnl_sum
            trade_id += 1
            entry_prices["TSLA"] = price
            
            # 记录买入 TSLA
            trades.append({
                "trade_id": trade_id,
                "date": date,
                "action": "买入TSLA",
                "price": round(price, 2),
                "shares": int(current_portfolio_value * position_ratio / price),
                "position_value": round(current_portfolio_value * position_ratio, 2),
                "cash": round(current_portfolio_value * (1 - position_ratio), 2),
                "pnl": None,
                "pnl_pct": None,
                "cum_pnl": None,
                "cum_pnl_pct": None
            })

            # 特殊处理：如果当前这根 K 线已经出现死叉，
            # 则视为「前一日金叉、当日死叉」的情况：
            # 仍在当日开盘买入 TSLA，但把 exit_signal_wait 置为 0，
            # 这样在下一根 K 线（exit_delay=0 时）强制卖出。
            if sell_signal.iloc[i]:
                exit_signal_wait = 0

        # 4. 出场逻辑：从 TSLA 切换到 Hedge
        if exit_signal_wait >= exit_delay + 1 and tsla_position == 1:
            exit_signal_wait = -1
            tsla_position = 0
            signal_wait = -1

            # --- 结算上一段 TSLA 的收益 ---
            tsla_ret = (price - entry_prices["TSLA"]) / entry_prices["TSLA"]
            tsla_pnl = current_portfolio_value * position_ratio * tsla_ret
            current_portfolio_value += tsla_pnl
            
            trade_id += 1
            trades.append({
                "trade_id": trade_id,
                "date": date,
                "action": "卖出TSLA",
                "price": round(price, 2),
                "shares": 0,
                "position_value": 0,
                "cash": round(current_portfolio_value, 2),
                "pnl": round(tsla_pnl, 2),
                "pnl_pct": round(tsla_ret * 100, 2),
                "cum_pnl": None,
                "cum_pnl_pct": None
            })

            # --- 买入对冲组合（成交价使用 Open） ---
            if hedge_names:
                for h_idx, h_name in enumerate(hedge_names):
                    h_price = hedge_dfs[h_idx]["Open"].iloc[i]
                    entry_prices[h_name] = h_price
                    trades.append({
                        "trade_id": trade_id,
                        "date": date,
                        "action": f"买入{h_name}",
                        "price": round(h_price, 2),
                        "shares": int(current_portfolio_value * position_ratio * weights[h_idx] / h_price),
                        "position_value": round(current_portfolio_value * position_ratio * weights[h_idx], 2),
                        "cash": "-",
                        "pnl": None,
                        "pnl_pct": None,
                        "cum_pnl": None,
                        "cum_pnl_pct": None
                    })
        
        # 5. 卖出超时放弃
        if exit_signal_wait > exit_delay + 1 and tsla_position == 1:
            exit_signal_wait = -1

        # 记录持仓 (对标 strategy_ma，应用 position_ratio)
        tsla_pos_list.append(tsla_position * position_ratio)
        for h_idx in range(len(hedge_dfs)):
            # 如果 TSLA 没仓位，则按权重分给 hedge
            h_pos = (weights[h_idx] * position_ratio) if tsla_position == 0 else 0
            hedge_pos_matrix[h_idx].append(h_pos)

    # 4. 计算收益
    combined = pd.DataFrame(index=common_dates)
    combined["TSLA_Position"] = tsla_pos_list
    combined["TSLA_Market_Return"] = tsla_df["Close"].pct_change()
    combined["TSLA_Return"] = combined["TSLA_Position"].shift(1) * combined["TSLA_Market_Return"]

    combined["Combined_Strategy_Return"] = combined["TSLA_Return"].fillna(0)

    for h_idx, hdf in enumerate(hedge_dfs):
        h_name = f"Hedge_{h_idx}"
        combined[f"{h_name}_Position"] = hedge_pos_matrix[h_idx]
        combined[f"{h_name}_Market_Return"] = hdf["Close"].pct_change()
        combined[f"{h_name}_Return"] = combined[f"{h_name}_Position"].shift(1) * combined[f"{h_name}_Market_Return"]
        combined["Combined_Strategy_Return"] += combined[f"{h_name}_Return"].fillna(0)

    # 计算累计盈亏供报表展示
    cum_pnl = 0
    for t in trades:
        if t["pnl"] is not None:
            cum_pnl += t["pnl"]
            t["cum_pnl"] = round(cum_pnl, 2)
            t["cum_pnl_pct"] = round(cum_pnl / initial_capital * 100, 2)

    return combined, trades

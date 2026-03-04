# -*- coding: utf-8 -*-
"""
MA 金叉死叉策略模块

逻辑简述：
- 买入：短均线上穿长均线（金叉），且可选「收盘价 > 短均线」过滤，支持入场延迟 N 根 K
- 卖出：短均线在长均线下方（死叉）

约定：
- Position：当前 K 收盘后的持仓（0 或 1）
- Strategy_Return：用「上一根 K 收盘后」的持仓 × 当日收益率
"""

import pandas as pd


def run(df, ma_short=5, ma_long=30, use_price_filter=True, entry_delay=0, exit_delay=0,
        initial_capital=100000, position_ratio=1.0):
    """
    在行情数据上计算 MA 金叉死叉的持仓与收益。

    参数
    ----
    df : pd.DataFrame
        需含 Close，索引为日期。
    ma_short, ma_long : int
        短均线、长均线周期（如 5、30）。
    use_price_filter : bool
        True 时仅当 Close > 短均线 才允许入场。
    entry_delay : int
        金叉出现后，延迟多少根 K 才允许入场；0 表示下一根满足条件即可入场。
    exit_delay : int
        死叉出现后，延迟多少根 K 才允许出场；0 表示下一根满足条件即可出场。

    initial_capital : float
        初始资金，默认 100000。
    position_ratio : float
        持仓比例，默认 1.0（全仓）。

    返回
    ----
    tuple
        (df, trades) - df 包含策略计算结果，trades 是交易清单列表。
    """
    df = df.copy()
    # 均线（列名固定为 MA5/MA30，与周期一致时便于阅读），保留两位小数
    df["MA5"] = df["Close"].rolling(window=ma_short).mean().round(2)
    df["MA30"] = df["Close"].rolling(window=ma_long).mean().round(2)

    # 金叉：当前短>长，前一根短<=长
    cross_long = (df["MA5"] >= df["MA30"]) & (df["MA5"].shift(1) < df["MA30"].shift(1))
    # 死叉：当前短<长，前一根短>=长
    sell_signal = (df["MA5"] <= df["MA30"]) & (df["MA5"].shift(1) > df["MA30"].shift(1))
    # 入场过滤：不启用则恒为 True（这里始终使用与 df 同索引的布尔序列，避免 use_price_filter=False 时标量 True 无法 iloc）
    price_ok = df["Close"] >= df["MA5"] if use_price_filter else pd.Series(True, index=df.index)
    buy_signal = cross_long & price_ok

    # 打印所有金叉和死叉信号
    print("\n" + "=" * 80)
    print(f"{'类型':<6} {'日期':<28} {'MA5':>10} {'MA30':>10} {'Close':>10}")
    print("-" * 80)
    for i in range(len(df)):
        if cross_long.iloc[i]:
            d = df.index[i]
            print(f"{'金叉':<6} {str(d):<28} {df['MA5'].iloc[i]:>10.2f} {df['MA30'].iloc[i]:>10.2f} {df['Close'].iloc[i]:>10.2f}")
        if sell_signal.iloc[i]:
            d = df.index[i]
            print(f"{'死叉':<6} {str(d):<28} {df['MA5'].iloc[i]:>10.2f} {df['MA30'].iloc[i]:>10.2f} {df['Close'].iloc[i]:>10.2f}")
    print("=" * 80 + "\n")

    # 逐 K 线模拟持仓（支持入场延迟和出场延迟）
    position = 0  # 当前持仓：0=空仓，1=持仓
    positions = []  # 持仓列表，用于存储每根 K 的持仓
    trades = []  # 交易清单
    signal_wait = -1  # 金叉后等待的 K 数：-1=无信号，0=信号当根，1=信号后第1根...
    exit_signal_wait = -1  # 死叉后等待的 K 数：-1=无信号，0=信号当根，1=信号后第1根...
    entry_price = 0  # 买入价格，用于计算盈亏
    trade_id = 0  # 交易对编号
    shares = 0  # 持仓股数
    cash = initial_capital  # 可用现金

    for i in range(len(df)):
        date = df.index[i]
        price = df["Close"].iloc[i]

        # 死叉信号检测：信号当根标记为 0，后续 K 线递增
        if sell_signal.iloc[i]:
            if position == 1:
                # 持仓时的死叉：用于出场延迟计数
                exit_signal_wait = 0  # 新信号出现，标记为第 0 根
            else:
                # 空仓时的死叉：取消之前的金叉等待信号（例如 2014-05-08 这种情况）
                signal_wait = -1
        elif exit_signal_wait >= 0 and position == 1:
            exit_signal_wait += 1  # 后续 K 线递增计数

        # 出场延迟满足 + 持仓 → 平仓
        # exit_delay=0 时，exit_signal_wait>=1 即信号后第 1 根 K 线卖出
        if exit_signal_wait >= exit_delay + 1 and position == 1:
            exit_signal_wait = -1  # 重置出场信号计数器
            position = 0
            pnl = round((price - entry_price) * shares, 2)  # 单笔盈亏（金额）
            cash += shares * price
            pnl_pct = round((price - entry_price) / entry_price * 100, 2)  # 单笔盈亏百分比
            trades.append({
                "trade_id": trade_id,
                "date": date,
                "action": "卖出",
                "price": round(price, 2),
                "shares": shares,
                "position_value": round(shares * price, 2),
                "cash": round(cash, 2),
                "pnl": pnl,
                "pnl_pct": pnl_pct,
                "cum_pnl": None,  # 后续计算
                "cum_pnl_pct": None  # 后续计算
            })
            shares = 0

        # 金叉信号检测（仅在空仓时跟踪信号；持仓期间忽略并清零计数）
        # 这样可以保证：每次平仓后，必须等「新的金叉」再次出现才开始重新计时。
        # 同时，如果在平仓当日又出现金叉（例如 2013-10-15），则在当日平仓后会记录这次金叉，
        # 使得下一根 K 线可以作为新的入场机会。
        if position == 0:
            if buy_signal.iloc[i]:
                if signal_wait < 0:
                    signal_wait = 0  # 新信号出现，标记为第 0 根
                else:
                    signal_wait += 1  # 已有信号，在此基础上递增
            elif signal_wait >= 0:
                signal_wait += 1  # 后续 K 线递增计数
        else:
            # 持仓期间不保留旧的金叉等待计数，避免平仓后直接用旧信号再次入场
            signal_wait = -1

        # 延迟满足 + 空仓 + 价格条件满足 → 开仓
        # entry_delay=0 时，signal_wait>=1 即信号后第 1 根 K 线买入
        if signal_wait >= entry_delay + 1 and position == 0 and price_ok.iloc[i]:
            signal_wait = -1  # 重置入场信号计数器
            position = 1
            entry_price = price
            trade_id += 1
            # 计算买入股数：基于当前可用现金和持仓比例
            invest_amount = cash * position_ratio
            shares = int(invest_amount / price)
            if shares == 0:
                # 资金不足以买入1股，跳过此次交易
                position = 0
                trade_id -= 1
            else:
                cash -= shares * price
            trades.append({
                "trade_id": trade_id,
                "date": date,
                "action": "买入",
                "price": round(price, 2),
                "shares": shares,
                "position_value": round(shares * price, 2),
                "cash": round(cash, 2),
                "pnl": None, # 单笔盈亏（金额）
                "pnl_pct": None, # 单笔盈亏（百分比）
                "cum_pnl": None, # 累计盈亏（金额）
                "cum_pnl_pct": None # 累计盈亏（百分比）
            })
        # 等待太久还没开仓 → 放弃这次信号
        # if signal_wait > entry_delay + 1 and position == 0:
        #     signal_wait = -1

        # 等待太久还没平仓（价格又涨回去了）→ 放弃这次出场信号
        if exit_signal_wait > exit_delay + 1 and position == 1:
            exit_signal_wait = -1
        # 记录当前 K 线的持仓状态
        positions.append(position)

    # 计算累计盈亏
    cum_pnl = 0
    for trade in trades:
        if trade["pnl"] is not None:
            cum_pnl += trade["pnl"] # 只处理卖出交易（pnl有值）
            trade["cum_pnl"] = round(cum_pnl, 2)
            trade["cum_pnl_pct"] = round(cum_pnl / initial_capital * 100, 2)

    df["Position"] = positions # 每根K线的持仓状态
    df["Market_Return"] = df["Close"].pct_change() # 市场收益率
    # 策略收益 = 昨日持仓 × 今日收益率（注意：这里使用的是昨日的持仓，即今日的入场持仓）
    df["Strategy_Return"] = df["Position"].shift(1) * df["Market_Return"]

    return df, trades

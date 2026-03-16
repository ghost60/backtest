# -*- coding: utf-8 -*-
"""
报告输出模块

职责：
- 在终端打印指标表格
- 将策略参数与指标写入 Markdown 文件（便于存档与对比）
"""

import os
import pandas as pd


def _fmt_val(key, val):
    """按指标类型格式化数值：回报/回撤/百分比用百分数，比率用小数，其余用整数。"""
    if not isinstance(val, float):
        return str(val)
    if any(k in key for k in ("回报", "回撤", "百分比")):
        return f"{val:.2%}"
    if "比率" in key:
        return f"{val:.2f}"
    return f"{val:.0f}"


def print_metrics(metrics, title="策略表现报告 (STRATEGY PERFORMANCE REPORT)"):
    """在终端打印指标字典：标题 + 每行「键: 格式化后的值」。"""
    print("\n" + "=" * 40)
    print(title)
    print("=" * 40)
    for k, v in metrics.items():
        # 对关键指标做更明确的说明，但保持原 key 便于代码复用
        label = k
        if k == "策略总回报":
            label = "策略总回报(基于净值曲线)"
        elif k == "基准总回报":
            label = "基准总回报(基于净值曲线)"
        print(f"{label:<20}: {_fmt_val(k, v):>15}")
    print("=" * 40)


def write_markdown(output_path, start_date, end_date, strategy_params, metrics,
                   capital_params=None, trades=None, factor_config=None, title_suffix=""):
    """
    将回测周期、策略参数、核心指标写入 Markdown 文件。

    参数
    ----
    output_path : str
        文件保存路径。
    start_date, end_date : str
        回测起止日期。
    strategy_params : dict
        执行层参数：name, entry_delay, exit_delay。
    metrics : dict
        指标名 -> 数值。
    capital_params : dict, optional
        资金参数，如 initial, position_ratio。
    trades : list, optional
        交易清单，用于计算总盈亏。
    factor_config : dict or list, optional
        因子配置（单因子字典或多因子列表），用于在报告中展示因子与参数。
    title_suffix : str
        报告标题后缀，可选。
    """
    out_dir = os.path.dirname(output_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    initial = capital_params.get("initial", 100000) if capital_params else 100000
    pos_ratio = capital_params.get("position_ratio", 1.0) if capital_params else 1.0
    max_leverage = capital_params.get("max_leverage", 1.0) if capital_params else 1.0
    entry_delay = strategy_params.get("entry_delay", 0)
    exit_delay = strategy_params.get("exit_delay", 0)
    param_rows = [
        f"| 入场延迟 | {entry_delay} 根K线 |",
        f"| 出场延迟 | {exit_delay} 根K线 |",
    ]
    if factor_config:
        # 兼容字典或多因子的列表
        f_configs = factor_config if isinstance(factor_config, list) else [factor_config]
        for i, cfg in enumerate(f_configs):
            ftype = cfg.get("type", "unknown")
            fparams = cfg.get("params", {})
            alloc = cfg.get("capital_alloc", 1.0)
            prefix = f"因子{i+1}[{ftype}]"
            param_rows.append(f"| {prefix} 资金占比 | {alloc:.0%} |")
            for k, v in sorted(fparams.items()):
                param_rows.append(f"| {prefix}.{k} | {v} |")
    else:
        ma_s = strategy_params.get("ma_short", 5)
        ma_l = strategy_params.get("ma_long", 30)
        param_rows.append(f"| 价格过滤 (Close>MA{ma_s}) | {'启用' if strategy_params.get('use_price_filter', True) else '禁用'} |")
        param_rows.append(f"| 买入信号 | MA{ma_s}金叉MA{ma_l} 且 Close>MA{ma_s} |")
        param_rows.append("| 卖出信号 | MA死叉 |")
    total_pnl = 0
    total_return_pct = 0
    if trades:
        last_trade = trades[-1]
        total_pnl = last_trade.get("cum_pnl", 0) or 0
        total_return_pct = last_trade.get("cum_pnl_pct", 0) or 0

    lines = [
        "# 策略回测表现报告" + (" " + title_suffix if title_suffix else ""),
        "",
        f"**回测周期**: {start_date} 至 {end_date}",
        "",
        "### 资金参数",
        "",
        "| 参数 | 值 |",
        "| :--- | :--- |",
        f"| 初始资金 | ${initial:,.0f} |",
        f"| 持仓比例 | {pos_ratio:.0%} |",
        f"| 最大杠杆倍数 | {max_leverage:.2f}x |",
        "",
        "### 策略参数",
        "",
        "| 参数 | 值 |",
        "| :--- | :--- |",
    ]
    lines += param_rows
    lines += [
        "",
        "### 盈亏汇总（基于实际成交）",
        "",
        "| 指标 | 数值 |说明|",
        "| :--- | :--- |:---|",
        f"| 总盈亏 | ${total_pnl:,.2f} | 基于每笔实际成交价与股数累计的盈亏金额 |",
        f"| 总收益率(成交口径) | {total_return_pct:.2f}% | 总盈亏 / 初始资金，仅按交易结果计算 |",
        f"| 最终资产 | ${initial + total_pnl:,.2f} | 初始资金 + 总盈亏 |",
        "",
        "### 核心指标（基于净值曲线）",
        "",
        "| 指标 | 数值 |",
        "| :--- | :--- |",
    ]
    for k, v in metrics.items():
        label = k
        if k == "策略总回报":
            label = "策略总回报(净值口径)"
        elif k == "基准总回报":
            label = "基准总回报(净值口径)"
        lines.append(f"| {label} | {_fmt_val(k, v)} |")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"指标已保存: {output_path}")


def write_markdown_hedge(output_path, start_date, end_date, strategy_params, metrics,
                          hedge_names, capital_params=None, trades=None, factor_config=None, title_suffix=""):
    """
    将对冲策略的回测表现写入 Markdown 文件。
    """
    out_dir = os.path.dirname(output_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    param_rows = [
        f"| 入场延迟 | {strategy_params.get('entry_delay', 0)} 根K线 |",
        f"| 出场延迟 | {strategy_params.get('exit_delay', 0)} 根K线 |",
    ]
    if factor_config:
        f_configs = factor_config if isinstance(factor_config, list) else [factor_config]
        for i, cfg in enumerate(f_configs):
            ftype = cfg.get("type", "unknown")
            fparams = cfg.get("params", {})
            alloc = cfg.get("capital_alloc", 1.0)
            prefix = f"因子{i+1}[{ftype}]"
            param_rows.append(f"| {prefix} 资金占比 | {alloc:.0%} |")
            for k, v in sorted(fparams.items()):
                param_rows.append(f"| {prefix}.{k} | {v} |")
    else:
        param_rows.extend([
            f"| 价格过滤 | {'启用' if strategy_params.get('use_price_filter', True) else '禁用'} |",
            f"| 短均线周期 | {strategy_params.get('ma_short', 5)} |",
            f"| 长均线周期 | {strategy_params.get('ma_long', 30)} |",
        ])

    initial = capital_params.get("initial", 100000) if capital_params else 100000
    max_leverage = capital_params.get("max_leverage", 1.0) if capital_params else 1.0

    lines = [
        "# 对冲策略回测表现报告" + (" " + title_suffix if title_suffix else ""),
        "",
        f"**回测周期**: {start_date} 至 {end_date}",
        "",
        "### 资金参数",
        "",
        "| 参数 | 值 |",
        "| :--- | :--- |",
        f"| 初始资金 | ${initial:,.0f} |",
        f"| 最大杠杆倍数 | {max_leverage:.2f}x |",
        "",
        "### 策略说明",
        "",
        "本策略实现多资产对冲交易：",
        "- 当主标的（TSLA）出现金叉买入信号时，**全仓买入主标的**",
        "- 当主标的出现死叉卖出信号时，**按权重比例切换至对冲标的组合**",
        f"- 对冲标的: {', '.join(hedge_names)}",
        "",
        "### 策略参数",
        "",
        "| 参数 | 值 |",
        "| :--- | :--- |",
    ]
    lines += param_rows
    lines += [
        "",
        "### 盈亏汇总",
        "",
        "| 指标 | 数值 |",
        "| :--- | :--- |",
    ]

    total_pnl = 0
    total_return_pct = 0
    if trades:
        last_trade = trades[-1]
        total_pnl = last_trade.get('cum_pnl', 0) or 0
        total_return_pct = last_trade.get('cum_pnl_pct', 0) or 0
    
    lines += [
        f"| 总盈亏 (对冲段) | ${total_pnl:,.2f} |",
        f"| 总收益率 (对冲段) | {total_return_pct:.2f}% |",
        f"| 初始资金 | ${initial:,.0f} |",
        "",
        "### 核心指标",
        "",
        "| 指标 | 数值 |",
        "| :--- | :--- |",
    ]

    for k, v in metrics.items():
        lines.append(f"| {k} | {_fmt_val(k, v)} |")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"对冲指标报告已保存: {output_path}")


def print_trades(trades):
    """在终端打印交易清单表格。"""
    if not trades:
        print("\n===== 无交易记录 =====")
        return

    print(f"\n===== 交易清单（共 {len(trades)} 笔）=====")
    print(f"{'交易ID':<8} {'日期':<22} {'操作':<6} {'价格':<10} {'股数':<10} {'仓位价值':<12} {'现金':<12} {'盈亏($)':<12} {'盈亏(%)':<10} {'累计盈亏($)':<14} {'累计(%)':<10}")
    print("-" * 130)
    for trade in [t for t in trades]:
        pnl_str = f"{trade['pnl']:,.2f}" if trade['pnl'] is not None else "-"
        pnl_pct_str = f"{trade['pnl_pct']:.2f}%" if trade['pnl_pct'] is not None else "-"
        cum_pnl_str = f"{trade['cum_pnl']:,.2f}" if trade['cum_pnl'] is not None else "-"
        cum_pnl_pct_str = f"{trade['cum_pnl_pct']:.2f}%" if trade['cum_pnl_pct'] is not None else "-"
        
        # 处理 cash 可能为 "-" 的情况
        cash_val = trade['cash']
        cash_str = f"{cash_val:,.2f}" if isinstance(cash_val, (int, float)) else str(cash_val)
        
        print(f"{trade['trade_id']:<8} {str(trade['date']):<22} {trade['action']:<6} "
              f"{trade['price']:<10.2f} {trade['shares']:<10} {trade['position_value']:>12,.2f} "
              f"{cash_str:>12} {pnl_str:>12} {pnl_pct_str:>10} {cum_pnl_str:>14} {cum_pnl_pct_str:>10}")
    print("-" * 130)


def save_trades_csv(trades, output_path):
    """将交易清单保存为 CSV 文件。"""
    if not trades:
        return

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    trades_df = pd.DataFrame(trades)
    trades_df.to_csv(output_path, index=False, encoding='utf-8-sig')
    print(f"交易清单已保存至: {output_path}")

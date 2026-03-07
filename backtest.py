# -*- coding: utf-8 -*-
"""
回测流程编排模块

职责：
- 按配置加载数据、运行策略、计算净值与指标、输出报告与图表
- 对外只暴露 run_backtest(config=None, config_path=None)，返回 metrics、df_clean、config
"""

import os
from pathlib import Path

# 包内相对导入，便于作为 backtest 包运行时正确解析（如 python -m backtest.tools.ma_param_search）
from .report import charts
from .report import metrics
from .report import report
from . import data_loader
from .factor import factor_double_ma
from .factor import factor_adx_ma
from .engine.single_asset import run_single_asset
from .report.quan_stats_report import generate_qs_report
from .config_loader import get_capital_params, get_output_paths, get_strategy_params, get_factor_config, get_hedge_config, load_config, PROJECT_ROOT

# 因子注册表：type -> (module, 计算函数名)，便于按配置调度
FACTOR_REGISTRY = {
    "double_ma": (factor_double_ma, "calculate_double_ma_factors"),
    "adx_ma": (factor_adx_ma, "calculate_adx_ma_factors"),
}
# 各因子输出的买卖信号列名（当前单/双均线一致，后续可扩展为从因子返回）
SIGNAL_BUY_COL = "MA_Buy_Signal"
SIGNAL_SELL_COL = "MA_Sell_Signal"


def _print_signals(df, buy_col=SIGNAL_BUY_COL, sell_col=SIGNAL_SELL_COL):
    """打印所有买入、卖出信号及产生信号时的各参数（价格与指标）。"""
    buys = df.index[df[buy_col]].tolist()
    sells = df.index[df[sell_col]].tolist()
    # 用于打印的因子/价格列（排除布尔信号列）
    skip = {buy_col, sell_col}
    param_cols = [c for c in df.columns if c not in skip and hasattr(df[c].dtype, "kind") and df[c].dtype.kind in "fiu" and (c in ("Open", "High", "Low", "Close") or c.startswith("MA") or c in ("ADX", "+DI", "-DI"))]
    if not buys and not sells:
        print("  （无买卖信号）")
        return
    print("  ---------- 买入信号 ----------")
    for i, dt in enumerate(buys, 1):
        row = df.loc[dt]
        vals = [f"{dt.strftime('%Y-%m-%d')}"]
        for col in param_cols:
            v = row[col] if col in row.index else None
            if v is None or (isinstance(v, float) and v != v):
                s = "-"
            elif isinstance(v, float):
                s = f"{v:.4g}" if abs(v) >= 1e-4 else f"{v:.2e}"
            else:
                s = str(v)
            vals.append(f"{col}={s}")
        print(f"    {i}. " + "  ".join(vals))
    print("  ---------- 卖出信号 ----------")
    for i, dt in enumerate(sells, 1):
        row = df.loc[dt]
        vals = [f"{dt.strftime('%Y-%m-%d')}"]
        for col in param_cols:
            v = row[col] if col in row.index else None
            if v is None or (isinstance(v, float) and v != v):
                s = "-"
            elif isinstance(v, float):
                s = f"{v:.4g}" if abs(v) >= 1e-4 else f"{v:.2e}"
            else:
                s = str(v)
            vals.append(f"{col}={s}")
        print(f"    {i}. " + "  ".join(vals))
    print(f"  合计: 买入 {len(buys)} 次, 卖出 {len(sells)} 次")


def run_backtest(config=None, config_path=None):
    """
    执行一次完整回测：加载配置 → 数据 → 策略 → 净值 → 指标 → 报告 + 图表。

    参数
    ----
    config : dict, optional
        已加载的配置；若提供则不再读 config_path。
    config_path : str, optional
        YAML 配置文件路径；不提供则用 config/double_ma.yaml。

    返回
    ----
    dict
        metrics: 指标字典；df_clean: 去 NaN 后的带净值的数据；config: 所用配置。
    """
    if config is None:
        config = load_config(config_path)

    resolved = config.get("_resolved", {})
    data_path = resolved.get("data_path")
    if not data_path or not os.path.isfile(data_path):
        raise FileNotFoundError(f"数据文件不存在: {data_path}")

    data_cfg = config.get("data", {})
    start_date = data_cfg.get("start_date")
    end_date = data_cfg.get("end_date")
    strategy_params = get_strategy_params(config)
    capital_params = get_capital_params(config)
    paths = get_output_paths(config)
    out_cfg = config.get("output", {})

    # 1. 加载数据
    print(f"正在加载数据 ({start_date} 至 {end_date})...")
    df = data_loader.load_data(data_path, start_date=start_date, end_date=end_date)

    # 2. 运行策略：先计算因子与信号，再交给通用撮合引擎
    print("正在运行策略...")
    factor_cfg = get_factor_config(config)
    factor_type = factor_cfg["type"]
    factor_params = dict(factor_cfg["params"])
    if factor_type not in FACTOR_REGISTRY:
        raise ValueError(f"不支持的因子类型: {factor_type}，可选: {list(FACTOR_REGISTRY.keys())}")
    # adx_ma：若启用其他资产过滤长均线，加载 other_asset 数据并传入因子
    if factor_type == "adx_ma" and factor_params.get("use_other_asset"):
        other_path = factor_params.pop("other_asset_path", None)
        if other_path:
            p = Path(other_path)
            if not p.is_absolute():
                p = Path(PROJECT_ROOT) / p
            other_asset_df = data_loader.load_data(str(p), start_date=start_date, end_date=end_date)
            factor_params["other_asset_df"] = other_asset_df
            print(f"已加载长均线过滤标的: {other_path}")
        else:
            factor_params["other_asset_df"] = None
    else:
        factor_params.pop("other_asset_path", None)
    module, fn_name = FACTOR_REGISTRY[factor_type]
    factor_fn = getattr(module, fn_name)
    df = factor_fn(df, **factor_params)
    print(f"策略参数: 因子={factor_type}, {factor_params}")
    print(f"资金参数: {capital_params}")
    print("买卖信号:")
    _print_signals(df)

    # 2.2 撮合层
    df, trades = run_single_asset(
        df,
        buy_signal=df[SIGNAL_BUY_COL],
        sell_signal=df[SIGNAL_SELL_COL],
        entry_delay=strategy_params.get("entry_delay", 0),
        exit_delay=strategy_params.get("exit_delay", 0),
        initial_capital=capital_params.get("initial_capital", 100000),
        position_ratio=capital_params.get("position_ratio", 1.0),
        price_col="Open",
    )

    # 3. 净值与指标（去掉均线导致的 NaN）
    print("正在计算指标...")
    df_clean = df.dropna().copy()
    df_clean = metrics.calculate_equity(df_clean)
    result_metrics = metrics.calculate_metrics(df_clean)

    # 4. 终端报告
    report.print_metrics(result_metrics)

    # 5. Markdown 报告
    out_dir = paths["output_dir"]
    os.makedirs(out_dir, exist_ok=True)

    # 6. 输出并保存交易清单
    # report.print_trades(trades)
    trades_csv_path = os.path.join(out_dir, paths["trades_filename"])
    report.save_trades_csv(trades, trades_csv_path)
    md_path = os.path.join(out_dir, paths["metrics_filename"])
    report.write_markdown(md_path, start_date, end_date, strategy_params, result_metrics, capital_params, trades, factor_config=factor_cfg)

    # 6. 图表
    charts.apply_style(out_cfg.get("font_sans_serif"))
    chart_path = os.path.join(out_dir, paths["chart_filename"])
    charts.generate_charts(df_clean, chart_path, figsize=tuple(out_cfg.get("chart_figsize", [12, 10])))

    # 7. QuantStats 报告
    qs_report_path = os.path.join(out_dir, paths["qs_report_filename"])
    generate_qs_report(df_clean["Strategy_Return"], benchmark=df_clean["Market_Return"],
                                     output_path=qs_report_path, title=f"回测分析报告 ({paths['config_name']})")

    return {"metrics": result_metrics, "df_clean": df_clean, "config": config, "trades": trades}


def run_hedge_backtest(config=None, config_path=None):
    """
    执行对冲回测流程。
    """
    from .report import charts_hedge
    from .factor import factor_double_ma_hedge

    if config is None:
        config = load_config(config_path)

    resolved = config.get("_resolved", {})
    tsla_path = resolved.get("data_path")
    
    data_cfg = config.get("data", {})
    start_date = data_cfg.get("start_date")
    end_date = data_cfg.get("end_date")
    strategy_params = get_strategy_params(config)
    capital_params = get_capital_params(config)
    paths = get_output_paths(config)
    out_cfg = config.get("output", {})
    hedge_cfg = get_hedge_config(config)
    factor_cfg = get_factor_config(config)

    if not hedge_cfg["enabled"]:
        print("警告: 配置文件中未启用对冲 (hedge.enabled=false)，正在退回标准回测...")
        return run_backtest(config=config)

    # 1. 加载数据
    print(f"正在加载 TSLA 数据...")
    tsla_df = data_loader.load_data(tsla_path, start_date=start_date, end_date=end_date)
    
    hedge_dfs = []
    hedge_names = []
    weights = []
    for s in hedge_cfg["symbols"]:
        print(f"正在加载对冲标的数据: {s['name']} ({s['path']})")
        df_h = data_loader.load_data(s["path"], start_date=start_date, end_date=end_date)
        hedge_dfs.append(df_h)
        hedge_names.append(s["name"])
        weights.append(s["weight"])

    # 2. 运行对冲策略（因子参数来自 factor 配置，执行参数来自 strategy）
    print("正在运行对冲策略...")
    df_combined, trades = factor_double_ma_hedge.run(tsla_df, hedge_dfs, weights,
                                            **factor_cfg["params"],
                                            entry_delay=strategy_params.get("entry_delay", 0),
                                            exit_delay=strategy_params.get("exit_delay", 0),
                                            **capital_params,
                                            hedge_names=hedge_names)

    # 3. 计算指标
    print("正在计算指标...")
    df_clean = df_combined.dropna().copy()
    df_clean = metrics.calculate_equity_hedge(df_clean, len(hedge_dfs))
    result_metrics = metrics.calculate_metrics_hedge(df_clean, hedge_names)

    # 4. 终端报告
    report.print_metrics(result_metrics, title="对冲策略表现报告 (HEDGE PERFORMANCE REPORT)")

    # 5. Markdown 报告
    out_dir = paths["output_dir"]
    os.makedirs(out_dir, exist_ok=True)

    # 6. 交易清单
    # report.print_trades(trades)
    trades_csv_path = os.path.join(out_dir, paths["trades_filename"])
    report.save_trades_csv(trades, trades_csv_path)

    md_path = os.path.join(out_dir, paths["metrics_filename"])
    report.write_markdown_hedge(md_path, start_date, end_date, strategy_params, result_metrics, hedge_names, 
                               capital_params=capital_params, trades=trades, factor_config=factor_cfg)

    # 6. 图表
    charts.apply_style(out_cfg.get("font_sans_serif"))
    chart_path = os.path.join(out_dir, paths["chart_filename"])
    charts_hedge.generate_charts_hedge(df_clean, chart_path, hedge_names, 
                                       figsize=tuple(out_cfg.get("chart_figsize", [14, 12])))

    # 7. QuantStats 报告
    qs_report_path = os.path.join(out_dir, paths["qs_report_filename"])
    generate_qs_report(df_clean["Combined_Strategy_Return"],
                                     benchmark=df_clean["TSLA_Market_Return"],
                                     output_path=qs_report_path, title=f"对冲回测报告 ({paths['config_name']})")

    return {"metrics": result_metrics, "df_clean": df_clean, "config": config}

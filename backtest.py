# -*- coding: utf-8 -*-
"""
回测流程编排模块

职责：
- 按配置加载数据、运行策略、计算净值与指标、输出报告与图表
- 对外只暴露 run_backtest(config=None, config_path=None)，返回 metrics、df_clean、config
"""

import os

from . import charts
from . import data_loader
from . import metrics
from . import report
from . import strategy_ma
from . import visualization
from .config_loader import get_capital_params, get_output_paths, get_strategy_params, load_config


def run_backtest(config=None, config_path=None):
    """
    执行一次完整回测：加载配置 → 数据 → 策略 → 净值 → 指标 → 报告 + 图表。

    参数
    ----
    config : dict, optional
        已加载的配置；若提供则不再读 config_path。
    config_path : str, optional
        YAML 配置文件路径；不提供则用 config/default.yaml。

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

    # 2. 运行策略
    print("正在运行策略...")
    print(f"策略参数: {strategy_params}")
    print(f"资金参数: {capital_params}")
    df, trades = strategy_ma.run(df, **strategy_params, **capital_params)

    # 3. 净值与指标（去掉均线导致的 NaN）
    print("正在计算指标...")
    df_clean = df.dropna().copy()
    df_clean = metrics.calculate_equity(df_clean)
    result_metrics = metrics.calculate_metrics(df_clean)

    # 4. 终端报告
    report.print_metrics(result_metrics)

    # 5. Markdown 报告
    out_dir = paths["output_dir"]

    # 6. 输出并保存交易清单
    report.print_trades(trades)
    trades_csv_path = os.path.join(out_dir, "trades.csv")
    report.save_trades_csv(trades, trades_csv_path)
    md_path = os.path.join(out_dir, paths["metrics_filename"])
    report.write_markdown(md_path, start_date, end_date, strategy_params, result_metrics, capital_params, trades)

    # 6. 图表
    charts.apply_style(out_cfg.get("font_sans_serif", "Arial Unicode MS"))
    chart_path = os.path.join(out_dir, paths["chart_filename"])
    charts.generate_charts(df_clean, chart_path, figsize=tuple(out_cfg.get("chart_figsize", [12, 10])))

    # 7. QuantStats 报告
    qs_report_path = os.path.join(out_dir, "qs_report_tsla.html")
    visualization.generate_qs_report(df_clean["Strategy_Return"], benchmark=df_clean["Market_Return"], 
                                     output_path=qs_report_path, title="TSLA 回测分析报告")

    return {"metrics": result_metrics, "df_clean": df_clean, "config": config, "trades": trades}


def run_hedge_backtest(config=None, config_path=None):
    """
    执行对冲回测流程。
    """
    from . import charts_hedge, strategy_hedge
    from .config_loader import get_hedge_config

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

    # 2. 运行对冲策略
    print("正在运行对冲策略...")
    df_combined, trades = strategy_hedge.run(tsla_df, hedge_dfs, weights, 
                                            **strategy_params, **capital_params,
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
    
    # 6. 交易清单
    report.print_trades(trades)
    # 动态生成文件名，如 trades_tsla_azo.csv 或 trades_tsla_azo_orly.csv
    hedge_suffix = "_".join([n.lower() for n in hedge_names])
    trades_csv_path = os.path.join(out_dir, f"trades_tsla_{hedge_suffix}.csv")
    report.save_trades_csv(trades, trades_csv_path)

    md_path = os.path.join(out_dir, paths["metrics_filename"])
    report.write_markdown_hedge(md_path, start_date, end_date, strategy_params, result_metrics, hedge_names, 
                               capital_params=capital_params, trades=trades)

    # 6. 图表
    charts.apply_style(out_cfg.get("font_sans_serif", "Arial Unicode MS"))
    chart_path = os.path.join(out_dir, paths["chart_filename"])
    charts_hedge.generate_charts_hedge(df_clean, chart_path, hedge_names, 
                                       figsize=tuple(out_cfg.get("chart_figsize", [14, 12])))

    # 7. QuantStats 报告
    qs_report_path = os.path.join(out_dir, f"qs_report_tsla_hedge.html")
    visualization.generate_qs_report(df_clean["Combined_Strategy_Return"], 
                                     benchmark=df_clean["TSLA_Market_Return"], 
                                     output_path=qs_report_path, title=f"TSLA 对冲回测报告 ({'_'.join(hedge_names)})")

    return {"metrics": result_metrics, "df_clean": df_clean, "config": config}

# -*- coding: utf-8 -*-
"""
回测流程编排模块

职责：
- 按配置加载数据、运行策略、计算净值与指标、输出报告与图表
- 对外只暴露 run_backtest(config=None, config_path=None)，返回 metrics、df_clean、config
"""

import os
from pathlib import Path
import pandas as pd

# 包内相对导入，便于作为 backtest 包运行时正确解析（如 python -m backtest.tools.ma_param_search）
from .report import charts
from .report import metrics
from .report import report
from . import data_loader
from .factor import factor_double_ma
from .factor import factor_adx_ma
from .factor import factor_double_ma_hedge
from .engine.single_asset import run_single_asset
from .report.quan_stats_report import generate_qs_report
from .data.binance_price import BinancePriceClient
from .config_loader import get_capital_params, get_output_paths, get_strategy_params, get_factor_config, get_hedge_config, load_config, PROJECT_ROOT

# 因子注册表：type -> (module, 计算函数名)，便于按配置调度
FACTOR_REGISTRY = {
    "double_ma": (factor_double_ma, "calculate_double_ma_factors"),
    "double_ma_hedge": (factor_double_ma_hedge, "calculate_double_ma_hedge_factors"),
    "adx_ma": (factor_adx_ma, "calculate_adx_ma_factors"),
}
# 各因子输出的买卖信号列名（当前单/双均线一致，后续可扩展为从因子返回）
SIGNAL_BUY_COL = "MA_Buy_Signal"
SIGNAL_SELL_COL = "MA_Sell_Signal"


def _build_margin_fx_getter(capital_params, start_date=None, end_date=None):
    """
    构建保证金币种兑 USD 汇率获取函数。
    返回:
      callable(date_like) -> fx_to_usd
      或 None（表示使用固定汇率）
    """
    margin_currency = str(capital_params.get("margin_currency", "USD")).upper()
    source = str(capital_params.get("margin_fx_source", "static")).lower()
    if margin_currency == "USD" or source != "binance":
        return None

    symbol = str(capital_params.get("margin_symbol", f"{margin_currency}USDT")).upper()
    interval = str(capital_params.get("margin_fx_interval", "1d"))
    # 高级连接参数使用内置默认，简化用户配置项
    timeout_sec = 5
    retry_times = 2
    retry_sleep_sec = 0.5
    fx_debug = bool(capital_params.get("margin_fx_debug", False))
    fail_fast = True
    exchanges = ["binance", "binanceus"]
    fallback_fx = capital_params.get("margin_fx_to_usd")
    client = BinancePriceClient(
        interval=interval,
        timeout_sec=timeout_sec,
        retry_times=retry_times,
        retry_sleep_sec=retry_sleep_sec,
        debug=fx_debug,
        fail_fast_when_fallback=fail_fast,
        exchanges=exchanges,
    )
    prefetch = bool(capital_params.get("margin_fx_prefetch", True))
    if prefetch and start_date is not None and end_date is not None:
        try:
            loaded = client.prefetch_range(symbol, start_date, end_date)
            print(
                f"[margin_fx] 预拉取完成: symbol={symbol}, interval={interval}, "
                f"loaded={loaded}, range=[{start_date}, {end_date}]"
            )
        except Exception as e:
            print(f"[margin_fx] 预拉取失败，将按需查询: {e}")

    state = {"fallback_warned": False, "fallback_only": False}

    def _getter(ts):
        if state["fallback_only"]:
            return float(fallback_fx)
        try:
            return float(client.get_price_at(symbol, ts))
        except Exception:
            if fallback_fx is not None and float(fallback_fx) > 0:
                state["fallback_only"] = True
                if not state["fallback_warned"]:
                    print(
                        f"警告: Binance 汇率获取失败，已回退为固定汇率 "
                        f"{float(fallback_fx):.6f} (symbol={symbol}, interval={interval})"
                    )
                    state["fallback_warned"] = True
                return float(fallback_fx)
            raise

    return _getter


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
    margin_fx_getter = _build_margin_fx_getter(capital_params, start_date=start_date, end_date=end_date)
    paths = get_output_paths(config)
    out_cfg = config.get("output", {})

    # 1. 加载数据
    print(f"正在加载数据 ({start_date} 至 {end_date})...")
    df = data_loader.load_data(data_path, start_date=start_date, end_date=end_date)

    # 2. 运行策略：支持多因子遍历并合并资金曲线
    print("正在运行策略 (支持多因子)...")
    parsed_factors = get_factor_config(config)
    
    all_trades = []
    # 存储每个因子跑出来的 df（主要为了最后把各因子的 Total_Value 相加）
    factor_results = []
    total_allocated_capital = 0.0
    
    # 组合级别的初始资金（总计）
    total_initial_capital = capital_params.get("initial_capital", 100000)
    
    # 分别运行每个因子
    for i, factor_cfg in enumerate(parsed_factors):
        factor_type = factor_cfg["type"]
        factor_params = dict(factor_cfg["params"])
        alloc_ratio = factor_cfg.get("capital_alloc", 1.0)
        
        # 该因子分配到的独立初始资金
        allocated_capital = total_initial_capital * alloc_ratio
        total_allocated_capital += allocated_capital
        
        if factor_type not in FACTOR_REGISTRY:
            raise ValueError(f"不支持的因子类型: {factor_type}，可选: {list(FACTOR_REGISTRY.keys())}")
            
        # adx_ma 特殊处理 (其他资产长均线)
        if factor_type == "adx_ma" and factor_params.get("use_other_asset"):
            other_path = factor_params.pop("other_asset_path", None)
            if other_path:
                p = Path(other_path)
                if not p.is_absolute():
                    p = Path(PROJECT_ROOT) / p
                other_asset_df = data_loader.load_data(str(p), start_date=start_date, end_date=end_date)
                factor_params["other_asset_df"] = other_asset_df
                print(f"[{factor_type}] 已加载长均线过滤标的: {other_path}")
            else:
                factor_params["other_asset_df"] = None
        else:
            factor_params.pop("other_asset_path", None)
            
        module, fn_name = FACTOR_REGISTRY[factor_type]
        factor_fn = getattr(module, fn_name)
        
        print(f"\n--- 开始运行因子 {i+1}/{len(parsed_factors)}: {factor_type} ---")
        print(f"参数: {factor_params}")
        pos_ratio = float(capital_params.get("position_ratio", 1.0))
        max_leverage = float(capital_params.get("max_leverage", 1.0))
        margin_currency = str(capital_params.get("margin_currency", "USD")).upper()
        margin_fx_source = str(capital_params.get("margin_fx_source", "static")).lower()
        margin_fx_to_usd = capital_params.get("margin_fx_to_usd")
        max_buy_power_margin = allocated_capital * pos_ratio * max_leverage
        if margin_currency == "USD":
            max_buy_power_margin_text = f"{max_buy_power_margin:,.2f} USD"
        elif margin_fx_to_usd is not None and float(margin_fx_to_usd) > 0:
            max_buy_power_margin_text = f"{max_buy_power_margin:,.8f} {margin_currency}"
        elif margin_fx_source == "binance":
            max_buy_power_margin_text = f"动态({margin_currency})"
        else:
            max_buy_power_margin_text = f"N/A {margin_currency}"
        print(
            f"分配资金: {allocated_capital} (占比 {alloc_ratio*100}%)  "
            f"保证金币种: {margin_currency}  "
            f"杠杆上限: {max_leverage:.2f}x  "
            f"最大可用买入规模: {max_buy_power_margin_text}"
        )
        
        # 计算因子信号
        factor_df = factor_fn(df.copy(), **factor_params)
        
        # 打印部分不强制，这里只打印单因子的
        if len(parsed_factors) == 1:
            print("买卖信号:")
            _print_signals(factor_df)

        # 2.2 单因子撮合层
        factor_df, trades = run_single_asset(
            factor_df,
            buy_signal=factor_df[SIGNAL_BUY_COL],
            sell_signal=factor_df[SIGNAL_SELL_COL],
            entry_delay=strategy_params.get("entry_delay", 0),
            exit_delay=strategy_params.get("exit_delay", 0),
            initial_capital=allocated_capital,
            position_ratio=capital_params.get("position_ratio", 1.0),
            max_leverage=capital_params.get("max_leverage", 1.0),
            margin_currency=capital_params.get("margin_currency", "USD"),
            margin_fx_to_usd=capital_params.get("margin_fx_to_usd", 1.0) or 1.0,
            margin_fx_getter=margin_fx_getter,
            margin_settlement_mode=capital_params.get("margin_settlement_mode", "principal_plus_pnl"),
            price_col="Open",
        )
        
        # 标记 trades 来自此因子
        for t in trades:
            t["factor_name"] = factor_type
        all_trades.extend(trades)
        
        factor_results.append(factor_df)

    # 按时间戳排序所有合并后的交易记录
    all_trades.sort(key=lambda x: x["date"])
    
    # ----- 资金聚合 (Portfolio Aggregation) -----
    # 以第一个结果为基准，复制一份汇总的 df
    df_combined = factor_results[0].copy()
    
    # 清空可能属于单一因子的列，仅保留主基准所需
    cols_to_keep = ["Open", "High", "Low", "Close", "Volume", "Market_Return"]
    for c in list(df_combined.columns):
        if c not in cols_to_keep:
            del df_combined[c]
            
    # 把所有因子的 Total_Value 加起来得到超级 Total_Value
    combined_total_value = pd.Series(0.0, index=df_combined.index)
    for f_df in factor_results:
        combined_total_value += f_df["Total_Value"]

    unallocated_cash = max(0.0, total_initial_capital - total_allocated_capital)
    if unallocated_cash:
        combined_total_value += unallocated_cash

    df_combined["Total_Value"] = combined_total_value
    # 组合的策略真实百分比回报
    df_combined["Strategy_Return"] = df_combined["Total_Value"].pct_change().fillna(0.0)

    # （为了报告和画图接口兼容，保留一个汇总的 Position：若任意一因子有头寸则为1）
    has_pos = pd.Series(False, index=df_combined.index)
    for f_df in factor_results:
        has_pos |= (f_df["Position"] > 0)
    df_combined["Position"] = has_pos.astype(int)

    df = df_combined # 让底下的 df_clean 处理使用组合 df
    trades = all_trades
    
    # 3. 净值与指标（去掉均线导致的 NaN）
    print("正在计算指标...")
    df_clean = df.dropna().copy()
    df_clean = metrics.calculate_equity(df_clean)
    result_metrics = metrics.calculate_metrics(df_clean, trades=trades)

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
    # 传递 parsed_factors 给报告，这样可以打印出多个因子的配置
    report.write_markdown(md_path, start_date, end_date, strategy_params, result_metrics, capital_params, trades, factor_config=parsed_factors)

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
    margin_fx_getter = _build_margin_fx_getter(capital_params, start_date=start_date, end_date=end_date)
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
                                            initial_capital=capital_params.get("initial_capital", 100000),
                                            position_ratio=capital_params.get("position_ratio", 1.0),
                                            max_leverage=capital_params.get("max_leverage", 1.0),
                                            margin_currency=capital_params.get("margin_currency", "USD"),
                                            margin_fx_to_usd=capital_params.get("margin_fx_to_usd", 1.0) or 1.0,
                                            margin_fx_getter=margin_fx_getter,
                                            hedge_names=hedge_names)

    # 3. 计算指标
    print("正在计算指标...")
    df_clean = df_combined.dropna().copy()
    df_clean = metrics.calculate_equity_hedge(df_clean, len(hedge_dfs))
    result_metrics = metrics.calculate_metrics_hedge(df_clean, hedge_names, trades=trades)

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

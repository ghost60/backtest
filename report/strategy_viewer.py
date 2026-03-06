#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
策略查看器（Strategy Viewer）

功能：
- 读取指定配置文件，运行回测/对冲回测
- 在终端集中展示参数
- 可选生成专用「策略查看器图」：价格 + 信号 + MA 指标 + 权益曲线 + 回撤 + 持仓

用法示例（在项目根的上一层目录运行）：
    python -m backtest.strategy_viewer -c backtest/config/default.yaml --viewer-chart

也可以在 backtest 目录内直接运行脚本：
    python strategy_viewer.py -c config/default.yaml --viewer-chart
"""

import argparse
import sys
import webbrowser
from pathlib import Path
from copy import deepcopy

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

# 参考 main.py，将项目根加入 sys.path，保证脚本/包两种运行方式都能导入 backtest
_PKG_DIR = Path(__file__).resolve().parent  # backtest/
if str(_PKG_DIR.parent) not in sys.path:
    sys.path.insert(0, str(_PKG_DIR.parent))

from backtest.backtest import run_backtest, run_hedge_backtest  # type: ignore
from backtest.config_loader import (  # type: ignore
    load_config,
    get_output_paths,
    get_strategy_params,
    get_capital_params,
    get_hedge_config,
)


def plot_strategy_viewer(df: pd.DataFrame, trades, output_path: Path):
    """
    生成「资产曲线 + 交易信号 + 指标 + 回撤」综合查看图。
    仅针对单标的回测（含 Close / MA 列等）。
    """
    if df is None or df.empty:
        print("警告: 无法绘制策略视图，df 为空。")
        return

    # 准备买卖点
    buy_x, buy_y, sell_x, sell_y = [], [], [], []
    for t in trades or []:
        d = pd.to_datetime(t.get("date"))
        if d in df.index:
            if t.get("action") in ("买入", "Buy", "LONG", "Long"):
                buy_x.append(d)
                buy_y.append(t.get("price"))
            elif t.get("action") in ("卖出", "Sell", "SHORT", "Short"):
                sell_x.append(d)
                sell_y.append(t.get("price"))

    # 计算回撤
    eq = df.get("Strategy_Equity")
    dd = None
    if eq is not None:
        rolling_max = eq.cummax()
        dd = (eq - rolling_max) / rolling_max

    output_path.parent.mkdir(parents=True, exist_ok=True)

    fig, axes = plt.subplots(3, 1, figsize=(14, 10), sharex=True)

    # 子图 1：价格 + 信号 + 均线
    ax_price = axes[0]
    if "Close" in df.columns:
        ax_price.plot(df.index, df["Close"], label="Close", color="black", linewidth=1)
    for col, color in [("MA5", "tab:blue"), ("MA30", "tab:orange")]:
        if col in df.columns:
            ax_price.plot(df.index, df[col], label=col, linewidth=1, alpha=0.8, color=color)

    if buy_x:
        ax_price.scatter(buy_x, buy_y, marker="^", color="green", label="买入", zorder=5)
    if sell_x:
        ax_price.scatter(sell_x, sell_y, marker="v", color="red", label="卖出", zorder=5)

    ax_price.set_ylabel("价格")
    ax_price.set_title("价格走势与交易信号 / 指标")
    ax_price.legend(loc="best")
    ax_price.grid(True, linestyle="--", alpha=0.3)

    # 子图 2：策略权益 + 回撤
    ax_eq = axes[1]
    if "Strategy_Equity" in df.columns:
        ax_eq.plot(df.index, df["Strategy_Equity"], label="策略净值", color="tab:blue")
    if "Market_Equity" in df.columns:
        ax_eq.plot(df.index, df["Market_Equity"], label="基准净值", color="tab:orange", alpha=0.6)

    ax_eq.set_ylabel("净值")
    ax_eq.set_title("权益曲线与回撤")
    ax_eq.grid(True, linestyle="--", alpha=0.3)

    if dd is not None:
        ax_dd = ax_eq.twinx()
        ax_dd.fill_between(df.index, dd, 0, color="red", alpha=0.2, label="回撤")
        ax_dd.set_ylabel("回撤")
        ax_dd.set_ylim(-1, 0)
        lines, labels = ax_eq.get_legend_handles_labels()
        lines2, labels2 = ax_dd.get_legend_handles_labels()
        ax_eq.legend(lines + lines2, labels + labels2, loc="upper left")
    else:
        ax_eq.legend(loc="best")

    # 子图 3：持仓与收益（简单同步监控）
    ax_pos = axes[2]
    if "Position" in df.columns:
        ax_pos.step(df.index, df["Position"], where="post", label="Position", color="tab:green")
    if "Strategy_Return" in df.columns:
        ax_pos.plot(
            df.index,
            (1 + df["Strategy_Return"]).cumprod(),
            label="策略收益累积",
            color="tab:blue",
            alpha=0.7,
        )

    ax_pos.set_ylabel("持仓 / 累积收益")
    ax_pos.set_title("持仓状态与收益同步视图")
    ax_pos.grid(True, linestyle="--", alpha=0.3)
    ax_pos.legend(loc="best")

    fig.autofmt_xdate()
    plt.tight_layout()
    plt.savefig(output_path, dpi=150)
    plt.close(fig)
    print(f"策略查看器图已保存: {output_path}")

def main():
    parser = argparse.ArgumentParser(description="TSLA 策略查看器（运行并查看回测结果）")
    parser.add_argument(
        "-c",
        "--config",
        default="config/default.yaml",
        help="配置文件路径（YAML），默认 config/default.yaml",
    )

    args = parser.parse_args()

    # 1. 加载配置
    cfg = load_config(args.config)
    cfg = deepcopy(cfg)

    hedge_cfg = get_hedge_config(cfg)
    is_hedge = bool(hedge_cfg.get("enabled"))

    print("=" * 80)
    print(f"使用配置文件: {args.config}")
    print(f"是否对冲策略: {'是' if is_hedge else '否'}")
    print("=" * 80)

    # 2. 打印核心参数
    strategy_params = get_strategy_params(cfg)
    capital_params = get_capital_params(cfg)
    print("\n策略参数:")
    for k, v in strategy_params.items():
        print(f"  {k}: {v}")
    print("\n资金参数:")
    for k, v in capital_params.items():
        print(f"  {k}: {v}")

    # 3. 运行回测
    if is_hedge:
        print("\n检测到已启用对冲配置，运行对冲回测...")
        result = run_hedge_backtest(config=cfg)
    else:
        print("\n运行标准单标的回测...")
        result = run_backtest(config=cfg)

    metrics = result.get("metrics", {})
    trades = result.get("trades", [])
    df_clean = result.get("df_clean")

    # 4. 解析输出目录（用于保存查看器图）
    paths = get_output_paths(cfg)
    out_dir = Path(paths["output_dir"])
    out_dir.mkdir(parents=True, exist_ok=True)

    # 5. 策略查看器综合图（仅单标的）
    if not is_hedge:
        if df_clean is None or df_clean.empty:
            print("警告: df_clean 为空，无法生成策略查看器图。")
        else:
            viewer_path = out_dir / "strategy_viewer.png"
            plot_strategy_viewer(df_clean, trades, viewer_path)
            if viewer_path.is_file():
                try:
                    webbrowser.open(viewer_path.as_uri())
                except Exception:
                    pass


if __name__ == "__main__":
    main()


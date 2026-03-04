#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
MA 双均线策略参数搜索脚本

用法：
- 在 `backtest` 包的上一层目录运行（包方式）：
    python -m backtest.ma_param_search
- 也可以在 `backtest` 目录内直接运行脚本：
    python ma_param_search.py

逻辑：
- 读取基础配置（默认使用 config/default.yaml）
- 在给定的 (ma_short, ma_long) 网格上循环：
    - 注入到 cfg["strategy"] 里
    - 调用 run_backtest(config=cfg)
    - 记录关键指标（夏普、年化、最大回撤等）
- 按目标指标排序，输出 TOP N 组合
"""

from copy import deepcopy
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd


# 参考 main.py，将项目根加入 sys.path，保证脚本/包两种运行方式都能导入 backtest
_PKG_DIR = Path(__file__).resolve().parent  # backtest/
if str(_PKG_DIR.parent) not in sys.path:
    sys.path.insert(0, str(_PKG_DIR.parent))

from backtest.backtest import run_backtest
from backtest.config_loader import load_config, get_output_paths


# 可调参数网格（按需修改）
SHORT_LIST = range(3, 21, 2)  # 3,5,7,...,19
LONG_LIST = range(30, 121, 5)  # 30,35,...,120

# 评价指标 key（来自 metrics.calculate_metrics 的返回）
# 可选："夏普比率"、"策略年化回报"、"策略总回报" 等
TARGET_METRIC = "夏普比率"
# 生成热力图时用于文件名的安全版本
TARGET_METRIC_FNAME = TARGET_METRIC.replace("%", "pct").replace("/", "_").replace(" ", "")

# 输出最优多少组参数
TOP_N = 20


def main():
    # 1. 读取基础配置（可按需改成其他配置文件）
    base_cfg = load_config("config/default.yaml")

    all_results = []

    # 2. 遍历参数网格
    for ma_short in SHORT_LIST:
        for ma_long in LONG_LIST:
            # 一般要求短均线 < 长均线
            if ma_short >= ma_long:
                continue

            cfg = deepcopy(base_cfg)
            cfg.setdefault("strategy", {})
            cfg["strategy"]["ma_short"] = ma_short
            cfg["strategy"]["ma_long"] = ma_long

            print("\n" + "=" * 80)
            print(f"开始回测 ma_short={ma_short}, ma_long={ma_long}")
            print("=" * 80)

            out = run_backtest(config=cfg)
            metrics = out["metrics"]

            target_value = metrics.get(TARGET_METRIC, 0.0)

            all_results.append(
                {
                    "ma_short": ma_short,
                    "ma_long": ma_long,
                    TARGET_METRIC: target_value,
                    "策略年化回报": metrics.get("策略年化回报", 0.0),
                    "策略总回报": metrics.get("策略总回报", 0.0),
                    "最大回撤": metrics.get("最大回撤", 0.0),
                }
            )

    if not all_results:
        print("没有得到任何回测结果，请检查参数网格设置。")
        return

    # 3. 构造 DataFrame，生成因子热力图
    df_results = pd.DataFrame(all_results)
    pivot = df_results.pivot(index="ma_short", columns="ma_long", values=TARGET_METRIC)

    paths = get_output_paths(base_cfg)
    out_dir = Path(paths["output_dir"])
    out_dir.mkdir(parents=True, exist_ok=True)
    heatmap_path = out_dir / f"ma_param_heatmap_{TARGET_METRIC_FNAME}.png"

    plt.figure(figsize=(10, 8))
    im = plt.imshow(pivot.values, origin="lower", aspect="auto", cmap="viridis")
    plt.colorbar(im, label=TARGET_METRIC)
    plt.xticks(range(len(pivot.columns)), pivot.columns)
    plt.yticks(range(len(pivot.index)), pivot.index)
    plt.xlabel("ma_long")
    plt.ylabel("ma_short")
    plt.title(f"MA 参数网格 {TARGET_METRIC} 热力图")
    plt.tight_layout()
    plt.savefig(heatmap_path, dpi=150)
    plt.close()

    print(f"\n因子热力图已保存到: {heatmap_path}")

    # 4. 生成目标指标的分箱图（直方图）
    bin_fig_path = out_dir / f"ma_param_hist_{TARGET_METRIC_FNAME}.png"
    plt.figure(figsize=(8, 6))
    plt.hist(df_results[TARGET_METRIC].dropna(), bins=20, color="steelblue", edgecolor="black", alpha=0.8)
    plt.xlabel(TARGET_METRIC)
    plt.ylabel("参数组合数量")
    plt.title(f"{TARGET_METRIC} 分布（参数组合分箱图）")
    plt.tight_layout()
    plt.savefig(bin_fig_path, dpi=150)
    plt.close()

    print(f"因子分箱图已保存到: {bin_fig_path}")

    # 5. 按目标指标排序，并将 TOP N 输出到文件 & 终端
    all_results.sort(key=lambda x: x[TARGET_METRIC], reverse=True)
    top_results = all_results[:TOP_N]
    df_top = pd.DataFrame(top_results)

    top_csv_path = out_dir / f"ma_param_top_{TARGET_METRIC_FNAME}.csv"
    df_top.to_csv(top_csv_path, index=False)
    print(f"按 {TARGET_METRIC} 排序的最优参数 TOP {TOP_N} 已保存到: {top_csv_path}")

    print("\n" + "#" * 80)
    print(f"按 {TARGET_METRIC} 排序的最优参数 TOP {TOP_N}")
    print("#" * 80)

    for r in top_results:
        print(
            f"ma_short={r['ma_short']:>3}, "
            f"ma_long={r['ma_long']:>3}, "
            f"{TARGET_METRIC}={r[TARGET_METRIC]:>7.4f}, "
            f"年化={r['策略年化回报']:>7.4f}, "
            f"总回报={r['策略总回报']:>7.4f}, "
            f"最大回撤={r['最大回撤']:>7.4f}"
        )


if __name__ == "__main__":
    main()


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


# 参考 main.py，将「包含 backtest 包的上层目录」加入 sys.path，
# 这样既支持包方式（python -m backtest.tools.ma_param_search），
# 也支持在 backtest 目录内直接运行脚本（python tools/ma_param_search.py）。
_TOOLS_DIR = Path(__file__).resolve().parent          # backtest/tools
_PROJECT_PARENT = _TOOLS_DIR.parent.parent            # backtest 的上层目录
if str(_PROJECT_PARENT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_PARENT))

from backtest.backtest import run_backtest
from backtest.config_loader import load_config, get_output_paths


# 可调参数网格（按需修改）
SHORT_LIST = range(2, 15, 3)  # 3,5,7,...,19
LONG_LIST = range(30, 60, 10)  # 30,35,...,120

# 评价指标 key（来自 metrics.calculate_metrics 的返回）
# 这里改为按「策略总回报」进行寻参排序
TARGET_METRIC = "策略总回报"
# 生成热力图时用于文件名的安全版本
TARGET_METRIC_FNAME = TARGET_METRIC.replace("%", "pct").replace("/", "_").replace(" ", "")

# 输出最优多少组参数
TOP_N = 20

# 用于“最优参数分箱图”的筛选比例：取前多少比例的参数组作为“最优集合”
# 例如 0.1 表示取指标排名前 10% 的参数组合，再看它们在 ma_short / ma_long 上的分布
TOP_BIN_FRACTION = 0.10


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

    # 4. 生成“最优参数”分箱图：看最优参数集中在哪些区间（而不是指标值本身的分布）
    # 取指标排名前 TOP_BIN_FRACTION 的参数组（至少 1 个）
    top_k = max(1, int(len(df_results) * TOP_BIN_FRACTION))
    df_best = df_results.nlargest(top_k, TARGET_METRIC).copy()

    bin_fig_path = out_dir / f"ma_param_best_bins_{TARGET_METRIC_FNAME}.png"
    fig, axes = plt.subplots(1, 2, figsize=(12, 4))

    # ma_short 分箱（按候选列表的离散取值做计数柱状图）
    short_counts = df_best["ma_short"].value_counts().sort_index()
    axes[0].bar(short_counts.index.astype(str), short_counts.values, color="steelblue", edgecolor="black", alpha=0.85)
    axes[0].set_title(f"最优参数 ma_short 分布（TOP {top_k}）")
    axes[0].set_xlabel("ma_short")
    axes[0].set_ylabel("出现次数")
    axes[0].tick_params(axis="x", rotation=45)
    axes[0].grid(True, axis="y", alpha=0.2)

    # ma_long 分箱
    long_counts = df_best["ma_long"].value_counts().sort_index()
    axes[1].bar(long_counts.index.astype(str), long_counts.values, color="darkorange", edgecolor="black", alpha=0.85)
    axes[1].set_title(f"最优参数 ma_long 分布（TOP {top_k}）")
    axes[1].set_xlabel("ma_long")
    axes[1].set_ylabel("出现次数")
    axes[1].tick_params(axis="x", rotation=45)
    axes[1].grid(True, axis="y", alpha=0.2)

    fig.suptitle(f"最优参数分箱图（按 {TARGET_METRIC} 排名取前 {TOP_BIN_FRACTION:.0%}）", y=1.05)
    fig.tight_layout()
    fig.savefig(bin_fig_path, dpi=150, bbox_inches="tight")
    plt.close(fig)

    print(f"最优参数分箱图已保存到: {bin_fig_path}")

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


#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
MA 双均线参数搜索脚本。

用法:
- 在包含 `backtest` 包的上层目录运行:
    python -m backtest.tools.ma_param_search
- 或在仓库根目录运行:
    python tools/ma_param_search.py
"""

from copy import deepcopy
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd


_TOOLS_DIR = Path(__file__).resolve().parent
_PROJECT_PARENT = _TOOLS_DIR.parent.parent
if str(_PROJECT_PARENT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_PARENT))

from backtest.backtest import run_backtest
from backtest.config_loader import get_factor_config, get_output_paths, load_config


# 可调参数网格
SHORT_LIST = range(2, 15, 3)   # 2, 5, 8, 11, 14
LONG_LIST = range(30, 60, 10)  # 30, 40, 50

# 评价指标
TARGET_METRIC = "策略总回报"
TARGET_METRIC_FNAME = TARGET_METRIC.replace("%", "pct").replace("/", "_").replace(" ", "")

# 输出前多少组参数
TOP_N = 20

def _set_double_ma_params(cfg: dict, ma_short: int, ma_long: int) -> None:
    """把搜索参数写回真正生效的 double_ma 因子配置。"""
    factors = cfg.get("factors")
    if factors:
        for factor_cfg in factors:
            if factor_cfg.get("type") == "double_ma":
                factor_cfg.setdefault("params", {})
                factor_cfg["params"]["ma_short"] = ma_short
                factor_cfg["params"]["ma_long"] = ma_long
                return
        raise ValueError("factors 中未找到 type=double_ma 的因子，无法执行 MA 参数搜索。")

    factor_cfg = cfg.get("factor")
    if factor_cfg and factor_cfg.get("type") == "double_ma":
        factor_cfg.setdefault("params", {})
        factor_cfg["params"]["ma_short"] = ma_short
        factor_cfg["params"]["ma_long"] = ma_long
        return

    raise ValueError("配置中未找到 type=double_ma 的 factor/factors，无法执行 MA 参数搜索。")


def _make_bin_counts(series: pd.Series, candidates) -> pd.Series:
    """按完整候选集合重建计数，避免分箱图只显示出现过的值。"""
    counts = series.value_counts().sort_index()
    return counts.reindex(list(candidates), fill_value=0)


def _aggregate_metric_by_param(df: pd.DataFrame, param_col: str, candidates) -> pd.DataFrame:
    """按参数值聚合目标指标，返回均值和样本数。"""
    grouped = (
        df.groupby(param_col)[TARGET_METRIC]
        .agg(["mean", "count"])
        .reindex(list(candidates))
        .fillna(0.0)
    )
    return grouped


def main():
    base_cfg = load_config("config/double_ma.yaml")

    # 先校验配置里确实有 double_ma 因子，避免跑完才发现参数没生效
    factor_list = get_factor_config(base_cfg)
    if not any(f.get("type") == "double_ma" for f in factor_list):
        raise ValueError("config/double_ma.yaml 中未找到 type=double_ma 的因子配置。")

    all_results = []

    for ma_short in SHORT_LIST:
        for ma_long in LONG_LIST:
            if ma_short >= ma_long:
                continue

            cfg = deepcopy(base_cfg)
            _set_double_ma_params(cfg, ma_short, ma_long)

            print("\n" + "=" * 80)
            print(f"开始回测 ma_short={ma_short}, ma_long={ma_long}")
            print("=" * 80)

            out = run_backtest(config=cfg)
            metrics = out["metrics"]

            all_results.append(
                {
                    "ma_short": ma_short,
                    "ma_long": ma_long,
                    TARGET_METRIC: float(metrics.get(TARGET_METRIC, 0.0)),
                    "策略年化回报": float(metrics.get("策略年化回报", 0.0)),
                    "策略总回报": float(metrics.get("策略总回报", 0.0)),
                    "最大回撤": float(metrics.get("最大回撤", 0.0)),
                }
            )

    if not all_results:
        print("没有得到任何回测结果，请检查参数网格设置。")
        return

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

    print(f"\n热力图已保存到: {heatmap_path}")

    df_best = df_results.copy()
    sample_size = len(df_best)

    bin_fig_path = out_dir / f"ma_param_best_bins_{TARGET_METRIC_FNAME}.png"
    fig, axes = plt.subplots(1, 2, figsize=(12, 4))

    short_stats = _aggregate_metric_by_param(df_best, "ma_short", SHORT_LIST)
    axes[0].bar(short_stats.index.astype(str), short_stats["mean"].values, color="steelblue", edgecolor="black", alpha=0.85)
    axes[0].set_title(f"参数 ma_short 平均{TARGET_METRIC} (全部 {sample_size} 组)")
    axes[0].set_xlabel("ma_short")
    axes[0].set_ylabel(f"平均{TARGET_METRIC}")
    axes[0].tick_params(axis="x", rotation=45)
    axes[0].grid(True, axis="y", alpha=0.2)
    for x, (_, row) in enumerate(short_stats.iterrows()):
        axes[0].text(x, row["mean"], f"n={int(row['count'])}", ha="center", va="bottom", fontsize=9)

    long_stats = _aggregate_metric_by_param(df_best, "ma_long", LONG_LIST)
    axes[1].bar(long_stats.index.astype(str), long_stats["mean"].values, color="darkorange", edgecolor="black", alpha=0.85)
    axes[1].set_title(f"参数 ma_long 平均{TARGET_METRIC} (全部 {sample_size} 组)")
    axes[1].set_xlabel("ma_long")
    axes[1].set_ylabel(f"平均{TARGET_METRIC}")
    axes[1].tick_params(axis="x", rotation=45)
    axes[1].grid(True, axis="y", alpha=0.2)
    for x, (_, row) in enumerate(long_stats.iterrows()):
        axes[1].text(x, row["mean"], f"n={int(row['count'])}", ha="center", va="bottom", fontsize=9)

    fig.suptitle(f"参数聚合图（全部参数组合，按参数值统计平均{TARGET_METRIC}）", y=1.05)
    fig.tight_layout()
    fig.savefig(bin_fig_path, dpi=150, bbox_inches="tight")
    plt.close(fig)

    print(f"最优参数分箱图已保存到: {bin_fig_path}")

    all_results.sort(key=lambda x: x[TARGET_METRIC], reverse=True)
    top_results = all_results[:TOP_N]
    df_top = pd.DataFrame(top_results)

    top_csv_path = out_dir / f"ma_param_top_{TARGET_METRIC_FNAME}.csv"
    df_top.to_csv(top_csv_path, index=False, encoding="utf-8-sig")
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

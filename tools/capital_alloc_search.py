#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
多因子资金分配比例搜索脚本

目标：
- 在给定的最大杠杆约束下（capital.max_leverage），
  自动搜索各因子的 capital_alloc 组合，找到在某个绩效指标下最优的资金分配方案。

用法示例（在项目根目录运行）：
- python -m backtest.tools.capital_alloc_search
- 或直接运行脚本：python tools/capital_alloc_search.py
"""

from __future__ import annotations

from copy import deepcopy
import itertools
from pathlib import Path
import sys

import pandas as pd


# 参考 tools/ma_param_search.py，设置 import 路径
_TOOLS_DIR = Path(__file__).resolve().parent          # backtest/tools
_PROJECT_PARENT = _TOOLS_DIR.parent.parent            # backtest 的上层目录
if str(_PROJECT_PARENT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_PARENT))

from backtest.backtest import run_backtest  # noqa: E402
from backtest.config_loader import load_config, get_output_paths, get_factor_config  # noqa: E402


# ---------------- 可调参数区 ----------------

# 默认使用的多因子配置文件
CONFIG_PATH = "config/multi_factor.yaml"

# 搜索步长与范围：例如 0.0, 0.2, 0.4, ..., max_leverage
# 注意：步长越小，组合数量越多，运行时间越长
ALLOC_STEP = 0.2

# 选择搜索排序口径（二选一，注释掉另一行即可）
TARGET_METRIC = "总盈亏金额"
# TARGET_METRIC = "策略总回报"


def _extract_total_pnl(trades: list[dict]) -> float:
    """从交易清单中提取最终累计盈亏金额。"""
    if not trades:
        return 0.0

    for trade in reversed(trades):
        cum_pnl = trade.get("cum_pnl")
        if cum_pnl is not None:
            return float(cum_pnl)
    return 0.0


def _resolve_target_value(metrics: dict, trades: list[dict]) -> float:
    """按顶部配置的 TARGET_METRIC 解析当前方案的排序值。"""
    if TARGET_METRIC == "总盈亏金额":
        return _extract_total_pnl(trades)
    if TARGET_METRIC == "策略总回报":
        return float(metrics.get("策略总回报", 0.0))
    raise ValueError(f"不支持的 TARGET_METRIC: {TARGET_METRIC}")


def _gen_alloc_grid(n_factors: int, max_leverage: float):
    """
    在 [0, max_leverage] 区间按 ALLOC_STEP 生成离散取值，
    枚举所有 n_factors 维的组合，并筛掉「总和 > max_leverage」和「全 0」的方案。
    """
    if n_factors <= 0:
        return []

    values = []
    v = 0.0
    # 构造 0, step, 2*step, ..., max_leverage
    while v <= max_leverage + 1e-9:
        # 保留两位小数，避免浮点累积误差
        values.append(round(v, 4))
        v += ALLOC_STEP

    combos = []
    for allocs in itertools.product(values, repeat=n_factors):
        total = sum(allocs)
        if total <= 0:
            continue  # 全 0 无意义
        if total - max_leverage > 1e-9:
            continue  # 超过最大杠杆约束
        combos.append(tuple(allocs))
    return combos


def main():
    # 1. 读取多因子基础配置
    base_cfg = load_config(CONFIG_PATH)

    # 从配置中获取多因子列表与最大杠杆
    parsed_factors = get_factor_config(base_cfg)
    if not isinstance(parsed_factors, list) or len(parsed_factors) == 0:
        raise ValueError("配置中未找到多因子列表 (factors)，请确认 config/multi_factor.yaml 设置正确。")

    capital_cfg = base_cfg.get("capital", {}) or {}
    max_leverage = float(capital_cfg.get("max_leverage", 1.0))
    initial_capital = float(capital_cfg.get("initial", 100000))

    n_factors = len(parsed_factors)
    print(f"检测到 {n_factors} 个因子，最大杠杆: {max_leverage:.2f}x，初始资金: {initial_capital:,.0f}")

    # 2. 生成资金分配网格
    alloc_candidates = _gen_alloc_grid(n_factors, max_leverage)
    if not alloc_candidates:
        print("在当前 max_leverage 与步长设置下，没有可行的资金分配组合。请调整 ALLOC_STEP 或 max_leverage。")
        return

    print(f"即将评估 {len(alloc_candidates)} 组资金分配方案，每组包含 {n_factors} 个因子分配比例。")

    all_results: list[dict] = []

    # 3. 遍历每一种资金分配组合，调用 run_backtest
    for idx, allocs in enumerate(alloc_candidates, start=1):
        cfg = deepcopy(base_cfg)
        # 更新每个因子的 capital_alloc
        # 注意：run_backtest 内部会重新调用 get_factor_config(cfg)，
        # 因此必须修改 cfg 原始结构中的 "factors" 列表，而不是 get_factor_config 的返回拷贝。
        raw_factors = cfg.get("factors")
        if not raw_factors:
            # 兼容单因子写法：factor: {...}
            raw_factors = [cfg.get("factor", {})]
            cfg["factors"] = raw_factors
        for i, alloc in enumerate(allocs):
            if i < len(raw_factors):
                raw_factors[i]["capital_alloc"] = float(alloc)

        # 解析一次，方便后面记录类型等信息（此处只是读，不影响 run_backtest 内部逻辑）
        factor_list = get_factor_config(cfg)

        # 打印进度
        print("\n" + "=" * 80)
        print(f"[{idx}/{len(alloc_candidates)}] 测试资金分配: {allocs} (合计 {sum(allocs):.2f}x)")
        print("=" * 80)

        out = run_backtest(config=cfg)
        metrics = out["metrics"]
        trades = out.get("trades", [])
        target_val = _resolve_target_value(metrics, trades)

        row: dict = {
            "目标指标": TARGET_METRIC,
            TARGET_METRIC: target_val,
        }
        # 记录常用指标方便后续筛选
        row["策略年化回报"] = float(metrics.get("策略年化回报", 0.0))
        row["最大回撤"] = float(metrics.get("最大回撤", 0.0))
        row["夏普比率"] = float(metrics.get("夏普比率", 0.0))
        row["总资金杠杆和"] = float(sum(allocs))

        # 为每个因子记录其名称与分配（以当前解析结果为准）
        for i, (factor_cfg, alloc) in enumerate(zip(factor_list, allocs)):
            ftype = factor_cfg.get("type", f"factor_{i}")
            row[f"因子{i+1}_类型"] = ftype
            row[f"因子{i+1}_资金分配"] = float(alloc)

        all_results.append(row)

    if not all_results:
        print("没有得到任何回测结果，请检查配置或网格设置。")
        return

    # 4. 汇总结果并输出
    df_results = pd.DataFrame(all_results)

    # 按目标指标降序排序
    df_results_sorted = df_results.sort_values(by=TARGET_METRIC, ascending=False)

    paths = get_output_paths(base_cfg)
    out_dir = Path(paths["output_dir"])
    out_dir.mkdir(parents=True, exist_ok=True)

    # 保存所有结果与 TOP N 结果
    safe_name = TARGET_METRIC.replace("%", "pct").replace("/", "_").replace(" ", "")
    all_csv = out_dir / f"capital_alloc_search_all_{safe_name}.csv"
    df_results_sorted.to_csv(all_csv, index=False, encoding="utf-8-sig")

    print("\n" + "#" * 80)
    print(f"资金分配搜索完成，按 {TARGET_METRIC} 排序的全部方案已保存。")
    print("#" * 80)
    # 终端仅简单打印前若干行，防止刷屏
    preview_n = min(10, len(df_results_sorted))
    for _, r in df_results_sorted.head(preview_n).iterrows():
        desc = [f"{TARGET_METRIC}={r[TARGET_METRIC]:.4f}",
                f"年化={r['策略年化回报']:.4f}",
                f"夏普={r['夏普比率']:.4f}",
                f"最大回撤={r['最大回撤']:.4f}",
                f"总杠杆和={r['总资金杠杆和']:.2f}x"]
        i = 1
        while f"因子{i}_类型" in r:
            desc.append(f"{r[f'因子{i}_类型']} alloc={r[f'因子{i}_资金分配']:.2f}x")
            i += 1
        print(" | ".join(desc))

    print(f"\n全部结果已保存到: {all_csv}")


if __name__ == "__main__":
    main()


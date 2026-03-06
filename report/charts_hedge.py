# -*- coding: utf-8 -*-
"""
对冲策略图表模块
"""

import os
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt


def generate_charts_hedge(df, output_path, hedge_names, figsize=(14, 12)):
    """
    生成对冲策略的回测图表。

    参数
    ----
    df : pd.DataFrame
        需含 Strategy_Equity, TSLA_Market_Equity, 各对冲标的 Market_Equity,
        Combined_Strategy_Return, TSLA_Market_Return, 各标的 Position。
    output_path : str
        保存文件路径。
    hedge_names : list[str]
        对冲标的显示名称。
    figsize : tuple
        画布大小。
    """
    out_dir = os.path.dirname(output_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    plt.figure(figsize=figsize)

    # 1. 资金曲线 (Log 坐标)
    plt.subplot(3, 1, 1)
    plt.plot(df.index, df["Strategy_Equity"], label="对冲策略 (组合)", linewidth=2, color="green")
    plt.plot(df.index, df["TSLA_Market_Equity"], label="TSLA 持有", alpha=0.5, color="blue")
    
    colors = ["orange", "red", "purple", "brown"]
    for i, name in enumerate(hedge_names):
        col_name = f"Hedge_{i}_Market_Equity"
        if col_name in df.columns:
            plt.plot(df.index, df[col_name], label=f"{name} 持有", alpha=0.5, color=colors[i % len(colors)])

    plt.yscale("log")
    plt.title("资金曲线对比 (对数坐标)")
    plt.legend()
    plt.grid(True, which="both", ls="-", alpha=0.3)

    # 2. 持仓分布图
    plt.subplot(3, 1, 2)
    tsla_mask = df["TSLA_Position"] > 0
    plt.fill_between(df.index, 0, 1, where=tsla_mask, alpha=0.3, color="blue", label="持有 TSLA")
    
    # 堆叠显示对冲标的持仓
    current_bottom = 0
    for i, name in enumerate(hedge_names):
        pos_col = f"Hedge_{i}_Position"
        if pos_col in df.columns:
            # 只有当 TSLA Position 为 0 时才有 hedge position
            h_mask = (df["TSLA_Position"] == 0) & (df[pos_col] > 0)
            weight = df[pos_col].max() # 假设权重固定
            plt.fill_between(df.index, current_bottom, current_bottom + weight, where=h_mask, 
                             alpha=0.5, color=colors[i % len(colors)], label=f"持有 {name}")
            current_bottom += weight

    plt.ylim(-0.1, 1.1)
    plt.title("持仓分布 (Position Distribution)")
    plt.ylabel("持仓权重")
    plt.legend()
    plt.grid(True, alpha=0.3)

    # 3. 年度收益率对比
    plt.subplot(3, 1, 3)
    try:
        # Combined_Strategy_Return, TSLA_Market_Return
        annual = df[["Combined_Strategy_Return", "TSLA_Market_Return"]].resample("YE").apply(lambda x: (1 + x).prod() - 1)
    except ValueError:
        annual = df[["Combined_Strategy_Return", "TSLA_Market_Return"]].resample("Y").apply(lambda x: (1 + x).prod() - 1)
    
    years = annual.index.year
    x = np.arange(len(years))
    width = 0.35
    
    bars1 = plt.bar(x - width/2, annual["Combined_Strategy_Return"], width, label="对冲策略")
    bars2 = plt.bar(x + width/2, annual["TSLA_Market_Return"], width, label="TSLA", alpha=0.7)
    
    for rect in bars1 + bars2:
        h = rect.get_height()
        plt.annotate(f"{h:.1%}", xy=(rect.get_x() + rect.get_width() / 2, h),
                     xytext=(0, 3 if h > 0 else -12), textcoords="offset points", 
                     ha="center", va="bottom", fontsize=8)

    plt.xticks(x, years, rotation=45)
    plt.title("每年收益率对比 (%)")
    plt.legend()
    plt.grid(True, axis="y", alpha=0.3)

    plt.tight_layout()
    plt.savefig(output_path, dpi=150)
    plt.close()
    print(f"对冲回测图表已保存: {output_path}")

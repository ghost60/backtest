# -*- coding: utf-8 -*-
"""
图表生成模块

职责：
- 设置 matplotlib 中文字体，避免乱码
- 生成两张图：资金曲线（对数坐标）、按年收益率对比柱状图
"""

import os
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt


def apply_style(font_sans_serif="Arial Unicode MS"):
    """设置全局绘图风格：中文字体、负号正常显示。Mac 用 Arial Unicode MS，Windows 可用 SimHei。"""
    plt.rcParams["font.sans-serif"] = [font_sans_serif]
    plt.rcParams["axes.unicode_minus"] = False


def generate_charts(df, output_path, figsize=(12, 10), strategy_label="策略", benchmark_label="TSLA 持有"):
    """
    生成回测结果图并保存。

    图1：策略净值 vs 基准净值（对数坐标）
    图2：按年统计的策略收益 vs 基准收益（柱状图）

    参数
    ----
    df : pd.DataFrame
        需含 Strategy_Equity, Market_Equity, Strategy_Return, Market_Return，索引为日期。
    output_path : str
        保存路径（含文件名）。
    figsize : tuple
        图像宽高。
    strategy_label, benchmark_label : str
        图例中的策略名、基准名。
    """
    out_dir = os.path.dirname(output_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    plt.figure(figsize=figsize)

    # 子图1：资金曲线（对数）
    plt.subplot(2, 1, 1)
    plt.plot(df.index, df["Strategy_Equity"], label=strategy_label)
    plt.plot(df.index, df["Market_Equity"], label=benchmark_label, alpha=0.7)
    plt.yscale("log")
    plt.title("资金曲线 (对数坐标) / Equity Curve (Log Scale)")
    plt.legend()
    plt.grid(True, which="both", ls="-")

    # 子图2：年度收益对比（每年收益 = (1+r1)(1+r2)...-1）
    plt.subplot(2, 1, 2)
    try:
        annual = df[["Strategy_Return", "Market_Return"]].resample("YE").apply(lambda x: (1 + x).prod() - 1)
    except ValueError:
        annual = df[["Strategy_Return", "Market_Return"]].resample("Y").apply(lambda x: (1 + x).prod() - 1)
    years = annual.index.year
    x = np.arange(len(years))
    w = 0.35
    bars1 = plt.bar(x - w / 2, annual["Strategy_Return"], w, label=strategy_label)
    bars2 = plt.bar(x + w / 2, annual["Market_Return"], w, label=benchmark_label)
    for rect in bars1 + bars2:
        h = rect.get_height()
        plt.annotate(f"{h:.1%}", xy=(rect.get_x() + rect.get_width() / 2, h),
                     xytext=(0, 3 if h > 0 else -12), textcoords="offset points", ha="center", va="bottom", fontsize=8)
    plt.xticks(x, years, rotation=45)
    plt.title("每年收益率对比 (%)")
    plt.legend()
    plt.grid(True, axis="y")

    plt.tight_layout()
    plt.savefig(output_path)
    plt.close()
    print(f"图表已保存: {output_path}")

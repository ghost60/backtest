# -*- coding: utf-8 -*-
"""
可视化增强模块

职责：
- 封装 quantstats 库，生成详细的性能分析报告（HTML 格式）
"""

import os
import quantstats as qs

# 解决 quantstats 在某些环境下绘图字体丢失的问题
try:
    import matplotlib.pyplot as plt
    plt.rcParams['font.sans-serif'] = ['Arial Unicode MS', 'SimHei', 'sans-serif']
    plt.rcParams['axes.unicode_minus'] = False
except:
    pass


def generate_qs_report(returns, benchmark=None, output_path="qs_report.html", title="回测报告"):
    """
    使用 quantstats 生成 HTML 性能报告。

    参数
    ----
    returns : pd.Series
        策略的日收益率序列（DatetimeIndex）。
    benchmark : pd.Series, optional
        基准标的的日收益率序列（DatetimeIndex）。
    output_path : str
        报告保存路径。
    title : str
        报告标题。
    """
    # 确保输出目录存在
    out_dir = os.path.dirname(output_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    # 预处理数据：去除 NaN 并确保类型正确，同时统一时区（QuantStats 对时区敏感）
    returns = returns.fillna(0)
    if returns.index.tz is not None:
        returns.index = returns.index.tz_localize(None)

    if benchmark is not None:
        benchmark = benchmark.fillna(0)
        if benchmark.index.tz is not None:
            benchmark.index = benchmark.index.tz_localize(None)

    # 生成 HTML 报告
    try:
        qs.reports.html(returns, benchmark=benchmark, output=output_path, title=title)
        print(f"QuantStats HTML 报告已生成: {output_path}")

        # 若传入的是字符串路径，转换为 Path 以便后续操作
        # from pathlib import Path

        # out_path = Path(output_path)
        # if out_path.is_file():
        #     try:
        #         import webbrowser

        #         webbrowser.open(out_path.as_uri())
        #     except Exception:
        #         pass
    except Exception as e:
        print(f"警告: 生成 QuantStats 报告失败: {e}")


def extend_stats(returns):
    """
    使用 quantstats 计算一些高级指标。
    """
    stats = {
        "Skewness (偏度)": round(qs.stats.skew(returns), 2),
        "Kurtosis (峰度)": round(qs.stats.kurtosis(returns), 2),
        "Calmar Ratio": round(qs.stats.calmar(returns), 2),
        "VaR (95%)": round(qs.stats.var(returns) * 100, 2),
    }
    return stats

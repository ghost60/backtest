#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
交互式策略查看器（HTML 版）

功能：
- 读取指定配置文件，运行回测（目前仅支持单标的回测）
- 生成一个独立的 HTML 文件：
  - 上半部分：价格 + MA + 买卖信号 + 权益曲线 + 回撤（Plotly 可缩放/拖动）
  - 下半部分：在当前时间窗口内动态刷新的成交清单与区间统计（胜率、盈亏等）

用法示例（在项目根的上一层目录运行）：
    python -m backtest.strategy_viewer_html -c backtest/config/default.yaml

也可以在 backtest 目录内直接运行脚本：
    python strategy_viewer_html.py -c config/default.yaml
"""

import argparse
import json
import sys
import webbrowser
from copy import deepcopy
from pathlib import Path

import pandas as pd

# 参考 main.py，将项目根加入 sys.path，保证脚本/包两种运行方式都能导入 backtest
_PKG_DIR = Path(__file__).resolve().parent  # backtest/
if str(_PKG_DIR.parent) not in sys.path:
    sys.path.insert(0, str(_PKG_DIR.parent))

from backtest.backtest import run_backtest  # type: ignore
from backtest.config_loader import (  # type: ignore
    get_capital_params,
    get_output_paths,
    get_strategy_params,
    get_hedge_config,
    load_config,
)

try:
    import plotly.graph_objs as go
    from plotly.subplots import make_subplots
except ImportError:  # pragma: no cover
    go = None
    make_subplots = None


def generate_html_viewer(df_clean: pd.DataFrame, trades, output_path: Path):
    """生成带时间缩放+联动统计的 HTML 策略查看器。"""
    if go is None or make_subplots is None:
        print("警告: 未安装 plotly，无法生成 HTML 策略查看器。请先执行: pip install plotly")
        return

    if df_clean is None or df_clean.empty:
        print("警告: df_clean 为空，无法生成 HTML 策略查看器。")
        return

    # 价格 & MA
    df_plot = df_clean.copy()
    df_plot = df_plot.reset_index().rename(columns={"index": "Date"})
    df_plot["Date"] = pd.to_datetime(df_plot["Date"])

    price_trace = go.Scatter(
        x=df_plot["Date"],
        y=df_plot["Close"],
        mode="lines",
        name="Close",
        line=dict(color="black"),
    )

    ma_traces = []
    for col, color in [("MA5", "blue"), ("MA30", "orange")]:
        if col in df_plot.columns:
            ma_traces.append(
                go.Scatter(
                    x=df_plot["Date"],
                    y=df_plot[col],
                    mode="lines",
                    name=col,
                    line=dict(color=color, width=1),
                )
            )

    # 信号点
    buy_x, buy_y, sell_x, sell_y = [], [], [], []
    for t in trades or []:
        d = pd.to_datetime(t.get("date"))
        if d in df_clean.index:
            if t.get("action") in ("买入", "Buy", "LONG", "Long"):
                buy_x.append(d)
                buy_y.append(t.get("price"))
            elif t.get("action") in ("卖出", "Sell", "SHORT", "Short"):
                sell_x.append(d)
                sell_y.append(t.get("price"))

    buy_trace = go.Scatter(
        x=buy_x,
        y=buy_y,
        mode="markers",
        name="买入",
        marker=dict(symbol="triangle-up", color="green", size=9),
    )
    sell_trace = go.Scatter(
        x=sell_x,
        y=sell_y,
        mode="markers",
        name="卖出",
        marker=dict(symbol="triangle-down", color="red", size=9),
    )

    # 权益 & 回撤
    eq = df_clean["Strategy_Equity"]
    rolling_max = eq.cummax()
    dd = (eq - rolling_max) / rolling_max

    equity_trace = go.Scatter(
        x=df_clean.index,
        y=eq,
        mode="lines",
        name="策略净值",
        line=dict(color="blue"),
        yaxis="y2",
    )
    dd_trace = go.Scatter(
        x=df_clean.index,
        y=dd,
        mode="lines",
        name="回撤",
        line=dict(color="red"),
        yaxis="y3",
        fill="tozeroy",
        fillcolor="rgba(255,0,0,0.2)",
    )

    fig = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.08,
        row_heights=[0.6, 0.4],
    )

    # 价格+信号+指标
    fig.add_trace(price_trace, row=1, col=1)
    for t_ma in ma_traces:
        fig.add_trace(t_ma, row=1, col=1)
    fig.add_trace(buy_trace, row=1, col=1)
    fig.add_trace(sell_trace, row=1, col=1)

    # 权益 + 回撤
    fig.add_trace(equity_trace, row=2, col=1)
    fig.add_trace(dd_trace, row=2, col=1)

    fig.update_layout(
        title="策略查看器 (可缩放时间并联动区间统计)",
        xaxis=dict(title="日期"),
        yaxis=dict(title="价格"),
        yaxis2=dict(title="净值", overlaying="y", side="left"),
        yaxis3=dict(
            title="回撤",
            overlaying="y",
            side="right",
            range=[-1, 0],
            showgrid=False,
        ),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )

    # 准备 JS 用的成交数据
    trades_js = []
    for t in trades or []:
        d = pd.to_datetime(t.get("date"))
        trades_js.append(
            {
                "date": d.isoformat(),
                "action": t.get("action"),
                "price": t.get("price"),
                "shares": t.get("shares"),
                "pnl": t.get("pnl"),
                "cum_pnl": t.get("cum_pnl"),
            }
        )

    fig_json = fig.to_json()

    html_tpl = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <title>TSLA 策略查看器</title>
  <script src="https://cdn.plot.ly/plotly-2.30.0.min.js"></script>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 0; padding: 0; }}
    #container {{ display: flex; flex-direction: column; height: 100vh; }}
    #chart {{ flex: 3 1 auto; }}
    #panel {{ flex: 2 1 auto; display: flex; border-top: 1px solid #ddd; }}
    #stats {{ width: 30%; padding: 8px 12px; border-right: 1px solid #eee; box-sizing: border-box; }}
    #trades {{ flex: 1 1 auto; padding: 8px 12px; overflow-y: auto; box-sizing: border-box; }}
    table {{ border-collapse: collapse; width: 100%; font-size: 12px; }}
    th, td {{ border: 1px solid #ddd; padding: 4px 6px; text-align: right; }}
    th {{ background: #f5f5f5; position: sticky; top: 0; z-index: 1; }}
  </style>
</head>
<body>
  <div id="container">
    <div id="chart"></div>
    <div id="panel">
      <div id="stats">
        <h3>区间绩效</h3>
        <div id="stats-content"></div>
      </div>
      <div id="trades">
        <h3>区间成交明细</h3>
        <div id="trades-table"></div>
      </div>
    </div>
  </div>
  <script>
    const FIG_DATA = {fig_json};
    const TRADES = {json.dumps(trades_js, ensure_ascii=False)};

    function formatNumber(x, digits=2) {{
      if (x === null || x === undefined || isNaN(x)) return "N/A";
      return x.toFixed(digits);
    }}

    function renderStats(xmin, xmax) {{
      let total = 0, win = 0, loss = 0, pnlSum = 0;
      const rows = [];
      for (const t of TRADES) {{
        const d = new Date(t.date);
        if (xmin && d < xmin) continue;
        if (xmax && d > xmax) continue;
        if (t.pnl !== null && t.pnl !== undefined) {{
          total += 1;
          pnlSum += t.pnl;
          if (t.pnl > 0) win += 1;
          else if (t.pnl < 0) loss += 1;
        }}
        rows.push(t);
      }}
      const winRate = total ? win / total * 100 : 0;
      const avgPnl = total ? pnlSum / total : 0;

      const statsDiv = document.getElementById("stats-content");
      statsDiv.innerHTML = `
        <p>成交笔数: <b>${{total}}</b></p>
        <p>盈利笔数: <b>${{win}}</b></p>
        <p>亏损笔数: <b>${{loss}}</b></p>
        <p>胜率: <b>${{formatNumber(winRate)}}%</b></p>
        <p>总盈亏: <b>${{formatNumber(pnlSum, 2)}}</b></p>
        <p>单笔平均盈亏: <b>${{formatNumber(avgPnl, 2)}}</b></p>
      `;

      // 交易表（最多展示 200 条）
      const maxRows = 200;
      let html = "<table><thead><tr><th>日期</th><th>方向</th><th>价格</th><th>数量</th><th>单笔盈亏</th><th>累计盈亏</th></tr></thead><tbody>";
      let count = 0;
      for (const t of rows) {{
        if (count >= maxRows) break;
        html += `
          <tr>
            <td style="text-align:left;">${{t.date.substring(0, 10)}}</td>
            <td>${{t.action || ""}}</td>
            <td>${{formatNumber(t.price, 2)}}</td>
            <td>${{t.shares !== null && t.shares !== undefined ? t.shares : ""}}</td>
            <td>${{t.pnl !== null && t.pnl !== undefined ? formatNumber(t.pnl, 2) : ""}}</td>
            <td>${{t.cum_pnl !== null && t.cum_pnl !== undefined ? formatNumber(t.cum_pnl, 2) : ""}}</td>
          </tr>`;
        count += 1;
      }}
      html += "</tbody></table>";
      document.getElementById("trades-table").innerHTML = html;
    }}

    document.addEventListener("DOMContentLoaded", function() {{
      const chartDiv = document.getElementById("chart");
      Plotly.newPlot(chartDiv, FIG_DATA.data, FIG_DATA.layout);

      // 初次渲染使用全局区间
      renderStats(null, null);

      chartDiv.on("plotly_relayout", function(e) {{
        const layout = chartDiv.layout || FIG_DATA.layout;
        let xmin = null, xmax = null;
        if (layout && layout.xaxis && layout.xaxis.range) {{
          xmin = new Date(layout.xaxis.range[0]);
          xmax = new Date(layout.xaxis.range[1]);
        }}
        renderStats(xmin, xmax);
      }});
    }});
  </script>
</body>
</html>
"""
    output_path.write_text(html_tpl, encoding="utf-8")
    print(f"HTML 策略查看器已生成: {output_path}")
    try:
        webbrowser.open(output_path.as_uri())
    except Exception:
        pass


def main():
    parser = argparse.ArgumentParser(description="TSLA 交互式策略查看器（HTML 版）")
    parser.add_argument(
        "-c",
        "--config",
        default="config/default.yaml",
        help="配置文件路径（YAML），默认 config/default.yaml",
    )

    args = parser.parse_args()

    cfg = load_config(args.config)
    cfg = deepcopy(cfg)

    hedge_cfg = get_hedge_config(cfg)
    if hedge_cfg.get("enabled"):
        print("当前配置为对冲回测（hedge.enabled=true），HTML 策略查看器暂仅支持单标的回测。")
        return

    print("=" * 80)
    print(f"使用配置文件: {args.config}")
    print("运行单标的回测以生成 HTML 策略查看器...")
    print("=" * 80)

    result = run_backtest(config=cfg)
    df_clean = result.get("df_clean")
    trades = result.get("trades", [])

    paths = get_output_paths(cfg)
    out_dir = Path(paths["output_dir"])
    out_dir.mkdir(parents=True, exist_ok=True)
    html_path = out_dir / "strategy_viewer.html"

    generate_html_viewer(df_clean, trades, html_path)


if __name__ == "__main__":
    main()


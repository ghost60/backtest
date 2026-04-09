环境安装：安装conda，创建新环境，运行pip install -r requirements.txt

# 量化回测项目（backtest 包）


MA 金叉死叉策略回测，模块化、可配置、便于扩展。

## 项目结构

```
backtest/
├── config/
│   └── default.yaml      # 默认配置（数据路径、回测区间、策略参数、输出目录）
├── config_loader.py      # 配置加载与路径解析
├── data_loader.py        # 数据加载与日期过滤
├── factor_double_ma.py        # MA 金叉死叉策略
├── metrics.py            # 净值曲线与绩效指标
├── charts.py             # 资金曲线与年度收益图
├── report.py             # 终端报告与 Markdown 输出
├── backtest.py           # 回测流程编排
├── main.py               # 包入口（python -m backtest.main）
├── run_hedge_azo.py      # TSLA+AZO 对冲一键脚本
├── run_hedge_triple.py   # TSLA+AZO+ORLY 对冲一键脚本
├── strategy_viewer.py    # 终端版策略查看器
├── strategy_viewer_html.py  # HTML 版策略查看器
├── ma_param_search.py    # MA 参数搜索脚本
└── README.md
```

## 快速开始

1. 安装依赖（在项目根或 backtest 目录下）:
   ```bash
   pip install -r backtest/requirements.txt
   ```

2. 修改配置（可选）:
   - 编辑 `backtest/config/default.yaml` 中的 `data.path`、`data.start_date`/`end_date`、`strategy.*`、`output.dir` 等。

3. 运行回测:
- 在项目根目录（backtest 的上一层目录）下:
     ```bash
     python -m backtest.main -c backtest/config/default.yaml
     ```

结果会输出到配置中的 `output.dir`（默认 `tsla_result/`），包括:
- 策略表现报告 Markdown
- 资金曲线与年度收益对比图

## 配置说明 (config/default.yaml)

| 配置项 | 说明 |
|--------|------|
| `data.path` | 主标的 CSV 路径（相对项目根或绝对路径） |
| `data.fallback_path` | 备用数据路径 |
| `data.start_date` / `end_date` | 回测起止日期 |
| `strategy.ma_short` / `ma_long` | 短/长均线周期 |
| `strategy.use_price_filter` | 是否启用 Close > MA_short 过滤 |
| `strategy.entry_delay` | 入场延迟 K 线数 |
| `output.dir` | 结果输出目录 |
| `output.chart_filename` / `metrics_filename` | 图表与报告文件名 |
| `capital.margin_currency` | 保证金币种：`USD / BTC / ETH` |
| `capital.margin_settlement_mode` | 保证金结算口径：`principal_plus_pnl`（默认）/ `mark_to_market`。仅 `USD` 保证金生效；非 `USD` 时固定按“持币作抵押、仅把盈亏折回币”结算 |
| `capital.margin_fx_source` | 汇率来源：`static / binance` |
| `capital.margin_symbol` / `margin_fx_interval` | 当 `binance` 时的交易对与K线周期（如 `BTCUSDT`, `1d`） |
| `capital.margin_fx_debug` / `margin_fx_prefetch` | 是否打印请求日志、是否启动预拉取 |
| `capital.margin_fx_to_usd` | 固定汇率或 Binance 失败时的兜底汇率 |

> 说明：`margin_fx_source=binance` 通过 `ccxt` 获取历史/最新价格，请先安装依赖。

## BTCDOM 复刻

- 如果你要复刻“50% 做多 BTC + 50% 做空山寨币篮子”的 BTCDOM 风格组合，使用 [config/btcdom_replica.yaml]
- 其中 `data.path` 是 BTC 数据，`hedge.symbols` 是做空篮子，`btcdom.long_weight` / `btcdom.short_weight` 控制多空权重。
- 当前实现是固定权重、按日再平衡的组合复刻，不包含额外择时信号。

## 最简统一账户

- `double_ma` 的最简统一账户示例配置见 [config/double_ma_unified_account.yaml](/Users/lsq-mac/code/backtest/config/double_ma_unified_account.yaml)。
- 该模式下，BTC 只作为抵押物，不因买入标的而减少；买入标的是借 USD 建仓，平仓时先还债。
- 若启用 `capital.margin_timing_enabled`，BTC/USD 抵押资产切换仅在空仓时发生；该配置仅用于统一账户引擎。

## 扩展建议

- **多标的 / 对冲**: 在 `config` 中增加 `symbols`、`hedge` 等，在 `backtest.py` 中根据配置分支调用不同策略（如现有 `5_30_backtest_tsla_azo.py` 中的对冲逻辑可抽成 `strategy_hedge.py`）。
- **新策略**: 新增 `strategy_xxx.py`，实现统一接口（如接收 `df` 与参数字典，返回带 `Position`、`Strategy_Return` 的 DataFrame），在 `backtest.py` 中按 `strategy.name` 选择执行。
- **更多指标**: 在 `metrics.py` 中增加最大回撤修复时间、交易清单等，在 `report.py` 中输出到 Markdown 或 CSV。

## 与旧脚本对应关系

- `5_30_backtest_tsla.py` 的单标的逻辑已拆分为上述模块，默认配置与之对齐；如需完全复现可继续使用该脚本。
- 对冲版本（如 `5_30_backtest_tsla_azo.py`）可后续按“扩展建议”接入配置与 backtest 流程。

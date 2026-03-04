# TSLA 量化回测项目

MA 金叉死叉策略回测，模块化、可配置、便于扩展。

## 项目结构

```
tsla/
├── config/
│   └── default.yaml      # 默认配置（数据路径、回测区间、策略参数、输出目录）
├── config_loader.py      # 配置加载与路径解析
├── data_loader.py        # 数据加载与日期过滤
├── strategy_ma.py        # MA 金叉死叉策略
├── metrics.py            # 净值曲线与绩效指标
├── charts.py             # 资金曲线与年度收益图
├── report.py             # 终端报告与 Markdown 输出
├── backtest.py           # 回测流程编排
├── run.py                # 推荐入口（可指定配置文件）
├── main.py               # 包入口（python -m tsla.main）
├── requirements.txt
└── README.md
```

## 快速开始

1. 安装依赖（在项目根或 tsla 目录下）:
   ```bash
   pip install -r tsla/requirements.txt
   ```

2. 修改配置（可选）:
   - 编辑 `tsla/config/default.yaml` 中的 `data.path`、`data.start_date`/`end_date`、`strategy.*`、`output.dir` 等。

3. 运行回测:
   - 在项目根目录 `xbx_code` 下:
     ```bash
     python tsla/run.py
     python tsla/run.py -c tsla/config/default.yaml
     ```
   - 或以包方式运行:
     ```bash
     python -m tsla.main -c tsla/config/default.yaml
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

## 扩展建议

- **多标的 / 对冲**: 在 `config` 中增加 `symbols`、`hedge` 等，在 `backtest.py` 中根据配置分支调用不同策略（如现有 `5_30_backtest_tsla_azo.py` 中的对冲逻辑可抽成 `strategy_hedge.py`）。
- **新策略**: 新增 `strategy_xxx.py`，实现统一接口（如接收 `df` 与参数字典，返回带 `Position`、`Strategy_Return` 的 DataFrame），在 `backtest.py` 中按 `strategy.name` 选择执行。
- **更多指标**: 在 `metrics.py` 中增加最大回撤修复时间、交易清单等，在 `report.py` 中输出到 Markdown 或 CSV。

## 与旧脚本对应关系

- `5_30_backtest_tsla.py` 的单标的逻辑已拆分为上述模块，默认配置与之对齐；如需完全复现可继续使用该脚本。
- 对冲版本（如 `5_30_backtest_tsla_azo.py`）可后续按“扩展建议”接入配置与 backtest 流程。

# ADX Moving AVG 策略说明

本文档对应 TradingView 脚本：`tv/ADX_Moving_AVG_Strategy.pine`，并说明与本仓库回测实现（`factor/factor_adx_ma.py` + `config/adx_ma.yaml`）的对应关系。

---

## 一、策略概述

**ADX Moving AVG Strategy** 是一个**趋势跟踪策略**：用 **ADX** 判断趋势强度，用**长周期均线**过滤方向，只在「趋势走强且价格在均线之上」时做多，在「趋势转弱或价格跌破均线」时平仓。

- **标的**：在图表主标的（如 TSLA）上交易。
- **方向**：仅做多（long），无做空。
- **仓位**：默认 95% 权益（`default_qty_type = strategy.percent_of_equity`）。

---

## 二、用到的指标

### 1. ADX（Average Directional Index）

- **含义**：衡量趋势强度，不区分方向；数值越大趋势越强。
- **计算**：
  - 先算 **+DM / -DM**（当日上涨/下跌幅度，只保留较大一方）。
  - 用 **RMA(TR)** 做真实波幅，再算 **+DI、-DI**（`dirmov` 中的 `plus`、`minus`）。
  - **DX** = 100 × |+DI − -DI| / (+DI + -DI)，再对 DX 做 **RMA(adxlen)** 得到 **ADX**。
- **参数**：
  - `dilen` = 14：计算 +DI、-DI 时的平滑周期。
  - `adxlen` = 14：ADX 的平滑周期。
- **用途**：  
  - **入场**：ADX **上穿** 阈值（默认 26）→ 认为趋势由弱转强。  
  - **出场**：ADX **下穿** 阈值 → 认为趋势转弱。

### 2. 长均线（Moving AVG Day）

- **周期**：`moving_avg_day` = 110（日线下的 110 日均线）。
- **两种用法**：
  - **本标的**：`sma_close_225 = ta.sma(close, moving_avg_day)`，变量名是 225，实际周期为 110。
  - **其他资产**：`selected_close = request.security(symbol_choice, '1D', close)`，`selected_ma = ta.sma(selected_close, moving_avg_day)`，即用 SPX/^GSPC 等另一标的的 110 日均线做过滤。
- **用途**：  
  - 入场：价格（本标的或所选标的）**大于** 对应 110 日均线。  
  - 出场：价格**小于**对应 110 日均线。

### 3. SMA 14 过滤（可选）

- **计算**：`sma_close_14 = ta.sma(close, 14)`，始终用**本标的**的 14 日收盘均线。
- **条件**：`sma_close_14 > sma_close_14[14]`，即「当前 14 日均线」大于「14 根 K 线前的 14 日均线」，表示短期均线在抬升。
- **用途**：仅影响**入场**；开启后多一层过滤，避免在短期走弱时开多。

---

## 三、参数一览

| 参数名 | 默认值 | 含义 |
|--------|--------|------|
| 开始/结束年月日 | 2020-01-01 ~ 2026-01-01 | 只在时间窗内允许开平仓 |
| **use_other_asset** | false | 是否用「其他资产」做长均线过滤 |
| **symbol_choice** | SPX | 其他资产代码（如 SPX、^GSPC） |
| **adx_threshold** | 26 | ADX 上穿做多、下穿平仓的阈值 |
| **moving_avg_day** | 110 | 长均线周期（日） |
| **adxlen** | 14 | ADX 平滑周期 |
| **dilen** | 14 | +DI、-DI 的平滑周期 |
| **if_sma14_filtered** | true | 是否启用 SMA14 过滤 |

---

## 四、入场逻辑（做多）

满足**全部**下列条件时开多：

1. **ADX 上穿阈值**：`ta.crossover(adx_value, adx_threshold)`  
   → 当前 ADX > 26 且前一根 ADX ≤ 26。

2. **长均线过滤**（二选一）：  
   - **use_other_asset = false**：本标的收盘价 > 本标的 110 日均线，即 `close > sma_close_225`。  
   - **use_other_asset = true**：所选标的收盘价 > 所选标的 110 日均线，即 `selected_close > selected_ma`。

3. **SMA14 过滤**（可选）：  
   - **if_sma14_filtered = true**：`sma_close_14 > sma_close_14[14]`（本标的 14 日均线在抬升）。  
   - **if_sma14_filtered = false**：不做此条件。

4. **在交易时间窗内**：`inTradeWindow == true`。

用表格概括：

| if_sma14_filtered | use_other_asset | 入场条件 |
|-------------------|-----------------|----------|
| false | false | ADX 上穿 26 **且** close > 本标的 110 日均线 |
| false | true  | ADX 上穿 26 **且** selected_close > selected_ma |
| true  | false | ADX 上穿 26 **且** close > 本标的 110 日均线 **且** sma14 > sma14[14] |
| true  | true  | ADX 上穿 26 **且** selected_close > selected_ma **且** sma14 > sma14[14] |

---

## 五、出场逻辑（平多）

满足**任意一条**即平仓：

1. **ADX 下穿阈值**：`ta.crossunder(adx_value, adx_threshold)`  
   → 当前 ADX < 26 且前一根 ADX ≥ 26。

2. **长均线过滤**：  
   - **use_other_asset = false**：本标的收盘价 < 本标的 110 日均线，即 `close < sma_close_225`。  
   - **use_other_asset = true**：所选标的收盘价 < 所选标的 110 日均线，即 `selected_close < selected_ma`。

3. **在交易时间窗内**：`inTradeWindow == true`。

平仓使用 `strategy.close("ADX", immediately = true)`，即信号出现后立即平仓。

---

## 六、策略流程简图

```
每根 K 线：
├─ 若 当前无多仓
│   └─ 若 ADX 上穿阈值 且 价格 > 长均线 且 [可选] SMA14 抬升 且 在时间窗内
│       → 开多（95% 权益）
│
└─ 若 当前有多仓
    └─ 若 ADX 下穿阈值 或 价格 < 长均线 且 在时间窗内
        → 立即平多
```

---

## 七、与本仓库回测的对应关系

| Pine 概念 | 本仓库 |
|-----------|--------|
| 主标的 | `data.path`（如 TSLA CSV） |
| use_other_asset + symbol_choice | `factor.params.use_other_asset` + `other_asset_path`（如 ^GSPC CSV） |
| adx_threshold | `factor.params.adx_threshold`（默认 26） |
| moving_avg_day | `factor.params.moving_avg_day`（默认 110） |
| adxlen / dilen | `factor.params.adx_period`（默认 14） |
| if_sma14_filtered | `factor.params.use_sma14_filter`（默认 true） |
| 入场/出场时机 | `strategy.entry_delay` / `strategy.exit_delay`（-1 = 信号当根成交，0 = 下一根成交） |

运行本仓库等价回测：

```bash
python -m backtest -c config/adx_ma.yaml
```

配置中可设置 `use_other_asset: true` 与 `other_asset_path: "data/^GSPC_25Y_yFinance.csv"`，以用 ^GSPC 做长均线过滤，与 Pine 中 `symbol_choice = "SPX"` 或 ^GSPC 的用法一致。

---

## 八、策略特点小结

- **趋势+均线双重过滤**：既要求 ADX 上穿（趋势增强），又要求价格在长均线之上，减少震荡市假突破。
- **可选用指数过滤**：用 SPX/^GSPC 的 110 日均线可间接表达「大盘趋势」，再决定是否做多个股。
- **SMA14 过滤**：可选地要求短期均线抬升，进一步过滤弱势反弹。
- **仅做多、无杠杆**：适合股票/ETF 等标的的日线趋势跟踪。

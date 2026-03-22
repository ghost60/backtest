# -*- coding: utf-8 -*-
"""
配置加载模块

职责：
- 从 YAML 读取配置（数据路径、回测区间、策略参数、输出目录等）
- 将相对路径解析为绝对路径（数据文件、输出目录）
- 提供 get_strategy_params / get_output_paths 供其他模块使用
"""

import os
from pathlib import Path

try:
    import yaml
except ImportError:
    yaml = None

# ---------- 路径常量 ----------
# 当前包所在目录，即 backtest/
PACKAGE_DIR = Path(__file__).resolve().parent
# 项目根目录，即 backtest/，用于解析「相对项目根」的路径
PROJECT_ROOT = PACKAGE_DIR


def _resolve_path(path_str, base_dir=None):
    """
    将配置中的路径字符串转为绝对路径。
    - 若 path_str 已是绝对路径，直接返回
    - 否则视为相对路径，相对于 base_dir（默认 PROJECT_ROOT）
    """
    if not path_str:
        return None
    p = Path(path_str)
    if p.is_absolute():
        return str(p)
    base = Path(base_dir) if base_dir else PROJECT_ROOT
    return str((base / p).resolve())


def _resolve_data_path(cfg):
    """解析数据文件路径"""
    path = (cfg.get("data") or {}).get("path") or ""
    return _resolve_path(path, PROJECT_ROOT)


def _resolve_output_dir(cfg):
    """解析输出目录：output.dir，相对路径时相对于项目根。"""
    out_dir = (cfg.get("output") or {}).get("dir") or "tsla_result"
    return _resolve_path(out_dir, PROJECT_ROOT)


def load_config(config_path=None):
    """
    加载配置入口。
    - config_path 若提供且文件存在，则用该文件；否则用 config/double_ma.yaml
    - 返回的 cfg 会多出 _resolved 字段：data_path, output_dir, package_dir, project_root
    """
    if yaml is None:
        raise ImportError("请安装 PyYAML: pip install pyyaml")

    if config_path and os.path.isfile(config_path):
        path = Path(config_path)
    else:
        path = PACKAGE_DIR / "config" / "double_ma.yaml"

    with open(path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}

    # 注入解析后的路径及配置文件名（用于所有输出文件名）
    cfg["_resolved"] = {
        "data_path": _resolve_data_path(cfg),
        "output_dir": _resolve_output_dir(cfg),
        "package_dir": str(PACKAGE_DIR),
        "project_root": str(PROJECT_ROOT),
        "config_name": path.stem,
    }
    return cfg


def get_strategy_params(cfg):
    """从配置中取出策略参数字典（仅执行相关：入场/出场延迟等，与因子无关）"""
    s = cfg.get("strategy", {})
    return {
        "name": s.get("name", "ma_cross"),
        "entry_delay": s.get("entry_delay", 0),
        "exit_delay": s.get("exit_delay", 0),
    }


def get_factor_config(cfg):
    """
    从配置中取出因子类型与参数。因子必须在 factor 段中配置

    配置示例：
        factor:
          type: double_ma   # 或 single_ma
          params:
            ma_short: 5
            ma_long: 30
            use_price_filter: true

    返回
    ----
    dict
        {"type": "double_ma" | "single_ma", "params": {...}}
    """
    # 向后兼容：可能是字典 (单因子 "factor:") 或列表 (多因子 "factors:")
    factor_cfg_list = cfg.get("factors")
    if not factor_cfg_list:
        single_factor = cfg.get("factor")
        if single_factor and isinstance(single_factor, dict):
            factor_cfg_list = [single_factor]
        else:
            raise ValueError("配置中必须包含 factor 段(字典)或 factors 段(列表)")

    parsed_factors = []
    for factor_cfg in factor_cfg_list:
        if not isinstance(factor_cfg, dict):
            raise ValueError("factor 项必须为字典格式。")

        ftype = (factor_cfg.get("type") or "").strip().lower()
        if not ftype:
            raise ValueError("factor 中必须指定 type，例如: type: double_ma")

        params = dict(factor_cfg.get("params") or {})
        capital_alloc = float(factor_cfg.get("capital_alloc", 1.0))

        if ftype not in ("double_ma", "double_ma_hedge", "adx_ma"):
            raise ValueError(f"不支持的因子类型: {ftype}，可选: double_ma, double_ma_hedge, adx_ma")

        parsed_factors.append({
            "type": ftype,
            "params": params,
            "capital_alloc": capital_alloc
        })

    return parsed_factors


def get_output_paths(cfg):
    """
    返回输出目录及所有输出文件名（均基于配置文件名 config_name）。
    config_name 来自加载的配置文件 stem，如 adx_ma.yaml → adx_ma。
    """
    resolved = cfg.get("_resolved", {})
    out_cfg = cfg.get("output", {})
    config_name = resolved.get("config_name", "backtest")
    return {
        "output_dir": resolved.get("output_dir", "tsla_result"),
        "config_name": config_name,
        "chart_filename": f"backtest_results_{config_name}.png",
        "metrics_filename": f"backtest_metrics_{config_name}.md",
        "trades_filename": f"trades_{config_name}.csv",
        "qs_report_filename": f"qs_report_{config_name}.html",
    }


def get_capital_params(cfg):
    """从配置中取出资金参数字典。"""
    c = cfg.get("capital", {})
    margin_currency = str(c.get("margin_currency", "USD")).upper()
    if margin_currency not in ("USD", "BTC", "ETH"):
        raise ValueError(f"不支持的保证金币种: {margin_currency}，可选: USD, BTC, ETH")

    margin_fx_source = str(c.get("margin_fx_source", "static")).lower()
    if margin_fx_source not in ("static", "binance"):
        raise ValueError(f"不支持的汇率来源: {margin_fx_source}，可选: static, binance")

    margin_fx_to_usd = c.get("margin_fx_to_usd")
    if margin_currency == "USD":
        margin_fx_to_usd = 1.0 if margin_fx_to_usd is None else float(margin_fx_to_usd)
    else:
        if margin_fx_source == "static":
            if margin_fx_to_usd is None:
                raise ValueError(
                    f"保证金币种为 {margin_currency} 且汇率来源为 static 时，"
                    "必须在 capital.margin_fx_to_usd 中设置该币种兑 USD 汇率。"
                )
            margin_fx_to_usd = float(margin_fx_to_usd)
            if margin_fx_to_usd <= 0:
                raise ValueError("capital.margin_fx_to_usd 必须大于 0。")
        else:
            # binance 模式下允许不提供固定汇率；若提供则作为 API 失败时兜底值
            margin_fx_to_usd = None if margin_fx_to_usd is None else float(margin_fx_to_usd)
            if margin_fx_to_usd is not None and margin_fx_to_usd <= 0:
                raise ValueError("capital.margin_fx_to_usd 必须大于 0。")

    default_symbol = f"{margin_currency}USDT" if margin_currency != "USD" else "USDUSDT"
    margin_symbol = str(c.get("margin_symbol", default_symbol)).upper()
    margin_fx_interval = str(c.get("margin_fx_interval", "1d"))
    # 简化配置：高级连接参数收敛为代码默认值，仅保留常用开关
    margin_fx_debug = bool(c.get("margin_fx_debug", False))
    margin_fx_prefetch = bool(c.get("margin_fx_prefetch", True))

    margin_settlement_mode = str(c.get("margin_settlement_mode", "principal_plus_pnl")).lower()
    if margin_settlement_mode not in ("principal_plus_pnl", "mark_to_market"):
        raise ValueError("capital.margin_settlement_mode 仅支持 principal_plus_pnl 或 mark_to_market")

    return {
        "initial_capital": c.get("initial", 100000),
        "position_ratio": c.get("position_ratio", 1.0),
        "max_leverage": c.get("max_leverage", 1.0),
        "margin_settlement_mode": margin_settlement_mode,
        "margin_currency": margin_currency,
        "margin_fx_to_usd": margin_fx_to_usd,
        "margin_fx_source": margin_fx_source,
        "margin_symbol": margin_symbol,
        "margin_fx_interval": margin_fx_interval,
        "margin_fx_debug": margin_fx_debug,
        "margin_fx_prefetch": margin_fx_prefetch,
    }


def get_hedge_config(cfg):
    """
    解析对冲配置。
    返回: { "enabled": bool, "symbols": [{ "name": str, "path": str, "weight": float }] }
    """
    h = cfg.get("hedge", {})
    enabled = h.get("enabled", False)
    if not enabled:
        return {"enabled": False}

    symbols_list = h.get("symbols", [])
    resolved_symbols = []
    for s in symbols_list:
        resolved_symbols.append({
            "name": s.get("name", "Unknown"),
            "path": _resolve_path(s.get("path"), PROJECT_ROOT),
            "weight": s.get("weight", 1.0)
        })

    return {
        "enabled": True,
        "symbols": resolved_symbols
    }

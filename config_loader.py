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
        path = PACKAGE_DIR / "config" / "default.yaml"

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
    factor_cfg = cfg.get("factor")
    if not factor_cfg or not isinstance(factor_cfg, dict):
        raise ValueError("配置中必须包含 factor 段，且 factor 需为对象。示例: factor: { type: double_ma, params: {...} }")

    ftype = (factor_cfg.get("type") or "").strip().lower()
    if not ftype:
        raise ValueError("factor 中必须指定 type，例如: factor: { type: double_ma, params: {...} }")

    params = dict(factor_cfg.get("params") or {})

    if ftype not in ("double_ma", "double_ma_hedge", "single_ma", "adx_ma", "adx_double_ma"):
        raise ValueError(f"不支持的因子类型: {ftype}，可选: double_ma, single_ma, adx_ma, adx_double_ma")

    return {"type": ftype, "params": params}


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
    return {
        "initial_capital": c.get("initial", 100000),
        "position_ratio": c.get("position_ratio", 1.0),
        "max_leverage": c.get("max_leverage", 1.0),
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

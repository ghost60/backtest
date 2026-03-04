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
# 当前包所在目录，即 tsla/
PACKAGE_DIR = Path(__file__).resolve().parent
# 项目根目录，即 tsla/，用于解析「相对项目根」的路径
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
    - config_path 若提供且文件存在，则用该文件；否则用 config/default.yaml
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

    # 注入解析后的路径，供 backtest 等直接使用
    cfg["_resolved"] = {
        "data_path": _resolve_data_path(cfg),
        "output_dir": _resolve_output_dir(cfg),
        "package_dir": str(PACKAGE_DIR),
        "project_root": str(PROJECT_ROOT),
    }
    return cfg


def get_strategy_params(cfg):
    """从配置中取出策略参数字典，供 strategy_ma.run(df, **params) 使用。"""
    s = cfg.get("strategy", {})
    return {
        "ma_short": s.get("ma_short", 5),
        "ma_long": s.get("ma_long", 30),
        "use_price_filter": s.get("use_price_filter", True),
        "entry_delay": s.get("entry_delay", 0),
        "exit_delay": s.get("exit_delay", 0),
    }


def get_output_paths(cfg):
    """返回输出目录及图表、报告文件名（不含目录）。"""
    resolved = cfg.get("_resolved", {})
    out_cfg = cfg.get("output", {})
    return {
        "output_dir": resolved.get("output_dir", "tsla_result"),
        "chart_filename": out_cfg.get("chart_filename", "backtest_results_tsla.png"),
        "metrics_filename": out_cfg.get("metrics_filename", "backtest_metrics_tsla.md"),
    }


def get_capital_params(cfg):
    """从配置中取出资金参数字典。"""
    c = cfg.get("capital", {})
    return {
        "initial_capital": c.get("initial", 100000),
        "position_ratio": c.get("position_ratio", 1.0),
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

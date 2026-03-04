# -*- coding: utf-8 -*-
"""
包初始化，定义 backtest 包及对外接口
TSLA 量化回测包

- run_backtest(config=None, config_path=None)：执行一次完整回测，返回 metrics / df_clean / config
- load_config(config_path=None)：加载 YAML 配置（含路径解析）
- get_strategy_params(cfg)、get_output_paths(cfg)：从配置中取策略参数与输出路径
"""

from .backtest import run_backtest, run_hedge_backtest
from .config_loader import load_config, get_strategy_params, get_output_paths, get_hedge_config

__all__ = ["run_backtest", "run_hedge_backtest", "load_config", "get_strategy_params", "get_output_paths", "get_hedge_config"]

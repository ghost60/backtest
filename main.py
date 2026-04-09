# -*- coding: utf-8 -*-
"""
以包方式运行回测时的入口（需在项目根下执行）

用法：python -m backtest.main
      python -m backtest.main -c backtest/config/double_ma.yaml
"""

import argparse
import sys
from pathlib import Path

# 将项目根加入 path，以便 python -m backtest.main 能正确解析 backtest 包
_PKG_DIR = Path(__file__).resolve().parent
if str(_PKG_DIR.parent) not in sys.path:
    sys.path.insert(0, str(_PKG_DIR.parent))

def main():
    parser = argparse.ArgumentParser(description="TSLA MA 金叉死叉策略回测")
    parser.add_argument("-c", "--config", default="config/double_ma.yaml", help="配置文件路径 (YAML)")
    args = parser.parse_args()
    
    # --- IDE 直接运行调试区 ---
    # 如果你在 IDE 中直接运行 main.py (不带参数)，可以在这里手动指定默认配置
    # config_path = "config/hedge_azo.yaml"
    # config_path = "config/hedge_azo_orly.yaml"
    # config_path = "config/adx_ma.yaml"
    # config_path = "config/multi_factor.yaml"
    # config_path = "config/btcdom_replica.yaml"
    # config_path = "config/double_ma_unified_account.yaml"
    config_path = args.config
    # -----------------------

    from backtest.config_loader import load_config, get_hedge_config
    from backtest.backtest import run_backtest, run_hedge_backtest, run_btcdom_backtest, run_unified_account_backtest

    config = load_config(config_path)
    strategy_name = str((config.get("strategy") or {}).get("name", "")).lower()
    hedge_cfg = get_hedge_config(config)

    if strategy_name == "double_ma_unified_account":
        run_unified_account_backtest(config=config)
    # elif strategy_name == "btcdom_replica":
    #     run_btcdom_backtest(config=config)
    # elif hedge_cfg.get("enabled"):
    #     run_hedge_backtest(config=config)
    else:
        run_backtest(config=config)


if __name__ == "__main__":
    main()

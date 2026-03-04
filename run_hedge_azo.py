# -*- coding: utf-8 -*-
"""
一键运行：TSLA + AZO 对冲策略
"""
import os
import sys
from pathlib import Path

# 确保能找到 tsla 包
curr_dir = Path(__file__).resolve().parent
if str(curr_dir.parent) not in sys.path:
    sys.path.insert(0, str(curr_dir.parent))

from tsla.backtest import run_hedge_backtest
from tsla.config_loader import load_config

if __name__ == "__main__":
    # 指定配置文件路径
    config_path = curr_dir / "config" / "hedge_azo.yaml"
    print(f">>> 开始运行对冲回测 (TSLA+AZO)，使用配置: {config_path}")
    
    config = load_config(str(config_path))
    run_hedge_backtest(config=config)
    
    print("\n>>> 回测完成！结果已保存在 result/ 目录下。")
    input("按回车键退出...")

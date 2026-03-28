#!/bin/bash
# 進入專案目錄
cd /Users/mylin/Documents/mylin102/squeeze-tw-futures-realtime

# 使用 uv 執行模擬交易
# 日誌會存到 logs/automation.log
mkdir -p logs
/Users/mylin/.local/bin/uv run scripts/daily_simulation.py MXFR1 >> logs/automation.log 2>&1

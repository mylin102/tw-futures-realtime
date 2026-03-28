#!/bin/bash
# 進入專案目錄
cd /Users/mylin/Documents/mylin102/squeeze-tw-futures-realtime

# 使用 uv 執行微台指自動交易 (依據 config/trade_config.yaml 設定)
# 日誌會存到 logs/automation.log
mkdir -p logs
/Users/mylin/.local/bin/uv run scripts/daily_simulation.py TMF >> logs/automation.log 2>&1

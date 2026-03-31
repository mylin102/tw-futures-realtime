#!/bin/bash
# 🌙☀️ Squeeze Futures Auto-Start Script
# 自動判斷日盤/夜盤並使用對應配置
# 包含錯誤處理、自動重啟機制和儀表板啟動

# 進入專案目錄
cd /Users/mylin/Documents/mylin102/tw-futures-realtime

# 建立日誌目錄
mkdir -p logs

# 錯誤處理函數
handle_error() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ❌ 錯誤：$1" >> logs/automation.log
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] 等待 60 秒後重啟..." >> logs/automation.log
    sleep 60
}

# 監控函數
monitor_process() {
    local pid=$1
    local script_name=$2
    
    while kill -0 $pid 2>/dev/null; do
        sleep 30
        # 檢查進程是否仍然運行
        if ! kill -0 $pid 2>/dev/null; then
            handle_error "$script_name 進程終止"
            return 1
        fi
    done
    return 0
}

# 啟動儀表板
start_dashboard() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] 📊 啟動儀表板 (port 8501)..." >> logs/automation.log
    
    # 檢查是否已運行
    if pgrep -f "streamlit.*dashboard.py" > /dev/null 2>&1; then
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] ⚠️  儀表板已在運行中" >> logs/automation.log
    else
        # 啟動儀表板
        nohup uv run streamlit run src/squeeze_futures/ui/dashboard.py \
            --server.port 8501 \
            --server.address 0.0.0.0 \
            --server.headless true \
            > logs/dashboard.log 2>&1 &
        DASHBOARD_PID=$!
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] ✓ 儀表板已啟動 (PID: $DASHBOARD_PID)" >> logs/automation.log
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] 🌐 訪問：http://localhost:8501" >> logs/automation.log
    fi
}

# 獲取當前時間
HOUR=$(date +%H)
DAY_OF_WEEK=$(date +%u)  # 1=週一，7=週日

# 判斷是否為交易日 (週一至週五)
if [ "$DAY_OF_WEEK" -gt 5 ]; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] 非交易日，跳过" >> logs/automation.log
    exit 0
fi

# 判斷時段
# 夜盤：15:00-05:00 (包含跨夜)
# 日盤：08:45-13:45
if [ "$HOUR" -ge 15 ] || [ "$HOUR" -lt 5 ]; then
    # 夜盤時段
    SESSION="night"
    SCRIPT="scripts/night_trading_v3.py"
    CONFIG="config/night_config.yaml"
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] 🌙 夜盤時段 (15:00-05:00)" >> logs/automation.log
elif [ "$HOUR" -ge 8 ] && [ "$HOUR" -lt 14 ]; then
    # 日盤時段
    SESSION="day"
    SCRIPT="scripts/daily_simulation.py"
    CONFIG="config/trade_config.yaml"
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ☀️ 日盤時段 (08:45-13:45)" >> logs/automation.log
else
    # 非交易時段
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] 非交易時段，跳过" >> logs/automation.log
    exit 0
fi

# 啟動儀表板
start_dashboard

# 執行對應的交易腳本（包含錯誤處理）
echo "[$(date '+%Y-%m-%d %H:%M:%S')] 啟動 $SESSION 交易系統..." >> logs/automation.log

# 使用 while 循環實現自動重啟
while true; do
    # 檢查是否仍為交易時段
    CURRENT_HOUR=$(date +%H)
    if [ "$SESSION" = "day" ] && ([ "$CURRENT_HOUR" -lt 8 ] || [ "$CURRENT_HOUR" -ge 14 ]); then
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] 日盤時段結束" >> logs/automation.log
        break
    fi
    
    if [ "$SESSION" = "night" ] && ([ "$CURRENT_HOUR" -ge 5 ] && [ "$CURRENT_HOUR" -lt 15 ]); then
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] 夜盤時段結束" >> logs/automation.log
        break
    fi
    
    # 啟動腳本
    /Users/mylin/.local/bin/uv run python $SCRIPT >> logs/automation.log 2>&1 &
    SCRIPT_PID=$!
    
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] 進程 PID: $SCRIPT_PID" >> logs/automation.log
    
    # 監控進程
    monitor_process $SCRIPT_PID $SCRIPT
    
    # 如果進程結束，記錄並等待重啟
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ⚠️  進程意外終止，準備重啟" >> logs/automation.log
    handle_error "腳本執行完畢或崩潰"
done

echo "[$(date '+%Y-%m-%d %H:%M:%S')] ✓ 交易系統停止" >> logs/automation.log

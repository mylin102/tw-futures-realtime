#!/bin/bash
# ☀️ 日盤開盤前檢查腳本
# 使用時間：08:30-08:45

echo "╔════════════════════════════════════════════════════════╗"
echo "║          日盤開盤前檢查 (08:$(date +%M))              ║"
echo "╚════════════════════════════════════════════════════════╝"
echo ""

cd /Users/mylin/Documents/mylin102/tw-futures-realtime

# 1. 檢查系統時間
echo "【1】系統時間檢查"
CURRENT_TIME=$(date +"%Y-%m-%d %H:%M:%S")
DAY_OF_WEEK=$(date +%u)
echo "  當前時間：$CURRENT_TIME"

if [ "$DAY_OF_WEEK" -gt 5 ]; then
    echo "  ⚠️  今天是週末，無交易"
    exit 0
else
    echo "  ✓ 今天是週 $DAY_OF_WEEK，有交易"
fi
echo ""

# 2. 檢查 Shioaji API 連線
echo "【2】Shioaji API 連線檢查"
if ping -c 1 210.59.255.161 &> /dev/null; then
    echo "  ✓ Shioaji API 伺服器連線正常"
else
    echo "  ⚠️  Shioaji API 伺服器連線失敗"
fi
echo ""

# 3. 檢查磁碟空間
echo "【3】磁碟空間檢查"
DISK_USAGE=$(df -h . | tail -1 | awk '{print $5}')
echo "  磁碟使用率：$DISK_USAGE"
if [ "${DISK_USAGE%\%}" -lt 80 ]; then
    echo "  ✓ 磁碟空間充足"
else
    echo "  ⚠️  磁碟空間不足，請清理"
fi
echo ""

# 4. 檢查進程
echo "【4】交易進程檢查"
if pgrep -f "daily_simulation" > /dev/null; then
    echo "  ⚠️  日盤交易已在運行中"
    echo "  PID: $(pgrep -f 'daily_simulation')"
elif pgrep -f "night_trading" > /dev/null; then
    echo "  ⚠️  夜盤交易仍在運行，將自動停止"
    pkill -f "night_trading"
    echo "  ✓ 已停止夜盤交易"
else
    echo "  ✓ 無交易進程運行"
fi
echo ""

# 5. 檢查配置文件
echo "【5】配置文件檢查"
if [ -f "config/day_config.yaml" ]; then
    echo "  ✓ day_config.yaml 存在"
    
    # 讀取關鍵參數
    ENTRY_SCORE=$(grep "entry_score:" config/day_config.yaml | head -1 | awk '{print $2}')
    STOP_LOSS=$(grep "stop_loss_pts:" config/day_config.yaml | head -1 | awk '{print $2}')
    LOTS=$(grep "lots_per_trade:" config/day_config.yaml | head -1 | awk '{print $2}')
    
    echo "  進場門檻：$ENTRY_SCORE"
    echo "  停損點數：$STOP_LOSS pts"
    echo "  交易口數：$LOTS 口"
else
    echo "  ⚠️  day_config.yaml 不存在"
fi
echo ""

# 6. 檢查日誌
echo "【6】昨日交易回顧"
if [ -f "logs/automation.log" ]; then
    YESTERDAY_TRADES=$(grep -c "EXIT" logs/automation.log 2>/dev/null || echo "0")
    echo "  昨日交易次數：$YESTERDAY_TRADES"
    
    LAST_PNL=$(grep "EXIT" logs/automation.log | tail -1 | grep -oP 'PnL: \K[0-9,-]+' || echo "N/A")
    echo "  最後一筆 PnL: $LAST_PNL"
else
    echo "  無昨日交易記錄"
fi
echo ""

# 7. 啟動建議
echo "【7】啟動建議"
HOUR=$(date +%H)
MINUTE=$(date +%M)

if [ "$HOUR" -ge 8 ] && [ "$HOUR" -lt 14 ]; then
    echo "  ✓ 當前為交易時段"
    
    if [ "$HOUR" -eq 8 ] && [ "$MINUTE" -lt 45 ]; then
        echo "  ⏰ 距離開盤還有 $((45-MINUTE)) 分鐘"
        echo "  建議：08:40 啟動系統"
    elif [ "$HOUR" -eq 8 ] && [ "$MINUTE" -ge 45 ]; then
        echo "  🚀 已開盤，立即啟動！"
        echo "  執行：bash autostart.sh"
    else
        echo "  ✓ 交易中，檢查是否已啟動"
        if ! pgrep -f "daily_simulation" > /dev/null; then
            echo "  ⚠️  交易未啟動，請執行：bash autostart.sh"
        fi
    fi
else
    echo "  ⚠️  非交易時段"
fi
echo ""

echo "╔════════════════════════════════════════════════════════╗"
echo "║                    檢查完成                            ║"
echo "╚════════════════════════════════════════════════════════╝"
echo ""
echo "快速啟動："
echo "  bash /Users/mylin/Documents/mylin102/tw-futures-realtime/autostart.sh"
echo ""

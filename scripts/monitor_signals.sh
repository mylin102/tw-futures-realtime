#!/bin/bash
# 持續監控策略 Plan A 並在有交易信號時通知
# 每 2 分鐘檢查一次

LOG_FILE="logs/trade_alerts.log"
DATA_FILE="logs/market_data/TMF_20260330_indicators.csv"
LAST_SIGNAL_FILE="/tmp/last_signal.txt"

echo "=== 策略 Plan A 持續監控 ===" | tee -a $LOG_FILE
echo "開始時間：$(date)" | tee -a $LOG_FILE
echo "檢查間隔：120 秒" | tee -a $LOG_FILE
echo "" | tee -a $LOG_FILE

# 初始化最後信號記錄
if [ ! -f "$LAST_SIGNAL_FILE" ]; then
    echo "none" > "$LAST_SIGNAL_FILE"
fi

check_interval=120  # 2 分鐘檢查一次

while true; do
    TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')
    
    # 讀取最新數據
    LATEST=$(tail -1 $DATA_FILE 2>/dev/null)
    if [ -z "$LATEST" ]; then
        echo "[$TIMESTAMP] 等待數據..." | tee -a $LOG_FILE
        sleep $check_interval
        continue
    fi
    
    # 解析數據
    BAR_TIME=$(echo $LATEST | cut -d',' -f1)
    CLOSE=$(echo $LATEST | cut -d',' -f2)
    SCORE=$(echo $LATEST | cut -d',' -f4)
    MOM_STATE=$(echo $LATEST | cut -d',' -f6)
    SQZ_ON=$(echo $LATEST | cut -d',' -f5)
    
    # 轉換 score 為整數
    SCORE_INT=${SCORE%.*}
    if [ -z "$SCORE_INT" ] || [ "$SCORE_INT" = "0" ]; then
        SCORE_INT=0
    fi
    
    # 檢查最後更新時間（避免監控停滯的數據）
    BAR_HOUR=$(echo $BAR_TIME | cut -d' ' -f2 | cut -d':' -f1)
    BAR_MIN=$(echo $BAR_TIME | cut -d' ' -f2 | cut -d':' -f2)
    
    echo "=== [$TIMESTAMP] 檢查 K 棒：$BAR_TIME ===" | tee -a $LOG_FILE
    echo "價格：$CLOSE | Score: $SCORE_INT | MomState: $MOM_STATE | Squeeze: $SQZ_ON" | tee -a $LOG_FILE
    
    # 檢查進場信號（放寬條件）
    SIGNAL="none"
    
    if [ "$SQZ_ON" = "False" ]; then
        # 多頭進場：score >= 30 AND mom_state >= 2
        if [ "$SCORE_INT" -ge 30 ] 2>/dev/null && { [ "$MOM_STATE" = "3" ] || [ "$MOM_STATE" = "2" ]; }; then
            SIGNAL="BUY"
            echo "🟢 [$TIMESTAMP] BUY 信號 detected!" | tee -a $LOG_FILE
            echo "   條件：score=$SCORE_INT (>=30) ✓, mom_state=$MOM_STATE (>=2) ✓, sqz_on=$SQZ_ON ✓" | tee -a $LOG_FILE
        # 空頭進場：score <= -30 AND mom_state <= 1
        elif [ "$SCORE_INT" -le -30 ] 2>/dev/null && { [ "$MOM_STATE" = "0" ] || [ "$MOM_STATE" = "1" ]; }; then
            SIGNAL="SELL"
            echo "🔴 [$TIMESTAMP] SELL 信號 detected!" | tee -a $LOG_FILE
            echo "   條件：score=$SCORE_INT (<=-30) ✓, mom_state=$MOM_STATE (<=1) ✓, sqz_on=$SQZ_ON ✓" | tee -a $LOG_FILE
        fi
    else
        echo "⚪ Squeeze 壓縮中，等待釋放..." | tee -a $LOG_FILE
    fi
    
    # 如果信號改變，記錄到日誌
    LAST_SIGNAL=$(cat "$LAST_SIGNAL_FILE" 2>/dev/null || echo "none")
    if [ "$SIGNAL" != "$LAST_SIGNAL" ] && [ "$SIGNAL" != "none" ]; then
        echo "⚠️ 信號變化：$LAST_SIGNAL → $SIGNAL" | tee -a $LOG_FILE
        echo "$SIGNAL" > "$LAST_SIGNAL_FILE"
        
        # 發送桌面通知（macOS）
        if command -v osascript &> /dev/null; then
            osascript -e "display notification \"策略 Plan A: $SIGNAL 信號 @ $CLOSE\" with title \"TW Futures Trader\""
        fi
    fi
    
    echo "" | tee -a $LOG_FILE
    sleep $check_interval
done

#!/bin/bash
# 策略 Plan A 夜盤監控腳本
# 每 5 分鐘回報一次交易信號狀態

LOG_FILE="logs/strategy_monitor.log"
DATA_FILE="logs/market_data/TMF_20260330_indicators.csv"

echo "=== 策略 Plan A 夜盤監控 ===" | tee -a $LOG_FILE
echo "開始時間：$(date)" | tee -a $LOG_FILE
echo "" | tee -a $LOG_FILE

while true; do
    echo "=== 檢查時間：$(date) ===" | tee -a $LOG_FILE
    
    # 讀取最新數據
    LATEST=$(tail -1 $DATA_FILE 2>/dev/null)
    if [ -z "$LATEST" ]; then
        echo "等待數據..." | tee -a $LOG_FILE
        sleep 60
        continue
    fi
    
    # 解析數據
    TIMESTAMP=$(echo $LATEST | cut -d',' -f1)
    CLOSE=$(echo $LATEST | cut -d',' -f2)
    SCORE=$(echo $LATEST | cut -d',' -f4)
    MOM_STATE=$(echo $LATEST | cut -d',' -f6)
    SQZ_ON=$(echo $LATEST | cut -d',' -f5)
    
    echo "時間：$TIMESTAMP" | tee -a $LOG_FILE
    echo "價格：$CLOSE" | tee -a $LOG_FILE
    echo "Score: $SCORE" | tee -a $LOG_FILE
    echo "MomState: $MOM_STATE" | tee -a $LOG_FILE
    echo "Squeeze: $SQZ_ON" | tee -a $LOG_FILE
    
    # 檢查進場信號（放寬條件）
    # 多頭：score >= 30 AND mom_state >= 2 AND sqz_on == False
    # 空頭：score <= -30 AND mom_state <= 1 AND sqz_on == False
    
    SCORE_INT=${SCORE%.*}
    
    if [ "$SQZ_ON" = "False" ]; then
        if [ "$SCORE_INT" -ge 30 ] 2>/dev/null && [ "$MOM_STATE" = "3" -o "$MOM_STATE" = "2" ]; then
            echo "🟢 BUY 信號 detected! (score>=$SCORE_INT, mom_state=$MOM_STATE)" | tee -a $LOG_FILE
        elif [ "$SCORE_INT" -le -30 ] 2>/dev/null && [ "$MOM_STATE" = "0" -o "$MOM_STATE" = "1" ]; then
            echo "🔴 SELL 信號 detected! (score<=$SCORE_INT, mom_state=$MOM_STATE)" | tee -a $LOG_FILE
        else
            echo "⚪ 無進場信號 (score=$SCORE_INT, mom_state=$MOM_STATE)" | tee -a $LOG_FILE
        fi
    else
        echo "⚪ Squeeze ON 中，等待釋放" | tee -a $LOG_FILE
    fi
    
    echo "" | tee -a $LOG_FILE
    sleep 300  # 每 5 分鐘檢查一次
done

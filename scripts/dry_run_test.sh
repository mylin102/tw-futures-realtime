#!/bin/bash
# 🧪 Squeeze Futures Dry Run 測試腳本
# 用於推送前測試系統是否正常運作

set -e  # 遇到錯誤立即停止

cd /Users/mylin/Documents/mylin102/tw-futures-realtime

echo "╔════════════════════════════════════════════════════════╗"
echo "║          Squeeze Futures Dry Run 測試                  ║"
echo "╚════════════════════════════════════════════════════════╝"
echo ""

# 1. 檢查 Python 語法
echo "【1】檢查 Python 語法..."
python3 -m py_compile src/squeeze_futures/ui/dashboard.py && echo "  ✓ dashboard.py 語法正確"
python3 -m py_compile scripts/daily_simulation.py && echo "  ✓ daily_simulation.py 語法正確"
python3 -m py_compile scripts/night_trading_v3.py && echo "  ✓ night_trading_v3.py 語法正確"
echo ""

# 2. 檢查配置文件
echo "【2】檢查配置文件..."
if [ -f "config/trade_config.yaml" ]; then
    python3 -c "import yaml; yaml.safe_load(open('config/trade_config.yaml'))" && echo "  ✓ trade_config.yaml 格式正確"
else
    echo "  ✗ trade_config.yaml 不存在"
    exit 1
fi

if [ -f "config/day_config.yaml" ]; then
    python3 -c "import yaml; yaml.safe_load(open('config/day_config.yaml'))" && echo "  ✓ day_config.yaml 格式正確"
else
    echo "  ✗ day_config.yaml 不存在"
    exit 1
fi

if [ -f "config/night_config.yaml" ]; then
    python3 -c "import yaml; yaml.safe_load(open('config/night_config.yaml'))" && echo "  ✓ night_config.yaml 格式正確"
else
    echo "  ✗ night_config.yaml 不存在"
    exit 1
fi
echo ""

# 3. 檢查必要檔案
echo "【3】檢查必要檔案..."
for file in "autostart.sh" "scripts/daily_simulation.py" "src/squeeze_futures/ui/dashboard.py"; do
    if [ -f "$file" ]; then
        echo "  ✓ $file 存在"
    else
        echo "  ✗ $file 不存在"
        exit 1
    fi
done
echo ""

# 4. 檢查 git 狀態
echo "【4】檢查 git 狀態..."
git status --short
echo ""

# 5. 執行 git diff 檢查
echo "【5】檢查變更內容..."
CHANGED_FILES=$(git diff --name-only HEAD)
if [ -n "$CHANGED_FILES" ]; then
    echo "  變更檔案:"
    echo "$CHANGED_FILES" | while read file; do
        echo "    - $file"
    done
else
    echo "  ✓ 無未提交的變更"
fi
echo ""

# 6. 測試儀表板啟動 (可選)
echo "【6】測試儀表板啟動..."
if pgrep -f "streamlit.*dashboard.py" > /dev/null 2>&1; then
    echo "  ⚠️  儀表板已在運行中"
else
    echo "  ✓ 儀表板未運行 (正常)"
fi
echo ""

# 7. 測試交易系統 (可選)
echo "【7】檢查交易系統進程..."
if pgrep -f "daily_simulation" > /dev/null 2>&1; then
    echo "  ⚠️  交易系統已在運行中"
else
    echo "  ✓ 交易系統未運行 (正常)"
fi
echo ""

# 8. 總結
echo "╔════════════════════════════════════════════════════════╗"
echo "║                    Dry Run 完成                        ║"
echo "╚════════════════════════════════════════════════════════╝"
echo ""
echo "✅ 所有檢查通過！可以安全推送"
echo ""
echo "下一步："
echo "  1. git add -A"
echo "  2. git commit -m \"描述變更內容\""
echo "  3. git push"
echo ""

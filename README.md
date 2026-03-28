# 🚀 Squeeze Taiwan Index Futures Real-time System

專為台灣指數期貨 (Taiwan Index Futures) 打造的專業級實戰監控與模擬交易系統。本系統整合了經典的 **TTM Squeeze Momentum** 策略，並透過 **MTF 多週期共振** 與 **VWAP 法人成本線** 進行多重過濾，旨在捕捉高品質的盤中噴發行情。

---

## 🌟 核心功能

### 1. 零延遲數據驅動
- **Shioaji API 整合**: 直接串接永豐金證券，提供毫秒級的盤中即時報價。
- **雙模式自動切換**: 若 API 未登入，自動切換至 `yfinance` 備案模式，確保監控不中斷。

### 2. 專業策略引擎 (Squeeze Logic)
系統核心邏輯基於能量釋放 (`fired`) 訊號，並具備以下特性：
- **MTF Alignment**: 同時掃描 1h (50%), 15m (30%), 5m (20%) 週期，計算共振分數。
- **進入條件**: 當 5m 週期出現能量釋放 (`fired`)，且 MTF 分數絕對值 > 70 並符合 VWAP 方向時進場。
- **雙向反手交易**: 支援在持有部位時，若出現強向反向訊號自動執行「平倉並反手」。

### 3. 全自動化通知與報告
- **即時成交警報**: 每一筆成交都會立即發送 **顏色標註的 HTML Email**。
- **每日績效總結**: 收盤後自動產出精美的 **HTML 績效報告**。
- **全自動執行**: 支援 Mac `cron` 排程，實現全天候無人值守運行。

---

## 🛠️ 快速安裝與設定

本專案使用 `uv` 進行環境管理。

```bash
# 1. 複製專案
git clone https://github.com/mylin102/squeeze-tw-futures-realtime.git
cd squeeze-tw-futures-realtime

# 2. 安裝環境
uv sync
```

### 🔐 認證配置 (.env)
請在專案根目錄建立 `.env`：
```ini
SHIOAJI_API_KEY=您的身份證字號
SHIOAJI_SECRET_KEY=您的密鑰
SHIOAJI_CERT_PATH=/路徑/您的憑證.pfx
SHIOAJI_CERT_PASSWORD=憑證密碼
```

### ⏰ 自動化排程 (macOS Cron)
在 `crontab -e` 加入：
```cron
45 8 * * 1-5 /path/to/autostart.sh
0 15 * * 1-5 /path/to/autostart.sh
```
> **注意**: macOS 使用者必須授予 `/usr/sbin/cron` 「完全磁碟取用權限」才能正常寫入日誌。

---

## 📈 實戰指令

### 啟動即時監控看板
```bash
uv run scripts/realtime_monitor.py MXFR1
```

### 啟動自動模擬交易
```bash
uv run scripts/daily_simulation.py MXFR1
```

---

## 📁 文件索引
- [🎯 核心策略邏輯 (SKILL.md)](SKILL.md): 詳細定義了進出場閾值與動能狀態。
- [📋 詳細操作手冊 (OPERATIONS.md)](OPERATIONS.md): 包含 API 測試與維護說明。

## ⚠️ 免責聲明
本專案僅供技術研究與模擬交易參考，不構成任何投資建議。金融交易具備高度風險，請投資人審慎評估。

## ⚖️ 授權
MIT License

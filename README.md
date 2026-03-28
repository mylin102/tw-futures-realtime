# 🚀 Squeeze Taiwan Index Futures Real-time System

專為台灣指數期貨 (Taiwan Index Futures) 打造的專業級自動化交易系統。整合了 **TTM Squeeze** 能量引擎、**MTF 多週期共振** 與 **VWAP 法人成本線**，並具備嚴謹的實戰風險控管與資金校驗機制。

---

## 🌟 核心功能

### 1. 專業交易策略 (Squeeze Logic)
系統採用深度優化後的 Squeeze 指標 (Length: 14)，精準捕捉盤整後的爆發行情：
- **MTF Alignment**: 同時掃描 1h (20%), 15m (40%), 5m (40%) 週期，計算共振分數。
- **進場過濾 (Score 70)**: 經過 60 天大數據回測驗證，Score 70 為兼顧勝率與獲利的最佳進場門檻。
- **動能加速**: 結合動能柱狀態 (Momentum State) 與 VWAP 成本線，確保具備趨勢優勢。

### 2. 進階風險控管 (Multi-layer Risk Mgmt)
- **硬性停損 (SL)**: 進場自動設定 40 點最後防線。
- **保本移動停損 (Break-even)**: 獲利達 40 點後，自動將停損點移至成本價，鎖定該筆交易不賠。
- **VWAP 結構停損**: 價格反向穿透 VWAP 線時立即平倉，避免成本結構破壞後的無謂虧損。
- **資金安全檢查**: 實戰下單前自動查詢可用保證金，確保高於安全門檻 (**25,000 TWD/口**) 才會執行。

### 3. 配置中心與部位管理
- **YAML 獨立配置**: 所有參數（包含實戰開關、交易口數、停損點數等）皆存放於 `config/trade_config.yaml`。
- **部位上限**: 支援設定最大持倉口數與一次交易口數。
- **收盤清倉**: 支援 Day-trading 模式，每日收盤前自動出清部位。

---

## ⚙️ 參數設定 (config/trade_config.yaml)

您可以透過修改此檔案來控制系統行為：
```yaml
live_trading: false      # 🚀 實戰開關 (True: 真正下單, False: 模擬)

trade_mgmt:
  lots_per_trade: 1      # 每次交易幾口
  max_positions: 3       # 最大留倉口數
  force_close_at_end: true # 收盤前是否自動清倉

risk_mgmt:
  stop_loss_pts: 40      # 固定停損點數
  break_even_pts: 40     # 保本觸發門檻
  exit_on_vwap: true     # 是否啟用 VWAP 結構停損
```

---

## 📊 研究與優化工具
- `scripts/advanced_backtest.py`: 執行雙策略 PK 回測，並產出高對比資產走勢圖。
- `scripts/compare_stop_loss.py`: 針對不同停損點數進行損益壓力測試。
- `scripts/optimize_strategy.py`: 自動掃描多組參數，尋找目前盤勢下的最佳組合。

---

## 🛠️ 快速安裝與執行

```bash
# 1. 複製專案
git clone https://github.com/mylin102/squeeze-tw-futures-realtime.git
cd squeeze-tw-futures-realtime

# 2. 安裝依賴環境
uv sync

# 3. 執行即時模擬/實戰
uv run scripts/daily_simulation.py TMF
```

---

## ⚠️ 免責聲明
本專案僅供技術研究與模擬交易參考，不構成投資建議。金融交易具備高度風險，請審慎評估。

## ⚖️ 授權
MIT License

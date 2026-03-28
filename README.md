# 🚀 Squeeze Taiwan Index Futures Ultimate System

專為台灣指數期貨 (TMF/MX) 打造的專業級自動化交易系統。本系統採用最新的 **Hybrid 進場引擎**、**Opening Regime (開盤強弱判定)** 與 **Partial Exit (分批停利)** 策略，在 60 天回測中展現了卓越的獲利爆發力。

---

## 🌟 核心戰力：分批停利策略 (Partial Exit)

這是本系統目前最強大的獲利引擎，透過 2 口進場的精細管理，實現「低風險、大波段」：
- **TP1 (落袋為安)**: 當獲利達 **+40 點** 時，自動平倉 **1 口** 鎖定基本利潤。
- **Runner (趨勢追蹤)**: 剩下的 **1 口** 自動移至 **保本停損**，零風險參與大波段。
- **回測驗證**: 此策略相較於單口操作，總獲利提升了約 **3.5 倍**。

---

## 🛡️ 安全與風控
- **智慧環境過濾**: 15m EMA 60 與每日開盤強弱判定雙重疊加，只做勝率最高的趨勢。
- **保證金檢查**: 實戰下單前校驗 **25,000 TWD/口**，資金不足自動發送告警。
- **多重平倉邏輯**: 包含 30 點硬性 SL、保本停損、VWAP 結構停損以及趨勢轉弱平倉。

---

## ⚙️ 系統設定 (config/trade_config.yaml)

```yaml
strategy:
  length: 20           # 最佳化計算週期
  entry_score: 70      # 嚴格進場門檻
  use_squeeze: true
  use_pullback: true
  regime_filter: "mid"

  partial_exit:        # 🚀 分批停利設定
    enabled: true
    tp1_pts: 40        # 獲利 40 點平 1 口
    tp1_lots: 1

trade_mgmt:
  lots_per_trade: 2    # 進場直接 2 口
  max_positions: 2
  force_close_at_end: false # 🌙 允許留倉 (Swing Mode)

risk_mgmt:
  stop_loss_pts: 30    # 初始停損 (2 口同步)
```

---

## 📊 績效回測 (TMF - 60D)
- **單口操作 (1 lot)**: +23,750 TWD
- **分批停利 (2 -> 1 lots)**: **+83,070 TWD** (目前預設)

---

## 🛠️ 快速啟動
- **即時交易/模擬**: `uv run scripts/daily_simulation.py TMF`
- **查看優化報告**: `open STRATEGY_REPORT.html`

---

## ⚠️ 免責聲明
本系統僅供技術研究，不構成投資建議。實戰具備高度風險，請投資人務必確認實戰開關 (`live_trading`)。

## ⚖️ 授權
MIT License

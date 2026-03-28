<!-- 
Skill: Squeeze Taiwan Futures Logic
Created: 2026-03-28
Description: 針對台指期微台設計的自動交易邏輯文件，包含指標計算與策略規則。
-->

# Skill: Squeeze Taiwan Futures Logic

此文件記錄了 `squeeze-tw-futures-realtime` 專案的核心交易邏輯與自動化設定，供 Agent 執行、維護與優化使用。

## 1. 核心策略與目標
*   **目標**：捕捉台指期（TX/MX/微台）能量擠壓後的趨勢釋放。
*   **基礎指標**：TTM Squeeze (Bollinger Bands vs Keltner Channels)。
*   **過濾機制**：多週期動能共振分數 (MTF Alignment) + 價格與成交量基準 (VWAP)。

## 2. 指標定義與狀態
*   **Squeeze On (`sqz_on`)**：當 BB 寬度小於 KC 寬度時，能量正在壓縮（盤整）。
*   **Fired 信號 (`fired`)**：當 `sqz_on` 由 True 轉為 False 的瞬間，能量釋放。
*   **動能狀態 (`mom_state`)**：
    *   `3`：動能為正且持續增強（淺藍）。
    *   `2`：動能為正但開始減弱（深藍）。
    *   `1`：動能為負且開始回升（黃/深紅）。
    *   `0`：動能為負且持續增強（淺紅）。
*   **MTF 分數 (`score`)**：綜合 1h (50%), 15m (30%), 5m (20%) 的動能方向與強度，範圍為 -100 到 100。

## 3. 交易進入條件 (Entry)
僅在 `fired`（能量釋放）發生的當根 K 線進行判斷：

*   **多單 (BUY)**：
    *   當前 5m 線發生 `fired`。
    *   MTF `score` > 70（多週期趨勢強勢向上）。
    *   `price_vs_vwap` > 0（價格在 VWAP 之上，多方勢）。
*   **空單 (SELL)**：
    *   當前 5m 線發生 `fired`。
    *   MTF `score` < -70（多週期趨勢強勢向下）。
    *   `price_vs_vwap` < 0（價格在 VWAP 之下，空方勢）。

## 4. 部位管理與反手邏輯 (Management)
*   **反手多單 (Flip to Long)**：若持空單時出現 `fired` 且 `score` > 70，則平空接多。
*   **反手空單 (Flip to Short)**：若持多單時出現 `fired` 且 `score` < -70，則平多接空。
*   **出場條件 (Exit)**：
    *   **多單出場**：`mom_state` < 3 或 `score` < 20。
    *   **空單出場**：`mom_state` > 0 或 `score` > -20。
    *   **休市平倉**：偵測到市場關閉且有持倉時，強制平倉。

## 5. 自動化執行架構
*   **腳本路徑**：`scripts/daily_simulation.py`
*   **啟動方式**：透過 `autostart.sh` 並由 `crontab` 排程執行。
*   **權限要求**：macOS `cron` 必須具備「完全磁碟取用權限」才能寫入日誌。
*   **日誌路徑**：`logs/automation.log`
*   **告警機制**：成交後透過 `send_email_notification` 發送 HTML 郵件。

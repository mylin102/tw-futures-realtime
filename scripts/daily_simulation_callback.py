#!/usr/bin/env python3
"""
Squeeze Taiwan Futures - Event-Driven Version using Shioaji Callback

使用 Shioaji API 的 callback 回呼函數接收即時 K 棒數據，
而非傳統的 polling 輪詢模式。

優勢:
- 即時性更高（數據推送 vs 主動查詢）
- 減少不必要的 API 呼叫
- 更準確的 K 棒收盤判斷

注意:
- 需要 shioaji >= 1.3.2
- 需要有效的 API key 和憑證
"""

import sys
import os
import time
import yaml
import threading
from datetime import datetime
from typing import Dict, Optional
import pandas as pd
from rich.console import Console

# Add src to path for local development
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from squeeze_futures.data.downloader import download_futures_data
from squeeze_futures.data.shioaji_client import ShioajiClient
from squeeze_futures.engine.constants import get_point_value
from squeeze_futures.engine.simulator import PaperTrader
from squeeze_futures.engine.indicators import calculate_futures_squeeze, calculate_mtf_alignment, calculate_atr
from squeeze_futures.report.notifier import send_email_notification

console = Console()


def load_config():
    config_path = os.path.join(os.path.dirname(__file__), "..", "config", "trade_config.yaml")
    with open(config_path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


class EventDrivenTrader:
    """Event-driven trader using shioaji callbacks"""

    def __init__(self, config: dict, ticker: str = "TMF"):
        self.config = config
        self.ticker = ticker
        self.shioaji = ShioajiClient()
        
        # 策略參數
        self.STRATEGY = config['strategy']
        self.MGMT = config['trade_mgmt']
        self.RISK = config['risk_mgmt']
        self.PB = self.STRATEGY.get('pullback', {})
        self.TP = self.STRATEGY.get('partial_exit', {})
        
        # 監控參數
        self.MONITOR = config.get('monitoring', {})
        self.DATA_MODE = self.MONITOR.get('data_mode', 'polling')
        self.PB_CONFIRM_BARS = self.MONITOR.get('pb_confirmation_bars', 12)
        
        # 狀態變數
        self.processed_data: Dict[str, pd.DataFrame] = {}
        self.last_processed_bar = None
        self.has_tp1_hit = False
        self.running = False
        
        # 初始化交易器
        EXEC = config.get('execution', {})
        self.trader = PaperTrader(
            ticker=ticker,
            initial_balance=EXEC.get('initial_balance', 100000),
            point_value=get_point_value(ticker),
            fee_per_side=EXEC.get('broker_fee_per_side', 20),
            exchange_fee_per_side=EXEC.get('exchange_fee_per_side', 0),
            tax_rate=EXEC.get('tax_rate', 0.0)
        )
        
        # 回呼函數鎖
        self._lock = threading.Lock()

    def on_kbar_callback(self, contract, kbar):
        """
        K 棒回呼函數（由 shioaji 在非同步線程中呼叫）
        
        Args:
            contract: Shioaji 合約物件
            kbar: K 棒物件（包含 Open, High, Low, Close, Volume, ts）
        """
        try:
            # 轉換為 DataFrame 並更新
            kbar_dict = {
                'Open': kbar.Open,
                'High': kbar.High,
                'Low': kbar.Low,
                'Close': kbar.Close,
                'Volume': kbar.Volume,
            }
            
            # 更新 5m K 棒數據
            # 注意：實際應用中需要維護完整的 K 棒歷史
            with self._lock:
                # 這裡簡化處理，實際需要累積 K 棒
                console.print(f"[dim]Tick received: {kbar.Close} @ {datetime.fromtimestamp(kbar.ts)}[/dim]")
                
                # 觸發交易邏輯檢查
                self._check_trading_signal()
                
        except Exception as e:
            console.print(f"[red]Callback error: {e}[/red]")

    def _check_trading_signal(self):
        """檢查交易信號（在回呼中呼叫）"""
        # 需要確保有足夠的數據
        if "5m" not in self.processed_data or "15m" not in self.processed_data:
            return

        df_5m = self.processed_data["5m"]
        if df_5m.empty:
            return

        last_5m = df_5m.iloc[-1]
        timestamp = last_5m.name

        # 避免重複處理同一根 K 棒
        if timestamp == self.last_processed_bar:
            return

        self.last_processed_bar = timestamp
        
        # 計算指標
        score = calculate_mtf_alignment(self.processed_data, weights=self.STRATEGY["weights"])['score']
        last_price = last_5m['Close']
        vwap = last_5m.get('vwap', last_price)

        console.print(f"[dim]Bar processed: {timestamp} | Price: {last_price} | Score: {score:.1f}[/dim]")

        # 執行交易邏輯（與 polling 版本相同）
        self._execute_trading_logic(last_price, vwap, timestamp, score, last_5m)

    def _execute_trading_logic(self, last_price, vwap, timestamp, score, last_5m):
        """執行交易邏輯"""
        # 風控與分批平倉
        if self.trader.position != 0:
            self.trader.update_trailing_stop(last_price)
            
            if self.TP['enabled'] and abs(self.trader.position) == self.MGMT['lots_per_trade'] and not self.has_tp1_hit:
                pnl_pts = (last_price - self.trader.entry_price) * (1 if self.trader.position > 0 else -1)
                if pnl_pts >= self.TP['tp1_pts']:
                    self._execute_trade("PARTIAL_EXIT", last_price, timestamp, self.TP['tp1_lots'])
                    self.has_tp1_hit = True
                    self.trader.current_stop_loss = self.trader.entry_price

            self._check_stop_loss(timestamp, last_price)

        # 進場邏輯
        if self.trader.position == 0:
            self.has_tp1_hit = False
            self._check_entry_signal(last_price, vwap, timestamp, score, last_5m)

    def _check_stop_loss(self, timestamp, last_price):
        """檢查停損"""
        vwap = self.processed_data["5m"].iloc[-1].get('vwap', last_price)
        
        if self.trader.position > 0 and self.trader.current_stop_loss and last_price <= self.trader.current_stop_loss:
            self._execute_trade("EXIT", self.trader.current_stop_loss, timestamp, abs(self.trader.position))
        elif self.trader.position < 0 and self.trader.current_stop_loss and last_price >= self.trader.current_stop_loss:
            self._execute_trade("EXIT", self.trader.current_stop_loss, timestamp, abs(self.trader.position))
        elif self.RISK.get("exit_on_vwap", False):
            if (self.trader.position > 0 and last_price < vwap) or \
               (self.trader.position < 0 and last_price > vwap):
                self._execute_trade("EXIT", last_price, timestamp, abs(self.trader.position))

    def _check_entry_signal(self, last_price, vwap, timestamp, score, last_5m):
        """檢查進場信號"""
        df_5m = self.processed_data["5m"]
        df_15m = self.processed_data.get("15m", df_5m)
        last_15m = df_15m.iloc[-1] if not df_15m.empty else last_5m

        # 計算 ATR 停損
        ATR_MULT = self.RISK.get('atr_multiplier', 0.0)
        ATR_LENGTH = self.RISK.get('atr_length', 14)
        
        if ATR_MULT > 0:
            atr_series = calculate_atr(df_5m, length=ATR_LENGTH)
            current_atr = atr_series.iloc[-1] if not atr_series.empty and not pd.isna(atr_series.iloc[-1]) else None
            stop_loss_pts = current_atr * ATR_MULT if current_atr else self.RISK["stop_loss_pts"]
        else:
            stop_loss_pts = self.RISK["stop_loss_pts"]

        # 進場條件
        sqz_buy = (not last_5m.get('sqz_on', False)) and score >= self.STRATEGY["entry_score"] and last_price > vwap
        pb_buy = df_5m['is_new_high'].tail(self.PB_CONFIRM_BARS).any() if 'is_new_high' in df_5m.columns else False
        pb_buy = pb_buy and last_5m.get('in_bull_pb_zone', False) and last_price > last_5m.get('Open', last_price)
        
        sqz_sell = (not last_5m.get('sqz_on', False)) and score <= -self.STRATEGY["entry_score"] and last_price < vwap
        pb_sell = df_5m['is_new_low'].tail(self.PB_CONFIRM_BARS).any() if 'is_new_low' in df_5m.columns else False
        pb_sell = pb_sell and last_5m.get('in_bear_pb_zone', False) and last_price < last_5m.get('Open', last_price)

        can_long = last_15m.get('Close', last_price) > last_15m.get('ema_filter', last_price)
        can_short = last_15m.get('Close', last_price) < last_15m.get('ema_filter', last_price)

        if (sqz_buy or pb_buy) and can_long and self.MGMT.get("allow_long", True):
            self._execute_trade("BUY", last_price, timestamp, self.MGMT["lots_per_trade"], stop_loss=stop_loss_pts)
        elif (sqz_sell or pb_sell) and can_short and self.MGMT.get("allow_short", True):
            self._execute_trade("SELL", last_price, timestamp, self.MGMT["lots_per_trade"], stop_loss=stop_loss_pts)

    def _execute_trade(self, signal: str, price: float, timestamp, lots: int, **kwargs):
        """執行交易"""
        result = self.trader.execute_signal(
            signal, price, timestamp, lots=lots,
            max_lots=self.MGMT.get("max_positions", 2),
            stop_loss=kwargs.get('stop_loss'),
            break_even_trigger=kwargs.get('break_even_trigger')
        )
        
        if result:
            direction = "🟢 BUY" if signal == "BUY" else "🔴 SELL" if signal == "SELL" else "⚪ EXIT"
            console.print(f"[bold green]{direction} {self.ticker} @ {price:.0f}[/bold green]")

    def start(self):
        """啟動 event-driven 交易"""
        console.print(f"🚀 Event-Driven Squeeze Trader Started - Mode: {self.DATA_MODE}")
        
        # 登入 shioaji
        self.shioaji.login()
        if not self.shioaji.is_logged_in:
            console.print("[bold red]Shioaji login failed![/bold red]")
            return

        contract = self.shioaji.get_futures_contract(self.ticker)
        if not contract:
            console.print(f"[bold red]Contract {self.ticker} not found![/bold red]")
            return

        if self.DATA_MODE == "callback":
            # 使用 callback 模式
            console.print("[green]Using CALLBACK mode (real-time data)[/green]")
            
            # 訂閱 K 棒數據
            self.shioaji.start_kbar_callback(contract, "5min", self.on_kbar_callback)
            
            # 初始載入歷史數據
            self._load_initial_data()
            
            # 保持運行
            self.running = True
            try:
                while self.running:
                    time.sleep(1)
            except KeyboardInterrupt:
                console.print("\n[yellow]Stopping trader...[/yellow]")
                self.running = False
        else:
            # 使用 polling 模式（向後相容）
            console.print(f"[yellow]Using POLLING mode (interval={self.MONITOR.get('poll_interval_secs', 30)}s)[/yellow]")
            self._run_polling_mode()

    def _load_initial_data(self):
        """初始載入歷史數據"""
        console.print("[dim]Loading initial data...[/dim]")
        for tf in ["5m", "15m", "1h"]:
            df = self.shioaji.get_kline(self.ticker, interval=tf)
            if df.empty:
                df = download_futures_data("^TWII", interval=tf, period="5d")
            if not df.empty:
                self.processed_data[tf] = calculate_futures_squeeze(
                    df, 
                    bb_length=self.STRATEGY["length"],
                    **{
                        'ema_fast': self.PB.get('ema_fast', 20),
                        'ema_slow': self.PB.get('ema_slow', 60),
                        'lookback': self.PB.get('lookback', 60),
                        'pb_buffer': self.PB.get('buffer', 1.002)
                    }
                )

    def _run_polling_mode(self):
        """Polling 模式運行（向後相容）"""
        # 這裡可以呼叫原有的 run_simulation 邏輯
        console.print("[yellow]Falling back to polling mode - use daily_simulation.py for full support[/yellow]")


def main():
    """Main entry point"""
    config = load_config()
    ticker = sys.argv[1] if len(sys.argv) > 1 else "TMF"
    
    trader = EventDrivenTrader(config, ticker)
    trader.start()


if __name__ == "__main__":
    main()

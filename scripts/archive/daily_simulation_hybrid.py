#!/usr/bin/env python3
"""
Squeeze Taiwan Futures - Hybrid Mode (Callback + Polling)

混合模式：
- Callback: 接收即時 tick/K 棒數據，觸發交易決策
- Polling: 定期同步完整 K 棒數據，確保數據完整性
- 雙重機制：當 callback 失效時，polling 作為備援

優勢:
- 即時性：callback 推送，毫秒級反應
- 穩定性：polling 定期校準，避免數據遺漏
- 容錯性：任一模式失效仍可運作
"""

import sys
import os
import time
import yaml
import threading
from datetime import datetime, timedelta
from typing import Dict, Optional, Any
from collections import deque
import pandas as pd
from rich.console import Console

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


class HybridDataFeed:
    """
    混合數據饋送：Callback + Polling
    
    功能:
    - 訂閱 shioaji callback 接收即時數據
    - 定期 polling 同步完整 K 棒
    - 數據緩衝與去重
    """

    def __init__(self, shioaji: ShioajiClient, ticker: str, config: dict):
        self.shioaji = shioaji
        self.ticker = ticker
        self.config = config
        
        self.monitor_cfg = config.get('monitoring', {})
        self.callback_cfg = self.monitor_cfg.get('callback', {})
        
        # 數據緩衝
        self.kbar_buffers: Dict[str, deque] = {
            '5m': deque(maxlen=self.callback_cfg.get('buffer_size', 100)),
            '15m': deque(maxlen=50),
            '1h': deque(maxlen=20)
        }
        
        # 狀態標誌
        self._last_callback_time: Dict[str, datetime] = {}
        self._callback_active = False
        self._polling_active = True
        self._lock = threading.Lock()
        
        # 統計
        self.stats = {
            'callback_count': 0,
            'polling_count': 0,
            'last_callback': None,
            'last_polling': None,
        }

    def on_kbar_callback(self, contract, kbar):
        """K 棒回呼處理"""
        try:
            ts = datetime.fromtimestamp(kbar.ts)
            now = datetime.now()
            
            # 更新狀態
            self._callback_active = True
            self._last_callback_time['5m'] = now
            self.stats['callback_count'] += 1
            self.stats['last_callback'] = ts
            
            # 構建 K 棒數據
            kbar_data = {
                'ts': ts,
                'Open': kbar.Open,
                'High': kbar.High,
                'Low': kbar.Low,
                'Close': kbar.Close,
                'Volume': kbar.Volume,
            }
            
            # 加入緩衝區
            with self._lock:
                self.kbar_buffers['5m'].append(kbar_data)
            
            console.print(f"[dim][CB] {ts.strftime('%H:%M:%S')} {kbar.Close} (vol: {kbar.Volume})[/dim]")
            
        except Exception as e:
            console.print(f"[red][Callback Error] {e}[/red]")

    def poll_sync(self, interval: str = "5m") -> Optional[pd.DataFrame]:
        """
        Polling 同步 K 棒數據
        
        Args:
            interval: 週期 (5m, 15m, 1h)
            
        Returns:
            DataFrame with OHLCV data
        """
        try:
            df = self.shioaji.get_kline(self.ticker, interval=interval)
            
            if df.empty:
                df = download_futures_data("^TWII", interval=interval, period="5d")
            
            if not df.empty:
                self._polling_active = True
                self.stats['polling_count'] += 1
                self.stats['last_polling'] = datetime.now()
                
                # 更新緩衝區
                with self._lock:
                    # 轉換為 dict 格式加入緩衝
                    for idx, row in df.tail(10).iterrows():
                        self.kbar_buffers[interval].append({
                            'ts': idx.to_pydatetime(),
                            'Open': row['Open'],
                            'High': row['High'],
                            'Low': row['Low'],
                            'Close': row['Close'],
                            'Volume': row.get('Volume', 0),
                        })
                
                console.print(f"[dim][POLL] Synced {interval}: {len(df)} bars[/dim]")
                return df
                
        except Exception as e:
            console.print(f"[red][Polling Error] {e}[/red]")
            self._polling_active = False
        
        return pd.DataFrame()

    def get_latest_kbars(self, interval: str = "5m", min_bars: int = 60) -> Optional[pd.DataFrame]:
        """
        獲取最新 K 棒數據（合併 callback + polling）
        
        Args:
            interval: 週期
            min_bars: 最小返回數量
            
        Returns:
            DataFrame with OHLCV data
        """
        with self._lock:
            buffer = self.kbar_buffers.get(interval, deque())
            if len(buffer) < min_bars:
                return None
            
            df = pd.DataFrame(list(buffer))
            if df.empty:
                return None
            
            df.set_index('ts', inplace=True)
            df = df.sort_index()
            
            # 確保 OHLCV 欄位
            df = df.rename(columns={
                'Open': 'Open', 'High': 'High', 'Low': 'Low',
                'Close': 'Close', 'Volume': 'Volume'
            })
            
            return df

    def check_health(self) -> dict:
        """檢查數據源健康狀態"""
        now = datetime.now()
        
        # 檢查 callback 是否活躍（最近 60 秒有數據）
        last_cb = self._last_callback_time.get('5m')
        cb_healthy = (last_cb and (now - last_cb).total_seconds() < 60) if last_cb else False
        
        return {
            'callback_active': self._callback_active,
            'callback_healthy': cb_healthy,
            'polling_active': self._polling_active,
            'buffer_sizes': {k: len(v) for k, v in self.kbar_buffers.items()},
            'stats': self.stats.copy(),
        }

    def subscribe(self):
        """訂閱市場數據"""
        contract = self.shioaji.get_futures_contract(self.ticker)
        if not contract:
            console.print("[red]Contract not found![/red]")
            return False
        
        # 訂閱 K 棒 callback
        success = self.shioaji.start_kbar_callback(contract, "5min", self.on_kbar_callback)
        if success:
            console.print("[green][SUB] Subscribed to kbar callback[/green]")
        else:
            console.print("[yellow][SUB] Callback subscription failed, using polling only[/yellow]")
        
        return success


class HybridTrader:
    """混合模式交易器"""

    def __init__(self, config: dict, ticker: str = "TMF"):
        self.config = config
        self.ticker = ticker
        
        # 策略參數
        self.STRATEGY = config['strategy']
        self.MGMT = config['trade_mgmt']
        self.RISK = config['risk_mgmt']
        self.PB = self.STRATEGY.get('pullback', {})
        self.TP = self.STRATEGY.get('partial_exit', {})
        
        # 監控參數
        self.monitor_cfg = config.get('monitoring', {})
        self.poll_interval = self.monitor_cfg.get('poll_interval_secs', 30)
        self.pb_confirm_bars = self.monitor_cfg.get('pb_confirmation_bars', 12)
        
        # 初始化
        self.shioaji = ShioajiClient()
        EXEC = config.get('execution', {})
        self.trader = PaperTrader(
            ticker=ticker,
            initial_balance=EXEC.get('initial_balance', 100000),
            point_value=get_point_value(ticker),
            fee_per_side=EXEC.get('broker_fee_per_side', 20),
            exchange_fee_per_side=EXEC.get('exchange_fee_per_side', 0),
            tax_rate=EXEC.get('tax_rate', 0.0)
        )
        
        self.data_feed = HybridDataFeed(self.shioaji, ticker, config)
        
        # 交易狀態
        self.processed_data: Dict[str, pd.DataFrame] = {}
        self.last_processed_bar = None
        self.has_tp1_hit = False
        self.running = False
        
        # 線程控制
        self._stop_event = threading.Event()

    def _process_bar(self, df_5m: pd.DataFrame, df_15m: pd.DataFrame, df_1h: pd.DataFrame = None):
        """處理 K 棒並執行交易邏輯"""
        if df_5m.empty or df_15m.empty:
            return
        
        last_5m = df_5m.iloc[-1]
        timestamp = last_5m.name
        
        # 避免重複處理
        if timestamp == self.last_processed_bar:
            return
        
        self.last_processed_bar = timestamp
        
        # 計算指標
        PB_ARGS = {
            'ema_fast': self.PB.get('ema_fast', 20),
            'ema_slow': self.PB.get('ema_slow', 60),
            'lookback': self.PB.get('lookback', 60),
            'pb_buffer': self.PB.get('buffer', 1.002)
        }
        
        self.processed_data['5m'] = calculate_futures_squeeze(df_5m, bb_length=self.STRATEGY["length"], **PB_ARGS)
        self.processed_data['15m'] = calculate_futures_squeeze(df_15m, bb_length=self.STRATEGY["length"], **PB_ARGS)
        
        if df_1h is not None and not df_1h.empty:
            self.processed_data['1h'] = calculate_futures_squeeze(df_1h, bb_length=self.STRATEGY["length"], **PB_ARGS)
        
        # 計算 MTF 對齊
        score = calculate_mtf_alignment(self.processed_data, weights=self.STRATEGY["weights"])['score']
        last_price = last_5m['Close']
        vwap = last_5m.get('vwap', last_price)
        
        console.print(f"[bold]Bar: {timestamp.strftime('%H:%M')} | Price: {last_price:.0f} | Score: {score:+.1f}[/bold]")
        
        # 執行交易
        self._execute_trading_logic(last_price, vwap, timestamp, score)

    def _execute_trading_logic(self, last_price: float, vwap: float, timestamp, score: float):
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

            self._check_stop_loss(timestamp, last_price, vwap)

        # 進場邏輯
        if self.trader.position == 0:
            self.has_tp1_hit = False
            self._check_entry_signal(last_price, vwap, timestamp, score)

    def _check_stop_loss(self, timestamp, last_price, vwap):
        """檢查停損"""
        exited = False
        
        if self.trader.position > 0 and self.trader.current_stop_loss:
            if last_price <= self.trader.current_stop_loss:
                self._execute_trade("EXIT", self.trader.current_stop_loss, timestamp, abs(self.trader.position))
                exited = True
        elif self.trader.position < 0 and self.trader.current_stop_loss:
            if last_price >= self.trader.current_stop_loss:
                self._execute_trade("EXIT", self.trader.current_stop_loss, timestamp, abs(self.trader.position))
                exited = True
        
        if not exited and self.RISK.get("exit_on_vwap", False):
            if (self.trader.position > 0 and last_price < vwap) or \
               (self.trader.position < 0 and last_price > vwap):
                self._execute_trade("EXIT", last_price, timestamp, abs(self.trader.position))

    def _check_entry_signal(self, last_price: float, vwap: float, timestamp, score: float):
        """檢查進場信號"""
        df_5m = self.processed_data.get('5m', pd.DataFrame())
        df_15m = self.processed_data.get('15m', pd.DataFrame())
        
        if df_5m.empty or df_15m.empty:
            return
        
        last_5m = df_5m.iloc[-1]
        last_15m = df_15m.iloc[-1]
        
        # ATR 停損
        ATR_MULT = self.RISK.get('atr_multiplier', 0.0)
        ATR_LENGTH = self.RISK.get('atr_length', 14)
        
        if ATR_MULT > 0:
            atr_series = calculate_atr(df_5m, length=ATR_LENGTH)
            current_atr = atr_series.iloc[-1] if not atr_series.empty else None
            stop_loss_pts = current_atr * ATR_MULT if current_atr else self.RISK["stop_loss_pts"]
        else:
            stop_loss_pts = self.RISK["stop_loss_pts"]
        
        # 進場條件
        sqz_buy = (not last_5m.get('sqz_on', False)) and score >= self.STRATEGY["entry_score"] and last_price > vwap and last_5m.get('mom_state') == 3
        pb_buy = df_5m['is_new_high'].tail(self.pb_confirm_bars).any() if 'is_new_high' in df_5m.columns else False
        pb_buy = pb_buy and last_5m.get('in_bull_pb_zone', False) and last_price > last_5m.get('Open', last_price)
        
        sqz_sell = (not last_5m.get('sqz_on', False)) and score <= -self.STRATEGY["entry_score"] and last_price < vwap and last_5m.get('mom_state') == 0
        pb_sell = df_5m['is_new_low'].tail(self.pb_confirm_bars).any() if 'is_new_low' in df_5m.columns else False
        pb_sell = pb_sell and last_5m.get('in_bear_pb_zone', False) and last_price < last_5m.get('Open', last_price)
        
        can_long = last_15m.get('Close', last_price) > last_15m.get('ema_filter', last_price)
        can_short = last_15m.get('Close', last_price) < last_15m.get('ema_filter', last_price)
        
        if (sqz_buy or pb_buy) and can_long and self.MGMT.get("allow_long", True):
            self._execute_trade("BUY", last_price, timestamp, self.MGMT["lots_per_trade"], stop_loss=stop_loss_pts, break_even_trigger=self.RISK.get("break_even_pts"))
        elif (sqz_sell or pb_sell) and can_short and self.MGMT.get("allow_short", True):
            self._execute_trade("SELL", last_price, timestamp, self.MGMT["lots_per_trade"], stop_loss=stop_loss_pts, break_even_trigger=self.RISK.get("break_even_pts"))

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

    def _polling_loop(self):
        """Polling 同步線程"""
        poll_interval = self.monitor_cfg.get('poll_interval_secs', 30)
        
        while not self._stop_event.is_set():
            try:
                # 同步各週期數據
                df_5m = self.data_feed.poll_sync("5m")
                df_15m = self.data_feed.poll_sync("15m")
                df_1h = self.data_feed.poll_sync("1h")
                
                if df_5m is not None and df_15m is not None:
                    self._process_bar(df_5m, df_15m, df_1h)
                
                # 等待下次輪詢
                self._stop_event.wait(poll_interval)
                
            except Exception as e:
                console.print(f"[red][Polling Loop Error] {e}[/red]")
                self._stop_event.wait(5)

    def _monitor_loop(self):
        """監控線程（檢查健康狀態）"""
        while not self._stop_event.is_set():
            try:
                health = self.data_feed.check_health()
                
                status_parts = []
                if health['callback_healthy']:
                    status_parts.append("[green]CB:OK[/green]")
                elif health['callback_active']:
                    status_parts.append("[yellow]CB:LAG[/yellow]")
                else:
                    status_parts.append("[red]CB:OFF[/red]")
                
                if health['polling_active']:
                    status_parts.append(f"[green]POLL:OK[/green] (buf: {health['buffer_sizes'].get('5m', 0)})")
                else:
                    status_parts.append("[red]POLL:OFF[/red]")
                
                status = " | ".join(status_parts)
                console.print(f"[dim][HEALTH] {status}[/dim]")
                
                self._stop_event.wait(60)  # 每分鐘檢查一次
                
            except Exception as e:
                console.print(f"[red][Monitor Error] {e}[/red]")
                self._stop_event.wait(10)

    def start(self):
        """啟動混合模式交易"""
        console.print(f"🚀 Hybrid Squeeze Trader Started - Mode: CALLBACK+POLLING")
        
        # 登入 shioaji
        self.shioaji.login()
        if not self.shioaji.is_logged_in:
            console.print("[bold red]Shioaji login failed![/bold red]")
            return
        
        # 訂閱 callback
        self.data_feed.subscribe()
        
        # 初始同步
        console.print("[dim]Initial data sync...[/dim]")
        df_5m = self.data_feed.poll_sync("5m")
        df_15m = self.data_feed.poll_sync("15m")
        df_1h = self.data_feed.poll_sync("1h")
        
        if df_5m is None or df_15m is None:
            console.print("[bold red]Initial sync failed![/bold red]")
            return
        
        # 啟動線程
        self.running = True
        
        polling_thread = threading.Thread(target=self._polling_loop, daemon=True)
        monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        
        polling_thread.start()
        monitor_thread.start()
        
        console.print("[green]✓ Trading started (Ctrl+C to stop)[/green]")
        
        # 主線程等待
        try:
            while self.running:
                time.sleep(1)
        except KeyboardInterrupt:
            console.print("\n[yellow]Stopping trader...[/yellow]")
            self.stop()
        
        polling_thread.join(timeout=5)
        monitor_thread.join(timeout=5)

    def stop(self):
        """停止交易"""
        self.running = False
        self._stop_event.set()
        
        # 平倉
        if self.trader.position != 0:
            console.print("[yellow]Closing position...[/yellow]")
            self._execute_trade("EXIT", 0, datetime.now(), abs(self.trader.position))
        
        # 登出
        self.shioaji.logout()
        console.print("[green]✓ Trader stopped[/green]")


def main():
    """Main entry point"""
    config = load_config()
    ticker = sys.argv[1] if len(sys.argv) > 1 else "TMF"
    
    trader = HybridTrader(config, ticker)
    trader.start()


if __name__ == "__main__":
    main()

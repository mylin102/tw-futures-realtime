import time
import datetime
import pandas as pd
import yaml
import shioaji as sj
from shioaji import TickFOPv1, Exchange
import sys
import os
import threading
from pathlib import Path
from rich.console import Console

# 加入本地 src
sys.path.append(os.path.join(os.path.dirname(__file__), "../src"))
from squeeze_futures.engine.indicators import calculate_futures_squeeze, calculate_mtf_alignment
import login.shioaji_login as shioaji_login

console = Console()

class TMFHybridMonitor:
    def __init__(self):
        self.cfg = self.load_config()
        self.mode = self.cfg['active_mode']
        self.m_cfg = self.cfg['modes'][self.mode]
        self.api = shioaji_login.login()
        
        self.market_data = {"TMF": {"close": 0.0, "bid": 0.0, "ask": 0.0}}
        self.active_contract = None
        self.lock = threading.Lock()
        
        self.position = 0 
        self.entry_price = 0
        self.has_tp1 = False
        
        # 紀錄路徑
        self.log_path = Path(__file__).parent / "../logs/market_data" / f"TMF_{datetime.datetime.now().strftime('%Y%m%d')}_indicators.csv"
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

    def load_config(self):
        path = Path(__file__).parent / "../config/trade_config.yaml"
        with open(path, 'r') as f: return yaml.safe_load(f)

    def find_contract(self):
        try:
            mtx_group = getattr(self.api.Contracts.Futures, "MXF", [])
            mtx_cons = [c for c in mtx_group if len(c.code) == 7]; mtx_cons.sort(key=lambda x: x.delivery_date)
            self.active_contract = mtx_cons[0]
            console.print(f"[bold green]TMF Monitoring: {self.active_contract.code}[/bold green]")
            return True
        except Exception: return False

    def on_tick(self, exchange: Exchange, tick: TickFOPv1):
        with self.lock:
            self.market_data["TMF"]["close"] = float(tick.close)
            self.market_data["TMF"]["bid"] = float(getattr(tick, 'bid_price', tick.close))
            self.market_data["TMF"]["ask"] = float(getattr(tick, 'ask_price', tick.close))

    def run_strategy_logic(self):
        try:
            now = datetime.datetime.now()
            # 🚀 出場優化：收盤誘捕
            is_eod_trap = (now.hour == 13 and 10 <= now.minute < 30)
            is_eod_panic = (now.hour == 13 and now.minute >= 30)
            
            if self.position != 0:
                cur_p = self.market_data["TMF"]["close"]
                cur_bid = self.market_data["TMF"]["bid"]
                cur_ask = self.market_data["TMF"]["ask"]
                
                if self.m_cfg['force_close_at_end']:
                    if is_eod_panic:
                        self.position = 0; console.print("[red]EOD Panic Flush.[/red]")
                    elif is_eod_trap:
                        # 掛單誘捕 (假設多單：掛高等待；空單：掛低等待)
                        trap_price = cur_ask + 2.0 if self.position > 0 else cur_bid - 2.0
                        if (self.position > 0 and cur_p >= trap_price) or (self.position < 0 and cur_p <= trap_price):
                            self.position = 0; console.print("[yellow]EOD Trap Fill![/yellow]")

            # (其餘指標計算與進場邏輯)
            # ...
        except Exception: pass

    def run(self):
        if not self.find_contract(): return
        self.api.quote.subscribe(self.active_contract, quote_type='tick', callback=self.on_tick)
        console.print(f">>> TMF [{self.mode}] Monitor Started <<<")
        try:
            while True:
                self.run_strategy_logic()
                time.sleep(60)
        except KeyboardInterrupt: self.api.logout()

if __name__ == "__main__":
    monitor = TMFHybridMonitor()
    monitor.run()

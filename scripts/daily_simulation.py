import sys
import os
import time
from datetime import datetime
import pandas as pd
from rich.console import Console
from rich.live import Live
from rich.panel import Panel

# 加入 src 到路徑
sys.path.append(os.path.join(os.path.dirname(__file__), "..", "src"))

from squeeze_futures.data.downloader import download_futures_data
from squeeze_futures.data.shioaji_client import ShioajiClient
from squeeze_futures.engine.indicators import calculate_futures_squeeze, calculate_mtf_alignment
from squeeze_futures.engine.simulator import PaperTrader
from squeeze_futures.report.notifier import send_email_notification

console = Console()

# --- 優化後的策略參數 (2026-03-28 Optimized) ---
STRATEGY_CONFIG = {
    "length": 14,
    "entry_score": 60,
    "stop_loss": 40,
    "break_even": 40,
    "weights": {"1h": 0.2, "15m": 0.4, "5m": 0.4}
}

def is_market_open():
    """判斷目前是否在台指期交易時段"""
    now = datetime.now()
    weekday = now.weekday()
    current_time = now.hour * 100 + now.minute
    
    is_day = (0 <= weekday <= 4) and (845 <= current_time < 1345)
    is_night = False
    if (0 <= weekday <= 4) and (current_time >= 1500): is_night = True
    if (1 <= weekday <= 5) and (current_time < 500): is_night = True
    return is_day or is_night

def run_simulation(ticker="MXFR1"):
    trader = PaperTrader(ticker=ticker)
    shioaji = ShioajiClient()
    use_shioaji = shioaji.login()
    
    console.print(f"[bold green]Starting Daily Simulation for {ticker} (Optimized)...[/bold green]")
    
    try:
        while True:
            if not is_market_open():
                if trader.position != 0:
                    console.print("\n[bold red]Market closed. Forcing exit position...[/bold red]")
                    break
                console.print(f"[{datetime.now().strftime('%H:%M:%S')}] Market is closed. Resting...", end="\r")
                time.sleep(300)
                continue

            # 1. 抓取多週期數據
            processed_data = {}
            for tf in ["5m", "15m", "1h"]:
                df = shioaji.get_kline(ticker, interval=tf) if use_shioaji else pd.DataFrame()
                if df.empty:
                    # 使用 ^TWII 代替 MXFR1 進行 yfinance 下載
                    df = download_futures_data("^TWII", interval=tf, period="5d")
                
                if not df.empty:
                    processed_data[tf] = calculate_futures_squeeze(
                        df, 
                        bb_length=STRATEGY_CONFIG["length"], 
                        kc_length=STRATEGY_CONFIG["length"]
                    )
            
            if "5m" not in processed_data: continue
            
            # 2. 策略邏輯
            last_5m = processed_data["5m"].iloc[-1]
            alignment = calculate_mtf_alignment(processed_data, weights=STRATEGY_CONFIG["weights"])
            score = alignment['score']
            
            current_price = last_5m['Close']
            timestamp = last_5m.name if hasattr(last_5m, 'name') else datetime.now()
            
            log_msg = ""
            
            # --- 風控與移動停損 ---
            if trader.position != 0:
                # 檢查保本觸發
                if trader.update_trailing_stop(current_price):
                    console.print(f"[cyan][{timestamp}] Break-even stop set at {trader.current_stop_loss}[/cyan]")
                
                # 檢查是否觸發停損 (初始或保本)
                stop_msg = trader.check_stop_loss(current_price, timestamp)
                if stop_msg:
                    log_msg = "[STOP LOSS] " + stop_msg

            # --- 進場邏輯 ---
            if not log_msg:
                # 情況 A: 目前空手
                if trader.position == 0:
                    # 改進：不強制 fired，只需能量釋放中且共振極強
                    is_trending = (not last_5m['sqz_on']) and (abs(score) >= STRATEGY_CONFIG["entry_score"])
                    if is_trending:
                        if score >= STRATEGY_CONFIG["entry_score"] and current_price > last_5m['vwap'] and last_5m['mom_state'] == 3:
                            log_msg = trader.execute_signal("BUY", current_price, timestamp, 
                                                           stop_loss=STRATEGY_CONFIG["stop_loss"],
                                                           break_even_trigger=STRATEGY_CONFIG["break_even"])
                        elif score <= -STRATEGY_CONFIG["entry_score"] and current_price < last_5m['vwap'] and last_5m['mom_state'] == 0:
                            log_msg = trader.execute_signal("SELL", current_price, timestamp,
                                                           stop_loss=STRATEGY_CONFIG["stop_loss"],
                                                           break_even_trigger=STRATEGY_CONFIG["break_even"])
                
                # 情況 B: 持有多單
                elif trader.position == 1:
                    # 強勢反向信號 (反手)
                    if score <= -STRATEGY_CONFIG["entry_score"]:
                        log_msg = trader.execute_signal("EXIT", current_price, timestamp)
                        log_msg += " | " + trader.execute_signal("SELL", current_price, timestamp,
                                                               stop_loss=STRATEGY_CONFIG["stop_loss"])
                    # 一般趨勢轉弱出場
                    elif last_5m['mom_state'] < 3 or score < 30:
                        log_msg = trader.execute_signal("EXIT", current_price, timestamp)
                
                # 情況 C: 持有空單
                elif trader.position == -1:
                    # 強勢反向信號 (反手)
                    if score >= STRATEGY_CONFIG["entry_score"]:
                        log_msg = trader.execute_signal("EXIT", current_price, timestamp)
                        log_msg += " | " + trader.execute_signal("BUY", current_price, timestamp,
                                                               stop_loss=STRATEGY_CONFIG["stop_loss"])
                    # 一般趨勢轉弱出場
                    elif last_5m['mom_state'] > 0 or score > -30:
                        log_msg = trader.execute_signal("EXIT", current_price, timestamp)

            if log_msg:
                console.print(f"[bold yellow][{timestamp}] {log_msg}[/bold yellow]")
                # Email 通知 (略過，維持原邏輯)
                subject = f"TRADE ALERT: {ticker}"
                send_email_notification(subject, log_msg, f"<h3>Trade Executed: {log_msg}</h3>")
            
            # 顯示
            pos_text = "LONG" if trader.position == 1 else "SHORT" if trader.position == -1 else "EMPTY"
            sl_text = f"SL: {trader.current_stop_loss:.1f}" if trader.current_stop_loss else "SL: None"
            console.print(f"[{datetime.now().strftime('%H:%M:%S')}] Price: {current_price:.1f} | Score: {score:.1f} | {pos_text} ({sl_text})", end="\r")
            
            time.sleep(30 if use_shioaji else 60)

    except KeyboardInterrupt:
        console.print("\n[bold red]Simulation ended.[/bold red]")
    finally:
        trader.save_report()

if __name__ == "__main__":
    run_simulation("^TWII")

import sys
import os
import time
import yaml
from datetime import datetime
import pandas as pd
from rich.console import Console

# 加入 src 到路徑
sys.path.append(os.path.join(os.path.dirname(__file__), "..", "src"))

from squeeze_futures.data.downloader import download_futures_data
from squeeze_futures.data.shioaji_client import ShioajiClient
from squeeze_futures.engine.indicators import calculate_futures_squeeze, calculate_mtf_alignment
from squeeze_futures.engine.simulator import PaperTrader
from squeeze_futures.report.notifier import send_email_notification

console = Console()

def load_config():
    config_path = os.path.join(os.path.dirname(__file__), "..", "config", "trade_config.yaml")
    with open(config_path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)

def check_funds_for_live(shioaji, lots, min_margin_per_lot=25000):
    """實戰前的資金安全校驗 (微台指目前每口約需 23,000，設定 25,000 作為安全門檻)"""
    available = shioaji.get_available_margin()
    required = lots * min_margin_per_lot
    if available < required:
        msg = f"❌ [FUND ALERT] Insufficient Funds! Available: {available:,.0f}, Required: {required:,.0f}"
        console.print(f"[bold red]{msg}[/bold red]")
        send_email_notification("CRITICAL: Insufficient Funds", msg, f"<h2 style='color:red;'>{msg}</h2>")
        return False
    console.print(f"[green]💰 Fund Check Passed. Available Margin: {available:,.0f}[/green]")
    return True

def get_market_status():
    now = datetime.now()
    weekday = now.weekday()
    current_time = now.hour * 100 + now.minute
    is_day = (0 <= weekday <= 4) and (845 <= current_time < 1345)
    is_night = False
    if (0 <= weekday <= 4) and (current_time >= 1500): is_night = True
    if (1 <= weekday <= 5) and (current_time < 500): is_night = True
    is_near_close = (is_day and current_time >= 1340) or (is_night and current_time >= 455)
    return {"open": is_day or is_night, "near_close": is_near_close}

def run_simulation(ticker="TMF"):
    cfg = load_config()
    LIVE_TRADING = cfg['live_trading']
    STRATEGY = cfg['strategy']
    MGMT = cfg['trade_mgmt']
    RISK = cfg['risk_mgmt']

    trader = PaperTrader(ticker=ticker)
    shioaji = ShioajiClient()
    use_shioaji = shioaji.login()
    contract = shioaji.get_futures_contract(ticker) if use_shioaji else None
    
    status_label = "[BOLD RED]!!! LIVE TRADING !!![/BOLD RED]" if LIVE_TRADING else "[CYAN]PAPER TRADING[/CYAN]"
    console.print(f"🚀 Squeeze Trader Started - Mode: {status_label}")
    
    # 盤前顯示餘額
    if use_shioaji:
        available = shioaji.get_available_margin()
        console.print(f"Current Available Margin: [bold yellow]{available:,.0f} TWD[/bold yellow]")

    try:
        while True:
            market = get_market_status()
            if not market["open"]:
                if trader.position != 0: trader.execute_signal("EXIT", trader.entry_price, datetime.now())
                time.sleep(300); continue

            # 1. 抓取數據
            processed_data = {}
            for tf in ["5m", "15m", "1h"]:
                df = shioaji.get_kline(ticker, interval=tf) if use_shioaji else pd.DataFrame()
                if df.empty: df = download_futures_data("^TWII", interval=tf, period="5d")
                if not df.empty: processed_data[tf] = calculate_futures_squeeze(df, bb_length=STRATEGY["length"], kc_length=STRATEGY["length"])
            
            if "5m" not in processed_data: continue
            last_5m = processed_data["5m"].iloc[-1]
            alignment = calculate_mtf_alignment(processed_data, weights=STRATEGY["weights"])
            score, last_price, vwap = alignment['score'], last_5m['Close'], last_5m['vwap']
            timestamp = last_5m.name if hasattr(last_5m, 'name') else datetime.now()
            
            log_msg, real_action = "", None
            
            # --- 2. 風控與出場 ---
            if trader.position != 0:
                trader.update_trailing_stop(last_price)
                stop_msg = trader.check_stop_loss(last_price, timestamp)
                if not stop_msg and RISK["exit_on_vwap"]:
                    if (trader.position > 0 and last_price < vwap) or (trader.position < 0 and last_price > vwap):
                        stop_msg = trader.execute_signal("EXIT", last_price, timestamp)
                        if stop_msg: stop_msg = "[VWAP] " + stop_msg
                if not stop_msg and market["near_close"] and MGMT["force_close_at_end"]:
                    stop_msg = trader.execute_signal("EXIT", last_price, timestamp)
                    if stop_msg: stop_msg = "[EOD] " + stop_msg
                
                if stop_msg:
                    log_msg = stop_msg
                    real_action = "Sell" if trader.position > 0 else "Buy"

            # --- 3. 進場判斷 ---
            if not log_msg:
                can_buy = MGMT["allow_long"] and score >= STRATEGY["entry_score"]
                can_sell = MGMT["allow_short"] and score <= -STRATEGY["entry_score"]
                
                if trader.position == 0 and (not last_5m['sqz_on']):
                    # 進場前檢查資金 (僅在實戰模式啟動時)
                    if can_buy and last_price > vwap and last_5m['mom_state'] == 3:
                        if not LIVE_TRADING or check_funds_for_live(shioaji, MGMT["lots_per_trade"]):
                            log_msg = trader.execute_signal("BUY", last_price, timestamp, lots=MGMT["lots_per_trade"], max_lots=MGMT["max_positions"], stop_loss=RISK["stop_loss_pts"], break_even_trigger=RISK["break_even_pts"])
                            real_action = "Buy"
                    elif can_sell and last_price < vwap and last_5m['mom_state'] == 0:
                        if not LIVE_TRADING or check_funds_for_live(shioaji, MGMT["lots_per_trade"]):
                            log_msg = trader.execute_signal("SELL", last_price, timestamp, lots=MGMT["lots_per_trade"], max_lots=MGMT["max_positions"], stop_loss=RISK["stop_loss_pts"], break_even_trigger=RISK["break_even_pts"])
                            real_action = "Sell"
                
                elif (trader.position > 0 and can_sell) or (trader.position < 0 and can_buy):
                    log_msg = trader.execute_signal("EXIT", last_price, timestamp)
                    real_action = "Sell" if trader.position > 0 else "Buy"

            # --- 🚀 實戰下單執行 ---
            if log_msg:
                console.print(f"[bold yellow][{timestamp}] {log_msg}[/bold yellow]")
                if LIVE_TRADING and real_action and contract:
                    shioaji.place_order(contract, real_action, MGMT["lots_per_trade"])
                send_email_notification(f"{'REAL' if LIVE_TRADING else 'PAPER'} TRADE", log_msg, f"<h3>{log_msg}</h3>")
            
            sl_disp = f"SL: {trader.current_stop_loss:.1f}" if trader.current_stop_loss else "SL: None"
            console.print(f"[{datetime.now().strftime('%H:%M:%S')}] Price: {last_price:.1f} | Score: {score:.1f} | {trader.position} lots ({sl_disp})", end="\r")
            time.sleep(30 if use_shioaji else 60)

    except KeyboardInterrupt: pass
    finally: trader.save_report(); shioaji.logout()

if __name__ == "__main__":
    run_simulation("TMF")

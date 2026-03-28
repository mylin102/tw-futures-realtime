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

def is_market_open():
    """
    判斷目前是否在台指期交易時段 (日盤 + 夜盤)
    """
    now = datetime.now()
    weekday = now.weekday() # 0 is Monday, 6 is Sunday
    
    # 時間計算用分表示 (更精確)
    current_time = now.hour * 100 + now.minute
    
    # A. 日盤時段: 08:45 - 13:45 (週一至週五)
    is_day = (0 <= weekday <= 4) and (845 <= current_time < 1345)
    
    # B. 夜盤時段: 15:00 - 05:00 (次日)
    # 週一 15:00 開始到週六 05:00 結束
    is_night = False
    # 15:00 之後開始 (週一至週五)
    if (0 <= weekday <= 4) and (current_time >= 1500):
        is_night = True
    # 05:00 之前結束 (週二至週六)
    if (1 <= weekday <= 5) and (current_time < 500):
        is_night = True
        
    return is_day or is_night

def run_simulation(ticker="MXFR1"):
    trader = PaperTrader(ticker=ticker)
    shioaji = ShioajiClient()
    use_shioaji = shioaji.login()
    
    console.print(f"[bold green]Starting Daily Simulation for {ticker}...[/bold green]")
    
    try:
        while True:
            if not is_market_open():
                # 如果不在交易時段，且有持倉，則強制平倉 (實務上期貨盤中平倉較安全)
                if trader.position != 0:
                    # 使用最後紀錄價格平倉
                    console.print("\n[bold red]Market closed. Forcing exit position...[/bold red]")
                    # 此處簡化處理，實際建議紀錄最後一筆價格
                    break
                
                console.print(f"[{datetime.now().strftime('%H:%M:%S')}] Market is closed. Resting...", end="\r")
                time.sleep(300) # 沒開盤時每 5 分鐘檢查一次
                continue

            # 1. 抓取多週期數據
            processed_data = {}
            for tf in ["5m", "15m", "1h"]:
                df = shioaji.get_kline(ticker, interval=tf) if use_shioaji else pd.DataFrame()
                if df.empty:
                    df = download_futures_data("^TWII", interval=tf, period="5d") # yfinance 備案
                
                if not df.empty:
                    processed_data[tf] = calculate_futures_squeeze(df)
            
            if "5m" not in processed_data: continue
            
            # 2. 策略邏輯
            last_5m = processed_data["5m"].iloc[-1]
            alignment = calculate_mtf_alignment(processed_data)
            score = alignment['score']
            
            current_price = last_5m['Close']
            timestamp = last_5m.name if hasattr(last_5m, 'name') else datetime.now()
            
            log_msg = ""
            
            # --- 核心交易邏輯 (含反手交易) ---
            
            # 情況 A: 目前空手 (Empty)
            if trader.position == 0:
                if last_5m['fired'] and score > 70 and last_5m['price_vs_vwap'] > 0:
                    log_msg = trader.execute_signal("BUY", current_price, timestamp)
                elif last_5m['fired'] and score < -70 and last_5m['price_vs_vwap'] < 0:
                    log_msg = trader.execute_signal("SELL", current_price, timestamp)
            
            # 情況 B: 持有多單 (Long)
            elif trader.position == 1:
                # 偵測到強勢反向信號 (反手條件)
                if last_5m['fired'] and score < -70:
                    log_msg = trader.execute_signal("EXIT", current_price, timestamp)
                    log_msg += " | " + trader.execute_signal("SELL", current_price, timestamp)
                # 一般出場條件 (動能轉弱或分數轉向)
                elif last_5m['mom_state'] < 3 or score < 20:
                    log_msg = trader.execute_signal("EXIT", current_price, timestamp)
            
            # 情況 C: 持有空單 (Short)
            elif trader.position == -1:
                # 偵測到強勢反向信號 (反手條件)
                if last_5m['fired'] and score > 70:
                    log_msg = trader.execute_signal("EXIT", current_price, timestamp)
                    log_msg += " | " + trader.execute_signal("BUY", current_price, timestamp)
                # 一般出場條件 (動能轉弱或分數轉向)
                elif last_5m['mom_state'] > 0 or score > -20:
                    log_msg = trader.execute_signal("EXIT", current_price, timestamp)

            if log_msg:
                console.print(f"[bold yellow][{timestamp}] {log_msg}[/bold yellow]")
                
                # --- 美化後的即時成交 Email 通知 ---
                action_type = log_msg.split(' ')[0] # BUY, SELL, Exit
                color = "#28a745" if "BUY" in log_msg else "#dc3545" if "SELL" in log_msg else "#007bff"
                bg_color = "#e9f7ef" if "BUY" in log_msg else "#f8d7da" if "SELL" in log_msg else "#e7f3ff"
                
                subject = f"TRADE ALERT: {ticker} - {action_type}"
                body_html = f"""
                <html>
                <body style="font-family: sans-serif;">
                    <div style="border-left: 10px solid {color}; background: {bg_color}; padding: 20px; border-radius: 5px;">
                        <h2 style="color: {color}; margin-top: 0;">Trade Executed: {log_msg}</h2>
                        <p style="font-size: 18px;"><strong>Ticker:</strong> {ticker}</p>
                        <p style="font-size: 24px; color: #333;"><strong>Price:</strong> {current_price:,.1f}</p>
                        <hr style="border: 0; border-top: 1px solid #ddd;">
                        <p><strong>MTF Score:</strong> {score:.1f}</p>
                        <p><strong>Time:</strong> {timestamp}</p>
                        <p><strong>Current Pos:</strong> {"LONG" if trader.position == 1 else "SHORT" if trader.position == -1 else "EMPTY"}</p>
                    </div>
                </body>
                </html>
                """
                send_email_notification(subject, log_msg, body_html)
                # ------------------------------
            
            # 顯示進度
            pos_text = "LONG" if trader.position == 1 else "SHORT" if trader.position == -1 else "EMPTY"
            console.print(f"[{datetime.now().strftime('%H:%M:%S')}] Price: {current_price:.1f} | Score: {score:.1f} | Pos: {pos_text}", end="\r")
            
            # 模擬盤中更新頻率
            time.sleep(30 if use_shioaji else 60)

    except KeyboardInterrupt:
        console.print("\n[bold red]Simulation ended by user.[/bold red]")
    finally:
        report_content = trader.get_performance_report()
        report_html = trader.get_performance_report_html()
        report_path = trader.save_report()
        console.print(f"[bold green]Report saved to: {report_path}[/bold green]")
        
        # 發送 Email
        subject = f"Squeeze Simulation Results - {datetime.now().strftime('%Y-%m-%d')}"
        if send_email_notification(subject, report_content, report_html):
            console.print("[bold cyan]Email notification sent (HTML)![/bold cyan]")
        else:
            console.print("[bold red]Failed to send Email notification.[/bold red]")

if __name__ == "__main__":
    # 使用 ^TWII 代替 MXFR1 進行週末測試 (yfinance 備案)
    run_simulation("^TWII")

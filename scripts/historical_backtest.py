#!/usr/bin/env python3
"""
Historical Backtest for Squeeze Taiwan Futures Logic.
Uses official TAIFEX data resampled to OHLC.
Supports TMF (Micro-TAIEX) and MTX (Mini-TAIEX).
"""

import sys
import os
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import zipfile
import requests
import urllib.request
from pathlib import Path
from rich.console import Console
from rich.progress import Progress

# Add src to path
sys.path.append(os.path.join(os.path.dirname(__file__), "..", "src"))

from squeeze_futures.engine.indicators import calculate_futures_squeeze, calculate_mtf_alignment
from squeeze_futures.engine.simulator import PaperTrader

console = Console()

# --- TAIFEX Download Utils ---

def download_taifex_raw(date_str, target_dir):
    """Download daily rpt from TAIFEX"""
    rpt_name = f'Daily_{date_str.replace("-", "_")}'
    url = f'https://www.taifex.com.tw/file/taifex/Dailydownload/Dailydownload/{rpt_name}.zip'
    
    zip_path = Path(target_dir) / f"{rpt_name}.zip"
    rpt_path = Path(target_dir) / f"{rpt_name}.rpt"
    
    if rpt_path.exists():
        return rpt_path

    try:
        # Check if file exists before downloading
        response = requests.head(url, timeout=5)
        if response.status_code != 200:
            return None
        
        urllib.request.urlretrieve(url, zip_path)
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(target_dir)
        
        if zip_path.exists():
            os.remove(zip_path)
        return rpt_path
    except Exception:
        return None

def load_and_resample(rpt_path, interval="5min", product_code="TMF"):
    """Load TAIFEX rpt and resample to OHLC"""
    try:
        df = pd.read_csv(rpt_path, encoding='big5', low_memory=False)
        df.columns = [c.strip() for c in df.columns]
        
        for col in df.select_dtypes(['object']).columns:
            df[col] = df[col].str.strip()
            
        product_col = '商品代號' if '商品代號' in df.columns else 'Code'
        if product_col not in df.columns:
             # Fallback for unexpected header versions
             df.columns = ['Date', 'Code', 'Expiry', 'Time', 'Price', 'Volume', 'Side1', 'Side2', 'Last'][:len(df.columns)]
             product_col = 'Code'
        
        df_filtered = df[df[product_col] == product_code].copy()
        if df_filtered.empty: return None
        
        date_col = '成交日期' if '成交日期' in df_filtered.columns else ('交易日期' if '交易日期' in df_filtered.columns else 'Date')
        time_col = '成交時間' if '成交時間' in df_filtered.columns else 'Time'
        price_col = '成交價格' if '成交價格' in df_filtered.columns else 'Price'
            
        df_filtered['dt_str'] = df_filtered[date_col].astype(str) + df_filtered[time_col].astype(str).str.zfill(6)
        df_filtered['datetime'] = pd.to_datetime(df_filtered['dt_str'], format='%Y%m%d%H%M%S')
        df_filtered.set_index('datetime', inplace=True)
        
        df_filtered[price_col] = pd.to_numeric(df_filtered[price_col], errors='coerce')
        resampled = df_filtered[price_col].resample(interval).ohlc()
        resampled['Volume'] = df_filtered[price_col].resample(interval).count()
        
        # Standardize for indicators.py
        resampled.columns = ['Open', 'High', 'Low', 'Close', 'Volume']
        return resampled.dropna()
    except Exception:
        return None

# --- Main Backtest Logic ---

def run_historical_backtest(days=60, product="TMF"):
    # 微台指 TMF 1點=10元, 小台指 MX 1點=50元
    point_value = 10 if product == "TMF" else 50
    trader = PaperTrader(ticker=product)
    
    raw_data_dir = Path("data/taifex_raw")
    raw_data_dir.mkdir(parents=True, exist_ok=True)
    
    end_date = datetime.now()
    start_date = end_date - timedelta(days=days)
    
    all_5m, all_15m, all_1h = [], [], []
    
    console.print(f"[bold cyan]🚀 Fetching {product} data for the last {days} days...[/bold cyan]")
    
    curr = start_date
    trade_days_found = 0
    with Progress() as progress:
        task = progress.add_task("[cyan]Downloading...", total=days)
        while curr <= end_date:
            date_str = curr.strftime('%Y-%m-%d')
            if curr.weekday() < 5: 
                rpt = download_taifex_raw(date_str, raw_data_dir)
                if rpt:
                    df5 = load_and_resample(rpt, "5min", product)
                    df15 = load_and_resample(rpt, "15min", product)
                    df1h = load_and_resample(rpt, "1h", product)
                    
                    if df5 is not None:
                        all_5m.append(df5)
                        all_15m.append(df15)
                        all_1h.append(df1h)
                        trade_days_found += 1
            curr += timedelta(days=1)
            progress.update(task, advance=1)
        
    if not all_5m:
        console.print("[bold red]No data found to backtest.[/bold red]")
        return

    # Combine and process
    full_5m = pd.concat(all_5m).sort_index()
    full_15m = pd.concat(all_15m).sort_index()
    full_1h = pd.concat(all_1h).sort_index()
    
    console.print(f"✅ Loaded {trade_days_found} trading days ({len(full_5m)} bars of 5m).")
    console.print(f"[bold green]Running Strategy Simulation...[/bold green]")
    
    processed_5m = calculate_futures_squeeze(full_5m)
    processed_15m = calculate_futures_squeeze(full_15m)
    processed_1h = calculate_futures_squeeze(full_1h)
    
    # Simple loop for MTF alignment
    for i in range(len(processed_5m)):
        current_time = processed_5m.index[i]
        row_5m = processed_5m.iloc[i]
        
        # MTF windowing
        m15 = processed_15m[processed_15m.index <= current_time]
        m1h = processed_1h[processed_1h.index <= current_time]
        if m15.empty or m1h.empty: continue
        
        data_dict = {"5m": processed_5m.iloc[:i+1], "15m": m15, "1h": m1h}
        alignment = calculate_mtf_alignment(data_dict)
        score = alignment['score']
        current_price = row_5m['Close']
        
        # Strategy (Matching SKILL.md)
        if trader.position == 0:
            if row_5m['fired'] and score > 70 and (current_price > row_5m['vwap']):
                trader.execute_signal("BUY", current_price, current_time)
            elif row_5m['fired'] and score < -70 and (current_price < row_5m['vwap']):
                trader.execute_signal("SELL", current_price, current_time)
        elif trader.position == 1:
            if row_5m['fired'] and score < -70:
                trader.execute_signal("EXIT", current_price, current_time)
                trader.execute_signal("SELL", current_price, current_time)
            elif row_5m['mom_state'] < 3 or score < 20:
                trader.execute_signal("EXIT", current_price, current_time)
        elif trader.position == -1:
            if row_5m['fired'] and score > 70:
                trader.execute_signal("EXIT", current_price, current_time)
                trader.execute_signal("BUY", current_price, current_time)
            elif row_5m['mom_state'] > 0 or score > -20:
                trader.execute_signal("EXIT", current_price, current_time)

    # Final report
    console.print("\n" + trader.get_performance_report())
    report_path = trader.save_report()
    console.print(f"[bold green]Backtest report saved to: {report_path}[/bold green]")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=60)
    parser.add_argument("--product", type=str, default="TMF", choices=["TMF", "MTX"])
    args = parser.parse_args()
    
    run_historical_backtest(days=args.days, product=args.product)

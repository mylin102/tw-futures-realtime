#!/usr/bin/env python3
import sys
import os
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from pathlib import Path
from rich.console import Console
from rich.table import Table
import itertools

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "src"))
from squeeze_futures.engine.indicators import calculate_futures_squeeze, calculate_mtf_alignment
from squeeze_futures.engine.simulator import PaperTrader

console = Console()

def load_data(data_dir="data/taifex_raw"):
    from historical_backtest import load_and_resample
    files = sorted(Path(data_dir).glob("Daily_*.rpt"))
    all_5m, all_15m, all_1h = [], [], []
    for f in files:
        d5 = load_and_resample(f, "5min", "TMF")
        d15 = load_and_resample(f, "15min", "TMF")
        d1h = load_and_resample(f, "1h", "TMF")
        if d5 is not None: all_5m.append(d5)
        if d15 is not None: all_15m.append(d15)
        if d1h is not None: all_1h.append(d1h)
    return pd.concat(all_5m).sort_index(), pd.concat(all_15m).sort_index(), pd.concat(all_1h).sort_index()

def run_single_backtest(data_5m, data_15m, data_1h, entry_score, stop_loss, length):
    trader = PaperTrader(ticker="TMF_OPT")
    
    # Calculate with specific length
    p5 = calculate_futures_squeeze(data_5m, bb_length=length, kc_length=length)
    p15 = calculate_futures_squeeze(data_15m, bb_length=length, kc_length=length)
    p1h = calculate_futures_squeeze(data_1h, bb_length=length, kc_length=length)
    
    # New Weights: Favoring short-term
    weights = {"1h": 0.2, "15m": 0.4, "5m": 0.4}
    
    for i in range(len(p5)):
        curr_time = p5.index[i]
        row = p5.iloc[i]
        price = row['Close']
        
        trader.check_stop_loss(price, curr_time)
        
        m15 = p15[p15.index <= curr_time]
        m1h = p1h[p1h.index <= curr_time]
        if m15.empty or m1h.empty: continue
        
        alignment = calculate_mtf_alignment({"5m": p5.iloc[:i+1], "15m": m15, "1h": m1h}, weights=weights)
        score = alignment['score']
        
        # 激進進場邏輯：不強制要求 fired，只要 sqz_on 為 False 且動能極強
        if trader.position == 0:
            # 條件：能量已釋放 OR 釋放瞬間，且共振分數極高
            is_trending = (not row['sqz_on']) and (abs(score) > entry_score)
            if is_trending:
                if score > entry_score and price > row['vwap'] and row['mom_state'] == 3:
                    trader.execute_signal("BUY", price, curr_time, stop_loss=stop_loss)
                elif score < -entry_score and price < row['vwap'] and row['mom_state'] == 0:
                    trader.execute_signal("SELL", price, curr_time, stop_loss=stop_loss)
        
        elif trader.position == 1:
            # 停利/出場：動能轉弱或分數低於閾值
            if row['mom_state'] < 3 or score < 30:
                trader.execute_signal("EXIT", price, curr_time)
        elif trader.position == -1:
            if row['mom_state'] > 0 or score > -30:
                trader.execute_signal("EXIT", price, curr_time)
                
    return {
        "entry": entry_score, "sl": stop_loss, "len": length,
        "pnl": trader.balance - 100000, "trades": len(trader.trades),
        "win_rate": (pd.DataFrame(trader.trades)['pnl_cash'] > 0).mean() * 100 if trader.trades else 0
    }

if __name__ == "__main__":
    console.print("[bold yellow]Loading historical data...[/bold yellow]")
    d5, d15, d1h = load_data()
    
    # Aggressive params sweep
    entry_scores = [50, 60]
    stop_losses = [40, 60]
    lengths = [10, 14, 20]
    
    results = []
    combinations = list(itertools.product(entry_scores, stop_losses, lengths))
    console.print(f"Testing {len(combinations)} parameter combinations...")
    
    for en, sl, le in combinations:
        res = run_single_backtest(d5, d15, d1h, en, sl, le)
        results.append(res)
        console.print(f"  Entry: {en}, SL: {sl}, Len: {le} => PnL: {res['pnl']:+g}, Trades: {res['trades']}", end="\r")

    df_res = pd.DataFrame(results).sort_values("pnl", ascending=False)
    
    table = Table(title="Aggressive Strategy Optimization Results")
    table.add_column("Length", justify="center")
    table.add_column("Entry Score", justify="center")
    table.add_column("Stop Loss", justify="center")
    table.add_column("PnL (TWD)", justify="right", style="bold")
    table.add_column("Trades", justify="center")
    table.add_column("Win Rate", justify="right")
    
    for _, r in df_res.head(15).iterrows():
        color = "green" if r['pnl'] > 0 else "red"
        table.add_row(
            str(r['len']), str(r['entry']), str(r['sl']),
            f"[{color}]{r['pnl']:+,.0f}[/{color}]", str(int(r['trades'])), f"{r['win_rate']:.1f}%"
        )
    console.print("\n", table)

#!/usr/bin/env python3
import sys
import os
import yaml
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from pathlib import Path
from rich.console import Console
from rich.table import Table

# 加入本地路徑
BASE_DIR = "/Users/mylin/Documents/mylin102/squeeze-tw-futures-realtime"
sys.path.append(os.path.join(BASE_DIR, "src"))
sys.path.append(os.path.join(BASE_DIR, "scripts"))

from squeeze_futures.engine.indicators import calculate_futures_squeeze, calculate_mtf_alignment
from historical_backtest import load_and_resample

console = Console()

def run_tmf_engine(p5, p15, p1h, enable_sniper=False):
    balance = 0
    position = 0
    entry_price = 0
    equity_curve = []
    stats = {"trap_fills": 0, "normal_exits": 0}
    weights = {"1h": 0.2, "15m": 0.4, "5m": 0.4}
    
    for i in range(len(p5)):
        row = p5.iloc[i]; price = row['Close']; timestamp = row.name
        
        if position != 0:
            is_trap_win = (enable_sniper and timestamp.hour == 13 and 10 <= timestamp.minute < 30)
            is_panic = (timestamp.hour == 13 and timestamp.minute >= 30) or (not enable_sniper and timestamp.hour == 13 and timestamp.minute >= 25)
            
            filled_price = None
            if is_trap_win:
                # 誘捕價：多單掛高 2 點，空單掛低 2 點
                trap_target = price + 2.0 if position > 0 else price - 2.0
                if (position > 0 and row['High'] >= trap_target) or (position < 0 and row['Low'] <= trap_target):
                    filled_price = trap_target; stats["trap_fills"] += 1
            
            if filled_price is None:
                m15 = p15[p15.index <= timestamp]
                score = calculate_mtf_alignment({"5m": p5.iloc[:i+1], "15m": m15, "1h": p1h[p1h.index <= timestamp]}, weights=weights)['score']
                if is_panic or abs(score) < 20:
                    filled_price = price; stats["normal_exits"] += 1
            
            if filled_price is not None:
                pnl = (filled_price - entry_price) * 10 * position # 1 點 = 10 元
                balance += pnl
                position = 0

        if position == 0:
            m15 = p15[p15.index <= timestamp]
            if not m15.empty:
                score = calculate_mtf_alignment({"5m": p5.iloc[:i+1], "15m": m15, "1h": p1h[p1h.index <= timestamp]}, weights=weights)['score']
                if abs(score) >= 70:
                    position = 2 if score > 0 else -2
                    entry_price = price
                    
        equity_curve.append(balance)
    return balance, equity_curve, stats

def run_test():
    data_dir = os.path.join(BASE_DIR, "data/taifex_raw")
    files = sorted(Path(data_dir).glob("Daily_*.rpt"))
    all_d = [load_and_resample(f, "5min", "TMF") for f in files]
    df5 = pd.concat([d for d in all_d if d is not None]).sort_index()
    def res_cl(df, tf): return df.resample(tf).agg({'Open':'first','High':'max','Low':'min','Close':'last','Volume':'sum'}).dropna()
    p5, p15, p1h = calculate_futures_squeeze(df5, 20), calculate_futures_squeeze(res_cl(df5, '15min'), 20), calculate_futures_squeeze(res_cl(df5, '1h'), 20)

    console.print("[cyan]Testing TMF Standard vs Exit Sniper...[/cyan]")
    pnl_base, eq_base, s_base = run_tmf_engine(p5, p15, p1h, False)
    pnl_snip, eq_snip, s_snip = run_tmf_engine(p5, p15, p1h, True)

    plt.style.use('dark_background'); fig, ax = plt.subplots(figsize=(14, 7))
    ax.step(df5.index, eq_base, color='#AAAAAA', label=f'Baseline (+{pnl_base:,.0f})', alpha=0.6)
    ax.step(df5.index, eq_snip, color='#00FF00', label=f'Exit Sniper Optimized (+{pnl_snip:,.0f})', linewidth=2)
    ax.set_title("TMF Execution Optimization: Exit Sniper PK"); ax.legend(); plt.tight_layout()
    plt.savefig(os.path.join(BASE_DIR, "exports/tmf_execution_pk.png"))
    
    table = Table(title="TMF Execution Strategy Comparison")
    table.add_column("Metric", style="cyan"); table.add_column("Baseline", style="white"); table.add_column("Exit Sniper", style="bold green")
    table.add_row("Total PnL", f"{pnl_base:+,.0f}", f"{pnl_snip:+,.0f}")
    table.add_row("Trap Fills", "-", str(s_snip['trap_fills']))
    console.print(table)
    os.system(f"open {os.path.join(BASE_DIR, 'exports/tmf_execution_pk.png')}")

if __name__ == "__main__":
    run_test()

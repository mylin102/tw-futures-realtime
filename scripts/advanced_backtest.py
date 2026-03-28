#!/usr/bin/env python3
import sys
import os
import yaml
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from datetime import datetime, timedelta
from pathlib import Path
from rich.console import Console
from rich.table import Table

# 加入 src 到路徑
sys.path.append(os.path.join(os.path.dirname(__file__), "..", "src"))
from squeeze_futures.engine.indicators import calculate_futures_squeeze, calculate_mtf_alignment
from squeeze_futures.engine.simulator import PaperTrader
from historical_backtest import load_and_resample

console = Console()

def load_config():
    config_path = Path(__file__).parent.parent / "config" / "trade_config.yaml"
    with open(config_path, 'r') as f:
        return yaml.safe_load(f)

def execute_engine(p5, p15, p1h, strategy_params, mgmt_params, risk_params, use_pb=False):
    """核心回測引擎"""
    trader = PaperTrader(ticker="TMF", initial_balance=100000)
    equity_curve = []
    
    for i in range(len(p5)):
        curr_time = p5.index[i]
        row = p5.iloc[i]
        price, vwap = row['Close'], row['vwap']
        
        if trader.position != 0:
            trader.update_trailing_stop(price)
            if trader.check_stop_loss(price, curr_time): pass
            elif risk_params['exit_on_vwap']:
                if (trader.position > 0 and price < vwap) or (trader.position < 0 and price > vwap):
                    trader.execute_signal("EXIT", price, curr_time)
        
        m15 = p15[p15.index <= curr_time]
        m1h = p1h[p1h.index <= curr_time]
        if not m15.empty and not m1h.empty:
            alignment = calculate_mtf_alignment({"5m": p5.iloc[:i+1], "15m": m15, "1h": m1h}, weights=strategy_params['weights'])
            score = alignment['score']
            
            if trader.position == 0:
                # Squeeze Signal
                sqz_buy = (not row['sqz_on']) and score >= strategy_params['entry_score'] and price > vwap and row['mom_state'] == 3
                sqz_sell = (not row['sqz_on']) and score <= -strategy_params['entry_score'] and price < vwap and row['mom_state'] == 0
                
                # Pullback Signal (Only Long)
                pb_buy = False
                if use_pb:
                    had_recent_high = p5['is_new_high'].iloc[max(0, i-15):i].any()
                    is_pullback = row['in_pullback_zone'] and price > row['Open']
                    if had_recent_high and is_pullback and row['bullish_align']:
                        pb_buy = True

                if (sqz_buy or pb_buy):
                    trader.execute_signal("BUY", price, curr_time, lots=mgmt_params['lots_per_trade'], max_lots=mgmt_params['max_positions'], stop_loss=risk_params['stop_loss_pts'], break_even_trigger=risk_params['break_even_pts'])
                elif sqz_sell:
                    trader.execute_signal("SELL", price, curr_time, lots=mgmt_params['lots_per_trade'], max_lots=mgmt_params['max_positions'], stop_loss=risk_params['stop_loss_pts'], break_even_trigger=risk_params['break_even_pts'])
            
            elif trader.position > 0 and (row['mom_state'] < 2 or score < 20):
                trader.execute_signal("EXIT", price, curr_time)
            elif trader.position < 0 and (row['mom_state'] > 1 or score > -20):
                trader.execute_signal("EXIT", price, curr_time)

        cur_eq = trader.balance + ((price - trader.entry_price) * trader.position * 10 if trader.position != 0 else 0)
        equity_curve.append(cur_eq)
        
    return equity_curve, trader

def run_strategy_pk():
    cfg = load_config()
    raw_data_dir = Path("data/taifex_raw")
    files = sorted(raw_data_dir.glob("Daily_*.rpt"))
    all_5m, all_15m, all_1h = [], [], []
    console.print(f"[bold cyan]📊 Loading historical data for Strategy PK...[/bold cyan]")
    for f in files:
        d5 = load_and_resample(f, "5min", "TMF")
        d15 = load_and_resample(f, "15min", "TMF")
        d1h = load_and_resample(f, "1h", "TMF")
        if d5 is not None:
            all_5m.append(d5); all_15m.append(d15); all_1h.append(d1h)
    
    p5 = calculate_futures_squeeze(pd.concat(all_5m).sort_index(), bb_length=cfg['strategy']['length'])
    p15 = calculate_futures_squeeze(pd.concat(all_15m).sort_index(), bb_length=cfg['strategy']['length'])
    p1h = calculate_futures_squeeze(pd.concat(all_1h).sort_index(), bb_length=cfg['strategy']['length'])

    console.print("[yellow]Running Base Squeeze Strategy...[/yellow]")
    eq_sqz, trader_sqz = execute_engine(p5, p15, p1h, cfg['strategy'], cfg['trade_mgmt'], cfg['risk_mgmt'], use_pb=False)
    
    console.print("[yellow]Running Hybrid Strategy (Squeeze + Pullback)...[/yellow]")
    eq_hybrid, trader_hybrid = execute_engine(p5, p15, p1h, cfg['strategy'], cfg['trade_mgmt'], cfg['risk_mgmt'], use_pb=True)

    table = Table(title="🏆 Strategy PK Results")
    table.add_column("Strategy", style="cyan")
    table.add_column("Net Profit", justify="right", style="bold")
    table.add_column("Trades", justify="center")
    table.add_row("Base Squeeze", f"{trader_sqz.balance-100000:+.0f}", str(len(trader_sqz.trades)))
    table.add_row("Hybrid (Sqz+PB)", f"{trader_hybrid.balance-100000:+.0f}", str(len(trader_hybrid.trades)))
    console.print(table)

    plt.style.use('dark_background')
    fig, ax = plt.subplots(figsize=(15, 8))
    ax.plot(p5.index, eq_sqz, color='#00CCFF', label='Base Squeeze', linewidth=2)
    ax.plot(p5.index, eq_hybrid, color='#00FF00', label='Hybrid (Squeeze + Pullback)', linewidth=2.5)
    ax.axhline(100000, color='white', linestyle=':', alpha=0.5)
    ax.set_title("Equity Curve Comparison: Squeeze vs. Hybrid", fontsize=16)
    ax.legend()
    plt.tight_layout()
    plt.savefig("exports/simulations/strategy_pk.png")
    os.system("open exports/simulations/strategy_pk.png")

if __name__ == "__main__":
    run_strategy_pk()

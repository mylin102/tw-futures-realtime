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

def execute_engine(p5, p15, p1h, strategy_params, mgmt_params, risk_params):
    """核心回測引擎"""
    trader = PaperTrader(ticker="TMF", initial_balance=100000)
    equity_curve = []
    signals = {"buy": [], "sell": [], "exit": []}
    
    for i in range(len(p5)):
        curr_time = p5.index[i]
        row = p5.iloc[i]
        price, vwap = row['Close'], row['vwap']
        
        if trader.position != 0:
            trader.update_trailing_stop(price)
            stop_msg = trader.check_stop_loss(price, curr_time)
            if not stop_msg and risk_params['exit_on_vwap']:
                if (trader.position > 0 and price < vwap) or (trader.position < 0 and price > vwap):
                    stop_msg = trader.execute_signal("EXIT", price, curr_time)
            if stop_msg: signals["exit"].append((curr_time, price))
        
        m15 = p15[p15.index <= curr_time]
        m1h = p1h[p1h.index <= curr_time]
        if not m15.empty and not m1h.empty:
            alignment = calculate_mtf_alignment({"5m": p5.iloc[:i+1], "15m": m15, "1h": m1h}, weights=strategy_params['weights'])
            score = alignment['score']
            
            if trader.position == 0 and (not row['sqz_on']):
                if score >= strategy_params['entry_score'] and price > vwap and row['mom_state'] == 3:
                    trader.execute_signal("BUY", price, curr_time, lots=mgmt_params['lots_per_trade'], max_lots=mgmt_params['max_positions'], stop_loss=risk_params['stop_loss_pts'], break_even_trigger=risk_params['break_even_pts'])
                    signals["buy"].append((curr_time, price))
                elif score <= -strategy_params['entry_score'] and price < vwap and row['mom_state'] == 0:
                    trader.execute_signal("SELL", price, curr_time, lots=mgmt_params['lots_per_trade'], max_lots=mgmt_params['max_positions'], stop_loss=risk_params['stop_loss_pts'], break_even_trigger=risk_params['break_even_pts'])
                    signals["sell"].append((curr_time, price))
            elif trader.position > 0 and (row['mom_state'] < 2 or score < 20):
                if trader.execute_signal("EXIT", price, curr_time): signals["exit"].append((curr_time, price))
            elif trader.position < 0 and (row['mom_state'] > 1 or score > -20):
                if trader.execute_signal("EXIT", price, curr_time): signals["exit"].append((curr_time, price))

        cur_eq = trader.balance + ((price - trader.entry_price) * trader.position * 10 if trader.position != 0 else 0)
        equity_curve.append(cur_eq)
        
    return equity_curve, signals, trader

def run_score_ladder_test(product="TMF"):
    cfg = load_config()
    raw_data_dir = Path("data/taifex_raw")
    files = sorted(raw_data_dir.glob("Daily_*.rpt"))
    all_5m, all_15m, all_1h = [], [], []
    console.print(f"[bold cyan]📊 Loading historical data for Score Ladder Test...[/bold cyan]")
    for f in files:
        d5 = load_and_resample(f, "5min", product)
        d15 = load_and_resample(f, "15min", product)
        d1h = load_and_resample(f, "1h", product)
        if d5 is not None:
            all_5m.append(d5); all_15m.append(d15); all_1h.append(d1h)
    
    full_5m = pd.concat(all_5m).sort_index()
    full_15m = pd.concat(all_15m).sort_index()
    full_1h = pd.concat(all_1h).sort_index()
    p5 = calculate_futures_squeeze(full_5m, bb_length=cfg['strategy']['length'])
    p15 = calculate_futures_squeeze(full_15m, bb_length=cfg['strategy']['length'])
    p1h = calculate_futures_squeeze(full_1h, bb_length=cfg['strategy']['length'])

    scores_to_test = [60, 70, 80]
    colors = ['#FF00FF', '#00CCFF', '#00FF00'] # 粉, 藍, 綠
    results = []

    plt.style.use('dark_background')
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(16, 12), sharex=True, gridspec_kw={'height_ratios': [2, 1.5]})
    
    # Ax1: Price
    ax1.plot(p5.index, p5['Close'], label='Price', color='#FFD700', alpha=0.4, linewidth=1)
    ax1.set_ylim(p5['Close'].min() - 500, p5['Close'].max() + 500)
    
    table = Table(title="📈 Score Ladder Test Results")
    table.add_column("Entry Score", style="cyan")
    table.add_column("Net Profit", justify="right", style="bold")
    table.add_column("Trades", justify="center")

    for i, score_val in enumerate(scores_to_test):
        test_cfg = cfg.copy(); test_cfg['strategy']['entry_score'] = score_val
        eq, sig, trader = execute_engine(p5, p15, p1h, test_cfg['strategy'], test_cfg['trade_mgmt'], test_cfg['risk_mgmt'])
        
        profit = trader.balance - 100000
        table.add_row(str(score_val), f"{profit:+.0f}", str(len(trader.trades)))
        
        # Plot Equity
        ax2.plot(p5.index, eq, color=colors[i], label=f'Score {score_val}', linewidth=2)
        
        # Plot Signals for Best/Current (Score 70)
        if score_val == 70:
            if sig['buy']: ax1.scatter([x[0] for x in sig['buy']], [x[1] for x in sig['buy']], marker='^', color='#00FF00', s=100, zorder=10)
            if sig['sell']: ax1.scatter([x[0] for x in sig['sell']], [x[1] for x in sig['sell']], marker='v', color='#FF3131', s=100, zorder=10)

    console.print(table)
    
    ax2.axhline(100000, color='white', linestyle=':', alpha=0.5)
    ax2.set_ylabel("Equity (TWD)")
    ax2.set_title("Equity PK: Score 60 vs 70 vs 80")
    ax2.legend()
    ax1.set_title("Price Action & Score 70 Signals")

    plt.tight_layout()
    plot_path = "exports/simulations/score_ladder_test.png"
    plt.savefig(plot_path, dpi=150)
    console.print(f"\n[bold green]✅ Ladder test plot saved to: {plot_path}[/bold green]")
    os.system(f"open {plot_path}")

if __name__ == "__main__":
    run_score_ladder_test()

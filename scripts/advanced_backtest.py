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

def run_advanced_backtest(days=60, product="TMF"):
    cfg = load_config()
    trader = PaperTrader(ticker=product, initial_balance=100000)
    
    # 策略與風險參數
    STRATEGY = cfg['strategy']
    MGMT = cfg['trade_mgmt']
    RISK = cfg['risk_mgmt']
    
    # 1. 準備資料
    raw_data_dir = Path("data/taifex_raw")
    files = sorted(raw_data_dir.glob("Daily_*.rpt"))
    all_5m, all_15m, all_1h = [], [], []
    
    console.print(f"[bold cyan]📊 Loading historical data ({product})...[/bold cyan]")
    for f in files:
        d5 = load_and_resample(f, "5min", product)
        d15 = load_and_resample(f, "15min", product)
        d1h = load_and_resample(f, "1h", product)
        if d5 is not None:
            all_5m.append(d5); all_15m.append(d15); all_1h.append(d1h)
            
    if not all_5m:
        console.print("[red]No data found.[/red]"); return

    full_5m = pd.concat(all_5m).sort_index()
    full_15m = pd.concat(all_15m).sort_index()
    full_1h = pd.concat(all_1h).sort_index()
    
    # 2. 計算指標
    p5 = calculate_futures_squeeze(full_5m, bb_length=STRATEGY['length'])
    p15 = calculate_futures_squeeze(full_15m, bb_length=STRATEGY['length'])
    p1h = calculate_futures_squeeze(full_1h, bb_length=STRATEGY['length'])
    
    # 3. 回測模擬循環
    equity_curve = []
    timestamps = []
    positions = []
    signals_buy = []
    signals_sell = []
    signals_exit = []
    
    console.print(f"[bold green]🚀 Running Simulation with YAML Config...[/bold green]")
    
    for i in range(len(p5)):
        curr_time = p5.index[i]
        row = p5.iloc[i]
        price = row['Close']
        vwap = row['vwap']
        
        # --- 風控檢查 ---
        if trader.position != 0:
            trader.update_trailing_stop(price)
            stop_msg = trader.check_stop_loss(price, curr_time)
            if not stop_msg and RISK['exit_on_vwap']:
                if (trader.position > 0 and price < vwap) or (trader.position < 0 and price > vwap):
                    stop_msg = trader.execute_signal("EXIT", price, curr_time)
            if stop_msg: signals_exit.append((curr_time, price))
        
        # --- 策略邏輯 ---
        m15 = p15[p15.index <= curr_time]
        m1h = p1h[p1h.index <= curr_time]
        if not m15.empty and not m1h.empty:
            alignment = calculate_mtf_alignment({"5m": p5.iloc[:i+1], "15m": m15, "1h": m1h}, weights=STRATEGY['weights'])
            score = alignment['score']
            
            if trader.position == 0 and (not row['sqz_on']):
                if score >= STRATEGY['entry_score'] and price > vwap and row['mom_state'] == 3:
                    trader.execute_signal("BUY", price, curr_time, lots=MGMT['lots_per_trade'], max_lots=MGMT['max_positions'], stop_loss=RISK['stop_loss_pts'], break_even_trigger=RISK['break_even_pts'])
                    signals_buy.append((curr_time, price))
                elif score <= -STRATEGY['entry_score'] and price < vwap and row['mom_state'] == 0:
                    trader.execute_signal("SELL", price, curr_time, lots=MGMT['lots_per_trade'], max_lots=MGMT['max_positions'], stop_loss=RISK['stop_loss_pts'], break_even_trigger=RISK['break_even_pts'])
                    signals_sell.append((curr_time, price))
            elif trader.position > 0 and (row['mom_state'] < 2 or score < 20):
                if trader.execute_signal("EXIT", price, curr_time): signals_exit.append((curr_time, price))
            elif trader.position < 0 and (row['mom_state'] > 1 or score > -20):
                if trader.execute_signal("EXIT", price, curr_time): signals_exit.append((curr_time, price))

        # 紀錄資產
        current_equity = trader.balance
        if trader.position != 0:
            # 加入帳面損益 (點數 * 10 * 口數)
            floating_pnl = (price - trader.entry_price) * trader.position * 10
            current_equity += floating_pnl
            
        equity_curve.append(current_equity)
        timestamps.append(curr_time)
        positions.append(trader.position)

    # 4. 績效統計
    total_trades = len(trader.trades)
    final_equity = trader.balance
    net_pnl = final_equity - 100000
    returns = pd.Series(equity_curve).pct_change().dropna()
    sharpe = (returns.mean() / returns.std()) * np.sqrt(252 * 54) if not returns.empty and returns.std() != 0 else 0
    
    # 計算 MDD
    peak = pd.Series(equity_curve).expanding().max()
    drawdown = (pd.Series(equity_curve) - peak) / peak
    mdd = drawdown.min() * 100

    # 5. 輸出報告表格
    table = Table(title=f"📈 Final Backtest Report - {product}")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="bold")
    table.add_row("Initial Capital", "100,000 TWD")
    table.add_row("Final Capital", f"{final_equity:,.0f} TWD")
    table.add_row("Net Profit/Loss", f"{net_pnl:+.0f} TWD ({ (net_pnl/1000):.1f}%)")
    table.add_row("Total Trades", str(total_trades))
    table.add_row("Max Drawdown", f"{mdd:.2f}%")
    table.add_row("Sharpe Ratio", f"{sharpe:.2f}")
    console.print(table)

    # 6. 繪製圖表
    plt.style.use('dark_background')
    fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(15, 12), sharex=True, gridspec_kw={'height_ratios': [3, 1, 1]})
    
    # Ax1: Price and Signals
    ax1.plot(timestamps, p5['Close'], label='Price', color='gray', alpha=0.5)
    if signals_buy: ax1.scatter([x[0] for x in signals_buy], [x[1] for x in signals_buy], marker='^', color='lime', label='BUY', s=100, zorder=5)
    if signals_sell: ax1.scatter([x[0] for x in signals_sell], [x[1] for x in signals_sell], marker='v', color='red', label='SELL', s=100, zorder=5)
    if signals_exit: ax1.scatter([x[0] for x in signals_exit], [x[1] for x in signals_exit], marker='x', color='yellow', label='EXIT', s=80, zorder=5)
    ax1.set_title(f"{product} Squeeze Strategy Backtest")
    ax1.legend()
    
    # Ax2: Equity Curve
    ax2.plot(timestamps, equity_curve, color='cyan', label='Equity Curve')
    ax2.fill_between(timestamps, 100000, equity_curve, color='cyan', alpha=0.1)
    ax2.set_ylabel("Balance (TWD)")
    ax2.legend()
    
    # Ax3: Positions
    ax3.fill_between(timestamps, 0, positions, color='orange', alpha=0.5, label='Position (Lots)')
    ax3.set_ylabel("Lots")
    ax3.legend()
    
    plt.tight_layout()
    report_img = "exports/simulations/backtest_plot.png"
    plt.savefig(report_img)
    console.print(f"\n[bold green]✅ Full report image saved to: {report_img}[/bold green]")
    
    # 儲存詳細交易日誌
    report_path = trader.save_report()
    console.print(f"[bold green]✅ Detailed trade log saved to: {report_path}[/bold green]")

if __name__ == "__main__":
    run_advanced_backtest(days=60, product="TMF")

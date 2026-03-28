#!/usr/bin/env python3
import sys
import os
import yaml
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from datetime import datetime
from pathlib import Path
from rich.console import Console
from rich.progress import Progress
import itertools
import io
import base64
from jinja2 import Template

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "src"))
from squeeze_futures.engine.indicators import calculate_futures_squeeze, calculate_mtf_alignment
from squeeze_futures.engine.simulator import PaperTrader
from historical_backtest import load_and_resample

console = Console()

def plot_to_base64(fig):
    buf = io.BytesIO()
    fig.savefig(buf, format='png', bbox_inches='tight', dpi=100)
    return base64.b64encode(buf.getvalue()).decode('utf-8')

def execute_backtest_full(p5, p15, p1h, length, score_thresh, regime, sl_pts, force_close, cfg_base):
    """執行完整回測，包含收盤清倉邏輯判斷"""
    trader = PaperTrader(ticker="TMF", initial_balance=100000)
    equity_curve = []
    weights = cfg_base['strategy']['weights']
    pb_cfg = cfg_base['strategy']['pullback']
    risk_cfg = cfg_base['risk_mgmt']
    
    for i in range(len(p5)):
        curr_time = p5.index[i]
        row = p5.iloc[i]
        price, vwap = row['Close'], row['vwap']
        
        # --- 1. 風控與收盤檢查 ---
        if trader.position != 0:
            trader.update_trailing_stop(price)
            stop_msg = trader.check_stop_loss(price, curr_time)
            
            # 收盤強制平倉判斷
            if not stop_msg and force_close:
                hhmm = curr_time.hour * 100 + curr_time.minute
                # 日盤 13:40 後, 夜盤 04:55 後清倉
                if (1340 <= hhmm < 1500) or (455 <= hhmm < 845):
                    trader.execute_signal("EXIT", price, curr_time)
                    stop_msg = True
            
            if not stop_msg and risk_cfg['exit_on_vwap']:
                if (trader.position > 0 and price < vwap) or (trader.position < 0 and price > vwap):
                    trader.execute_signal("EXIT", price, curr_time)
        
        # --- 2. 進場判定 ---
        m15 = p15[p15.index <= curr_time]
        m1h = p1h[p1h.index <= curr_time]
        if m15.empty or m1h.empty: 
            equity_curve.append(trader.balance)
            continue
            
        alignment = calculate_mtf_alignment({"5m": p5.iloc[:i+1], "15m": m15, "1h": m1h}, weights=weights)
        score = alignment['score']
        
        can_long, can_short = True, True
        if regime == "macro":
            can_long = (m1h.iloc[-1]['Close'] > m1h.iloc[-1]['ema_macro'])
            can_short = (m1h.iloc[-1]['Close'] < m1h.iloc[-1]['ema_macro'])
        elif regime == "mid":
            can_long = (m15.iloc[-1]['Close'] > m15.iloc[-1]['ema_filter'])
            can_short = (m15.iloc[-1]['Close'] < m15.iloc[-1]['ema_filter'])

        if trader.position == 0:
            if not row['sqz_on']:
                if score >= score_thresh and price > vwap and row['mom_state'] == 3 and can_long:
                    trader.execute_signal("BUY", price, curr_time, stop_loss=sl_pts, break_even_trigger=sl_pts)
                elif score <= -score_thresh and price < vwap and row['mom_state'] == 0 and can_short:
                    trader.execute_signal("SELL", price, curr_time, stop_loss=sl_pts, break_even_trigger=sl_pts)
            
            if trader.position == 0:
                lb = pb_cfg.get('lookback', 60) // 5
                if p5['is_new_high'].iloc[max(0, i-lb):i].any() and row['in_bull_pb_zone'] and price > row['Open'] and row['bullish_align'] and can_long:
                    trader.execute_signal("BUY", price, curr_time, stop_loss=sl_pts, break_even_trigger=sl_pts)
                elif p5['is_new_low'].iloc[max(0, i-lb):i].any() and row['in_bear_pb_zone'] and price < row['Open'] and row['bearish_align'] and can_short:
                    trader.execute_signal("SELL", price, curr_time, stop_loss=sl_pts, break_even_trigger=sl_pts)
        
        elif trader.position > 0 and (row['mom_state'] < 2 or score < 20):
            trader.execute_signal("EXIT", price, curr_time)
        elif trader.position < 0 and (row['mom_state'] > 1 or score > -20):
            trader.execute_signal("EXIT", price, curr_time)

        cur_eq = trader.balance + ((price - trader.entry_price) * trader.position * 10 if trader.position != 0 else 0)
        equity_curve.append(cur_eq)
        
    return trader, equity_curve

def run_backtest_and_report():
    cfg = yaml.safe_load(open("config/trade_config.yaml"))
    console.print("[bold yellow]🚀 Running Overnight vs. Day-Trade Comparison...[/bold yellow]")
    
    files = sorted(Path("data/taifex_raw").glob("Daily_*.rpt"))
    all_d = [load_and_resample(f, "5min", "TMF") for f in files]
    all_d15 = [load_and_resample(f, "15min", "TMF") for f in files]
    all_d1h = [load_and_resample(f, "1h", "TMF") for f in files]
    df5, df15, df1h = pd.concat([d for d in all_d if d is not None]), pd.concat([d for d in all_d15 if d is not None]), pd.concat([d for d in all_d1h if d is not None])

    # 1. 執行對照測試 (使用目前最佳參數)
    # best: Len 20, Score 70, Regime mid, SL 30
    best_p = {"len": 20, "score": 70, "regime": "mid", "sl": 30}
    
    p5 = calculate_futures_squeeze(df5, bb_length=best_p['len'])
    p15 = calculate_futures_squeeze(df15, bb_length=best_p['len'])
    p1h = calculate_futures_squeeze(df1h, bb_length=best_p['len'])

    console.print("Testing Swing Mode (Allow Overnight)...")
    t_swing, eq_swing = execute_backtest_full(p5, p15, p1h, best_p['len'], best_p['score'], best_p['regime'], best_p['sl'], False, cfg)
    
    console.print("Testing Day-Trade Mode (Force Close)...")
    t_day, eq_day = execute_backtest_full(p5, p15, p1h, best_p['len'], best_p['score'], best_p['regime'], best_p['sl'], True, cfg)

    # 2. 繪圖
    plt.style.use('dark_background')
    fig, ax = plt.subplots(figsize=(15, 7))
    ax.plot(df5.index, eq_swing, color='#00FF00', label='Swing (Allow Overnight)', linewidth=2.5)
    ax.plot(df5.index, eq_day, color='#FF00FF', label='Day-Trade (Force Close)', linewidth=2)
    ax.axhline(100000, color='white', linestyle='--', alpha=0.5)
    ax.set_title("Equity Comparison: Day-Trade vs. Swing Mode", fontsize=16)
    ax.legend(); img_base64 = plot_to_base64(fig)

    # 3. HTML Template (精簡版更新)
    html_template = """
    <!DOCTYPE html>
    <html>
    <head><title>Hold-over Comparison Report</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <style>body { background:#121212; color:#eee; } .card { background:#1e1e1e; border:1px solid #333; margin:20px 0; }</style>
    </head>
    <body>
        <div class="container py-5">
            <h1 class="text-center mb-4">🌙 Day-Trade vs. Swing Comparison</h1>
            <div class="row">
                <div class="col-md-6">
                    <div class="card p-4 text-center">
                        <h4>Swing (Overnight)</h4>
                        <h2 class="text-success">+{{ "{:,.0f}".format(pnl_swing) }} TWD</h2>
                        <p>Trades: {{ t_swing }}</p>
                    </div>
                </div>
                <div class="col-md-6">
                    <div class="card p-4 text-center">
                        <h4>Day-Trade (Exit EOD)</h4>
                        <h2 class="text-info">+{{ "{:,.0f}".format(pnl_day) }} TWD</h2>
                        <p>Trades: {{ t_day }}</p>
                    </div>
                </div>
            </div>
            <div class="card p-3"><img src="data:image/png;base64,{{img}}" class="img-fluid"></div>
        </div>
    </body>
    </html>
    """
    t = Template(html_template)
    with open("HOLDING_COMPARISON.html", "w", encoding='utf-8') as f:
        f.write(t.render(pnl_swing=t_swing.balance-100000, pnl_day=t_day.balance-100000, t_swing=len(t_swing.trades), t_day=len(t_day.trades), img=img_base64))
    
    console.print("\n[bold green]✅ Comparison Report generated: HOLDING_COMPARISON.html[/bold green]")
    os.system("open HOLDING_COMPARISON.html")

if __name__ == "__main__":
    run_backtest_and_report()

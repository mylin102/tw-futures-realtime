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
    """將 matplotlib 圖表轉為 base64 字串"""
    buf = io.BytesIO()
    fig.savefig(buf, format='png', bbox_inches='tight', dpi=100)
    return base64.b64encode(buf.getvalue()).decode('utf-8')

def execute_backtest_full(p5, p15, p1h, length, score_thresh, regime, sl_pts, cfg_base):
    """執行完整回測並回傳資產曲線"""
    trader = PaperTrader(ticker="TMF", initial_balance=100000)
    equity_curve = []
    weights = cfg_base['strategy']['weights']
    pb_cfg = cfg_base['strategy']['pullback']
    risk_cfg = cfg_base['risk_mgmt']
    
    for i in range(len(p5)):
        curr_time = p5.index[i]
        row = p5.iloc[i]
        price, vwap = row['Close'], row['vwap']
        if trader.position != 0:
            trader.update_trailing_stop(price)
            if not trader.check_stop_loss(price, curr_time) and risk_cfg['exit_on_vwap']:
                if (trader.position > 0 and price < vwap) or (trader.position < 0 and price > vwap):
                    trader.execute_signal("EXIT", price, curr_time)
        
        row_15m = p15[p15.index <= curr_time].iloc[-1]
        row_1h = p1h[p1h.index <= curr_time].iloc[-1]
        alignment = calculate_mtf_alignment({"5m": p5.iloc[:i+1], "15m": p15[p15.index <= curr_time], "1h": p1h[p1h.index <= curr_time]}, weights=weights)
        score = alignment['score']
        
        can_long, can_short = True, True
        if regime == "macro":
            can_long = (row_1h['Close'] > row_1h['ema_macro'])
            can_short = (row_1h['Close'] < row_1h['ema_macro'])
        elif regime == "mid":
            can_long = (row_15m['Close'] > row_15m['ema_filter'])
            can_short = (row_15m['Close'] < row_15m['ema_filter'])

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
    console.print("[bold yellow]🚀 Generating Professional HTML Backtest Report...[/bold yellow]")
    
    files = sorted(Path("data/taifex_raw").glob("Daily_*.rpt"))
    all_d = [load_and_resample(f, "5min", "TMF") for f in files]
    all_d15 = [load_and_resample(f, "15min", "TMF") for f in files]
    all_d1h = [load_and_resample(f, "1h", "TMF") for f in files]
    df5, df15, df1h = pd.concat([d for d in all_d if d is not None]), pd.concat([d for d in all_d15 if d is not None]), pd.concat([d for d in all_d1h if d is not None])

    lengths, scores, regimes, sls = [10, 14, 20], [60, 70, 80], ["none", "mid", "macro"], [30, 40, 50]
    combos = list(itertools.product(lengths, scores, regimes, sls))
    results = []
    top_equity_curves = {}

    with Progress() as progress:
        task = progress.add_task("[cyan]Testing 81 Combinations...", total=len(combos))
        for length in lengths:
            p5 = calculate_futures_squeeze(df5, bb_length=length)
            p15 = calculate_futures_squeeze(df15, bb_length=length)
            p1h = calculate_futures_squeeze(df1h, bb_length=length)
            for score, regime, sl in [c[1:] for c in combos if c[0] == length]:
                t, eq = execute_backtest_full(p5, p15, p1h, length, score, regime, sl, cfg)
                pnl = t.balance - 100000
                results.append({"Len": length, "Score": score, "Regime": regime, "SL": sl, "PnL": pnl, "Trades": len(t.trades)})
                top_equity_curves[f"L{length}_S{score}_{regime}_SL{sl}"] = (pnl, eq)
                progress.update(task, advance=1)

    df_res = pd.DataFrame(results).sort_values("PnL", ascending=False)
    
    # --- 繪製圖表 ---
    plt.style.use('dark_background')
    
    # 1. 敏感度分析 (Sensitivity)
    fig_sens, axes = plt.subplots(1, 3, figsize=(18, 5))
    df_res.groupby('Regime')['PnL'].mean().plot(kind='bar', ax=axes[0], color='#00FF00', title='Avg PnL by Regime')
    df_res.groupby('Len')['PnL'].mean().plot(kind='bar', ax=axes[1], color='#00CCFF', title='Avg PnL by Length')
    df_res.groupby('SL')['PnL'].mean().plot(kind='bar', ax=axes[2], color='#FF00FF', title='Avg PnL by StopLoss')
    img_sens = plot_to_base64(fig_sens)

    # 2. 前三名 Equity PK
    fig_pk, ax_pk = plt.subplots(figsize=(15, 7))
    for i, (key, val) in enumerate(list(sorted(top_equity_curves.items(), key=lambda x: x[1][0], reverse=True))[:3]):
        ax_pk.plot(df5.index, val[1], label=f"Rank {i+1}: {key}", linewidth=2)
    ax_pk.axhline(100000, color='white', linestyle='--', alpha=0.5)
    ax_pk.set_title("Top 3 Strategy Equity Curves PK")
    ax_pk.legend(); img_pk = plot_to_base64(fig_pk)

    # --- HTML Template ---
    html_template = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Squeeze Strategy Optimization Report</title>
        <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
        <style>
            body { background-color: #121212; color: #e0e0e0; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; }
            .card { background-color: #1e1e1e; border: 1px solid #333; margin-bottom: 20px; }
            .best-params { font-size: 1.5rem; font-weight: bold; color: #00FF00; }
            table { color: #e0e0e0 !important; }
            .header-box { padding: 40px 0; background: linear-gradient(135deg, #1a237e 0%, #000000 100%); margin-bottom: 30px; }
        </style>
    </head>
    <body>
        <div class="header-box text-center">
            <h1>📊 Squeeze Taiwan Futures Optimization Report</h1>
            <p>Backtest Period: Last 60 Days | TMF (Micro-TAIEX)</p>
        </div>
        <div class="container">
            <div class="row">
                <div class="col-md-4">
                    <div class="card p-4 text-center">
                        <h3>🏆 Recommended Set</h3>
                        <p class="best-params">Len: {{best.Len}} | Score: {{best.Score}}<br>Regime: {{best.Regime}} | SL: {{best.SL}}</p>
                        <h2 class="text-success">+{{ "{:,.0f}".format(best.PnL) }} TWD</h2>
                    </div>
                </div>
                <div class="col-md-8">
                    <div class="card p-3">
                        <h4>🔍 Parameter Sensitivity (Avg PnL)</h4>
                        <img src="data:image/png;base64,{{img_sens}}" class="img-fluid">
                    </div>
                </div>
            </div>
            <div class="card p-3">
                <h4>🚀 Top 3 Strategy Performance (Equity Curves)</h4>
                <img src="data:image/png;base64,{{img_pk}}" class="img-fluid">
            </div>
            <div class="card p-3">
                <h4>📋 Full Results (Top 20)</h4>
                <table class="table table-dark table-striped table-hover">
                    <thead><tr><th>Rank</th><th>Len</th><th>Score</th><th>Regime</th><th>SL</th><th>PnL (TWD)</th><th>Trades</th></tr></thead>
                    <tbody>
                        {% for idx, row in df_top.iterrows() %}
                        <tr><td>{{ loop.index }}</td><td>{{row.Len}}</td><td>{{row.Score}}</td><td>{{row.Regime}}</td><td>{{row.SL}}</td><td class="text-success">+{{ "{:,.0f}".format(row.PnL) }}</td><td>{{row.Trades}}</td></tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
        </div>
    </body>
    </html>
    """
    
    t = Template(html_template)
    final_html = t.render(best=df_res.iloc[0], df_top=df_res.head(20), img_sens=img_sens, img_pk=img_pk)
    
    with open("STRATEGY_REPORT.html", "w", encoding='utf-8') as f:
        f.write(final_html)
    
    console.print(f"\n[bold green]✅ Professional HTML report generated: STRATEGY_REPORT.html[/bold green]")
    os.system("open STRATEGY_REPORT.html")

if __name__ == "__main__":
    run_backtest_and_report()

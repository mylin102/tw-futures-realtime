import sys
import os
import time
import yaml
from datetime import datetime
import pandas as pd
from rich.console import Console

# Add src to path for local development
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from squeeze_futures.data.downloader import download_futures_data
from squeeze_futures.data.shioaji_client import ShioajiClient
from squeeze_futures.engine.constants import get_point_value
from squeeze_futures.engine.simulator import PaperTrader
from squeeze_futures.engine.indicators import calculate_futures_squeeze, calculate_mtf_alignment, calculate_atr
from squeeze_futures.report.notifier import send_email_notification
from squeeze_futures.data.data_storage import save_kbar, save_trade, get_storage

console = Console()

# 初始化數據儲存
data_storage = get_storage("TMF")



# ========== 趨勢突破策略整合 ==========

def check_trend_breakout_signal(df_5m: pd.DataFrame, df_15m: pd.DataFrame) -> dict:
    from squeeze_futures.engine.trend_breakout import check_trend_breakout
    
    result = {'trend_long': False, 'trend_short': False, 'reasons': []}
    
    if len(df_5m) >= 20:
        breakout_5m = check_trend_breakout(df_5m, lookback=20, ma_length=20, compare_bars=5, slope_threshold=0.1)
        
        if breakout_5m['long_signal']:
            result['trend_long'] = True
            result['reasons'].extend([f"5m: {r}" for r in breakout_5m['long_reasons']])
        
        if breakout_5m['short_signal']:
            result['trend_short'] = True
            result['reasons'].extend([f"5m: {r}" for r in breakout_5m['short_reasons']])
    
    return result

def load_config():
    config_path = os.path.join(os.path.dirname(__file__), "..", "config", "trade_config.yaml")
    with open(config_path, 'r', encoding='utf-8') as f: return yaml.safe_load(f)

def save_bar_data(row, score, regime_desc, ticker):
    """將每一棒的指標狀態存入 CSV"""
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    log_dir = os.path.join(base_dir, "logs", "market_data")
    os.makedirs(log_dir, exist_ok=True)
    date_str = datetime.now().strftime("%Y%m%d")
    file_path = os.path.join(log_dir, f"{ticker}_{date_str}_indicators.csv")
    data = {
        "timestamp": [row.name], "close": [row['Close']], "vwap": [row['vwap']], "score": [score],
        "sqz_on": [row['sqz_on']], "mom_state": [row['mom_state']], "regime": [regime_desc],
        "bull_align": [row['bullish_align']], "bear_align": [row['bearish_align']],
        "in_pb_zone": [row['in_bull_pb_zone'] or row['in_bear_pb_zone']]
    }
    df = pd.DataFrame(data)
    header = not os.path.exists(file_path)
    df.to_csv(file_path, mode='a', index=False, header=header)

def check_funds_for_live(shioaji, lots, min_margin_per_lot=25000):
    available = shioaji.get_available_margin()
    required = lots * min_margin_per_lot
    if available < required:
        msg = f"❌ [FUND ALERT] Insufficient Funds! Required: {required:,.0f}"
        console.print(f"[bold red]{msg}[/bold red]")
        send_email_notification("CRITICAL: Insufficient Funds", msg, f"<h2 style='color:red;'>{msg}</h2>")
        return False
    return True

def get_market_status():
    now = datetime.now()
    weekday, current_time = now.weekday(), now.hour * 100 + now.minute
    is_day = (0 <= weekday <= 4) and (845 <= current_time < 1345)
    is_night = ((0 <= weekday <= 4) and (current_time >= 1500)) or ((1 <= weekday <= 5) and (current_time < 500))
    is_near_close = (is_day and current_time >= 1340) or (is_night and current_time >= 455)
    return {"open": is_day or is_night, "near_close": is_near_close}

def run_simulation(ticker="TMF"):
    cfg = load_config()
    LIVE_TRADING, STRATEGY, MGMT, RISK = cfg['live_trading'], cfg['strategy'], cfg['trade_mgmt'], cfg['risk_mgmt']
    EXEC = cfg.get('execution', {})  # 執行與成本模型
    MONITOR = cfg.get('monitoring', {})  # 監控設定
    PB, TP = STRATEGY.get('pullback', {}), STRATEGY.get('partial_exit', {})
    FILTER_MODE = STRATEGY.get('regime_filter', 'mid')

    # ATR 動態停損參數
    # atr_multiplier > 0 → 使用 ATR 動態停損
    # atr_multiplier = 0 → 使用固定停損 (stop_loss_pts)
    ATR_MULT = RISK.get('atr_multiplier', 0.0)
    ATR_LENGTH = RISK.get('atr_length', 14)

    # 預處理 Pullback 參數
    PB_ARGS = {
        'ema_fast': PB.get('ema_fast', 20),
        'ema_slow': PB.get('ema_slow', 60),
        'lookback': PB.get('lookback', 60),
        'pb_buffer': PB.get('buffer', 1.002)
    }

    # 從配置文件讀取交易成本參數
    INITIAL_BALANCE = EXEC.get('initial_balance', 100000)
    FEE_PER_SIDE = EXEC.get('broker_fee_per_side', 20)
    EXCHANGE_FEE = EXEC.get('exchange_fee_per_side', 0)
    TAX_RATE = EXEC.get('tax_rate', 0.0)

    # 從配置文件讀取監控設定
    POLL_INTERVAL = MONITOR.get('poll_interval_secs', 30)
    PB_CONFIRM_BARS = MONITOR.get('pb_confirmation_bars', 12)

    trader = PaperTrader(
        ticker=ticker,
        initial_balance=INITIAL_BALANCE,
        point_value=get_point_value(ticker),
        fee_per_side=FEE_PER_SIDE,
        exchange_fee_per_side=EXCHANGE_FEE,
        tax_rate=TAX_RATE
    )
    shioaji = ShioajiClient()
    shioaji.login()
    contract = shioaji.get_futures_contract(ticker)
    live_ready = LIVE_TRADING and shioaji.is_logged_in and contract is not None
    if LIVE_TRADING and not live_ready:
        console.print("[bold yellow]LIVE requested, but broker session/contract is unavailable. Falling back to PAPER.[/bold yellow]")

    console.print(f"🚀 Squeeze Trader Started - Mode: {'LIVE' if live_ready else 'PAPER'}")
    
    has_tp1_hit = False
    last_processed_bar = None

    def execute_trade(signal: str, price: float, ts, lots: int, *, stop_loss=None, break_even_trigger=None):
        """
        執行交易並發送通知（僅 LIVE 模式）
        """
        action = None
        if signal == "BUY":
            action = "Buy"
        elif signal == "SELL":
            action = "Sell"
        elif signal in {"EXIT", "PARTIAL_EXIT"}:
            if trader.position == 0:
                return None
            action = "Sell" if trader.position > 0 else "Buy"

        if live_ready and action is not None:
            trade = shioaji.place_order(contract, action=action, quantity=lots)
            if trade is None:
                console.print(f"[bold red][{ts}] Live order failed: {signal} {lots}[/bold red]")
                return None

        # 記錄交易到儲存系統
        save_trade({
            'type': signal,
            'timestamp': ts,
            'price': price,
            'lots': lots,
        })
        
        result = trader.execute_signal(
            signal,
            price,
            ts,
            lots=lots,
            max_lots=MGMT["max_positions"],
            stop_loss=stop_loss,
            break_even_trigger=break_even_trigger,
        )
        
        # 🚀 發送交易通知（僅 LIVE 模式）
        if live_ready and result:
            direction = "🟢 BUY" if signal == "BUY" else "🔴 SELL" if signal == "SELL" else "⚪ EXIT"
            pnl_text = ""
            if "PnL" in result:
                pnl_text = f"PnL: {result.split('PnL: ')[-1]}"
            
            html_body = f"""<html><body style="font-family: Arial, sans-serif;">
                <div style="padding: 20px; background: #f5f5f5;">
                    <div style="max-width: 600px; margin: 0 auto; background: white; border-radius: 10px; padding: 20px;">
                        <h2 style="color: #1a1a2e;">{direction}</h2>
                        <table style="width: 100%; border-collapse: collapse;">
                            <tr><td style="padding: 8px 0; color: #666;">Time</td><td>{ts.strftime('%Y-%m-%d %H:%M:%S')}</td></tr>
                            <tr><td style="padding: 8px 0; color: #666;">Ticker</td><td>{ticker}</td></tr>
                            <tr><td style="padding: 8px 0; color: #666;">Price</td><td>{price:.0f}</td></tr>
                            <tr><td style="padding: 8px 0; color: #666;">Lots</td><td>{lots}</td></tr>
                            {f'<tr><td style="padding: 8px 0; color: #666;">{pnl_text}</td><td></td></tr>' if pnl_text else ''}
                        </table>
                        <div style="margin-top: 20px; padding: 10px; background: #e8f4fd; border-radius: 5px; font-size: 12px; color: #666;">
                            Squeeze Futures Auto-Trader
                        </div>
                    </div>
                </div>
            </body></html>"""
            
            send_email_notification(
                subject=f"[TW Futures] {signal} {ticker} @ {price:.0f}",
                body_text=f"{signal} {ticker} {lots} lots @ {price:.0f}. {pnl_text}",
                body_html=html_body
            )
            console.print(f"[dim]✉️  Trade notification sent[/dim]")
        
        return result

    def check_stop_loss(ts, market_price: float):
        if trader.position > 0 and trader.current_stop_loss and market_price <= trader.current_stop_loss:
            return execute_trade("EXIT", trader.current_stop_loss, ts, abs(trader.position))
        if trader.position < 0 and trader.current_stop_loss and market_price >= trader.current_stop_loss:
            return execute_trade("EXIT", trader.current_stop_loss, ts, abs(trader.position))
        return None

    def _send_daily_report(trader, ticker, live_mode):
        """
        生成並發送每日交易報告（HTML 格式，含權益曲線）
        """
        import json
        from datetime import datetime
        
        trades = trader.trades
        pnl = trader.balance - 100000
        
        # 計算交易統計
        winning = len([t for t in trades if t['pnl_cash'] > 0])
        losing = len([t for t in trades if t['pnl_cash'] < 0])
        win_rate = (winning / len(trades) * 100) if trades else 0
        
        gross_profit = sum(t['pnl_cash'] for t in trades if t['pnl_cash'] > 0)
        gross_loss = abs(sum(t['pnl_cash'] for t in trades if t['pnl_cash'] < 0))
        profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else float('inf')
        
        total_cost = sum(t.get('total_cost', 0) for t in trades)
        
        # 生成權益曲線數據
        cumulative = 100000
        equity_data = [{'x': 0, 'y': cumulative}]
        for i, trade in enumerate(trades, 1):
            cumulative += trade['pnl_cash']
            equity_data.append({'x': i, 'y': cumulative})
        
        # 交易明細表格
        trades_html = ""
        for t in trades[-20:]:  # 最近 20 筆
            pnl_class = "profit" if t['pnl_cash'] > 0 else "loss"
            pnl_sign = "+" if t['pnl_cash'] > 0 else ""
            time_str = t['entry_time'].strftime('%m/%d %H:%M') if isinstance(t['entry_time'], datetime) else str(t['entry_time'])
            trades_html += f"""<tr>
                <td>{time_str}</td>
                <td><span class="side {t['direction'].lower()}">{t['direction']}</span></td>
                <td>{t['entry_price']:.0f}</td>
                <td>{t['exit_price']:.0f}</td>
                <td>{t['lots']}</td>
                <td class="{pnl_class}">{pnl_sign}{t['pnl_cash']:,.0f}</td>
            </tr>"""
        
        html_body = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 0; padding: 20px; background: #f5f5f5; }}
        .container {{ max-width: 900px; margin: 0 auto; background: white; border-radius: 10px; padding: 30px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }}
        h1 {{ color: #1a1a2e; margin-bottom: 10px; }}
        .subtitle {{ color: #666; margin-bottom: 30px; }}
        .metrics {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 20px; margin: 30px 0; }}
        .metric-box {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 20px; border-radius: 10px; text-align: center; }}
        .metric-box.profit {{ background: linear-gradient(135deg, #11998e 0%, #38ef7d 100%); }}
        .metric-box.loss {{ background: linear-gradient(135deg, #eb3349 0%, #f45c43 100%); }}
        .metric-value {{ font-size: 2em; font-weight: bold; margin-bottom: 5px; }}
        .metric-label {{ font-size: 0.9em; opacity: 0.9; }}
        .chart-container {{ position: relative; height: 350px; margin: 30px 0; }}
        table {{ width: 100%; border-collapse: collapse; margin: 30px 0; }}
        th {{ background: #1a1a2e; color: white; padding: 12px; text-align: left; }}
        td {{ padding: 10px; border-bottom: 1px solid #eee; }}
        tr:hover {{ background: #f8f9fa; }}
        .profit {{ color: #11998e; font-weight: bold; }}
        .loss {{ color: #eb3349; font-weight: bold; }}
        .side {{ padding: 4px 8px; border-radius: 4px; font-size: 0.85em; font-weight: bold; }}
        .side.long {{ background: #d4edda; color: #155724; }}
        .side.short {{ background: #f8d7da; color: #721c24; }}
        .footer {{ margin-top: 30px; padding-top: 20px; border-top: 1px solid #eee; color: #666; font-size: 0.9em; text-align: center; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>📊 Daily Trading Report</h1>
        <p class="subtitle">Ticker: <strong>{ticker}</strong> | Date: {datetime.now().strftime('%Y-%m-%d')}</p>
        
        <div class="metrics">
            <div class="metric-box {'profit' if pnl > 0 else 'loss'}">
                <div class="metric-value">{pnl:+,.0f}</div>
                <div class="metric-label">Net PnL (TWD)</div>
            </div>
            <div class="metric-box">
                <div class="metric-value">{len(trades)}</div>
                <div class="metric-label">Total Trades</div>
            </div>
            <div class="metric-box">
                <div class="metric-value">{win_rate:.1f}%</div>
                <div class="metric-label">Win Rate</div>
            </div>
            <div class="metric-box">
                <div class="metric-value">{profit_factor:.2f}</div>
                <div class="metric-label">Profit Factor</div>
            </div>
            <div class="metric-box">
                <div class="metric-value">{total_cost:,.0f}</div>
                <div class="metric-label">Total Cost</div>
            </div>
            <div class="metric-box">
                <div class="metric-value">{trader.balance:,.0f}</div>
                <div class="metric-label">Ending Balance</div>
            </div>
        </div>
        
        <div class="chart-container">
            <canvas id="equityChart"></canvas>
        </div>
        
        <h2>📈 Recent Trades ({len(trades)} total)</h2>
        <table>
            <thead>
                <tr>
                    <th>Time</th>
                    <th>Side</th>
                    <th>Entry</th>
                    <th>Exit</th>
                    <th>Lots</th>
                    <th>PnL</th>
                </tr>
            </thead>
            <tbody>
                {trades_html if trades_html else '<tr><td colspan="6" style="text-align: center; color: #999;">No trades today</td></tr>'}
            </tbody>
        </table>
        
        <div class="footer">
            Generated by Squeeze Futures Auto-Trader | Mode: {'LIVE' if live_mode else 'PAPER'}
        </div>
    </div>
    
    <script>
        const ctx = document.getElementById('equityChart').getContext('2d');
        const equityData = {json.dumps(equity_data)};
        
        new Chart(ctx, {{
            type: 'line',
            data: {{
                labels: equityData.map(d => d.x),
                datasets: [{{
                    label: 'Equity Curve (TWD)',
                    data: equityData.map(d => d.y),
                    borderColor: 'rgb({76 if pnl >= 0 else 235}, {153 if pnl >= 0 else 51}, {102 if pnl >= 0 else 73})',
                    backgroundColor: 'rgba({76 if pnl >= 0 else 235}, {153 if pnl >= 0 else 51}, {102 if pnl >= 0 else 73}, 0.1)',
                    borderWidth: 3,
                    fill: true,
                    tension: 0.3,
                    pointRadius: 3,
                    pointHoverRadius: 5
                }}]
            }},
            options: {{
                responsive: true,
                maintainAspectRatio: false,
                plugins: {{
                    legend: {{ display: false }},
                    tooltip: {{
                        backgroundColor: 'rgba(0, 0, 0, 0.8)',
                        titleColor: '#fff',
                        bodyColor: '#fff',
                        callbacks: {{
                            label: function(context) {{
                                return 'Balance: ' + context.parsed.y.toLocaleString('en-US', {{minimumFractionDigits: 0, maximumFractionDigits: 0}}) + ' TWD';
                            }}
                        }}
                    }}
                }},
                scales: {{
                    x: {{
                        display: true,
                        title: {{ display: true, text: 'Trade Number' }},
                        grid: {{ color: 'rgba(0, 0, 0, 0.05)' }}
                    }},
                    y: {{
                        display: true,
                        title: {{ display: true, text: 'Equity (TWD)' }},
                        grid: {{ color: 'rgba(0, 0, 0, 0.05)' }},
                        ticks: {{
                            callback: function(value) {{
                                return value.toLocaleString('en-US', {{minimumFractionDigits: 0, maximumFractionDigits: 0}});
                            }}
                        }}
                    }}
                }}
            }}
        }});
    </script>
</body>
</html>"""
        
        send_email_notification(
            subject=f"[TW Futures] Daily Report {ticker} {datetime.now().strftime('%Y-%m-%d')} | PnL: {pnl:+,.0f} TWD",
            body_text=f"Daily PnL: {pnl:+,.0f} TWD | Trades: {len(trades)} | Win Rate: {win_rate:.1f}%",
            body_html=html_body
        )
        console.print("[dim]✉️  Daily report sent[/dim]")

    try:
        while True:
            market = get_market_status()
            is_weekend_test = os.getenv("WEEKEND_TEST") == "1"

            if not market["open"] and not is_weekend_test:
                if trader.position != 0:
                    execute_trade("EXIT", trader.entry_price, datetime.now(), abs(trader.position))
                
                # 收盤後自動結束（避免無限循環和持續寫 log）
                console.print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Market Closed. Shutting down...")
                
                # 🚀 生成並發送收盤報告（僅 LIVE 模式）
                if live_ready:
                    console.print("[dim]Generating daily report...[/dim]")
                    _send_daily_report(trader, ticker, live_ready)
                else:
                    console.print("[dim]Saving final report...[/dim]")
                    trader.save_report()
                
                shioaji.logout()
                console.print("[green]✓ Trader shutdown complete.[/green]")
                break  # 退出無限循環
            
            # 1. 抓取數據
            processed_data = {}
            for tf in ["5m", "15m", "1h"]:
                df = shioaji.get_kline(ticker, interval=tf)
                if df.empty: df = download_futures_data("^TWII", interval=tf, period="5d")
                if not df.empty:
                    processed_data[tf] = calculate_futures_squeeze(df, bb_length=STRATEGY["length"], **PB_ARGS)

            if "5m" not in processed_data or "15m" not in processed_data:
                if is_weekend_test: break
                continue
                
            df_5m, df_15m = processed_data["5m"], processed_data["15m"]
            last_5m, last_15m = df_5m.iloc[-1], df_15m.iloc[-1]
            score = calculate_mtf_alignment(processed_data, weights=STRATEGY["weights"])['score']
            last_price, vwap = last_5m['Close'], last_5m['vwap']
            timestamp = last_5m.name
            
            # --- 🚀 紀錄數據 ---
            if last_processed_bar != timestamp:
                regime_desc = "NORMAL"
                if last_5m['opening_bullish']: regime_desc = "STRONG"
                elif last_5m['opening_bearish']: regime_desc = "WEAK"
                save_bar_data(last_5m, score, regime_desc, ticker)
                last_processed_bar = timestamp
                console.print(f"[dim]Bar logged: {timestamp}[/dim]")

            if is_weekend_test: 
                console.print("[green]Weekend Test Logging Success.[/green]")
                break

            # (核心交易邏輯...)
            # --- 2. 風控與分批平倉 ---
            if trader.position != 0:
                trader.update_trailing_stop(last_price)
                if TP['enabled'] and abs(trader.position) == MGMT['lots_per_trade'] and not has_tp1_hit:
                    pnl_pts = (last_price - trader.entry_price) * (1 if trader.position > 0 else -1)
                    if pnl_pts >= TP['tp1_pts']:
                        msg = execute_trade("PARTIAL_EXIT", last_price, timestamp, TP['tp1_lots'])
                        if msg:
                            has_tp1_hit = True; trader.current_stop_loss = trader.entry_price

                stop_msg = check_stop_loss(timestamp, last_price)
                if not stop_msg and RISK["exit_on_vwap"]:
                    if (trader.position > 0 and last_price < vwap and not last_5m['opening_bullish']) or \
                       (trader.position < 0 and last_price > vwap and not last_5m['opening_bearish']):
                        stop_msg = execute_trade("EXIT", last_price, timestamp, abs(trader.position))
                        if stop_msg:
                            stop_msg = "[VWAP] " + stop_msg
                
                if stop_msg:
                    console.print(f"[bold yellow][{timestamp}] {stop_msg}[/bold yellow]")
                    has_tp1_hit = False

            # --- 3. 進場邏輯 ---
            if trader.position == 0:
                has_tp1_hit = False
                
                # 計算停損點數
                # 若 atr_multiplier > 0，使用 ATR 動態停損；否則使用固定停損
                if ATR_MULT > 0:
                    atr_series = calculate_atr(df_5m, length=ATR_LENGTH)
                    if not atr_series.empty:
                        current_atr = atr_series.iloc[-1]
                        if not pd.isna(current_atr):
                            stop_loss_pts = current_atr * ATR_MULT
                        else:
                            stop_loss_pts = RISK["stop_loss_pts"]
                    else:
                        stop_loss_pts = RISK["stop_loss_pts"]
                else:
                    stop_loss_pts = RISK["stop_loss_pts"]

                # 【放寬進場條件】
                # 原：mom_state == 3 (多頭動能增強) / mom_state == 0 (空頭動能增強)
                # 新：mom_state >= 2 (多頭動能強或持平) / mom_state <= 1 (空頭動能強或持平)
                sqz_buy = (not last_5m['sqz_on']) and score >= STRATEGY["entry_score"] and True and last_5m["mom_state"] >= 2  # VWAP check disabled for entry
                pb_buy = df_5m['is_new_high'].tail(PB_CONFIRM_BARS).any() and last_5m['in_bull_pb_zone'] and last_price > last_5m['Open']
                sqz_sell = (not last_5m['sqz_on']) and score <= -STRATEGY["entry_score"] and True and last_5m["mom_state"] <= 1  # VWAP check disabled for entry
                pb_sell = df_5m['is_new_low'].tail(PB_CONFIRM_BARS).any() and last_5m['in_bear_pb_zone'] and last_price < last_5m['Open']

                # 【趨勢過濾 - 根據 regime_filter 設定】
                # loose: 完全禁用趨勢過濾
                # mid: 15m EMA filter ±0.2%
                # strict: 15m EMA filter ±0.1%
                if FILTER_MODE == "loose":
                    can_long = True
                    can_short = True
                elif FILTER_MODE == "mid":
                    can_long = (last_15m['Close'] > last_15m['ema_filter'] * 0.998) or last_5m['opening_bullish']
                    can_short = (last_15m['Close'] < last_15m['ema_filter'] * 1.002) or last_5m['opening_bearish']
                else:  # strict
                    can_long = (last_15m['Close'] > last_15m['ema_filter'] * 0.999) or last_5m['opening_bullish']
                    can_short = (last_15m['Close'] < last_15m['ema_filter'] * 1.001) or last_5m['opening_bearish']

                # 【趨勢突破確認】
                trend_signal = check_trend_breakout_signal(df_5m, df_15m)
                
                # 進場邏輯：Squeeze 信號 + 趨勢突破確認
                # 多頭：Squeeze 多頭 OR 趨勢突破多頭
                long_confirmed = (sqz_buy or pb_buy) and can_long
                trend_long_confirmed = trend_signal['trend_long']
                
                # 空頭：Squeeze 空頭 OR 趨勢突破空頭
                short_confirmed = (sqz_sell or pb_sell) and can_short
                trend_short_confirmed = trend_signal['trend_short']
                
                if (long_confirmed or trend_long_confirmed) and MGMT["allow_long"]:
                    if not live_ready or check_funds_for_live(shioaji, MGMT["lots_per_trade"]):
                        if trend_long_confirmed:
                            console.print(f"[dim]📈 Trend Breakout LONG: {', '.join(trend_signal['reasons'])}[/dim]")
                        execute_trade("BUY", last_price, timestamp, MGMT["lots_per_trade"], stop_loss=stop_loss_pts, break_even_trigger=RISK["break_even_pts"])
                elif (short_confirmed or trend_short_confirmed) and MGMT["allow_short"]:
                    if not live_ready or check_funds_for_live(shioaji, MGMT["lots_per_trade"]):
                        if trend_short_confirmed:
                            console.print(f"[dim]📉 Trend Breakout SHORT: {', '.join(trend_signal['reasons'])}[/dim]")
                        execute_trade("SELL", last_price, timestamp, MGMT["lots_per_trade"], stop_loss=stop_loss_pts, break_even_trigger=RISK["break_even_pts"])

            time.sleep(POLL_INTERVAL)

    except KeyboardInterrupt: pass
    finally: trader.save_report(); shioaji.logout()

if __name__ == "__main__":
    run_simulation("TMF")


# ========== 趨勢突破策略整合 ==========

def check_trend_breakout_signal(df_5m: pd.DataFrame, df_15m: pd.DataFrame) -> dict:
    """
    檢查趨勢突破信號 (與 Squeeze 結合)
    
    進場條件：
    多頭：
    - 價格 > 多頭趨勢線
    - MA20 斜率 > 0.1%
    - Squeeze 信號符合
    
    空頭：
    - 價格 < 空頭趨勢線
    - MA20 斜率 < -0.1%
    - Squeeze 信號符合
    """
    from squeeze_futures.engine.trend_breakout import check_trend_breakout
    
    result = {
        'trend_long': False,
        'trend_short': False,
        'reasons': []
    }
    
    # 檢查 5m 趨勢
    if len(df_5m) >= 20:
        breakout_5m = check_trend_breakout(
            df_5m,
            lookback=20,
            ma_length=20,
            compare_bars=5,
            slope_threshold=0.1
        )
        
        if breakout_5m['long_signal']:
            result['trend_long'] = True
            result['reasons'].extend([f"5m: {r}" for r in breakout_5m['long_reasons']])
        
        if breakout_5m['short_signal']:
            result['trend_short'] = True
            result['reasons'].extend([f"5m: {r}" for r in breakout_5m['short_reasons']])
    
    return result

import sys
import os
import time
import yaml
from datetime import datetime
import pandas as pd
from rich.console import Console

# 加入 src 到路徑
sys.path.append(os.path.join(os.path.dirname(__file__), "..", "src"))

from squeeze_futures.data.downloader import download_futures_data
from squeeze_futures.data.shioaji_client import ShioajiClient
from squeeze_futures.engine.constants import get_point_value
from squeeze_futures.engine.indicators import calculate_futures_squeeze, calculate_mtf_alignment, calculate_atr
from squeeze_futures.engine.simulator import PaperTrader
from squeeze_futures.report.notifier import send_email_notification

console = Console()

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

    trader = PaperTrader(ticker=ticker, point_value=get_point_value(ticker))
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

        return trader.execute_signal(
            signal,
            price,
            ts,
            lots=lots,
            max_lots=MGMT["max_positions"],
            stop_loss=stop_loss,
            break_even_trigger=break_even_trigger,
        )

    def check_stop_loss(ts, market_price: float):
        if trader.position > 0 and trader.current_stop_loss and market_price <= trader.current_stop_loss:
            return execute_trade("EXIT", trader.current_stop_loss, ts, abs(trader.position))
        if trader.position < 0 and trader.current_stop_loss and market_price >= trader.current_stop_loss:
            return execute_trade("EXIT", trader.current_stop_loss, ts, abs(trader.position))
        return None

    try:
        while True:
            market = get_market_status()
            is_weekend_test = os.getenv("WEEKEND_TEST") == "1"

            if not market["open"] and not is_weekend_test:
                if trader.position != 0:
                    execute_trade("EXIT", trader.entry_price, datetime.now(), abs(trader.position))
                
                # 收盤後自動結束（避免無限循環和持續寫 log）
                console.print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Market Closed. Shutting down...")
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
                
                sqz_buy = (not last_5m['sqz_on']) and score >= STRATEGY["entry_score"] and last_price > vwap and last_5m['mom_state'] == 3
                pb_buy = df_5m['is_new_high'].tail(12).any() and last_5m['in_bull_pb_zone'] and last_price > last_5m['Open']
                sqz_sell = (not last_5m['sqz_on']) and score <= -STRATEGY["entry_score"] and last_price < vwap and last_5m['mom_state'] == 0
                pb_sell = df_5m['is_new_low'].tail(12).any() and last_5m['in_bear_pb_zone'] and last_price < last_5m['Open']

                can_long = (last_15m['Close'] > last_15m['ema_filter'] or last_5m['opening_bullish'])
                can_short = (last_15m['Close'] < last_15m['ema_filter'] or last_5m['opening_bearish'])

                if (sqz_buy or pb_buy) and can_long and MGMT["allow_long"]:
                    if not live_ready or check_funds_for_live(shioaji, MGMT["lots_per_trade"]):
                        execute_trade("BUY", last_price, timestamp, MGMT["lots_per_trade"], stop_loss=stop_loss_pts, break_even_trigger=RISK["break_even_pts"])
                elif (sqz_sell or pb_sell) and can_short and MGMT["allow_short"]:
                    if not live_ready or check_funds_for_live(shioaji, MGMT["lots_per_trade"]):
                        execute_trade("SELL", last_price, timestamp, MGMT["lots_per_trade"], stop_loss=stop_loss_pts, break_even_trigger=RISK["break_even_pts"])

            time.sleep(30)

    except KeyboardInterrupt: pass
    finally: trader.save_report(); shioaji.logout()

if __name__ == "__main__":
    run_simulation("TMF")

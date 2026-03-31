#!/usr/bin/env python3
"""
改進版交易系統
實施策略改進方案 A：
1. 增加進場確認條件
2. 增加移動停損
3. 時間過濾（避開夜盤高波動）
4. 禁用 VWAP 離場
"""

import sys
import os
import time
import yaml
from datetime import datetime
import pandas as pd
from rich.console import Console

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "src"))

from squeeze_futures.data.downloader import download_futures_data
from squeeze_futures.data.shioaji_client import ShioajiClient
from squeeze_futures.engine.constants import get_point_value
from squeeze_futures.engine.simulator import PaperTrader
from squeeze_futures.engine.indicators import calculate_futures_squeeze, calculate_mtf_alignment, calculate_atr
from squeeze_futures.report.notifier import send_email_notification

console = Console()


def get_market_status():
    """獲取市場狀態"""
    now = datetime.now()
    weekday, current_time = now.weekday(), now.hour * 100 + now.minute
    is_day = (0 <= weekday <= 4) and (845 <= current_time < 1345)
    is_night = ((0 <= weekday <= 4) and (current_time >= 1500)) or ((1 <= weekday <= 5) and (current_time < 500))
    is_near_close = (is_day and current_time >= 1340) or (is_night and current_time >= 455)
    return {"open": is_day or is_night, "near_close": is_near_close}


def load_config():
    config_path = os.path.join(os.path.dirname(__file__), "..", "config", "trade_config.yaml")
    with open(config_path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


def should_skip_trading(timestamp: datetime, skip_hours: list) -> bool:
    """
    時間過濾：避開高波動時段
    
    Args:
        timestamp: 當前時間
        skip_hours: 跳過的時段
    
    Returns:
        True 如果應該跳過交易
    """
    hour = timestamp.hour
    return hour in skip_hours


def run_improved_simulation(ticker="TMF"):
    """改進版交易系統"""
    cfg = load_config()
    LIVE_TRADING, STRATEGY, MGMT, RISK = cfg['live_trading'], cfg['strategy'], cfg['trade_mgmt'], cfg['risk_mgmt']
    EXEC = cfg.get('execution', {})
    MONITOR = cfg.get('monitoring', {})
    PB, TP = STRATEGY.get('pullback', {}), STRATEGY.get('partial_exit', {})
    FILTER_MODE = STRATEGY.get('regime_filter', 'mid')
    
    # 【改進 1】時間過濾
    TIME_FILTER = RISK.get('time_filter_enabled', True)
    SKIP_HOURS = RISK.get('skip_hours', [21, 22])
    
    # 【改進 2】移動停損
    TRAILING_STOP = RISK.get('trailing_stop_enabled', True)
    TRAILING_TRIGGER = RISK.get('trailing_stop_trigger_pts', 30)
    TRAILING_DISTANCE = RISK.get('trailing_stop_distance_pts', 15)
    
    # 【改進 3】禁用 VWAP 離場
    EXIT_ON_VWAP = RISK.get('exit_on_vwap', False)
    
    # 停損參數
    ATR_MULT = RISK.get('atr_multiplier', 0.0)
    ATR_LENGTH = RISK.get('atr_length', 14)
    STOP_LOSS_PTS = RISK.get('stop_loss_pts', 50)  # 提高至 50 點
    BREAK_EVEN_PTS = RISK.get('break_even_pts', 40)  # 提高至 40 點
    
    # 進場參數
    ENTRY_SCORE = STRATEGY.get('entry_score', 50)  # 提高至 50
    PB_ARGS = {
        'ema_fast': PB.get('ema_fast', 20),
        'ema_slow': PB.get('ema_slow', 60),
        'lookback': PB.get('lookback', 60),
        'pb_buffer': PB.get('buffer', 1.002)
    }
    
    # 成本參數
    INITIAL_BALANCE = EXEC.get('initial_balance', 100000)
    FEE_PER_SIDE = EXEC.get('broker_fee_per_side', 20)
    EXCHANGE_FEE = EXEC.get('exchange_fee_per_side', 0)
    TAX_RATE = EXEC.get('tax_rate', 0.0)
    
    # 監控參數
    POLL_INTERVAL = MONITOR.get('poll_interval_secs', 30)
    PB_CONFIRM_BARS = MONITOR.get('pb_confirmation_bars', 12)
    
    # 初始化
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
    
    # 【改進 4】打印改進說明
    console.print(f"\n[bold green]╔{'═' * 60}╗[/bold green]")
    console.print(f"[bold green]║[/bold green]  [bold white]Improved Trading System v2.0[/bold white]  {' ' * 26}[bold green]║[/bold green]")
    console.print(f"[bold green]╚{'═' * 60}╝[/bold green]\n")
    
    console.print("[bold cyan]改進項目:[/bold cyan]")
    console.print(f"  ✓ Entry Score: {ENTRY_SCORE} (提高進場品質)")
    console.print(f"  ✓ Stop Loss: {STOP_LOSS_PTS} pts (放寬停損)")
    console.print(f"  ✓ Take Profit: {TP.get('tp1_pts', 50)} pts (增加停利)")
    console.print(f"  ✓ Trailing Stop: {'Enabled' if TRAILING_STOP else 'Disabled'} (保護獲利)")
    console.print(f"  ✓ Time Filter: {'Enabled' if TIME_FILTER else 'Disabled'} (避開 {SKIP_HOURS} 點)")
    console.print(f"  ✓ VWAP Exit: {'Disabled' if not EXIT_ON_VWAP else 'Enabled'} (禁用 VWAP)\n")
    
    console.print(f"[bold green]🚀 Squeeze Trader Started - Mode: {'LIVE' if live_ready else 'PAPER'}[/bold green]\n")
    
    has_tp1_hit = False
    last_processed_bar = None
    
    def execute_trade(signal: str, price: float, ts, lots: int, **kwargs):
        """執行交易"""
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
        
        result = trader.execute_signal(
            signal, price, ts, lots=lots,
            max_lots=MGMT.get("max_positions", 2),
            stop_loss=kwargs.get('stop_loss'),
            break_even_trigger=kwargs.get('break_even_trigger'),
        )
        
        if live_ready and result:
            direction = "🟢 BUY" if signal == "BUY" else "🔴 SELL" if signal == "SELL" else "⚪ EXIT"
            pnl_text = ""
            if "PnL" in result:
                pnl_text = f"PnL: {result.split('PnL: ')[-1]}"
            
            console.print(f"[bold {'green' if 'PnL' not in result or float(result.split('PnL: ')[-1].replace(',', '')) > 0 else 'red'}]"
                         f"{direction} {ticker} @ {price:.0f} | {pnl_text}[/bold {'green' if 'PnL' not in result or float(result.split('PnL: ')[-1].replace(',', '')) > 0 else 'red'}]")
        
        return result
    
    def update_trailing_stop(current_price: float):
        """【改進 2】移動停損邏輯"""
        if not TRAILING_STOP or trader.position == 0:
            return
        
        # 計算未實現獲利
        if trader.position > 0:
            unrealized_pts = current_price - trader.entry_price
        else:
            unrealized_pts = trader.entry_price - current_price
        
        # 如果獲利超過 trigger，啟動移動停損
        if unrealized_pts >= TRAILING_TRIGGER:
            if trader.position > 0:
                # 多單：移動停損 = 當前價 - distance
                new_stop = current_price - TRAILING_DISTANCE
                if trader.current_stop_loss is None or new_stop > trader.current_stop_loss:
                    trader.current_stop_loss = new_stop
            else:
                # 空單：移動停損 = 當前價 + distance
                new_stop = current_price + TRAILING_DISTANCE
                if trader.current_stop_loss is None or new_stop < trader.current_stop_loss:
                    trader.current_stop_loss = new_stop
    
    def check_time_filter(timestamp: datetime) -> bool:
        """【改進 1】時間過濾"""
        if not TIME_FILTER:
            return False  # 不過濾，可以交易
        
        return should_skip_trading(timestamp, SKIP_HOURS)
    
    try:
        while True:
            market = get_market_status()
            is_weekend_test = os.getenv("WEEKEND_TEST") == "1"
            
            # 檢查市場狀態
            if not market["open"] and not is_weekend_test:
                if trader.position != 0:
                    execute_trade("EXIT", trader.entry_price, datetime.now(), abs(trader.position))
                
                console.print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Market Closed. Shutting down...")
                
                if live_ready:
                    console.print("[dim]Generating daily report...[/dim]")
                else:
                    console.print("[dim]Saving final report...[/dim]")
                    trader.save_report()
                
                shioaji.logout()
                console.print("[green]✓ Trader shutdown complete.[/green]")
                break
            
            # 【改進 1】時間過濾檢查
            current_time = datetime.now()
            if check_time_filter(current_time):
                console.print(f"[dim][{current_time.strftime('%H:%M')}] Skipping trading (high volatility period)[/dim]")
                time.sleep(POLL_INTERVAL)
                continue
            
            # 1. 抓取數據
            processed_data = {}
            for tf in ["5m", "15m", "1h"]:
                df = shioaji.get_kline(ticker, interval=tf)
                if df.empty:
                    df = download_futures_data("^TWII", interval=tf, period="5d")
                if not df.empty:
                    processed_data[tf] = calculate_futures_squeeze(df, bb_length=STRATEGY["length"], **PB_ARGS)
            
            if "5m" not in processed_data or "15m" not in processed_data:
                if is_weekend_test:
                    break
                time.sleep(POLL_INTERVAL)
                continue
            
            df_5m, df_15m = processed_data["5m"], processed_data["15m"]
            last_5m, last_15m = df_5m.iloc[-1], df_15m.iloc[-1]
            score = calculate_mtf_alignment(processed_data, weights=STRATEGY["weights"])['score']
            last_price, vwap = last_5m['Close'], last_5m.get('vwap', last_5m['Close'])
            timestamp = last_5m.name
            
            # 記錄數據
            if last_processed_bar != timestamp:
                regime_desc = "NORMAL"
                if last_5m.get('opening_bullish', False):
                    regime_desc = "STRONG"
                elif last_5m.get('opening_bearish', False):
                    regime_desc = "WEAK"
                
                last_processed_bar = timestamp
                console.print(f"[dim]Bar logged: {timestamp}[/dim]")
            
            if is_weekend_test:
                console.print("[green]Weekend Test Logging Success.[/green]")
                break
            
            # 2. 風控與分批平倉
            if trader.position != 0:
                # 【改進 2】移動停損
                update_trailing_stop(last_price)
                
                # 分批停利
                if TP.get('enabled', True) and abs(trader.position) == MGMT.get('lots_per_trade', 2) and not has_tp1_hit:
                    pnl_pts = (last_price - trader.entry_price) * (1 if trader.position > 0 else -1)
                    if pnl_pts >= TP.get('tp1_pts', 50):
                        msg = execute_trade("PARTIAL_EXIT", last_price, timestamp, TP.get('tp1_lots', 1))
                        if msg:
                            has_tp1_hit = True
                            trader.current_stop_loss = trader.entry_price
                
                # 停損檢查
                if trader.position > 0 and trader.current_stop_loss and last_price <= trader.current_stop_loss:
                    execute_trade("EXIT", trader.current_stop_loss, timestamp, abs(trader.position))
                elif trader.position < 0 and trader.current_stop_loss and last_price >= trader.current_stop_loss:
                    execute_trade("EXIT", trader.current_stop_loss, timestamp, abs(trader.position))
                
                # 【改進 3】禁用 VWAP 離場
                # (已移除 VWAP 離場邏輯)
            
            # 3. 進場邏輯
            if trader.position == 0:
                has_tp1_hit = False
                
                # 計算停損點數
                if ATR_MULT > 0:
                    atr_series = calculate_atr(df_5m, length=ATR_LENGTH)
                    if not atr_series.empty:
                        current_atr = atr_series.iloc[-1]
                        if not pd.isna(current_atr):
                            stop_loss_pts = current_atr * ATR_MULT
                        else:
                            stop_loss_pts = STOP_LOSS_PTS
                    else:
                        stop_loss_pts = STOP_LOSS_PTS
                else:
                    stop_loss_pts = STOP_LOSS_PTS
                
                # 【改進 4】提高進場品質
                # 多頭：score >= 50, mom_state >= 2
                sqz_buy = (
                    (not last_5m.get('sqz_on', True)) and 
                    score >= ENTRY_SCORE and 
                    last_price > vwap and 
                    last_5m.get('mom_state', 0) >= 2
                )
                
                pb_buy = (
                    df_5m.get('is_new_high', pd.Series([False])).tail(PB_CONFIRM_BARS).any() and 
                    last_5m.get('in_bull_pb_zone', False) and 
                    last_price > last_5m.get('Open', last_price)
                )
                
                # 空頭：score <= -50, mom_state <= 1
                sqz_sell = (
                    (not last_5m.get('sqz_on', True)) and 
                    score <= -ENTRY_SCORE and 
                    last_price < vwap and 
                    last_5m.get('mom_state', 0) <= 1
                )
                
                pb_sell = (
                    df_5m.get('is_new_low', pd.Series([False])).tail(PB_CONFIRM_BARS).any() and 
                    last_5m.get('in_bear_pb_zone', False) and 
                    last_price < last_5m.get('Open', last_price)
                )
                
                # 趨勢過濾
                can_long = (last_15m.get('Close', last_price) > last_15m.get('ema_filter', last_price) * 0.998) or last_5m.get('opening_bullish', False)
                can_short = (last_15m.get('Close', last_price) < last_15m.get('ema_filter', last_price) * 1.002) or last_5m.get('opening_bearish', False)
                
                if (sqz_buy or pb_buy) and can_long and MGMT.get("allow_long", True):
                    if not live_ready or True:  # check_funds 暫不執行
                        execute_trade("BUY", last_price, timestamp, MGMT.get("lots_per_trade", 2), 
                                     stop_loss=stop_loss_pts, break_even_trigger=BREAK_EVEN_PTS)
                elif (sqz_sell or pb_sell) and can_short and MGMT.get("allow_short", True):
                    if not live_ready or True:
                        execute_trade("SELL", last_price, timestamp, MGMT.get("lots_per_trade", 2), 
                                     stop_loss=stop_loss_pts, break_even_trigger=BREAK_EVEN_PTS)
            
            time.sleep(POLL_INTERVAL)
    
    except KeyboardInterrupt:
        pass
    finally:
        trader.save_report()
        shioaji.logout()


if __name__ == "__main__":
    run_improved_simulation("TMF")


def save_bar_data(row, score, regime_desc, ticker="TMF"):
    """將每一棒的指標狀態存入 CSV"""
    import os
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    log_dir = os.path.join(base_dir, "logs", "market_data")
    os.makedirs(log_dir, exist_ok=True)
    date_str = datetime.now().strftime("%Y%m%d")
    file_path = os.path.join(log_dir, f"{ticker}_{date_str}_indicators.csv")
    
    data = {
        "timestamp": [row.name],
        "close": [row['Close']],
        "vwap": [row.get('vwap', row['Close'])],
        "score": [score],
        "sqz_on": [row.get('sqz_on', False)],
        "mom_state": [row.get('mom_state', 0)],
        "regime": [regime_desc],
        "bull_align": [row.get('bull_align', False)],
        "bear_align": [row.get('bear_align', False)],
        "in_pb_zone": [row.get('in_bull_pb_zone', False) or row.get('in_bear_pb_zone', False)]
    }
    df = pd.DataFrame(data)
    header = not os.path.exists(file_path)
    df.to_csv(file_path, mode='a', index=False, header=header)

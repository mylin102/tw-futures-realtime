#!/usr/bin/env python3
"""
夜盤策略回測腳本
測試：15 分線看趨勢 (TSM), 5 分線找進場 (TWII)
"""

import sys
import os
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from pathlib import Path
from rich.console import Console
from rich.table import Table

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from squeeze_futures.data.tsm_client import download_tsm_data, calculate_tsm_indicators, get_tsm_signal
from squeeze_futures.engine import DataManager
from squeeze_futures.engine.indicators import calculate_futures_squeeze, calculate_mtf_alignment
from squeeze_futures.engine.simulator import PaperTrader
from squeeze_futures.engine.constants import get_point_value

console = Console()


def is_night_session(timestamp: datetime) -> bool:
    """判斷是否為夜盤時段"""
    hour = timestamp.hour
    return hour >= 15 or hour < 5


def load_tsm_data(period: str = "5d") -> pd.DataFrame:
    """載入 TSM 15 分線數據"""
    console.print("[dim]下載 TSM 15m 數據...[/dim]")
    tsm_df = download_tsm_data(period=period, interval="15m")
    
    if tsm_df is not None:
        tsm_df = calculate_tsm_indicators(tsm_df)
    
    return tsm_df


def load_twii_data(period: str = "5d") -> dict:
    """載入 TWII 多時間框架數據"""
    console.print("[dim]下載 TWII 數據...[/dim]")
    dm = DataManager("data/taifex_raw")
    
    data = {}
    for tf in ["5m", "15m", "1h"]:
        df = dm.load_yahoo("^TWII", period=period, interval=tf)
        if not df.empty:
            df = calculate_futures_squeeze(
                df,
                bb_length=20,
                ema_fast=20,
                ema_slow=60,
                lookback=60,
                pb_buffer=1.002
            )
            data[tf] = df
    
    return data


def backtest_night_strategy(tsm_df: pd.DataFrame, twii_data: dict, config: dict) -> dict:
    """
    夜盤策略回測
    
    邏輯：
    1. TSM 15m 看趨勢 (權重 50%)
    2. TWII 5m 找進場 (權重 20%)
    3. MTF Score 確認
    """
    console.print("\n[bold yellow]執行夜盤回測...[/bold yellow]\n")
    
    # 初始化交易器
    trader = PaperTrader(
        ticker="TMF",
        initial_balance=config['initial_balance'],
        point_value=10,
        fee_per_side=20
    )
    
    # 參數
    entry_score = config.get('entry_score', 35)
    stop_loss_pts = config.get('stop_loss_pts', 80)
    tp1_pts = config.get('tp1_pts', 60)
    trailing_trigger = config.get('trailing_trigger', 50)
    trailing_distance = config.get('trailing_distance', 25)
    tsm_min_confidence = config.get('tsm_min_confidence', 0.5)
    
    # 獲取數據
    tsm_15m = tsm_df
    twii_5m = twii_data.get('5m')
    twii_15m = twii_data.get('15m')
    twii_1h = twii_data.get('1h')
    
    if twii_5m is None:
        console.print("[red]✗ TWII 數據不足[/red]")
        return None
    
    # 對齊時間索引 (包含所有時段，因為 Yahoo 數據只有日盤)
    # 註解：Yahoo Finance 的^TWII 只有日盤數據 (09:00-13:25)
    # 夜盤需要使用 Shioaji API 或真實期貨數據
    console.print(f"[yellow]⚠ 注意：Yahoo Finance 數據只有日盤[/yellow]")
    console.print(f"[dim]夜盤回測需要 Shioaji API 或真實期貨數據[/dim]\n")
    
    # 暫時使用全部數據回測 (包含日盤)
    # night_mask = twii_5m.index.hour.isin([15, 16, 17, 18, 19, 20, 21, 22, 23, 0, 1, 2, 3, 4])
    # twii_5m = twii_5m[night_mask]
    
    console.print(f"[green]✓ 回測數據：{len(twii_5m)} 筆 5m K 棒 (日盤 + 夜盤)[/green]")
    
    # 回測主循環
    trades = []
    has_tp1_hit = False
    prev_tsm_signal = None
    
    for i in range(1, len(twii_5m)):
        timestamp = twii_5m.index[i]
        
        # 獲取當前 K 棒
        bar_5m = twii_5m.iloc[i]
        
        # 獲取對應的 15m K 棒 (最近一筆)
        try:
            bar_15m_idx = twii_15m.index.get_loc(timestamp) if timestamp in twii_15m.index else -1
            if bar_15m_idx == -1:
                # 向前填充
                bar_15m_idx = twii_15m.index.get_indexer([timestamp], method='ffill')[0]
            bar_15m = twii_15m.iloc[bar_15m_idx] if bar_15m_idx >= 0 else bar_5m
        except:
            bar_15m = bar_5m
        
        # 【關鍵】TSM 15m 趨勢判斷 (延遲 15 分鐘)
        tsm_signal = None
        if tsm_15m is not None:
            # 找到對應時間的 TSM 數據 (延遲 15 分鐘)
            delayed_time = timestamp - timedelta(minutes=15)
            try:
                if delayed_time >= tsm_15m.index[0]:
                    tsm_idx = tsm_15m.index.get_indexer([delayed_time], method='ffill')[0]
                    if tsm_idx >= 0:
                        tsm_bar = tsm_15m.iloc[tsm_idx]
                        tsm_signal = get_tsm_signal(tsm_15m.iloc[:tsm_idx+1])
            except:
                pass
        
        # TSM 信號確認
        tsm_confirmed = False
        tsm_direction = 0
        if tsm_signal and tsm_signal['confidence'] >= tsm_min_confidence:
            tsm_confirmed = True
            tsm_direction = tsm_signal['trend']
        
        # 計算 MTF Score (15m 權重 50%, 5m 權重 20%)
        mtf_data = {
            '1h': twii_1h.iloc[:i+1] if twii_1h is not None else None,
            '15m': twii_15m.iloc[:i+1],
            '5m': twii_5m.iloc[:i+1]
        }
        mtf_data = {k: v for k, v in mtf_data.items() if v is not None and not v.empty}
        
        if len(mtf_data) > 0:
            mtf_result = calculate_mtf_alignment(
                mtf_data,
                weights={"1h": 0.3, "15m": 0.5, "5m": 0.2}
            )
            score = mtf_result.get('score', 0)
        else:
            score = 0
        
        # 當前價格
        last_price = bar_5m['Close']
        vwap = bar_5m.get('vwap', last_price)
        mom_state = bar_5m.get('mom_state', 0)
        sqz_on = bar_5m.get('sqz_on', True)
        
        # 進場邏輯
        if trader.position == 0:
            has_tp1_hit = False
            
            # 多頭進場
            if tsm_direction == 1 or not tsm_confirmed:  # TSM 多頭或無信號
                sqz_buy = (
                    (not sqz_on) and
                    score >= entry_score and
                    last_price > vwap and
                    mom_state >= 1
                )
                
                if sqz_buy:
                    # 進場
                    trader.execute_signal(
                        "BUY", last_price, timestamp,
                        lots=1,  # 夜盤 1 口
                        stop_loss=stop_loss_pts,
                        break_even_trigger=50
                    )
                    
                    trades.append({
                        'type': 'ENTRY',
                        'time': timestamp,
                        'price': last_price,
                        'direction': 'LONG',
                        'tsm_signal': tsm_signal['signal'] if tsm_signal else 'N/A',
                        'score': score,
                    })
            
            # 空頭進場
            elif tsm_direction == -1 or not tsm_confirmed:  # TSM 空頭或無信號
                sqz_sell = (
                    (not sqz_on) and
                    score <= -entry_score and
                    last_price < vwap and
                    mom_state <= 1
                )
                
                if sqz_sell:
                    # 進場
                    trader.execute_signal(
                        "SELL", last_price, timestamp,
                        lots=1,  # 夜盤 1 口
                        stop_loss=stop_loss_pts,
                        break_even_trigger=50
                    )
                    
                    trades.append({
                        'type': 'ENTRY',
                        'time': timestamp,
                        'price': last_price,
                        'direction': 'SHORT',
                        'tsm_signal': tsm_signal['signal'] if tsm_signal else 'N/A',
                        'score': score,
                    })
        
        # 出場邏輯
        else:
            # 移動停損
            if trader.position > 0:
                unrealized_pts = last_price - trader.entry_price
            else:
                unrealized_pts = trader.entry_price - last_price
            
            if unrealized_pts >= trailing_trigger:
                if trader.position > 0:
                    new_stop = last_price - trailing_distance
                    if trader.current_stop_loss is None or new_stop > trader.current_stop_loss:
                        trader.current_stop_loss = new_stop
                else:
                    new_stop = last_price + trailing_distance
                    if trader.current_stop_loss is None or new_stop < trader.current_stop_loss:
                        trader.current_stop_loss = new_stop
            
            # 分批停利
            if not has_tp1_hit and abs(trader.position) == 1:
                pnl_pts = (last_price - trader.entry_price) * (1 if trader.position > 0 else -1)
                if pnl_pts >= tp1_pts:
                    trader.execute_signal("PARTIAL_EXIT", last_price, timestamp, 1)
                    has_tp1_hit = True
                    trader.current_stop_loss = trader.entry_price
            
            # 停損檢查
            if trader.position > 0 and trader.current_stop_loss and last_price <= trader.current_stop_loss:
                trader.execute_signal("EXIT", trader.current_stop_loss, timestamp, 1)
            elif trader.position < 0 and trader.current_stop_loss and last_price >= trader.current_stop_loss:
                trader.execute_signal("EXIT", trader.current_stop_loss, timestamp, 1)
    
    # 計算績效
    exits = [t for t in trader.trades if t.get('type') == 'EXIT']
    
    if exits:
        total_pnl = sum(t['pnl_cash'] for t in exits)
        winning = [t for t in exits if t['pnl_cash'] > 0]
        losing = [t for t in exits if t['pnl_cash'] < 0]
        
        win_rate = len(winning) / len(exits) * 100 if exits else 0
        avg_pnl = np.mean([t['pnl_cash'] for t in exits])
        
        gross_profit = sum(t['pnl_cash'] for t in winning) if winning else 0
        gross_loss = abs(sum(t['pnl_cash'] for t in losing)) if losing else 0
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0
    else:
        total_pnl = 0
        win_rate = 0
        avg_pnl = 0
        profit_factor = 0
    
    return {
        'total_pnl': total_pnl,
        'final_balance': trader.balance,
        'total_trades': len(exits),
        'win_rate': win_rate,
        'avg_pnl': avg_pnl,
        'profit_factor': profit_factor,
        'trades': trader.trades,
        'entry_trades': trades,
    }


def print_backtest_results(results: dict):
    """打印回測結果"""
    console.print("\n[bold green]╔" + "═" * 60 + "╗[/bold green]")
    console.print("[bold green]║[/bold green]" + " " * 18 + "NIGHT SESSION BACKTEST RESULTS" + " " * 10 + "[bold green]║[/bold green]")
    console.print("[bold green]╚" + "═" * 60 + "╝[/bold green]\n")
    
    # 績效指標
    table = Table(title="Performance Metrics")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", justify="right")
    
    table.add_row("Total PnL", f"{results['total_pnl']:,.0f} TWD")
    table.add_row("Final Balance", f"{results['final_balance']:,.0f} TWD")
    table.add_row("Total Trades", str(results['total_trades']))
    table.add_row("Win Rate", f"{results['win_rate']:.1f}%")
    table.add_row("Avg PnL", f"{results['avg_pnl']:,.0f} TWD")
    table.add_row("Profit Factor", f"{results['profit_factor']:.2f}")
    
    console.print(table)
    
    # 交易明細
    if results['entry_trades']:
        console.print(f"\n[bold yellow]Trade Details ({len(results['entry_trades'])} trades):[/bold yellow]\n")
        
        table = Table(title="Trade Log")
        table.add_column("Time", style="dim")
        table.add_column("Type", justify="center")
        table.add_column("Price", justify="right")
        table.add_column("TSM Signal", justify="center")
        table.add_column("Score", justify="right")
        
        for trade in results['entry_trades'][:20]:  # 顯示前 20 筆
            table.add_row(
                trade['time'].strftime("%m-%d %H:%M"),
                "🟢 LONG" if trade['direction'] == 'LONG' else "🔴 SHORT",
                f"{trade['price']:.0f}",
                trade['tsm_signal'],
                f"{trade['score']:+.1f}",
            )
        
        console.print(table)


def main():
    """主函數"""
    console.print("[bold blue]╔" + "═" * 60 + "╗[/bold blue]")
    console.print("[bold blue]║[/bold blue]" + " " * 15 + "NIGHT STRATEGY BACKTEST" + " " * 16 + "[bold blue]║[/bold blue]")
    console.print("[bold blue]╚" + "═" * 60 + "╝[/bold blue]\n")
    
    # 配置
    config = {
        'initial_balance': 100000,
        'entry_score': 35,
        'stop_loss_pts': 80,
        'tp1_pts': 60,
        'trailing_trigger': 50,
        'trailing_distance': 25,
        'tsm_min_confidence': 0.5,
    }
    
    # 載入數據 (最近 5 天，包含昨晚)
    tsm_df = load_tsm_data(period="5d")
    twii_data = load_twii_data(period="5d")
    
    if tsm_df is None or not twii_data:
        console.print("[red]✗ 數據載入失敗[/red]")
        return
    
    # 執行回測
    results = backtest_night_strategy(tsm_df, twii_data, config)
    
    if results:
        # 打印結果
        print_backtest_results(results)
        
        # 保存結果
        import json
        output_dir = Path("exports/backtests")
        output_dir.mkdir(parents=True, exist_ok=True)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_file = output_dir / f"night_backtest_{timestamp}.json"
        
        with open(output_file, 'w') as f:
            json.dump({
                'total_pnl': results['total_pnl'],
                'win_rate': results['win_rate'],
                'total_trades': results['total_trades'],
                'trades': [
                    {k: (v.strftime('%Y-%m-%d %H:%M:%S') if isinstance(v, datetime) else v)
                     for k, v in t.items()}
                    for t in results['trades']
                ],
            }, f, indent=2, default=str)
        
        console.print(f"\n[green]✓ 結果已保存至：{output_file}[/green]\n")
    
    console.print("[bold blue]╔" + "═" * 60 + "╗[/bold blue]")
    console.print("[bold blue]║[/bold blue]" + " " * 20 + "BACKTEST COMPLETE" + " " * 21 + "[bold blue]║[/bold blue]")
    console.print("[bold blue]╚" + "═" * 60 + "╝[/bold blue]\n")


if __name__ == "__main__":
    main()

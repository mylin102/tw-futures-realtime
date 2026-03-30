#!/usr/bin/env python3
"""
完整乾跑報告 (Full Dry Run Report)
模擬完整交易日並生成所有業務報告
"""

import sys
import os
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime, time
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from squeeze_futures.business import (
    RiskManager, RiskLimits,
    SignalGenerator, SignalConfig,
    CapitalManager, CapitalConfig,
)
from squeeze_futures.engine import DataManager
from squeeze_futures.engine.analytics import QuantAnalytics

console = Console()


def simulate_full_day_trading():
    """模擬完整一日交易"""
    console.print("[bold blue]╔" + "═" * 78 + "╗[/bold blue]")
    console.print("[bold blue]║[/bold blue]" + " " * 20 + "SQUEEZE FUTURES DRY RUN REPORT" + " " * 27 + "[bold blue]║[/bold blue]")
    console.print("[bold blue]╚" + "═" * 78 + "╝[/bold blue]")
    console.print()
    
    # ========== 初始化 ==========
    console.print("[bold yellow]【1】系統初始化[/bold yellow]\n")
    
    # 配置
    risk_limits = RiskLimits(
        max_position_size=4,
        max_daily_loss=5000,
        max_drawdown=0.10,
        stop_loss_pts=30,
        break_even_pts=30,
    )
    
    signal_config = SignalConfig(
        entry_score_threshold=30,
        mom_state_long=2,
        mom_state_short=1,
        use_open_signal=True,
        use_squeeze=True,
        use_pullback=True,
    )
    
    capital_config = CapitalConfig(
        initial_capital=100000,
        max_capital_usage=0.5,
        risk_per_trade=0.02,
        margin_per_lot=25000,
    )
    
    # 初始化
    risk_manager = RiskManager(risk_limits)
    signal_generator = SignalGenerator(signal_config)
    capital_manager = CapitalManager(capital_config)
    
    console.print("[green]✓[/green] Risk Manager: 停損監控就緒")
    console.print("[green]✓[/green] Signal Generator: 開盤買進就緒")
    console.print("[green]✓[/green] Capital Manager: 資金控制就緒")
    console.print()
    
    # ========== 載入數據 ==========
    console.print("[bold yellow]【2】市場數據載入[/bold yellow]\n")
    
    # 使用 ^TWII 數據模擬 TMF 期貨
    dm = DataManager("data/taifex_raw")
    df = dm.load_yahoo("^TWII", period="60d", interval="5m")
    df = dm.add_indicators(df, indicators=['squeeze', 'vwap'])
    
    if df.empty:
        console.print("[red]✗ 無法載入數據[/red]")
        return
    
    console.print(f"[green]✓[/green] 載入 {len(df)} 筆 5m K 棒")
    console.print(f"[dim]時間範圍：{df.index[0]} ~ {df.index[-1]}[/dim]\n")
    
    # ========== 交易模擬 ==========
    console.print("[bold yellow]【3】交易信號模擬[/bold yellow]\n")
    
    symbol = "TMF"
    position = None
    trades = []
    equity_curve = [capital_config.initial_capital]
    
    for i in range(len(df)):
        current_df = df.iloc[:i+1].copy()
        current_price = current_df.iloc[-1]['Close']
        timestamp = current_df.index[-1]
        
        # 更新權益曲線
        if position:
            unrealized_pnl = (current_price - position['entry_price']) * position['direction'] * position['size'] * 10
            current_equity = capital_config.initial_capital + sum(t['pnl'] for t in trades) + unrealized_pnl
        else:
            current_equity = capital_config.initial_capital + sum(t['pnl'] for t in trades)
        
        equity_curve.append(current_equity)
        
        # 生成信號
        if position is None:
            signal = signal_generator.generate_squeeze_signal(symbol, current_df)
            
            if signal:
                # 進場
                stop_loss = current_price - 30 * signal.direction
                sizing = capital_manager.calculate_position_size(
                    symbol=symbol,
                    entry_price=current_price,
                    stop_loss_price=stop_loss,
                )
                
                position = {
                    'symbol': symbol,
                    'direction': signal.direction,
                    'entry_price': current_price,
                    'entry_time': timestamp,
                    'size': sizing.lots,
                    'stop_loss': stop_loss,
                }
                
                risk_manager.update_position(
                    symbol=symbol,
                    direction=signal.direction,
                    size=sizing.lots,
                    entry_price=current_price,
                    current_price=current_price,
                )
                
                trades.append({
                    'type': 'ENTRY',
                    'time': timestamp,
                    'price': current_price,
                    'direction': signal.direction,
                    'size': sizing.lots,
                })
        
        else:
            # 檢查出場
            exit_reason = None
            
            # 停損檢查
            if position['direction'] > 0:
                if current_price <= position['stop_loss']:
                    exit_reason = 'STOP_LOSS'
                elif (current_price - position['entry_price']) * 10 >= 300:  # 30 點獲利
                    exit_reason = 'TAKE_PROFIT'
            else:
                if current_price >= position['stop_loss']:
                    exit_reason = 'STOP_LOSS'
                elif (position['entry_price'] - current_price) * 10 >= 300:
                    exit_reason = 'TAKE_PROFIT'
            
            # 收盤強制平倉
            if timestamp.hour >= 13 and position:
                exit_reason = 'EOD_CLOSE'
            
            if exit_reason:
                # 出場
                pnl = (current_price - position['entry_price']) * position['direction'] * position['size'] * 10
                
                capital_manager.record_trade_result(pnl)
                risk_manager.record_trade({'pnl': pnl})
                
                trades.append({
                    'type': 'EXIT',
                    'time': timestamp,
                    'price': current_price,
                    'pnl': pnl,
                    'exit_reason': exit_reason,
                })
                
                console.print(
                    f"[bold {'green' if pnl > 0 else 'red'}]"
                    f"{'✓' if pnl > 0 else '✗'} EXIT: {symbol} @ {current_price:.0f}, "
                    f"PnL: {pnl:,+0f} TWD ({exit_reason})"
                    f"[/bold {'green' if pnl > 0 else 'red'}]"
                )
                
                position = None
    
    # ========== 生成報告 ==========
    console.print("\n[bold yellow]【4】完整業務報告[/bold yellow]\n")
    
    # 1. 交易摘要
    console.print(Panel(
        f"[bold]Total Trades:[/bold] {len([t for t in trades if t['type'] == 'EXIT'])}\n"
        f"[bold]Winning Trades:[/bold] {len([t for t in trades if t['type'] == 'EXIT' and t.get('pnl', 0) > 0])}\n"
        f"[bold]Losing Trades:[/bold] {len([t for t in trades if t['type'] == 'EXIT' and t.get('pnl', 0) < 0])}",
        title="📊 Trading Summary",
        border_style="blue",
    ))
    console.print()
    
    # 2. 績效指標
    if trades:
        exits = [t for t in trades if t['type'] == 'EXIT' and 'pnl' in t]
        if exits:
            total_pnl = sum(t['pnl'] for t in exits)
            win_rate = len([t for t in exits if t['pnl'] > 0]) / len(exits) * 100
            avg_pnl = np.mean([t['pnl'] for t in exits])
            best_trade = max(t['pnl'] for t in exits)
            worst_trade = min(t['pnl'] for t in exits)
            
            # 計算權益曲線指標
            equity_array = np.array(equity_curve)
            peak = np.maximum.accumulate(equity_array)
            drawdown = (peak - equity_array) / peak * 100
            max_dd = np.max(drawdown)
            
            table = Table(title="📈 Performance Metrics")
            table.add_column("Metric", style="cyan")
            table.add_column("Value", justify="right")
            
            table.add_row("Total PnL", f"{total_pnl:,+0f} TWD")
            table.add_row("Win Rate", f"{win_rate:.1f}%")
            table.add_row("Avg Trade", f"{avg_pnl:,.0f} TWD")
            table.add_row("Best Trade", f"{best_trade:,+0f} TWD")
            table.add_row("Worst Trade", f"{worst_trade:,.0f} TWD")
            table.add_row("Max Drawdown", f"{max_dd:.2f}%")
            
            console.print(table)
            console.print()
    
    # 3. 風險報告
    risk_manager.print_risk_report()
    console.print()
    
    # 4. 資金報告
    capital_manager.print_capital_report()
    console.print()
    
    # 5. 交易明細
    if trades:
        trade_df = pd.DataFrame(trades)
        console.print(Panel(
            trade_df.to_string(index=False),
            title="📝 Trade Log",
            border_style="dim",
        ))
        console.print()
    
    # 6. 量化分析
    if len(equity_curve) > 1:
        console.print("[bold yellow]【5】量化分析報告[/bold yellow]\n")
        
        analytics = QuantAnalytics(
            equity_curve=np.array(equity_curve),
            pnl=np.array([t.get('pnl', 0) for t in trades if t['type'] == 'EXIT']),
            initial_balance=capital_config.initial_capital,
        )
        
        analytics.print_report()
        console.print()
    
    # ========== 最終總結 ==========
    console.print("[bold blue]╔" + "═" * 78 + "╗[/bold blue]")
    console.print("[bold blue]║[/bold blue]" + " " * 30 + "DRY RUN COMPLETE" + " " * 34 + "[bold blue]║[/bold blue]")
    console.print("[bold blue]╚" + "═" * 78 + "╝[/bold blue]")


if __name__ == "__main__":
    simulate_full_day_trading()

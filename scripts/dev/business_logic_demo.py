#!/usr/bin/env python3
"""
業務邏輯整合演示
展示如何使用 RiskManager, SignalGenerator, CapitalManager, PerformanceOptimizer
"""

import sys
import os
import numpy as np
from pathlib import Path
from rich.console import Console

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from squeeze_futures.business import (
    RiskManager, RiskLimits,
    SignalGenerator, SignalConfig,
    CapitalManager, CapitalConfig,
    PerformanceOptimizer,
)
from squeeze_futures.engine import DataManager

console = Console()


def main():
    """主函數"""
    console.print("[bold blue]=== Squeeze Futures Business Logic Demo ===[/bold blue]\n")
    
    # ========== 1. 初始化 ==========
    console.print("[bold yellow]1. 初始化業務模組[/bold yellow]\n")
    
    # 風險管理
    risk_limits = RiskLimits(
        max_position_size=4,
        max_daily_loss=5000,
        max_drawdown=0.10,
        stop_loss_pts=30,
    )
    risk_manager = RiskManager(risk_limits)
    
    # 信號生成
    signal_config = SignalConfig(
        entry_score_threshold=30,
        use_open_signal=True,
        use_squeeze=True,
        use_pullback=True,
    )
    signal_generator = SignalGenerator(signal_config)
    
    # 資金控制
    capital_config = CapitalConfig(
        initial_capital=100000,
        max_capital_usage=0.5,
        risk_per_trade=0.02,
    )
    capital_manager = CapitalManager(capital_config)
    
    # 速度優化
    optimizer = PerformanceOptimizer()
    
    console.print("[green]✓ All business modules initialized[/green]\n")
    
    # ========== 2. 載入數據 ==========
    console.print("[bold yellow]2. 載入市場數據[/bold yellow]\n")
    
    dm = DataManager("data/taifex_raw")
    df = dm.load_yahoo("^TWII", period="60d", interval="5m")
    df = dm.add_indicators(df, indicators=['squeeze', 'vwap'])
    
    if df.empty:
        console.print("[red]無法載入數據[/red]")
        return
    
    console.print(f"[green]✓ 載入 {len(df)} 筆數據[/green]\n")
    
    # ========== 3. 模擬交易流程 ==========
    console.print("[bold yellow]3. 模擬交易流程[/bold yellow]\n")
    
    symbol = "TMF"
    position = None
    
    for i in range(len(df)):
        current_df = df.iloc[:i+1]
        current_price = current_df.iloc[-1]['Close']
        timestamp = current_df.index[-1]
        
        # 生成信號
        signal = signal_generator.generate_squeeze_signal(symbol, current_df)
        
        if signal and position is None:
            # 進場
            position = {
                'symbol': symbol,
                'direction': signal.direction,
                'entry_price': current_price,
                'size': 2,
            }
            
            # 更新風險管理
            risk_manager.update_position(
                symbol=symbol,
                direction=signal.direction,
                size=2,
                entry_price=current_price,
                current_price=current_price,
            )
            
            # 計算部位
            stop_loss = current_price - 30 * signal.direction
            sizing = capital_manager.calculate_position_size(
                symbol=symbol,
                entry_price=current_price,
                stop_loss_price=stop_loss,
            )
            
            console.print(f"[bold green]✓ ENTRY: {symbol} {'LONG' if signal.direction > 0 else 'SHORT'} "
                         f"@ {current_price:.0f} ({sizing.lots} lots)[/bold green]\n")
        
        elif position:
            # 檢查停損
            stop_loss = position['entry_price'] - 30 * position['direction']
            exit_signal = risk_manager.check_stop_loss(symbol, current_price)
            
            if exit_signal:
                # 出場
                pnl = (current_price - position['entry_price']) * position['direction'] * position['size'] * 10
                
                capital_manager.record_trade_result(pnl)
                risk_manager.record_trade({'pnl': pnl})
                
                console.print(f"[bold {'green' if pnl > 0 else 'red'}]"
                             f"✓ EXIT: {symbol} @ {current_price:.0f}, PnL: {pnl:,.0f} TWD[/bold {'green' if pnl > 0 else 'red'}]\n")
                
                position = None
    
    # ========== 4. 打印報告 ==========
    console.print("[bold yellow]4. 業務報告[/bold yellow]\n")
    
    # 風險報告
    risk_manager.print_risk_report()
    console.print()
    
    # 資金報告
    capital_manager.print_capital_report()
    console.print()
    
    # 信號報告
    signal_generator.print_signal_report()
    console.print()
    
    # 效能建議
    recs = optimizer.recommend_optimization(len(df))
    console.print("[bold blue]Performance Recommendations:[/bold blue]")
    for key, value in recs.items():
        console.print(f"  {key}: {value}")
    
    console.print("\n[bold green]=== Demo Complete ===[/bold green]")


if __name__ == "__main__":
    main()

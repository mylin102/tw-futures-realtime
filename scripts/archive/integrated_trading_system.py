#!/usr/bin/env python3
"""
完整交易系統整合腳本
整合數據、信號、風險管理、資金控制於一體
"""

import sys
import os
import time
from datetime import datetime
from pathlib import Path
from rich.console import Console
from rich.panel import Panel

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from squeeze_futures.business import (
    RiskManager, RiskLimits,
    SignalGenerator, SignalConfig,
    CapitalManager, CapitalConfig,
)
from squeeze_futures.engine import DataManager
from squeeze_futures.data.shioaji_client import ShioajiClient

console = Console()


class TradingSystem:
    """
    完整交易系統
    
    整合：
    - 數據管理
    - 信號生成
    - 風險管理
    - 資金控制
    - 訂單執行
    """
    
    def __init__(self, config: dict):
        """
        Args:
            config: 系統配置字典
        """
        console.print("[bold blue]╔" + "═" * 60 + "╗[/bold blue]")
        console.print("[bold blue]║[/bold blue]" + " " * 20 + "INITIALIZING TRADING SYSTEM" + " " * 14 + "[bold blue]║[/bold blue]")
        console.print("[bold blue]╚" + "═" * 60 + "╝[/bold blue]\n")
        
        # 1. 風險管理
        self.risk_manager = RiskManager(RiskLimits(
            max_position_size=config.get('max_position_size', 4),
            max_daily_loss=config.get('max_daily_loss', 5000),
            max_drawdown=config.get('max_drawdown', 0.10),
            stop_loss_pts=config.get('stop_loss_pts', 30),
            break_even_pts=config.get('break_even_pts', 30),
        ))
        
        # 2. 信號生成
        self.signal_generator = SignalGenerator(SignalConfig(
            entry_score_threshold=config.get('entry_score', 30),
            mom_state_long=config.get('mom_state_long', 2),
            mom_state_short=config.get('mom_state_short', 1),
            use_open_signal=config.get('use_open_signal', True),
            use_squeeze=config.get('use_squeeze', True),
            use_pullback=config.get('use_pullback', True),
        ))
        
        # 3. 資金控制
        self.capital_manager = CapitalManager(CapitalConfig(
            initial_capital=config.get('initial_capital', 100000),
            max_capital_usage=config.get('max_capital_usage', 0.5),
            risk_per_trade=config.get('risk_per_trade', 0.02),
            margin_per_lot=config.get('margin_per_lot', 25000),
        ))
        
        # 4. 數據管理
        self.data_manager = DataManager(config.get('data_dir', 'data/taifex_raw'))
        
        # 5. Shioaji API (可選)
        self.use_shioaji = config.get('use_shioaji', False)
        if self.use_shioaji:
            self.shioaji = ShioajiClient()
            self.shioaji.login()
        else:
            self.shioaji = None
        
        self.config = config
        self.position = None
        self.running = False
        
        console.print("\n[green]✓ 交易系統初始化完成[/green]\n")
    
    def load_data(self):
        """載入市場數據"""
        console.print("[bold yellow]載入市場數據...[/bold yellow]")
        
        if self.use_shioaji and self.shioaji:
            # 使用 Shioaji 即時數據
            df = self.shioaji.get_kline("TMF", interval="5m")
            if df is not None and not df.empty:
                console.print(f"[green]✓ 從 Shioaji 載入 {len(df)} 筆數據[/green]")
                return df
        
        # 使用 Yahoo Finance 數據
        df = self.data_manager.load_yahoo("^TWII", period="60d", interval="5m")
        df = self.data_manager.add_indicators(df, indicators=['squeeze', 'vwap'])
        
        console.print(f"[green]✓ 載入 {len(df)} 筆數據[/green]")
        return df
    
    def run_backtest(self, df: pd.DataFrame):
        """執行回測"""
        console.print("\n[bold yellow]執行回測...[/bold yellow]\n")
        
        symbol = "TMF"
        trades = []
        equity_curve = [self.capital_manager.config.initial_capital]
        
        for i in range(len(df)):
            current_df = df.iloc[:i+1].copy()
            current_price = current_df.iloc[-1]['Close']
            timestamp = current_df.index[-1]
            
            # 更新權益
            if self.position:
                unrealized = (current_price - self.position['entry']) * self.position['direction'] * self.position['size'] * 10
                current_equity = equity_curve[-1] + unrealized
            else:
                current_equity = equity_curve[-1]
            
            equity_curve.append(current_equity)
            
            # 生成信號
            if self.position is None:
                signal = self.signal_generator.generate_squeeze_signal(symbol, current_df)
                
                if signal:
                    # 進場
                    stop_loss = current_price - 30 * signal.direction
                    sizing = self.capital_manager.calculate_position_size(
                        symbol=symbol,
                        entry_price=current_price,
                        stop_loss_price=stop_loss,
                    )
                    
                    self.position = {
                        'symbol': symbol,
                        'direction': signal.direction,
                        'entry': current_price,
                        'time': timestamp,
                        'size': sizing.lots,
                        'stop_loss': stop_loss,
                    }
                    
                    self.risk_manager.update_position(
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
                    })
            
            else:
                # 檢查出場
                exit_reason = None
                
                if self.position['direction'] > 0:
                    if current_price <= self.position['stop_loss']:
                        exit_reason = 'STOP_LOSS'
                    elif (current_price - self.position['entry']) * 10 >= 300:
                        exit_reason = 'TAKE_PROFIT'
                else:
                    if current_price >= self.position['stop_loss']:
                        exit_reason = 'STOP_LOSS'
                    elif (self.position['entry'] - current_price) * 10 >= 300:
                        exit_reason = 'TAKE_PROFIT'
                
                if exit_reason:
                    # 出場
                    pnl = (current_price - self.position['entry']) * self.position['direction'] * self.position['size'] * 10
                    
                    self.capital_manager.record_trade_result(pnl)
                    self.risk_manager.record_trade({'pnl': pnl})
                    
                    trades.append({
                        'type': 'EXIT',
                        'time': timestamp,
                        'price': current_price,
                        'pnl': pnl,
                        'reason': exit_reason,
                    })
                    
                    console.print(
                        f"[bold {'green' if pnl > 0 else 'red'}]"
                        f"{'✓' if pnl > 0 else '✗'} EXIT: {symbol} @ {current_price:.0f}, "
                        f"PnL: {pnl:,+0f} TWD ({exit_reason})"
                        f"[/bold {'green' if pnl > 0 else 'red'}]"
                    )
                    
                    self.position = None
        
        return trades, equity_curve
    
    def print_report(self, trades: list, equity_curve: list):
        """打印報告"""
        from squeeze_futures.engine.analytics import QuantAnalytics
        import numpy as np
        
        console.print("\n[bold yellow]=== 交易報告 ===[/bold yellow]\n")
        
        # 交易摘要
        exits = [t for t in trades if t['type'] == 'EXIT']
        
        if exits:
            total_pnl = sum(t['pnl'] for t in exits)
            win_rate = len([t for t in exits if t['pnl'] > 0]) / len(exits) * 100
            avg_pnl = np.mean([t['pnl'] for t in exits])
            
            console.print(Panel(
                f"[bold]總交易:[/bold] {len(exits)}\n"
                f"[bold]總損益:[/bold] {total_pnl:,+0f} TWD\n"
                f"[bold]勝率:[/bold] {win_rate:.1f}%\n"
                f"[bold]平均損益:[/bold] {avg_pnl:,.0f} TWD",
                title="📊 Trading Summary",
                border_style="blue",
            ))
        
        # 量化分析
        if len(equity_curve) > 1:
            analytics = QuantAnalytics(
                equity_curve=np.array(equity_curve),
                pnl=np.array([t.get('pnl', 0) for t in exits]),
                initial_balance=self.capital_manager.config.initial_capital,
            )
            
            console.print()
            analytics.print_report()
        
        # 風險報告
        console.print()
        self.risk_manager.print_risk_report()
        
        # 資金報告
        console.print()
        self.capital_manager.print_capital_report()
    
    def run(self):
        """運行交易系統"""
        self.running = True
        
        # 載入數據
        df = self.load_data()
        
        if df is None or df.empty:
            console.print("[red]✗ 無法載入數據，系統終止[/red]")
            return
        
        # 執行回測
        trades, equity_curve = self.run_backtest(df)
        
        # 打印報告
        self.print_report(trades, equity_curve)
        
        console.print("\n[bold green]✓ 交易系統運行完成[/bold green]")
        
        self.running = False


def main():
    """主函數"""
    # 系統配置
    config = {
        # 風險管理
        'max_position_size': 4,
        'max_daily_loss': 5000,
        'max_drawdown': 0.10,
        'stop_loss_pts': 30,
        'break_even_pts': 30,
        
        # 信號生成
        'entry_score': 30,
        'mom_state_long': 2,
        'mom_state_short': 1,
        'use_open_signal': True,
        'use_squeeze': True,
        'use_pullback': True,
        
        # 資金控制
        'initial_capital': 100000,
        'max_capital_usage': 0.5,
        'risk_per_trade': 0.02,
        'margin_per_lot': 25000,
        
        # 數據
        'data_dir': 'data/taifex_raw',
        
        # Shioaji (設為 False 使用 Yahoo Finance)
        'use_shioaji': False,
    }
    
    # 創建並運行系統
    system = TradingSystem(config)
    system.run()


if __name__ == "__main__":
    import pandas as pd
    main()

#!/usr/bin/env python3
"""
策略比較回測：改進版 vs Pine Script 趨勢跟隨

Pine Script 策略邏輯：
- EMA 交叉 (20/60)
- ATR 動態停損 (2x ATR)
- 簡單趋势跟隨

改進版策略邏輯：
- Squeeze + MTF 對齊
- 移動停損
- 時間過濾
"""

import sys
import os
import pandas as pd
import numpy as np
from datetime import datetime
from pathlib import Path
from rich.console import Console
from rich.table import Table

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from squeeze_futures.engine import DataManager
from squeeze_futures.engine.indicators import calculate_futures_squeeze, calculate_mtf_alignment, calculate_atr
from squeeze_futures.engine.simulator import PaperTrader
from squeeze_futures.engine.constants import get_point_value

console = Console()


class PineTrendFollower:
    """
    Pine Script 趨勢跟隨策略
    
    邏輯：
    - EMA 交叉 (20/60)
    - ATR 動態停損 (2x ATR)
    - 收盤價 > EMA Short 確認
    """
    
    def __init__(self, df: pd.DataFrame, config: dict):
        """
        Args:
            df: OHLCV 數據
            config: 策略配置
        """
        self.df = df.copy()
        self.config = config
        
        # 計算指標
        self.df['ema_short'] = self.df['Close'].rolling(window=20).mean()
        self.df['ema_long'] = self.df['Close'].rolling(window=60).mean()
        self.df['atr'] = calculate_atr(self.df)
        
        # 交易記錄
        self.trades = []
        self.position = None
        self.equity_curve = [config.get('initial_balance', 100000)]
    
    def run_backtest(self) -> dict:
        """執行回測"""
        initial_balance = self.config.get('initial_balance', 100000)
        point_value = self.config.get('point_value', 10)
        lots = self.config.get('lots', 2)
        atr_multiplier = self.config.get('atr_multiplier', 2.0)
        
        balance = initial_balance
        
        for i in range(1, len(self.df)):
            row = self.df.iloc[i]
            prev_row = self.df.iloc[i-1]
            
            # 檢查 EMA 交叉
            ema_cross = (
                prev_row['ema_short'] <= prev_row['ema_long'] and
                row['ema_short'] > row['ema_long']
            )
            
            # 進場條件：EMA 交叉 + 收盤價 > EMA Short
            long_condition = ema_cross and row['Close'] > row['ema_short']
            
            # 進場
            if long_condition and self.position is None:
                self.position = {
                    'type': 'long',
                    'entry_price': row['Close'],
                    'entry_time': row.name,
                    'atr': row['atr'],
                    'stop_loss': row['Close'] - atr_multiplier * row['atr'],
                }
                
                self.trades.append({
                    'type': 'ENTRY',
                    'time': row.name,
                    'price': row['Close'],
                    'direction': 'long',
                })
            
            # 出場檢查
            elif self.position:
                # 更新移動停損
                if row['atr'] > 0:
                    new_stop = row['Close'] - atr_multiplier * row['atr']
                    if new_stop > self.position['stop_loss']:
                        self.position['stop_loss'] = new_stop
                
                # 停損檢查
                if row['Low'] <= self.position['stop_loss']:
                    exit_price = self.position['stop_loss']
                    pnl_pts = exit_price - self.position['entry_price']
                    pnl_cash = pnl_pts * point_value * lots
                    
                    balance += pnl_cash
                    
                    self.trades.append({
                        'type': 'EXIT',
                        'time': row.name,
                        'price': exit_price,
                        'pnl': pnl_cash,
                        'reason': 'STOP_LOSS',
                    })
                    
                    self.position = None
        
        # 平倉未平部位
        if self.position:
            exit_price = self.df.iloc[-1]['Close']
            pnl_pts = exit_price - self.position['entry_price']
            pnl_cash = pnl_pts * point_value * lots
            balance += pnl_cash
            
            self.trades.append({
                'type': 'EXIT',
                'time': self.df.index[-1],
                'price': exit_price,
                'pnl': pnl_cash,
                'reason': 'EOD',
            })
        
        # 計算績效指標
        exits = [t for t in self.trades if t['type'] == 'EXIT']
        
        if exits:
            total_pnl = sum(t['pnl'] for t in exits)
            winning = [t for t in exits if t['pnl'] > 0]
            losing = [t for t in exits if t['pnl'] < 0]
            
            win_rate = len(winning) / len(exits) * 100 if exits else 0
            avg_pnl = np.mean([t['pnl'] for t in exits])
            
            gross_profit = sum(t['pnl'] for t in winning) if winning else 0
            gross_loss = abs(sum(t['pnl'] for t in losing)) if losing else 0
            profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')
        else:
            total_pnl = 0
            win_rate = 0
            avg_pnl = 0
            profit_factor = 0
        
        return {
            'strategy_name': 'Pine Trend Follower',
            'total_pnl': total_pnl,
            'final_balance': balance,
            'total_trades': len(exits),
            'win_rate': win_rate,
            'avg_pnl': avg_pnl,
            'profit_factor': profit_factor,
            'trades': self.trades,
        }


class ImprovedStrategy:
    """
    改進版 Squeeze 策略
    
    邏輯：
    - Squeeze 釋放 + MTF 對齊
    - 進場門檻提高 (score >= 50)
    - 移動停損
    - 時間過濾
    """
    
    def __init__(self, df: pd.DataFrame, config: dict):
        """
        Args:
            df: OHLCV 數據
            config: 策略配置
        """
        self.df = df.copy()
        self.config = config
        
        # 計算指標
        self.df = calculate_futures_squeeze(self.df)
        
        # 交易記錄
        self.trades = []
        self.position = None
        self.equity_curve = [config.get('initial_balance', 100000)]
    
    def run_backtest(self) -> dict:
        """執行回測"""
        initial_balance = self.config.get('initial_balance', 100000)
        point_value = self.config.get('point_value', 10)
        lots = self.config.get('lots', 2)
        
        # 改進版參數
        entry_score = self.config.get('entry_score', 50)
        stop_loss_pts = self.config.get('stop_loss_pts', 50)
        tp1_pts = self.config.get('tp1_pts', 50)
        trailing_trigger = self.config.get('trailing_trigger', 30)
        trailing_distance = self.config.get('trailing_distance', 15)
        
        # 時間過濾：跳過 21, 22 點
        skip_hours = self.config.get('skip_hours', [21, 22])
        
        balance = initial_balance
        has_tp1_hit = False
        
        for i in range(1, len(self.df)):
            row = self.df.iloc[i]
            
            # 時間過濾
            if hasattr(row.name, 'hour') and row.name.hour in skip_hours:
                continue
            
            # 進場條件
            if self.position is None:
                # Squeeze 釋放 + 高分數 + 動能確認
                long_condition = (
                    (not row.get('sqz_on', True)) and
                    row.get('score', 0) >= entry_score and
                    row.get('mom_state', 0) >= 1 and        # 【調整】從 2 降至 1
                    row['Close'] > row.get('vwap', row['Close'])
                )
                
                if long_condition:
                    self.position = {
                        'type': 'long',
                        'entry_price': row['Close'],
                        'entry_time': row.name,
                        'stop_loss': row['Close'] - stop_loss_pts,
                        'take_profit': row['Close'] + tp1_pts,
                    }
                    
                    self.trades.append({
                        'type': 'ENTRY',
                        'time': row.name,
                        'price': row['Close'],
                        'direction': 'long',
                    })
            
            # 出場檢查
            elif self.position:
                # 移動停損
                unrealized_pts = row['Close'] - self.position['entry_price']
                if unrealized_pts >= trailing_trigger:
                    new_stop = row['Close'] - trailing_distance
                    if new_stop > self.position['stop_loss']:
                        self.position['stop_loss'] = new_stop
                
                # 停損/停利檢查
                exit_reason = None
                exit_price = None
                
                if row['Low'] <= self.position['stop_loss']:
                    exit_price = self.position['stop_loss']
                    exit_reason = 'STOP_LOSS'
                elif row['High'] >= self.position['take_profit'] and not has_tp1_hit:
                    exit_price = self.position['take_profit']
                    exit_reason = 'TAKE_PROFIT'
                    has_tp1_hit = True
                
                if exit_price:
                    pnl_pts = exit_price - self.position['entry_price']
                    pnl_cash = pnl_pts * point_value * lots
                    balance += pnl_cash
                    
                    self.trades.append({
                        'type': 'EXIT',
                        'time': row.name,
                        'price': exit_price,
                        'pnl': pnl_cash,
                        'reason': exit_reason,
                    })
                    
                    self.position = None
                    has_tp1_hit = False
        
        # 平倉未平部位
        if self.position:
            exit_price = self.df.iloc[-1]['Close']
            pnl_pts = exit_price - self.position['entry_price']
            pnl_cash = pnl_pts * point_value * lots
            balance += pnl_cash
            
            self.trades.append({
                'type': 'EXIT',
                'time': self.df.index[-1],
                'price': exit_price,
                'pnl': pnl_cash,
                'reason': 'EOD',
            })
        
        # 計算績效指標
        exits = [t for t in self.trades if t['type'] == 'EXIT']
        
        if exits:
            total_pnl = sum(t['pnl'] for t in exits)
            winning = [t for t in exits if t['pnl'] > 0]
            losing = [t for t in exits if t['pnl'] < 0]
            
            win_rate = len(winning) / len(exits) * 100 if exits else 0
            avg_pnl = np.mean([t['pnl'] for t in exits])
            
            gross_profit = sum(t['pnl'] for t in winning) if winning else 0
            gross_loss = abs(sum(t['pnl'] for t in losing)) if losing else 0
            profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')
        else:
            total_pnl = 0
            win_rate = 0
            avg_pnl = 0
            profit_factor = 0
        
        return {
            'strategy_name': 'Improved Squeeze v2',
            'total_pnl': total_pnl,
            'final_balance': balance,
            'total_trades': len(exits),
            'win_rate': win_rate,
            'avg_pnl': avg_pnl,
            'profit_factor': profit_factor,
            'trades': self.trades,
        }


def compare_strategies(df: pd.DataFrame, config: dict):
    """比較兩種策略"""
    console.print("\n[bold blue]╔" + "═" * 70 + "╗[/bold blue]")
    console.print("[bold blue]║[/bold blue]" + " " * 20 + "STRATEGY COMPARISON BACKTEST" + " " * 20 + "[bold blue]║[/bold blue]")
    console.print("[bold blue]╚" + "═" * 70 + "╝[/bold blue]\n")
    
    # 執行 Pine Script 策略回測
    console.print("[yellow]Running Pine Trend Follower...[/yellow]")
    pine_strategy = PineTrendFollower(df, config)
    pine_results = pine_strategy.run_backtest()
    
    # 執行改進版策略回測
    console.print("[yellow]Running Improved Squeeze v2...[/yellow]")
    improved_strategy = ImprovedStrategy(df, config)
    improved_results = improved_strategy.run_backtest()
    
    # 顯示比較結果
    console.print("\n[bold green]=== Backtest Results ===[/bold green]\n")
    
    table = Table(title="Strategy Comparison")
    table.add_column("Metric", style="cyan")
    table.add_column("Pine Trend", justify="right", style="yellow")
    table.add_column("Improved v2", justify="right", style="green")
    table.add_column("Difference", justify="right")
    
    metrics = [
        ('Total PnL', 'total_pnl', 'TWD'),
        ('Final Balance', 'final_balance', 'TWD'),
        ('Total Trades', 'total_trades', ''),
        ('Win Rate', 'win_rate', '%'),
        ('Avg PnL', 'avg_pnl', 'TWD'),
        ('Profit Factor', 'profit_factor', ''),
    ]
    
    for name, key, unit in metrics:
        pine_val = pine_results[key]
        imp_val = improved_results[key]
        diff = imp_val - pine_val
        
        if key in ['total_pnl', 'final_balance', 'avg_pnl']:
            pine_str = f"{pine_val:,.0f} {unit}"
            imp_str = f"{imp_val:,.0f} {unit}"
            diff_str = f"{diff:+,.0f} {unit}"
        elif key == 'win_rate':
            pine_str = f"{pine_val:.1f}{unit}"
            imp_str = f"{imp_val:.1f}{unit}"
            diff_str = f"{diff:+.1f}{unit}"
        else:
            pine_str = str(pine_val)
            imp_str = str(imp_val)
            diff_str = f"{diff:+d}" if key == 'total_trades' else f"{diff:+.2f}"
        
        # 標記較佳值
        is_better = imp_val > pine_val if key not in ['total_trades'] else imp_val < pine_val
        diff_style = "bold green" if is_better else "bold red"
        
        table.add_row(
            name,
            pine_str,
            f"[bold green]{imp_str}[/bold green]",
            f"[{diff_style}]{diff_str}[/{diff_style}]",
        )
    
    console.print(table)
    
    # 交易明細
    console.print("\n[bold yellow]=== Trade Details ===[/bold yellow]\n")
    
    console.print(f"[cyan]Pine Trend Follower ({len(pine_results['trades'])} trades):[/cyan]")
    for trade in pine_results['trades'][:10]:  # 顯示前 10 筆
        if trade['type'] == 'ENTRY':
            console.print(f"  {trade['time'].strftime('%m-%d %H:%M')} {trade['direction'].upper()} @ {trade['price']:.0f}")
        else:
            pnl_style = "green" if trade['pnl'] > 0 else "red"
            console.print(f"  {trade['time'].strftime('%m-%d %H:%M')} EXIT @ {trade['price']:.0f} [bold {pnl_style}]PnL: {trade['pnl']:+,.0f}[/bold {pnl_style}] ({trade['reason']})")
    
    console.print(f"\n[cyan]Improved Squeeze v2 ({len(improved_results['trades'])} trades):[/cyan]")
    for trade in improved_results['trades'][:10]:  # 顯示前 10 筆
        if trade['type'] == 'ENTRY':
            console.print(f"  {trade['time'].strftime('%m-%d %H:%M')} {trade['direction'].upper()} @ {trade['price']:.0f}")
        else:
            pnl_style = "green" if trade['pnl'] > 0 else "red"
            console.print(f"  {trade['time'].strftime('%m-%d %H:%M')} EXIT @ {trade['price']:.0f} [bold {pnl_style}]PnL: {trade['pnl']:+,.0f}[/bold {pnl_style}] ({trade['reason']})")
    
    # 結論
    console.print("\n[bold blue]=== Conclusion ===[/bold blue]\n")
    
    if improved_results['total_pnl'] > pine_results['total_pnl']:
        console.print("[bold green]✓ Improved Squeeze v2 outperforms Pine Trend Follower[/bold green]")
    else:
        console.print("[bold yellow]⚠ Pine Trend Follower outperforms Improved Squeeze v2[/bold yellow]")
    
    if improved_results['win_rate'] > pine_results['win_rate']:
        console.print(f"[bold green]✓ Improved win rate: {improved_results['win_rate']:.1f}% vs {pine_results['win_rate']:.1f}%[/bold green]")
    
    return {
        'pine': pine_results,
        'improved': improved_results,
    }


def main():
    """主函數"""
    console.print("[bold blue]╔" + "═" * 70 + "╗[/bold blue]")
    console.print("[bold blue]║[/bold blue]" + " " * 20 + "NIGHT SESSION BACKTEST" + " " * 26 + "[bold blue]║[/bold blue]")
    console.print("[bold blue]╚" + "═" * 70 + "╝[/bold blue]\n")
    
    # 載入數據
    console.print("[bold yellow]【1】載入市場數據[/bold yellow]\n")
    
    dm = DataManager("data/taifex_raw")
    
    # 使用 ^TWII 數據模擬 TMF (延長至 30 天)
    df = dm.load_yahoo("^TWII", period="30d", interval="5m")
    
    if df.empty:
        console.print("[red]✗ 無法載入數據[/red]")
        return
    
    console.print(f"[green]✓ 載入 {len(df)} 筆 5m K 棒[/green]")
    console.print(f"[dim]時間範圍：{df.index[0]} ~ {df.index[-1]}[/dim]\n")
    
    # 使用全部數據回測 (包含日盤和夜盤)
    # 注意：Yahoo Finance 的^TWII 只有日盤數據
    
    # 回測配置
    config = {
        'initial_balance': 100000,
        'point_value': 10,
        'lots': 2,
        
        # Pine Script 策略參數
        'atr_multiplier': 2.0,
        
        # 改進版策略參數
        'entry_score': 40,           # 【調整】從 50 降至 40，增加進場機會
        'stop_loss_pts': 50,
        'tp1_pts': 50,
        'trailing_trigger': 30,
        'trailing_distance': 15,
        'skip_hours': [],            # 【調整】不禁用夜盤，觀察為主
    }
    
    # 執行比較回測
    results = compare_strategies(df, config)
    
    # 保存結果
    console.print("\n[bold yellow]【3】保存結果[/bold yellow]\n")
    
    import json
    output_dir = Path("exports/backtests")
    output_dir.mkdir(parents=True, exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    # 保存 Pine 結果
    with open(output_dir / f"pine_result_{timestamp}.json", 'w') as f:
        json.dump({
            'total_pnl': results['pine']['total_pnl'],
            'win_rate': results['pine']['win_rate'],
            'total_trades': results['pine']['total_trades'],
            'trades': [
                {k: (v.strftime('%Y-%m-%d %H:%M:%S') if isinstance(v, datetime) else v) 
                 for k, v in t.items()}
                for t in results['pine']['trades']
            ],
        }, f, indent=2, default=str)
    
    # 保存改進版結果
    with open(output_dir / f"improved_result_{timestamp}.json", 'w') as f:
        json.dump({
            'total_pnl': results['improved']['total_pnl'],
            'win_rate': results['improved']['win_rate'],
            'total_trades': results['improved']['total_trades'],
            'trades': [
                {k: (v.strftime('%Y-%m-%d %H:%M:%S') if isinstance(v, datetime) else v) 
                 for k, v in t.items()}
                for t in results['improved']['trades']
            ],
        }, f, indent=2, default=str)
    
    console.print(f"[green]✓ 結果已保存至：{output_dir}[/green]\n")
    
    console.print("[bold blue]╔" + "═" * 70 + "╗[/bold blue]")
    console.print("[bold blue]║[/bold blue]" + " " * 25 + "BACKTEST COMPLETE" + " " * 26 + "[bold blue]║[/bold blue]")
    console.print("[bold blue]╚" + "═" * 70 + "╝[/bold blue]\n")


if __name__ == "__main__":
    main()

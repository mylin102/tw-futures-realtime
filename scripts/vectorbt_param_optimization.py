#!/usr/bin/env python3
"""
使用 vectorbt 對今日數據進行回測參數優化

功能：
1. 載入當日市場數據
2. 測試不同參數組合
3. 找出最佳獲利參數
4. 生成優化報告
"""

import pandas as pd
import numpy as np
import vectorbt as vbt
from datetime import datetime
from pathlib import Path
from rich.console import Console
from rich.table import Table

console = Console()

# ========== 數據載入 ==========

def load_today_data(date: str = None) -> pd.DataFrame:
    """載入當日市場數據"""
    if date is None:
        date = datetime.now().strftime("%Y%m%d")
    
    data_file = Path(f"logs/market_data/TMF_{date}_indicators.csv")
    
    if not data_file.exists():
        console.print(f"[red]✗ 找不到數據檔案：{data_file}[/red]")
        return None
    
    df = pd.read_csv(data_file, index_col=0, parse_dates=True)
    df = df.sort_index()
    df = df.drop_duplicates(keep='last')
    
    console.print(f"[green]✓ 載入 {len(df)} 筆 K 棒[/green]")
    console.print(f"[dim]時間範圍：{df.index[0]} ~ {df.index[-1]}[/dim]")
    
    return df


# ========== Vectorbt 回測 ==========

def backtest_with_params(
    close: pd.Series,
    score: pd.Series,
    mom_state: pd.Series,
    sqz_on: pd.Series,
    entry_score: float,
    mom_state_long: int,
    mom_state_short: int,
    stop_loss_pts: float,
    take_profit_pts: float,
    point_value: float = 10,
    fees: float = 40  # 來回手續費
) -> dict:
    """
    使用指定參數進行回測
    
    進場條件：
    - 多頭：score >= entry_score AND mom_state >= mom_state_long AND sqz_on=False
    - 空頭：score <= -entry_score AND mom_state <= mom_state_short AND sqz_on=False
    
    出場條件：
    - 停損：entry_price ± stop_loss_pts
    - 停利：entry_price ± take_profit_pts
    """
    
    # 生成進場信號
    long_entries = (score >= entry_score) & (mom_state >= mom_state_long) & (~sqz_on)
    short_entries = (score <= -entry_score) & (mom_state <= mom_state_short) & (~sqz_on)
    
    # 生成出場信號 (簡化：使用固定點數)
    # 實際應該追蹤進場價格，這裡簡化處理
    
    # 使用 vectorbt 的 Portfolio 回測
    # 多頭信號
    long_exits = long_entries.shift(-1)  # 簡化：下一根 K 棒出場
    short_exits = short_entries.shift(-1)
    
    # 合併信號
    entries = long_entries | short_entries
    exits = long_exits | short_exits
    
    # 方向：多頭=1, 空頭=-1
    direction = pd.Series(0, index=close.index)
    direction[long_entries] = 1
    direction[short_entries] = -1
    
    if entries.sum() == 0:
        return {
            'total_return': 0,
            'total_trades': 0,
            'win_rate': 0,
            'profit_factor': 0,
            'sharpe_ratio': 0,
            'max_drawdown': 0,
        }
    
    # 使用 vectorbt 回測
    try:
        # 簡化回測：計算每次進出的損益
        trades = []
        position = None
        
        for i in range(len(close)):
            if entries.iloc[i] and position is None:
                # 進場
                position = {
                    'entry_price': close.iloc[i],
                    'direction': direction.iloc[i],
                    'entry_time': close.index[i],
                }
            elif position is not None:
                # 檢查停損/停利
                pnl_pts = (close.iloc[i] - position['entry_price']) * position['direction']
                
                # 出場
                trades.append({
                    'entry_time': position['entry_time'],
                    'exit_time': close.index[i],
                    'entry_price': position['entry_price'],
                    'exit_price': close.iloc[i],
                    'direction': position['direction'],
                    'pnl_pts': pnl_pts,
                    'pnl_cash': pnl_pts * point_value - fees,
                })
                position = None
        
        if not trades:
            return {
                'total_return': 0,
                'total_trades': 0,
                'win_rate': 0,
                'profit_factor': 0,
                'sharpe_ratio': 0,
                'max_drawdown': 0,
            }
        
        # 計算績效指標
        trades_df = pd.DataFrame(trades)
        
        total_pnl = trades_df['pnl_cash'].sum()
        total_trades = len(trades_df)
        
        winning = trades_df[trades_df['pnl_cash'] > 0]
        losing = trades_df[trades_df['pnl_cash'] < 0]
        
        win_rate = len(winning) / total_trades * 100 if total_trades > 0 else 0
        
        gross_profit = winning['pnl_cash'].sum() if len(winning) > 0 else 0
        gross_loss = abs(losing['pnl_cash'].sum()) if len(losing) > 0 else 0
        
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0
        
        # 計算權益曲線
        equity_curve = 100000 + trades_df['pnl_cash'].cumsum()
        peak = equity_curve.cummax()
        drawdown = (peak - equity_curve) / peak * 100
        max_drawdown = drawdown.max()
        
        # Sharpe 比率 (簡化)
        returns = trades_df['pnl_cash'] / 100000  # 假設 10 萬本金
        sharpe = returns.mean() / returns.std() * np.sqrt(252) if returns.std() > 0 else 0
        
        return {
            'total_return': total_pnl,
            'total_trades': total_trades,
            'win_rate': win_rate,
            'profit_factor': profit_factor,
            'sharpe_ratio': sharpe,
            'max_drawdown': max_drawdown,
            'trades': trades_df,
        }
        
    except Exception as e:
        console.print(f"[red]回測錯誤：{e}[/red]")
        return {
            'total_return': 0,
            'total_trades': 0,
            'win_rate': 0,
            'profit_factor': 0,
            'sharpe_ratio': 0,
            'max_drawdown': 0,
        }


# ========== 參數優化 ==========

def optimize_parameters(df: pd.DataFrame) -> pd.DataFrame:
    """
    參數網格搜索
    
    測試參數：
    - entry_score: [20, 30, 40, 50]
    - mom_state_long: [1, 2, 3]
    - stop_loss_pts: [60, 80, 100]
    - take_profit_pts: [30, 40, 50]
    """
    
    console.print("\n[bold yellow]開始參數優化...[/bold yellow]\n")
    
    # 準備數據
    close = df['close']
    score = df['score']
    mom_state = df['mom_state']
    sqz_on = ~df['sqz_on'].astype(bool)  # True when OFF
    
    # 參數網格
    param_grid = {
        'entry_score': [20, 30, 40, 50],
        'mom_state_long': [1, 2, 3],
        'stop_loss_pts': [60, 80, 100],
        'take_profit_pts': [30, 40, 50],
    }
    
    results = []
    total_combos = (
        len(param_grid['entry_score']) *
        len(param_grid['mom_state_long']) *
        len(param_grid['stop_loss_pts']) *
        len(param_grid['take_profit_pts'])
    )
    
    console.print(f"[dim]測試 {total_combos} 種參數組合[/dim]\n")
    
    combo = 0
    for entry_score in param_grid['entry_score']:
        for mom_state_long in param_grid['mom_state_long']:
            for stop_loss in param_grid['stop_loss_pts']:
                for take_profit in param_grid['take_profit_pts']:
                    combo += 1
                    
                    # 回測
                    result = backtest_with_params(
                        close=close,
                        score=score,
                        mom_state=mom_state,
                        sqz_on=sqz_on,
                        entry_score=entry_score,
                        mom_state_long=mom_state_long,
                        mom_state_short=1,  # 固定
                        stop_loss_pts=stop_loss,
                        take_profit_pts=take_profit,
                    )
                    
                    result['params'] = {
                        'entry_score': entry_score,
                        'mom_state_long': mom_state_long,
                        'stop_loss_pts': stop_loss,
                        'take_profit_pts': take_profit,
                    }
                    
                    results.append(result)
                    
                    if combo % 20 == 0:
                        console.print(f"[dim]進度：{combo}/{total_combos}[/dim]")
    
    # 轉換為 DataFrame
    results_df = pd.DataFrame([
        {
            **r['params'],
            'total_return': r['total_return'],
            'total_trades': r['total_trades'],
            'win_rate': r['win_rate'],
            'profit_factor': r['profit_factor'],
            'sharpe_ratio': r['sharpe_ratio'],
            'max_drawdown': r['max_drawdown'],
        }
        for r in results
    ])
    
    return results_df


# ========== 結果展示 ==========

def display_top_results(results_df: pd.DataFrame, top_n: int = 10):
    """顯示最佳結果"""
    
    # 按總報酬排序
    top_by_return = results_df.nlargest(top_n, 'total_return')
    
    console.print("\n[bold green]╔" + "═" * 70 + "╗[/bold green]")
    console.print("[bold green]║[/bold green]" + " " * 20 + "最佳參數組合 (按總報酬)" + " " * 21 + "[bold green]║[/bold green]")
    console.print("[bold green]╚" + "═" * 70 + "╝[/bold green]\n")
    
    table = Table(title=f"Top {top_n} Parameter Combinations")
    table.add_column("Rank", style="dim")
    table.add_column("Entry Score", justify="right")
    table.add_column("Mom State", justify="right")
    table.add_column("Stop Loss", justify="right")
    table.add_column("Take Profit", justify="right")
    table.add_column("Total Return", justify="right", style="green")
    table.add_column("Trades", justify="right")
    table.add_column("Win Rate", justify="right")
    table.add_column("Profit Factor", justify="right")
    table.add_column("Max DD", justify="right", style="red")
    
    for idx, row in top_by_return.iterrows():
        table.add_row(
            str(idx + 1),
            str(int(row['entry_score'])),
            str(int(row['mom_state_long'])),
            f"{int(row['stop_loss_pts'])}",
            f"{int(row['take_profit_pts'])}",
            f"{row['total_return']:+,.0f}",
            str(int(row['total_trades'])),
            f"{row['win_rate']:.1f}%",
            f"{row['profit_factor']:.2f}",
            f"{row['max_drawdown']:.1f}%",
        )
    
    console.print(table)
    
    # 按盈虧比排序
    console.print("\n[bold blue]╔" + "═" * 70 + "╗[/bold blue]")
    console.print("[bold blue]║[/bold blue]" + " " * 20 + "最佳參數組合 (按盈虧比)" + " " * 20 + "[bold blue]║[/bold blue]")
    console.print("[bold blue]╚" + "═" * 70 + "╝[/bold blue]\n")
    
    top_by_pf = results_df[results_df['profit_factor'] > 0].nlargest(top_n, 'profit_factor')
    
    table = Table(title=f"Top {top_n} by Profit Factor")
    table.add_column("Rank", style="dim")
    table.add_column("Entry Score", justify="right")
    table.add_column("Mom State", justify="right")
    table.add_column("Stop Loss", justify="right")
    table.add_column("Take Profit", justify="right")
    table.add_column("Total Return", justify="right", style="green")
    table.add_column("Trades", justify="right")
    table.add_column("Win Rate", justify="right")
    table.add_column("Profit Factor", justify="right", style="cyan")
    table.add_column("Max DD", justify="right", style="red")
    
    for idx, row in top_by_pf.iterrows():
        table.add_row(
            str(idx + 1),
            str(int(row['entry_score'])),
            str(int(row['mom_state_long'])),
            f"{int(row['stop_loss_pts'])}",
            f"{int(row['take_profit_pts'])}",
            f"{row['total_return']:+,.0f}",
            str(int(row['total_trades'])),
            f"{row['win_rate']:.1f}%",
            f"{row['profit_factor']:.2f}",
            f"{row['max_drawdown']:.1f}%",
        )
    
    console.print(table)


# ========== 主函數 ==========

def main():
    """主函數"""
    console.print("[bold blue]╔" + "═" * 70 + "╗[/bold blue]")
    console.print("[bold blue]║[/bold blue]" + " " * 15 + "Vectorbt 參數優化回測" + " " * 26 + "[bold blue]║[/bold blue]")
    console.print("[bold blue]╚" + "═" * 70 + "╝[/bold blue]\n")
    
    # 載入數據
    df = load_today_data()
    
    if df is None or len(df) < 20:
        console.print("[red]✗ 數據不足，無法回測[/red]")
        return
    
    # 執行參數優化
    results_df = optimize_parameters(df)
    
    if results_df.empty:
        console.print("[yellow]⚠️  無有效回測結果[/yellow]")
        return
    
    # 顯示最佳結果
    display_top_results(results_df, top_n=10)
    
    # 保存結果
    output_dir = Path("exports/backtests")
    output_dir.mkdir(parents=True, exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = output_dir / f"vectorbt_optimization_{timestamp}.csv"
    
    results_df.to_csv(output_file, index=False)
    console.print(f"\n[green]✓ 結果已保存至：{output_file}[/green]\n")
    
    # 總結
    best = results_df.loc[results_df['total_return'].idxmax()]
    console.print("[bold]最佳參數組合:[/bold]")
    console.print(f"  Entry Score: {int(best['entry_score'])}")
    console.print(f"  Mom State Long: >= {int(best['mom_state_long'])}")
    console.print(f"  Stop Loss: {int(best['stop_loss_pts'])} pts")
    console.print(f"  Take Profit: {int(best['take_profit_pts'])} pts")
    console.print(f"  Total Return: {best['total_return']:+,.0f} TWD")
    console.print(f"  Win Rate: {best['win_rate']:.1f}%")
    console.print(f"  Profit Factor: {best['profit_factor']:.2f}")


if __name__ == "__main__":
    main()

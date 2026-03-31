#!/usr/bin/env python3
"""
參數優化腳本 (Parameter Optimization)

使用向量化回測引擎進行參數網格搜索

優化目標：
- 最大化總報酬
- 最大化 Sharpe 比率
- 最小化最大回撤
- 最小化 Ulcer Index
"""

import sys
import os
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime
from rich.console import Console
from rich.table import Table
from itertools import product

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from squeeze_futures.engine import (
    DataManager,
    VectorizedSimulator,
    SimulatorConfig,
)
from squeeze_futures.engine.analytics import QuantAnalytics

console = Console()


def run_parameter_optimization():
    """執行參數優化"""
    console.print("[bold blue]╔" + "═" * 70 + "╗[/bold blue]")
    console.print("[bold blue]║[/bold blue]" + " " * 20 + "PARAMETER OPTIMIZATION" + " " * 26 + "[bold blue]║[/bold blue]")
    console.print("[bold blue]╚" + "═" * 70 + "╝[/bold blue]\n")
    
    # ========== 1. 載入數據 ==========
    console.print("[bold yellow]【1】載入市場數據[/bold yellow]\n")
    
    dm = DataManager("data/taifex_raw")
    df = dm.load_yahoo("^TWII", period="60d", interval="5m")
    df = dm.add_indicators(df, indicators=['squeeze', 'vwap'])
    
    if df.empty:
        console.print("[red]✗ 無法載入數據[/red]")
        return
    
    console.print(f"[green]✓ 載入 {len(df)} 筆 5m K 棒[/green]")
    console.print(f"[dim]時間範圍：{df.index[0]} ~ {df.index[-1]}[/dim]\n")
    
    # ========== 2. 定義參數網格 ==========
    console.print("[bold yellow]【2】定義參數網格[/bold yellow]\n")
    
    param_grid = {
        'entry_score': [20, 30, 40, 50],
        'mom_state_long': [2, 3],
        'mom_state_short': [0, 1],
        'stop_loss_pts': [20, 30, 40],
        'tp1_pts': [20, 30, 40],
    }
    
    # 計算組合數
    n_combinations = 1
    for values in param_grid.values():
        n_combinations *= len(values)
    
    console.print(f"[dim]測試 {n_combinations} 種參數組合[/dim]\n")
    
    # ========== 3. 執行回測 ==========
    console.print("[bold yellow]【3】執行向量化回測[/bold yellow]\n")
    
    config = SimulatorConfig(
        initial_balance=100000,
        point_value=10,
        fee_per_side=20,
        exchange_fee=0,
        tax_rate=0.00002,
        max_positions=2,
        lots_per_trade=2,
    )
    
    sim = VectorizedSimulator(df, config)
    
    results = []
    progress = 0
    
    for combo in product(*param_grid.values()):
        params = dict(zip(param_grid.keys(), combo))
        
        result = sim.run(**params)
        
        metrics = result['metrics']
        metrics['params'] = params
        results.append(metrics)
        
        progress += 1
        if progress % 20 == 0:
            console.print(f"[dim]進度：{progress}/{n_combinations}[/dim]")
    
    # ========== 4. 分析結果 ==========
    console.print("\n[bold yellow]【4】分析回測結果[/bold yellow]\n")
    
    # 轉換為 DataFrame
    df_results = pd.DataFrame(results)
    
    # 展開 params
    params_df = pd.DataFrame([r['params'] for r in results])
    for col in params_df.columns:
        df_results[f'param_{col}'] = params_df[col]
    
    # 按總報酬排序
    df_sorted = df_results.sort_values('total_return', ascending=False)
    
    # ========== 5. 顯示最佳結果 ==========
    console.print("[bold green]=== 最佳 20 組參數 ===[/bold green]\n")
    
    table = Table(title="Top 20 Parameter Combinations by Total Return")
    table.add_column("Rank", style="dim")
    table.add_column("Entry Score", justify="right")
    table.add_column("MS Long", justify="right")
    table.add_column("MS Short", justify="right")
    table.add_column("SL Pts", justify="right")
    table.add_column("TP1 Pts", justify="right")
    table.add_column("Total Return", justify="right", style="green")
    table.add_column("Sharpe", justify="right")
    table.add_column("Max DD", justify="right", style="red")
    table.add_column("Ulcer", justify="right")
    table.add_column("Recovery", justify="right")
    table.add_column("Trades", justify="right")
    
    for idx, row in df_sorted.head(20).iterrows():
        table.add_row(
            str(idx + 1),
            str(int(row['param_entry_score'])),
            str(int(row['param_mom_state_long'])),
            str(int(row['param_mom_state_short'])),
            str(int(row['param_stop_loss_pts'])),
            str(int(row['param_tp1_pts'])),
            f"{row['total_return']*100:.1f}%",
            f"{row['sharpe_ratio']:.2f}",
            f"{row['max_drawdown']:,.0f}",
            f"{row['ulcer_index']:.1f}",
            f"{row['recovery_factor']:.2f}",
            str(int(row['total_trades'])),
        )
    
    console.print(table)
    
    # ========== 6. 參數影響分析 ==========
    console.print("\n[bold yellow]【5】參數影響分析[/bold yellow]\n")
    
    # Entry Score 影響
    console.print("[cyan]Entry Score 對總報酬的影響:[/cyan]")
    score_analysis = df_results.groupby('param_entry_score')['total_return'].agg(['mean', 'std', 'count']).round(4)
    console.print(score_analysis)
    
    # Stop Loss 影響
    console.print("\n[cyan]Stop Loss 對最大回撤的影響:[/cyan]")
    sl_analysis = df_results.groupby('param_stop_loss_pts')['max_drawdown'].agg(['mean', 'std']).round(2)
    console.print(sl_analysis)
    
    # ========== 7. 建議最佳參數 ==========
    console.print("\n[bold green]=== 建議最佳參數 ===[/bold green]\n")
    
    # 按 Recovery Factor 選擇
    best_by_recovery = df_results.loc[df_results['recovery_factor'].idxmax()]
    
    console.print("[bold]按修復因子 (Recovery Factor) 選擇:[/bold]")
    console.print(f"  Entry Score: {int(best_by_recovery['param_entry_score'])}")
    console.print(f"  Mom State (Long): >= {int(best_by_recovery['param_mom_state_long'])}")
    console.print(f"  Mom State (Short): <= {int(best_by_recovery['param_mom_state_short'])}")
    console.print(f"  Stop Loss: {int(best_by_recovery['param_stop_loss_pts'])} pts")
    console.print(f"  TP1: {int(best_by_recovery['param_tp1_pts'])} pts")
    console.print(f"\n  預期績效:")
    console.print(f"    總報酬：{best_by_recovery['total_return']*100:.1f}%")
    console.print(f"    夏普比率：{best_by_recovery['sharpe_ratio']:.2f}")
    console.print(f"    最大回撤：{best_by_recovery['max_drawdown']:,.0f} TWD")
    console.print(f"    修復因子：{best_by_recovery['recovery_factor']:.2f}")
    console.print(f"    Ulcer Index: {best_by_recovery['ulcer_index']:.1f}")
    
    # ========== 8. 保存結果 ==========
    console.print("\n[bold yellow]【6】保存結果[/bold yellow]\n")
    
    output_dir = Path("exports/optimizations")
    output_dir.mkdir(parents=True, exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    # 保存完整結果
    output_file = output_dir / f"param_optimization_{timestamp}.csv"
    df_results.to_csv(output_file, index=False)
    console.print(f"[green]✓ 結果已保存至：{output_file}[/green]")
    
    # 保存最佳參數
    best_params = {
        'entry_score': int(best_by_recovery['param_entry_score']),
        'mom_state_long': int(best_by_recovery['param_mom_state_long']),
        'mom_state_short': int(best_by_recovery['param_mom_state_short']),
        'stop_loss_pts': int(best_by_recovery['param_stop_loss_pts']),
        'tp1_pts': int(best_by_recovery['param_tp1_pts']),
        'expected_return': best_by_recovery['total_return'],
        'sharpe_ratio': best_by_recovery['sharpe_ratio'],
        'max_drawdown': best_by_recovery['max_drawdown'],
        'recovery_factor': best_by_recovery['recovery_factor'],
    }
    
    import json
    with open(output_dir / f"best_params_{timestamp}.json", 'w') as f:
        json.dump(best_params, f, indent=2)
    
    console.print(f"[green]✓ 最佳參數已保存至：{output_dir / f'best_params_{timestamp}.json'}[/green]")
    
    console.print("\n[bold blue]╔" + "═" * 70 + "╗[/bold blue]")
    console.print("[bold blue]║[/bold blue]" + " " * 25 + "OPTIMIZATION COMPLETE" + " " * 22 + "[bold blue]║[/bold blue]")
    console.print("[bold blue]╚" + "═" * 70 + "╝[/bold blue]")


if __name__ == "__main__":
    run_parameter_optimization()

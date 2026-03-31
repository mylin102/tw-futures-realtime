#!/usr/bin/env python3
"""
新架構演示腳本
展示如何使用 DataManager, VectorizedSimulator, QuantAnalytics
"""

import sys
import os
from pathlib import Path
from rich.console import Console

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from squeeze_futures.engine import (
    DataManager,
    VectorizedSimulator,
    SimulatorConfig,
    QuantAnalytics,
)

console = Console()


def main():
    """主函數"""
    console.print("[bold blue]=== Squeeze Futures 新架構演示 ===[/bold blue]\n")
    
    # ========== 1. 數據管理 ==========
    console.print("[bold yellow]1. 數據管理 (DataManager)[/bold yellow]")
    
    dm = DataManager("data/taifex_raw")
    
    # 載入 Yahoo Finance 數據
    df = dm.load_yahoo("^TWII", period="60d", interval="5m")
    
    if df.empty:
        console.print("[red]無法載入數據[/red]")
        return
    
    # 添加指標
    df = dm.add_indicators(df, indicators=['squeeze', 'vwap'])
    
    console.print(f"[green]✓ 載入 {len(df)} 筆數據[/green]\n")
    
    # ========== 2. 向量化模擬 ==========
    console.print("[bold yellow]2. 向量化模擬 (VectorizedSimulator)[/bold yellow]")
    
    config = SimulatorConfig(
        initial_balance=100000,
        point_value=10,
        fee_per_side=20,
        exchange_fee=0,
        tax_rate=0.00002,
        max_positions=2,
        lots_per_trade=2,
        slippage=1.0,
    )
    
    sim = VectorizedSimulator(df, config)
    
    # 執行單一回測
    result = sim.run(
        entry_score=30,
        mom_state_long=2,
        mom_state_short=1,
        stop_loss_pts=30,
        tp1_pts=30,
        tp1_lots=1,
        exit_on_vwap=True,
    )
    
    console.print(f"[green]✓ 完成回測[/green]\n")
    
    # ========== 3. 量化分析 ==========
    console.print("[bold yellow]3. 量化分析 (QuantAnalytics)[/bold yellow]")
    
    analytics = QuantAnalytics(
        equity_curve=result['results']['equity_curve'],
        pnl=result['results']['pnl'],
        initial_balance=config.initial_balance,
    )
    
    # 打印報告
    analytics.print_report()
    
    # ========== 4. 參數優化 ==========
    console.print("\n[bold yellow]4. 參數優化 (Parameter Grid)[/bold yellow]")
    
    param_grid = {
        'entry_score': [20, 30, 40],
        'mom_state_long': [2, 3],
        'stop_loss_pts': [20, 30],
    }
    
    console.print(f"[dim]測試 {len(list(__import__('itertools').product(*param_grid.values())))} 種組合...[/dim]")
    
    results_df = sim.run_param_grid(param_grid)
    
    # 顯示最佳結果
    if not results_df.empty:
        best = results_df.loc[results_df['recovery_factor'].idxmax()]
        
        console.print(f"\n[bold green]最佳參數組合:[/bold green]")
        console.print(f"  Entry Score: {best.get('param_entry_score', 'N/A')}")
        console.print(f"  Mom State Long: >= {best.get('param_mom_state_long', 'N/A')}")
        console.print(f"  Stop Loss: {best.get('param_stop_loss_pts', 'N/A')} pts")
        console.print(f"  Recovery Factor: {best.get('recovery_factor', 0):.2f}")
        console.print(f"  Total Return: {best.get('total_return', 0)*100:.1f}%")
    
    # ========== 5. 保存結果 ==========
    console.print("\n[bold yellow]5. 保存結果[/bold yellow]")
    
    output_dir = Path("exports/analytics")
    output_dir.mkdir(parents=True, exist_ok=True)
    
    from datetime import datetime
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    # 保存詳細結果
    results_df.to_csv(output_dir / f"param_grid_{timestamp}.csv", index=False)
    console.print(f"[green]✓ 結果已保存至：{output_dir / f'param_grid_{timestamp}.csv'}[/green]")
    
    # 保存分析報告
    import json
    report = analytics.to_dict()
    with open(output_dir / f"analytics_{timestamp}.json", 'w') as f:
        json.dump(report, f, indent=2)
    console.print(f"[green]✓ 分析報告已保存至：{output_dir / f'analytics_{timestamp}.json'}[/green]")
    
    console.print("\n[bold green]=== 演示完成 ===[/bold green]")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
向量化回測引擎演示
使用 NumPy/Numba 進行高效參數優化
"""

import sys
import os
import pandas as pd
from pathlib import Path
from rich.console import Console
from rich.table import Table

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from squeeze_futures.engine.vectorized_backtest import VectorizedBacktester, BacktestConfig

console = Console()


def main():
    """主函數"""
    console.print("[bold blue]=== 向量化回測引擎演示 ===[/bold blue]\n")
    
    # 1. 載入數據
    console.print("[dim]載入數據...[/dim]")
    
    data_files = list(Path("data/taifex_raw").glob("TWII*.csv"))
    if not data_files:
        console.print("[red]找不到數據檔案[/red]")
        return
    
    df = pd.read_csv(data_files[0], index_col=0, parse_dates=True)
    console.print(f"[green]載入 {len(df)} 筆 K 棒數據[/green]\n")
    
    # 2. 初始化回測器
    config = BacktestConfig(
        initial_balance=100000,
        point_value=10,
        fee_per_side=20,
        exchange_fee=0,
        tax_rate=0.00002,
        max_positions=2,
        lots_per_trade=2,
    )
    
    backtester = VectorizedBacktester(df, config)
    
    # 3. 執行單一回測
    console.print("\n[yellow]執行單一回測...[/yellow]")
    
    result = backtester.run_backtest(
        entry_score=30,
        mom_state_long=2,
        mom_state_short=1,
        regime_filter_mode=0,  # loose
        use_pb=True,
        pb_confirm_bars=12,
        stop_loss_pts=30,
        tp1_pts=30,
        tp1_lots=1,
        exit_on_vwap=True,
    )
    
    # 顯示結果
    metrics = result['metrics']
    
    table = Table(title="單一回測結果")
    table.add_column("指標", style="cyan")
    table.add_column("數值", justify="right")
    
    table.add_row("總報酬率", f"{metrics['total_return']*100:.2f}%")
    table.add_row("夏普比率", f"{metrics['sharpe_ratio']:.2f}")
    table.add_row("最大回撤", f"{metrics['max_drawdown']:,.0f} TWD")
    table.add_row("潰瘍指數", f"{metrics['ulcer_index']:.2f}")
    table.add_row("修復因子", f"{metrics['recovery_factor']:.2f}")
    table.add_row("期望值", f"{metrics.get('expectancy', 0):,.0f} TWD")
    table.add_row("勝率", f"{metrics.get('win_rate', 0):.1f}%")
    table.add_row("盈虧比", f"{metrics.get('profit_factor', 0):.2f}")
    table.add_row("平均交易", f"{metrics.get('avg_trade', 0):,.0f} TWD")
    table.add_row("交易次數", f"{metrics.get('total_trades', 0)}")
    table.add_row("獲利次數", f"{metrics.get('winning_trades', 0)}")
    table.add_row("虧損次數", f"{metrics.get('losing_trades', 0)}")
    
    console.print(table)
    
    # 4. 執行參數網格優化
    console.print("\n[yellow]執行參數網格優化...[/yellow]")
    
    param_grid = {
        'entry_score': [20, 30, 40, 50],
        'mom_state_long': [2, 3],
        'mom_state_short': [0, 1],
        'regime_filter_mode': [0, 1],  # loose, mid
        'stop_loss_pts': [20, 30, 40],
        'tp1_pts': [20, 30, 40],
    }
    
    results_df = backtester.run_parameter_grid(param_grid)
    
    # 顯示最佳結果
    console.print("\n[bold green]=== 最佳 20 組參數 ===[/bold green]\n")
    
    # 按總報酬率排序
    top_by_return = results_df.nlargest(20, 'total_return')
    
    table = Table(title="按總報酬率排序 Top 20")
    table.add_column("Rank", style="dim")
    table.add_column("Entry Score", justify="right")
    table.add_column("MS Long", justify="right")
    table.add_column("MS Short", justify="right")
    table.add_column("Regime", justify="center")
    table.add_column("SL Pts", justify="right")
    table.add_column("TP1 Pts", justify="right")
    table.add_column("總報酬", justify="right", style="green")
    table.add_column("夏普", justify="right")
    table.add_column("最大回撤", justify="right", style="red")
    table.add_column("修復因子", justify="right")
    table.add_column("交易次數", justify="right")
    
    for idx, row in top_by_return.iterrows():
        regime_map = {0: 'loose', 1: 'mid', 2: 'strict'}
        table.add_row(
            str(idx + 1),
            str(int(row.get('param_entry_score', 0))),
            str(int(row.get('param_mom_state_long', 0))),
            str(int(row.get('param_mom_state_short', 0))),
            regime_map.get(int(row.get('param_regime_filter_mode', 0)), 'unknown'),
            str(int(row.get('param_stop_loss_pts', 0))),
            str(int(row.get('param_tp1_pts', 0))),
            f"{row.get('total_return', 0)*100:.1f}%",
            f"{row.get('sharpe_ratio', 0):.2f}",
            f"{row.get('max_drawdown', 0):,.0f}",
            f"{row.get('recovery_factor', 0):.2f}",
            str(int(row.get('total_trades', 0))),
        )
    
    console.print(table)
    
    # 保存結果
    output_dir = Path(__file__).parent.parent / "exports" / "optimizations"
    output_dir.mkdir(parents=True, exist_ok=True)
    
    from datetime import datetime
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = output_dir / f"vectorized_optimization_{timestamp}.csv"
    
    results_df.to_csv(output_file, index=False)
    console.print(f"\n[green]結果已保存至：{output_file}[/green]")
    
    # 參數影響分析
    console.print("\n[bold blue]=== 參數影響分析 ===[/bold blue]\n")
    
    # Entry Score 影響
    console.print("[yellow]Entry Score 對總報酬的影響:[/yellow]")
    score_analysis = results_df.groupby('param_entry_score')['total_return'].agg(['mean', 'std', 'count']).round(4)
    console.print(score_analysis)
    
    # Stop Loss 影響
    console.print("\n[yellow]Stop Loss 對最大回撤的影響:[/yellow]")
    sl_analysis = results_df.groupby('param_stop_loss_pts')['max_drawdown'].agg(['mean', 'std']).round(2)
    console.print(sl_analysis)
    
    # 建議最佳參數
    best = results_df.loc[results_df['recovery_factor'].idxmax()]
    console.print("\n[bold green]=== 建議最佳參數 (按修復因子) ===[/bold green]")
    console.print(f"Entry Score: {int(best['param_entry_score'])}")
    console.print(f"Mom State (Long): >= {int(best['param_mom_state_long'])}")
    console.print(f"Mom State (Short): <= {int(best['param_mom_state_short'])}")
    console.print(f"Regime Filter: {'loose' if best['param_regime_filter_mode'] == 0 else 'mid'}")
    console.print(f"Stop Loss: {int(best['param_stop_loss_pts'])} pts")
    console.print(f"TP1: {int(best['param_tp1_pts'])} pts")
    console.print(f"\n預期績效:")
    console.print(f"  總報酬：{best['total_return']*100:.1f}%")
    console.print(f"  夏普比率：{best['sharpe_ratio']:.2f}")
    console.print(f"  最大回撤：{best['max_drawdown']:,.0f} TWD")
    console.print(f"  修復因子：{best['recovery_factor']:.2f}")
    console.print(f"  交易次數：{int(best['total_trades'])}")


if __name__ == "__main__":
    main()

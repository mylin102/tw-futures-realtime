#!/usr/bin/env python3
"""
Vectorbt-Style Stats Report
專業量化交易統計報告

靈感來自 vectorbt-pro 的 stats 模組
"""

import numpy as np
import pandas as pd
from pathlib import Path
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text

console = Console()


def generate_vectorbt_stats(
    total_return: float,
    sharpe_ratio: float,
    sortino_ratio: float,
    ulcer_index: float,
    recovery_factor: float,
    profit_factor: float,
    expectancy: float,
    max_drawdown: float,
    max_drawdown_pct: float,
    total_trades: int,
    win_rate: float,
    avg_trade: float,
    best_trade: float,
    worst_trade: float,
    avg_holding_period: float = 0,
    trades_per_day: float = 0,
) -> str:
    """
    生成 vectorbt-style 統計報告
    
    Returns:
        格式化的報告字串
    """
    # 評估每個指標
    sharpe_status = "✓ Good" if sharpe_ratio > 1.0 else "⚠ Average" if sharpe_ratio > 0.5 else "✗ Poor"
    ulcer_status = "✓ Good" if ulcer_index < 5 else "⚠ Average" if ulcer_index < 10 else "✗ Poor"
    recovery_status = "✓ Good" if recovery_factor > 1.0 else "⚠ Average" if recovery_factor > 0.5 else "✗ Poor"
    profit_status = "✓ Good" if profit_factor > 1.5 else "⚠ Average" if profit_factor > 1.2 else "✗ Poor"
    
    # 建立報告
    report = []
    report.append("=" * 60)
    report.append("           VECTORBT-STYLE PERFORMANCE STATS")
    report.append("=" * 60)
    report.append("")
    
    # 核心指標
    report.append("CORE METRICS:")
    report.append(f"  Expectancy:      {expectancy*100:>8.2f}% per trade")
    report.append(f"  Recovery Factor: {recovery_factor:>8.2f}")
    report.append(f"  Ulcer Index:     {ulcer_index:>8.2f}")
    report.append(f"  Profit Factor:   {profit_factor:>8.2f}")
    report.append("")
    
    # 風險調整後報酬
    report.append("RISK-ADJUSTED RETURNS:")
    report.append(f"  Sharpe Ratio:    {sharpe_ratio:>8.2f}  {sharpe_status}")
    report.append(f"  Sortino Ratio:   {sortino_ratio:>8.2f}")
    report.append(f"  Max Drawdown:    {max_drawdown_pct:>8.2f}%  ({max_drawdown:,.0f} TWD)")
    report.append("")
    
    # 交易統計
    report.append("TRADE STATISTICS:")
    report.append(f"  Total Trades:    {total_trades:>8d}")
    report.append(f"  Win Rate:        {win_rate:>8.1f}%")
    report.append(f"  Avg Trade:       {avg_trade:>8,.0f} TWD")
    report.append(f"  Best Trade:      {best_trade:>8,.0f} TWD")
    report.append(f"  Worst Trade:     {worst_trade:>8,.0f} TWD")
    report.append("")
    
    # 綜合評估
    report.append("OVERALL ASSESSMENT:")
    
    # 計算綜合評分
    score = 0
    if sharpe_ratio > 1.0: score += 1
    if ulcer_index < 5: score += 1
    if recovery_factor > 1.0: score += 1
    if profit_factor > 1.5: score += 1
    if win_rate > 50: score += 1
    
    if score >= 4:
        assessment = "EXCELLENT - Strategy shows strong risk-adjusted returns"
    elif score >= 3:
        assessment = "GOOD - Strategy is viable with room for improvement"
    elif score >= 2:
        assessment = "AVERAGE - Strategy needs optimization"
    else:
        assessment = "POOR - Strategy requires significant improvement"
    
    report.append(f"  Score: {score}/5 - {assessment}")
    report.append("")
    report.append("=" * 60)
    
    return "\n".join(report)


def print_vectorbt_report(analytics):
    """
    打印 vectorbt-style 報告
    
    Args:
        analytics: QuantAnalytics 實例
    """
    from squeeze_futures.engine.analytics import QuantAnalytics
    
    # 獲取所有指標
    perf = analytics.get_performance_metrics()
    risk = analytics.get_risk_metrics()
    stats = analytics.get_trade_stats()
    
    # 打印核心指標
    console.print()
    console.print(Panel(
        f"[bold]Expectancy:[/bold]      {stats.expectancy*100:.2f}% per trade\n"
        f"[bold]Recovery Factor:[/bold] {risk.recovery_factor:.2f}\n"
        f"[bold]Ulcer Index:[/bold]     {risk.ulcer_index:.2f}\n"
        f"[bold]Profit Factor:[/bold]   {perf.profit_factor:.2f}",
        title="[bold blue]VECTORBT-STYLE STATS[/bold blue]",
        border_style="blue",
    ))
    
    # 風險調整後報酬
    sharpe_status = "[green]✓ Good[/green]" if risk.sharpe_ratio > 1.0 else "[yellow]⚠ Average[/yellow]" if risk.sharpe_ratio > 0.5 else "[red]✗ Poor[/red]"
    
    table = Table(title="Risk-Adjusted Returns", show_header=True)
    table.add_column("Metric", style="cyan")
    table.add_column("Value", justify="right")
    table.add_column("Status", justify="center")
    
    table.add_row("Sharpe Ratio", f"{risk.sharpe_ratio:.2f}", sharpe_status)
    table.add_row("Sortino Ratio", f"{risk.sortino_ratio:.2f}", "")
    table.add_row("Max Drawdown", f"{risk.max_drawdown_pct:.2f}% ({risk.max_drawdown:,.0f} TWD)", "")
    table.add_row("Ulcer Index", f"{risk.ulcer_index:.2f}", "[green]✓ Good[/green]" if risk.ulcer_index < 5 else "[yellow]⚠ Average[/yellow]" if risk.ulcer_index < 10 else "[red]✗ Poor[/red]")
    
    console.print()
    console.print(table)
    
    # 交易統計
    table = Table(title="Trade Statistics", show_header=True)
    table.add_column("Metric", style="cyan")
    table.add_column("Value", justify="right")
    
    table.add_row("Total Trades", f"{stats.total_trades}")
    table.add_row("Win Rate", f"{stats.win_rate:.1f}%")
    table.add_row("Avg Trade", f"{stats.avg_trade:,.0f} TWD")
    table.add_row("Best Trade", f"{stats.largest_win:,.0f} TWD")
    table.add_row("Worst Trade", f"{stats.largest_loss:,.0f} TWD")
    table.add_row("Expectancy", f"{stats.expectancy:,.0f} TWD")
    
    console.print()
    console.print(table)
    
    # 綜合評估
    score = sum([
        risk.sharpe_ratio > 1.0,
        risk.ulcer_index < 5,
        risk.recovery_factor > 1.0,
        perf.profit_factor > 1.5,
        stats.win_rate > 50,
    ])
    
    if score >= 4:
        assessment = "[bold green]EXCELLENT[/bold green]"
        comment = "Strategy shows strong risk-adjusted returns"
    elif score >= 3:
        assessment = "[bold yellow]GOOD[/bold yellow]"
        comment = "Strategy is viable with room for improvement"
    elif score >= 2:
        assessment = "[bold yellow]AVERAGE[/bold yellow]"
        comment = "Strategy needs optimization"
    else:
        assessment = "[bold red]POOR[/bold red]"
        comment = "Strategy requires significant improvement"
    
    console.print()
    console.print(Panel(
        f"[bold]Overall Score:[/bold] {score}/5 - {assessment}\n\n{comment}",
        title="[bold blue]OVERALL ASSESSMENT[/bold blue]",
        border_style="blue",
    ))


def main():
    """演示用主函數"""
    from squeeze_futures.engine import (
        DataManager,
        VectorizedSimulator,
        SimulatorConfig,
        QuantAnalytics,
    )
    
    console.print("[bold blue]=== Vectorbt-Style Stats Report Demo ===[/bold blue]\n")
    
    # 1. 載入數據
    dm = DataManager("data/taifex_raw")
    df = dm.load_yahoo("^TWII", period="60d", interval="5m")
    df = dm.add_indicators(df, indicators=['squeeze'])
    
    # 2. 執行回測
    config = SimulatorConfig(initial_balance=100000)
    sim = VectorizedSimulator(df, config)
    
    result = sim.run(
        entry_score=30,
        mom_state_long=2,
        mom_state_short=1,
        stop_loss_pts=30,
        tp1_pts=30,
        tp1_lots=1,
        exit_on_vwap=True,
    )
    
    # 3. 量化分析
    analytics = QuantAnalytics(
        equity_curve=result['results']['equity_curve'],
        pnl=result['results']['pnl'],
        initial_balance=config.initial_balance,
    )
    
    # 4. 打印 vectorbt-style 報告
    print_vectorbt_report(analytics)
    
    # 5. 生成文字報告
    perf = analytics.get_performance_metrics()
    risk = analytics.get_risk_metrics()
    stats = analytics.get_trade_stats()
    
    report = generate_vectorbt_stats(
        total_return=perf.total_return_pct / 100,
        sharpe_ratio=risk.sharpe_ratio,
        sortino_ratio=risk.sortino_ratio,
        ulcer_index=risk.ulcer_index,
        recovery_factor=risk.recovery_factor,
        profit_factor=perf.profit_factor,
        expectancy=stats.expectancy / analytics.initial_balance,
        max_drawdown=risk.max_drawdown,
        max_drawdown_pct=risk.max_drawdown_pct,
        total_trades=stats.total_trades,
        win_rate=stats.win_rate,
        avg_trade=stats.avg_trade,
        best_trade=stats.largest_win,
        worst_trade=stats.largest_loss,
    )
    
    console.print()
    console.print(Panel(report, title="Text Report", border_style="dim"))


if __name__ == "__main__":
    main()

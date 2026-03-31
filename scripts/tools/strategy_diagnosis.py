#!/usr/bin/env python3
"""
策略診斷工具
分析交易記錄，找出策略問題
"""

import sys
import os
import pandas as pd
import numpy as np
from pathlib import Path
from rich.console import Console
from rich.table import Table

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

console = Console()


def analyze_trades(log_file: str = "logs/automation.log"):
    """分析交易記錄"""
    console.print("[bold blue]╔" + "═" * 60 + "╗[/bold blue]")
    console.print("[bold blue]║[/bold blue]" + " " * 20 + "STRATEGY DIAGNOSIS" + " " * 22 + "[bold blue]║[/bold blue]")
    console.print("[bold blue]╚" + "═" * 60 + "╝[/bold blue]\n")
    
    # 讀取日誌
    if not Path(log_file).exists():
        console.print(f"[red]找不到日誌檔案：{log_file}[/red]")
        return
    
    with open(log_file, 'r') as f:
        lines = f.readlines()
    
    # 提取交易記錄
    trades = []
    current_trade = None
    
    for line in lines:
        if 'EXIT' in line and 'PnL' in line:
            # 解析出場記錄
            try:
                # [2026-03-30 23:00:00] EXIT 2 at 32407.0, PnL: -706
                parts = line.strip().split('] ')
                if len(parts) >= 2:
                    timestamp = parts[0].replace('[', '')
                    rest = parts[1]
                    
                    # 解析價格和 PnL
                    import re
                    price_match = re.search(r'at ([\d.]+)', rest)
                    pnl_match = re.search(r'PnL: ([\d-]+)', rest)
                    reason_match = re.search(r'\[(\w+)\]', rest)
                    
                    if price_match and pnl_match:
                        trade = {
                            'time': timestamp,
                            'price': float(price_match.group(1)),
                            'pnl': float(pnl_match.group(1)),
                            'reason': reason_match.group(1) if reason_match else 'STOP_LOSS',
                        }
                        trades.append(trade)
            except Exception as e:
                pass
    
    if not trades:
        console.print("[yellow]⚠ 未找到交易記錄[/yellow]")
        return
    
    # ========== 交易統計 ==========
    console.print("[bold yellow]【1】交易統計[/bold yellow]\n")
    
    total_trades = len(trades)
    winning = [t for t in trades if t['pnl'] > 0]
    losing = [t for t in trades if t['pnl'] < 0]
    
    win_rate = len(winning) / total_trades * 100 if total_trades > 0 else 0
    total_pnl = sum(t['pnl'] for t in trades)
    avg_pnl = np.mean([t['pnl'] for t in trades])
    avg_win = np.mean([t['pnl'] for t in winning]) if winning else 0
    avg_loss = np.mean([t['pnl'] for t in losing]) if losing else 0
    
    table = Table(title="Trading Statistics")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", justify="right")
    
    table.add_row("Total Trades", str(total_trades))
    table.add_row("Winning", str(len(winning)))
    table.add_row("Losing", str(len(losing)))
    table.add_row("Win Rate", f"{win_rate:.1f}%")
    table.add_row("Total PnL", f"{total_pnl:,.0f} TWD")
    table.add_row("Avg PnL", f"{avg_pnl:,.0f} TWD")
    table.add_row("Avg Win", f"{avg_win:,.0f} TWD")
    table.add_row("Avg Loss", f"{avg_loss:,.0f} TWD")
    
    console.print(table)
    
    # ========== 出場原因分析 ==========
    console.print("\n[bold yellow]【2】出場原因分析[/bold yellow]\n")
    
    reasons = {}
    for t in trades:
        reason = t['reason']
        if reason not in reasons:
            reasons[reason] = {'count': 0, 'pnl': 0}
        reasons[reason]['count'] += 1
        reasons[reason]['pnl'] += t['pnl']
    
    table = Table(title="Exit Reason Analysis")
    table.add_column("Reason", style="cyan")
    table.add_column("Count", justify="right")
    table.add_column("Avg PnL", justify="right")
    table.add_column("Total PnL", justify="right")
    
    for reason, data in sorted(reasons.items(), key=lambda x: x[1]['count'], reverse=True):
        avg = data['pnl'] / data['count'] if data['count'] > 0 else 0
        table.add_row(
            reason,
            str(data['count']),
            f"{avg:,.0f}",
            f"{data['pnl']:,.0f}",
        )
    
    console.print(table)
    
    # ========== 問題診斷 ==========
    console.print("\n[bold yellow]【3】問題診斷[/bold yellow]\n")
    
    issues = []
    
    # 問題 1: 勝率過低
    if win_rate < 30:
        issues.append({
            'problem': 'Win Rate Too Low',
            'severity': 'HIGH',
            'suggestion': 'Improve entry signal quality or add confirmation conditions',
        })
    
    # 問題 2: 平均虧損 > 平均獲利
    if abs(avg_loss) > abs(avg_win) * 0.8:
        issues.append({
            'problem': 'Avg Loss > Avg Win',
            'severity': 'HIGH',
            'suggestion': 'Widen stop loss or add take profit mechanism',
        })
    
    # 問題 3: VWAP 離場表現差
    if 'VWAP' in reasons and reasons['VWAP']['pnl'] < -500:
        issues.append({
            'problem': 'VWAP Exit Performing Poorly',
            'severity': 'MEDIUM',
            'suggestion': 'Disable VWAP exit or adjust threshold',
        })
    
    # 問題 4: 連續虧損
    consecutive_losses = 0
    max_consecutive = 0
    for t in trades:
        if t['pnl'] < 0:
            consecutive_losses += 1
            max_consecutive = max(max_consecutive, consecutive_losses)
        else:
            consecutive_losses = 0
    
    if max_consecutive >= 5:
        issues.append({
            'problem': f'{max_consecutive} Consecutive Losses',
            'severity': 'HIGH',
            'suggestion': 'Strategy may not suit current market conditions',
        })
    
    # 顯示問題
    if issues:
        table = Table(title="Identified Issues")
        table.add_column("Problem", style="red")
        table.add_column("Severity", justify="center")
        table.add_column("Suggestion", style="green")
        
        for issue in issues:
            severity_color = "bold red" if issue['severity'] == 'HIGH' else "bold yellow"
            table.add_row(
                issue['problem'],
                f"[{severity_color}]{issue['severity']}[/{severity_color}]",
                issue['suggestion'],
            )
        
        console.print(table)
    else:
        console.print("[green]✓ No major issues identified[/green]")
    
    # ========== 改進建議 ==========
    console.print("\n[bold yellow]【4】改進建議[/bold yellow]\n")
    
    recommendations = []
    
    if win_rate < 30:
        recommendations.append({
            'priority': 'HIGH',
            'action': '暫停夜盤交易',
            'reason': '夜盤流動性不足，策略失效',
        })
        recommendations.append({
            'priority': 'HIGH',
            'action': '增加進場確認條件',
            'reason': '當前信號過於簡單，勝率过低',
        })
    
    if 'VWAP' in reasons:
        recommendations.append({
            'priority': 'MEDIUM',
            'action': '禁用 VWAP 離場',
            'reason': 'VWAP 在震盪市不斷停損',
        })
    
    recommendations.append({
        'priority': 'MEDIUM',
        'action': '增加移動停損',
        'reason': '保護未實現獲利',
    })
    
    recommendations.append({
        'priority': 'LOW',
        'action': '實施時間過濾',
        'reason': '避開高波動時段',
    })
    
    table = Table(title="Recommendations")
    table.add_column("Priority", style="cyan")
    table.add_column("Action", style="green")
    table.add_column("Reason", style="dim")
    
    for rec in sorted(recommendations, key=lambda x: {'HIGH': 0, 'MEDIUM': 1, 'LOW': 2}[x['priority']]):
        priority_color = "bold red" if rec['priority'] == 'HIGH' else "bold yellow" if rec['priority'] == 'MEDIUM' else "dim"
        table.add_row(
            f"[{priority_color}]{rec['priority']}[/{priority_color}]",
            rec['action'],
            rec['reason'],
        )
    
    console.print(table)
    
    # ========== 結論 ==========
    console.print("\n[bold blue]╔" + "═" * 60 + "╗[/bold blue]")
    console.print("[bold blue]║[/bold blue]" + " " * 25 + "DIAGNOSIS COMPLETE" + " " * 17 + "[bold blue]║[/bold blue]")
    console.print("[bold blue]╚" + "═" * 60 + "╝[/bold blue]\n")
    
    # 計算問題評分
    high_issues = len([i for i in issues if i['severity'] == 'HIGH'])
    
    if high_issues >= 2:
        console.print("[bold red]⚠️  策略存在嚴重問題，建議立即暫停交易並改進[/bold red]\n")
    elif high_issues >= 1:
        console.print("[bold yellow]⚠️  策略存在問題，建議盡快改進[/bold yellow]\n")
    else:
        console.print("[bold green]✓ 策略基本正常，可繼續觀察[/bold green]\n")


if __name__ == "__main__":
    analyze_trades()

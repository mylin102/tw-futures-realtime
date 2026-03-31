#!/usr/bin/env python3
"""
交易數據導出工具
將即時交易數據導出為標準格式，供回測復盤使用
"""

import sys
import os
import pandas as pd
import json
from datetime import datetime
from pathlib import Path
from rich.console import Console

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

console = Console()


def export_market_data(
    input_dir: str = "logs/market_data",
    output_dir: str = "data/backtest",
    date: str = None
):
    """
    導出市場數據
    
    Args:
        input_dir: 輸入目錄 (即時數據)
        output_dir: 輸出目錄 (回測數據)
        date: 日期 (YYYYMMDD), 預設今天
    """
    if date is None:
        date = datetime.now().strftime("%Y%m%d")
    
    console.print(f"[bold blue]導出 {date} 市場數據...[/bold blue]\n")
    
    # 建立輸出目錄
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    
    # 尋找輸入檔案
    input_pattern = f"TMF_{date}*.csv"
    input_files = list(Path(input_dir).glob(input_pattern))
    
    if not input_files:
        console.print(f"[yellow]⚠️  找不到 {date} 的數據檔案[/yellow]")
        return None
    
    # 合併所有數據
    all_data = []
    for file in sorted(input_files):
        try:
            df = pd.read_csv(file, index_col=0, parse_dates=True)
            all_data.append(df)
            console.print(f"[dim]✓ 載入 {file.name}: {len(df)} 筆[/dim]")
        except Exception as e:
            console.print(f"[red]✗ 讀取失敗 {file.name}: {e}[/red]")
    
    if not all_data:
        return None
    
    # 合併並去重
    merged = pd.concat(all_data)
    merged = merged[~merged.index.duplicated(keep='last')]
    merged = merged.sort_index()
    
    # 去除重複欄位
    merged = merged.loc[:, ~merged.columns.duplicated()]
    
    # 確保必要欄位
    required_cols = ['Open', 'High', 'Low', 'Close', 'Volume', 'score', 'sqz_on', 'mom_state', 'vwap']
    for col in required_cols:
        if col not in merged.columns:
            merged[col] = 0 if col in ['Open', 'High', 'Low', 'Close', 'Volume', 'score'] else False
    
    console.print(f"\n[green]✓ 合併完成：{len(merged)} 筆數據[/green]")
    
    # 保存為 CSV
    output_file = output_path / f"TMF_{date}_5m.csv"
    merged.to_csv(output_file)
    
    console.print(f"[green]✓ 已保存至：{output_file}[/green]\n")
    
    # 顯示統計
    console.print("[bold]數據統計:[/bold]")
    console.print(f"  時間範圍：{merged.index[0]} ~ {merged.index[-1]}")
    console.print(f"  總筆數：{len(merged)}")
    console.print(f"  價格範圍：{merged['Close'].min():.0f} ~ {merged['Close'].max():.0f}")
    console.print(f"  Score 範圍：{merged['score'].min():.1f} ~ {merged['score'].max():.1f}")
    
    return output_file


def export_trade_log(
    input_file: str = "logs/automation.log",
    output_dir: str = "data/backtest",
    date: str = None
):
    """
    導出交易日誌
    
    Args:
        input_file: 自動化日誌
        output_dir: 輸出目錄
        date: 日期
    """
    if date is None:
        date = datetime.now().strftime("%Y%m%d")
    
    console.print(f"\n[bold blue]導出 {date} 交易日誌...[/bold blue]\n")
    
    if not Path(input_file).exists():
        console.print(f"[yellow]⚠️  找不到日誌檔案：{input_file}[/yellow]")
        return None
    
    # 解析交易日誌
    trades = []
    with open(input_file, 'r') as f:
        for line in f:
            if date in line and ('EXIT' in line or 'BUY' in line or 'SELL' in line):
                try:
                    # 解析時間
                    time_part = line.split(']')[0].replace('[', '')
                    
                    # 解析交易類型
                    if 'EXIT' in line:
                        trade_type = 'EXIT'
                    elif 'BUY' in line:
                        trade_type = 'BUY'
                    elif 'SELL' in line:
                        trade_type = 'SELL'
                    else:
                        continue
                    
                    # 解析價格
                    import re
                    price_match = re.search(r'at ([\d.]+)', line)
                    price = float(price_match.group(1)) if price_match else 0
                    
                    # 解析 PnL
                    pnl_match = re.search(r'PnL: ([\d,-]+)', line)
                    pnl = float(pnl_match.group(1).replace(',', '')) if pnl_match else 0
                    
                    # 解析原因
                    reason = 'NORMAL'
                    if 'VWAP' in line:
                        reason = 'VWAP'
                    elif 'STOP' in line.upper():
                        reason = 'STOP_LOSS'
                    elif 'PARTIAL' in line.upper():
                        reason = 'PARTIAL_EXIT'
                    
                    trades.append({
                        'timestamp': time_part,
                        'type': trade_type,
                        'price': price,
                        'pnl': pnl,
                        'reason': reason,
                    })
                except Exception as e:
                    pass
    
    if not trades:
        console.print(f"[yellow]⚠️  未找到交易記錄[/yellow]")
        return None
    
    # 保存為 CSV
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    
    output_file = output_path / f"TMF_{date}_trades.csv"
    df_trades = pd.DataFrame(trades)
    df_trades.to_csv(output_file, index=False)
    
    console.print(f"[green]✓ 已保存至：{output_file}[/green]")
    console.print(f"[dim]  共 {len(trades)} 筆交易[/dim]\n")
    
    return output_file


def generate_backtest_report(
    market_file: str = None,
    trade_file: str = None,
    output_dir: str = "exports/backtests",
    date: str = None
):
    """
    生成回測報告
    
    Args:
        market_file: 市場數據檔案
        trade_file: 交易數據檔案
        output_dir: 輸出目錄
        date: 日期
    """
    if date is None:
        date = datetime.now().strftime("%Y%m%d")
    
    console.print(f"\n[bold blue]生成 {date} 回測報告...[/bold blue]\n")
    
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    
    # 讀取交易數據
    if trade_file and Path(trade_file).exists():
        df_trades = pd.read_csv(trade_file)
        
        # 計算統計
        exits = df_trades[df_trades['type'] == 'EXIT']
        
        if len(exits) > 0:
            total_pnl = exits['pnl'].sum()
            winning = exits[exits['pnl'] > 0]
            losing = exits[exits['pnl'] < 0]
            
            win_rate = len(winning) / len(exits) * 100 if len(exits) > 0 else 0
            avg_win = winning['pnl'].mean() if len(winning) > 0 else 0
            avg_loss = abs(losing['pnl'].mean()) if len(losing) > 0 else 0
            
            gross_profit = winning['pnl'].sum() if len(winning) > 0 else 0
            gross_loss = abs(losing['pnl'].sum()) if len(losing) > 0 else 0
            profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0
            
            # 生成報告
            report = {
                'date': date,
                'total_trades': len(exits),
                'winning_trades': len(winning),
                'losing_trades': len(losing),
                'win_rate': round(win_rate, 2),
                'total_pnl': round(total_pnl, 2),
                'avg_win': round(avg_win, 2),
                'avg_loss': round(avg_loss, 2),
                'profit_factor': round(profit_factor, 2) if profit_factor != float('inf') else 999.99,
                'trades': df_trades.to_dict('records'),
            }
            
            # 保存 JSON
            output_file = output_path / f"report_{date}.json"
            with open(output_file, 'w') as f:
                json.dump(report, f, indent=2)
            
            console.print(f"[green]✓ 報告已保存至：{output_file}[/green]\n")
            
            # 打印摘要
            console.print("[bold]交易摘要:[/bold]")
            console.print(f"  總交易：{len(exits)}")
            console.print(f"  總 PnL: {total_pnl:,.0f} TWD")
            console.print(f"  勝率：{win_rate:.1f}%")
            console.print(f"  盈虧比：{profit_factor:.2f}")
            
            return report
    
    return None


def main():
    """主函數"""
    console.print("[bold blue]╔" + "═" * 60 + "╗[/bold blue]")
    console.print("[bold blue]║[/bold blue]" + " " * 18 + "交易數據導出工具" + " " * 22 + "[bold blue]║[/bold blue]")
    console.print("[bold blue]╚" + "═" * 60 + "╝[/bold blue]\n")
    
    # 參數
    date = datetime.now().strftime("%Y%m%d")
    
    # 1. 導出市場數據
    market_file = export_market_data(date=date)
    
    # 2. 導出交易日誌
    trade_file = export_trade_log(date=date)
    
    # 3. 生成報告
    if trade_file:
        generate_backtest_report(
            market_file=market_file,
            trade_file=trade_file,
            date=date
        )
    
    console.print("\n[bold blue]╔" + "═" * 60 + "╗[/bold blue]")
    console.print("[bold blue]║[/bold blue]" + " " * 20 + "導出完成" + " " * 30 + "[bold blue]║[/bold blue]")
    console.print("[bold blue]╚" + "═" * 60 + "╝[/bold blue]\n")


if __name__ == "__main__":
    main()

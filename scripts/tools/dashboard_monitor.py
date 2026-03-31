#!/usr/bin/env python3
"""
實時交易監控儀表板
持續監控交易過程、進場信號、持倉狀態和績效
"""

import sys
import os
import time
import pandas as pd
from datetime import datetime
from pathlib import Path
from rich.console import Console
from rich.live import Live
from rich.table import Table
from rich.panel import Panel
from rich.layout import Layout

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

console = Console()

LOG_FILE = Path("logs/automation.log")
MARKET_DIR = Path("logs/market_data")


def parse_trade_log(log_file: Path, date: str = None) -> list:
    """解析交易日誌"""
    if date is None:
        date = datetime.now().strftime("%Y-%m-%d")
    
    trades = []
    if log_file.exists():
        with open(log_file, 'r') as f:
            for line in f:
                if date in line and ('EXIT' in line or 'BUY' in line or 'SELL' in line):
                    try:
                        # 解析時間
                        time_part = line.split(']')[0].replace('[', '')
                        
                        # 解析類型
                        if 'PARTIAL_EXIT' in line:
                            trade_type = 'PARTIAL'
                        elif 'EXIT' in line:
                            trade_type = 'EXIT'
                        elif 'BUY' in line:
                            trade_type = 'BUY'
                        elif 'SELL' in line:
                            trade_type = 'SELL'
                        else:
                            continue
                        
                        # 解析價格和 PnL
                        import re
                        price_match = re.search(r'at ([\d.]+)', line)
                        pnl_match = re.search(r'PnL: ([\d,-]+)', line)
                        
                        price = float(price_match.group(1)) if price_match else 0
                        pnl = float(pnl_match.group(1).replace(',', '')) if pnl_match else 0
                        
                        trades.append({
                            'time': time_part.split(' ')[1][:8] if ' ' in time_part else time_part,
                            'type': trade_type,
                            'price': price,
                            'pnl': pnl,
                        })
                    except:
                        pass
    
    return trades


def get_latest_market_data(market_dir: Path, date: str = None) -> dict:
    """獲取最新市場數據"""
    if date is None:
        date = datetime.now().strftime("%Y%m%d")
    
    pattern = f"TMF_{date}*.csv"
    files = list(market_dir.glob(pattern))
    
    if not files:
        return None
    
    # 讀取最新檔案
    latest_file = max(files, key=os.path.getmtime)
    try:
        df = pd.read_csv(latest_file, index_col=0, parse_dates=True)
        if len(df) > 0:
            last_row = df.iloc[-1]
            return {
                'time': df.index[-1].strftime("%H:%M"),
                'close': last_row.get('close', 0),
                'score': last_row.get('score', 0),
                'sqz_on': last_row.get('sqz_on', False),
                'mom_state': last_row.get('mom_state', 0),
                'vwap': last_row.get('vwap', last_row.get('close', 0)),
            }
    except:
        pass
    
    return None


def calculate_performance(trades: list) -> dict:
    """計算績效統計"""
    exits = [t for t in trades if t['type'] in ['EXIT', 'PARTIAL']]
    
    if not exits:
        return {
            'total_pnl': 0,
            'total_trades': 0,
            'winning': 0,
            'losing': 0,
            'win_rate': 0,
        }
    
    total_pnl = sum(t['pnl'] for t in exits)
    winning = [t for t in exits if t['pnl'] > 0]
    losing = [t for t in exits if t['pnl'] < 0]
    
    return {
        'total_pnl': total_pnl,
        'total_trades': len(exits),
        'winning': len(winning),
        'losing': len(losing),
        'win_rate': len(winning) / len(exits) * 100 if exits else 0,
    }


def create_layout():
    """創建監控佈局"""
    layout = Layout()
    layout.split_column(
        Layout(name="header", size=3),
        Layout(name="body"),
        Layout(name="footer", size=10),
    )
    return layout


def update_header() -> Panel:
    """更新標題"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return Panel(
        f"[bold blue]Squeeze Futures 實時監控[/bold blue]\n{now}",
        border_style="blue",
    )


def update_market_panel(market_data: dict) -> Panel:
    """更新市場數據面板"""
    if not market_data:
        return Panel("[yellow]等待數據...[/yellow]", title="市場數據")
    
    # 判斷多空
    score = market_data['score']
    if score >= 50:
        signal = "[bold green]多頭[/bold green]"
    elif score <= -50:
        signal = "[bold red]空頭[/bold red]"
    else:
        signal = "[yellow]震盪[/yellow]"
    
    content = f"""
[bold]時間:[/bold] {market_data['time']}
[bold]價格:[/bold] {market_data['close']:.0f}
[bold]VWAP:[/bold] {market_data['vwap']:.0f}
[bold]Score:[/bold] {score:+.1f} {signal}
[bold]Squeeze:[/bold] {"ON" if market_data['sqz_on'] else "OFF"}
[bold]MomState:[/bold] {market_data['mom_state']}
"""
    return Panel(content, title="市場數據", border_style="cyan")


def update_position_panel(trades: list) -> Panel:
    """更新持倉面板"""
    if not trades:
        return Panel("[green]目前無持倉[/green]", title="持倉狀態")
    
    # 查找最新進場和平倉
    last_buy = next((t for t in reversed(trades) if t['type'] == 'BUY'), None)
    last_exit = next((t for t in reversed(trades) if t['type'] in ['EXIT', 'PARTIAL']), None)
    
    if last_buy and last_exit:
        buy_time = last_buy['time']
        exit_time = last_exit['time']
        
        if exit_time > buy_time:
            return Panel("[green]目前無持倉[/green]", title="持倉狀態")
        else:
            content = f"""
[bold]進場時間:[/bold] {buy_time}
[bold]進場價格:[/bold] {last_buy['price']:.0f}
[yellow]持有部位中...[/yellow]
"""
            return Panel(content, title="持倉狀態", border_style="yellow")
    elif last_buy:
        content = f"""
[bold]進場時間:[/bold] {last_buy['time']}
[bold]進場價格:[/bold] {last_buy['price']:.0f}
[yellow]持有部位中...[/yellow]
"""
        return Panel(content, title="持倉狀態", border_style="yellow")
    else:
        return Panel("[green]目前無持倉[/green]", title="持倉狀態")


def update_performance_panel(perf: dict) -> Panel:
    """更新績效面板"""
    pnl_color = "green" if perf['total_pnl'] > 0 else "red" if perf['total_pnl'] < 0 else "white"
    
    content = f"""
[bold]總 PnL:[/bold] [{pnl_color}]{perf['total_pnl']:+,.0f} TWD[/{pnl_color}]
[bold]交易次數:[/bold] {perf['total_trades']}
[bold]勝率:[/bold] {perf['win_rate']:.1f}%
[bold]獲利:[/bold] [green]{perf['winning']}[/green] | [bold]虧損:[/bold] [red]{perf['losing']}[/red]
"""
    return Panel(content, title="績效統計", border_style="magenta")


def update_trade_table(trades: list) -> Table:
    """更新交易表格"""
    table = Table(title="交易記錄", show_header=True, header_style="bold cyan")
    table.add_column("時間", style="dim")
    table.add_column("類型", justify="center")
    table.add_column("價格", justify="right")
    table.add_column("PnL", justify="right")
    
    for trade in trades[-10:]:  # 顯示最近 10 筆
        type_style = "green" if trade['type'] in ['BUY', 'SELL'] else "yellow"
        pnl_style = "green" if trade['pnl'] > 0 else "red" if trade['pnl'] < 0 else ""
        
        type_icon = "🟢" if trade['type'] == 'BUY' else "🔴" if trade['type'] == 'SELL' else "⚪"
        
        table.add_row(
            trade['time'],
            f"[{type_style}]{type_icon} {trade['type']}[/{type_style}]",
            f"{trade['price']:.0f}",
            f"[{pnl_style}]{trade['pnl']:+,.0f}[/{pnl_style}]",
        )
    
    return table


def main():
    """主函數"""
    console.print("[bold blue]啟動監控系統...[/bold blue]\n")
    
    layout = create_layout()
    
    # 初始數據
    trades = parse_trade_log(LOG_FILE)
    market_data = get_latest_market_data(MARKET_DIR)
    perf = calculate_performance(trades)
    
    with Live(layout, console=console, refresh_per_second=1) as live:
        while True:
            try:
                # 更新數據
                trades = parse_trade_log(LOG_FILE)
                market_data = get_latest_market_data(MARKET_DIR)
                perf = calculate_performance(trades)
                
                # 更新佈局
                layout["header"].update(update_header())
                
                # 主體區域
                body_layout = Layout()
                body_layout.split_row(
                    Layout(name="market"),
                    Layout(name="position"),
                    Layout(name="performance"),
                )
                
                body_layout["market"].update(update_market_panel(market_data))
                body_layout["position"].update(update_position_panel(trades))
                body_layout["performance"].update(update_performance_panel(perf))
                
                layout["body"].update(body_layout)
                
                # 底部交易記錄
                layout["footer"].update(update_trade_table(trades))
                
                time.sleep(5)  # 每 5 秒更新一次
                
            except KeyboardInterrupt:
                console.print("\n[yellow]監控停止[/yellow]")
                break
            except Exception as e:
                console.print(f"[red]錯誤：{e}[/red]")
                time.sleep(5)


if __name__ == "__main__":
    main()

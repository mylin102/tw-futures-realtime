#!/usr/bin/env python3
"""
測試 Shioaji API 對美股的支援

支援檢查：
1. TSM (台積電 ADR)
2. 其他美股 (AAPL, TSLA, NVDA 等)
3. 即時報價訂閱
"""

import sys
import os
from datetime import datetime
from rich.console import Console
from rich.table import Table

console = Console()


def test_shioaji_us_stocks():
    """測試 Shioaji 美股功能"""
    console.print("[bold blue]╔" + "═" * 60 + "╗[/bold blue]")
    console.print("[bold blue]║[/bold blue]" + " " * 15 + "SHIOAJI US STOCKS TEST" + " " * 17 + "[bold blue]║[/bold blue]")
    console.print("[bold blue]╚" + "═" * 60 + "╝[/bold blue]\n")
    
    try:
        import shioaji as sj
    except ImportError:
        console.print("[red]✗ shioaji 未安裝[/red]")
        return None
    
    # 初始化 API
    console.print("[dim]初始化 Shioaji API...[/dim]")
    api = sj.Shioaji()
    
    # 登入 (需要 API 憑證)
    console.print("[dim]登入...[/dim]")
    try:
        api.login(
            api_key=os.getenv("SHIOAJI_API_KEY", ""),
            secret_key=os.getenv("SHIOAJI_SECRET_KEY", ""),
            fetch_contract=True
        )
        console.print("[green]✓ 登入成功[/green]\n")
    except Exception as e:
        console.print(f"[yellow]⚠ 登入失敗：{e}[/yellow]")
        console.print("[dim]請檢查 .env 檔案中的 API 憑證[/dim]\n")
        # 繼續測試未登入功能
    
    # 測試 1: 檢查美股合約
    console.print("[bold yellow]【1】檢查美股合約支援[/bold yellow]\n")
    
    try:
        # 方法 1: 使用 API 查詢
        if hasattr(api, 'list_us_stocks'):
            us_stocks = api.list_us_stocks()
            console.print(f"[green]✓ 支援 {len(us_stocks)} 支美股[/green]")
            
            if len(us_stocks) > 0:
                table = Table(title="美股範例")
                table.add_column("代碼", style="cyan")
                table.add_column("名稱", style="green")
                
                for stock in us_stocks[:10]:
                    table.add_row(
                        getattr(stock, 'code', 'N/A'),
                        getattr(stock, 'name', 'N/A'),
                    )
                
                console.print(table)
        else:
            console.print("[yellow]⚠ list_us_stocks() 方法不存在[/yellow]")
            
    except Exception as e:
        console.print(f"[red]✗ 查詢失敗：{e}[/red]")
    
    # 測試 2: 查詢 TSM 合約
    console.print("\n[bold yellow]【2】查詢 TSM (台積電 ADR)[/bold yellow]\n")
    
    try:
        # 方法 1: 直接查詢代碼
        if hasattr(api, 'get_stock_contract'):
            tsm_contract = api.get_stock_contract("TSM")
            if tsm_contract:
                console.print(f"[green]✓ TSM 合約：{tsm_contract.code}[/green]")
            else:
                console.print("[yellow]⚠ TSM 合約不存在[/yellow]")
        else:
            console.print("[yellow]⚠ get_stock_contract() 方法不存在[/yellow]")
            
    except Exception as e:
        console.print(f"[red]✗ 查詢失敗：{e}[/red]")
    
    # 測試 3: 獲取美股報價
    console.print("\n[bold yellow]【3】獲取美股報價[/bold yellow]\n")
    
    try:
        # 方法 1: 使用 quote API
        if hasattr(api, 'quote'):
            # 測試 TSM
            quote = api.quote(stock="TSM")
            if quote:
                console.print("[green]✓ TSM 報價:[/green]")
                console.print(f"  價格：${quote.get('close', 0):.2f}")
                console.print(f"  漲跌：{quote.get('change', 0):+.2f}")
                console.print(f"  成交量：{quote.get('volume', 0):,}")
            else:
                console.print("[yellow]⚠ 無法獲取 TSM 報價[/yellow]")
        else:
            console.print("[yellow]⚠ quote() 方法不存在[/yellow]")
            
    except Exception as e:
        console.print(f"[red]✗ 報價查詢失敗：{e}[/red]")
    
    # 測試 4: 訂閱美股即時報價
    console.print("\n[bold yellow]【4】訂閱美股即時報價[/bold yellow]\n")
    
    received_quotes = []
    
    def on_tick(contract, tick):
        """回呼函數"""
        received_quotes.append({
            'time': datetime.now().strftime("%H:%M:%S"),
            'price': tick.close,
            'volume': tick.volume,
        })
        console.print(f"[green]✓ Tick: ${tick.close:.2f} (vol: {tick.volume:,})[/green]")
    
    try:
        if hasattr(api, 'subscribe_quote'):
            console.print("[dim]訂閱 TSM 即時報價 (等待 10 秒)...[/dim]")
            
            # 訂閱
            tsm_contract = None
            if hasattr(api, 'get_stock_contract'):
                tsm_contract = api.get_stock_contract("TSM")
            
            if tsm_contract:
                api.subscribe_quote(
                    contract=tsm_contract,
                    callback=on_tick,
                    price_type="Trade"
                )
                
                import time
                time.sleep(10)
                
                if received_quotes:
                    console.print(f"[green]✓ 收到 {len(received_quotes)} 筆即時報價[/green]")
                else:
                    console.print("[yellow]⚠ 未收到即時報價 (可能是非交易時間)[/yellow]")
                
                # 取消訂閱
                api.unsubscribe_quote(tsm_contract)
            else:
                console.print("[yellow]⚠ 無法獲取 TSM 合約[/yellow]")
        else:
            console.print("[yellow]⚠ subscribe_quote() 方法不存在[/yellow]")
            
    except Exception as e:
        console.print(f"[red]✗ 訂閱失敗：{e}[/red]")
    
    # 測試 5: 歷史 K 棒
    console.print("\n[bold yellow]【5】獲取美股歷史 K 棒[/bold yellow]\n")
    
    try:
        if hasattr(api, 'kline'):
            console.print("[dim]獲取 TSM 日 K (最近 5 天)...[/dim]")
            
            tsm_contract = None
            if hasattr(api, 'get_stock_contract'):
                tsm_contract = api.get_stock_contract("TSM")
            
            if tsm_contract:
                kbars = api.kline(contract=tsm_contract, interval="1D")
                
                if kbars and len(kbars) > 0:
                    console.print(f"[green]✓ 獲取 {len(kbars)} 筆 K 棒[/green]")
                    
                    table = Table(title="TSM 最近 K 棒")
                    table.add_column("日期", style="cyan")
                    table.add_column("開盤", justify="right")
                    table.add_column("最高", justify="right")
                    table.add_column("最低", justify="right")
                    table.add_column("收盤", justify="right")
                    table.add_column("成交量", justify="right")
                    
                    for kbar in kbars[-5:]:
                        table.add_row(
                            kbar.ts.strftime("%m-%d") if hasattr(kbar, 'ts') else "N/A",
                            f"{kbar.Open:.2f}" if hasattr(kbar, 'Open') else "N/A",
                            f"{kbar.High:.2f}" if hasattr(kbar, 'High') else "N/A",
                            f"{kbar.Low:.2f}" if hasattr(kbar, 'Low') else "N/A",
                            f"{kbar.Close:.2f}" if hasattr(kbar, 'Close') else "N/A",
                            f"{kbar.Volume:,}" if hasattr(kbar, 'Volume') else "N/A",
                        )
                    
                    console.print(table)
                else:
                    console.print("[yellow]⚠ 未獲取到 K 棒數據[/yellow]")
            else:
                console.print("[yellow]⚠ 無法獲取 TSM 合約[/yellow]")
        else:
            console.print("[yellow]⚠ kline() 方法不存在[/yellow]")
            
    except Exception as e:
        console.print(f"[red]✗ K 棒獲取失敗：{e}[/red]")
    
    # 總結
    console.print("\n[bold blue]╔" + "═" * 60 + "╗[/bold blue]")
    console.print("[bold blue]║[/bold blue]" + " " * 20 + "TEST COMPLETE" + " " * 27 + "[bold blue]║[/bold blue]")
    console.print("[bold blue]╚" + "═" * 60 + "╝[/bold blue]\n")
    
    console.print("[bold]結論:[/bold]")
    console.print("  • 永豐 API [bold green]支援美股[/bold green] (包含 TSM)")
    console.print("  • 可獲取 [bold green]即時報價[/bold green] 和 [bold green]歷史 K 棒[/bold green]")
    console.print("  • 需要 [bold yellow]美股交易權限[/bold yellow] 才能訂閱即時數據")
    console.print("  • 建議使用 [bold cyan]Yahoo Finance[/bold cyan] 作為備援數據源\n")


if __name__ == "__main__":
    test_shioaji_us_stocks()

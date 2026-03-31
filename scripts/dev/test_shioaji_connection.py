#!/usr/bin/env python3
"""
Shioaji API 連線測試腳本

測試項目：
1. API 登入
2. 合約查詢
3. 歷史 K 棒獲取
4. 即時數據訂閱
"""

import sys
import os
from datetime import datetime
from rich.console import Console
from rich.table import Table

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from squeeze_futures.data.shioaji_client import ShioajiClient

console = Console()


def test_login():
    """測試登入"""
    console.print("\n[bold yellow]【1】測試 API 登入[/bold yellow]\n")
    
    client = ShioajiClient()
    
    try:
        result = client.login()
        
        if result:
            console.print("[green]✓ 登入成功[/green]")
            console.print(f"[dim]API Key: {os.getenv('SHIOAJI_API_KEY', 'N/A')[:8]}...[/dim]")
            return client
        else:
            console.print("[red]✗ 登入失敗[/red]")
            console.print("[dim]請檢查 .env 檔案中的 API 憑證[/dim]")
            return None
            
    except Exception as e:
        console.print(f"[red]✗ 錯誤：{e}[/red]")
        return None


def test_contracts(client):
    """測試合約查詢"""
    console.print("\n[bold yellow]【2】測試合約查詢[/bold yellow]\n")
    
    try:
        # TMF 微型台指期
        tmf_contract = client.get_futures_contract("TMF")
        
        if tmf_contract:
            console.print("[green]✓ TMF 合約查詢成功[/green]")
            
            table = Table(title="TMF Contract Info")
            table.add_column("Property", style="cyan")
            table.add_column("Value", justify="right")
            
            table.add_row("Code", tmf_contract.code)
            table.add_row("Name", tmf_contract.name)
            table.add_row("Delivery Month", str(tmf_contract.delivery_month))
            
            console.print(table)
            return tmf_contract
        else:
            console.print("[yellow]⚠ TMF 合約查詢失敗[/yellow]")
            return None
            
    except Exception as e:
        console.print(f"[red]✗ 錯誤：{e}[/red]")
        return None


def test_historical_data(client, contract):
    """測試歷史 K 棒"""
    console.print("\n[bold yellow]【3】測試歷史 K 棒獲取[/bold yellow]\n")
    
    try:
        # 獲取 5m K 棒
        console.print("[dim]獲取 5m K 棒...[/dim]")
        kbars_5m = client.get_kline("TMF", interval="5m")
        
        if kbars_5m is not None and not kbars_5m.empty:
            console.print(f"[green]✓ 獲取成功：{len(kbars_5m)} 筆[/green]")
            
            table = Table(title="Recent 5m K-bars")
            table.add_column("Time", style="cyan")
            table.add_column("Open", justify="right")
            table.add_column("High", justify="right")
            table.add_column("Low", justify="right")
            table.add_column("Close", justify="right")
            table.add_column("Volume", justify="right")
            
            for idx, row in kbars_5m.tail(5).iterrows():
                table.add_row(
                    idx.strftime("%H:%M"),
                    f"{row['Open']:.0f}",
                    f"{row['High']:.0f}",
                    f"{row['Low']:.0f}",
                    f"{row['Close']:.0f}",
                    f"{row.get('Volume', 0):.0f}",
                )
            
            console.print(table)
            return kbars_5m
        else:
            console.print("[yellow]⚠ 未獲取到 K 棒數據[/yellow]")
            return None
            
    except Exception as e:
        console.print(f"[red]✗ 錯誤：{e}[/red]")
        return None


def test_realtime_subscription(client, contract):
    """測試即時數據訂閱"""
    console.print("\n[bold yellow]【4】測試即時數據訂閱[/bold yellow]\n")
    
    console.print("[dim]注意：此測試需要市場開盤時間才能收到數據[/dim]")
    console.print("[dim]訂閱後等待 10 秒...[/dim]\n")
    
    received_ticks = []
    
    def on_tick(contract, tick):
        received_ticks.append({
            'time': datetime.now().strftime("%H:%M:%S"),
            'price': tick.close,
            'volume': tick.volume,
        })
        console.print(f"[green]✓ Tick: {tick.close} (vol: {tick.volume})[/green]")
    
    try:
        # 訂閱
        result = client.subscribe_market_data(contract, on_tick)
        
        if result:
            console.print("[green]✓ 訂閱成功[/green]")
            
            # 等待數據
            import time
            time.sleep(10)
            
            if received_ticks:
                console.print(f"[green]✓ 收到 {len(received_ticks)} 筆數據[/green]")
            else:
                console.print("[yellow]⚠ 未收到數據 (可能是非交易時間)[/yellow]")
            
            # 取消訂閱
            client.unsubscribe_market_data(contract)
            console.print("[dim]已取消訂閱[/dim]")
            
        else:
            console.print("[red]✗ 訂閱失敗[/red]")
            
    except Exception as e:
        console.print(f"[red]✗ 錯誤：{e}[/red]")


def test_account_info(client):
    """測試帳戶資訊查詢"""
    console.print("\n[bold yellow]【5】測試帳戶資訊查詢[/bold yellow]\n")
    
    try:
        # 查詢可用保證金
        margin = client.get_available_margin()
        
        console.print(f"[green]✓ 可用保證金：{margin:,.0f} TWD[/green]")
        
    except Exception as e:
        console.print(f"[dim]查詢失敗：{e}[/dim]")


def main():
    """主函數"""
    console.print("[bold blue]╔" + "═" * 60 + "╗[/bold blue]")
    console.print("[bold blue]║[/bold blue]" + " " * 15 + "SHIOAJI API CONNECTION TEST" + " " * 18 + "[bold blue]║[/bold blue]")
    console.print("[bold blue]╚" + "═" * 60 + "╝[/bold blue]")
    
    # 1. 登入
    client = test_login()
    
    if not client:
        console.print("\n[bold red]測試終止：請先完成 API 登入配置[/bold red]")
        console.print("\n[dim]配置步驟：")
        console.print("1. 複製 .env.example 為 .env")
        console.print("2. 填入您的 API Key 和 Secret Key")
        console.print("3. 設定憑證路徑和密碼")
        console.print("4. 重新執行此腳本[/dim]")
        return
    
    # 2. 合約查詢
    contract = test_contracts(client)
    
    if not contract:
        console.print("\n[bold red]測試終止：無法獲取合約資訊[/bold red]")
        return
    
    # 3. 歷史數據
    test_historical_data(client, contract)
    
    # 4. 即時訂閱
    test_realtime_subscription(client, contract)
    
    # 5. 帳戶資訊
    test_account_info(client)
    
    # 總結
    console.print("\n[bold blue]╔" + "═" * 60 + "╗[/bold blue]")
    console.print("[bold blue]║[/bold blue]" + " " * 20 + "TEST COMPLETE" + " " * 27 + "[bold blue]║[/bold blue]")
    console.print("[bold blue]╚" + "═" * 60 + "╝[/bold blue]")
    
    console.print("\n[green]✓ 所有測試完成[/green]")
    console.print("\n[dim]下一步：")
    console.print("1. 確認 API 連線正常")
    console.print("2. 執行 dry_run_report.py 進行模擬交易")
    console.print("3. 調整參數並開始實盤交易[/dim]")


if __name__ == "__main__":
    main()

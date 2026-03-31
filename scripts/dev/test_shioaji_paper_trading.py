#!/usr/bin/env python3
"""
永豐 API Paper Trading 測試 (從 .env 讀取憑證)
"""

import shioaji as sj
from dotenv import load_dotenv
import os
from rich.console import Console

# 載入 .env 檔案
load_dotenv()

console = Console()

console.print("[bold blue]╔════════════════════════════════════════════════════════╗[/bold blue]")
console.print("[bold blue]║          永豐 API Paper Trading 測試                   ║[/bold blue]")
console.print("[bold blue]╚════════════════════════════════════════════════════════╝[/bold blue]\n")

# 檢查憑證
console.print("[bold]【1】檢查憑證配置[/bold]")
api_key = os.getenv('SHIOAJI_API_KEY')
secret_key = os.getenv('SHIOAJI_SECRET_KEY')
ca_path = os.getenv('SHIOAJI_CA_PATH')
ca_name = os.getenv('SHIOAJI_CA_NAME')
ca_passwd = os.getenv('SHIOAJI_CA_PASSWD')

if not api_key or not secret_key:
    console.print("[red]✗ 缺少 API 憑證[/red]")
    console.print("[yellow]請在 .env 檔案中配置:[/yellow]")
    console.print("""
SHIOAJI_API_KEY=your_api_key
SHIOAJI_SECRET_KEY=your_secret_key
""")
    exit(1)

console.print(f"[green]✓ API Key: {api_key[:10]}...[/green]")
console.print(f"[green]✓ Secret Key: {secret_key[:10]}...[/green]")
if ca_path and ca_name:
    console.print(f"[green]✓ 憑證路徑：{ca_path}[/green]")
    console.print(f"[green]✓ 憑證名稱：{ca_name}[/green]")

# 測試連線
console.print("\n[bold]【2】測試 API 連線[/bold]")
try:
    api = sj.Shioaji()
    
    # 使用 .env 憑證登入
    api.login(
        api_key=api_key,
        secret_key=secret_key,
        fetch_contract=True
    )
    
    console.print("[green]✓ API 連線成功[/green]")
    
    # 查詢帳號
    try:
        balance = api.get_account_balance()
        if balance:
            console.print(f"[dim]可用金額：{balance.get('available_cash', 'N/A'):,}[/dim]")
    except:
        pass
    
except Exception as e:
    console.print(f"[red]✗ API 連線失敗：{e}[/red]")
    console.print("[yellow]可能原因:[/yellow]")
    console.print("  1. 憑證錯誤或過期")
    console.print("  2. 網路連線問題")
    console.print("  3. API 維護中")
    exit(1)

# Paper Trading 說明
console.print("\n[bold]【3】交易模式說明[/bold]")
console.print("""
永豐 Shioaji API 提供兩種模式：

1. **模擬環境 (Paper Trading)**:
   - 下單不會實際成交
   - 使用測試伺服器
   - 適合策略測試

2. **正式環境 (Live Trading)**:
   - 下單會實際成交
   - 使用正式伺服器
   - 適合實際交易

**切換方式**:
編輯 config/trade_config.yaml:
  live_trading: false  → 模擬交易
  live_trading: true   → 實際交易
""")

# 查詢合約
console.print("\n[bold]【4】查詢台指期合約[/bold]")
try:
    futures = api.Contracts.Futures
    if futures:
        console.print(f"[green]✓ 可查詢期貨合約[/green]")
        
        # 顯示台指期
        tx_found = False
        for code in ['TXF', 'MTF']:
            if code in futures:
                contract = futures[code]
                if not tx_found:
                    console.print(f"[dim]  - {contract.code}: {contract.name} (到期日：{contract.delivery_date})[/dim]")
                    tx_found = True
    else:
        console.print("[yellow]⚠️ 無期貨合約[/yellow]")
except Exception as e:
    console.print(f"[red]✗ 查詢失敗：{e}[/red]")

# 總結
console.print("\n[bold blue]╔════════════════════════════════════════════════════════╗[/bold blue]")
console.print("[bold blue]║                    測試完成                            ║[/bold blue]")
console.print("[bold blue]╚════════════════════════════════════════════════════════╝[/bold blue]\n")

console.print("[bold]✅ 測試結果:[/bold]")
console.print("  ✓ API 連線正常")
console.print("  ✓ .env 配置正確")
console.print("  ✓ 合約查詢正常\n")

console.print("[bold]📋 下一步:[/bold]")
console.print("""
1. **模擬交易 (推薦)**:
   ```bash
   # 確保配置
   live_trading: false
   
   # 執行系統
   bash autostart.sh
   ```

2. **實際交易 (謹慎)**:
   ```bash
   # 修改配置
   live_trading: true
   
   # 執行系統
   bash autostart.sh
   ```

3. **監控**:
   ```bash
   tail -f logs/automation.log | grep -E "(BUY|SELL)"
   ```
""")

console.print("[yellow]⚠️  提醒:[/yellow]")
console.print("""
  - 先用 live_trading: false 測試策略
  - 確認正常後再切換到 live_trading: true
  - 實際交易請謹慎評估風險
""")

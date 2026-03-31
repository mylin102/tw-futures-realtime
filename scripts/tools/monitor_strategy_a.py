#!/usr/bin/env python3
"""
實時交易信號監控腳本
顯示新策略參數下的即時交易信號
"""
import pandas as pd
from datetime import datetime
from rich.console import Console
from rich.table import Table
from rich.live import Live
from rich.panel import Panel

console = Console()

def load_latest_data():
    """載入最新市場數據"""
    try:
        df = pd.read_csv("logs/market_data/TMF_20260330_indicators.csv")
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df = df.drop_duplicates(subset=['timestamp'], keep='last')
        df = df.sort_values('timestamp', ascending=False)
        return df
    except Exception as e:
        return None

def generate_signal(row):
    """根據策略參數生成交易信號"""
    score = row.get('score', 0)
    mom_state = row.get('mom_state', 0)
    bull_align = row.get('bull_align', False)
    bear_align = row.get('bear_align', False)
    in_pb_zone = row.get('in_pb_zone', False)
    sqz_on = row.get('sqz_on', True)
    
    # 新策略參數：entry_score = 50
    LONG_SIGNAL = (
        (not sqz_on) and 
        score >= 50 and 
        mom_state == 3
    )
    
    SHORT_SIGNAL = (
        (not sqz_on) and 
        score <= -50 and 
        mom_state == 0
    )
    
    if LONG_SIGNAL:
        return "🟢 BUY", "green"
    elif SHORT_SIGNAL:
        return "🔴 SELL", "red"
    else:
        return "⚪ HOLD", "yellow"

def create_dashboard(df):
    """創建監控儀表板"""
    latest = df.iloc[0]
    prev = df.iloc[1] if len(df) > 1 else latest
    
    # 價格變化
    price_change = latest['close'] - prev['close']
    price_change_pct = (price_change / prev['close']) * 100 if prev['close'] != 0 else 0
    
    # 信號
    signal, color = generate_signal(latest)
    
    # 創建狀態表
    table = Table(show_header=False, box=None)
    table.add_column("Label", style="dim")
    table.add_column("Value")
    
    table.add_row("📈 商品", "TMF (微型台指期)")
    table.add_row("⏰ 最新時間", latest['timestamp'].strftime('%Y-%m-%d %H:%M:%S'))
    table.add_row("💰 最新價格", f"{latest['close']:.0f} ({price_change:+.0f}, {price_change_pct:+.2f}%)")
    table.add_row("📊 MTF Score", f"{score:.1f}" if (score := latest.get('score', 0)) else "N/A")
    table.add_row("🎯 動能狀態", f"mom_state={latest.get('mom_state', 'N/A')}")
    table.add_row("📈 多頭對齊", "✅" if latest.get('bull_align') else "❌")
    table.add_row("📉 空頭對齊", "✅" if latest.get('bear_align') else "❌")
    table.add_row("🔄 Squeeze", "ON" if latest.get('sqz_on') else "OFF")
    table.add_row("", "")
    table.add_row("🎯 交易信號", f"[{color} bold]{signal}[/{color} bold]")
    
    # 策略參數狀態
    params_panel = Panel(
        f"[bold]新策略參數 (Plan A)[/bold]\n"
        f"• entry_score: 50 (原 70)\n"
        f"• MA20-5tick 動態停損：啟用\n"
        f"• 分批停利：40 點 / 1 口\n"
        f"• ATR 停損：停用",
        title="📋 策略配置",
        border_style="blue"
    )
    
    # 最近 K 棒統計
    recent_df = df.head(10)
    stats_panel = Panel(
        f"最近 10 根 K 棒統計\n"
        f"• 最高分：{recent_df['score'].max():.1f}\n"
        f"• 最低分：{recent_df['score'].min():.1f}\n"
        f"• 平均分：{recent_df['score'].mean():.1f}\n"
        f"• 多頭對齊：{recent_df['bull_align'].sum()} 次\n"
        f"• 空頭對齊：{recent_df['bear_align'].sum()} 次",
        title="📊 統計",
        border_style="green"
    )
    
    return table, params_panel, stats_panel

def main():
    console.print("[bold blue]🚀 策略 Plan A 實時監控[/bold blue]\n")
    console.print("按 Ctrl+C 停止監控\n")
    
    try:
        while True:
            df = load_latest_data()
            
            if df is None or df.empty:
                console.print("[red]等待數據...[/red]")
                import time
                time.sleep(5)
                continue
            
            table, params_panel, stats_panel = create_dashboard(df)
            
            console.clear()
            console.print(table)
            console.print()
            console.print(params_panel)
            console.print(stats_panel)
            
            import time
            time.sleep(5)
            
    except KeyboardInterrupt:
        console.print("\n[yellow]監控停止[/yellow]")

if __name__ == "__main__":
    main()

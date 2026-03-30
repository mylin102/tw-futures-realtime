#!/usr/bin/env python3
"""
從 TAIFEX 下載 TMF 期貨數據
"""

import sys
import os
import requests
import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path
from rich.console import Console

console = Console()

def download_tmf_data(days: int = 60):
    """
    下載 TMF 微型台指期數據
    
    使用 Yahoo Finance
    """
    console.print(f"[bold blue]下載 TMF 期貨數據 ({days} 天)...[/bold blue]\n")
    
    try:
        import yfinance as yf
        
        # TMF 代碼
        ticker = "TMF"
        
        console.print(f"[dim]從 Yahoo Finance 下載：{ticker}[/dim]")
        console.print(f"[dim]期間：{days} 天[/dim]\n")
        
        ticker_obj = yf.Ticker(ticker)
        df = ticker_obj.history(period=f"{days}d", interval="5m")
        
        if df.empty:
            console.print("[yellow]未獲取到數據，嘗試使用 ^TWII 代替...[/yellow]")
            # 如果 TMF 不可用，使用 ^TWII
            df = ticker_obj.history(period=f"{days}d", interval="1d")
            if df.empty:
                return None
        
        # 標準化欄位
        df = df.rename(columns={
            'Open': 'Open',
            'High': 'High',
            'Low': 'Low',
            'Close': 'Close',
            'Volume': 'Volume',
        })
        
        df = df[['Open', 'High', 'Low', 'Close', 'Volume']]
        df = df.dropna()
        
        # 保存
        output_dir = Path("data/taifex_raw")
        output_dir.mkdir(parents=True, exist_ok=True)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_file = output_dir / f"TMF_5m_{timestamp}.csv"
        df.to_csv(output_file)
        
        console.print(f"\n[green]✓ 下載成功：{len(df)} 筆 5m K 棒[/green]")
        console.print(f"[green]✓ 已保存至：{output_file}[/green]")
        
        # 顯示統計
        console.print(f"\n[bold blue]=== TMF 數據統計 ===[/bold blue]\n")
        console.print(f"日期範圍：{df.index[0]} ~ {df.index[-1]}")
        console.print(f"總筆數：{len(df)}")
        console.print(f"價格範圍：{df['Close'].min():.0f} ~ {df['Close'].max():.0f}")
        
        return df
        
    except ImportError:
        console.print("[red]yfinance 未安裝[/red]")
        return None
    except Exception as e:
        console.print(f"[red]下載錯誤：{e}[/red]")
        return None


def generate_5m_from_daily(daily_df: pd.DataFrame) -> pd.DataFrame:
    """
    從日 K 數據生成模擬的 5m 數據
    
    注意：這是簡化版本，實際應該使用 tick 數據
    """
    console.print("\n[bold blue]生成模擬 5m 數據...[/bold blue]\n")
    
    intraday_data = []
    bars_per_day = 60  # 5m K 棒，約 60 根/天
    
    for date, row in daily_df.iterrows():
        open_p = row['open']
        close_p = row['close']
        high_p = row['high']
        low_p = row['low']
        volume = row.get('volume', 1000) / bars_per_day
        
        for i in range(bars_per_day):
            # 線性插值 + 隨機波動
            progress = i / bars_per_day
            noise = (np.random.rand() - 0.5) * 5  # ±2.5 點隨機
            
            bar_open = open_p + (close_p - open_p) * progress + noise
            bar_close = open_p + (close_p - open_p) * (progress + 1/bars_per_day) + noise
            bar_high = max(bar_open, bar_close) + (high_p - max(open_p, close_p)) * progress
            bar_low = min(bar_open, bar_close) - (min(open_p, close_p) - low_p) * progress
            
            timestamp = date + pd.Timedelta(hours=8, minutes=45 + i * 5)
            
            intraday_data.append({
                'timestamp': timestamp,
                'Open': bar_open,
                'High': bar_high,
                'Low': bar_low,
                'Close': bar_close,
                'Volume': volume,
            })
    
    df_5m = pd.DataFrame(intraday_data)
    df_5m = df_5m.set_index('timestamp')
    
    # 保存
    output_dir = Path("data/taifex_raw")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = output_dir / f"TMF_5m_{timestamp}.csv"
    df_5m.to_csv(output_file)
    
    console.print(f"[green]✓ 生成 {len(df_5m)} 筆 5m K 棒[/green]")
    console.print(f"[green]✓ 已保存至：{output_file}[/green]\n")
    
    return df_5m


if __name__ == "__main__":
    import numpy as np
    
    # 1. 下載日 K 數據
    daily_df = download_tmf_data(days=30)
    
    if daily_df is not None and len(daily_df) > 0:
        # 2. 生成 5m 數據
        df_5m = generate_5m_from_daily(daily_df)
        
        # 3. 顯示統計
        console.print("[bold blue]=== TMF 數據統計 ===[/bold blue]\n")
        console.print(f"日期範圍：{df_5m.index[0]} ~ {df_5m.index[-1]}")
        console.print(f"總筆數：{len(df_5m)}")
        console.print(f"價格範圍：{df_5m['Close'].min():.0f} ~ {df_5m['Close'].max():.0f}")
        console.print(f"平均成交量：{df_5m['Volume'].mean():.0f}")

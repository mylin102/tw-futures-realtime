#!/usr/bin/env python3
"""
下載台指期歷史數據（TAIFEX）
支援 TMF（微型台指期）和 MTX（小型台指期）

數據來源：
- TAIFEX 官網每日交易資料
- 儲存為 CSV 格式供回測使用
"""

import sys
import os
import requests
import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path
from rich.console import Console
from rich.progress import Progress

console = Console()

# TAIFEX 歷史數據下載 URL
TAIFEX_DAILY_URL = "https://www.taifex.com.tw/cht/9/futuresDataDailyDownload"
TAIFEX_MINUTE_URL = "https://www.taifex.com.tw/cht/9/futuresRT"

# 商品代碼對照
PRODUCT_MAP = {
    "TMF": "MF",      # 微型台指期
    "MTX": "MXF",     # 小型台指期
    "TXF": "TXF",     # 大型台指期
}


def download_taifex_daily(product: str = "MF", start_date: str = None, end_date: str = None):
    """
    下載 TAIFEX 每日交易資料
    
    Args:
        product: 商品代碼 (MF=TMF, MXF=MTX)
        start_date: 開始日期 YYYYMMDD
        end_date: 結束日期 YYYYMMDD
    
    Returns:
        DataFrame with OHLCV data
    """
    if end_date is None:
        end_date = datetime.now().strftime("%Y%m%d")
    
    if start_date is None:
        # 預設下載最近 30 天
        start_date = (datetime.now() - timedelta(days=30)).strftime("%Y%m%d")
    
    console.print(f"[dim]下載 {product} 歷史數據：{start_date} ~ {end_date}[/dim]")
    
    try:
        # TAIFEX 下載參數
        params = {
            "commodityid": product,
            "queryStartDate": start_date,
            "queryEndDate": end_date,
        }
        
        # 發送請求
        headers = {
            "User-Agent": "Mozilla/5.0",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }
        
        response = requests.get(TAIFEX_DAILY_URL, params=params, headers=headers, timeout=30)
        
        if response.status_code != 200:
            console.print(f"[red]下載失敗：HTTP {response.status_code}[/red]")
            return None
        
        # 解析 HTML 表格
        dfs = pd.read_html(response.text)
        if not dfs:
            console.print("[yellow]未找到數據表格[/yellow]")
            return None
        
        df = dfs[0]
        
        # 欄位重命名
        column_map = {
            "交易日期": "date",
            "開盤價": "Open",
            "最高價": "High",
            "最低價": "Low",
            "收盤價": "Close",
            "成交量": "Volume",
        }
        
        df = df.rename(columns=column_map)
        
        # 只保留需要的欄位
        keep_cols = ["date", "Open", "High", "Low", "Close", "Volume"]
        df = df[[c for c in keep_cols if c in df.columns]]
        
        # 轉換日期格式
        df["date"] = pd.to_datetime(df["date"])
        df = df.set_index("date")
        
        # 轉換數值格式
        for col in ["Open", "High", "Low", "Close", "Volume"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        
        df = df.dropna()
        
        console.print(f"[green]下載成功：{len(df)} 筆日 K 數據[/green]")
        return df
        
    except Exception as e:
        console.print(f"[red]下載錯誤：{e}[/red]")
        return None


def generate_intraday_data(daily_df: pd.DataFrame, interval: str = "5m") -> pd.DataFrame:
    """
    從日 K 數據生成模擬的盤中數據（用於回測）
    
    注意：這是簡化版本，實際盤中數據需要從交易所獲取
    
    Args:
        daily_df: 日 K 數據
        interval: 週期 (5m, 15m, 1h)
    
    Returns:
        DataFrame with intraday OHLCV
    """
    console.print(f"[dim]生成 {interval} 模擬盤中數據...[/dim]")
    
    # 簡化：將日 K 數據複製為盤中數據
    # 實際應用應該使用真實的 tick 或 K 棒數據
    
    intraday_data = []
    
    for date, row in daily_df.iterrows():
        # 生成 8:45-13:45 的數據（日盤）
        # 每個區間生成一根 K 棒
        
        # 計算區間數量
        if interval == "5m":
            bars_per_day = 60  # 約 60 根 5m K 棒
        elif interval == "15m":
            bars_per_day = 20
        elif interval == "1h":
            bars_per_day = 5
        else:
            bars_per_day = 60
        
        # 簡單分配價格
        open_price = row["Open"]
        close_price = row["Close"]
        high_price = row["High"]
        low_price = row["Low"]
        
        for i in range(bars_per_day):
            # 線性插值
            progress = i / bars_per_day
            bar_open = open_price + (close_price - open_price) * progress
            bar_close = open_price + (close_price - open_price) * (progress + 1/bars_per_day)
            bar_high = max(bar_open, bar_close) + (high_price - close_price) * (i / bars_per_day)
            bar_low = min(bar_open, bar_close) - (close_price - low_price) * (i / bars_per_day)
            
            timestamp = date + timedelta(hours=8, minutes=45 + i * int(interval.replace("m", "")))
            
            intraday_data.append({
                "timestamp": timestamp,
                "Open": bar_open,
                "High": bar_high,
                "Low": bar_low,
                "Close": bar_close,
                "Volume": row["Volume"] / bars_per_day,
            })
    
    df = pd.DataFrame(intraday_data)
    df = df.set_index("timestamp")
    
    console.print(f"[green]生成 {len(df)} 筆 {interval} 數據[/green]")
    return df


def download_yfinance_data(ticker: str = "^TWII", period: str = "60d", interval: str = "5m"):
    """
    從 Yahoo Finance 下載台股指數數據
    
    Args:
        ticker: 代碼 (^TWII=台股指數)
        period: 期間 (1d, 5d, 1mo, 3mo, 6mo, 1y, 2y, 5y, 10y, ytd, max)
        interval: 週期 (1m, 2m, 5m, 15m, 30m, 60m, 90m, 1h, 1d, 5d, 1wk, 1mo, 3mo)
    
    Returns:
        DataFrame with OHLCV data
    """
    console.print(f"[dim]從 Yahoo Finance 下載 {ticker} ({interval}, {period})...[/dim]")
    
    try:
        import yfinance as yf
        
        ticker_obj = yf.Ticker(ticker)
        df = ticker_obj.history(period=period, interval=interval)
        
        if df.empty:
            console.print("[yellow]未獲取到數據[/yellow]")
            return None
        
        # 清理欄位
        df = df.rename(columns={
            "Open": "Open",
            "High": "High",
            "Low": "Low",
            "Close": "Close",
            "Volume": "Volume",
        })
        
        df = df[["Open", "High", "Low", "Close", "Volume"]]
        df = df.dropna()
        
        console.print(f"[green]下載成功：{len(df)} 筆數據[/green]")
        return df
        
    except ImportError:
        console.print("[yellow]yfinance 未安裝，請執行：pip install yfinance[/yellow]")
        return None
    except Exception as e:
        console.print(f"[red]下載錯誤：{e}[/red]")
        return None


def save_data(df: pd.DataFrame, output_dir: str = "data/taifex_raw", filename: str = None):
    """
    保存數據到 CSV
    
    Args:
        df: 數據 DataFrame
        output_dir: 輸出目錄
        filename: 檔案名稱
    """
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    
    if filename is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"TMF_{timestamp}.csv"
    
    filepath = output_path / filename
    
    # 保存為 CSV
    df.to_csv(filepath)
    
    console.print(f"[green]數據已保存至：{filepath}[/green]")
    return filepath


def main():
    """主函數"""
    console.print("[bold blue]=== TAIFEX 歷史數據下載工具 ===[/bold blue]\n")
    
    # 選擇下載方式
    console.print("請選擇數據來源:")
    console.print("1. Yahoo Finance（推薦，有真實盤中數據）")
    console.print("2. TAIFEX 官網（僅日 K 數據）")
    console.print("3. 使用現有數據")
    
    choice = console.input("\n請輸入選項 (1/2/3): ").strip()
    
    if choice == "1":
        # Yahoo Finance
        period = console.input("下載期間 (預設 60d): ").strip() or "60d"
        interval = console.input("K 棒週期 (預設 5m): ").strip() or "5m"
        
        df = download_yfinance_data("^TWII", period=period, interval=interval)
        
        if df is not None:
            save_data(df)
            
    elif choice == "2":
        # TAIFEX
        product = console.input("商品代碼 (預設 MF=TMF): ").strip() or "MF"
        days = console.input("下載天數 (預設 30): ").strip() or "30"
        
        start_date = (datetime.now() - timedelta(days=int(days))).strftime("%Y%m%d")
        end_date = datetime.now().strftime("%Y%m%d")
        
        daily_df = download_taifex_daily(product, start_date, end_date)
        
        if daily_df is not None:
            # 生成盤中數據
            interval = console.input("生成 K 棒週期 (預設 5m): ").strip() or "5m"
            intraday_df = generate_intraday_data(daily_df, interval)
            save_data(intraday_df)
            
    elif choice == "3":
        console.print("[green]使用現有數據進行回測[/green]")
        console.print("請執行：uv run python scripts/backtest/optimize_entry_params.py")
        
    else:
        console.print("[red]無效選項[/red]")


if __name__ == "__main__":
    main()

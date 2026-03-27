import sys
import os
import time
from datetime import datetime
import pandas as pd
from rich.console import Console
from rich.table import Table
from rich.live import Live
from rich.panel import Panel
from rich.layout import Layout

# 加入 src 到路徑
sys.path.append(os.path.join(os.path.dirname(__file__), "..", "src"))

from squeeze_futures.data.downloader import download_futures_data
from squeeze_futures.engine.indicators import calculate_futures_squeeze, calculate_mtf_alignment

console = Console()

def make_layout() -> Layout:
    layout = Layout()
    layout.split_column(
        Layout(name="header", size=3),
        Layout(name="main", size=15),
        Layout(name="footer", size=10)
    )
    return layout

def generate_status_table(ticker: str, data_dict: dict[str, pd.DataFrame]) -> Table:
    table = Table(show_header=True, header_style="bold magenta", expand=True)
    table.add_column("Timeframe", style="cyan")
    table.add_column("Price", style="white")
    table.add_column("Sqz", justify="center")
    table.add_column("Mom Color", justify="center")
    table.add_column("vs VWAP %", justify="right")
    table.add_column("Signal")
    
    for tf in ["5m", "15m", "1h"]:
        if tf not in data_dict: continue
        df = data_dict[tf]
        if df.empty: continue
        
        last = df.iloc[-1]
        
        # Sqz Status
        sqz_val = "[red]ON[/red]" if last['sqz_on'] else "[green]OFF[/green]"
        
        # Mom Color
        mom_state = last['mom_state']
        mom_colors = {0: "deep_pink4", 1: "light_pink3", 2: "dark_green", 3: "green3"}
        mom_color = mom_colors.get(mom_state, "white")
        mom_text = f"[{mom_color}]████[/{mom_color}]"
        
        # VWAP
        vwap_diff = last['price_vs_vwap'] * 100
        vwap_color = "green" if vwap_diff > 0 else "red"
        vwap_text = f"[{vwap_color}]{vwap_diff:+.2f}%[/{vwap_color}]"
        
        # Signal
        sig = "Wait"
        if last['fired']:
            sig = "[bold yellow]★ FIRED[/bold yellow]"
        elif not last['sqz_on']:
            sig = "Trending"
            
        table.add_row(tf, f"{last['Close']:.1f}", sqz_val, mom_text, vwap_text, sig)
        
    return table

def main(ticker="^TWII"):
    layout = make_layout()
    
    with Live(layout, refresh_per_second=1) as live:
        while True:
            try:
                # 1. 抓取多週期數據
                tfs = ["5m", "15m", "1h"]
                raw_data = {}
                processed_data = {}
                
                for tf in tfs:
                    period = "5d" if tf != "1h" else "1mo"
                    df = download_futures_data(ticker, interval=tf, period=period)
                    if not df.empty:
                        processed_data[tf] = calculate_futures_squeeze(df)
                
                # 2. 計算 MTF Alignment
                alignment = calculate_mtf_alignment(processed_data)
                
                # 3. 更新 UI
                layout["header"].update(Panel(f"[bold white]Real-time MTF Squeeze: {ticker}[/bold white]", style="on blue"))
                layout["main"].update(generate_status_table(ticker, processed_data))
                
                # Footer: Alignment Score
                score = alignment.get('score', 0)
                score_color = "green" if score > 60 else "red" if score < -60 else "yellow"
                score_bar = "█" * int(abs(score)/5)
                
                footer_text = f"\n[bold]MTF Alignment Score: [{score_color}]{score:.1f}[/{score_color}][/bold]\n"
                footer_text += f"Direction: {'[green]BULLISH[/green]' if score > 0 else '[red]BEARISH[/red]'}\n"
                footer_text += f"Strength: {score_bar}\n"
                
                if alignment.get('is_aligned'):
                    footer_text += "\n[blink bold yellow]>>> CONFLUENCE DETECTED <<<[/blink bold yellow]"
                
                layout["footer"].update(Panel(footer_text, title="Strategy Confluence"))
                
                time.sleep(60)
                
            except KeyboardInterrupt:
                break
            except Exception as e:
                console.print(f"Error: {e}")
                time.sleep(10)

if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "^TWII"
    main(target)

import pandas as pd
from datetime import datetime
import os

class PaperTrader:
    def __init__(self, ticker="MXFR1", initial_balance=100000):
        self.ticker = ticker
        self.balance = initial_balance
        self.position = 0  # 0: 空手, 1: 多單, -1: 空單
        self.entry_price = 0
        self.entry_time = None
        self.trades = []
        self.fee_per_side = 20 # 預估手續費+稅

    def execute_signal(self, signal: str, price: float, timestamp: datetime, stop_loss=None, break_even_trigger=None):
        """
        執行信號：'BUY', 'SELL', 'EXIT'
        stop_loss: 初始停損點數
        break_even_trigger: 獲利達此點數後，停損移至成本價
        """
        if signal == "BUY" and self.position == 0:
            self.position = 1
            self.entry_price = price
            self.entry_time = timestamp
            self.current_stop_loss = price - stop_loss if stop_loss else None
            self.be_triggered = False
            self.be_points = break_even_trigger
            return f"Entry LONG at {price} (SL: {self.current_stop_loss})"
            
        elif signal == "SELL" and self.position == 0:
            self.position = -1
            self.entry_price = price
            self.entry_time = timestamp
            self.current_stop_loss = price + stop_loss if stop_loss else None
            self.be_triggered = False
            self.be_points = break_even_trigger
            return f"Entry SHORT at {price} (SL: {self.current_stop_loss})"
            
        elif signal == "EXIT" and self.position != 0:
            pnl_points = (price - self.entry_price) * self.position
            pnl_cash = pnl_points * 10 - (self.fee_per_side * 2)
            
            trade_record = {
                "ticker": self.ticker,
                "entry_time": self.entry_time,
                "exit_time": timestamp,
                "direction": "LONG" if self.position == 1 else "SHORT",
                "entry_price": self.entry_price,
                "exit_price": price,
                "pnl_points": pnl_points,
                "pnl_cash": pnl_cash
            }
            self.trades.append(trade_record)
            self.balance += pnl_cash
            self.position = 0
            self.current_stop_loss = None
            return f"Exit at {price}, PnL: {pnl_cash:.0f}"
            
        return None

    def update_trailing_stop(self, current_price: float):
        """實作保本停損邏輯"""
        if self.position == 0 or not self.be_points or self.be_triggered:
            return
            
        pnl = (current_price - self.entry_price) * self.position
        if pnl >= self.be_points:
            # 獲利達標，移至保本點 (稍微加一點點手續費補償)
            self.current_stop_loss = self.entry_price + (2 * self.position)
            self.be_triggered = True
            return True
        return False

    def check_stop_loss(self, current_price: float, timestamp: datetime):
        """檢查是否觸發停損 (初始停損或保本停損)"""
        if self.position == 1 and self.current_stop_loss and current_price <= self.current_stop_loss:
            return self.execute_signal("EXIT", self.current_stop_loss, timestamp)
        elif self.position == -1 and self.current_stop_loss and current_price >= self.current_stop_loss:
            return self.execute_signal("EXIT", self.current_stop_loss, timestamp)
        return None

    def get_performance_report(self):
        if not self.trades:
            return "No trades executed today."
            
        df = pd.DataFrame(self.trades)
        total_pnl = df['pnl_cash'].sum()
        win_rate = (df['pnl_cash'] > 0).mean() * 100
        
        report = f"""
# 📊 Squeeze Strategy Daily Simulation Report
**Date**: {datetime.now().strftime('%Y-%m-%d')}
**Ticker**: {self.ticker}

## 📈 Performance Summary
- **Total Net PnL**: {total_pnl:+.0f} TWD
- **Total Trades**: {len(df)}
- **Win Rate**: {win_rate:.1f}%
- **Max Gain**: {df['pnl_points'].max():.1f} pts
- **Max Drawdown**: {df['pnl_points'].min():.1f} pts

## 📝 Trade Logs
{df[['entry_time', 'exit_time', 'direction', 'entry_price', 'exit_price', 'pnl_points', 'pnl_cash']].to_markdown()}
"""
        return report

    def get_performance_report_html(self):
        if not self.trades:
            return "<h3>No trades executed today.</h3>"
            
        df = pd.DataFrame(self.trades)
        total_pnl = df['pnl_cash'].sum()
        win_rate = (df['pnl_cash'] > 0).mean() * 100
        pnl_color = "green" if total_pnl >= 0 else "red"
        
        # 建立 HTML 表格
        table_html = df[['entry_time', 'exit_time', 'direction', 'entry_price', 'exit_price', 'pnl_points', 'pnl_cash']].to_html(classes='trade-table', index=False)
        
        html = f"""
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
                .summary {{ background: #f4f4f4; padding: 15px; border-radius: 8px; }}
                .pnl {{ font-size: 24px; font-weight: bold; color: {pnl_color}; }}
                .trade-table {{ width: 100%; border-collapse: collapse; margin-top: 20px; }}
                .trade-table th, .trade-table td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
                .trade-table th {{ background-color: #007bff; color: white; }}
                .trade-table tr:nth-child(even) {{ background-color: #f2f2f2; }}
            </style>
        </head>
        <body>
            <h2>📊 Squeeze Strategy Daily Report</h2>
            <p><strong>Date:</strong> {datetime.now().strftime('%Y-%m-%d')} | <strong>Ticker:</strong> {self.ticker}</p>
            
            <div class="summary">
                <h3>📈 Performance Summary</h3>
                <p>Total Net PnL: <span class="pnl">{total_pnl:+.0f} TWD</span></p>
                <ul>
                    <li>Total Trades: {len(df)}</li>
                    <li>Win Rate: {win_rate:.1f}%</li>
                    <li>Max Gain: {df['pnl_points'].max():.1f} pts</li>
                    <li>Max Drawdown: {df['pnl_points'].min():.1f} pts</li>
                </ul>
            </div>

            <h3>📝 Trade Logs</h3>
            {table_html}
            
            <p style="font-size: 12px; color: #888; margin-top: 30px;">
                Generated by Squeeze Futures Real-time System.
            </p>
        </body>
        </html>
        """
        return html

    def save_report(self):
        report_dir = "exports/simulations"
        os.makedirs(report_dir, exist_ok=True)
        filename = f"{report_dir}/report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
        with open(filename, "w", encoding="utf-8") as f:
            f.write(self.get_performance_report())
        return filename

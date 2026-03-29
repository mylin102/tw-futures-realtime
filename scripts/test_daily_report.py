#!/usr/bin/env python3
"""
測試發送每日交易報告（HTML 格式）
"""
import sys
import os
import json
from datetime import datetime, timedelta
from pathlib import Path

sys.path.append(os.path.join(os.path.dirname(__file__), "src"))
from squeeze_futures.report.notifier import send_email_notification


def generate_test_report():
    """生成測試用的交易報告"""
    
    # 模擬交易數據
    ticker = "TMF"
    live_mode = False  # PAPER 模式測試
    initial_balance = 100000
    
    # 模擬交易記錄
    trades = [
        {
            'entry_time': datetime.now() - timedelta(hours=5),
            'exit_time': datetime.now() - timedelta(hours=4, minutes=45),
            'direction': 'LONG',
            'entry_price': 32000,
            'exit_price': 32040,
            'lots': 2,
            'pnl_cash': 800,
            'total_cost': 53,
        },
        {
            'entry_time': datetime.now() - timedelta(hours=4, minutes=30),
            'exit_time': datetime.now() - timedelta(hours=4, minutes=25),
            'direction': 'SHORT',
            'entry_price': 32050,
            'exit_price': 32048,
            'lots': 2,
            'pnl_cash': 40 - 53,
            'total_cost': 53,
        },
        {
            'entry_time': datetime.now() - timedelta(hours=3),
            'exit_time': datetime.now() - timedelta(hours=2, minutes=40),
            'direction': 'LONG',
            'entry_price': 32100,
            'exit_price': 32150,
            'lots': 2,
            'pnl_cash': 1000 - 53,
            'total_cost': 53,
        },
        {
            'entry_time': datetime.now() - timedelta(hours=2, minutes=30),
            'exit_time': datetime.now() - timedelta(hours=2, minutes=25),
            'direction': 'LONG',
            'entry_price': 32150,
            'exit_price': 32120,
            'lots': 2,
            'pnl_cash': -600 - 53,
            'total_cost': 53,
        },
        {
            'entry_time': datetime.now() - timedelta(hours=2),
            'exit_time': datetime.now() - timedelta(hours=1, minutes=30),
            'direction': 'SHORT',
            'entry_price': 32130,
            'exit_price': 32080,
            'lots': 2,
            'pnl_cash': 1000 - 53,
            'total_cost': 53,
        },
    ]
    
    # 計算統計數據
    pnl = sum(t['pnl_cash'] for t in trades)
    ending_balance = initial_balance + pnl
    
    winning = len([t for t in trades if t['pnl_cash'] > 0])
    losing = len([t for t in trades if t['pnl_cash'] < 0])
    win_rate = (winning / len(trades) * 100) if trades else 0
    
    gross_profit = sum(t['pnl_cash'] for t in trades if t['pnl_cash'] > 0)
    gross_loss = abs(sum(t['pnl_cash'] for t in trades if t['pnl_cash'] < 0))
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else float('inf')
    
    total_cost = sum(t.get('total_cost', 0) for t in trades)
    
    # 生成權益曲線數據
    cumulative = initial_balance
    equity_data = [{'x': 0, 'y': cumulative}]
    for i, trade in enumerate(trades, 1):
        cumulative += trade['pnl_cash']
        equity_data.append({'x': i, 'y': cumulative})
    
    # 交易明細表格
    trades_html = ""
    for t in trades[-20:]:
        pnl_class = "profit" if t['pnl_cash'] > 0 else "loss"
        pnl_sign = "+" if t['pnl_cash'] > 0 else ""
        time_str = t['entry_time'].strftime('%m/%d %H:%M') if isinstance(t['entry_time'], datetime) else str(t['entry_time'])
        side_class = "long" if t['direction'] == 'LONG' else "short"
        side_icon = "🟢" if t['direction'] == 'LONG' else "🔴"
        trades_html += f"""<tr>
            <td>{time_str}</td>
            <td><span class="side {side_class}">{side_icon} {t['direction']}</span></td>
            <td>{t['entry_price']:.0f}</td>
            <td>{t['exit_price']:.0f}</td>
            <td>{t['lots']}</td>
            <td class="{pnl_class}">{pnl_sign}{t['pnl_cash']:,.0f}</td>
        </tr>"""
    
    # 生成 HTML 報告
    html_body = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 0; padding: 20px; background: #f5f5f5; }}
        .container {{ max-width: 900px; margin: 0 auto; background: white; border-radius: 10px; padding: 30px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }}
        h1 {{ color: #1a1a2e; margin-bottom: 10px; }}
        .subtitle {{ color: #666; margin-bottom: 30px; }}
        .metrics {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 20px; margin: 30px 0; }}
        .metric-box {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 20px; border-radius: 10px; text-align: center; }}
        .metric-box.profit {{ background: linear-gradient(135deg, #11998e 0%, #38ef7d 100%); }}
        .metric-box.loss {{ background: linear-gradient(135deg, #eb3349 0%, #f45c43 100%); }}
        .metric-value {{ font-size: 2em; font-weight: bold; margin-bottom: 5px; }}
        .metric-label {{ font-size: 0.9em; opacity: 0.9; }}
        .chart-container {{ position: relative; height: 350px; margin: 30px 0; }}
        table {{ width: 100%; border-collapse: collapse; margin: 30px 0; }}
        th {{ background: #1a1a2e; color: white; padding: 12px; text-align: left; }}
        td {{ padding: 10px; border-bottom: 1px solid #eee; }}
        tr:hover {{ background: #f8f9fa; }}
        .profit {{ color: #11998e; font-weight: bold; }}
        .loss {{ color: #eb3349; font-weight: bold; }}
        .side {{ padding: 4px 8px; border-radius: 4px; font-size: 0.85em; font-weight: bold; }}
        .side.long {{ background: #d4edda; color: #155724; }}
        .side.short {{ background: #f8d7da; color: #721c24; }}
        .footer {{ margin-top: 30px; padding-top: 20px; border-top: 1px solid #eee; color: #666; font-size: 0.9em; text-align: center; }}
        .test-badge {{ display: inline-block; background: #ff9800; color: white; padding: 4px 12px; border-radius: 20px; font-size: 0.8em; margin-left: 10px; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>📊 Daily Trading Report <span class="test-badge">TEST</span></h1>
        <p class="subtitle">Ticker: <strong>{ticker}</strong> | Date: {datetime.now().strftime('%Y-%m-%d')} | Mode: <strong>{'LIVE' if live_mode else 'PAPER'}</strong></p>
        
        <div class="metrics">
            <div class="metric-box {'profit' if pnl > 0 else 'loss'}">
                <div class="metric-value">{pnl:+,.0f}</div>
                <div class="metric-label">Net PnL (TWD)</div>
            </div>
            <div class="metric-box">
                <div class="metric-value">{len(trades)}</div>
                <div class="metric-label">Total Trades</div>
            </div>
            <div class="metric-box">
                <div class="metric-value">{win_rate:.1f}%</div>
                <div class="metric-label">Win Rate</div>
            </div>
            <div class="metric-box">
                <div class="metric-value">{profit_factor:.2f}</div>
                <div class="metric-label">Profit Factor</div>
            </div>
            <div class="metric-box">
                <div class="metric-value">{total_cost:,.0f}</div>
                <div class="metric-label">Total Cost</div>
            </div>
            <div class="metric-box">
                <div class="metric-value">{ending_balance:,.0f}</div>
                <div class="metric-label">Ending Balance</div>
            </div>
        </div>
        
        <div class="chart-container">
            <canvas id="equityChart"></canvas>
        </div>
        
        <h2>📈 Recent Trades ({len(trades)} total)</h2>
        <table>
            <thead>
                <tr>
                    <th>Time</th>
                    <th>Side</th>
                    <th>Entry</th>
                    <th>Exit</th>
                    <th>Lots</th>
                    <th>PnL</th>
                </tr>
            </thead>
            <tbody>
                {trades_html if trades_html else '<tr><td colspan="6" style="text-align: center; color: #999;">No trades today</td></tr>'}
            </tbody>
        </table>
        
        <div class="footer">
            Generated by Squeeze Futures Auto-Trader<br>
            <em style="color: #ff9800;">⚠️ This is a TEST email. No real trades were executed.</em>
        </div>
    </div>
    
    <script>
        const ctx = document.getElementById('equityChart').getContext('2d');
        const equityData = {json.dumps(equity_data)};
        
        new Chart(ctx, {{
            type: 'line',
            data: {{
                labels: equityData.map(d => d.x),
                datasets: [{{
                    label: 'Equity Curve (TWD)',
                    data: equityData.map(d => d.y),
                    borderColor: 'rgb({76 if pnl >= 0 else 235}, {153 if pnl >= 0 else 51}, {102 if pnl >= 0 else 73})',
                    backgroundColor: 'rgba({76 if pnl >= 0 else 235}, {153 if pnl >= 0 else 51}, {102 if pnl >= 0 else 73}, 0.1)',
                    borderWidth: 3,
                    fill: true,
                    tension: 0.3,
                    pointRadius: 3,
                    pointHoverRadius: 5
                }}]
            }},
            options: {{
                responsive: true,
                maintainAspectRatio: false,
                plugins: {{
                    legend: {{ display: false }},
                    tooltip: {{
                        backgroundColor: 'rgba(0, 0, 0, 0.8)',
                        titleColor: '#fff',
                        bodyColor: '#fff',
                        callbacks: {{
                            label: function(context) {{
                                return 'Balance: ' + context.parsed.y.toLocaleString('en-US', {{minimumFractionDigits: 0, maximumFractionDigits: 0}}) + ' TWD';
                            }}
                        }}
                    }}
                }},
                scales: {{
                    x: {{
                        display: true,
                        title: {{ display: true, text: 'Trade Number' }},
                        grid: {{ color: 'rgba(0, 0, 0, 0.05)' }}
                    }},
                    y: {{
                        display: true,
                        title: {{ display: true, text: 'Equity (TWD)' }},
                        grid: {{ color: 'rgba(0, 0, 0, 0.05)' }},
                        ticks: {{
                            callback: function(value) {{
                                return value.toLocaleString('en-US', {{minimumFractionDigits: 0, maximumFractionDigits: 0}});
                            }}
                        }}
                    }}
                }}
            }}
        }});
    </script>
</body>
</html>"""
    
    return html_body, pnl, len(trades), win_rate


def main():
    print("=" * 60)
    print("📧 測試發送每日交易報告")
    print("=" * 60)
    
    print("\n生成測試報告...")
    html_body, pnl, trades, win_rate = generate_test_report()
    
    subject = f"[TW Futures] 🧪 TEST Daily Report TMF {datetime.now().strftime('%Y-%m-%d')} | PnL: {pnl:+,.0f} TWD"
    body_text = f"TEST - Daily PnL: {pnl:+,.0f} TWD | Trades: {trades} | Win Rate: {win_rate:.1f}%"
    
    print(f"\n收件者：mylim304@gmail.com")
    print(f"主旨：{subject}")
    print(f"內容：HTML 格式（含互動式權益曲線圖）")
    
    print("\n發送中...")
    if send_email_notification(subject, body_text, html_body):
        print("\n✅ 測試郵件發送成功！")
        print("   請檢查 mylim304@gmail.com 收件箱")
    else:
        print("\n❌ 測試郵件發送失敗")
        print("   請檢查 ~/.config/squeeze-backtest-email.env 配置")


if __name__ == "__main__":
    main()

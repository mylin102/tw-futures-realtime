import sys
import os

# 加入 src 到路徑
sys.path.append(os.path.join(os.path.dirname(__file__), "..", "src"))

from squeeze_futures.report.notifier import send_email_notification

def test():
    print("Testing HTML Email notification...")
    subject = "Squeeze Strategy HTML Preview"
    
    body_text = "This is a test email for Squeeze strategy simulation reports."
    
    body_html = """
    <html>
    <head>
        <style>
            body { font-family: sans-serif; }
            .pnl { color: green; font-size: 20px; font-weight: bold; }
            table { width: 100%; border-collapse: collapse; }
            th, td { border: 1px solid #ddd; padding: 8px; }
            th { background-color: #007bff; color: white; }
        </style>
    </head>
    <body>
        <h2>📊 Strategy Report Preview</h2>
        <p>This is how your daily report will look in your inbox.</p>
        <div style="background: #f9f9f9; padding: 15px; border-radius: 5px;">
            <p>Total Net PnL: <span class="pnl">+1,200 TWD</span></p>
        </div>
        <h3>📝 Sample Logs</h3>
        <table>
            <tr><th>Time</th><th>Action</th><th>Price</th><th>PnL</th></tr>
            <tr><td>09:30:00</td><td>BUY</td><td>23,450</td><td>-</td></tr>
            <tr><td>10:15:00</td><td>EXIT</td><td>23,570</td><td>+1,200</td></tr>
        </table>
        <p style="color: #888; font-size: 12px;">Testing Squeeze Futures System...</p>
    </body>
    </html>
    """
    
    if send_email_notification(subject, body_text, body_html):
        print("Success! Please check mylim304@gmail.com for the HTML preview.")
    else:
        print("Failed! Check your configuration in ~/.config/squeeze-backtest-email.env")

def test_alert():
    print("\nTesting Real-time TRADE ALERT notification...")
    ticker = "MXFR1"
    action = "BUY (Entry)"
    price = 23456.0
    score = 85.5
    
    subject = f"TRADE ALERT: {ticker} - {action}"
    
    body_text = f"Squeeze Alert: {ticker} {action} at {price}. Score: {score}"
    
    body_html = f"""
    <html>
    <body style="font-family: Arial, sans-serif;">
        <div style="border-left: 10px solid #28a745; background: #e9f7ef; padding: 20px;">
            <h2 style="color: #155724; margin-top: 0;">🚀 Trade Executed: {action}</h2>
            <p style="font-size: 18px;"><strong>Ticker:</strong> {ticker}</p>
            <p style="font-size: 24px; color: #333;"><strong>Price:</strong> {price:,.1f}</p>
            <hr style="border: 0; border-top: 1px solid #c3e6cb;">
            <p><strong>MTF Alignment Score:</strong> <span style="color: green;">{score:.1f} (Strong Bullish)</span></p>
            <p><strong>Time:</strong> {datetime.now().strftime('%H:%M:%S')}</p>
            <p style="font-size: 12px; color: #666;">Status: Position Opened</p>
        </div>
    </body>
    </html>
    """
    
    if send_email_notification(subject, body_text, body_html):
        print("Success! Check for 'TRADE ALERT' in your inbox.")

if __name__ == "__main__":
    from datetime import datetime
    test() # 執行報告預覽
    test_alert() # 執行即時警報預覽

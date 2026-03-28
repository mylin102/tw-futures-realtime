import sys
import os

# 加入 src 到路徑
sys.path.append(os.path.join(os.path.dirname(__file__), "..", "src"))

from squeeze_futures.report.notifier import send_email_notification

def test():
    print("Testing Email notification...")
    subject = "Squeeze Strategy Test Email"
    body = "This is a test email to verify that your Squeeze strategy simulation reports can be sent successfully.\n\nEverything looks good!"
    
    if send_email_notification(subject, body):
        print("Success! Please check your inbox (mylim304@gmail.com).")
    else:
        print("Failed! Check your configuration in ~/.config/squeeze-backtest-email.env")

if __name__ == "__main__":
    test()

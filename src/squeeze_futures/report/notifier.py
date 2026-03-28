import os
import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

def send_email_notification(subject: str, body_markdown: str):
    """
    發送 Email 通知。
    設定讀取自 ~/.config/squeeze-backtest-email.env
    """
    env_path = os.path.expanduser("~/.config/squeeze-backtest-email.env")
    if not os.path.exists(env_path):
        logger.error(f"Email config not found at {env_path}")
        return False
        
    load_dotenv(env_path)
    
    smtp_server = os.getenv("SMTP_SERVER", "smtp.gmail.com")
    smtp_port = int(os.getenv("SMTP_PORT", 587))
    username = os.getenv("SMTP_USERNAME")
    password = os.getenv("SMTP_PASSWORD")
    recipient = os.getenv("SMTP_RECIPIENT")
    
    if not all([username, password, recipient]):
        logger.error("Missing SMTP credentials in config file.")
        return False

    try:
        msg = MIMEMultipart()
        msg['From'] = username
        msg['To'] = recipient
        msg['Subject'] = subject
        
        # 將 Markdown 內容加入 Email (純文字格式)
        msg.attach(MIMEText(body_markdown, 'plain'))
        
        server = smtplib.SMTP(smtp_server, smtp_port)
        server.starttls()
        server.login(username, password)
        server.send_message(msg)
        server.quit()
        
        logger.info(f"Email sent successfully to {recipient}")
        return True
    except Exception as e:
        logger.error(f"Failed to send email: {str(e)}")
        return False

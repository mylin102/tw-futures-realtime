import os
import logging
import pandas as pd
from dotenv import load_dotenv
from datetime import datetime, timedelta

try:
    import shioaji as sj
except ImportError:
    sj = None

load_dotenv()
logger = logging.getLogger(__name__)

class ShioajiClient:
    def __init__(self):
        self.api = None
        self.is_logged_in = False
        if sj is None: return
        self.api = sj.Shioaji()

    def login(self):
        api_key = os.getenv("SHIOAJI_API_KEY")
        secret_key = os.getenv("SHIOAJI_SECRET_KEY")
        cert_path = os.getenv("SHIOAJI_CERT_PATH")
        cert_password = os.getenv("SHIOAJI_CERT_PASSWORD")
        if not all([api_key, secret_key]): return False
        try:
            self.api.login(api_key=api_key, secret_key=secret_key, fetch_contract=True)
            if cert_path and os.path.exists(cert_path):
                self.api.activate_ca(ca_path=cert_path, ca_passwd=cert_password, person_id=api_key)
            self.is_logged_in = True
            return True
        except Exception as e:
            logger.error(f"Shioaji login failed: {e}")
            return False

    def get_available_margin(self):
        """查詢期貨帳戶可用保證金 (TWD)"""
        if not self.is_logged_in: return 0
        try:
            # 取得所有帳戶的權益數
            margins = self.api.get_account_margin()
            # 這裡簡單取第一個期貨帳戶的可用餘額 (Available Margin)
            if margins:
                return float(margins[0].available_margin)
            return 0
        except Exception as e:
            logger.error(f"Failed to fetch margin: {e}")
            return 0

    def get_futures_contract(self, ticker: str):
        if not self.is_logged_in: return None
        try:
            if ticker == 'TXFR1': return self.api.Contracts.Futures.TXF.TXFR1
            if ticker == 'MXFR1': return self.api.Contracts.Futures.MXF.MXFR1
            if ticker == 'TMF':
                contracts = [c for c in self.api.Contracts.Futures.TMF if c.delivery_month]
                return sorted(contracts, key=lambda x: x.delivery_month)[0]
            return None
        except Exception: return None

    def place_order(self, contract, action: str, quantity: int, price: float = 0):
        if not self.is_logged_in: return None
        try:
            order = self.api.Order(
                action=action, price=price, quantity=quantity,
                order_type=sj.constant.OrderType.MTL,
                price_type=sj.constant.StockPriceType.MKT if price == 0 else sj.constant.StockPriceType.LMT,
                market_type=sj.constant.FuturesMarketType.Night if datetime.now().hour >= 15 or datetime.now().hour < 5 else sj.constant.FuturesMarketType.Common
            )
            trade = self.api.place_order(contract, order)
            return trade
        except Exception as e:
            logger.error(f"Order placement failed: {e}")
            return None

    def get_kline(self, ticker: str, interval: str = "5m"):
        if not self.is_logged_in: return pd.DataFrame()
        try:
            contract = self.get_futures_contract(ticker)
            if not contract: return pd.DataFrame()
            start_date = (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d")
            kbars = self.api.kbars(contract, start=start_date)
            df = pd.DataFrame({**kbars})
            if df.empty: return df
            df.ts = pd.to_datetime(df.ts)
            df.set_index('ts', inplace=True)
            df = df.rename(columns={'Open':'Open','High':'High','Low':'Low','Close':'Close','Volume':'Volume'})
            return df
        except Exception: return pd.DataFrame()

    def logout(self):
        if self.api: self.api.logout()

import pandas as pd
import numpy as np
import pandas_ta as ta

def calculate_futures_squeeze(df: pd.DataFrame, bb_length=14, bb_std=2.0, kc_length=14, kc_scalar=1.5, 
                             ema_fast=20, ema_slow=60, lookback=60, pb_buffer=1.002, ema_macro=200) -> pd.DataFrame:
    """
    統一欄位格式：Open, High, Low, Close, Volume 為首字母大寫。
    內部指標：sqz_on, momentum, vwap, mom_state, fired 等為小寫。
    """
    if df.empty or len(df) < max(bb_length, ema_slow, lookback, ema_macro):
        return df

    df = df.copy()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(-1)
    
    # 確保標準 OHLCV 欄位大寫
    name_map = {c: c.capitalize() for c in df.columns if c.lower() in ['open', 'high', 'low', 'close', 'volume']}
    df = df.rename(columns=name_map)

    # 1. 基礎 Squeeze 計算
    sqz = df.ta.squeeze(bb_length=bb_length, bb_std=bb_std, kc_length=kc_length, kc_scalar=kc_scalar, lazy=True)
    res = df.copy()
    
    sqz_on_cols = [c for c in sqz.columns if 'SQZ_ON' in c]
    res['sqz_on'] = sqz[sqz_on_cols[0]].astype(bool) if sqz_on_cols else False
    
    mom_cols = [c for c in sqz.columns if 'SQZ_' in c and not any(x in c for x in ['ON', 'OFF', 'NO'])]
    res['momentum'] = sqz[mom_cols[0]].fillna(0) if mom_cols else 0
    
    res['vwap'] = (res['Close'] * res['Volume']).cumsum() / res['Volume'].cumsum()
    res['fired'] = (~res['sqz_on']) & (res['sqz_on'].shift(1) == True)
    
    # 2. 動能狀態
    res['mom_prev'] = res['momentum'].shift(1).fillna(0)
    def get_mom_state(row):
        m, p = row['momentum'], row['mom_prev']
        if m > 0: return 3 if m >= p else 2
        else: return 0 if m <= p else 1
    res['mom_state'] = res.apply(get_mom_state, axis=1)
    
    # 3. 趨勢指標
    res['ema_fast'] = df.ta.ema(length=ema_fast)
    res['ema_slow'] = df.ta.ema(length=ema_slow)
    res['ema_filter'] = df.ta.ema(length=60) 
    res['ema_macro'] = df.ta.ema(length=ema_macro)
    res['bullish_align'] = res['ema_fast'] > res['ema_slow']
    res['bearish_align'] = res['ema_fast'] < res['ema_slow']
    
    # 4. 極值與拉回
    res['recent_high'] = res['Close'].rolling(window=lookback).max()
    res['recent_low'] = res['Close'].rolling(window=lookback).min()
    res['is_new_high'] = res['Close'] >= res['recent_high'].shift(1)
    res['is_new_low'] = res['Close'] <= res['recent_low'].shift(1)
    res['in_bull_pb_zone'] = (res['Close'] <= res['ema_fast'] * pb_buffer) & (res['Close'] >= res['ema_slow']) & res['bullish_align']
    res['in_bear_pb_zone'] = (res['Close'] >= res['ema_fast'] * (2 - pb_buffer)) & (res['Close'] <= res['ema_slow']) & res['bearish_align']
    
    # 5. 開盤強弱判定
    res['date'] = res.index.date
    res['day_open'] = res.groupby('date')['Open'].transform('first')
    res['day_min'] = res.groupby('date')['Low'].cummin()
    res['day_max'] = res.groupby('date')['High'].cummax()
    res['opening_bullish'] = (res['Close'] > res['day_open']) & (res['day_min'] >= res['day_open'] * 0.999)
    res['opening_bearish'] = (res['Close'] < res['day_open']) & (res['day_max'] <= res['day_open'] * 1.001)
    
    return res

def calculate_mtf_alignment(data_dict: dict[str, pd.DataFrame], weights=None) -> dict:
    if not data_dict: return {"score": 0, "is_aligned": False}
    if weights is None: weights = {"1h": 0.2, "15m": 0.4, "5m": 0.4}
    latest_states = {}
    for tf, df in data_dict.items():
        if df.empty: continue
        last = df.iloc[-1]
        direction = 1 if last['momentum'] > 0 else -1
        strength = 1.5 if (last['mom_state'] in [0, 3]) else 1.0
        latest_states[tf] = direction * strength
    total_score = 0
    available_weight = 0
    for tf, val in latest_states.items():
        w = weights.get(tf, 0.1); total_score += val * w; available_weight += w
    norm_score = (total_score / (1.5 * available_weight)) * 100 if available_weight > 0 else 0
    return {"score": norm_score, "states": latest_states, "is_aligned": abs(norm_score) >= 60}

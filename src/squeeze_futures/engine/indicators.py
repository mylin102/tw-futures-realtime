import pandas as pd
import numpy as np
import pandas_ta as ta

def calculate_futures_squeeze(df: pd.DataFrame, bb_length=14, bb_std=2.0, kc_length=14, kc_scalar=1.5) -> pd.DataFrame:
    """
    優化後的 Squeeze 指標，支援自定義週期（預設改為 14 提高靈敏度）。
    """
    if df.empty or len(df) < bb_length:
        return df

    # 數據標準化
    df = df.copy()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(-1)
    df.columns = [c.capitalize() for c in df.columns]

    # 1. 基礎 TTM Squeeze 計算
    sqz = df.ta.squeeze(bb_length=bb_length, bb_std=bb_std, kc_length=kc_length, kc_scalar=kc_scalar, lazy=True)
    
    sqz_on_col = [c for c in sqz.columns if 'SQZ_ON' in c][0]
    mom_col = [c for c in sqz.columns if c.startswith('SQZ_') and c not in ['SQZ_ON', 'SQZ_OFF', 'SQZ_NO']][0]
    
    # 2. 能量等級 (Energy Level)
    bb = df.ta.bbands(length=bb_length, std=bb_std)
    kc = df.ta.kc(length=kc_length, scalar=kc_scalar)
    
    # 確保 BB 與 KC 欄位存在
    try:
        bb_width = bb.iloc[:, 2] - bb.iloc[:, 0] # Upper - Lower
        kc_width = kc.iloc[:, 2] - kc.iloc[:, 0] # Upper - Lower
        squeeze_ratio = (kc_width - bb_width) / kc_width
    except:
        squeeze_ratio = 0
    
    # 3. 穩定的 VWAP
    if 'Volume' in df.columns and df['Volume'].sum() > 0:
        vwap_val = (df['Close'] * df['Volume']).cumsum() / df['Volume'].cumsum()
    else:
        vwap_val = df['Close'].rolling(window=bb_length).mean()
    
    # 4. 集成結果
    res = df.copy()
    res['sqz_on'] = sqz[sqz_on_col].astype(bool)
    res['momentum'] = sqz[mom_col].fillna(0)
    res['sqz_ratio'] = squeeze_ratio
    res['vwap'] = vwap_val
    res['price_vs_vwap'] = ((res['Close'] - res['vwap']) / res['vwap']).fillna(0)
    
    # 5. 動能狀態 (0-3)
    res['mom_prev'] = res['momentum'].shift(1).fillna(0)
    def get_mom_state(row):
        m, p = row['momentum'], row['mom_prev']
        if m > 0: return 3 if m >= p else 2
        else: return 0 if m <= p else 1
    res['mom_state'] = res.apply(get_mom_state, axis=1)
    
    # 6. Fired 信號
    res['fired'] = (~res['sqz_on']) & (res['sqz_on'].shift(1) == True)
    
    # 7. 新增：趨勢排列指標 (EMA 20/60)
    res['ema_fast'] = df.ta.ema(length=20)
    res['ema_slow'] = df.ta.ema(length=60)
    res['bullish_align'] = res['ema_fast'] > res['ema_slow']
    
    # 8. 新增：近期新高與拉回判定
    res['recent_high'] = res['Close'].rolling(window=60).max()
    res['is_new_high'] = res['Close'] >= res['recent_high'].shift(1)
    # 拉回區間：價格位於 EMA 20 與 EMA 60 之間，且處於多頭排列
    res['in_pullback_zone'] = (res['Close'] <= res['ema_fast'] * 1.002) & (res['Close'] >= res['ema_slow']) & res['bullish_align']
    
    return res

def calculate_mtf_alignment(data_dict: dict[str, pd.DataFrame], weights=None) -> dict:
    """
    計算多週期共振分數，支援自定義權重。
    """
    if not data_dict: return {"score": 0, "is_aligned": False}
    if weights is None: weights = {"1h": 0.3, "15m": 0.4, "5m": 0.3} # 預設改為中短線優先
    
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
        w = weights.get(tf, 0.1)
        total_score += val * w
        available_weight += w
        
    norm_score = (total_score / (1.5 * available_weight)) * 100 if available_weight > 0 else 0
    return {"score": norm_score, "states": latest_states, "is_aligned": abs(norm_score) >= 60}

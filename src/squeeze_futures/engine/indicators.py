import pandas as pd
import numpy as np
import pandas_ta as ta

def calculate_futures_squeeze(df: pd.DataFrame, bb_length=20, bb_std=2.0, kc_length=20, kc_scalar=1.5) -> pd.DataFrame:
    """
    專為期貨設計的 Squeeze 指標計算，包含穩定的 VWAP 處理。
    """
    if df.empty or len(df) < bb_length:
        return df

    # 數據標準化 (處理大小寫與 MultiIndex)
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
    
    bb_width = bb.filter(like='BBU').iloc[:, 0] - bb.filter(like='BBL').iloc[:, 0]
    kc_width = kc.filter(like='KCU').iloc[:, 0] - kc.filter(like='KCL').iloc[:, 0]
    squeeze_ratio = (kc_width - bb_width) / kc_width
    
    # 3. 穩定的 VWAP/基準線計算
    # 檢查是否有成交量數據且不全為零
    has_volume = 'Volume' in df.columns and df['Volume'].sum() > 0
    
    if has_volume:
        try:
            # 嘗試計算 VWAP
            vwap_temp = df.ta.vwap()
            if vwap_temp is not None and not vwap_temp.isna().all():
                vwap_val = vwap_temp
            else:
                # 手動計算累計 VWAP 備案
                vwap_val = (df['Close'] * df['Volume']).cumsum() / df['Volume'].cumsum()
        except:
            vwap_val = (df['Close'] * df['Volume']).cumsum() / df['Volume'].cumsum()
    else:
        # 無成交量時，使用 20 週期均線作為替代基準
        vwap_val = df['Close'].rolling(window=bb_length).mean()
    
    # 4. 集成結果
    res = df.copy()
    res['sqz_on'] = sqz[sqz_on_col].astype(bool)
    res['momentum'] = sqz[mom_col].fillna(0)
    res['sqz_ratio'] = squeeze_ratio.fillna(0)
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
    
    return res

def calculate_mtf_alignment(data_dict: dict[str, pd.DataFrame]) -> dict:
    """
    計算多週期共振分數。
    """
    if not data_dict: return {"score": 0, "is_aligned": False}
    
    latest_states = {}
    
    for tf, df in data_dict.items():
        if df.empty: continue
        last = df.iloc[-1]
        
        # 動能方向：1 (正), -1 (負)
        direction = 1 if last['momentum'] > 0 else -1
        # 強度：增強中 (State 0 或 3) 權重較高
        strength = 1.5 if (last['mom_state'] in [0, 3]) else 1.0
        
        latest_states[tf] = direction * strength
        
    # 綜合評分 (-100 到 100)
    weights = {"1h": 0.5, "15m": 0.3, "5m": 0.2}
    total_score = 0
    available_weight = 0
    
    for tf, val in latest_states.items():
        w = weights.get(tf, 0.1)
        total_score += val * w
        available_weight += w
        
    if available_weight > 0:
        # 正規化到 -100 ~ 100
        norm_score = (total_score / (1.5 * available_weight)) * 100
    else:
        norm_score = 0
        
    return {
        "score": norm_score,
        "states": latest_states,
        "is_aligned": abs(norm_score) >= 60
    }

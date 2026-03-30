#!/usr/bin/env python3
"""
進場策略參數優化回測腳本
使用 vectorbt-pro 風格的參數網格搜索

測試不同進場參數組合：
- entry_score: [20, 30, 40, 50, 60, 70]
- mom_state_long: [2, 3] (多頭動能條件)
- mom_state_short: [0, 1] (空頭動能條件)
- regime_filter: ["loose", "mid", "strict"]
- use_pb: [True, False] (是否使用回測進場)
"""

import sys
import os
import pandas as pd
import numpy as np
from datetime import datetime
from pathlib import Path
from itertools import product
from rich.console import Console
from rich.table import Table
import yaml

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from squeeze_futures.engine.constants import get_point_value
from squeeze_futures.engine.simulator import PaperTrader
from squeeze_futures.engine.indicators import calculate_futures_squeeze, calculate_mtf_alignment, calculate_atr

console = Console()


def load_config():
    """載入配置文件"""
    config_path = Path(__file__).parent.parent.parent / "config" / "trade_config.yaml"
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_market_data(data_dir="logs/market_data"):
    """載入儲存的市場數據"""
    data_files = list(Path(data_dir).glob("TMF_*.csv"))
    
    # 如果沒有儲存的數據，嘗試從 historical_backtest 載入
    if not data_files:
        console.print("[yellow]找不到儲存的市場數據，嘗試從 data/taifex_raw 載入...[/yellow]")
        from scripts.backtest.historical_backtest import load_and_resample
        p5, p15, p1h = load_and_resample("data/taifex_raw")
        if p5 is not None and len(p5) > 0:
            console.print(f"[green]載入 {len(p5)} 筆 5m K 棒數據[/green]")
            return p5
        return None
    
    # 合併所有數據檔案
    all_data = []
    for file in sorted(data_files):
        df = pd.read_csv(file, index_col=0, parse_dates=True)
        all_data.append(df)
    
    if not all_data:
        return None
    
    # 合併並去重
    combined = pd.concat(all_data)
    combined = combined[~combined.index.duplicated(keep='last')]
    combined = combined.sort_index()
    
    # 確保欄位名稱正確（大寫）
    combined.columns = combined.columns.str.capitalize()
    
    # 確保有 Open 欄位
    if 'Open' not in combined.columns and 'open' in combined.columns.str.lower():
        combined['Open'] = combined['Close']  # 如果沒有 Open，用 Close 代替
    
    console.print(f"[green]載入 {len(combined)} 筆 K 棒數據[/green]")
    console.print(f"時間範圍：{combined.index[0]} ~ {combined.index[-1]}")
    
    return combined


def run_param_backtest(df, params, cfg):
    """
    執行單一參數組合回測（使用已計算好的指標數據）
    
    Args:
        df: 市場數據 DataFrame（需包含 score, sqz_on, mom_state, regime, bull_align, bear_align, in_pb_zone, Close, vwap, Open）
        params: 參數字典
        cfg: 配置文件
    
    Returns:
        回測結果字典
    """
    # 解構參數
    entry_score = params['entry_score']
    mom_state_long = params['mom_state_long']
    mom_state_short = params['mom_state_short']
    regime_filter = params['regime_filter']
    use_pb = params['use_pb']
    
    # 初始化交易器
    EXEC = cfg.get('execution', {})
    trader = PaperTrader(
        ticker="TMF",
        initial_balance=EXEC.get('initial_balance', 100000),
        point_value=get_point_value("TMF"),
        fee_per_side=EXEC.get('broker_fee_per_side', 20),
        exchange_fee_per_side=EXEC.get('exchange_fee_per_side', 0),
        tax_rate=EXEC.get('tax_rate', 0.0)
    )
    
    # 策略參數
    STRATEGY = cfg['strategy']
    MGMT = cfg['trade_mgmt']
    RISK = cfg['risk_mgmt']
    TP = STRATEGY.get('partial_exit', {})
    
    # 確保數據有必要的欄位
    required_cols = ['Close', 'score', 'sqz_on', 'mom_state', 'regime', 'bull_align', 'bear_align', 'in_pb_zone']
    for col in required_cols:
        if col not in df.columns:
            df[col] = 0 if col in ['score', 'mom_state'] else False
    
    # 如果沒有 Open，用 Close 代替
    if 'Open' not in df.columns:
        df['Open'] = df['Close']
    if 'vwap' not in df.columns:
        df['vwap'] = df['Close']
    
    # 回測主循環
    has_tp1_hit = False
    PB_CONFIRM_BARS = cfg.get('monitoring', {}).get('pb_confirmation_bars', 12)
    
    for i in range(len(df)):
        row = df.iloc[i]
        timestamp = row.name if hasattr(row, 'name') else df.index[i]
        last_price = row['Close']
        vwap = row.get('vwap', last_price)
        score = row['score']
        
        # 趨勢過濾（使用 regime 欄位）
        regime = row.get('regime', 'NORMAL')
        if regime_filter == "loose":
            can_long = True
            can_short = True
        elif regime_filter == "mid":
            can_long = regime in ['STRONG', 'NORMAL']
            can_short = regime in ['WEAK', 'NORMAL']
        else:  # strict
            can_long = regime == 'STRONG'
            can_short = regime == 'WEAK'
        
        # 停損計算
        stop_loss_pts = RISK.get('stop_loss_pts', 30)
        
        # 進場邏輯
        if trader.position == 0:
            has_tp1_hit = False
            
            # 多頭進場
            sqz_buy = (not row['sqz_on']) and score >= entry_score and last_price > vwap
            sqz_buy = sqz_buy and (row['mom_state'] >= mom_state_long)
            
            pb_buy = False
            if use_pb:
                pb_buy = row.get('bull_align', False) and row.get('in_pb_zone', False) and last_price > row['Open']
            
            if (sqz_buy or pb_buy) and can_long and MGMT.get("allow_long", True):
                trader.execute_signal(
                    "BUY", last_price, timestamp,
                    lots=MGMT.get("lots_per_trade", 2),
                    max_lots=MGMT.get("max_positions", 2),
                    stop_loss=stop_loss_pts,
                    break_even_trigger=RISK.get("break_even_pts", 30)
                )
            
            # 空頭進場
            sqz_sell = (not row['sqz_on']) and score <= -entry_score and last_price < vwap
            sqz_sell = sqz_sell and (row['mom_state'] <= mom_state_short)
            
            pb_sell = False
            if use_pb:
                pb_sell = row.get('bear_align', False) and row.get('in_pb_zone', False) and last_price < row['Open']
            
            if (sqz_sell or pb_sell) and can_short and MGMT.get("allow_short", True):
                trader.execute_signal(
                    "SELL", last_price, timestamp,
                    lots=MGMT.get("lots_per_trade", 2),
                    max_lots=MGMT.get("max_positions", 2),
                    stop_loss=stop_loss_pts,
                    break_even_trigger=RISK.get("break_even_pts", 30)
                )
        
        # 分批停利與停損
        else:
            trader.update_trailing_stop(last_price)
            
            if TP.get('enabled', True) and abs(trader.position) == MGMT.get('lots_per_trade', 2) and not has_tp1_hit:
                pnl_pts = (last_price - trader.entry_price) * (1 if trader.position > 0 else -1)
                if pnl_pts >= TP.get('tp1_pts', 30):
                    trader.execute_signal("PARTIAL_EXIT", last_price, timestamp, TP.get('tp1_lots', 1))
                    has_tp1_hit = True
                    trader.current_stop_loss = trader.entry_price
            
            # VWAP 離場
            if RISK.get('exit_on_vwap', True):
                if (trader.position > 0 and last_price < vwap) or \
                   (trader.position < 0 and last_price > vwap):
                    trader.execute_signal("EXIT", last_price, timestamp, abs(trader.position))
    
    # 計算績效指標
    trades = trader.trades
    if not trades:
        return None
    
    winning = len([t for t in trades if t['pnl_cash'] > 0])
    losing = len([t for t in trades if t['pnl_cash'] < 0])
    total_trades = len(trades)
    
    gross_profit = sum(t['pnl_cash'] for t in trades if t['pnl_cash'] > 0)
    gross_loss = abs(sum(t['pnl_cash'] for t in trades if t['pnl_cash'] < 0))
    total_cost = sum(t.get('total_cost', 0) for t in trades)
    
    net_profit = gross_profit - gross_loss - total_cost
    win_rate = (winning / total_trades * 100) if total_trades > 0 else 0
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else float('inf')
    avg_trade = net_profit / total_trades if total_trades > 0 else 0
    
    # 計算最大回撤
    equity_curve = [100000]
    for trade in trades:
        equity_curve.append(equity_curve[-1] + trade['pnl_cash'])
    
    max_dd = 0
    peak = equity_curve[0]
    for eq in equity_curve:
        if eq > peak:
            peak = eq
        dd = peak - eq
        if dd > max_dd:
            max_dd = dd
    
    return {
        'params': params,
        'net_profit': net_profit,
        'total_trades': total_trades,
        'win_rate': win_rate,
        'profit_factor': profit_factor,
        'avg_trade': avg_trade,
        'max_drawdown': max_dd,
        'gross_profit': gross_profit,
        'gross_loss': gross_loss,
        'total_cost': total_cost,
        'final_balance': trader.balance,
    }


def run_parameter_optimization():
    """執行參數優化"""
    console.print("[bold blue]=== 進場策略參數優化回測 ===[/bold blue]\n")
    
    # 載入配置和數據
    cfg = load_config()
    df = load_market_data()
    
    if df is None or len(df) < 20:
        console.print("[red]數據不足，需要至少 20 筆 K 棒[/red]")
        return
    
    # 定義參數網格
    param_grid = {
        'entry_score': [20, 30, 40, 50, 60, 70],
        'mom_state_long': [2, 3],
        'mom_state_short': [0, 1],
        'regime_filter': ['loose', 'mid'],
        'use_pb': [True, False],
    }
    
    # 生成所有參數組合
    param_combinations = list(product(
        param_grid['entry_score'],
        param_grid['mom_state_long'],
        param_grid['mom_state_short'],
        param_grid['regime_filter'],
        param_grid['use_pb']
    ))
    
    console.print(f"[yellow]測試 {len(param_combinations)} 種參數組合[/yellow]\n")
    
    # 執行回測
    results = []
    for i, (es, msl, mss, rf, upb) in enumerate(param_combinations):
        params = {
            'entry_score': es,
            'mom_state_long': msl,
            'mom_state_short': mss,
            'regime_filter': rf,
            'use_pb': upb,
        }
        
        result = run_param_backtest(df, params, cfg)
        if result:
            results.append(result)
        
        if (i + 1) % 20 == 0:
            console.print(f"[dim]進度：{i+1}/{len(param_combinations)}[/dim]")
    
    if not results:
        console.print("[red]回測失敗，沒有產生任何交易[/red]")
        return
    
    # 轉換為 DataFrame
    results_df = pd.DataFrame(results)
    
    # 排序並顯示最佳結果
    console.print("\n[bold green]=== 最佳 20 組參數 ===[/bold green]\n")
    
    # 按淨利排序
    top_by_profit = results_df.nlargest(20, 'net_profit')
    
    table = Table(title="按淨利排序 Top 20")
    table.add_column("Rank", style="dim")
    table.add_column("Entry Score", justify="right")
    table.add_column("MS Long", justify="right")
    table.add_column("MS Short", justify="right")
    table.add_column("Regime", justify="center")
    table.add_column("Use PB", justify="center")
    table.add_column("Net Profit", justify="right", style="green")
    table.add_column("Trades", justify="right")
    table.add_column("Win Rate", justify="right")
    table.add_column("PF", justify="right")
    table.add_column("Max DD", justify="right", style="red")
    
    for idx, row in top_by_profit.iterrows():
        p = row['params']
        table.add_row(
            str(idx + 1),
            str(p['entry_score']),
            str(p['mom_state_long']),
            str(p['mom_state_short']),
            p['regime_filter'],
            "✓" if p['use_pb'] else "✗",
            f"{row['net_profit']:,.0f}",
            str(row['total_trades']),
            f"{row['win_rate']:.1f}%",
            f"{row['profit_factor']:.2f}",
            f"{row['max_drawdown']:,.0f}",
        )
    
    console.print(table)
    
    # 保存結果
    output_dir = Path(__file__).parent.parent / "exports" / "optimizations"
    output_dir.mkdir(parents=True, exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = output_dir / f"entry_params_optimization_{timestamp}.csv"
    results_df.to_csv(output_file, index=False)
    
    console.print(f"\n[green]結果已保存至：{output_file}[/green]")
    
    # 參數分析
    console.print("\n[bold blue]=== 參數影響分析 ===[/bold blue]\n")
    
    # Entry Score 影響
    score_analysis = results_df.groupby(results_df['params'].apply(lambda x: x['entry_score'])).agg({
        'net_profit': ['mean', 'std', 'count'],
        'win_rate': 'mean',
        'profit_factor': 'mean',
    }).round(2)
    console.print("[yellow]Entry Score 影響:[/yellow]")
    console.print(score_analysis)
    
    # Mom State 影響
    ms_long_analysis = results_df.groupby(results_df['params'].apply(lambda x: x['mom_state_long'])).agg({
        'net_profit': ['mean', 'std'],
        'win_rate': 'mean',
    }).round(2)
    console.print("\n[yellow]Mom State (Long) 影響:[/yellow]")
    console.print(ms_long_analysis)
    
    # Regime Filter 影響
    regime_analysis = results_df.groupby(results_df['params'].apply(lambda x: x['regime_filter'])).agg({
        'net_profit': ['mean', 'std', 'count'],
        'win_rate': 'mean',
    }).round(2)
    console.print("\n[yellow]Regime Filter 影響:[/yellow]")
    console.print(regime_analysis)
    
    # 建議最佳參數
    best = results_df.loc[results_df['net_profit'].idxmax()]
    console.print("\n[bold green]=== 建議最佳參數 ===[/bold green]")
    console.print(f"Entry Score: {best['params']['entry_score']}")
    console.print(f"Mom State (Long): >= {best['params']['mom_state_long']}")
    console.print(f"Mom State (Short): <= {best['params']['mom_state_short']}")
    console.print(f"Regime Filter: {best['params']['regime_filter']}")
    console.print(f"Use Pullback: {best['params']['use_pb']}")
    console.print(f"\n預期績效:")
    console.print(f"  淨利：{best['net_profit']:,.0f} TWD")
    console.print(f"  交易次數：{best['total_trades']}")
    console.print(f"  勝率：{best['win_rate']:.1f}%")
    console.print(f"  盈虧比：{best['profit_factor']:.2f}")
    console.print(f"  最大回撤：{best['max_drawdown']:,.0f} TWD")


if __name__ == "__main__":
    run_parameter_optimization()

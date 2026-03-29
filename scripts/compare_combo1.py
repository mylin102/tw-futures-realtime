#!/usr/bin/env python3
import os
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import pandas_ta as ta
import yaml
from rich.console import Console
from rich.table import Table

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "src"))

from historical_backtest import load_and_resample
from squeeze_futures.engine.constants import get_point_value
from squeeze_futures.engine.execution import build_execution_model, simulate_order_fill
from squeeze_futures.engine.indicators import calculate_futures_squeeze, calculate_mtf_alignment
from squeeze_futures.engine.simulator import PaperTrader


console = Console()


def load_config():
    config_path = Path(__file__).parent.parent / "config" / "trade_config.yaml"
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_processed_data(cfg):
    files = sorted(Path("data/taifex_raw").glob("Daily_*.rpt"))
    all_d, all_d15, all_d1h = [], [], []
    for f in files:
        d5 = load_and_resample(f, "5min", "TMF")
        d15 = load_and_resample(f, "15min", "TMF")
        d1h = load_and_resample(f, "1h", "TMF")
        if d5 is not None:
            all_d.append(d5)
            all_d15.append(d15)
            all_d1h.append(d1h)

    pb = cfg["strategy"]["pullback"]
    p_args = {
        "bb_length": cfg["strategy"]["length"],
        "ema_fast": pb["ema_fast"],
        "ema_slow": pb["ema_slow"],
        "lookback": pb["lookback"],
        "pb_buffer": pb["buffer"],
    }

    p5 = calculate_futures_squeeze(pd.concat(all_d).sort_index(), **p_args)
    p15 = calculate_futures_squeeze(pd.concat(all_d15).sort_index(), **p_args)
    p1h = calculate_futures_squeeze(pd.concat(all_d1h).sort_index(), **p_args)

    p5["rsi14"] = ta.rsi(p5["Close"], length=14)
    p15["ema60_rising"] = p15["ema_filter"] > p15["ema_filter"].shift(1)
    p15["ema60_falling"] = p15["ema_filter"] < p15["ema_filter"].shift(1)
    return files, p5, p15, p1h


def build_trader(cfg):
    exec_cfg = cfg.get("execution", {})
    return PaperTrader(
        ticker="TMF",
        initial_balance=100000,
        point_value=get_point_value("TMF"),
        fee_per_side=exec_cfg.get("broker_fee_per_side", 20),
        exchange_fee_per_side=exec_cfg.get("exchange_fee_per_side", 0),
        tax_rate=exec_cfg.get("tax_rate", 0.0),
    )


def run_engine(p5, p15, p1h, cfg, use_combo1=False):
    trader = build_trader(cfg)
    exec_cfg = cfg.get("execution", {})
    execution_model = build_execution_model(exec_cfg)
    strat, mgmt, risk = cfg["strategy"], cfg["trade_mgmt"], cfg["risk_mgmt"]
    tp = strat.get("partial_exit", {})
    has_tp1_hit = False
    equity_curve = []

    for i in range(len(p5)):
        curr_time = p5.index[i]
        row = p5.iloc[i]
        price, vwap = row["Close"], row["vwap"]

        if trader.position != 0:
            trader.update_trailing_stop(price)
            if tp.get("enabled") and abs(trader.position) == mgmt["lots_per_trade"] and not has_tp1_hit:
                pnl = (price - trader.entry_price) * (1 if trader.position > 0 else -1)
                if pnl >= tp.get("tp1_pts", 40):
                    trader.execute_signal("PARTIAL_EXIT", price, curr_time, lots=tp.get("tp1_lots", 1))
                    trader.current_stop_loss = trader.entry_price
                    has_tp1_hit = True

            if trader.check_stop_loss(price, curr_time):
                has_tp1_hit = False
            elif risk["exit_on_vwap"]:
                if (trader.position > 0 and price < vwap and not row["opening_bullish"]) or (
                    trader.position < 0 and price > vwap and not row["opening_bearish"]
                ):
                    trader.execute_signal("EXIT", price, curr_time)
                    has_tp1_hit = False

        m15 = p15[p15.index <= curr_time]
        m1h = p1h[p1h.index <= curr_time]
        if m15.empty:
            equity_curve.append(trader.balance)
            continue

        last_15m = m15.iloc[-1]
        score = calculate_mtf_alignment({"5m": p5.iloc[: i + 1], "15m": m15, "1h": p1h[p1h.index <= curr_time]}, weights=strat["weights"])[
            "score"
        ]

        if trader.position == 0:
            has_tp1_hit = False
            sqz_buy = (not row["sqz_on"]) and score >= strat["entry_score"] and price > vwap and row["mom_state"] == 3
            pb_buy = (
                p5["is_new_high"].iloc[max(0, i - 12) : i].any()
                and row["in_bull_pb_zone"]
                and price > row["Open"]
                and row["bullish_align"]
            )
            sqz_sell = (not row["sqz_on"]) and score <= -strat["entry_score"] and price < vwap and row["mom_state"] == 0
            pb_sell = (
                p5["is_new_low"].iloc[max(0, i - 12) : i].any()
                and row["in_bear_pb_zone"]
                and price < row["Open"]
                and row["bearish_align"]
            )

            combo1_buy = bool(use_combo1 and last_15m["ema60_rising"] and row["rsi14"] <= 30)
            combo1_sell = bool(use_combo1 and last_15m["ema60_falling"] and row["rsi14"] >= 70)

            if sqz_buy or pb_buy or combo1_buy:
                fill_price = simulate_order_fill("BUY", price, row, execution_model)
                if fill_price is not None:
                    trader.execute_signal(
                        "BUY",
                        fill_price,
                        curr_time,
                        lots=mgmt["lots_per_trade"],
                        max_lots=mgmt["lots_per_trade"],
                        stop_loss=risk["stop_loss_pts"],
                        break_even_trigger=risk["break_even_pts"],
                    )
            elif sqz_sell or pb_sell or combo1_sell:
                fill_price = simulate_order_fill("SELL", price, row, execution_model)
                if fill_price is not None:
                    trader.execute_signal(
                        "SELL",
                        fill_price,
                        curr_time,
                        lots=mgmt["lots_per_trade"],
                        max_lots=mgmt["lots_per_trade"],
                        stop_loss=risk["stop_loss_pts"],
                        break_even_trigger=risk["break_even_pts"],
                    )
        elif trader.position > 0 and (row["mom_state"] < 2 or score < 20):
            trader.execute_signal("EXIT", price, curr_time)
            has_tp1_hit = False
        elif trader.position < 0 and (row["mom_state"] > 1 or score > -20):
            trader.execute_signal("EXIT", price, curr_time)
            has_tp1_hit = False

        mark_to_market = (price - trader.entry_price) * trader.position * trader.point_value if trader.position != 0 else 0
        equity_curve.append(trader.balance + mark_to_market)

    return trader, pd.Series(equity_curve, index=p5.index[: len(equity_curve)])


def summarize_result(name, trader, equity_curve):
    trades = pd.DataFrame(trader.trades)
    max_equity = equity_curve.cummax()
    drawdown = equity_curve - max_equity
    gross_profit = float(trades.loc[trades["pnl_cash"] > 0, "pnl_cash"].sum()) if not trades.empty else 0.0
    gross_loss = float(-trades.loc[trades["pnl_cash"] < 0, "pnl_cash"].sum()) if not trades.empty else 0.0
    profit_factor = (gross_profit / gross_loss) if gross_loss else None
    return {
        "name": name,
        "net_profit": trader.balance - 100000,
        "ending_balance": trader.balance,
        "trades": len(trades),
        "win_rate": float((trades["pnl_cash"] > 0).mean() * 100) if not trades.empty else 0.0,
        "avg_trade": float(trades["pnl_cash"].mean()) if not trades.empty else 0.0,
        "max_drawdown": float(drawdown.min()) if len(drawdown) else 0.0,
        "profit_factor": profit_factor,
        "total_cost": float(trades["total_cost"].sum()) if not trades.empty else 0.0,
    }


def save_report(files, baseline, combo1):
    lines = [
        "# Combo1 Comparison Report",
        "",
        f"- Generated at: {datetime.now().isoformat(timespec='seconds')}",
        f"- Data files: {len(files)}",
        "- Combo1 assumption: 15m EMA60 slope defines trend; 5m RSI(14) <= 30 triggers long in uptrend; >= 70 triggers short in downtrend.",
        "",
        "## Summary",
        "",
        "| Strategy | Net Profit | Ending Balance | Trades | Win Rate | Avg Trade | Max Drawdown | Profit Factor | Total Cost |",
        "|:--|--:|--:|--:|--:|--:|--:|--:|--:|",
        f"| Baseline | {baseline['net_profit']:+,.0f} | {baseline['ending_balance']:,.0f} | {baseline['trades']} | {baseline['win_rate']:.1f}% | {baseline['avg_trade']:+,.1f} | {baseline['max_drawdown']:,.0f} | {baseline['profit_factor']:.2f} | {baseline['total_cost']:,.0f} |",
        f"| Baseline + Combo1 | {combo1['net_profit']:+,.0f} | {combo1['ending_balance']:,.0f} | {combo1['trades']} | {combo1['win_rate']:.1f}% | {combo1['avg_trade']:+,.1f} | {combo1['max_drawdown']:,.0f} | {combo1['profit_factor']:.2f} | {combo1['total_cost']:,.0f} |",
        "",
        "## Delta",
        "",
        f"- Net Profit Delta: {combo1['net_profit'] - baseline['net_profit']:+,.0f} TWD",
        f"- Trades Delta: {combo1['trades'] - baseline['trades']:+d}",
        f"- Win Rate Delta: {combo1['win_rate'] - baseline['win_rate']:+.1f} pct",
        f"- Max Drawdown Delta: {combo1['max_drawdown'] - baseline['max_drawdown']:+,.0f} TWD",
        f"- Total Cost Delta: {combo1['total_cost'] - baseline['total_cost']:+,.0f} TWD",
    ]
    out_path = Path("exports/simulations") / f"combo1_comparison_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
    out_path.write_text("\n".join(lines), encoding="utf-8")
    return out_path


def main():
    cfg = load_config()
    files, p5, p15, p1h = load_processed_data(cfg)

    baseline_trader, baseline_curve = run_engine(p5, p15, p1h, cfg, use_combo1=False)
    combo1_trader, combo1_curve = run_engine(p5, p15, p1h, cfg, use_combo1=True)

    baseline = summarize_result("Baseline", baseline_trader, baseline_curve)
    combo1 = summarize_result("Baseline + Combo1", combo1_trader, combo1_curve)

    table = Table(title="Combo1 Backtest Comparison")
    table.add_column("Strategy", style="cyan")
    table.add_column("Net Profit", justify="right")
    table.add_column("Trades", justify="right")
    table.add_column("Win Rate", justify="right")
    table.add_column("MDD", justify="right")
    table.add_column("Cost", justify="right")
    for row in [baseline, combo1]:
        table.add_row(
            row["name"],
            f"{row['net_profit']:+,.0f}",
            str(row["trades"]),
            f"{row['win_rate']:.1f}%",
            f"{row['max_drawdown']:,.0f}",
            f"{row['total_cost']:,.0f}",
        )
    console.print(table)
    report_path = save_report(files, baseline, combo1)
    console.print(f"[green]Report saved:[/green] {report_path}")


if __name__ == "__main__":
    main()

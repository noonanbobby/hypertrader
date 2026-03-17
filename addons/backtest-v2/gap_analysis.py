#!/usr/bin/env python3
"""
Final validation: 6 confidence gap tests before deployment.
"""

import json
import numpy as np
from pathlib import Path
from datetime import datetime, timezone
from copy import deepcopy

DATA_DIR = Path(__file__).parent.parent / "backtest-data"
OUTPUT_DIR = Path(__file__).parent

import sys
sys.path.insert(0, str(Path(__file__).parent))
from engine import calc_supertrend, calc_sma, calc_atr


def load_klines_binance(filename):
    with open(DATA_DIR / filename) as f:
        klines = json.load(f)
    return {
        "opens": np.array([k["open"] for k in klines], dtype=np.float64),
        "highs": np.array([k["high"] for k in klines], dtype=np.float64),
        "lows": np.array([k["low"] for k in klines], dtype=np.float64),
        "closes": np.array([k["close"] for k in klines], dtype=np.float64),
        "volumes": np.array([k["volume"] for k in klines], dtype=np.float64),
        "timestamps": np.array([k["open_time"] for k in klines], dtype=np.int64),
        "n": len(klines),
    }


def load_klines_hl(filename):
    with open(DATA_DIR / filename) as f:
        klines = json.load(f)
    return {
        "opens": np.array([k["o"] for k in klines], dtype=np.float64),
        "highs": np.array([k["h"] for k in klines], dtype=np.float64),
        "lows": np.array([k["l"] for k in klines], dtype=np.float64),
        "closes": np.array([k["c"] for k in klines], dtype=np.float64),
        "volumes": np.array([k["v"] for k in klines], dtype=np.float64),
        "timestamps": np.array([k["t"] for k in klines], dtype=np.int64),
        "n": len(klines),
    }


def run_mtf_fixed(data_15m, data_1h, entry_atr, entry_mult, entry_src,
                  confirm_atr, confirm_mult, confirm_src,
                  start_bar, end_bar, fixed_size=125.0, leverage=10.0,
                  taker_fee=0.00045, slippage=0.0001,
                  starting_capital=500.0):
    """MTF backtest with fixed position sizing. Returns (trades, equity_curve, final_equity)."""
    d = data_15m
    n = min(end_bar, d["n"])

    _, h_dirs = calc_supertrend(data_1h["highs"], data_1h["lows"], data_1h["closes"],
                                 confirm_atr, confirm_mult, confirm_src)
    h_ts = data_1h["timestamps"]
    htf_dir = np.ones(n)
    h_idx = 0
    for i in range(n):
        while h_idx < len(h_ts) - 1 and h_ts[h_idx + 1] <= d["timestamps"][i]:
            h_idx += 1
        if h_idx < len(h_dirs):
            htf_dir[i] = h_dirs[h_idx]

    o, h, l, c, v, ts = (d["opens"][:n], d["highs"][:n], d["lows"][:n],
                          d["closes"][:n], d["volumes"][:n], d["timestamps"][:n])
    st_line, st_dir = calc_supertrend(h, l, c, entry_atr, entry_mult, entry_src)

    equity = starting_capital
    position = 0
    entry_price = 0.0
    position_size = fixed_size * leverage
    entry_bar_idx = 0
    trades = []
    equity_curve = []
    pending = None

    for i in range(start_bar, n):
        if pending is not None and i > start_bar:
            action = pending
            pending = None

            exec_price = o[i]

            if action == "close" and position != 0:
                fill = exec_price - exec_price * slippage * position
                pnl_raw = (fill - entry_price) * position * (position_size / entry_price)
                fee = position_size * taker_fee
                net = pnl_raw - fee
                trades.append({
                    "pnl_before_fees": round(pnl_raw, 4),
                    "fee": round(fee, 4),
                    "pnl": round(net, 4),
                    "direction": position,
                    "entry_price": round(entry_price, 2),
                    "exit_price": round(fill, 2),
                    "entry_time": int(ts[entry_bar_idx]),
                    "exit_time": int(ts[i]),
                    "bars_held": i - entry_bar_idx,
                })
                equity += net
                position = 0

            elif action.startswith("open") or action.startswith("flip"):
                if position != 0:
                    fill_close = exec_price - exec_price * slippage * position
                    pnl_raw = (fill_close - entry_price) * position * (position_size / entry_price)
                    fee = position_size * taker_fee
                    net = pnl_raw - fee
                    trades.append({
                        "pnl_before_fees": round(pnl_raw, 4),
                        "fee": round(fee, 4),
                        "pnl": round(net, 4),
                        "direction": position,
                        "entry_price": round(entry_price, 2),
                        "exit_price": round(fill_close, 2),
                        "entry_time": int(ts[entry_bar_idx]),
                        "exit_time": int(ts[i]),
                        "bars_held": i - entry_bar_idx,
                    })
                    equity += net

                new_dir = 1 if "long" in action else -1
                fill_open = exec_price + exec_price * slippage * new_dir
                fee = position_size * taker_fee
                equity -= fee
                position = new_dir
                entry_price = fill_open
                entry_bar_idx = i

        if position != 0:
            unrealized = (c[i] - entry_price) * position * (position_size / entry_price)
            equity_curve.append(equity + unrealized)
        else:
            equity_curve.append(equity)

        if i >= n - 1:
            if position != 0:
                pending = "close"
            continue

        if np.isnan(st_dir[i]) or np.isnan(st_dir[i-1]):
            continue

        if st_dir[i] == st_dir[i-1]:
            continue

        new_dir = 1 if st_dir[i] == 1 else -1

        if htf_dir[i] != new_dir:
            if position != 0:
                pending = "close"
            continue

        if position == 0:
            pending = "open_long" if new_dir == 1 else "open_short"
        elif position != new_dir:
            pending = "flip_long" if new_dir == 1 else "flip_short"

    # Close remaining
    if pending == "close" and position != 0:
        fill = c[n-1] * (1 - slippage * position)
        pnl_raw = (fill - entry_price) * position * (position_size / entry_price)
        fee = position_size * taker_fee
        net = pnl_raw - fee
        trades.append({
            "pnl_before_fees": round(pnl_raw, 4),
            "fee": round(fee, 4),
            "pnl": round(net, 4),
            "direction": position,
            "entry_price": round(entry_price, 2),
            "exit_price": round(fill, 2),
            "entry_time": int(ts[entry_bar_idx]),
            "exit_time": int(ts[n-1]),
            "bars_held": n - 1 - entry_bar_idx,
        })
        equity += net

    return trades, equity_curve, equity


def main():
    print("=" * 100)
    print("FINAL VALIDATION — 6 CONFIDENCE GAP TESTS")
    print("=" * 100)

    # Load all data
    bn_15m = load_klines_binance("binance_btc_15m.json")
    bn_1h = load_klines_binance("binance_btc_1h.json")
    hl_15m = load_klines_hl("BTC_15m_candles.json")
    hl_1h = load_klines_hl("BTC_1h_candles.json")

    MTF_E = (8, 4.0, "hlc3")
    MTF_C = (10, 4.0, "close")

    # ═══════════════════════════════════════════════════════════
    # GAP 1: CROSS-EXCHANGE VALIDATION (Binance vs Hyperliquid)
    # ═══════════════════════════════════════════════════════════
    print(f"\n{'='*100}")
    print("GAP 1: CROSS-EXCHANGE VALIDATION — Binance vs Hyperliquid (same 52-day window)")
    print(f"{'='*100}")

    # Find the overlapping window: HL 15m starts at 2026-01-23, ends 2026-03-16
    hl_start_ts = hl_15m["timestamps"][0]
    hl_end_ts = hl_15m["timestamps"][-1]

    hl_start_dt = datetime.fromtimestamp(hl_start_ts/1000, tz=timezone.utc)
    hl_end_dt = datetime.fromtimestamp(hl_end_ts/1000, tz=timezone.utc)
    print(f"\n  HL 15m data: {hl_start_dt.strftime('%Y-%m-%d')} to {hl_end_dt.strftime('%Y-%m-%d')} ({hl_15m['n']} candles)")

    # Find corresponding Binance window
    bn_start_idx = np.searchsorted(bn_15m["timestamps"], hl_start_ts)
    bn_end_idx = np.searchsorted(bn_15m["timestamps"], hl_end_ts)
    print(f"  Binance window: bars {bn_start_idx} to {bn_end_idx} ({bn_end_idx - bn_start_idx} candles)")

    # Price comparison
    # Align by timestamp
    common_ts = np.intersect1d(hl_15m["timestamps"], bn_15m["timestamps"])
    print(f"  Common timestamps: {len(common_ts)}")

    if len(common_ts) > 100:
        hl_idx = np.searchsorted(hl_15m["timestamps"], common_ts)
        bn_idx = np.searchsorted(bn_15m["timestamps"], common_ts)

        # Valid indices
        valid = (hl_idx < hl_15m["n"]) & (bn_idx < bn_15m["n"])
        hl_idx = hl_idx[valid]
        bn_idx = bn_idx[valid]

        price_diff = np.abs(hl_15m["closes"][hl_idx] - bn_15m["closes"][bn_idx])
        pct_diff = price_diff / bn_15m["closes"][bn_idx] * 100

        print(f"\n  Price difference (close):")
        print(f"    Mean: ${np.mean(price_diff):.2f} ({np.mean(pct_diff):.4f}%)")
        print(f"    Max:  ${np.max(price_diff):.2f} ({np.max(pct_diff):.4f}%)")
        print(f"    Median: ${np.median(price_diff):.2f}")

    # Run backtest on Hyperliquid data
    # We need aligned 1H data too
    hl_1h_start_idx = np.searchsorted(hl_1h["timestamps"], hl_start_ts)
    # Use HL 1H from start (it goes back further)

    trades_hl, _, eq_hl = run_mtf_fixed(
        hl_15m, hl_1h, *MTF_E, *MTF_C,
        start_bar=200, end_bar=hl_15m["n"],
    )

    # Binance on same window
    # Create Binance sub-data matching HL window
    bn_sub_15m = {k: v[bn_start_idx:bn_end_idx+1] if isinstance(v, np.ndarray) else v
                  for k, v in bn_15m.items()}
    bn_sub_15m["n"] = bn_end_idx - bn_start_idx + 1

    trades_bn, _, eq_bn = run_mtf_fixed(
        bn_sub_15m, bn_1h, *MTF_E, *MTF_C,
        start_bar=200, end_bar=bn_sub_15m["n"],
    )

    pnl_hl = eq_hl - 500
    pnl_bn = eq_bn - 500

    print(f"\n  Results on same 52-day window:")
    print(f"  {'Exchange':>15s} | {'Trades':>6s} {'P&L':>10s} {'Win%':>6s} {'PF':>6s}")
    print(f"  {'─'*15} | {'─'*6} {'─'*10} {'─'*6} {'─'*6}")

    for label, trades_x, pnl_x in [("Hyperliquid", trades_hl, pnl_hl), ("Binance", trades_bn, pnl_bn)]:
        wins = sum(1 for t in trades_x if t["pnl"] > 0)
        wr = wins / len(trades_x) * 100 if trades_x else 0
        gp = sum(t["pnl"] for t in trades_x if t["pnl"] > 0)
        gl = abs(sum(t["pnl"] for t in trades_x if t["pnl"] <= 0))
        pf = gp / gl if gl > 0 else 9999
        print(f"  {label:>15s} | {len(trades_x):>6d} ${pnl_x:>9.2f} {wr:>5.1f}% {pf:>6.2f}")

    # Compare trade-by-trade if trade counts match
    if len(trades_hl) == len(trades_bn):
        print(f"\n  Trade-by-trade comparison (same # of trades):")
        diffs = []
        for i, (th, tb) in enumerate(zip(trades_hl, trades_bn)):
            diffs.append(abs(th["pnl"] - tb["pnl"]))
        print(f"    Mean P&L difference per trade: ${np.mean(diffs):.4f}")
        print(f"    Max P&L difference: ${np.max(diffs):.4f}")
    else:
        print(f"\n  Trade count mismatch: HL={len(trades_hl)}, BN={len(trades_bn)}")
        # Compare entry timestamps
        hl_entries = set(t["entry_time"] for t in trades_hl)
        bn_entries = set(t["entry_time"] for t in trades_bn)
        common_entries = hl_entries & bn_entries
        hl_only = hl_entries - bn_entries
        bn_only = bn_entries - hl_entries
        print(f"    Common entry times: {len(common_entries)}")
        print(f"    HL-only entries: {len(hl_only)}")
        print(f"    BN-only entries: {len(bn_only)}")

    diff = abs(pnl_hl - pnl_bn)
    print(f"\n  P&L difference: ${diff:.2f} ({'MATERIAL' if diff > 50 else 'ACCEPTABLE'})")

    # ═══════════════════════════════════════════════════════════
    # GAP 2: VERIFY THE BIG WINNERS
    # ═══════════════════════════════════════════════════════════
    print(f"\n{'='*100}")
    print("GAP 2: TOP 10 WINNING TRADES — Pure MTF, fixed $125, 730 days (Binance)")
    print(f"{'='*100}")

    trades_full, _, _ = run_mtf_fixed(
        bn_15m, bn_1h, *MTF_E, *MTF_C,
        start_bar=200, end_bar=bn_15m["n"],
    )

    sorted_by_pnl = sorted(trades_full, key=lambda t: t["pnl"], reverse=True)

    print(f"\n  {'#':>3s} {'Entry Date':>18s} {'Exit Date':>18s} {'Dir':>5s} {'Entry$':>10s} {'Exit$':>10s} {'P&L':>9s} {'Hours':>6s} {'Context'}")
    print(f"  {'─'*3} {'─'*18} {'─'*18} {'─'*5} {'─'*10} {'─'*10} {'─'*9} {'─'*6} {'─'*30}")

    for i, t in enumerate(sorted_by_pnl[:10]):
        entry_dt = datetime.fromtimestamp(t["entry_time"]/1000, tz=timezone.utc)
        exit_dt = datetime.fromtimestamp(t["exit_time"]/1000, tz=timezone.utc)
        hours = t["bars_held"] * 15 / 60
        direction = "LONG" if t["direction"] == 1 else "SHORT"
        pct_move = abs(t["exit_price"] - t["entry_price"]) / t["entry_price"] * 100

        # Context: look at price 24h before entry and 24h after exit
        entry_bar = t.get("entry_bar", 0)
        # Determine trend context
        if pct_move > 3:
            context = f"{pct_move:.1f}% move — strong trend"
        elif pct_move > 1.5:
            context = f"{pct_move:.1f}% move — moderate trend"
        else:
            context = f"{pct_move:.1f}% move — choppy"

        print(f"  {i+1:>3d} {entry_dt.strftime('%Y-%m-%d %H:%M'):>18s} {exit_dt.strftime('%Y-%m-%d %H:%M'):>18s} "
              f"{direction:>5s} ${t['entry_price']:>9.2f} ${t['exit_price']:>9.2f} "
              f"${t['pnl']:>8.2f} {hours:>5.1f}h {context}")

    print(f"\n  Verify these on TradingView: BTCUSDT 15m chart with ST(8, 4.0, hlc3)")

    # Also show top 5 losers
    print(f"\n  TOP 5 LOSING TRADES:")
    for i, t in enumerate(sorted_by_pnl[-5:]):
        entry_dt = datetime.fromtimestamp(t["entry_time"]/1000, tz=timezone.utc)
        exit_dt = datetime.fromtimestamp(t["exit_time"]/1000, tz=timezone.utc)
        hours = t["bars_held"] * 15 / 60
        direction = "LONG" if t["direction"] == 1 else "SHORT"
        print(f"  {i+1:>3d} {entry_dt.strftime('%Y-%m-%d %H:%M'):>18s} {exit_dt.strftime('%Y-%m-%d %H:%M'):>18s} "
              f"{direction:>5s} ${t['entry_price']:>9.2f} ${t['exit_price']:>9.2f} ${t['pnl']:>8.2f} {hours:>5.1f}h")

    # ═══════════════════════════════════════════════════════════
    # GAP 3: MAKER FILL FEASIBILITY
    # ═══════════════════════════════════════════════════════════
    print(f"\n{'='*100}")
    print("GAP 3: MAKER FILL FEASIBILITY ANALYSIS")
    print(f"{'='*100}")

    # BTC spread on Hyperliquid is typically $1 on ~$70-100K price = ~0.001%
    btc_price = 73500  # approximate current
    spread_usd = 1.0
    spread_pct = spread_usd / btc_price * 100

    print(f"\n  Hyperliquid BTC perpetual:")
    print(f"    Typical spread: ${spread_usd} ({spread_pct:.4f}%)")
    print(f"    Taker fee: 0.045% ($0.5625 per $1,250 notional)")
    print(f"    Maker fee: 0.020% ($0.2500 per $1,250 notional)")
    print(f"    Saving per trade: ${0.5625 - 0.2500:.4f}")

    # Analyze the 437 trades: how quickly does price move after signal?
    # If signal fires at bar close and we place limit at best bid/ask,
    # the question is: does the next bar's open match the limit price?
    print(f"\n  Signal-to-fill analysis (how much does price move between signal close and next open?):")
    moves = []
    for t in trades_full:
        # entry_price includes slippage, but we can approximate the close-to-open gap
        # from the data directly
        pass

    # Estimate from data: for each ST flip bar, measure |close[i] - open[i+1]|
    st_line, st_dir = calc_supertrend(bn_15m["highs"], bn_15m["lows"], bn_15m["closes"],
                                       MTF_E[0], MTF_E[1], MTF_E[2])
    flip_gaps = []
    for i in range(201, bn_15m["n"] - 1):
        if not np.isnan(st_dir[i]) and not np.isnan(st_dir[i-1]) and st_dir[i] != st_dir[i-1]:
            gap = abs(bn_15m["opens"][i+1] - bn_15m["closes"][i])
            gap_pct = gap / bn_15m["closes"][i] * 100
            flip_gaps.append(gap_pct)

    if flip_gaps:
        print(f"    Flips analyzed: {len(flip_gaps)}")
        print(f"    Close-to-next-open gap: mean {np.mean(flip_gaps):.4f}%, median {np.median(flip_gaps):.4f}%, max {np.max(flip_gaps):.4f}%")
        # With a 15-second timeout placing at best bid/ask, estimate fill rate
        # If the gap is < spread, a limit order at best bid/ask would fill
        fill_rate = sum(1 for g in flip_gaps if g < spread_pct) / len(flip_gaps) * 100
        print(f"    Estimated maker fill rate (gap < spread): {fill_rate:.1f}%")
        # More realistic: with 15 second window, price fluctuates ~0.01-0.02%
        # so even if gap is slightly larger, there's a chance it sweeps back
        fill_rate_realistic = sum(1 for g in flip_gaps if g < 0.02) / len(flip_gaps) * 100
        print(f"    Realistic fill rate (gap < 0.02%): {fill_rate_realistic:.1f}%")

    # Blended fee scenarios
    print(f"\n  Blended fee scenarios ({len(trades_full)} trades, $1,250 notional each):")
    total_notional = len(trades_full) * 1250

    scenarios = [
        ("100% taker", 0.0, 0.00045),
        ("50% maker / 50% taker", 0.5, None),
        ("70% maker / 30% taker", 0.7, None),
        ("100% maker", 1.0, 0.00020),
    ]

    base_pnl_before_fees = sum(t["pnl_before_fees"] for t in trades_full)

    for label, maker_pct, fixed_rate in scenarios:
        if fixed_rate is not None:
            total_fees = total_notional * fixed_rate
        else:
            maker_trades = int(len(trades_full) * maker_pct)
            taker_trades = len(trades_full) - maker_trades
            total_fees = maker_trades * 1250 * 0.00020 + taker_trades * 1250 * 0.00045
        net_pnl = base_pnl_before_fees - total_fees
        print(f"    {label:>25s}: Fees ${total_fees:>7.2f} -> Net P&L ${net_pnl:>7.2f} ({net_pnl/500*100:>+6.1f}%)")

    # ═══════════════════════════════════════════════════════════
    # GAP 4: (Paper trader will be written separately)
    # ═══════════════════════════════════════════════════════════
    print(f"\n{'='*100}")
    print("GAP 4: PAPER TRADER — See addons/paper-trader.py (built separately)")
    print(f"{'='*100}")

    # ═══════════════════════════════════════════════════════════
    # GAP 5: ACTUAL VS BACKTESTED (last 52 days)
    # ═══════════════════════════════════════════════════════════
    print(f"\n{'='*100}")
    print("GAP 5: BACKTEST PREDICTION FOR LAST 52 DAYS (Jan 23 - Mar 16)")
    print(f"{'='*100}")

    # Run backtest on the 52-day HL window using Binance data
    trades_52d, ec_52d, eq_52d = run_mtf_fixed(
        bn_sub_15m, bn_1h, *MTF_E, *MTF_C,
        start_bar=200, end_bar=bn_sub_15m["n"],
    )

    pnl_52d = eq_52d - 500
    wins_52d = sum(1 for t in trades_52d if t["pnl"] > 0)

    print(f"\n  Backtest prediction (52 days, Binance data):")
    print(f"    Trades: {len(trades_52d)}")
    print(f"    P&L: ${pnl_52d:.2f} ({pnl_52d/500*100:.1f}%)")
    print(f"    Win rate: {wins_52d/len(trades_52d)*100:.1f}%" if trades_52d else "    No trades")

    # Compare to what the live bot actually did
    # We only have ~2 days of real trades from the DB
    print(f"\n  Actual live bot trades (from webhook_logs, Mar 15-16):")
    print(f"    Only 2 days of real trading data available (trading was paused)")
    print(f"    Successful trade executions: ~5 (mix of market fills and limit attempts)")
    print(f"    Most webhooks show 'Trading paused' — bot was not actively trading for the full 52 days")
    print(f"\n  VERDICT: Cannot compare — insufficient live trade data. Paper trader (GAP 4) is critical.")

    # Show what the backtest predicts for the signals that DID fire
    print(f"\n  Backtest signals during Mar 15-16 window:")
    mar15_start = int(datetime(2026, 3, 15, 0, 0, tzinfo=timezone.utc).timestamp() * 1000)
    mar16_end = int(datetime(2026, 3, 16, 23, 59, tzinfo=timezone.utc).timestamp() * 1000)

    for t in trades_52d:
        if mar15_start <= t["entry_time"] <= mar16_end or mar15_start <= t["exit_time"] <= mar16_end:
            entry_dt = datetime.fromtimestamp(t["entry_time"]/1000, tz=timezone.utc)
            exit_dt = datetime.fromtimestamp(t["exit_time"]/1000, tz=timezone.utc)
            d_str = "LONG" if t["direction"] == 1 else "SHORT"
            print(f"    {entry_dt.strftime('%m-%d %H:%M')} -> {exit_dt.strftime('%m-%d %H:%M')} {d_str} "
                  f"${t['entry_price']:.0f}->${t['exit_price']:.0f} P&L=${t['pnl']:.2f}")

    # ═══════════════════════════════════════════════════════════
    # GAP 6: SENSITIVITY TO STARTING POINT
    # ═══════════════════════════════════════════════════════════
    print(f"\n{'='*100}")
    print("GAP 6: STARTING POINT SENSITIVITY — 12 different start dates (every 60 days)")
    print(f"{'='*100}")

    bars_per_60d = 60 * 24 * 4  # 60 days of 15m bars = 5760
    n_bn = bn_15m["n"]

    print(f"\n  {'#':>3s} {'Start Date':>12s} {'Days':>5s} {'Trades':>6s} {'P&L $':>9s} {'P&L %':>7s} {'Win%':>6s} {'PF':>6s} {'MaxDD%':>7s} {'Low $':>7s} {'Verdict'}")
    print(f"  {'─'*3} {'─'*12} {'─'*5} {'─'*6} {'─'*9} {'─'*7} {'─'*6} {'─'*6} {'─'*7} {'─'*7} {'─'*20}")

    start_results = []
    for start_idx in range(12):
        start_bar = 200 + start_idx * bars_per_60d
        if start_bar >= n_bn - 1000:  # need at least ~10 days of runway
            break

        remaining_bars = n_bn - start_bar
        remaining_days = remaining_bars / (24 * 4)

        trades_s, ec_s, eq_s = run_mtf_fixed(
            bn_15m, bn_1h, *MTF_E, *MTF_C,
            start_bar=start_bar, end_bar=n_bn,
        )

        pnl_s = eq_s - 500
        wins_s = sum(1 for t in trades_s if t["pnl"] > 0)
        wr_s = wins_s / len(trades_s) * 100 if trades_s else 0
        gp = sum(t["pnl"] for t in trades_s if t["pnl"] > 0)
        gl = abs(sum(t["pnl"] for t in trades_s if t["pnl"] <= 0))
        pf_s = gp / gl if gl > 0 else 9999

        # Max drawdown
        if ec_s:
            ec_arr = np.array(ec_s)
            peak = np.maximum.accumulate(ec_arr)
            dd = (peak - ec_arr) / peak * 100
            max_dd = float(np.max(dd))
            min_eq = float(np.min(ec_arr))
        else:
            max_dd = 0
            min_eq = 500

        start_dt = datetime.fromtimestamp(bn_15m["timestamps"][start_bar]/1000, tz=timezone.utc)

        if pnl_s > 50:
            verdict = "PROFITABLE"
        elif pnl_s > 0:
            verdict = "marginal"
        elif pnl_s > -50:
            verdict = "marginal loss"
        else:
            verdict = "LOSING"

        if min_eq < 300:
            verdict += " + deep DD"

        start_results.append({
            "start_date": start_dt.strftime('%Y-%m-%d'),
            "days": round(remaining_days, 0),
            "trades": len(trades_s),
            "pnl": round(pnl_s, 2),
            "pnl_pct": round(pnl_s/500*100, 1),
            "win_rate": round(wr_s, 1),
            "pf": round(pf_s, 2),
            "max_dd": round(max_dd, 1),
            "min_eq": round(min_eq, 2),
            "verdict": verdict,
        })

        print(f"  {start_idx+1:>3d} {start_dt.strftime('%Y-%m-%d'):>12s} {remaining_days:>5.0f} {len(trades_s):>6d} "
              f"${pnl_s:>8.2f} {pnl_s/500*100:>6.1f}% {wr_s:>5.1f}% {pf_s:>6.2f} {max_dd:>6.1f}% ${min_eq:>6.0f} {verdict}")

    profitable = sum(1 for r in start_results if r["pnl"] > 0)
    print(f"\n  Profitable starts: {profitable}/{len(start_results)}")
    print(f"  Avg P&L across all starts: ${np.mean([r['pnl'] for r in start_results]):.2f}")
    print(f"  Worst start: {min(start_results, key=lambda r: r['pnl'])['start_date']} "
          f"(${min(start_results, key=lambda r: r['pnl'])['pnl']:.0f})")
    print(f"  Best start: {max(start_results, key=lambda r: r['pnl'])['start_date']} "
          f"(${max(start_results, key=lambda r: r['pnl'])['pnl']:.0f})")

    deep_dd = sum(1 for r in start_results if r["min_eq"] < 300)
    print(f"  Starts with equity dropping below $300: {deep_dd}/{len(start_results)}")

    # ═══════════════════════════════════════════════════════════
    # SAVE ALL RESULTS
    # ═══════════════════════════════════════════════════════════
    output = {
        "gap1_cross_exchange": {
            "hl_pnl": round(pnl_hl, 2),
            "bn_pnl": round(pnl_bn, 2),
            "hl_trades": len(trades_hl),
            "bn_trades": len(trades_bn),
            "difference": round(diff, 2),
        },
        "gap2_top10_winners": [
            {
                "entry": datetime.fromtimestamp(t["entry_time"]/1000, tz=timezone.utc).isoformat(),
                "exit": datetime.fromtimestamp(t["exit_time"]/1000, tz=timezone.utc).isoformat(),
                "direction": "long" if t["direction"] == 1 else "short",
                "entry_price": t["entry_price"],
                "exit_price": t["exit_price"],
                "pnl": t["pnl"],
                "hours": round(t["bars_held"] * 15 / 60, 1),
            } for t in sorted_by_pnl[:10]
        ],
        "gap3_maker_feasibility": {
            "estimated_fill_rate": round(fill_rate_realistic, 1) if flip_gaps else 0,
            "blended_50_50_pnl": round(base_pnl_before_fees - (len(trades_full) * 1250 * 0.5 * 0.00020 + len(trades_full) * 1250 * 0.5 * 0.00045), 2),
        },
        "gap5_52day_prediction": {
            "trades": len(trades_52d),
            "pnl": round(pnl_52d, 2),
        },
        "gap6_starting_sensitivity": start_results,
    }

    out_path = OUTPUT_DIR / "gap_analysis.json"
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2)
    print(f"\n  All results saved to {out_path}")


if __name__ == "__main__":
    main()

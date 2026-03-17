#!/usr/bin/env python3
"""
Simple parameter heatmap: 7x7 grid on validation set only.
"""

import json
import numpy as np
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "backtest-data"

import sys
sys.path.insert(0, str(Path(__file__).parent))
from engine import calc_supertrend


def load_klines(filename):
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


def run_mtf_fixed(data_15m, data_1h, entry_atr, entry_mult, entry_src,
                  confirm_atr, confirm_mult, confirm_src,
                  start_bar, end_bar, fixed_size=125.0, leverage=10.0,
                  taker_fee=0.00045, slippage=0.0001, starting_capital=500.0):
    d = data_15m; n = min(end_bar, d["n"])
    _, h_dirs = calc_supertrend(data_1h["highs"], data_1h["lows"], data_1h["closes"],
                                 confirm_atr, confirm_mult, confirm_src)
    h_ts = data_1h["timestamps"]
    htf_dir = np.ones(n); h_idx = 0
    for i in range(n):
        while h_idx < len(h_ts) - 1 and h_ts[h_idx + 1] <= d["timestamps"][i]: h_idx += 1
        if h_idx < len(h_dirs): htf_dir[i] = h_dirs[h_idx]
    o, h, l, c, ts = d["opens"][:n], d["highs"][:n], d["lows"][:n], d["closes"][:n], d["timestamps"][:n]
    st_line, st_dir = calc_supertrend(h, l, c, entry_atr, entry_mult, entry_src)
    notional = fixed_size * leverage
    equity = starting_capital; position = 0; entry_price = 0.0; entry_bar_idx = 0
    trades = 0; pending = None
    for i in range(start_bar, n):
        if pending is not None and i > start_bar:
            action = pending; pending = None; ep = o[i]
            if action == "close" and position != 0:
                fill = ep - ep * slippage * position
                pnl = (fill - entry_price) * position * (notional / entry_price) - notional * taker_fee
                equity += pnl; position = 0; trades += 1
            elif action.startswith("open") or action.startswith("flip"):
                if position != 0:
                    fill_c = ep - ep * slippage * position
                    pnl = (fill_c - entry_price) * position * (notional / entry_price) - notional * taker_fee
                    equity += pnl; trades += 1
                nd = 1 if "long" in action else -1
                equity -= notional * taker_fee
                position = nd; entry_price = ep + ep * slippage * nd; entry_bar_idx = i
        if i >= n - 1:
            if position != 0: pending = "close"
            continue
        if np.isnan(st_dir[i]) or np.isnan(st_dir[i-1]): continue
        if st_dir[i] == st_dir[i-1]: continue
        nd = 1 if st_dir[i] == 1 else -1
        if htf_dir[i] != nd:
            if position != 0: pending = "close"
            continue
        if position == 0: pending = "open_long" if nd == 1 else "open_short"
        elif position != nd: pending = "flip_long" if nd == 1 else "flip_short"
    if pending == "close" and position != 0:
        fill = c[n-1] * (1 - slippage * position)
        pnl = (fill - entry_price) * position * (notional / entry_price) - notional * taker_fee
        equity += pnl; trades += 1
    return equity - starting_capital, trades


def main():
    btc_15m = load_klines("binance_btc_15m.json")
    btc_1h = load_klines("binance_btc_1h.json")
    n = btc_15m["n"]
    val_start = int(n * 0.7)  # last 30%

    from datetime import datetime, timezone
    val_start_dt = datetime.fromtimestamp(btc_15m["timestamps"][val_start]/1000, tz=timezone.utc)
    val_end_dt = datetime.fromtimestamp(btc_15m["timestamps"][-1]/1000, tz=timezone.utc)

    mults = [2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0]
    atrs = [7, 8, 9, 10, 11, 12, 14]

    print(f"BTC Pure MTF (1H confirm ST(10,4.0,close)), fixed $125, taker fees")
    print(f"VALIDATION SET ONLY: {val_start_dt.strftime('%Y-%m-%d')} to {val_end_dt.strftime('%Y-%m-%d')} ({n - val_start} bars)")
    print(f"Entry source: hlc3 for all\n")

    # Build grid
    grid_pnl = {}
    grid_trades = {}
    for atr_p in atrs:
        for mult in mults:
            pnl, tr = run_mtf_fixed(
                btc_15m, btc_1h, atr_p, mult, "hlc3", 10, 4.0, "close",
                start_bar=val_start, end_bar=n)
            grid_pnl[(atr_p, mult)] = pnl
            grid_trades[(atr_p, mult)] = tr

    # Print P&L heatmap
    print("P&L ($) — VALIDATION SET")
    print(f"{'ATR':>5s}", end="")
    for m in mults:
        print(f" {'m=' + str(m):>8s}", end="")
    print()
    print(f"{'─'*5}", end="")
    for _ in mults:
        print(f" {'─'*8}", end="")
    print()

    for atr_p in atrs:
        print(f"{atr_p:>5d}", end="")
        for mult in mults:
            pnl = grid_pnl[(atr_p, mult)]
            if pnl > 50:
                marker = "+"
            elif pnl > 0:
                marker = " "
            elif pnl > -50:
                marker = " "
            else:
                marker = "-"
            print(f" {marker}${pnl:>6.0f}", end="")
        print()

    # Print trade count
    print(f"\nTrade count")
    print(f"{'ATR':>5s}", end="")
    for m in mults:
        print(f" {'m=' + str(m):>8s}", end="")
    print()
    print(f"{'─'*5}", end="")
    for _ in mults:
        print(f" {'─'*8}", end="")
    print()
    for atr_p in atrs:
        print(f"{atr_p:>5d}", end="")
        for mult in mults:
            print(f" {grid_trades[(atr_p, mult)]:>8d}", end="")
        print()

    # Summary
    profitable = sum(1 for v in grid_pnl.values() if v > 0)
    total = len(grid_pnl)
    print(f"\nProfitable cells: {profitable}/{total} ({profitable/total*100:.0f}%)")

    # Find the profitable zone
    print(f"\nProfitable zone (P&L > $0):")
    for atr_p in atrs:
        row = []
        for mult in mults:
            if grid_pnl[(atr_p, mult)] > 0:
                row.append(f"{mult}")
        if row:
            print(f"  ATR {atr_p}: mult {', '.join(row)}")

    # Center of profitable zone
    pos_mults = []; pos_atrs = []
    for (a, m), pnl in grid_pnl.items():
        if pnl > 0:
            pos_mults.append(m); pos_atrs.append(a)
    if pos_mults:
        print(f"\nCenter of profitable zone: ATR ~{np.median(pos_atrs):.0f}, Mult ~{np.median(pos_mults):.1f}")
        print(f"Profitable multiplier range: {min(pos_mults):.1f} to {max(pos_mults):.1f}")
        print(f"Profitable ATR range: {min(pos_atrs)} to {max(pos_atrs)}")

    # Best, worst, median
    sorted_pnl = sorted(grid_pnl.items(), key=lambda x: x[1], reverse=True)
    best = sorted_pnl[0]
    worst = sorted_pnl[-1]
    median_val = sorted_pnl[len(sorted_pnl)//2]
    print(f"\nBest:   ATR={best[0][0]}, Mult={best[0][1]} -> ${best[1]:.0f}")
    print(f"Worst:  ATR={worst[0][0]}, Mult={worst[0][1]} -> ${worst[1]:.0f}")
    print(f"Median: ATR={median_val[0][0]}, Mult={median_val[0][1]} -> ${median_val[1]:.0f}")

    # Visual heatmap with symbols
    print(f"\nVISUAL HEATMAP (validation P&L)")
    print(f"  ██ = >$100  |  ▓▓ = $50-100  |  ░░ = $0-50  |  .. = $-50-0  |  XX = <-$50")
    print(f"\n{'ATR':>5s}", end="")
    for m in mults:
        print(f" {'m='+str(m):>6s}", end="")
    print()
    for atr_p in atrs:
        print(f"{atr_p:>5d}", end="")
        for mult in mults:
            pnl = grid_pnl[(atr_p, mult)]
            if pnl > 100: sym = "  ██"
            elif pnl > 50: sym = "  ▓▓"
            elif pnl > 0: sym = "  ░░"
            elif pnl > -50: sym = "  .."
            else: sym = "  XX"
            print(f" {sym:>6s}", end="")
        print()


if __name__ == "__main__":
    main()

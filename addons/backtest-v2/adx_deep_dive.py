#!/usr/bin/env python3
"""
Deep ADX investigation: cross-asset, entry/exit ADX, ADX direction filter, skip-ranging-only.
"""

import numpy as np
from pathlib import Path
import json
from collections import defaultdict

DATA_DIR = Path(__file__).parent.parent / "backtest-data"

import sys
sys.path.insert(0, str(Path(__file__).parent))
from engine import calc_supertrend, calc_tr


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


def calc_adx(highs, lows, closes, period=14):
    n = len(closes)
    adx = np.full(n, np.nan)
    if n < period * 2 + 1: return adx
    plus_dm = np.zeros(n); minus_dm = np.zeros(n)
    for i in range(1, n):
        up = highs[i] - highs[i-1]; down = lows[i-1] - lows[i]
        if up > down and up > 0: plus_dm[i] = up
        if down > up and down > 0: minus_dm[i] = down
    tr = calc_tr(highs, lows, closes)
    def rma(data, p):
        out = np.full(len(data), np.nan)
        out[p] = np.sum(data[1:p+1])
        for i in range(p+1, len(data)):
            out[i] = out[i-1] - out[i-1]/p + data[i]
        return out
    s_tr = rma(tr, period); s_pdm = rma(plus_dm, period); s_mdm = rma(minus_dm, period)
    dx = np.full(n, np.nan)
    for i in range(period, n):
        if s_tr[i] and not np.isnan(s_tr[i]) and s_tr[i] > 0:
            pdi = 100 * s_pdm[i] / s_tr[i]; mdi = 100 * s_mdm[i] / s_tr[i]
            s = pdi + mdi
            if s > 0: dx[i] = 100 * abs(pdi - mdi) / s
    fv = period
    while fv < n and np.isnan(dx[fv]): fv += 1
    if fv + period >= n: return adx
    adx[fv + period - 1] = np.nanmean(dx[fv:fv+period])
    for i in range(fv + period, n):
        if not np.isnan(dx[i]) and not np.isnan(adx[i-1]):
            adx[i] = (adx[i-1] * (period - 1) + dx[i]) / period
    return adx


def run_mtf_tagged(data_15m, data_1h, entry_atr, entry_mult, entry_src,
                   confirm_atr, confirm_mult, confirm_src,
                   start_bar, end_bar, adx_values,
                   fixed_size=125.0, leverage=10.0,
                   taker_fee=0.00045, slippage=0.0001, starting_capital=500.0,
                   adx_filter_min=None, adx_filter_max=None,
                   adx_direction_filter=None):
    """
    MTF backtest returning trades tagged with ADX at entry AND exit.
    adx_direction_filter: "rising" = only trade when ADX rising, "falling" = only when falling, None = no filter
    """
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
    trades = []; equity_curve = []; pending = None

    for i in range(start_bar, n):
        if pending is not None and i > start_bar:
            action = pending; pending = None; ep = o[i]
            if action == "close" and position != 0:
                fill = ep - ep * slippage * position
                pnl = (fill - entry_price) * position * (notional / entry_price) - notional * taker_fee
                adx_entry = float(adx_values[entry_bar_idx]) if not np.isnan(adx_values[entry_bar_idx]) else -1
                adx_exit = float(adx_values[i]) if not np.isnan(adx_values[i]) else -1
                trades.append({"pnl": pnl, "direction": position,
                               "entry_price": entry_price, "exit_price": fill,
                               "entry_time": int(ts[entry_bar_idx]), "exit_time": int(ts[i]),
                               "bars_held": i - entry_bar_idx,
                               "adx_entry": adx_entry, "adx_exit": adx_exit})
                equity += pnl; position = 0
            elif action.startswith("open") or action.startswith("flip"):
                if position != 0:
                    fill_c = ep - ep * slippage * position
                    pnl = (fill_c - entry_price) * position * (notional / entry_price) - notional * taker_fee
                    adx_entry = float(adx_values[entry_bar_idx]) if not np.isnan(adx_values[entry_bar_idx]) else -1
                    adx_exit = float(adx_values[i]) if not np.isnan(adx_values[i]) else -1
                    trades.append({"pnl": pnl, "direction": position,
                                   "entry_price": entry_price, "exit_price": fill_c,
                                   "entry_time": int(ts[entry_bar_idx]), "exit_time": int(ts[i]),
                                   "bars_held": i - entry_bar_idx,
                                   "adx_entry": adx_entry, "adx_exit": adx_exit})
                    equity += pnl
                nd = 1 if "long" in action else -1
                equity -= notional * taker_fee
                position = nd; entry_price = ep + ep * slippage * nd; entry_bar_idx = i
        if position != 0:
            equity_curve.append(equity + (c[i] - entry_price) * position * (notional / entry_price))
        else:
            equity_curve.append(equity)
        if i >= n - 1:
            if position != 0: pending = "close"
            continue
        if np.isnan(st_dir[i]) or np.isnan(st_dir[i-1]): continue
        if st_dir[i] == st_dir[i-1]: continue
        nd = 1 if st_dir[i] == 1 else -1
        if htf_dir[i] != nd:
            if position != 0: pending = "close"
            continue

        # ADX hard cutoff filter
        if adx_filter_min is not None or adx_filter_max is not None:
            av = adx_values[i]
            if np.isnan(av):
                if position != 0: pending = "close"
                continue
            if adx_filter_min is not None and av < adx_filter_min:
                if position != 0: pending = "close"
                continue
            if adx_filter_max is not None and av > adx_filter_max:
                if position != 0: pending = "close"
                continue

        # ADX direction filter
        if adx_direction_filter is not None:
            av = adx_values[i]
            # Use 4-bar lookback to determine ADX direction
            lookback = 4
            if i >= lookback and not np.isnan(av) and not np.isnan(adx_values[i - lookback]):
                adx_rising = av > adx_values[i - lookback]
                if adx_direction_filter == "rising" and not adx_rising:
                    if position != 0: pending = "close"
                    continue
                if adx_direction_filter == "falling" and adx_rising:
                    if position != 0: pending = "close"
                    continue

        if position == 0: pending = "open_long" if nd == 1 else "open_short"
        elif position != nd: pending = "flip_long" if nd == 1 else "flip_short"

    if pending == "close" and position != 0:
        fill = c[n-1] * (1 - slippage * position)
        pnl = (fill - entry_price) * position * (notional / entry_price) - notional * taker_fee
        adx_entry = float(adx_values[entry_bar_idx]) if not np.isnan(adx_values[entry_bar_idx]) else -1
        adx_exit = float(adx_values[n-1]) if not np.isnan(adx_values[n-1]) else -1
        trades.append({"pnl": pnl, "direction": position,
                       "entry_price": entry_price, "exit_price": fill,
                       "entry_time": int(ts[entry_bar_idx]), "exit_time": int(ts[n-1]),
                       "bars_held": n - 1 - entry_bar_idx,
                       "adx_entry": adx_entry, "adx_exit": adx_exit})
        equity += pnl
    return trades, equity_curve, equity


def bucket_stats(trades, label):
    if not trades:
        return {"n": 0, "pnl": 0, "pf": 0, "wr": 0}
    pnl = sum(t["pnl"] for t in trades)
    wins = [t for t in trades if t["pnl"] > 0]
    gp = sum(t["pnl"] for t in wins)
    gl = abs(sum(t["pnl"] for t in trades if t["pnl"] <= 0))
    pf = gp / gl if gl > 0 else 9999
    return {"n": len(trades), "pnl": round(pnl, 2), "pf": round(pf, 2),
            "wr": round(len(wins)/len(trades)*100, 1)}


def main():
    print("=" * 100)
    print("ADX DEEP DIVE")
    print("=" * 100)
    warmup = 200

    assets = {}
    for name, f15, f1h in [("BTC", "binance_btc_15m.json", "binance_btc_1h.json"),
                            ("ETH", "binance_eth_15m.json", "binance_eth_1h.json"),
                            ("SOL", "binance_sol_15m.json", "binance_sol_1h.json")]:
        d15 = load_klines(f15); d1h = load_klines(f1h)
        adx = calc_adx(d15["highs"], d15["lows"], d15["closes"])
        assets[name] = (d15, d1h, adx)

    # ═══════════════════════════════════════════════════════════
    # 1. CROSS-ASSET: ADX > 35 P&L for each asset
    # ═══════════════════════════════════════════════════════════
    print(f"\n{'='*100}")
    print("1. ADX > 35 P&L — CROSS-ASSET COMPARISON")
    print(f"{'='*100}")

    print(f"\n  {'Asset':>5s} | {'ADX<20':>30s} | {'ADX 20-35':>30s} | {'ADX>35':>30s}")
    print(f"  {'─'*5} | {'─'*30} | {'─'*30} | {'─'*30}")

    for name, (d15, d1h, adx) in assets.items():
        trades, _, _ = run_mtf_tagged(d15, d1h, 8, 4.0, "hlc3", 10, 4.0, "close",
                                       start_bar=warmup, end_bar=d15["n"], adx_values=adx)

        low = [t for t in trades if 0 <= t["adx_entry"] < 20]
        mid = [t for t in trades if 20 <= t["adx_entry"] < 35]
        high = [t for t in trades if t["adx_entry"] >= 35]

        sl = bucket_stats(low, ""); sm = bucket_stats(mid, ""); sh = bucket_stats(high, "")
        print(f"  {name:>5s} | {sl['n']:>3d}tr ${sl['pnl']:>7.0f} PF={sl['pf']:>5.2f} W={sl['wr']:>4.1f}% "
              f"| {sm['n']:>3d}tr ${sm['pnl']:>7.0f} PF={sm['pf']:>5.2f} W={sm['wr']:>4.1f}% "
              f"| {sh['n']:>3d}tr ${sh['pnl']:>7.0f} PF={sh['pf']:>5.2f} W={sh['wr']:>4.1f}%")

    # Finer breakdown of ADX > 30 zone
    print(f"\n  Finer breakdown (ADX 30+ zone):")
    print(f"  {'Asset':>5s} | {'30-35':>25s} | {'35-40':>25s} | {'40-50':>25s} | {'50+':>25s}")
    print(f"  {'─'*5} | {'─'*25} | {'─'*25} | {'─'*25} | {'─'*25}")

    for name, (d15, d1h, adx) in assets.items():
        trades, _, _ = run_mtf_tagged(d15, d1h, 8, 4.0, "hlc3", 10, 4.0, "close",
                                       start_bar=warmup, end_bar=d15["n"], adx_values=adx)
        bins = [(30, 35), (35, 40), (40, 50), (50, 100)]
        parts = []
        for lo, hi in bins:
            bt = [t for t in trades if lo <= t["adx_entry"] < hi]
            s = bucket_stats(bt, "")
            parts.append(f"{s['n']:>3d}tr ${s['pnl']:>6.0f} PF={s['pf']:>4.2f}")
        print(f"  {name:>5s} | {parts[0]} | {parts[1]} | {parts[2]} | {parts[3]}")

    # ═══════════════════════════════════════════════════════════
    # 2. ADX AT ENTRY VS EXIT
    # ═══════════════════════════════════════════════════════════
    print(f"\n{'='*100}")
    print("2. ADX AT ENTRY VS EXIT — BTC trades with ADX > 35 at entry")
    print(f"{'='*100}")

    btc_d15, btc_d1h, btc_adx = assets["BTC"]
    btc_trades, _, _ = run_mtf_tagged(btc_d15, btc_d1h, 8, 4.0, "hlc3", 10, 4.0, "close",
                                       start_bar=warmup, end_bar=btc_d15["n"], adx_values=btc_adx)

    high_adx = [t for t in btc_trades if t["adx_entry"] >= 35]
    mid_adx = [t for t in btc_trades if 20 <= t["adx_entry"] < 35]
    low_adx = [t for t in btc_trades if 0 <= t["adx_entry"] < 20]

    print(f"\n  ADX ENTRY vs EXIT (mean values):")
    for label, bucket in [("ADX < 20 at entry", low_adx),
                           ("ADX 20-35 at entry", mid_adx),
                           ("ADX > 35 at entry", high_adx)]:
        if not bucket: continue
        entry_adx = [t["adx_entry"] for t in bucket if t["adx_entry"] > 0]
        exit_adx = [t["adx_exit"] for t in bucket if t["adx_exit"] > 0]
        winners = [t for t in bucket if t["pnl"] > 0]
        losers = [t for t in bucket if t["pnl"] <= 0]

        win_entry = [t["adx_entry"] for t in winners if t["adx_entry"] > 0]
        win_exit = [t["adx_exit"] for t in winners if t["adx_exit"] > 0]
        loss_entry = [t["adx_entry"] for t in losers if t["adx_entry"] > 0]
        loss_exit = [t["adx_exit"] for t in losers if t["adx_exit"] > 0]

        print(f"\n  {label} ({len(bucket)} trades):")
        print(f"    All:     entry ADX {np.mean(entry_adx):.1f} -> exit ADX {np.mean(exit_adx):.1f} "
              f"(change {np.mean(exit_adx) - np.mean(entry_adx):+.1f})")
        if win_entry:
            print(f"    Winners: entry ADX {np.mean(win_entry):.1f} -> exit ADX {np.mean(win_exit):.1f} "
                  f"(change {np.mean(win_exit) - np.mean(win_entry):+.1f})")
        if loss_entry:
            print(f"    Losers:  entry ADX {np.mean(loss_entry):.1f} -> exit ADX {np.mean(loss_exit):.1f} "
                  f"(change {np.mean(loss_exit) - np.mean(loss_entry):+.1f})")

    # ADX rising vs falling at entry for high-ADX trades
    print(f"\n  ADX DIRECTION at entry (high-ADX BTC trades):")
    rising = [t for t in high_adx if t["adx_exit"] > t["adx_entry"]]
    falling = [t for t in high_adx if t["adx_exit"] <= t["adx_entry"]]
    sr = bucket_stats(rising, ""); sf = bucket_stats(falling, "")
    print(f"    ADX rose during trade:  {sr['n']} trades, P&L ${sr['pnl']:.0f}, PF={sr['pf']:.2f}")
    print(f"    ADX fell during trade:  {sf['n']} trades, P&L ${sf['pnl']:.0f}, PF={sf['pf']:.2f}")

    # ═══════════════════════════════════════════════════════════
    # 3. ADX DIRECTION FILTER
    # ═══════════════════════════════════════════════════════════
    print(f"\n{'='*100}")
    print("3. ADX DIRECTION FILTER — Rising vs Falling vs No filter (BTC, 730 days)")
    print(f"{'='*100}")

    configs = [
        ("No filter", None, None, None),
        ("ADX rising only", None, None, "rising"),
        ("ADX falling only", None, None, "falling"),
        ("ADX >= 20 (skip ranging)", 20, None, None),
        ("ADX 20-35", 20, 35, None),
        ("ADX >= 20 + rising", 20, None, "rising"),
        ("ADX >= 20 + falling", 20, None, "falling"),
    ]

    print(f"\n  {'Config':>30s} | {'Trades':>6s} {'P&L $':>8s} {'PF':>6s} {'Win%':>6s} {'MDD%':>6s}")
    print(f"  {'─'*30} | {'─'*6} {'─'*8} {'─'*6} {'─'*6} {'─'*6}")

    for label, adx_min, adx_max, adx_dir in configs:
        trades, ec, eq = run_mtf_tagged(
            btc_d15, btc_d1h, 8, 4.0, "hlc3", 10, 4.0, "close",
            start_bar=warmup, end_bar=btc_d15["n"], adx_values=btc_adx,
            adx_filter_min=adx_min, adx_filter_max=adx_max,
            adx_direction_filter=adx_dir)
        pnl = eq - 500
        s = bucket_stats(trades, "")
        mdd = 0
        if ec:
            ea = np.array(ec); peak = np.maximum.accumulate(ea)
            mdd = float(np.max((peak - ea) / peak * 100))
        print(f"  {label:>30s} | {s['n']:>6d} ${pnl:>7.0f} {s['pf']:>6.2f} {s['wr']:>5.1f}% {mdd:>5.1f}%")

    # ═══════════════════════════════════════════════════════════
    # 4. SKIP RANGING ONLY — the simple question
    # ═══════════════════════════════════════════════════════════
    print(f"\n{'='*100}")
    print("4. THE SIMPLE COMPARISON — BTC, fixed $125, taker fees, full 730 days")
    print(f"{'='*100}")

    variants = [
        ("Unfiltered", None, None),
        ("ADX >= 20 (skip ranging)", 20, None),
        ("ADX 20-35 (skip ranging + extreme)", 20, 35),
        ("ADX >= 15 (lighter ranging skip)", 15, None),
        ("ADX >= 25 (strict ranging skip)", 25, None),
    ]

    print(f"\n  {'Config':>40s} | {'Trades':>6s} {'P&L $':>8s} {'PF':>6s} {'Win%':>6s} {'MDD%':>6s} {'$/trade':>8s}")
    print(f"  {'─'*40} | {'─'*6} {'─'*8} {'─'*6} {'─'*6} {'─'*6} {'─'*8}")

    for label, adx_min, adx_max in variants:
        trades, ec, eq = run_mtf_tagged(
            btc_d15, btc_d1h, 8, 4.0, "hlc3", 10, 4.0, "close",
            start_bar=warmup, end_bar=btc_d15["n"], adx_values=btc_adx,
            adx_filter_min=adx_min, adx_filter_max=adx_max)
        pnl = eq - 500; s = bucket_stats(trades, "")
        mdd = 0
        if ec:
            ea = np.array(ec); peak = np.maximum.accumulate(ea)
            mdd = float(np.max((peak - ea) / peak * 100))
        avg_pnl = pnl / s["n"] if s["n"] > 0 else 0
        print(f"  {label:>40s} | {s['n']:>6d} ${pnl:>7.0f} {s['pf']:>6.2f} {s['wr']:>5.1f}% {mdd:>5.1f}% ${avg_pnl:>7.2f}")

    # Same for ETH and SOL
    for name in ["ETH", "SOL"]:
        d15, d1h, adx = assets[name]
        print(f"\n  {name}:")
        for label, adx_min, adx_max in variants:
            trades, ec, eq = run_mtf_tagged(
                d15, d1h, 8, 4.0, "hlc3", 10, 4.0, "close",
                start_bar=warmup, end_bar=d15["n"], adx_values=adx,
                adx_filter_min=adx_min, adx_filter_max=adx_max)
            pnl = eq - 500; s = bucket_stats(trades, "")
            mdd = 0
            if ec:
                ea = np.array(ec); peak = np.maximum.accumulate(ea)
                mdd = float(np.max((peak - ea) / peak * 100))
            avg_pnl = pnl / s["n"] if s["n"] > 0 else 0
            print(f"  {label:>40s} | {s['n']:>6d} ${pnl:>7.0f} {s['pf']:>6.2f} {s['wr']:>5.1f}% {mdd:>5.1f}% ${avg_pnl:>7.2f}")

    # ═══════════════════════════════════════════════════════════
    # VERDICT
    # ═══════════════════════════════════════════════════════════
    print(f"\n{'='*100}")
    print("VERDICT")
    print(f"{'='*100}")


if __name__ == "__main__":
    main()

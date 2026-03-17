#!/usr/bin/env python3
"""
Compare Binance spot vs Bybit perpetual candle data and Supertrend signals.
"""

import json
import time
import numpy as np
import requests
from pathlib import Path
from datetime import datetime, timezone

DATA_DIR = Path(__file__).parent.parent / "backtest-data"

import sys
sys.path.insert(0, str(Path(__file__).parent))
from engine import calc_supertrend, calc_tr


def fetch_bybit_klines(symbol, interval, limit=1000):
    """Fetch klines from Bybit v5 API. interval: '15' for 15m, '60' for 1h."""
    url = "https://api.bybit.com/v5/market/kline"
    all_klines = []
    end_time = int(time.time() * 1000)

    interval_ms = {"1": 60000, "5": 300000, "15": 900000, "60": 3600000, "240": 14400000}[str(interval)]

    # Bybit returns newest first, paginate backwards
    while len(all_klines) < limit:
        batch = min(1000, limit - len(all_klines))
        params = {"category": "linear", "symbol": symbol, "interval": str(interval), "limit": batch, "end": end_time}
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        if data["retCode"] != 0:
            print(f"  Bybit API error: {data['retMsg']}")
            break

        rows = data["result"]["list"]
        if not rows:
            break

        for r in rows:
            all_klines.append({
                "open_time": int(r[0]),
                "open": float(r[1]),
                "high": float(r[2]),
                "low": float(r[3]),
                "close": float(r[4]),
                "volume": float(r[5]),
            })

        # Bybit returns newest first, so move end_time before the oldest in this batch
        oldest_ts = int(rows[-1][0])
        end_time = oldest_ts - 1
        time.sleep(0.1)

    # Sort chronologically (Bybit returns newest first)
    all_klines.sort(key=lambda k: k["open_time"])
    return all_klines


def load_binance_klines(filename):
    with open(DATA_DIR / filename) as f:
        klines = json.load(f)
    return klines


def main():
    print("=" * 100)
    print("EXCHANGE COMPARISON — Binance Spot vs Bybit Perpetual")
    print("=" * 100)

    # ═══════════════════════════════════════════════════════════
    # 1. FETCH BYBIT DATA
    # ═══════════════════════════════════════════════════════════
    print("\n  Fetching Bybit BTCUSDT perpetual 15m candles (last 1000)...")
    bybit_15m = fetch_bybit_klines("BTCUSDT", 15, limit=1000)
    print(f"  Got {len(bybit_15m)} candles")

    if not bybit_15m:
        print("  FAILED to fetch Bybit data. Aborting.")
        return

    by_start = datetime.fromtimestamp(bybit_15m[0]["open_time"] / 1000, tz=timezone.utc)
    by_end = datetime.fromtimestamp(bybit_15m[-1]["open_time"] / 1000, tz=timezone.utc)
    print(f"  Bybit range: {by_start.strftime('%Y-%m-%d %H:%M')} to {by_end.strftime('%Y-%m-%d %H:%M')}")

    # Also fetch 1H for MTF
    print("  Fetching Bybit BTCUSDT perpetual 1H candles (last 1000)...")
    bybit_1h = fetch_bybit_klines("BTCUSDT", 60, limit=1000)
    print(f"  Got {len(bybit_1h)} candles")

    # ═══════════════════════════════════════════════════════════
    # 2. ALIGN BINANCE DATA TO SAME WINDOW
    # ═══════════════════════════════════════════════════════════
    print("\n  Loading Binance spot data and aligning to same window...")
    bn_all = load_binance_klines("binance_btc_15m.json")
    bn_1h_all = load_binance_klines("binance_btc_1h.json")

    # Build timestamp -> candle lookup for Binance
    bn_by_ts = {k["open_time"]: k for k in bn_all}
    bn_1h_by_ts = {k["open_time"]: k for k in bn_1h_all}

    # Find common timestamps
    by_timestamps = set(k["open_time"] for k in bybit_15m)
    bn_timestamps = set(k["open_time"] for k in bn_all)
    common_ts = sorted(by_timestamps & bn_timestamps)

    print(f"  Bybit timestamps: {len(by_timestamps)}")
    print(f"  Binance timestamps: {len(bn_timestamps)}")
    print(f"  Common timestamps: {len(common_ts)}")

    if len(common_ts) < 100:
        print("  Too few common timestamps. Aborting.")
        return

    # Build aligned arrays
    by_aligned = []
    bn_aligned = []
    by_ts_lookup = {k["open_time"]: k for k in bybit_15m}

    for ts in common_ts:
        by_aligned.append(by_ts_lookup[ts])
        bn_aligned.append(bn_by_ts[ts])

    # ═══════════════════════════════════════════════════════════
    # 3. PRICE COMPARISON
    # ═══════════════════════════════════════════════════════════
    print(f"\n{'='*100}")
    print(f"PRICE COMPARISON — {len(common_ts)} aligned candles")
    print(f"{'='*100}")

    by_closes = np.array([k["close"] for k in by_aligned])
    bn_closes = np.array([k["close"] for k in bn_aligned])
    by_highs = np.array([k["high"] for k in by_aligned])
    bn_highs = np.array([k["high"] for k in bn_aligned])
    by_lows = np.array([k["low"] for k in by_aligned])
    bn_lows = np.array([k["low"] for k in bn_aligned])
    by_opens = np.array([k["open"] for k in by_aligned])
    bn_opens = np.array([k["open"] for k in bn_aligned])

    close_diff = np.abs(by_closes - bn_closes)
    close_pct = close_diff / bn_closes * 100
    high_diff = np.abs(by_highs - bn_highs)
    low_diff = np.abs(by_lows - bn_lows)
    open_diff = np.abs(by_opens - bn_opens)

    print(f"\n  {'Metric':>20s} | {'Mean':>10s} {'Median':>10s} {'Max':>10s} {'Mean %':>8s}")
    print(f"  {'─'*20} | {'─'*10} {'─'*10} {'─'*10} {'─'*8}")
    for label, arr, pct_arr in [
        ("Close diff", close_diff, close_pct),
        ("High diff", high_diff, high_diff / bn_highs * 100),
        ("Low diff", low_diff, low_diff / bn_lows * 100),
        ("Open diff", open_diff, open_diff / bn_opens * 100),
    ]:
        print(f"  {label:>20s} | ${np.mean(arr):>9.2f} ${np.median(arr):>9.2f} ${np.max(arr):>9.2f} {np.mean(pct_arr):>7.4f}%")

    # Sample: show last 10 candles side by side
    print(f"\n  Last 10 candles — Close price comparison:")
    print(f"  {'Time':>20s} | {'Binance':>10s} {'Bybit':>10s} {'Diff':>8s} {'Diff %':>8s}")
    print(f"  {'─'*20} | {'─'*10} {'─'*10} {'─'*8} {'─'*8}")
    for i in range(-10, 0):
        dt = datetime.fromtimestamp(common_ts[i] / 1000, tz=timezone.utc)
        bc = bn_closes[i]; yc = by_closes[i]; d = abs(bc - yc); dp = d / bc * 100
        print(f"  {dt.strftime('%m-%d %H:%M'):>20s} | ${bc:>9.2f} ${yc:>9.2f} ${d:>7.2f} {dp:>7.4f}%")

    # ═══════════════════════════════════════════════════════════
    # 4. SUPERTREND SIGNAL COMPARISON
    # ═══════════════════════════════════════════════════════════
    print(f"\n{'='*100}")
    print("SUPERTREND SIGNAL COMPARISON — ST(10, 4.0, hl2) on aligned data")
    print(f"{'='*100}")

    n = len(common_ts)

    # Compute Supertrend on each
    by_h = np.array([k["high"] for k in by_aligned])
    by_l = np.array([k["low"] for k in by_aligned])
    by_c = np.array([k["close"] for k in by_aligned])
    bn_h = np.array([k["high"] for k in bn_aligned])
    bn_l = np.array([k["low"] for k in bn_aligned])
    bn_c = np.array([k["close"] for k in bn_aligned])

    _, by_dir = calc_supertrend(by_h, by_l, by_c, 10, 4.0, "hl2")
    _, bn_dir = calc_supertrend(bn_h, bn_l, bn_c, 10, 4.0, "hl2")

    # Compare directions
    valid = ~(np.isnan(by_dir) | np.isnan(bn_dir))
    dir_agree = np.sum(by_dir[valid] == bn_dir[valid])
    dir_total = np.sum(valid)
    dir_disagree = dir_total - dir_agree
    print(f"\n  Direction agreement: {dir_agree}/{dir_total} ({dir_agree/dir_total*100:.2f}%)")
    print(f"  Direction disagreement: {dir_disagree}/{dir_total} ({dir_disagree/dir_total*100:.2f}%)")

    # Compare flips
    by_flips = []; bn_flips = []
    for i in range(1, n):
        if not np.isnan(by_dir[i]) and not np.isnan(by_dir[i-1]) and by_dir[i] != by_dir[i-1]:
            by_flips.append((common_ts[i], int(by_dir[i])))
        if not np.isnan(bn_dir[i]) and not np.isnan(bn_dir[i-1]) and bn_dir[i] != bn_dir[i-1]:
            bn_flips.append((common_ts[i], int(bn_dir[i])))

    by_flip_set = set(by_flips)
    bn_flip_set = set(bn_flips)
    common_flips = by_flip_set & bn_flip_set
    by_only = by_flip_set - bn_flip_set
    bn_only = bn_flip_set - by_flip_set

    print(f"\n  Supertrend flips:")
    print(f"    Bybit flips:    {len(by_flips)}")
    print(f"    Binance flips:  {len(bn_flips)}")
    print(f"    Common flips:   {len(common_flips)} (same bar, same direction)")
    print(f"    Bybit-only:     {len(by_only)}")
    print(f"    Binance-only:   {len(bn_only)}")

    total_flips = len(by_flip_set | bn_flip_set)
    divergence_pct = (len(by_only) + len(bn_only)) / total_flips * 100 if total_flips > 0 else 0
    print(f"\n  Signal divergence: {divergence_pct:.1f}%")
    print(f"  {'PASS — under 5%, Binance backtest is valid' if divergence_pct < 5 else 'SIGNIFICANT — may need Bybit-specific backtest'}")

    # Show the divergent flips
    if by_only or bn_only:
        print(f"\n  Divergent flips (last 10):")
        all_divergent = []
        for ts_val, d in by_only:
            dt = datetime.fromtimestamp(ts_val / 1000, tz=timezone.utc)
            all_divergent.append((dt, "Bybit only", "BULL" if d == 1 else "BEAR"))
        for ts_val, d in bn_only:
            dt = datetime.fromtimestamp(ts_val / 1000, tz=timezone.utc)
            all_divergent.append((dt, "Binance only", "BULL" if d == 1 else "BEAR"))
        all_divergent.sort(key=lambda x: x[0])
        for dt, source, direction in all_divergent[-10:]:
            print(f"    {dt.strftime('%Y-%m-%d %H:%M')} — {source} — {direction}")

    # ═══════════════════════════════════════════════════════════
    # 5. MTF SIGNAL COMPARISON (with 1H confirmation)
    # ═══════════════════════════════════════════════════════════
    print(f"\n{'='*100}")
    print("MTF SIGNAL COMPARISON — ST(8,4.0,hlc3) 15m + ST(10,4.0,close) 1H confirm")
    print(f"{'='*100}")

    # Compute ST(8,4.0,hlc3) on both
    _, by_dir84 = calc_supertrend(by_h, by_l, by_c, 8, 4.0, "hlc3")
    _, bn_dir84 = calc_supertrend(bn_h, bn_l, bn_c, 8, 4.0, "hlc3")

    # 1H Supertrend — align to 15m bars
    # Build Bybit 1H arrays
    by_1h_h = np.array([k["high"] for k in bybit_1h])
    by_1h_l = np.array([k["low"] for k in bybit_1h])
    by_1h_c = np.array([k["close"] for k in bybit_1h])
    by_1h_ts = np.array([k["open_time"] for k in bybit_1h])
    _, by_1h_dir = calc_supertrend(by_1h_h, by_1h_l, by_1h_c, 10, 4.0, "close")

    # Binance 1H
    bn_1h_matched = [bn_1h_by_ts[k["open_time"]] for k in bn_1h_all if k["open_time"] in bn_1h_by_ts]
    bn_1h_h = np.array([k["high"] for k in bn_1h_all])
    bn_1h_l = np.array([k["low"] for k in bn_1h_all])
    bn_1h_c = np.array([k["close"] for k in bn_1h_all])
    bn_1h_ts = np.array([k["open_time"] for k in bn_1h_all])
    _, bn_1h_dir = calc_supertrend(bn_1h_h, bn_1h_l, bn_1h_c, 10, 4.0, "close")

    # Align 1H direction to 15m timestamps
    common_ts_arr = np.array(common_ts)

    def align_1h(dir_1h, ts_1h, ts_15m):
        aligned = np.ones(len(ts_15m))
        idx = 0
        for i in range(len(ts_15m)):
            while idx < len(ts_1h) - 1 and ts_1h[idx + 1] <= ts_15m[i]:
                idx += 1
            if idx < len(dir_1h):
                aligned[i] = dir_1h[idx]
        return aligned

    by_htf = align_1h(by_1h_dir, by_1h_ts, common_ts_arr)
    bn_htf = align_1h(bn_1h_dir, bn_1h_ts, common_ts_arr)

    # Count MTF signals (flip + 1H agrees)
    by_mtf_signals = []
    bn_mtf_signals = []
    for i in range(1, n):
        # Bybit
        if not np.isnan(by_dir84[i]) and not np.isnan(by_dir84[i-1]) and by_dir84[i] != by_dir84[i-1]:
            nd = 1 if by_dir84[i] == 1 else -1
            if by_htf[i] == nd:
                by_mtf_signals.append((common_ts[i], nd))
        # Binance
        if not np.isnan(bn_dir84[i]) and not np.isnan(bn_dir84[i-1]) and bn_dir84[i] != bn_dir84[i-1]:
            nd = 1 if bn_dir84[i] == 1 else -1
            if bn_htf[i] == nd:
                bn_mtf_signals.append((common_ts[i], nd))

    by_mtf_set = set(by_mtf_signals)
    bn_mtf_set = set(bn_mtf_signals)
    mtf_common = by_mtf_set & bn_mtf_set
    mtf_by_only = by_mtf_set - bn_mtf_set
    mtf_bn_only = bn_mtf_set - by_mtf_set
    mtf_total = len(by_mtf_set | bn_mtf_set)
    mtf_div = (len(mtf_by_only) + len(mtf_bn_only)) / mtf_total * 100 if mtf_total > 0 else 0

    print(f"\n  MTF signals (15m flip + 1H confirms):")
    print(f"    Bybit:          {len(by_mtf_signals)}")
    print(f"    Binance:        {len(bn_mtf_signals)}")
    print(f"    Common:         {len(mtf_common)}")
    print(f"    Bybit-only:     {len(mtf_by_only)}")
    print(f"    Binance-only:   {len(mtf_bn_only)}")
    print(f"\n  MTF signal divergence: {mtf_div:.1f}%")
    print(f"  {'PASS — under 5%' if mtf_div < 5 else 'REVIEW — over 5%'}")

    # ═══════════════════════════════════════════════════════════
    # VERDICT
    # ═══════════════════════════════════════════════════════════
    print(f"\n{'='*100}")
    print("VERDICT")
    print(f"{'='*100}")
    print(f"\n  Price difference:      mean ${np.mean(close_diff):.2f} ({np.mean(close_pct):.4f}%)")
    print(f"  ST direction match:    {dir_agree/dir_total*100:.2f}%")
    print(f"  ST flip divergence:    {divergence_pct:.1f}%")
    print(f"  MTF signal divergence: {mtf_div:.1f}%")

    if divergence_pct < 5 and mtf_div < 10:
        print(f"\n  CONCLUSION: Binance backtest is valid for Bybit/Hyperliquid trading.")
        print(f"  Use either BTCUSDT or BTCUSDT.P on TradingView — signals will be nearly identical.")
    elif divergence_pct < 10:
        print(f"\n  CONCLUSION: Minor divergence. Binance backtest is approximately valid.")
        print(f"  Prefer BTCUSDT.P (perpetual) on TradingView if available for exact match.")
    else:
        print(f"\n  CONCLUSION: Significant divergence. Consider rerunning backtest on perpetual data.")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Step 0b: Automated indicator verification.
Compare our custom calculations against the `ta` library (battle-tested open source).
For Supertrend (not in `ta`), use an independent reference implementation and cross-check.
"""

import json
import numpy as np
import pandas as pd
from pathlib import Path

# ta library — battle-tested, thousands of users
import ta
from ta.momentum import RSIIndicator
from ta.trend import MACD as MACD_TA

DATA_DIR = Path(__file__).parent.parent / "backtest-data"

# ═══════════════════════════════════════════════════════════════
# Load our custom indicator module
# ═══════════════════════════════════════════════════════════════
import sys
sys.path.insert(0, str(Path(__file__).parent))
from step0_fetch_and_verify import (
    calc_supertrend, calc_rsi, calc_macd, calc_squeeze_momentum,
    calc_tr, calc_atr_rma, calc_sma, calc_ema, calc_linreg
)


# ═══════════════════════════════════════════════════════════════
# REFERENCE SUPERTREND — independent implementation from scratch
# Based on TradingView Pine Script v6 source, translated line by line
# ═══════════════════════════════════════════════════════════════

def reference_supertrend(df: pd.DataFrame, period: int, multiplier: float, source: str = "hl2"):
    """
    Independent Supertrend implementation using pandas only.
    Translated directly from TradingView's Pine Script:

    //@version=6
    // Pine: ta.supertrend(factor, atrPeriod)
    // atr = ta.atr(atrPeriod)  // uses RMA
    // src = hl2
    // up = src - factor * atr
    // dn = src + factor * atr
    // up1 = nz(up[1], up)
    // dn1 = nz(dn[1], dn)
    // up := close[1] > up1 ? math.max(up, up1) : up
    // dn := close[1] < dn1 ? math.min(dn, dn1) : dn
    // trend = 1
    // trend := nz(trend[1], trend)
    // trend := trend == -1 and close > dn1 ? 1 : trend == 1 and close < up1 ? -1 : trend
    // supertrend = trend == 1 ? up : dn
    """
    h = df["high"].values
    l = df["low"].values
    c = df["close"].values
    n = len(c)

    # Source
    if source == "hl2":
        src = (h + l) / 2
    elif source == "hlc3":
        src = (h + l + c) / 3
    elif source == "close":
        src = c.copy()

    # True Range
    tr = np.zeros(n)
    tr[0] = h[0] - l[0]
    for i in range(1, n):
        tr[i] = max(h[i] - l[i], abs(h[i] - c[i-1]), abs(l[i] - c[i-1]))

    # ATR via RMA (Wilder's smoothing)
    atr = np.full(n, np.nan)
    atr[period - 1] = np.mean(tr[:period])
    for i in range(period, n):
        atr[i] = (atr[i-1] * (period - 1) + tr[i]) / period

    # Basic bands
    basic_up = src - multiplier * atr
    basic_dn = src + multiplier * atr

    # Final bands + trend
    up = np.full(n, np.nan)
    dn = np.full(n, np.nan)
    trend = np.ones(n)
    st = np.full(n, np.nan)

    start = period - 1
    up[start] = basic_up[start]
    dn[start] = basic_dn[start]
    trend[start] = 1
    st[start] = up[start]

    for i in range(start + 1, n):
        # Pine: up := close[1] > up1 ? max(up, up1) : up
        up1 = up[i-1]
        dn1 = dn[i-1]

        if c[i-1] > up1:
            up[i] = max(basic_up[i], up1)
        else:
            up[i] = basic_up[i]

        if c[i-1] < dn1:
            dn[i] = min(basic_dn[i], dn1)
        else:
            dn[i] = basic_dn[i]

        # Pine: trend logic
        prev_trend = trend[i-1]
        if prev_trend == -1 and c[i] > dn1:
            trend[i] = 1
        elif prev_trend == 1 and c[i] < up1:
            trend[i] = -1
        else:
            trend[i] = prev_trend

        st[i] = up[i] if trend[i] == 1 else dn[i]

    return st, trend


# ═══════════════════════════════════════════════════════════════
# REFERENCE RSI using `ta` library
# ═══════════════════════════════════════════════════════════════

def reference_rsi(closes: pd.Series, period: int) -> pd.Series:
    """RSI from ta library."""
    indicator = RSIIndicator(close=closes, window=period)
    return indicator.rsi()


# ═══════════════════════════════════════════════════════════════
# REFERENCE MACD using `ta` library
# ═══════════════════════════════════════════════════════════════

def reference_macd(closes: pd.Series, fast=12, slow=26, signal=9):
    """MACD from ta library."""
    indicator = MACD_TA(close=closes, window_fast=fast, window_slow=slow, window_sign=signal)
    return indicator.macd(), indicator.macd_signal(), indicator.macd_diff()


# ═══════════════════════════════════════════════════════════════
# COMPARISON HELPERS
# ═══════════════════════════════════════════════════════════════

def compare_arrays(name: str, custom: np.ndarray, reference: np.ndarray, last_n: int = 20, tolerance: float = 0.01):
    """Compare two arrays and report differences."""
    # Align to the shorter array from the end
    min_len = min(len(custom), len(reference))
    c = custom[-min_len:]
    r = reference[-min_len:]

    # Find valid (non-NaN) overlap
    valid = ~(np.isnan(c) | np.isnan(r))
    c_valid = c[valid]
    r_valid = r[valid]

    if len(c_valid) == 0:
        print(f"\n  {name}: NO OVERLAPPING VALID DATA")
        return False

    diff = np.abs(c_valid - r_valid)
    max_diff = np.max(diff)
    mean_diff = np.mean(diff)

    # For the last N values specifically
    c_last = custom[-last_n:]
    r_last = reference[-last_n:]
    valid_last = ~(np.isnan(c_last) | np.isnan(r_last))

    passed = max_diff <= tolerance

    status = "PASS" if passed else "FAIL"
    print(f"\n  {name}: {status}")
    print(f"    Max difference (all data):  {max_diff:.6f}")
    print(f"    Mean difference (all data): {mean_diff:.6f}")
    print(f"    Tolerance: {tolerance}")

    # Print last N comparison
    print(f"\n    Last {last_n} values comparison:")
    print(f"    {'Custom':>14s} {'Reference':>14s} {'Diff':>12s} {'OK':>4s}")
    print(f"    {'─'*14} {'─'*14} {'─'*12} {'─'*4}")
    for i in range(last_n):
        cv = c_last[i]
        rv = r_last[i]
        if np.isnan(cv) or np.isnan(rv):
            print(f"    {'NaN':>14s} {'NaN':>14s} {'─':>12s} {'─':>4s}")
        else:
            d = abs(cv - rv)
            ok = "OK" if d <= tolerance else "BAD"
            print(f"    {cv:>14.2f} {rv:>14.2f} {d:>12.6f} {ok:>4s}")

    return passed


def main():
    print("=" * 70)
    print("AUTOMATED INDICATOR VERIFICATION")
    print("Custom code vs battle-tested libraries")
    print("=" * 70)

    # Load data
    with open(DATA_DIR / "binance_btc_15m.json") as f:
        klines = json.load(f)

    df = pd.DataFrame(klines)
    closes_np = df["close"].values.astype(float)
    highs_np = df["high"].values.astype(float)
    lows_np = df["low"].values.astype(float)
    closes_pd = df["close"].astype(float)

    all_passed = True

    # ═══════════════════════════════════════════════════════════
    # 1. SUPERTREND(10, 3.0, hl2)
    # ═══════════════════════════════════════════════════════════
    print("\n" + "=" * 70)
    print("1. SUPERTREND(10, 3.0, hl2) — Custom vs Reference Implementation")
    print("=" * 70)

    custom_st, custom_dir = calc_supertrend(highs_np, lows_np, closes_np, 10, 3.0, "hl2")
    ref_st, ref_dir = reference_supertrend(df, 10, 3.0, "hl2")

    passed = compare_arrays("Supertrend Line", custom_st, ref_st, last_n=20, tolerance=0.01)
    all_passed = all_passed and passed

    # Also compare direction
    min_len = min(len(custom_dir), len(ref_dir))
    dir_match = np.sum(custom_dir[-min_len:] == ref_dir[-min_len:])
    dir_total = min_len
    dir_pct = dir_match / dir_total * 100
    print(f"\n    Direction agreement: {dir_match}/{dir_total} ({dir_pct:.2f}%)")
    if dir_pct < 100:
        # Find first disagreement from the end
        for i in range(1, min(1000, min_len)):
            if custom_dir[-i] != ref_dir[-i]:
                print(f"    First disagreement from end at index -{i}: custom={custom_dir[-i]}, ref={ref_dir[-i]}")
                break
        all_passed = False

    # ═══════════════════════════════════════════════════════════
    # 1b. SUPERTREND(10, 2.0, hl2)
    # ═══════════════════════════════════════════════════════════
    print("\n" + "=" * 70)
    print("1b. SUPERTREND(10, 2.0, hl2)")
    print("=" * 70)

    custom_st2, custom_dir2 = calc_supertrend(highs_np, lows_np, closes_np, 10, 2.0, "hl2")
    ref_st2, ref_dir2 = reference_supertrend(df, 10, 2.0, "hl2")

    passed = compare_arrays("Supertrend Line", custom_st2, ref_st2, last_n=10, tolerance=0.01)
    all_passed = all_passed and passed

    # ═══════════════════════════════════════════════════════════
    # 1c. SUPERTREND(10, 1.3, close)
    # ═══════════════════════════════════════════════════════════
    print("\n" + "=" * 70)
    print("1c. SUPERTREND(10, 1.3, close)")
    print("=" * 70)

    custom_st3, custom_dir3 = calc_supertrend(highs_np, lows_np, closes_np, 10, 1.3, "close")
    ref_st3, ref_dir3 = reference_supertrend(df, 10, 1.3, "close")

    passed = compare_arrays("Supertrend Line", custom_st3, ref_st3, last_n=10, tolerance=0.01)
    all_passed = all_passed and passed

    # ═══════════════════════════════════════════════════════════
    # 2. RSI(7) and RSI(14)
    # ═══════════════════════════════════════════════════════════
    print("\n" + "=" * 70)
    print("2. RSI — Custom vs `ta` library")
    print("=" * 70)

    custom_rsi7 = calc_rsi(closes_np, 7)
    ref_rsi7 = reference_rsi(closes_pd, 7).values

    passed = compare_arrays("RSI(7)", custom_rsi7, ref_rsi7, last_n=10, tolerance=0.01)
    all_passed = all_passed and passed

    custom_rsi14 = calc_rsi(closes_np, 14)
    ref_rsi14 = reference_rsi(closes_pd, 14).values

    passed = compare_arrays("RSI(14)", custom_rsi14, ref_rsi14, last_n=10, tolerance=0.01)
    all_passed = all_passed and passed

    # ═══════════════════════════════════════════════════════════
    # 3. MACD(12, 26, 9)
    # ═══════════════════════════════════════════════════════════
    print("\n" + "=" * 70)
    print("3. MACD(12, 26, 9) — Custom vs `ta` library")
    print("=" * 70)

    custom_macd, custom_signal, custom_hist = calc_macd(closes_np)
    ref_macd, ref_signal, ref_hist = reference_macd(closes_pd)

    passed = compare_arrays("MACD Line", custom_macd, ref_macd.values, last_n=10, tolerance=0.1)
    all_passed = all_passed and passed

    passed = compare_arrays("MACD Signal", custom_signal, ref_signal.values, last_n=10, tolerance=0.1)
    all_passed = all_passed and passed

    passed = compare_arrays("MACD Histogram", custom_hist, ref_hist.values, last_n=10, tolerance=0.1)
    all_passed = all_passed and passed

    # ═══════════════════════════════════════════════════════════
    # 4. SQUEEZE MOMENTUM
    # ═══════════════════════════════════════════════════════════
    print("\n" + "=" * 70)
    print("4. SQUEEZE MOMENTUM — Custom vs independent reference")
    print("=" * 70)

    # No ta library equivalent, so build a pandas-based reference
    # LazyBear's Squeeze Momentum:
    # BB: SMA(close, 20) ± 2.0 * stdev(close, 20)
    # KC: SMA(close, 20) ± 1.5 * SMA(TR, 20)
    # Squeeze ON: lower_bb > lower_kc and upper_bb < upper_kc
    # val = linreg(close - avg(avg(highest(high,20), lowest(low,20)), SMA(close,20)), 20, 0)

    bb_basis = closes_pd.rolling(20).mean()
    bb_std = closes_pd.rolling(20).std(ddof=0)
    upper_bb = bb_basis + 2.0 * bb_std
    lower_bb = bb_basis - 2.0 * bb_std

    # TR for KC
    tr_series = pd.Series(np.zeros(len(df)), index=df.index)
    tr_series.iloc[0] = highs_np[0] - lows_np[0]
    for i in range(1, len(df)):
        tr_series.iloc[i] = max(
            highs_np[i] - lows_np[i],
            abs(highs_np[i] - closes_np[i-1]),
            abs(lows_np[i] - closes_np[i-1])
        )

    kc_atr = tr_series.rolling(20).mean()
    kc_basis = closes_pd.rolling(20).mean()
    upper_kc = kc_basis + 1.5 * kc_atr
    lower_kc = kc_basis - 1.5 * kc_atr

    ref_squeeze_on = (lower_bb > lower_kc) & (upper_bb < upper_kc)

    # Momentum value
    highest_high = df["high"].astype(float).rolling(20).max()
    lowest_low = df["low"].astype(float).rolling(20).min()
    mid_hl = (highest_high + lowest_low) / 2
    mid_all = (mid_hl + kc_basis) / 2
    mom_src = closes_pd - mid_all

    # Linear regression
    ref_histogram = pd.Series(np.full(len(df), np.nan), index=df.index)
    for i in range(19, len(df)):
        window = mom_src.iloc[i-19:i+1].values
        if np.any(np.isnan(window)):
            continue
        x = np.arange(20, dtype=float)
        x_mean = x.mean()
        y_mean = window.mean()
        ss_xy = np.sum((x - x_mean) * (window - y_mean))
        ss_xx = np.sum((x - x_mean) ** 2)
        slope = ss_xy / ss_xx
        intercept = y_mean - slope * x_mean
        ref_histogram.iloc[i] = intercept + slope * 19

    custom_sqz_hist, custom_sqz_on = calc_squeeze_momentum(highs_np, lows_np, closes_np)

    passed = compare_arrays("SQZ Histogram", custom_sqz_hist, ref_histogram.values, last_n=10, tolerance=0.1)
    all_passed = all_passed and passed

    # Compare squeeze on/off
    ref_sqz_bool = ref_squeeze_on.values
    min_len = min(len(custom_sqz_on), len(ref_sqz_bool))
    sqz_match = np.sum(custom_sqz_on[-min_len:] == ref_sqz_bool[-min_len:])
    valid_sqz = ~pd.isna(ref_squeeze_on).values[-min_len:]
    sqz_valid_match = np.sum(custom_sqz_on[-min_len:][valid_sqz] == ref_sqz_bool[-min_len:][valid_sqz])
    sqz_valid_total = np.sum(valid_sqz)
    print(f"\n    Squeeze On/Off agreement: {sqz_valid_match}/{sqz_valid_total} ({sqz_valid_match/sqz_valid_total*100:.2f}%)")

    # ═══════════════════════════════════════════════════════════
    # FINAL VERDICT
    # ═══════════════════════════════════════════════════════════
    print("\n" + "=" * 70)
    if all_passed:
        print("ALL INDICATORS VERIFIED — CALCULATIONS MATCH REFERENCE IMPLEMENTATIONS")
    else:
        print("SOME INDICATORS FAILED VERIFICATION — SEE DETAILS ABOVE")
        print("Fixing discrepancies before proceeding...")
    print("=" * 70)

    return all_passed


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Step 0: Fetch Binance data and verify indicator calculations against TradingView.
"""

import json
import time
import math
import requests
import numpy as np
from datetime import datetime, timezone
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "backtest-data"
OUTPUT_DIR = Path(__file__).parent

# ═══════════════════════════════════════════════════════════════
# DATA FETCHING
# ═══════════════════════════════════════════════════════════════

def fetch_binance_klines(symbol: str, interval: str, limit_days: int = 730) -> list[dict]:
    """Fetch klines from Binance public API, paginating backwards."""
    url = "https://api.binance.com/api/v3/klines"
    all_klines = []

    # Binance returns max 1000 candles per request
    # Calculate how far back we need to go
    interval_ms = {
        "1m": 1 * 60 * 1000,
        "3m": 3 * 60 * 1000,
        "5m": 5 * 60 * 1000,
        "15m": 15 * 60 * 1000,
        "30m": 30 * 60 * 1000,
        "1h": 60 * 60 * 1000,
        "2h": 2 * 60 * 60 * 1000,
        "4h": 4 * 60 * 60 * 1000,
        "1d": 24 * 60 * 60 * 1000,
    }[interval]

    end_time = int(time.time() * 1000)
    start_time = end_time - (limit_days * 24 * 60 * 60 * 1000)

    current_start = start_time
    request_count = 0

    while current_start < end_time:
        params = {
            "symbol": symbol,
            "interval": interval,
            "startTime": current_start,
            "limit": 1000,
        }

        resp = requests.get(url, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        if not data:
            break

        for k in data:
            all_klines.append({
                "open_time": k[0],
                "open": float(k[1]),
                "high": float(k[2]),
                "low": float(k[3]),
                "close": float(k[4]),
                "volume": float(k[5]),
                "close_time": k[6],
                "quote_volume": float(k[7]),
                "trades": k[8],
            })

        # Move start to after the last candle we got
        current_start = data[-1][0] + interval_ms
        request_count += 1

        if request_count % 10 == 0:
            print(f"  Fetched {len(all_klines)} candles so far...")

        # Rate limit: Binance allows 1200 req/min, but be polite
        time.sleep(0.1)

    return all_klines


def check_gaps(klines: list[dict], interval: str) -> list[dict]:
    """Check for missing candles in the data."""
    interval_ms = {
        "1m": 1 * 60 * 1000,
        "3m": 3 * 60 * 1000,
        "5m": 5 * 60 * 1000,
        "15m": 15 * 60 * 1000,
        "30m": 30 * 60 * 1000,
        "1h": 60 * 60 * 1000,
        "2h": 2 * 60 * 60 * 1000,
        "4h": 4 * 60 * 60 * 1000,
        "1d": 24 * 60 * 60 * 1000,
    }[interval]

    gaps = []
    for i in range(1, len(klines)):
        expected = klines[i-1]["open_time"] + interval_ms
        actual = klines[i]["open_time"]
        if actual != expected:
            missing_count = (actual - expected) // interval_ms
            gaps.append({
                "after": datetime.fromtimestamp(klines[i-1]["open_time"]/1000, tz=timezone.utc).isoformat(),
                "before": datetime.fromtimestamp(klines[i]["open_time"]/1000, tz=timezone.utc).isoformat(),
                "missing_candles": missing_count,
            })
    return gaps


# ═══════════════════════════════════════════════════════════════
# INDICATOR CALCULATIONS — written from scratch
# ═══════════════════════════════════════════════════════════════

def calc_tr(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray) -> np.ndarray:
    """True Range calculation."""
    n = len(highs)
    tr = np.zeros(n)
    tr[0] = highs[0] - lows[0]
    for i in range(1, n):
        tr[i] = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i-1]),
            abs(lows[i] - closes[i-1])
        )
    return tr


def calc_atr_rma(tr: np.ndarray, period: int) -> np.ndarray:
    """ATR using RMA (Wilder's smoothing) — matches TradingView's ta.atr()."""
    n = len(tr)
    atr = np.full(n, np.nan)

    # First ATR value is SMA of first `period` TR values
    if n < period:
        return atr

    atr[period - 1] = np.mean(tr[:period])

    # RMA: atr[i] = (atr[i-1] * (period - 1) + tr[i]) / period
    for i in range(period, n):
        atr[i] = (atr[i-1] * (period - 1) + tr[i]) / period

    return atr


def calc_supertrend(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray,
                     atr_period: int, multiplier: float, source: str = "hl2") -> tuple[np.ndarray, np.ndarray]:
    """
    Supertrend calculation matching TradingView's ta.supertrend().
    Returns (supertrend_line, direction) where direction: 1 = bullish (price above), -1 = bearish (price below).

    TradingView Pine logic:
      src = hl2 (or hlc3 or close)
      atr = ta.atr(atr_period)
      up = src - multiplier * atr
      dn = src + multiplier * atr

      up := up > nz(up[1], up) or close[1] < nz(up[1], up) ? up : nz(up[1], up)
      dn := dn < nz(dn[1], dn) or close[1] > nz(dn[1], dn) ? dn : nz(dn[1], dn)

      trend := 1
      trend := nz(trend[1], trend)
      trend := trend == -1 and close > dn[1] ? 1 : trend == 1 and close < up[1] ? -1 : trend

      supertrend = trend == 1 ? up : dn
    """
    n = len(closes)

    # Calculate source
    if source == "hl2":
        src = (highs + lows) / 2
    elif source == "hlc3":
        src = (highs + lows + closes) / 3
    elif source == "close":
        src = closes.copy()
    else:
        raise ValueError(f"Unknown source: {source}")

    # Calculate ATR using RMA
    tr = calc_tr(highs, lows, closes)
    atr = calc_atr_rma(tr, atr_period)

    # Basic upper and lower bands
    basic_up = src - multiplier * atr
    basic_dn = src + multiplier * atr

    # Final bands with trailing logic
    final_up = np.full(n, np.nan)
    final_dn = np.full(n, np.nan)
    direction = np.ones(n)  # 1 = bullish, -1 = bearish
    supertrend = np.full(n, np.nan)

    # Start from the first valid ATR value
    start = atr_period - 1

    final_up[start] = basic_up[start]
    final_dn[start] = basic_dn[start]
    direction[start] = 1
    supertrend[start] = final_up[start]

    for i in range(start + 1, n):
        # Update upper band (support line for longs)
        if basic_up[i] > final_up[i-1] or closes[i-1] < final_up[i-1]:
            final_up[i] = basic_up[i]
        else:
            final_up[i] = final_up[i-1]

        # Update lower band (resistance line for shorts)
        if basic_dn[i] < final_dn[i-1] or closes[i-1] > final_dn[i-1]:
            final_dn[i] = basic_dn[i]
        else:
            final_dn[i] = final_dn[i-1]

        # Update direction
        prev_dir = direction[i-1]
        if prev_dir == -1 and closes[i] > final_dn[i-1]:
            direction[i] = 1
        elif prev_dir == 1 and closes[i] < final_up[i-1]:
            direction[i] = -1
        else:
            direction[i] = prev_dir

        # Supertrend line
        if direction[i] == 1:
            supertrend[i] = final_up[i]
        else:
            supertrend[i] = final_dn[i]

    return supertrend, direction


def calc_rsi(closes: np.ndarray, period: int) -> np.ndarray:
    """
    RSI using RMA (Wilder's smoothing) — matches TradingView's ta.rsi().
    """
    n = len(closes)
    rsi = np.full(n, np.nan)

    if n < period + 1:
        return rsi

    # Price changes
    delta = np.diff(closes)  # length n-1

    gains = np.where(delta > 0, delta, 0.0)
    losses = np.where(delta < 0, -delta, 0.0)

    # First average: SMA of first `period` values
    avg_gain = np.mean(gains[:period])
    avg_loss = np.mean(losses[:period])

    if avg_loss == 0:
        rsi[period] = 100.0
    else:
        rs = avg_gain / avg_loss
        rsi[period] = 100.0 - 100.0 / (1.0 + rs)

    # Subsequent values: RMA
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period

        if avg_loss == 0:
            rsi[i + 1] = 100.0
        else:
            rs = avg_gain / avg_loss
            rsi[i + 1] = 100.0 - 100.0 / (1.0 + rs)

    return rsi


def calc_ema(data: np.ndarray, period: int) -> np.ndarray:
    """EMA calculation matching TradingView."""
    n = len(data)
    ema = np.full(n, np.nan)

    # Find first non-NaN value
    start = 0
    while start < n and np.isnan(data[start]):
        start += 1

    if start + period > n:
        return ema

    # First EMA value is SMA of first `period` values
    ema[start + period - 1] = np.mean(data[start:start + period])

    k = 2.0 / (period + 1)
    for i in range(start + period, n):
        ema[i] = data[i] * k + ema[i-1] * (1 - k)

    return ema


def calc_sma(data: np.ndarray, period: int) -> np.ndarray:
    """Simple moving average."""
    n = len(data)
    sma = np.full(n, np.nan)
    for i in range(period - 1, n):
        sma[i] = np.mean(data[i - period + 1:i + 1])
    return sma


def calc_macd(closes: np.ndarray, fast: int = 12, slow: int = 26, signal: int = 9):
    """MACD matching TradingView."""
    fast_ema = calc_ema(closes, fast)
    slow_ema = calc_ema(closes, slow)
    macd_line = fast_ema - slow_ema
    signal_line = calc_ema(macd_line, signal)
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def calc_linreg(data: np.ndarray, period: int) -> np.ndarray:
    """Linear regression value (endpoint) — matches TradingView's ta.linreg(src, length, 0)."""
    n = len(data)
    result = np.full(n, np.nan)

    for i in range(period - 1, n):
        window = data[i - period + 1:i + 1]
        # x = 0, 1, 2, ..., period-1
        x = np.arange(period, dtype=float)
        x_mean = x.mean()
        y_mean = window.mean()

        ss_xy = np.sum((x - x_mean) * (window - y_mean))
        ss_xx = np.sum((x - x_mean) ** 2)

        if ss_xx == 0:
            result[i] = y_mean
        else:
            slope = ss_xy / ss_xx
            intercept = y_mean - slope * x_mean
            # Value at the last point (x = period - 1)
            result[i] = intercept + slope * (period - 1)

    return result


def calc_squeeze_momentum(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray,
                           bb_length: int = 20, bb_mult: float = 2.0,
                           kc_length: int = 20, kc_mult: float = 1.5) -> tuple[np.ndarray, np.ndarray]:
    """
    Squeeze Momentum Indicator [LazyBear] — matches TradingView.
    Returns (histogram_values, squeeze_on) where squeeze_on is boolean (True = squeeze is ON, bands inside KC).

    Logic:
    - BB = SMA ± bb_mult * stdev
    - KC = SMA ± kc_mult * ATR(kc_length) using SMA-based ATR (not RMA for KC in LazyBear's version)
    - Squeeze ON when BB is inside KC (lower_bb > lower_kc and upper_bb < upper_kc)
    - Histogram = linreg(close - avg(avg(highest(high,kc_length), lowest(low,kc_length)), SMA(close,kc_length)), kc_length, 0)
    """
    n = len(closes)

    # Bollinger Bands
    bb_basis = calc_sma(closes, bb_length)
    bb_dev = np.full(n, np.nan)
    for i in range(bb_length - 1, n):
        bb_dev[i] = np.std(closes[i - bb_length + 1:i + 1], ddof=0) * bb_mult

    upper_bb = bb_basis + bb_dev
    lower_bb = bb_basis - bb_dev

    # Keltner Channels — LazyBear uses SMA-based ATR (ta.sma(ta.tr, length))
    tr = calc_tr(highs, lows, closes)
    kc_atr = calc_sma(tr, kc_length)
    kc_basis = calc_sma(closes, kc_length)

    upper_kc = kc_basis + kc_mult * kc_atr
    lower_kc = kc_basis - kc_mult * kc_atr

    # Squeeze detection
    squeeze_on = np.full(n, False)
    for i in range(n):
        if not np.isnan(lower_bb[i]) and not np.isnan(lower_kc[i]):
            squeeze_on[i] = (lower_bb[i] > lower_kc[i]) and (upper_bb[i] < upper_kc[i])

    # Momentum histogram
    # highest(high, kc_length), lowest(low, kc_length)
    highest_high = np.full(n, np.nan)
    lowest_low = np.full(n, np.nan)
    for i in range(kc_length - 1, n):
        highest_high[i] = np.max(highs[i - kc_length + 1:i + 1])
        lowest_low[i] = np.min(lows[i - kc_length + 1:i + 1])

    # val = linreg(close - avg(avg(highest_high, lowest_low), sma(close, kc_length)), kc_length, 0)
    mid_hl = (highest_high + lowest_low) / 2
    mid_all = (mid_hl + kc_basis) / 2
    momentum_src = closes - mid_all

    histogram = calc_linreg(momentum_src, kc_length)

    return histogram, squeeze_on


# ═══════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════

def main():
    print("=" * 70)
    print("STEP 0: DATA COLLECTION AND INDICATOR VERIFICATION")
    print("=" * 70)

    # ─── Fetch 15m data ───
    print("\n[1/4] Fetching BTCUSDT 15m candles from Binance (up to 730 days)...")
    klines_15m = fetch_binance_klines("BTCUSDT", "15m", limit_days=730)

    first_dt = datetime.fromtimestamp(klines_15m[0]["open_time"]/1000, tz=timezone.utc)
    last_dt = datetime.fromtimestamp(klines_15m[-1]["open_time"]/1000, tz=timezone.utc)
    total_days = (last_dt - first_dt).total_seconds() / 86400

    print(f"  Date range: {first_dt.strftime('%Y-%m-%d %H:%M')} to {last_dt.strftime('%Y-%m-%d %H:%M')} UTC")
    print(f"  Total candles: {len(klines_15m)}")
    print(f"  Total days: {total_days:.1f}")

    gaps_15m = check_gaps(klines_15m, "15m")
    total_missing = sum(g["missing_candles"] for g in gaps_15m)
    print(f"  Gaps found: {len(gaps_15m)} ({total_missing} missing candles)")
    if gaps_15m[:5]:
        for g in gaps_15m[:5]:
            print(f"    Gap: {g['after']} -> {g['before']} ({g['missing_candles']} candles)")
        if len(gaps_15m) > 5:
            print(f"    ... and {len(gaps_15m) - 5} more gaps")

    # Save 15m data
    filepath_15m = DATA_DIR / "binance_btc_15m.json"
    with open(filepath_15m, "w") as f:
        json.dump(klines_15m, f)
    print(f"  Saved to {filepath_15m}")

    # ─── Fetch 1H data ───
    print("\n[2/4] Fetching BTCUSDT 1H candles from Binance (up to 730 days)...")
    klines_1h = fetch_binance_klines("BTCUSDT", "1h", limit_days=730)

    first_dt_1h = datetime.fromtimestamp(klines_1h[0]["open_time"]/1000, tz=timezone.utc)
    last_dt_1h = datetime.fromtimestamp(klines_1h[-1]["open_time"]/1000, tz=timezone.utc)
    total_days_1h = (last_dt_1h - first_dt_1h).total_seconds() / 86400

    print(f"  Date range: {first_dt_1h.strftime('%Y-%m-%d %H:%M')} to {last_dt_1h.strftime('%Y-%m-%d %H:%M')} UTC")
    print(f"  Total candles: {len(klines_1h)}")
    print(f"  Total days: {total_days_1h:.1f}")

    gaps_1h = check_gaps(klines_1h, "1h")
    total_missing_1h = sum(g["missing_candles"] for g in gaps_1h)
    print(f"  Gaps found: {len(gaps_1h)} ({total_missing_1h} missing candles)")

    filepath_1h = DATA_DIR / "binance_btc_1h.json"
    with open(filepath_1h, "w") as f:
        json.dump(klines_1h, f)
    print(f"  Saved to {filepath_1h}")

    # ─── Indicator Verification ───
    print("\n[3/4] Calculating indicators on 15m data for verification...")
    print("=" * 70)

    # Convert to numpy arrays
    closes = np.array([k["close"] for k in klines_15m])
    highs = np.array([k["high"] for k in klines_15m])
    lows = np.array([k["low"] for k in klines_15m])
    timestamps = [k["open_time"] for k in klines_15m]

    # ─── Supertrend(10, 3.0, hl2) — TradingView default ───
    print("\n── SUPERTREND(10, 3.0, hl2) ──")
    st_line, st_dir = calc_supertrend(highs, lows, closes, 10, 3.0, "hl2")

    print(f"  Last 10 values:")
    for i in range(-10, 0):
        idx = len(klines_15m) + i
        dt = datetime.fromtimestamp(timestamps[idx]/1000, tz=timezone.utc)
        direction_str = "BULL" if st_dir[idx] == 1 else "BEAR"
        print(f"    {dt.strftime('%Y-%m-%d %H:%M')} UTC | Close: {closes[idx]:.2f} | ST: {st_line[idx]:.2f} | {direction_str}")

    # ─── Supertrend(10, 2.0, hl2) — user's live settings ───
    print("\n── SUPERTREND(10, 2.0, hl2) ──")
    st_line2, st_dir2 = calc_supertrend(highs, lows, closes, 10, 2.0, "hl2")

    print(f"  Last 10 values:")
    for i in range(-10, 0):
        idx = len(klines_15m) + i
        dt = datetime.fromtimestamp(timestamps[idx]/1000, tz=timezone.utc)
        direction_str = "BULL" if st_dir2[idx] == 1 else "BEAR"
        print(f"    {dt.strftime('%Y-%m-%d %H:%M')} UTC | Close: {closes[idx]:.2f} | ST: {st_line2[idx]:.2f} | {direction_str}")

    # ─── Supertrend(10, 1.3, close) — colleague's settings ───
    print("\n── SUPERTREND(10, 1.3, close) ──")
    st_line3, st_dir3 = calc_supertrend(highs, lows, closes, 10, 1.3, "close")

    print(f"  Last 10 values:")
    for i in range(-10, 0):
        idx = len(klines_15m) + i
        dt = datetime.fromtimestamp(timestamps[idx]/1000, tz=timezone.utc)
        direction_str = "BULL" if st_dir3[idx] == 1 else "BEAR"
        print(f"    {dt.strftime('%Y-%m-%d %H:%M')} UTC | Close: {closes[idx]:.2f} | ST: {st_line3[idx]:.2f} | {direction_str}")

    # ─── RSI ───
    print("\n── RSI ──")
    rsi7 = calc_rsi(closes, 7)
    rsi14 = calc_rsi(closes, 14)

    print(f"  Last 5 RSI values:")
    for i in range(-5, 0):
        idx = len(klines_15m) + i
        dt = datetime.fromtimestamp(timestamps[idx]/1000, tz=timezone.utc)
        print(f"    {dt.strftime('%Y-%m-%d %H:%M')} UTC | Close: {closes[idx]:.2f} | RSI(7): {rsi7[idx]:.2f} | RSI(14): {rsi14[idx]:.2f}")

    # ─── MACD ───
    print("\n── MACD(12, 26, 9) ──")
    macd_line, signal_line, macd_hist = calc_macd(closes)

    print(f"  Last 5 MACD values:")
    for i in range(-5, 0):
        idx = len(klines_15m) + i
        dt = datetime.fromtimestamp(timestamps[idx]/1000, tz=timezone.utc)
        print(f"    {dt.strftime('%Y-%m-%d %H:%M')} UTC | MACD: {macd_line[idx]:.2f} | Signal: {signal_line[idx]:.2f} | Hist: {macd_hist[idx]:.2f}")

    # ─── Squeeze Momentum ───
    print("\n── SQUEEZE MOMENTUM [LazyBear] ──")
    sqz_hist, sqz_on = calc_squeeze_momentum(highs, lows, closes)

    print(f"  Last 5 Squeeze values:")
    for i in range(-5, 0):
        idx = len(klines_15m) + i
        dt = datetime.fromtimestamp(timestamps[idx]/1000, tz=timezone.utc)
        squeeze_str = "SQUEEZE ON" if sqz_on[idx] else "SQUEEZE OFF"
        print(f"    {dt.strftime('%Y-%m-%d %H:%M')} UTC | Histogram: {sqz_hist[idx]:.2f} | {squeeze_str}")

    # ─── Summary ───
    print("\n" + "=" * 70)
    print("DATA VERIFICATION SUMMARY")
    print("=" * 70)
    print(f"  15m data: {total_days:.1f} days, {len(klines_15m)} candles, {len(gaps_15m)} gaps ({total_missing} missing)")
    print(f"  1H data:  {total_days_1h:.1f} days, {len(klines_1h)} candles, {len(gaps_1h)} gaps ({total_missing_1h} missing)")
    print(f"  Date range: {first_dt.strftime('%Y-%m-%d')} to {last_dt.strftime('%Y-%m-%d')} UTC")
    print()
    print("  CURRENT VALUES (last closed bar):")
    print(f"    Close:           {closes[-1]:.2f}")
    print(f"    ST(10,3.0,hl2):  {st_line[-1]:.2f} ({'BULL' if st_dir[-1]==1 else 'BEAR'})")
    print(f"    ST(10,2.0,hl2):  {st_line2[-1]:.2f} ({'BULL' if st_dir2[-1]==1 else 'BEAR'})")
    print(f"    ST(10,1.3,close):{st_line3[-1]:.2f} ({'BULL' if st_dir3[-1]==1 else 'BEAR'})")
    print(f"    RSI(7):          {rsi7[-1]:.2f}")
    print(f"    RSI(14):         {rsi14[-1]:.2f}")
    print(f"    MACD:            {macd_line[-1]:.2f} | Signal: {signal_line[-1]:.2f} | Hist: {macd_hist[-1]:.2f}")
    print(f"    SQZ Mom:         {sqz_hist[-1]:.2f} | {'SQUEEZE ON' if sqz_on[-1] else 'SQUEEZE OFF'}")

    print()
    print(">>> STOP HERE. Compare these values to your TradingView chart.")
    print(">>> Do NOT proceed to backtesting until values are confirmed correct.")
    print()

    # Save verification data
    verification = {
        "data_15m": {
            "date_range": f"{first_dt.isoformat()} to {last_dt.isoformat()}",
            "total_candles": len(klines_15m),
            "total_days": round(total_days, 1),
            "gaps": len(gaps_15m),
            "missing_candles": total_missing,
        },
        "data_1h": {
            "date_range": f"{first_dt_1h.isoformat()} to {last_dt_1h.isoformat()}",
            "total_candles": len(klines_1h),
            "total_days": round(total_days_1h, 1),
            "gaps": len(gaps_1h),
            "missing_candles": total_missing_1h,
        },
        "indicators_last_bar": {
            "timestamp": datetime.fromtimestamp(timestamps[-1]/1000, tz=timezone.utc).isoformat(),
            "close": closes[-1],
            "supertrend_10_3_hl2": {"value": round(st_line[-1], 2), "direction": "BULL" if st_dir[-1]==1 else "BEAR"},
            "supertrend_10_2_hl2": {"value": round(st_line2[-1], 2), "direction": "BULL" if st_dir2[-1]==1 else "BEAR"},
            "supertrend_10_1.3_close": {"value": round(st_line3[-1], 2), "direction": "BULL" if st_dir3[-1]==1 else "BEAR"},
            "rsi_7": round(rsi7[-1], 2),
            "rsi_14": round(rsi14[-1], 2),
            "macd": {"line": round(macd_line[-1], 2), "signal": round(signal_line[-1], 2), "histogram": round(macd_hist[-1], 2)},
            "squeeze_momentum": {"histogram": round(sqz_hist[-1], 2), "squeeze_on": bool(sqz_on[-1])},
        },
    }

    verification_path = OUTPUT_DIR / "data_verification.json"
    with open(verification_path, "w") as f:
        json.dump(verification, f, indent=2)
    print(f"Verification data saved to {verification_path}")


if __name__ == "__main__":
    main()

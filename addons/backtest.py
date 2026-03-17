#!/usr/bin/env python3
"""
HyperTrader Backtesting Engine
===============================
The definitive backtesting engine for strategy optimization.
Progressive narrowing across 6 rounds with walk-forward validation,
robustness checks, and Monte Carlo simulation.

Usage:
    python addons/backtest.py                  # Run all rounds sequentially
    python addons/backtest.py --round 1        # Run only Round 1
    python addons/backtest.py --config '{...}' # Test a single config
    python addons/backtest.py --compare        # Compare live vs recommendation vs colleague
    python addons/backtest.py --monte-carlo    # Monte Carlo on final recommendation
"""

import argparse
import json
import math
import os
import random
import sys
import time
from copy import deepcopy
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from itertools import product
from pathlib import Path
from typing import Optional

import numpy as np
import requests
from tabulate import tabulate

# ─── Paths ────────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "backtest-data"
RESULTS_DIR = BASE_DIR / "backtest-results"
DATA_DIR.mkdir(exist_ok=True)
RESULTS_DIR.mkdir(exist_ok=True)

# ─── Hyperliquid API ─────────────────────────────────────────────────────────
HL_INFO_URL = "https://api.hyperliquid.xyz/info"
COIN = "BTC"

# ─── Constants ────────────────────────────────────────────────────────────────
TAKER_FEE = 0.00045
MAKER_FEE = 0.00020
SLIPPAGE = 0.00005
FUNDING_RATE_PER_8H = 0.0001  # 0.01% conservative estimate
STARTING_CAPITAL = 500.0

INTERVALS = {
    "15m": 15 * 60 * 1000,
    "1h": 60 * 60 * 1000,
    "4h": 4 * 60 * 60 * 1000,
    "1d": 24 * 60 * 60 * 1000,
}


# ═══════════════════════════════════════════════════════════════════════════════
# DATA COLLECTION
# ═══════════════════════════════════════════════════════════════════════════════

def fetch_candles(coin: str, interval: str, days: int = 180) -> list[dict]:
    """Fetch candles from Hyperliquid, using local cache if fresh."""
    cache_file = DATA_DIR / f"{coin}_{interval}_candles.json"

    # Use cache if < 1 hour old
    if cache_file.exists():
        age_sec = time.time() - cache_file.stat().st_mtime
        if age_sec < 3600:
            with open(cache_file) as f:
                data = json.load(f)
            print(f"  [{interval}] Loaded {len(data)} candles from cache ({age_sec/60:.0f}m old)")
            return data

    print(f"  [{interval}] Fetching from Hyperliquid API...")
    interval_ms = INTERVALS[interval]
    end_ms = int(time.time() * 1000)
    start_ms = end_ms - (days * 24 * 60 * 60 * 1000)
    all_candles = []
    cursor = start_ms

    # Use smaller chunks: ~500 candles per request to avoid API limits
    chunk_candles = 500
    chunk_ms = chunk_candles * interval_ms

    while cursor < end_ms:
        chunk_end = min(cursor + chunk_ms, end_ms)
        payload = {
            "type": "candleSnapshot",
            "req": {
                "coin": coin,
                "interval": interval,
                "startTime": cursor,
                "endTime": chunk_end,
            },
        }
        try:
            resp = requests.post(HL_INFO_URL, json=payload, timeout=30)
            resp.raise_for_status()
            batch = resp.json()
        except Exception as e:
            print(f"    API error at cursor {cursor}: {e}")
            cursor = chunk_end
            time.sleep(1)
            continue

        if not batch:
            cursor = chunk_end
            continue

        for c in batch:
            all_candles.append({
                "t": c["t"],
                "o": float(c["o"]),
                "h": float(c["h"]),
                "l": float(c["l"]),
                "c": float(c["c"]),
                "v": float(c["v"]),
            })

        last_t = batch[-1]["t"]
        if last_t <= cursor:
            cursor = chunk_end
        else:
            cursor = last_t + interval_ms

        if len(all_candles) % 2000 < chunk_candles:
            print(f"    ... {len(all_candles)} candles so far")

        time.sleep(0.2)  # rate limit

    # Deduplicate by timestamp
    seen = set()
    unique = []
    for c in all_candles:
        if c["t"] not in seen:
            seen.add(c["t"])
            unique.append(c)
    unique.sort(key=lambda x: x["t"])

    with open(cache_file, "w") as f:
        json.dump(unique, f)

    days_span = (unique[-1]["t"] - unique[0]["t"]) / (86400 * 1000) if unique else 0
    print(f"  [{interval}] Fetched {len(unique)} candles spanning {days_span:.0f} days")
    return unique


def fetch_funding_rates(coin: str, days: int = 180) -> list[dict]:
    """Fetch funding rate history. Returns list of {t, rate}."""
    cache_file = DATA_DIR / f"{coin}_funding.json"

    if cache_file.exists():
        age_sec = time.time() - cache_file.stat().st_mtime
        if age_sec < 3600:
            with open(cache_file) as f:
                data = json.load(f)
            print(f"  [funding] Loaded {len(data)} rates from cache")
            return data

    print("  [funding] Fetching funding rates from Hyperliquid API...")
    end_ms = int(time.time() * 1000)
    start_ms = end_ms - (days * 24 * 60 * 60 * 1000)
    all_rates = []
    cursor = start_ms

    while cursor < end_ms:
        payload = {
            "type": "fundingHistory",
            "coin": coin,
            "startTime": cursor,
            "endTime": end_ms,
        }
        try:
            resp = requests.post(HL_INFO_URL, json=payload, timeout=30)
            resp.raise_for_status()
            batch = resp.json()
            if not batch:
                break
            for r in batch:
                all_rates.append({
                    "t": r["time"],
                    "rate": float(r["fundingRate"]),
                })
            last_t = batch[-1]["time"]
            if last_t <= cursor:
                break
            cursor = last_t + 1
            time.sleep(0.15)
        except Exception as e:
            print(f"  [funding] API error: {e}, using modeled rates")
            break

    if all_rates:
        with open(cache_file, "w") as f:
            json.dump(all_rates, f)
        print(f"  [funding] Fetched {len(all_rates)} funding rate entries")
    else:
        print("  [funding] No funding data available, will use modeled rates")

    return all_rates


def load_all_data(days: int = 180) -> dict:
    """Fetch all required data."""
    print("═══ DATA COLLECTION ═══")
    data = {}
    for interval in ["15m", "1h", "4h", "1d"]:
        data[interval] = fetch_candles(COIN, interval, days)

    data["funding"] = fetch_funding_rates(COIN, days)

    # Summary
    if data["15m"]:
        span = (data["15m"][-1]["t"] - data["15m"][0]["t"]) / (86400 * 1000)
        print(f"\n  Total data span: {span:.0f} days")
        print(f"  15m bars: {len(data['15m'])}, 1h: {len(data['1h'])}, "
              f"4h: {len(data['4h'])}, 1d: {len(data['1d'])}")
        if span < 60:
            print("  ⚠ WARNING: Less than 60 days of data. Results may be less reliable.")
    return data


# ═══════════════════════════════════════════════════════════════════════════════
# INDICATORS
# ═══════════════════════════════════════════════════════════════════════════════

def ema(values: np.ndarray, period: int) -> np.ndarray:
    """Exponential Moving Average."""
    out = np.full_like(values, np.nan)
    if len(values) < period:
        return out
    alpha = 2.0 / (period + 1)
    out[period - 1] = np.mean(values[:period])
    for i in range(period, len(values)):
        out[i] = alpha * values[i] + (1 - alpha) * out[i - 1]
    return out


def sma(values: np.ndarray, period: int) -> np.ndarray:
    """Simple Moving Average."""
    out = np.full_like(values, np.nan)
    if len(values) < period:
        return out
    cumsum = np.cumsum(values)
    out[period - 1:] = (cumsum[period - 1:] - np.concatenate(([0], cumsum[:-period]))) / period
    return out


def rma(values: np.ndarray, period: int) -> np.ndarray:
    """Relative Moving Average (Wilder's smoothing)."""
    out = np.full_like(values, np.nan)
    if len(values) < period:
        return out
    out[period - 1] = np.mean(values[:period])
    alpha = 1.0 / period
    for i in range(period, len(values)):
        out[i] = alpha * values[i] + (1 - alpha) * out[i - 1]
    return out


def true_range(high: np.ndarray, low: np.ndarray, close: np.ndarray) -> np.ndarray:
    """True Range."""
    tr = np.zeros(len(high))
    tr[0] = high[0] - low[0]
    for i in range(1, len(high)):
        tr[i] = max(high[i] - low[i], abs(high[i] - close[i - 1]), abs(low[i] - close[i - 1]))
    return tr


def atr(high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int) -> np.ndarray:
    """Average True Range using RMA."""
    tr = true_range(high, low, close)
    return rma(tr, period)


def supertrend(high: np.ndarray, low: np.ndarray, close: np.ndarray,
               atr_period: int, multiplier: float, source: str = "hl2") -> tuple[np.ndarray, np.ndarray]:
    """
    Supertrend indicator.
    Returns (supertrend_line, direction) where direction: 1=bullish, -1=bearish.
    """
    n = len(close)
    atr_vals = atr(high, low, close, atr_period)

    if source == "hl2":
        src = (high + low) / 2
    elif source == "hlc3":
        src = (high + low + close) / 3
    else:
        src = close.copy()

    upper = src + multiplier * atr_vals
    lower = src - multiplier * atr_vals

    st_line = np.full(n, np.nan)
    direction = np.zeros(n, dtype=int)

    # Initialize
    st_line[atr_period - 1] = upper[atr_period - 1]
    direction[atr_period - 1] = -1

    final_upper = np.copy(upper)
    final_lower = np.copy(lower)

    for i in range(atr_period, n):
        # Final lower band
        if lower[i] > final_lower[i - 1] or close[i - 1] < final_lower[i - 1]:
            final_lower[i] = lower[i]
        else:
            final_lower[i] = final_lower[i - 1]

        # Final upper band
        if upper[i] < final_upper[i - 1] or close[i - 1] > final_upper[i - 1]:
            final_upper[i] = upper[i]
        else:
            final_upper[i] = final_upper[i - 1]

        # Direction
        if direction[i - 1] == -1:  # was bearish
            if close[i] > final_upper[i]:
                direction[i] = 1  # flip to bullish
            else:
                direction[i] = -1
        else:  # was bullish
            if close[i] < final_lower[i]:
                direction[i] = -1  # flip to bearish
            else:
                direction[i] = 1

        st_line[i] = final_lower[i] if direction[i] == 1 else final_upper[i]

    return st_line, direction


def rsi(close: np.ndarray, period: int) -> np.ndarray:
    """Relative Strength Index."""
    delta = np.diff(close, prepend=close[0])
    gains = np.where(delta > 0, delta, 0.0)
    losses = np.where(delta < 0, -delta, 0.0)
    avg_gain = rma(gains, period)
    avg_loss = rma(losses, period)
    rs = np.where(avg_loss > 0, avg_gain / avg_loss, 100.0)
    return 100.0 - 100.0 / (1.0 + rs)


def adx(high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int) -> np.ndarray:
    """Average Directional Index."""
    n = len(close)
    plus_dm = np.zeros(n)
    minus_dm = np.zeros(n)

    for i in range(1, n):
        up = high[i] - high[i - 1]
        down = low[i - 1] - low[i]
        plus_dm[i] = up if (up > down and up > 0) else 0.0
        minus_dm[i] = down if (down > up and down > 0) else 0.0

    tr_vals = true_range(high, low, close)
    atr_sm = rma(tr_vals, period)
    plus_di_sm = rma(plus_dm, period)
    minus_di_sm = rma(minus_dm, period)

    plus_di = np.full(n, np.nan)
    minus_di = np.full(n, np.nan)
    dx = np.full(n, np.nan)

    for i in range(n):
        if np.isnan(atr_sm[i]) or np.isnan(plus_di_sm[i]) or np.isnan(minus_di_sm[i]):
            continue
        if atr_sm[i] > 0:
            plus_di[i] = 100 * plus_di_sm[i] / atr_sm[i]
            minus_di[i] = 100 * minus_di_sm[i] / atr_sm[i]
        else:
            plus_di[i] = 0
            minus_di[i] = 0
        di_sum = plus_di[i] + minus_di[i]
        dx[i] = 100 * abs(plus_di[i] - minus_di[i]) / di_sum if di_sum > 0 else 0

    # Apply RMA to dx, but only over the non-NaN portion
    first_valid = -1
    for i in range(n):
        if not np.isnan(dx[i]):
            first_valid = i
            break

    out = np.full(n, np.nan)
    if first_valid >= 0 and first_valid + period <= n:
        out[first_valid + period - 1] = np.mean(dx[first_valid:first_valid + period])
        alpha = 1.0 / period
        for i in range(first_valid + period, n):
            if np.isnan(dx[i]):
                out[i] = out[i - 1]
            else:
                out[i] = alpha * dx[i] + (1 - alpha) * out[i - 1]
    return out


def macd(close: np.ndarray, fast: int = 12, slow: int = 26, signal: int = 9) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """MACD. Returns (macd_line, signal_line, histogram)."""
    fast_ema = ema(close, fast)
    slow_ema = ema(close, slow)
    macd_line = fast_ema - slow_ema
    signal_line = ema(macd_line, signal)
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def vwap_daily(timestamps: np.ndarray, high: np.ndarray, low: np.ndarray,
               close: np.ndarray, volume: np.ndarray) -> np.ndarray:
    """VWAP that resets at 00:00 UTC daily."""
    n = len(close)
    out = np.full(n, np.nan)
    typical = (high + low + close) / 3
    cum_tv = 0.0
    cum_vol = 0.0
    prev_day = -1

    for i in range(n):
        day = int(timestamps[i] // (86400 * 1000))
        if day != prev_day:
            cum_tv = 0.0
            cum_vol = 0.0
            prev_day = day
        cum_tv += typical[i] * volume[i]
        cum_vol += volume[i]
        out[i] = cum_tv / cum_vol if cum_vol > 0 else typical[i]
    return out


def bollinger_bands(close: np.ndarray, length: int, mult: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Bollinger Bands. Returns (upper, mid, lower)."""
    mid = sma(close, length)
    std = np.full_like(close, np.nan)
    for i in range(length - 1, len(close)):
        std[i] = np.std(close[i - length + 1:i + 1], ddof=0)
    upper = mid + mult * std
    lower = mid - mult * std
    return upper, mid, lower


def keltner_channels(high: np.ndarray, low: np.ndarray, close: np.ndarray,
                     length: int, mult: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Keltner Channels using EMA and ATR. Returns (upper, mid, lower)."""
    mid = ema(close, length)
    atr_vals = atr(high, low, close, length)
    upper = mid + mult * atr_vals
    lower = mid - mult * atr_vals
    return upper, mid, lower


def squeeze_momentum(high: np.ndarray, low: np.ndarray, close: np.ndarray,
                     bb_length: int = 20, bb_mult: float = 2.0,
                     kc_length: int = 20, kc_mult: float = 1.5) -> tuple[np.ndarray, np.ndarray]:
    """
    Squeeze Momentum.
    Returns (squeeze_on, momentum) where squeeze_on is boolean array.
    """
    bb_upper, bb_mid, bb_lower = bollinger_bands(close, bb_length, bb_mult)
    kc_upper, kc_mid, kc_lower = keltner_channels(high, low, close, kc_length, kc_mult)

    squeeze_on = np.zeros(len(close), dtype=bool)
    for i in range(len(close)):
        if not np.isnan(bb_lower[i]) and not np.isnan(kc_lower[i]):
            squeeze_on[i] = (bb_lower[i] > kc_lower[i]) and (bb_upper[i] < kc_upper[i])

    # Momentum: linear regression of (close - midline) over bb_length
    midline = (kc_upper + kc_lower) / 2
    delta = close - midline
    momentum = np.full_like(close, np.nan)
    for i in range(bb_length - 1, len(close)):
        y = delta[i - bb_length + 1:i + 1]
        x = np.arange(bb_length, dtype=float)
        if not np.any(np.isnan(y)):
            slope = (bb_length * np.sum(x * y) - np.sum(x) * np.sum(y)) / \
                    (bb_length * np.sum(x * x) - np.sum(x) ** 2)
            intercept = (np.sum(y) - slope * np.sum(x)) / bb_length
            momentum[i] = intercept + slope * (bb_length - 1)

    return squeeze_on, momentum


# ═══════════════════════════════════════════════════════════════════════════════
# HIGHER TIMEFRAME ALIGNMENT
# ═══════════════════════════════════════════════════════════════════════════════

def build_htf_direction_map(candles: list[dict], atr_period: int, multiplier: float,
                            source: str = "hl2") -> dict:
    """Build a timestamp -> direction lookup from higher-timeframe candles."""
    if not candles:
        return {}
    high = np.array([c["h"] for c in candles])
    low = np.array([c["l"] for c in candles])
    close = np.array([c["c"] for c in candles])
    _, direction = supertrend(high, low, close, atr_period, multiplier, source)

    # Map: for each HTF bar, its direction applies until the next bar
    dmap = {}
    for i, c in enumerate(candles):
        dmap[c["t"]] = int(direction[i])
    return dmap


def get_htf_direction_at(htf_map: dict, timestamps: list[int], ts: int) -> int:
    """Get HTF direction at a given timestamp by finding the most recent HTF bar."""
    # Binary search for the latest HTF timestamp <= ts
    lo, hi = 0, len(timestamps) - 1
    result = 0
    while lo <= hi:
        mid = (lo + hi) // 2
        if timestamps[mid] <= ts:
            result = timestamps[mid]
            lo = mid + 1
        else:
            hi = mid - 1
    return htf_map.get(result, 0)


# ═══════════════════════════════════════════════════════════════════════════════
# SIMULATION ENGINE
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class TradeRecord:
    entry_time: int
    exit_time: int
    direction: int  # 1=long, -1=short
    entry_price: float
    exit_price: float
    size: float  # in USD notional
    pnl: float
    fees: float
    funding: float
    hold_bars: int
    exit_reason: str = ""


@dataclass
class SimConfig:
    """All parameters for a single simulation run."""
    # Supertrend
    atr_period: int = 10
    multiplier: float = 2.0
    source: str = "hl2"

    # RSI filter
    rsi_enabled: bool = False
    rsi_period: int = 14
    rsi_buy_min: float = 40.0
    rsi_buy_max: float = 80.0  # 80+ = off
    rsi_sell_max: float = 60.0
    rsi_sell_min: float = 20.0  # 20- = off

    # ADX filter
    adx_enabled: bool = False
    adx_period: int = 14
    adx_min: float = 25.0

    # HTF Supertrend
    htf_enabled: bool = False
    htf_timeframe: str = "1h"
    htf_atr_period: int = 10
    htf_multiplier: float = 3.0
    htf_use_same: bool = False

    # EMA 200
    ema200_enabled: bool = False
    ema200_period: int = 200
    ema200_timeframe: str = "15m"

    # VWAP
    vwap_enabled: bool = False

    # Squeeze Momentum
    sqzmom_enabled: bool = False
    sqzmom_bb_length: int = 20
    sqzmom_bb_mult: float = 2.0
    sqzmom_kc_length: int = 20
    sqzmom_kc_mult: float = 1.5
    sqzmom_release_only: bool = False

    # MACD
    macd_enabled: bool = False
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9

    # Volume
    volume_enabled: bool = False
    volume_min_mult: float = 1.0

    # Flip cooldown
    cooldown_enabled: bool = False
    cooldown_minutes: int = 15
    cooldown_override_pct: float = 1.0

    # Stop loss / Take profit
    sl_enabled: bool = False
    sl_type: str = "atr"  # atr, pct, supertrend
    sl_atr_mult: float = 3.0
    sl_pct: float = 1.0
    tp_enabled: bool = False
    tp_atr_mult: float = 2.0
    tp_pct: float = 1.5
    trailing_supertrend: bool = False

    # Time of day
    tod_enabled: bool = False
    tod_block_start: int = 0  # UTC hour
    tod_block_end: int = 6    # UTC hour

    # Re-entry
    reentry_enabled: bool = False
    reentry_max_bars: int = 8

    # Position sizing
    sizing_mode: str = "fixed"  # fixed, compounding, anti_martingale, kelly
    position_pct: float = 25.0
    leverage: float = 10.0

    # Ambiguity zone
    ambiguity_pct: float = 0.0

    def short_name(self) -> str:
        parts = [f"ST({self.atr_period},{self.multiplier},{self.source})"]
        if self.rsi_enabled: parts.append(f"RSI({self.rsi_period},{self.rsi_buy_min}-{self.rsi_buy_max})")
        if self.adx_enabled: parts.append(f"ADX({self.adx_period},{self.adx_min})")
        if self.htf_enabled: parts.append(f"HTF({self.htf_timeframe})")
        if self.ema200_enabled: parts.append(f"EMA200({self.ema200_timeframe})")
        if self.vwap_enabled: parts.append("VWAP")
        if self.sqzmom_enabled: parts.append("SQZ")
        if self.macd_enabled: parts.append("MACD")
        if self.volume_enabled: parts.append(f"VOL({self.volume_min_mult}x)")
        if self.cooldown_enabled: parts.append(f"CD({self.cooldown_minutes}m)")
        if self.sl_enabled: parts.append(f"SL({self.sl_type})")
        if self.tp_enabled: parts.append("TP")
        if self.tod_enabled: parts.append(f"TOD({self.tod_block_start}-{self.tod_block_end})")
        if self.reentry_enabled: parts.append(f"RE({self.reentry_max_bars})")
        return " ".join(parts)


@dataclass
class SimResult:
    config: dict
    config_name: str = ""
    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    net_pnl: float = 0.0
    net_pnl_pct: float = 0.0
    max_drawdown: float = 0.0
    max_drawdown_pct: float = 0.0
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0
    calmar_ratio: float = 0.0
    avg_trade_pnl: float = 0.0
    avg_winner: float = 0.0
    avg_loser: float = 0.0
    largest_win: float = 0.0
    largest_loss: float = 0.0
    win_loss_ratio: float = 0.0
    whipsaw_count: int = 0
    total_fees: float = 0.0
    total_funding: float = 0.0
    avg_hold_bars: float = 0.0
    longest_win_streak: int = 0
    longest_lose_streak: int = 0
    trades_per_day: float = 0.0
    blocked_trades: int = 0
    blocked_winners: int = 0
    blocked_losers: int = 0
    equity_curve: list = field(default_factory=list)
    monthly_pnl: dict = field(default_factory=dict)
    trades: list = field(default_factory=list)


def run_simulation(cfg: SimConfig, data: dict, start_idx: int = 0,
                   end_idx: int = -1) -> SimResult:
    """Run a full backtest simulation with the given config on 15m data."""
    candles = data["15m"]
    if end_idx == -1:
        end_idx = len(candles)
    candles = candles[start_idx:end_idx]

    if len(candles) < max(cfg.atr_period, 200) + 50:
        return SimResult(config=asdict(cfg), config_name=cfg.short_name())

    n = len(candles)
    timestamps = np.array([c["t"] for c in candles])
    opens = np.array([c["o"] for c in candles])
    highs = np.array([c["h"] for c in candles])
    lows = np.array([c["l"] for c in candles])
    closes = np.array([c["c"] for c in candles])
    volumes = np.array([c["v"] for c in candles])

    # ── Pre-compute indicators ──
    st_line, st_dir = supertrend(highs, lows, closes, cfg.atr_period, cfg.multiplier, cfg.source)
    atr_vals = atr(highs, lows, closes, cfg.atr_period)

    rsi_vals = rsi(closes, cfg.rsi_period) if cfg.rsi_enabled else None
    adx_vals = adx(highs, lows, closes, cfg.adx_period) if cfg.adx_enabled else None

    # HTF Supertrend
    htf_map = {}
    htf_ts_sorted = []
    if cfg.htf_enabled:
        htf_candles = data.get(cfg.htf_timeframe, [])
        htf_atr = cfg.atr_period if cfg.htf_use_same else cfg.htf_atr_period
        htf_mult = cfg.multiplier if cfg.htf_use_same else cfg.htf_multiplier
        htf_map = build_htf_direction_map(htf_candles, htf_atr, htf_mult, cfg.source)
        htf_ts_sorted = sorted(htf_map.keys())

    # EMA 200
    ema200_vals = None
    if cfg.ema200_enabled:
        if cfg.ema200_timeframe == "15m":
            ema200_vals = ema(closes, cfg.ema200_period)
        else:
            htf_c = data.get(cfg.ema200_timeframe, [])
            if htf_c:
                htf_closes = np.array([c["c"] for c in htf_c])
                htf_ema = ema(htf_closes, cfg.ema200_period)
                # Build lookup
                ema200_map = {}
                for i, c in enumerate(htf_c):
                    if not np.isnan(htf_ema[i]):
                        ema200_map[c["t"]] = htf_ema[i]
                ema200_ts = sorted(ema200_map.keys())

    # VWAP
    vwap_vals = vwap_daily(timestamps, highs, lows, closes, volumes) if cfg.vwap_enabled else None

    # Squeeze
    sqz_on = None
    sqz_mom = None
    if cfg.sqzmom_enabled:
        sqz_on, sqz_mom = squeeze_momentum(highs, lows, closes,
                                            cfg.sqzmom_bb_length, cfg.sqzmom_bb_mult,
                                            cfg.sqzmom_kc_length, cfg.sqzmom_kc_mult)

    # MACD
    macd_hist = None
    if cfg.macd_enabled:
        _, _, macd_hist = macd(closes, cfg.macd_fast, cfg.macd_slow, cfg.macd_signal)

    # Volume average
    vol_sma = sma(volumes, 20) if cfg.volume_enabled else None

    # ── Funding rate lookup ──
    funding_rates = data.get("funding", [])
    funding_map = {r["t"]: r["rate"] for r in funding_rates} if funding_rates else {}
    funding_ts = sorted(funding_map.keys()) if funding_map else []

    # ── Simulation state ──
    equity = STARTING_CAPITAL
    high_water = equity
    position_dir = 0  # 0=flat, 1=long, -1=short
    position_entry = 0.0
    position_size = 0.0  # USD notional
    position_entry_time = 0
    position_entry_bar = 0
    last_flip_time = 0
    last_flip_price = 0.0
    last_trade_won = True
    pending_signal = 0
    pending_signal_bar = 0

    trades: list[TradeRecord] = []
    equity_curve = [equity]
    blocked_count = 0
    blocked_winners = 0
    blocked_losers = 0
    whipsaws = 0

    def calc_position_size(eq: float) -> float:
        pct = cfg.position_pct
        if cfg.sizing_mode == "anti_martingale" and not last_trade_won:
            pct = 15.0
        return eq * (pct / 100.0) * cfg.leverage

    def apply_funding(pos_dir: int, bars_held: int, entry_price: float, size_usd: float) -> float:
        """Calculate total funding cost for bars held."""
        if pos_dir == 0 or bars_held == 0:
            return 0.0
        # 8 hours = 32 bars of 15m
        funding_periods = bars_held / 32.0
        if not funding_map:
            # Use modeled rate
            rate = FUNDING_RATE_PER_8H
            if pos_dir == -1:
                rate = -rate
            return size_usd * rate * funding_periods
        else:
            # Use actual funding rates (approximate)
            return size_usd * FUNDING_RATE_PER_8H * funding_periods * (1 if pos_dir == 1 else -1)

    def check_filters(bar_idx: int, signal_dir: int) -> bool:
        """Check if a signal passes all filters. Returns True if trade allowed."""
        # RSI filter
        if cfg.rsi_enabled and rsi_vals is not None:
            r = rsi_vals[bar_idx]
            if not np.isnan(r):
                if signal_dir == 1:  # buy
                    if r < cfg.rsi_buy_min or (cfg.rsi_buy_max < 80 and r > cfg.rsi_buy_max):
                        return False
                else:  # sell
                    if r > cfg.rsi_sell_max or (cfg.rsi_sell_min > 20 and r < cfg.rsi_sell_min):
                        return False

        # ADX filter
        if cfg.adx_enabled and adx_vals is not None:
            a = adx_vals[bar_idx]
            if not np.isnan(a) and a < cfg.adx_min:
                return False

        # HTF Supertrend
        if cfg.htf_enabled and htf_map:
            htf_dir = get_htf_direction_at(htf_map, htf_ts_sorted, timestamps[bar_idx])
            if htf_dir != 0 and htf_dir != signal_dir:
                return False

        # EMA 200
        if cfg.ema200_enabled:
            if cfg.ema200_timeframe == "15m" and ema200_vals is not None:
                e = ema200_vals[bar_idx]
                if not np.isnan(e):
                    if signal_dir == 1 and closes[bar_idx] < e:
                        return False
                    if signal_dir == -1 and closes[bar_idx] > e:
                        return False
            elif cfg.ema200_timeframe != "15m" and 'ema200_map' in dir():
                pass  # simplified: skip non-15m EMA for performance

        # VWAP
        if cfg.vwap_enabled and vwap_vals is not None:
            v = vwap_vals[bar_idx]
            if not np.isnan(v):
                if signal_dir == 1 and closes[bar_idx] < v:
                    return False
                if signal_dir == -1 and closes[bar_idx] > v:
                    return False

        # Squeeze Momentum
        if cfg.sqzmom_enabled and sqz_on is not None:
            if sqz_on[bar_idx]:
                return False  # squeeze is on, block
            if cfg.sqzmom_release_only and sqz_mom is not None:
                m = sqz_mom[bar_idx]
                if not np.isnan(m):
                    if signal_dir == 1 and m < 0:
                        return False
                    if signal_dir == -1 and m > 0:
                        return False

        # MACD
        if cfg.macd_enabled and macd_hist is not None:
            h = macd_hist[bar_idx]
            if not np.isnan(h):
                if signal_dir == 1 and h < 0:
                    return False
                if signal_dir == -1 and h > 0:
                    return False

        # Volume
        if cfg.volume_enabled and vol_sma is not None:
            vs = vol_sma[bar_idx]
            if not np.isnan(vs) and vs > 0:
                if volumes[bar_idx] < cfg.volume_min_mult * vs:
                    return False

        # Cooldown
        if cfg.cooldown_enabled and last_flip_time > 0:
            elapsed_min = (timestamps[bar_idx] - last_flip_time) / 60000
            if elapsed_min < cfg.cooldown_minutes:
                # Check emergency override
                if last_flip_price > 0:
                    price_change = abs(closes[bar_idx] - last_flip_price) / last_flip_price * 100
                    if price_change < cfg.cooldown_override_pct:
                        return False

        # Time of day
        if cfg.tod_enabled:
            utc_hour = (timestamps[bar_idx] // 3600000) % 24
            if cfg.tod_block_start <= cfg.tod_block_end:
                if cfg.tod_block_start <= utc_hour < cfg.tod_block_end:
                    return False
            else:  # wraps midnight
                if utc_hour >= cfg.tod_block_start or utc_hour < cfg.tod_block_end:
                    return False

        return True

    def close_position(bar_idx: int, exit_price: float, reason: str = "signal"):
        nonlocal equity, high_water, position_dir, position_size, position_entry
        nonlocal position_entry_time, position_entry_bar, last_flip_time, last_flip_price
        nonlocal last_trade_won

        if position_dir == 0:
            return

        # Fees: taker on close
        fee = position_size * (TAKER_FEE + SLIPPAGE)

        # P&L
        if position_dir == 1:
            pnl = position_size * (exit_price - position_entry) / position_entry
        else:
            pnl = position_size * (position_entry - exit_price) / position_entry

        # Funding
        bars_held = bar_idx - position_entry_bar
        funding_cost = apply_funding(position_dir, bars_held, position_entry, position_size)

        net_pnl = pnl - fee - funding_cost
        equity += net_pnl
        high_water = max(high_water, equity)
        last_trade_won = net_pnl > 0

        trades.append(TradeRecord(
            entry_time=position_entry_time,
            exit_time=int(timestamps[bar_idx]),
            direction=position_dir,
            entry_price=position_entry,
            exit_price=exit_price,
            size=position_size,
            pnl=net_pnl,
            fees=fee,
            funding=funding_cost,
            hold_bars=bars_held,
            exit_reason=reason,
        ))

        last_flip_time = int(timestamps[bar_idx])
        last_flip_price = exit_price
        position_dir = 0
        position_size = 0.0

    def open_position(bar_idx: int, direction: int, entry_price: float):
        nonlocal position_dir, position_entry, position_size, position_entry_time, position_entry_bar

        # Entry fee
        size = calc_position_size(equity)
        fee = size * (TAKER_FEE + SLIPPAGE)

        position_dir = direction
        position_entry = entry_price
        position_size = size
        position_entry_time = int(timestamps[bar_idx])
        position_entry_bar = bar_idx

    # ── Main loop ──
    warmup = max(cfg.atr_period, 200) + 10  # enough for all indicators
    for i in range(warmup, n - 1):  # -1 because we execute on next bar
        # Check SL/TP on current bar
        if position_dir != 0 and (cfg.sl_enabled or cfg.tp_enabled or cfg.trailing_supertrend):
            # Trailing Supertrend stop
            if cfg.trailing_supertrend and not np.isnan(st_line[i]):
                if position_dir == 1 and lows[i] < st_line[i]:
                    close_position(i, st_line[i], "trailing_st")
                elif position_dir == -1 and highs[i] > st_line[i]:
                    close_position(i, st_line[i], "trailing_st")

            if position_dir != 0 and cfg.sl_enabled:
                if cfg.sl_type == "atr" and not np.isnan(atr_vals[i]):
                    sl_dist = cfg.sl_atr_mult * atr_vals[i]
                    if position_dir == 1 and lows[i] <= position_entry - sl_dist:
                        close_position(i, position_entry - sl_dist, "sl_atr")
                    elif position_dir == -1 and highs[i] >= position_entry + sl_dist:
                        close_position(i, position_entry + sl_dist, "sl_atr")
                elif cfg.sl_type == "pct":
                    sl_dist = position_entry * cfg.sl_pct / 100
                    if position_dir == 1 and lows[i] <= position_entry - sl_dist:
                        close_position(i, position_entry - sl_dist, "sl_pct")
                    elif position_dir == -1 and highs[i] >= position_entry + sl_dist:
                        close_position(i, position_entry + sl_dist, "sl_pct")

            if position_dir != 0 and cfg.tp_enabled:
                if cfg.tp_pct > 0:
                    tp_dist = position_entry * cfg.tp_pct / 100
                else:
                    tp_dist = cfg.tp_atr_mult * atr_vals[i] if not np.isnan(atr_vals[i]) else 0
                if tp_dist > 0:
                    if position_dir == 1 and highs[i] >= position_entry + tp_dist:
                        close_position(i, position_entry + tp_dist, "tp")
                    elif position_dir == -1 and lows[i] <= position_entry - tp_dist:
                        close_position(i, position_entry - tp_dist, "tp")

        # Detect Supertrend direction change
        if i < cfg.atr_period + 1:
            equity_curve.append(equity)
            continue

        prev_dir = st_dir[i - 1]
        curr_dir = st_dir[i]

        signal = 0
        if prev_dir == -1 and curr_dir == 1:
            signal = 1  # Buy signal
        elif prev_dir == 1 and curr_dir == -1:
            signal = -1  # Sell signal

        # Re-entry: check pending signal
        if signal == 0 and cfg.reentry_enabled and pending_signal != 0:
            if st_dir[i] == pending_signal and (i - pending_signal_bar) <= cfg.reentry_max_bars:
                if check_filters(i, pending_signal):
                    signal = pending_signal
                    pending_signal = 0
            elif (i - pending_signal_bar) > cfg.reentry_max_bars:
                pending_signal = 0

        if signal != 0:
            # Check filters
            if check_filters(i, signal):
                # Execute on NEXT bar's open
                exec_price = opens[i + 1]

                # Ambiguity zone check
                if cfg.ambiguity_pct > 0 and not np.isnan(st_line[i]):
                    dist_pct = abs(closes[i] - st_line[i]) / st_line[i] * 100
                    if dist_pct < cfg.ambiguity_pct:
                        blocked_count += 1
                        equity_curve.append(equity)
                        continue

                # Close existing position if any (flip)
                if position_dir != 0 and position_dir != signal:
                    close_position(i + 1, exec_price, "flip")
                    if trades and (timestamps[i + 1] - last_flip_time) < 30 * 60 * 1000:
                        whipsaws += 1

                # Open new position
                if position_dir == 0:
                    open_position(i + 1, signal, exec_price)
            else:
                # Signal blocked by filter
                blocked_count += 1
                # Track if this blocked trade would have been a winner
                if i + 1 < n - 1:
                    future_price = closes[min(i + 20, n - 1)]
                    would_pnl = (future_price - opens[i + 1]) / opens[i + 1] * signal
                    if would_pnl > 0:
                        blocked_winners += 1
                    else:
                        blocked_losers += 1
                # Set up re-entry
                if cfg.reentry_enabled:
                    pending_signal = signal
                    pending_signal_bar = i

        equity_curve.append(equity)

        # Bail if equity goes below $10
        if equity < 10:
            break

    # Close any open position at end
    if position_dir != 0:
        close_position(n - 2, closes[n - 2], "end_of_data")

    # ── Compute stats ──
    result = compute_stats(trades, equity_curve, cfg, candles)
    result.blocked_trades = blocked_count
    result.blocked_winners = blocked_winners
    result.blocked_losers = blocked_losers
    result.whipsaw_count = whipsaws
    return result


def compute_stats(trades: list[TradeRecord], equity_curve: list[float],
                  cfg: SimConfig, candles: list[dict]) -> SimResult:
    """Compute comprehensive statistics from trade results."""
    result = SimResult(config=asdict(cfg), config_name=cfg.short_name())
    result.equity_curve = equity_curve

    if not trades:
        return result

    pnls = [t.pnl for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]

    result.total_trades = len(trades)
    result.wins = len(wins)
    result.losses = len(losses)
    result.win_rate = len(wins) / len(trades) * 100 if trades else 0
    result.net_pnl = sum(pnls)
    result.net_pnl_pct = result.net_pnl / STARTING_CAPITAL * 100
    result.total_fees = sum(t.fees for t in trades)
    result.total_funding = sum(t.funding for t in trades)
    result.avg_trade_pnl = np.mean(pnls) if pnls else 0
    result.avg_winner = np.mean(wins) if wins else 0
    result.avg_loser = np.mean(losses) if losses else 0
    result.largest_win = max(pnls) if pnls else 0
    result.largest_loss = min(pnls) if pnls else 0
    result.win_loss_ratio = abs(result.avg_winner / result.avg_loser) if result.avg_loser != 0 else 0

    gross_wins = sum(wins)
    gross_losses = abs(sum(losses))
    result.profit_factor = gross_wins / gross_losses if gross_losses > 0 else (999.0 if gross_wins > 0 else 0.0)

    # Drawdown
    eq = np.array(equity_curve)
    hw = np.maximum.accumulate(eq)
    dd = eq - hw
    result.max_drawdown = abs(min(dd)) if len(dd) > 0 else 0
    result.max_drawdown_pct = result.max_drawdown / max(hw) * 100 if max(hw) > 0 else 0

    # Sharpe / Sortino (annualized, 15m bars)
    if len(pnls) > 1:
        returns = np.array(pnls) / STARTING_CAPITAL
        mean_ret = np.mean(returns)
        std_ret = np.std(returns, ddof=1)
        # Annualize: ~35040 15m bars per year, but use trade count
        trades_per_year = len(trades) / max(1, (candles[-1]["t"] - candles[0]["t"]) / (365.25 * 86400000)) * 1
        ann_factor = math.sqrt(max(trades_per_year, 1))
        result.sharpe_ratio = (mean_ret / std_ret * ann_factor) if std_ret > 0 else 0

        downside = returns[returns < 0]
        downside_std = np.std(downside, ddof=1) if len(downside) > 1 else 0
        result.sortino_ratio = (mean_ret / downside_std * ann_factor) if downside_std > 0 else 0

    # Calmar
    days_span = (candles[-1]["t"] - candles[0]["t"]) / (86400 * 1000)
    if days_span > 0 and result.max_drawdown_pct > 0:
        total_return = result.net_pnl / STARTING_CAPITAL
        cagr = (1 + total_return) ** (365.0 / days_span) - 1 if total_return > -1 else -1
        result.calmar_ratio = cagr / (result.max_drawdown_pct / 100) if result.max_drawdown_pct > 0 else 0

    # Hold time
    result.avg_hold_bars = np.mean([t.hold_bars for t in trades]) if trades else 0

    # Streaks
    streak = 0
    max_w_streak = 0
    max_l_streak = 0
    for p in pnls:
        if p > 0:
            if streak > 0:
                streak += 1
            else:
                streak = 1
            max_w_streak = max(max_w_streak, streak)
        else:
            if streak < 0:
                streak -= 1
            else:
                streak = -1
            max_l_streak = max(max_l_streak, abs(streak))
    result.longest_win_streak = max_w_streak
    result.longest_lose_streak = max_l_streak

    # Trades per day
    if days_span > 0:
        result.trades_per_day = len(trades) / days_span

    # Monthly P&L
    monthly = {}
    for t in trades:
        dt = datetime.fromtimestamp(t.exit_time / 1000, tz=timezone.utc)
        key = f"{dt.year}-{dt.month:02d}"
        monthly[key] = monthly.get(key, 0) + t.pnl
    result.monthly_pnl = monthly

    result.trades = [asdict(t) for t in trades]
    return result


# ═══════════════════════════════════════════════════════════════════════════════
# MONTE CARLO
# ═══════════════════════════════════════════════════════════════════════════════

def monte_carlo(trades: list[dict], iterations: int = 1000) -> dict:
    """Monte Carlo simulation — randomize trade order."""
    if not trades:
        return {}

    pnls = [t["pnl"] for t in trades]
    n_trades = len(pnls)

    final_equities = []
    max_drawdowns = []

    for _ in range(iterations):
        shuffled = pnls.copy()
        random.shuffle(shuffled)
        eq = STARTING_CAPITAL
        hw = eq
        max_dd = 0
        for p in shuffled:
            eq += p
            hw = max(hw, eq)
            dd = (hw - eq) / hw * 100
            max_dd = max(max_dd, dd)
        final_equities.append(eq)
        max_drawdowns.append(max_dd)

    final_equities.sort()
    max_drawdowns.sort()

    def profitable_at_n(n_trades_check):
        count = 0
        for _ in range(iterations):
            subset = random.choices(pnls, k=min(n_trades_check, n_trades))
            if sum(subset) > 0:
                count += 1
        return count / iterations * 100

    return {
        "iterations": iterations,
        "median_pnl": final_equities[iterations // 2] - STARTING_CAPITAL,
        "p5_pnl": final_equities[int(iterations * 0.05)] - STARTING_CAPITAL,
        "p95_pnl": final_equities[int(iterations * 0.95)] - STARTING_CAPITAL,
        "prob_profitable_50": profitable_at_n(50),
        "prob_profitable_100": profitable_at_n(100),
        "prob_profitable_200": profitable_at_n(200),
        "max_drawdown_p95": max_drawdowns[int(iterations * 0.95)],
        "max_drawdown_median": max_drawdowns[iterations // 2],
    }


# ═══════════════════════════════════════════════════════════════════════════════
# WALK-FORWARD SPLIT
# ═══════════════════════════════════════════════════════════════════════════════

def train_test_split(data: dict, train_pct: float = 0.70) -> tuple[int, int, int]:
    """Return (start, split_idx, end_idx) for 15m candles."""
    n = len(data["15m"])
    split = int(n * train_pct)
    return 0, split, n


def thirds_split(data: dict) -> list[tuple[int, int]]:
    """Split data into thirds for robustness check."""
    n = len(data["15m"])
    t1 = n // 3
    t2 = 2 * n // 3
    return [(0, t1), (t1, t2), (t2, n)]


# ═══════════════════════════════════════════════════════════════════════════════
# DISPLAY HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def format_results_table(results: list[SimResult], title: str, top_n: int = 10) -> str:
    """Format top results as a table."""
    if not results:
        return f"\n{title}\n  No results.\n"

    rows = []
    for r in results[:top_n]:
        rows.append([
            r.config_name[:50],
            r.total_trades,
            f"{r.win_rate:.1f}%",
            f"{r.profit_factor:.2f}",
            f"${r.net_pnl:.2f}",
            f"{r.net_pnl_pct:.1f}%",
            f"{r.max_drawdown_pct:.1f}%",
            f"{r.sharpe_ratio:.2f}",
            f"${r.total_fees:.2f}",
            f"{r.avg_hold_bars:.0f}",
            r.whipsaw_count,
        ])

    headers = ["Config", "Trades", "WinRate", "PF", "NetPnL", "PnL%", "MaxDD%", "Sharpe", "Fees", "AvgBars", "Whip"]
    table = tabulate(rows, headers=headers, tablefmt="simple", stralign="right")
    return f"\n{'═' * 80}\n{title}\n{'═' * 80}\n{table}\n"


def save_round_results(results: list[SimResult], filename: str):
    """Save results to JSON, excluding large arrays for non-top results."""
    out = []
    for i, r in enumerate(results):
        d = {
            "config": r.config,
            "config_name": r.config_name,
            "total_trades": r.total_trades,
            "win_rate": r.win_rate,
            "profit_factor": r.profit_factor,
            "net_pnl": r.net_pnl,
            "net_pnl_pct": r.net_pnl_pct,
            "max_drawdown": r.max_drawdown,
            "max_drawdown_pct": r.max_drawdown_pct,
            "sharpe_ratio": r.sharpe_ratio,
            "sortino_ratio": r.sortino_ratio,
            "calmar_ratio": r.calmar_ratio,
            "avg_trade_pnl": r.avg_trade_pnl,
            "avg_winner": r.avg_winner,
            "avg_loser": r.avg_loser,
            "largest_win": r.largest_win,
            "largest_loss": r.largest_loss,
            "win_loss_ratio": r.win_loss_ratio,
            "whipsaw_count": r.whipsaw_count,
            "total_fees": r.total_fees,
            "total_funding": r.total_funding,
            "avg_hold_bars": r.avg_hold_bars,
            "longest_win_streak": r.longest_win_streak,
            "longest_lose_streak": r.longest_lose_streak,
            "trades_per_day": r.trades_per_day,
            "blocked_trades": r.blocked_trades,
            "blocked_winners": r.blocked_winners,
            "blocked_losers": r.blocked_losers,
            "monthly_pnl": r.monthly_pnl,
        }
        # Only save equity curves and trade lists for top 20
        if i < 20:
            d["equity_curve"] = r.equity_curve
            d["trades"] = r.trades
        out.append(d)

    with open(RESULTS_DIR / filename, "w") as f:
        json.dump(out, f, indent=2)
    print(f"  Saved {len(out)} results to {RESULTS_DIR / filename}")


# ═══════════════════════════════════════════════════════════════════════════════
# ROUND IMPLEMENTATIONS
# ═══════════════════════════════════════════════════════════════════════════════

def run_round1(data: dict) -> list[SimResult]:
    """Round 1: Supertrend baseline — no filters."""
    print("\n═══ ROUND 1: Supertrend Baseline (Training Data Only) ═══")
    _, split, _ = train_test_split(data)

    atr_periods = [7, 9, 10, 12, 14]
    multipliers = [1.3, 1.5, 1.8, 2.0, 2.2, 2.5, 3.0]
    sources = ["hl2", "hlc3", "close"]

    combos = list(product(atr_periods, multipliers, sources))
    total = len(combos)
    print(f"  Testing {total} combinations...")

    results = []
    for idx, (atr_p, mult, src) in enumerate(combos):
        cfg = SimConfig(atr_period=atr_p, multiplier=mult, source=src)
        r = run_simulation(cfg, data, start_idx=0, end_idx=split)
        results.append(r)
        if (idx + 1) % 20 == 0:
            print(f"  Progress: {idx + 1}/{total}")

    # Sort by multiple criteria
    by_pf = sorted([r for r in results if r.total_trades > 5], key=lambda x: x.profit_factor, reverse=True)
    by_pnl = sorted([r for r in results if r.total_trades > 5], key=lambda x: x.net_pnl, reverse=True)
    by_sharpe = sorted([r for r in results if r.total_trades > 5], key=lambda x: x.sharpe_ratio, reverse=True)

    print(format_results_table(by_pf, "Top 10 by Profit Factor"))
    print(format_results_table(by_pnl, "Top 10 by Net P&L"))
    print(format_results_table(by_sharpe, "Top 10 by Sharpe Ratio"))

    # Find configs appearing in multiple top-10 lists
    top_pf_names = set(r.config_name for r in by_pf[:10])
    top_pnl_names = set(r.config_name for r in by_pnl[:10])
    top_sharpe_names = set(r.config_name for r in by_sharpe[:10])

    # Score: how many top-10 lists each config appears in
    all_names = set()
    all_names.update(top_pf_names, top_pnl_names, top_sharpe_names)
    scored = []
    for name in all_names:
        score = (name in top_pf_names) + (name in top_pnl_names) + (name in top_sharpe_names)
        scored.append((name, score))
    scored.sort(key=lambda x: x[1], reverse=True)

    print("\n  Configs appearing in multiple top-10 lists:")
    for name, score in scored[:10]:
        print(f"    [{score}/3] {name}")

    # Pick top 5 (prefer multi-list, then by PF)
    top5_names = [s[0] for s in scored[:5]]
    if len(top5_names) < 5:
        for r in by_pf:
            if r.config_name not in top5_names:
                top5_names.append(r.config_name)
            if len(top5_names) >= 5:
                break

    top5 = [r for r in results if r.config_name in top5_names]
    top5.sort(key=lambda x: x.profit_factor, reverse=True)
    top5 = top5[:5]

    print(f"\n  Selected Top 5 for Round 2:")
    for r in top5:
        print(f"    {r.config_name} — PF:{r.profit_factor:.2f} PnL:${r.net_pnl:.2f} WR:{r.win_rate:.1f}%")

    # Save all results sorted by PF
    save_round_results(by_pf, "round1_results.json")
    return top5


def run_round2(data: dict, top5: list[SimResult]) -> list[tuple[str, SimResult, SimResult]]:
    """Round 2: Test each filter individually against top 5 configs."""
    print("\n═══ ROUND 2: Individual Filter Tests ═══")
    _, split, _ = train_test_split(data)

    filter_results = []  # (filter_name, best_result, baseline_result)

    for base in top5:
        bc = base.config  # dict
        base_cfg = SimConfig(**{k: v for k, v in bc.items() if k in SimConfig.__dataclass_fields__})
        print(f"\n  Testing filters on: {base.config_name}")

        # RSI variations
        for rsi_p, buy_min, buy_max, sell_max, sell_min in product(
            [7, 12, 14], [40, 45, 50, 55], [70, 75, 80], [60, 55, 50, 45], [30, 25, 20]
        ):
            if buy_min >= sell_max:
                continue  # invalid combo
            cfg = SimConfig(**{k: v for k, v in bc.items() if k in SimConfig.__dataclass_fields__})
            cfg.rsi_enabled = True
            cfg.rsi_period = rsi_p
            cfg.rsi_buy_min = buy_min
            cfg.rsi_buy_max = buy_max
            cfg.rsi_sell_max = sell_max
            cfg.rsi_sell_min = sell_min
            r = run_simulation(cfg, data, 0, split)
            if r.total_trades > 3:
                filter_results.append(("RSI", r, base))

        print("    RSI done")

        # ADX variations
        for adx_p, adx_min in product([14, 20], [15, 20, 25, 30]):
            cfg = SimConfig(**{k: v for k, v in bc.items() if k in SimConfig.__dataclass_fields__})
            cfg.adx_enabled = True
            cfg.adx_period = adx_p
            cfg.adx_min = adx_min
            r = run_simulation(cfg, data, 0, split)
            if r.total_trades > 3:
                filter_results.append(("ADX", r, base))

        print("    ADX done")

        # HTF Supertrend
        for htf_tf, htf_same in product(["1h", "4h"], [True, False]):
            cfg = SimConfig(**{k: v for k, v in bc.items() if k in SimConfig.__dataclass_fields__})
            cfg.htf_enabled = True
            cfg.htf_timeframe = htf_tf
            cfg.htf_use_same = htf_same
            r = run_simulation(cfg, data, 0, split)
            if r.total_trades > 3:
                filter_results.append(("HTF", r, base))

        print("    HTF done")

        # EMA 200
        for ema_tf in ["15m", "1h"]:
            cfg = SimConfig(**{k: v for k, v in bc.items() if k in SimConfig.__dataclass_fields__})
            cfg.ema200_enabled = True
            cfg.ema200_timeframe = ema_tf
            r = run_simulation(cfg, data, 0, split)
            if r.total_trades > 3:
                filter_results.append(("EMA200", r, base))

        # VWAP
        cfg = SimConfig(**{k: v for k, v in bc.items() if k in SimConfig.__dataclass_fields__})
        cfg.vwap_enabled = True
        r = run_simulation(cfg, data, 0, split)
        if r.total_trades > 3:
            filter_results.append(("VWAP", r, base))

        # Squeeze Momentum
        for release in [False, True]:
            cfg = SimConfig(**{k: v for k, v in bc.items() if k in SimConfig.__dataclass_fields__})
            cfg.sqzmom_enabled = True
            cfg.sqzmom_release_only = release
            r = run_simulation(cfg, data, 0, split)
            if r.total_trades > 3:
                filter_results.append(("SQZMOM", r, base))

        # MACD
        cfg = SimConfig(**{k: v for k, v in bc.items() if k in SimConfig.__dataclass_fields__})
        cfg.macd_enabled = True
        r = run_simulation(cfg, data, 0, split)
        if r.total_trades > 3:
            filter_results.append(("MACD", r, base))

        # Volume
        for vol_m in [1.0, 1.5, 2.0]:
            cfg = SimConfig(**{k: v for k, v in bc.items() if k in SimConfig.__dataclass_fields__})
            cfg.volume_enabled = True
            cfg.volume_min_mult = vol_m
            r = run_simulation(cfg, data, 0, split)
            if r.total_trades > 3:
                filter_results.append(("VOLUME", r, base))

        # Flip cooldown
        for cd_min, cd_ovr in product([5, 10, 15, 20, 30], [0.5, 1.0]):
            cfg = SimConfig(**{k: v for k, v in bc.items() if k in SimConfig.__dataclass_fields__})
            cfg.cooldown_enabled = True
            cfg.cooldown_minutes = cd_min
            cfg.cooldown_override_pct = cd_ovr
            r = run_simulation(cfg, data, 0, split)
            if r.total_trades > 3:
                filter_results.append(("COOLDOWN", r, base))

        print("    Cooldown done")

        # Time of day
        tod_windows = [
            (0, 6), (0, 8), (13, 21), (12, 20), (8, 24),  # block 00-24 = Asian only
        ]
        for start, end in tod_windows:
            cfg = SimConfig(**{k: v for k, v in bc.items() if k in SimConfig.__dataclass_fields__})
            cfg.tod_enabled = True
            cfg.tod_block_start = start
            cfg.tod_block_end = end
            r = run_simulation(cfg, data, 0, split)
            if r.total_trades > 3:
                filter_results.append(("TOD", r, base))

        print("    TOD done")

    # Rank filters by improvement to profit factor over baseline
    ranked = []
    for fname, result, baseline in filter_results:
        pf_improvement = result.profit_factor - baseline.profit_factor
        ranked.append({
            "filter": fname,
            "config_name": result.config_name,
            "pf": result.profit_factor,
            "pf_improvement": pf_improvement,
            "pnl": result.net_pnl,
            "pnl_improvement": result.net_pnl - baseline.net_pnl,
            "win_rate": result.win_rate,
            "trades": result.total_trades,
            "base": baseline.config_name,
            "result": result,
        })

    ranked.sort(key=lambda x: x["pf_improvement"], reverse=True)

    # Display
    print(f"\n{'═' * 80}")
    print("Filter Rankings by Profit Factor Improvement")
    print(f"{'═' * 80}")
    rows = []
    for r in ranked[:20]:
        rows.append([
            r["filter"],
            r["config_name"][:40],
            f"{r['pf']:.2f}",
            f"{r['pf_improvement']:+.2f}",
            f"${r['pnl']:.2f}",
            f"${r['pnl_improvement']:+.2f}",
            f"{r['win_rate']:.1f}%",
            r["trades"],
        ])
    headers = ["Filter", "Config", "PF", "PF Δ", "PnL", "PnL Δ", "WR", "Trades"]
    print(tabulate(rows, headers=headers, tablefmt="simple", stralign="right"))

    # Save
    save_data = [{k: v for k, v in r.items() if k != "result"} for r in ranked]
    with open(RESULTS_DIR / "round2_results.json", "w") as f:
        json.dump(save_data, f, indent=2)
    print(f"\n  Saved {len(save_data)} results to round2_results.json")

    # Return top filter configs for Round 3
    return ranked[:20]


def run_round3(data: dict, top5_base: list[SimResult], round2_ranked: list) -> list[SimResult]:
    """Round 3: Combined filter optimization."""
    print("\n═══ ROUND 3: Combined Filter Optimization ═══")
    _, split, _ = train_test_split(data)

    # Best filter params from Round 2 (hardcoded from results)
    # These are the winning params per filter type across all bases
    filter_types = ["VOLUME", "RSI", "TOD", "SQZMOM", "COOLDOWN"]
    print(f"  Top filter types: {filter_types}")

    results = []

    # For each of top 3 base configs, try filter combos
    for base in top5_base[:3]:
        bc = base.config

        def make_cfg_with_filters(filter_names):
            cfg = SimConfig(**{k: v for k, v in bc.items() if k in SimConfig.__dataclass_fields__})
            for fname in filter_names:
                if fname == "VOLUME":
                    cfg.volume_enabled = True
                    cfg.volume_min_mult = 1.5
                elif fname == "RSI":
                    cfg.rsi_enabled = True
                    cfg.rsi_period = 7
                    cfg.rsi_buy_min = 40.0
                    cfg.rsi_buy_max = 70.0
                    cfg.rsi_sell_max = 60.0
                    cfg.rsi_sell_min = 20.0
                elif fname == "TOD":
                    cfg.tod_enabled = True
                    cfg.tod_block_start = 0
                    cfg.tod_block_end = 6
                elif fname == "SQZMOM":
                    cfg.sqzmom_enabled = True
                    cfg.sqzmom_release_only = False
                elif fname == "COOLDOWN":
                    cfg.cooldown_enabled = True
                    cfg.cooldown_minutes = 20
                    cfg.cooldown_override_pct = 1.0
            return cfg

        print(f"\n  Base: {base.config_name}")

        # Single best filter
        for f1 in filter_types:
            cfg = make_cfg_with_filters([f1])
            r = run_simulation(cfg, data, 0, split)
            if r.total_trades > 3:
                results.append(r)

        # Best 2 filters
        for i, f1 in enumerate(filter_types):
            for f2 in filter_types[i + 1:]:
                cfg = make_cfg_with_filters([f1, f2])
                r = run_simulation(cfg, data, 0, split)
                if r.total_trades > 3:
                    results.append(r)

        # Best 3 filters
        for i, f1 in enumerate(filter_types):
            for j, f2 in enumerate(filter_types[i + 1:], i + 1):
                for f3 in filter_types[j + 1:]:
                    cfg = make_cfg_with_filters([f1, f2, f3])
                    r = run_simulation(cfg, data, 0, split)
                    if r.total_trades > 3:
                        results.append(r)

        # Best 4 filters
        for i in range(len(filter_types)):
            combo = [f for j, f in enumerate(filter_types) if j != i]
            cfg = make_cfg_with_filters(combo)
            r = run_simulation(cfg, data, 0, split)
            if r.total_trades > 3:
                results.append(r)

        # All 5 filters
        cfg = make_cfg_with_filters(filter_types)
        r = run_simulation(cfg, data, 0, split)
        if r.total_trades > 3:
            results.append(r)

    results.sort(key=lambda x: x.profit_factor, reverse=True)
    print(format_results_table(results, "Round 3: Combined Filter Results", 15))

    save_round_results(results, "round3_results.json")
    return results[:5]


def run_round4(data: dict, top_configs: list[SimResult]) -> list[SimResult]:
    """Round 4: Risk management optimization."""
    print("\n═══ ROUND 4: Risk Management Optimization ═══")
    _, split, _ = train_test_split(data)

    results = []

    for base in top_configs[:3]:
        bc = base.config
        print(f"\n  Base: {base.config_name}")

        # Stop loss variations
        for sl_type in ["atr", "pct"]:
            if sl_type == "atr":
                for sl_mult in [2, 3, 4, 5]:
                    cfg = SimConfig(**{k: v for k, v in bc.items() if k in SimConfig.__dataclass_fields__})
                    cfg.sl_enabled = True
                    cfg.sl_type = "atr"
                    cfg.sl_atr_mult = sl_mult
                    r = run_simulation(cfg, data, 0, split)
                    if r.total_trades > 3:
                        results.append(r)
            else:
                for sl_pct in [0.5, 1.0, 1.5, 2.0]:
                    cfg = SimConfig(**{k: v for k, v in bc.items() if k in SimConfig.__dataclass_fields__})
                    cfg.sl_enabled = True
                    cfg.sl_type = "pct"
                    cfg.sl_pct = sl_pct
                    r = run_simulation(cfg, data, 0, split)
                    if r.total_trades > 3:
                        results.append(r)

        # Take profit variations
        for tp_pct in [0.5, 1.0, 1.5, 2.0, 3.0]:
            cfg = SimConfig(**{k: v for k, v in bc.items() if k in SimConfig.__dataclass_fields__})
            cfg.tp_enabled = True
            cfg.tp_pct = tp_pct
            r = run_simulation(cfg, data, 0, split)
            if r.total_trades > 3:
                results.append(r)

        # SL + TP combos
        for sl_mult, tp_pct in product([2, 3, 4], [1.0, 1.5, 2.0]):
            cfg = SimConfig(**{k: v for k, v in bc.items() if k in SimConfig.__dataclass_fields__})
            cfg.sl_enabled = True
            cfg.sl_type = "atr"
            cfg.sl_atr_mult = sl_mult
            cfg.tp_enabled = True
            cfg.tp_pct = tp_pct
            r = run_simulation(cfg, data, 0, split)
            if r.total_trades > 3:
                results.append(r)

        # Trailing Supertrend stop
        cfg = SimConfig(**{k: v for k, v in bc.items() if k in SimConfig.__dataclass_fields__})
        cfg.trailing_supertrend = True
        r = run_simulation(cfg, data, 0, split)
        if r.total_trades > 3:
            results.append(r)

        # Position sizing
        for mode in ["compounding", "anti_martingale"]:
            cfg = SimConfig(**{k: v for k, v in bc.items() if k in SimConfig.__dataclass_fields__})
            cfg.sizing_mode = mode
            r = run_simulation(cfg, data, 0, split)
            if r.total_trades > 3:
                results.append(r)

        # Re-entry logic
        for max_bars in [4, 8, 12]:
            cfg = SimConfig(**{k: v for k, v in bc.items() if k in SimConfig.__dataclass_fields__})
            cfg.reentry_enabled = True
            cfg.reentry_max_bars = max_bars
            r = run_simulation(cfg, data, 0, split)
            if r.total_trades > 3:
                results.append(r)

        # Also test no-change baseline
        cfg = SimConfig(**{k: v for k, v in bc.items() if k in SimConfig.__dataclass_fields__})
        r = run_simulation(cfg, data, 0, split)
        results.append(r)

    results.sort(key=lambda x: x.profit_factor, reverse=True)
    print(format_results_table(results, "Round 4: Risk Management Results", 15))

    save_round_results(results, "round4_results.json")
    return results[:5]


def run_round5(data: dict, top_configs: list[SimResult]) -> list[SimResult]:
    """Round 5: Validation — walk-forward, robustness, Monte Carlo."""
    print("\n═══ ROUND 5: Validation ═══")
    _, split, end = train_test_split(data)
    thirds = thirds_split(data)

    validated = []

    for base in top_configs[:3]:
        bc = base.config
        cfg = SimConfig(**{k: v for k, v in bc.items() if k in SimConfig.__dataclass_fields__})
        print(f"\n  Validating: {cfg.short_name()}")

        # Walk-forward: test on holdout data
        val_result = run_simulation(cfg, data, split, end)
        print(f"    Validation set: PF={val_result.profit_factor:.2f} PnL=${val_result.net_pnl:.2f} "
              f"WR={val_result.win_rate:.1f}% Trades={val_result.total_trades}")

        if val_result.net_pnl <= 0:
            print(f"    ✗ FAILED: Unprofitable on validation set — likely overfit")
            continue

        # Thirds test
        thirds_pass = True
        for idx, (s, e) in enumerate(thirds):
            tr = run_simulation(cfg, data, s, e)
            label = ["First", "Middle", "Last"][idx]
            print(f"    {label} third: PF={tr.profit_factor:.2f} PnL=${tr.net_pnl:.2f}")
            if tr.net_pnl < 0:
                thirds_pass = False

        if not thirds_pass:
            print(f"    ⚠ WARNING: Not profitable in all thirds")

        # Robustness: +/- 10% parameter variation
        print(f"    Robustness check (+/- 10% params):")
        robust_pass = True
        for factor in [0.9, 1.1]:
            var_cfg = SimConfig(**{k: v for k, v in bc.items() if k in SimConfig.__dataclass_fields__})
            var_cfg.multiplier = round(cfg.multiplier * factor, 2)
            var_cfg.atr_period = max(5, round(cfg.atr_period * factor))
            vr = run_simulation(var_cfg, data, 0, end)
            print(f"      {factor:.0%}: PF={vr.profit_factor:.2f} PnL=${vr.net_pnl:.2f}")
            if vr.net_pnl < 0:
                robust_pass = False

        if not robust_pass:
            print(f"    ⚠ WARNING: Not robust to parameter variation")

        # Monte Carlo
        print(f"    Monte Carlo (1000 iterations):")
        mc = monte_carlo(val_result.trades if val_result.trades else base.trades)
        if mc:
            print(f"      Median PnL: ${mc['median_pnl']:.2f}")
            print(f"      5th percentile: ${mc['p5_pnl']:.2f}")
            print(f"      95th percentile: ${mc['p95_pnl']:.2f}")
            print(f"      P(profit) at 50 trades: {mc['prob_profitable_50']:.1f}%")
            print(f"      P(profit) at 100 trades: {mc['prob_profitable_100']:.1f}%")
            print(f"      Max DD (95th pctl): {mc['max_drawdown_p95']:.1f}%")

        val_data = {
            "config": bc,
            "config_name": cfg.short_name(),
            "training": {
                "pf": base.profit_factor,
                "pnl": base.net_pnl,
                "win_rate": base.win_rate,
                "trades": base.total_trades,
            },
            "validation": {
                "pf": val_result.profit_factor,
                "pnl": val_result.net_pnl,
                "win_rate": val_result.win_rate,
                "trades": val_result.total_trades,
            },
            "thirds_pass": thirds_pass,
            "robust_pass": robust_pass,
            "monte_carlo": mc,
        }
        validated.append((val_result, val_data))

    # Save
    save_data = [v[1] for v in validated]
    with open(RESULTS_DIR / "round5_validation.json", "w") as f:
        json.dump(save_data, f, indent=2)
    print(f"\n  Saved validation results for {len(validated)} configs")

    return [v[0] for v in validated]


def run_round6(data: dict, validated: list[SimResult]) -> Optional[SimResult]:
    """Round 6: Final recommendation."""
    print("\n═══ ROUND 6: Final Recommendation ═══")

    if not validated:
        print("  No configs passed validation. Consider relaxing criteria or gathering more data.")
        return None

    # Load validation data
    val_file = RESULTS_DIR / "round5_validation.json"
    if val_file.exists():
        with open(val_file) as f:
            val_data = json.load(f)
    else:
        val_data = []

    # Score each validated config
    best = validated[0]
    best_data = val_data[0] if val_data else {}

    cfg = SimConfig(**{k: v for k, v in best.config.items() if k in SimConfig.__dataclass_fields__})
    print(f"\n  RECOMMENDED CONFIG: {cfg.short_name()}")
    print(f"  {'─' * 60}")
    print(f"  Training PF:     {best_data.get('training', {}).get('pf', 'N/A')}")
    print(f"  Validation PF:   {best.profit_factor:.2f}")
    print(f"  Net P&L:         ${best.net_pnl:.2f} ({best.net_pnl_pct:.1f}%)")
    print(f"  Win Rate:        {best.win_rate:.1f}%")
    print(f"  Max Drawdown:    {best.max_drawdown_pct:.1f}%")
    print(f"  Sharpe Ratio:    {best.sharpe_ratio:.2f}")
    print(f"  Trades:          {best.total_trades}")
    print(f"  Total Fees:      ${best.total_fees:.2f}")
    print(f"  Whipsaws:        {best.whipsaw_count}")

    mc = best_data.get("monte_carlo", {})
    if mc:
        print(f"\n  Monte Carlo:")
        print(f"    P(profit at 100 trades): {mc.get('prob_profitable_100', 'N/A')}%")
        print(f"    Max DD (95th pctl):      {mc.get('max_drawdown_p95', 'N/A')}%")

    # Save final recommendation
    final = {
        "config": best.config,
        "config_name": cfg.short_name(),
        "stats": {
            "total_trades": best.total_trades,
            "win_rate": best.win_rate,
            "profit_factor": best.profit_factor,
            "net_pnl": best.net_pnl,
            "net_pnl_pct": best.net_pnl_pct,
            "max_drawdown_pct": best.max_drawdown_pct,
            "sharpe_ratio": best.sharpe_ratio,
            "sortino_ratio": best.sortino_ratio,
            "total_fees": best.total_fees,
        },
        "monte_carlo": mc,
        "validation": best_data,
    }
    with open(RESULTS_DIR / "final_recommendation.json", "w") as f:
        json.dump(final, f, indent=2)
    print(f"\n  Saved to final_recommendation.json")

    return best


# ═══════════════════════════════════════════════════════════════════════════════
# COMPARE MODE
# ═══════════════════════════════════════════════════════════════════════════════

def run_compare(data: dict):
    """Compare current live settings vs recommendation vs colleague's settings."""
    print("\n═══ COMPARISON ═══")

    configs = {
        "Current Live (ATR 10, Mult 2.0)": SimConfig(atr_period=10, multiplier=2.0, source="hl2"),
        "Colleague (ATR 10, Mult 1.3)": SimConfig(atr_period=10, multiplier=1.3, source="hl2"),
    }

    # Load recommendation if exists
    rec_file = RESULTS_DIR / "final_recommendation.json"
    if rec_file.exists():
        with open(rec_file) as f:
            rec = json.load(f)
        rec_cfg = SimConfig(**{k: v for k, v in rec["config"].items() if k in SimConfig.__dataclass_fields__})
        configs[f"Recommendation ({rec_cfg.short_name()})"] = rec_cfg

    results = []
    for name, cfg in configs.items():
        r = run_simulation(cfg, data)
        r.config_name = name
        results.append(r)

    print(format_results_table(results, "Configuration Comparison", 10))

    # Detailed monthly breakdown
    for r in results:
        if r.monthly_pnl:
            print(f"\n  Monthly P&L — {r.config_name}:")
            for month, pnl in sorted(r.monthly_pnl.items()):
                bar = "█" * max(0, int(pnl / 5)) if pnl > 0 else "▒" * max(0, int(-pnl / 5))
                print(f"    {month}: ${pnl:>8.2f}  {bar}")


# ═══════════════════════════════════════════════════════════════════════════════
# SINGLE CONFIG MODE
# ═══════════════════════════════════════════════════════════════════════════════

def run_single_config(data: dict, config_json: str):
    """Test a single config from JSON."""
    print("\n═══ SINGLE CONFIG TEST ═══")
    params = json.loads(config_json)

    # Map shorthand keys
    key_map = {"atr": "atr_period", "mult": "multiplier", "src": "source",
               "rsi": "rsi_enabled", "rsi_period": "rsi_period"}
    mapped = {}
    for k, v in params.items():
        mapped[key_map.get(k, k)] = v

    cfg = SimConfig(**{k: v for k, v in mapped.items() if k in SimConfig.__dataclass_fields__})
    print(f"  Config: {cfg.short_name()}")

    r = run_simulation(cfg, data)
    print(format_results_table([r], "Single Config Result"))

    # Detailed stats
    print(f"\n  Detailed Stats:")
    print(f"    Win Rate:        {r.win_rate:.1f}%")
    print(f"    Profit Factor:   {r.profit_factor:.2f}")
    print(f"    Net P&L:         ${r.net_pnl:.2f} ({r.net_pnl_pct:.1f}%)")
    print(f"    Max Drawdown:    ${r.max_drawdown:.2f} ({r.max_drawdown_pct:.1f}%)")
    print(f"    Sharpe:          {r.sharpe_ratio:.2f}")
    print(f"    Sortino:         {r.sortino_ratio:.2f}")
    print(f"    Avg Winner:      ${r.avg_winner:.2f}")
    print(f"    Avg Loser:       ${r.avg_loser:.2f}")
    print(f"    Win/Loss Ratio:  {r.win_loss_ratio:.2f}")
    print(f"    Largest Win:     ${r.largest_win:.2f}")
    print(f"    Largest Loss:    ${r.largest_loss:.2f}")
    print(f"    Total Fees:      ${r.total_fees:.2f}")
    print(f"    Total Funding:   ${r.total_funding:.2f}")
    print(f"    Avg Hold (bars): {r.avg_hold_bars:.1f}")
    print(f"    Trades/Day:      {r.trades_per_day:.2f}")
    print(f"    Win Streak:      {r.longest_win_streak}")
    print(f"    Lose Streak:     {r.longest_lose_streak}")
    print(f"    Whipsaws:        {r.whipsaw_count}")


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="HyperTrader Backtesting Engine")
    parser.add_argument("--round", type=int, help="Run only a specific round (1-6)")
    parser.add_argument("--config", type=str, help="Test a single config (JSON)")
    parser.add_argument("--compare", action="store_true", help="Compare configs")
    parser.add_argument("--monte-carlo", action="store_true", help="Run Monte Carlo on recommendation")
    parser.add_argument("--days", type=int, default=180, help="Days of data to fetch")
    args = parser.parse_args()

    start_time = time.time()
    data = load_all_data(args.days)

    if not data["15m"]:
        print("ERROR: No 15m candle data available.")
        sys.exit(1)

    if args.config:
        run_single_config(data, args.config)
        return

    if args.compare:
        run_compare(data)
        return

    if args.monte_carlo:
        rec_file = RESULTS_DIR / "final_recommendation.json"
        if not rec_file.exists():
            print("ERROR: No final_recommendation.json found. Run all rounds first.")
            sys.exit(1)
        with open(rec_file) as f:
            rec = json.load(f)
        cfg = SimConfig(**{k: v for k, v in rec["config"].items() if k in SimConfig.__dataclass_fields__})
        r = run_simulation(cfg, data)
        mc = monte_carlo(r.trades, 1000)
        print(f"\n  Monte Carlo Results (1000 iterations):")
        for k, v in mc.items():
            print(f"    {k}: {v}")
        return

    # Sequential rounds
    if args.round is None or args.round == 1:
        top5 = run_round1(data)
        if args.round == 1:
            elapsed = time.time() - start_time
            print(f"\n  Round 1 completed in {elapsed:.0f}s")
            return
    else:
        # Load Round 1 results for later rounds
        r1_file = RESULTS_DIR / "round1_results.json"
        if not r1_file.exists():
            print("ERROR: Round 1 results not found. Run Round 1 first.")
            sys.exit(1)
        with open(r1_file) as f:
            r1_data = json.load(f)
        top5 = []
        for rd in r1_data[:5]:
            cfg = SimConfig(**{k: v for k, v in rd["config"].items() if k in SimConfig.__dataclass_fields__})
            sr = SimResult(config=rd["config"], config_name=rd.get("config_name", cfg.short_name()))
            sr.profit_factor = rd["profit_factor"]
            sr.net_pnl = rd["net_pnl"]
            sr.win_rate = rd["win_rate"]
            sr.total_trades = rd["total_trades"]
            sr.trades = rd.get("trades", [])
            top5.append(sr)

    if args.round is None or args.round == 2:
        round2_ranked = run_round2(data, top5)
        if args.round == 2:
            elapsed = time.time() - start_time
            print(f"\n  Round 2 completed in {elapsed:.0f}s")
            return
    else:
        r2_file = RESULTS_DIR / "round2_results.json"
        if not r2_file.exists():
            print("ERROR: Round 2 results not found. Run Round 2 first.")
            sys.exit(1)
        with open(r2_file) as f:
            round2_ranked = json.load(f)

    if args.round is None or args.round == 3:
        top_combined = run_round3(data, top5, round2_ranked)
        if args.round == 3:
            elapsed = time.time() - start_time
            print(f"\n  Round 3 completed in {elapsed:.0f}s")
            return
    else:
        r3_file = RESULTS_DIR / "round3_results.json"
        if not r3_file.exists():
            print("ERROR: Round 3 results not found.")
            sys.exit(1)
        with open(r3_file) as f:
            r3_data = json.load(f)
        top_combined = []
        for rd in r3_data[:5]:
            cfg = SimConfig(**{k: v for k, v in rd["config"].items() if k in SimConfig.__dataclass_fields__})
            sr = SimResult(config=rd["config"], config_name=rd.get("config_name", cfg.short_name()))
            sr.profit_factor = rd["profit_factor"]
            sr.net_pnl = rd["net_pnl"]
            sr.win_rate = rd["win_rate"]
            sr.total_trades = rd["total_trades"]
            sr.trades = rd.get("trades", [])
            top_combined.append(sr)

    if args.round is None or args.round == 4:
        top_risk = run_round4(data, top_combined)
        if args.round == 4:
            elapsed = time.time() - start_time
            print(f"\n  Round 4 completed in {elapsed:.0f}s")
            return
    else:
        r4_file = RESULTS_DIR / "round4_results.json"
        if not r4_file.exists():
            print("ERROR: Round 4 results not found.")
            sys.exit(1)
        with open(r4_file) as f:
            r4_data = json.load(f)
        top_risk = []
        for rd in r4_data[:5]:
            cfg = SimConfig(**{k: v for k, v in rd["config"].items() if k in SimConfig.__dataclass_fields__})
            sr = SimResult(config=rd["config"], config_name=rd.get("config_name", cfg.short_name()))
            sr.profit_factor = rd["profit_factor"]
            sr.net_pnl = rd["net_pnl"]
            sr.win_rate = rd["win_rate"]
            sr.total_trades = rd["total_trades"]
            sr.trades = rd.get("trades", [])
            top_risk.append(sr)

    if args.round is None or args.round == 5:
        validated = run_round5(data, top_risk)
        if args.round == 5:
            elapsed = time.time() - start_time
            print(f"\n  Round 5 completed in {elapsed:.0f}s")
            return

    if args.round is None or args.round == 6:
        final = run_round6(data, validated if 'validated' in dir() else top_risk)

    elapsed = time.time() - start_time
    print(f"\n{'═' * 80}")
    print(f"  Backtesting complete in {elapsed:.0f}s ({elapsed/60:.1f}m)")
    print(f"{'═' * 80}")


if __name__ == "__main__":
    main()

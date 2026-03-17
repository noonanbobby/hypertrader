#!/usr/bin/env python3
"""
Three advanced strategy tests: multi-asset, conviction sizing, regime adaptation.
"""

import json
import time
import numpy as np
from pathlib import Path
from datetime import datetime, timezone
import requests

DATA_DIR = Path(__file__).parent.parent / "backtest-data"
OUTPUT_DIR = Path(__file__).parent

import sys
sys.path.insert(0, str(Path(__file__).parent))
from engine import calc_supertrend, calc_sma, calc_atr, calc_tr, calc_atr_rma


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


def fetch_binance_klines(symbol, interval, limit_days=730):
    url = "https://api.binance.com/api/v3/klines"
    interval_ms = {"15m": 15*60*1000, "1h": 60*60*1000}[interval]
    end_time = int(time.time() * 1000)
    start_time = end_time - (limit_days * 24 * 60 * 60 * 1000)
    all_klines = []
    current_start = start_time
    while current_start < end_time:
        resp = requests.get(url, params={"symbol": symbol, "interval": interval, "startTime": current_start, "limit": 1000}, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        if not data:
            break
        for k in data:
            all_klines.append({"open_time": k[0], "open": float(k[1]), "high": float(k[2]),
                               "low": float(k[3]), "close": float(k[4]), "volume": float(k[5])})
        current_start = data[-1][0] + interval_ms
        time.sleep(0.1)
    return all_klines


def calc_adx(highs, lows, closes, period=14):
    n = len(closes)
    adx = np.full(n, np.nan)
    if n < period * 2 + 1:
        return adx
    plus_dm = np.zeros(n)
    minus_dm = np.zeros(n)
    for i in range(1, n):
        up = highs[i] - highs[i-1]
        down = lows[i-1] - lows[i]
        if up > down and up > 0: plus_dm[i] = up
        if down > up and down > 0: minus_dm[i] = down
    tr = calc_tr(highs, lows, closes)
    def rma(data, p):
        out = np.full(len(data), np.nan)
        out[p] = np.sum(data[1:p+1])
        for i in range(p+1, len(data)):
            out[i] = out[i-1] - out[i-1]/p + data[i]
        return out
    s_tr = rma(tr, period)
    s_pdm = rma(plus_dm, period)
    s_mdm = rma(minus_dm, period)
    pdi = np.full(n, np.nan)
    mdi = np.full(n, np.nan)
    dx = np.full(n, np.nan)
    for i in range(period, n):
        if s_tr[i] and not np.isnan(s_tr[i]) and s_tr[i] > 0:
            pdi[i] = 100 * s_pdm[i] / s_tr[i]
            mdi[i] = 100 * s_mdm[i] / s_tr[i]
            s = pdi[i] + mdi[i]
            if s > 0:
                dx[i] = 100 * abs(pdi[i] - mdi[i]) / s
    fv = period
    while fv < n and np.isnan(dx[fv]): fv += 1
    if fv + period >= n: return adx
    adx[fv + period - 1] = np.nanmean(dx[fv:fv+period])
    for i in range(fv + period, n):
        if not np.isnan(dx[i]) and not np.isnan(adx[i-1]):
            adx[i] = (adx[i-1] * (period - 1) + dx[i]) / period
    return adx


def run_mtf_fixed(data_15m, data_1h, entry_atr, entry_mult, entry_src,
                  confirm_atr, confirm_mult, confirm_src,
                  start_bar, end_bar, fixed_size=125.0, leverage=10.0,
                  taker_fee=0.00045, slippage=0.0001, starting_capital=500.0,
                  adx_sizing=None, adx_values=None):
    """
    MTF backtest with fixed sizing.
    adx_sizing: if set, dict with {"strong": size, "moderate": size, "weak": size}
    adx_values: precomputed ADX array (same length as data_15m)
    """
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
    position_size = 0.0
    entry_bar_idx = 0
    trades = []
    equity_curve = []
    pending = None

    def get_size(bar_idx):
        if adx_sizing and adx_values is not None and bar_idx < len(adx_values) and not np.isnan(adx_values[bar_idx]):
            a = adx_values[bar_idx]
            if a >= 30: return adx_sizing["strong"] * leverage
            elif a >= 20: return adx_sizing["moderate"] * leverage
            else: return adx_sizing["weak"] * leverage
        return fixed_size * leverage

    for i in range(start_bar, n):
        if pending is not None and i > start_bar:
            action = pending
            pending = None
            exec_price = o[i]
            if action == "close" and position != 0:
                fill = exec_price - exec_price * slippage * position
                pnl_raw = (fill - entry_price) * position * (position_size / entry_price)
                fee = position_size * taker_fee
                trades.append({"pnl_before_fees": pnl_raw, "fee": fee, "pnl": pnl_raw - fee,
                               "direction": position, "entry_price": entry_price, "exit_price": fill,
                               "entry_time": int(ts[entry_bar_idx]), "exit_time": int(ts[i]),
                               "bars_held": i - entry_bar_idx, "size_usd": position_size})
                equity += pnl_raw - fee
                position = 0
                position_size = 0.0
            elif action.startswith("open") or action.startswith("flip"):
                if position != 0:
                    fill_close = exec_price - exec_price * slippage * position
                    pnl_raw = (fill_close - entry_price) * position * (position_size / entry_price)
                    fee = position_size * taker_fee
                    trades.append({"pnl_before_fees": pnl_raw, "fee": fee, "pnl": pnl_raw - fee,
                                   "direction": position, "entry_price": entry_price, "exit_price": fill_close,
                                   "entry_time": int(ts[entry_bar_idx]), "exit_time": int(ts[i]),
                                   "bars_held": i - entry_bar_idx, "size_usd": position_size})
                    equity += pnl_raw - fee
                new_dir = 1 if "long" in action else -1
                fill_open = exec_price + exec_price * slippage * new_dir
                position_size = get_size(i)
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
            if position != 0: pending = "close"
            continue
        if np.isnan(st_dir[i]) or np.isnan(st_dir[i-1]):
            continue
        if st_dir[i] == st_dir[i-1]:
            continue
        new_dir = 1 if st_dir[i] == 1 else -1
        if htf_dir[i] != new_dir:
            if position != 0: pending = "close"
            continue
        if position == 0:
            pending = "open_long" if new_dir == 1 else "open_short"
        elif position != new_dir:
            pending = "flip_long" if new_dir == 1 else "flip_short"

    if pending == "close" and position != 0:
        fill = c[n-1] * (1 - slippage * position)
        pnl_raw = (fill - entry_price) * position * (position_size / entry_price)
        fee = position_size * taker_fee
        trades.append({"pnl_before_fees": pnl_raw, "fee": fee, "pnl": pnl_raw - fee,
                       "direction": position, "entry_price": entry_price, "exit_price": fill,
                       "entry_time": int(ts[entry_bar_idx]), "exit_time": int(ts[n-1]),
                       "bars_held": n - 1 - entry_bar_idx, "size_usd": position_size})
        equity += pnl_raw - fee

    return trades, equity_curve, equity


def run_regime_adaptive(data_15m, data_1h, adx_values,
                        fast_atr, fast_mult, fast_src,
                        slow_atr, slow_mult, slow_src,
                        confirm_atr, confirm_mult, confirm_src,
                        trending_threshold=25, ranging_threshold=20,
                        start_bar=200, end_bar=-1,
                        fixed_size=125.0, leverage=10.0,
                        taker_fee=0.00045, slippage=0.0001,
                        starting_capital=500.0):
    """Regime-adaptive: switches between fast and slow Supertrend based on ADX."""
    d = data_15m
    n = end_bar if end_bar > 0 else d["n"]

    _, h_dirs = calc_supertrend(data_1h["highs"], data_1h["lows"], data_1h["closes"],
                                 confirm_atr, confirm_mult, confirm_src)
    h_ts = data_1h["timestamps"]
    htf_dir = np.ones(n)
    h_idx = 0
    for i in range(n):
        while h_idx < len(h_ts) - 1 and h_ts[h_idx + 1] <= d["timestamps"][i]:
            h_idx += 1
        if h_idx < len(h_dirs): htf_dir[i] = h_dirs[h_idx]

    o, h, l, c, v, ts = (d["opens"][:n], d["highs"][:n], d["lows"][:n],
                          d["closes"][:n], d["volumes"][:n], d["timestamps"][:n])

    # Pre-compute both ST variants
    st_fast_line, st_fast_dir = calc_supertrend(h, l, c, fast_atr, fast_mult, fast_src)
    st_slow_line, st_slow_dir = calc_supertrend(h, l, c, slow_atr, slow_mult, slow_src)

    # Build composite direction: use fast in trending, slow in ranging, either in neutral
    composite_dir = np.full(n, np.nan)
    regime_used = np.full(n, 0)  # 0=nan, 1=fast, 2=slow
    for i in range(n):
        if np.isnan(adx_values[i]):
            composite_dir[i] = st_slow_dir[i]
            regime_used[i] = 2
        elif adx_values[i] >= trending_threshold:
            composite_dir[i] = st_fast_dir[i]
            regime_used[i] = 1
        elif adx_values[i] < ranging_threshold:
            composite_dir[i] = st_slow_dir[i]
            regime_used[i] = 2
        else:
            # Neutral: use slow (more conservative)
            composite_dir[i] = st_slow_dir[i]
            regime_used[i] = 2

    position_size = fixed_size * leverage
    equity = starting_capital
    position = 0
    entry_price = 0.0
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
                trades.append({"pnl": pnl_raw - fee, "pnl_before_fees": pnl_raw, "fee": fee,
                               "direction": position, "entry_price": entry_price, "exit_price": fill,
                               "entry_time": int(ts[entry_bar_idx]), "exit_time": int(ts[i]),
                               "bars_held": i - entry_bar_idx, "regime": int(regime_used[entry_bar_idx])})
                equity += pnl_raw - fee
                position = 0
            elif action.startswith("open") or action.startswith("flip"):
                if position != 0:
                    fill_close = exec_price - exec_price * slippage * position
                    pnl_raw = (fill_close - entry_price) * position * (position_size / entry_price)
                    fee = position_size * taker_fee
                    trades.append({"pnl": pnl_raw - fee, "pnl_before_fees": pnl_raw, "fee": fee,
                                   "direction": position, "entry_price": entry_price, "exit_price": fill_close,
                                   "entry_time": int(ts[entry_bar_idx]), "exit_time": int(ts[i]),
                                   "bars_held": i - entry_bar_idx, "regime": int(regime_used[entry_bar_idx])})
                    equity += pnl_raw - fee
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
            if position != 0: pending = "close"
            continue
        if np.isnan(composite_dir[i]) or np.isnan(composite_dir[i-1]):
            continue
        if composite_dir[i] == composite_dir[i-1]:
            continue
        new_dir = 1 if composite_dir[i] == 1 else -1
        if htf_dir[i] != new_dir:
            if position != 0: pending = "close"
            continue
        if position == 0:
            pending = "open_long" if new_dir == 1 else "open_short"
        elif position != new_dir:
            pending = "flip_long" if new_dir == 1 else "flip_short"

    if pending == "close" and position != 0:
        fill = c[n-1] * (1 - slippage * position)
        pnl_raw = (fill - entry_price) * position * (position_size / entry_price)
        fee = position_size * taker_fee
        trades.append({"pnl": pnl_raw - fee, "pnl_before_fees": pnl_raw, "fee": fee,
                       "direction": position, "entry_price": entry_price, "exit_price": fill,
                       "entry_time": int(ts[entry_bar_idx]), "exit_time": int(ts[n-1]),
                       "bars_held": n - 1 - entry_bar_idx, "regime": int(regime_used[entry_bar_idx])})
        equity += pnl_raw - fee

    return trades, equity_curve, equity


def stats(trades, starting=500.0, equity_curve=None):
    if not trades:
        return {"trades": 0, "pnl": 0, "win_rate": 0, "pf": 0, "max_dd": 0, "fees": 0}
    pnl = sum(t["pnl"] for t in trades)
    wins = [t for t in trades if t["pnl"] > 0]
    losses = [t for t in trades if t["pnl"] <= 0]
    gp = sum(t["pnl"] for t in wins)
    gl = abs(sum(t["pnl"] for t in losses))
    pf = gp / gl if gl > 0 else 9999
    fees = sum(t["fee"] for t in trades)
    max_dd = 0
    if equity_curve:
        ec = np.array(equity_curve)
        peak = np.maximum.accumulate(ec)
        dd = (peak - ec) / peak * 100
        max_dd = float(np.max(dd))
    return {
        "trades": len(trades), "pnl": round(pnl, 2), "pnl_pct": round(pnl/starting*100, 1),
        "win_rate": round(len(wins)/len(trades)*100, 1), "pf": round(pf, 2),
        "max_dd": round(max_dd, 1), "fees": round(fees, 2),
        "avg_pnl": round(pnl/len(trades), 2),
    }


def main():
    t0 = time.time()
    print("=" * 100)
    print("ADVANCED STRATEGY TESTS")
    print("=" * 100)

    # Load BTC data
    btc_15m = load_klines("binance_btc_15m.json")
    btc_1h = load_klines("binance_btc_1h.json")
    n_btc = btc_15m["n"]
    warmup = 200

    # ═══════════════════════════════════════════════════════════
    # 1. MULTI-ASSET DIVERSIFICATION
    # ═══════════════════════════════════════════════════════════
    print(f"\n{'='*100}")
    print("1. MULTI-ASSET DIVERSIFICATION — BTC + ETH + SOL")
    print(f"{'='*100}")

    # Fetch ETH and SOL data
    assets = {"BTC": {"15m": "binance_btc_15m.json", "1h": "binance_btc_1h.json"}}

    for symbol, label in [("ETHUSDT", "ETH"), ("SOLUSDT", "SOL")]:
        f15 = DATA_DIR / f"binance_{label.lower()}_15m.json"
        f1h = DATA_DIR / f"binance_{label.lower()}_1h.json"

        if f15.exists():
            print(f"  {label} 15m: loading cached data...")
        else:
            print(f"  {label} 15m: fetching from Binance...")
            klines = fetch_binance_klines(symbol, "15m", 730)
            with open(f15, "w") as f:
                json.dump(klines, f)
            print(f"    Got {len(klines)} candles")

        if f1h.exists():
            print(f"  {label} 1h: loading cached data...")
        else:
            print(f"  {label} 1h: fetching from Binance...")
            klines = fetch_binance_klines(symbol, "1h", 730)
            with open(f1h, "w") as f:
                json.dump(klines, f)
            print(f"    Got {len(klines)} candles")

        assets[label] = {"15m": f"binance_{label.lower()}_15m.json", "1h": f"binance_{label.lower()}_1h.json"}

    # Run Pure MTF on each asset individually ($125/trade)
    print(f"\n  Running Pure MTF on each asset ($125/trade, taker fees)...")
    individual_results = {}

    for asset_name, files in assets.items():
        d15 = load_klines(files["15m"])
        d1h = load_klines(files["1h"])
        trades, ec, eq = run_mtf_fixed(d15, d1h, 8, 4.0, "hlc3", 10, 4.0, "close",
                                        start_bar=warmup, end_bar=d15["n"])
        s = stats(trades, equity_curve=ec)
        individual_results[asset_name] = {"trades": trades, "ec": ec, "eq": eq, "stats": s}
        print(f"    {asset_name}: {s['trades']} trades, P&L ${s['pnl']:.0f} ({s['pnl_pct']:.1f}%), "
              f"PF={s['pf']:.2f}, Win={s['win_rate']:.1f}%, MDD={s['max_dd']:.1f}%")

    # Combined portfolio: $42/trade per asset ($125 total split 3 ways)
    # Re-run with $42 sizing
    print(f"\n  Running diversified portfolio ($42/trade per asset, $125 total)...")
    portfolio_trades_all = []
    portfolio_equity_curves = {}

    for asset_name, files in assets.items():
        d15 = load_klines(files["15m"])
        d1h = load_klines(files["1h"])
        trades, ec, eq = run_mtf_fixed(d15, d1h, 8, 4.0, "hlc3", 10, 4.0, "close",
                                        start_bar=warmup, end_bar=d15["n"],
                                        fixed_size=42.0, starting_capital=167.0)
        portfolio_equity_curves[asset_name] = ec
        for t in trades:
            t["asset"] = asset_name
        portfolio_trades_all.extend(trades)

    # Combine equity curves (sum of all three)
    # Align by length (use shortest)
    min_len = min(len(ec) for ec in portfolio_equity_curves.values())
    combined_ec = np.zeros(min_len)
    for asset_name, ec in portfolio_equity_curves.items():
        combined_ec += np.array(ec[:min_len])

    combined_pnl = float(combined_ec[-1]) - 500.0
    combined_peak = np.maximum.accumulate(combined_ec)
    combined_dd = (combined_peak - combined_ec) / combined_peak * 100
    combined_max_dd = float(np.max(combined_dd))

    portfolio_trades_all.sort(key=lambda t: t.get("entry_time", 0))
    p_wins = sum(1 for t in portfolio_trades_all if t["pnl"] > 0)
    p_gp = sum(t["pnl"] for t in portfolio_trades_all if t["pnl"] > 0)
    p_gl = abs(sum(t["pnl"] for t in portfolio_trades_all if t["pnl"] <= 0))
    p_pf = p_gp / p_gl if p_gl > 0 else 9999
    p_fees = sum(t["fee"] for t in portfolio_trades_all)

    print(f"\n  COMPARISON:")
    print(f"  {'Config':>30s} | {'Trades':>6s} {'P&L $':>8s} {'P&L %':>7s} {'PF':>6s} {'Win%':>6s} {'MDD%':>6s} {'Fees':>8s}")
    print(f"  {'─'*30} | {'─'*6} {'─'*8} {'─'*7} {'─'*6} {'─'*6} {'─'*6} {'─'*8}")

    btc_s = individual_results["BTC"]["stats"]
    print(f"  {'BTC only ($125/trade)':>30s} | {btc_s['trades']:>6d} ${btc_s['pnl']:>7.0f} {btc_s['pnl_pct']:>6.1f}% "
          f"{btc_s['pf']:>6.2f} {btc_s['win_rate']:>5.1f}% {btc_s['max_dd']:>5.1f}% ${btc_s['fees']:>7.0f}")

    for asset in ["ETH", "SOL"]:
        s = individual_results[asset]["stats"]
        print(f"  {f'{asset} only ($125/trade)':>30s} | {s['trades']:>6d} ${s['pnl']:>7.0f} {s['pnl_pct']:>6.1f}% "
              f"{s['pf']:>6.2f} {s['win_rate']:>5.1f}% {s['max_dd']:>5.1f}% ${s['fees']:>7.0f}")

    print(f"  {'PORTFOLIO ($42 x 3 assets)':>30s} | {len(portfolio_trades_all):>6d} ${combined_pnl:>7.0f} {combined_pnl/500*100:>6.1f}% "
          f"{p_pf:>6.2f} {p_wins/len(portfolio_trades_all)*100:>5.1f}% {combined_max_dd:>5.1f}% ${p_fees:>7.0f}")

    # Correlation analysis
    print(f"\n  Trade timing overlap (do assets trade at the same time?):")
    for a1 in ["BTC", "ETH", "SOL"]:
        for a2 in ["BTC", "ETH", "SOL"]:
            if a1 >= a2: continue
            t1_times = set()
            for t in individual_results[a1]["trades"]:
                for bar in range(t.get("entry_time", 0), t.get("exit_time", 0), 15*60*1000):
                    t1_times.add(bar // (60*60*1000))  # hourly buckets
            t2_times = set()
            for t in individual_results[a2]["trades"]:
                for bar in range(t.get("entry_time", 0), t.get("exit_time", 0), 15*60*1000):
                    t2_times.add(bar // (60*60*1000))
            if t1_times and t2_times:
                overlap = len(t1_times & t2_times) / len(t1_times | t2_times) * 100
                print(f"    {a1}-{a2} position overlap: {overlap:.0f}%")

    # ═══════════════════════════════════════════════════════════
    # 2. CONVICTION SIZING
    # ═══════════════════════════════════════════════════════════
    print(f"\n{'='*100}")
    print("2. CONVICTION SIZING — Size by ADX trend strength")
    print(f"{'='*100}")

    adx_btc = calc_adx(btc_15m["highs"], btc_15m["lows"], btc_15m["closes"], 14)

    # Flat baseline
    trades_flat, ec_flat, eq_flat = run_mtf_fixed(
        btc_15m, btc_1h, 8, 4.0, "hlc3", 10, 4.0, "close",
        start_bar=warmup, end_bar=n_btc, fixed_size=125.0)
    s_flat = stats(trades_flat, equity_curve=ec_flat)

    # Conviction sizing variants
    sizing_variants = [
        ("Flat $125", None),
        ("ADX: $175/$125/$75", {"strong": 175, "moderate": 125, "weak": 75}),
        ("ADX: $200/$125/$50", {"strong": 200, "moderate": 125, "weak": 50}),
        ("ADX: $175/$125/$0 (skip ranging)", {"strong": 175, "moderate": 125, "weak": 0}),
        ("ADX: $250/$125/$0 (aggressive)", {"strong": 250, "moderate": 125, "weak": 0}),
    ]

    print(f"\n  ADX distribution in BTC 15m data:")
    valid_adx = adx_btc[~np.isnan(adx_btc)]
    print(f"    Strong (>=30): {np.sum(valid_adx >= 30)/len(valid_adx)*100:.1f}%")
    print(f"    Moderate (20-30): {np.sum((valid_adx >= 20) & (valid_adx < 30))/len(valid_adx)*100:.1f}%")
    print(f"    Weak (<20): {np.sum(valid_adx < 20)/len(valid_adx)*100:.1f}%")

    print(f"\n  {'Config':>35s} | {'Trades':>6s} {'P&L $':>8s} {'P&L %':>7s} {'PF':>6s} {'Win%':>6s} {'MDD%':>6s} {'AvgSize':>8s}")
    print(f"  {'─'*35} | {'─'*6} {'─'*8} {'─'*7} {'─'*6} {'─'*6} {'─'*6} {'─'*8}")

    for label, sizing in sizing_variants:
        if sizing is None:
            trades_v, ec_v, eq_v = trades_flat, ec_flat, eq_flat
            s = s_flat
            avg_size = 125.0
        else:
            # Handle $0 sizing (skip) by using very small size
            actual_sizing = {}
            for k, v in sizing.items():
                actual_sizing[k] = max(v, 0.01)  # near-zero instead of zero

            trades_v, ec_v, eq_v = run_mtf_fixed(
                btc_15m, btc_1h, 8, 4.0, "hlc3", 10, 4.0, "close",
                start_bar=warmup, end_bar=n_btc,
                adx_sizing=actual_sizing, adx_values=adx_btc)
            s = stats(trades_v, equity_curve=ec_v)

            # Filter out near-zero trades for stats
            if sizing.get("weak", 125) == 0:
                real_trades = [t for t in trades_v if t.get("size_usd", 0) > 10]
                s_real = stats(real_trades, equity_curve=ec_v)
                s["pnl"] = s_real["pnl"]
                s["pnl_pct"] = s_real["pnl_pct"]
                s["pf"] = s_real["pf"]
                s["trades"] = s_real["trades"]
                s["win_rate"] = s_real["win_rate"]

            avg_size = np.mean([t.get("size_usd", 1250) / 10 for t in trades_v])

        print(f"  {label:>35s} | {s['trades']:>6d} ${s['pnl']:>7.0f} {s['pnl_pct']:>6.1f}% "
              f"{s['pf']:>6.2f} {s['win_rate']:>5.1f}% {s['max_dd']:>5.1f}% ${avg_size:>7.0f}")

    # Breakdown by ADX regime for conviction sizing
    print(f"\n  Regime breakdown for ADX $175/$125/$75:")
    trades_conv, _, _ = run_mtf_fixed(
        btc_15m, btc_1h, 8, 4.0, "hlc3", 10, 4.0, "close",
        start_bar=warmup, end_bar=n_btc,
        adx_sizing={"strong": 175, "moderate": 125, "weak": 75}, adx_values=adx_btc)

    for regime_label, size_range in [("Strong (ADX>=30, $175)", (1700, 1800)),
                                      ("Moderate (ADX 20-30, $125)", (1200, 1300)),
                                      ("Weak (ADX<20, $75)", (700, 800))]:
        regime_trades = [t for t in trades_conv if size_range[0] <= t.get("size_usd", 0) <= size_range[1]]
        if regime_trades:
            r_pnl = sum(t["pnl"] for t in regime_trades)
            r_wins = sum(1 for t in regime_trades if t["pnl"] > 0)
            r_gp = sum(t["pnl"] for t in regime_trades if t["pnl"] > 0)
            r_gl = abs(sum(t["pnl"] for t in regime_trades if t["pnl"] <= 0))
            r_pf = r_gp / r_gl if r_gl > 0 else 9999
            print(f"    {regime_label}: {len(regime_trades)} trades, P&L ${r_pnl:.0f}, "
                  f"PF={r_pf:.2f}, Win={r_wins/len(regime_trades)*100:.1f}%")

    # ═════════════════════════════════════════════════════════
    # 3. REGIME ADAPTATION
    # ═══════════════════════════════════════════════════════════
    print(f"\n{'='*100}")
    print("3. REGIME ADAPTATION — Fast ST in trends, Slow ST in ranges")
    print(f"{'='*100}")

    # Test grid of fast/slow parameter pairs
    fast_params = [
        (8, 2.5, "hlc3"),  # faster: lower multiplier
        (8, 3.0, "hlc3"),
        (7, 2.5, "close"),
        (7, 3.0, "close"),
        (8, 2.0, "hlc3"),
    ]
    slow_params = [
        (8, 4.0, "hlc3"),   # our current (baseline)
        (10, 4.0, "close"),
        (8, 5.0, "hlc3"),
        (10, 5.0, "close"),
        (12, 4.0, "close"),
        (12, 5.0, "hlc3"),
    ]

    # Baseline: single ST(8, 4.0, hlc3) for reference
    print(f"\n  Baseline (single ST): P&L ${s_flat['pnl']:.0f}, PF={s_flat['pf']:.2f}, "
          f"Trades={s_flat['trades']}, MDD={s_flat['max_dd']:.1f}%")

    print(f"\n  Testing {len(fast_params)} x {len(slow_params)} = {len(fast_params)*len(slow_params)} fast/slow combos...")

    regime_results = []
    for fa, fm, fs in fast_params:
        for sa, sm, ss in slow_params:
            if fm >= sm:
                continue  # fast mult should be < slow mult

            trades_r, ec_r, eq_r = run_regime_adaptive(
                btc_15m, btc_1h, adx_btc,
                fa, fm, fs, sa, sm, ss,
                10, 4.0, "close",
                start_bar=warmup, end_bar=n_btc)
            s_r = stats(trades_r, equity_curve=ec_r)

            regime_results.append({
                "fast": f"ST({fa},{fm},{fs})",
                "slow": f"ST({sa},{sm},{ss})",
                "stats": s_r,
            })

    regime_results.sort(key=lambda r: r["stats"]["pf"], reverse=True)

    print(f"\n  TOP 10 REGIME-ADAPTIVE CONFIGS (by PF):")
    print(f"  {'Fast (trending)':>20s} {'Slow (ranging)':>20s} | {'Trades':>6s} {'P&L $':>8s} {'P&L %':>7s} {'PF':>6s} {'Win%':>6s} {'MDD%':>6s}")
    print(f"  {'─'*20} {'─'*20} | {'─'*6} {'─'*8} {'─'*7} {'─'*6} {'─'*6} {'─'*6}")

    for r in regime_results[:10]:
        s = r["stats"]
        print(f"  {r['fast']:>20s} {r['slow']:>20s} | {s['trades']:>6d} ${s['pnl']:>7.0f} {s['pnl_pct']:>6.1f}% "
              f"{s['pf']:>6.2f} {s['win_rate']:>5.1f}% {s['max_dd']:>5.1f}%")

    # Best regime-adaptive vs baseline
    best_regime = regime_results[0] if regime_results else None

    if best_regime:
        print(f"\n  BEST REGIME-ADAPTIVE: {best_regime['fast']} (trending) / {best_regime['slow']} (ranging)")
        bs = best_regime["stats"]
        print(f"    P&L: ${bs['pnl']:.0f} vs baseline ${s_flat['pnl']:.0f} (diff ${bs['pnl'] - s_flat['pnl']:.0f})")
        print(f"    PF: {bs['pf']:.2f} vs baseline {s_flat['pf']:.2f}")
        print(f"    Trades: {bs['trades']} vs baseline {s_flat['trades']}")
        print(f"    MDD: {bs['max_dd']:.1f}% vs baseline {s_flat['max_dd']:.1f}%")

        # Regime breakdown for best
        best_fast = fast_params[0]  # approximate; find actual
        for fa, fm, fs in fast_params:
            if f"ST({fa},{fm},{fs})" == best_regime["fast"]:
                best_fast = (fa, fm, fs)
                break
        best_slow = slow_params[0]
        for sa, sm, ss in slow_params:
            if f"ST({sa},{sm},{ss})" == best_regime["slow"]:
                best_slow = (sa, sm, ss)
                break

        trades_best_r, _, _ = run_regime_adaptive(
            btc_15m, btc_1h, adx_btc,
            *best_fast, *best_slow,
            10, 4.0, "close",
            start_bar=warmup, end_bar=n_btc)

        fast_trades = [t for t in trades_best_r if t.get("regime") == 1]
        slow_trades = [t for t in trades_best_r if t.get("regime") == 2]
        print(f"\n    Fast ST trades (trending): {len(fast_trades)}, P&L ${sum(t['pnl'] for t in fast_trades):.0f}")
        print(f"    Slow ST trades (ranging):  {len(slow_trades)}, P&L ${sum(t['pnl'] for t in slow_trades):.0f}")

    # ═══════════════════════════════════════════════════════════
    # FINAL COMPARISON
    # ═══════════════════════════════════════════════════════════
    print(f"\n{'='*100}")
    print("FINAL COMPARISON — ALL STRATEGIES")
    print(f"{'='*100}")

    print(f"\n  {'Strategy':>40s} | {'Trades':>6s} {'P&L $':>8s} {'P&L %':>7s} {'PF':>6s} {'Win%':>6s} {'MDD%':>6s}")
    print(f"  {'─'*40} | {'─'*6} {'─'*8} {'─'*7} {'─'*6} {'─'*6} {'─'*6}")

    # Baseline
    print(f"  {'Pure MTF BTC $125 (baseline)':>40s} | {s_flat['trades']:>6d} ${s_flat['pnl']:>7.0f} {s_flat['pnl_pct']:>6.1f}% "
          f"{s_flat['pf']:>6.2f} {s_flat['win_rate']:>5.1f}% {s_flat['max_dd']:>5.1f}%")

    # Portfolio
    print(f"  {'Portfolio BTC+ETH+SOL ($42 x 3)':>40s} | {len(portfolio_trades_all):>6d} ${combined_pnl:>7.0f} {combined_pnl/500*100:>6.1f}% "
          f"{p_pf:>6.2f} {p_wins/len(portfolio_trades_all)*100:>5.1f}% {combined_max_dd:>5.1f}%")

    # Individual assets
    for asset in ["ETH", "SOL"]:
        s = individual_results[asset]["stats"]
        print(f"  {f'{asset} only $125':>40s} | {s['trades']:>6d} ${s['pnl']:>7.0f} {s['pnl_pct']:>6.1f}% "
              f"{s['pf']:>6.2f} {s['win_rate']:>5.1f}% {s['max_dd']:>5.1f}%")

    # Conviction best
    # Re-run conviction best for clean stats
    trades_conv_best, ec_conv_best, _ = run_mtf_fixed(
        btc_15m, btc_1h, 8, 4.0, "hlc3", 10, 4.0, "close",
        start_bar=warmup, end_bar=n_btc,
        adx_sizing={"strong": 175, "moderate": 125, "weak": 75}, adx_values=adx_btc)
    s_conv = stats(trades_conv_best, equity_curve=ec_conv_best)
    print(f"  {'Conviction ADX $175/$125/$75':>40s} | {s_conv['trades']:>6d} ${s_conv['pnl']:>7.0f} {s_conv['pnl_pct']:>6.1f}% "
          f"{s_conv['pf']:>6.2f} {s_conv['win_rate']:>5.1f}% {s_conv['max_dd']:>5.1f}%")

    # Skip-ranging
    trades_skip, ec_skip, _ = run_mtf_fixed(
        btc_15m, btc_1h, 8, 4.0, "hlc3", 10, 4.0, "close",
        start_bar=warmup, end_bar=n_btc,
        adx_sizing={"strong": 175, "moderate": 125, "weak": 0.01}, adx_values=adx_btc)
    s_skip = stats([t for t in trades_skip if t.get("size_usd", 0) > 10], equity_curve=ec_skip)
    print(f"  {'Conviction $175/$125/SKIP ranging':>40s} | {s_skip['trades']:>6d} ${s_skip['pnl']:>7.0f} {s_skip['pnl_pct']:>6.1f}% "
          f"{s_skip['pf']:>6.2f} {s_skip['win_rate']:>5.1f}% {s_skip['max_dd']:>5.1f}%")

    # Regime adaptive best
    if best_regime:
        bs = best_regime["stats"]
        regime_label = "Regime " + best_regime["fast"] + "/" + best_regime["slow"]
        print(f"  {regime_label:>40s} | {bs['trades']:>6d} ${bs['pnl']:>7.0f} {bs['pnl_pct']:>6.1f}% "
              f"{bs['pf']:>6.2f} {bs['win_rate']:>5.1f}% {bs['max_dd']:>5.1f}%")

    elapsed = time.time() - t0
    print(f"\n  Total runtime: {elapsed:.0f}s")


if __name__ == "__main__":
    main()

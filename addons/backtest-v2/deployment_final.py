#!/usr/bin/env python3
"""
Final deployment analysis: HL availability, combined config, ADX filters,
missed trade sensitivity, per-asset optimization.
"""

import json
import time
import numpy as np
import requests
from pathlib import Path
from datetime import datetime, timezone
from collections import defaultdict
from itertools import product

DATA_DIR = Path(__file__).parent.parent / "backtest-data"

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


def run_mtf_fixed(data_15m, data_1h, entry_atr, entry_mult, entry_src,
                  confirm_atr, confirm_mult, confirm_src,
                  start_bar, end_bar, fixed_size=125.0, leverage=10.0,
                  taker_fee=0.00045, slippage=0.0001, starting_capital=500.0,
                  adx_values=None, adx_min=None, adx_max=None):
    """MTF backtest with optional ADX band filter."""
    d = data_15m; n = min(end_bar, d["n"])
    _, h_dirs = calc_supertrend(data_1h["highs"], data_1h["lows"], data_1h["closes"],
                                 confirm_atr, confirm_mult, confirm_src)
    h_ts = data_1h["timestamps"]
    htf_dir = np.ones(n); h_idx = 0
    for i in range(n):
        while h_idx < len(h_ts) - 1 and h_ts[h_idx + 1] <= d["timestamps"][i]: h_idx += 1
        if h_idx < len(h_dirs): htf_dir[i] = h_dirs[h_idx]

    o, h, l, c, v, ts = (d["opens"][:n], d["highs"][:n], d["lows"][:n],
                          d["closes"][:n], d["volumes"][:n], d["timestamps"][:n])
    st_line, st_dir = calc_supertrend(h, l, c, entry_atr, entry_mult, entry_src)

    notional = fixed_size * leverage
    equity = starting_capital; position = 0; entry_price = 0.0; entry_bar_idx = 0
    trades = []; equity_curve = []; pending = None

    for i in range(start_bar, n):
        if pending is not None and i > start_bar:
            action = pending; pending = None; ep = o[i]
            if action == "close" and position != 0:
                fill = ep - ep * slippage * position
                pnl_raw = (fill - entry_price) * position * (notional / entry_price)
                fee = notional * taker_fee
                trades.append({"pnl": pnl_raw - fee, "fee": fee, "direction": position,
                               "entry_price": entry_price, "exit_price": fill,
                               "entry_time": int(ts[entry_bar_idx]), "exit_time": int(ts[i]),
                               "bars_held": i - entry_bar_idx})
                equity += pnl_raw - fee; position = 0
            elif action.startswith("open") or action.startswith("flip"):
                if position != 0:
                    fill_c = ep - ep * slippage * position
                    pnl_raw = (fill_c - entry_price) * position * (notional / entry_price)
                    fee = notional * taker_fee
                    trades.append({"pnl": pnl_raw - fee, "fee": fee, "direction": position,
                                   "entry_price": entry_price, "exit_price": fill_c,
                                   "entry_time": int(ts[entry_bar_idx]), "exit_time": int(ts[i]),
                                   "bars_held": i - entry_bar_idx})
                    equity += pnl_raw - fee
                nd = 1 if "long" in action else -1
                fill_o = ep + ep * slippage * nd
                fee = notional * taker_fee; equity -= fee
                position = nd; entry_price = fill_o; entry_bar_idx = i
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
        # ADX band filter
        if adx_values is not None and adx_min is not None and adx_max is not None:
            adx_val = adx_values[i] if i < len(adx_values) else np.nan
            if np.isnan(adx_val) or adx_val < adx_min or adx_val > adx_max:
                if position != 0: pending = "close"
                continue
        if position == 0: pending = "open_long" if nd == 1 else "open_short"
        elif position != nd: pending = "flip_long" if nd == 1 else "flip_short"

    if pending == "close" and position != 0:
        fill = c[n-1] * (1 - slippage * position)
        pnl_raw = (fill - entry_price) * position * (notional / entry_price)
        fee = notional * taker_fee
        trades.append({"pnl": pnl_raw - fee, "fee": fee, "direction": position,
                       "entry_price": entry_price, "exit_price": fill,
                       "entry_time": int(ts[entry_bar_idx]), "exit_time": int(ts[n-1]),
                       "bars_held": n - 1 - entry_bar_idx})
        equity += pnl_raw - fee
    return trades, equity_curve, equity


def stats(trades, starting=500.0, equity_curve=None):
    if not trades: return {"trades": 0, "pnl": 0, "pf": 0, "win_rate": 0, "max_dd": 0}
    pnl = sum(t["pnl"] for t in trades)
    wins = [t for t in trades if t["pnl"] > 0]
    gp = sum(t["pnl"] for t in wins)
    gl = abs(sum(t["pnl"] for t in trades if t["pnl"] <= 0))
    pf = gp / gl if gl > 0 else 9999
    max_dd = 0
    if equity_curve:
        ec = np.array(equity_curve); peak = np.maximum.accumulate(ec)
        max_dd = float(np.max((peak - ec) / peak * 100))
    return {"trades": len(trades), "pnl": round(pnl, 2), "pf": round(pf, 2),
            "win_rate": round(len(wins)/len(trades)*100, 1), "max_dd": round(max_dd, 1),
            "fees": round(sum(t["fee"] for t in trades), 2)}


def monthly_breakdown(trades):
    months = defaultdict(lambda: {"trades": 0, "pnl": 0, "wins": 0})
    for t in trades:
        dt = datetime.fromtimestamp(t["exit_time"]/1000, tz=timezone.utc)
        key = dt.strftime("%Y-%m")
        months[key]["trades"] += 1; months[key]["pnl"] += t["pnl"]
        if t["pnl"] > 0: months[key]["wins"] += 1
    return dict(months)


def print_monthly(months, label, compact=False):
    sorted_m = sorted(months.keys())
    cum = 0; pos = 0; total = 0
    if not compact:
        print(f"\n  {label}:")
        print(f"  {'Month':>8s} | {'Tr':>3s} {'P&L $':>8s} {'Cum $':>8s} |")
        print(f"  {'─'*8} | {'─'*3} {'─'*8} {'─'*8} |")
    for m in sorted_m:
        d = months[m]; cum += d["pnl"]; total += 1
        if d["pnl"] > 0: pos += 1
        if not compact:
            bar_len = min(int(abs(d["pnl"]) / 15), 40)
            bar = ("+" * bar_len) if d["pnl"] > 0 else ("-" * bar_len)
            print(f"  {m:>8s} | {d['trades']:>3d} ${d['pnl']:>7.0f} ${cum:>7.0f} | {bar}")
    return pos, total, cum


def main():
    t0 = time.time()
    print("=" * 110)
    print("DEPLOYMENT FINAL ANALYSIS")
    print("=" * 110)
    warmup = 200

    # ═══════════════════════════════════════════════════════════
    # 1. HYPERLIQUID AVAILABILITY CHECK
    # ═══════════════════════════════════════════════════════════
    print(f"\n{'='*110}")
    print("1. HYPERLIQUID AVAILABILITY — ETH and SOL perpetuals")
    print(f"{'='*110}")

    try:
        resp = requests.post("https://api.hyperliquid.xyz/info", json={"type": "meta"}, timeout=10)
        meta = resp.json()
        universe = meta.get("universe", [])

        print(f"\n  Total perpetuals on Hyperliquid: {len(universe)}")
        targets = {"BTC": None, "ETH": None, "SOL": None}
        for asset in universe:
            name = asset.get("name", "")
            if name in targets:
                targets[name] = asset

        for name, info in targets.items():
            if info:
                print(f"\n  {name}-USD Perpetual: AVAILABLE")
                print(f"    szDecimals: {info.get('szDecimals', '?')}")
                print(f"    maxLeverage: {info.get('maxLeverage', '?')}x")
            else:
                print(f"\n  {name}-USD Perpetual: NOT FOUND")

        # Check current prices and 24h volume
        resp2 = requests.post("https://api.hyperliquid.xyz/info", json={"type": "allMids"}, timeout=10)
        mids = resp2.json()

        # Get recent trades for volume estimate
        for name in ["BTC", "ETH", "SOL"]:
            price = float(mids.get(name, 0))
            if price > 0:
                print(f"    Current price: ${price:.2f}")

        # Check L2 book depth
        print(f"\n  Order book depth (top of book):")
        for name in ["BTC", "ETH", "SOL"]:
            try:
                resp_book = requests.post("https://api.hyperliquid.xyz/info",
                    json={"type": "l2Book", "coin": name}, timeout=10)
                book = resp_book.json()
                levels = book.get("levels", [[], []])
                if len(levels) >= 2 and levels[0] and levels[1]:
                    best_bid = float(levels[0][0].get("px", 0))
                    best_ask = float(levels[1][0].get("px", 0))
                    bid_sz = float(levels[0][0].get("sz", 0))
                    ask_sz = float(levels[1][0].get("sz", 0))
                    spread = best_ask - best_bid
                    spread_pct = spread / best_bid * 100 if best_bid > 0 else 0
                    # Sum top 5 levels
                    bid_depth = sum(float(l.get("sz", 0)) * float(l.get("px", 0)) for l in levels[0][:5])
                    ask_depth = sum(float(l.get("sz", 0)) * float(l.get("px", 0)) for l in levels[1][:5])
                    print(f"    {name}: Bid ${best_bid:.2f} ({bid_sz:.4f}) / Ask ${best_ask:.2f} ({ask_sz:.4f}) "
                          f"| Spread: ${spread:.2f} ({spread_pct:.4f}%) "
                          f"| 5-level depth: ${bid_depth:,.0f} / ${ask_depth:,.0f}")
            except Exception as e:
                print(f"    {name}: Error fetching book: {e}")

    except Exception as e:
        print(f"  Error connecting to Hyperliquid API: {e}")

    # Load all data
    btc_15m = load_klines("binance_btc_15m.json"); btc_1h = load_klines("binance_btc_1h.json")
    eth_15m = load_klines("binance_eth_15m.json"); eth_1h = load_klines("binance_eth_1h.json")
    sol_15m = load_klines("binance_sol_15m.json"); sol_1h = load_klines("binance_sol_1h.json")

    btc_adx = calc_adx(btc_15m["highs"], btc_15m["lows"], btc_15m["closes"])
    eth_adx = calc_adx(eth_15m["highs"], eth_15m["lows"], eth_15m["closes"])
    sol_adx = calc_adx(sol_15m["highs"], sol_15m["lows"], sol_15m["closes"])

    # ═══════════════════════════════════════════════════════════
    # 2. COMBINED CONFIG — BTC+ETH+SOL, ADX 20-35
    # ═══════════════════════════════════════════════════════════
    print(f"\n{'='*110}")
    print("2. COMBINED: BTC+ETH+SOL, $42/asset, ADX 20-35 filter, taker fees")
    print(f"{'='*110}")

    assets_data = {
        "BTC": (btc_15m, btc_1h, btc_adx),
        "ETH": (eth_15m, eth_1h, eth_adx),
        "SOL": (sol_15m, sol_1h, sol_adx),
    }

    combined_trades = []
    combined_ecs = {}
    per_asset_stats = {}

    for name, (d15, d1h, adx) in assets_data.items():
        trades, ec, eq = run_mtf_fixed(
            d15, d1h, 8, 4.0, "hlc3", 10, 4.0, "close",
            start_bar=warmup, end_bar=d15["n"],
            fixed_size=42.0, starting_capital=167.0,
            adx_values=adx, adx_min=20, adx_max=35)
        for t in trades: t["asset"] = name
        combined_trades.extend(trades)
        combined_ecs[name] = ec
        s = stats(trades, starting=167.0, equity_curve=ec)
        per_asset_stats[name] = s
        print(f"  {name}: {s['trades']} trades, P&L ${s['pnl']:.0f} ({s['pnl']/167*100:.1f}%), "
              f"PF={s['pf']:.2f}, Win={s['win_rate']:.1f}%, MDD={s['max_dd']:.1f}%")

    # Combined equity
    min_len = min(len(ec) for ec in combined_ecs.values())
    comb_ec = sum(np.array(ec[:min_len]) for ec in combined_ecs.values())
    comb_pnl = float(comb_ec[-1]) - 500
    comb_peak = np.maximum.accumulate(comb_ec)
    comb_dd = (comb_peak - comb_ec) / comb_peak * 100
    comb_mdd = float(np.max(comb_dd))

    comb_wins = sum(1 for t in combined_trades if t["pnl"] > 0)
    comb_gp = sum(t["pnl"] for t in combined_trades if t["pnl"] > 0)
    comb_gl = abs(sum(t["pnl"] for t in combined_trades if t["pnl"] <= 0))
    comb_pf = comb_gp / comb_gl if comb_gl > 0 else 9999
    comb_fees = sum(t["fee"] for t in combined_trades)

    print(f"\n  COMBINED: {len(combined_trades)} trades, P&L ${comb_pnl:.0f} ({comb_pnl/500*100:.1f}%), "
          f"PF={comb_pf:.2f}, Win={comb_wins/len(combined_trades)*100:.1f}%, MDD={comb_mdd:.1f}%, Fees=${comb_fees:.0f}")

    # Monthly breakdown by asset
    all_months_data = defaultdict(lambda: {"BTC": 0, "ETH": 0, "SOL": 0, "total": 0,
                                            "btc_tr": 0, "eth_tr": 0, "sol_tr": 0})
    for t in combined_trades:
        dt = datetime.fromtimestamp(t["exit_time"]/1000, tz=timezone.utc)
        m = dt.strftime("%Y-%m")
        all_months_data[m][t["asset"]] += t["pnl"]
        all_months_data[m]["total"] += t["pnl"]
        all_months_data[m][t["asset"].lower() + "_tr"] += 1

    print(f"\n  MONTHLY BREAKDOWN:")
    print(f"  {'Month':>8s} | {'BTC':>6s} {'ETH':>6s} {'SOL':>6s} | {'Total':>7s} {'Cum':>8s} | {'#BTC':>4s} {'#ETH':>4s} {'#SOL':>4s}")
    print(f"  {'─'*8} | {'─'*6} {'─'*6} {'─'*6} | {'─'*7} {'─'*8} | {'─'*4} {'─'*4} {'─'*4}")

    cum = 0; pos_months = 0
    for m in sorted(all_months_data.keys()):
        d = all_months_data[m]; cum += d["total"]
        if d["total"] > 0: pos_months += 1
        print(f"  {m:>8s} | ${d['BTC']:>5.0f} ${d['ETH']:>5.0f} ${d['SOL']:>5.0f} | ${d['total']:>6.0f} ${cum:>7.0f} | "
              f"{d['btc_tr']:>4d} {d['eth_tr']:>4d} {d['sol_tr']:>4d}")

    print(f"\n  Positive months: {pos_months}/{len(all_months_data)}")

    # ═══════════════════════════════════════════════════════════
    # 3. BTC STANDALONE ADX 20-35 FILTERED
    # ═══════════════════════════════════════════════════════════
    print(f"\n{'='*110}")
    print("3. BTC STANDALONE — ADX 20-35 filter vs unfiltered")
    print(f"{'='*110}")

    # Unfiltered
    t_uf, ec_uf, _ = run_mtf_fixed(btc_15m, btc_1h, 8, 4.0, "hlc3", 10, 4.0, "close",
                                     start_bar=warmup, end_bar=btc_15m["n"])
    s_uf = stats(t_uf, equity_curve=ec_uf)

    # ADX 20-35
    t_af, ec_af, _ = run_mtf_fixed(btc_15m, btc_1h, 8, 4.0, "hlc3", 10, 4.0, "close",
                                     start_bar=warmup, end_bar=btc_15m["n"],
                                     adx_values=btc_adx, adx_min=20, adx_max=35)
    s_af = stats(t_af, equity_curve=ec_af)

    # ADX 20-999 (skip ranging only)
    t_sr, ec_sr, _ = run_mtf_fixed(btc_15m, btc_1h, 8, 4.0, "hlc3", 10, 4.0, "close",
                                     start_bar=warmup, end_bar=btc_15m["n"],
                                     adx_values=btc_adx, adx_min=20, adx_max=999)
    s_sr = stats(t_sr, equity_curve=ec_sr)

    print(f"\n  {'Config':>30s} | {'Trades':>6s} {'P&L $':>8s} {'PF':>6s} {'Win%':>6s} {'MDD%':>6s} {'Fees':>7s}")
    print(f"  {'─'*30} | {'─'*6} {'─'*8} {'─'*6} {'─'*6} {'─'*6} {'─'*7}")
    for label, s in [("BTC Unfiltered", s_uf), ("BTC ADX 20-35", s_af), ("BTC ADX >= 20 (skip ranging)", s_sr)]:
        print(f"  {label:>30s} | {s['trades']:>6d} ${s['pnl']:>7.0f} {s['pf']:>6.2f} {s['win_rate']:>5.1f}% "
              f"{s['max_dd']:>5.1f}% ${s['fees']:>6.0f}")

    # Monthly for ADX 20-35
    btc_af_months = monthly_breakdown(t_af)
    pos, total, cum = print_monthly(btc_af_months, "BTC ADX 20-35 Monthly")
    print(f"\n  Positive months: {pos}/{total}")

    # ═══════════════════════════════════════════════════════════
    # 4. SOL STANDALONE ADX 20-35
    # ═══════════════════════════════════════════════════════════
    print(f"\n{'='*110}")
    print("4. SOL STANDALONE — ADX 20-35 filter, $125, taker fees")
    print(f"{'='*110}")

    t_sol_uf, ec_sol_uf, _ = run_mtf_fixed(sol_15m, sol_1h, 8, 4.0, "hlc3", 10, 4.0, "close",
                                             start_bar=warmup, end_bar=sol_15m["n"])
    s_sol_uf = stats(t_sol_uf, equity_curve=ec_sol_uf)

    t_sol_af, ec_sol_af, _ = run_mtf_fixed(sol_15m, sol_1h, 8, 4.0, "hlc3", 10, 4.0, "close",
                                             start_bar=warmup, end_bar=sol_15m["n"],
                                             adx_values=sol_adx, adx_min=20, adx_max=35)
    s_sol_af = stats(t_sol_af, equity_curve=ec_sol_af)

    print(f"\n  {'Config':>25s} | {'Trades':>6s} {'P&L $':>8s} {'PF':>6s} {'Win%':>6s} {'MDD%':>6s}")
    print(f"  {'─'*25} | {'─'*6} {'─'*8} {'─'*6} {'─'*6} {'─'*6}")
    print(f"  {'SOL Unfiltered':>25s} | {s_sol_uf['trades']:>6d} ${s_sol_uf['pnl']:>7.0f} {s_sol_uf['pf']:>6.2f} "
          f"{s_sol_uf['win_rate']:>5.1f}% {s_sol_uf['max_dd']:>5.1f}%")
    print(f"  {'SOL ADX 20-35':>25s} | {s_sol_af['trades']:>6d} ${s_sol_af['pnl']:>7.0f} {s_sol_af['pf']:>6.2f} "
          f"{s_sol_af['win_rate']:>5.1f}% {s_sol_af['max_dd']:>5.1f}%")

    sol_af_months = monthly_breakdown(t_sol_af)
    pos, total, cum = print_monthly(sol_af_months, "SOL ADX 20-35 Monthly")
    print(f"\n  Positive months: {pos}/{total}")

    # ═══════════════════════════════════════════════════════════
    # 5. MISSED TRADE SENSITIVITY — Monte Carlo
    # ═══════════════════════════════════════════════════════════
    print(f"\n{'='*110}")
    print("5. MISSED TRADE SENSITIVITY — What if the bot misses 5% of trades?")
    print(f"{'='*110}")

    # Run for each asset unfiltered
    all_asset_trades = {
        "BTC": t_uf,
        "ETH": None,
        "SOL": t_sol_uf,
    }
    # Also run ETH unfiltered
    t_eth_uf, ec_eth_uf, _ = run_mtf_fixed(eth_15m, eth_1h, 8, 4.0, "hlc3", 10, 4.0, "close",
                                             start_bar=warmup, end_bar=eth_15m["n"])
    all_asset_trades["ETH"] = t_eth_uf

    for asset_name, asset_trades in all_asset_trades.items():
        pnls = [t["pnl"] for t in asset_trades]
        n_trades = len(pnls)
        n_remove = max(1, int(n_trades * 0.05))
        base_pnl = sum(pnls)

        mc_results = []
        np.random.seed(42)
        for _ in range(1000):
            # Randomly remove 5% of trades
            indices = np.random.choice(n_trades, size=n_trades - n_remove, replace=False)
            mc_pnl = sum(pnls[i] for i in indices)
            mc_results.append(mc_pnl)

        mc_results.sort()
        p5 = mc_results[49]; p25 = mc_results[249]; p50 = mc_results[499]
        p75 = mc_results[749]; p95 = mc_results[949]

        print(f"\n  {asset_name} ({n_trades} trades, removing {n_remove} = 5%):")
        print(f"    Base P&L:      ${base_pnl:.0f}")
        print(f"    5th percentile:  ${p5:.0f}")
        print(f"    25th percentile: ${p25:.0f}")
        print(f"    Median:          ${p50:.0f}")
        print(f"    75th percentile: ${p75:.0f}")
        print(f"    95th percentile: ${p95:.0f}")
        print(f"    Worst case:      ${mc_results[0]:.0f}")
        print(f"    Best case:       ${mc_results[-1]:.0f}")
        print(f"    Goes negative:   {sum(1 for r in mc_results if r < 0)}/1000 ({sum(1 for r in mc_results if r < 0)/10:.1f}%)")

    # ═══════════════════════════════════════════════════════════
    # 6. PER-ASSET ST OPTIMIZATION
    # ═══════════════════════════════════════════════════════════
    print(f"\n{'='*110}")
    print("6. PER-ASSET SUPERTREND OPTIMIZATION — Top 20 combos per asset")
    print(f"{'='*110}")

    SCREEN = list(product(
        [7, 8, 9, 10, 12],
        [2.5, 3.0, 3.5, 4.0, 5.0],
        ["hl2", "hlc3", "close"],
    ))  # 75 combos

    for asset_name, d15, d1h in [("BTC", btc_15m, btc_1h),
                                   ("ETH", eth_15m, eth_1h),
                                   ("SOL", sol_15m, sol_1h)]:
        results = []
        for atr_p, mult, src in SCREEN:
            trades, ec, eq = run_mtf_fixed(
                d15, d1h, atr_p, mult, src, 10, 4.0, "close",
                start_bar=warmup, end_bar=d15["n"])
            s = stats(trades, equity_curve=ec)
            results.append({"atr": atr_p, "mult": mult, "src": src, **s})

        results.sort(key=lambda r: r["pf"], reverse=True)

        print(f"\n  {asset_name} — Top 15 by PF (1H confirm always ST(10,4.0,close)):")
        print(f"  {'#':>3s} {'ATR':>3s} {'Mult':>4s} {'Src':>5s} | {'Trades':>6s} {'P&L $':>8s} {'PF':>6s} {'Win%':>6s} {'MDD%':>6s}")
        print(f"  {'─'*3} {'─'*3} {'─'*4} {'─'*5} | {'─'*6} {'─'*8} {'─'*6} {'─'*6} {'─'*6}")

        for i, r in enumerate(results[:15]):
            marker = " <-- current" if r["atr"] == 8 and r["mult"] == 4.0 and r["src"] == "hlc3" else ""
            print(f"  {i+1:>3d} {r['atr']:>3d} {r['mult']:>4.1f} {r['src']:>5s} | "
                  f"{r['trades']:>6d} ${r['pnl']:>7.0f} {r['pf']:>6.2f} {r['win_rate']:>5.1f}% {r['max_dd']:>5.1f}%{marker}")

        # Best for this asset
        best = results[0]
        print(f"\n  {asset_name} OPTIMAL: ST({best['atr']}, {best['mult']}, {best['src']}) — "
              f"PF={best['pf']:.2f}, P&L=${best['pnl']:.0f}")

    # ═══════════════════════════════════════════════════════════
    # FINAL SUMMARY
    # ═══════════════════════════════════════════════════════════
    print(f"\n{'='*110}")
    print("FINAL SUMMARY")
    print(f"{'='*110}")

    print(f"\n  DEPLOYMENT OPTIONS (all taker fees, fixed sizing):")
    print(f"  {'Option':>45s} | {'Trades':>6s} {'P&L $':>8s} {'PF':>6s} {'Win%':>6s} {'MDD%':>6s}")
    print(f"  {'─'*45} | {'─'*6} {'─'*8} {'─'*6} {'─'*6} {'─'*6}")

    options = [
        ("BTC $125 unfiltered", s_uf),
        ("BTC $125 ADX 20-35", s_af),
        ("SOL $125 unfiltered", s_sol_uf),
        ("SOL $125 ADX 20-35", s_sol_af),
        ("3-asset $42 each, ADX 20-35", {"trades": len(combined_trades), "pnl": round(comb_pnl, 2),
         "pf": round(comb_pf, 2), "win_rate": round(comb_wins/len(combined_trades)*100, 1),
         "max_dd": round(comb_mdd, 1)}),
    ]
    for label, s in options:
        print(f"  {label:>45s} | {s['trades']:>6d} ${s['pnl']:>7.0f} {s['pf']:>6.2f} {s['win_rate']:>5.1f}% {s['max_dd']:>5.1f}%")

    elapsed = time.time() - t0
    print(f"\n  Runtime: {elapsed:.0f}s")


if __name__ == "__main__":
    main()

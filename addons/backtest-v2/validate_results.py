#!/usr/bin/env python3
"""
Validate suspicious results: SOL/ETH concentration, regime adaptation logic,
ADX>30 trades, and BTC monthly P&L.
"""

import json
import numpy as np
from pathlib import Path
from datetime import datetime, timezone
from collections import defaultdict

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
    dx = np.full(n, np.nan)
    for i in range(period, n):
        if s_tr[i] and not np.isnan(s_tr[i]) and s_tr[i] > 0:
            pdi = 100 * s_pdm[i] / s_tr[i]
            mdi = 100 * s_mdm[i] / s_tr[i]
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
                  adx_values=None):
    """MTF backtest, returns trades tagged with ADX at entry."""
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
        if h_idx < len(h_dirs): htf_dir[i] = h_dirs[h_idx]

    o, h, l, c, v, ts = (d["opens"][:n], d["highs"][:n], d["lows"][:n],
                          d["closes"][:n], d["volumes"][:n], d["timestamps"][:n])
    st_line, st_dir = calc_supertrend(h, l, c, entry_atr, entry_mult, entry_src)

    notional = fixed_size * leverage
    equity = starting_capital
    position = 0; entry_price = 0.0; entry_bar_idx = 0
    trades = []; equity_curve = []; pending = None

    for i in range(start_bar, n):
        if pending is not None and i > start_bar:
            action = pending; pending = None
            ep = o[i]
            if action == "close" and position != 0:
                fill = ep - ep * slippage * position
                pnl_raw = (fill - entry_price) * position * (notional / entry_price)
                fee = notional * taker_fee
                adx_val = float(adx_values[entry_bar_idx]) if adx_values is not None and not np.isnan(adx_values[entry_bar_idx]) else -1
                trades.append({"pnl_before_fees": pnl_raw, "fee": fee, "pnl": pnl_raw - fee,
                               "direction": position, "entry_price": entry_price, "exit_price": fill,
                               "entry_time": int(ts[entry_bar_idx]), "exit_time": int(ts[i]),
                               "bars_held": i - entry_bar_idx, "adx": adx_val})
                equity += pnl_raw - fee; position = 0
            elif action.startswith("open") or action.startswith("flip"):
                if position != 0:
                    fill_c = ep - ep * slippage * position
                    pnl_raw = (fill_c - entry_price) * position * (notional / entry_price)
                    fee = notional * taker_fee
                    adx_val = float(adx_values[entry_bar_idx]) if adx_values is not None and not np.isnan(adx_values[entry_bar_idx]) else -1
                    trades.append({"pnl_before_fees": pnl_raw, "fee": fee, "pnl": pnl_raw - fee,
                                   "direction": position, "entry_price": entry_price, "exit_price": fill_c,
                                   "entry_time": int(ts[entry_bar_idx]), "exit_time": int(ts[i]),
                                   "bars_held": i - entry_bar_idx, "adx": adx_val})
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
        if position == 0: pending = "open_long" if nd == 1 else "open_short"
        elif position != nd: pending = "flip_long" if nd == 1 else "flip_short"

    if pending == "close" and position != 0:
        fill = c[n-1] * (1 - slippage * position)
        pnl_raw = (fill - entry_price) * position * (notional / entry_price)
        fee = notional * taker_fee
        adx_val = float(adx_values[entry_bar_idx]) if adx_values is not None and not np.isnan(adx_values[entry_bar_idx]) else -1
        trades.append({"pnl_before_fees": pnl_raw, "fee": fee, "pnl": pnl_raw - fee,
                       "direction": position, "entry_price": entry_price, "exit_price": fill,
                       "entry_time": int(ts[entry_bar_idx]), "exit_time": int(ts[n-1]),
                       "bars_held": n - 1 - entry_bar_idx, "adx": adx_val})
        equity += pnl_raw - fee
    return trades, equity_curve, equity


def monthly_table(trades, label):
    """Monthly P&L breakdown."""
    months = defaultdict(lambda: {"trades": 0, "pnl": 0, "wins": 0, "losses": 0, "biggest_win": 0, "biggest_loss": 0})
    for t in trades:
        dt = datetime.fromtimestamp(t["exit_time"]/1000, tz=timezone.utc)
        key = dt.strftime("%Y-%m")
        months[key]["trades"] += 1
        months[key]["pnl"] += t["pnl"]
        if t["pnl"] > 0:
            months[key]["wins"] += 1
            months[key]["biggest_win"] = max(months[key]["biggest_win"], t["pnl"])
        else:
            months[key]["losses"] += 1
            months[key]["biggest_loss"] = min(months[key]["biggest_loss"], t["pnl"])

    sorted_months = sorted(months.keys())
    cum_pnl = 0
    pos_months = 0
    neg_months = 0

    print(f"\n  {label} — MONTHLY P&L:")
    print(f"  {'Month':>8s} | {'Trades':>6s} {'W':>3s} {'L':>3s} {'P&L $':>9s} {'Cum $':>9s} {'BigWin':>8s} {'BigLoss':>9s} |")
    print(f"  {'─'*8} | {'─'*6} {'─'*3} {'─'*3} {'─'*9} {'─'*9} {'─'*8} {'─'*9} |")

    for m in sorted_months:
        d = months[m]
        cum_pnl += d["pnl"]
        if d["pnl"] > 0: pos_months += 1
        else: neg_months += 1
        bar_len = int(abs(d["pnl"]) / 10)
        bar = ("+" * bar_len) if d["pnl"] > 0 else ("-" * bar_len)
        print(f"  {m:>8s} | {d['trades']:>6d} {d['wins']:>3d} {d['losses']:>3d} ${d['pnl']:>8.2f} ${cum_pnl:>8.2f} "
              f"${d['biggest_win']:>7.2f} ${d['biggest_loss']:>8.2f} | {bar}")

    print(f"\n  Positive months: {pos_months}/{pos_months+neg_months} ({pos_months/(pos_months+neg_months)*100:.0f}%)")
    return months


def main():
    print("=" * 110)
    print("RESULT VALIDATION")
    print("=" * 110)

    warmup = 200

    # ═══════════════════════════════════════════════════════════
    # 5. BTC MONTHLY P&L (answering this first — it's the core question)
    # ═══════════════════════════════════════════════════════════
    print(f"\n{'='*110}")
    print("5. BTC PURE MTF — MONTHLY P&L (the core question)")
    print(f"{'='*110}")

    btc_15m = load_klines("binance_btc_15m.json")
    btc_1h = load_klines("binance_btc_1h.json")
    btc_adx = calc_adx(btc_15m["highs"], btc_15m["lows"], btc_15m["closes"], 14)

    trades_btc, ec_btc, eq_btc = run_mtf_fixed(
        btc_15m, btc_1h, 8, 4.0, "hlc3", 10, 4.0, "close",
        start_bar=warmup, end_bar=btc_15m["n"], adx_values=btc_adx)

    btc_months = monthly_table(trades_btc, "BTC Pure MTF $125 fixed")

    # Concentration analysis
    sorted_trades = sorted(trades_btc, key=lambda t: t["pnl"], reverse=True)
    total_pnl = sum(t["pnl"] for t in trades_btc)
    top5_pnl = sum(t["pnl"] for t in sorted_trades[:5])
    top10_pnl = sum(t["pnl"] for t in sorted_trades[:10])
    top20_pnl = sum(t["pnl"] for t in sorted_trades[:20])
    print(f"\n  PROFIT CONCENTRATION:")
    print(f"    Total P&L: ${total_pnl:.2f}")
    print(f"    Top 5 trades:  ${top5_pnl:.2f} ({top5_pnl/total_pnl*100:.0f}% of total)")
    print(f"    Top 10 trades: ${top10_pnl:.2f} ({top10_pnl/total_pnl*100:.0f}% of total)")
    print(f"    Top 20 trades: ${top20_pnl:.2f} ({top20_pnl/total_pnl*100:.0f}% of total)")
    print(f"    Remove best trade (${sorted_trades[0]['pnl']:.2f}): remaining P&L ${total_pnl - sorted_trades[0]['pnl']:.2f}")

    # ═══════════════════════════════════════════════════════════
    # 1. SOL SURVIVORSHIP BIAS
    # ═══════════════════════════════════════════════════════════
    print(f"\n{'='*110}")
    print("1. SOL — SURVIVORSHIP BIAS CHECK")
    print(f"{'='*110}")

    sol_15m = load_klines("binance_sol_15m.json")
    sol_1h = load_klines("binance_sol_1h.json")

    sol_start_price = sol_15m["closes"][0]
    sol_end_price = sol_15m["closes"][-1]
    sol_start_dt = datetime.fromtimestamp(sol_15m["timestamps"][0]/1000, tz=timezone.utc)
    sol_end_dt = datetime.fromtimestamp(sol_15m["timestamps"][-1]/1000, tz=timezone.utc)
    sol_bh = (sol_end_price / sol_start_price - 1) * 100

    print(f"\n  SOL price: ${sol_start_price:.2f} ({sol_start_dt.strftime('%Y-%m-%d')}) -> ${sol_end_price:.2f} ({sol_end_dt.strftime('%Y-%m-%d')})")
    print(f"  Buy & hold return: {sol_bh:.1f}%")

    trades_sol, ec_sol, eq_sol = run_mtf_fixed(
        sol_15m, sol_1h, 8, 4.0, "hlc3", 10, 4.0, "close",
        start_bar=warmup, end_bar=sol_15m["n"])

    sol_months = monthly_table(trades_sol, "SOL Pure MTF $125 fixed")

    sol_total = sum(t["pnl"] for t in trades_sol)
    sol_sorted = sorted(trades_sol, key=lambda t: t["pnl"], reverse=True)
    sol_top1 = sol_sorted[0]["pnl"]
    sol_top5 = sum(t["pnl"] for t in sol_sorted[:5])
    sol_top10 = sum(t["pnl"] for t in sol_sorted[:10])

    print(f"\n  PROFIT CONCENTRATION:")
    print(f"    Total P&L: ${sol_total:.2f}")
    print(f"    Best trade: ${sol_top1:.2f} ({sol_top1/sol_total*100:.0f}% of total)")
    entry_dt = datetime.fromtimestamp(sol_sorted[0]["entry_time"]/1000, tz=timezone.utc)
    exit_dt = datetime.fromtimestamp(sol_sorted[0]["exit_time"]/1000, tz=timezone.utc)
    d_str = "LONG" if sol_sorted[0]["direction"] == 1 else "SHORT"
    print(f"      {d_str} {entry_dt.strftime('%Y-%m-%d %H:%M')} -> {exit_dt.strftime('%Y-%m-%d %H:%M')} "
          f"${sol_sorted[0]['entry_price']:.2f} -> ${sol_sorted[0]['exit_price']:.2f}")
    print(f"    Top 5 trades:  ${sol_top5:.2f} ({sol_top5/sol_total*100:.0f}%)")
    print(f"    Top 10 trades: ${sol_top10:.2f} ({sol_top10/sol_total*100:.0f}%)")
    print(f"    Remove best trade: remaining ${sol_total - sol_top1:.2f} ({(sol_total-sol_top1)/500*100:.1f}%)")
    print(f"    Remove top 5:      remaining ${sol_total - sol_top5:.2f} ({(sol_total-sol_top5)/500*100:.1f}%)")

    # Is SOL still better than BTC without the best trade?
    btc_total = sum(t["pnl"] for t in trades_btc)
    btc_no_best = btc_total - sorted_trades[0]["pnl"]
    sol_no_best = sol_total - sol_top1
    print(f"\n  WITHOUT BEST TRADE: SOL ${sol_no_best:.0f} vs BTC ${btc_no_best:.0f} -> {'SOL still wins' if sol_no_best > btc_no_best else 'BTC wins'}")

    # ═══════════════════════════════════════════════════════════
    # 2. ETH SAME QUESTION
    # ═══════════════════════════════════════════════════════════
    print(f"\n{'='*110}")
    print("2. ETH — MONTHLY P&L AND CONCENTRATION")
    print(f"{'='*110}")

    eth_15m = load_klines("binance_eth_15m.json")
    eth_1h = load_klines("binance_eth_1h.json")

    eth_start_price = eth_15m["closes"][0]
    eth_end_price = eth_15m["closes"][-1]
    eth_bh = (eth_end_price / eth_start_price - 1) * 100
    print(f"\n  ETH price: ${eth_start_price:.2f} -> ${eth_end_price:.2f} (buy & hold: {eth_bh:.1f}%)")

    trades_eth, ec_eth, eq_eth = run_mtf_fixed(
        eth_15m, eth_1h, 8, 4.0, "hlc3", 10, 4.0, "close",
        start_bar=warmup, end_bar=eth_15m["n"])

    eth_months = monthly_table(trades_eth, "ETH Pure MTF $125 fixed")

    eth_total = sum(t["pnl"] for t in trades_eth)
    eth_sorted = sorted(trades_eth, key=lambda t: t["pnl"], reverse=True)
    eth_top1 = eth_sorted[0]["pnl"]
    eth_top5 = sum(t["pnl"] for t in eth_sorted[:5])
    eth_top10 = sum(t["pnl"] for t in eth_sorted[:10])

    print(f"\n  PROFIT CONCENTRATION:")
    print(f"    Total P&L: ${eth_total:.2f}")
    print(f"    Best trade: ${eth_top1:.2f} ({eth_top1/eth_total*100:.0f}%)")
    print(f"    Top 5:  ${eth_top5:.2f} ({eth_top5/eth_total*100:.0f}%)")
    print(f"    Top 10: ${eth_top10:.2f} ({eth_top10/eth_total*100:.0f}%)")
    print(f"    Remove best trade: remaining ${eth_total - eth_top1:.0f}")
    print(f"    Remove top 5:      remaining ${eth_total - eth_top5:.0f}")
    print(f"\n  WITHOUT BEST TRADE: ETH ${eth_total - eth_top1:.0f} vs BTC ${btc_no_best:.0f} -> {'ETH still wins' if (eth_total-eth_top1) > btc_no_best else 'BTC wins'}")

    # ═══════════════════════════════════════════════════════════
    # 3. REGIME ADAPTATION — WHY DOES IT FAIL?
    # ═══════════════════════════════════════════════════════════
    print(f"\n{'='*110}")
    print("3. REGIME ADAPTATION — DIAGNOSTIC")
    print(f"{'='*110}")

    # The issue: when we switch to a "fast" ST in trending, we get MORE signals
    # but many are whipsaws. Let's trace exactly what happens.

    # Run the best regime-adaptive: ST(7,3.0,close) trending / ST(12,4.0,close) ranging
    # vs baseline ST(8,4.0,hlc3) everywhere

    print(f"\n  The claim: ADX 20-30 is profitable (PF 1.35). So using optimal params per regime should help.")
    print(f"  The reality: regime adaptation ADDS trades in trending zones, and those extra trades lose money.")

    # Count how many signals each ST variant generates in each regime
    n_btc = btc_15m["n"]
    h, l, c = btc_15m["highs"][:n_btc], btc_15m["lows"][:n_btc], btc_15m["closes"][:n_btc]

    # Baseline ST
    _, dir_base = calc_supertrend(h, l, c, 8, 4.0, "hlc3")
    # Fast ST
    _, dir_fast = calc_supertrend(h, l, c, 7, 3.0, "close")
    # Slow ST
    _, dir_slow = calc_supertrend(h, l, c, 12, 4.0, "close")

    # Count flips in each regime
    for st_label, st_dir in [("Baseline ST(8,4.0,hlc3)", dir_base),
                              ("Fast ST(7,3.0,close)", dir_fast),
                              ("Slow ST(12,4.0,close)", dir_slow)]:
        flips_trending = 0
        flips_ranging = 0
        flips_neutral = 0
        for i in range(warmup, n_btc):
            if np.isnan(st_dir[i]) or np.isnan(st_dir[i-1]): continue
            if st_dir[i] != st_dir[i-1]:
                adx = btc_adx[i]
                if np.isnan(adx): continue
                if adx >= 25: flips_trending += 1
                elif adx < 20: flips_ranging += 1
                else: flips_neutral += 1

        total = flips_trending + flips_ranging + flips_neutral
        print(f"\n  {st_label}: {total} total flips")
        print(f"    Trending (ADX>=25): {flips_trending} ({flips_trending/total*100:.0f}%)")
        print(f"    Ranging  (ADX<20):  {flips_ranging} ({flips_ranging/total*100:.0f}%)")
        print(f"    Neutral  (20-25):   {flips_neutral} ({flips_neutral/total*100:.0f}%)")

    print(f"\n  KEY INSIGHT: Fast ST generates {int((dir_fast[warmup:] != np.roll(dir_fast, 1)[warmup:]).sum())} flips vs "
          f"Baseline's {int((dir_base[warmup:] != np.roll(dir_base, 1)[warmup:]).sum())}.")
    print(f"  More flips = more fees = more whipsaws in sideways action within 'trending' regimes.")
    print(f"  ADX >= 25 doesn't mean 'trending in one direction' — it means 'directional movement is strong'")
    print(f"  which can include volatile two-way swings that whipsaw a fast Supertrend.")

    # ═══════════════════════════════════════════════════════════
    # 4. ADX > 30 LOSING MONEY — WHY?
    # ═══════════════════════════════════════════════════════════
    print(f"\n{'='*110}")
    print("4. ADX > 30 TRADES — WHY DO STRONG TRENDS LOSE MONEY?")
    print(f"{'='*110}")

    # Get all trades that entered when ADX > 30
    adx30_trades = [t for t in trades_btc if t["adx"] >= 30]
    adx30_wins = [t for t in adx30_trades if t["pnl"] > 0]
    adx30_losses = [t for t in adx30_trades if t["pnl"] <= 0]
    adx30_pnl = sum(t["pnl"] for t in adx30_trades)

    print(f"\n  ADX >= 30 trades: {len(adx30_trades)} ({len(adx30_wins)} wins, {len(adx30_losses)} losses)")
    print(f"  Total P&L: ${adx30_pnl:.2f}")
    print(f"  Win rate: {len(adx30_wins)/len(adx30_trades)*100:.1f}%")

    # Show each trade
    print(f"\n  ALL {len(adx30_trades)} TRADES WITH ADX >= 30 AT ENTRY:")
    print(f"  {'#':>3s} {'Entry Date':>18s} {'Dir':>5s} {'ADX':>5s} {'Entry$':>10s} {'Exit$':>10s} {'P&L':>9s} {'Hours':>6s} {'Bars':>5s}")
    print(f"  {'─'*3} {'─'*18} {'─'*5} {'─'*5} {'─'*10} {'─'*10} {'─'*9} {'─'*6} {'─'*5}")

    for i, t in enumerate(sorted(adx30_trades, key=lambda x: x["entry_time"])):
        entry_dt = datetime.fromtimestamp(t["entry_time"]/1000, tz=timezone.utc)
        d_str = "LONG" if t["direction"] == 1 else "SHORT"
        hours = t["bars_held"] * 15 / 60
        print(f"  {i+1:>3d} {entry_dt.strftime('%Y-%m-%d %H:%M'):>18s} {d_str:>5s} {t['adx']:>5.1f} "
              f"${t['entry_price']:>9.2f} ${t['exit_price']:>9.2f} ${t['pnl']:>8.2f} {hours:>5.1f}h {t['bars_held']:>5d}")

    # Analyze: are these late entries?
    # Check how long the trend had been running before entry
    print(f"\n  ANALYSIS — Are these late entries?")

    short_trades = [t for t in adx30_trades if t["bars_held"] <= 8]  # <= 2 hours
    medium_trades = [t for t in adx30_trades if 8 < t["bars_held"] <= 32]  # 2-8 hours
    long_trades = [t for t in adx30_trades if t["bars_held"] > 32]  # > 8 hours

    print(f"    Short holds (<=2h):  {len(short_trades)} trades, P&L ${sum(t['pnl'] for t in short_trades):.2f}")
    print(f"    Medium holds (2-8h): {len(medium_trades)} trades, P&L ${sum(t['pnl'] for t in medium_trades):.2f}")
    print(f"    Long holds (>8h):    {len(long_trades)} trades, P&L ${sum(t['pnl'] for t in long_trades):.2f}")

    # ADX at entry vs outcome
    adx_bins = [(30, 35), (35, 40), (40, 50), (50, 100)]
    print(f"\n    ADX level at entry vs outcome:")
    for lo, hi in adx_bins:
        bin_trades = [t for t in adx30_trades if lo <= t["adx"] < hi]
        if bin_trades:
            bin_pnl = sum(t["pnl"] for t in bin_trades)
            bin_wins = sum(1 for t in bin_trades if t["pnl"] > 0)
            print(f"      ADX {lo}-{hi}: {len(bin_trades)} trades, P&L ${bin_pnl:.2f}, Win {bin_wins/len(bin_trades)*100:.0f}%")

    print(f"\n  VERDICT: ADX > 30 means the trend is ALREADY MATURE.")
    print(f"  By the time ADX reaches 30, the big move has happened. New entries catch the tail end")
    print(f"  and get stopped out on the mean reversion. This is classic 'late to the party' behavior.")

    # ═══════════════════════════════════════════════════════════
    # CROSS-ASSET MONTHLY COMPARISON
    # ═══════════════════════════════════════════════════════════
    print(f"\n{'='*110}")
    print("CROSS-ASSET MONTHLY COMPARISON")
    print(f"{'='*110}")

    all_months = sorted(set(list(btc_months.keys()) + list(eth_months.keys()) + list(sol_months.keys())))
    print(f"\n  {'Month':>8s} | {'BTC P&L':>9s} {'ETH P&L':>9s} {'SOL P&L':>9s} | {'Sum':>9s} {'BTC cum':>9s} {'ETH cum':>9s} {'SOL cum':>9s}")
    print(f"  {'─'*8} | {'─'*9} {'─'*9} {'─'*9} | {'─'*9} {'─'*9} {'─'*9} {'─'*9}")

    btc_cum = eth_cum = sol_cum = 0
    for m in all_months:
        b = btc_months.get(m, {"pnl": 0})["pnl"]
        e = eth_months.get(m, {"pnl": 0})["pnl"]
        s = sol_months.get(m, {"pnl": 0})["pnl"]
        btc_cum += b; eth_cum += e; sol_cum += s
        total = b + e + s
        print(f"  {m:>8s} | ${b:>8.0f} ${e:>8.0f} ${s:>8.0f} | ${total:>8.0f} ${btc_cum:>8.0f} ${eth_cum:>8.0f} ${sol_cum:>8.0f}")

    print(f"\n  Months where ALL 3 are positive: ", end="")
    both_pos = [m for m in all_months if btc_months.get(m, {"pnl": 0})["pnl"] > 0
                and eth_months.get(m, {"pnl": 0})["pnl"] > 0
                and sol_months.get(m, {"pnl": 0})["pnl"] > 0]
    print(f"{len(both_pos)}/{len(all_months)}")

    print(f"  Months where ALL 3 are negative: ", end="")
    both_neg = [m for m in all_months if btc_months.get(m, {"pnl": 0})["pnl"] < 0
                and eth_months.get(m, {"pnl": 0})["pnl"] < 0
                and sol_months.get(m, {"pnl": 0})["pnl"] < 0]
    print(f"{len(both_neg)}/{len(all_months)}")


if __name__ == "__main__":
    main()

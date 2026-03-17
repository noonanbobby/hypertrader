#!/usr/bin/env python3
"""
Test SQZMOM_LB and MACD+RSI filters against Pure MTF baseline.
Then full validation on the winner.
"""

import numpy as np
from pathlib import Path
import json
from datetime import datetime, timezone

DATA_DIR = Path(__file__).parent.parent / "backtest-data"

import sys
sys.path.insert(0, str(Path(__file__).parent))
from engine import calc_supertrend, calc_tr, calc_atr_rma


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


# ═══════════════════════════════════════════════════════════════
# INDICATORS
# ═══════════════════════════════════════════════════════════════

def calc_sma(data, period):
    n = len(data); out = np.full(n, np.nan)
    cs = np.cumsum(data)
    out[period-1:] = (cs[period-1:] - np.concatenate(([0], cs[:-period]))) / period
    return out


def calc_ema(data, period):
    n = len(data); out = np.full(n, np.nan)
    start = 0
    while start < n and np.isnan(data[start]): start += 1
    if start + period > n: return out
    out[start + period - 1] = np.mean(data[start:start + period])
    k = 2.0 / (period + 1)
    for i in range(start + period, n):
        out[i] = data[i] * k + out[i-1] * (1 - k)
    return out


def calc_linreg(data, period):
    n = len(data); out = np.full(n, np.nan)
    x = np.arange(period, dtype=float)
    x_mean = x.mean()
    ss_xx = np.sum((x - x_mean)**2)
    for i in range(period - 1, n):
        w = data[i - period + 1:i + 1]
        if np.any(np.isnan(w)): continue
        y_mean = w.mean()
        ss_xy = np.sum((x - x_mean) * (w - y_mean))
        slope = ss_xy / ss_xx
        intercept = y_mean - slope * x_mean
        out[i] = intercept + slope * (period - 1)
    return out


def calc_squeeze_momentum(highs, lows, closes, bb_length=20, bb_mult=2.0, kc_length=20, kc_mult=1.5):
    """LazyBear Squeeze Momentum. Returns (histogram, squeeze_on)."""
    n = len(closes)
    bb_basis = calc_sma(closes, bb_length)
    bb_dev = np.full(n, np.nan)
    for i in range(bb_length - 1, n):
        bb_dev[i] = np.std(closes[i - bb_length + 1:i + 1], ddof=0) * bb_mult
    upper_bb = bb_basis + bb_dev; lower_bb = bb_basis - bb_dev

    tr = calc_tr(highs, lows, closes)
    kc_atr = calc_sma(tr, kc_length)
    kc_basis = calc_sma(closes, kc_length)
    upper_kc = kc_basis + kc_mult * kc_atr; lower_kc = kc_basis - kc_mult * kc_atr

    squeeze_on = np.full(n, False)
    for i in range(n):
        if not np.isnan(lower_bb[i]) and not np.isnan(lower_kc[i]):
            squeeze_on[i] = (lower_bb[i] > lower_kc[i]) and (upper_bb[i] < upper_kc[i])

    highest_high = np.full(n, np.nan); lowest_low = np.full(n, np.nan)
    for i in range(kc_length - 1, n):
        highest_high[i] = np.max(highs[i - kc_length + 1:i + 1])
        lowest_low[i] = np.min(lows[i - kc_length + 1:i + 1])
    mid_hl = (highest_high + lowest_low) / 2
    mid_all = (mid_hl + kc_basis) / 2
    momentum_src = closes - mid_all
    histogram = calc_linreg(momentum_src, kc_length)
    return histogram, squeeze_on


def calc_macd(closes, fast=12, slow=26, signal=9):
    fast_ema = calc_ema(closes, fast); slow_ema = calc_ema(closes, slow)
    macd_line = fast_ema - slow_ema
    signal_line = calc_ema(macd_line, signal)
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def calc_rsi(closes, period=14):
    n = len(closes); rsi = np.full(n, np.nan)
    if n < period + 1: return rsi
    delta = np.diff(closes)
    gains = np.where(delta > 0, delta, 0.0); losses = np.where(delta < 0, -delta, 0.0)
    avg_gain = np.mean(gains[:period]); avg_loss = np.mean(losses[:period])
    if avg_loss == 0: rsi[period] = 100.0
    else: rsi[period] = 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        if avg_loss == 0: rsi[i + 1] = 100.0
        else: rsi[i + 1] = 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)
    return rsi


def calc_adx(highs, lows, closes, period=14):
    n = len(closes); adx = np.full(n, np.nan)
    if n < period*2+1: return adx
    plus_dm = np.zeros(n); minus_dm = np.zeros(n)
    for i in range(1, n):
        up = highs[i]-highs[i-1]; down = lows[i-1]-lows[i]
        if up > down and up > 0: plus_dm[i] = up
        if down > up and down > 0: minus_dm[i] = down
    tr = calc_tr(highs, lows, closes)
    def rma(data, p):
        out = np.full(len(data), np.nan); out[p] = np.sum(data[1:p+1])
        for i in range(p+1, len(data)): out[i] = out[i-1]-out[i-1]/p+data[i]
        return out
    s_tr = rma(tr, period); s_pdm = rma(plus_dm, period); s_mdm = rma(minus_dm, period)
    dx = np.full(n, np.nan); pdi = np.full(n, np.nan); mdi = np.full(n, np.nan)
    for i in range(period, n):
        if s_tr[i] and not np.isnan(s_tr[i]) and s_tr[i] > 0:
            pdi[i] = 100*s_pdm[i]/s_tr[i]; mdi[i] = 100*s_mdm[i]/s_tr[i]
            s = pdi[i]+mdi[i]
            if s > 0: dx[i] = 100*abs(pdi[i]-mdi[i])/s
    fv = period
    while fv < n and np.isnan(dx[fv]): fv += 1
    if fv+period >= n: return adx
    adx[fv+period-1] = np.nanmean(dx[fv:fv+period])
    for i in range(fv+period, n):
        if not np.isnan(dx[i]) and not np.isnan(adx[i-1]):
            adx[i] = (adx[i-1]*(period-1)+dx[i])/period
    return adx


# ═══════════════════════════════════════════════════════════════
# BACKTEST
# ═══════════════════════════════════════════════════════════════

def run_mtf(data_15m, data_1h, entry_atr, entry_mult, entry_src,
            start_bar, end_bar, fixed_size=125.0, leverage=10.0,
            taker_fee=0.00045, slippage=0.0001, starting_capital=500.0,
            signal_filter=None):
    d = data_15m; n = min(end_bar, d["n"])
    _, h_dirs = calc_supertrend(data_1h["highs"], data_1h["lows"], data_1h["closes"], 10, 4.0, "close")
    h_ts = data_1h["timestamps"]
    htf_dir = np.ones(n); h_idx = 0
    for i in range(n):
        while h_idx < len(h_ts)-1 and h_ts[h_idx+1] <= d["timestamps"][i]: h_idx += 1
        if h_idx < len(h_dirs): htf_dir[i] = h_dirs[h_idx]
    o,h,l,c,ts = d["opens"][:n],d["highs"][:n],d["lows"][:n],d["closes"][:n],d["timestamps"][:n]
    st_line, st_dir = calc_supertrend(h,l,c,entry_atr,entry_mult,entry_src)
    notional = fixed_size*leverage
    equity = starting_capital; position = 0; entry_price = 0.0; entry_bar = 0
    trades = []; equity_curve = []; pending = None

    for i in range(start_bar, n):
        if pending is not None and i > start_bar:
            action = pending; pending = None; ep = o[i]
            if action == "close" and position != 0:
                fill = ep-ep*slippage*position
                pnl = (fill-entry_price)*position*(notional/entry_price)-notional*taker_fee
                trades.append({"pnl": pnl, "entry_time": int(ts[entry_bar]), "exit_time": int(ts[i])})
                equity += pnl; position = 0
            elif action.startswith("open") or action.startswith("flip"):
                if position != 0:
                    fill_c = ep-ep*slippage*position
                    pnl = (fill_c-entry_price)*position*(notional/entry_price)-notional*taker_fee
                    trades.append({"pnl": pnl, "entry_time": int(ts[entry_bar]), "exit_time": int(ts[i])})
                    equity += pnl
                nd = 1 if "long" in action else -1
                equity -= notional*taker_fee
                position = nd; entry_price = ep+ep*slippage*nd; entry_bar = i
        if position != 0:
            equity_curve.append(equity+(c[i]-entry_price)*position*(notional/entry_price))
        else:
            equity_curve.append(equity)
        if i >= n-1:
            if position != 0: pending = "close"
            continue
        if np.isnan(st_dir[i]) or np.isnan(st_dir[i-1]): continue
        if st_dir[i] == st_dir[i-1]: continue
        nd = 1 if st_dir[i] == 1 else -1
        if htf_dir[i] != nd:
            if position != 0: pending = "close"
            continue
        if signal_filter is not None and not signal_filter(i, nd):
            if position != 0: pending = "close"
            continue
        if position == 0: pending = "open_long" if nd == 1 else "open_short"
        elif position != nd: pending = "flip_long" if nd == 1 else "flip_short"

    if pending == "close" and position != 0:
        fill = c[n-1]*(1-slippage*position)
        pnl = (fill-entry_price)*position*(notional/entry_price)-notional*taker_fee
        trades.append({"pnl": pnl, "entry_time": int(ts[entry_bar]), "exit_time": int(ts[n-1])})
        equity += pnl
    return trades, equity_curve, equity


def m(trades, ec=None):
    if not trades: return {"n":0,"pnl":0,"pf":0,"wr":0,"mdd":0}
    pnl = sum(t["pnl"] for t in trades)
    wins = [t for t in trades if t["pnl"]>0]; gp = sum(t["pnl"] for t in wins)
    gl = abs(sum(t["pnl"] for t in trades if t["pnl"]<=0))
    pf = gp/gl if gl>0 else 9999; mdd = 0
    if ec:
        ea = np.array(ec); pk = np.maximum.accumulate(ea)
        if len(ea)>0: mdd = float(np.max((pk-ea)/pk*100))
    return {"n":len(trades),"pnl":round(pnl,2),"pf":round(pf,2),
            "wr":round(len(wins)/len(trades)*100,1),"mdd":round(mdd,1)}


def print_row(label, r, baseline_pnl=None):
    avg = r["pnl"]/r["n"] if r["n"] else 0
    delta = f"({r['pnl']-baseline_pnl:+.0f})" if baseline_pnl is not None else ""
    print(f"  {label:>40s} | {r['n']:>6d} ${r['pnl']:>7.0f} {delta:>7s} {r['pf']:>6.2f} {r['wr']:>5.1f}% {r['mdd']:>5.1f}% ${avg:>6.2f}")


def main():
    print("="*110)
    print("SQZMOM + MACD FILTER TESTS — BTC Pure MTF, $125 fixed, taker fees, 730 days")
    print("="*110)
    warmup = 200

    btc_15m = load_klines("binance_btc_15m.json")
    btc_1h = load_klines("binance_btc_1h.json")
    n = btc_15m["n"]
    h, l, c, v, ts = btc_15m["highs"], btc_15m["lows"], btc_15m["closes"], btc_15m["volumes"], btc_15m["timestamps"]

    print("\n  Computing indicators...")
    sqz_hist, sqz_on = calc_squeeze_momentum(h, l, c, 20, 2.0, 20, 1.5)
    macd_line, macd_signal, macd_hist = calc_macd(c, 12, 26, 9)
    rsi14 = calc_rsi(c, 14)
    adx14 = calc_adx(h, l, c, 14)

    # ADX rising precompute
    adx_rising = np.full(n, False)
    for i in range(4, n):
        if not np.isnan(adx14[i]) and not np.isnan(adx14[i-4]):
            adx_rising[i] = adx14[i] > adx14[i-4]

    # Squeeze just turned off (was on previous bar, now off)
    sqz_just_off = np.full(n, False)
    for i in range(1, n):
        sqz_just_off[i] = sqz_on[i-1] and not sqz_on[i]
    # Squeeze recently turned off (within last 3 bars)
    sqz_recent_off = np.full(n, False)
    for i in range(3, n):
        sqz_recent_off[i] = any(sqz_just_off[i-j] for j in range(4))

    # ═══════════════════════════════════════════════════════════
    # BASELINE
    # ═══════════════════════════════════════════════════════════
    base_trades, base_ec, _ = run_mtf(btc_15m, btc_1h, 8, 4.0, "hlc3", warmup, n)
    base = m(base_trades, base_ec)

    print(f"\n  {'Filter':>40s} | {'Trades':>6s} {'P&L $':>7s} {'Delta':>7s} {'PF':>6s} {'Win%':>6s} {'MDD%':>6s} {'$/tr':>7s}")
    print(f"  {'─'*40} | {'─'*6} {'─'*7} {'─'*7} {'─'*6} {'─'*6} {'─'*6} {'─'*7}")
    print_row("BASELINE (no filter)", base)

    # ═══════════════════════════════════════════════════════════
    # SQUEEZE MOMENTUM FILTERS
    # ═══════════════════════════════════════════════════════════
    print(f"\n  --- SQUEEZE MOMENTUM ---")

    sqz_filters = [
        ("A) Block when squeeze ON", lambda i, d: not sqz_on[i]),
        ("B) Only when squeeze just OFF", lambda i, d: sqz_recent_off[i]),
        ("C) Squeeze OFF + hist matches dir", lambda i, d: (not sqz_on[i]) and (not np.isnan(sqz_hist[i])) and ((sqz_hist[i] > 0) if d == 1 else (sqz_hist[i] < 0))),
        ("Histogram matches direction only", lambda i, d: (not np.isnan(sqz_hist[i])) and ((sqz_hist[i] > 0) if d == 1 else (sqz_hist[i] < 0))),
    ]

    sqz_results = {}
    for label, filt in sqz_filters:
        trades, ec, _ = run_mtf(btc_15m, btc_1h, 8, 4.0, "hlc3", warmup, n, signal_filter=filt)
        r = m(trades, ec)
        sqz_results[label] = r
        print_row(label, r, base["pnl"])

    # ═══════════════════════════════════════════════════════════
    # MACD FILTERS
    # ═══════════════════════════════════════════════════════════
    print(f"\n  --- MACD ---")

    macd_filters = [
        ("MACD histogram > 0 / < 0", lambda i, d: (not np.isnan(macd_hist[i])) and ((macd_hist[i] > 0) if d == 1 else (macd_hist[i] < 0))),
        ("MACD line > signal / < signal", lambda i, d: (not np.isnan(macd_line[i])) and (not np.isnan(macd_signal[i])) and ((macd_line[i] > macd_signal[i]) if d == 1 else (macd_line[i] < macd_signal[i]))),
    ]

    macd_results = {}
    for label, filt in macd_filters:
        trades, ec, _ = run_mtf(btc_15m, btc_1h, 8, 4.0, "hlc3", warmup, n, signal_filter=filt)
        r = m(trades, ec)
        macd_results[label] = r
        print_row(label, r, base["pnl"])

    # ═══════════════════════════════════════════════════════════
    # RSI FILTER (for comparison)
    # ═══════════════════════════════════════════════════════════
    print(f"\n  --- RSI (comparison) ---")

    rsi_filters = [
        ("RSI(14) buy>50, sell<50", lambda i, d: (not np.isnan(rsi14[i])) and ((rsi14[i] > 50) if d == 1 else (rsi14[i] < 50))),
    ]
    for label, filt in rsi_filters:
        trades, ec, _ = run_mtf(btc_15m, btc_1h, 8, 4.0, "hlc3", warmup, n, signal_filter=filt)
        r = m(trades, ec)
        print_row(label, r, base["pnl"])

    # ═══════════════════════════════════════════════════════════
    # OUR EXISTING BEST FILTERS (comparison)
    # ═══════════════════════════════════════════════════════════
    print(f"\n  --- EXISTING BEST (comparison) ---")

    existing = [
        ("ADX>=15 + rising", lambda i, d: (not np.isnan(adx14[i])) and adx14[i] >= 15 and adx_rising[i]),
        ("DI spread > 15", None),  # need DI, compute inline
    ]

    # ADX>=15 + rising
    filt_adx = lambda i, d: (not np.isnan(adx14[i])) and adx14[i] >= 15 and adx_rising[i]
    trades_adx, ec_adx, _ = run_mtf(btc_15m, btc_1h, 8, 4.0, "hlc3", warmup, n, signal_filter=filt_adx)
    r_adx = m(trades_adx, ec_adx)
    print_row("ADX>=15 + rising", r_adx, base["pnl"])

    # DI spread > 15
    # DI computation (ADX already computed above, need DI+/DI- separately)
    plus_dm_arr = np.zeros(n); minus_dm_arr = np.zeros(n)
    for i in range(1, n):
        up = h[i]-h[i-1]; down = l[i-1]-l[i]
        if up > down and up > 0: plus_dm_arr[i] = up
        if down > up and down > 0: minus_dm_arr[i] = down
    tr = calc_tr(h, l, c)
    def rma(data, p):
        out = np.full(len(data), np.nan); out[p] = np.sum(data[1:p+1])
        for i in range(p+1, len(data)): out[i] = out[i-1]-out[i-1]/p+data[i]
        return out
    s_tr = rma(tr, 14); s_pdm = rma(plus_dm_arr, 14); s_mdm = rma(minus_dm_arr, 14)
    pdi = np.full(n, np.nan); mdi = np.full(n, np.nan)
    for i in range(14, n):
        if s_tr[i] and not np.isnan(s_tr[i]) and s_tr[i] > 0:
            pdi[i] = 100*s_pdm[i]/s_tr[i]; mdi[i] = 100*s_mdm[i]/s_tr[i]

    filt_di = lambda i, d: (not np.isnan(pdi[i])) and (not np.isnan(mdi[i])) and (((pdi[i]-mdi[i]) >= 15) if d == 1 else ((mdi[i]-pdi[i]) >= 15))
    trades_di, ec_di, _ = run_mtf(btc_15m, btc_1h, 8, 4.0, "hlc3", warmup, n, signal_filter=filt_di)
    r_di = m(trades_di, ec_di)
    print_row("DI spread > 15", r_di, base["pnl"])

    # ═══════════════════════════════════════════════════════════
    # COMBINATIONS with ADX>=15+rising
    # ═══════════════════════════════════════════════════════════
    print(f"\n  --- COMBINATIONS WITH ADX>=15 + RISING ---")

    combos = [
        ("+ SQZ OFF + hist match", lambda i, d: filt_adx(i, d) and (not sqz_on[i]) and (not np.isnan(sqz_hist[i])) and ((sqz_hist[i] > 0) if d == 1 else (sqz_hist[i] < 0))),
        ("+ SQZ block when ON", lambda i, d: filt_adx(i, d) and not sqz_on[i]),
        ("+ MACD histogram", lambda i, d: filt_adx(i, d) and (not np.isnan(macd_hist[i])) and ((macd_hist[i] > 0) if d == 1 else (macd_hist[i] < 0))),
        ("+ MACD signal cross", lambda i, d: filt_adx(i, d) and (not np.isnan(macd_line[i])) and (not np.isnan(macd_signal[i])) and ((macd_line[i] > macd_signal[i]) if d == 1 else (macd_line[i] < macd_signal[i]))),
        ("+ SQZ hist + MACD hist", lambda i, d: filt_adx(i, d) and (not np.isnan(sqz_hist[i])) and ((sqz_hist[i] > 0) if d == 1 else (sqz_hist[i] < 0)) and (not np.isnan(macd_hist[i])) and ((macd_hist[i] > 0) if d == 1 else (macd_hist[i] < 0))),
    ]

    combo_results = {}
    for label, filt in combos:
        trades, ec, _ = run_mtf(btc_15m, btc_1h, 8, 4.0, "hlc3", warmup, n, signal_filter=filt)
        r = m(trades, ec)
        combo_results[label] = r
        print_row("ADX>=15+rising " + label, r, base["pnl"])

    # ═══════════════════════════════════════════════════════════
    # DETERMINE WINNER
    # ═══════════════════════════════════════════════════════════
    print(f"\n{'='*110}")
    print("RANKING — All filters by Profit Factor")
    print(f"{'='*110}")

    all_results = [("BASELINE", base)]
    for label, r in sqz_results.items(): all_results.append((label, r))
    for label, r in macd_results.items(): all_results.append((label, r))
    all_results.append(("ADX>=15 + rising", r_adx))
    all_results.append(("DI spread > 15", r_di))
    for label, r in combo_results.items(): all_results.append(("ADX+rising " + label, r))

    all_results.sort(key=lambda x: x[1]["pf"], reverse=True)

    print(f"\n  {'#':>3s} {'Filter':>50s} | {'Trades':>6s} {'P&L $':>8s} {'PF':>6s} {'Win%':>6s} {'MDD%':>6s} {'$/tr':>7s}")
    print(f"  {'─'*3} {'─'*50} | {'─'*6} {'─'*8} {'─'*6} {'─'*6} {'─'*6} {'─'*7}")

    for i, (label, r) in enumerate(all_results):
        avg = r["pnl"]/r["n"] if r["n"] else 0
        marker = " <-- BEST" if i == 0 else ""
        print(f"  {i+1:>3d} {label:>50s} | {r['n']:>6d} ${r['pnl']:>7.0f} {r['pf']:>6.2f} {r['wr']:>5.1f}% {r['mdd']:>5.1f}% ${avg:>6.2f}{marker}")

    # ═══════════════════════════════════════════════════════════
    # FULL VALIDATION ON WINNER
    # ═══════════════════════════════════════════════════════════
    winner_label, winner_stats = all_results[0]
    print(f"\n{'='*110}")
    print(f"FULL VALIDATION — {winner_label}")
    print(f"{'='*110}")

    # Determine which filter function to use for the winner
    # Build a lookup
    filter_fns = {
        "BASELINE": None,
        "ADX>=15 + rising": filt_adx,
        "DI spread > 15": filt_di,
    }
    for label, filt in sqz_filters: filter_fns[label] = filt
    for label, filt in macd_filters: filter_fns[label] = filt
    for label, filt in combos: filter_fns["ADX+rising " + label] = filt

    winner_fn = filter_fns.get(winner_label)

    # 1. Walk-forward
    train_end = int(n * 0.7)
    train_dt = datetime.fromtimestamp(ts[train_end]/1000, tz=timezone.utc)
    print(f"\n  1. WALK-FORWARD (split: {train_dt.strftime('%Y-%m-%d')})")

    t_train, ec_train, _ = run_mtf(btc_15m, btc_1h, 8, 4.0, "hlc3", warmup, train_end, signal_filter=winner_fn)
    t_val, ec_val, _ = run_mtf(btc_15m, btc_1h, 8, 4.0, "hlc3", train_end, n, signal_filter=winner_fn)
    m_train = m(t_train, ec_train); m_val = m(t_val, ec_val)

    print(f"     TRAIN:    {m_train['n']} trades, P&L ${m_train['pnl']:.0f}, PF={m_train['pf']:.2f}, Win={m_train['wr']:.1f}%, MDD={m_train['mdd']:.1f}%")
    print(f"     VALIDATE: {m_val['n']} trades, P&L ${m_val['pnl']:.0f}, PF={m_val['pf']:.2f}, Win={m_val['wr']:.1f}%, MDD={m_val['mdd']:.1f}%")
    wf_pass = m_val["pnl"] > 0 and m_val["pf"] > 1.0
    print(f"     {'PASS' if wf_pass else 'FAIL'}")

    # 2. Starting points
    print(f"\n  2. STARTING POINTS (6 points, 120 days apart)")
    bars_120d = 120*24*4; sp_pass = True
    for idx in range(6):
        sb = warmup + idx*bars_120d
        if sb >= n-1000: break
        sdt = datetime.fromtimestamp(ts[sb]/1000, tz=timezone.utc)
        days = (n-sb)/(24*4)
        trades_s, ec_s, _ = run_mtf(btc_15m, btc_1h, 8, 4.0, "hlc3", sb, n, signal_filter=winner_fn)
        r = m(trades_s, ec_s)
        if r["pnl"] <= 0: sp_pass = False
        print(f"     {idx+1}. {sdt.strftime('%Y-%m-%d')} ({days:.0f}d): {r['n']} trades, ${r['pnl']:.0f}, PF={r['pf']:.2f}, MDD={r['mdd']:.1f}% {'PASS' if r['pnl']>0 else 'FAIL'}")
    print(f"     {'PASS' if sp_pass else 'FAIL'}")

    # 3. Parameter robustness
    print(f"\n  3. PARAMETER ROBUSTNESS (+/-20% on mult and ATR)")
    rob_pass = True
    variations = [
        ("Base", 8, 4.0), ("M+20%", 8, 4.8), ("M-20%", 8, 3.2),
        ("ATR+2", 10, 4.0), ("ATR-2", 6, 4.0),
        ("Both+20%", 10, 4.8), ("Both-20%", 6, 3.2),
    ]
    for label, atr, mult in variations:
        trades_r, ec_r, _ = run_mtf(btc_15m, btc_1h, atr, mult, "hlc3", warmup, n, signal_filter=winner_fn)
        r = m(trades_r, ec_r)
        if label != "Base" and r["pnl"] <= 0: rob_pass = False
        status = "" if label == "Base" else ("PASS" if r["pnl"]>0 else "FAIL")
        print(f"     {label:>10s} ST({atr},{mult}): {r['n']} trades, ${r['pnl']:.0f}, PF={r['pf']:.2f}, MDD={r['mdd']:.1f}% {status}")
    print(f"     {'PASS' if rob_pass else 'FAIL'}")

    # VERDICT
    print(f"\n{'='*110}")
    print("FINAL VERDICT")
    print(f"{'='*110}")
    print(f"\n  Best filter: {winner_label}")
    print(f"  Full 730d:   {winner_stats['n']} trades, P&L ${winner_stats['pnl']:.0f}, PF={winner_stats['pf']:.2f}, MDD={winner_stats['mdd']:.1f}%")
    print(f"  Walk-forward: {'PASS' if wf_pass else 'FAIL'}")
    print(f"  Start points: {'PASS' if sp_pass else 'FAIL'}")
    print(f"  Robustness:   {'PASS' if rob_pass else 'FAIL'}")
    all_pass = wf_pass and sp_pass and rob_pass
    print(f"\n  OVERALL: {'ALL PASS — ready for deployment' if all_pass else 'SOME FAILED — review before deployment'}")

    # Current values
    print(f"\n  CURRENT VALUES (last bar):")
    idx = n - 1
    dt = datetime.fromtimestamp(ts[idx]/1000, tz=timezone.utc)
    print(f"    Time: {dt.strftime('%Y-%m-%d %H:%M')} UTC")
    print(f"    SQZ Momentum histogram: {sqz_hist[idx]:.2f}, Squeeze {'ON' if sqz_on[idx] else 'OFF'}")
    print(f"    MACD: line={macd_line[idx]:.2f}, signal={macd_signal[idx]:.2f}, histogram={macd_hist[idx]:.2f}")
    print(f"    RSI(14): {rsi14[idx]:.2f}")
    print(f"    ADX(14): {adx14[idx]:.2f}, rising={adx_rising[idx]}")


if __name__ == "__main__":
    main()

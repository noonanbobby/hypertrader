#!/usr/bin/env python3
"""
Test CMF, DI+/DI-, MFI filters against Pure MTF baseline on BTC.
"""

import numpy as np
from pathlib import Path
import json
from datetime import datetime, timezone

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


# ═══════════════════════════════════════════════════════════════
# INDICATOR CALCULATIONS
# ═══════════════════════════════════════════════════════════════

def calc_cmf(highs, lows, closes, volumes, period=20):
    """Chaikin Money Flow. Returns array of CMF values."""
    n = len(closes)
    cmf = np.full(n, np.nan)
    # Money Flow Multiplier = ((Close - Low) - (High - Close)) / (High - Low)
    # Money Flow Volume = MFM * Volume
    hl_range = highs - lows
    mfm = np.where(hl_range > 0, ((closes - lows) - (highs - closes)) / hl_range, 0.0)
    mfv = mfm * volumes
    for i in range(period - 1, n):
        vol_sum = np.sum(volumes[i - period + 1:i + 1])
        if vol_sum > 0:
            cmf[i] = np.sum(mfv[i - period + 1:i + 1]) / vol_sum
    return cmf


def calc_di(highs, lows, closes, period=14):
    """Directional Index: returns (DI+, DI-, ADX)."""
    n = len(closes)
    plus_di = np.full(n, np.nan)
    minus_di = np.full(n, np.nan)
    adx = np.full(n, np.nan)
    if n < period * 2 + 1:
        return plus_di, minus_di, adx
    plus_dm = np.zeros(n); minus_dm = np.zeros(n)
    for i in range(1, n):
        up = highs[i] - highs[i-1]; down = lows[i-1] - lows[i]
        if up > down and up > 0: plus_dm[i] = up
        if down > up and down > 0: minus_dm[i] = down
    tr = calc_tr(highs, lows, closes)
    def rma(data, p):
        out = np.full(len(data), np.nan); out[p] = np.sum(data[1:p+1])
        for i in range(p+1, len(data)): out[i] = out[i-1] - out[i-1]/p + data[i]
        return out
    s_tr = rma(tr, period); s_pdm = rma(plus_dm, period); s_mdm = rma(minus_dm, period)
    dx = np.full(n, np.nan)
    for i in range(period, n):
        if s_tr[i] and not np.isnan(s_tr[i]) and s_tr[i] > 0:
            plus_di[i] = 100 * s_pdm[i] / s_tr[i]
            minus_di[i] = 100 * s_mdm[i] / s_tr[i]
            s = plus_di[i] + minus_di[i]
            if s > 0: dx[i] = 100 * abs(plus_di[i] - minus_di[i]) / s
    fv = period
    while fv < n and np.isnan(dx[fv]): fv += 1
    if fv + period < n:
        adx[fv + period - 1] = np.nanmean(dx[fv:fv + period])
        for i in range(fv + period, n):
            if not np.isnan(dx[i]) and not np.isnan(adx[i-1]):
                adx[i] = (adx[i-1] * (period - 1) + dx[i]) / period
    return plus_di, minus_di, adx


def calc_mfi(highs, lows, closes, volumes, period=14):
    """Money Flow Index (volume-weighted RSI)."""
    n = len(closes)
    mfi = np.full(n, np.nan)
    typical = (highs + lows + closes) / 3
    raw_mf = typical * volumes
    if n < period + 1:
        return mfi
    for i in range(period, n):
        pos_flow = 0.0; neg_flow = 0.0
        for j in range(i - period + 1, i + 1):
            if typical[j] > typical[j - 1]:
                pos_flow += raw_mf[j]
            elif typical[j] < typical[j - 1]:
                neg_flow += raw_mf[j]
        if neg_flow > 0:
            ratio = pos_flow / neg_flow
            mfi[i] = 100 - 100 / (1 + ratio)
        else:
            mfi[i] = 100.0
    return mfi


# ═══════════════════════════════════════════════════════════════
# BACKTEST ENGINE WITH PLUGGABLE FILTER
# ═══════════════════════════════════════════════════════════════

def run_mtf(data_15m, data_1h, start_bar, end_bar,
            fixed_size=125.0, leverage=10.0, taker_fee=0.00045, slippage=0.0001,
            starting_capital=500.0,
            signal_filter=None):
    """
    Pure MTF backtest. signal_filter(bar_idx, direction) -> True to allow, False to block.
    direction: 1 for long, -1 for short.
    """
    d = data_15m; n = min(end_bar, d["n"])
    _, h_dirs = calc_supertrend(data_1h["highs"], data_1h["lows"], data_1h["closes"], 10, 4.0, "close")
    h_ts = data_1h["timestamps"]
    htf_dir = np.ones(n); h_idx = 0
    for i in range(n):
        while h_idx < len(h_ts)-1 and h_ts[h_idx+1] <= d["timestamps"][i]: h_idx += 1
        if h_idx < len(h_dirs): htf_dir[i] = h_dirs[h_idx]
    o,h,l,c,ts = d["opens"][:n],d["highs"][:n],d["lows"][:n],d["closes"][:n],d["timestamps"][:n]
    st_line, st_dir = calc_supertrend(h,l,c, 8, 4.0, "hlc3")
    notional = fixed_size * leverage
    equity = starting_capital; position = 0; entry_price = 0.0; entry_bar = 0
    trades = []; equity_curve = []; pending = None
    blocked_trades = []  # signals that were filtered out

    for i in range(start_bar, n):
        if pending is not None and i > start_bar:
            action = pending; pending = None; ep = o[i]
            if action == "close" and position != 0:
                fill = ep - ep*slippage*position
                pnl = (fill-entry_price)*position*(notional/entry_price) - notional*taker_fee
                trades.append({"pnl": pnl, "direction": position, "entry_time": int(ts[entry_bar]),
                               "exit_time": int(ts[i]), "bars_held": i-entry_bar})
                equity += pnl; position = 0
            elif action.startswith("open") or action.startswith("flip"):
                if position != 0:
                    fill_c = ep - ep*slippage*position
                    pnl = (fill_c-entry_price)*position*(notional/entry_price) - notional*taker_fee
                    trades.append({"pnl": pnl, "direction": position, "entry_time": int(ts[entry_bar]),
                                   "exit_time": int(ts[i]), "bars_held": i-entry_bar})
                    equity += pnl
                nd = 1 if "long" in action else -1
                equity -= notional*taker_fee
                position = nd; entry_price = ep + ep*slippage*nd; entry_bar = i
        if position != 0:
            equity_curve.append(equity + (c[i]-entry_price)*position*(notional/entry_price))
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
        # Apply filter
        if signal_filter is not None and not signal_filter(i, nd):
            blocked_trades.append({"bar": i, "direction": nd, "time": int(ts[i])})
            if position != 0: pending = "close"
            continue
        if position == 0: pending = "open_long" if nd == 1 else "open_short"
        elif position != nd: pending = "flip_long" if nd == 1 else "flip_short"

    if pending == "close" and position != 0:
        fill = c[n-1]*(1-slippage*position)
        pnl = (fill-entry_price)*position*(notional/entry_price) - notional*taker_fee
        trades.append({"pnl": pnl, "direction": position, "entry_time": int(ts[entry_bar]),
                       "exit_time": int(ts[n-1]), "bars_held": n-1-entry_bar})
        equity += pnl
    return trades, equity_curve, equity, blocked_trades


def st(trades, ec=None, cap=500.0):
    if not trades: return {"n":0,"pnl":0,"pf":0,"wr":0,"mdd":0}
    pnl = sum(t["pnl"] for t in trades)
    wins = [t for t in trades if t["pnl"]>0]; gp = sum(t["pnl"] for t in wins)
    gl = abs(sum(t["pnl"] for t in trades if t["pnl"]<=0))
    pf = gp/gl if gl>0 else 9999
    mdd = 0
    if ec:
        ea = np.array(ec); pk = np.maximum.accumulate(ea)
        mdd = float(np.max((pk-ea)/pk*100))
    return {"n":len(trades),"pnl":round(pnl,2),"pf":round(pf,2),
            "wr":round(len(wins)/len(trades)*100,1),"mdd":round(mdd,1)}


def analyze_blocked(blocked, baseline_trades):
    """For each blocked signal, find the corresponding baseline trade and check if it was a winner."""
    # Build lookup: signal bar -> baseline trade result
    # This is approximate: match blocked signal times to baseline trade entry times
    baseline_by_entry = {}
    for t in baseline_trades:
        baseline_by_entry[t["entry_time"]] = t

    blocked_winners = 0; blocked_losers = 0; unmatched = 0
    for b in blocked:
        bt = baseline_by_entry.get(b["time"])
        if bt:
            if bt["pnl"] > 0: blocked_winners += 1
            else: blocked_losers += 1
        else:
            unmatched += 1
    return blocked_winners, blocked_losers, unmatched


def main():
    print("="*110)
    print("NEW INDICATOR FILTERS — CMF, DI+/DI-, MFI")
    print("="*110)
    warmup = 200

    btc_15m = load_klines("binance_btc_15m.json")
    btc_1h = load_klines("binance_btc_1h.json")
    n = btc_15m["n"]
    h, l, c, v, ts = btc_15m["highs"], btc_15m["lows"], btc_15m["closes"], btc_15m["volumes"], btc_15m["timestamps"]

    # Pre-compute all indicators
    print("\n  Computing indicators...")
    cmf20 = calc_cmf(h, l, c, v, 20)
    plus_di, minus_di, adx14 = calc_di(h, l, c, 14)
    mfi14 = calc_mfi(h, l, c, v, 14)

    # ADX direction (for our existing best filter)
    adx_rising = np.full(n, False)
    for i in range(4, n):
        if not np.isnan(adx14[i]) and not np.isnan(adx14[i-4]):
            adx_rising[i] = adx14[i] > adx14[i-4]

    # ═══════════════════════════════════════════════════════════
    # BASELINE
    # ═══════════════════════════════════════════════════════════
    base_trades, base_ec, base_eq, _ = run_mtf(btc_15m, btc_1h, warmup, n)
    base = st(base_trades, base_ec)
    print(f"\n  BASELINE (no filter): {base['n']} trades, P&L ${base['pnl']:.0f}, PF={base['pf']:.2f}, "
          f"Win={base['wr']:.1f}%, MDD={base['mdd']:.1f}%")

    # ═══════════════════════════════════════════════════════════
    # RUN ALL FILTER VARIANTS
    # ═══════════════════════════════════════════════════════════
    filters = []

    # --- CMF ---
    for thresh in [0.0, 0.05, 0.10]:
        label = f"CMF(20) > {thresh}" if thresh > 0 else "CMF(20) > 0"
        def make_f(t):
            def f(i, d):
                cv = cmf20[i]
                if np.isnan(cv): return False
                if d == 1: return cv > t      # buy: CMF positive
                else: return cv < -t           # sell: CMF negative
            return f
        filters.append((label, "CMF", make_f(thresh)))

    # --- DI+ / DI- ---
    for min_spread in [0, 5, 10, 15]:
        label = f"DI+>DI-" + (f" spread>{min_spread}" if min_spread > 0 else "")
        def make_f(ms):
            def f(i, d):
                pi, mi = plus_di[i], minus_di[i]
                if np.isnan(pi) or np.isnan(mi): return False
                if d == 1: return pi > mi and (pi - mi) >= ms   # buy: DI+ > DI-
                else: return mi > pi and (mi - pi) >= ms         # sell: DI- > DI+
            return f
        filters.append((label, "DI", make_f(min_spread)))

    # --- MFI ---
    mfi_configs = [
        ("MFI buy>40<80, sell>20<60", lambda i, d: (40 < mfi14[i] < 80) if d == 1 else (20 < mfi14[i] < 60) if not np.isnan(mfi14[i]) else False),
        ("MFI buy>50, sell<50", lambda i, d: (mfi14[i] > 50 if d == 1 else mfi14[i] < 50) if not np.isnan(mfi14[i]) else False),
        ("MFI buy>40, sell<60", lambda i, d: (mfi14[i] > 40 if d == 1 else mfi14[i] < 60) if not np.isnan(mfi14[i]) else False),
    ]
    for label, f in mfi_configs:
        filters.append((label, "MFI", f))

    # --- Our existing best filters for comparison ---
    def adx15_rising(i, d):
        av = adx14[i]
        if np.isnan(av) or av < 15: return False
        return adx_rising[i]
    filters.append(("ADX>=15 + rising (our best)", "ADX", adx15_rising))

    def adx20_rising(i, d):
        av = adx14[i]
        if np.isnan(av) or av < 20: return False
        return adx_rising[i]
    filters.append(("ADX>=20 + rising", "ADX", adx20_rising))

    # ═══════════════════════════════════════════════════════════
    # RESULTS TABLE
    # ═══════════════════════════════════════════════════════════
    print(f"\n{'='*110}")
    print("RESULTS — All filters vs baseline")
    print(f"{'='*110}")

    print(f"\n  {'Filter':>35s} | {'Trades':>6s} {'P&L $':>8s} {'PF':>6s} {'Win%':>6s} {'MDD%':>6s} {'$/tr':>7s} | {'Blocked':>7s} {'BlkW':>5s} {'BlkL':>5s}")
    print(f"  {'─'*35} | {'─'*6} {'─'*8} {'─'*6} {'─'*6} {'─'*6} {'─'*7} | {'─'*7} {'─'*5} {'─'*5}")

    # Baseline row
    print(f"  {'BASELINE (no filter)':>35s} | {base['n']:>6d} ${base['pnl']:>7.0f} {base['pf']:>6.2f} {base['wr']:>5.1f}% "
          f"{base['mdd']:>5.1f}% ${base['pnl']/base['n']:>6.2f} |     {'─':>3s}   {'─':>3s}   {'─':>3s}")

    results = []
    for label, category, filt_fn in filters:
        trades, ec, eq, blocked = run_mtf(btc_15m, btc_1h, warmup, n, signal_filter=filt_fn)
        r = st(trades, ec)
        bw, bl, bu = analyze_blocked(blocked, base_trades)
        avg = r["pnl"]/r["n"] if r["n"] else 0
        print(f"  {label:>35s} | {r['n']:>6d} ${r['pnl']:>7.0f} {r['pf']:>6.2f} {r['wr']:>5.1f}% "
              f"{r['mdd']:>5.1f}% ${avg:>6.2f} | {len(blocked):>7d} {bw:>5d} {bl:>5d}")
        results.append({"label": label, "category": category, "stats": r,
                        "blocked": len(blocked), "blocked_winners": bw, "blocked_losers": bl})

    # ═══════════════════════════════════════════════════════════
    # ANALYSIS — blocked trade quality
    # ═══════════════════════════════════════════════════════════
    print(f"\n{'='*110}")
    print("BLOCKED TRADE ANALYSIS — Did filters block more losers than winners?")
    print(f"{'='*110}")

    print(f"\n  A good filter blocks more losers than winners (high BlkL/BlkW ratio).")
    print(f"\n  {'Filter':>35s} | {'Blocked':>7s} {'Winners':>7s} {'Losers':>7s} {'Ratio L/W':>9s} {'Net saved':>10s}")
    print(f"  {'─'*35} | {'─'*7} {'─'*7} {'─'*7} {'─'*9} {'─'*10}")

    for r in results:
        bw = r["blocked_winners"]; bl = r["blocked_losers"]
        ratio = bl / bw if bw > 0 else 9999
        # Estimate P&L saved: blocked losers have avg loss of baseline losers
        base_losses = [t["pnl"] for t in base_trades if t["pnl"] <= 0]
        base_wins = [t["pnl"] for t in base_trades if t["pnl"] > 0]
        avg_loss = np.mean(base_losses) if base_losses else 0
        avg_win = np.mean(base_wins) if base_wins else 0
        net_saved = bl * abs(avg_loss) - bw * avg_win
        print(f"  {r['label']:>35s} | {r['blocked']:>7d} {bw:>7d} {bl:>7d} {ratio:>9.2f} ${net_saved:>9.0f}")

    # ═══════════════════════════════════════════════════════════
    # BEST FROM EACH CATEGORY
    # ═══════════════════════════════════════════════════════════
    print(f"\n{'='*110}")
    print("BEST FROM EACH CATEGORY")
    print(f"{'='*110}")

    for cat in ["CMF", "DI", "MFI", "ADX"]:
        cat_results = [r for r in results if r["category"] == cat]
        if not cat_results: continue
        best = max(cat_results, key=lambda r: r["stats"]["pf"])
        s = best["stats"]
        print(f"\n  {cat} best: {best['label']}")
        print(f"    Trades={s['n']}, P&L=${s['pnl']:.0f}, PF={s['pf']:.2f}, Win={s['wr']:.1f}%, MDD={s['mdd']:.1f}%")
        print(f"    vs baseline: PF {base['pf']:.2f}->{s['pf']:.2f}, MDD {base['mdd']:.1f}%->{s['mdd']:.1f}%")

    # ═══════════════════════════════════════════════════════════
    # COMBINATIONS — best from each + 1H MTF
    # ═══════════════════════════════════════════════════════════
    print(f"\n{'='*110}")
    print("COMBINATIONS — Best filters together")
    print(f"{'='*110}")

    # Top filters to combine
    combo_filters = []

    # Best CMF
    best_cmf_thresh = 0.0
    best_cmf_pf = 0
    for r in results:
        if r["category"] == "CMF" and r["stats"]["pf"] > best_cmf_pf:
            best_cmf_pf = r["stats"]["pf"]
            best_cmf_thresh = float(r["label"].split("> ")[1]) if "> " in r["label"] else 0.0

    # Best DI
    best_di_spread = 0
    best_di_pf = 0
    for r in results:
        if r["category"] == "DI" and r["stats"]["pf"] > best_di_pf:
            best_di_pf = r["stats"]["pf"]
            if "spread>" in r["label"]:
                best_di_spread = int(r["label"].split("spread>")[1])

    combos = [
        ("ADX>=15 rising + CMF>0", lambda i, d: adx15_rising(i, d) and (not np.isnan(cmf20[i])) and (cmf20[i] > 0 if d == 1 else cmf20[i] < 0)),
        ("ADX>=15 rising + DI confirm", lambda i, d: adx15_rising(i, d) and (not np.isnan(plus_di[i])) and (not np.isnan(minus_di[i])) and ((plus_di[i] > minus_di[i]) if d == 1 else (minus_di[i] > plus_di[i]))),
        ("ADX>=15 rising + MFI 50", lambda i, d: adx15_rising(i, d) and (not np.isnan(mfi14[i])) and (mfi14[i] > 50 if d == 1 else mfi14[i] < 50)),
        ("DI confirm + CMF>0", lambda i, d: (not np.isnan(plus_di[i])) and (not np.isnan(minus_di[i])) and ((plus_di[i] > minus_di[i]) if d == 1 else (minus_di[i] > plus_di[i])) and (not np.isnan(cmf20[i])) and (cmf20[i] > 0 if d == 1 else cmf20[i] < 0)),
        ("ADX>=15 rising + DI + CMF", lambda i, d: adx15_rising(i, d) and (not np.isnan(plus_di[i])) and (not np.isnan(minus_di[i])) and ((plus_di[i] > minus_di[i]) if d == 1 else (minus_di[i] > plus_di[i])) and (not np.isnan(cmf20[i])) and (cmf20[i] > 0 if d == 1 else cmf20[i] < 0)),
    ]

    print(f"\n  {'Combination':>35s} | {'Trades':>6s} {'P&L $':>8s} {'PF':>6s} {'Win%':>6s} {'MDD%':>6s} {'$/tr':>7s}")
    print(f"  {'─'*35} | {'─'*6} {'─'*8} {'─'*6} {'─'*6} {'─'*6} {'─'*7}")
    print(f"  {'BASELINE':>35s} | {base['n']:>6d} ${base['pnl']:>7.0f} {base['pf']:>6.2f} {base['wr']:>5.1f}% "
          f"{base['mdd']:>5.1f}% ${base['pnl']/base['n']:>6.2f}")

    for label, filt_fn in combos:
        trades, ec, eq, blocked = run_mtf(btc_15m, btc_1h, warmup, n, signal_filter=filt_fn)
        r = st(trades, ec)
        avg = r["pnl"]/r["n"] if r["n"] else 0
        print(f"  {label:>35s} | {r['n']:>6d} ${r['pnl']:>7.0f} {r['pf']:>6.2f} {r['wr']:>5.1f}% "
              f"{r['mdd']:>5.1f}% ${avg:>6.2f}")

    # ═══════════════════════════════════════════════════════════
    # CURRENT LIVE VALUES
    # ═══════════════════════════════════════════════════════════
    print(f"\n{'='*110}")
    print("CURRENT LIVE VALUES — Last 5 bars of BTC 15m")
    print(f"{'='*110}")

    print(f"\n  {'Time (UTC)':>20s} | {'Close':>10s} {'CMF(20)':>8s} {'DI+':>6s} {'DI-':>6s} {'DI spread':>9s} {'ADX':>6s} {'MFI(14)':>8s}")
    print(f"  {'─'*20} | {'─'*10} {'─'*8} {'─'*6} {'─'*6} {'─'*9} {'─'*6} {'─'*8}")

    for i in range(-5, 0):
        idx = n + i
        dt = datetime.fromtimestamp(ts[idx]/1000, tz=timezone.utc)
        di_spread = (plus_di[idx] - minus_di[idx]) if not np.isnan(plus_di[idx]) and not np.isnan(minus_di[idx]) else 0
        print(f"  {dt.strftime('%Y-%m-%d %H:%M'):>20s} | ${c[idx]:>9.2f} "
              f"{cmf20[idx]:>8.4f} {plus_di[idx]:>6.1f} {minus_di[idx]:>6.1f} {di_spread:>+9.1f} "
              f"{adx14[idx]:>6.1f} {mfi14[idx]:>8.1f}")

    print(f"\n  Add to TradingView:")
    print(f"    CMF: Chaikin Money Flow (length=20)")
    print(f"    DI+/DI-: Directional Movement Index (length=14) — shows DI+ and DI- lines")
    print(f"    MFI: Money Flow Index (length=14)")
    print(f"    ADX: Average Directional Index (length=14)")


if __name__ == "__main__":
    main()

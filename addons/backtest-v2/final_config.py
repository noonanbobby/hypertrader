#!/usr/bin/env python3
"""
FINAL definitive config: per-asset ADX filters with direction.
"""

import numpy as np
from pathlib import Path
import json
from collections import defaultdict
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


def calc_adx(highs, lows, closes, period=14):
    n = len(closes); adx = np.full(n, np.nan)
    if n < period * 2 + 1: return adx
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
            pdi = 100*s_pdm[i]/s_tr[i]; mdi = 100*s_mdm[i]/s_tr[i]; s = pdi+mdi
            if s > 0: dx[i] = 100*abs(pdi-mdi)/s
    fv = period
    while fv < n and np.isnan(dx[fv]): fv += 1
    if fv + period >= n: return adx
    adx[fv+period-1] = np.nanmean(dx[fv:fv+period])
    for i in range(fv+period, n):
        if not np.isnan(dx[i]) and not np.isnan(adx[i-1]):
            adx[i] = (adx[i-1]*(period-1)+dx[i])/period
    return adx


def run_mtf(data_15m, data_1h, entry_atr, entry_mult, entry_src,
            confirm_atr, confirm_mult, confirm_src,
            start_bar, end_bar, adx_values,
            fixed_size=125.0, leverage=10.0,
            taker_fee=0.00045, slippage=0.0001, starting_capital=500.0,
            adx_min=None, adx_max=None, adx_rising=False):
    d = data_15m; n = min(end_bar, d["n"])
    _, h_dirs = calc_supertrend(data_1h["highs"], data_1h["lows"], data_1h["closes"],
                                 confirm_atr, confirm_mult, confirm_src)
    h_ts = data_1h["timestamps"]
    htf_dir = np.ones(n); h_idx = 0
    for i in range(n):
        while h_idx < len(h_ts)-1 and h_ts[h_idx+1] <= d["timestamps"][i]: h_idx += 1
        if h_idx < len(h_dirs): htf_dir[i] = h_dirs[h_idx]
    o,h,l,c,ts = d["opens"][:n],d["highs"][:n],d["lows"][:n],d["closes"][:n],d["timestamps"][:n]
    st_line, st_dir = calc_supertrend(h,l,c,entry_atr,entry_mult,entry_src)
    notional = fixed_size*leverage
    equity = starting_capital; position = 0; entry_price = 0.0; entry_bar_idx = 0
    trades = []; equity_curve = []; pending = None
    lookback = 4

    for i in range(start_bar, n):
        if pending is not None and i > start_bar:
            action = pending; pending = None; ep = o[i]
            if action == "close" and position != 0:
                fill = ep - ep*slippage*position
                pnl = (fill-entry_price)*position*(notional/entry_price) - notional*taker_fee
                trades.append({"pnl": pnl, "fee": notional*taker_fee, "direction": position,
                               "entry_price": entry_price, "exit_price": fill,
                               "entry_time": int(ts[entry_bar_idx]), "exit_time": int(ts[i]),
                               "bars_held": i-entry_bar_idx})
                equity += pnl; position = 0
            elif action.startswith("open") or action.startswith("flip"):
                if position != 0:
                    fill_c = ep - ep*slippage*position
                    pnl = (fill_c-entry_price)*position*(notional/entry_price) - notional*taker_fee
                    trades.append({"pnl": pnl, "fee": notional*taker_fee, "direction": position,
                                   "entry_price": entry_price, "exit_price": fill_c,
                                   "entry_time": int(ts[entry_bar_idx]), "exit_time": int(ts[i]),
                                   "bars_held": i-entry_bar_idx})
                    equity += pnl
                nd = 1 if "long" in action else -1
                equity -= notional*taker_fee
                position = nd; entry_price = ep + ep*slippage*nd; entry_bar_idx = i
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
        # ADX filters
        av = adx_values[i] if i < len(adx_values) else np.nan
        if np.isnan(av):
            if position != 0: pending = "close"
            continue
        if adx_min is not None and av < adx_min:
            if position != 0: pending = "close"
            continue
        if adx_max is not None and av > adx_max:
            if position != 0: pending = "close"
            continue
        if adx_rising and i >= lookback:
            prev_av = adx_values[i-lookback]
            if np.isnan(prev_av) or av <= prev_av:
                if position != 0: pending = "close"
                continue
        if position == 0: pending = "open_long" if nd == 1 else "open_short"
        elif position != nd: pending = "flip_long" if nd == 1 else "flip_short"

    if pending == "close" and position != 0:
        fill = c[n-1]*(1-slippage*position)
        pnl = (fill-entry_price)*position*(notional/entry_price) - notional*taker_fee
        trades.append({"pnl": pnl, "fee": notional*taker_fee, "direction": position,
                       "entry_price": entry_price, "exit_price": fill,
                       "entry_time": int(ts[entry_bar_idx]), "exit_time": int(ts[n-1]),
                       "bars_held": n-1-entry_bar_idx})
        equity += pnl
    return trades, equity_curve, equity


def s(trades, ec=None, cap=500.0):
    if not trades: return {"n":0,"pnl":0,"pf":0,"wr":0,"mdd":0,"fees":0}
    pnl = sum(t["pnl"] for t in trades)
    wins = [t for t in trades if t["pnl"]>0]
    gp = sum(t["pnl"] for t in wins); gl = abs(sum(t["pnl"] for t in trades if t["pnl"]<=0))
    pf = gp/gl if gl>0 else 9999
    mdd = 0
    if ec:
        ea = np.array(ec); pk = np.maximum.accumulate(ea)
        mdd = float(np.max((pk-ea)/pk*100)) if len(ea)>0 else 0
    fees = sum(t["fee"] for t in trades)
    return {"n":len(trades),"pnl":round(pnl,2),"pf":round(pf,2),
            "wr":round(len(wins)/len(trades)*100,1),"mdd":round(mdd,1),"fees":round(fees,2)}


def main():
    print("="*110)
    print("FINAL DEFINITIVE CONFIG")
    print("="*110)
    warmup = 200

    data = {}
    for name, f15, f1h in [("BTC","binance_btc_15m.json","binance_btc_1h.json"),
                            ("ETH","binance_eth_15m.json","binance_eth_1h.json"),
                            ("SOL","binance_sol_15m.json","binance_sol_1h.json")]:
        d15 = load_klines(f15); d1h = load_klines(f1h)
        adx = calc_adx(d15["highs"], d15["lows"], d15["closes"])
        data[name] = (d15, d1h, adx)

    # Asset-specific configs
    CONFIGS = {
        "BTC": {"adx_min": 15, "adx_max": None, "adx_rising": True},
        "ETH": {"adx_min": 20, "adx_max": 35, "adx_rising": True},
        "SOL": {"adx_min": 15, "adx_max": None, "adx_rising": True},
    }

    # ═══════════════════════════════════════════════════════════
    # 1. PER-ASSET RESULTS
    # ═══════════════════════════════════════════════════════════
    print(f"\n{'='*110}")
    print("1. PER-ASSET RESULTS — $42/asset, taker fees, full 730 days")
    print(f"{'='*110}")

    per_asset = {}
    per_asset_ec = {}

    print(f"\n  {'Asset':>5s} {'Filter':>30s} | {'Trades':>6s} {'P&L $':>8s} {'PF':>6s} {'Win%':>6s} {'MDD%':>6s} {'Fees':>7s} {'$/tr':>7s}")
    print(f"  {'─'*5} {'─'*30} | {'─'*6} {'─'*8} {'─'*6} {'─'*6} {'─'*6} {'─'*7} {'─'*7}")

    for name, cfg in CONFIGS.items():
        d15, d1h, adx = data[name]
        filt_label = f"ADX>={cfg['adx_min']}" + (f" & <={cfg['adx_max']}" if cfg['adx_max'] else "") + (" + rising" if cfg['adx_rising'] else "")
        trades, ec, eq = run_mtf(d15, d1h, 8, 4.0, "hlc3", 10, 4.0, "close",
                                  start_bar=warmup, end_bar=d15["n"], adx_values=adx,
                                  fixed_size=42.0, starting_capital=167.0, **cfg)
        st = s(trades, ec, 167.0)
        per_asset[name] = trades
        per_asset_ec[name] = ec
        for t in trades: t["asset"] = name
        avg = st["pnl"]/st["n"] if st["n"] else 0
        print(f"  {name:>5s} {filt_label:>30s} | {st['n']:>6d} ${st['pnl']:>7.0f} {st['pf']:>6.2f} {st['wr']:>5.1f}% {st['mdd']:>5.1f}% ${st['fees']:>6.0f} ${avg:>6.2f}")

    # ═══════════════════════════════════════════════════════════
    # 2. COMBINED PORTFOLIO
    # ═══════════════════════════════════════════════════════════
    print(f"\n{'='*110}")
    print("2. COMBINED PORTFOLIO")
    print(f"{'='*110}")

    all_trades = []
    for name in ["BTC","ETH","SOL"]:
        all_trades.extend(per_asset[name])

    min_len = min(len(ec) for ec in per_asset_ec.values())
    comb_ec = sum(np.array(ec[:min_len]) for ec in per_asset_ec.values())
    comb_pnl = float(comb_ec[-1]) - 500
    comb_st = s(all_trades, list(comb_ec), 500.0)

    print(f"\n  Combined: {comb_st['n']} trades, P&L ${comb_pnl:.0f} ({comb_pnl/500*100:.1f}%), "
          f"PF={comb_st['pf']:.2f}, Win={comb_st['wr']:.1f}%, MDD={comb_st['mdd']:.1f}%")

    # ═══════════════════════════════════════════════════════════
    # 3. MONTHLY BREAKDOWN
    # ═══════════════════════════════════════════════════════════
    print(f"\n{'='*110}")
    print("3. MONTHLY BREAKDOWN — Combined portfolio")
    print(f"{'='*110}")

    months = defaultdict(lambda: {"BTC":0,"ETH":0,"SOL":0,"total":0,"n":0})
    for t in all_trades:
        dt = datetime.fromtimestamp(t["exit_time"]/1000, tz=timezone.utc)
        m = dt.strftime("%Y-%m")
        months[m][t["asset"]] += t["pnl"]; months[m]["total"] += t["pnl"]; months[m]["n"] += 1

    print(f"\n  {'Month':>8s} | {'BTC':>6s} {'ETH':>6s} {'SOL':>6s} | {'Total':>7s} {'Cum':>8s} |")
    print(f"  {'─'*8} | {'─'*6} {'─'*6} {'─'*6} | {'─'*7} {'─'*8} |")
    cum = 0; pos = 0
    for m in sorted(months.keys()):
        d = months[m]; cum += d["total"]
        if d["total"] > 0: pos += 1
        bar_len = min(int(abs(d["total"])/10), 40)
        bar = ("+"*bar_len) if d["total"] > 0 else ("-"*bar_len)
        print(f"  {m:>8s} | ${d['BTC']:>5.0f} ${d['ETH']:>5.0f} ${d['SOL']:>5.0f} | ${d['total']:>6.0f} ${cum:>7.0f} | {bar}")
    print(f"\n  Positive months: {pos}/{len(months)} ({pos/len(months)*100:.0f}%)")

    # ═══════════════════════════════════════════════════════════
    # 4. WALK-FORWARD VALIDATION
    # ═══════════════════════════════════════════════════════════
    print(f"\n{'='*110}")
    print("4. WALK-FORWARD — Train 70% / Validate 30%")
    print(f"{'='*110}")

    for period_label, start_pct, end_pct in [("TRAIN (0-70%)", 0.0, 0.7), ("VALIDATE (70-100%)", 0.7, 1.0)]:
        print(f"\n  {period_label}:")
        period_trades = []
        period_ecs = {}
        for name, cfg in CONFIGS.items():
            d15, d1h, adx = data[name]
            n = d15["n"]
            sb = max(warmup, int(n*start_pct))
            eb = int(n*end_pct)
            trades, ec, eq = run_mtf(d15, d1h, 8, 4.0, "hlc3", 10, 4.0, "close",
                                      start_bar=sb, end_bar=eb, adx_values=adx,
                                      fixed_size=42.0, starting_capital=167.0, **cfg)
            st = s(trades, ec, 167.0)
            for t in trades: t["asset"] = name
            period_trades.extend(trades)
            period_ecs[name] = ec
            print(f"    {name}: {st['n']} trades, P&L ${st['pnl']:.0f}, PF={st['pf']:.2f}, Win={st['wr']:.1f}%, MDD={st['mdd']:.1f}%")

        if period_ecs:
            ml = min(len(ec) for ec in period_ecs.values())
            ce = sum(np.array(ec[:ml]) for ec in period_ecs.values())
            cp = float(ce[-1]) - 500
            cs = s(period_trades, list(ce), 500.0)
            print(f"    COMBINED: {cs['n']} trades, P&L ${cp:.0f}, PF={cs['pf']:.2f}, Win={cs['wr']:.1f}%, MDD={cs['mdd']:.1f}%")

    # ═══════════════════════════════════════════════════════════
    # 5. STARTING POINT SENSITIVITY
    # ═══════════════════════════════════════════════════════════
    print(f"\n{'='*110}")
    print("5. STARTING POINT SENSITIVITY — 6 points")
    print(f"{'='*110}")

    bars_per_120d = 120*24*4

    print(f"\n  {'#':>3s} {'Start':>12s} | {'BTC':>8s} {'ETH':>8s} {'SOL':>8s} | {'Combined':>9s} {'MDD%':>6s}")
    print(f"  {'─'*3} {'─'*12} | {'─'*8} {'─'*8} {'─'*8} | {'─'*9} {'─'*6}")

    for idx in range(6):
        sb = warmup + idx*bars_per_120d
        n_ref = data["BTC"][0]["n"]
        if sb >= n_ref - 1000: break
        start_dt = datetime.fromtimestamp(data["BTC"][0]["timestamps"][sb]/1000, tz=timezone.utc)

        ecs = {}; pnls = {}
        for name, cfg in CONFIGS.items():
            d15, d1h, adx = data[name]
            trades, ec, eq = run_mtf(d15, d1h, 8, 4.0, "hlc3", 10, 4.0, "close",
                                      start_bar=sb, end_bar=d15["n"], adx_values=adx,
                                      fixed_size=42.0, starting_capital=167.0, **cfg)
            ecs[name] = ec; pnls[name] = eq - 167.0

        ml = min(len(ec) for ec in ecs.values())
        ce = sum(np.array(ec[:ml]) for ec in ecs.values())
        cp = float(ce[-1]) - 500
        pk = np.maximum.accumulate(ce)
        mdd = float(np.max((pk-ce)/pk*100))

        print(f"  {idx+1:>3d} {start_dt.strftime('%Y-%m-%d'):>12s} | ${pnls['BTC']:>7.0f} ${pnls['ETH']:>7.0f} ${pnls['SOL']:>7.0f} | ${cp:>8.0f} {mdd:>5.1f}%")

    # ═══════════════════════════════════════════════════════════
    # 6. REMOVE TOP 5 TRADES
    # ═══════════════════════════════════════════════════════════
    print(f"\n{'='*110}")
    print("6. ROBUSTNESS — Remove top 5 trades from each asset")
    print(f"{'='*110}")

    for name in ["BTC","ETH","SOL"]:
        trades = per_asset[name]
        total = sum(t["pnl"] for t in trades)
        sorted_t = sorted(trades, key=lambda t: t["pnl"], reverse=True)
        top5_pnl = sum(t["pnl"] for t in sorted_t[:5])
        remaining = total - top5_pnl
        print(f"  {name}: Total ${total:.0f} | Top 5 = ${top5_pnl:.0f} ({top5_pnl/total*100:.0f}%) | "
              f"Without top 5: ${remaining:.0f} ({'PROFITABLE' if remaining > 0 else 'NEGATIVE'})")

    # Combined without top 5 per asset
    combined_minus_top5 = 0
    for name in ["BTC","ETH","SOL"]:
        trades = per_asset[name]
        sorted_t = sorted(trades, key=lambda t: t["pnl"], reverse=True)
        combined_minus_top5 += sum(t["pnl"] for t in sorted_t[5:])
    print(f"\n  Combined without top 5 per asset: ${combined_minus_top5:.0f} "
          f"({'PROFITABLE' if combined_minus_top5 > 0 else 'NEGATIVE'})")

    # ═══════════════════════════════════════════════════════════
    # 7. WITH vs WITHOUT ADX RISING REQUIREMENT
    # ═══════════════════════════════════════════════════════════
    print(f"\n{'='*110}")
    print("7. ADX RISING vs LEVEL-ONLY — per asset, $42, taker fees")
    print(f"{'='*110}")

    configs_compare = {
        "BTC": [
            ("ADX>=15 + rising", {"adx_min":15,"adx_max":None,"adx_rising":True}),
            ("ADX>=15 level only", {"adx_min":15,"adx_max":None,"adx_rising":False}),
            ("Unfiltered", {"adx_min":None,"adx_max":None,"adx_rising":False}),
        ],
        "ETH": [
            ("ADX 20-35 + rising", {"adx_min":20,"adx_max":35,"adx_rising":True}),
            ("ADX 20-35 level only", {"adx_min":20,"adx_max":35,"adx_rising":False}),
            ("Unfiltered", {"adx_min":None,"adx_max":None,"adx_rising":False}),
        ],
        "SOL": [
            ("ADX>=15 + rising", {"adx_min":15,"adx_max":None,"adx_rising":True}),
            ("ADX>=15 level only", {"adx_min":15,"adx_max":None,"adx_rising":False}),
            ("Unfiltered", {"adx_min":None,"adx_max":None,"adx_rising":False}),
        ],
    }

    for name in ["BTC","ETH","SOL"]:
        d15, d1h, adx = data[name]
        print(f"\n  {name}:")
        print(f"  {'Config':>25s} | {'Trades':>6s} {'P&L $':>8s} {'PF':>6s} {'Win%':>6s} {'MDD%':>6s} {'$/tr':>7s}")
        print(f"  {'─'*25} | {'─'*6} {'─'*8} {'─'*6} {'─'*6} {'─'*6} {'─'*7}")
        for label, cfg in configs_compare[name]:
            trades, ec, eq = run_mtf(d15, d1h, 8, 4.0, "hlc3", 10, 4.0, "close",
                                      start_bar=warmup, end_bar=d15["n"], adx_values=adx,
                                      fixed_size=42.0, starting_capital=167.0, **cfg)
            st = s(trades, ec, 167.0); avg = st["pnl"]/st["n"] if st["n"] else 0
            print(f"  {label:>25s} | {st['n']:>6d} ${st['pnl']:>7.0f} {st['pf']:>6.2f} {st['wr']:>5.1f}% {st['mdd']:>5.1f}% ${avg:>6.2f}")

    # ═══════════════════════════════════════════════════════════
    # BTC STANDALONE $125
    # ═══════════════════════════════════════════════════════════
    print(f"\n{'='*110}")
    print("BTC STANDALONE — $125 fixed, taker fees, full 730 days")
    print(f"{'='*110}")

    btc_d15, btc_d1h, btc_adx = data["BTC"]
    btc_configs = [
        ("No ADX filter", {"adx_min":None,"adx_max":None,"adx_rising":False}),
        ("ADX>=15 + rising", {"adx_min":15,"adx_max":None,"adx_rising":True}),
        ("ADX>=20 + rising", {"adx_min":20,"adx_max":None,"adx_rising":True}),
        ("ADX>=15 level only", {"adx_min":15,"adx_max":None,"adx_rising":False}),
        ("ADX>=20 level only", {"adx_min":20,"adx_max":None,"adx_rising":False}),
        ("ADX 20-35 + rising", {"adx_min":20,"adx_max":35,"adx_rising":True}),
    ]

    print(f"\n  {'Config':>25s} | {'Trades':>6s} {'P&L $':>8s} {'P&L %':>7s} {'PF':>6s} {'Win%':>6s} {'MDD%':>6s} {'$/tr':>7s}")
    print(f"  {'─'*25} | {'─'*6} {'─'*8} {'─'*7} {'─'*6} {'─'*6} {'─'*6} {'─'*7}")

    for label, cfg in btc_configs:
        trades, ec, eq = run_mtf(btc_d15, btc_d1h, 8, 4.0, "hlc3", 10, 4.0, "close",
                                  start_bar=warmup, end_bar=btc_d15["n"], adx_values=btc_adx,
                                  fixed_size=125.0, starting_capital=500.0, **cfg)
        st = s(trades, ec, 500.0); pnl = eq-500; avg = pnl/st["n"] if st["n"] else 0
        print(f"  {label:>25s} | {st['n']:>6d} ${pnl:>7.0f} {pnl/500*100:>6.1f}% {st['pf']:>6.2f} {st['wr']:>5.1f}% {st['mdd']:>5.1f}% ${avg:>6.2f}")

    # Walk-forward for BTC standalone best
    print(f"\n  BTC standalone walk-forward (ADX>=15 + rising, $125):")
    for period_label, sp, ep in [("TRAIN 70%", 0.0, 0.7), ("VALIDATE 30%", 0.7, 1.0)]:
        n = btc_d15["n"]; sb = max(warmup, int(n*sp)); eb = int(n*ep)
        trades, ec, eq = run_mtf(btc_d15, btc_d1h, 8, 4.0, "hlc3", 10, 4.0, "close",
                                  start_bar=sb, end_bar=eb, adx_values=btc_adx,
                                  fixed_size=125.0, starting_capital=500.0,
                                  adx_min=15, adx_rising=True)
        st = s(trades, ec, 500.0); pnl = eq-500
        print(f"    {period_label}: {st['n']} trades, P&L ${pnl:.0f}, PF={st['pf']:.2f}, Win={st['wr']:.1f}%, MDD={st['mdd']:.1f}%")


if __name__ == "__main__":
    main()

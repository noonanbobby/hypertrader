#!/usr/bin/env python3
"""
Compounding Scenarios — Fixed vs Semi-Compound vs Full Compound

Recovery ST(8, 4.0, α=5, θ=1.0) + ADX>=15 rising(4) + SQZ + 1H ST(10,4)
Strategy B exit (immediate on ST flip, re-entry with all filters)
$500 starting capital, 20x leverage, 0.045% taker, 0.01% slippage
"""

import json
import sys
import numpy as np
from pathlib import Path
from dataclasses import dataclass
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).parent))
from engine import calc_tr, calc_atr_rma, calc_supertrend, BacktestResult

DATA_DIR = Path(__file__).parent.parent / "backtest-data"


def calc_adx(highs, lows, closes, period=14):
    n=len(highs); plus_dm=np.zeros(n); minus_dm=np.zeros(n)
    for i in range(1,n):
        up=highs[i]-highs[i-1]; down=lows[i-1]-lows[i]
        if up>down and up>0: plus_dm[i]=up
        if down>up and down>0: minus_dm[i]=down
    tr=calc_tr(highs,lows,closes)
    def rma_s(data,p):
        out=np.zeros(n); out[p]=np.sum(data[1:p+1])
        for i in range(p+1,n): out[i]=out[i-1]-out[i-1]/p+data[i]
        return out
    s_tr=rma_s(tr,period); s_pdm=rma_s(plus_dm,period); s_mdm=rma_s(minus_dm,period)
    dx=np.zeros(n)
    for i in range(period,n):
        if s_tr[i]>0:
            pdi=100*s_pdm[i]/s_tr[i]; mdi=100*s_mdm[i]/s_tr[i]; t=pdi+mdi
            if t>0: dx[i]=100*abs(pdi-mdi)/t
    adx=np.full(n,np.nan); fv=period
    while fv<n and dx[fv]==0: fv+=1
    if fv+period>=n: return adx
    adx[fv+period-1]=np.mean(dx[fv:fv+period])
    for i in range(fv+period,n): adx[i]=(adx[i-1]*(period-1)+dx[i])/period
    return adx

def calc_squeeze(highs, lows, closes, bb_len=20, bb_mult=2.0, kc_len=20, kc_mult=1.5):
    n=len(closes); squeeze=np.full(n,False); tr=calc_tr(highs,lows,closes)
    for i in range(max(bb_len,kc_len)-1,n):
        w=closes[i-bb_len+1:i+1]; bb_b=np.mean(w); bb_s=np.std(w,ddof=0)
        ub=bb_b+bb_mult*bb_s; lb=bb_b-bb_mult*bb_s
        kc_b=np.mean(closes[i-kc_len+1:i+1]); kc_a=np.mean(tr[i-kc_len+1:i+1])
        uk=kc_b+kc_mult*kc_a; lk=kc_b-kc_mult*kc_a
        squeeze[i]=(lb>lk)and(ub<uk)
    return squeeze

def calc_recovery_supertrend(highs, lows, closes, atr_period=8, multiplier=4.0,
                              recovery_alpha=5.0, recovery_threshold=1.0):
    n=len(closes); src=(highs+lows)/2
    tr=calc_tr(highs,lows,closes); atr=calc_atr_rma(tr,atr_period)
    st_band=np.full(n,np.nan); direction=np.ones(n); switch_price=np.zeros(n)
    alpha=recovery_alpha/100.0; start=atr_period-1
    st_band[start]=src[start]-multiplier*atr[start]; direction[start]=1; switch_price[start]=closes[start]
    for i in range(start+1,n):
        if np.isnan(atr[i]):
            st_band[i]=st_band[i-1]; direction[i]=direction[i-1]; switch_price[i]=switch_price[i-1]; continue
        ub=src[i]+multiplier*atr[i]; lb=src[i]-multiplier*atr[i]; pb=st_band[i-1]; dev=recovery_threshold*atr[i]
        if direction[i-1]==1:
            loss=(switch_price[i-1]-closes[i])>dev
            tb=(alpha*closes[i]+(1-alpha)*pb) if loss else lb
            st_band[i]=max(tb,pb)
            if closes[i]<st_band[i]: direction[i]=-1; st_band[i]=ub; switch_price[i]=closes[i]
            else: direction[i]=1; switch_price[i]=switch_price[i-1]
        else:
            loss=(closes[i]-switch_price[i-1])>dev
            tb=(alpha*closes[i]+(1-alpha)*pb) if loss else ub
            st_band[i]=min(tb,pb)
            if closes[i]>st_band[i]: direction[i]=1; st_band[i]=lb; switch_price[i]=closes[i]
            else: direction[i]=-1; switch_price[i]=switch_price[i-1]
    return st_band, direction

def load_candles(filepath):
    data=json.load(open(filepath))
    return (np.array([c["open_time"] for c in data],dtype=np.int64),
            np.array([float(c["open"]) for c in data]),
            np.array([float(c["high"]) for c in data]),
            np.array([float(c["low"]) for c in data]),
            np.array([float(c["close"]) for c in data]),
            np.array([float(c["volume"]) for c in data]))

def align_1h_to_15m(ts_15m, dir_1h, ts_1h):
    aligned=np.full(len(ts_15m),np.nan); j=0
    for i in range(len(ts_15m)):
        while j<len(ts_1h)-1 and ts_1h[j+1]<=ts_15m[i]: j+=1
        if j<len(dir_1h): aligned[i]=dir_1h[j]
    return aligned


@dataclass
class Trade:
    entry_bar:int; entry_price:float; direction:int; size_usd:float
    exit_bar:int=0; exit_price:float=0.0; pnl:float=0.0; fees:float=0.0
    equity_after:float=0.0


def run_compound_bt(c15, o15, h15, l15, ts15, st_dir, st_dir_1h, adx, squeeze,
                     sizing_mode="fixed",  # "fixed", "semi", "full"
                     capital=500.0, fixed_margin=125.0, pct=0.25, lev=20.0,
                     fee_rate=0.00045, slip=0.0001, warmup=200,
                     adx_min=15.0, adx_lb=4):
    nn = len(c15)
    eff = max(0, warmup)
    equity = capital; pos = 0; ep = 0.0; eb = 0; ps = 0.0
    trades = []; ec_bars = []; ec_vals = []; pending = None

    # Semi-compound: recalculate every 30 days (2880 bars)
    semi_size = fixed_margin * lev  # initial
    last_rebalance_bar = eff

    def fl(p, d, ic):
        s = p * slip
        return (p-s if d==1 else p+s) if ic else (p+s if d==1 else p-s)

    def get_size(bar_idx):
        nonlocal semi_size, last_rebalance_bar
        if sizing_mode == "fixed":
            return fixed_margin * lev
        elif sizing_mode == "semi":
            if bar_idx - last_rebalance_bar >= 2880:  # 30 days
                semi_size = equity * pct * lev
                last_rebalance_bar = bar_idx
            return semi_size
        elif sizing_mode == "full":
            return equity * pct * lev
        return fixed_margin * lev

    def filters_pass(i):
        if np.isnan(st_dir_1h[i]) or st_dir[i] != st_dir_1h[i]: return False
        if np.isnan(adx[i]) or adx[i] < adx_min: return False
        pr = i - adx_lb
        if pr >= 0 and not np.isnan(adx[pr]) and adx[i] <= adx[pr]: return False
        if squeeze[i]: return False
        return True

    for i in range(eff, nn):
        if pending is not None and i > eff:
            act = pending; pending = None
            if act == "close" and pos != 0:
                f = fl(o15[i], pos, True)
                pnl_r = (f - ep) * pos * (ps / ep); fe = ps * fee_rate
                net = pnl_r - fe; equity += net
                trades.append(Trade(eb, ep, pos, ps, i, f, net, fe, equity))
                pos = 0; ps = 0.0
            elif act in ("ol", "os"):
                d = 1 if act == "ol" else -1
                f = fl(o15[i], d, False)
                ps = get_size(i)
                if ps < 10: ps = 10  # minimum
                fe = ps * fee_rate; equity -= fe
                pos = d; ep = f; eb = i
            elif act in ("fl", "fs"):
                if pos != 0:
                    f = fl(o15[i], pos, True)
                    pnl_r = (f - ep) * pos * (ps / ep); fe = ps * fee_rate
                    net = pnl_r - fe; equity += net
                    trades.append(Trade(eb, ep, pos, ps, i, f, net, fe, equity))
                d = 1 if act == "fl" else -1
                f2 = fl(o15[i], d, False)
                ps = get_size(i)
                if ps < 10: ps = 10
                fe2 = ps * fee_rate; equity -= fe2
                pos = d; ep = f2; eb = i

        if pos != 0:
            unr = (c15[i] - ep) * pos * (ps / ep)
            ec_vals.append(equity + unr)
        else:
            ec_vals.append(equity)
        ec_bars.append(i)

        if i >= nn - 1:
            if pos != 0: pending = "close"
            continue
        if np.isnan(st_dir[i]): continue
        curr = st_dir[i]; prev = st_dir[i-1] if i > 0 and not np.isnan(st_dir[i-1]) else curr
        flipped = curr != prev; sig = 1 if curr == 1 else -1

        # Strategy B
        if flipped and pos != 0 and sig != pos:
            if filters_pass(i): pending = "fl" if sig == 1 else "fs"
            else: pending = "close"
            continue
        if flipped and filters_pass(i):
            if pos == 0: pending = "ol" if sig == 1 else "os"
            elif pos != sig: pending = "fl" if sig == 1 else "fs"

    # Close remaining
    if pos != 0 and pending == "close":
        f = fl(c15[nn-1], pos, True)
        pnl_r = (f - ep) * pos * (ps / ep); fe = ps * fee_rate
        net = pnl_r - fe; equity += net
        trades.append(Trade(eb, ep, pos, ps, nn-1, f, net, fe, equity))
        if ec_vals: ec_vals[-1] = equity

    return equity, trades, ec_bars, ec_vals


def main():
    print("=" * 100)
    print("  COMPOUNDING SCENARIOS — Fixed vs Semi vs Full")
    print("  Recovery ST(8,4,α=5,θ=1.0) + Filters | Strategy B exit")
    print("  $500 start | 20x leverage | 0.045% taker | 0.01% slippage")
    print("=" * 100)

    ts15, o15, h15, l15, c15, v15 = load_candles(DATA_DIR / "binance_btc_15m.json")
    ts1h, o1h, h1h, l1h, c1h, v1h = load_candles(DATA_DIR / "binance_btc_1h.json")

    _, st_dir = calc_recovery_supertrend(h15, l15, c15, 8, 4.0, 5.0, 1.0)
    adx_arr = calc_adx(h15, l15, c15, 14)
    squeeze_arr = calc_squeeze(h15, l15, c15, 20, 2.0, 20, 1.5)
    _, st_dir_1h_raw = calc_supertrend(h1h, l1h, c1h, 10, 4.0, "close")
    st_dir_1h = align_1h_to_15m(ts15, st_dir_1h_raw, ts1h)

    scenarios = [
        ("A: Fixed $125", "fixed"),
        ("B: Semi (30-day)", "semi"),
        ("C: Full Compound", "full"),
    ]

    all_results = {}
    for name, mode in scenarios:
        eq, trades, bars, vals = run_compound_bt(
            c15, o15, h15, l15, ts15, st_dir, st_dir_1h, adx_arr, squeeze_arr,
            sizing_mode=mode, capital=500.0, fixed_margin=125.0, pct=0.25, lev=20.0,
        )
        all_results[mode] = {"equity": eq, "trades": trades, "bars": bars, "vals": vals, "name": name}

    # ═══════════════════════════════════════════════════
    # SUMMARY TABLE
    # ═══════════════════════════════════════════════════

    print(f"\n{'═'*100}")
    print(f"  RESULTS SUMMARY")
    print(f"{'═'*100}")

    w = 28
    print(f"\n  {'Metric':<24} {'A: Fixed $125':<{w}} {'B: Semi (30-day)':<{w}} {'C: Full Compound':<{w}}")
    print(f"  {'─'*22}  {'─'*(w-2)}  {'─'*(w-2)}  {'─'*(w-2)}")

    for mode_key in ["fixed", "semi", "full"]:
        r = all_results[mode_key]
        # Pre-compute stats
        r["total_return"] = (r["equity"] - 500) / 500 * 100
        r["num_trades"] = len(r["trades"])
        if r["trades"]:
            r["worst_loss"] = min(t.pnl for t in r["trades"])
            r["best_win"] = max(t.pnl for t in r["trades"])
            r["total_fees"] = sum(t.fees for t in r["trades"])
            wins = [t for t in r["trades"] if t.pnl > 0]
            losses = [t for t in r["trades"] if t.pnl <= 0]
            r["win_rate"] = len(wins) / len(r["trades"]) * 100
            gp = sum(t.pnl for t in wins); gl = abs(sum(t.pnl for t in losses))
            r["pf"] = gp / gl if gl > 0 else float('inf')
            r["avg_size"] = np.mean([t.size_usd for t in r["trades"]])
        else:
            r["worst_loss"] = 0; r["best_win"] = 0; r["total_fees"] = 0
            r["win_rate"] = 0; r["pf"] = 0; r["avg_size"] = 0

        if r["vals"]:
            ec = np.array(r["vals"])
            pk = np.maximum.accumulate(ec)
            dd = (pk - ec) / pk
            r["mdd"] = float(np.max(dd)) * 100
            # Find worst drawdown $ amount
            dd_dollar = pk - ec
            r["mdd_dollar"] = float(np.max(dd_dollar))
        else:
            r["mdd"] = 0; r["mdd_dollar"] = 0

    def row(label, key, fmt_fn=None):
        vals = []
        for m in ["fixed", "semi", "full"]:
            v = all_results[m][key]
            if fmt_fn:
                vals.append(fmt_fn(v))
            else:
                vals.append(str(v))
        print(f"  {label:<24} {vals[0]:<{w}} {vals[1]:<{w}} {vals[2]:<{w}}")

    row("Starting Capital", "equity", lambda _: "$500.00")
    row("Ending Capital", "equity", lambda v: f"${v:,.2f}")
    row("Total Return", "total_return", lambda v: f"{v:+,.1f}%")
    row("Profit Factor", "pf", lambda v: f"{v:.2f}" if v < 9999 else "INF")
    row("Win Rate", "win_rate", lambda v: f"{v:.1f}%")
    row("Max Drawdown %", "mdd", lambda v: f"{v:.1f}%")
    row("Max Drawdown $", "mdd_dollar", lambda v: f"${v:,.2f}")
    row("Worst Single Loss", "worst_loss", lambda v: f"${v:,.2f}")
    row("Best Single Win", "best_win", lambda v: f"${v:+,.2f}")
    row("Total Trades", "num_trades", lambda v: str(v))
    row("Total Fees", "total_fees", lambda v: f"${v:,.2f}")
    row("Avg Position Size", "avg_size", lambda v: f"${v:,.0f}")

    # ═══════════════════════════════════════════════════
    # MONTHLY EQUITY CURVE
    # ═══════════════════════════════════════════════════

    print(f"\n\n{'═'*100}")
    print(f"  MONTHLY EQUITY CURVE")
    print(f"{'═'*100}")

    # Build monthly snapshots
    # Each bar is 15 min. 1 month ≈ 2880 bars
    month_bars = 2880

    # Get date from timestamp
    def bar_to_month(bar_idx):
        if bar_idx < len(ts15):
            ts_ms = ts15[bar_idx]
            dt = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
            return dt.strftime("%Y-%m")
        return "?"

    # Sample equity at month boundaries
    print(f"\n  {'Month':<12}", end="")
    for name, mode in scenarios:
        print(f" {name:<20}", end="")
    print()
    print(f"  {'─'*10}  " + "  ".join(["─" * 18] * 3))

    warmup = 200
    total_bars = len(c15)
    month_idx = 0
    bar = warmup

    while bar < total_bars:
        month_label = bar_to_month(bar)

        print(f"  {month_label:<12}", end="")
        for _, mode in scenarios:
            r = all_results[mode]
            # Find closest equity value to this bar
            if r["bars"]:
                # Binary search for closest bar
                idx = np.searchsorted(r["bars"], bar)
                if idx >= len(r["vals"]):
                    idx = len(r["vals"]) - 1
                eq = r["vals"][idx]
                print(f" ${eq:>12,.2f}        ", end="")
            else:
                print(f" {'N/A':>12}        ", end="")
        print()

        bar += month_bars
        month_idx += 1

    # Final
    print(f"  {'FINAL':<12}", end="")
    for _, mode in scenarios:
        r = all_results[mode]
        print(f" ${r['equity']:>12,.2f}        ", end="")
    print()

    # ═══════════════════════════════════════════════════
    # TRADE SIZE PROGRESSION (for compound modes)
    # ═══════════════════════════════════════════════════

    print(f"\n\n{'═'*100}")
    print(f"  POSITION SIZE PROGRESSION")
    print(f"{'═'*100}")

    for name, mode in scenarios:
        r = all_results[mode]
        if not r["trades"]:
            continue
        trades = r["trades"]
        n_trades = len(trades)

        sizes = [t.size_usd for t in trades]
        # Show first 5, middle, last 5
        print(f"\n  {name}:")
        print(f"    First 5 trades:  {', '.join(f'${s:,.0f}' for s in sizes[:5])}")
        if n_trades > 10:
            mid = n_trades // 2
            print(f"    Middle trades:   {', '.join(f'${s:,.0f}' for s in sizes[mid-2:mid+3])}")
        print(f"    Last 5 trades:   {', '.join(f'${s:,.0f}' for s in sizes[-5:])}")
        print(f"    Min: ${min(sizes):,.0f} | Max: ${max(sizes):,.0f} | Avg: ${np.mean(sizes):,.0f}")

    # ═══════════════════════════════════════════════════
    # RISK ANALYSIS
    # ═══════════════════════════════════════════════════

    print(f"\n\n{'═'*100}")
    print(f"  RISK ANALYSIS — Worst Consecutive Losses")
    print(f"{'═'*100}")

    for name, mode in scenarios:
        r = all_results[mode]
        trades = r["trades"]
        if not trades:
            continue

        # Find worst consecutive loss streak
        max_streak = 0; curr_streak = 0; max_streak_pnl = 0; curr_streak_pnl = 0
        worst_3 = []

        for t in trades:
            if t.pnl <= 0:
                curr_streak += 1
                curr_streak_pnl += t.pnl
                if curr_streak > max_streak:
                    max_streak = curr_streak
                    max_streak_pnl = curr_streak_pnl
            else:
                curr_streak = 0
                curr_streak_pnl = 0

        # Worst 3 trades
        sorted_trades = sorted(trades, key=lambda t: t.pnl)[:3]

        print(f"\n  {name}:")
        print(f"    Worst loss streak: {max_streak} trades, total ${max_streak_pnl:,.2f}")
        print(f"    Worst 3 trades: {', '.join(f'${t.pnl:,.2f}' for t in sorted_trades)}")

        # Equity at worst point
        if r["vals"]:
            min_eq = min(r["vals"])
            print(f"    Lowest equity point: ${min_eq:,.2f} ({(min_eq-500)/500*100:+.1f}% from start)")

    print(f"\n{'═'*100}")
    print(f"  RECOMMENDATION")
    print(f"{'═'*100}")

    fixed = all_results["fixed"]
    semi = all_results["semi"]
    full = all_results["full"]

    print(f"\n  Fixed:  ${fixed['equity']:>10,.2f} final ({fixed['total_return']:>+7.1f}%) | MDD {fixed['mdd']:.1f}% | Worst ${fixed['worst_loss']:>8,.2f}")
    print(f"  Semi:   ${semi['equity']:>10,.2f} final ({semi['total_return']:>+7.1f}%) | MDD {semi['mdd']:.1f}% | Worst ${semi['worst_loss']:>8,.2f}")
    print(f"  Full:   ${full['equity']:>10,.2f} final ({full['total_return']:>+7.1f}%) | MDD {full['mdd']:.1f}% | Worst ${full['worst_loss']:>8,.2f}")

    print(f"\n{'═'*100}")


if __name__ == "__main__":
    main()

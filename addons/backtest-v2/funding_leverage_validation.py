#!/usr/bin/env python3
"""
Production Validation — Funding Rates + Leverage Levels

Recovery ST(8, 4.0, α=5, θ=1.0) + ADX>=15 rising(4) + SQZ + 1H ST(10,4)
Strategy B exit (immediate on ST flip, re-entry with all filters)

Additions:
  1. Funding rate: 0.01% every 8 hours on full notional while in position
  2. Three leverage levels: 5x, 10x, 20x
  3. Semi-compound (30-day rebalance, 25% of equity) at $5,000 start

Each gets full validation: 730-day, walk-forward, 6 starts, robustness.
"""

import json
import sys
import numpy as np
from pathlib import Path
from dataclasses import dataclass

sys.path.insert(0, str(Path(__file__).parent))
from engine import calc_tr, calc_atr_rma, calc_supertrend, BacktestResult

DATA_DIR = Path(__file__).parent.parent / "backtest-data"

# Funding: 0.01% every 8 hours = every 32 bars (32 × 15min = 8h)
FUNDING_RATE = 0.0001  # 0.01%
FUNDING_INTERVAL_BARS = 32  # 8 hours in 15m bars


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


# ═══════════════════════════════════════════════════════════════
# ENGINE WITH FUNDING
# ═══════════════════════════════════════════════════════════════

@dataclass
class Trade:
    entry_bar:int; entry_price:float; direction:int; size_usd:float
    exit_bar:int=0; exit_price:float=0.0; pnl:float=0.0
    fees:float=0.0; funding:float=0.0; equity_after:float=0.0
    bars_held:int=0


def run_bt(c15, o15, h15, l15, ts15, st_dir, st_dir_1h, adx, squeeze,
           start_bar=0, end_bar=-1, capital=500.0,
           sizing_mode="fixed", fixed_margin=125.0, pct=0.25, lev=10.0,
           fee_rate=0.00045, slip=0.0001, warmup=200,
           adx_min=15.0, adx_lb=4):

    nn = len(c15) if end_bar < 0 else end_bar
    eff = max(start_bar, warmup)
    equity = capital; pos = 0; ep = 0.0; eb = 0; ps = 0.0
    trades = []; ec = []; pending = None
    total_funding = 0.0
    bars_in_pos = 0  # count bars since entry for funding
    last_funding_bar = 0  # last bar funding was charged

    # Semi-compound state
    semi_size = fixed_margin * lev
    last_rebalance_bar = eff

    def fl(p, d, ic):
        s = p * slip
        return (p-s if d==1 else p+s) if ic else (p+s if d==1 else p-s)

    def get_size(bar_idx):
        nonlocal semi_size, last_rebalance_bar
        if sizing_mode == "fixed":
            return fixed_margin * lev
        elif sizing_mode == "semi":
            if bar_idx - last_rebalance_bar >= 2880:
                semi_size = max(10, equity * pct * lev)
                last_rebalance_bar = bar_idx
            return semi_size
        elif sizing_mode == "full":
            return max(10, equity * pct * lev)
        return fixed_margin * lev

    def filters_pass(i):
        if np.isnan(st_dir_1h[i]) or st_dir[i] != st_dir_1h[i]: return False
        if np.isnan(adx[i]) or adx[i] < adx_min: return False
        pr = i - adx_lb
        if pr >= 0 and not np.isnan(adx[pr]) and adx[i] <= adx[pr]: return False
        if squeeze[i]: return False
        return True

    trade_funding_accum = 0.0  # funding accumulated for current trade

    for i in range(eff, nn):
        # Execute pending
        if pending is not None and i > eff:
            act = pending; pending = None
            if act == "close" and pos != 0:
                f = fl(o15[i], pos, True)
                pnl_r = (f - ep) * pos * (ps / ep); fe = ps * fee_rate
                net = pnl_r - fe - trade_funding_accum
                equity += pnl_r - fe  # funding already deducted bar-by-bar
                held = i - eb
                trades.append(Trade(eb, ep, pos, ps, i, f, net, fe, trade_funding_accum, equity, held))
                pos = 0; ps = 0.0; trade_funding_accum = 0.0
            elif act in ("ol", "os"):
                d = 1 if act == "ol" else -1
                f = fl(o15[i], d, False)
                ps = get_size(i)
                fe = ps * fee_rate; equity -= fe
                pos = d; ep = f; eb = i; last_funding_bar = i; trade_funding_accum = 0.0
            elif act in ("fl", "fs"):
                if pos != 0:
                    f = fl(o15[i], pos, True)
                    pnl_r = (f - ep) * pos * (ps / ep); fe = ps * fee_rate
                    net = pnl_r - fe - trade_funding_accum
                    equity += pnl_r - fe
                    held = i - eb
                    trades.append(Trade(eb, ep, pos, ps, i, f, net, fe, trade_funding_accum, equity, held))
                d = 1 if act == "fl" else -1
                f2 = fl(o15[i], d, False)
                ps = get_size(i)
                fe2 = ps * fee_rate; equity -= fe2
                pos = d; ep = f2; eb = i; last_funding_bar = i; trade_funding_accum = 0.0

        # Funding charge: every 32 bars (8 hours) while in position
        if pos != 0 and (i - last_funding_bar) >= FUNDING_INTERVAL_BARS:
            funding_cost = ps * FUNDING_RATE
            equity -= funding_cost
            total_funding += funding_cost
            trade_funding_accum += funding_cost
            last_funding_bar = i

        # MTM equity
        if pos != 0:
            unr = (c15[i] - ep) * pos * (ps / ep)
            ec.append(equity + unr)
        else:
            ec.append(equity)

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
        net = pnl_r - fe - trade_funding_accum
        equity += pnl_r - fe
        held = nn - 1 - eb
        trades.append(Trade(eb, ep, pos, ps, nn-1, f, net, fe, trade_funding_accum, equity, held))
        if ec: ec[-1] = equity

    # Stats
    r = BacktestResult(config=None); r.trades = trades; r.equity_curve = ec
    r.num_trades = len(trades); r.final_equity = equity
    r.total_pnl = equity - capital; r.total_fees = sum(t.fees for t in trades)
    if trades:
        wins = [t for t in trades if t.pnl > 0]; losses = [t for t in trades if t.pnl <= 0]
        r.win_rate = len(wins) / len(trades) * 100
        gp = sum(t.pnl for t in wins); gl = abs(sum(t.pnl for t in losses))
        r.profit_factor = gp / gl if gl > 0 else float('inf')
    if ec:
        e = np.array(ec); pk = np.maximum.accumulate(e)
        dd = (pk - e) / pk; r.max_drawdown_pct = float(np.max(dd)) * 100
        if len(e) > 1:
            ret = np.diff(e) / e[:-1]
            if np.std(ret) > 0:
                r.sharpe_ratio = float(np.mean(ret) / np.std(ret) * np.sqrt(35040))

    # Extra stats
    r._total_funding = total_funding
    r._avg_hold_bars = np.mean([t.bars_held for t in trades]) if trades else 0
    r._worst_trade = min(t.pnl for t in trades) if trades else 0
    r._best_trade = max(t.pnl for t in trades) if trades else 0
    return r


def fp(v): return f"{v:.2f}" if v < 9999 else "INF"


def run_validation(label, c15, o15, h15, l15, ts15, st_dir, st_dir_1h, adx, squeeze,
                    h1h, l1h, c1h, ts1h, **bt_kwargs):
    """Run full validation suite, return summary dict."""
    # Full
    full = run_bt(c15, o15, h15, l15, ts15, st_dir, st_dir_1h, adx, squeeze, **bt_kwargs)

    # Walk-forward
    split = int(len(c15) * 0.7)
    wf = run_bt(c15, o15, h15, l15, ts15, st_dir, st_dir_1h, adx, squeeze,
                start_bar=split, **bt_kwargs)

    # 6 starting points
    seg = len(c15) // 6; sp = 0
    for s in range(6):
        r = run_bt(c15, o15, h15, l15, ts15, st_dir, st_dir_1h, adx, squeeze,
                   start_bar=s*seg, **bt_kwargs)
        if r.total_pnl > 0: sp += 1

    # Robustness
    rob_pass = 0; rob_total = 0
    base_capital = bt_kwargs.get("capital", 500.0)
    base_fixed = bt_kwargs.get("fixed_margin", 125.0)
    for af in [0.8, 1.0, 1.2]:
        for mf in [0.8, 1.0, 1.2]:
            if af == 1.0 and mf == 1.0: continue
            rob_total += 1
            atr_v = max(2, int(round(8*af))); mult_v = round(4.0*mf, 1)
            _, sd = calc_recovery_supertrend(h15, l15, c15, atr_v, mult_v, 5.0, 1.0)
            adx_v = calc_adx(h15, l15, c15, 14)
            _, sd1h = calc_supertrend(h1h, l1h, c1h, 10, 4.0, "close")
            sd1h_a = align_1h_to_15m(ts15, sd1h, ts1h)
            tr = run_bt(c15, o15, h15, l15, ts15, sd, sd1h_a, adx_v, squeeze, **bt_kwargs)
            if tr.profit_factor > 1.0: rob_pass += 1

    return {
        "label": label,
        "trades": full.num_trades, "wr": full.win_rate, "pf": full.profit_factor,
        "pnl": full.total_pnl, "final": full.final_equity,
        "mdd": full.max_drawdown_pct, "sharpe": full.sharpe_ratio,
        "fees": full.total_fees, "funding": full._total_funding,
        "avg_hold_h": full._avg_hold_bars * 0.25,  # bars × 15min / 60
        "worst": full._worst_trade, "best": full._best_trade,
        "wf_pf": wf.profit_factor, "wf_mdd": wf.max_drawdown_pct,
        "sp": sp, "rob": rob_pass, "rob_t": rob_total,
    }


def main():
    print("=" * 120)
    print("  PRODUCTION VALIDATION — Funding Rates + Leverage Levels")
    print("  Recovery ST(8,4,α=5,θ=1.0) + ADX>=15 rising(4) + SQZ + 1H | Strategy B exit")
    print("  Funding: 0.01% per 8 hours on notional | Taker: 0.045% | Slippage: 0.01%")
    print("=" * 120)

    ts15, o15, h15, l15, c15, v15 = load_candles(DATA_DIR / "binance_btc_15m.json")
    ts1h, o1h, h1h, l1h, c1h, v1h = load_candles(DATA_DIR / "binance_btc_1h.json")
    print(f"  Data: {len(c15)} 15m bars ({len(c15)//96} days)\n")

    _, st_dir = calc_recovery_supertrend(h15, l15, c15, 8, 4.0, 5.0, 1.0)
    adx_arr = calc_adx(h15, l15, c15, 14)
    squeeze_arr = calc_squeeze(h15, l15, c15, 20, 2.0, 20, 1.5)
    _, st_dir_1h_raw = calc_supertrend(h1h, l1h, c1h, 10, 4.0, "close")
    st_dir_1h = align_1h_to_15m(ts15, st_dir_1h_raw, ts1h)

    all_results = []

    # ═══════════════════════════════════════════════════
    # PART 1: Fixed sizing at 3 leverage levels ($500 start)
    # ═══════════════════════════════════════════════════

    print("  Running fixed sizing at 5x, 10x, 20x...")
    for lev in [5, 10, 20]:
        margin = 125.0
        r = run_validation(
            f"Fixed {lev}x", c15, o15, h15, l15, ts15, st_dir, st_dir_1h, adx_arr, squeeze_arr,
            h1h, l1h, c1h, ts1h,
            capital=500.0, sizing_mode="fixed", fixed_margin=margin, lev=float(lev),
        )
        all_results.append(r)
        print(f"    {lev}x: PF={fp(r['pf'])} P&L=${r['pnl']:+,.0f} MDD={r['mdd']:.1f}% Funding=${r['funding']:.0f}")

    # ═══════════════════════════════════════════════════
    # PART 2: Semi-compound at 3 leverage levels ($5,000 start)
    # ═══════════════════════════════════════════════════

    print("\n  Running semi-compound at 5x, 10x, 20x ($5,000 start)...")
    for lev in [5, 10, 20]:
        r = run_validation(
            f"Semi {lev}x", c15, o15, h15, l15, ts15, st_dir, st_dir_1h, adx_arr, squeeze_arr,
            h1h, l1h, c1h, ts1h,
            capital=5000.0, sizing_mode="semi", pct=0.25, lev=float(lev),
        )
        all_results.append(r)
        print(f"    {lev}x: PF={fp(r['pf'])} P&L=${r['pnl']:+,.0f} MDD={r['mdd']:.1f}% Funding=${r['funding']:.0f}")

    # ═══════════════════════════════════════════════════
    # MASTER TABLE
    # ═══════════════════════════════════════════════════

    print(f"\n\n{'═'*140}")
    print(f"  MASTER RESULTS TABLE")
    print(f"{'═'*140}")

    w = 20
    names = [r["label"] for r in all_results]
    hdr = f"  {'Metric':<20}"
    for n in names: hdr += f" {n:<{w}}"
    print(hdr)
    print(f"  {'─'*18}  " + "  ".join(["─"*(w-2)] * len(names)))

    def row(label, key, fmt_fn):
        r = f"  {label:<20}"
        for res in all_results: r += f" {fmt_fn(res[key]):<{w}}"
        return r

    print(row("Starting Capital", "label", lambda _: "$500" if "Fixed" in _ else "$5,000"))
    print(row("Final Equity", "final", lambda v: f"${v:,.0f}"))
    print(row("Total P&L", "pnl", lambda v: f"${v:+,.0f}"))
    print(row("Total Return", "pnl",
              lambda v: f"{v/500*100:+.0f}%" if abs(v) < 50000 else f"{v/5000*100:+.0f}%"))
    print(f"  {'─'*18}  " + "  ".join(["─"*(w-2)] * len(names)))
    print(row("Profit Factor", "pf", lambda v: fp(v)))
    print(row("Win Rate", "wr", lambda v: f"{v:.1f}%"))
    print(row("Trades", "trades", lambda v: str(v)))
    print(row("Avg Hold", "avg_hold_h", lambda v: f"{v:.1f}h"))
    print(f"  {'─'*18}  " + "  ".join(["─"*(w-2)] * len(names)))
    print(row("Max Drawdown", "mdd", lambda v: f"{v:.1f}%"))
    print(row("Sharpe", "sharpe", lambda v: f"{v:.2f}"))
    print(row("Worst Trade", "worst", lambda v: f"${v:,.2f}"))
    print(row("Best Trade", "best", lambda v: f"${v:+,.2f}"))
    print(f"  {'─'*18}  " + "  ".join(["─"*(w-2)] * len(names)))
    print(row("Trading Fees", "fees", lambda v: f"${v:,.0f}"))
    print(row("Funding Paid", "funding", lambda v: f"${v:,.0f}"))

    # Total cost
    print(f"  {'Total Costs':<20}", end="")
    for res in all_results:
        tc = res["fees"] + res["funding"]
        print(f" ${tc:>14,.0f}     ", end="")
    print()

    # Cost as % of gross profit
    print(f"  {'Cost % of Gross':<20}", end="")
    for res in all_results:
        tc = res["fees"] + res["funding"]
        gross = res["pnl"] + tc  # gross = net + costs
        pct = tc / gross * 100 if gross > 0 else 0
        print(f" {pct:>14.1f}%     ", end="")
    print()

    print(f"  {'─'*18}  " + "  ".join(["─"*(w-2)] * len(names)))
    print(row("WF Validate PF", "wf_pf", lambda v: fp(v)))
    print(row("WF Validate MDD", "wf_mdd", lambda v: f"{v:.1f}%"))
    print(row("6/6 Starts Prof.", "sp", lambda v: f"{v}/6"))
    print(row("Robust PF>1", "rob", lambda v: f"{v}/{all_results[0]['rob_t']}"))

    # Pass/fail
    print(f"  {'─'*18}  " + "  ".join(["─"*(w-2)] * len(names)))
    print(f"  {'Full PF > 1.0':<20}", end="")
    for r in all_results: print(f" {'PASS' if r['pf']>1 else 'FAIL':<{w}}", end="")
    print()
    print(f"  {'WF PF > 1.0':<20}", end="")
    for r in all_results: print(f" {'PASS' if r['wf_pf']>1 else 'FAIL':<{w}}", end="")
    print()
    print(f"  {'MDD < 50%':<20}", end="")
    for r in all_results: print(f" {'PASS' if r['mdd']<50 else 'FAIL':<{w}}", end="")
    print()
    print(f"  {'All checks pass':<20}", end="")
    for r in all_results:
        ok = r['pf']>1 and r['wf_pf']>1 and r['mdd']<50 and r['sp']>=5 and r['rob']>=5
        print(f" {'YES' if ok else 'NO':<{w}}", end="")
    print()

    # ═══════════════════════════════════════════════════
    # FUNDING IMPACT ANALYSIS
    # ═══════════════════════════════════════════════════

    print(f"\n\n{'═'*100}")
    print(f"  FUNDING IMPACT ANALYSIS")
    print(f"{'═'*100}")

    print(f"\n  Strategy B holds positions for an average of {all_results[0]['avg_hold_h']:.1f} hours.")
    print(f"  At 0.01% per 8 hours, each trade pays ~{all_results[0]['avg_hold_h']/8*0.01:.4f}% in funding.")
    print()

    for r in all_results:
        funding_pct = r["funding"] / (r["pnl"] + r["fees"] + r["funding"]) * 100 if (r["pnl"] + r["fees"] + r["funding"]) > 0 else 0
        fees_pct = r["fees"] / (r["pnl"] + r["fees"] + r["funding"]) * 100 if (r["pnl"] + r["fees"] + r["funding"]) > 0 else 0
        print(f"  {r['label']:<16}  Funding: ${r['funding']:>8,.2f} ({funding_pct:.1f}% of gross)  "
              f"Fees: ${r['fees']:>8,.2f} ({fees_pct:.1f}% of gross)  "
              f"Net P&L: ${r['pnl']:>+10,.2f}")

    # ═══════════════════════════════════════════════════
    # RECOMMENDATION
    # ═══════════════════════════════════════════════════

    print(f"\n\n{'═'*100}")
    print(f"  DEPLOYMENT RECOMMENDATION")
    print(f"{'═'*100}")

    # Find best passing config
    passing = [r for r in all_results if r['pf']>1 and r['wf_pf']>1 and r['mdd']<50 and r['sp']>=5]
    if passing:
        best = max(passing, key=lambda r: r['pf'])
        print(f"\n  Best risk-adjusted (passes all checks):")
        print(f"    {best['label']}")
        print(f"    PF={fp(best['pf'])}  P&L=${best['pnl']:+,.0f}  MDD={best['mdd']:.1f}%")
        print(f"    Sharpe={best['sharpe']:.2f}  WF PF={fp(best['wf_pf'])}  {best['sp']}/6 starts  {best['rob']}/{best['rob_t']} robust")
        print(f"    Funding drag: ${best['funding']:,.0f} ({best['funding']/(best['pnl']+best['fees']+best['funding'])*100:.1f}% of gross)")

    # Highest absolute return
    best_abs = max(all_results, key=lambda r: r['pnl'])
    print(f"\n  Highest absolute return:")
    print(f"    {best_abs['label']}")
    print(f"    PF={fp(best_abs['pf'])}  P&L=${best_abs['pnl']:+,.0f}  MDD={best_abs['mdd']:.1f}%")
    checks = "PASS" if (best_abs['pf']>1 and best_abs['wf_pf']>1 and best_abs['mdd']<50 and best_abs['sp']>=5) else "FAIL"
    print(f"    All checks: {checks}")

    print(f"\n{'═'*100}")


if __name__ == "__main__":
    main()

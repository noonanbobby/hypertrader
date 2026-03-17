#!/usr/bin/env python3
"""
Exit Logic Deep Dive — Analyzing the $425 gap between Strategy A and B

Q1: How long does B sit flat after exit? Distribution of flat periods.
Q2: Are the missed trades (while flat) profitable or losing?
Q3: Hybrid C — exit on ST flip, re-entry needs ST flip back + 1H only (drop ADX+SQZ on re-entry)
Q4: Hybrid D — exit on ST flip, re-entry needs ST flip back + ADX>=15 (drop rising + squeeze on re-entry)

Full validation on A, B, C, D side by side.
"""

import json
import sys
import numpy as np
from pathlib import Path
from dataclasses import dataclass, field

sys.path.insert(0, str(Path(__file__).parent))
from engine import calc_tr, calc_atr_rma, calc_supertrend, BacktestResult

DATA_DIR = Path(__file__).parent.parent / "backtest-data"


# ═══════════════════════════════════════════════════════════════
# INDICATORS
# ═══════════════════════════════════════════════════════════════

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
# ENGINE — supports modes A, B, C (1H only re-entry), D (ADX only re-entry)
# ═══════════════════════════════════════════════════════════════

@dataclass
class Trade:
    entry_bar:int; entry_price:float; direction:int; size_usd:float
    exit_bar:int=0; exit_price:float=0.0; pnl:float=0.0; fees:float=0.0
    reason:str=""; was_reentry:bool=False

def run_bt(c15, o15, h15, l15, ts15, st_dir, st_dir_1h, adx, squeeze,
           mode="A", start_bar=0, end_bar=-1, capital=500.0, fixed=125.0, lev=10.0,
           fee_rate=0.00045, slip=0.0001, warmup=200, adx_min=15.0, adx_lb=4):
    nn=len(c15) if end_bar<0 else end_bar
    eff=max(start_bar,warmup)
    equity=capital; pos=0; ep=0.0; eb=0; ps=0.0
    trades=[]; ec=[]; pending=None
    flat_since=-1  # bar when we went flat (for analysis)
    was_reentry=False

    def fl(p,d,ic):
        s=p*slip
        return (p-s if d==1 else p+s) if ic else (p+s if d==1 else p-s)

    def full_filters(i):
        """All filters: 1H + ADX>=min & rising + squeeze off"""
        if np.isnan(st_dir_1h[i]) or st_dir[i]!=st_dir_1h[i]: return False
        if np.isnan(adx[i]) or adx[i]<adx_min: return False
        pr=i-adx_lb
        if pr>=0 and not np.isnan(adx[pr]) and adx[i]<=adx[pr]: return False
        if squeeze[i]: return False
        return True

    def reentry_filters_C(i):
        """Hybrid C re-entry: ST flip back + 1H only"""
        if np.isnan(st_dir_1h[i]) or st_dir[i]!=st_dir_1h[i]: return False
        return True

    def reentry_filters_D(i):
        """Hybrid D re-entry: ST flip back + ADX>=15 (no rising, no squeeze)"""
        if np.isnan(st_dir_1h[i]) or st_dir[i]!=st_dir_1h[i]: return False
        if np.isnan(adx[i]) or adx[i]<adx_min: return False
        return True

    for i in range(eff,nn):
        if pending is not None and i>eff:
            act=pending; pending=None
            if act=="close" and pos!=0:
                f=fl(o15[i],pos,True); pnl_r=(f-ep)*pos*(ps/ep); fe=ps*fee_rate
                trades.append(Trade(eb,ep,pos,ps,i,f,pnl_r-fe,fe,"close",was_reentry))
                equity+=pnl_r-fe; pos=0; ps=0.0; flat_since=i; was_reentry=False
            elif act in ("ol","os"):
                d=1 if act=="ol" else -1; f=fl(o15[i],d,False); ps=fixed*lev; fe=ps*fee_rate; equity-=fe
                pos=d; ep=f; eb=i; was_reentry=(flat_since>=0)
            elif act in ("fl","fs"):
                if pos!=0:
                    f=fl(o15[i],pos,True); pnl_r=(f-ep)*pos*(ps/ep); fe=ps*fee_rate
                    trades.append(Trade(eb,ep,pos,ps,i,f,pnl_r-fe,fe,"flip",was_reentry))
                    equity+=pnl_r-fe
                d=1 if act=="fl" else -1; f2=fl(o15[i],d,False); ps=fixed*lev; fe2=ps*fee_rate; equity-=fe2
                pos=d; ep=f2; eb=i; was_reentry=False

        if pos!=0: ec.append(equity+(c15[i]-ep)*pos*(ps/ep))
        else: ec.append(equity)

        if i>=nn-1:
            if pos!=0: pending="close"
            continue
        if np.isnan(st_dir[i]): continue
        curr=st_dir[i]; prev=st_dir[i-1] if i>0 and not np.isnan(st_dir[i-1]) else curr
        flipped=curr!=prev; sig=1 if curr==1 else -1

        if mode=="A":
            if not flipped: continue
            if not full_filters(i): continue
            if pos==0: pending="ol" if sig==1 else "os"
            elif pos!=sig: pending="fl" if sig==1 else "fs"

        elif mode=="B":
            if flipped and pos!=0 and sig!=pos:
                if full_filters(i): pending="fl" if sig==1 else "fs"
                else: pending="close"
                continue
            if flipped and full_filters(i):
                if pos==0: pending="ol" if sig==1 else "os"
                elif pos!=sig: pending="fl" if sig==1 else "fs"

        elif mode=="C":
            # Exit on ST flip, re-entry needs ST flip + 1H only
            if flipped and pos!=0 and sig!=pos:
                if reentry_filters_C(i): pending="fl" if sig==1 else "fs"
                else: pending="close"
                continue
            if flipped and pos==0:
                # From flat: first entry needs full filters, re-entry needs 1H only
                if flat_since >= 0:
                    if reentry_filters_C(i): pending="ol" if sig==1 else "os"
                else:
                    if full_filters(i): pending="ol" if sig==1 else "os"
            elif flipped and pos!=sig:
                if reentry_filters_C(i): pending="fl" if sig==1 else "fs"

        elif mode=="D":
            # Exit on ST flip, re-entry needs ST flip + ADX>=15 (no rising, no squeeze)
            if flipped and pos!=0 and sig!=pos:
                if reentry_filters_D(i): pending="fl" if sig==1 else "fs"
                else: pending="close"
                continue
            if flipped and pos==0:
                if flat_since >= 0:
                    if reentry_filters_D(i): pending="ol" if sig==1 else "os"
                else:
                    if full_filters(i): pending="ol" if sig==1 else "os"
            elif flipped and pos!=sig:
                if reentry_filters_D(i): pending="fl" if sig==1 else "fs"

    if pos!=0 and pending=="close":
        f=fl(c15[nn-1],pos,True); pnl_r=(f-ep)*pos*(ps/ep); fe=ps*fee_rate
        trades.append(Trade(eb,ep,pos,ps,nn-1,f,pnl_r-fe,fe,"eod",was_reentry)); equity+=pnl_r-fe
        if ec: ec[-1]=equity

    r=BacktestResult(config=None); r.trades=trades; r.equity_curve=ec
    r.num_trades=len(trades); r.final_equity=equity; r.total_pnl=equity-capital
    r.total_fees=sum(t.fees for t in trades)
    if trades:
        wins=[t for t in trades if t.pnl>0]; losses=[t for t in trades if t.pnl<=0]
        r.win_rate=len(wins)/len(trades)*100
        gp=sum(t.pnl for t in wins); gl=abs(sum(t.pnl for t in losses))
        r.profit_factor=gp/gl if gl>0 else float('inf')
    if ec:
        e=np.array(ec); pk=np.maximum.accumulate(e); dd=(pk-e)/pk; r.max_drawdown_pct=float(np.max(dd))*100
        if len(e)>1:
            ret=np.diff(e)/e[:-1]
            if np.std(ret)>0: r.sharpe_ratio=float(np.mean(ret)/np.std(ret)*np.sqrt(35040))
    return r


def fp(v): return f"{v:.2f}" if v < 9999 else "INF"


# ═══════════════════════════════════════════════════════════════
# Q1 + Q2 ANALYSIS (run Strategy B, analyze flat periods)
# ═══════════════════════════════════════════════════════════════

def analyze_flat_periods(c15, o15, h15, l15, ts15, st_dir, st_dir_1h, adx, squeeze):
    """Run Strategy B and analyze what happens during flat periods."""
    nn = len(c15)
    warmup = 200; adx_min = 15.0; adx_lb = 4

    def full_filters(i):
        if np.isnan(st_dir_1h[i]) or st_dir[i] != st_dir_1h[i]: return False
        if np.isnan(adx[i]) or adx[i] < adx_min: return False
        pr = i - adx_lb
        if pr >= 0 and not np.isnan(adx[pr]) and adx[i] <= adx[pr]: return False
        if squeeze[i]: return False
        return True

    # Track: when does B exit (go flat), and when does it re-enter?
    pos = 0
    flat_periods = []  # (exit_bar, reentry_bar, bars_flat, exit_dir, reentry_dir)
    exit_bar = -1
    exit_dir = 0

    # Also track: what would have happened if we stayed in (like A)
    # For each flat period, simulate the price movement during that gap

    missed_trades = []  # (exit_bar, reentry_bar, price_at_exit, price_at_reentry, direction_if_stayed)

    for i in range(warmup, nn):
        if np.isnan(st_dir[i]): continue
        curr = st_dir[i]
        prev = st_dir[i-1] if i > 0 and not np.isnan(st_dir[i-1]) else curr
        flipped = curr != prev
        sig = 1 if curr == 1 else -1

        if flipped and pos != 0 and sig != pos:
            if full_filters(i):
                # Would flip directly — no flat period
                pos = sig
            else:
                # Goes flat
                exit_bar = i
                exit_dir = pos
                pos = 0
            continue

        if flipped and full_filters(i):
            if pos == 0 and exit_bar >= 0:
                # Re-entering from flat
                bars_flat = i - exit_bar
                flat_periods.append({
                    "exit_bar": exit_bar,
                    "reentry_bar": i,
                    "bars_flat": bars_flat,
                    "exit_dir": exit_dir,
                    "reentry_dir": sig,
                    "price_at_exit": c15[exit_bar],
                    "price_at_reentry": c15[i],
                })
                pos = sig
                exit_bar = -1
            elif pos == 0:
                pos = sig
            elif pos != sig:
                pos = sig

    return flat_periods


def analyze_missed_pnl(flat_periods, c15, o15):
    """For each flat period, calculate what P&L Strategy A would have earned."""
    results = []
    for fp_data in flat_periods:
        eb = fp_data["exit_bar"]
        rb = fp_data["reentry_bar"]
        exit_price = o15[eb + 1] if eb + 1 < len(o15) else c15[eb]  # A would still be in at exit bar
        reentry_price = o15[rb + 1] if rb + 1 < len(o15) else c15[rb]

        # Strategy A stays in the ORIGINAL direction during the flat period
        # The exit_dir is the direction A would hold
        direction = fp_data["exit_dir"]

        # What would the PnL be from staying in during the flat period?
        # A exits when filters pass for the opposite direction, which is the reentry_bar
        missed_pnl_pct = (reentry_price - exit_price) / exit_price * direction * 100

        results.append({
            **fp_data,
            "missed_pnl_pct": missed_pnl_pct,
            "profitable": missed_pnl_pct > 0,
        })
    return results


# ═══════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════

def main():
    print("=" * 100)
    print("  EXIT LOGIC DEEP DIVE — Why does A make $425 more than B?")
    print("  Recovery ST(8, 4.0, α=5, θ=1.0) + ADX>=15 rising(4) + SQZ + 1H")
    print("=" * 100)

    ts15,o15,h15,l15,c15,v15 = load_candles(DATA_DIR/"binance_btc_15m.json")
    ts1h,o1h,h1h,l1h,c1h,v1h = load_candles(DATA_DIR/"binance_btc_1h.json")

    _,st_dir = calc_recovery_supertrend(h15,l15,c15,8,4.0,5.0,1.0)
    adx = calc_adx(h15,l15,c15,14)
    squeeze = calc_squeeze(h15,l15,c15,20,2.0,20,1.5)
    _,st_dir_1h_raw = calc_supertrend(h1h,l1h,c1h,10,4.0,"close")
    st_dir_1h = align_1h_to_15m(ts15,st_dir_1h_raw,ts1h)

    # ═══════════════════════════════════════════════════
    # QUESTION 1: Flat period distribution
    # ═══════════════════════════════════════════════════

    flat_periods = analyze_flat_periods(c15, o15, h15, l15, ts15, st_dir, st_dir_1h, adx, squeeze)

    print(f"\n{'═'*80}")
    print(f"  Q1: HOW LONG DOES B SIT FLAT AFTER EXIT?")
    print(f"{'═'*80}")
    print(f"  Total flat periods (exits that go flat): {len(flat_periods)}")

    if flat_periods:
        bars = [fp["bars_flat"] for fp in flat_periods]
        print(f"  Average flat duration: {np.mean(bars):.1f} bars ({np.mean(bars)*15/60:.1f} hours)")
        print(f"  Median flat duration:  {np.median(bars):.0f} bars ({np.median(bars)*15/60:.1f} hours)")
        print(f"  Min: {min(bars)} bars ({min(bars)*15/60:.1f}h) | Max: {max(bars)} bars ({max(bars)*15/60:.1f}h)")

        # Distribution
        b1 = sum(1 for b in bars if b == 1)
        b2_5 = sum(1 for b in bars if 2 <= b <= 5)
        b6_20 = sum(1 for b in bars if 6 <= b <= 20)
        b20_100 = sum(1 for b in bars if 20 < b <= 100)
        b100p = sum(1 for b in bars if b > 100)

        total = len(bars)
        print(f"\n  Distribution:")
        print(f"    1 bar  (15 min):    {b1:>4} ({b1/total*100:>5.1f}%)")
        print(f"    2-5 bars (30m-1h):  {b2_5:>4} ({b2_5/total*100:>5.1f}%)")
        print(f"    6-20 bars (1.5-5h): {b6_20:>4} ({b6_20/total*100:>5.1f}%)")
        print(f"    21-100 bars (5-25h):{b20_100:>4} ({b20_100/total*100:>5.1f}%)")
        print(f"    100+ bars (25h+):   {b100p:>4} ({b100p/total*100:>5.1f}%)")

    # ═══════════════════════════════════════════════════
    # QUESTION 2: Are missed trades profitable?
    # ═══════════════════════════════════════════════════

    missed = analyze_missed_pnl(flat_periods, c15, o15)

    print(f"\n{'═'*80}")
    print(f"  Q2: ARE THE TRADES B MISSES (WHILE FLAT) ACTUALLY GOOD TRADES?")
    print(f"{'═'*80}")

    if missed:
        profitable = [m for m in missed if m["profitable"]]
        losing = [m for m in missed if not m["profitable"]]
        total_m = len(missed)

        print(f"  Total flat-period gaps analyzed: {total_m}")
        print(f"  If A stayed in during these gaps:")
        print(f"    Profitable: {len(profitable)} ({len(profitable)/total_m*100:.1f}%)")
        print(f"    Losing:     {len(losing)} ({len(losing)/total_m*100:.1f}%)")

        if profitable:
            avg_win_pct = np.mean([m["missed_pnl_pct"] for m in profitable])
            print(f"    Avg winning gap: +{avg_win_pct:.2f}% price move")
        if losing:
            avg_loss_pct = np.mean([m["missed_pnl_pct"] for m in losing])
            print(f"    Avg losing gap:  {avg_loss_pct:.2f}% price move")

        all_pnl_pcts = [m["missed_pnl_pct"] for m in missed]
        print(f"    Net avg gap PnL: {np.mean(all_pnl_pcts):+.3f}% per gap")
        print(f"    Total missed move: {sum(all_pnl_pcts):+.2f}%")

        # Break down by flat duration
        print(f"\n  Profitability by flat duration:")
        for label, lo, hi in [("1 bar", 1, 1), ("2-5 bars", 2, 5), ("6-20 bars", 6, 20),
                               ("21-100 bars", 21, 100), ("100+ bars", 100, 99999)]:
            subset = [m for m in missed if lo <= m["bars_flat"] <= hi]
            if subset:
                prof = sum(1 for m in subset if m["profitable"])
                avg = np.mean([m["missed_pnl_pct"] for m in subset])
                print(f"    {label:<15} {len(subset):>3} gaps | {prof}/{len(subset)} profitable ({prof/len(subset)*100:.0f}%) | avg {avg:+.3f}%")

    # ═══════════════════════════════════════════════════
    # QUESTION 3+4: Hybrid strategies — full validation
    # ═══════════════════════════════════════════════════

    modes = [
        ("A: Filter Exit", "A"),
        ("B: Immediate Exit", "B"),
        ("C: Re-entry 1H only", "C"),
        ("D: Re-entry ADX only", "D"),
    ]

    print(f"\n\n{'═'*110}")
    print(f"  Q3+Q4: HYBRID STRATEGIES — FULL VALIDATION")
    print(f"  A = Exit+entry need all filters")
    print(f"  B = Exit on ST flip, re-entry needs all filters")
    print(f"  C = Exit on ST flip, re-entry needs ST flip + 1H only")
    print(f"  D = Exit on ST flip, re-entry needs ST flip + ADX>=15 (no rising, no squeeze)")
    print(f"{'═'*110}")

    # Full 730-day
    full_results = {}
    for name, m in modes:
        full_results[m] = run_bt(c15,o15,h15,l15,ts15,st_dir,st_dir_1h,adx,squeeze,mode=m)

    w = 22
    def header():
        h = f"  {'Metric':<18}"
        for name, _ in modes: h += f" {name:<{w}}"
        return h
    def row(label, vals):
        r = f"  {label:<18}"
        for v in vals: r += f" {v:<{w}}"
        return r
    def divider():
        return f"  {'─'*16}  " + "  ".join(["─"*(w-2)] * len(modes))

    print(f"\n{'─'*110}")
    print(f"  Full Period (730 days)")
    print(f"{'─'*110}")
    print(header()); print(divider())
    print(row("Trades", [str(full_results[m].num_trades) for _,m in modes]))
    print(row("Win Rate", [f"{full_results[m].win_rate:.1f}%" for _,m in modes]))
    print(row("Profit Factor", [fp(full_results[m].profit_factor) for _,m in modes]))
    print(row("Total P&L", [f"${full_results[m].total_pnl:+.0f}" for _,m in modes]))
    print(row("Max Drawdown", [f"{full_results[m].max_drawdown_pct:.1f}%" for _,m in modes]))
    print(row("Sharpe", [f"{full_results[m].sharpe_ratio:.2f}" for _,m in modes]))
    print(row("Fees", [f"${full_results[m].total_fees:.0f}" for _,m in modes]))

    # Trade analysis
    for _,m in modes:
        r = full_results[m]
        if r.trades:
            wins = [t for t in r.trades if t.pnl > 0]
            losses = [t for t in r.trades if t.pnl <= 0]
            avg_w = np.mean([t.pnl for t in wins]) if wins else 0
            avg_l = np.mean([t.pnl for t in losses]) if losses else 0
            avg_dur = np.mean([t.exit_bar - t.entry_bar for t in r.trades]) * 15 / 60
            in_market = sum(t.exit_bar - t.entry_bar for t in r.trades) / (len(c15) - 200) * 100

    print()
    print(row("Avg Win", [f"${np.mean([t.pnl for t in full_results[m].trades if t.pnl>0]):+.2f}" if [t for t in full_results[m].trades if t.pnl>0] else "$0" for _,m in modes]))
    print(row("Avg Loss", [f"${np.mean([t.pnl for t in full_results[m].trades if t.pnl<=0]):.2f}" if [t for t in full_results[m].trades if t.pnl<=0] else "$0" for _,m in modes]))
    print(row("Avg Duration", [f"{np.mean([t.exit_bar-t.entry_bar for t in full_results[m].trades])*15/60:.1f}h" for _,m in modes]))
    print(row("Time in Market", [f"{sum(t.exit_bar-t.entry_bar for t in full_results[m].trades)/(len(c15)-200)*100:.1f}%" for _,m in modes]))

    # Walk-forward
    split = int(len(c15) * 0.7)
    wf_results = {}
    for _,m in modes:
        wf_results[m] = run_bt(c15,o15,h15,l15,ts15,st_dir,st_dir_1h,adx,squeeze,mode=m,start_bar=split)

    print(f"\n{'─'*110}")
    print(f"  Walk-Forward Validate (30%)")
    print(f"{'─'*110}")
    print(header()); print(divider())
    print(row("Trades", [str(wf_results[m].num_trades) for _,m in modes]))
    print(row("Profit Factor", [fp(wf_results[m].profit_factor) for _,m in modes]))
    print(row("P&L", [f"${wf_results[m].total_pnl:+.0f}" for _,m in modes]))
    print(row("MDD", [f"{wf_results[m].max_drawdown_pct:.1f}%" for _,m in modes]))
    print(row("Sharpe", [f"{wf_results[m].sharpe_ratio:.2f}" for _,m in modes]))

    # 6 starting points
    seg = len(c15) // 6
    sp_counts = {m: 0 for _,m in modes}
    for s in range(6):
        for _,m in modes:
            r = run_bt(c15,o15,h15,l15,ts15,st_dir,st_dir_1h,adx,squeeze,mode=m,start_bar=s*seg)
            if r.total_pnl > 0: sp_counts[m] += 1

    # Robustness
    rob_pf1 = {m: 0 for _,m in modes}
    rob_wins = {m: 0 for _,m in modes}
    rob_total = 0
    for af in [0.8, 1.0, 1.2]:
        for mf in [0.8, 1.0, 1.2]:
            rob_total += 1
            _,sd = calc_recovery_supertrend(h15,l15,c15,max(2,int(round(8*af))),round(4.0*mf,1),5.0,1.0)
            adx_v = calc_adx(h15,l15,c15,14)
            pfs = {}
            for _,m in modes:
                r = run_bt(c15,o15,h15,l15,ts15,sd,st_dir_1h,adx_v,squeeze,mode=m)
                if r.profit_factor > 1.0: rob_pf1[m] += 1
                pfs[m] = r.profit_factor
            best = max(pfs, key=pfs.get)
            rob_wins[best] += 1

    # ═══════════════════════════════════════════════════
    # SCORECARD
    # ═══════════════════════════════════════════════════

    print(f"\n\n{'═'*110}")
    print(f"  FINAL SCORECARD")
    print(f"{'═'*110}")
    print(header()); print(divider())
    print(row("Full PF", [fp(full_results[m].profit_factor) for _,m in modes]))
    print(row("Full PF > 1.0", ["PASS" if full_results[m].profit_factor>1 else "FAIL" for _,m in modes]))
    print(row("WF PF", [fp(wf_results[m].profit_factor) for _,m in modes]))
    print(row("WF PF > 1.0", ["PASS" if wf_results[m].profit_factor>1 else "FAIL" for _,m in modes]))
    print(row("6/6 starts", [f"{sp_counts[m]}/6" for _,m in modes]))
    print(row("MDD < 40%", ["PASS" if full_results[m].max_drawdown_pct<40 else "FAIL" for _,m in modes]))
    print(row("Robust PF>1", [f"{rob_pf1[m]}/{rob_total}" for _,m in modes]))
    print(row("Robust wins", [f"{rob_wins[m]}/{rob_total}" for _,m in modes]))

    # Composite score
    print(f"\n  Composite:")
    for name, m in modes:
        score = 0
        score += 3 if full_results[m].profit_factor > 1 else 0
        score += 3 if wf_results[m].profit_factor > 1 else 0
        score += 2 if full_results[m].max_drawdown_pct < 40 else 0
        score += sp_counts[m]
        score += rob_wins[m]
        score += int(full_results[m].profit_factor * 10)
        pnl_score = "P&L" if full_results[m].total_pnl == max(full_results[mm].total_pnl for _,mm in modes) else ""
        mdd_score = "MDD" if full_results[m].max_drawdown_pct == min(full_results[mm].max_drawdown_pct for _,mm in modes) else ""
        pf_score = "PF" if full_results[m].profit_factor == max(full_results[mm].profit_factor for _,mm in modes) else ""
        badges = " ".join(filter(None, [pnl_score, mdd_score, pf_score]))
        print(f"    {name:<22}  score={score:>3}  PF={fp(full_results[m].profit_factor)}  "
              f"P&L=${full_results[m].total_pnl:>+7.0f}  MDD={full_results[m].max_drawdown_pct:>5.1f}%  "
              f"{'  ◄ ' + badges if badges else ''}")

    print(f"{'═'*110}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Recovery ST Exit Logic Comparison — Strategy A vs B

Strategy A (current): Exit only when Recovery ST flips AND all filters pass for new direction
Strategy B (proposed): Exit immediately when Recovery ST flips, go flat, re-enter with filters

Both use: Recovery ST(8, 4.0, α=5, θ=1.0) + ADX>=15 rising(4) + SQZ off + 1H ST(10,4,close)
Full validation suite on both.
"""

import json
import sys
import numpy as np
from pathlib import Path
from dataclasses import dataclass

sys.path.insert(0, str(Path(__file__).parent))
from engine import calc_tr, calc_atr_rma, calc_supertrend, BacktestResult

DATA_DIR = Path(__file__).parent.parent / "backtest-data"


def calc_adx(highs, lows, closes, period=14):
    n = len(highs); plus_dm = np.zeros(n); minus_dm = np.zeros(n)
    for i in range(1, n):
        up = highs[i]-highs[i-1]; down = lows[i-1]-lows[i]
        if up > down and up > 0: plus_dm[i] = up
        if down > up and down > 0: minus_dm[i] = down
    tr = calc_tr(highs, lows, closes)
    def rma_s(data, p):
        out = np.zeros(n); out[p] = np.sum(data[1:p+1])
        for i in range(p+1, n): out[i] = out[i-1]-out[i-1]/p+data[i]
        return out
    s_tr=rma_s(tr,period); s_pdm=rma_s(plus_dm,period); s_mdm=rma_s(minus_dm,period)
    dx = np.zeros(n)
    for i in range(period, n):
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
    ts=np.array([c["open_time"] for c in data],dtype=np.int64)
    o=np.array([float(c["open"]) for c in data]); h=np.array([float(c["high"]) for c in data])
    l=np.array([float(c["low"]) for c in data]); c=np.array([float(c["close"]) for c in data])
    v=np.array([float(c["volume"]) for c in data])
    return ts,o,h,l,c,v

def align_1h_to_15m(ts_15m, dir_1h, ts_1h):
    aligned=np.full(len(ts_15m),np.nan); j=0
    for i in range(len(ts_15m)):
        while j<len(ts_1h)-1 and ts_1h[j+1]<=ts_15m[i]: j+=1
        if j<len(dir_1h): aligned[i]=dir_1h[j]
    return aligned


@dataclass
class Trade:
    entry_bar:int; entry_price:float; direction:int; size_usd:float
    exit_bar:int=0; exit_price:float=0.0; pnl:float=0.0; fees:float=0.0; reason:str=""


def run_bt(c15, o15, h15, l15, ts15, st_dir, st_dir_1h, adx, squeeze,
           mode="A", start_bar=0, end_bar=-1, capital=500.0, fixed=125.0, lev=10.0,
           fee_rate=0.00045, slip=0.0001, warmup=200, adx_min=15.0, adx_lb=4):
    nn=len(c15) if end_bar<0 else end_bar
    eff=max(start_bar,warmup)
    equity=capital; pos=0; ep=0.0; eb=0; ps=0.0
    trades=[]; ec=[]; pending=None

    def fl(p,d,ic):
        s=p*slip
        return (p-s if d==1 else p+s) if ic else (p+s if d==1 else p-s)

    def all_filters(i):
        if np.isnan(st_dir_1h[i]) or st_dir[i]!=st_dir_1h[i]: return False
        if np.isnan(adx[i]) or adx[i]<adx_min: return False
        pr=i-adx_lb
        if pr>=0 and not np.isnan(adx[pr]) and adx[i]<=adx[pr]: return False
        if squeeze[i]: return False
        return True

    for i in range(eff,nn):
        if pending is not None and i>eff:
            act=pending; pending=None
            if act=="close" and pos!=0:
                f=fl(o15[i],pos,True); pnl_r=(f-ep)*pos*(ps/ep); fe=ps*fee_rate
                trades.append(Trade(eb,ep,pos,ps,i,f,pnl_r-fe,fe,"close")); equity+=pnl_r-fe; pos=0; ps=0.0
            elif act in ("ol","os"):
                d=1 if act=="ol" else -1; f=fl(o15[i],d,False); ps=fixed*lev; fe=ps*fee_rate; equity-=fe
                pos=d; ep=f; eb=i
            elif act in ("fl","fs"):
                if pos!=0:
                    f=fl(o15[i],pos,True); pnl_r=(f-ep)*pos*(ps/ep); fe=ps*fee_rate
                    trades.append(Trade(eb,ep,pos,ps,i,f,pnl_r-fe,fe,"flip")); equity+=pnl_r-fe
                d=1 if act=="fl" else -1; f2=fl(o15[i],d,False); ps=fixed*lev; fe2=ps*fee_rate; equity-=fe2
                pos=d; ep=f2; eb=i

        if pos!=0: ec.append(equity+(c15[i]-ep)*pos*(ps/ep))
        else: ec.append(equity)

        if i>=nn-1:
            if pos!=0: pending="close"
            continue
        if np.isnan(st_dir[i]): continue
        curr=st_dir[i]; prev=st_dir[i-1] if i>0 and not np.isnan(st_dir[i-1]) else curr
        flipped=curr!=prev; sig=1 if curr==1 else -1

        if mode == "A":
            # Strategy A: only flip when ALL filters pass
            if not flipped: continue
            if not all_filters(i): continue
            if pos==0: pending="ol" if sig==1 else "os"
            elif pos!=sig: pending="fl" if sig==1 else "fs"

        elif mode == "B":
            # Strategy B: exit on Recovery ST flip regardless of filters, re-enter with filters
            if flipped and pos!=0 and sig!=pos:
                if all_filters(i):
                    pending="fl" if sig==1 else "fs"
                else:
                    pending="close"
                continue
            if flipped and all_filters(i):
                if pos==0: pending="ol" if sig==1 else "os"
                elif pos!=sig: pending="fl" if sig==1 else "fs"

    if pos!=0 and pending=="close":
        f=fl(c15[nn-1],pos,True); pnl_r=(f-ep)*pos*(ps/ep); fe=ps*fee_rate
        trades.append(Trade(eb,ep,pos,ps,nn-1,f,pnl_r-fe,fe,"eod")); equity+=pnl_r-fe
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


def main():
    print("=" * 100)
    print("  RECOVERY ST EXIT LOGIC — A vs B")
    print("  A = Exit only when Recovery ST flips AND all filters pass (current bot)")
    print("  B = Exit immediately on Recovery ST flip, go flat, re-enter with filters")
    print("  Recovery ST(8, 4.0, α=5, θ=1.0) + ADX>=15 rising(4) + SQZ + 1H ST(10,4)")
    print("=" * 100)

    ts15,o15,h15,l15,c15,v15 = load_candles(DATA_DIR/"binance_btc_15m.json")
    ts1h,o1h,h1h,l1h,c1h,v1h = load_candles(DATA_DIR/"binance_btc_1h.json")
    print(f"  Data: {len(c15)} 15m bars ({len(c15)//96} days)\n")

    # Pre-compute indicators
    _,st_dir = calc_recovery_supertrend(h15,l15,c15,8,4.0,5.0,1.0)
    adx = calc_adx(h15,l15,c15,14)
    squeeze = calc_squeeze(h15,l15,c15,20,2.0,20,1.5)
    _,st_dir_1h_raw = calc_supertrend(h1h,l1h,c1h,10,4.0,"close")
    st_dir_1h = align_1h_to_15m(ts15,st_dir_1h_raw,ts1h)

    def run_both(label, **kwargs):
        ra = run_bt(c15,o15,h15,l15,ts15,st_dir,st_dir_1h,adx,squeeze,mode="A",**kwargs)
        rb = run_bt(c15,o15,h15,l15,ts15,st_dir,st_dir_1h,adx,squeeze,mode="B",**kwargs)
        return ra, rb

    def print_compare(label, ra, rb):
        print(f"\n{'─'*90}")
        print(f"  {label}")
        print(f"{'─'*90}")
        print(f"  {'Metric':<18} {'A: Filter Exit':<25} {'B: Immediate Exit':<25} {'Delta':<15}")
        print(f"  {'─'*16}   {'─'*23}   {'─'*23}   {'─'*13}")
        metrics = [
            ("Trades", str(ra.num_trades), str(rb.num_trades), ""),
            ("Win Rate", f"{ra.win_rate:.1f}%", f"{rb.win_rate:.1f}%", f"{rb.win_rate-ra.win_rate:+.1f}%"),
            ("Profit Factor", fp(ra.profit_factor), fp(rb.profit_factor),
             f"{rb.profit_factor-ra.profit_factor:+.2f}" if ra.profit_factor<9999 and rb.profit_factor<9999 else ""),
            ("Total P&L", f"${ra.total_pnl:+.2f}", f"${rb.total_pnl:+.2f}", f"${rb.total_pnl-ra.total_pnl:+.2f}"),
            ("Max Drawdown", f"{ra.max_drawdown_pct:.1f}%", f"{rb.max_drawdown_pct:.1f}%",
             f"{rb.max_drawdown_pct-ra.max_drawdown_pct:+.1f}%"),
            ("Sharpe", f"{ra.sharpe_ratio:.2f}", f"{rb.sharpe_ratio:.2f}", f"{rb.sharpe_ratio-ra.sharpe_ratio:+.2f}"),
            ("Fees", f"${ra.total_fees:.2f}", f"${rb.total_fees:.2f}", f"${rb.total_fees-ra.total_fees:+.2f}"),
        ]
        for name, va, vb, delta in metrics:
            print(f"  {name:<18} {va:<25} {vb:<25} {delta:<15}")

    # ═══ TEST 1: Full 730-day ═══
    print("\n" + "=" * 90)
    print("  TEST 1: FULL 730-DAY BACKTEST")
    print("=" * 90)
    fa, fb = run_both("full")
    print_compare("Full Period (730 days)", fa, fb)

    # Trade duration analysis
    if fa.trades and fb.trades:
        def avg_dur(trades):
            durs = [t.exit_bar - t.entry_bar for t in trades if t.exit_bar > t.entry_bar]
            return np.mean(durs) * 15 / 60 if durs else 0  # hours
        def avg_win(trades):
            wins = [t.pnl for t in trades if t.pnl > 0]
            return np.mean(wins) if wins else 0
        def avg_loss(trades):
            losses = [t.pnl for t in trades if t.pnl <= 0]
            return np.mean(losses) if losses else 0

        print(f"\n  {'Trade Analysis':<18} {'A: Filter Exit':<25} {'B: Immediate Exit':<25}")
        print(f"  {'─'*16}   {'─'*23}   {'─'*23}")
        print(f"  {'Avg Duration':<18} {avg_dur(fa.trades):.1f}h{'':<20} {avg_dur(fb.trades):.1f}h")
        print(f"  {'Avg Win':<18} ${avg_win(fa.trades):+.2f}{'':<19} ${avg_win(fb.trades):+.2f}")
        print(f"  {'Avg Loss':<18} ${avg_loss(fa.trades):.2f}{'':<19} ${avg_loss(fb.trades):.2f}")
        print(f"  {'Win/Loss Ratio':<18} {abs(avg_win(fa.trades)/avg_loss(fa.trades)):.2f}x{'':<20} "
              f"{abs(avg_win(fb.trades)/avg_loss(fb.trades)):.2f}x")

        # Time in market
        a_bars = sum(t.exit_bar - t.entry_bar for t in fa.trades)
        b_bars = sum(t.exit_bar - t.entry_bar for t in fb.trades)
        total = len(c15) - 200
        print(f"  {'Time in Market':<18} {a_bars/total*100:.1f}%{'':<20} {b_bars/total*100:.1f}%")

    # ═══ TEST 2: Walk-forward ═══
    print("\n\n" + "=" * 90)
    print("  TEST 2: WALK-FORWARD (70% train / 30% validate)")
    print("=" * 90)
    split = int(len(c15) * 0.7)

    ta, tb = run_both("train", end_bar=split)
    print_compare("Train Period (70%)", ta, tb)

    va, vb = run_both("validate", start_bar=split)
    print_compare("Validate Period (30%)", va, vb)

    # ═══ TEST 3: 6 Starting Points ═══
    print("\n\n" + "=" * 90)
    print("  TEST 3: 6 STARTING POINTS")
    print("=" * 90)

    total_bars = len(c15); seg = total_bars // 6
    sp_a = 0; sp_b = 0
    sp_results = []
    for s in range(6):
        start = s * seg; days = (total_bars - start) // 96
        sa, sb = run_both(f"sp{s}", start_bar=start)
        if sa.total_pnl > 0: sp_a += 1
        if sb.total_pnl > 0: sp_b += 1
        sp_results.append((s, days, sa, sb))
        print_compare(f"Start #{s+1} (bar {start}, ~{days} days)", sa, sb)

    # ═══ TEST 4: Parameter Robustness ═══
    print("\n\n" + "=" * 90)
    print("  TEST 4: PARAMETER ROBUSTNESS (+/-20% ATR and multiplier)")
    print("=" * 90)

    rob_a = 0; rob_b = 0; rob_total = 0; rob_a_wins = 0; rob_b_wins = 0

    print(f"\n  {'ATR':<5} {'Mult':<6} {'A: PF':<10} {'A: MDD':<10} {'B: PF':<10} {'B: MDD':<10} {'Better'}")
    print(f"  {'─'*3}  {'─'*4}  {'─'*8}  {'─'*8}  {'─'*8}  {'─'*8}  {'─'*6}")

    for af in [0.8, 1.0, 1.2]:
        for mf in [0.8, 1.0, 1.2]:
            atr_v = max(2, int(round(8*af))); mult_v = round(4.0*mf, 1)
            _, sd = calc_recovery_supertrend(h15, l15, c15, atr_v, mult_v, 5.0, 1.0)
            adx_v = calc_adx(h15, l15, c15, 14)
            pa = run_bt(c15,o15,h15,l15,ts15,sd,st_dir_1h,adx_v,squeeze,mode="A")
            pb = run_bt(c15,o15,h15,l15,ts15,sd,st_dir_1h,adx_v,squeeze,mode="B")
            if pa.profit_factor > 1.0: rob_a += 1
            if pb.profit_factor > 1.0: rob_b += 1
            better = "A" if pa.profit_factor > pb.profit_factor else "B"
            if better == "A": rob_a_wins += 1
            else: rob_b_wins += 1
            rob_total += 1
            base = " ◄BASE" if af==1.0 and mf==1.0 else ""
            print(f"  {atr_v:<5} {mult_v:<6} {fp(pa.profit_factor):<10} {pa.max_drawdown_pct:.1f}%{'':<5} "
                  f"{fp(pb.profit_factor):<10} {pb.max_drawdown_pct:.1f}%{'':<5} {better}{base}")

    # ═══ SCORECARD ═══
    print("\n\n" + "=" * 90)
    print("  FINAL SCORECARD")
    print("=" * 90)

    print(f"\n  {'Check':<35} {'A: Filter Exit':<20} {'B: Immediate Exit':<20}")
    print(f"  {'─'*33}   {'─'*18}   {'─'*18}")
    print(f"  {'Full PF > 1.0':<35} {'PASS' if fa.profit_factor>1 else 'FAIL':<20} {'PASS' if fb.profit_factor>1 else 'FAIL':<20}")
    print(f"  {'Full PF value':<35} {fp(fa.profit_factor):<20} {fp(fb.profit_factor):<20}")
    print(f"  {'Walk-forward PF > 1.0':<35} {'PASS' if va.profit_factor>1 else 'FAIL':<20} {'PASS' if vb.profit_factor>1 else 'FAIL':<20}")
    print(f"  {'Walk-forward PF value':<35} {fp(va.profit_factor):<20} {fp(vb.profit_factor):<20}")
    print(f"  {'All 6 starts profitable':<35} {sp_a}/6{'':<16} {sp_b}/6")
    print(f"  {'MDD < 40%':<35} {'PASS' if fa.max_drawdown_pct<40 else 'FAIL':<20} {'PASS' if fb.max_drawdown_pct<40 else 'FAIL':<20}")
    print(f"  {'MDD < 50%':<35} {'PASS' if fa.max_drawdown_pct<50 else 'FAIL':<20} {'PASS' if fb.max_drawdown_pct<50 else 'FAIL':<20}")
    print(f"  {'Robustness PF>1 (9 combos)':<35} {rob_a}/{rob_total}{'':<14} {rob_b}/{rob_total}")
    print(f"  {'Robustness head-to-head':<35} {rob_a_wins}/{rob_total}{'':<14} {rob_b_wins}/{rob_total}")

    # Winner
    score_a = (fa.profit_factor>1)*3 + (va.profit_factor>1)*3 + sp_a + rob_a_wins + (fa.max_drawdown_pct<40)*2
    score_b = (fb.profit_factor>1)*3 + (vb.profit_factor>1)*3 + sp_b + rob_b_wins + (fb.max_drawdown_pct<40)*2
    winner = "A (Filter Exit)" if score_a > score_b else "B (Immediate Exit)"

    print(f"\n  WINNER: Strategy {winner}")
    print(f"  Composite Score: A={score_a}  B={score_b}")

    # Practical implications
    print(f"\n  PRACTICAL IMPLICATIONS:")
    if fb.profit_factor > fa.profit_factor:
        print(f"  - Strategy B has higher PF ({fp(fb.profit_factor)} vs {fp(fa.profit_factor)})")
    else:
        print(f"  - Strategy A has higher PF ({fp(fa.profit_factor)} vs {fp(fb.profit_factor)})")
    if fb.max_drawdown_pct < fa.max_drawdown_pct:
        print(f"  - Strategy B has lower MDD ({fb.max_drawdown_pct:.1f}% vs {fa.max_drawdown_pct:.1f}%)")
    else:
        print(f"  - Strategy A has lower MDD ({fa.max_drawdown_pct:.1f}% vs {fb.max_drawdown_pct:.1f}%)")
    if fb.total_pnl > fa.total_pnl:
        print(f"  - Strategy B has more P&L (${fb.total_pnl:+.0f} vs ${fa.total_pnl:+.0f})")
    else:
        print(f"  - Strategy A has more P&L (${fa.total_pnl:+.0f} vs ${fb.total_pnl:+.0f})")
    print(f"  - B trades {fb.num_trades-fa.num_trades:+d} more trades ({fb.num_trades} vs {fa.num_trades})")
    print(f"  - B pays ${fb.total_fees-fa.total_fees:+.0f} more in fees")
    print("=" * 90)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Entry Window Test — Fix for missed signals when filters clear after flip bar.

Current baseline: Signal only fires on the exact flip bar if all filters pass.
Solution 1: Allow signal within N bars after flip (N=2, 3, 4).
Solution 2: Fire on first bar where all filters pass after flip, max 10 bar window.

All use Recovery ST(8, 4.0, α=5, θ=1.0) + ADX>=15 rising(4) + SQZ + 1H ST(10,4)
Strategy B exit, $125×10x, 0.045% taker, 0.01% slippage, with funding.
"""

import json
import sys
import numpy as np
from pathlib import Path
from dataclasses import dataclass

sys.path.insert(0, str(Path(__file__).parent))
from engine import calc_tr, calc_atr_rma, calc_supertrend, BacktestResult

DATA_DIR = Path(__file__).parent.parent / "backtest-data"

FUNDING_RATE = 0.0001
FUNDING_INTERVAL_BARS = 32


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
    exit_bar:int=0; exit_price:float=0.0; pnl:float=0.0; fees:float=0.0; funding:float=0.0


def run_bt(c15, o15, h15, l15, ts15, st_dir, st_dir_1h, adx, squeeze,
           mode="baseline",  # "baseline", "window_N", "filter_clear_N"
           window_bars=0,     # for window mode: N bars after flip
           max_window=10,     # for filter_clear mode: max bars to wait
           start_bar=0, end_bar=-1, capital=500.0, fixed=125.0, lev=10.0,
           fee_rate=0.00045, slip=0.0001, warmup=200, adx_min=15.0, adx_lb=4):

    nn=len(c15) if end_bar<0 else end_bar
    eff=max(start_bar,warmup)
    equity=capital; pos=0; ep=0.0; eb=0; ps=0.0
    trades=[]; ec=[]; pending=None
    total_funding=0.0; trade_funding=0.0; last_funding_bar=0

    # Track pending flip for delayed entry
    pending_flip_bar = -999  # bar where last flip happened
    pending_flip_dir = 0     # 1 or -1

    def fl(p,d,ic):
        s=p*slip
        return (p-s if d==1 else p+s) if ic else (p+s if d==1 else p-s)

    def filters_pass(i):
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
                net=pnl_r-fe-trade_funding; equity+=pnl_r-fe
                trades.append(Trade(eb,ep,pos,ps,i,f,net,fe,trade_funding))
                pos=0; ps=0.0; trade_funding=0.0
            elif act in ("ol","os"):
                d=1 if act=="ol" else -1; f=fl(o15[i],d,False); ps=fixed*lev; fe=ps*fee_rate; equity-=fe
                pos=d; ep=f; eb=i; last_funding_bar=i; trade_funding=0.0
            elif act in ("fl","fs"):
                if pos!=0:
                    f=fl(o15[i],pos,True); pnl_r=(f-ep)*pos*(ps/ep); fe=ps*fee_rate
                    net=pnl_r-fe-trade_funding; equity+=pnl_r-fe
                    trades.append(Trade(eb,ep,pos,ps,i,f,net,fe,trade_funding))
                d=1 if act=="fl" else -1; f2=fl(o15[i],d,False); ps=fixed*lev; fe2=ps*fee_rate; equity-=fe2
                pos=d; ep=f2; eb=i; last_funding_bar=i; trade_funding=0.0

        # Funding
        if pos!=0 and (i-last_funding_bar)>=FUNDING_INTERVAL_BARS:
            fc=ps*FUNDING_RATE; equity-=fc; total_funding+=fc; trade_funding+=fc; last_funding_bar=i

        if pos!=0: ec.append(equity+(c15[i]-ep)*pos*(ps/ep))
        else: ec.append(equity)

        if i>=nn-1:
            if pos!=0: pending="close"
            continue
        if np.isnan(st_dir[i]): continue
        curr=st_dir[i]; prev=st_dir[i-1] if i>0 and not np.isnan(st_dir[i-1]) else curr
        flipped=curr!=prev; sig=1 if curr==1 else -1

        # Strategy B exit: always exit on flip regardless of filters
        if flipped and pos!=0 and sig!=pos:
            if filters_pass(i):
                pending="fl" if sig==1 else "fs"
            else:
                pending="close"
            # Also register this as a pending flip for potential delayed re-entry
            pending_flip_bar=i; pending_flip_dir=sig
            continue

        # ════════════════════════════════════════════════════
        # ENTRY LOGIC — varies by mode
        # ════════════════════════════════════════════════════

        if mode == "baseline":
            # Original: signal only fires on exact flip bar with all filters
            if flipped and filters_pass(i):
                if pos==0: pending="ol" if sig==1 else "os"
                elif pos!=sig: pending="fl" if sig==1 else "fs"

        elif mode.startswith("window"):
            # Solution 1: Allow entry within N bars after flip
            if flipped:
                pending_flip_bar=i; pending_flip_dir=sig

            if pos==0 and pending_flip_bar>=0:
                bars_since_flip = i - pending_flip_bar
                # Check: is ST still in the same direction as the flip?
                if st_dir[i] == (1 if pending_flip_dir==1 else -1):
                    if bars_since_flip <= window_bars and filters_pass(i):
                        pending="ol" if pending_flip_dir==1 else "os"
                        pending_flip_bar=-999  # consumed
                else:
                    pending_flip_bar=-999  # ST flipped again, abandon

            # Also handle flip from position (not just from flat)
            if flipped and pos!=0 and sig!=pos and filters_pass(i):
                # Already handled by exit logic above (which sets pending to fl/fs)
                pass

        elif mode.startswith("filter_clear"):
            # Solution 2: Fire on first bar where filters pass after a flip
            if flipped:
                pending_flip_bar=i; pending_flip_dir=sig

            if pos==0 and pending_flip_bar>=0:
                bars_since_flip = i - pending_flip_bar
                if st_dir[i] == (1 if pending_flip_dir==1 else -1):
                    if bars_since_flip <= max_window and filters_pass(i):
                        pending="ol" if pending_flip_dir==1 else "os"
                        pending_flip_bar=-999
                    elif bars_since_flip > max_window:
                        pending_flip_bar=-999  # window expired
                else:
                    pending_flip_bar=-999  # direction changed

    # Close remaining
    if pos!=0 and pending=="close":
        f=fl(c15[nn-1],pos,True); pnl_r=(f-ep)*pos*(ps/ep); fe=ps*fee_rate
        net=pnl_r-fe-trade_funding; equity+=pnl_r-fe
        trades.append(Trade(eb,ep,pos,ps,nn-1,f,net,fe,trade_funding))
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
    r._total_funding=total_funding
    return r


def fp(v): return f"{v:.2f}" if v<9999 else "INF"


def run_validation(label, c15, o15, h15, l15, ts15, st_dir, st_dir_1h, adx, squeeze,
                    h1h, l1h, c1h, ts1h, **bt_kwargs):
    full=run_bt(c15,o15,h15,l15,ts15,st_dir,st_dir_1h,adx,squeeze,**bt_kwargs)
    split=int(len(c15)*0.7)
    wf=run_bt(c15,o15,h15,l15,ts15,st_dir,st_dir_1h,adx,squeeze,start_bar=split,**bt_kwargs)
    seg=len(c15)//6; sp=0
    for s in range(6):
        r=run_bt(c15,o15,h15,l15,ts15,st_dir,st_dir_1h,adx,squeeze,start_bar=s*seg,**bt_kwargs)
        if r.total_pnl>0: sp+=1
    rob=0; rob_t=0
    for af in [0.8,1.0,1.2]:
        for mf in [0.8,1.0,1.2]:
            if af==1.0 and mf==1.0: continue
            rob_t+=1
            _,sd=calc_recovery_supertrend(h15,l15,c15,max(2,int(round(8*af))),round(4.0*mf,1),5.0,1.0)
            adx_v=calc_adx(h15,l15,c15,14)
            _,sd1h=calc_supertrend(h1h,l1h,c1h,10,4.0,"close")
            sd1h_a=align_1h_to_15m(ts15,sd1h,ts1h)
            tr=run_bt(c15,o15,h15,l15,ts15,sd,sd1h_a,adx_v,squeeze,**bt_kwargs)
            if tr.profit_factor>1.0: rob+=1
    return {"label":label,"trades":full.num_trades,"wr":full.win_rate,"pf":full.profit_factor,
            "pnl":full.total_pnl,"final":full.final_equity,"mdd":full.max_drawdown_pct,
            "sharpe":full.sharpe_ratio,"fees":full.total_fees,"funding":full._total_funding,
            "wf_pf":wf.profit_factor,"wf_mdd":wf.max_drawdown_pct,"sp":sp,"rob":rob,"rob_t":rob_t}


def main():
    print("="*110)
    print("  ENTRY WINDOW TEST — Fixing missed signals when filters clear after flip")
    print("  Recovery ST(8,4,α=5,θ=1.0) + ADX>=15 rising(4) + SQZ + 1H | Strategy B exit")
    print("  $500 start | 10x | 0.045% taker | 0.01% slip | 0.01%/8h funding")
    print("="*110)

    ts15,o15,h15,l15,c15,v15=load_candles(DATA_DIR/"binance_btc_15m.json")
    ts1h,o1h,h1h,l1h,c1h,v1h=load_candles(DATA_DIR/"binance_btc_1h.json")
    print(f"  Data: {len(c15)} 15m bars ({len(c15)//96} days)\n")

    _,st_dir=calc_recovery_supertrend(h15,l15,c15,8,4.0,5.0,1.0)
    adx_arr=calc_adx(h15,l15,c15,14)
    squeeze_arr=calc_squeeze(h15,l15,c15,20,2.0,20,1.5)
    _,st_dir_1h_raw=calc_supertrend(h1h,l1h,c1h,10,4.0,"close")
    st_dir_1h=align_1h_to_15m(ts15,st_dir_1h_raw,ts1h)

    # Count missed signals in baseline
    print("  Analyzing missed entries in baseline...")
    missed=0; entered=0
    flip_bar=-999; flip_dir=0
    for i in range(200,len(c15)):
        if np.isnan(st_dir[i]): continue
        curr=st_dir[i]; prev=st_dir[i-1] if i>0 and not np.isnan(st_dir[i-1]) else curr
        if curr!=prev:
            flip_bar=i; flip_dir=1 if curr==1 else -1
            adx_ok=not np.isnan(adx_arr[i]) and adx_arr[i]>=15
            pr=i-4
            adx_rising=pr>=0 and not np.isnan(adx_arr[pr]) and adx_arr[i]>adx_arr[pr]
            htf_ok=not np.isnan(st_dir_1h[i]) and st_dir[i]==st_dir_1h[i]
            sqz_ok=not squeeze_arr[i]
            if htf_ok and adx_ok and adx_rising and sqz_ok:
                entered+=1
            else:
                # Check if filters clear within 10 bars
                cleared=False
                for j in range(1,11):
                    if i+j>=len(c15): break
                    if st_dir[i+j]!=curr: break  # flipped again
                    a_ok=not np.isnan(adx_arr[i+j]) and adx_arr[i+j]>=15
                    pr2=i+j-4
                    a_r=pr2>=0 and not np.isnan(adx_arr[pr2]) and adx_arr[i+j]>adx_arr[pr2]
                    h_ok=not np.isnan(st_dir_1h[i+j]) and st_dir[i+j]==st_dir_1h[i+j]
                    s_ok=not squeeze_arr[i+j]
                    if h_ok and a_ok and a_r and s_ok:
                        cleared=True; missed+=1; break
                if not cleared:
                    pass  # filters never cleared — not a missed entry

    print(f"  Total flips: {entered+missed+0}")
    print(f"  Entered on flip bar: {entered}")
    print(f"  Missed (filters cleared within 10 bars): {missed}")
    print(f"  Miss rate: {missed/(entered+missed)*100:.1f}%\n")

    # Run all configurations
    configs = [
        ("Baseline (flip bar only)", {"mode": "baseline"}),
        ("Window N=2", {"mode": "window", "window_bars": 2}),
        ("Window N=3", {"mode": "window", "window_bars": 3}),
        ("Window N=4", {"mode": "window", "window_bars": 4}),
        ("Filter Clear (max 5)", {"mode": "filter_clear", "max_window": 5}),
        ("Filter Clear (max 10)", {"mode": "filter_clear", "max_window": 10}),
        ("Filter Clear (max 20)", {"mode": "filter_clear", "max_window": 20}),
    ]

    results = []
    for label, kwargs in configs:
        print(f"  Running: {label}...", end="", flush=True)
        r = run_validation(label, c15, o15, h15, l15, ts15, st_dir, st_dir_1h, adx_arr, squeeze_arr,
                           h1h, l1h, c1h, ts1h, **kwargs)
        results.append(r)
        print(f" PF={fp(r['pf'])} trades={r['trades']} MDD={r['mdd']:.1f}%")

    # Master table
    w=16
    print(f"\n{'═'*130}")
    print(f"  RESULTS TABLE")
    print(f"{'═'*130}")
    hdr=f"  {'Metric':<18}"
    for r in results: hdr+=f" {r['label']:<{w}}"
    print(hdr)
    print(f"  {'─'*16}  "+"  ".join(["─"*(w-2)]*len(results)))

    def row(label,key,fmt_fn):
        s=f"  {label:<18}"
        for r in results: s+=f" {fmt_fn(r[key]):<{w}}"
        return s

    print(row("Trades","trades",str))
    print(row("Win Rate","wr",lambda v:f"{v:.1f}%"))
    print(row("Profit Factor","pf",fp))
    print(row("Total P&L","pnl",lambda v:f"${v:+,.0f}"))
    print(row("Max Drawdown","mdd",lambda v:f"{v:.1f}%"))
    print(row("Sharpe","sharpe",lambda v:f"{v:.2f}"))
    print(row("Fees","fees",lambda v:f"${v:.0f}"))
    print(row("Funding","funding",lambda v:f"${v:.0f}"))
    print(f"  {'─'*16}  "+"  ".join(["─"*(w-2)]*len(results)))
    print(row("WF Valid PF","wf_pf",fp))
    print(row("WF Valid MDD","wf_mdd",lambda v:f"{v:.1f}%"))
    print(row("6/6 Starts","sp",lambda v:f"{v}/6"))
    print(row("Robust PF>1","rob",lambda v:f"{v}/{results[0]['rob_t']}"))
    print(f"  {'─'*16}  "+"  ".join(["─"*(w-2)]*len(results)))
    print(f"  {'PF > 1.0':<18}",end="")
    for r in results: print(f" {'PASS' if r['pf']>1 else 'FAIL':<{w}}",end="")
    print()
    print(f"  {'WF PF > 1.0':<18}",end="")
    for r in results: print(f" {'PASS' if r['wf_pf']>1 else 'FAIL':<{w}}",end="")
    print()
    print(f"  {'MDD < 50%':<18}",end="")
    for r in results: print(f" {'PASS' if r['mdd']<50 else 'FAIL':<{w}}",end="")
    print()
    print(f"  {'All checks':<18}",end="")
    for r in results:
        ok=r['pf']>1 and r['wf_pf']>1 and r['mdd']<50 and r['sp']>=5 and r['rob']>=5
        print(f" {'YES' if ok else 'NO':<{w}}",end="")
    print()

    # Delta from baseline
    base=results[0]
    print(f"\n{'═'*130}")
    print(f"  DELTA FROM BASELINE")
    print(f"{'═'*130}")
    print(f"  {'Config':<25} {'ΔTrades':>10} {'ΔPF':>10} {'ΔMDD':>10} {'ΔP&L':>12} {'ΔSharpe':>10}")
    print(f"  {'─'*23}   {'─'*8}   {'─'*8}   {'─'*8}   {'─'*10}   {'─'*8}")
    for r in results[1:]:
        dt=r['trades']-base['trades']
        dpf=r['pf']-base['pf']
        dmdd=r['mdd']-base['mdd']
        dpnl=r['pnl']-base['pnl']
        dsh=r['sharpe']-base['sharpe']
        print(f"  {r['label']:<25} {dt:>+10} {dpf:>+10.2f} {dmdd:>+10.1f}% {dpnl:>+12,.0f} {dsh:>+10.2f}")

    # Find best
    passing=[r for r in results if r['pf']>1 and r['wf_pf']>1 and r['mdd']<50 and r['sp']>=5]
    if passing:
        best=max(passing,key=lambda r:r['pf'])
        print(f"\n{'═'*80}")
        print(f"  BEST CONFIGURATION (passes all checks, highest PF):")
        print(f"  {best['label']}")
        print(f"  PF={fp(best['pf'])} | P&L=${best['pnl']:+,.0f} | MDD={best['mdd']:.1f}% | "
              f"Trades={best['trades']} | WF PF={fp(best['wf_pf'])} | {best['sp']}/6 | {best['rob']}/{best['rob_t']}")
        print(f"{'═'*80}")

    print()


if __name__=="__main__":
    main()

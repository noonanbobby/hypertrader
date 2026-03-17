#!/usr/bin/env python3
"""
Recovery ST Parameter Grid Search — Full Validation Suite

Grid: recovery_alpha × recovery_threshold
  alpha:     1, 2, 3, 5, 8, 10, 15, 20
  threshold: 0.5, 1.0, 1.5, 2.0, 2.5, 3.0

Fixed: ATR=8, mult=4.0, ADX>=15 rising(4), SQZ BB(20,2) KC(20,1.5), 1H ST(10,4,close)
Strategy B exit, $125×10x, 0.045% taker
"""

import json
import sys
import numpy as np
from pathlib import Path
from dataclasses import dataclass

sys.path.insert(0, str(Path(__file__).parent))
from engine import calc_tr, calc_atr_rma, calc_supertrend, BacktestResult

DATA_DIR = Path(__file__).parent.parent / "backtest-data"

# ═══════════════════════════════════════════════════════════════
# INDICATORS (copied from previous scripts for standalone run)
# ═══════════════════════════════════════════════════════════════

def calc_adx(highs, lows, closes, period=14):
    n = len(highs)
    plus_dm = np.zeros(n); minus_dm = np.zeros(n)
    for i in range(1, n):
        up = highs[i] - highs[i-1]; down = lows[i-1] - lows[i]
        if up > down and up > 0: plus_dm[i] = up
        if down > up and down > 0: minus_dm[i] = down
    tr = calc_tr(highs, lows, closes)
    def rma_s(data, p):
        out = np.zeros(n); out[p] = np.sum(data[1:p+1])
        for i in range(p+1, n): out[i] = out[i-1] - out[i-1]/p + data[i]
        return out
    s_tr = rma_s(tr, period); s_pdm = rma_s(plus_dm, period); s_mdm = rma_s(minus_dm, period)
    dx = np.zeros(n)
    for i in range(period, n):
        if s_tr[i] > 0:
            pdi = 100*s_pdm[i]/s_tr[i]; mdi = 100*s_mdm[i]/s_tr[i]; t = pdi+mdi
            if t > 0: dx[i] = 100*abs(pdi-mdi)/t
    adx = np.full(n, np.nan); fv = period
    while fv < n and dx[fv] == 0: fv += 1
    if fv + period >= n: return adx
    adx[fv+period-1] = np.mean(dx[fv:fv+period])
    for i in range(fv+period, n): adx[i] = (adx[i-1]*(period-1)+dx[i])/period
    return adx

def calc_squeeze(highs, lows, closes, bb_len=20, bb_mult=2.0, kc_len=20, kc_mult=1.5):
    n = len(closes); squeeze = np.full(n, False); tr = calc_tr(highs, lows, closes)
    for i in range(max(bb_len, kc_len)-1, n):
        w = closes[i-bb_len+1:i+1]; bb_b = np.mean(w); bb_s = np.std(w, ddof=0)
        ub = bb_b+bb_mult*bb_s; lb = bb_b-bb_mult*bb_s
        kc_b = np.mean(closes[i-kc_len+1:i+1]); kc_a = np.mean(tr[i-kc_len+1:i+1])
        uk = kc_b+kc_mult*kc_a; lk = kc_b-kc_mult*kc_a
        squeeze[i] = (lb > lk) and (ub < uk)
    return squeeze

def calc_recovery_supertrend(highs, lows, closes, atr_period=8, multiplier=4.0,
                              recovery_alpha=5.0, recovery_threshold=1.0):
    n = len(closes); src = (highs+lows)/2
    tr = calc_tr(highs, lows, closes); atr = calc_atr_rma(tr, atr_period)
    st_band = np.full(n, np.nan); direction = np.ones(n); switch_price = np.zeros(n)
    alpha = recovery_alpha / 100.0; start = atr_period - 1
    st_band[start] = src[start] - multiplier*atr[start]; direction[start] = 1; switch_price[start] = closes[start]
    for i in range(start+1, n):
        if np.isnan(atr[i]):
            st_band[i]=st_band[i-1]; direction[i]=direction[i-1]; switch_price[i]=switch_price[i-1]; continue
        ub=src[i]+multiplier*atr[i]; lb=src[i]-multiplier*atr[i]; pb=st_band[i-1]; dev=recovery_threshold*atr[i]
        if direction[i-1]==1:
            loss=(switch_price[i-1]-closes[i])>dev
            tb=(alpha*closes[i]+(1-alpha)*pb) if loss else lb
            st_band[i]=max(tb, pb)
            if closes[i]<st_band[i]: direction[i]=-1; st_band[i]=ub; switch_price[i]=closes[i]
            else: direction[i]=1; switch_price[i]=switch_price[i-1]
        else:
            loss=(closes[i]-switch_price[i-1])>dev
            tb=(alpha*closes[i]+(1-alpha)*pb) if loss else ub
            st_band[i]=min(tb, pb)
            if closes[i]>st_band[i]: direction[i]=1; st_band[i]=lb; switch_price[i]=closes[i]
            else: direction[i]=-1; switch_price[i]=switch_price[i-1]
    return st_band, direction

def load_candles(filepath):
    data = json.load(open(filepath))
    ts = np.array([c["open_time"] for c in data], dtype=np.int64)
    o = np.array([float(c["open"]) for c in data]); h = np.array([float(c["high"]) for c in data])
    l = np.array([float(c["low"]) for c in data]); c = np.array([float(c["close"]) for c in data])
    v = np.array([float(c["volume"]) for c in data])
    return ts, o, h, l, c, v

def align_1h_to_15m(ts_15m, dir_1h, ts_1h):
    aligned = np.full(len(ts_15m), np.nan); j = 0
    for i in range(len(ts_15m)):
        while j < len(ts_1h)-1 and ts_1h[j+1] <= ts_15m[i]: j += 1
        if j < len(dir_1h): aligned[i] = dir_1h[j]
    return aligned

# ═══════════════════════════════════════════════════════════════
# ENGINE
# ═══════════════════════════════════════════════════════════════

@dataclass
class Trade:
    entry_bar: int; entry_price: float; direction: int; size_usd: float
    exit_bar: int = 0; exit_price: float = 0.0; pnl: float = 0.0; fees: float = 0.0

def run_bt(c15, o15, h15, l15, ts15, st_dir, st_dir_1h, adx, squeeze,
           start_bar=0, end_bar=-1, capital=500.0, fixed=125.0, lev=10.0,
           fee_rate=0.00045, slip=0.0001, warmup=200, adx_min=15.0, adx_lb=4):
    nn = len(c15) if end_bar < 0 else end_bar
    eff = max(start_bar, warmup)
    equity = capital; pos = 0; ep = 0.0; eb = 0; ps = 0.0
    trades = []; ec = []; pending = None

    def fl(p, d, ic):
        s = p * slip
        return (p-s if d==1 else p+s) if ic else (p+s if d==1 else p-s)

    def fp(i):
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
                f = fl(o15[i], pos, True); pnl = (f-ep)*pos*(ps/ep); fe = ps*fee_rate
                trades.append(Trade(eb, ep, pos, ps, i, f, pnl-fe, fe)); equity += pnl-fe; pos=0; ps=0.0
            elif act in ("ol","os"):
                d = 1 if act=="ol" else -1; f=fl(o15[i],d,False); ps=fixed*lev; fe=ps*fee_rate; equity-=fe
                pos=d; ep=f; eb=i
            elif act in ("fl","fs"):
                if pos != 0:
                    f=fl(o15[i],pos,True); pnl=(f-ep)*pos*(ps/ep); fe=ps*fee_rate
                    trades.append(Trade(eb,ep,pos,ps,i,f,pnl-fe,fe)); equity+=pnl-fe
                d=1 if act=="fl" else -1; f2=fl(o15[i],d,False); ps=fixed*lev; fe2=ps*fee_rate; equity-=fe2
                pos=d; ep=f2; eb=i

        if pos != 0: ec.append(equity + (c15[i]-ep)*pos*(ps/ep))
        else: ec.append(equity)

        if i >= nn-1:
            if pos != 0: pending = "close"
            continue
        if np.isnan(st_dir[i]): continue
        curr = st_dir[i]; prev = st_dir[i-1] if i>0 and not np.isnan(st_dir[i-1]) else curr
        flipped = curr != prev; sig = 1 if curr==1 else -1

        if flipped and pos != 0 and sig != pos:
            pending = ("fl" if sig==1 else "fs") if fp(i) else "close"
            continue
        if flipped and fp(i):
            if pos == 0: pending = "ol" if sig==1 else "os"
            elif pos != sig: pending = "fl" if sig==1 else "fs"

    if pos != 0 and pending == "close":
        f=fl(c15[nn-1],pos,True); pnl=(f-ep)*pos*(ps/ep); fe=ps*fee_rate
        trades.append(Trade(eb,ep,pos,ps,nn-1,f,pnl-fe,fe)); equity+=pnl-fe
        if ec: ec[-1]=equity

    r = BacktestResult(config=None); r.trades=trades; r.equity_curve=ec
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

# ═══════════════════════════════════════════════════════════════
# GRID SEARCH
# ═══════════════════════════════════════════════════════════════

def main():
    print("=" * 120)
    print("  RECOVERY ST PARAMETER GRID SEARCH")
    print("  Fixed: ATR=8, mult=4.0, ADX>=15 rising(4), SQZ BB(20,2) KC(20,1.5), 1H ST(10,4,close)")
    print("  Strategy B exit | $125 × 10x | 0.045% taker | 730 days BTC 15m")
    print("=" * 120)

    ts15, o15, h15, l15, c15, v15 = load_candles(DATA_DIR / "binance_btc_15m.json")
    ts1h, o1h, h1h, l1h, c1h, v1h = load_candles(DATA_DIR / "binance_btc_1h.json")
    print(f"  Data: {len(c15)} 15m bars, {len(c1h)} 1H bars\n")

    # Pre-compute shared indicators (don't change with recovery params)
    adx = calc_adx(h15, l15, c15, 14)
    squeeze = calc_squeeze(h15, l15, c15, 20, 2.0, 20, 1.5)
    _, st_dir_1h_raw = calc_supertrend(h1h, l1h, c1h, 10, 4.0, "close")
    st_dir_1h = align_1h_to_15m(ts15, st_dir_1h_raw, ts1h)

    alphas = [1, 2, 3, 5, 8, 10, 15, 20]
    thresholds = [0.5, 1.0, 1.5, 2.0, 2.5, 3.0]
    split = int(len(c15) * 0.7)
    total_bars = len(c15); seg = total_bars // 6

    results = []

    print(f"  Running {len(alphas) * len(thresholds)} combinations...\n")

    for ra in alphas:
        for rt in thresholds:
            # Compute Recovery ST with these params
            _, st_dir = calc_recovery_supertrend(h15, l15, c15, 8, 4.0, ra, rt)

            # Full
            full = run_bt(c15, o15, h15, l15, ts15, st_dir, st_dir_1h, adx, squeeze)

            # Walk-forward validate
            wf = run_bt(c15, o15, h15, l15, ts15, st_dir, st_dir_1h, adx, squeeze, start_bar=split)

            # 6 starting points
            sp = 0
            for s in range(6):
                r = run_bt(c15, o15, h15, l15, ts15, st_dir, st_dir_1h, adx, squeeze, start_bar=s*seg)
                if r.total_pnl > 0: sp += 1

            # Robustness: vary ATR and mult +/-20%
            rob = 0; rob_t = 0
            for af in [0.8, 1.0, 1.2]:
                for mf in [0.8, 1.0, 1.2]:
                    if af == 1.0 and mf == 1.0: continue
                    rob_t += 1
                    atr_v = max(2, int(round(8 * af))); mult_v = round(4.0 * mf, 1)
                    _, sd = calc_recovery_supertrend(h15, l15, c15, atr_v, mult_v, ra, rt)
                    adx_v = calc_adx(h15, l15, c15, 14)
                    tr = run_bt(c15, o15, h15, l15, ts15, sd, st_dir_1h, adx_v, squeeze)
                    if tr.profit_factor > 1.0: rob += 1

            results.append({
                "ra": ra, "rt": rt,
                "trades": full.num_trades, "wr": full.win_rate,
                "pf": full.profit_factor, "pnl": full.total_pnl,
                "mdd": full.max_drawdown_pct, "sharpe": full.sharpe_ratio,
                "wf_pf": wf.profit_factor, "wf_mdd": wf.max_drawdown_pct,
                "sp": sp, "rob": rob, "rob_t": rob_t,
            })

    # ═══════════════════════════════════════════════════
    # HEATMAP TABLE: PF by alpha × threshold
    # ═══════════════════════════════════════════════════

    fp = lambda v: f"{v:.2f}" if v < 9999 else "INF"

    print("\n" + "=" * 100)
    print("  PROFIT FACTOR HEATMAP (alpha × threshold)")
    print("=" * 100)
    header = f"  {'α \\ θ':<8}"
    for t in thresholds: header += f"  {t:<10}"
    print(header)
    print(f"  {'─'*6}  " + "  ".join(["─"*8] * len(thresholds)))
    for ra in alphas:
        row = f"  {ra:<8}"
        for rt in thresholds:
            r = next(x for x in results if x["ra"]==ra and x["rt"]==rt)
            pf_str = fp(r["pf"])
            # Highlight: bold if PF > 1.5 and MDD < 40%
            if r["pf"] > 1.5 and r["mdd"] < 40: pf_str = f"*{pf_str}*"
            row += f"  {pf_str:<10}"
        print(row)

    print("\n" + "=" * 100)
    print("  MAX DRAWDOWN HEATMAP (alpha × threshold)")
    print("=" * 100)
    header = f"  {'α \\ θ':<8}"
    for t in thresholds: header += f"  {t:<10}"
    print(header)
    print(f"  {'─'*6}  " + "  ".join(["─"*8] * len(thresholds)))
    for ra in alphas:
        row = f"  {ra:<8}"
        for rt in thresholds:
            r = next(x for x in results if x["ra"]==ra and x["rt"]==rt)
            mdd_str = f"{r['mdd']:.1f}%"
            if r["mdd"] < 40: mdd_str = f"*{mdd_str}*"
            row += f"  {mdd_str:<10}"
        print(row)

    print("\n" + "=" * 100)
    print("  P&L HEATMAP (alpha × threshold)")
    print("=" * 100)
    header = f"  {'α \\ θ':<8}"
    for t in thresholds: header += f"  {t:<10}"
    print(header)
    print(f"  {'─'*6}  " + "  ".join(["─"*8] * len(thresholds)))
    for ra in alphas:
        row = f"  {ra:<8}"
        for rt in thresholds:
            r = next(x for x in results if x["ra"]==ra and x["rt"]==rt)
            row += f"  ${r['pnl']:>+7.0f}  "
        print(row)

    # ═══════════════════════════════════════════════════
    # FULL DETAIL TABLE — top candidates
    # ═══════════════════════════════════════════════════

    # Filter: PF > 1.0 and MDD < 40%
    candidates = [r for r in results if r["pf"] > 1.0 and r["mdd"] < 40]
    candidates.sort(key=lambda x: -x["pf"])

    print("\n\n" + "=" * 130)
    print(f"  TOP CANDIDATES (PF > 1.0 AND MDD < 40%) — {len(candidates)} found")
    print("=" * 130)
    print(f"  {'α':<4} {'θ':<5} {'Trades':<8} {'WR':<7} {'PF':<8} {'P&L':<10} {'MDD':<8} {'Sharpe':<8} {'WF PF':<8} {'WF MDD':<8} {'6/6':<6} {'Rob':<7} {'Pass'}")
    print(f"  {'─'*2}  {'─'*3}  {'─'*6}  {'─'*5}  {'─'*6}  {'─'*8}  {'─'*6}  {'─'*6}  {'─'*6}  {'─'*6}  {'─'*4}  {'─'*5}  {'─'*4}")

    for r in candidates[:25]:
        passes = sum([
            r["pf"] > 1.0,
            r["wf_pf"] > 1.0,
            r["mdd"] < 40,
            r["sp"] >= 5,
            r["rob"] >= 5,
        ])
        print(f"  {r['ra']:<4} {r['rt']:<5} {r['trades']:<8} {r['wr']:.1f}%{'':<2} {fp(r['pf']):<8} "
              f"${r['pnl']:>+7.0f}   {r['mdd']:.1f}%{'':<3} {r['sharpe']:.2f}{'':<4} "
              f"{fp(r['wf_pf']):<8} {r['wf_mdd']:.1f}%{'':<3} {r['sp']}/6{'':<2} "
              f"{r['rob']}/{r['rob_t']}{'':<2} {passes}/5")

    # ═══════════════════════════════════════════════════
    # BEST OVERALL
    # ═══════════════════════════════════════════════════

    # Best = highest PF among those passing ALL checks
    fully_passing = [r for r in results
                     if r["pf"] > 1.0 and r["wf_pf"] > 1.0 and r["mdd"] < 40
                     and r["sp"] >= 5 and r["rob"] >= 5]
    if fully_passing:
        fully_passing.sort(key=lambda x: -x["pf"])
        best = fully_passing[0]
        print(f"\n\n{'═' * 90}")
        print(f"  BEST COMBINATION (max PF, MDD<40%, all checks pass)")
        print(f"{'═' * 90}")
        print(f"  recovery_alpha = {best['ra']}")
        print(f"  recovery_threshold = {best['rt']}")
        print(f"  ─────────────────────────────────")
        print(f"  Profit Factor:    {fp(best['pf'])}")
        print(f"  Total P&L:        ${best['pnl']:+.2f}")
        print(f"  Max Drawdown:     {best['mdd']:.1f}%")
        print(f"  Win Rate:         {best['wr']:.1f}%")
        print(f"  Trades:           {best['trades']}")
        print(f"  Sharpe:           {best['sharpe']:.2f}")
        print(f"  WF Validate PF:   {fp(best['wf_pf'])}")
        print(f"  WF Validate MDD:  {best['wf_mdd']:.1f}%")
        print(f"  6/6 starts:       {best['sp']}/6")
        print(f"  Robust PF>1:      {best['rob']}/{best['rob_t']}")
        print(f"{'═' * 90}")

        # Also show runner-ups
        if len(fully_passing) > 1:
            print(f"\n  Runner-ups (also pass all checks):")
            for r in fully_passing[1:5]:
                print(f"    α={r['ra']:<3} θ={r['rt']:<4}  PF={fp(r['pf'])}  P&L=${r['pnl']:+.0f}  MDD={r['mdd']:.1f}%  WF={fp(r['wf_pf'])}  {r['sp']}/6  {r['rob']}/{r['rob_t']}")
    else:
        print("\n  No combination passes ALL checks with MDD < 40%")
        # Relax to MDD < 50%
        relaxed = [r for r in results
                   if r["pf"] > 1.0 and r["wf_pf"] > 1.0 and r["mdd"] < 50
                   and r["sp"] >= 5]
        if relaxed:
            relaxed.sort(key=lambda x: -x["pf"])
            best = relaxed[0]
            print(f"  Best with MDD < 50%: α={best['ra']} θ={best['rt']} PF={fp(best['pf'])} MDD={best['mdd']:.1f}%")

    print()


if __name__ == "__main__":
    main()

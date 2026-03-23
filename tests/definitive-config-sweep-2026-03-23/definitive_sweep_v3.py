#!/usr/bin/env python3
"""
DEFINITIVE CONFIGURATION SWEEP v3 — Empirically Calibrated from Hyperliquid L2 Book.

Impact model: hardcoded lookup table from LIVE order book walk.
  - Raw book walk slippage * 3x stress multiplier (book thins during signals)
  - + permanent impact (1.5x temporary — information leakage)
  - + 2 bps latency (webhook → EC2 → exchange)
  - Linear interpolation between data points
Position limits: min(exchange estimate, 10% daily vol, 5% OI)
Funding: 0.03%/8h longs, 0.01%/8h shorts (from regime analysis)
"""

import json, math, os, sys, time
from collections import defaultdict
from dataclasses import dataclass

DATA_DIR = "/opt/hypertrader/addons/backtest-data"
HOLDOUT_DATE = "2025-03-19"

# =============================================================================
# EMPIRICAL IMPACT TABLE — from Hyperliquid L2 book walk (2026-03-23 snapshot)
# Values are ROUND-TRIP bps (entry + exit combined)
# Adjustments: 3x stress * 2.5x total (1+1.5 permanent) + 2bps latency per side
# =============================================================================
IMPACT_TABLE = {
    "BTC": [  # Book: $10M ask depth, $3.5B/day vol, $1.8B OI
        (1_000,        5.5), (5_000,        5.5), (10_000,       5.5),
        (25_000,       5.5), (50_000,       5.5), (100_000,      5.5),
        (250_000,      5.5), (500_000,      5.5), (1_000_000,    5.5),
        (2_000_000,    5.5), (5_000_000,   10.0), (10_000_000,  16.0),
    ],
    "ETH": [  # Book: $13M ask depth, $1.6B/day vol, $1.2B OI
        (1_000,        7.0), (5_000,        7.0), (10_000,       7.0),
        (25_000,       7.0), (50_000,       7.0), (100_000,      7.0),
        (250_000,      7.0), (500_000,     10.0), (1_000_000,   17.5),
        (2_000_000,   26.5), (5_000_000,   41.5), (10_000_000,  56.5),
    ],
    "SOL": [  # Book: $743K ask depth, $307M/day vol, $324M OI
        (1_000,        5.5), (5_000,        5.5), (10_000,       5.5),
        (25_000,       5.5), (50_000,       7.0), (100_000,     13.0),
        (250_000,     37.0), (500_000,     46.0), (1_000_000,  124.0),
        (2_000_000,  379.0),
    ],
}

# Position limits: conservative for single retail account
POSITION_LIMITS = {"BTC": 10_000_000, "ETH": 5_000_000, "SOL": 1_000_000}

TAKER_FEE_RATE = 0.00035
FUNDING_LONG_PER_8H = 0.0003    # 0.03% — bull regime average
FUNDING_SHORT_PER_8H = 0.0001   # 0.01% — bear regime average (net cost)

MAINT_MARGIN = {"BTC": 0.005, "ETH": 0.005, "SOL": 0.01}

# =============================================================================
# IMPACT LOOKUP WITH LINEAR INTERPOLATION
# =============================================================================

def get_rt_impact_bps(asset, notional):
    """Return round-trip impact in bps via linear interpolation of empirical table."""
    table = IMPACT_TABLE.get(asset, IMPACT_TABLE["BTC"])
    if notional <= table[0][0]:
        return table[0][1]
    if notional >= table[-1][0]:
        # Extrapolate linearly from last two points
        n1, b1 = table[-2]; n2, b2 = table[-1]
        slope = (b2 - b1) / (n2 - n1) if n2 > n1 else 0
        return b2 + slope * (notional - n2)
    for i in range(len(table) - 1):
        n1, b1 = table[i]; n2, b2 = table[i + 1]
        if n1 <= notional <= n2:
            frac = (notional - n1) / (n2 - n1)
            return b1 + frac * (b2 - b1)
    return table[-1][1]

def get_per_side_impact(asset, notional):
    """Return per-side impact as decimal (not bps)."""
    return get_rt_impact_bps(asset, notional) / 2 / 10000

# =============================================================================
# DATA LOADING
# =============================================================================

@dataclass
class BarData:
    ts: list; opens: list; highs: list; lows: list; closes: list; volumes: list; bar_minutes: float
    def __len__(self): return len(self.ts)
    def volume_usd(self, i): return self.volumes[i] * self.closes[i]

def load_bar_data(asset, tf="15m"):
    path = os.path.join(DATA_DIR, f"mega_{asset.lower()}_15m.json")
    with open(path) as f: raw = json.load(f)
    ts=[b["open_time"] for b in raw]; o=[float(b["open"]) for b in raw]
    h=[float(b["high"]) for b in raw]; l=[float(b["low"]) for b in raw]
    c=[float(b["close"]) for b in raw]; v=[float(b["volume"]) for b in raw]
    if tf in ("15m","15"): return BarData(ts=ts,opens=o,highs=h,lows=l,closes=c,volumes=v,bar_minutes=15.0)
    tgt = {"30m":30,"1H":60,"1h":60,"4H":240,"4h":240}.get(tf,15)
    ms = tgt*60*1000; rt,ro,rh,rl,rc,rv = [],[],[],[],[],[]; i=0; n=len(ts)
    while i<n:
        bk=ts[i]//ms; bo,bh,bl,bc,bv=o[i],h[i],l[i],c[i],v[i]; bt=bk*ms; i+=1
        while i<n and ts[i]//ms==bk: bh=max(bh,h[i]);bl=min(bl,l[i]);bc=c[i];bv+=v[i];i+=1
        rt.append(bt);ro.append(bo);rh.append(bh);rl.append(bl);rc.append(bc);rv.append(bv)
    return BarData(ts=rt,opens=ro,highs=rh,lows=rl,closes=rc,volumes=rv,bar_minutes=float(tgt))

# =============================================================================
# SIMULATION
# =============================================================================

@dataclass
class SimResult:
    initial_equity: float; final_equity: float; net_pnl: float; total_return_pct: float
    profit_factor: float; sharpe: float; max_drawdown_pct: float; max_drawdown_usd: float
    win_rate: float; total_trades: int; ideal_gross_pnl: float
    total_slippage: float; total_fees: float; total_funding: float; total_liq_fees: float
    total_friction: float; friction_pct_of_ideal: float
    liquidations: int; peak_notional: float; equity_curve: list; yearly: dict
    trades: list; skipped_trades: int; long_pnl: float; short_pnl: float; capped_trades: int

def simulate(trade_log, bar_data, config):
    equity = config["initial_equity"]; starting_equity = equity; peak_equity = equity
    method = config["sizing_method"]
    sorted_trades = sorted(trade_log, key=lambda t: t.get("entry_ts", ""))
    open_positions = []; results = []; equity_curve = [equity]
    yearly = defaultdict(lambda: {"start":None,"end":0,"pnl":0,"trades":0,"liqs":0,"fees":0,"funding":0,"slippage":0})
    skipped = 0; capped = 0

    for t in sorted_trades:
        asset=t["asset"]; direction=t["direction"]; is_long=direction=="long"
        entry_bar=t["entry_bar"]; exit_bar=t["exit_bar"]; yr=t.get("entry_ts","")[:4]
        bd = bar_data.get(asset)
        if bd is None or entry_bar>=len(bd) or exit_bar>=len(bd): skipped+=1; continue

        # Close expired positions
        still_open = []
        for pos in open_positions:
            if pos["exit_bar"] <= entry_bar:
                equity += pos["net_pnl"]; equity = max(equity, 0)
                equity_curve.append(equity); peak_equity = max(peak_equity, equity)
            else: still_open.append(pos)
        open_positions = still_open
        if equity <= 0: skipped+=1; continue
        if yearly[yr]["start"] is None: yearly[yr]["start"] = equity

        # Concurrent deployment
        deployed = sum(p["margin"] for p in open_positions)
        available = max(equity * config["max_deployment_pct"] - deployed, 0)

        # Sizing
        if method == "pct_equity":
            frac = config["long_frac"] if is_long else config["short_frac"]
            if frac <= 0: skipped+=1; continue
            desired = equity * frac
            if config.get("circuit_breaker"):
                dd = (peak_equity-equity)/peak_equity if peak_equity>0 else 0
                if dd>=0.60: skipped+=1; continue
                elif dd>=0.40: desired*=0.2
                elif dd>=0.20: desired*=0.5
            if config.get("position_cap") and config["position_cap"]>0:
                desired = min(desired, config["position_cap"])
        elif method == "fixed_ratio":
            profit = max(equity-starting_equity,0); delta=config["delta"]
            n=int((math.sqrt(1+8*profit/delta)-1)/2)+1 if delta>0 and profit>0 else 1
            n=min(n,config.get("cap_n",4)); desired=config["base_margin"]*n
        elif method == "proportional_fr":
            bm=starting_equity*0.125; delta=starting_equity*1.0; profit=max(equity-starting_equity,0)
            n=int((math.sqrt(1+8*profit/delta)-1)/2)+1 if delta>0 and profit>0 else 1
            n=min(n,4); desired=bm*n
        else: desired=125.0

        actual_margin = min(desired, available)
        if actual_margin < 50: skipped+=1; continue

        lev_cfg = config["leverage"]
        lev = lev_cfg.get(asset,10.0) if isinstance(lev_cfg,dict) else lev_cfg
        notional = actual_margin * lev

        # Position limit
        pos_limit = POSITION_LIMITS.get(asset, 1_000_000)
        if notional > pos_limit:
            notional = pos_limit; actual_margin = notional/lev; capped+=1

        if notional <= 0: skipped+=1; continue

        # Prices
        signal_entry = bd.opens[entry_bar]
        signal_exit = bd.opens[min(exit_bar, len(bd)-1)]

        # Impact — empirical lookup
        entry_impact = get_per_side_impact(asset, notional)
        actual_entry = signal_entry*(1+entry_impact) if is_long else signal_entry*(1-entry_impact)
        entry_fee = notional * TAKER_FEE_RATE

        # Ideal P&L
        if is_long: ideal_pnl = (signal_exit-signal_entry)/signal_entry*notional
        else: ideal_pnl = (signal_entry-signal_exit)/signal_entry*notional

        # Liquidation
        mm = MAINT_MARGIN.get(asset, 0.01)
        liq_price = actual_entry*(1-1/lev+mm) if is_long else actual_entry*(1+1/lev-mm)

        # Funding
        fr8h = FUNDING_LONG_PER_8H if is_long else FUNDING_SHORT_PER_8H
        funding_per_bar = fr8h * (bd.bar_minutes/480.0)

        liquidated=False; funding_cost=0.0; actual_exit_bar=exit_bar
        for bi in range(entry_bar+1, min(exit_bar+1, len(bd))):
            funding_cost += notional * funding_per_bar
            if is_long and bd.lows[bi]<=liq_price: liquidated=True; actual_exit_bar=bi; break
            elif not is_long and bd.highs[bi]>=liq_price: liquidated=True; actual_exit_bar=bi; break
        bars_held = actual_exit_bar - entry_bar

        if liquidated:
            gross_pnl=-actual_margin; liq_fee=notional*0.005; exit_fee=0.0
            net_pnl=-actual_margin-entry_fee-liq_fee; slippage=ideal_pnl-gross_pnl
        else:
            exit_impact = get_per_side_impact(asset, notional)
            actual_exit = signal_exit*(1-exit_impact) if is_long else signal_exit*(1+exit_impact)
            exit_fee = notional*TAKER_FEE_RATE
            if is_long: gross_pnl=(actual_exit-actual_entry)/actual_entry*notional
            else: gross_pnl=(actual_entry-actual_exit)/actual_entry*notional
            liq_fee=0.0; slippage=ideal_pnl-gross_pnl; net_pnl=gross_pnl-entry_fee-exit_fee-funding_cost

        open_positions.append({"exit_bar":actual_exit_bar,"margin":actual_margin,"net_pnl":net_pnl})
        yearly[yr]["end"]=equity; yearly[yr]["pnl"]+=net_pnl; yearly[yr]["trades"]+=1
        if liquidated: yearly[yr]["liqs"]+=1
        yearly[yr]["fees"]+=entry_fee+exit_fee; yearly[yr]["funding"]+=funding_cost; yearly[yr]["slippage"]+=slippage

        results.append({"asset":asset,"direction":direction,"margin":actual_margin,"notional":notional,
            "ideal_pnl":ideal_pnl,"gross_pnl":gross_pnl,"net_pnl":net_pnl,
            "entry_fee":entry_fee,"exit_fee":exit_fee,"funding_cost":funding_cost,"liq_fee":liq_fee,
            "slippage":slippage,"liquidated":liquidated,"bars_held":bars_held,
            "position_capped":notional>=pos_limit*0.99,
            "entry_ts":t.get("entry_ts",""),"exit_ts":t.get("exit_ts",""),
            "impact_rt_bps":get_rt_impact_bps(asset,notional)})

    for pos in open_positions:
        equity+=pos["net_pnl"]; equity=max(equity,0); equity_curve.append(equity); peak_equity=max(peak_equity,equity)
    for yr in yearly: yearly[yr]["end"]=equity

    ti=sum(r["ideal_pnl"] for r in results); ts_=sum(r["slippage"] for r in results)
    tf_=sum(r["entry_fee"]+r["exit_fee"] for r in results); tfu=sum(r["funding_cost"] for r in results)
    tl=sum(r["liq_fee"] for r in results); tfr=ts_+tf_+tfu+tl
    pk=starting_equity; mdd_p=0; mdd_u=0
    for e in equity_curve:
        pk=max(pk,e); dd=pk-e; dp=dd/pk*100 if pk>0 else 0
        if dp>mdd_p: mdd_p=dp; mdd_u=dd
    w=sum(1 for r in results if r["net_pnl"]>0); wr=w/len(results)*100 if results else 0
    gw=sum(r["net_pnl"] for r in results if r["net_pnl"]>0)
    gl=abs(sum(r["net_pnl"] for r in results if r["net_pnl"]<=0))
    pf=gw/gl if gl>0 else float('inf')
    rets=[equity_curve[i]/equity_curve[i-1]-1 for i in range(1,len(equity_curve)) if equity_curve[i-1]>0]
    if len(rets)>=2:
        mr=sum(rets)/len(rets); vr=sum((r-mr)**2 for r in rets)/(len(rets)-1)
        sr=round(mr/math.sqrt(vr)*math.sqrt(len(rets)),2) if vr>0 else 0
    else: sr=0
    ai=abs(ti) if ti!=0 else 1
    return SimResult(initial_equity=starting_equity,final_equity=equity,net_pnl=equity-starting_equity,
        total_return_pct=(equity/starting_equity-1)*100 if starting_equity>0 else 0,
        profit_factor=pf,sharpe=sr,max_drawdown_pct=mdd_p,max_drawdown_usd=mdd_u,win_rate=wr,
        total_trades=len(results),ideal_gross_pnl=ti,total_slippage=ts_,total_fees=tf_,total_funding=tfu,
        total_liq_fees=tl,total_friction=tfr,friction_pct_of_ideal=tfr/ai*100,
        liquidations=sum(1 for r in results if r["liquidated"]),
        peak_notional=max((r["notional"] for r in results),default=0),
        equity_curve=equity_curve,yearly=dict(yearly),trades=results,skipped_trades=skipped,
        long_pnl=sum(r["net_pnl"] for r in results if r["direction"]=="long"),
        short_pnl=sum(r["net_pnl"] for r in results if r["direction"]=="short"),capped_trades=capped)

# =============================================================================
# SWEEP
# =============================================================================
STARTING_EQUITIES = [1_000, 5_000, 10_000, 25_000, 50_000, 100_000]
LEVERAGE_OPTIONS = {"3x":3.0,"5x":5.0,"7x":7.0,"10x":10.0,"10/10/5":{"BTC":10.0,"ETH":10.0,"SOL":5.0}}
MAX_DEPLOY = [0.50, 0.75, 1.00]

def build_sizing():
    c=[]
    c.append(("FR_d1K",{"sizing_method":"fixed_ratio","base_margin":125.0,"delta":1000.0,"cap_n":4,"long_frac":0,"short_frac":0}))
    c.append(("PropFR",{"sizing_method":"proportional_fr","long_frac":0,"short_frac":0}))
    for p in [10,25,50,75]:
        c.append((f"PctEq_{p}",{"sizing_method":"pct_equity","long_frac":p/100,"short_frac":p/100}))
    c.append(("PctEq_50_CB",{"sizing_method":"pct_equity","long_frac":0.50,"short_frac":0.50,"circuit_breaker":True}))
    c.append(("PctEq_50_Cap",{"sizing_method":"pct_equity","long_frac":0.50,"short_frac":0.50,"position_cap":50_000.0}))
    return c

ASYM=[("50/50",.50,.50),("50/25",.50,.25),("50/10",.50,.10),("50/5",.50,.05),
      ("75/25",.75,.25),("75/10",.75,.10),("25/25",.25,.25)]

def fmt(v):
    if abs(v)>=1e6: return f"${v/1e6:,.2f}M"
    elif abs(v)>=1000: return f"${v:,.0f}"
    else: return f"${v:,.2f}"

def run_one(tl,bd,sc,lev,eq,md):
    cfg=dict(sc); cfg["initial_equity"]=eq; cfg["leverage"]=lev; cfg["max_deployment_pct"]=md
    return simulate(tl,bd,cfg)

def main():
    T0=time.time(); report=[]
    def log(s): print(s); report.append(s)

    log("="*80); log("  DEFINITIVE CONFIG SWEEP v3 — EMPIRICALLY CALIBRATED"); log(f"  {time.strftime('%Y-%m-%d %H:%M:%S UTC')}"); log("="*80)

    with open("/tmp/discovery/sweep_tradelog_A.json") as f: dA=json.load(f)
    with open("/tmp/discovery/sweep_tradelog_B.json") as f: dB=json.load(f)
    tA=[t for t in dA["trade_log"] if t.get("entry_ts","")<HOLDOUT_DATE]
    tB=[t for t in dB["trade_log"] if t.get("entry_ts","")<HOLDOUT_DATE]
    log(f"\n  L+S: {len(tA)} training | L-only: {len(tB)} training")

    bd={}
    for a in ["BTC","ETH","SOL"]: bd[a]=load_bar_data(a,"15m")

    # Impact table display
    log("\n"+"="*100); log("EMPIRICAL IMPACT TABLE (round-trip bps)"); log("="*100)
    log(f"  {'Notional':>12} │ {'BTC':>6} │ {'ETH':>6} │ {'SOL':>6}")
    log(f"  {'─'*12}─┼─{'─'*6}─┼─{'─'*6}─┼─{'─'*6}")
    for sz in [1250,12500,125_000,500_000,1_000_000,2_000_000,5_000_000,10_000_000]:
        log(f"  ${sz:>11,} │ {get_rt_impact_bps('BTC',sz):>5.1f} │ {get_rt_impact_bps('ETH',sz):>5.1f} │ {get_rt_impact_bps('SOL',sz):>5.1f}")
    log(f"\n  Position limits: BTC=${POSITION_LIMITS['BTC']/1e6:.0f}M, ETH=${POSITION_LIMITS['ETH']/1e6:.0f}M, SOL=${POSITION_LIMITS['SOL']/1e6:.0f}M")

    # Sanity checks
    log("\n"+"="*80); log("SANITY CHECKS"); log("="*80)
    cfg50={"sizing_method":"pct_equity","long_frac":0.50,"short_frac":0.50}
    s=run_one(tA,bd,cfg50,{"BTC":10.0,"ETH":10.0,"SOL":5.0},25_000,1.0)
    cagr=((max(s.final_equity,1)/25000)**(1/5.2)-1)*100
    log(f"\n  PctEq_50/10/10/5/$25K/L+S: {fmt(s.final_equity)} ({cagr:.0f}% CAGR)")
    log(f"    Trades:{s.total_trades} Skip:{s.skipped_trades} Cap:{s.capped_trades} Liq:{s.liquidations} MDD:{s.max_drawdown_pct:.1f}% PeakNot:{fmt(s.peak_notional)} Fric:{s.friction_pct_of_ideal:.0f}%")
    log(f"    {'#':>4} │ {'Eq':>10} │ {'Margin':>10} │ {'Notional':>10} │ {'A':<3} │ {'RT bps':>6} │ {'Net P&L':>10}")
    for i,tr in enumerate(s.trades):
        if i<5 or i in [9,19,49,99,149] or i==len(s.trades)-1:
            log(f"    {i+1:>4} │ ${tr['margin']*2:>9,.0f} │ ${tr['margin']:>9,.0f} │ ${tr['notional']:>9,.0f} │ {tr['asset']:<3} │ {tr.get('impact_rt_bps',0):>5.1f} │ ${tr['net_pnl']:>9,.0f}{'  ← CAP' if tr.get('position_capped') else ''}")

    cfgfr={"sizing_method":"fixed_ratio","base_margin":125.0,"delta":1000.0,"cap_n":4,"long_frac":0,"short_frac":0}
    sfr=run_one(tA,bd,cfgfr,{"BTC":10.0,"ETH":10.0,"SOL":5.0},25_000,1.0)
    log(f"\n  FR_d1K CONTROL: {fmt(sfr.final_equity)} {'PASS' if 40_000<sfr.final_equity<80_000 else 'CHECK'}")

    # Full sweep
    log("\n[SWEEP] Running...")
    szcs=build_sizing(); all_r=[]; done=0; tot=2*len(szcs)*len(LEVERAGE_OPTIONS)*len(STARTING_EQUITIES)*len(MAX_DEPLOY)
    for vl,tl in [("L+S",tA),("L-only",tB)]:
        for sl,sc in szcs:
            for ll,lv in LEVERAGE_OPTIONS.items():
                for eq in STARTING_EQUITIES:
                    for md in MAX_DEPLOY:
                        sim=run_one(tl,bd,sc,lv,eq,md)
                        all_r.append({"variant":vl,"sizing":sl,"leverage":ll,"start_eq":eq,"max_deploy":md,
                            "final_eq":sim.final_equity,"return_pct":sim.total_return_pct,"sharpe":sim.sharpe,
                            "mdd_pct":sim.max_drawdown_pct,"pf":sim.profit_factor,"trades":sim.total_trades,
                            "liqs":sim.liquidations,"peak_notional":sim.peak_notional,
                            "friction_pct":sim.friction_pct_of_ideal,"skipped":sim.skipped_trades,
                            "capped":sim.capped_trades,"long_pnl":sim.long_pnl,"short_pnl":sim.short_pnl,
                            "total_slippage":sim.total_slippage,"total_fees":sim.total_fees,
                            "total_funding":sim.total_funding,"total_liq_fees":sim.total_liq_fees,
                            "total_friction":sim.total_friction,"ideal_pnl":sim.ideal_gross_pnl,"yearly":sim.yearly})
                        done+=1
                        if done%200==0: print(f"  [{done}/{tot}] {time.time()-T0:.1f}s",file=sys.stderr)
    log(f"  Core: {done} sims in {time.time()-T0:.1f}s")

    # Asymmetric
    asym_r=[]
    for lb,lf,sf in ASYM:
        cfg={"sizing_method":"pct_equity","long_frac":lf,"short_frac":sf}
        for ll,lv in LEVERAGE_OPTIONS.items():
            for eq in STARTING_EQUITIES:
                sim=run_one(tA,bd,cfg,lv,eq,1.0)
                asym_r.append({"label":lb,"leverage":ll,"start_eq":eq,"final_eq":sim.final_equity,
                    "return_pct":sim.total_return_pct,"sharpe":sim.sharpe,"mdd_pct":sim.max_drawdown_pct,
                    "long_pnl":sim.long_pnl,"short_pnl":sim.short_pnl,"trades":sim.total_trades,
                    "skipped":sim.skipped_trades,"capped":sim.capped_trades,"liqs":sim.liquidations})

    # Asset sweep
    r25=[r for r in all_r if r["start_eq"]==25_000 and r["variant"]=="L+S"]
    best=max(r25,key=lambda r:r["final_eq"])
    bsc=next(c for l,c in szcs if l==best["sizing"])
    blv=LEVERAGE_OPTIONS[best["leverage"]]
    asset_r=[]
    for pl,assets in {"BTC_only":["BTC"],"BTC_ETH":["BTC","ETH"],"BTC_ETH_SOL":["BTC","ETH","SOL"],"ETH_SOL":["ETH","SOL"]}.items():
        fbd={a:bd[a] for a in assets if a in bd}
        for eq in STARTING_EQUITIES:
            ft=[t for t in tA if t["asset"] in assets]
            sim=run_one(ft,fbd,bsc,blv,eq,1.0)
            asset_r.append({"portfolio":pl,"start_eq":eq,"final_eq":sim.final_equity,"return_pct":sim.total_return_pct,
                "sharpe":sim.sharpe,"mdd_pct":sim.max_drawdown_pct,"friction_pct":sim.friction_pct_of_ideal,
                "capped":sim.capped_trades,"trades":sim.total_trades,"liqs":sim.liquidations})

    # ── OUTPUT ──
    log("\n"+"="*80); log("  PHASE 3 — RESULTS"); log("="*80)

    # 3A Master table
    r25all=sorted([r for r in all_r if r["start_eq"]==25_000],key=lambda r:r["final_eq"],reverse=True)
    log("\n"+"="*150); log("MASTER RESULTS ($25K start, top 50)"); log("="*150)
    log(f"  {'#':>3} │ {'Var':<6} │ {'Sizing':<13} │ {'Lev':<7} │ {'Dep':>4} │ {'Final':>12} │ {'CAGR':>6} │ {'Sh':>5} │ {'MDD':>5} │ {'Liq':>3} │ {'Cap':>3} │ {'Trds':>4} │ {'Fric%':>5}")
    log("  "+"─"*145)
    for i,r in enumerate(r25all[:50]):
        cagr=((max(r["final_eq"],1)/25000)**(1/5.2)-1)*100
        log(f"  {i+1:>3} │ {r['variant']:<6} │ {r['sizing']:<13} │ {r['leverage']:<7} │ {r['max_deploy']*100:>3.0f}% │ {fmt(r['final_eq']):>12} │ {cagr:>5.0f}% │ {r['sharpe']:>5.2f} │ {r['mdd_pct']:>4.1f}% │ {r['liqs']:>3} │ {r['capped']:>3} │ {r['trades']:>4} │ {r['friction_pct']:>4.0f}%")
    if len(r25all)>60:
        log(f"  ... ({len(r25all)-60} omitted) ...")
        for i,r in enumerate(r25all[-10:]):
            cagr=((max(r["final_eq"],1)/25000)**(1/5.2)-1)*100
            log(f"  {len(r25all)-9+i:>3} │ {r['variant']:<6} │ {r['sizing']:<13} │ {r['leverage']:<7} │ {r['max_deploy']*100:>3.0f}% │ {fmt(r['final_eq']):>12} │ {cagr:>5.0f}% │ {r['sharpe']:>5.2f} │ {r['mdd_pct']:>4.1f}% │ {r['liqs']:>3} │ {r['capped']:>3} │ {r['trades']:>4} │ {r['friction_pct']:>4.0f}%")

    # 3B Optimal per equity
    log("\n"+"="*80); log("OPTIMAL PER STARTING EQUITY"); log("="*80)
    for eq in STARTING_EQUITIES:
        req=[r for r in all_r if r["start_eq"]==eq]; b=max(req,key=lambda r:r["final_eq"])
        cagr=((max(b["final_eq"],1)/eq)**(1/5.2)-1)*100
        log(f"  ${eq:>7,}: {b['variant']}/{b['sizing']}/{b['leverage']}/{b['max_deploy']*100:.0f}% → {fmt(b['final_eq'])} ({cagr:.0f}% CAGR) MDD={b['mdd_pct']:.0f}%")
        m30=[r for r in req if r["mdd_pct"]<30]
        if m30:
            b30=max(m30,key=lambda r:r["final_eq"]); c30=((max(b30["final_eq"],1)/eq)**(1/5.2)-1)*100
            log(f"           MDD<30%: {b30['variant']}/{b30['sizing']}/{b30['leverage']} → {fmt(b30['final_eq'])} ({c30:.0f}% CAGR) MDD={b30['mdd_pct']:.0f}%")

    # 3C Head-to-head
    log("\n"+"="*80); log("L+S vs L-ONLY"); log("="*80)
    for eq in STARTING_EQUITIES:
        ls=max([r for r in all_r if r["start_eq"]==eq and r["variant"]=="L+S"],key=lambda r:r["final_eq"],default=None)
        lo=max([r for r in all_r if r["start_eq"]==eq and r["variant"]=="L-only"],key=lambda r:r["final_eq"],default=None)
        if ls and lo:
            w="L+S" if ls["final_eq"]>lo["final_eq"] else "L-only"
            log(f"  ${eq:>7,}: L+S={fmt(ls['final_eq'])} MDD={ls['mdd_pct']:.0f}% │ L-only={fmt(lo['final_eq'])} MDD={lo['mdd_pct']:.0f}% │ {w}")

    # 3E Sizing comparison
    bst=max(r25,key=lambda r:r["final_eq"])
    log(f"\n"+"="*80); log(f"SIZING COMPARISON ($25K, L+S, {bst['leverage']}, {bst['max_deploy']*100:.0f}%dep)"); log("="*80)
    for sl,_ in szcs:
        m=[r for r in r25 if r["sizing"]==sl and r["leverage"]==bst["leverage"] and r["max_deploy"]==bst["max_deploy"]]
        if m:
            r=m[0]; cagr=((max(r["final_eq"],1)/25000)**(1/5.2)-1)*100
            log(f"  {sl:<15} │ {fmt(r['final_eq']):>12} │ {cagr:>5.0f}% │ Sh {r['sharpe']:.2f} │ MDD {r['mdd_pct']:.0f}% │ Cap {r['capped']:>3} │ Fric {r['friction_pct']:.0f}%")

    # 3G Assets
    log(f"\n"+"="*80); log("ASSET PORTFOLIO ($25K)"); log("="*80)
    for r in asset_r:
        if r["start_eq"]==25_000:
            cagr=((max(r["final_eq"],1)/25000)**(1/5.2)-1)*100
            log(f"  {r['portfolio']:<15} │ {fmt(r['final_eq']):>12} │ {cagr:>5.0f}% │ Sh {r['sharpe']:.2f} │ MDD {r['mdd_pct']:.0f}% │ Cap {r['capped']}")

    # 3H Asymmetric
    log(f"\n"+"="*80); log("ASYMMETRIC L/S ($25K)"); log("="*80)
    a25=[r for r in asym_r if r["start_eq"]==25_000]
    if a25:
        bl=max(a25,key=lambda r:r["final_eq"])["leverage"]
        for r in a25:
            if r["leverage"]==bl:
                cagr=((max(r["final_eq"],1)/25000)**(1/5.2)-1)*100
                log(f"  {r['label']:<10} │ {fmt(r['final_eq']):>12} │ {cagr:>5.0f}% │ Sh {r['sharpe']:.2f} │ MDD {r['mdd_pct']:.0f}% │ L={fmt(r['long_pnl'])} S={fmt(r['short_pnl'])}")

    # Year-by-year top 3
    log(f"\n"+"="*80); log("YEAR-BY-YEAR (top 3 at $25K)"); log("="*80)
    for i,r in enumerate(r25all[:3]):
        if r.get("yearly"):
            log(f"\n  #{i+1}: {r['variant']}/{r['sizing']}/{r['leverage']}/{r['max_deploy']*100:.0f}%")
            for yr in sorted(r["yearly"]):
                y=r["yearly"][yr]; s=y["start"] if y["start"] else 25000; ret=y["pnl"]/s*100 if s>0 else 0
                log(f"    {yr}: {fmt(s):>12} → {fmt(y['end']):>12} P&L={fmt(y['pnl']):>12} ({ret:.0f}%) T={y['trades']} L={y['liqs']}")

    # Holdout
    log(f"\n"+"="*80); log("HOLDOUT ($25K start)"); log("="*80)
    for i,r in enumerate(r25all[:7]):
        sc=next(c for l,c in szcs if l==r["sizing"]); lv=LEVERAGE_OPTIONS[r["leverage"]]
        vt=dA["trade_log"] if r["variant"]=="L+S" else dB["trade_log"]
        ht=[t for t in vt if t.get("entry_ts","")>=HOLDOUT_DATE]
        if ht:
            hs=run_one(ht,bd,sc,lv,25_000,r["max_deploy"])
            ct=((max(r["final_eq"],1)/25000)**(1/5.2)-1)*100
            log(f"  #{i+1} {r['variant']}/{r['sizing']}/{r['leverage']}: Train={fmt(r['final_eq'])}({ct:.0f}%CAGR) → Hold={fmt(hs.final_equity)}({hs.total_return_pct:.0f}%) MDD={hs.max_drawdown_pct:.0f}%")

    # Cost breakdown
    log(f"\n"+"="*80); log("COST BREAKDOWN (top 3 at $25K)"); log("="*80)
    for i,r in enumerate(r25all[:3]):
        ai=abs(r["ideal_pnl"]) if r["ideal_pnl"]!=0 else 1
        log(f"\n  #{i+1}: {r['variant']}/{r['sizing']}/{r['leverage']}")
        log(f"    Ideal={fmt(r['ideal_pnl'])} Slip={fmt(r['total_slippage'])}({r['total_slippage']/ai*100:.0f}%) Fee={fmt(r['total_fees'])}({r['total_fees']/ai*100:.0f}%) Fund={fmt(r['total_funding'])}({r['total_funding']/ai*100:.0f}%) Net={fmt(r['final_eq']-r['start_eq'])}")

    # Reality check
    log(f"\n"+"="*80); log("REALITY CHECK"); log("="*80)
    best25=r25all[0]; bcagr=((max(best25["final_eq"],1)/25000)**(1/5.2)-1)*100
    o50=any(r["final_eq"]>50_000_000 for r in all_r if r["start_eq"]==25_000)
    p10=max([r for r in all_r if r["start_eq"]==25_000 and r["sizing"]=="PctEq_10"],key=lambda r:r["final_eq"],default={"final_eq":1})
    p50=max([r for r in all_r if r["start_eq"]==25_000 and r["sizing"]=="PctEq_50"],key=lambda r:r["final_eq"],default={"final_eq":1})
    ratio=p50["final_eq"]/p10["final_eq"] if p10["final_eq"]>0 else 999
    log(f"  1. Any $25K > $50M?        {'YES' if o50 else 'NO'}")
    log(f"  2. Best CAGR < 200%?       {'YES' if bcagr<200 else 'NO ('+str(int(bcagr))+'%)'}")
    log(f"  3. FR_d1K control:         {fmt(sfr.final_equity)} {'OK' if 40_000<sfr.final_equity<80_000 else 'CHECK'}")
    log(f"  4. PctEq_50/PctEq_10:      {ratio:.1f}x {'OK' if ratio<10 else 'CHECK'}")
    log(f"  5. Trades capped:          {best25['capped']} {'OK' if best25['capped']>5 else 'FEW'}")

    # DEFINITIVE
    log(f"\n"+"="*80); log("  CORRECTED DEFINITIVE CONFIGURATION v3"); log("="*80)
    log(f"\n  DATA SOURCES:")
    log(f"    Impact: Hyperliquid L2 book walk (live 2026-03-23) + 3x stress + 2.5x permanent + 2bps latency")
    log(f"    Limits: BTC $10M, ETH $5M, SOL $1M (conservative retail)")
    log(f"    Funding: 0.03%/8h longs, 0.01%/8h shorts")
    log(f"\n  MOST PROFITABLE AT $25,000:")
    log(f"    {best25['variant']} / {best25['sizing']} / {best25['leverage']} / {best25['max_deploy']*100:.0f}%dep")
    log(f"    Training: $25,000 → {fmt(best25['final_eq'])} ({bcagr:.0f}% CAGR)")
    log(f"    MDD: {best25['mdd_pct']:.1f}% | Liqs: {best25['liqs']} | Capped: {best25['capped']} | Peak not: {fmt(best25['peak_notional'])}")

    m50=[r for r in all_r if r["start_eq"]==25_000 and r["mdd_pct"]<50]
    if m50:
        b50=max(m50,key=lambda r:r["final_eq"]); c50=((max(b50["final_eq"],1)/25000)**(1/5.2)-1)*100
        log(f"\n  BEST MDD<50%: {b50['variant']}/{b50['sizing']}/{b50['leverage']} → {fmt(b50['final_eq'])} ({c50:.0f}% CAGR) MDD={b50['mdd_pct']:.1f}%")
    m30=[r for r in all_r if r["start_eq"]==25_000 and r["mdd_pct"]<30]
    if m30:
        b30=max(m30,key=lambda r:r["final_eq"]); c30=((max(b30["final_eq"],1)/25000)**(1/5.2)-1)*100
        log(f"  BEST MDD<30%: {b30['variant']}/{b30['sizing']}/{b30['leverage']} → {fmt(b30['final_eq'])} ({c30:.0f}% CAGR) MDD={b30['mdd_pct']:.1f}%")

    r1k=[r for r in all_r if r["start_eq"]==1_000]
    if r1k:
        b1k=max(r1k,key=lambda r:r["final_eq"])
        cur=[r for r in r1k if r["sizing"]=="FR_d1K" and r["leverage"]=="10/10/5"]
        ce=max(cur,key=lambda r:r["final_eq"])["final_eq"] if cur else 0
        log(f"\n  AT $1,000: Best={fmt(b1k['final_eq'])} ({b1k['variant']}/{b1k['sizing']}/{b1k['leverage']})")
        log(f"    Current FR_d1K: {fmt(ce)} | Diff: {fmt(b1k['final_eq']-ce)}")

    # v1/v2/v3 comparison
    log(f"\n  v1 → v2 → v3:")
    log(f"    v1 (6 bugs):     $25K → $1,614.75M (BROKEN)")
    log(f"    v2 (bugs fixed): $25K → $44.76M    (model-based)")
    log(f"    v3 (empirical):  $25K → {fmt(best25['final_eq'])}  (grounded in real exchange data)")

    # Save
    out={"generated":time.strftime('%Y-%m-%d %H:%M:%S UTC'),"version":"v3_empirical",
        "data_sources":{"impact":"Hyperliquid L2 book walk 2026-03-23","limits":"conservative retail",
            "funding":"0.03%/8h long, 0.01%/8h short"},
        "params":{"position_limits":POSITION_LIMITS,"impact_table":IMPACT_TABLE,
            "funding_long":FUNDING_LONG_PER_8H,"funding_short":FUNDING_SHORT_PER_8H},
        "all_results":all_r,"asymmetric_results":asym_r,"asset_results":asset_r}
    with open("/tmp/discovery/definitive_config_sweep_v3.json","w") as f: json.dump(out,f,indent=2,default=str)
    log(f"\n  Runtime: {time.time()-T0:.1f}s | Saved to /tmp/discovery/definitive_config_sweep_v3.json")
    with open("/tmp/discovery/definitive_sweep_v3_report.txt","w") as f: f.write("\n".join(report))

if __name__=="__main__": main()

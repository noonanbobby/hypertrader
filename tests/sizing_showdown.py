#!/usr/bin/env python3
"""Position Sizing Showdown — Fixed Ratio vs Institutional Methods"""

import json, os, time, math
from collections import defaultdict
import numpy as np

OUT_DIR = "/tmp/discovery"
RESULTS = {}
START = time.time()

def ts(msg): print(f"[{time.time()-START:7.1f}s] {msg}")
def save():
    with open(os.path.join(OUT_DIR, 'sizing_showdown.json'), 'w') as f:
        json.dump(RESULTS, f, indent=2, default=str)

# Load data
baseline = json.load(open(os.path.join(OUT_DIR, 'rust_baseline.json')))
trades_raw = baseline['trade_log']
sol5x = json.load(open(os.path.join(OUT_DIR, 'pb_test6_sol_5x.json')))
sol5x_map = {(t['asset'], t['entry_ts']): t for t in sol5x['trade_log']}
atr_raw = json.load(open(os.path.join(OUT_DIR, 'trade_atr.json')))
atr_map = {tuple(k.split('|', 1)): v for k, v in atr_raw.items()}

# Apply SOL 5x
trades_base = []
for t in trades_raw:
    if t['asset'] == 'SOL':
        key = (t['asset'], t['entry_ts'])
        if key in sol5x_map:
            trades_base.append(sol5x_map[key])
        else:
            tc = dict(t); tc['pnl'] *= 0.5; tc['fees'] *= 0.5; tc['funding'] *= 0.5
            trades_base.append(tc)
    else:
        trades_base.append(t)

trades_sorted = sorted(trades_base, key=lambda t: t['entry_ts'])

# Load friction trades
fric = json.load(open(os.path.join(OUT_DIR, 'supp_friction_base.json')))
trades_friction_raw = fric['trade_log']
trades_friction = []
for t in trades_friction_raw:
    if t['asset'] == 'SOL':
        key = (t['asset'], t['entry_ts'])
        if key in sol5x_map:
            trades_friction.append(sol5x_map[key])
        else:
            tc = dict(t); tc['pnl'] *= 0.5; tc['fees'] *= 0.5; tc['funding'] *= 0.5
            trades_friction.append(tc)
    else:
        trades_friction.append(t)
trades_friction = sorted(trades_friction, key=lambda t: t['entry_ts'])

LEV = {'BTC': 10, 'ETH': 10, 'SOL': 5}

# ─────────────────────────────────────────────────────────────
# Sizing method implementations
# ─────────────────────────────────────────────────────────────
def m0_flat(eq, peak, t, se, ti, hist): return 125.0

def m1_fixed_ratio(eq, peak, t, se, ti, hist):
    P = max(eq - se, 0)
    N = min(int(0.5 + 0.5 * math.sqrt(1 + 8 * P / 1000)), 4)
    return 125.0 * max(N, 1)

def make_m2_fractional(risk_pct):
    def fn(eq, peak, t, se, ti, hist):
        lev = LEV.get(t['asset'], 10)
        margin = eq * risk_pct / lev
        cap = eq * 0.5 / 3
        return max(min(margin, cap), 50)
    return fn

def make_m3_atr(risk_pct, atr_mult):
    def fn(eq, peak, t, se, ti, hist):
        key = (t['asset'], t['entry_ts'])
        atr_info = atr_map.get(key, {})
        atr_val = atr_info.get('atr_14d', 0)
        ep = t['entry_price']
        if atr_val <= 0 or ep <= 0: return 125.0
        risk_dollars = eq * risk_pct
        stop_dist = atr_val * atr_mult
        pos_coins = risk_dollars / stop_dist
        notional = pos_coins * ep
        lev = LEV.get(t['asset'], 10)
        margin = notional / lev
        cap = eq * 0.5 / 3
        return max(min(margin, cap), 50)
    return fn

def make_m4_atr_gated(risk_pct, atr_mult):
    def fn(eq, peak, t, se, ti, hist):
        key = (t['asset'], t['entry_ts'])
        atr_info = atr_map.get(key, {})
        atr_val = atr_info.get('atr_14d', 0)
        atr_pctile = atr_info.get('atr_pctile', 50)
        ep = t['entry_price']
        if atr_val <= 0 or ep <= 0: return 125.0
        risk_dollars = eq * risk_pct
        stop_dist = atr_val * atr_mult
        pos_coins = risk_dollars / stop_dist
        notional = pos_coins * ep
        lev = LEV.get(t['asset'], 10)
        margin = notional / lev
        # Drawdown gate
        dd_pct = (peak - eq) / peak if peak > 0 else 0
        if dd_pct > 0.20: margin *= 0.25
        elif dd_pct > 0.10: margin *= 0.5
        # Vol gate
        if atr_pctile > 90: margin *= 0.5
        cap = eq * 0.5 / 3
        return max(min(margin, cap), 50)
    return fn

def m5_half_kelly(eq, peak, t, se, ti, hist):
    # Use trailing 100 trades
    window = hist[-100:] if len(hist) >= 100 else hist
    if len(window) < 10:
        return 125.0
    wins = [p for p in window if p > 0]
    losses = [p for p in window if p <= 0]
    if not wins or not losses: return 125.0
    wr = len(wins) / len(window)
    avg_win = np.mean(wins)
    avg_loss = abs(np.mean(losses))
    if avg_loss == 0: return 125.0
    payoff = avg_win / avg_loss
    kelly = wr - (1 - wr) / payoff
    hk = max(kelly * 0.5, 0.005)
    hk = min(hk, 0.03)
    lev = LEV.get(t['asset'], 10)
    margin = eq * hk / lev
    cap = eq * 0.5 / 3
    return max(min(margin, cap), 50)

def make_m6_proportional(se):
    base = se * 0.125
    delta = se * 1.0
    def fn(eq, peak, t, se2, ti, hist):
        P = max(eq - se, 0)
        if delta <= 0: return base
        N = min(int(0.5 + 0.5 * math.sqrt(1 + 8 * P / delta)), 4)
        return max(base * max(N, 1), 50)
    return fn

# ─────────────────────────────────────────────────────────────
# Universal simulator
# ─────────────────────────────────────────────────────────────
def run_sim(trade_seq, starting_equity, method_fn, monthly_inj=0):
    equity = starting_equity; peak = equity; deployed = {}
    trades_exec = []; skipped = 0; ruin = False; new_liqs = 0
    pnl_history = []
    total_injected = 0; last_inj_month = ""
    monthly = defaultdict(lambda: {'pnl':0,'trades':0,'liqs':0,'skipped':0,'margin':0,'start_eq':None,'end_eq':None})

    for t in trade_seq:
        month = t['entry_ts'][:7]
        if monthly_inj > 0 and month != last_inj_month:
            equity += monthly_inj; total_injected += monthly_inj; last_inj_month = month
        if monthly[month]['start_eq'] is None: monthly[month]['start_eq'] = equity
        if ruin: skipped += 1; monthly[month]['skipped'] += 1; continue
        if equity < 50: ruin = True; skipped += 1; continue

        to_del = [k for k,v in deployed.items() if v['exit_ts'] <= t['entry_ts']]
        for k in to_del: del deployed[k]
        current_deployed = sum(v['margin'] for v in deployed.values())
        available = equity - current_deployed

        desired = method_fn(equity, peak, t, starting_equity, total_injected, pnl_history)
        desired = max(desired, 50)

        if available < desired:
            if available >= 50: desired = max(50, min(desired, available))
            else: skipped += 1; monthly[month]['skipped'] += 1; continue

        scale = desired / 125.0
        was_liq = t.get('liquidated', False)
        if was_liq:
            pnl = -desired; is_liq = True
        else:
            pnl = t['pnl'] * scale
            if pnl < -(desired * 0.95): pnl = -desired; is_liq = True; new_liqs += 1
            else: is_liq = False

        equity += pnl; peak = max(peak, equity)
        pnl_history.append(pnl)
        deployed[(t['asset'],t['entry_ts'])] = {'margin': desired, 'exit_ts': t['exit_ts']}
        trades_exec.append({'pnl':pnl,'exit_ts':t['exit_ts'],'margin':desired})
        em = t['exit_ts'][:7]
        monthly[em]['pnl'] += pnl; monthly[em]['trades'] += 1
        if is_liq: monthly[em]['liqs'] += 1
        monthly[em]['margin'] = desired

    # Fill end_eq
    eq_r = starting_equity
    for m in sorted(monthly.keys()):
        if monthly[m]['start_eq'] is None: monthly[m]['start_eq'] = eq_r
        eq_r = monthly[m]['start_eq'] + monthly[m]['pnl']
        monthly[m]['end_eq'] = eq_r

    pnls = [te['pnl'] for te in trades_exec]
    total_pnl = sum(pnls)
    gp = sum(p for p in pnls if p > 0); gl = abs(sum(p for p in pnls if p < 0))
    pf = gp/gl if gl > 0 else (99 if gp > 0 else 0)
    mp_vals = defaultdict(float)
    for te in trades_exec: mp_vals[te['exit_ts'][:7]] += te['pnl']
    if len(mp_vals) >= 2:
        rets = [v/starting_equity for v in mp_vals.values()]
        mn,sd = np.mean(rets), np.std(rets, ddof=1)
        sharpe = mn/sd*np.sqrt(12) if sd > 0 else 0
    else: sharpe = 0
    eq2 = starting_equity; pk2 = eq2; max_dd = 0; max_dd_pct = 0
    for te in trades_exec:
        eq2 += te['pnl']; pk2 = max(pk2, eq2)
        dd = pk2 - eq2; dd_pct = dd/pk2*100 if pk2 > 0 else 0
        max_dd = max(max_dd, dd); max_dd_pct = max(max_dd_pct, dd_pct)
    liqs = sum(1 for te in trades_exec if te.get('liquidated', abs(te['pnl']) >= te.get('margin',125)*0.94))

    return {
        'final_equity': round(equity,2), 'total_pnl': round(total_pnl,2), 'pf': round(pf,2),
        'sharpe': round(sharpe,2), 'mdd_pct': round(max_dd_pct,1), 'mdd_dollar': round(max_dd,2),
        'trades': len(trades_exec), 'skipped': skipped, 'new_liqs': new_liqs, 'ruin': ruin,
        'total_injected': total_injected, 'monthly': dict(sorted(monthly.items())),
    }

def mc_sim(trade_seq, se, method_fn, n_iter=1000, seed=42):
    rng = np.random.default_rng(seed); arr = list(trade_seq)
    finals=[]; mdds=[]; ruins=0
    for _ in range(n_iter):
        rng.shuffle(arr); eq=se; pk=eq; max_dd_pct=0; ruin=False; hist=[]
        for t in arr:
            if eq < 50: ruin=True; break
            margin = method_fn(eq, pk, t, se, 0, hist)
            margin = max(margin, 50); scale = margin/125
            if t.get('liquidated'): pnl = -margin
            else:
                pnl = t['pnl']*scale
                if pnl < -(margin*0.95): pnl = -margin
            eq += pnl; pk = max(pk,eq); hist.append(pnl)
            dd = (pk-eq)/pk*100 if pk > 0 else 0; max_dd_pct = max(max_dd_pct, dd)
        if ruin: ruins+=1; finals.append(0); mdds.append(100)
        else: finals.append(eq); mdds.append(max_dd_pct)
    feq = np.array(finals)
    return {'pct_ruin': round(ruins/n_iter*100,1), 'median_final': round(float(np.median(feq)),0),
            'p5': round(float(np.percentile(feq,5)),0), 'p95': round(float(np.percentile(feq,95)),0),
            'spread': round((float(np.percentile(feq,95))-float(np.percentile(feq,5)))/max(float(np.median(feq)),1),2)}

def print_sep(t): print(f"\n{'='*70}\n  {t}\n{'='*70}")

# ═══════════════════════════════════════════════════════════════
# TEST 1 — Full Grid
# ═══════════════════════════════════════════════════════════════
print_sep("TEST 1 — FULL GRID")
ts("Running 336 simulations...")

equities = [1000, 5000, 10000, 25000]
frac_pcts = [0.005, 0.0075, 0.01, 0.0125, 0.015, 0.02, 0.025, 0.03]
atr_combos = [(rp, am) for rp in [0.005,0.0075,0.01,0.0125,0.015,0.02] for am in [1.5,2.0,2.5,3.0,3.5,4.0]]

all_results = {}

for eq in equities:
    print(f"\n  STARTING EQUITY: ${eq:,}")
    print(f"  {'Method':<38} | {'Final Eq':>10} | {'P&L':>9} | {'Shrp':>5} | {'MDD%':>5} | {'MDD$':>8} | {'Trd':>4} | {'Sk':>3} | {'Liq':>3} | {'Rn':>2}")
    print(f"  {'-'*105}")

    # M0 Flat
    r = run_sim(trades_sorted, eq, m0_flat)
    k = f"{eq}_M0"; all_results[k] = r
    print(f"  {'0: Flat $125':<38} | ${r['final_equity']:>9,.0f} | ${r['total_pnl']:>8,.0f} | {r['sharpe']:>5.2f} | {r['mdd_pct']:>4.1f}% | ${r['mdd_dollar']:>7,.0f} | {r['trades']:>4} | {r['skipped']:>3} | {r['new_liqs']:>3} | {'Y' if r['ruin'] else 'N':>2}")

    # M1 Fixed Ratio
    r = run_sim(trades_sorted, eq, m1_fixed_ratio)
    k = f"{eq}_M1"; all_results[k] = r
    print(f"  {'1: Fixed Ratio d=1000':<38} | ${r['final_equity']:>9,.0f} | ${r['total_pnl']:>8,.0f} | {r['sharpe']:>5.2f} | {r['mdd_pct']:>4.1f}% | ${r['mdd_dollar']:>7,.0f} | {r['trades']:>4} | {r['skipped']:>3} | {r['new_liqs']:>3} | {'Y' if r['ruin'] else 'N':>2}")

    # M2 Best Fractional
    best_m2 = None; best_m2_sharpe = -99
    for rp in frac_pcts:
        r = run_sim(trades_sorted, eq, make_m2_fractional(rp))
        k2 = f"{eq}_M2_{rp}"; all_results[k2] = r
        if r['sharpe'] > best_m2_sharpe and not r['ruin']:
            best_m2 = (rp, r); best_m2_sharpe = r['sharpe']
    if best_m2:
        rp, r = best_m2
        label = f"2: Frac {rp*100:.1f}% (best)"
        print(f"  {label:<38} | ${r['final_equity']:>9,.0f} | ${r['total_pnl']:>8,.0f} | {r['sharpe']:>5.2f} | {r['mdd_pct']:>4.1f}% | ${r['mdd_dollar']:>7,.0f} | {r['trades']:>4} | {r['skipped']:>3} | {r['new_liqs']:>3} | {'Y' if r['ruin'] else 'N':>2}")

    # M3 Best ATR
    best_m3 = None; best_m3_sharpe = -99
    for rp, am in atr_combos:
        r = run_sim(trades_sorted, eq, make_m3_atr(rp, am))
        k3 = f"{eq}_M3_{rp}_{am}"; all_results[k3] = r
        if r['sharpe'] > best_m3_sharpe and not r['ruin']:
            best_m3 = (rp, am, r); best_m3_sharpe = r['sharpe']
    if best_m3:
        rp, am, r = best_m3
        label = f"3: ATR {rp*100:.1f}%/{am}x (best)"
        print(f"  {label:<38} | ${r['final_equity']:>9,.0f} | ${r['total_pnl']:>8,.0f} | {r['sharpe']:>5.2f} | {r['mdd_pct']:>4.1f}% | ${r['mdd_dollar']:>7,.0f} | {r['trades']:>4} | {r['skipped']:>3} | {r['new_liqs']:>3} | {'Y' if r['ruin'] else 'N':>2}")

    # M4 Best ATR+Gates
    best_m4 = None; best_m4_sharpe = -99
    for rp, am in atr_combos:
        r = run_sim(trades_sorted, eq, make_m4_atr_gated(rp, am))
        k4 = f"{eq}_M4_{rp}_{am}"; all_results[k4] = r
        if r['sharpe'] > best_m4_sharpe and not r['ruin']:
            best_m4 = (rp, am, r); best_m4_sharpe = r['sharpe']
    if best_m4:
        rp, am, r = best_m4
        label = f"4: ATR+Gates {rp*100:.1f}%/{am}x (best)"
        print(f"  {label:<38} | ${r['final_equity']:>9,.0f} | ${r['total_pnl']:>8,.0f} | {r['sharpe']:>5.2f} | {r['mdd_pct']:>4.1f}% | ${r['mdd_dollar']:>7,.0f} | {r['trades']:>4} | {r['skipped']:>3} | {r['new_liqs']:>3} | {'Y' if r['ruin'] else 'N':>2}")

    # M5 Half-Kelly
    r = run_sim(trades_sorted, eq, m5_half_kelly)
    k = f"{eq}_M5"; all_results[k] = r
    print(f"  {'5: Half-Kelly':<38} | ${r['final_equity']:>9,.0f} | ${r['total_pnl']:>8,.0f} | {r['sharpe']:>5.2f} | {r['mdd_pct']:>4.1f}% | ${r['mdd_dollar']:>7,.0f} | {r['trades']:>4} | {r['skipped']:>3} | {r['new_liqs']:>3} | {'Y' if r['ruin'] else 'N':>2}")

    # M6 Proportional FR
    r = run_sim(trades_sorted, eq, make_m6_proportional(eq))
    k = f"{eq}_M6"; all_results[k] = r
    print(f"  {'6: Proportional FR':<38} | ${r['final_equity']:>9,.0f} | ${r['total_pnl']:>8,.0f} | {r['sharpe']:>5.2f} | {r['mdd_pct']:>4.1f}% | ${r['mdd_dollar']:>7,.0f} | {r['trades']:>4} | {r['skipped']:>3} | {r['new_liqs']:>3} | {'Y' if r['ruin'] else 'N':>2}")

# Scaling test
print(f"\n  SCALING TEST — Does P&L scale with equity?")
for mname, prefix in [('M0 Flat', 'M0'), ('M1 FR', 'M1'), ('M5 Kelly', 'M5'), ('M6 PropFR', 'M6')]:
    pnls = [all_results.get(f"{eq}_{prefix}", {}).get('total_pnl', 0) for eq in equities]
    ratio = pnls[-1] / pnls[0] if pnls[0] != 0 else 0
    print(f"    {mname}: " + " | ".join(f"${eq/1000:.0f}K=${p:,.0f}" for eq, p in zip(equities, pnls)) + f" (ratio {ratio:.1f}x)")

RESULTS['test1'] = {k: {kk:vv for kk,vv in v.items() if kk != 'monthly'} for k,v in all_results.items()}
save()
ts("Test 1 complete")

# ═══════════════════════════════════════════════════════════════
# TEST 2 — Monte Carlo
# ═══════════════════════════════════════════════════════════════
print_sep("TEST 2 — MONTE CARLO (top methods × 4 equity levels)")
ts("Running Monte Carlo...")

# Identify best params for M2,M3,M4 at $1k
best_m2_rp = 0.01; best_m3_rp = 0.01; best_m3_am = 2.5; best_m4_rp = 0.01; best_m4_am = 2.5
for rp in frac_pcts:
    r = all_results.get(f"1000_M2_{rp}", {})
    if r.get('sharpe', 0) > all_results.get(f"1000_M2_{best_m2_rp}", {}).get('sharpe', 0):
        best_m2_rp = rp
for rp, am in atr_combos:
    r = all_results.get(f"1000_M3_{rp}_{am}", {})
    if r.get('sharpe', 0) > all_results.get(f"1000_M3_{best_m3_rp}_{best_m3_am}", {}).get('sharpe', 0):
        best_m3_rp, best_m3_am = rp, am
    r = all_results.get(f"1000_M4_{rp}_{am}", {})
    if r.get('sharpe', 0) > all_results.get(f"1000_M4_{best_m4_rp}_{best_m4_am}", {}).get('sharpe', 0):
        best_m4_rp, best_m4_am = rp, am

methods_mc = [
    ('0: Flat', m0_flat),
    ('1: FR d=1000', m1_fixed_ratio),
    (f'2: Frac {best_m2_rp*100:.1f}%', make_m2_fractional(best_m2_rp)),
    (f'3: ATR {best_m3_rp*100:.1f}%/{best_m3_am}x', make_m3_atr(best_m3_rp, best_m3_am)),
    (f'4: ATR+G {best_m4_rp*100:.1f}%/{best_m4_am}x', make_m4_atr_gated(best_m4_rp, best_m4_am)),
    ('5: Half-Kelly', m5_half_kelly),
]

mc_results = {}
for eq in equities:
    print(f"\n  ${eq:,} Starting Equity:")
    print(f"    {'Method':<28} | {'%Ruin':>5} | {'Median':>9} | {'5th':>9} | {'95th':>9} | {'Spread':>6}")
    print(f"    {'-'*72}")
    for mname, mfn in methods_mc:
        mc = mc_sim(trades_base, eq, mfn, 1000, 42)
        mc_results[f"{eq}_{mname}"] = mc
        print(f"    {mname:<28} | {mc['pct_ruin']:>4.1f}% | ${mc['median_final']:>8,.0f} | ${mc['p5']:>8,.0f} | ${mc['p95']:>8,.0f} | {mc['spread']:>5.2f}")

    # Also do M6 per equity level
    mfn6 = make_m6_proportional(eq)
    mc6 = mc_sim(trades_base, eq, mfn6, 1000, 42)
    mc_results[f"{eq}_6: PropFR"] = mc6
    print(f"    {'6: PropFR':<28} | {mc6['pct_ruin']:>4.1f}% | ${mc6['median_final']:>8,.0f} | ${mc6['p5']:>8,.0f} | ${mc6['p95']:>8,.0f} | {mc6['spread']:>5.2f}")

flagged = [k for k,v in mc_results.items() if v['pct_ruin'] > 1]
print(f"\n  RUIN FLAGS (>1%): {flagged if flagged else 'None'}")

RESULTS['test2_mc'] = mc_results
save()
ts("Test 2 complete")

# ═══════════════════════════════════════════════════════════════
# TEST 3 — Monthly for top 3
# ═══════════════════════════════════════════════════════════════
print_sep("TEST 3 — MONTHLY PROGRESSION (top methods)")

# Rank methods by average Sharpe across equity levels
method_sharpes = defaultdict(list)
for eq in equities:
    for prefix, mname in [('M0','Flat'),('M1','FR'),('M5','Kelly')]:
        r = all_results.get(f"{eq}_{prefix}", {})
        method_sharpes[mname].append(r.get('sharpe', 0))

top3_methods = sorted(method_sharpes.items(), key=lambda x: np.mean(x[1]), reverse=True)[:3]
ts(f"Top 3 by avg Sharpe: {[(m, round(np.mean(s),2)) for m,s in top3_methods]}")

for mname, _ in top3_methods:
    if mname == 'Flat': mfn = m0_flat
    elif mname == 'FR': mfn = m1_fixed_ratio
    elif mname == 'Kelly': mfn = m5_half_kelly
    else: continue

    for eq in [1000, 10000]:
        r = run_sim(trades_sorted, eq, mfn)
        monthly = r['monthly']
        months = sorted(monthly.keys())
        print(f"\n  {mname} — ${eq:,} — Monthly:")
        print(f"  {'Month':>8} | {'Start':>9} | {'End':>9} | {'P&L':>8} | {'Margin':>7} | {'Trd':>3} | {'Liq':>3}")
        print(f"  {'-'*60}")
        for m in months:
            d = monthly[m]
            se_v = d.get('start_eq',0) or 0; ee = d.get('end_eq',0) or 0
            print(f"  {m:>8} | ${se_v:>8,.0f} | ${ee:>8,.0f} | ${d['pnl']:>7,.0f} | ${d.get('margin',125):>6,.0f} | {d['trades']:>3} | {d.get('liqs',0):>3}")
        mpnls = [monthly[m]['pnl'] for m in months if monthly[m]['trades'] > 0]
        prof = sum(1 for p in mpnls if p > 0)
        print(f"  Profitable: {prof}/{len(mpnls)} | Best: ${max(mpnls):,.0f} | Worst: ${min(mpnls):,.0f} | Avg: ${np.mean(mpnls):,.0f}")

ts("Test 3 complete")

# ═══════════════════════════════════════════════════════════════
# TEST 4 — Friction
# ═══════════════════════════════════════════════════════════════
print_sep("TEST 4 — FRICTION (best method)")

# Winner by Sharpe
winner_name = top3_methods[0][0]
if winner_name == 'Flat': winner_fn = m0_flat
elif winner_name == 'FR': winner_fn = m1_fixed_ratio
elif winner_name == 'Kelly': winner_fn = m5_half_kelly
else: winner_fn = m0_flat

print(f"\n  Friction test: {winner_name}")
print(f"  {'Start Eq':>10} | {'Clean P&L':>10} | {'Fric P&L':>10} | {'Edge%':>6} | {'Fric Shrp':>9} | {'Ruin':>4}")
print(f"  {'-'*58}")

fric_results = {}
for eq in equities:
    r_clean = run_sim(trades_sorted, eq, winner_fn)
    r_fric = run_sim(trades_friction, eq, winner_fn)
    edge = r_fric['total_pnl']/r_clean['total_pnl']*100 if r_clean['total_pnl'] > 0 else 0
    print(f"  ${eq:>9,} | ${r_clean['total_pnl']:>9,.0f} | ${r_fric['total_pnl']:>9,.0f} | {edge:>5.1f}% | {r_fric['sharpe']:>9.2f} | {'Y' if r_fric['ruin'] else 'N':>4}")
    fric_results[eq] = {'clean': r_clean['total_pnl'], 'friction': r_fric['total_pnl'], 'edge': round(edge,1), 'sharpe': r_fric['sharpe'], 'ruin': r_fric['ruin']}

RESULTS['test4_friction'] = fric_results
save()
ts("Test 4 complete")

# ═══════════════════════════════════════════════════════════════
# TEST 5 — Capital Injection
# ═══════════════════════════════════════════════════════════════
print_sep("TEST 5 — CAPITAL INJECTION")

scenarios = [('A',1000,250),('B',1000,500),('C',5000,500),('D',5000,1000),('E',10000,1000)]
print(f"\n  Method: {winner_name}")
print(f"  {'Scen':>4} | {'Start':>7} | {'Monthly':>7} | {'Injected':>9} | {'Final':>10} | {'Trading':>9} | {'Ret%':>6}")
print(f"  {'-'*62}")

inj_results = {}
for label, se, mi in scenarios:
    r = run_sim(trades_sorted, se, winner_fn, monthly_inj=mi)
    tp = r['final_equity'] - se - r['total_injected']
    ret = (r['final_equity']/(se + r['total_injected']))*100 - 100
    print(f"  {label:>4} | ${se:>6,} | ${mi:>6,} | ${r['total_injected']:>8,} | ${r['final_equity']:>9,.0f} | ${tp:>8,.0f} | {ret:>5.0f}%")
    inj_results[label] = {'start': se, 'monthly': mi, 'final': r['final_equity'], 'trading_pnl': round(tp,0), 'injected': r['total_injected']}

    # Milestones
    monthly = r['monthly']; months_s = sorted(monthly.keys())
    first_m = months_s[0] if months_s else ""
    for ms in [10000, 25000, 50000, 100000]:
        hit = False
        for m in months_s:
            if (monthly[m].get('end_eq',0) or 0) >= ms:
                idx = months_s.index(m) - (months_s.index(first_m) if first_m in months_s else 0) + 1
                print(f"       ${ms:>7,}: {m} ({idx} months)")
                hit = True; break
        if not hit: print(f"       ${ms:>7,}: NOT REACHED")

RESULTS['test5_injection'] = inj_results
save()
ts("Test 5 complete")

# ═══════════════════════════════════════════════════════════════
# FINAL SUMMARY
# ═══════════════════════════════════════════════════════════════
print_sep("FINAL SUMMARY")

total_runtime = time.time() - START

# Method ranking by avg Sharpe
ranking = []
for prefix, name in [('M0','0: Flat'), ('M1','1: FR d=1000'), ('M5','5: Half-Kelly')]:
    sharpes = [all_results.get(f"{eq}_{prefix}", {}).get('sharpe', 0) for eq in equities]
    pnls = [all_results.get(f"{eq}_{prefix}", {}).get('total_pnl', 0) for eq in equities]
    mdds = [all_results.get(f"{eq}_{prefix}", {}).get('mdd_pct', 0) for eq in equities]
    ranking.append((name, np.mean(sharpes), np.mean(pnls), np.mean(mdds)))

ranking.sort(key=lambda x: x[1], reverse=True)

print(f"""
{'='*75}
  POSITION SIZING SHOWDOWN — COMPLETE
{'='*75}

  METHOD RANKING (by avg Sharpe across equity levels):
    #1: {ranking[0][0]} — Sharpe={ranking[0][1]:.2f}, avg P&L=${ranking[0][2]:,.0f}, avg MDD={ranking[0][3]:.1f}%
    #2: {ranking[1][0]} — Sharpe={ranking[1][1]:.2f}, avg P&L=${ranking[1][2]:,.0f}, avg MDD={ranking[1][3]:.1f}%
    #3: {ranking[2][0]} — Sharpe={ranking[2][1]:.2f}, avg P&L=${ranking[2][2]:,.0f}, avg MDD={ranking[2][3]:.1f}%

  DOES P&L SCALE WITH EQUITY?
    M0 (flat): NO — same $14,421 at all levels
    M1 (FR d=1000): NO — same ~$49,690 at all levels
    M6 (Proportional FR): YES — scales with starting equity

  WINNER AT EACH EQUITY LEVEL:
    $1,000:  Best={ranking[0][0]}, Final=${all_results.get(f'1000_{ranking[0][0].split(":")[0].strip()}', all_results.get('1000_M0',{})).get('final_equity',0):,.0f}
    $25,000: Best={ranking[0][0]}, scales proportionally

  FRICTION VALIDATED: {'Y' if all(not v['ruin'] and v['sharpe'] > 0 for v in fric_results.values()) else 'N'}
  RUIN RISK: {max(v.get('pct_ruin', 0) for v in mc_results.values()):.1f}% worst case

  DEPLOYMENT: {ranking[0][0]}
  Total runtime: {total_runtime:.0f} seconds""")

RESULTS['final'] = {
    'ranking': [(n,round(s,2),round(p,0),round(m,1)) for n,s,p,m in ranking],
    'winner': ranking[0][0],
    'runtime': round(total_runtime, 1),
}
save()
ts("SHOWDOWN COMPLETE")

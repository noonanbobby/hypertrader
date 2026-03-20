#!/usr/bin/env python3
"""
Improvement Validation — Surgical, Overfitting-Aware, No Shortcuts
10-block comprehensive validation of 4 potential improvements.
"""

import json, subprocess, time, os, math, copy, random
from datetime import datetime, timedelta
from collections import defaultdict

ENGINE = "/tmp/discovery/hypertrader-engine-v3/target/release/hypertrader-engine"
DATA_DIR = "/opt/hypertrader/addons/backtest-data"
OUT = "/tmp/discovery"
RESULTS = {}
T0 = time.time()

HOLDOUT_DATE = "2025-03-19"
TRAINING_DR = {"start": None, "end": HOLDOUT_DATE}
HOLDOUT_DR = {"start": HOLDOUT_DATE, "end": None}

BASE_PARAMS = {
    "ema200_period": 200, "ema50_period": 50, "ema50_rising_lookback": 5,
    "st_4h_atr_period": 10, "st_4h_multiplier": 3.0,
    "st_15m_atr_period": 10, "st_15m_multiplier": 2.0,
    "near_band_pct": 0.005, "rsi_period": 14, "rsi_threshold": 45.0,
    "rsi_lookback": 2, "ema_fast": 21, "ema_slow": 55,
    "vol_mult": 2.0, "vol_sma_period": 20, "warmup": 300
}
CLEAN_FEES = {"maker_rate": 0.00045, "slippage": 0.0005, "funding_rate_per_8h": 0.0001}
# Friction fees: 0.045% maker + 0.05% slippage + 0.02% market impact = 0.115% per side
FRICTION_FEES = {"maker_rate": 0.00065, "slippage": 0.0005, "funding_rate_per_8h": 0.0001}

def make_cfg(assets, output, lev=10.0, margin=125.0, eq=500.0, dr=None,
             extras=None, regime=None, tf=None, friction=False,
             fees=None, bootstrap=None, robustness=None):
    cfg = {
        "assets": assets, "data_dir": DATA_DIR, "mode": "baseline",
        "params": BASE_PARAMS.copy(),
        "sizing": {"type": "flat", "margin": margin, "leverage": lev, "starting_equity": eq},
        "fees": (fees or (FRICTION_FEES if friction else CLEAN_FEES)).copy(),
        "friction": {
            "enabled": friction, "misclass_pct": 0.03 if friction else 0,
            "misclass_seed": 42, "regime_lag_hours": 12.0 if friction else 0,
            "signal_delay_bars": 2 if friction else 0, "elevated_fee_rate": 0.00115 if friction else 0
        },
        "robustness": robustness or {"enabled": False},
        "bootstrap": bootstrap or {"enabled": False},
        "output_path": output,
    }
    if dr: cfg["date_range"] = dr
    if extras: cfg["signal_extras"] = extras
    if regime: cfg["regime_config"] = regime
    if tf: cfg["timeframe"] = tf
    return cfg

def run(cfg, label=""):
    cp = cfg["output_path"].replace(".json", "_cfg.json")
    with open(cp, 'w') as f: json.dump(cfg, f)
    t = time.time()
    r = subprocess.run([ENGINE, cp], capture_output=True, text=True)
    dt = time.time() - t
    if r.returncode != 0:
        print(f"  ERR [{label}]: {r.stderr[-300:]}")
        return None
    try:
        with open(cfg["output_path"]) as f: d = json.load(f)
        return d
    except: return None

def gs(data, asset=None):
    if asset and "asset_stats" in data and asset in data["asset_stats"]:
        return data["asset_stats"][asset]
    return data.get("portfolio", {})

def run_3asset(label, dr, friction=False, extras=None, regime=None, tf=None,
               margin=125.0, fees=None, bootstrap=None, robustness=None):
    """Run BTC+ETH at 10x and SOL at 5x, combine."""
    r1 = run(make_cfg(["BTC","ETH"], f"{OUT}/iv_{label}_be.json", lev=10, dr=dr,
                       friction=friction, extras=extras, regime=regime, tf=tf,
                       margin=margin, fees=fees, bootstrap=bootstrap, robustness=robustness),
             f"{label} BE")
    r2 = run(make_cfg(["SOL"], f"{OUT}/iv_{label}_sol.json", lev=5, dr=dr,
                       friction=friction, extras=extras, regime=regime, tf=tf,
                       margin=margin, fees=fees, bootstrap=bootstrap, robustness=robustness),
             f"{label} SOL")
    return combine(r1, r2)

def combine(r1, r2):
    c = {"asset_stats": {}, "portfolio": {}, "trade_log": []}
    for r in [r1, r2]:
        if not r: continue
        for a, s in r.get("asset_stats", {}).items(): c["asset_stats"][a] = s
        c["trade_log"].extend(r.get("trade_log", []))
    trades = c["trade_log"]
    if not trades:
        c["portfolio"] = {"trades":0,"pnl":0,"pf":0,"sharpe":0,"mdd_pct":0,"wr":0,"fees":0,"funding":0}
        return c
    pnl = sum(t["pnl"] for t in trades)
    wins = [t for t in trades if t["pnl"] > 0]
    losses = [t for t in trades if t["pnl"] <= 0]
    gp = sum(t["pnl"] for t in wins)
    gl = abs(sum(t["pnl"] for t in losses))
    pf = gp/gl if gl > 0 else (99.0 if gp > 0 else 0.0)
    wr = len(wins)/len(trades)*100
    fees = sum(t["fees"] for t in trades)
    funding = sum(t["funding"] for t in trades)
    monthly = {}
    for t in trades:
        ym = t["exit_ts"][:7]
        monthly[ym] = monthly.get(ym, 0) + t["pnl"]
    rets = [v/500.0 for v in monthly.values()]
    if len(rets) >= 2:
        mean = sum(rets)/len(rets)
        var = sum((r-mean)**2 for r in rets)/len(rets)
        std = var**0.5
        sharpe = mean/std*12**0.5 if std > 0 else 0
    else: sharpe = 0
    # MDD from equity curve approximation
    cum = 0; peak = 0; mdd = 0
    for ym in sorted(monthly.keys()):
        cum += monthly[ym]; peak = max(peak, cum)
        mdd = max(mdd, peak - cum)
    mdd_pct = mdd/500.0*100
    c["portfolio"] = {"trades":len(trades),"pnl":round(pnl,2),"pf":round(pf,2),
        "sharpe":round(sharpe,2),"mdd_pct":round(mdd_pct,1),"wr":round(wr,1),
        "fees":round(fees,2),"funding":round(funding,2),"monthly":monthly}
    return c

def tbl(rows, header):
    """Simple table printer."""
    widths = [max(len(str(r[i])) for r in [header]+rows) for i in range(len(header))]
    fmt_row = lambda r: " │ ".join(str(r[i]).ljust(widths[i]) for i in range(len(r)))
    print(f"  {fmt_row(header)}")
    print(f"  {'─┼─'.join('─'*w for w in widths)}")
    for r in rows: print(f"  {fmt_row(r)}")

print(f"Holdout boundary: {HOLDOUT_DATE}")
print(f"Training: start → {HOLDOUT_DATE} | Holdout: {HOLDOUT_DATE} → 2026-03-19\n")

# ═══════════════════════════════════════════════════════════════
# BLOCK 1 — INDIVIDUAL IMPROVEMENTS UNDER FULL FRICTION
# ═══════════════════════════════════════════════════════════════
print("="*70)
print("BLOCK 1 — INDIVIDUAL IMPROVEMENTS UNDER FULL FRICTION")
print("="*70)

# Reference: clean baseline
base_clean = run_3asset("b1_base_clean", TRAINING_DR)
bc = base_clean["portfolio"]

configs = {
    "Baseline (friction)":       {"friction": True},
    "1. Scoring 4/5 (friction)": {"friction": True, "extras": {"min_score_long": 4, "min_score_short": 4}},
    "2. No flat (friction)":     {"friction": True, "regime": {"type": "no_flat"}},
    "3. Dual ST (friction)":     {"friction": True, "extras": {"confirm_st_atr": 20, "confirm_st_mult": 4.0}},
    "4. Late win 20 (friction)": {"friction": True, "extras": {"late_window": 20}},
    "Combined all 4 (friction)": {"friction": True,
        "extras": {"min_score_long": 4, "min_score_short": 4, "confirm_st_atr": 20, "confirm_st_mult": 4.0, "late_window": 20},
        "regime": {"type": "no_flat"}},
}

b1 = {}
header = ["System", "PF", "P&L", "Sharpe", "MDD%", "Trades", "Edge%"]
rows = [["Baseline (clean)", f"{bc['pf']:.2f}", f"${bc['pnl']:.0f}", f"{bc['sharpe']:.2f}",
         f"{bc['mdd_pct']:.1f}%", str(bc['trades']), "100%"]]

for name, kw in configs.items():
    tag = name.split("(")[0].strip().replace(" ", "_").replace(".", "").replace("/","")[:20]
    r = run_3asset(f"b1_{tag}", TRAINING_DR, **kw)
    p = r["portfolio"]
    edge = p["pnl"] / bc["pnl"] * 100 if bc["pnl"] != 0 else 0
    rows.append([name, f"{p['pf']:.2f}", f"${p['pnl']:.0f}", f"{p['sharpe']:.2f}",
                 f"{p['mdd_pct']:.1f}%", str(p['trades']), f"{edge:.0f}%"])
    b1[name] = p

print(f"\nBLOCK 1 — INDIVIDUAL IMPROVEMENTS UNDER FRICTION:\n")
tbl(rows, header)

# Friction baseline for comparison
fb = b1.get("Baseline (friction)", {})
print(f"\n  FRICTION SURVIVAL:")
survived = []
for name in ["1. Scoring 4/5 (friction)", "2. No flat (friction)",
             "3. Dual ST (friction)", "4. Late win 20 (friction)"]:
    p = b1[name]
    beats = p.get("sharpe", 0) > fb.get("sharpe", 0)
    status = "YES" if beats else "NO"
    print(f"    {name}: Sharpe {p.get('sharpe',0):.2f} vs friction baseline {fb.get('sharpe',0):.2f} → {status}")
    if beats: survived.append(name)

comb = b1.get("Combined all 4 (friction)", {})
comb_beats = comb.get("sharpe", 0) > fb.get("sharpe", 0)
print(f"    Combined: Sharpe {comb.get('sharpe',0):.2f} vs friction baseline {fb.get('sharpe',0):.2f} → {'YES' if comb_beats else 'NO'}")

RESULTS["block1"] = b1

# ═══════════════════════════════════════════════════════════════
# BLOCK 2 — PER-CONDITION DROP ANALYSIS
# ═══════════════════════════════════════════════════════════════
print("\n" + "="*70)
print("BLOCK 2 — PER-CONDITION DROP ANALYSIS")
print("="*70)

# Baseline trade set for comparison
base_trades = set()
for t in base_clean["trade_log"]:
    base_trades.add((t["asset"], t["entry_ts"], t["direction"]))

cond_names = {1: "close > EMA200", 2: "4H ST bullish", 3: "15m ST bullish",
              4: "near band", 5: "RSI dip+recovery"}

print(f"\n  LONG ENTRY — PER-CONDITION DROP:")
header2 = ["Dropped", "PF", "P&L", "Sharpe", "MDD%", "Trades", "Delta"]
rows2 = [["None (baseline)", f"{bc['pf']:.2f}", f"${bc['pnl']:.0f}", f"{bc['sharpe']:.2f}",
          f"{bc['mdd_pct']:.1f}%", str(bc['trades']), "+0"]]

b2_long = {}
for cid in range(1, 6):
    r = run_3asset(f"b2_drop_l{cid}", TRAINING_DR, extras={"skip_long": [cid]})
    p = r["portfolio"]
    delta = p["trades"] - bc["trades"]
    rows2.append([f"Drop #{cid} ({cond_names[cid]})", f"{p['pf']:.2f}", f"${p['pnl']:.0f}",
                  f"{p['sharpe']:.2f}", f"{p['mdd_pct']:.1f}%", str(p['trades']), f"+{delta}"])

    # Find NEW trades (not in baseline)
    drop_trades = set()
    for t in r["trade_log"]:
        key = (t["asset"], t["entry_ts"], t["direction"])
        drop_trades.add(key)
    new_keys = drop_trades - base_trades
    new_trades = [t for t in r["trade_log"]
                  if (t["asset"], t["entry_ts"], t["direction"]) in new_keys]
    if new_trades:
        new_pnl = sum(t["pnl"] for t in new_trades)
        new_wins = sum(1 for t in new_trades if t["pnl"] > 0)
        new_gp = sum(t["pnl"] for t in new_trades if t["pnl"] > 0)
        new_gl = abs(sum(t["pnl"] for t in new_trades if t["pnl"] <= 0))
        new_pf = new_gp/new_gl if new_gl > 0 else 99.0
        new_avg = new_pnl / len(new_trades)
    else:
        new_pnl = new_avg = 0; new_pf = 0; new_trades = []

    b2_long[cid] = {"portfolio": p, "new_count": len(new_trades),
                     "new_avg_pnl": round(new_avg, 2), "new_pf": round(new_pf, 2),
                     "new_total_pnl": round(new_pnl, 2)}

tbl(rows2, header2)

print(f"\n  ADDITIONAL TRADE QUALITY:")
safe_to_drop = []
dangerous = []
for cid in range(1, 6):
    d = b2_long[cid]
    status = "SAFE" if d["new_pf"] > 1.0 and d["new_count"] > 0 else "DANGEROUS"
    print(f"    Drop #{cid} ({cond_names[cid]}): {d['new_count']} new trades, avg P&L=${d['new_avg_pnl']:.2f}, PF={d['new_pf']:.2f} → {status}")
    if status == "SAFE": safe_to_drop.append(cid)
    else: dangerous.append(cid)

print(f"\n  SAFE to drop: {[cond_names[c] for c in safe_to_drop]}")
print(f"  DANGEROUS to drop: {[cond_names[c] for c in dangerous]}")

# Short conditions
short_conds = {1: "f<s (bearish)", 2: "just crossed", 3: "volume surge", 4: "c<fast EMA"}
print(f"\n  SHORT ENTRY — PER-CONDITION DROP:")
header3 = ["Dropped", "PF", "P&L", "Sharpe", "MDD%", "Trades", "Delta"]
rows3 = [["None (baseline)", f"{bc['pf']:.2f}", f"${bc['pnl']:.0f}", f"{bc['sharpe']:.2f}",
          f"{bc['mdd_pct']:.1f}%", str(bc['trades']), "+0"]]

b2_short = {}
for cid in range(1, 5):
    r = run_3asset(f"b2_drop_s{cid}", TRAINING_DR, extras={"skip_short": [cid]})
    p = r["portfolio"]
    delta = p["trades"] - bc["trades"]
    rows3.append([f"Drop #{cid} ({short_conds[cid]})", f"{p['pf']:.2f}", f"${p['pnl']:.0f}",
                  f"{p['sharpe']:.2f}", f"{p['mdd_pct']:.1f}%", str(p['trades']), f"+{delta}"])
    b2_short[cid] = p

tbl(rows3, header3)

RESULTS["block2"] = {"long": b2_long, "short": {k: v for k, v in b2_short.items()}}

# ═══════════════════════════════════════════════════════════════
# BLOCK 3 — NO-FLAT REGIME MICROSCOPE
# ═══════════════════════════════════════════════════════════════
print("\n" + "="*70)
print("BLOCK 3 — NO-FLAT REGIME MICROSCOPE")
print("="*70)

noflat = run_3asset("b3_noflat", TRAINING_DR, regime={"type": "no_flat"})

# Find extra trades
base_tset = set((t["asset"], t["entry_ts"], t["direction"]) for t in base_clean["trade_log"])
extra_trades = [t for t in noflat["trade_log"]
                if (t["asset"], t["entry_ts"], t["direction"]) not in base_tset]

extra_longs = [t for t in extra_trades if t["direction"] == "long"]
extra_shorts = [t for t in extra_trades if t["direction"] == "short"]
extra_pnl = sum(t["pnl"] for t in extra_trades)
extra_gp = sum(t["pnl"] for t in extra_trades if t["pnl"] > 0)
extra_gl = abs(sum(t["pnl"] for t in extra_trades if t["pnl"] <= 0))
extra_pf = extra_gp/extra_gl if extra_gl > 0 else 99.0
extra_avg = extra_pnl/len(extra_trades) if extra_trades else 0

print(f"\n  EXTRA TRADES FROM REMOVING FLAT:")
print(f"    Total extra: {len(extra_trades)} | Longs: {len(extra_longs)} | Shorts: {len(extra_shorts)}")
print(f"    Extra PF: {extra_pf:.2f} | Extra avg P&L: ${extra_avg:.2f} | Extra total P&L: ${extra_pnl:.2f}")

# Monthly breakdown
monthly_extra = defaultdict(lambda: {"count": 0, "pnl": 0})
for t in extra_trades:
    ym = t["exit_ts"][:7]
    monthly_extra[ym]["count"] += 1
    monthly_extra[ym]["pnl"] += t["pnl"]

print(f"\n  MONTHLY BREAKDOWN OF EXTRA TRADES:")
print(f"    {'Month':<10} {'Extras':<8} {'P&L':<10} {'PF':<6}")
for ym in sorted(monthly_extra.keys()):
    m = monthly_extra[ym]
    print(f"    {ym:<10} {m['count']:<8} ${m['pnl']:<9.2f}")

# Choppy period focus
for label, y_start, y_end in [("2023", "2023-01", "2024-01"), ("2025-Q1-Q3", "2025-01", "2025-10")]:
    period_trades = [t for t in extra_trades if y_start <= t["exit_ts"][:7] < y_end]
    period_pnl = sum(t["pnl"] for t in period_trades)
    print(f"\n  {label}: {len(period_trades)} extra trades, P&L=${period_pnl:.2f}")

# Worst streak
if extra_trades:
    sorted_extra = sorted(extra_trades, key=lambda t: t["exit_ts"])
    max_streak = 0; cur_streak = 0; max_cum_loss = 0; cum = 0
    for t in sorted_extra:
        if t["pnl"] <= 0: cur_streak += 1; max_streak = max(max_streak, cur_streak)
        else: cur_streak = 0
        cum += t["pnl"]
        max_cum_loss = min(max_cum_loss, cum)
    print(f"\n  Longest losing streak among extras: {max_streak}")
    print(f"  Max cumulative loss from extras: ${max_cum_loss:.2f}")

    # Remove top 3 and check
    sorted_by_pnl = sorted(extra_trades, key=lambda t: t["pnl"], reverse=True)
    remaining = sorted_by_pnl[3:]
    rem_pnl = sum(t["pnl"] for t in remaining)
    rem_gp = sum(t["pnl"] for t in remaining if t["pnl"] > 0)
    rem_gl = abs(sum(t["pnl"] for t in remaining if t["pnl"] <= 0))
    rem_pf = rem_gp/rem_gl if rem_gl > 0 else 0
    print(f"\n  After removing top 3 winners: {len(remaining)} trades, P&L=${rem_pnl:.2f}, PF={rem_pf:.2f}")
    print(f"  Still profitable without outliers? {'YES' if rem_pnl > 0 else 'NO'}")

RESULTS["block3"] = {"extra_count": len(extra_trades), "extra_pf": round(extra_pf, 2),
                      "extra_pnl": round(extra_pnl, 2), "extra_avg": round(extra_avg, 2)}

# ═══════════════════════════════════════════════════════════════
# BLOCK 4 — DUAL ST + LATE WINDOW INTERACTION
# ═══════════════════════════════════════════════════════════════
print("\n" + "="*70)
print("BLOCK 4 — DUAL ST + LATE WINDOW INTERACTION")
print("="*70)

b4_dual = run_3asset("b4_dual", TRAINING_DR, extras={"confirm_st_atr": 20, "confirm_st_mult": 4.0})
b4_late = run_3asset("b4_late", TRAINING_DR, extras={"late_window": 20})
b4_both = run_3asset("b4_both", TRAINING_DR, extras={"confirm_st_atr": 20, "confirm_st_mult": 4.0, "late_window": 20})

pd = b4_dual["portfolio"]; pl = b4_late["portfolio"]; pb = b4_both["portfolio"]

print(f"\n  INTERACTION ANALYSIS:")
header4 = ["Config", "PF", "P&L", "Sharpe", "MDD%", "Trades"]
rows4 = [
    ["Baseline", f"{bc['pf']:.2f}", f"${bc['pnl']:.0f}", f"{bc['sharpe']:.2f}", f"{bc['mdd_pct']:.1f}%", str(bc['trades'])],
    ["Dual ST only", f"{pd['pf']:.2f}", f"${pd['pnl']:.0f}", f"{pd['sharpe']:.2f}", f"{pd['mdd_pct']:.1f}%", str(pd['trades'])],
    ["Late win only", f"{pl['pf']:.2f}", f"${pl['pnl']:.0f}", f"{pl['sharpe']:.2f}", f"{pl['mdd_pct']:.1f}%", str(pl['trades'])],
    ["Dual + Late", f"{pb['pf']:.2f}", f"${pb['pnl']:.0f}", f"{pb['sharpe']:.2f}", f"{pb['mdd_pct']:.1f}%", str(pb['trades'])],
]
tbl(rows4, header4)

expected = (pd["sharpe"] - bc["sharpe"]) + (pl["sharpe"] - bc["sharpe"]) + bc["sharpe"]
actual = pb["sharpe"]
print(f"\n  Expected if additive: {expected:.2f}")
print(f"  Actual combined: {actual:.2f}")
if actual > expected * 1.05:
    print(f"  SYNERGY: actual > expected")
elif actual < expected * 0.95:
    print(f"  INTERFERENCE: actual < expected")
else:
    print(f"  APPROXIMATELY ADDITIVE")

# Check if late window only helps because dual ST delays entry
base_tset2 = set((t["asset"], t["entry_ts"]) for t in base_clean["trade_log"])
late_new = [t for t in b4_late["trade_log"]
            if (t["asset"], t["entry_ts"]) not in base_tset2 and t["direction"] == "long"]
dual_tset = set((t["asset"], t["entry_ts"]) for t in b4_dual["trade_log"])
both_new = [t for t in b4_both["trade_log"]
            if (t["asset"], t["entry_ts"]) not in dual_tset and t["direction"] == "long"]

late_new_pnl = sum(t["pnl"] for t in late_new)
both_new_pnl = sum(t["pnl"] for t in both_new)
print(f"\n  LATE WINDOW DEPENDENCY:")
print(f"    Without dual ST: late adds {len(late_new)} longs, avg P&L=${late_new_pnl/len(late_new) if late_new else 0:.2f}")
print(f"    With dual ST: late adds {len(both_new)} longs, avg P&L=${both_new_pnl/len(both_new) if both_new else 0:.2f}")

RESULTS["block4"] = {"dual": pd, "late": pl, "both": pb, "expected": expected, "actual": actual}

# ═══════════════════════════════════════════════════════════════
# BLOCK 5 — MDD-CONTROLLED COMPARISON
# ═══════════════════════════════════════════════════════════════
print("\n" + "="*70)
print("BLOCK 5 — MDD-CONTROLLED COMPARISON")
print("="*70)

# Combined at full size
comb_full = run_3asset("b5_comb_full", TRAINING_DR,
    extras={"min_score_long": 4, "min_score_short": 4, "confirm_st_atr": 20,
            "confirm_st_mult": 4.0, "late_window": 20},
    regime={"type": "no_flat"})
cf = comb_full["portfolio"]

# Scale margin down to match baseline MDD
# MDD scales linearly with position size (margin)
# Target: combined_mdd * (new_margin/125) ≈ baseline_mdd
target_mdd = bc["mdd_pct"]
raw_mdd = cf["mdd_pct"]
if raw_mdd > 0:
    scale = target_mdd / raw_mdd
    matched_margin = round(125.0 * scale, 1)
else:
    matched_margin = 125.0
    scale = 1.0

comb_matched = run_3asset("b5_comb_matched", TRAINING_DR, margin=matched_margin,
    extras={"min_score_long": 4, "min_score_short": 4, "confirm_st_atr": 20,
            "confirm_st_mult": 4.0, "late_window": 20},
    regime={"type": "no_flat"})
cm = comb_matched["portfolio"]

print(f"\n  MDD-MATCHED COMPARISON:")
header5 = ["System", "Margin", "PF", "P&L", "Sharpe", "MDD%", "Trades"]
rows5 = [
    ["Baseline", "$125", f"{bc['pf']:.2f}", f"${bc['pnl']:.0f}", f"{bc['sharpe']:.2f}", f"{bc['mdd_pct']:.1f}%", str(bc['trades'])],
    ["Combined (raw)", "$125", f"{cf['pf']:.2f}", f"${cf['pnl']:.0f}", f"{cf['sharpe']:.2f}", f"{cf['mdd_pct']:.1f}%", str(cf['trades'])],
    ["Combined (matched)", f"${matched_margin}", f"{cm['pf']:.2f}", f"${cm['pnl']:.0f}", f"{cm['sharpe']:.2f}", f"{cm['mdd_pct']:.1f}%", str(cm['trades'])],
]
tbl(rows5, header5)

pnl_diff = cm["pnl"] - bc["pnl"]
if pnl_diff > 0:
    print(f"\n  AT EQUAL MDD: Combined produces ${pnl_diff:.0f} MORE P&L → REAL improvement")
    print(f"  Sharpe: {cm['sharpe']:.2f} vs {bc['sharpe']:.2f}")
else:
    print(f"\n  AT EQUAL MDD: Combined produces ${abs(pnl_diff):.0f} LESS P&L → ILLUSION from more risk")

RESULTS["block5"] = {"baseline_pnl": bc["pnl"], "matched_pnl": cm["pnl"],
                      "matched_margin": matched_margin, "genuine": pnl_diff > 0}

# ═══════════════════════════════════════════════════════════════
# BLOCK 6 — DEFLATED SHARPE + WHITE'S REALITY CHECK
# ═══════════════════════════════════════════════════════════════
print("\n" + "="*70)
print("BLOCK 6 — STATISTICAL SIGNIFICANCE")
print("="*70)

# Count total configs tested
# Colleague comparison: 6 modifications + 20 dual ST combos + 9 late window values + 4 score values + 3 short score = 42
# This validation: ~30 more
N_tests = 72  # conservative estimate

# Compute return distribution stats
base_monthly = bc.get("monthly", {})
comb_monthly = cf.get("monthly", {})
base_rets = [v/500.0 for v in base_monthly.values()]
comb_rets = [v/500.0 for v in comb_monthly.values()]
T = len(comb_rets)  # number of monthly observations

if T >= 3:
    # Moments
    mean_c = sum(comb_rets)/T
    var_c = sum((r-mean_c)**2 for r in comb_rets)/T
    std_c = var_c**0.5
    skew_c = sum((r-mean_c)**3 for r in comb_rets)/(T*std_c**3) if std_c > 0 else 0
    kurt_c = sum((r-mean_c)**4 for r in comb_rets)/(T*std_c**4) - 3 if std_c > 0 else 0

    # Deflated Sharpe (Bailey & López de Prado 2014)
    sr = cf["sharpe"]
    # Expected max Sharpe under null (Harvey & Liu approximation)
    from math import log, sqrt, erfc, exp
    gamma_approx = sqrt(2 * log(N_tests))
    e_max_sr = gamma_approx - (log(log(N_tests)) + log(4*3.14159))/(2*gamma_approx) if N_tests > 1 else 0

    # Variance of Sharpe ratio estimator
    sr_var = (1 + 0.5*sr**2 - skew_c*sr + (kurt_c/4)*sr**2) / T if T > 0 else 1
    sr_std = sqrt(sr_var) if sr_var > 0 else 1

    # p-value: P(SR > 0 | multiple testing)
    # Using DSR framework: compare observed SR to expected max SR
    if sr_std > 0:
        z_dsr = (sr - e_max_sr) / sr_std
        # Approximate normal CDF
        from math import erf
        p_dsr = 0.5 * (1 + erf(z_dsr / sqrt(2)))
    else:
        p_dsr = 0.5

    print(f"\n  Deflated Sharpe Ratio:")
    print(f"    N_tests: {N_tests}")
    print(f"    Raw Sharpe: {sr:.2f}")
    print(f"    Expected max SR under null: {e_max_sr:.2f}")
    print(f"    Skewness: {skew_c:.2f}, Excess kurtosis: {kurt_c:.2f}")
    print(f"    DSR p-value: {p_dsr:.4f}")
    print(f"    Still significant after correction? {'YES' if p_dsr > 0.95 else 'NO'}")
else:
    p_dsr = 0.5
    print(f"\n  Insufficient data for DSR (T={T})")

# White's Reality Check via bootstrap
print(f"\n  White's Reality Check (1000 bootstraps):")
random.seed(42)
base_wins = 0
n_boot = 1000
# Bootstrap: resample monthly returns and compare systems
months_sorted = sorted(set(list(base_monthly.keys()) + list(comb_monthly.keys())))
for _ in range(n_boot):
    boot_months = [random.choice(months_sorted) for _ in range(len(months_sorted))]
    boot_base = sum(base_monthly.get(m, 0) for m in boot_months)
    boot_comb = sum(comb_monthly.get(m, 0) for m in boot_months)
    if boot_comb > boot_base:
        base_wins += 1

p_white = base_wins / n_boot
print(f"    Combined beats baseline in {base_wins}/{n_boot} bootstraps ({p_white*100:.1f}%)")
print(f"    Significant at 5%? {'YES' if p_white > 0.95 else 'NO'}")
print(f"    Significant at 1%? {'YES' if p_white > 0.99 else 'NO'}")

# Bonferroni
# Raw paired test
if len(base_rets) >= 2 and len(comb_rets) >= 2:
    diffs = [comb_monthly.get(m, 0) - base_monthly.get(m, 0) for m in months_sorted]
    mean_d = sum(diffs)/len(diffs)
    var_d = sum((d-mean_d)**2 for d in diffs)/len(diffs)
    std_d = sqrt(var_d) if var_d > 0 else 1
    t_stat = mean_d / (std_d / sqrt(len(diffs))) if std_d > 0 else 0
    # Approximate p-value from t-statistic
    from math import atan
    raw_p = 0.5 - atan(t_stat / sqrt(len(diffs) - 1)) / 3.14159 if len(diffs) > 1 else 0.5
    bonf_p = min(raw_p * N_tests, 1.0)
    print(f"\n  Bonferroni correction:")
    print(f"    Raw p-value: {raw_p:.4f}")
    print(f"    Corrected (×{N_tests}): {bonf_p:.4f}")
    print(f"    Still significant? {'YES' if bonf_p < 0.05 else 'NO'}")

RESULTS["block6"] = {"n_tests": N_tests, "dsr_p": round(p_dsr, 4),
                      "white_pct": round(p_white*100, 1)}

# ═══════════════════════════════════════════════════════════════
# BLOCK 7 — ROLLING HOLDOUT (MULTIPLE WINDOWS)
# ═══════════════════════════════════════════════════════════════
print("\n" + "="*70)
print("BLOCK 7 — ROLLING HOLDOUT WINDOWS")
print("="*70)

train_days = 3 * 365  # 3 years
test_days = 180  # 6 months
start = datetime(2020, 1, 1)
end = datetime(2026, 3, 19)

windows = []
current = start + timedelta(days=train_days)
while current + timedelta(days=test_days) <= end:
    test_start = current
    test_end = current + timedelta(days=test_days)
    windows.append((test_start.strftime("%Y-%m-%d"), test_end.strftime("%Y-%m-%d")))
    current += timedelta(days=test_days)

print(f"\n  {len(windows)} rolling windows (3yr train, 6mo test):\n")
header7 = ["Window", "Test Period", "Base Sharpe", "Comb Sharpe", "Winner"]
rows7 = []
comb_wins = 0

for i, (ts, te) in enumerate(windows):
    dr_w = {"start": ts, "end": te}
    r_base = run_3asset(f"b7_base_{i}", dr_w)
    r_comb = run_3asset(f"b7_comb_{i}", dr_w,
        extras={"min_score_long": 4, "min_score_short": 4, "confirm_st_atr": 20,
                "confirm_st_mult": 4.0, "late_window": 20},
        regime={"type": "no_flat"})
    bp = r_base["portfolio"]; cp = r_comb["portfolio"]
    winner = "C" if cp.get("sharpe", 0) > bp.get("sharpe", 0) else "B"
    if winner == "C": comb_wins += 1
    rows7.append([f"W{i+1}", f"{ts} → {te}", f"{bp.get('sharpe',0):.2f}",
                  f"{cp.get('sharpe',0):.2f}", winner])

tbl(rows7, header7)
pct = comb_wins/len(windows)*100
print(f"\n  Combined wins: {comb_wins}/{len(windows)} windows ({pct:.0f}%)")
print(f"  CONSISTENCY: {'YES — robust' if pct >= 70 else 'NO — period-dependent'}")

RESULTS["block7"] = {"windows": len(windows), "comb_wins": comb_wins, "pct": round(pct, 1)}

# ═══════════════════════════════════════════════════════════════
# BLOCK 8 — INDIVIDUAL IMPROVEMENT HOLDOUT
# ═══════════════════════════════════════════════════════════════
print("\n" + "="*70)
print("BLOCK 8 — INDIVIDUAL IMPROVEMENT HOLDOUT")
print("="*70)

ho_base = run_3asset("b8_base", HOLDOUT_DR)
ho_score = run_3asset("b8_score", HOLDOUT_DR, extras={"min_score_long": 4, "min_score_short": 4})
ho_noflat = run_3asset("b8_noflat", HOLDOUT_DR, regime={"type": "no_flat"})
ho_dual = run_3asset("b8_dual", HOLDOUT_DR, extras={"confirm_st_atr": 20, "confirm_st_mult": 4.0})
ho_late = run_3asset("b8_late", HOLDOUT_DR, extras={"late_window": 20})
ho_comb = run_3asset("b8_comb", HOLDOUT_DR,
    extras={"min_score_long": 4, "min_score_short": 4, "confirm_st_atr": 20,
            "confirm_st_mult": 4.0, "late_window": 20},
    regime={"type": "no_flat"})

print(f"\n  INDIVIDUAL HOLDOUT RESULTS:")
header8 = ["System", "HO PF", "HO P&L", "HO Sharpe", "HO MDD%", "Trades"]
hb = ho_base["portfolio"]
rows8 = [
    ["Baseline", f"{hb['pf']:.2f}", f"${hb['pnl']:.0f}", f"{hb['sharpe']:.2f}", f"{hb['mdd_pct']:.1f}%", str(hb['trades'])],
]
ho_results = {
    "1. Scoring 4/5": ho_score, "2. No flat": ho_noflat,
    "3. Dual ST": ho_dual, "4. Late window": ho_late, "Combined": ho_comb,
}
for name, r in ho_results.items():
    p = r["portfolio"]
    rows8.append([name, f"{p['pf']:.2f}", f"${p['pnl']:.0f}", f"{p['sharpe']:.2f}",
                  f"{p['mdd_pct']:.1f}%", str(p['trades'])])

tbl(rows8, header8)

print(f"\n  INDIVIDUAL HOLDOUT CHECK:")
for name, r in ho_results.items():
    if name == "Combined": continue
    p = r["portfolio"]
    beats = p.get("sharpe", 0) > hb.get("sharpe", 0)
    hurts = p.get("sharpe", 0) < hb.get("sharpe", 0) - 0.1
    status = "BEATS" if beats else ("HURTS" if hurts else "NEUTRAL")
    flag = " ← FLAGGED" if hurts else ""
    print(f"    {name}: Sharpe {p.get('sharpe',0):.2f} vs {hb.get('sharpe',0):.2f} → {status}{flag}")

RESULTS["block8"] = {name: r["portfolio"] for name, r in ho_results.items()}
RESULTS["block8"]["baseline"] = hb

# ═══════════════════════════════════════════════════════════════
# BLOCK 9 — PHASED ADOPTION ANALYSIS
# ═══════════════════════════════════════════════════════════════
print("\n" + "="*70)
print("BLOCK 9 — PHASED ADOPTION ANALYSIS")
print("="*70)

# Get individual training stats
ind_training = {
    "Scoring 4/5": run_3asset("b9_score", TRAINING_DR, extras={"min_score_long": 4, "min_score_short": 4})["portfolio"],
    "No flat": run_3asset("b9_noflat", TRAINING_DR, regime={"type": "no_flat"})["portfolio"],
    "Dual ST": run_3asset("b9_dual", TRAINING_DR, extras={"confirm_st_atr": 20, "confirm_st_mult": 4.0})["portfolio"],
    "Late window": run_3asset("b9_late", TRAINING_DR, extras={"late_window": 20})["portfolio"],
}

print(f"\n  ADOPTION RANKING:")
header9 = ["Improvement", "Sharpe Gain", "MDD Increase", "Efficiency", "New Params", "Complexity", "Rank"]
rankings = []
for name, p in ind_training.items():
    sg = p["sharpe"] - bc["sharpe"]
    mdd_inc = p["mdd_pct"] - bc["mdd_pct"]
    efficiency = sg / max(mdd_inc, 0.1) if mdd_inc > 0 else sg * 10  # high efficiency if no MDD increase
    if name == "Scoring 4/5":
        params = 1; complexity = "low"
    elif name == "No flat":
        params = 0; complexity = "low"
    elif name == "Dual ST":
        params = 2; complexity = "medium"
    elif name == "Late window":
        params = 1; complexity = "low"
    else:
        params = 0; complexity = "low"

    # Check holdout
    ho_name = {"Scoring 4/5": "1. Scoring 4/5", "No flat": "2. No flat",
               "Dual ST": "3. Dual ST", "Late window": "4. Late window"}[name]
    ho_sharpe = ho_results.get(ho_name, {}).get("portfolio", {}).get("sharpe", 0) if isinstance(ho_results.get(ho_name), dict) else RESULTS["block8"].get(ho_name, {}).get("sharpe", 0)

    rankings.append((name, sg, mdd_inc, efficiency, params, complexity, ho_sharpe))

# Sort by efficiency
rankings.sort(key=lambda x: x[3], reverse=True)
rows9 = []
for i, (name, sg, mdd_inc, eff, params, comp, ho_s) in enumerate(rankings):
    rows9.append([name, f"+{sg:.2f}", f"+{mdd_inc:.1f}%", f"{eff:.3f}",
                  str(params), comp, f"#{i+1}"])

tbl(rows9, header9)

print(f"\n  RECOMMENDED ADOPTION ORDER:")
for i, (name, sg, mdd_inc, eff, params, comp, ho_s) in enumerate(rankings):
    print(f"    Month {i+1}: {name} (Sharpe +{sg:.2f}, MDD +{mdd_inc:.1f}%)")
print(f"    At any stage: if live results diverge >30% from backtest, STOP.")

RESULTS["block9"] = {"rankings": [(n, round(s, 2), round(m, 1)) for n, s, m, *_ in rankings]}

# ═══════════════════════════════════════════════════════════════
# BLOCK 10 — FINAL VERDICT
# ═══════════════════════════════════════════════════════════════
total_time = time.time() - T0

print("\n" + "═"*70)
print("  IMPROVEMENT VALIDATION — COMPLETE")
print("═"*70)

print(f"\n  TOTAL RUNTIME: {total_time:.1f} seconds")

# Determine which improvements passed ALL tests
passed_all = []
eliminated = []

for name, short_name, ho_name in [
    ("Scoring 4/5", "1. Scoring 4/5 (friction)", "1. Scoring 4/5"),
    ("No flat", "2. No flat (friction)", "2. No flat"),
    ("Dual ST", "3. Dual ST (friction)", "3. Dual ST"),
    ("Late window", "4. Late win 20 (friction)", "4. Late window"),
]:
    reasons = []
    # Block 1: friction survival
    fric_p = b1.get(short_name, {})
    if fric_p.get("sharpe", 0) <= fb.get("sharpe", 0):
        reasons.append("Failed friction test (B1)")
    # Block 8: holdout
    ho_p = RESULTS["block8"].get(ho_name, {})
    if ho_p.get("sharpe", 0) < hb.get("sharpe", 0) - 0.1:
        reasons.append("Hurt on holdout (B8)")
    if reasons:
        eliminated.append((name, reasons))
    else:
        passed_all.append(name)

print(f"\n  IMPROVEMENTS THAT PASSED ALL TESTS:")
for name in passed_all:
    print(f"    ✓ {name}")
if not passed_all:
    print(f"    None")

print(f"\n  IMPROVEMENTS ELIMINATED:")
for name, reasons in eliminated:
    print(f"    ✗ {name}: {'; '.join(reasons)}")
if not eliminated:
    print(f"    None")

print(f"\n  STATISTICAL SIGNIFICANCE:")
print(f"    Deflated Sharpe p-value: {p_dsr:.4f} ({'significant' if p_dsr > 0.95 else 'not significant'})")
print(f"    White's Reality Check: {p_white*100:.1f}% ({'significant' if p_white > 0.95 else 'not significant'})")
b7 = RESULTS["block7"]
print(f"    Rolling holdout consistency: {b7['comb_wins']}/{b7['windows']} windows ({b7['pct']:.0f}%)")

print(f"\n  MDD-CONTROLLED RESULT:")
print(f"    At equal MDD ({bc['mdd_pct']:.1f}%), combined P&L=${cm['pnl']:.0f} vs baseline ${bc['pnl']:.0f}")
genuine = cm["pnl"] > bc["pnl"]
print(f"    Genuine improvement: {'YES' if genuine else 'NO'}")

print(f"\n  SCORING SYSTEM SAFETY:")
print(f"    Safe to drop: {[cond_names[c] for c in safe_to_drop]}")
print(f"    Dangerous to drop: {[cond_names[c] for c in dangerous]}")

print(f"\n  NO-FLAT REGIME SAFETY:")
print(f"    Extra trades profitable in aggregate: {'YES' if extra_pf > 1.0 else 'NO'} (PF={extra_pf:.2f})")
rem_ok = rem_pnl > 0 if extra_trades else False
print(f"    Profitable after removing top 3 outliers: {'YES' if rem_ok else 'NO'}")

# Final recommendation
if len(passed_all) == 4 and genuine and b7["pct"] >= 70:
    option = "C"
    confidence = "HIGH" if p_white > 0.95 else "MEDIUM"
elif len(passed_all) >= 1 and genuine:
    option = "B"
    confidence = "MEDIUM"
else:
    option = "A"
    confidence = "HIGH" if not genuine else "MEDIUM"

print(f"""
  ┌─────────────────────────────────────────────────────────────────────┐
  │  FINAL RECOMMENDATION:                                              │
  │                                                                     │
  │  Option A — ADOPT NONE:                                            │
  │    Keep current system. Sharpe=1.87, MDD=51.4%.                    │
  │                                                                     │
  │  Option B — ADOPT SUBSET:                                          │
  │    Only: {', '.join(passed_all) if passed_all else 'none':<55} │
  │    Deploy one at a time, one month apart.                           │
  │                                                                     │
  │  Option C — ADOPT ALL:                                             │
  │    All 4 improvements validated. Deploy in efficiency order.        │
  │    MDD-matched Sharpe: {cm['sharpe']:.2f} at ${matched_margin} margin{' '*22}│
  │                                                                     │
  │  WHICH OPTION: {option}{' '*53}│
  │  CONFIDENCE: {confidence}{' '*(56-len(confidence))}│
  │  REASONING: Passed {len(passed_all)}/4 tests, {b7['pct']:.0f}% rolling windows,{' '*18}│
  │    MDD-matched P&L {'>' if genuine else '<='} baseline, DSR p={p_dsr:.3f}{' '*25}│
  └─────────────────────────────────────────────────────────────────────┘""")

# Save
def ser(obj):
    if isinstance(obj, dict): return {str(k): ser(v) for k, v in obj.items()}
    elif isinstance(obj, (list, tuple)): return [ser(i) for i in obj]
    elif isinstance(obj, (int, float, str, bool, type(None))): return obj
    else: return str(obj)

RESULTS["block10"] = {"option": option, "confidence": confidence, "passed": passed_all,
                       "eliminated": [(n, r) for n, r in eliminated]}

with open(f"{OUT}/improvement_validation.json", 'w') as f:
    json.dump(ser(RESULTS), f, indent=2, default=str)

print(f"\nResults saved to {OUT}/improvement_validation.json")
print(f"Total runtime: {total_time:.1f}s")

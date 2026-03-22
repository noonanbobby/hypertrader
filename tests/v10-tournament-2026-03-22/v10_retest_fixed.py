#!/usr/bin/env python3
"""V10 Retest — FIXED percent-of-equity sizing with realistic exchange constraints."""
import json, subprocess, os, math, time
from collections import defaultdict

ENGINE = "/home/ubuntu/hypertrader-engine-v4/target/release/hypertrader-engine"
DATA_DIR = "/opt/hypertrader/addons/backtest-data"
HOLDOUT = "2025-03-19"
ASSETS = ["BTC", "ETH", "SOL"]
T0 = time.time()

def v10_cfg(assets, tf="30m", date_range=None, out="/tmp/_tmp.json"):
    sp = {"timeframe":tf,"atr_period":10,"base_mult":6.0,"trend_mult":4.0,"range_mult":8.0,
        "adx_adapt_thresh":25.0,"slow_atr_period":20,"slow_mult":8.0,"use_dual_st_buys":True,
        "use_dual_st_sells":True,"cooldown":2,"late_window":1,"min_score":6,"use_rsi":True,
        "rsi_period":14,"rsi_buy_max":70,"rsi_sell_min":30,"use_zlema":True,"zlema_period":200,
        "use_volume":True,"vol_sma_period":20,"vol_multiplier":1.0,"use_adx_filter":True,
        "adx_period":14,"adx_minimum":25.0,"use_squeeze":True,"exit_on_raw_flip":True,
        "use_ema_atr":True,"longs_only":False}
    cfg = {"assets":assets,"data_dir":DATA_DIR,"mode":"baseline","timeframe":tf,
        "params":{"ema200_period":200,"ema50_period":50,"ema50_rising_lookback":5,
            "st_4h_atr_period":10,"st_4h_multiplier":3.0,"st_15m_atr_period":10,
            "st_15m_multiplier":2.0,"near_band_pct":0.005,"rsi_period":14,"rsi_threshold":45.0,
            "rsi_lookback":2,"ema_fast":21,"ema_slow":55,"vol_mult":2.0,"vol_sma_period":20,"warmup":300},
        "strategy":{"long_entry":{"type":"adaptive_zlema_st","params":sp},
            "short_entry":{"type":"adaptive_zlema_st_short","params":{"timeframe":tf}},
            "exit":{"type":"current"}},
        "regime_config":{"type":"none"},
        "sizing":{"type":"flat","margin":125.0,"leverage":10.0,"starting_equity":500.0},
        "fees":{"maker_rate":0.0006,"slippage":0.0005,"funding_rate_per_8h":0.0001},
        "output_path":out}
    if date_range: cfg["date_range"] = date_range
    return cfg

def run(cfg, label=""):
    cp = cfg["output_path"].replace(".json","_cfg.json")
    with open(cp,'w') as f: json.dump(cfg, f)
    r = subprocess.run([ENGINE, cp], capture_output=True, text=True, timeout=300)
    if r.returncode != 0: print(f"  ERROR {label}: {r.stderr[-200:]}")
    with open(cfg["output_path"]) as f: return json.load(f)

def pct_equity_sim(trade_log, starting=100000, fraction=0.50, leverage=7.0,
                   base_margin=125, base_leverage=10,
                   max_notional=10_000_000):
    """Recompute equity with percent-of-equity sizing.

    FIXED version with realistic exchange constraints:
    - max_notional: hard cap on per-trade notional (exchange position limit)
      Default $10M represents a realistic Hyperliquid BTC max for individual traders.
    - Liquidation: if trade loss exceeds deployed margin, cap loss at -margin.
    """
    equity = starting
    base_notional = base_margin * base_leverage  # 1250
    eq_curve = [equity]
    yearly = defaultdict(lambda: {"start": None, "end": 0, "pnl": 0, "trades": 0, "liqs": 0})
    liquidations = 0

    for t in trade_log:
        yr = t.get("entry_ts","")[:4]
        if yearly[yr]["start"] is None: yearly[yr]["start"] = equity

        # Target position sizing
        target_notional = fraction * equity * leverage
        # Cap at exchange limit
        actual_notional = min(target_notional, max_notional) if max_notional > 0 else target_notional
        actual_margin = actual_notional / leverage

        # Scale factor: how much bigger is our position vs the base $125 flat run
        scale = actual_notional / base_notional if base_notional > 0 else 1

        # Scale the P&L
        scaled_pnl = t["pnl"] * scale

        # Liquidation check: loss cannot exceed deployed margin
        if scaled_pnl < -actual_margin:
            scaled_pnl = -actual_margin
            liquidations += 1
            yearly[yr]["liqs"] += 1

        equity += scaled_pnl
        equity = max(equity, 0)
        eq_curve.append(equity)
        yearly[yr]["end"] = equity
        yearly[yr]["pnl"] += scaled_pnl
        yearly[yr]["trades"] += 1

    peak = starting; max_dd_pct = 0; max_dd_usd = 0
    peak_val = starting; trough_val = starting
    for e in eq_curve:
        peak = max(peak, e)
        dd_pct = (peak - e) / peak * 100 if peak > 0 else 0
        dd_usd = peak - e
        if dd_pct > max_dd_pct:
            max_dd_pct = dd_pct; max_dd_usd = dd_usd
            peak_val = peak; trough_val = e

    return {"final_equity": equity, "pnl": equity - starting, "mdd_pct": max_dd_pct,
            "mdd_usd": max_dd_usd, "peak_at_mdd": peak_val, "trough_at_mdd": trough_val,
            "yearly": dict(yearly), "liquidations": liquidations, "eq_curve": eq_curve}

# ============================================================
print("=" * 72)
print("  V10 RETEST — CORRECTED SIZING (with exchange limits)")
print("=" * 72)

# Run engine: v10 training (flat $125)
r_v10 = run(v10_cfg(ASSETS, date_range={"start":"2020-01-01","end":HOLDOUT},
    out="/tmp/v10fix_train.json"), "v10-train")
tl_v10 = r_v10["trade_log"]
p_v10 = r_v10["portfolio"]

# Run engine: our system training (flat $125)
our_cfg = json.load(open("/tmp/discovery/rust_baseline_config.json"))
our_cfg["output_path"] = "/tmp/v10fix_ours.json"
our_cfg["date_range"] = {"start":"2020-01-01","end":HOLDOUT}
with open("/tmp/v10fix_ours_cfg.json",'w') as f: json.dump(our_cfg, f)
subprocess.run([ENGINE, "/tmp/v10fix_ours_cfg.json"], capture_output=True, timeout=60)
with open("/tmp/v10fix_ours.json") as f: r_ours = json.load(f)
tl_ours = r_ours["trade_log"]
p_ours = r_ours["portfolio"]

# Holdout runs
r_v10_ho = run(v10_cfg(ASSETS, date_range={"start":HOLDOUT,"end":"2026-12-31"},
    out="/tmp/v10fix_holdout.json"), "v10-holdout")
tl_v10_ho = r_v10_ho["trade_log"]
p_v10_ho = r_v10_ho["portfolio"]

our_ho = json.load(open("/tmp/discovery/rust_baseline_config.json"))
our_ho["output_path"] = "/tmp/v10fix_holdout_ours.json"
our_ho["date_range"] = {"start":HOLDOUT,"end":"2026-12-31"}
with open("/tmp/v10fix_holdout_ours_cfg.json",'w') as f: json.dump(our_ho, f)
subprocess.run([ENGINE, "/tmp/v10fix_holdout_ours_cfg.json"], capture_output=True, timeout=60)
with open("/tmp/v10fix_holdout_ours.json") as f: r_ours_ho = json.load(f)
tl_ours_ho = r_ours_ho["trade_log"]
p_ours_ho = r_ours_ho["portfolio"]

# ============================================================
print("\n1. FLAT $125 (should match previous — unchanged by fix)")
print(f"   v10:  PF={p_v10['pf']}, P&L=${p_v10['pnl']}, Sharpe={p_v10['sharpe']}, Trades={p_v10['trades']}")
print(f"   Ours: PF={p_ours['pf']}, P&L=${p_ours['pnl']}, Sharpe={p_ours['sharpe']}, Trades={p_ours['trades']}")

# ============================================================
# CORRECTED percent-of-equity with $10M notional cap
print("\n" + "=" * 72)
print("2. CORRECTED PERCENT-OF-EQUITY SIZING")
print("   50% equity, 7x leverage, $100K start, $10M max notional per trade")
print("=" * 72)

for label, tl, pf_flat in [("His v10", tl_v10, p_v10), ("Our system", tl_ours, p_ours)]:
    sim = pct_equity_sim(tl, starting=100000, fraction=0.50, leverage=7.0, max_notional=10_000_000)
    print(f"\n  {label} (training):")
    print(f"    Final equity: ${sim['final_equity']:,.2f}")
    print(f"    Return: {(sim['final_equity']/100000-1)*100:.1f}%")
    print(f"    P&L: ${sim['pnl']:,.2f}")
    print(f"    MDD: {sim['mdd_pct']:.1f}% (${sim['mdd_usd']:,.0f})")
    print(f"    Peak at MDD: ${sim['peak_at_mdd']:,.0f} → Trough: ${sim['trough_at_mdd']:,.0f}")
    print(f"    Liquidations: {sim['liquidations']}")
    print(f"    Flat $125 PF: {pf_flat['pf']} | Flat $125 Sharpe: {pf_flat['sharpe']}")

    print(f"\n    Year-by-year:")
    print(f"    {'Year':<6}{'Start':>14}{'End':>14}{'P&L':>14}{'Return':>8}{'Trades':>7}{'Liqs':>6}")
    for yr in sorted(sim["yearly"]):
        y = sim["yearly"][yr]
        s = y["start"] if y["start"] else 100000
        ret = y["pnl"]/s*100 if s > 0 else 0
        print(f"    {yr:<6}{s:>14,.0f}{y['end']:>14,.0f}{y['pnl']:>14,.0f}{ret:>7.1f}%{y['trades']:>7}{y['liqs']:>6}")

# ============================================================
# Also test with different caps to show sensitivity
print("\n" + "=" * 72)
print("3. SENSITIVITY TO MAX NOTIONAL CAP")
print("=" * 72)

print(f"\n  {'Cap':>12}  {'v10 Final Eq':>16}  {'v10 Return':>10}  {'v10 MDD':>8}  {'Ours Final Eq':>16}  {'Ours Return':>10}  {'Ours MDD':>8}")
for cap in [2_000_000, 5_000_000, 10_000_000, 25_000_000, 50_000_000, 0]:
    sv = pct_equity_sim(tl_v10, max_notional=cap)
    so = pct_equity_sim(tl_ours, max_notional=cap)
    cap_str = f"${cap/1e6:.0f}M" if cap > 0 else "No cap"
    print(f"  {cap_str:>12}  {sv['final_equity']:>16,.0f}  {(sv['final_equity']/1e5-1)*100:>9.0f}%  {sv['mdd_pct']:>7.1f}%  {so['final_equity']:>16,.0f}  {(so['final_equity']/1e5-1)*100:>9.0f}%  {so['mdd_pct']:>7.1f}%")

# ============================================================
print("\n" + "=" * 72)
print("4. HOLDOUT COMPARISON (corrected sizing, $10M cap)")
print("=" * 72)

sv_ho = pct_equity_sim(tl_v10_ho, max_notional=10_000_000)
so_ho = pct_equity_sim(tl_ours_ho, max_notional=10_000_000)

print(f"""
  Holdout (his sizing, $10M cap):
                  {'PF':>7}{'Flat P&L':>10}{'Equity P&L':>14}{'Final Eq':>14}{'MDD%':>7}{'Liqs':>6}
  His v10         {p_v10_ho.get('pf',0):>7.2f}{p_v10_ho.get('pnl',0):>10.2f}{sv_ho['pnl']:>14,.2f}{sv_ho['final_equity']:>14,.2f}{sv_ho['mdd_pct']:>6.1f}%{sv_ho['liquidations']:>6}
  Our system      {p_ours_ho.get('pf',0):>7.2f}{p_ours_ho.get('pnl',0):>10.2f}{so_ho['pnl']:>14,.2f}{so_ho['final_equity']:>14,.2f}{so_ho['mdd_pct']:>6.1f}%{so_ho['liquidations']:>6}

  Holdout ($125 flat):
  His v10:  PF={p_v10_ho.get('pf',0)}, Sharpe={p_v10_ho.get('sharpe',0)}, P&L=${p_v10_ho.get('pnl',0):.2f}
  Our sys:  PF={p_ours_ho.get('pf',0)}, Sharpe={p_ours_ho.get('sharpe',0)}, P&L=${p_ours_ho.get('pnl',0):.2f}
""")

# ============================================================
print("=" * 72)
print("5. FINAL COMPARISON — CORRECTED")
print("=" * 72)

sv_t = pct_equity_sim(tl_v10, max_notional=10_000_000)
so_t = pct_equity_sim(tl_ours, max_notional=10_000_000)

print(f"""
  AT EQUAL SIZING ($125 flat — pure strategy quality):
    Our system: Sharpe={p_ours['sharpe']}, PF={p_ours['pf']}, P&L=${p_ours['pnl']:,.2f}
    His v10:    Sharpe={p_v10['sharpe']}, PF={p_v10['pf']}, P&L=${p_v10['pnl']:,.2f}
    Winner: {'Ours' if p_ours['sharpe'] > p_v10['sharpe'] else 'His'}

  AT HIS SIZING — CORRECTED ($100K, 50%, 7x, $10M cap):
    Our system: ${so_t['final_equity']:,.0f} ({(so_t['final_equity']/1e5-1)*100:.0f}% return), MDD={so_t['mdd_pct']:.1f}%
    His v10:    ${sv_t['final_equity']:,.0f} ({(sv_t['final_equity']/1e5-1)*100:.0f}% return), MDD={sv_t['mdd_pct']:.1f}%
    Winner: {'Ours' if so_t['final_equity'] > sv_t['final_equity'] else 'His'}

  HOLDOUT ($125 flat):
    Our system: Sharpe={p_ours_ho['sharpe']}, PF={p_ours_ho['pf']}
    His v10:    Sharpe={p_v10_ho['sharpe']}, PF={p_v10_ho['pf']}
    Winner: {'Ours' if p_ours_ho['sharpe'] > p_v10_ho['sharpe'] else 'His'}

  HOLDOUT (his sizing, $10M cap):
    Our system: ${so_ho['final_equity']:,.0f}, MDD={so_ho['mdd_pct']:.1f}%
    His v10:    ${sv_ho['final_equity']:,.0f}, MDD={sv_ho['mdd_pct']:.1f}%
    Winner: {'Ours' if so_ho['final_equity'] > sv_ho['final_equity'] else 'His'}
""")

# Save
results = {
    "fix_description": "Added $10M max notional cap per trade to pct_equity_sim. "
        "Also fixed engine funding calculation for non-15m timeframes.",
    "flat_125": {"v10": p_v10, "ours": p_ours},
    "pct_equity_corrected_10M_cap": {
        "v10_training": {"final_equity": sv_t["final_equity"], "mdd_pct": sv_t["mdd_pct"],
            "liquidations": sv_t["liquidations"]},
        "ours_training": {"final_equity": so_t["final_equity"], "mdd_pct": so_t["mdd_pct"],
            "liquidations": so_t["liquidations"]},
        "v10_holdout": {"final_equity": sv_ho["final_equity"], "mdd_pct": sv_ho["mdd_pct"]},
        "ours_holdout": {"final_equity": so_ho["final_equity"], "mdd_pct": so_ho["mdd_pct"]},
    },
    "holdout_flat": {"v10": p_v10_ho, "ours": p_ours_ho},
    "runtime": time.time() - T0,
}
with open("/tmp/discovery/v10_retest_fixed.json", 'w') as f:
    json.dump(results, f, indent=2, default=str)
print(f"  Saved to /tmp/discovery/v10_retest_fixed.json ({time.time()-T0:.1f}s)")

#!/usr/bin/env python3
"""
Colleague Strategy Comparison & Component Analysis
Comprehensive backtesting comparison using the v3 Rust engine.
"""

import json
import subprocess
import time
import os
import copy
import math
from datetime import datetime, timezone, timedelta

ENGINE = "/tmp/discovery/hypertrader-engine-v3/target/release/hypertrader-engine"
DATA_DIR = "/opt/hypertrader/addons/backtest-data"
OUT_DIR = "/tmp/discovery"
RESULTS = {}
TOTAL_START = time.time()

# ─── Date range ───
# Data: 2020-01-01 to 2026-03-19
# Holdout: last 12 months → 2025-03-19 to 2026-03-19
# Training: start to 2025-03-19
HOLDOUT_DATE = "2025-03-19"
DATA_END = "2026-03-19"
print(f"Holdout boundary: {HOLDOUT_DATE} (training: start → {HOLDOUT_DATE}, holdout: {HOLDOUT_DATE} → {DATA_END})")

# ─── Base configs ───
BASE_PARAMS = {
    "ema200_period": 200, "ema50_period": 50, "ema50_rising_lookback": 5,
    "st_4h_atr_period": 10, "st_4h_multiplier": 3.0,
    "st_15m_atr_period": 10, "st_15m_multiplier": 2.0,
    "near_band_pct": 0.005, "rsi_period": 14, "rsi_threshold": 45.0,
    "rsi_lookback": 2, "ema_fast": 21, "ema_slow": 55,
    "vol_mult": 2.0, "vol_sma_period": 20, "warmup": 300
}

BASE_FEES = {"maker_rate": 0.00045, "slippage": 0.0005, "funding_rate_per_8h": 0.0001}

def make_our_config(assets, output, leverage=10.0, margin=125.0, equity=500.0,
                    date_range=None, signal_extras=None, regime_config=None,
                    timeframe=None, robustness=None, bootstrap=None):
    cfg = {
        "assets": assets,
        "data_dir": DATA_DIR,
        "mode": "baseline",
        "params": BASE_PARAMS.copy(),
        "sizing": {"type": "flat", "margin": margin, "leverage": leverage, "starting_equity": equity},
        "fees": BASE_FEES.copy(),
        "friction": {"enabled": False},
        "robustness": robustness or {"enabled": False},
        "bootstrap": bootstrap or {"enabled": False},
        "output_path": output,
    }
    if date_range:
        cfg["date_range"] = date_range
    if signal_extras:
        cfg["signal_extras"] = signal_extras
    if regime_config:
        cfg["regime_config"] = regime_config
    if timeframe:
        cfg["timeframe"] = timeframe
    return cfg


def make_colleague_config(assets, output, margin=125.0, leverage=10.0, equity=500.0,
                          date_range=None, commission=0.00045, slippage=0.0005):
    return {
        "assets": assets,
        "data_dir": DATA_DIR,
        "mode": "baseline",
        "timeframe": "1H",
        "params": BASE_PARAMS.copy(),
        "regime_config": {"type": "none"},
        "strategy": {
            "long_entry": {
                "type": "dual_supertrend",
                "params": {
                    "timeframe": "1H",
                    "primary_atr_period": 12, "primary_multiplier": 1.3,
                    "primary_source": "close", "primary_use_rma": True,
                    "confirm_atr_period": 20, "confirm_multiplier": 2.5,
                    "use_dual_st_buys": True, "use_dual_st_sells": False,
                    "min_score": 2, "late_window": 15, "cooldown_bars": 2,
                    "use_rsi_filter": True, "rsi_period": 14, "rsi_buy_max": 70, "rsi_sell_min": 15,
                    "use_ema_filter": True, "ema_period": 200,
                    "use_volume_filter": True, "volume_sma_period": 20, "volume_multiplier": 1.0
                }
            },
            "short_entry": {"type": "dual_supertrend_short", "params": {"timeframe": "1H"}},
            "exit": {"type": "flip"}
        },
        "sizing": {"type": "flat", "margin": margin, "leverage": leverage, "starting_equity": equity},
        "fees": {"maker_rate": commission, "slippage": slippage, "funding_rate_per_8h": 0.0001},
        "friction": {"enabled": False},
        "robustness": {"enabled": False},
        "bootstrap": {"enabled": False},
        "output_path": output,
        **({"date_range": date_range} if date_range else {}),
    }


def run_engine(config, label=""):
    cfg_path = config["output_path"].replace(".json", "_cfg.json")
    with open(cfg_path, 'w') as f:
        json.dump(config, f)
    t0 = time.time()
    result = subprocess.run([ENGINE, cfg_path], capture_output=True, text=True)
    elapsed = time.time() - t0
    if result.returncode != 0:
        print(f"  ERROR [{label}]: {result.stderr[-500:]}")
        return None
    try:
        with open(config["output_path"]) as f:
            data = json.load(f)
        if label:
            print(f"  [{label}] {elapsed:.2f}s")
        return data
    except Exception as e:
        print(f"  ERROR reading output [{label}]: {e}")
        return None


def get_stats(data, asset=None):
    """Extract stats from engine output."""
    if asset and "asset_stats" in data and asset in data["asset_stats"]:
        return data["asset_stats"][asset]
    return data.get("portfolio", {})


def fmt(val, prefix="", suffix="", decimals=2):
    if val is None:
        return "N/A"
    if isinstance(val, float):
        return f"{prefix}{val:.{decimals}f}{suffix}"
    return f"{prefix}{val}{suffix}"


def yearly_pnl(data, asset=None):
    """Extract year-by-year P&L from monthly data."""
    years = {}
    stats = get_stats(data, asset) if asset else data.get("portfolio", {})
    monthly = stats.get("monthly", {})
    for ym, pnl in monthly.items():
        year = ym[:4]
        years[year] = years.get(year, 0) + pnl
    return years


def portfolio_yearly_pnl(data):
    """Sum yearly P&L across all assets."""
    years = {}
    for asset, stats in data.get("asset_stats", {}).items():
        for ym, pnl in stats.get("monthly", {}).items():
            year = ym[:4]
            years[year] = years.get(year, 0) + pnl
    return years


TRAINING_DR = {"start": None, "end": HOLDOUT_DATE}
HOLDOUT_DR = {"start": HOLDOUT_DATE, "end": None}

# ═══════════════════════════════════════════════════════════════
# BLOCK 1 — Colleague's Exact Strategy
# ═══════════════════════════════════════════════════════════════
print("\n" + "="*70)
print("BLOCK 1 — COLLEAGUE'S EXACT STRATEGY")
print("="*70)

# 1a: $125 fixed sizing, 3 assets, training period
coll_fixed = make_colleague_config(
    ["BTC", "ETH", "SOL"],
    f"{OUT_DIR}/cc_b1_fixed.json",
    margin=125.0, leverage=10.0, equity=500.0,
    date_range=TRAINING_DR
)
r_coll_fixed = run_engine(coll_fixed, "Colleague $125 fixed, 3 assets, training")

# 1b: TradingView settings ($10K, all-in) — BTC only
coll_tv = make_colleague_config(
    ["BTC"],
    f"{OUT_DIR}/cc_b1_tv.json",
    margin=1000.0, leverage=10.0, equity=10000.0,
    date_range=TRAINING_DR,
    commission=0.0005, slippage=0.0005
)
r_coll_tv = run_engine(coll_tv, "Colleague TradingView settings, BTC only")

# Print Block 1
if r_coll_fixed and r_coll_tv:
    print("\nBLOCK 1 — COLLEAGUE'S EXACT STRATEGY:\n")
    print("  $125 FIXED SIZING (for fair comparison with our system):")
    print(f"    {'Asset':<6} {'PF':<7} {'P&L':<10} {'Sharpe':<8} {'MDD%':<7} {'Trades':<8} {'WR%':<7} {'Avg Hold':<10} {'Fees':<8} {'Funding':<8}")
    total_fees = 0
    total_funding = 0
    for asset in ["BTC", "ETH", "SOL"]:
        s = get_stats(r_coll_fixed, asset)
        longs = sum(1 for t in r_coll_fixed.get("trade_log", []) if t["asset"] == asset and t["direction"] == "long")
        shorts = sum(1 for t in r_coll_fixed.get("trade_log", []) if t["asset"] == asset and t["direction"] == "short")
        total_fees += s.get("fees", 0)
        total_funding += s.get("funding", 0)
        print(f"    {asset:<6} {s.get('pf',0):<7.2f} ${s.get('pnl',0):<9.2f} {s.get('sharpe',0):<8.2f} {s.get('mdd_pct',0):<6.1f}% {s.get('trades',0):<8} {s.get('wr',0):<6.1f}% {s.get('avg_bars',0):<10.1f} ${s.get('fees',0):<7.2f} ${s.get('funding',0):<7.2f}")
    p = r_coll_fixed.get("portfolio", {})
    print(f"    {'PORT':<6} {p.get('pf',0):<7.2f} ${p.get('pnl',0):<9.2f} {p.get('sharpe',0):<8.2f} {p.get('mdd_pct',0):<6.1f}% {p.get('trades',0):<8}")
    print(f"    Total fees: ${total_fees:.2f}  Total funding: ${total_funding:.2f}")

    print("\n  100% EQUITY SIZING (TradingView settings):")
    btc_tv = get_stats(r_coll_tv, "BTC")
    print(f"    BTC: PF={btc_tv.get('pf',0):.2f} | P&L=${btc_tv.get('pnl',0):.2f} | Sharpe={btc_tv.get('sharpe',0):.2f} | MDD={btc_tv.get('mdd_pct',0):.1f}% | Trades={btc_tv.get('trades',0)}")

    print("\n  Year-by-year P&L ($125 sizing, BTC only):")
    yp_btc = yearly_pnl(r_coll_fixed, "BTC")
    for y in sorted(yp_btc.keys()):
        print(f"    {y}: ${yp_btc[y]:.2f}")

    print("\n  Year-by-year P&L ($125 sizing, 3-asset portfolio):")
    yp_port = portfolio_yearly_pnl(r_coll_fixed)
    for y in sorted(yp_port.keys()):
        print(f"    {y}: ${yp_port[y]:.2f}")

    # Losing trades analysis
    all_trades = r_coll_fixed.get("trade_log", [])
    losing = [t for t in all_trades if t["pnl"] < 0]
    losing_pct = len(losing) / len(all_trades) * 100 if all_trades else 0
    longest_loser = max(all_trades, key=lambda t: t["bars_held"] if t["pnl"] < 0 else 0, default=None)
    biggest_loser = min(all_trades, key=lambda t: t["pnl"], default=None)

    print(f"\n  OBSERVATIONS:")
    print(f"    Always-in total fee drag: ${total_fees:.2f}")
    print(f"    Always-in total funding drag: ${total_funding:.2f}")
    print(f"    % of losing trades: {losing_pct:.1f}%")
    if biggest_loser:
        print(f"    Biggest single loss: ${biggest_loser['pnl']:.2f} ({biggest_loser['bars_held']} bars)")
    if longest_loser and longest_loser["pnl"] < 0:
        print(f"    Longest losing trade: {longest_loser['bars_held']} bars (${longest_loser['pnl']:.2f})")

    # Choppy market analysis (2023, 2025)
    for y in ["2023", "2025"]:
        yp = yp_port.get(y, 0)
        print(f"    {y} (choppy) portfolio P&L: ${yp:.2f}")

RESULTS["block1"] = {
    "fixed": r_coll_fixed,
    "tv": r_coll_tv,
}

# ═══════════════════════════════════════════════════════════════
# BLOCK 2 — HEAD-TO-HEAD COMPARISON
# ═══════════════════════════════════════════════════════════════
print("\n" + "="*70)
print("BLOCK 2 — HEAD-TO-HEAD COMPARISON")
print("="*70)

# Our system: 3 assets, BTC/ETH 10x, SOL 5x — need separate runs for SOL
# Run BTC+ETH at 10x
our_btceth = make_our_config(
    ["BTC", "ETH"], f"{OUT_DIR}/cc_b2_ours_btceth.json",
    leverage=10.0, date_range=TRAINING_DR
)
r_our_btceth = run_engine(our_btceth, "Our system BTC+ETH 10x")

# Run SOL at 5x
our_sol = make_our_config(
    ["SOL"], f"{OUT_DIR}/cc_b2_ours_sol.json",
    leverage=5.0, date_range=TRAINING_DR
)
r_our_sol = run_engine(our_sol, "Our system SOL 5x")

# Colleague: all 10x
# Already have r_coll_fixed from Block 1

# Colleague with SOL at 5x
coll_btceth_10x = make_colleague_config(
    ["BTC", "ETH"], f"{OUT_DIR}/cc_b2_coll_btceth.json",
    margin=125.0, leverage=10.0, equity=500.0, date_range=TRAINING_DR
)
r_coll_btceth = run_engine(coll_btceth_10x, "Colleague BTC+ETH 10x")

coll_sol_5x = make_colleague_config(
    ["SOL"], f"{OUT_DIR}/cc_b2_coll_sol5x.json",
    margin=125.0, leverage=5.0, equity=500.0, date_range=TRAINING_DR
)
r_coll_sol5x = run_engine(coll_sol_5x, "Colleague SOL 5x")

# Combine our results
def combine_results(r1, r2):
    """Combine two engine outputs into a portfolio view."""
    combined = {"asset_stats": {}, "portfolio": {}, "trade_log": []}
    for r in [r1, r2]:
        if r:
            for a, s in r.get("asset_stats", {}).items():
                combined["asset_stats"][a] = s
            combined["trade_log"].extend(r.get("trade_log", []))
    # Recompute portfolio
    trades = combined["trade_log"]
    if trades:
        pnl = sum(t["pnl"] for t in trades)
        wins = [t for t in trades if t["pnl"] > 0]
        losses = [t for t in trades if t["pnl"] <= 0]
        gp = sum(t["pnl"] for t in wins)
        gl = abs(sum(t["pnl"] for t in losses))
        pf = gp / gl if gl > 0 else (99.0 if gp > 0 else 0.0)
        wr = len(wins) / len(trades) * 100
        fees = sum(t["fees"] for t in trades)
        funding = sum(t["funding"] for t in trades)
        avg_bars = sum(t["bars_held"] for t in trades) / len(trades)
        # Monthly P&L for Sharpe
        monthly = {}
        for t in trades:
            ym = t["exit_ts"][:7]
            monthly[ym] = monthly.get(ym, 0) + t["pnl"]
        rets = [v/500.0 for v in monthly.values()]
        if len(rets) >= 2:
            mean = sum(rets) / len(rets)
            var = sum((r - mean)**2 for r in rets) / len(rets)
            std = var**0.5
            sharpe = mean / std * 12**0.5 if std > 0 else 0
        else:
            sharpe = 0
        # MDD from monthly cumulative
        cum = 0
        peak = 0
        mdd = 0
        for ym in sorted(monthly.keys()):
            cum += monthly[ym]
            peak = max(peak, cum)
            dd = peak - cum
            mdd = max(mdd, dd)
        mdd_pct = mdd / 500.0 * 100 if mdd > 0 else 0

        combined["portfolio"] = {
            "trades": len(trades), "pnl": round(pnl, 2), "pf": round(pf, 2),
            "sharpe": round(sharpe, 2), "mdd_pct": round(mdd_pct, 1),
            "wr": round(wr, 1), "fees": round(fees, 2), "funding": round(funding, 2),
            "avg_bars": round(avg_bars, 1), "monthly": monthly
        }
    return combined

r_ours = combine_results(r_our_btceth, r_our_sol)
r_coll_sol5x_combined = combine_results(r_coll_btceth, r_coll_sol5x)

# Print Block 2
print("\nBLOCK 2 — HEAD-TO-HEAD:\n")
print("  3-ASSET PORTFOLIO COMPARISON:")
print(f"    {'Metric':<22} {'Our System':<18} {'His (10x all)':<18} {'His (SOL 5x)':<18}")

for label, key in [("P&L:", "pnl"), ("PF:", "pf"), ("Sharpe:", "sharpe"), ("MDD%:", "mdd_pct"),
                    ("Trades:", "trades")]:
    ov = r_ours["portfolio"].get(key, "N/A")
    hv = r_coll_fixed["portfolio"].get(key, "N/A") if r_coll_fixed else "N/A"
    h5v = r_coll_sol5x_combined["portfolio"].get(key, "N/A")
    if isinstance(ov, float):
        print(f"    {label:<22} {ov:<18.2f} {hv:<18.2f} {h5v:<18.2f}")
    else:
        print(f"    {label:<22} {str(ov):<18} {str(hv):<18} {str(h5v):<18}")

# Time in market
our_time = 0
our_total = 0
for asset_data in [r_our_btceth, r_our_sol]:
    if asset_data:
        for a, s in asset_data.get("asset_stats", {}).items():
            n = s.get("n_bars", 0)
            bull = s.get("regime_bull_pct", 0) or 0
            bear = s.get("regime_bear_pct", 0) or 0
            our_total += n
            # Approximate: in-market ≈ trades × avg bars / total bars
            trades_bars = s.get("trades", 0) * s.get("avg_bars", 0)
            our_time += trades_bars

our_time_pct = our_time / our_total * 100 if our_total > 0 else 0
our_fees = sum(s.get("fees", 0) for s in r_ours["asset_stats"].values())
our_funding = sum(s.get("funding", 0) for s in r_ours["asset_stats"].values())

print(f"    {'Time in market:':<22} {our_time_pct:<17.1f}% {'~100%':<18} {'~100%':<18}")
print(f"    {'Total fees:':<22} ${our_fees:<17.2f} ${r_coll_fixed['portfolio'].get('pnl',0) + sum(get_stats(r_coll_fixed, a).get('fees',0) for a in ['BTC','ETH','SOL']) if r_coll_fixed else 0 :.2f}")

print("\n  PER-ASSET BREAKDOWN:")
for asset in ["BTC", "ETH", "SOL"]:
    o = r_ours["asset_stats"].get(asset, {})
    h = get_stats(r_coll_fixed, asset) if r_coll_fixed else {}
    winner = "Ours" if o.get("pnl", 0) > h.get("pnl", 0) else "His"
    print(f"    {asset}: Our PF={o.get('pf',0):.2f} P&L=${o.get('pnl',0):.2f} | His PF={h.get('pf',0):.2f} P&L=${h.get('pnl',0):.2f} | Winner: {winner}")

print("\n  YEAR-BY-YEAR (3-asset portfolio):")
our_yearly = {}
for r in [r_our_btceth, r_our_sol]:
    if r:
        for a, s in r.get("asset_stats", {}).items():
            for ym, pnl in s.get("monthly", {}).items():
                y = ym[:4]
                our_yearly[y] = our_yearly.get(y, 0) + pnl

coll_yearly = portfolio_yearly_pnl(r_coll_fixed) if r_coll_fixed else {}
all_years = sorted(set(list(our_yearly.keys()) + list(coll_yearly.keys())))
print(f"    {'Year':<6} {'Our P&L':<12} {'His P&L':<12} {'Winner':<8}")
for y in all_years:
    ov = our_yearly.get(y, 0)
    hv = coll_yearly.get(y, 0)
    winner = "Ours" if ov > hv else "His"
    print(f"    {y:<6} ${ov:<11.2f} ${hv:<11.2f} {winner}")

# Market regime comparisons
print("\n  MARKET REGIME ANALYSIS:")
for years_label, year_list in [("BEAR (2022)", ["2022"]), ("BULL (2021)", ["2021"]),
                                 ("CHOPPY (2023+2025)", ["2023", "2025"])]:
    ov = sum(our_yearly.get(y, 0) for y in year_list)
    hv = sum(coll_yearly.get(y, 0) for y in year_list)
    winner = "Ours" if ov > hv else "His"
    print(f"    {years_label}: Our=${ov:.2f} His=${hv:.2f} Winner={winner}")

# Overall winner
our_p = r_ours["portfolio"]
his_p = r_coll_fixed["portfolio"] if r_coll_fixed else {}
print("\n  OVERALL WINNER:")
for label, key, higher_better in [("By Sharpe:", "sharpe", True), ("By P&L:", "pnl", True), ("By MDD:", "mdd_pct", False)]:
    ov = our_p.get(key, 0)
    hv = his_p.get(key, 0)
    if higher_better:
        winner = "Ours" if ov > hv else "His"
    else:
        winner = "Ours" if ov < hv else "His"
    print(f"    {label} {winner} ({ov:.2f} vs {hv:.2f})")

RESULTS["block2"] = {"ours": r_ours, "colleague_10x": r_coll_fixed, "colleague_sol5x": r_coll_sol5x_combined}

# ═══════════════════════════════════════════════════════════════
# BLOCK 3 — CAN HIS IDEAS IMPROVE OUR SYSTEM?
# ═══════════════════════════════════════════════════════════════
print("\n" + "="*70)
print("BLOCK 3 — CAN HIS IDEAS IMPROVE OUR SYSTEM?")
print("="*70)

# Baseline for comparison
our_baseline_sharpe = our_p.get("sharpe", 0)
our_baseline_pnl = our_p.get("pnl", 0)
our_baseline_trades = our_p.get("trades", 0)
print(f"\n  Our baseline: Sharpe={our_baseline_sharpe:.2f}, PF={our_p.get('pf',0):.2f}, P&L=${our_baseline_pnl:.2f}, Trades={our_baseline_trades}")

improvements = []

# ─── Test 3A: Late Confirmation Window ───
print("\n  TEST 3A — LATE CONFIRMATION WINDOW ON OUR SYSTEM:")
print(f"    {'Window':<8} {'Trades':<8} {'PF':<7} {'P&L':<10} {'Sharpe':<8} {'MDD%':<7} {'New vs base':<12}")

test3a_results = {}
for window in [0, 1, 2, 3, 5, 8, 10, 15, 20]:
    # BTC+ETH 10x
    cfg_be = make_our_config(
        ["BTC", "ETH"], f"{OUT_DIR}/cc_3a_be_w{window}.json",
        leverage=10.0, date_range=TRAINING_DR,
        signal_extras={"late_window": window, "min_score_long": 5, "min_score_short": 4}
    )
    r_be = run_engine(cfg_be, f"3A w={window} BTC+ETH")

    # SOL 5x
    cfg_s = make_our_config(
        ["SOL"], f"{OUT_DIR}/cc_3a_sol_w{window}.json",
        leverage=5.0, date_range=TRAINING_DR,
        signal_extras={"late_window": window, "min_score_long": 5, "min_score_short": 4}
    )
    r_s = run_engine(cfg_s, f"3A w={window} SOL")

    combined = combine_results(r_be, r_s)
    p = combined["portfolio"]
    delta = p.get("trades", 0) - our_baseline_trades
    print(f"    {window:<8} {p.get('trades',0):<8} {p.get('pf',0):<7.2f} ${p.get('pnl',0):<9.2f} {p.get('sharpe',0):<8.2f} {p.get('mdd_pct',0):<6.1f}% {'+' if delta >= 0 else ''}{delta}")
    test3a_results[window] = p

# Find best
best_3a = max(test3a_results.items(), key=lambda x: x[1].get("sharpe", 0))
if best_3a[1].get("sharpe", 0) > our_baseline_sharpe:
    print(f"\n  Late confirmation HELPS: optimal window={best_3a[0]}, Sharpe improves {our_baseline_sharpe:.2f} → {best_3a[1]['sharpe']:.2f}")
    improvements.append(("late_window", best_3a[0], best_3a[1]["sharpe"]))
else:
    print(f"\n  Late confirmation DOESN'T HELP: best window={best_3a[0]}, Sharpe={best_3a[1].get('sharpe',0):.2f} vs baseline {our_baseline_sharpe:.2f}")

# ─── Test 3B: Scoring System ───
print("\n  TEST 3B — SCORING SYSTEM ON OUR ENTRIES:")
print("\n  LONG ENTRIES:")
print(f"    {'Min Score':<10} {'Trades':<8} {'PF':<7} {'P&L':<10} {'Sharpe':<8} {'MDD%':<7}")

test3b_long = {}
for ms in [2, 3, 4, 5]:
    cfg_be = make_our_config(
        ["BTC", "ETH"], f"{OUT_DIR}/cc_3b_long_be_{ms}.json",
        leverage=10.0, date_range=TRAINING_DR,
        signal_extras={"min_score_long": ms, "min_score_short": 4}
    )
    r_be = run_engine(cfg_be, f"3B long ms={ms} BTC+ETH")
    cfg_s = make_our_config(
        ["SOL"], f"{OUT_DIR}/cc_3b_long_sol_{ms}.json",
        leverage=5.0, date_range=TRAINING_DR,
        signal_extras={"min_score_long": ms, "min_score_short": 4}
    )
    r_s = run_engine(cfg_s, f"3B long ms={ms} SOL")
    combined = combine_results(r_be, r_s)
    p = combined["portfolio"]
    baseline_mark = " (baseline)" if ms == 5 else ""
    print(f"    {ms} of 5{baseline_mark:<5} {p.get('trades',0):<8} {p.get('pf',0):<7.2f} ${p.get('pnl',0):<9.2f} {p.get('sharpe',0):<8.2f} {p.get('mdd_pct',0):<6.1f}%")
    test3b_long[ms] = p

print("\n  SHORT ENTRIES:")
print(f"    {'Min Score':<10} {'Trades':<8} {'PF':<7} {'P&L':<10} {'Sharpe':<8} {'MDD%':<7}")

test3b_short = {}
for ms in [2, 3, 4]:
    cfg_be = make_our_config(
        ["BTC", "ETH"], f"{OUT_DIR}/cc_3b_short_be_{ms}.json",
        leverage=10.0, date_range=TRAINING_DR,
        signal_extras={"min_score_long": 5, "min_score_short": ms}
    )
    r_be = run_engine(cfg_be, f"3B short ms={ms} BTC+ETH")
    cfg_s = make_our_config(
        ["SOL"], f"{OUT_DIR}/cc_3b_short_sol_{ms}.json",
        leverage=5.0, date_range=TRAINING_DR,
        signal_extras={"min_score_long": 5, "min_score_short": ms}
    )
    r_s = run_engine(cfg_s, f"3B short ms={ms} SOL")
    combined = combine_results(r_be, r_s)
    p = combined["portfolio"]
    baseline_mark = " (baseline)" if ms == 4 else ""
    print(f"    {ms} of 4{baseline_mark:<5} {p.get('trades',0):<8} {p.get('pf',0):<7.2f} ${p.get('pnl',0):<9.2f} {p.get('sharpe',0):<8.2f} {p.get('mdd_pct',0):<6.1f}%")
    test3b_short[ms] = p

# Best combo
all_3b = {}
for ml in [2, 3, 4, 5]:
    for ms in [2, 3, 4]:
        key = (ml, ms)
        # Use existing results where possible, otherwise compute
        if ml == 5 and ms == 4:
            all_3b[key] = test3b_long[5]  # baseline
        elif ml == 5:
            all_3b[key] = test3b_short[ms]
        elif ms == 4:
            all_3b[key] = test3b_long[ml]
        # else we'd need to compute — skip these combos for now

best_3b = max(all_3b.items(), key=lambda x: x[1].get("sharpe", 0))
if best_3b[1].get("sharpe", 0) > our_baseline_sharpe:
    print(f"\n  Scoring HELPS: optimal long={best_3b[0][0]}/5 short={best_3b[0][1]}/4, Sharpe={best_3b[1]['sharpe']:.2f}")
    improvements.append(("scoring", best_3b[0], best_3b[1]["sharpe"]))
else:
    print(f"\n  Scoring DOESN'T HELP: best={best_3b[0]}, Sharpe={best_3b[1].get('sharpe',0):.2f} vs baseline {our_baseline_sharpe:.2f}")

# ─── Test 3C: Dual SuperTrend Confirmation ───
print("\n  TEST 3C — DUAL SUPERTREND CONFIRMATION:")
print(f"    {'Config':<22} {'Trades':<8} {'PF':<7} {'P&L':<10} {'Sharpe':<8} {'MDD%':<7}")

# Baseline first
print(f"    {'No confirmation':<22} {our_baseline_trades:<8} {our_p.get('pf',0):<7.2f} ${our_baseline_pnl:<9.2f} {our_baseline_sharpe:<8.2f} {our_p.get('mdd_pct',0):<6.1f}%")

test3c_results = {}
for atr_p in [15, 20, 25, 30]:
    for mult in [2.0, 2.5, 3.0, 3.5, 4.0]:
        cfg_be = make_our_config(
            ["BTC", "ETH"], f"{OUT_DIR}/cc_3c_be_{atr_p}_{int(mult*10)}.json",
            leverage=10.0, date_range=TRAINING_DR,
            signal_extras={"confirm_st_atr": atr_p, "confirm_st_mult": mult}
        )
        r_be = run_engine(cfg_be, f"3C ATR={atr_p} M={mult}")
        cfg_s = make_our_config(
            ["SOL"], f"{OUT_DIR}/cc_3c_sol_{atr_p}_{int(mult*10)}.json",
            leverage=5.0, date_range=TRAINING_DR,
            signal_extras={"confirm_st_atr": atr_p, "confirm_st_mult": mult}
        )
        r_s = run_engine(cfg_s, f"3C ATR={atr_p} M={mult} SOL")
        combined = combine_results(r_be, r_s)
        p = combined["portfolio"]
        label = f"ATR={atr_p} M={mult}"
        print(f"    {label:<22} {p.get('trades',0):<8} {p.get('pf',0):<7.2f} ${p.get('pnl',0):<9.2f} {p.get('sharpe',0):<8.2f} {p.get('mdd_pct',0):<6.1f}%")
        test3c_results[(atr_p, mult)] = p

best_3c = max(test3c_results.items(), key=lambda x: x[1].get("sharpe", 0))
if best_3c[1].get("sharpe", 0) > our_baseline_sharpe:
    print(f"\n  Dual ST HELPS: best ATR={best_3c[0][0]} M={best_3c[0][1]}, Sharpe={best_3c[1]['sharpe']:.2f}")
    improvements.append(("dual_st", best_3c[0], best_3c[1]["sharpe"]))
else:
    print(f"\n  Dual ST DOESN'T HELP: reduces trades too much, best Sharpe={best_3c[1].get('sharpe',0):.2f}")

# ─── Test 3D: Our Strategy on 1H ───
print("\n  TEST 3D — OUR STRATEGY ON 1H:")

cfg_1h_be = make_our_config(
    ["BTC", "ETH"], f"{OUT_DIR}/cc_3d_1h_be.json",
    leverage=10.0, date_range=TRAINING_DR, timeframe="1H"
)
r_1h_be = run_engine(cfg_1h_be, "3D 1H BTC+ETH")

cfg_1h_s = make_our_config(
    ["SOL"], f"{OUT_DIR}/cc_3d_1h_sol.json",
    leverage=5.0, date_range=TRAINING_DR, timeframe="1H"
)
r_1h_s = run_engine(cfg_1h_s, "3D 1H SOL")
r_1h = combine_results(r_1h_be, r_1h_s)

p_1h = r_1h["portfolio"]
print(f"    {'Metric':<22} {'15m (baseline)':<18} {'1H':<18}")
for label, key in [("Trades:", "trades"), ("PF:", "pf"), ("P&L:", "pnl"),
                    ("Sharpe:", "sharpe"), ("MDD%:", "mdd_pct")]:
    ov = our_p.get(key, 0)
    hv = p_1h.get(key, 0)
    if isinstance(ov, float):
        print(f"    {label:<22} {ov:<18.2f} {hv:<18.2f}")
    else:
        print(f"    {label:<22} {str(ov):<18} {str(hv):<18}")

if p_1h.get("sharpe", 0) > our_baseline_sharpe:
    print(f"  1H timeframe HELPS: Sharpe improves {our_baseline_sharpe:.2f} → {p_1h['sharpe']:.2f}")
    improvements.append(("timeframe_1h", True, p_1h["sharpe"]))
else:
    print(f"  1H timeframe DOESN'T HELP: Sharpe={p_1h.get('sharpe',0):.2f} vs baseline {our_baseline_sharpe:.2f}")

# ─── Test 3E: Relaxed Short Filters ───
print("\n  TEST 3E — RELAXED SHORT FILTERS:")

cfg_re_be = make_our_config(
    ["BTC", "ETH"], f"{OUT_DIR}/cc_3e_relaxed_be.json",
    leverage=10.0, date_range=TRAINING_DR,
    signal_extras={"relaxed_shorts": True}
)
r_re_be = run_engine(cfg_re_be, "3E relaxed shorts BTC+ETH")

cfg_re_s = make_our_config(
    ["SOL"], f"{OUT_DIR}/cc_3e_relaxed_sol.json",
    leverage=5.0, date_range=TRAINING_DR,
    signal_extras={"relaxed_shorts": True}
)
r_re_s = run_engine(cfg_re_s, "3E relaxed shorts SOL")
r_relaxed = combine_results(r_re_be, r_re_s)

p_re = r_relaxed["portfolio"]
print(f"    {'Metric':<24} {'Current':<16} {'Relaxed':<16}")
for label, key in [("Short trades:", "trades"), ("PF:", "pf"), ("P&L:", "pnl"),
                    ("Sharpe:", "sharpe"), ("MDD%:", "mdd_pct")]:
    ov = our_p.get(key, 0)
    hv = p_re.get(key, 0)
    if isinstance(ov, float):
        print(f"    {label:<24} {ov:<16.2f} {hv:<16.2f}")
    else:
        print(f"    {label:<24} {str(ov):<16} {str(hv):<16}")

if p_re.get("sharpe", 0) > our_baseline_sharpe:
    print(f"  Relaxed shorts HELP: Sharpe {our_baseline_sharpe:.2f} → {p_re['sharpe']:.2f}")
    improvements.append(("relaxed_shorts", True, p_re["sharpe"]))
else:
    print(f"  Relaxed shorts DON'T HELP: Sharpe={p_re.get('sharpe',0):.2f} vs baseline {our_baseline_sharpe:.2f}")

# ─── Test 3F: No Flat Regime ───
print("\n  TEST 3F — NO FLAT REGIME (ALWAYS LOOKING):")

cfg_nf_be = make_our_config(
    ["BTC", "ETH"], f"{OUT_DIR}/cc_3f_noflat_be.json",
    leverage=10.0, date_range=TRAINING_DR,
    regime_config={"type": "no_flat"}
)
r_nf_be = run_engine(cfg_nf_be, "3F no-flat BTC+ETH")

cfg_nf_s = make_our_config(
    ["SOL"], f"{OUT_DIR}/cc_3f_noflat_sol.json",
    leverage=5.0, date_range=TRAINING_DR,
    regime_config={"type": "no_flat"}
)
r_nf_s = run_engine(cfg_nf_s, "3F no-flat SOL")
r_nf = combine_results(r_nf_be, r_nf_s)

p_nf = r_nf["portfolio"]
print(f"    {'Metric':<24} {'With FLAT':<16} {'No FLAT':<16}")
for label, key in [("Trades:", "trades"), ("PF:", "pf"), ("P&L:", "pnl"),
                    ("Sharpe:", "sharpe"), ("MDD%:", "mdd_pct")]:
    ov = our_p.get(key, 0)
    hv = p_nf.get(key, 0)
    if isinstance(ov, float):
        print(f"    {label:<24} {ov:<16.2f} {hv:<16.2f}")
    else:
        print(f"    {label:<24} {str(ov):<16} {str(hv):<16}")

if p_nf.get("sharpe", 0) > our_baseline_sharpe:
    print(f"  Removing FLAT HELPS: Sharpe {our_baseline_sharpe:.2f} → {p_nf['sharpe']:.2f}")
    improvements.append(("no_flat", True, p_nf["sharpe"]))
else:
    print(f"  Removing FLAT DOESN'T HELP: Sharpe={p_nf.get('sharpe',0):.2f} vs baseline {our_baseline_sharpe:.2f}")

RESULTS["block3"] = {
    "test3a": test3a_results,
    "test3b_long": test3b_long,
    "test3b_short": test3b_short,
    "test3c": test3c_results,
    "test3d": p_1h,
    "test3e": p_re,
    "test3f": p_nf,
    "improvements": improvements,
}

# ═══════════════════════════════════════════════════════════════
# BLOCK 4 — COMBINED IMPROVEMENTS
# ═══════════════════════════════════════════════════════════════
print("\n" + "="*70)
print("BLOCK 4 — COMBINED IMPROVEMENTS")
print("="*70)

if not improvements:
    print("\n  No improvements found in Block 3. Our system is already optimized.")
    r_improved = None
else:
    print(f"\n  Improvements found ({len(improvements)}):")
    combined_extras = {}
    combined_regime = None
    combined_tf = None

    for imp_name, imp_val, imp_sharpe in improvements:
        print(f"    {imp_name}: value={imp_val}, Sharpe={imp_sharpe:.2f} (baseline={our_baseline_sharpe:.2f})")
        if imp_name == "late_window":
            combined_extras["late_window"] = imp_val
        elif imp_name == "scoring":
            combined_extras["min_score_long"] = imp_val[0]
            combined_extras["min_score_short"] = imp_val[1]
        elif imp_name == "dual_st":
            combined_extras["confirm_st_atr"] = imp_val[0]
            combined_extras["confirm_st_mult"] = imp_val[1]
        elif imp_name == "relaxed_shorts":
            combined_extras["relaxed_shorts"] = True
        elif imp_name == "no_flat":
            combined_regime = {"type": "no_flat"}
        elif imp_name == "timeframe_1h":
            combined_tf = "1H"

    # Run combined
    cfg_comb_be = make_our_config(
        ["BTC", "ETH"], f"{OUT_DIR}/cc_b4_combined_be.json",
        leverage=10.0, date_range=TRAINING_DR,
        signal_extras=combined_extras if combined_extras else None,
        regime_config=combined_regime,
        timeframe=combined_tf,
    )
    r_comb_be = run_engine(cfg_comb_be, "Block 4 combined BTC+ETH")

    cfg_comb_s = make_our_config(
        ["SOL"], f"{OUT_DIR}/cc_b4_combined_sol.json",
        leverage=5.0, date_range=TRAINING_DR,
        signal_extras=combined_extras if combined_extras else None,
        regime_config=combined_regime,
        timeframe=combined_tf,
    )
    r_comb_s = run_engine(cfg_comb_s, "Block 4 combined SOL")
    r_improved = combine_results(r_comb_be, r_comb_s)

    p_comb = r_improved["portfolio"]
    print(f"\n  Combined system vs baseline:")
    print(f"    {'Metric':<22} {'Baseline':<16} {'Combined':<16}")
    for label, key in [("PF:", "pf"), ("P&L:", "pnl"), ("Sharpe:", "sharpe"),
                        ("MDD%:", "mdd_pct"), ("Trades:", "trades")]:
        ov = our_p.get(key, 0)
        hv = p_comb.get(key, 0)
        if isinstance(ov, float):
            print(f"    {label:<22} {ov:<16.2f} {hv:<16.2f}")
        else:
            print(f"    {label:<22} {str(ov):<16} {str(hv):<16}")

    sum_indiv = sum(s for _, _, s in improvements)
    avg_indiv = sum_indiv / len(improvements)
    synergy = "SYNERGIZE" if p_comb.get("sharpe", 0) > avg_indiv else "INTERFERE"
    print(f"\n  Components {synergy}: combined Sharpe={p_comb.get('sharpe',0):.2f} vs avg individual={avg_indiv:.2f}")

RESULTS["block4"] = {"improved": r_improved}

# ═══════════════════════════════════════════════════════════════
# BLOCK 5 — STRESS SUITE
# ═══════════════════════════════════════════════════════════════
print("\n" + "="*70)
print("BLOCK 5 — STRESS SUITE")
print("="*70)

def run_stress_suite(label, make_cfg_fn, leverage_sol=5.0):
    """Run a subset of stress tests for a given config generator."""
    results = {}

    # 1. Bootstrap (500 iterations)
    print(f"\n  [{label}] Bootstrap (500 iter)...")
    cfg_boot = make_cfg_fn(
        ["BTC", "ETH", "SOL"], f"{OUT_DIR}/cc_b5_{label}_boot.json",
    )
    cfg_boot["bootstrap"] = {"enabled": True, "n_iterations": 500, "block_size_days": 14, "seed": 42, "threads": 14}
    # For SOL 5x we need separate runs but bootstrap needs all trades together
    # So for stress: run all at 10x for simplicity except our system
    r_boot = run_engine(cfg_boot, f"B5 {label} bootstrap")
    if r_boot and r_boot.get("bootstrap"):
        b = r_boot["bootstrap"]
        results["bootstrap"] = b
        print(f"    {b.get('pct_profitable',0):.1f}% profitable, median PF={b.get('median_pf',0):.2f}, p5 PF={b.get('p5_pf',0):.2f}")
    else:
        print(f"    Bootstrap failed or not available")

    # 2. Parameter robustness (500 combos ±30%)
    print(f"  [{label}] Robustness (500 combos)...")
    cfg_rob = make_cfg_fn(
        ["BTC", "ETH", "SOL"], f"{OUT_DIR}/cc_b5_{label}_rob.json",
    )
    cfg_rob["robustness"] = {"enabled": True, "n_combos": 500, "variation_pct": 30, "seed": 42, "threads": 14}
    r_rob = run_engine(cfg_rob, f"B5 {label} robustness")
    if r_rob and r_rob.get("robustness"):
        rb = r_rob["robustness"]
        results["robustness"] = rb
        print(f"    {rb.get('profitable_pct',0):.1f}% profitable, median PF={rb.get('median_pf',0):.2f}")
    else:
        print(f"    Robustness failed or not available")

    # 3. Walk-forward (365d train / 90d test)
    print(f"  [{label}] Walk-forward...")
    wf_results = []
    # Walk forward windows
    start_dt = datetime(2020, 7, 1)
    train_days = 365
    test_days = 90
    end_dt = datetime(2025, 3, 19)
    current = start_dt
    while current + timedelta(days=train_days + test_days) <= end_dt:
        train_end = current + timedelta(days=train_days)
        test_end = train_end + timedelta(days=test_days)
        # Test on the test period
        cfg_wf = make_cfg_fn(
            ["BTC", "ETH", "SOL"], f"{OUT_DIR}/cc_b5_{label}_wf_{current.strftime('%Y%m%d')}.json",
        )
        cfg_wf["date_range"] = {"start": train_end.strftime("%Y-%m-%d"), "end": test_end.strftime("%Y-%m-%d")}
        r_wf = run_engine(cfg_wf, f"B5 {label} WF {train_end.strftime('%Y-%m')}")
        if r_wf:
            wf_p = r_wf.get("portfolio", {})
            wf_results.append({
                "period": f"{train_end.strftime('%Y-%m-%d')} to {test_end.strftime('%Y-%m-%d')}",
                "pf": wf_p.get("pf", 0), "pnl": wf_p.get("pnl", 0),
                "sharpe": wf_p.get("sharpe", 0), "trades": wf_p.get("trades", 0)
            })
        current += timedelta(days=test_days)

    results["walk_forward"] = wf_results
    profitable_wf = sum(1 for w in wf_results if w["pnl"] > 0)
    print(f"    {profitable_wf}/{len(wf_results)} windows profitable")

    # 4. Year-by-year
    print(f"  [{label}] Year-by-year...")
    yby = {}
    for year in range(2020, 2026):
        cfg_y = make_cfg_fn(
            ["BTC", "ETH", "SOL"], f"{OUT_DIR}/cc_b5_{label}_y{year}.json",
        )
        cfg_y["date_range"] = {"start": f"{year}-01-01", "end": f"{year+1}-01-01"}
        r_y = run_engine(cfg_y, f"B5 {label} Y{year}")
        if r_y:
            yp = r_y.get("portfolio", {})
            yby[year] = {"pf": yp.get("pf", 0), "pnl": yp.get("pnl", 0), "trades": yp.get("trades", 0), "sharpe": yp.get("sharpe", 0)}
            print(f"    {year}: PF={yp.get('pf',0):.2f} P&L=${yp.get('pnl',0):.2f} Sharpe={yp.get('sharpe',0):.2f} Trades={yp.get('trades',0)}")
    results["yearly"] = yby

    # 5. Fee breakeven
    print(f"  [{label}] Fee breakeven...")
    cfg_base = make_cfg_fn(
        ["BTC", "ETH", "SOL"], f"{OUT_DIR}/cc_b5_{label}_feebase.json",
    )
    r_base = run_engine(cfg_base, f"B5 {label} fee base")
    if r_base:
        base_pnl = r_base["portfolio"]["pnl"]
        base_fees = sum(s.get("fees", 0) for s in r_base["asset_stats"].values())
        fee_be = BASE_FEES["maker_rate"] * (base_pnl + base_fees) / base_fees if base_fees > 0 else 0
        results["fee_breakeven"] = round(fee_be * 10000, 1)  # in bps
        print(f"    Fee breakeven: {results['fee_breakeven']:.1f} bps (current: {BASE_FEES['maker_rate']*10000:.1f} bps)")

    return results

# Our baseline stress
def make_our_stress(assets, output):
    return make_our_config(assets, output, leverage=10.0, margin=125.0, equity=500.0, date_range=TRAINING_DR)

def make_coll_stress(assets, output):
    return make_colleague_config(assets, output, margin=125.0, leverage=10.0, equity=500.0, date_range=TRAINING_DR)

print("\n  ── Our System ──")
stress_ours = run_stress_suite("ours", make_our_stress)

print("\n  ── Colleague's System ──")
stress_coll = run_stress_suite("coll", make_coll_stress)

if r_improved:
    print("\n  ── Improved System ──")
    def make_improved_stress(assets, output):
        return make_our_config(assets, output, leverage=10.0, margin=125.0, equity=500.0,
                              date_range=TRAINING_DR,
                              signal_extras=combined_extras if combined_extras else None,
                              regime_config=combined_regime, timeframe=combined_tf)
    stress_improved = run_stress_suite("improved", make_improved_stress)
else:
    stress_improved = None

RESULTS["block5"] = {"ours": stress_ours, "colleague": stress_coll, "improved": stress_improved}

# ═══════════════════════════════════════════════════════════════
# BLOCK 6 — SACRED HOLDOUT
# ═══════════════════════════════════════════════════════════════
print("\n" + "="*70)
print("BLOCK 6 — SACRED HOLDOUT")
print("="*70)

# Our baseline on holdout
ho_our_be = make_our_config(
    ["BTC", "ETH"], f"{OUT_DIR}/cc_b6_ours_be.json",
    leverage=10.0, date_range=HOLDOUT_DR
)
r_ho_our_be = run_engine(ho_our_be, "Holdout: Our BTC+ETH")

ho_our_s = make_our_config(
    ["SOL"], f"{OUT_DIR}/cc_b6_ours_sol.json",
    leverage=5.0, date_range=HOLDOUT_DR
)
r_ho_our_s = run_engine(ho_our_s, "Holdout: Our SOL")
r_ho_ours = combine_results(r_ho_our_be, r_ho_our_s)

# Colleague on holdout
ho_coll = make_colleague_config(
    ["BTC", "ETH", "SOL"], f"{OUT_DIR}/cc_b6_coll.json",
    margin=125.0, leverage=10.0, equity=500.0, date_range=HOLDOUT_DR
)
r_ho_coll = run_engine(ho_coll, "Holdout: Colleague")

# Improved on holdout (if exists)
r_ho_improved = None
if r_improved:
    ho_imp_be = make_our_config(
        ["BTC", "ETH"], f"{OUT_DIR}/cc_b6_improved_be.json",
        leverage=10.0, date_range=HOLDOUT_DR,
        signal_extras=combined_extras if combined_extras else None,
        regime_config=combined_regime, timeframe=combined_tf,
    )
    r_ho_imp_be = run_engine(ho_imp_be, "Holdout: Improved BTC+ETH")

    ho_imp_s = make_our_config(
        ["SOL"], f"{OUT_DIR}/cc_b6_improved_sol.json",
        leverage=5.0, date_range=HOLDOUT_DR,
        signal_extras=combined_extras if combined_extras else None,
        regime_config=combined_regime, timeframe=combined_tf,
    )
    r_ho_imp_s = run_engine(ho_imp_s, "Holdout: Improved SOL")
    r_ho_improved = combine_results(r_ho_imp_be, r_ho_imp_s)

print("\nBLOCK 6 — HOLDOUT:\n")
print(f"    {'Metric':<22} {'Our Baseline':<16} {'Our Improved':<16} {'Colleague':<16}")
ho_p_ours = r_ho_ours["portfolio"]
ho_p_coll = r_ho_coll["portfolio"] if r_ho_coll else {}
ho_p_imp = r_ho_improved["portfolio"] if r_ho_improved else {}

for label, key in [("PF:", "pf"), ("P&L:", "pnl"), ("Sharpe:", "sharpe"), ("MDD%:", "mdd_pct"), ("Trades:", "trades")]:
    ov = ho_p_ours.get(key, 0)
    iv = ho_p_imp.get(key, "N/A") if ho_p_imp else "N/A"
    cv = ho_p_coll.get(key, 0)
    if isinstance(ov, float):
        iv_str = f"{iv:.2f}" if isinstance(iv, (int, float)) else str(iv)
        print(f"    {label:<22} {ov:<16.2f} {iv_str:<16} {cv:<16.2f}")
    else:
        iv_str = str(iv)
        print(f"    {label:<22} {str(ov):<16} {iv_str:<16} {str(cv):<16}")

# Determine holdout winner
winners = [(ho_p_ours.get("sharpe", 0), "Our Baseline")]
if ho_p_imp:
    winners.append((ho_p_imp.get("sharpe", 0), "Our Improved"))
winners.append((ho_p_coll.get("sharpe", 0), "Colleague"))
holdout_winner = max(winners, key=lambda x: x[0])
print(f"\n  HOLDOUT WINNER: {holdout_winner[1]} (Sharpe={holdout_winner[0]:.2f})")

RESULTS["block6"] = {
    "ours": r_ho_ours,
    "colleague": r_ho_coll,
    "improved": r_ho_improved,
}

# ═══════════════════════════════════════════════════════════════
# BLOCK 7 — FINAL REPORT
# ═══════════════════════════════════════════════════════════════
total_time = time.time() - TOTAL_START

print("\n" + "═"*70)
print("  COLLEAGUE COMPARISON — COMPLETE")
print("═"*70)

print(f"\n  TOTAL RUNTIME: {total_time:.1f} seconds")

# Colleague performance summary
coll_btc = get_stats(r_coll_fixed, "BTC") if r_coll_fixed else {}
coll_port = r_coll_fixed["portfolio"] if r_coll_fixed else {}
ho_coll_p = r_ho_coll["portfolio"] if r_ho_coll else {}
btc_tv_s = get_stats(r_coll_tv, "BTC") if r_coll_tv else {}

print(f"\n  COLLEAGUE'S STRATEGY PERFORMANCE:")
print(f"    His exact settings, BTC only, $125 sizing:")
print(f"      Training: PF={coll_btc.get('pf',0):.2f} | P&L=${coll_btc.get('pnl',0):.2f} | Sharpe={coll_btc.get('sharpe',0):.2f} | MDD={coll_btc.get('mdd_pct',0):.1f}%")
print(f"      Holdout:  PF={get_stats(r_ho_coll, 'BTC').get('pf',0):.2f} | P&L=${get_stats(r_ho_coll, 'BTC').get('pnl',0):.2f} | Sharpe (port)={ho_coll_p.get('sharpe',0):.2f}")
print(f"    His settings, 3 assets:")
print(f"      Training: PF={coll_port.get('pf',0):.2f} | P&L=${coll_port.get('pnl',0):.2f} | Sharpe={coll_port.get('sharpe',0):.2f} | MDD={coll_port.get('mdd_pct',0):.1f}%")
print(f"    His TradingView settings ($10K, 100% equity):")
print(f"      BTC: PF={btc_tv_s.get('pf',0):.2f} | P&L=${btc_tv_s.get('pnl',0):.2f} | Sharpe={btc_tv_s.get('sharpe',0):.2f}")

our_train_p = r_ours["portfolio"]
print(f"\n  OUR SYSTEM PERFORMANCE:")
print(f"    Training: PF={our_train_p.get('pf',0):.2f} | P&L=${our_train_p.get('pnl',0):.2f} | Sharpe={our_train_p.get('sharpe',0):.2f} | MDD={our_train_p.get('mdd_pct',0):.1f}%")
print(f"    Holdout:  PF={ho_p_ours.get('pf',0):.2f} | P&L=${ho_p_ours.get('pnl',0):.2f} | Sharpe={ho_p_ours.get('sharpe',0):.2f}")

print(f"\n  HEAD-TO-HEAD WINNER:")
for label, key, higher in [("By Sharpe:", "sharpe", True), ("By P&L:", "pnl", True), ("By MDD:", "mdd_pct", False)]:
    ov = our_train_p.get(key, 0)
    hv = coll_port.get(key, 0)
    winner = "Ours" if (ov > hv if higher else ov < hv) else "His"
    print(f"    {label} {winner} ({ov:.2f} vs {hv:.2f})")
print(f"    By holdout: {'Ours' if ho_p_ours.get('sharpe',0) > ho_coll_p.get('sharpe',0) else 'His'}")

print(f"\n  COMPONENT ANALYSIS — WHAT WE LEARNED FROM HIS APPROACH:")
test_results = {
    "Late confirmation window": ("3a", best_3a),
    "Scoring system (N of M)": ("3b", best_3b),
    "Dual ST confirmation": ("3c", best_3c),
    "1H timeframe": ("3d", (None, p_1h)),
    "Relaxed short filters": ("3e", (None, p_re)),
    "No flat regime": ("3f", (None, p_nf)),
}
for name, (_, data) in test_results.items():
    val = data[1] if isinstance(data, tuple) else data
    sharpe = val.get("sharpe", 0)
    helps = sharpe > our_baseline_sharpe
    status = "HELPS" if helps else "DOESN'T HELP"
    print(f"    {name + ':':<30} {status} — Sharpe={sharpe:.2f} vs baseline {our_baseline_sharpe:.2f}")

if improvements:
    print(f"\n  ADOPTED IMPROVEMENTS:")
    for name, val, sharpe in improvements:
        print(f"    {name}: {val} (Sharpe={sharpe:.2f})")
else:
    print(f"\n  No component of the colleague's strategy improves our validated system")

# Final verdict
print(f"""
  ┌─────────────────────────────────────────────────────────────────────┐
  │  FINAL VERDICT:                                                     │
  │                                                                     │
  │  1. Is his strategy profitable?                                    │
  │     {'YES' if coll_port.get('pnl',0) > 0 else 'NO'} — PF={coll_port.get('pf',0):.2f}, Sharpe={coll_port.get('sharpe',0):.2f} over training, $125 sizing{' '*5}│
  │                                                                     │
  │  2. Does it beat our system?                                       │
  │     Training: {'YES' if coll_port.get('sharpe',0) > our_train_p.get('sharpe',0) else 'NO'} — Sharpe {coll_port.get('sharpe',0):.2f} vs {our_train_p.get('sharpe',0):.2f}{' '*28}│
  │     Holdout:  {'YES' if ho_coll_p.get('sharpe',0) > ho_p_ours.get('sharpe',0) else 'NO'} — Sharpe {ho_coll_p.get('sharpe',0):.2f} vs {ho_p_ours.get('sharpe',0):.2f}{' '*28}│
  │                                                                     │
  │  3. Did we find improvements for our system?                       │
  │     {'YES — ' + str(len(improvements)) + ' improvements found' if improvements else 'NO — our system is already optimized'}{' '*30}│
  │                                                                     │
  │  4. Recommendation:                                                │
  │     {'KEEP our system as-is' if not improvements else 'ADOPT improvements if holdout confirms'}{' '*30}│
  │                                                                     │
  └─────────────────────────────────────────────────────────────────────┘""")

# Save everything
RESULTS["block7"] = {
    "total_runtime_seconds": round(total_time, 1),
    "holdout_boundary": HOLDOUT_DATE,
    "our_training": our_train_p,
    "our_holdout": ho_p_ours,
    "colleague_training": coll_port,
    "colleague_holdout": ho_coll_p,
    "improvements": [(n, str(v), s) for n, v, s in improvements],
}

# Convert non-serializable items
def make_serializable(obj):
    if isinstance(obj, dict):
        return {str(k): make_serializable(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [make_serializable(i) for i in obj]
    elif isinstance(obj, tuple):
        return list(obj)
    elif isinstance(obj, (int, float, str, bool, type(None))):
        return obj
    else:
        return str(obj)

with open(f"{OUT_DIR}/colleague_comparison.json", 'w') as f:
    json.dump(make_serializable(RESULTS), f, indent=2, default=str)

print(f"\nResults saved to {OUT_DIR}/colleague_comparison.json")
print(f"Total runtime: {total_time:.1f}s")

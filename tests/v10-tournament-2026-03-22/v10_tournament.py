#!/usr/bin/env python3
"""
Colleague V10 "Adaptive + ZLEMA" — Complete Backtest Tournament
All 13 blocks. Data only. No deployment.
"""
import json, subprocess, os, copy, math, sys, time
from collections import defaultdict, Counter
from datetime import datetime, timedelta

ENGINE = "/home/ubuntu/hypertrader-engine-v4/target/release/hypertrader-engine"
DATA_DIR = "/opt/hypertrader/addons/backtest-data"
OUT_DIR = "/tmp/discovery"
os.makedirs(OUT_DIR, exist_ok=True)

HOLDOUT_DATE = "2025-03-19"
ASSETS = ["BTC", "ETH", "SOL"]
RESULTS = {}
T0 = time.time()

# =============================================================================
# HELPERS
# =============================================================================

def v10_params(tf="30m", overrides=None):
    """Generate v10 strategy params with optional overrides."""
    p = {
        "timeframe": tf,
        "atr_period": 10, "base_mult": 6.0, "trend_mult": 4.0, "range_mult": 8.0,
        "adx_adapt_thresh": 25.0, "slow_atr_period": 20, "slow_mult": 8.0,
        "use_dual_st_buys": True, "use_dual_st_sells": True,
        "cooldown": 2, "late_window": 1, "min_score": 6,
        "use_rsi": True, "rsi_period": 14, "rsi_buy_max": 70, "rsi_sell_min": 30,
        "use_zlema": True, "zlema_period": 200,
        "use_volume": True, "vol_sma_period": 20, "vol_multiplier": 1.0,
        "use_adx_filter": True, "adx_period": 14, "adx_minimum": 25.0,
        "use_squeeze": True, "exit_on_raw_flip": True,
        "use_ema_atr": True, "longs_only": False,
    }
    if overrides:
        p.update(overrides)
    return p

def make_config(assets, tf="30m", overrides=None, date_range=None,
                fee_rate=0.0006, slippage=0.0005, funding=0.0001,
                margin=125.0, leverage=10.0, equity=500.0,
                friction=None, robustness=None, bootstrap=None,
                output_path="/tmp/_v10_tmp.json"):
    """Generate a complete engine config for v10."""
    sp = v10_params(tf, overrides)
    cfg = {
        "assets": assets,
        "data_dir": DATA_DIR,
        "mode": "baseline",
        "timeframe": tf,
        "params": {
            "ema200_period": 200, "ema50_period": 50, "ema50_rising_lookback": 5,
            "st_4h_atr_period": 10, "st_4h_multiplier": 3.0,
            "st_15m_atr_period": 10, "st_15m_multiplier": 2.0,
            "near_band_pct": 0.005, "rsi_period": 14, "rsi_threshold": 45.0,
            "rsi_lookback": 2, "ema_fast": 21, "ema_slow": 55,
            "vol_mult": 2.0, "vol_sma_period": 20, "warmup": 300,
        },
        "strategy": {
            "long_entry": {"type": "adaptive_zlema_st", "params": sp},
            "short_entry": {"type": "adaptive_zlema_st_short", "params": {"timeframe": tf}},
            "exit": {"type": "current"},
        },
        "regime_config": {"type": "none"},
        "sizing": {"type": "flat", "margin": margin, "leverage": leverage, "starting_equity": equity},
        "fees": {"maker_rate": fee_rate, "slippage": slippage, "funding_rate_per_8h": funding},
        "output_path": output_path,
    }
    if date_range:
        cfg["date_range"] = date_range
    if friction:
        cfg["friction"] = friction
    if robustness:
        cfg["robustness"] = robustness
        cfg["mode"] = "baseline"  # robustness is a flag, not a mode
    if bootstrap:
        cfg["bootstrap"] = bootstrap
    return cfg

def run(cfg, label=""):
    """Write config, run engine, return parsed results."""
    cfg_path = cfg["output_path"].replace(".json", "_cfg.json")
    with open(cfg_path, 'w') as f:
        json.dump(cfg, f)
    try:
        r = subprocess.run([ENGINE, cfg_path], capture_output=True, text=True, timeout=300)
        if r.returncode != 0:
            print(f"  [ERROR {label}] {r.stderr[-200:]}", file=sys.stderr)
            return None
    except Exception as e:
        print(f"  [ERROR {label}] {e}", file=sys.stderr)
        return None
    try:
        with open(cfg["output_path"]) as f:
            return json.load(f)
    except:
        return None

def ps(result, key="portfolio"):
    """Extract portfolio stats dict."""
    if not result: return {}
    return result.get(key, {})

def ast(result, sym):
    """Extract per-asset stats."""
    if not result: return {}
    return result.get("asset_stats", {}).get(sym, {})

def trades(result):
    """Get trade log."""
    if not result: return []
    return result.get("trade_log", [])

def fmt(v, d=2):
    if v is None or v == "": return "N/A"
    if isinstance(v, float): return f"{v:.{d}f}"
    return str(v)

def fixed_ratio_equity(trade_log, starting=1000, delta=1000, base_margin=125, leverage=10, cap=4):
    """Recompute equity with Fixed Ratio sizing."""
    equity = starting
    eq_curve = [equity]
    for t in trade_log:
        N = int(0.5 + 0.5 * math.sqrt(1 + 8 * max(equity - starting, 0) / delta))
        N = min(max(N, 1), cap)
        scale = N
        pnl = t["pnl"] * scale
        equity += pnl
        eq_curve.append(equity)
    peak = starting
    max_dd = 0
    for e in eq_curve:
        peak = max(peak, e)
        dd = (peak - e) / peak * 100 if peak > 0 else 0
        max_dd = max(max_dd, dd)
    total_pnl = equity - starting
    return {"final_equity": equity, "pnl": total_pnl, "mdd_pct": max_dd, "trades": len(trade_log)}

def pct_equity_sim(trade_log, starting=100000, fraction=0.95, base_margin=125, leverage=10):
    """Recompute equity with percent-of-equity sizing."""
    equity = starting
    base_notional = base_margin * leverage  # 1250
    eq_curve = [equity]
    for t in trade_log:
        position_value = fraction * equity
        scale = position_value / base_notional if base_notional > 0 else 1
        pnl = t["pnl"] * scale
        equity += pnl
        equity = max(equity, 0)  # can't go below 0
        eq_curve.append(equity)
    peak = starting
    max_dd_pct = 0
    max_dd_usd = 0
    for e in eq_curve:
        peak = max(peak, e)
        dd_pct = (peak - e) / peak * 100 if peak > 0 else 0
        dd_usd = peak - e
        max_dd_pct = max(max_dd_pct, dd_pct)
        max_dd_usd = max(max_dd_usd, dd_usd)
    return {"final_equity": equity, "pnl": equity - starting, "mdd_pct": max_dd_pct,
            "mdd_usd": max_dd_usd, "trades": len(trade_log)}

def trade_stats(tlog):
    """Compute stats from a trade log."""
    if not tlog: return {"trades":0,"pf":0,"pnl":0,"sharpe":0,"wr":0}
    longs = [t for t in tlog if t.get("direction") == "long"]
    shorts = [t for t in tlog if t.get("direction") == "short"]
    gross_p = sum(t["pnl"] for t in tlog if t["pnl"] > 0)
    gross_l = abs(sum(t["pnl"] for t in tlog if t["pnl"] < 0))
    pf = gross_p / gross_l if gross_l > 0 else 999
    pnl = sum(t["pnl"] for t in tlog)
    wins = sum(1 for t in tlog if t["pnl"] > 0)
    wr = wins / len(tlog) * 100 if tlog else 0
    fees = sum(t.get("fees",0) for t in tlog)
    funding = sum(t.get("funding",0) for t in tlog)
    avg_hold = sum(t.get("bars_held",0) for t in tlog) / len(tlog) if tlog else 0
    return {"trades": len(tlog), "longs": len(longs), "shorts": len(shorts),
            "pf": round(pf,2), "pnl": round(pnl,2), "wr": round(wr,1),
            "fees": round(fees,2), "funding": round(funding,2), "avg_hold": round(avg_hold,1)}

def sharpe_from_trades(tlog):
    """Simple monthly Sharpe approximation."""
    if len(tlog) < 2: return 0
    monthly = defaultdict(float)
    for t in tlog:
        m = t.get("exit_ts","")[:7]
        monthly[m] += t["pnl"]
    rets = list(monthly.values())
    if len(rets) < 2: return 0
    mu = sum(rets)/len(rets)
    var = sum((r-mu)**2 for r in rets)/len(rets)
    std = math.sqrt(var) if var > 0 else 0.001
    return round(mu/std * math.sqrt(12), 2)

def count_flat_exits(tlog):
    """Count exits where the reason was ST flip (went flat, not reversed)."""
    # Flat exits: a trade closes, and the next trade (if any) doesn't start at the same bar
    flat = 0
    for i, t in enumerate(tlog):
        if t.get("exit_reason_detail","") and "flip" in t.get("exit_reason_detail","").lower():
            flat += 1
    return flat

print("=" * 72)
print("  COLLEAGUE V10 'ADAPTIVE + ZLEMA' — COMPLETE BACKTEST TOURNAMENT")
print("=" * 72)
print()

# =============================================================================
# BLOCK 0 — HIS EXACT SETTINGS
# =============================================================================
print("BLOCK 0 — HIS EXACT SETTINGS, RAW RESULTS")
print("-" * 60)

# 0A: BTC, 30m
out_0a = os.path.join(OUT_DIR, "v10_b0a.json")
cfg_0a = make_config(["BTC"], tf="30m", output_path=out_0a)
r0a = run(cfg_0a, "B0A-BTC")
p0a = ps(r0a)
t0a = trades(r0a)
ts0a = trade_stats(t0a)

# Also compute flat exits
flat_exits = sum(1 for i in range(len(t0a)-1)
    if t0a[i]["exit_bar"] < t0a[i+1]["entry_bar"] - 1) if len(t0a) > 1 else 0

# Time in market
total_bars_held = sum(t.get("bars_held",0) for t in t0a)
total_bars = ast(r0a, "BTC").get("n_bars", 1)
time_in_mkt = total_bars_held / total_bars * 100 if total_bars > 0 else 0

# Fixed Ratio
fr0a = fixed_ratio_equity(t0a)
# 95% equity
pe0a = pct_equity_sim(t0a)

print(f"""
BLOCK 0A — V10 EXACT SETTINGS (BTC, 30m):

  $125 FLAT SIZING (pure strategy comparison):
    Trades: {ts0a['trades']} (longs: {ts0a['longs']}, shorts: {ts0a['shorts']}, flat exits: ~{flat_exits})
    PF: {ts0a['pf']} | P&L: ${ts0a['pnl']} | Sharpe: {p0a.get('sharpe','?')} | MDD%: {p0a.get('mdd_pct','?')}%
    Win rate: {ts0a['wr']}%
    Avg hold: {ts0a['avg_hold']} bars ({round(ts0a['avg_hold']*0.5,1)} hours)
    Total fees: ${ts0a['fees']} | Total funding: ${ts0a['funding']}
    % time in market: {round(time_in_mkt,1)}%

  FIXED RATIO d=$1,000 ($1,000 start — our actual sizing):
    Trades: {fr0a['trades']} | PF: {ts0a['pf']} | P&L: ${round(fr0a['pnl'],2)} | Final equity: ${round(fr0a['final_equity'],2)}
    MDD%: {round(fr0a['mdd_pct'],1)}%

  95% EQUITY SIZING ($100K initial — his TradingView settings):
    Trades: {pe0a['trades']} | PF: {ts0a['pf']} | P&L: ${round(pe0a['pnl'],2)} | Final equity: ${round(pe0a['final_equity'],2)}
    MDD%: {round(pe0a['mdd_pct'],1)}% | MDD$: ${round(pe0a['mdd_usd'],2)}

  HIS CLAIMED STATS: 630% / 2Y, Sharpe 1.64, 32 trades
  OUR 95% EQUITY RETURN: {round((pe0a['final_equity']/100000 - 1)*100,1)}% over full dataset
""")

# 0B: All assets, 30m
out_0b = os.path.join(OUT_DIR, "v10_b0b.json")
cfg_0b = make_config(ASSETS, tf="30m", output_path=out_0b)
r0b = run(cfg_0b, "B0B")
print("BLOCK 0B — V10 ON OTHER ASSETS (30m):\n")
print(f"  {'Asset':<6}{'PF':>6}{'P&L':>10}{'Sharpe':>8}{'MDD%':>7}{'Trades':>8}{'WR%':>6}{'Fees':>8}{'Funding':>9}")
for sym in ASSETS + ["PORT"]:
    if sym == "PORT":
        s = ps(r0b)
        tl = trades(r0b)
    else:
        s = ast(r0b, sym)
        tl = [t for t in trades(r0b) if t.get("asset") == sym]
    ts_ = trade_stats(tl)
    print(f"  {sym:<6}{s.get('pf',0):>6.2f}{s.get('pnl',0):>10.2f}{s.get('sharpe',0):>8.2f}"
          f"{s.get('mdd_pct',0):>6.1f}%{ts_['trades']:>7}{ts_['wr']:>6.1f}{ts_['fees']:>8.2f}{ts_['funding']:>9.2f}")

multi_asset = sum(1 for sym in ASSETS if ast(r0b, sym).get("pnl", 0) > 0) >= 2
print(f"\n  Works on 2+ assets? {'YES' if multi_asset else 'NO'}\n")

# 0C: Alternative timeframes
print("BLOCK 0C — V10 ON ALTERNATIVE TIMEFRAMES:\n")
print(f"  {'TF':<6}{'Asset':<6}{'PF':>6}{'P&L':>10}{'Sharpe':>8}{'Trades':>8}")
tf_results = {}
for tf in ["15m", "30m", "1H"]:
    out_tf = os.path.join(OUT_DIR, f"v10_b0c_{tf}.json")
    if tf == "30m":
        r_tf = r0b  # reuse
    else:
        cfg_tf = make_config(ASSETS, tf=tf, output_path=out_tf)
        r_tf = run(cfg_tf, f"B0C-{tf}")
    tf_results[tf] = r_tf
    for sym in ASSETS:
        s = ast(r_tf, sym)
        print(f"  {tf:<6}{sym:<6}{s.get('pf',0):>6.2f}{s.get('pnl',0):>10.2f}{s.get('sharpe',0):>8.2f}{s.get('trades',0):>8}")

# Find best TF by portfolio Sharpe
best_tf = max(tf_results, key=lambda tf: ps(tf_results[tf]).get("sharpe", 0))
print(f"\n  Best timeframe: {best_tf} (by portfolio Sharpe: {ps(tf_results[best_tf]).get('sharpe',0)})\n")

# 0D: Year by year (best TF, $125 flat, portfolio)
print(f"BLOCK 0D — YEAR BY YEAR (best TF={best_tf}):\n")
best_r = tf_results[best_tf]
best_trades = trades(best_r)

years = sorted(set(t.get("entry_ts","")[:4] for t in best_trades))
print(f"  {'Year':<6}{'BTC P&L':>10}{'ETH P&L':>10}{'SOL P&L':>10}{'Portfolio':>10}{'Long P&L':>10}{'Short P&L':>10}")
total_long_pnl = 0
total_short_pnl = 0
losing_years = []
for yr in years:
    yr_trades = [t for t in best_trades if t.get("entry_ts","")[:4] == yr]
    btc_pnl = sum(t["pnl"] for t in yr_trades if t.get("asset") == "BTC")
    eth_pnl = sum(t["pnl"] for t in yr_trades if t.get("asset") == "ETH")
    sol_pnl = sum(t["pnl"] for t in yr_trades if t.get("asset") == "SOL")
    port_pnl = sum(t["pnl"] for t in yr_trades)
    long_pnl = sum(t["pnl"] for t in yr_trades if t.get("direction") == "long")
    short_pnl = sum(t["pnl"] for t in yr_trades if t.get("direction") == "short")
    total_long_pnl += long_pnl
    total_short_pnl += short_pnl
    if port_pnl < 0: losing_years.append(yr)
    print(f"  {yr:<6}{btc_pnl:>10.2f}{eth_pnl:>10.2f}{sol_pnl:>10.2f}{port_pnl:>10.2f}{long_pnl:>10.2f}{short_pnl:>10.2f}")

total_pnl = total_long_pnl + total_short_pnl
long_pct = total_long_pnl / total_pnl * 100 if total_pnl != 0 else 50
print(f"\n  Profitable every year? {'YES' if not losing_years else 'NO — lost: ' + ', '.join(losing_years)}")
print(f"  Long vs short contribution: {round(long_pct,1)}% long, {round(100-long_pct,1)}% short\n")

# =============================================================================
# BLOCK 1 — HEAD-TO-HEAD
# =============================================================================
print("=" * 60)
print("BLOCK 1 — HEAD-TO-HEAD VS OUR SYSTEM")
print("-" * 60)

# Run our system on training period
out_ours = os.path.join(OUT_DIR, "v10_b1_ours.json")
our_cfg_str = open("/tmp/discovery/rust_baseline_config.json").read()
our_cfg = json.loads(our_cfg_str)
our_cfg["output_path"] = out_ours
our_cfg["date_range"] = {"start": "2020-01-01", "end": HOLDOUT_DATE}
with open(out_ours.replace(".json", "_cfg.json"), 'w') as f:
    json.dump(our_cfg, f)
r_ours = None
try:
    subprocess.run([ENGINE, out_ours.replace(".json", "_cfg.json")], capture_output=True, timeout=60)
    with open(out_ours) as f:
        r_ours = json.load(f)
except: pass

# Run v10 on training period (best TF)
out_v10_train = os.path.join(OUT_DIR, "v10_b1_his.json")
cfg_v10_train = make_config(ASSETS, tf=best_tf, date_range={"start": "2020-01-01", "end": HOLDOUT_DATE},
                             output_path=out_v10_train)
r_v10_train = run(cfg_v10_train, "B1-v10-train")

p_ours = ps(r_ours)
p_his = ps(r_v10_train)
t_ours = trades(r_ours)
t_his = trades(r_v10_train)
ts_ours = trade_stats(t_ours)
ts_his = trade_stats(t_his)

# Fixed Ratio for both
fr_ours = fixed_ratio_equity(t_ours)
fr_his = fixed_ratio_equity(t_his)

print(f"""
  $125 FLAT (pure strategy comparison):
                              Our System (long-only)    His v10 ({best_tf})
  P&L:                        ${p_ours.get('pnl',0):<24.2f}${p_his.get('pnl',0):.2f}
  PF:                         {p_ours.get('pf',0):<24.2f}{p_his.get('pf',0):.2f}
  Sharpe:                     {p_ours.get('sharpe',0):<24.2f}{p_his.get('sharpe',0):.2f}
  MDD%:                       {p_ours.get('mdd_pct',0):<23.1f}%{p_his.get('mdd_pct',0):.1f}%
  Trades:                     {ts_ours['trades']:<24}{ts_his['trades']}

  FIXED RATIO d=$1,000 ($1,000 start — realistic):
                              Our System (long-only)    His v10
  Final equity:               ${fr_ours['final_equity']:<23.2f}${fr_his['final_equity']:.2f}
  P&L:                        ${fr_ours['pnl']:<23.2f}${fr_his['pnl']:.2f}
  Win rate:                   {ts_ours['wr']:<23.1f}%{ts_his['wr']:.1f}%
  Total fees:                 ${ts_ours['fees']:<23.2f}${ts_his['fees']:.2f}
  Total funding:              ${ts_ours['funding']:<23.2f}${ts_his['funding']:.2f}
""")

# Per-asset
print("  PER-ASSET:")
for sym in ASSETS:
    so = ast(r_ours, sym)
    sh = ast(r_v10_train, sym)
    winner = "Ours" if so.get("pnl",0) > sh.get("pnl",0) else "His"
    print(f"    {sym}: Our PF={so.get('pf',0):.2f} P&L=${so.get('pnl',0):.2f} | His PF={sh.get('pf',0):.2f} P&L=${sh.get('pnl',0):.2f} | Winner: {winner}")

# Year by year
print(f"\n  YEAR-BY-YEAR:")
print(f"    {'Year':<6}{'Our P&L':>10}{'His P&L':>10}  Winner")
all_years = sorted(set(t.get("entry_ts","")[:4] for t in t_ours + t_his))
for yr in all_years:
    op = sum(t["pnl"] for t in t_ours if t.get("entry_ts","")[:4] == yr)
    hp = sum(t["pnl"] for t in t_his if t.get("entry_ts","")[:4] == yr)
    w = "Ours" if op > hp else "His"
    print(f"    {yr:<6}{op:>10.2f}{hp:>10.2f}  {w}")

sharpe_winner = "Ours" if p_ours.get("sharpe",0) > p_his.get("sharpe",0) else "His"
pnl_winner = "Ours" if p_ours.get("pnl",0) > p_his.get("pnl",0) else "His"
print(f"\n  OVERALL WINNER BY SHARPE: {sharpe_winner}")
print(f"  OVERALL WINNER BY P&L: {pnl_winner}\n")

# =============================================================================
# BLOCK 2 — CRASH EVENTS
# =============================================================================
print("=" * 60)
print("BLOCK 2 — CRASH EVENT ANALYSIS")
print("-" * 60)

crash_events = [
    ("COVID Mar 2020", "2020-03-01", "2020-03-31"),
    ("LUNA May 2022", "2022-05-01", "2022-05-31"),
    ("FTX Nov 2022", "2022-11-01", "2022-11-30"),
    ("Aug 2024 Flash", "2024-08-01", "2024-08-31"),
]

# Use full-period BTC trades on best TF
btc_trades = [t for t in trades(tf_results[best_tf]) if t.get("asset") == "BTC"]
for event_name, start, end in crash_events:
    event_trades = [t for t in btc_trades
                    if (t.get("entry_ts","")[:10] >= start and t.get("entry_ts","")[:10] <= end) or
                       (t.get("exit_ts","")[:10] >= start and t.get("exit_ts","")[:10] <= end and
                        t.get("entry_ts","")[:10] < end)]
    total_pnl = sum(t["pnl"] for t in event_trades)
    print(f"\n  {event_name}:")
    if event_trades:
        for t in event_trades:
            print(f"    {t.get('direction','?'):>5} | Entry: {t.get('entry_ts','')[:16]} | Exit: {t.get('exit_ts','')[:16]} | P&L: ${t['pnl']:.2f} | Bars: {t.get('bars_held',0)}")
        print(f"    Total event P&L: ${total_pnl:.2f}")
    else:
        # Check if in position from before
        pre_trades = [t for t in btc_trades if t.get("entry_ts","")[:10] < start and t.get("exit_ts","")[:10] >= start]
        if pre_trades:
            for t in pre_trades:
                print(f"    In {t.get('direction','?')} from {t.get('entry_ts','')[:16]} (exited {t.get('exit_ts','')[:16]}, P&L: ${t['pnl']:.2f})")
        else:
            print(f"    No trades during this event (was flat)")

crash_total = sum(sum(t["pnl"] for t in btc_trades
    if (t.get("entry_ts","")[:10] >= s and t.get("entry_ts","")[:10] <= e) or
       (t.get("exit_ts","")[:10] >= s and t.get("exit_ts","")[:10] <= e and t.get("entry_ts","")[:10] < e))
    for _, s, e in crash_events)
print(f"\n  CRASH SUMMARY: Total crash P&L: ${crash_total:.2f}")

# =============================================================================
# BLOCK 3 — COMPONENT ANALYSIS
# =============================================================================
print("\n" + "=" * 60)
print("BLOCK 3 — COMPONENT CONTRIBUTION")
print("-" * 60)

component_variants = [
    ("Full v10 (all features)", {}),
    ("No adaptive mult (fixed 6.0)", {"trend_mult": 6.0, "range_mult": 6.0}),
    ("No ZLEMA (disable EMA filter)", {"use_zlema": False}),
    ("No squeeze filter", {"use_squeeze": False}),
    ("No ADX filter", {"use_adx_filter": False}),
    ("No dual ST confirmation", {"use_dual_st_buys": False, "use_dual_st_sells": False}),
    ("No RSI filter", {"use_rsi": False}),
    ("No volume filter", {"use_volume": False}),
    ("EMA-ATR -> RMA-ATR", {"use_ema_atr": False}),
    ("No exit on raw flip", {"exit_on_raw_flip": False}),
    ("Min score 4 instead of 6", {"min_score": 4}),
    ("Min score 5 instead of 6", {"min_score": 5}),
    ("Longs only (no shorts)", {"longs_only": True}),
]

print(f"\n  {'Config':<34}{'PF':>6}{'P&L':>10}{'Sharpe':>8}{'Trades':>8}  Change")
baseline_sharpe = None
for name, ov in component_variants:
    out_c = os.path.join(OUT_DIR, f"v10_b3_{name[:20].replace(' ','_')}.json")
    cfg_c = make_config(ASSETS, tf=best_tf, date_range={"start": "2020-01-01", "end": HOLDOUT_DATE},
                         overrides=ov, output_path=out_c)
    r_c = run(cfg_c, f"B3-{name[:15]}")
    p_c = ps(r_c)
    if baseline_sharpe is None:
        baseline_sharpe = p_c.get("sharpe", 0)
    change = p_c.get("sharpe",0) - baseline_sharpe if baseline_sharpe else 0
    chg_str = "baseline" if name.startswith("Full") else (f"+{change:.2f}" if change >= 0 else f"{change:.2f}")
    print(f"  {name:<34}{p_c.get('pf',0):>6.2f}{p_c.get('pnl',0):>10.2f}{p_c.get('sharpe',0):>8.2f}{p_c.get('trades',0):>8}  {chg_str}")

# =============================================================================
# BLOCK 4 — TRADE QUALITY
# =============================================================================
print("\n" + "=" * 60)
print("BLOCK 4 — TRADE QUALITY ANALYSIS")
print("-" * 60)

best_train_trades = [t for t in trades(r_v10_train)]
buckets = [(1,4), (5,12), (13,24), (25,48), (49,96), (97, 99999)]
print(f"\n  {'Duration':<14}{'Trades':>7}{'PF':>7}{'Avg P&L':>10}{'Total P&L':>11}  Assessment")
for lo, hi in buckets:
    bt = [t for t in best_train_trades if lo <= t.get("bars_held",0) <= hi]
    if not bt:
        print(f"  {lo}-{hi if hi<99999 else '+':<10}{'bars':<4}{0:>7}{0:>7.2f}{0:>10.2f}{0:>11.2f}")
        continue
    gp = sum(t["pnl"] for t in bt if t["pnl"] > 0)
    gl = abs(sum(t["pnl"] for t in bt if t["pnl"] < 0))
    pf = gp/gl if gl > 0 else 999
    avg = sum(t["pnl"] for t in bt)/len(bt)
    tot = sum(t["pnl"] for t in bt)
    label = "whipsaw?" if lo <= 4 and pf < 1 else ""
    lbl = f"{lo}-{hi if hi<99999 else '+'} bars"
    print(f"  {lbl:<14}{len(bt):>7}{pf:>7.2f}{avg:>10.2f}{tot:>11.2f}  {label}")

whipsaw = [t for t in best_train_trades if t.get("bars_held",0) < 8 and t["pnl"] < 0]
whipsaw_cost = sum(t["pnl"] for t in whipsaw)
non_whipsaw_pnl = sum(t["pnl"] for t in best_train_trades) - whipsaw_cost
print(f"\n  Whipsaw trades (< 8 bars AND lost): {len(whipsaw)} ({round(len(whipsaw)/max(len(best_train_trades),1)*100,1)}% of all trades)")
print(f"  Whipsaw cost: ${whipsaw_cost:.2f}")
print(f"  Non-whipsaw P&L: ${non_whipsaw_pnl:.2f}")

longs = [t for t in best_train_trades if t.get("direction") == "long"]
shorts = [t for t in best_train_trades if t.get("direction") == "short"]
for label, tl in [("LONG", longs), ("SHORT", shorts)]:
    ts_ = trade_stats(tl)
    print(f"\n  {label} TRADES: Count: {ts_['trades']} | PF: {ts_['pf']} | P&L: ${ts_['pnl']} | Avg hold: {ts_['avg_hold']} bars | Win rate: {ts_['wr']}%")

# =============================================================================
# BLOCK 5 — FRICTION
# =============================================================================
print("\n" + "=" * 60)
print("BLOCK 5 — FRICTION TEST")
print("-" * 60)

friction_cfg = {"enabled": True, "misclass_pct": 0.0, "misclass_seed": 42,
                "regime_lag_hours": 0.0, "signal_delay_bars": 2, "elevated_fee_rate": 0.0013}

# v10 with friction
out_f10 = os.path.join(OUT_DIR, "v10_b5_friction.json")
cfg_f10 = make_config(ASSETS, tf=best_tf, date_range={"start": "2020-01-01", "end": HOLDOUT_DATE},
                       friction=friction_cfg, output_path=out_f10)
r_f10 = run(cfg_f10, "B5-v10-friction")

# Our system with full friction (regime lag matters for ours)
our_friction = {"enabled": True, "misclass_pct": 3.0, "misclass_seed": 42,
                "regime_lag_hours": 12.0, "signal_delay_bars": 2, "elevated_fee_rate": 0.0013}
out_fours = os.path.join(OUT_DIR, "v10_b5_ours_friction.json")
our_cfg2 = json.loads(our_cfg_str)
our_cfg2["output_path"] = out_fours
our_cfg2["date_range"] = {"start": "2020-01-01", "end": HOLDOUT_DATE}
our_cfg2["friction"] = our_friction
with open(out_fours.replace(".json","_cfg.json"), 'w') as f:
    json.dump(our_cfg2, f)
try:
    subprocess.run([ENGINE, out_fours.replace(".json","_cfg.json")], capture_output=True, timeout=60)
    with open(out_fours) as f:
        r_fours = json.load(f)
except:
    r_fours = None

p_f10 = ps(r_f10)
p_fours = ps(r_fours)
clean_his = p_his.get("sharpe",0)
fric_his = p_f10.get("sharpe",0)
edge_his = fric_his / clean_his * 100 if clean_his != 0 else 0
clean_ours = p_ours.get("sharpe",0)
fric_ours = p_fours.get("sharpe",0)
edge_ours = fric_ours / clean_ours * 100 if clean_ours != 0 else 0

print(f"""
  {'System':<20}{'Clean Sharpe':>14}{'Friction Sharpe':>16}{'Edge Retained':>15}{'Clean P&L':>12}{'Friction P&L':>14}
  {'Our system':<20}{clean_ours:>14.2f}{fric_ours:>16.2f}{edge_ours:>14.1f}%{p_ours.get('pnl',0):>12.2f}{p_fours.get('pnl',0):>14.2f}
  {'His v10':<20}{clean_his:>14.2f}{fric_his:>16.2f}{edge_his:>14.1f}%{p_his.get('pnl',0):>12.2f}{p_f10.get('pnl',0):>14.2f}
""")

# =============================================================================
# BLOCK 6 — WALK-FORWARD
# =============================================================================
print("=" * 60)
print("BLOCK 6 — WALK-FORWARD VALIDATION")
print("-" * 60)

# 90-day test windows rolling forward
wf_start = datetime(2021, 1, 1)
wf_end_limit = datetime(2025, 3, 19)
window_days = 90
profitable_windows = 0
total_windows = 0

print(f"\n  {'Window':>7}{'Train End':>12}{'Test Period':>26}{'Sharpe':>8}{'P&L':>10}  Prof?")
while wf_start + timedelta(days=window_days) <= wf_end_limit:
    test_start = wf_start
    test_end = wf_start + timedelta(days=window_days)
    train_start = test_start - timedelta(days=365)
    total_windows += 1

    out_wf = os.path.join(OUT_DIR, f"v10_b6_wf{total_windows}.json")
    cfg_wf = make_config(ASSETS, tf=best_tf,
        date_range={"start": test_start.strftime("%Y-%m-%d"), "end": test_end.strftime("%Y-%m-%d")},
        output_path=out_wf)
    r_wf = run(cfg_wf, f"B6-WF{total_windows}")
    p_wf = ps(r_wf)
    is_prof = p_wf.get("pnl", 0) > 0
    if is_prof: profitable_windows += 1

    print(f"  {total_windows:>7}{train_start.strftime('%Y-%m-%d'):>12}"
          f"  {test_start.strftime('%Y-%m-%d')} - {test_end.strftime('%Y-%m-%d')}"
          f"{p_wf.get('sharpe',0):>8.2f}{p_wf.get('pnl',0):>10.2f}  {'Y' if is_prof else 'N'}")

    wf_start += timedelta(days=window_days)

print(f"\n  Profitable windows: {profitable_windows}/{total_windows} ({round(profitable_windows/max(total_windows,1)*100,1)}%)")
print(f"  Our system WF windows: 9/17 (53%) — from previous test\n")

# =============================================================================
# BLOCK 7 — BOOTSTRAP + MONTE CARLO
# =============================================================================
print("=" * 60)
print("BLOCK 7 — BOOTSTRAP + MONTE CARLO")
print("-" * 60)

# Bootstrap via engine
out_bs = os.path.join(OUT_DIR, "v10_b7_bootstrap.json")
cfg_bs = make_config(ASSETS, tf=best_tf, date_range={"start": "2020-01-01", "end": HOLDOUT_DATE},
    bootstrap={"enabled": True, "n_iterations": 500, "block_size_days": 14, "seed": 42, "threads": 14},
    output_path=out_bs)
r_bs = run(cfg_bs, "B7-bootstrap")
bs = r_bs.get("bootstrap", {}) if r_bs else {}

print(f"""
  BOOTSTRAP (500 iterations, 2-week blocks):
    % profitable: {bs.get('pct_profitable','?')}%
    Median PF: {bs.get('median_pf','?')}
    5th percentile PF: {bs.get('p5_pf','?')}
    p-value (PF > 1.0): {bs.get('p_value_pf_gt1', '?')}
""")

# Monte Carlo (trade-order shuffles in Python)
import random
random.seed(42)
mc_trades = [t for t in trades(r_v10_train)]
mc_ruin = 0
mc_finals = []
n_mc = 1000
for _ in range(n_mc):
    shuffled = mc_trades[:]
    random.shuffle(shuffled)
    equity = 1000.0
    peak = equity
    ruined = False
    for t in shuffled:
        equity += t["pnl"]
        if equity <= 0:
            ruined = True
            break
    if ruined:
        mc_ruin += 1
        mc_finals.append(0)
    else:
        mc_finals.append(equity)

mc_finals.sort()
print(f"""  MONTE CARLO (1,000 trade-order shuffles, $1,000 start, $125 flat):
    Ruin %: {mc_ruin/n_mc*100:.1f}%
    Median final equity: ${mc_finals[500]:.2f}
    5th percentile: ${mc_finals[50]:.2f}
    95th percentile: ${mc_finals[950]:.2f}
""")

# =============================================================================
# BLOCK 8 — PARAMETER SENSITIVITY
# =============================================================================
print("=" * 60)
print("BLOCK 8 — PARAMETER SENSITIVITY")
print("-" * 60)

out_rob = os.path.join(OUT_DIR, "v10_b8_robustness.json")
cfg_rob = make_config(ASSETS, tf=best_tf, date_range={"start": "2020-01-01", "end": HOLDOUT_DATE},
    robustness={"enabled": True, "n_combos": 500, "variation_pct": 30.0, "seed": 42, "threads": 14},
    output_path=out_rob)
r_rob = run(cfg_rob, "B8-robustness")
rob = r_rob.get("robustness", {}) if r_rob else {}

print(f"""
  % profitable: {rob.get('profitable_pct','?')}%
  Median Sharpe: {rob.get('median_sharpe','?')}
  Sharpe range (5th to 95th): {rob.get('p5_sharpe','?')} to {rob.get('p95_sharpe','?')}
  Median PF: {rob.get('median_pf','?')}
""")

# =============================================================================
# BLOCK 9 — FEE BREAKEVEN
# =============================================================================
print("=" * 60)
print("BLOCK 9 — FEE BREAKEVEN")
print("-" * 60)

fee_levels = [0, 0.0002, 0.00045, 0.0006, 0.001, 0.0015, 0.002, 0.003]
print(f"\n  {'Fee (bps)':>10}{'PF':>7}{'P&L':>10}{'Sharpe':>8}  Profitable?")
breakeven_fee = None
for fee in fee_levels:
    out_fee = os.path.join(OUT_DIR, f"v10_b9_fee{int(fee*10000)}.json")
    cfg_fee = make_config(ASSETS, tf=best_tf, date_range={"start": "2020-01-01", "end": HOLDOUT_DATE},
                           fee_rate=fee, output_path=out_fee)
    r_fee = run(cfg_fee, f"B9-fee{int(fee*10000)}")
    p_fee = ps(r_fee)
    is_prof = p_fee.get("pnl", 0) > 0
    if not is_prof and breakeven_fee is None:
        breakeven_fee = fee * 10000
    print(f"  {fee*10000:>10.1f}{p_fee.get('pf',0):>7.2f}{p_fee.get('pnl',0):>10.2f}{p_fee.get('sharpe',0):>8.2f}  {'Y' if is_prof else 'N'}")

if breakeven_fee is None: breakeven_fee = 30  # still profitable at max tested
print(f"\n  Breakeven fee: ~{breakeven_fee:.0f} bps")
print(f"  Our system breakeven: 137 bps — v10 is {'more' if breakeven_fee > 137 else 'less'} fee-resilient\n")

# =============================================================================
# BLOCK 10 — FAT TRADE ANALYSIS
# =============================================================================
print("=" * 60)
print("BLOCK 10 — FAT TRADE FRAGILITY")
print("-" * 60)

sorted_trades = sorted(trades(r_v10_train), key=lambda t: t["pnl"], reverse=True)
total_pnl_all = sum(t["pnl"] for t in sorted_trades)
print(f"\n  {'Removed':>10}{'PF':>7}{'P&L':>10}{'Sharpe':>8}")
for n_remove in [1, 3, 5, 10, 20]:
    remaining = sorted_trades[n_remove:]
    if not remaining: continue
    gp = sum(t["pnl"] for t in remaining if t["pnl"] > 0)
    gl = abs(sum(t["pnl"] for t in remaining if t["pnl"] < 0))
    pf = gp/gl if gl > 0 else 999
    pnl = sum(t["pnl"] for t in remaining)
    sh = sharpe_from_trades(remaining)
    print(f"  Top {n_remove:<6}{pf:>7.2f}{pnl:>10.2f}{sh:>8.2f}")

top3_pnl = sum(t["pnl"] for t in sorted_trades[:3])
top3_pct = top3_pnl / total_pnl_all * 100 if total_pnl_all > 0 else 0
top5_remaining = sum(t["pnl"] for t in sorted_trades[5:])
fragility = "HIGH" if top3_pct > 50 else ("MEDIUM" if top3_pct > 20 else "LOW")
print(f"\n  Top 3 trades: ${top3_pnl:.2f} ({top3_pct:.1f}% of total P&L)")
print(f"  Still profitable without top 5? {'YES' if top5_remaining > 0 else 'NO'}")
print(f"  FRAGILITY: {fragility}\n")

# =============================================================================
# BLOCK 11 — BLACK SWAN EVENTS
# =============================================================================
print("=" * 60)
print("BLOCK 11 — BLACK SWAN EVENTS")
print("-" * 60)

# We need to check positions during each event from the full BTC trade log
btc_full = [t for t in trades(tf_results[best_tf]) if t.get("asset") == "BTC"]
print(f"\n  {'Event':<20}{'Position':>10}{'Event P&L':>11}{'Survived?':>10}")
for event_name, start, end in crash_events:
    event_t = [t for t in btc_full
        if (t.get("entry_ts","")[:10] <= end and t.get("exit_ts","")[:10] >= start)]
    total = sum(t["pnl"] for t in event_t) if event_t else 0
    pos = event_t[0].get("direction","flat") if event_t else "flat"
    survived = "Y" if total >= 0 else ("Y (loss)" if total > -100 else "N")
    print(f"  {event_name:<20}{pos:>10}{total:>11.2f}{survived:>10}")

# =============================================================================
# BLOCK 12 — SACRED HOLDOUT
# =============================================================================
print("\n" + "=" * 60)
print("BLOCK 12 — SACRED HOLDOUT")
print("-" * 60)

holdout_range = {"start": HOLDOUT_DATE, "end": "2026-12-31"}

# Our system on holdout
out_h_ours = os.path.join(OUT_DIR, "v10_b12_ours.json")
our_cfg3 = json.loads(our_cfg_str)
our_cfg3["output_path"] = out_h_ours
our_cfg3["date_range"] = holdout_range
with open(out_h_ours.replace(".json","_cfg.json"), 'w') as f:
    json.dump(our_cfg3, f)
try:
    subprocess.run([ENGINE, out_h_ours.replace(".json","_cfg.json")], capture_output=True, timeout=60)
    with open(out_h_ours) as f:
        r_h_ours = json.load(f)
except:
    r_h_ours = None

# v10 on holdout - all 3 TFs
print(f"\n  {'System':<20}{'PF':>7}{'P&L':>10}{'Sharpe':>8}{'MDD%':>7}{'Months Prof':>13}")
# Our system
p_ho = ps(r_h_ours)
ht_ours = trades(r_h_ours)
monthly_ours = defaultdict(float)
for t in ht_ours:
    monthly_ours[t.get("exit_ts","")[:7]] += t["pnl"]
months_prof_ours = sum(1 for v in monthly_ours.values() if v > 0)
print(f"  {'Our system':<20}{p_ho.get('pf',0):>7.2f}{p_ho.get('pnl',0):>10.2f}{p_ho.get('sharpe',0):>8.2f}{p_ho.get('mdd_pct',0):>6.1f}%{months_prof_ours:>8}/{max(len(monthly_ours),1)}")

holdout_results = {}
for tf in ["15m", "30m", "1H"]:
    out_htf = os.path.join(OUT_DIR, f"v10_b12_{tf}.json")
    cfg_htf = make_config(ASSETS, tf=tf, date_range=holdout_range, output_path=out_htf)
    r_htf = run(cfg_htf, f"B12-{tf}")
    p_htf = ps(r_htf)
    holdout_results[tf] = p_htf
    ht_trades = trades(r_htf)
    monthly = defaultdict(float)
    for t in ht_trades:
        monthly[t.get("exit_ts","")[:7]] += t["pnl"]
    mp = sum(1 for v in monthly.values() if v > 0)
    print(f"  {'His v10 ('+tf+')':<20}{p_htf.get('pf',0):>7.2f}{p_htf.get('pnl',0):>10.2f}{p_htf.get('sharpe',0):>8.2f}{p_htf.get('mdd_pct',0):>6.1f}%{mp:>8}/{max(len(monthly),1)}")

best_holdout_tf = max(holdout_results, key=lambda k: holdout_results[k].get("sharpe",0))
ho_winner = "Ours" if p_ho.get("sharpe",0) > holdout_results[best_holdout_tf].get("sharpe",0) else f"His ({best_holdout_tf})"
print(f"\n  HOLDOUT WINNER: {ho_winner}\n")

# =============================================================================
# BLOCK 13 — FINAL REPORT
# =============================================================================
total_time = time.time() - T0

# Gather key stats
train_v10 = p_his
holdout_v10 = holdout_results.get(best_tf, {})
train_ours = p_ours
holdout_ours_p = p_ho

# Shorts assessment
longs_only_r = None
for name, ov in component_variants:
    if "Longs only" in name:
        out_lo = os.path.join(OUT_DIR, f"v10_b3_{name[:20].replace(' ','_')}.json")
        try:
            with open(out_lo) as f:
                longs_only_r = json.load(f)
        except: pass

lo_pf = ps(longs_only_r).get("pf",0) if longs_only_r else 0

print("=" * 72)
print("  COLLEAGUE V10 'ADAPTIVE + ZLEMA' — COMPLETE ANALYSIS")
print("=" * 72)
print(f"""
  TOTAL RUNTIME: {total_time:.1f} seconds

  HIS V10 STRATEGY PERFORMANCE:
    Best timeframe: {best_tf}
    Training: PF={train_v10.get('pf',0):.2f} | P&L=${train_v10.get('pnl',0):.2f} | Sharpe={train_v10.get('sharpe',0):.2f} | MDD={train_v10.get('mdd_pct',0):.1f}% | Trades={train_v10.get('trades',0)}
    Holdout:  PF={holdout_v10.get('pf',0):.2f} | P&L=${holdout_v10.get('pnl',0):.2f} | Sharpe={holdout_v10.get('sharpe',0):.2f}
    Profitable every year: {'YES' if not losing_years else 'NO — lost: ' + ', '.join(losing_years)}
    Works on 2+ assets: {'YES' if multi_asset else 'NO'}

  OUR SYSTEM PERFORMANCE:
    Training: PF={train_ours.get('pf',0):.2f} | P&L=${train_ours.get('pnl',0):.2f} | Sharpe={train_ours.get('sharpe',0):.2f} | MDD={train_ours.get('mdd_pct',0):.1f}%
    Holdout:  PF={holdout_ours_p.get('pf',0):.2f} | P&L=${holdout_ours_p.get('pnl',0):.2f} | Sharpe={holdout_ours_p.get('sharpe',0):.2f}

  HEAD-TO-HEAD:
    Training Sharpe: Ours={train_ours.get('sharpe',0):.2f} vs His={train_v10.get('sharpe',0):.2f} | Winner: {'Ours' if train_ours.get('sharpe',0) > train_v10.get('sharpe',0) else 'His'}
    Holdout Sharpe:  Ours={holdout_ours_p.get('sharpe',0):.2f} vs His={holdout_v10.get('sharpe',0):.2f} | Winner: {'Ours' if holdout_ours_p.get('sharpe',0) > holdout_v10.get('sharpe',0) else 'His'}
    Training P&L:   Ours=${train_ours.get('pnl',0):.2f} vs His=${train_v10.get('pnl',0):.2f} | Winner: {'Ours' if train_ours.get('pnl',0) > train_v10.get('pnl',0) else 'His'}
    Holdout P&L:    Ours=${holdout_ours_p.get('pnl',0):.2f} vs His=${holdout_v10.get('pnl',0):.2f} | Winner: {'Ours' if holdout_ours_p.get('pnl',0) > holdout_v10.get('pnl',0) else 'His'}
    MDD: Ours={train_ours.get('mdd_pct',0):.1f}% vs His={train_v10.get('mdd_pct',0):.1f}% | Winner: {'Ours' if train_ours.get('mdd_pct',0) < train_v10.get('mdd_pct',0) else 'His'}

  STRESS TEST SUMMARY:
    Walk-forward: His={profitable_windows}/{total_windows} profitable (Ours=9/17)
    Bootstrap profitable: His={bs.get('pct_profitable','?')}% (Ours=100%)
    Parameter robustness: His={rob.get('profitable_pct','?')}% profitable (Ours=94.8%)
    Friction edge retained: His={edge_his:.1f}% (Ours={edge_ours:.1f}%)
    Fee breakeven: His=~{breakeven_fee:.0f} bps (Ours=137 bps)
    Fat trade fragility: His={fragility} (Ours=LOW)
    MC ruin: His={mc_ruin/n_mc*100:.1f}% (Ours=0%)

  KEY FINDINGS:
    Shorts in v10: long-only PF={lo_pf:.2f} vs full PF={train_v10.get('pf',0):.2f}

  VERDICT:
    1. Is v10 profitable? {'YES' if train_v10.get('pf',0) > 1 else 'NO'} — PF={train_v10.get('pf',0):.2f}, Sharpe={train_v10.get('sharpe',0):.2f}
    2. Does v10 beat our system? {'YES' if train_v10.get('sharpe',0) > train_ours.get('sharpe',0) and holdout_v10.get('sharpe',0) > holdout_ours_p.get('sharpe',0) else 'NO'}
""")

# Save all results
RESULTS = {
    "block0": {
        "btc_30m": {"portfolio": p0a, "trades": len(t0a), "flat_sizing": ts0a,
                     "fixed_ratio": fr0a, "pct_equity": pe0a},
        "all_assets_30m": {"portfolio": ps(r0b)},
        "timeframe_comparison": {tf: {"portfolio": ps(tf_results[tf])} for tf in tf_results},
        "best_timeframe": best_tf,
    },
    "block1": {
        "ours_training": {"portfolio": p_ours},
        "his_training": {"portfolio": p_his},
    },
    "block5": {
        "ours_friction": {"portfolio": p_fours},
        "his_friction": {"portfolio": p_f10},
        "edge_retained_his": edge_his,
        "edge_retained_ours": edge_ours,
    },
    "block6": {"profitable_windows": profitable_windows, "total_windows": total_windows},
    "block7": {"bootstrap": bs, "mc_ruin_pct": mc_ruin/n_mc*100,
               "mc_median_equity": mc_finals[500]},
    "block8": {"robustness": rob},
    "block9": {"breakeven_bps": breakeven_fee},
    "block10": {"fragility": fragility, "top3_pct": top3_pct},
    "block12": {
        "ours_holdout": {"portfolio": p_ho},
        "his_holdout": {tf: {"portfolio": holdout_results[tf]} for tf in holdout_results},
    },
    "runtime_seconds": total_time,
}

with open(os.path.join(OUT_DIR, "v10_tournament.json"), 'w') as f:
    json.dump(RESULTS, f, indent=2, default=str)
print(f"\n  All results saved to {OUT_DIR}/v10_tournament.json")

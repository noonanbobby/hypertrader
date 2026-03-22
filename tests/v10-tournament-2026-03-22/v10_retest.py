#!/usr/bin/env python3
"""V10 Retest — Colleague's ACTUAL Settings (7x leverage, 50% position size)"""
import json, subprocess, os, math, sys, time
from collections import defaultdict
from datetime import datetime, timedelta

ENGINE = "/home/ubuntu/hypertrader-engine-v4/target/release/hypertrader-engine"
DATA_DIR = "/opt/hypertrader/addons/backtest-data"
OUT_DIR = "/tmp/discovery"
os.makedirs(OUT_DIR, exist_ok=True)
T0 = time.time()

HOLDOUT_DATE = "2025-03-19"
ASSETS = ["BTC", "ETH", "SOL"]

def v10_params(tf="30m", overrides=None):
    p = {
        "timeframe": tf, "atr_period": 10, "base_mult": 6.0, "trend_mult": 4.0,
        "range_mult": 8.0, "adx_adapt_thresh": 25.0, "slow_atr_period": 20, "slow_mult": 8.0,
        "use_dual_st_buys": True, "use_dual_st_sells": True, "cooldown": 2, "late_window": 1,
        "min_score": 6, "use_rsi": True, "rsi_period": 14, "rsi_buy_max": 70, "rsi_sell_min": 30,
        "use_zlema": True, "zlema_period": 200, "use_volume": True, "vol_sma_period": 20,
        "vol_multiplier": 1.0, "use_adx_filter": True, "adx_period": 14, "adx_minimum": 25.0,
        "use_squeeze": True, "exit_on_raw_flip": True, "use_ema_atr": True, "longs_only": False,
    }
    if overrides: p.update(overrides)
    return p

def make_config(assets, tf="30m", overrides=None, date_range=None,
                fee_rate=0.0006, slippage=0.0005, funding=0.0001,
                margin=125.0, leverage=10.0, equity=500.0, output_path="/tmp/_tmp.json"):
    sp = v10_params(tf, overrides)
    cfg = {
        "assets": assets, "data_dir": DATA_DIR, "mode": "baseline", "timeframe": tf,
        "params": {"ema200_period":200,"ema50_period":50,"ema50_rising_lookback":5,
            "st_4h_atr_period":10,"st_4h_multiplier":3.0,"st_15m_atr_period":10,
            "st_15m_multiplier":2.0,"near_band_pct":0.005,"rsi_period":14,"rsi_threshold":45.0,
            "rsi_lookback":2,"ema_fast":21,"ema_slow":55,"vol_mult":2.0,"vol_sma_period":20,"warmup":300},
        "strategy": {
            "long_entry": {"type": "adaptive_zlema_st", "params": sp},
            "short_entry": {"type": "adaptive_zlema_st_short", "params": {"timeframe": tf}},
            "exit": {"type": "current"}},
        "regime_config": {"type": "none"},
        "sizing": {"type": "flat", "margin": margin, "leverage": leverage, "starting_equity": equity},
        "fees": {"maker_rate": fee_rate, "slippage": slippage, "funding_rate_per_8h": funding},
        "output_path": output_path,
    }
    if date_range: cfg["date_range"] = date_range
    return cfg

def run(cfg, label=""):
    cfg_path = cfg["output_path"].replace(".json", "_cfg.json")
    with open(cfg_path, 'w') as f: json.dump(cfg, f)
    try:
        r = subprocess.run([ENGINE, cfg_path], capture_output=True, text=True, timeout=300)
        if r.returncode != 0:
            print(f"  [ERROR {label}] {r.stderr[-300:]}", file=sys.stderr)
            return None
    except Exception as e:
        print(f"  [ERROR {label}] {e}", file=sys.stderr)
        return None
    try:
        with open(cfg["output_path"]) as f: return json.load(f)
    except: return None

def pct_equity_sim(trade_log, starting=100000, fraction=0.50, leverage=7.0, base_margin=125, base_leverage=10):
    """Recompute equity with percent-of-equity sizing at specified leverage."""
    equity = starting
    base_notional = base_margin * base_leverage  # 1250
    eq_curve = [equity]
    yearly = defaultdict(lambda: {"start": None, "end": 0, "pnl": 0, "trades": 0})
    for t in trade_log:
        yr = t.get("entry_ts","")[:4]
        if yearly[yr]["start"] is None: yearly[yr]["start"] = equity
        position_margin = fraction * equity
        position_notional = position_margin * leverage
        scale = position_notional / base_notional if base_notional > 0 else 1
        pnl = t["pnl"] * scale
        equity += pnl
        equity = max(equity, 0)
        eq_curve.append(equity)
        yearly[yr]["end"] = equity
        yearly[yr]["pnl"] += pnl
        yearly[yr]["trades"] += 1
    peak = starting
    max_dd_pct = 0; max_dd_usd = 0
    for e in eq_curve:
        peak = max(peak, e)
        dd_pct = (peak - e) / peak * 100 if peak > 0 else 0
        dd_usd = peak - e
        max_dd_pct = max(max_dd_pct, dd_pct)
        max_dd_usd = max(max_dd_usd, dd_usd)
    return {"final_equity": equity, "pnl": equity - starting, "mdd_pct": max_dd_pct,
            "mdd_usd": max_dd_usd, "eq_curve": eq_curve, "yearly": dict(yearly)}

def fixed_ratio_equity(trade_log, starting=1000, delta=1000, base_margin=125, leverage=10, cap=4):
    equity = starting
    for t in trade_log:
        N = int(0.5 + 0.5 * math.sqrt(1 + 8 * max(equity - starting, 0) / delta))
        N = min(max(N, 1), cap)
        equity += t["pnl"] * N
    peak = starting; max_dd = 0
    eq = starting
    for t in trade_log:
        N = int(0.5 + 0.5 * math.sqrt(1 + 8 * max(eq - starting, 0) / delta))
        N = min(max(N, 1), cap)
        eq += t["pnl"] * N
        peak = max(peak, eq)
        dd = (peak - eq) / peak * 100 if peak > 0 else 0
        max_dd = max(max_dd, dd)
    return {"final_equity": equity, "pnl": equity - starting, "mdd_pct": max_dd}

print("=" * 72)
print("  V10 RETEST — COLLEAGUE'S ACTUAL SETTINGS (7x, 50% equity)")
print("=" * 72)

# ═══════════════════════════════════════════════════════════════
# STEP 0 — TRADE LOG COMPARISON
# ═══════════════════════════════════════════════════════════════
print("\n" + "=" * 60)
print("STEP 0 — TRADE VERIFICATION")
print("=" * 60)

# 0A — Full dataset BTC 30m
out_0a = os.path.join(OUT_DIR, "v10_retest_0a.json")
cfg_0a = make_config(["BTC"], tf="30m", output_path=out_0a)
r0a = run(cfg_0a, "0A")
tl = r0a.get("trade_log", []) if r0a else []

print(f"\n  Our trade count (BTC, 30m, full dataset): {len(tl)}")
print(f"  His trade count: 95-96")
print(f"  Difference: {len(tl) - 95} trades")

# Print ALL trades
print(f"\n  COMPLETE TRADE LOG ({len(tl)} trades):")
print(f"  {'#':>4} {'Dir':>5} {'Entry Date':>12} {'Entry Time':>6} {'Entry$':>10} {'Exit Date':>12} {'Exit Time':>6} {'Exit$':>10} {'P&L':>8} {'Bars':>5}")
for i, t in enumerate(tl):
    d = t.get("direction","?")[:5]
    ets = t.get("entry_ts","")
    xts = t.get("exit_ts","")
    ed = ets[:10] if len(ets)>=10 else "?"
    et = ets[11:16] if len(ets)>=16 else "?"
    xd = xts[:10] if len(xts)>=10 else "?"
    xt = xts[11:16] if len(xts)>=16 else "?"
    ep = t.get("entry_price",0)
    xp = t.get("exit_price",0)
    pnl = t.get("pnl",0)
    bars = t.get("bars_held",0)
    print(f"  {i+1:>4} {d:>5} {ed:>12} {et:>6} {ep:>10.2f} {xd:>12} {xt:>6} {xp:>10.2f} {pnl:>8.2f} {bars:>5}")

# 0B — Check 30m bar alignment
print(f"\n  30m BAR ALIGNMENT (first 10 bars):")
with open(os.path.join(DATA_DIR, "mega_btc_15m.json")) as f:
    raw15 = json.load(f)

ms30 = 1_800_000
bars30 = []
i = 0
while i < len(raw15) and len(bars30) < 10:
    ts = raw15[i]["open_time"]
    period = ts // ms30
    o = float(raw15[i]["open"])
    h = float(raw15[i]["high"])
    l = float(raw15[i]["low"])
    c = float(raw15[i]["close"])
    v = float(raw15[i]["volume"])
    i += 1
    while i < len(raw15) and raw15[i]["open_time"] // ms30 == period:
        h = max(h, float(raw15[i]["high"]))
        l = min(l, float(raw15[i]["low"]))
        c = float(raw15[i]["close"])
        v += float(raw15[i]["volume"])
        i += 1
    bars30.append({"ts": period * ms30, "o": o, "h": h, "l": l, "c": c, "v": v})

for b in bars30:
    dt = datetime.utcfromtimestamp(b["ts"]/1000)
    print(f"    {dt.strftime('%Y-%m-%d %H:%M')} | O={b['o']:.2f} H={b['h']:.2f} L={b['l']:.2f} C={b['c']:.2f} V={b['v']:.0f}")

first_dt = datetime.utcfromtimestamp(bars30[0]["ts"]/1000)
aligned = first_dt.minute in [0, 30]
print(f"\n  First bar starts at :{first_dt.minute:02d} — {'CORRECT' if aligned else 'MISALIGNED'}")

# 0C — Date range check
first_trade = tl[0] if tl else {}
last_trade = tl[-1] if tl else {}
print(f"\n  Data starts: {datetime.utcfromtimestamp(bars30[0]['ts']/1000).strftime('%Y-%m-%d')}")
print(f"  First trade: {first_trade.get('entry_ts','?')[:10]}")
print(f"  Last trade exit: {last_trade.get('exit_ts','?')[:10]}")
print(f"  His stated range: March 2020 to March 2026")

# Check data range — his starts March 2020, ours starts Jan 2020
jan_feb_trades = [t for t in tl if t.get("entry_ts","")[:7] in ["2020-01", "2020-02"]]
print(f"  Trades in Jan-Feb 2020 (before his data starts): {len(jan_feb_trades)}")
if jan_feb_trades:
    print(f"    These trades exist in OUR data but NOT his — explains part of the count difference")
    for t in jan_feb_trades:
        print(f"    {t.get('direction','?'):>5} {t.get('entry_ts','')[:16]} → {t.get('exit_ts','')[:16]} P&L=${t.get('pnl',0):.2f}")

# Run with his date range (March 2020 - March 2026)
out_0a_his_range = os.path.join(OUT_DIR, "v10_retest_0a_hisrange.json")
cfg_0a_hr = make_config(["BTC"], tf="30m", date_range={"start": "2020-03-01", "end": "2026-03-22"},
                          output_path=out_0a_his_range)
r0a_hr = run(cfg_0a_hr, "0A-hisrange")
tl_hr = r0a_hr.get("trade_log", []) if r0a_hr else []
print(f"\n  Trade count with HIS date range (Mar 2020 - Mar 2026): {len(tl_hr)}")
print(f"  Difference from his 95-96: {len(tl_hr) - 95}")

# ═══════════════════════════════════════════════════════════════
# STEP 1 — FULL RESULTS WITH HIS ACTUAL SIZING
# ═══════════════════════════════════════════════════════════════
print("\n" + "=" * 60)
print("STEP 1 — FULL RESULTS WITH HIS ACTUAL SIZING")
print("=" * 60)

# 1A — BTC at his sizing
# Use flat $125 trade log and recompute with his sizing
sim_btc = pct_equity_sim(tl, starting=100000, fraction=0.50, leverage=7.0)
print(f"""
STEP 1A — V10 ACTUAL SETTINGS (BTC, 30m, full dataset):

  Initial capital: $100,000
  Position size: 50% of equity
  Leverage: 7x
  Per-trade notional at start: $350,000

  Results:
    Trades: {len(tl)} (longs: {sum(1 for t in tl if t.get('direction')=='long')}, shorts: {sum(1 for t in tl if t.get('direction')=='short')})
    Final equity: ${sim_btc['final_equity']:,.2f}
    Return: {(sim_btc['final_equity']/100000 - 1)*100:.1f}%
    MDD%: {sim_btc['mdd_pct']:.1f}% | MDD$: ${sim_btc['mdd_usd']:,.2f}
    Win rate: {sum(1 for t in tl if t['pnl']>0)/len(tl)*100:.1f}%

  HIS CLAIM: $100K -> $3M (3,000% return), 95 trades
  OUR RESULT: $100K -> ${sim_btc['final_equity']:,.2f} ({(sim_btc['final_equity']/100000 - 1)*100:.1f}% return), {len(tl)} trades
""")

# 1B — Year by year at his sizing
print("STEP 1B — YEAR BY YEAR (BTC, his sizing):\n")
print(f"  {'Year':<6}{'Start Eq':>14}{'End Eq':>14}{'P&L':>14}{'Return':>8}{'Trades':>8}  Prof?")
yearly = sim_btc["yearly"]
losing_years = []
for yr in sorted(yearly):
    y = yearly[yr]
    start_eq = y["start"] if y["start"] is not None else 100000
    end_eq = y["end"]
    pnl = y["pnl"]
    ret = pnl / start_eq * 100 if start_eq > 0 else 0
    prof = "Y" if pnl > 0 else "N"
    if pnl <= 0: losing_years.append(yr)
    print(f"  {yr:<6}{start_eq:>14,.2f}{end_eq:>14,.2f}{pnl:>14,.2f}{ret:>7.1f}%{y['trades']:>8}  {prof}")

print(f"\n  HIS CLAIM: profitable every year")
print(f"  OUR RESULT: {'CONFIRMED' if not losing_years else 'DENIED — lost in: ' + ', '.join(losing_years)}")

# 1C — All 3 assets at his sizing
print(f"\nSTEP 1C — ALL ASSETS (his sizing):\n")
out_all = os.path.join(OUT_DIR, "v10_retest_all.json")
cfg_all = make_config(ASSETS, tf="30m", output_path=out_all)
r_all = run(cfg_all, "1C-all")
tl_all = r_all.get("trade_log", []) if r_all else []

print(f"  {'Asset':<6}{'Final Eq':>14}{'Return':>8}{'PF':>7}{'Sharpe':>8}{'MDD%':>7}{'Trades':>8}")
for sym in ASSETS:
    sym_trades = [t for t in tl_all if t.get("asset") == sym]
    sim = pct_equity_sim(sym_trades, starting=100000, fraction=0.50, leverage=7.0)
    s = r_all.get("asset_stats", {}).get(sym, {})
    print(f"  {sym:<6}{sim['final_equity']:>14,.2f}{(sim['final_equity']/100000-1)*100:>7.1f}%{s.get('pf',0):>7.2f}{s.get('sharpe',0):>8.2f}{sim['mdd_pct']:>6.1f}%{len(sym_trades):>8}")

# Portfolio (all 3 assets combined, each starting with $100K)
port_sim = pct_equity_sim(sorted(tl_all, key=lambda t: t.get("exit_ts","")),
                           starting=300000, fraction=0.50/3, leverage=7.0)
p_all = r_all.get("portfolio", {})
print(f"  {'PORT':<6}{port_sim['final_equity']:>14,.2f}{(port_sim['final_equity']/300000-1)*100:>7.1f}%{p_all.get('pf',0):>7.2f}{p_all.get('sharpe',0):>8.2f}{port_sim['mdd_pct']:>6.1f}%{len(tl_all):>8}")

# 1D — Liquidation check
print(f"\nSTEP 1D — LIQUIDATION CHECK:\n")
# At 7x leverage, liquidation occurs at ~14% adverse move (1/7 = 14.3%)
for sym in ASSETS:
    sym_trades = [t for t in tl_all if t.get("asset") == sym]
    liq_count = 0
    worst_adverse = 0
    for t in sym_trades:
        ep = t.get("entry_price", 0)
        if ep == 0: continue
        # Check worst adverse move using high/low during trade
        # We don't have intra-trade high/low in trade log, so use entry/exit prices
        xp = t.get("exit_price", 0)
        if t.get("direction") == "long":
            adverse = (ep - xp) / ep * 100 if xp < ep else 0
        else:
            adverse = (xp - ep) / ep * 100 if xp > ep else 0
        worst_adverse = max(worst_adverse, adverse)
        # At 7x, liquidation at ~14.3% adverse
        if t.get("liquidated"): liq_count += 1
    print(f"  {sym}: Liquidations={liq_count}, Worst adverse move (entry-to-exit)={worst_adverse:.1f}%")
    if worst_adverse > 14.3:
        print(f"    WARNING: {worst_adverse:.1f}% exceeds 7x liquidation threshold of 14.3%")

# ═══════════════════════════════════════════════════════════════
# STEP 2 — SIZING COMPARISON
# ═══════════════════════════════════════════════════════════════
print("\n" + "=" * 60)
print("STEP 2 — SIZING COMPARISON")
print("=" * 60)

# Training period for all
out_v10_train = os.path.join(OUT_DIR, "v10_retest_train.json")
cfg_v10_train = make_config(ASSETS, tf="30m", date_range={"start":"2020-01-01","end":HOLDOUT_DATE},
                             output_path=out_v10_train)
r_v10_train = run(cfg_v10_train, "2-train")
tl_train = r_v10_train.get("trade_log", []) if r_v10_train else []
p_train = r_v10_train.get("portfolio", {}) if r_v10_train else {}

# Our system training
out_ours = os.path.join(OUT_DIR, "v10_retest_ours.json")
our_base = json.load(open("/tmp/discovery/rust_baseline_config.json"))
our_base["output_path"] = out_ours
our_base["date_range"] = {"start":"2020-01-01","end":HOLDOUT_DATE}
with open(out_ours.replace(".json","_cfg.json"), 'w') as f: json.dump(our_base, f)
subprocess.run([ENGINE, out_ours.replace(".json","_cfg.json")], capture_output=True, timeout=60)
with open(out_ours) as f: r_ours = json.load(f)
tl_ours = r_ours.get("trade_log", [])
p_ours = r_ours.get("portfolio", {})

# His sizing on v10
sim_his_sizing = pct_equity_sim(tl_train, starting=100000, fraction=0.50, leverage=7.0)
# His sizing on OUR system
sim_ours_his_sizing = pct_equity_sim(tl_ours, starting=100000, fraction=0.50, leverage=7.0)
# FR on v10
fr_v10 = fixed_ratio_equity(tl_train)
# FR on ours
fr_ours = fixed_ratio_equity(tl_ours)

print(f"""
  {'Configuration':<46}{'Final Eq':>14}{'P&L':>12}{'Sharpe':>8}{'MDD%':>7}
  {'His v10, his sizing ($100K, 50%, 7x)':<46}{sim_his_sizing['final_equity']:>14,.2f}{sim_his_sizing['pnl']:>12,.2f}{p_train.get('sharpe',0):>8.2f}{sim_his_sizing['mdd_pct']:>6.1f}%
  {'His v10, $125 flat':<46}{'$'+str(round(500+p_train.get('pnl',0),2)):>14}{p_train.get('pnl',0):>12.2f}{p_train.get('sharpe',0):>8.2f}{p_train.get('mdd_pct',0):>6.1f}%
  {'His v10, FR d=$1K from $1K':<46}{fr_v10['final_equity']:>14,.2f}{fr_v10['pnl']:>12,.2f}{'':>8}{fr_v10['mdd_pct']:>6.1f}%
  {'Our system, $125 flat':<46}{'$'+str(round(500+p_ours.get('pnl',0),2)):>14}{p_ours.get('pnl',0):>12.2f}{p_ours.get('sharpe',0):>8.2f}{p_ours.get('mdd_pct',0):>6.1f}%
  {'Our system, FR d=$1K from $1K':<46}{fr_ours['final_equity']:>14,.2f}{fr_ours['pnl']:>12,.2f}{'':>8}{fr_ours['mdd_pct']:>6.1f}%
  {'Our system, his sizing ($100K, 50%, 7x)':<46}{sim_ours_his_sizing['final_equity']:>14,.2f}{sim_ours_his_sizing['pnl']:>12,.2f}{p_ours.get('sharpe',0):>8.2f}{sim_ours_his_sizing['mdd_pct']:>6.1f}%

  AT EQUAL SIZING ($125 flat — pure strategy comparison):
    Ours: Sharpe={p_ours.get('sharpe',0):.2f}, PF={p_ours.get('pf',0):.2f}, P&L=${p_ours.get('pnl',0):.2f}
    His:  Sharpe={p_train.get('sharpe',0):.2f}, PF={p_train.get('pf',0):.2f}, P&L=${p_train.get('pnl',0):.2f}
    Winner: {'Ours' if p_ours.get('sharpe',0) > p_train.get('sharpe',0) else 'His'}

  AT HIS SIZING ($100K, 50%, 7x — applied to BOTH):
    Our system: ${sim_ours_his_sizing['final_equity']:,.2f} ({(sim_ours_his_sizing['final_equity']/100000-1)*100:.1f}% return), MDD={sim_ours_his_sizing['mdd_pct']:.1f}%
    His v10:    ${sim_his_sizing['final_equity']:,.2f} ({(sim_his_sizing['final_equity']/100000-1)*100:.1f}% return), MDD={sim_his_sizing['mdd_pct']:.1f}%
    Winner: {'Ours' if sim_ours_his_sizing['final_equity'] > sim_his_sizing['final_equity'] else 'His'}
""")

# ═══════════════════════════════════════════════════════════════
# STEP 3 — WALK-FORWARD WITH HIS SIZING
# ═══════════════════════════════════════════════════════════════
print("=" * 60)
print("STEP 3 — WALK-FORWARD")
print("=" * 60)

wf_start = datetime(2021, 1, 1)
wf_end_limit = datetime(2025, 3, 19)
window_days = 90
profitable_windows = 0
total_windows = 0
train_sharpes = []
test_sharpes = []

print(f"\n  {'Win':>4}{'Test Period':>26}{'Sharpe':>8}{'P&L':>10}  Prof?")
while wf_start + timedelta(days=window_days) <= wf_end_limit:
    test_start = wf_start
    test_end = wf_start + timedelta(days=window_days)
    total_windows += 1
    out_wf = os.path.join(OUT_DIR, f"v10_retest_wf{total_windows}.json")
    cfg_wf = make_config(ASSETS, tf="30m",
        date_range={"start": test_start.strftime("%Y-%m-%d"), "end": test_end.strftime("%Y-%m-%d")},
        output_path=out_wf)
    r_wf = run(cfg_wf, f"WF{total_windows}")
    p_wf = r_wf.get("portfolio", {}) if r_wf else {}
    is_prof = p_wf.get("pnl", 0) > 0
    if is_prof: profitable_windows += 1
    sh = p_wf.get("sharpe", 0)
    test_sharpes.append(sh)
    print(f"  {total_windows:>4}  {test_start.strftime('%Y-%m-%d')} - {test_end.strftime('%Y-%m-%d')}{sh:>8.2f}{p_wf.get('pnl',0):>10.2f}  {'Y' if is_prof else 'N'}")
    wf_start += timedelta(days=window_days)

avg_test_sharpe = sum(test_sharpes)/len(test_sharpes) if test_sharpes else 0
# Training sharpe is from full training run
print(f"\n  Profitable windows: {profitable_windows}/{total_windows} ({round(profitable_windows/max(total_windows,1)*100,1)}%)")
print(f"  Training Sharpe (full period): {p_train.get('sharpe',0):.2f}")
print(f"  Average test window Sharpe: {avg_test_sharpe:.2f}")
print(f"\n  HIS CLAIM: test Sharpe 1.79 > training Sharpe 0.89")
print(f"  OUR RESULT: training={p_train.get('sharpe',0):.2f}, avg test={avg_test_sharpe:.2f}")

# ═══════════════════════════════════════════════════════════════
# STEP 4 — HOLDOUT WITH HIS SIZING
# ═══════════════════════════════════════════════════════════════
print("\n" + "=" * 60)
print("STEP 4 — HOLDOUT")
print("=" * 60)

holdout_range = {"start": HOLDOUT_DATE, "end": "2026-12-31"}

# v10 holdout
out_h10 = os.path.join(OUT_DIR, "v10_retest_holdout.json")
cfg_h10 = make_config(ASSETS, tf="30m", date_range=holdout_range, output_path=out_h10)
r_h10 = run(cfg_h10, "holdout-v10")
tl_h10 = r_h10.get("trade_log", []) if r_h10 else []
p_h10 = r_h10.get("portfolio", {}) if r_h10 else {}

# Our system holdout
out_hours = os.path.join(OUT_DIR, "v10_retest_holdout_ours.json")
our_h = json.load(open("/tmp/discovery/rust_baseline_config.json"))
our_h["output_path"] = out_hours
our_h["date_range"] = holdout_range
with open(out_hours.replace(".json","_cfg.json"), 'w') as f: json.dump(our_h, f)
subprocess.run([ENGINE, out_hours.replace(".json","_cfg.json")], capture_output=True, timeout=60)
with open(out_hours) as f: r_hours = json.load(f)
tl_hours = r_hours.get("trade_log", [])
p_hours = r_hours.get("portfolio", {})

# His sizing on holdout
sim_h10_his = pct_equity_sim(tl_h10, starting=100000, fraction=0.50, leverage=7.0)
sim_hours_his = pct_equity_sim(tl_hours, starting=100000, fraction=0.50, leverage=7.0)

print(f"""
  His sizing ($100K, 50%, 7x):
                  {'PF':>7}{'P&L':>12}{'Sharpe':>8}{'MDD%':>7}{'Final Eq':>14}
  His v10         {p_h10.get('pf',0):>7.2f}{sim_h10_his['pnl']:>12,.2f}{p_h10.get('sharpe',0):>8.2f}{sim_h10_his['mdd_pct']:>6.1f}%{sim_h10_his['final_equity']:>14,.2f}
  Our system      {p_hours.get('pf',0):>7.2f}{sim_hours_his['pnl']:>12,.2f}{p_hours.get('sharpe',0):>8.2f}{sim_hours_his['mdd_pct']:>6.1f}%{sim_hours_his['final_equity']:>14,.2f}

  $125 flat (pure strategy):
                  {'PF':>7}{'P&L':>10}{'Sharpe':>8}{'MDD%':>7}
  His v10         {p_h10.get('pf',0):>7.2f}{p_h10.get('pnl',0):>10.2f}{p_h10.get('sharpe',0):>8.2f}{p_h10.get('mdd_pct',0):>6.1f}%
  Our system      {p_hours.get('pf',0):>7.2f}{p_hours.get('pnl',0):>10.2f}{p_hours.get('sharpe',0):>8.2f}{p_hours.get('mdd_pct',0):>6.1f}%

  HOLDOUT WINNER: {'Ours' if p_hours.get('sharpe',0) > p_h10.get('sharpe',0) else 'His'}
""")

# ═══════════════════════════════════════════════════════════════
# STEP 5 — MDD REALITY CHECK
# ═══════════════════════════════════════════════════════════════
print("=" * 60)
print("STEP 5 — DRAWDOWN REALITY CHECK AT HIS SIZING")
print("=" * 60)

# Training period MDD
ec = sim_his_sizing["eq_curve"]
peak = 100000; peak_idx = 0; trough_idx = 0; max_dd_val = 0
for i, e in enumerate(ec):
    if e >= peak:
        peak = e; peak_idx = i
    dd = peak - e
    if dd > max_dd_val:
        max_dd_val = dd; trough_idx = i; worst_peak = peak; worst_peak_idx = peak_idx

# Recovery
recovery_idx = None
for i in range(trough_idx, len(ec)):
    if ec[i] >= worst_peak:
        recovery_idx = i; break

print(f"""
  Training period MDD (his sizing, all assets):
    Peak: ${worst_peak:,.2f}
    Trough: ${ec[trough_idx]:,.2f}
    Drawdown: ${max_dd_val:,.2f} ({sim_his_sizing['mdd_pct']:.1f}%)
    Recovery: {'reached peak again' if recovery_idx else 'never recovered'}

  At 7x leverage:
    A 14.3% adverse BTC move liquidates the entire position
    A 10% BTC drop = 70% loss on position margin

  Would you survive this psychologically?
    Starting at $100K, MDD of {sim_his_sizing['mdd_pct']:.1f}%:
    Account drops from ${worst_peak:,.0f} to ${ec[trough_idx]:,.0f}
    That's a ${max_dd_val:,.0f} paper loss
""")

# Holdout MDD
print(f"  Holdout period MDD (his sizing):")
print(f"    v10: {sim_h10_his['mdd_pct']:.1f}% (${sim_h10_his['mdd_usd']:,.2f} from peak)")
print(f"    Our: {sim_hours_his['mdd_pct']:.1f}% (${sim_hours_his['mdd_usd']:,.2f} from peak)")

# ═══════════════════════════════════════════════════════════════
# STEP 6 — FINAL COMPARISON
# ═══════════════════════════════════════════════════════════════
print("\n" + "=" * 72)
print("  V10 RETEST — FINAL COMPARISON")
print("=" * 72)

print(f"""
  TRADE COUNT VERIFICATION:
    His count: 95-96 | Our count (full dataset): {len(tl)} | Our count (his date range): {len(tl_hr)}
    Jan-Feb 2020 trades (ours only): {len(jan_feb_trades)}
    Match: {'CLOSE' if abs(len(tl_hr) - 95) <= 5 else 'NO'} — difference of {abs(len(tl_hr) - 95)} trades

  HIS CLAIMS vs OUR RESULTS:
    Claim: $100K -> $3M (3000%)     Our result: $100K -> ${sim_his_sizing['final_equity']:,.0f} ({(sim_his_sizing['final_equity']/100000-1)*100:.0f}%) {'CONFIRMED' if sim_his_sizing['final_equity'] > 2500000 else 'NOT CONFIRMED'}
    Claim: profitable every year     Our result: {'CONFIRMED' if not losing_years else 'DENIED — lost: ' + ', '.join(losing_years)}
    Claim: 95 trades (BTC)          Our result: {len(tl)} ({len(tl_hr)} on his date range) {'CLOSE MATCH' if abs(len(tl_hr)-95) <= 5 else 'DIFFERS'}
    Claim: WF test > training        Our result: training={p_train.get('sharpe',0):.2f}, avg test={avg_test_sharpe:.2f} {'CONFIRMED' if avg_test_sharpe > p_train.get('sharpe',0) else 'NOT CONFIRMED'}

  AT EQUAL SIZING ($125 flat — the only fair comparison):
    Our system: Sharpe={p_ours.get('sharpe',0):.2f}, PF={p_ours.get('pf',0):.2f}, P&L=${p_ours.get('pnl',0):,.2f}
    His v10:    Sharpe={p_train.get('sharpe',0):.2f}, PF={p_train.get('pf',0):.2f}, P&L=${p_train.get('pnl',0):,.2f}
    Winner: {'Ours' if p_ours.get('sharpe',0) > p_train.get('sharpe',0) else 'His'}

  AT HIS SIZING ($100K, 50%, 7x — applied to BOTH systems):
    Our system: ${sim_ours_his_sizing['final_equity']:,.0f}, MDD={sim_ours_his_sizing['mdd_pct']:.1f}%
    His v10:    ${sim_his_sizing['final_equity']:,.0f}, MDD={sim_his_sizing['mdd_pct']:.1f}%
    Winner: {'Ours' if sim_ours_his_sizing['final_equity'] > sim_his_sizing['final_equity'] else 'His'}

  HOLDOUT ($125 flat):
    Our system: Sharpe={p_hours.get('sharpe',0):.2f}, PF={p_hours.get('pf',0):.2f}
    His v10:    Sharpe={p_h10.get('sharpe',0):.2f}, PF={p_h10.get('pf',0):.2f}
    Winner: {'Ours' if p_hours.get('sharpe',0) > p_h10.get('sharpe',0) else 'His'}

  HOLDOUT (his sizing on both):
    Our system: ${sim_hours_his['final_equity']:,.0f}
    His v10:    ${sim_h10_his['final_equity']:,.0f}
    Winner: {'Ours' if sim_hours_his['final_equity'] > sim_h10_his['final_equity'] else 'His'}

  THE LEVERAGE QUESTION:
    His $3M claim {'is' if sim_his_sizing['final_equity'] > 2500000 else 'is NOT'} reproducible on our data
    The return is {'primarily' if sim_his_sizing['final_equity'] / 100000 > 5 else 'partially'} from 7x leverage amplification
    At $125 flat (no leverage amplification), v10 P&L is only ${p_train.get('pnl',0):,.2f}
    Our system at 7x: ${sim_ours_his_sizing['final_equity']:,.0f} ({'beats' if sim_ours_his_sizing['final_equity'] > sim_his_sizing['final_equity'] else 'loses to'} his ${sim_his_sizing['final_equity']:,.0f})
    MDD at 7x: his={sim_his_sizing['mdd_pct']:.1f}% vs ours={sim_ours_his_sizing['mdd_pct']:.1f}%
""")

# Save results
results = {
    "step0": {"trade_count_full": len(tl), "trade_count_his_range": len(tl_hr),
              "jan_feb_trades": len(jan_feb_trades)},
    "step1": {"btc_his_sizing": {"final_equity": sim_btc["final_equity"], "mdd_pct": sim_btc["mdd_pct"]},
              "yearly": {yr: {"pnl": yearly[yr]["pnl"], "trades": yearly[yr]["trades"]} for yr in yearly}},
    "step2": {"v10_flat": p_train, "ours_flat": p_ours,
              "v10_his_sizing": {"final_equity": sim_his_sizing["final_equity"], "mdd_pct": sim_his_sizing["mdd_pct"]},
              "ours_his_sizing": {"final_equity": sim_ours_his_sizing["final_equity"], "mdd_pct": sim_ours_his_sizing["mdd_pct"]}},
    "step3": {"profitable_windows": profitable_windows, "total_windows": total_windows,
              "train_sharpe": p_train.get("sharpe",0), "avg_test_sharpe": avg_test_sharpe},
    "step4": {"v10_holdout_flat": p_h10, "ours_holdout_flat": p_hours,
              "v10_holdout_his_sizing": {"final_equity": sim_h10_his["final_equity"]},
              "ours_holdout_his_sizing": {"final_equity": sim_hours_his["final_equity"]}},
    "runtime": time.time() - T0,
}
with open(os.path.join(OUT_DIR, "v10_retest.json"), 'w') as f:
    json.dump(results, f, indent=2, default=str)
print(f"\n  All results saved to {OUT_DIR}/v10_retest.json")
print(f"  Runtime: {time.time()-T0:.1f}s")

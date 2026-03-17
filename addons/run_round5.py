#!/usr/bin/env python3
"""Round 5: Validation suite for top 5 configs."""
import sys, json, time, random
sys.path.insert(0, 'addons')
from backtest import *

start_time = time.time()
data = load_all_data(180)
_, split, end = train_test_split(data)
thirds = thirds_split(data)

n15 = len(data['15m'])
train_days = (data['15m'][split-1]['t'] - data['15m'][0]['t']) / 86400000
val_days = (data['15m'][-1]['t'] - data['15m'][split]['t']) / 86400000
print(f"\nData split: {n15} total bars")
print(f"  Training: bars 0-{split} ({train_days:.0f} days)")
print(f"  Validation: bars {split}-{end} ({val_days:.0f} days)")

# The 5 configs advancing
configs = [
    ("RSI + Trailing ST", SimConfig(atr_period=9, multiplier=3.0, source="hl2",
        rsi_enabled=True, rsi_period=7, rsi_buy_min=40, rsi_buy_max=70, rsi_sell_max=60, rsi_sell_min=20,
        trailing_supertrend=True)),
    ("VOL + TOD", SimConfig(atr_period=9, multiplier=3.0, source="hl2",
        volume_enabled=True, volume_min_mult=1.5,
        tod_enabled=True, tod_block_start=0, tod_block_end=6)),
    ("CD + TOD (close)", SimConfig(atr_period=14, multiplier=3.0, source="close",
        cooldown_enabled=True, cooldown_minutes=20, cooldown_override_pct=1.0,
        tod_enabled=True, tod_block_start=0, tod_block_end=6)),
    ("RSI+SQZ+CD (close)", SimConfig(atr_period=14, multiplier=3.0, source="close",
        rsi_enabled=True, rsi_period=7, rsi_buy_min=40, rsi_buy_max=70, rsi_sell_max=60, rsi_sell_min=20,
        sqzmom_enabled=True,
        cooldown_enabled=True, cooldown_minutes=20, cooldown_override_pct=1.0)),
    ("CD+TOD+Trail (close)", SimConfig(atr_period=14, multiplier=3.0, source="close",
        cooldown_enabled=True, cooldown_minutes=20, cooldown_override_pct=1.0,
        tod_enabled=True, tod_block_start=0, tod_block_end=6,
        trailing_supertrend=True)),
]

# ======================================================================
# STEP 1: Training vs Validation
# ======================================================================
print(f"\n{'=' * 120}")
print("STEP 1: WALK-FORWARD VALIDATION (Training vs Holdout)")
print(f"{'=' * 120}")
hdr = f"{'Config':<25} {'Set':>5} {'Trades':>6} {'WR':>6} {'PF':>6} {'PnL':>10} {'DD%':>6} {'Sharpe':>7} {'$/Trade':>8}"
print(hdr)
print("-" * len(hdr))

validation_results = {}
for name, cfg in configs:
    train_r = run_simulation(cfg, data, 0, split)
    val_r = run_simulation(cfg, data, split, end)
    full_r = run_simulation(cfg, data, 0, end)
    validation_results[name] = {"train": train_r, "val": val_r, "full": full_r, "cfg": cfg}

    for label, r in [("TRAIN", train_r), ("VAL", val_r), ("FULL", full_r)]:
        n = name if label == "TRAIN" else ""
        print(f"{n:<25} {label:>5} {r.total_trades:>6} {r.win_rate:>5.1f}% {r.profit_factor:>6.2f} ${r.net_pnl:>9.2f} {r.max_drawdown_pct:>5.1f}% {r.sharpe_ratio:>7.2f} ${r.avg_trade_pnl:>7.2f}")
    status = "PASS" if val_r.net_pnl > 0 else "FAIL"
    print(f"{'':25} {'':>5} {'':>6} {'':>6} {'':>6} {'':>10} {'':>6} {'':>7} [{status}]")
    print()

# ======================================================================
# STEP 2: Thirds test
# ======================================================================
print(f"\n{'=' * 120}")
print("STEP 2: THIRDS TEST (profitable in each third of data?)")
print(f"{'=' * 120}")
print(f"{'Config':<25} {'Third':>6} {'Trades':>6} {'WR':>6} {'PF':>6} {'PnL':>10} {'Status':>8}")
print("-" * 70)

thirds_results = {}
for name, cfg in configs:
    thirds_results[name] = []
    all_pass = True
    for idx, (s, e) in enumerate(thirds):
        label = ["1st", "2nd", "3rd"][idx]
        r = run_simulation(cfg, data, s, e)
        passed = r.net_pnl > 0
        if not passed:
            all_pass = False
        thirds_results[name].append(r)
        status = "OK" if passed else "FAIL"
        n = name if idx == 0 else ""
        print(f"{n:<25} {label:>6} {r.total_trades:>6} {r.win_rate:>5.1f}% {r.profit_factor:>6.2f} ${r.net_pnl:>9.2f} {status:>8}")
    verdict = "ALL PASS" if all_pass else "PARTIAL"
    print(f"{'':25} {'':>6} {'':>6} {'':>6} {'':>6} {'':>10} [{verdict}]")
    print()

# ======================================================================
# STEP 3: Robustness (+/- 10% parameter variation)
# ======================================================================
print(f"\n{'=' * 120}")
print("STEP 3: ROBUSTNESS CHECK (+/- 10% parameter variation on full data)")
print(f"{'=' * 120}")
print(f"{'Config':<25} {'Variant':>10} {'Trades':>6} {'WR':>6} {'PF':>6} {'PnL':>10} {'DD%':>6} {'Status':>8}")
print("-" * 85)

robustness_results = {}
for name, cfg in configs:
    robustness_results[name] = {"pass": True, "variants": []}

    base_r = validation_results[name]["full"]
    print(f"{name:<25} {'baseline':>10} {base_r.total_trades:>6} {base_r.win_rate:>5.1f}% {base_r.profit_factor:>6.2f} ${base_r.net_pnl:>9.2f} {base_r.max_drawdown_pct:>5.1f}%")

    variations = [
        ("ATR-10%", max(5, round(cfg.atr_period * 0.9)), round(cfg.multiplier, 2)),
        ("ATR+10%", round(cfg.atr_period * 1.1), round(cfg.multiplier, 2)),
        ("Mult-10%", cfg.atr_period, round(cfg.multiplier * 0.9, 2)),
        ("Mult+10%", cfg.atr_period, round(cfg.multiplier * 1.1, 2)),
        ("Both-10%", max(5, round(cfg.atr_period * 0.9)), round(cfg.multiplier * 0.9, 2)),
        ("Both+10%", round(cfg.atr_period * 1.1), round(cfg.multiplier * 1.1, 2)),
    ]

    for vlabel, vatr, vmult in variations:
        vcfg = SimConfig(**{k: v for k, v in cfg.__dict__.items()})
        vcfg.atr_period = vatr
        vcfg.multiplier = vmult
        vr = run_simulation(vcfg, data, 0, end)
        passed = vr.net_pnl > 0
        if not passed:
            robustness_results[name]["pass"] = False
        robustness_results[name]["variants"].append(vr)
        status = "OK" if passed else "FAIL"
        pnl_delta = vr.net_pnl - base_r.net_pnl
        print(f"{'':25} {vlabel:>10} {vr.total_trades:>6} {vr.win_rate:>5.1f}% {vr.profit_factor:>6.2f} ${vr.net_pnl:>9.2f} {vr.max_drawdown_pct:>5.1f}% {status:>8} (delta ${pnl_delta:>+.0f})")

    verdict = "ROBUST" if robustness_results[name]["pass"] else "FRAGILE"
    print(f"{'':25} {'':>10} {'':>6} {'':>6} {'':>6} {'':>10} {'':>6} [{verdict}]")
    print()

# ======================================================================
# STEP 4: Monte Carlo
# ======================================================================
print(f"\n{'=' * 120}")
print("STEP 4: MONTE CARLO SIMULATION (1000 iterations, full data trades)")
print(f"{'=' * 120}")

mc_results = {}
for name, cfg in configs:
    full_r = validation_results[name]["full"]
    if not full_r.trades:
        print(f"  {name}: No trades")
        continue

    pnls = [t["pnl"] for t in full_r.trades]
    n_trades = len(pnls)
    iterations = 1000

    final_equities = []
    max_drawdowns = []

    for _ in range(iterations):
        shuffled = pnls.copy()
        random.shuffle(shuffled)
        eq = STARTING_CAPITAL
        hw = eq
        max_dd = 0
        for p in shuffled:
            eq += p
            hw = max(hw, eq)
            dd = (hw - eq) / hw * 100 if hw > 0 else 0
            max_dd = max(max_dd, dd)
        final_equities.append(eq)
        max_drawdowns.append(max_dd)

    final_equities.sort()
    max_drawdowns.sort()

    def prob_profit_at_n(n_check, iters=2000):
        count = 0
        for _ in range(iters):
            subset = random.choices(pnls, k=min(n_check, n_trades))
            if sum(subset) > 0:
                count += 1
        return count / iters * 100

    mc = {
        "total_trades": n_trades,
        "median_final_eq": final_equities[iterations // 2],
        "median_pnl": final_equities[iterations // 2] - STARTING_CAPITAL,
        "p5_pnl": final_equities[int(iterations * 0.05)] - STARTING_CAPITAL,
        "p25_pnl": final_equities[int(iterations * 0.25)] - STARTING_CAPITAL,
        "p75_pnl": final_equities[int(iterations * 0.75)] - STARTING_CAPITAL,
        "p95_pnl": final_equities[int(iterations * 0.95)] - STARTING_CAPITAL,
        "max_dd_median": max_drawdowns[iterations // 2],
        "max_dd_p95": max_drawdowns[int(iterations * 0.95)],
        "prob_profit_20": prob_profit_at_n(20),
        "prob_profit_50": prob_profit_at_n(50),
        "prob_profit_100": prob_profit_at_n(100),
        "prob_profit_200": prob_profit_at_n(200),
    }
    mc_results[name] = mc

    print(f"\n  {name} ({n_trades} trades)")
    print(f"  {'_' * 60}")
    print(f"  Final equity distribution:")
    print(f"    5th percentile (worst):  ${mc['p5_pnl']:>+10.2f}  (equity ${STARTING_CAPITAL + mc['p5_pnl']:.2f})")
    print(f"    25th percentile:         ${mc['p25_pnl']:>+10.2f}")
    print(f"    Median:                  ${mc['median_pnl']:>+10.2f}")
    print(f"    75th percentile:         ${mc['p75_pnl']:>+10.2f}")
    print(f"    95th percentile (best):  ${mc['p95_pnl']:>+10.2f}")
    print(f"  Max drawdown:")
    print(f"    Median:                  {mc['max_dd_median']:>10.1f}%")
    print(f"    95th percentile (worst): {mc['max_dd_p95']:>10.1f}%")
    print(f"  Probability of profit:")
    print(f"    After 20 trades:         {mc['prob_profit_20']:>10.1f}%")
    print(f"    After 50 trades:         {mc['prob_profit_50']:>10.1f}%")
    print(f"    After 100 trades:        {mc['prob_profit_100']:>10.1f}%")
    print(f"    After 200 trades:        {mc['prob_profit_200']:>10.1f}%")

# ======================================================================
# STEP 5: Monthly P&L
# ======================================================================
print(f"\n{'=' * 120}")
print("STEP 5: MONTHLY P&L BREAKDOWN (full data)")
print(f"{'=' * 120}")

for name, cfg in configs:
    full_r = validation_results[name]["full"]
    if full_r.monthly_pnl:
        print(f"\n  {name}:")
        for month, pnl in sorted(full_r.monthly_pnl.items()):
            bar_len = int(abs(pnl) / 20)
            bar = ("+" * bar_len) if pnl > 0 else ("-" * bar_len)
            sign = "+" if pnl > 0 else ""
            print(f"    {month}: ${sign}{pnl:>8.2f}  {bar}")

# ======================================================================
# SUMMARY SCORECARD
# ======================================================================
print(f"\n{'=' * 120}")
print("VALIDATION SCORECARD")
print(f"{'=' * 120}")
print(f"{'Config':<25} {'Val PnL':>8} {'ValPass':>8} {'Thirds':>7} {'Robust':>7} {'MC P100':>8} {'MC DD95':>8} {'Score':>6}")
print("-" * 80)

for name, cfg in configs:
    vr = validation_results[name]
    val_pass = vr["val"].net_pnl > 0
    thirds_pass = all(r.net_pnl > 0 for r in thirds_results[name])
    robust = robustness_results[name]["pass"]
    mc = mc_results.get(name, {})
    mc_prob = mc.get("prob_profit_100", 0)
    mc_dd = mc.get("max_dd_p95", 99)

    score = 0
    if val_pass: score += 2
    if thirds_pass: score += 2
    if robust: score += 2
    if mc_prob >= 60: score += 2
    if mc_dd < 15: score += 1
    if vr["full"].profit_factor >= 2.0: score += 1

    val_label = "PASS" if val_pass else "FAIL"
    thirds_label = "PASS" if thirds_pass else "FAIL"
    robust_label = "PASS" if robust else "FAIL"

    print(f"{name:<25} ${vr['val'].net_pnl:>7.2f} {val_label:>8} {thirds_label:>7} {robust_label:>7} {mc_prob:>7.1f}% {mc_dd:>7.1f}% {score:>5}/10")

# Save
save_data = {}
for name, cfg in configs:
    vr = validation_results[name]
    mc = mc_results.get(name, {})
    save_data[name] = {
        "config": vr["full"].config,
        "config_name": vr["full"].config_name,
        "training": {"trades": vr["train"].total_trades, "pf": vr["train"].profit_factor, "pnl": vr["train"].net_pnl, "win_rate": vr["train"].win_rate, "max_dd": vr["train"].max_drawdown_pct, "sharpe": vr["train"].sharpe_ratio},
        "validation": {"trades": vr["val"].total_trades, "pf": vr["val"].profit_factor, "pnl": vr["val"].net_pnl, "win_rate": vr["val"].win_rate, "max_dd": vr["val"].max_drawdown_pct, "sharpe": vr["val"].sharpe_ratio},
        "full": {"trades": vr["full"].total_trades, "pf": vr["full"].profit_factor, "pnl": vr["full"].net_pnl, "win_rate": vr["full"].win_rate, "max_dd": vr["full"].max_drawdown_pct, "sharpe": vr["full"].sharpe_ratio},
        "thirds_pass": all(r.net_pnl > 0 for r in thirds_results[name]),
        "robust_pass": robustness_results[name]["pass"],
        "monte_carlo": mc,
    }

with open(RESULTS_DIR / "round5_validation.json", "w") as f:
    json.dump(save_data, f, indent=2)

elapsed = time.time() - start_time
print(f"\nRound 5 completed in {elapsed:.0f}s")
print(f"Results saved to round5_validation.json")

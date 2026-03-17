#!/usr/bin/env python3
"""
Step 2: Individual filter testing on top 10 baseline configs.
Test each filter type individually, train 70% / validate 30%.
"""

import json
import time
import numpy as np
from pathlib import Path
from copy import deepcopy

from engine import BacktestConfig, run_backtest, result_to_dict

DATA_DIR = Path(__file__).parent.parent / "backtest-data"
OUTPUT_DIR = Path(__file__).parent

# Top 10 from Step 1
TOP10_CONFIGS = [
    (8, 4.0, "hlc3"),
    (7, 4.0, "close"),
    (11, 4.0, "close"),
    (10, 4.0, "close"),
    (9, 4.0, "close"),
    (8, 4.0, "close"),
    (12, 4.0, "close"),
    (9, 4.0, "hl2"),
    (11, 4.0, "hl2"),
    (12, 4.0, "hl2"),
]

# Filter variations to test
RSI_FILTERS = [
    # (period, buy_low, buy_high, sell_low, sell_high)
    (7, 30, 70, 30, 70),
    (7, 35, 70, 30, 65),
    (7, 40, 70, 30, 60),
    (7, 40, 75, 25, 60),
    (7, 45, 70, 30, 55),
    (7, 50, 70, 30, 50),
    (7, 50, 80, 20, 50),
    (9, 30, 70, 30, 70),
    (9, 35, 70, 30, 65),
    (9, 40, 70, 30, 60),
    (9, 45, 70, 30, 55),
    (9, 50, 70, 30, 50),
    (14, 30, 70, 30, 70),
    (14, 35, 70, 30, 65),
    (14, 40, 70, 30, 60),
    (14, 45, 70, 30, 55),
    (14, 50, 70, 30, 50),
    (14, 50, 80, 20, 50),
]

VOLUME_FILTERS = [
    # threshold multiplier
    1.0, 1.25, 1.5, 2.0,
]

TIME_FILTERS = [
    # (block_start, block_end)
    (0, 4),
    (0, 6),
    (0, 8),
    (22, 6),  # wraps midnight
]

COOLDOWN_FILTERS = [
    # (bars, override_pct)
    (1, 0.01),   # 15min cooldown
    (2, 0.01),   # 30min cooldown
    (4, 0.01),   # 1hr cooldown
    (8, 0.01),   # 2hr cooldown
]


def run_config_pair(opens, highs, lows, closes, volumes, timestamps, config, train_end, val_end):
    """Run train + validate for a config."""
    train_result = run_backtest(opens, highs, lows, closes, volumes, timestamps,
                                config, start_bar=0, end_bar=train_end)

    val_config = deepcopy(config)
    val_config.warmup = max(200, train_end)
    val_result = run_backtest(opens, highs, lows, closes, volumes, timestamps,
                              val_config, start_bar=train_end, end_bar=val_end)

    return train_result, val_result


def main():
    print("=" * 70)
    print("STEP 2: INDIVIDUAL FILTER TESTING")
    print("=" * 70)

    # Load data
    with open(DATA_DIR / "binance_btc_15m.json") as f:
        klines = json.load(f)

    opens = np.array([k["open"] for k in klines], dtype=np.float64)
    highs = np.array([k["high"] for k in klines], dtype=np.float64)
    lows = np.array([k["low"] for k in klines], dtype=np.float64)
    closes = np.array([k["close"] for k in klines], dtype=np.float64)
    volumes = np.array([k["volume"] for k in klines], dtype=np.float64)
    timestamps = np.array([k["open_time"] for k in klines], dtype=np.int64)

    n = len(closes)
    train_end = int(n * 0.7)
    val_end = n

    all_filter_results = {}
    start_time = time.time()

    # ═══════════════════════════════════════════════════════════
    # BASELINE (no filters) for comparison
    # ═══════════════════════════════════════════════════════════
    print("\n  Running baselines for top 10...")
    baselines = {}
    for atr_p, mult, src in TOP10_CONFIGS:
        config = BacktestConfig(atr_period=atr_p, multiplier=mult, source=src)
        _, val = run_config_pair(opens, highs, lows, closes, volumes, timestamps, config, train_end, val_end)
        baselines[(atr_p, mult, src)] = result_to_dict(val)

    # ═══════════════════════════════════════════════════════════
    # RSI FILTER
    # ═══════════════════════════════════════════════════════════
    rsi_results = []
    total_rsi = len(TOP10_CONFIGS) * len(RSI_FILTERS)
    print(f"\n  Testing RSI filters: {total_rsi} combinations...")

    count = 0
    for atr_p, mult, src in TOP10_CONFIGS:
        for rsi_p, bl, bh, sl, sh in RSI_FILTERS:
            config = BacktestConfig(
                atr_period=atr_p, multiplier=mult, source=src,
                rsi_enabled=True, rsi_period=rsi_p,
                rsi_buy_low=bl, rsi_buy_high=bh,
                rsi_sell_low=sl, rsi_sell_high=sh,
            )
            _, val = run_config_pair(opens, highs, lows, closes, volumes, timestamps, config, train_end, val_end)
            vd = result_to_dict(val)

            base = baselines[(atr_p, mult, src)]
            pf_improvement = vd["profit_factor"] - base["profit_factor"]

            rsi_results.append({
                "base": {"atr_period": atr_p, "multiplier": mult, "source": src},
                "filter": {"rsi_period": rsi_p, "buy": [bl, bh], "sell": [sl, sh]},
                "validate": vd,
                "pf_improvement": round(pf_improvement, 4),
            })
            count += 1
            if count % 50 == 0:
                print(f"    [{count}/{total_rsi}]")

    all_filter_results["rsi"] = rsi_results

    # ═══════════════════════════════════════════════════════════
    # VOLUME FILTER
    # ═══════════════════════════════════════════════════════════
    vol_results = []
    total_vol = len(TOP10_CONFIGS) * len(VOLUME_FILTERS)
    print(f"\n  Testing Volume filters: {total_vol} combinations...")

    for atr_p, mult, src in TOP10_CONFIGS:
        for thresh in VOLUME_FILTERS:
            config = BacktestConfig(
                atr_period=atr_p, multiplier=mult, source=src,
                volume_enabled=True, volume_threshold=thresh,
            )
            _, val = run_config_pair(opens, highs, lows, closes, volumes, timestamps, config, train_end, val_end)
            vd = result_to_dict(val)

            base = baselines[(atr_p, mult, src)]
            pf_improvement = vd["profit_factor"] - base["profit_factor"]

            vol_results.append({
                "base": {"atr_period": atr_p, "multiplier": mult, "source": src},
                "filter": {"volume_threshold": thresh},
                "validate": vd,
                "pf_improvement": round(pf_improvement, 4),
            })

    all_filter_results["volume"] = vol_results

    # ═══════════════════════════════════════════════════════════
    # TIME-OF-DAY FILTER
    # ═══════════════════════════════════════════════════════════
    time_results = []
    total_time = len(TOP10_CONFIGS) * len(TIME_FILTERS)
    print(f"\n  Testing Time-of-day filters: {total_time} combinations...")

    for atr_p, mult, src in TOP10_CONFIGS:
        for block_start, block_end in TIME_FILTERS:
            config = BacktestConfig(
                atr_period=atr_p, multiplier=mult, source=src,
                time_filter_enabled=True,
                time_block_start=block_start, time_block_end=block_end,
            )
            _, val = run_config_pair(opens, highs, lows, closes, volumes, timestamps, config, train_end, val_end)
            vd = result_to_dict(val)

            base = baselines[(atr_p, mult, src)]
            pf_improvement = vd["profit_factor"] - base["profit_factor"]

            time_results.append({
                "base": {"atr_period": atr_p, "multiplier": mult, "source": src},
                "filter": {"block_start": block_start, "block_end": block_end},
                "validate": vd,
                "pf_improvement": round(pf_improvement, 4),
            })

    all_filter_results["time"] = time_results

    # ═══════════════════════════════════════════════════════════
    # COOLDOWN FILTER
    # ═══════════════════════════════════════════════════════════
    cd_results = []
    total_cd = len(TOP10_CONFIGS) * len(COOLDOWN_FILTERS)
    print(f"\n  Testing Cooldown filters: {total_cd} combinations...")

    for atr_p, mult, src in TOP10_CONFIGS:
        for cd_bars, cd_override in COOLDOWN_FILTERS:
            config = BacktestConfig(
                atr_period=atr_p, multiplier=mult, source=src,
                cooldown_enabled=True,
                cooldown_bars=cd_bars, cooldown_override_pct=cd_override,
            )
            _, val = run_config_pair(opens, highs, lows, closes, volumes, timestamps, config, train_end, val_end)
            vd = result_to_dict(val)

            base = baselines[(atr_p, mult, src)]
            pf_improvement = vd["profit_factor"] - base["profit_factor"]

            cd_results.append({
                "base": {"atr_period": atr_p, "multiplier": mult, "source": src},
                "filter": {"cooldown_bars": cd_bars, "override_pct": cd_override},
                "validate": vd,
                "pf_improvement": round(pf_improvement, 4),
            })

    all_filter_results["cooldown"] = cd_results

    elapsed = time.time() - start_time
    print(f"\n  All filters tested in {elapsed:.1f}s")

    # ═══════════════════════════════════════════════════════════
    # ANALYSIS — rank filters by avg improvement to validation PF
    # ═══════════════════════════════════════════════════════════
    print("\n" + "=" * 70)
    print("FILTER RANKING BY AVERAGE VALIDATION PF IMPROVEMENT")
    print("=" * 70)

    # RSI — group by filter params, average improvement across base configs
    print("\n── RSI FILTERS ──")
    rsi_grouped = {}
    for r in rsi_results:
        key = json.dumps(r["filter"], sort_keys=True)
        if key not in rsi_grouped:
            rsi_grouped[key] = []
        rsi_grouped[key].append(r["pf_improvement"])

    rsi_ranked = sorted(rsi_grouped.items(), key=lambda x: np.mean(x[1]), reverse=True)
    print(f"  {'Filter':>50s} | {'Avg PF Imp':>10s} {'Min':>8s} {'Max':>8s} {'Improved':>8s}")
    for key, imps in rsi_ranked[:10]:
        filt = json.loads(key)
        improved = sum(1 for x in imps if x > 0)
        print(f"  RSI({filt['rsi_period']}) buy={filt['buy']} sell={filt['sell']:>16s} | "
              f"{np.mean(imps):>10.4f} {min(imps):>8.4f} {max(imps):>8.4f} {improved:>5d}/10")

    # Volume
    print("\n── VOLUME FILTERS ──")
    vol_grouped = {}
    for r in vol_results:
        key = json.dumps(r["filter"], sort_keys=True)
        if key not in vol_grouped:
            vol_grouped[key] = []
        vol_grouped[key].append(r["pf_improvement"])

    vol_ranked = sorted(vol_grouped.items(), key=lambda x: np.mean(x[1]), reverse=True)
    print(f"  {'Filter':>25s} | {'Avg PF Imp':>10s} {'Min':>8s} {'Max':>8s} {'Improved':>8s}")
    for key, imps in vol_ranked:
        filt = json.loads(key)
        improved = sum(1 for x in imps if x > 0)
        print(f"  Volume > {filt['volume_threshold']}x avg{' ':>10s} | "
              f"{np.mean(imps):>10.4f} {min(imps):>8.4f} {max(imps):>8.4f} {improved:>5d}/10")

    # Time
    print("\n── TIME-OF-DAY FILTERS ──")
    time_grouped = {}
    for r in time_results:
        key = json.dumps(r["filter"], sort_keys=True)
        if key not in time_grouped:
            time_grouped[key] = []
        time_grouped[key].append(r["pf_improvement"])

    time_ranked = sorted(time_grouped.items(), key=lambda x: np.mean(x[1]), reverse=True)
    print(f"  {'Filter':>25s} | {'Avg PF Imp':>10s} {'Min':>8s} {'Max':>8s} {'Improved':>8s}")
    for key, imps in time_ranked:
        filt = json.loads(key)
        improved = sum(1 for x in imps if x > 0)
        print(f"  Block {filt['block_start']:02d}-{filt['block_end']:02d} UTC{' ':>8s} | "
              f"{np.mean(imps):>10.4f} {min(imps):>8.4f} {max(imps):>8.4f} {improved:>5d}/10")

    # Cooldown
    print("\n── COOLDOWN FILTERS ──")
    cd_grouped = {}
    for r in cd_results:
        key = json.dumps(r["filter"], sort_keys=True)
        if key not in cd_grouped:
            cd_grouped[key] = []
        cd_grouped[key].append(r["pf_improvement"])

    cd_ranked = sorted(cd_grouped.items(), key=lambda x: np.mean(x[1]), reverse=True)
    print(f"  {'Filter':>25s} | {'Avg PF Imp':>10s} {'Min':>8s} {'Max':>8s} {'Improved':>8s}")
    for key, imps in cd_ranked:
        filt = json.loads(key)
        bars = filt["cooldown_bars"]
        mins = bars * 15
        improved = sum(1 for x in imps if x > 0)
        print(f"  {mins}min cooldown{' ':>10s} | "
              f"{np.mean(imps):>10.4f} {min(imps):>8.4f} {max(imps):>8.4f} {improved:>5d}/10")

    # ─── Overall best filter from each category ───
    print("\n" + "=" * 70)
    print("TOP 3 FILTERS FOR STEP 3")
    print("=" * 70)

    # Collect best from each category
    all_best = []
    if rsi_ranked:
        best_rsi = json.loads(rsi_ranked[0][0])
        all_best.append(("RSI", best_rsi, np.mean(rsi_ranked[0][1])))
        print(f"  #1 RSI({best_rsi['rsi_period']}) buy={best_rsi['buy']} sell={best_rsi['sell']} — avg PF improvement: {np.mean(rsi_ranked[0][1]):.4f}")

    if vol_ranked:
        best_vol = json.loads(vol_ranked[0][0])
        all_best.append(("Volume", best_vol, np.mean(vol_ranked[0][1])))
        print(f"  #2 Volume > {best_vol['volume_threshold']}x avg — avg PF improvement: {np.mean(vol_ranked[0][1]):.4f}")

    if time_ranked:
        best_time = json.loads(time_ranked[0][0])
        all_best.append(("Time", best_time, np.mean(time_ranked[0][1])))
        print(f"  #3 Block {best_time['block_start']:02d}-{best_time['block_end']:02d} UTC — avg PF improvement: {np.mean(time_ranked[0][1]):.4f}")

    if cd_ranked:
        best_cd = json.loads(cd_ranked[0][0])
        all_best.append(("Cooldown", best_cd, np.mean(cd_ranked[0][1])))
        print(f"  #4 {best_cd['cooldown_bars']*15}min cooldown — avg PF improvement: {np.mean(cd_ranked[0][1]):.4f}")

    # Sort by improvement
    all_best.sort(key=lambda x: x[2], reverse=True)
    top3_filters = all_best[:3]
    print(f"\n  Selected top 3: {[f[0] for f in top3_filters]}")

    # Save results
    output_path = OUTPUT_DIR / "step2_filters.json"
    with open(output_path, "w") as f:
        json.dump({
            "baselines": {f"ST({a},{m},{s})": baselines[(a,m,s)] for a,m,s in TOP10_CONFIGS},
            "rsi_top5": [{"filter": json.loads(k), "avg_improvement": round(np.mean(v), 4)} for k, v in rsi_ranked[:5]],
            "volume_ranked": [{"filter": json.loads(k), "avg_improvement": round(np.mean(v), 4)} for k, v in vol_ranked],
            "time_ranked": [{"filter": json.loads(k), "avg_improvement": round(np.mean(v), 4)} for k, v in time_ranked],
            "cooldown_ranked": [{"filter": json.loads(k), "avg_improvement": round(np.mean(v), 4)} for k, v in cd_ranked],
            "top3_filters": [{"type": f[0], "params": f[1], "avg_improvement": round(f[2], 4)} for f in top3_filters],
            "all_results": all_filter_results,
        }, f, indent=2)
    print(f"\n  Results saved to {output_path}")


if __name__ == "__main__":
    main()

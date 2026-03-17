#!/usr/bin/env python3
"""
Step 1: Baseline Supertrend parameter sweep.
231 combinations, walk-forward train 70% / validate 30%.
No filters, no trailing stop — pure Supertrend flip.
"""

import json
import time
import numpy as np
from pathlib import Path
from itertools import product
from concurrent.futures import ProcessPoolExecutor, as_completed
import multiprocessing

from engine import BacktestConfig, run_backtest, result_to_dict

DATA_DIR = Path(__file__).parent.parent / "backtest-data"
OUTPUT_DIR = Path(__file__).parent

# Parameter grid
ATR_PERIODS = [7, 8, 9, 10, 11, 12, 14]
MULTIPLIERS = [1.0, 1.3, 1.5, 1.8, 2.0, 2.2, 2.5, 2.8, 3.0, 3.5, 4.0]
SOURCES = ["hl2", "hlc3", "close"]


def run_single_config(args):
    """Run a single config on both train and validation sets."""
    opens, highs, lows, closes, volumes, timestamps, atr_p, mult, src, train_end, val_end = args

    config = BacktestConfig(
        atr_period=atr_p,
        multiplier=mult,
        source=src,
    )

    # Train: bars [0, train_end)
    train_result = run_backtest(opens, highs, lows, closes, volumes, timestamps,
                                config, start_bar=0, end_bar=train_end)

    # Validate: bars [train_end, val_end)
    # Need to compute indicators from beginning for accuracy, but only trade in validation window
    val_config = BacktestConfig(
        atr_period=atr_p,
        multiplier=mult,
        source=src,
        warmup=max(200, train_end),  # skip all training bars
    )
    val_result = run_backtest(opens, highs, lows, closes, volumes, timestamps,
                              val_config, start_bar=train_end, end_bar=val_end)

    return {
        "params": {"atr_period": atr_p, "multiplier": mult, "source": src},
        "train": result_to_dict(train_result),
        "validate": result_to_dict(val_result),
        "overfit": train_result.total_pnl > 0 and val_result.total_pnl <= 0,
    }


def main():
    print("=" * 70)
    print("STEP 1: BASELINE SUPERTREND PARAMETER SWEEP")
    print(f"  {len(ATR_PERIODS)} ATR periods x {len(MULTIPLIERS)} multipliers x {len(SOURCES)} sources")
    print(f"  = {len(ATR_PERIODS) * len(MULTIPLIERS) * len(SOURCES)} combinations")
    print("  Walk-forward: 70% train, 30% validate")
    print("  No filters, standard Supertrend flip exit")
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

    from datetime import datetime, timezone
    train_start_dt = datetime.fromtimestamp(timestamps[0]/1000, tz=timezone.utc)
    train_end_dt = datetime.fromtimestamp(timestamps[train_end-1]/1000, tz=timezone.utc)
    val_start_dt = datetime.fromtimestamp(timestamps[train_end]/1000, tz=timezone.utc)
    val_end_dt = datetime.fromtimestamp(timestamps[-1]/1000, tz=timezone.utc)

    print(f"\n  Total bars: {n}")
    print(f"  Train: bars 0-{train_end-1} ({train_start_dt.strftime('%Y-%m-%d')} to {train_end_dt.strftime('%Y-%m-%d')})")
    print(f"  Valid: bars {train_end}-{val_end-1} ({val_start_dt.strftime('%Y-%m-%d')} to {val_end_dt.strftime('%Y-%m-%d')})")

    # Build parameter combinations
    combos = list(product(ATR_PERIODS, MULTIPLIERS, SOURCES))
    print(f"\n  Running {len(combos)} combinations...")

    start_time = time.time()
    results = []

    # Run sequentially (numpy arrays can't be pickled easily across processes for this)
    for idx, (atr_p, mult, src) in enumerate(combos):
        args = (opens, highs, lows, closes, volumes, timestamps, atr_p, mult, src, train_end, val_end)
        r = run_single_config(args)
        results.append(r)

        if (idx + 1) % 50 == 0 or idx == len(combos) - 1:
            elapsed = time.time() - start_time
            rate = (idx + 1) / elapsed
            remaining = (len(combos) - idx - 1) / rate if rate > 0 else 0
            print(f"  [{idx+1}/{len(combos)}] {elapsed:.0f}s elapsed, ~{remaining:.0f}s remaining")

    elapsed = time.time() - start_time
    print(f"\n  Completed {len(results)} backtests in {elapsed:.1f}s")

    # ─── Analysis ───
    print("\n" + "=" * 70)
    print("RESULTS — SORTED BY VALIDATION SET PERFORMANCE")
    print("=" * 70)

    # Flag low confidence
    for r in results:
        r["low_confidence"] = bool(r["validate"]["num_trades"] < 50)
        r["overfit"] = bool(r["overfit"])

    # Count overfit
    overfit_count = sum(1 for r in results if r["overfit"])
    profitable_val = sum(1 for r in results if r["validate"]["total_pnl"] > 0)
    print(f"\n  Profitable on validation: {profitable_val}/{len(results)}")
    print(f"  Overfit (train +, val -): {overfit_count}/{len(results)}")

    # ─── Top 20 by Validation Profit Factor ───
    sorted_pf = sorted(results, key=lambda r: r["validate"]["profit_factor"], reverse=True)
    print("\n" + "-" * 100)
    print("TOP 20 BY VALIDATION PROFIT FACTOR")
    print("-" * 100)
    print(f"  {'ATR':>3s} {'Mult':>4s} {'Src':>5s} | {'Val PF':>7s} {'Val P&L':>9s} {'Val Win%':>8s} {'Val #':>5s} {'Val Sharpe':>10s} {'Val MDD%':>8s} | {'Train PF':>8s} {'Train P&L':>10s} {'Overfit':>7s} {'LowConf':>7s}")

    for r in sorted_pf[:20]:
        p = r["params"]
        v = r["validate"]
        t = r["train"]
        flag = "OVERFIT" if r["overfit"] else ""
        lc = "LOW" if r["low_confidence"] else ""
        print(f"  {p['atr_period']:>3d} {p['multiplier']:>4.1f} {p['source']:>5s} | "
              f"{v['profit_factor']:>7.2f} {v['total_pnl']:>9.2f} {v['win_rate']:>7.1f}% {v['num_trades']:>5d} {v['sharpe_ratio']:>10.2f} {v['max_drawdown_pct']:>7.1f}% | "
              f"{t['profit_factor']:>8.2f} {t['total_pnl']:>10.2f} {flag:>7s} {lc:>7s}")

    # ─── Top 20 by Validation P&L ───
    sorted_pnl = sorted(results, key=lambda r: r["validate"]["total_pnl"], reverse=True)
    print("\n" + "-" * 100)
    print("TOP 20 BY VALIDATION P&L")
    print("-" * 100)
    print(f"  {'ATR':>3s} {'Mult':>4s} {'Src':>5s} | {'Val PF':>7s} {'Val P&L':>9s} {'Val Win%':>8s} {'Val #':>5s} {'Val Sharpe':>10s} {'Val MDD%':>8s} | {'Train PF':>8s} {'Train P&L':>10s} {'Overfit':>7s} {'LowConf':>7s}")

    for r in sorted_pnl[:20]:
        p = r["params"]
        v = r["validate"]
        t = r["train"]
        flag = "OVERFIT" if r["overfit"] else ""
        lc = "LOW" if r["low_confidence"] else ""
        print(f"  {p['atr_period']:>3d} {p['multiplier']:>4.1f} {p['source']:>5s} | "
              f"{v['profit_factor']:>7.2f} {v['total_pnl']:>9.2f} {v['win_rate']:>7.1f}% {v['num_trades']:>5d} {v['sharpe_ratio']:>10.2f} {v['max_drawdown_pct']:>7.1f}% | "
              f"{t['profit_factor']:>8.2f} {t['total_pnl']:>10.2f} {flag:>7s} {lc:>7s}")

    # ─── Top 20 by Validation Sharpe ───
    sorted_sharpe = sorted(results, key=lambda r: r["validate"]["sharpe_ratio"], reverse=True)
    print("\n" + "-" * 100)
    print("TOP 20 BY VALIDATION SHARPE RATIO")
    print("-" * 100)
    print(f"  {'ATR':>3s} {'Mult':>4s} {'Src':>5s} | {'Val PF':>7s} {'Val P&L':>9s} {'Val Win%':>8s} {'Val #':>5s} {'Val Sharpe':>10s} {'Val MDD%':>8s} | {'Train PF':>8s} {'Train P&L':>10s} {'Overfit':>7s} {'LowConf':>7s}")

    for r in sorted_sharpe[:20]:
        p = r["params"]
        v = r["validate"]
        t = r["train"]
        flag = "OVERFIT" if r["overfit"] else ""
        lc = "LOW" if r["low_confidence"] else ""
        print(f"  {p['atr_period']:>3d} {p['multiplier']:>4.1f} {p['source']:>5s} | "
              f"{v['profit_factor']:>7.2f} {v['total_pnl']:>9.2f} {v['win_rate']:>7.1f}% {v['num_trades']:>5d} {v['sharpe_ratio']:>10.2f} {v['max_drawdown_pct']:>7.1f}% | "
              f"{t['profit_factor']:>8.2f} {t['total_pnl']:>10.2f} {flag:>7s} {lc:>7s}")

    # ─── Bottom 10 (worst performing on validation) ───
    print("\n" + "-" * 100)
    print("BOTTOM 10 (WORST VALIDATION PERFORMANCE)")
    print("-" * 100)
    print(f"  {'ATR':>3s} {'Mult':>4s} {'Src':>5s} | {'Val PF':>7s} {'Val P&L':>9s} {'Val Win%':>8s} {'Val #':>5s} {'Val Sharpe':>10s} {'Val MDD%':>8s} | {'Train PF':>8s} {'Train P&L':>10s} {'Overfit':>7s}")

    sorted_worst = sorted(results, key=lambda r: r["validate"]["total_pnl"])
    for r in sorted_worst[:10]:
        p = r["params"]
        v = r["validate"]
        t = r["train"]
        flag = "OVERFIT" if r["overfit"] else ""
        print(f"  {p['atr_period']:>3d} {p['multiplier']:>4.1f} {p['source']:>5s} | "
              f"{v['profit_factor']:>7.2f} {v['total_pnl']:>9.2f} {v['win_rate']:>7.1f}% {v['num_trades']:>5d} {v['sharpe_ratio']:>10.2f} {v['max_drawdown_pct']:>7.1f}% | "
              f"{t['profit_factor']:>8.2f} {t['total_pnl']:>10.2f} {flag:>7s}")

    # ─── Reference configs ───
    print("\n" + "-" * 100)
    print("REFERENCE CONFIGURATIONS")
    print("-" * 100)

    refs = {
        "Your live: ST(10, 2.0, hl2)": (10, 2.0, "hl2"),
        "Colleague: ST(10, 1.3, close)": (10, 1.3, "close"),
        "TV default: ST(10, 3.0, hl2)": (10, 3.0, "hl2"),
    }

    for label, (atr_p, mult, src) in refs.items():
        for r in results:
            if (r["params"]["atr_period"] == atr_p and
                r["params"]["multiplier"] == mult and
                r["params"]["source"] == src):
                v = r["validate"]
                t = r["train"]
                print(f"  {label}")
                print(f"    Train:  PF={t['profit_factor']:.2f}  P&L=${t['total_pnl']:.2f}  Win={t['win_rate']:.1f}%  Trades={t['num_trades']}  Sharpe={t['sharpe_ratio']:.2f}")
                print(f"    Valid:  PF={v['profit_factor']:.2f}  P&L=${v['total_pnl']:.2f}  Win={v['win_rate']:.1f}%  Trades={v['num_trades']}  Sharpe={v['sharpe_ratio']:.2f}  MDD={v['max_drawdown_pct']:.1f}%")
                break

    # Save full results
    output_path = OUTPUT_DIR / "step1_baseline.json"
    with open(output_path, "w") as f:
        json.dump({
            "metadata": {
                "total_bars": n,
                "train_bars": train_end,
                "validate_bars": val_end - train_end,
                "train_period": f"{train_start_dt.strftime('%Y-%m-%d')} to {train_end_dt.strftime('%Y-%m-%d')}",
                "validate_period": f"{val_start_dt.strftime('%Y-%m-%d')} to {val_end_dt.strftime('%Y-%m-%d')}",
                "total_combinations": len(results),
                "profitable_on_validation": profitable_val,
                "overfit_count": overfit_count,
            },
            "top10_validation_pf": [{"rank": i+1, **r} for i, r in enumerate(sorted_pf[:10])],
            "top10_validation_pnl": [{"rank": i+1, **r} for i, r in enumerate(sorted_pnl[:10])],
            "top10_validation_sharpe": [{"rank": i+1, **r} for i, r in enumerate(sorted_sharpe[:10])],
            "all_results": results,
        }, f, indent=2)
    print(f"\n  Results saved to {output_path}")

    # Print the top 10 for Step 2
    print("\n" + "=" * 70)
    print("TOP 10 FOR STEP 2 (by validation profit factor, excluding low confidence)")
    print("=" * 70)
    top10 = [r for r in sorted_pf if not r["low_confidence"]][:10]
    for i, r in enumerate(top10):
        p = r["params"]
        v = r["validate"]
        print(f"  #{i+1}: ST({p['atr_period']}, {p['multiplier']}, {p['source']}) — "
              f"Val PF={v['profit_factor']:.2f}, P&L=${v['total_pnl']:.2f}, "
              f"Trades={v['num_trades']}, Win={v['win_rate']:.1f}%, Sharpe={v['sharpe_ratio']:.2f}")


if __name__ == "__main__":
    main()

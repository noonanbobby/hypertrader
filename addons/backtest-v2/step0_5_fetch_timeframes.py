#!/usr/bin/env python3
"""
Step 0.5: Fetch additional timeframe data from Binance and run timeframe comparison.
"""

import json
import time
import numpy as np
from pathlib import Path
from datetime import datetime, timezone
from itertools import product

DATA_DIR = Path(__file__).parent.parent / "backtest-data"
OUTPUT_DIR = Path(__file__).parent

import sys
sys.path.insert(0, str(Path(__file__).parent))
from step0_fetch_and_verify import fetch_binance_klines, check_gaps
from engine import BacktestConfig, run_backtest, result_to_dict


TIMEFRAMES = {
    "5m": {"interval": "5m", "file": "binance_btc_5m.json", "bars_per_year": 105120},
    "15m": {"interval": "15m", "file": "binance_btc_15m.json", "bars_per_year": 35040},
    "30m": {"interval": "30m", "file": "binance_btc_30m.json", "bars_per_year": 17520},
    "1h": {"interval": "1h", "file": "binance_btc_1h.json", "bars_per_year": 8760},
    "2h": {"interval": "2h", "file": "binance_btc_2h.json", "bars_per_year": 4380},
    "4h": {"interval": "4h", "file": "binance_btc_4h.json", "bars_per_year": 2190},
}

# Quick screen: top 20 ATR/Mult/Source combos
QUICK_SCREEN = list(product(
    [7, 9, 10, 12, 14],          # 5 ATR periods
    [1.5, 2.0, 2.5, 3.0, 4.0],  # 5 multipliers
    ["hl2", "close"],             # 2 sources
))  # = 50 combos per timeframe


def load_or_fetch(tf_name: str, tf_info: dict, limit_days: int = 730) -> list:
    filepath = DATA_DIR / tf_info["file"]

    if filepath.exists():
        print(f"  {tf_name}: Loading existing data from {filepath.name}...")
        with open(filepath) as f:
            return json.load(f)

    print(f"  {tf_name}: Fetching from Binance...")
    klines = fetch_binance_klines("BTCUSDT", tf_info["interval"], limit_days=limit_days)

    with open(filepath, "w") as f:
        json.dump(klines, f)

    return klines


def run_tf_backtest(klines: list, atr_p: int, mult: float, src: str, train_pct: float = 0.7):
    """Run a single backtest on given kline data."""
    opens = np.array([k["open"] for k in klines], dtype=np.float64)
    highs = np.array([k["high"] for k in klines], dtype=np.float64)
    lows = np.array([k["low"] for k in klines], dtype=np.float64)
    closes = np.array([k["close"] for k in klines], dtype=np.float64)
    volumes = np.array([k["volume"] for k in klines], dtype=np.float64)
    timestamps = np.array([k["open_time"] for k in klines], dtype=np.int64)

    n = len(closes)
    train_end = int(n * train_pct)

    config = BacktestConfig(atr_period=atr_p, multiplier=mult, source=src)

    # Validation only
    val_config = BacktestConfig(
        atr_period=atr_p, multiplier=mult, source=src,
        warmup=max(200, train_end),
    )
    val_result = run_backtest(opens, highs, lows, closes, volumes, timestamps,
                              val_config, start_bar=train_end, end_bar=n)

    return val_result


def main():
    print("=" * 70)
    print("STEP 0.5: TIMEFRAME OPTIMIZATION")
    print(f"  Testing {len(TIMEFRAMES)} timeframes x {len(QUICK_SCREEN)} parameter combos")
    print("=" * 70)

    # ─── Fetch all timeframe data ───
    print("\n[1/3] Fetching/loading candle data...")
    all_data = {}
    for tf_name, tf_info in TIMEFRAMES.items():
        klines = load_or_fetch(tf_name, tf_info)

        first_dt = datetime.fromtimestamp(klines[0]["open_time"]/1000, tz=timezone.utc)
        last_dt = datetime.fromtimestamp(klines[-1]["open_time"]/1000, tz=timezone.utc)
        days = (last_dt - first_dt).total_seconds() / 86400

        gaps = check_gaps(klines, tf_info["interval"])
        total_missing = sum(g["missing_candles"] for g in gaps)
        print(f"    {tf_name}: {len(klines)} candles, {days:.0f} days, {len(gaps)} gaps ({total_missing} missing)")
        print(f"      {first_dt.strftime('%Y-%m-%d')} to {last_dt.strftime('%Y-%m-%d')}")

        all_data[tf_name] = klines

    # ─── Run quick screen on each timeframe ───
    print(f"\n[2/3] Running {len(QUICK_SCREEN)} Supertrend combos on each timeframe...")

    tf_results = {}
    for tf_name in TIMEFRAMES:
        klines = all_data[tf_name]
        n = len(klines)
        train_end = int(n * 0.7)

        timestamps = [k["open_time"] for k in klines]
        val_start_dt = datetime.fromtimestamp(timestamps[train_end]/1000, tz=timezone.utc)
        val_end_dt = datetime.fromtimestamp(timestamps[-1]/1000, tz=timezone.utc)
        val_days = (val_end_dt - val_start_dt).total_seconds() / 86400

        results = []
        for idx, (atr_p, mult, src) in enumerate(QUICK_SCREEN):
            val_result = run_tf_backtest(klines, atr_p, mult, src)
            rd = result_to_dict(val_result)

            # Calculate avg hold time and trades per day
            trades_per_day = rd["num_trades"] / val_days if val_days > 0 else 0
            avg_hold_bars = 0
            if val_result.trades:
                hold_bars = [t.exit_bar - t.entry_bar for t in val_result.trades]
                avg_hold_bars = np.mean(hold_bars)

            rd["trades_per_day"] = round(trades_per_day, 2)
            rd["avg_hold_bars"] = round(avg_hold_bars, 1)
            rd["params"] = {"atr_period": atr_p, "multiplier": mult, "source": src}

            results.append(rd)

        # Sort by validation PF
        results.sort(key=lambda r: r["profit_factor"], reverse=True)
        tf_results[tf_name] = {
            "val_days": round(val_days, 1),
            "val_bars": n - train_end,
            "results": results,
            "best_pf": results[0] if results else None,
            "best_pnl": max(results, key=lambda r: r["total_pnl"]) if results else None,
        }

        best = results[0]
        print(f"  {tf_name:>3s}: Best PF={best['profit_factor']:.2f} "
              f"(ST({best['params']['atr_period']},{best['params']['multiplier']},{best['params']['source']})) "
              f"P&L=${best['total_pnl']:.0f} "
              f"Trades={best['num_trades']} ({best['trades_per_day']:.1f}/day) "
              f"MDD={best['max_drawdown_pct']:.0f}%")

    # ─── Multi-timeframe strategies ───
    print(f"\n[3/3] Testing multi-timeframe confirmation strategies...")

    # For MTF: entry on lower TF, confirmed by higher TF direction
    # We need aligned timestamps. Simpler approach: for each lower TF bar,
    # find the corresponding higher TF Supertrend direction.

    mtf_configs = [
        ("15m", "1h", "Entry 15m, confirm 1H"),
        ("5m", "15m", "Entry 5m, confirm 15m"),
        ("30m", "4h", "Entry 30m, confirm 4H"),
    ]

    mtf_results = []
    for entry_tf, confirm_tf, label in mtf_configs:
        entry_data = all_data[entry_tf]
        confirm_data = all_data[confirm_tf]

        # Build a lookup: timestamp -> higher TF Supertrend direction
        c_closes = np.array([k["close"] for k in confirm_data], dtype=np.float64)
        c_highs = np.array([k["high"] for k in confirm_data], dtype=np.float64)
        c_lows = np.array([k["low"] for k in confirm_data], dtype=np.float64)
        c_timestamps = np.array([k["open_time"] for k in confirm_data], dtype=np.int64)

        # Use best params from each TF for confirmation
        best_entry = tf_results[entry_tf]["best_pf"]["params"]
        best_confirm = tf_results[confirm_tf]["best_pf"]["params"]

        # Calculate higher TF Supertrend
        from engine import calc_supertrend as engine_st
        _, confirm_dirs = engine_st(c_highs, c_lows, c_closes,
                                      best_confirm["atr_period"],
                                      best_confirm["multiplier"],
                                      best_confirm["source"])

        # Map higher TF direction to each lower TF bar
        # For each entry bar, find the last completed higher TF bar
        e_timestamps = np.array([k["open_time"] for k in entry_data], dtype=np.int64)
        n_entry = len(entry_data)

        # Create direction array aligned to entry TF
        htf_dir_aligned = np.ones(n_entry)
        c_idx = 0
        for i in range(n_entry):
            while c_idx < len(c_timestamps) - 1 and c_timestamps[c_idx + 1] <= e_timestamps[i]:
                c_idx += 1
            if c_idx < len(confirm_dirs):
                htf_dir_aligned[i] = confirm_dirs[c_idx]

        # Run backtest with MTF filter
        # Custom: only take signals when entry ST direction matches higher TF direction
        opens_e = np.array([k["open"] for k in entry_data], dtype=np.float64)
        highs_e = np.array([k["high"] for k in entry_data], dtype=np.float64)
        lows_e = np.array([k["low"] for k in entry_data], dtype=np.float64)
        closes_e = np.array([k["close"] for k in entry_data], dtype=np.float64)
        volumes_e = np.array([k["volume"] for k in entry_data], dtype=np.float64)

        train_end_e = int(n_entry * 0.7)

        # We need to modify the engine to support MTF... for now, do a manual simulation
        from engine import calc_supertrend as cs, BacktestConfig as BC

        config = BC(
            atr_period=best_entry["atr_period"],
            multiplier=best_entry["multiplier"],
            source=best_entry["source"],
            warmup=max(200, train_end_e),
        )

        st_line, st_dir = cs(highs_e, lows_e, closes_e,
                              config.atr_period, config.multiplier, config.source)

        # Simple MTF backtest: standard ST on entry TF, but skip signals where HTF disagrees
        equity = 500.0
        position = 0
        entry_price = 0.0
        position_size = 0.0
        trades_list = []
        pending = None

        for i in range(max(200, train_end_e), n_entry):
            # Execute pending
            if pending is not None:
                action = pending
                pending = None

                if action == "close" and position != 0:
                    fill = opens_e[i] * (1 - 0.0001 * position)
                    pnl = (fill - entry_price) * position * (position_size / entry_price)
                    fee = position_size * 0.00045
                    equity += pnl - fee
                    trades_list.append(pnl - fee)
                    position = 0

                elif action.startswith("flip") or action.startswith("open"):
                    if position != 0:
                        fill_close = opens_e[i] * (1 - 0.0001 * position)
                        pnl = (fill_close - entry_price) * position * (position_size / entry_price)
                        fee = position_size * 0.00045
                        equity += pnl - fee
                        trades_list.append(pnl - fee)

                    new_dir = 1 if "long" in action else -1
                    fill_open = opens_e[i] * (1 + 0.0001 * new_dir)
                    position_size = equity * 0.25 * 10.0
                    fee = position_size * 0.00045
                    equity -= fee
                    position = new_dir
                    entry_price = fill_open

            if i >= n_entry - 1:
                if position != 0:
                    pending = "close"
                continue

            if np.isnan(st_dir[i]) or np.isnan(st_dir[i-1]):
                continue

            if st_dir[i] != st_dir[i-1]:
                new_dir = 1 if st_dir[i] == 1 else -1

                # MTF filter: only take signal if higher TF agrees
                if htf_dir_aligned[i] != new_dir:
                    # Higher TF disagrees — close position if open, don't flip
                    if position != 0:
                        pending = "close"
                    continue

                if position == 0:
                    pending = "open_long" if new_dir == 1 else "open_short"
                elif position != new_dir:
                    pending = "flip_long" if new_dir == 1 else "flip_short"

        # Handle final pending
        if pending == "close" and position != 0:
            fill = closes_e[-1] * (1 - 0.0001 * position)
            pnl = (fill - entry_price) * position * (position_size / entry_price)
            fee = position_size * 0.00045
            equity += pnl - fee
            trades_list.append(pnl - fee)

        val_days = (e_timestamps[-1] - e_timestamps[train_end_e]) / (1000 * 86400)
        wins = sum(1 for t in trades_list if t > 0)
        gross_profit = sum(t for t in trades_list if t > 0)
        gross_loss = abs(sum(t for t in trades_list if t <= 0))
        pf = gross_profit / gross_loss if gross_loss > 0 else 9999.0

        mtf_result = {
            "label": label,
            "entry_tf": entry_tf,
            "confirm_tf": confirm_tf,
            "entry_params": best_entry,
            "confirm_params": best_confirm,
            "num_trades": len(trades_list),
            "final_equity": round(equity, 2),
            "total_pnl": round(equity - 500, 2),
            "win_rate": round(wins / len(trades_list) * 100, 1) if trades_list else 0,
            "profit_factor": round(pf, 4),
            "trades_per_day": round(len(trades_list) / val_days, 2) if val_days > 0 else 0,
        }
        mtf_results.append(mtf_result)
        print(f"  {label}: PF={pf:.2f} P&L=${equity-500:.0f} Trades={len(trades_list)} ({mtf_result['trades_per_day']:.1f}/day) Win={mtf_result['win_rate']:.1f}%")

    # ═══════════════════════════════════════════════════════════
    # COMPARISON TABLE
    # ═══════════════════════════════════════════════════════════
    print("\n" + "=" * 100)
    print("TIMEFRAME COMPARISON — BEST CONFIG PER TIMEFRAME (validation set)")
    print("=" * 100)
    print(f"  {'TF':>4s} | {'Best Config':>22s} | {'PF':>6s} {'P&L':>8s} {'Win%':>6s} {'Trades':>6s} {'Tr/Day':>6s} {'AvgHold':>8s} {'MDD%':>6s} {'Sharpe':>7s} {'Fees':>8s}")
    print(f"  {'─'*4} | {'─'*22} | {'─'*6} {'─'*8} {'─'*6} {'─'*6} {'─'*6} {'─'*8} {'─'*6} {'─'*7} {'─'*8}")

    for tf_name in ["5m", "15m", "30m", "1h", "2h", "4h"]:
        tfr = tf_results[tf_name]
        best = tfr["best_pf"]
        p = best["params"]
        cfg = f"ST({p['atr_period']},{p['multiplier']},{p['source']})"
        print(f"  {tf_name:>4s} | {cfg:>22s} | "
              f"{best['profit_factor']:>6.2f} {best['total_pnl']:>8.0f} {best['win_rate']:>5.1f}% {best['num_trades']:>6d} "
              f"{best['trades_per_day']:>6.1f} {best['avg_hold_bars']:>7.1f}b {best['max_drawdown_pct']:>5.1f}% "
              f"{best.get('sharpe_ratio', 0):>7.2f} {best['total_fees']:>8.1f}")

    print("\n  MULTI-TIMEFRAME STRATEGIES:")
    for mtf in mtf_results:
        print(f"  {mtf['label']:>30s} | PF={mtf['profit_factor']:.2f} P&L=${mtf['total_pnl']:.0f} Trades={mtf['num_trades']} Win={mtf['win_rate']:.1f}%")

    # ─── Determine winning timeframe ───
    # Rank by: PF > 1.0, then by P&L
    all_tf_ranked = []
    for tf_name in TIMEFRAMES:
        best = tf_results[tf_name]["best_pf"]
        all_tf_ranked.append((tf_name, best["profit_factor"], best["total_pnl"], best["num_trades"]))

    all_tf_ranked.sort(key=lambda x: (x[1], x[2]), reverse=True)

    winner_tf = all_tf_ranked[0][0]
    winner_pf = all_tf_ranked[0][1]

    print(f"\n  WINNING TIMEFRAME: {winner_tf} (PF={winner_pf:.2f})")
    print(f"  This timeframe will be used for all subsequent steps.")

    # Save
    output = {
        "timeframe_results": {},
        "mtf_results": mtf_results,
        "winning_timeframe": winner_tf,
    }
    for tf_name in TIMEFRAMES:
        tfr = tf_results[tf_name]
        output["timeframe_results"][tf_name] = {
            "val_days": tfr["val_days"],
            "val_bars": tfr["val_bars"],
            "best_pf": tfr["best_pf"],
            "best_pnl": tfr["best_pnl"],
            "top5": tfr["results"][:5],
        }

    output_path = OUTPUT_DIR / "step0_5_timeframes.json"
    with open(output_path, "w") as f:
        json.dump(output, f, indent=2)
    print(f"\n  Results saved to {output_path}")


if __name__ == "__main__":
    main()

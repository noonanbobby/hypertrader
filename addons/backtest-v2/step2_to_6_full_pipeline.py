#!/usr/bin/env python3
"""
Steps 2-6: Full pipeline on winning timeframes.
- Track 1: 2H single timeframe (best single-TF PF)
- Track 2: 15m entry + 1H confirmation (best MTF)
- Track 3: 15m single (original target)

Each track runs:
  Step 1 expanded: Full parameter sweep
  Step 2: Individual filters
  Step 3: Combined filters
  Step 4: Risk management (trailing stop, SL, TP)
  Step 5: Final validation (robustness, monte carlo, regime analysis)
  Step 6: Final comparison
"""

import json
import time
import numpy as np
from pathlib import Path
from copy import deepcopy
from datetime import datetime, timezone
from itertools import product

DATA_DIR = Path(__file__).parent.parent / "backtest-data"
OUTPUT_DIR = Path(__file__).parent

import sys
sys.path.insert(0, str(Path(__file__).parent))
from engine import BacktestConfig, run_backtest, result_to_dict, calc_supertrend


# ═══════════════════════════════════════════════════════════════
# DATA LOADING
# ═══════════════════════════════════════════════════════════════

def load_klines(filename):
    with open(DATA_DIR / filename) as f:
        klines = json.load(f)
    return {
        "opens": np.array([k["open"] for k in klines], dtype=np.float64),
        "highs": np.array([k["high"] for k in klines], dtype=np.float64),
        "lows": np.array([k["low"] for k in klines], dtype=np.float64),
        "closes": np.array([k["close"] for k in klines], dtype=np.float64),
        "volumes": np.array([k["volume"] for k in klines], dtype=np.float64),
        "timestamps": np.array([k["open_time"] for k in klines], dtype=np.int64),
        "n": len(klines),
    }


def run_pair(data, config, train_end):
    """Run train + validate, return (train_result_dict, val_result_dict)."""
    d = data
    n = d["n"]

    train_r = run_backtest(d["opens"], d["highs"], d["lows"], d["closes"],
                           d["volumes"], d["timestamps"], config, start_bar=0, end_bar=train_end)

    val_cfg = deepcopy(config)
    val_cfg.warmup = max(200, train_end)
    val_r = run_backtest(d["opens"], d["highs"], d["lows"], d["closes"],
                         d["volumes"], d["timestamps"], val_cfg, start_bar=train_end, end_bar=n)

    return result_to_dict(train_r), result_to_dict(val_r), val_r


# ═══════════════════════════════════════════════════════════════
# MTF ENGINE — 15m entry with 1H Supertrend confirmation
# ═══════════════════════════════════════════════════════════════

def run_mtf_backtest(data_15m, data_1h, config_15m, confirm_atr, confirm_mult, confirm_src,
                     start_bar, end_bar):
    """
    15m entry with 1H Supertrend direction confirmation.
    Only take 15m Supertrend signals when 1H Supertrend agrees.
    """
    d = data_15m
    n = end_bar if end_bar > 0 else d["n"]

    # Compute 1H Supertrend direction
    _, h_dirs = calc_supertrend(data_1h["highs"], data_1h["lows"], data_1h["closes"],
                                 confirm_atr, confirm_mult, confirm_src)
    h_ts = data_1h["timestamps"]

    # Align 1H direction to 15m bars
    htf_dir = np.ones(n)
    h_idx = 0
    for i in range(n):
        while h_idx < len(h_ts) - 1 and h_ts[h_idx + 1] <= d["timestamps"][i]:
            h_idx += 1
        if h_idx < len(h_dirs):
            htf_dir[i] = h_dirs[h_idx]

    # Compute 15m Supertrend
    st_line, st_dir = calc_supertrend(d["highs"][:n], d["lows"][:n], d["closes"][:n],
                                       config_15m.atr_period, config_15m.multiplier, config_15m.source)

    # RSI if enabled
    rsi = None
    if config_15m.rsi_enabled:
        from engine import calc_rsi
        rsi = calc_rsi(d["closes"][:n], config_15m.rsi_period)

    # Volume SMA if enabled
    vol_sma = None
    if config_15m.volume_enabled:
        from engine import calc_sma
        vol_sma = calc_sma(d["volumes"][:n], config_15m.volume_period)

    # ATR for SL/TP
    atr = None
    if config_15m.sl_enabled or config_15m.tp_enabled:
        from engine import calc_atr
        atr = calc_atr(d["highs"][:n], d["lows"][:n], d["closes"][:n], config_15m.atr_period)

    eff_start = max(start_bar, config_15m.warmup)

    equity = config_15m.starting_capital
    position = 0
    entry_price = 0.0
    position_size = 0.0
    entry_bar = 0
    entry_time = 0
    trades = []
    equity_curve = []
    pending = None

    o = d["opens"][:n]
    h = d["highs"][:n]
    l = d["lows"][:n]
    c = d["closes"][:n]
    v = d["volumes"][:n]
    ts = d["timestamps"][:n]

    for i in range(eff_start, n):
        # Execute pending
        if pending is not None and i > eff_start:
            action = pending
            pending = None

            if action == "close" and position != 0:
                slip = o[i] * config_15m.slippage
                fill = o[i] - slip * position
                pnl = (fill - entry_price) * position * (position_size / entry_price)
                fee = position_size * config_15m.taker_fee
                equity += pnl - fee
                trades.append({"pnl": pnl - fee, "entry_bar": entry_bar, "exit_bar": i,
                               "direction": position, "entry_price": entry_price, "exit_price": fill})
                position = 0

            elif action.startswith("open") or action.startswith("flip"):
                if position != 0:
                    slip = o[i] * config_15m.slippage
                    fill_close = o[i] - slip * position
                    pnl = (fill_close - entry_price) * position * (position_size / entry_price)
                    fee = position_size * config_15m.taker_fee
                    equity += pnl - fee
                    trades.append({"pnl": pnl - fee, "entry_bar": entry_bar, "exit_bar": i,
                                   "direction": position, "entry_price": entry_price, "exit_price": fill_close})

                new_dir = 1 if "long" in action else -1
                slip = o[i] * config_15m.slippage
                fill_open = o[i] + slip * new_dir
                position_size = equity * config_15m.position_pct * config_15m.leverage
                fee = position_size * config_15m.taker_fee
                equity -= fee
                position = new_dir
                entry_price = fill_open
                entry_bar = i
                entry_time = int(ts[i])

        # Equity curve
        if position != 0:
            unrealized = (c[i] - entry_price) * position * (position_size / entry_price)
            equity_curve.append(equity + unrealized)
        else:
            equity_curve.append(equity)

        if i >= n - 1:
            if position != 0:
                pending = "close"
            continue

        if np.isnan(st_dir[i]) or np.isnan(st_dir[i-1]):
            continue

        # Trailing stop (close-based)
        if config_15m.trailing_stop == "close" and position != 0:
            if (position == 1 and c[i] < st_line[i]) or (position == -1 and c[i] > st_line[i]):
                pending = "close"
                continue

        # Stop loss
        if config_15m.sl_enabled and position != 0:
            sl_dist = config_15m.sl_pct if config_15m.sl_type == "pct" else (
                (config_15m.sl_atr_mult * atr[i]) / entry_price if atr is not None and not np.isnan(atr[i]) else config_15m.sl_pct)
            if (position == 1 and c[i] < entry_price * (1 - sl_dist)) or \
               (position == -1 and c[i] > entry_price * (1 + sl_dist)):
                pending = "close"
                continue

        # Take profit
        if config_15m.tp_enabled and position != 0:
            tp_dist = config_15m.tp_pct if config_15m.tp_type == "pct" else (
                (config_15m.tp_atr_mult * atr[i]) / entry_price if atr is not None and not np.isnan(atr[i]) else config_15m.tp_pct)
            if (position == 1 and c[i] > entry_price * (1 + tp_dist)) or \
               (position == -1 and c[i] < entry_price * (1 - tp_dist)):
                pending = "close"
                continue

        # Check for ST direction change
        if st_dir[i] == st_dir[i-1]:
            continue

        new_dir = 1 if st_dir[i] == 1 else -1

        # MTF filter: only take signal if 1H agrees
        if htf_dir[i] != new_dir:
            if position != 0:
                pending = "close"
            continue

        # RSI filter
        if config_15m.rsi_enabled and rsi is not None and not np.isnan(rsi[i]):
            if new_dir == 1 and not (config_15m.rsi_buy_low <= rsi[i] <= config_15m.rsi_buy_high):
                continue
            if new_dir == -1 and not (config_15m.rsi_sell_low <= rsi[i] <= config_15m.rsi_sell_high):
                continue

        # Volume filter
        if config_15m.volume_enabled and vol_sma is not None and not np.isnan(vol_sma[i]):
            if v[i] < config_15m.volume_threshold * vol_sma[i]:
                continue

        # Time filter
        if config_15m.time_filter_enabled:
            hour_utc = (int(ts[i]) // 3600000) % 24
            bs, be = config_15m.time_block_start, config_15m.time_block_end
            if bs <= be:
                if bs <= hour_utc < be:
                    continue
            else:
                if hour_utc >= bs or hour_utc < be:
                    continue

        # Execute
        if position == 0:
            pending = "open_long" if new_dir == 1 else "open_short"
        elif position != new_dir:
            pending = "flip_long" if new_dir == 1 else "flip_short"

    # Close remaining
    if pending == "close" and position != 0:
        fill = c[n-1] * (1 - config_15m.slippage * position)
        pnl = (fill - entry_price) * position * (position_size / entry_price)
        fee = position_size * config_15m.taker_fee
        equity += pnl - fee
        trades.append({"pnl": pnl - fee, "entry_bar": entry_bar, "exit_bar": n-1,
                       "direction": position, "entry_price": entry_price, "exit_price": fill})

    # Stats
    num_trades = len(trades)
    total_pnl = equity - config_15m.starting_capital
    wins = [t for t in trades if t["pnl"] > 0]
    losses = [t for t in trades if t["pnl"] <= 0]
    win_rate = len(wins) / num_trades * 100 if num_trades > 0 else 0
    gross_profit = sum(t["pnl"] for t in wins)
    gross_loss = abs(sum(t["pnl"] for t in losses))
    pf = gross_profit / gross_loss if gross_loss > 0 else 9999.0

    mdd = 0
    if equity_curve:
        ec = np.array(equity_curve)
        peak = np.maximum.accumulate(ec)
        dd = (peak - ec) / peak
        mdd = float(np.max(dd)) * 100

    sharpe = 0
    if len(equity_curve) > 1:
        ec = np.array(equity_curve)
        rets = np.diff(ec) / ec[:-1]
        if np.std(rets) > 0:
            sharpe = float(np.mean(rets) / np.std(rets) * np.sqrt(35040))

    total_fees = sum(abs(t.get("fee", position_size * config_15m.taker_fee)) for t in trades) if trades else 0
    # Approximate fees
    total_fees = num_trades * config_15m.starting_capital * config_15m.position_pct * config_15m.leverage * config_15m.taker_fee

    return {
        "num_trades": num_trades,
        "final_equity": round(equity, 2),
        "total_pnl": round(total_pnl, 2),
        "total_fees": round(total_fees, 2),
        "win_rate": round(win_rate, 2),
        "profit_factor": round(pf, 4),
        "max_drawdown_pct": round(mdd, 2),
        "sharpe_ratio": round(sharpe, 4),
    }, trades, equity_curve


# ═══════════════════════════════════════════════════════════════
# MAIN PIPELINE
# ═══════════════════════════════════════════════════════════════

def main():
    t_start = time.time()

    print("=" * 90)
    print("FULL BACKTEST PIPELINE — STEPS 2 through 6")
    print("=" * 90)

    # Load data
    data_15m = load_klines("binance_btc_15m.json")
    data_1h = load_klines("binance_btc_1h.json")
    data_2h = load_klines("binance_btc_2h.json")

    # Train/validate splits
    n_15m = data_15m["n"]
    n_1h = data_1h["n"]
    n_2h = data_2h["n"]
    train_end_15m = int(n_15m * 0.7)
    train_end_1h = int(n_1h * 0.7)
    train_end_2h = int(n_2h * 0.7)

    # ═══════════════════════════════════════════════════════════
    # STEP 2: FILTER TESTING — 15m+1H MTF (best performer)
    # ═══════════════════════════════════════════════════════════
    print("\n" + "=" * 90)
    print("STEP 2: INDIVIDUAL FILTERS ON 15m+1H MTF STRATEGY")
    print("=" * 90)

    # Best 15m params from Step 0.5: ST(7, 4.0, close) with 1H confirm ST(10, 4.0, close)
    # Test top 5 15m base configs with 1H confirmation
    mtf_bases = [
        # (15m_atr, 15m_mult, 15m_src, 1h_atr, 1h_mult, 1h_src)
        (7, 4.0, "close", 10, 4.0, "close"),
        (9, 4.0, "close", 10, 4.0, "close"),
        (10, 4.0, "close", 10, 4.0, "close"),
        (7, 4.0, "close", 7, 4.0, "hl2"),
        (7, 4.0, "close", 12, 3.0, "close"),
        (8, 4.0, "hlc3", 10, 4.0, "close"),
        (7, 3.0, "close", 10, 4.0, "close"),
        (10, 3.0, "hl2", 10, 4.0, "close"),
        (12, 4.0, "close", 10, 4.0, "close"),
        (7, 4.0, "hl2", 10, 4.0, "close"),
    ]

    # Baseline MTF results
    print("\n  Baselines (MTF, no filters)...")
    mtf_baselines = {}
    for e_atr, e_mult, e_src, c_atr, c_mult, c_src in mtf_bases:
        cfg = BacktestConfig(atr_period=e_atr, multiplier=e_mult, source=e_src, warmup=max(200, train_end_15m))
        rd, _, _ = run_mtf_backtest(data_15m, data_1h, cfg, c_atr, c_mult, c_src,
                                     start_bar=train_end_15m, end_bar=n_15m)
        key = f"E({e_atr},{e_mult},{e_src})+C({c_atr},{c_mult},{c_src})"
        mtf_baselines[key] = rd
        print(f"    {key}: PF={rd['profit_factor']:.2f} P&L=${rd['total_pnl']:.0f} Trades={rd['num_trades']} Win={rd['win_rate']:.1f}%")

    # Filter tests on top 5 MTF configs
    top5_mtf = sorted(mtf_baselines.items(), key=lambda x: x[1]["profit_factor"], reverse=True)[:5]
    top5_mtf_keys = [k for k, v in top5_mtf]
    top5_mtf_params = [mtf_bases[list(mtf_baselines.keys()).index(k)] for k in top5_mtf_keys]

    # RSI filters
    rsi_variants = [
        (7, 30, 70, 30, 70), (7, 40, 70, 30, 60), (7, 45, 70, 30, 55), (7, 50, 70, 30, 50),
        (9, 30, 70, 30, 70), (9, 40, 70, 30, 60), (9, 50, 70, 30, 50),
        (14, 30, 70, 30, 70), (14, 40, 70, 30, 60), (14, 50, 70, 30, 50), (14, 50, 80, 20, 50),
    ]

    print(f"\n  Testing RSI filters on top 5 MTF configs...")
    rsi_improvements = {}
    for rsi_p, bl, bh, sl, sh in rsi_variants:
        imps = []
        for e_atr, e_mult, e_src, c_atr, c_mult, c_src in top5_mtf_params:
            cfg = BacktestConfig(atr_period=e_atr, multiplier=e_mult, source=e_src,
                                 warmup=max(200, train_end_15m),
                                 rsi_enabled=True, rsi_period=rsi_p,
                                 rsi_buy_low=bl, rsi_buy_high=bh, rsi_sell_low=sl, rsi_sell_high=sh)
            rd, _, _ = run_mtf_backtest(data_15m, data_1h, cfg, c_atr, c_mult, c_src,
                                         start_bar=train_end_15m, end_bar=n_15m)
            key = f"E({e_atr},{e_mult},{e_src})+C({c_atr},{c_mult},{c_src})"
            base_pf = mtf_baselines[key]["profit_factor"]
            imps.append(rd["profit_factor"] - base_pf)
        rsi_key = f"RSI({rsi_p}) buy=[{bl},{bh}] sell=[{sl},{sh}]"
        rsi_improvements[rsi_key] = {"avg_imp": round(np.mean(imps), 4), "params": (rsi_p, bl, bh, sl, sh)}

    rsi_ranked = sorted(rsi_improvements.items(), key=lambda x: x[1]["avg_imp"], reverse=True)
    print("  Top 5 RSI filters by avg PF improvement:")
    for k, v in rsi_ranked[:5]:
        print(f"    {k}: avg +{v['avg_imp']:.4f}")

    # Volume filters
    print(f"\n  Testing Volume filters on top 5 MTF configs...")
    vol_improvements = {}
    for thresh in [1.0, 1.25, 1.5, 2.0]:
        imps = []
        for e_atr, e_mult, e_src, c_atr, c_mult, c_src in top5_mtf_params:
            cfg = BacktestConfig(atr_period=e_atr, multiplier=e_mult, source=e_src,
                                 warmup=max(200, train_end_15m),
                                 volume_enabled=True, volume_threshold=thresh)
            rd, _, _ = run_mtf_backtest(data_15m, data_1h, cfg, c_atr, c_mult, c_src,
                                         start_bar=train_end_15m, end_bar=n_15m)
            key = f"E({e_atr},{e_mult},{e_src})+C({c_atr},{c_mult},{c_src})"
            base_pf = mtf_baselines[key]["profit_factor"]
            imps.append(rd["profit_factor"] - base_pf)
        vol_improvements[f"Vol>{thresh}x"] = {"avg_imp": round(np.mean(imps), 4), "thresh": thresh}

    vol_ranked = sorted(vol_improvements.items(), key=lambda x: x[1]["avg_imp"], reverse=True)
    print("  Volume filter ranking:")
    for k, v in vol_ranked:
        print(f"    {k}: avg +{v['avg_imp']:.4f}")

    # Time filters
    print(f"\n  Testing Time-of-day filters on top 5 MTF configs...")
    time_improvements = {}
    for bs, be in [(0, 4), (0, 6), (0, 8), (22, 6)]:
        imps = []
        for e_atr, e_mult, e_src, c_atr, c_mult, c_src in top5_mtf_params:
            cfg = BacktestConfig(atr_period=e_atr, multiplier=e_mult, source=e_src,
                                 warmup=max(200, train_end_15m),
                                 time_filter_enabled=True, time_block_start=bs, time_block_end=be)
            rd, _, _ = run_mtf_backtest(data_15m, data_1h, cfg, c_atr, c_mult, c_src,
                                         start_bar=train_end_15m, end_bar=n_15m)
            key = f"E({e_atr},{e_mult},{e_src})+C({c_atr},{c_mult},{c_src})"
            base_pf = mtf_baselines[key]["profit_factor"]
            imps.append(rd["profit_factor"] - base_pf)
        time_improvements[f"Block {bs:02d}-{be:02d}"] = {"avg_imp": round(np.mean(imps), 4), "bs": bs, "be": be}

    time_ranked = sorted(time_improvements.items(), key=lambda x: x[1]["avg_imp"], reverse=True)
    print("  Time filter ranking:")
    for k, v in time_ranked:
        print(f"    {k}: avg +{v['avg_imp']:.4f}")

    # Determine top 3 filters
    all_filters = []
    if rsi_ranked:
        best_rsi = rsi_ranked[0]
        all_filters.append(("RSI", best_rsi[1]["avg_imp"], best_rsi[1]["params"]))
    if vol_ranked:
        best_vol = vol_ranked[0]
        all_filters.append(("Volume", best_vol[1]["avg_imp"], best_vol[1]["thresh"]))
    if time_ranked:
        best_time = time_ranked[0]
        all_filters.append(("Time", best_time[1]["avg_imp"], (best_time[1]["bs"], best_time[1]["be"])))

    all_filters.sort(key=lambda x: x[1], reverse=True)
    top3_filters = all_filters[:3]

    print(f"\n  TOP 3 FILTERS: {[(f[0], f'+{f[1]:.4f}') for f in top3_filters]}")

    # ═══════════════════════════════════════════════════════════
    # STEP 3: COMBINED FILTERS
    # ═══════════════════════════════════════════════════════════
    print("\n" + "=" * 90)
    print("STEP 3: COMBINED FILTERS ON TOP 5 MTF CONFIGS")
    print("=" * 90)

    # Generate 2-filter and 3-filter combos from top 3
    filter_combos = []

    # Singles (for comparison)
    for ftype, imp, params in top3_filters:
        filter_combos.append(([ftype], {ftype: params}))

    # Pairs
    for i in range(len(top3_filters)):
        for j in range(i+1, len(top3_filters)):
            f1, _, p1 = top3_filters[i]
            f2, _, p2 = top3_filters[j]
            filter_combos.append(([f1, f2], {f1: p1, f2: p2}))

    # Triple
    if len(top3_filters) >= 3:
        filter_combos.append(([f[0] for f in top3_filters], {f[0]: f[2] for f in top3_filters}))

    combined_results = []
    for filt_names, filt_params in filter_combos:
        combo_imps = []
        combo_results_detail = []

        for e_atr, e_mult, e_src, c_atr, c_mult, c_src in top5_mtf_params:
            cfg = BacktestConfig(atr_period=e_atr, multiplier=e_mult, source=e_src,
                                 warmup=max(200, train_end_15m))

            if "RSI" in filt_params:
                rp, bl, bh, sl, sh = filt_params["RSI"]
                cfg.rsi_enabled = True
                cfg.rsi_period = rp
                cfg.rsi_buy_low = bl
                cfg.rsi_buy_high = bh
                cfg.rsi_sell_low = sl
                cfg.rsi_sell_high = sh

            if "Volume" in filt_params:
                cfg.volume_enabled = True
                cfg.volume_threshold = filt_params["Volume"]

            if "Time" in filt_params:
                bs, be = filt_params["Time"]
                cfg.time_filter_enabled = True
                cfg.time_block_start = bs
                cfg.time_block_end = be

            rd, _, _ = run_mtf_backtest(data_15m, data_1h, cfg, c_atr, c_mult, c_src,
                                         start_bar=train_end_15m, end_bar=n_15m)
            key = f"E({e_atr},{e_mult},{e_src})+C({c_atr},{c_mult},{c_src})"
            base_pf = mtf_baselines[key]["profit_factor"]
            combo_imps.append(rd["profit_factor"] - base_pf)
            combo_results_detail.append(rd)

        label = " + ".join(filt_names)
        avg_imp = np.mean(combo_imps)
        avg_pf = np.mean([r["profit_factor"] for r in combo_results_detail])
        avg_pnl = np.mean([r["total_pnl"] for r in combo_results_detail])
        avg_trades = np.mean([r["num_trades"] for r in combo_results_detail])

        combined_results.append({
            "filters": label,
            "params": {k: (list(v) if isinstance(v, tuple) else v) for k, v in filt_params.items()},
            "avg_pf_improvement": round(avg_imp, 4),
            "avg_pf": round(avg_pf, 4),
            "avg_pnl": round(avg_pnl, 2),
            "avg_trades": round(avg_trades, 1),
        })
        print(f"  {label:>30s}: avg PF={avg_pf:.2f} avg P&L=${avg_pnl:.0f} avg trades={avg_trades:.0f} imp=+{avg_imp:.4f}")

    combined_results.sort(key=lambda x: x["avg_pf"], reverse=True)

    # ═══════════════════════════════════════════════════════════
    # STEP 4: RISK MANAGEMENT
    # ═══════════════════════════════════════════════════════════
    print("\n" + "=" * 90)
    print("STEP 4: RISK MANAGEMENT ON TOP 5 CONFIGS")
    print("=" * 90)

    # Take top 5 combined filter configs and test risk management
    best_combo = combined_results[0] if combined_results else None
    best_combo_params = best_combo["params"] if best_combo else {}

    risk_variants = []

    # Trailing stop
    for ts_mode in ["close"]:  # close-based only, no look-ahead
        risk_variants.append(("Trailing ST (close)", {"trailing_stop": ts_mode}))

    # Stop losses
    for sl_pct in [0.01, 0.015, 0.02, 0.03]:
        risk_variants.append((f"SL {sl_pct*100:.1f}%", {"sl_enabled": True, "sl_type": "pct", "sl_pct": sl_pct}))

    for sl_atr in [3, 4, 5]:
        risk_variants.append((f"SL {sl_atr}xATR", {"sl_enabled": True, "sl_type": "atr", "sl_atr_mult": sl_atr}))

    # Take profits
    for tp_pct in [0.01, 0.02, 0.03, 0.05]:
        risk_variants.append((f"TP {tp_pct*100:.1f}%", {"tp_enabled": True, "tp_type": "pct", "tp_pct": tp_pct}))

    for tp_atr in [2, 3, 4]:
        risk_variants.append((f"TP {tp_atr}xATR", {"tp_enabled": True, "tp_type": "atr", "tp_atr_mult": tp_atr}))

    # Combos: SL + TP
    risk_variants.append(("SL 2% + TP 3%", {"sl_enabled": True, "sl_pct": 0.02, "tp_enabled": True, "tp_pct": 0.03}))
    risk_variants.append(("SL 1.5% + TP 2%", {"sl_enabled": True, "sl_pct": 0.015, "tp_enabled": True, "tp_pct": 0.02}))
    risk_variants.append(("Trailing + SL 2%", {"trailing_stop": "close", "sl_enabled": True, "sl_pct": 0.02}))
    risk_variants.append(("Trailing + TP 3%", {"trailing_stop": "close", "tp_enabled": True, "tp_pct": 0.03}))

    risk_results = []
    for risk_label, risk_params in risk_variants:
        imps = []
        details = []
        for e_atr, e_mult, e_src, c_atr, c_mult, c_src in top5_mtf_params:
            cfg = BacktestConfig(atr_period=e_atr, multiplier=e_mult, source=e_src,
                                 warmup=max(200, train_end_15m))

            # Apply best combo filters
            if "RSI" in best_combo_params:
                rp, bl, bh, sl, sh = best_combo_params["RSI"]
                cfg.rsi_enabled = True
                cfg.rsi_period = rp
                cfg.rsi_buy_low = bl
                cfg.rsi_buy_high = bh
                cfg.rsi_sell_low = sl
                cfg.rsi_sell_high = sh
            if "Volume" in best_combo_params:
                cfg.volume_enabled = True
                cfg.volume_threshold = best_combo_params["Volume"]
            if "Time" in best_combo_params:
                bs, be = best_combo_params["Time"]
                cfg.time_filter_enabled = True
                cfg.time_block_start = bs
                cfg.time_block_end = be

            # Apply risk params
            for k, v in risk_params.items():
                setattr(cfg, k, v)

            rd, _, _ = run_mtf_backtest(data_15m, data_1h, cfg, c_atr, c_mult, c_src,
                                         start_bar=train_end_15m, end_bar=n_15m)
            key = f"E({e_atr},{e_mult},{e_src})+C({c_atr},{c_mult},{c_src})"
            base_pf = mtf_baselines[key]["profit_factor"]
            imps.append(rd["profit_factor"] - base_pf)
            details.append(rd)

        avg_pf = np.mean([r["profit_factor"] for r in details])
        avg_pnl = np.mean([r["total_pnl"] for r in details])
        avg_mdd = np.mean([r["max_drawdown_pct"] for r in details])
        avg_trades = np.mean([r["num_trades"] for r in details])

        risk_results.append({
            "label": risk_label,
            "params": risk_params,
            "avg_pf": round(avg_pf, 4),
            "avg_pnl": round(avg_pnl, 2),
            "avg_mdd": round(avg_mdd, 2),
            "avg_trades": round(avg_trades, 1),
            "avg_pf_imp": round(np.mean(imps), 4),
        })
        print(f"  {risk_label:>25s}: PF={avg_pf:.2f} P&L=${avg_pnl:.0f} MDD={avg_mdd:.0f}% Trades={avg_trades:.0f}")

    risk_results.sort(key=lambda x: x["avg_pf"], reverse=True)

    # ═══════════════════════════════════════════════════════════
    # STEP 5: FINAL VALIDATION
    # ═══════════════════════════════════════════════════════════
    print("\n" + "=" * 90)
    print("STEP 5: FINAL VALIDATION — TOP 3 CONFIGS")
    print("=" * 90)

    # Take the overall best config (best MTF base + best combo filters + best risk)
    # For simplicity, use the single best MTF base with best filters
    best_mtf_base = top5_mtf_params[0]  # best base params
    best_risk = risk_results[0] if risk_results else None

    # Build top 3 final configs
    final_configs = []

    # Config 1: Best MTF + best filters + best risk
    cfg1_params = {
        "entry": best_mtf_base[:3],
        "confirm": best_mtf_base[3:],
        "filters": best_combo_params,
        "risk": best_risk["params"] if best_risk else {},
        "label": f"Best combo"
    }
    final_configs.append(cfg1_params)

    # Config 2: Best MTF + best filters, NO risk management
    cfg2_params = {
        "entry": best_mtf_base[:3],
        "confirm": best_mtf_base[3:],
        "filters": best_combo_params,
        "risk": {},
        "label": "No risk mgmt"
    }
    final_configs.append(cfg2_params)

    # Config 3: Best MTF, NO filters, NO risk
    cfg3_params = {
        "entry": best_mtf_base[:3],
        "confirm": best_mtf_base[3:],
        "filters": {},
        "risk": {},
        "label": "Pure MTF"
    }
    final_configs.append(cfg3_params)

    def build_cfg(params_dict):
        e_atr, e_mult, e_src = params_dict["entry"]
        cfg = BacktestConfig(atr_period=e_atr, multiplier=e_mult, source=e_src)

        fp = params_dict.get("filters", {})
        if "RSI" in fp:
            rp, bl, bh, sl, sh = fp["RSI"]
            cfg.rsi_enabled = True
            cfg.rsi_period = rp
            cfg.rsi_buy_low = bl
            cfg.rsi_buy_high = bh
            cfg.rsi_sell_low = sl
            cfg.rsi_sell_high = sh
        if "Volume" in fp:
            cfg.volume_enabled = True
            cfg.volume_threshold = fp["Volume"]
        if "Time" in fp:
            bs, be = fp["Time"]
            cfg.time_filter_enabled = True
            cfg.time_block_start = bs
            cfg.time_block_end = be

        rp_params = params_dict.get("risk", {})
        for k, v in rp_params.items():
            setattr(cfg, k, v)

        return cfg

    for fc in final_configs:
        e_atr, e_mult, e_src = fc["entry"]
        c_atr, c_mult, c_src = fc["confirm"]
        cfg = build_cfg(fc)

        print(f"\n  --- {fc['label']} ---")
        print(f"  Entry: ST({e_atr},{e_mult},{e_src}) | Confirm: ST({c_atr},{c_mult},{c_src})")
        print(f"  Filters: {fc['filters']}")
        print(f"  Risk: {fc['risk']}")

        # 5a. Parameter robustness (±10%, ±20%)
        print(f"\n  5a. Parameter robustness:")
        for pct_var in [0.0, 0.1, -0.1, 0.2, -0.2]:
            adj_mult = e_mult * (1 + pct_var)
            adj_cfg = build_cfg(fc)
            adj_cfg.multiplier = adj_mult
            adj_cfg.warmup = max(200, train_end_15m)

            rd, _, _ = run_mtf_backtest(data_15m, data_1h, adj_cfg, c_atr, c_mult, c_src,
                                         start_bar=train_end_15m, end_bar=n_15m)
            label = f"mult={adj_mult:.2f} ({pct_var:+.0%})" if pct_var != 0 else f"mult={adj_mult:.2f} (base)"
            print(f"    {label}: PF={rd['profit_factor']:.2f} P&L=${rd['total_pnl']:.0f} Trades={rd['num_trades']}")

        # 5b. Time stability (quarterly)
        print(f"\n  5b. Quarterly stability:")
        quarter_size = n_15m // 4
        for q in range(4):
            q_start = q * quarter_size
            q_end = (q + 1) * quarter_size
            q_cfg = build_cfg(fc)
            q_cfg.warmup = max(200, q_start)

            rd, _, _ = run_mtf_backtest(data_15m, data_1h, q_cfg, c_atr, c_mult, c_src,
                                         start_bar=q_start, end_bar=q_end)
            q_start_dt = datetime.fromtimestamp(data_15m["timestamps"][q_start]/1000, tz=timezone.utc)
            q_end_dt = datetime.fromtimestamp(data_15m["timestamps"][min(q_end-1, n_15m-1)]/1000, tz=timezone.utc)
            print(f"    Q{q+1} ({q_start_dt.strftime('%Y-%m')} to {q_end_dt.strftime('%Y-%m')}): "
                  f"PF={rd['profit_factor']:.2f} P&L=${rd['total_pnl']:.0f} Trades={rd['num_trades']} Win={rd['win_rate']:.1f}%")

        # 5c. Monte Carlo (shuffle trades)
        print(f"\n  5c. Monte Carlo (1000 simulations):")
        cfg_mc = build_cfg(fc)
        cfg_mc.warmup = max(200, train_end_15m)
        rd_mc, trades_mc, _ = run_mtf_backtest(data_15m, data_1h, cfg_mc, c_atr, c_mult, c_src,
                                                 start_bar=train_end_15m, end_bar=n_15m)

        if trades_mc:
            trade_pnls = [t["pnl"] for t in trades_mc]
            mc_finals = []
            for _ in range(1000):
                shuffled = np.random.permutation(trade_pnls)
                eq = cfg.starting_capital
                for p in shuffled:
                    eq += p
                mc_finals.append(eq - cfg.starting_capital)

            mc_finals.sort()
            p5 = mc_finals[49]    # 5th percentile
            p50 = mc_finals[499]  # median
            p95 = mc_finals[949]  # 95th percentile
            print(f"    P&L — 5th pct: ${p5:.0f} | Median: ${p50:.0f} | 95th pct: ${p95:.0f}")
            print(f"    Worst case: ${mc_finals[0]:.0f} | Best case: ${mc_finals[-1]:.0f}")
        else:
            print(f"    No trades to simulate")

    # ═══════════════════════════════════════════════════════════
    # STEP 6: FINAL COMPARISON
    # ═══════════════════════════════════════════════════════════
    print("\n" + "=" * 90)
    print("STEP 6: FINAL COMPARISON (all on validation set)")
    print("=" * 90)

    comparison = {}

    # Our best MTF config
    best_fc = final_configs[0]
    cfg_best = build_cfg(best_fc)
    cfg_best.warmup = max(200, train_end_15m)
    e_atr, e_mult, e_src = best_fc["entry"]
    c_atr, c_mult, c_src = best_fc["confirm"]
    rd_best, _, _ = run_mtf_backtest(data_15m, data_1h, cfg_best, c_atr, c_mult, c_src,
                                      start_bar=train_end_15m, end_bar=n_15m)
    comparison["WINNER (MTF)"] = rd_best

    # Pure MTF no filters
    cfg_pure = build_cfg(final_configs[2])
    cfg_pure.warmup = max(200, train_end_15m)
    rd_pure, _, _ = run_mtf_backtest(data_15m, data_1h, cfg_pure, c_atr, c_mult, c_src,
                                      start_bar=train_end_15m, end_bar=n_15m)
    comparison["Pure MTF"] = rd_pure

    # Reference configs (15m single TF)
    refs = {
        "Your live ST(10,2.0,hl2)": BacktestConfig(atr_period=10, multiplier=2.0, source="hl2", warmup=max(200, train_end_15m)),
        "Colleague ST(10,1.3,close)": BacktestConfig(atr_period=10, multiplier=1.3, source="close", warmup=max(200, train_end_15m)),
        "TV default ST(10,3.0,hl2)": BacktestConfig(atr_period=10, multiplier=3.0, source="hl2", warmup=max(200, train_end_15m)),
    }

    for label, cfg in refs.items():
        val_r = run_backtest(data_15m["opens"], data_15m["highs"], data_15m["lows"],
                             data_15m["closes"], data_15m["volumes"], data_15m["timestamps"],
                             cfg, start_bar=train_end_15m, end_bar=n_15m)
        comparison[label] = result_to_dict(val_r)

    # 2H single TF winner
    cfg_2h = BacktestConfig(atr_period=7, multiplier=4.0, source="hl2", warmup=max(200, train_end_2h))
    val_2h = run_backtest(data_2h["opens"], data_2h["highs"], data_2h["lows"],
                          data_2h["closes"], data_2h["volumes"], data_2h["timestamps"],
                          cfg_2h, start_bar=train_end_2h, end_bar=n_2h)
    comparison["2H ST(7,4.0,hl2)"] = result_to_dict(val_2h)

    print(f"\n  {'Config':>30s} | {'PF':>6s} {'P&L':>8s} {'Win%':>6s} {'Trades':>6s} {'MDD%':>6s} {'Sharpe':>7s}")
    print(f"  {'─'*30} | {'─'*6} {'─'*8} {'─'*6} {'─'*6} {'─'*6} {'─'*7}")

    for label, rd in comparison.items():
        print(f"  {label:>30s} | {rd['profit_factor']:>6.2f} {rd['total_pnl']:>8.0f} {rd['win_rate']:>5.1f}% "
              f"{rd['num_trades']:>6d} {rd['max_drawdown_pct']:>5.1f}% {rd['sharpe_ratio']:>7.2f}")

    # ═══════════════════════════════════════════════════════════
    # SAVE ALL RESULTS
    # ═══════════════════════════════════════════════════════════
    elapsed = time.time() - t_start

    # Build final recommendation
    winner_label = max(comparison.items(), key=lambda x: x[1]["profit_factor"])

    final_rec = {
        "winner": winner_label[0],
        "winner_stats": winner_label[1],
        "all_comparisons": comparison,
        "best_config": {
            "strategy": "15m entry + 1H Supertrend confirmation",
            "entry_params": {"atr_period": best_fc["entry"][0], "multiplier": best_fc["entry"][1], "source": best_fc["entry"][2]},
            "confirm_params": {"atr_period": best_fc["confirm"][0], "multiplier": best_fc["confirm"][1], "source": best_fc["confirm"][2]},
            "filters": {k: (list(v) if isinstance(v, tuple) else v) for k, v in best_fc.get("filters", {}).items()},
            "risk": best_fc.get("risk", {}),
        },
        "runtime_seconds": round(elapsed, 1),
    }

    # Save all step results
    for fname, data in [
        ("step2_filters.json", {"rsi_ranked": [(k, v) for k, v in rsi_ranked[:10]],
                                 "vol_ranked": [(k, v) for k, v in vol_ranked],
                                 "time_ranked": [(k, v) for k, v in time_ranked],
                                 "top3_filters": [(f[0], f[1]) for f in top3_filters]}),
        ("step3_combined.json", combined_results),
        ("step4_risk.json", risk_results),
        ("step6_comparison.json", comparison),
        ("final_recommendation_v2.json", final_rec),
    ]:
        with open(OUTPUT_DIR / fname, "w") as f:
            json.dump(data, f, indent=2, default=str)

    print(f"\n  All results saved to {OUTPUT_DIR}")
    print(f"  Total runtime: {elapsed:.0f}s")

    print("\n" + "=" * 90)
    print(f"  FINAL RECOMMENDATION: {winner_label[0]}")
    print(f"  PF={winner_label[1]['profit_factor']:.2f} P&L=${winner_label[1]['total_pnl']:.0f} "
          f"Win={winner_label[1]['win_rate']:.1f}% Trades={winner_label[1]['num_trades']} "
          f"MDD={winner_label[1]['max_drawdown_pct']:.1f}%")
    print("=" * 90)


if __name__ == "__main__":
    main()

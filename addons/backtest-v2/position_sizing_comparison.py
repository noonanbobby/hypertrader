#!/usr/bin/env python3
"""
Position sizing comparison: 6 runs across 2 configs x 3 position sizes.
Reports compounding P&L, drawdown, risk of ruin, largest single loss.
"""

import json
import numpy as np
from pathlib import Path
from copy import deepcopy
from datetime import datetime, timezone

DATA_DIR = Path(__file__).parent.parent / "backtest-data"

import sys
sys.path.insert(0, str(Path(__file__).parent))
from engine import BacktestConfig, calc_supertrend, calc_rsi, calc_sma, calc_atr


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


def run_mtf_detailed(data_15m, data_1h, entry_atr, entry_mult, entry_src,
                     confirm_atr, confirm_mult, confirm_src,
                     position_pct, leverage, start_bar, end_bar,
                     # Filters
                     vol_enabled=False, vol_threshold=1.25,
                     time_enabled=False, time_block_start=22, time_block_end=6,
                     sl_enabled=False, sl_type="atr", sl_atr_mult=5.0,
                     starting_capital=500.0, taker_fee=0.00045, slippage=0.0001):
    """
    Full MTF backtest with detailed trade-level tracking for position sizing analysis.
    """
    d = data_15m
    n = end_bar

    # 1H Supertrend direction
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

    # 15m indicators
    o = d["opens"][:n]
    h = d["highs"][:n]
    l = d["lows"][:n]
    c = d["closes"][:n]
    v = d["volumes"][:n]
    ts = d["timestamps"][:n]

    st_line, st_dir = calc_supertrend(h, l, c, entry_atr, entry_mult, entry_src)

    vol_sma = None
    if vol_enabled:
        vol_sma = calc_sma(v, 20)

    atr = None
    if sl_enabled:
        atr = calc_atr(h, l, c, entry_atr)

    # State
    equity = starting_capital
    position = 0
    entry_price = 0.0
    position_size = 0.0
    entry_bar_idx = 0
    trades = []
    equity_curve = []
    min_equity = starting_capital
    pending = None

    for i in range(start_bar, n):
        # Execute pending at this bar's OPEN
        if pending is not None and i > start_bar:
            action = pending
            pending = None

            if action == "close" and position != 0:
                slip = o[i] * slippage
                fill = o[i] - slip * position
                pnl_raw = (fill - entry_price) * position * (position_size / entry_price)
                fee = position_size * taker_fee
                net_pnl = pnl_raw - fee

                trades.append({
                    "pnl": net_pnl,
                    "pnl_pct": net_pnl / equity * 100 if equity > 0 else 0,
                    "entry_price": entry_price,
                    "exit_price": fill,
                    "direction": position,
                    "size_usd": position_size,
                    "bars_held": i - entry_bar_idx,
                    "fee": fee,
                })
                equity += net_pnl
                min_equity = min(min_equity, equity)
                position = 0
                position_size = 0.0

            elif action.startswith("open") or action.startswith("flip"):
                # Close existing if flipping
                if position != 0:
                    slip = o[i] * slippage
                    fill_close = o[i] - slip * position
                    pnl_raw = (fill_close - entry_price) * position * (position_size / entry_price)
                    fee = position_size * taker_fee
                    net_pnl = pnl_raw - fee

                    trades.append({
                        "pnl": net_pnl,
                        "pnl_pct": net_pnl / equity * 100 if equity > 0 else 0,
                        "entry_price": entry_price,
                        "exit_price": fill_close,
                        "direction": position,
                        "size_usd": position_size,
                        "bars_held": i - entry_bar_idx,
                        "fee": fee,
                    })
                    equity += net_pnl
                    min_equity = min(min_equity, equity)

                # Open new — position size based on CURRENT equity (compounding)
                if equity <= 0:
                    position = 0
                    position_size = 0.0
                    continue

                new_dir = 1 if "long" in action else -1
                slip = o[i] * slippage
                fill_open = o[i] + slip * new_dir
                position_size = equity * position_pct * leverage
                fee = position_size * taker_fee
                equity -= fee
                min_equity = min(min_equity, equity)

                position = new_dir
                entry_price = fill_open
                entry_bar_idx = i

        # Mark-to-market equity curve
        if position != 0:
            unrealized = (c[i] - entry_price) * position * (position_size / entry_price)
            mtm_equity = equity + unrealized
        else:
            mtm_equity = equity
        equity_curve.append(mtm_equity)
        min_equity = min(min_equity, mtm_equity)

        if i >= n - 1:
            if position != 0:
                pending = "close"
            continue

        if np.isnan(st_dir[i]) or np.isnan(st_dir[i-1]):
            continue

        # Stop loss check
        if sl_enabled and position != 0 and atr is not None and not np.isnan(atr[i]):
            sl_dist = (sl_atr_mult * atr[i]) / entry_price
            if (position == 1 and c[i] < entry_price * (1 - sl_dist)) or \
               (position == -1 and c[i] > entry_price * (1 + sl_dist)):
                pending = "close"
                continue

        # Supertrend direction change
        if st_dir[i] == st_dir[i-1]:
            continue

        new_dir = 1 if st_dir[i] == 1 else -1

        # MTF filter
        if htf_dir[i] != new_dir:
            if position != 0:
                pending = "close"
            continue

        # Volume filter
        if vol_enabled and vol_sma is not None and not np.isnan(vol_sma[i]):
            if v[i] < vol_threshold * vol_sma[i]:
                continue

        # Time filter
        if time_enabled:
            hour_utc = (int(ts[i]) // 3600000) % 24
            if time_block_start > time_block_end:  # wraps midnight
                if hour_utc >= time_block_start or hour_utc < time_block_end:
                    continue
            else:
                if time_block_start <= hour_utc < time_block_end:
                    continue

        # Execute signal
        if position == 0:
            pending = "open_long" if new_dir == 1 else "open_short"
        elif position != new_dir:
            pending = "flip_long" if new_dir == 1 else "flip_short"

    # Close remaining
    if pending == "close" and position != 0:
        fill = c[n-1] * (1 - slippage * position)
        pnl_raw = (fill - entry_price) * position * (position_size / entry_price)
        fee = position_size * taker_fee
        net_pnl = pnl_raw - fee
        trades.append({
            "pnl": net_pnl,
            "pnl_pct": net_pnl / equity * 100 if equity > 0 else 0,
            "entry_price": entry_price,
            "exit_price": fill,
            "direction": position,
            "size_usd": position_size,
            "bars_held": n - 1 - entry_bar_idx,
            "fee": fee,
        })
        equity += net_pnl
        min_equity = min(min_equity, equity)
        if equity_curve:
            equity_curve[-1] = equity

    # Compute detailed stats
    num_trades = len(trades)
    total_pnl = equity - starting_capital
    total_pnl_pct = (equity / starting_capital - 1) * 100

    wins = [t for t in trades if t["pnl"] > 0]
    losses = [t for t in trades if t["pnl"] <= 0]
    win_rate = len(wins) / num_trades * 100 if num_trades > 0 else 0

    gross_profit = sum(t["pnl"] for t in wins)
    gross_loss = abs(sum(t["pnl"] for t in losses))
    pf = gross_profit / gross_loss if gross_loss > 0 else 9999.0

    largest_loss = min((t["pnl"] for t in trades), default=0)
    largest_win = max((t["pnl"] for t in trades), default=0)

    # Max drawdown from equity curve
    ec = np.array(equity_curve) if equity_curve else np.array([starting_capital])
    peak = np.maximum.accumulate(ec)
    dd_pct = (peak - ec) / peak * 100
    max_dd_pct = float(np.max(dd_pct))

    # Find the peak-to-trough details
    max_dd_idx = np.argmax(dd_pct)
    peak_idx = np.argmax(peak[:max_dd_idx + 1]) if max_dd_idx > 0 else 0
    peak_val = ec[peak_idx]
    trough_val = ec[max_dd_idx]

    # Risk of ruin
    risk_of_ruin = bool(min_equity < 100)
    lowest_equity = min_equity

    # Total fees
    total_fees = sum(t["fee"] for t in trades)

    return {
        "num_trades": num_trades,
        "final_equity": round(equity, 2),
        "total_pnl_usd": round(total_pnl, 2),
        "total_pnl_pct": round(total_pnl_pct, 1),
        "win_rate": round(win_rate, 1),
        "profit_factor": round(pf, 4),
        "max_drawdown_pct": round(max_dd_pct, 1),
        "max_dd_peak": round(peak_val, 2),
        "max_dd_trough": round(trough_val, 2),
        "largest_loss_usd": round(largest_loss, 2),
        "largest_win_usd": round(largest_win, 2),
        "risk_of_ruin": risk_of_ruin,
        "lowest_equity": round(lowest_equity, 2),
        "total_fees": round(total_fees, 2),
        "avg_trade_pnl": round(total_pnl / num_trades, 2) if num_trades > 0 else 0,
        "sharpe": round(float(np.mean(np.diff(ec) / ec[:-1]) / np.std(np.diff(ec) / ec[:-1]) * np.sqrt(35040)) if len(ec) > 1 and np.std(np.diff(ec) / ec[:-1]) > 0 else 0, 2),
        "equity_curve": ec.tolist(),
    }


def main():
    print("=" * 100)
    print("POSITION SIZING COMPARISON — Compounding (% of current equity)")
    print("=" * 100)

    data_15m = load_klines("binance_btc_15m.json")
    data_1h = load_klines("binance_btc_1h.json")

    n = data_15m["n"]
    train_end = int(n * 0.7)

    ts = data_15m["timestamps"]
    val_start_dt = datetime.fromtimestamp(ts[train_end]/1000, tz=timezone.utc)
    val_end_dt = datetime.fromtimestamp(ts[-1]/1000, tz=timezone.utc)
    print(f"\n  Validation period: {val_start_dt.strftime('%Y-%m-%d')} to {val_end_dt.strftime('%Y-%m-%d')}")
    print(f"  Starting capital: $500")

    # Two strategy configs
    configs = {
        "Pure MTF": {
            "entry": (8, 4.0, "hlc3"),
            "confirm": (10, 4.0, "close"),
            "vol_enabled": False,
            "time_enabled": False,
            "sl_enabled": False,
        },
        "MTF + Vol + Time + SL 5xATR": {
            "entry": (8, 4.0, "hlc3"),
            "confirm": (10, 4.0, "close"),
            "vol_enabled": True, "vol_threshold": 1.25,
            "time_enabled": True, "time_block_start": 22, "time_block_end": 6,
            "sl_enabled": True, "sl_type": "atr", "sl_atr_mult": 5.0,
        },
    }

    position_sizes = [
        (0.25, 10.0, "25% x 10x"),
        (0.35, 10.0, "35% x 10x"),
        (0.50, 10.0, "50% x 10x"),
    ]

    all_results = {}

    for strat_name, strat_cfg in configs.items():
        print(f"\n{'='*100}")
        print(f"  STRATEGY: {strat_name}")
        print(f"  Entry: ST({strat_cfg['entry'][0]}, {strat_cfg['entry'][1]}, {strat_cfg['entry'][2]}) on 15m")
        print(f"  Confirm: ST({strat_cfg['confirm'][0]}, {strat_cfg['confirm'][1]}, {strat_cfg['confirm'][2]}) on 1H")
        if strat_cfg.get("vol_enabled"):
            print(f"  Volume filter: > {strat_cfg['vol_threshold']}x avg")
        if strat_cfg.get("time_enabled"):
            print(f"  Time block: {strat_cfg['time_block_start']:02d}:00-{strat_cfg['time_block_end']:02d}:00 UTC")
        if strat_cfg.get("sl_enabled"):
            print(f"  Stop loss: {strat_cfg['sl_atr_mult']}x ATR")
        print(f"{'='*100}")

        strat_results = []

        for pos_pct, lev, label in position_sizes:
            e = strat_cfg["entry"]
            cf = strat_cfg["confirm"]

            result = run_mtf_detailed(
                data_15m, data_1h,
                entry_atr=e[0], entry_mult=e[1], entry_src=e[2],
                confirm_atr=cf[0], confirm_mult=cf[1], confirm_src=cf[2],
                position_pct=pos_pct, leverage=lev,
                start_bar=train_end, end_bar=n,
                vol_enabled=strat_cfg.get("vol_enabled", False),
                vol_threshold=strat_cfg.get("vol_threshold", 1.25),
                time_enabled=strat_cfg.get("time_enabled", False),
                time_block_start=strat_cfg.get("time_block_start", 22),
                time_block_end=strat_cfg.get("time_block_end", 6),
                sl_enabled=strat_cfg.get("sl_enabled", False),
                sl_type=strat_cfg.get("sl_type", "atr"),
                sl_atr_mult=strat_cfg.get("sl_atr_mult", 5.0),
            )

            result["label"] = label
            result["position_pct"] = pos_pct
            result["leverage"] = lev
            result["effective_exposure"] = f"{pos_pct * lev * 100:.0f}% of equity"
            strat_results.append(result)

        all_results[strat_name] = strat_results

        # Print table
        print(f"\n  {'Position Size':>18s} | {'Net P&L $':>10s} {'P&L %':>8s} {'Final $':>9s} | {'PF':>6s} {'Win%':>6s} {'Trades':>6s} | {'MDD%':>6s} {'Biggest Loss':>13s} {'Lowest $':>9s} {'Ruin?':>6s} | {'Fees':>8s} {'Sharpe':>7s}")
        print(f"  {'─'*18} | {'─'*10} {'─'*8} {'─'*9} | {'─'*6} {'─'*6} {'─'*6} | {'─'*6} {'─'*13} {'─'*9} {'─'*6} | {'─'*8} {'─'*7}")

        for r in strat_results:
            ruin_flag = "YES!" if r["risk_of_ruin"] else "no"
            print(f"  {r['label']:>18s} | "
                  f"${r['total_pnl_usd']:>9.2f} {r['total_pnl_pct']:>7.1f}% ${r['final_equity']:>8.2f} | "
                  f"{r['profit_factor']:>6.2f} {r['win_rate']:>5.1f}% {r['num_trades']:>6d} | "
                  f"{r['max_drawdown_pct']:>5.1f}% ${r['largest_loss_usd']:>12.2f} ${r['lowest_equity']:>8.2f} {ruin_flag:>6s} | "
                  f"${r['total_fees']:>7.2f} {r['sharpe']:>7.2f}")

        # Detailed drawdown analysis
        print(f"\n  Drawdown details:")
        for r in strat_results:
            print(f"    {r['label']}: Peak ${r['max_dd_peak']:.2f} -> Trough ${r['max_dd_trough']:.2f} "
                  f"(lost ${r['max_dd_peak'] - r['max_dd_trough']:.2f}, {r['max_drawdown_pct']:.1f}%)")

        # Effective leverage analysis
        print(f"\n  Effective exposure per trade:")
        for r in strat_results:
            print(f"    {r['label']}: {r['effective_exposure']} notional per trade")

    # ═══════════════════════════════════════════════════════════
    # SIDE-BY-SIDE COMPARISON
    # ═══════════════════════════════════════════════════════════
    print(f"\n\n{'='*100}")
    print("SIDE-BY-SIDE: All 6 configurations")
    print(f"{'='*100}")
    print(f"\n  {'Config':>42s} | {'P&L $':>9s} {'P&L %':>8s} {'Final $':>9s} {'PF':>6s} {'MDD%':>6s} {'MaxLoss':>9s} {'Low $':>8s} {'Ruin':>5s}")
    print(f"  {'─'*42} | {'─'*9} {'─'*8} {'─'*9} {'─'*6} {'─'*6} {'─'*9} {'─'*8} {'─'*5}")

    for strat_name, strat_results in all_results.items():
        for r in strat_results:
            label = f"{strat_name} @ {r['label']}"
            ruin = "YES" if r["risk_of_ruin"] else "no"
            print(f"  {label:>42s} | "
                  f"${r['total_pnl_usd']:>8.0f} {r['total_pnl_pct']:>7.1f}% ${r['final_equity']:>8.0f} "
                  f"{r['profit_factor']:>6.2f} {r['max_drawdown_pct']:>5.1f}% "
                  f"${r['largest_loss_usd']:>8.0f} ${r['lowest_equity']:>7.0f} {ruin:>5s}")

    # Save
    output = {}
    for strat_name, strat_results in all_results.items():
        output[strat_name] = []
        for r in strat_results:
            r_copy = {k: v for k, v in r.items() if k != "equity_curve"}
            output[strat_name].append(r_copy)

    out_path = Path(__file__).parent / "position_sizing_comparison.json"
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2)
    print(f"\n  Results saved to {out_path}")


if __name__ == "__main__":
    main()

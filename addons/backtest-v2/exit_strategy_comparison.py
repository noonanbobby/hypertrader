#!/usr/bin/env python3
"""
Exit Strategy Comparison: Flip-Only vs 15m-Flip Exit

Strategy A (Current bot behavior — flip only):
  Entry: 15m ST flip + 1H ST agrees + ADX >= 15 rising
  Exit: ONLY when opposite direction also passes ALL filters (flip)

Strategy B (Exit on 15m flip):
  Entry: 15m ST flip + 1H ST agrees + ADX >= 15 rising
  Exit: immediately when 15m ST flips against position, regardless of 1H/ADX

Tests:
  1. Full 730-day results
  2. Walk-forward train/validate split
  3. All 6 starting points
  4. Parameter robustness
"""

import json
import sys
import numpy as np
from pathlib import Path
from dataclasses import dataclass, field

sys.path.insert(0, str(Path(__file__).parent))
from engine import calc_tr, calc_atr_rma, calc_supertrend, BacktestResult

DATA_DIR = Path(__file__).parent.parent / "backtest-data"

# ═══════════════════════════════════════════════════════════════
# ADX CALCULATION
# ═══════════════════════════════════════════════════════════════

def calc_adx(highs, lows, closes, period=14):
    n = len(highs)
    plus_dm = np.zeros(n)
    minus_dm = np.zeros(n)
    for i in range(1, n):
        up = highs[i] - highs[i-1]
        down = lows[i-1] - lows[i]
        if up > down and up > 0:
            plus_dm[i] = up
        if down > up and down > 0:
            minus_dm[i] = down

    tr = calc_tr(highs, lows, closes)

    # RMA smoothing
    def rma_smooth(data, p):
        out = np.zeros(n)
        out[p] = np.sum(data[1:p+1])
        for i in range(p+1, n):
            out[i] = out[i-1] - out[i-1]/p + data[i]
        return out

    s_tr = rma_smooth(tr, period)
    s_pdm = rma_smooth(plus_dm, period)
    s_mdm = rma_smooth(minus_dm, period)

    dx = np.zeros(n)
    for i in range(period, n):
        if s_tr[i] > 0:
            pdi = 100 * s_pdm[i] / s_tr[i]
            mdi = 100 * s_mdm[i] / s_tr[i]
            total = pdi + mdi
            if total > 0:
                dx[i] = 100 * abs(pdi - mdi) / total

    adx = np.full(n, np.nan)
    fv = period
    while fv < n and dx[fv] == 0:
        fv += 1
    if fv + period >= n:
        return adx

    adx[fv + period - 1] = np.mean(dx[fv:fv+period])
    for i in range(fv + period, n):
        adx[i] = (adx[i-1] * (period-1) + dx[i]) / period

    return adx


# ═══════════════════════════════════════════════════════════════
# LOAD DATA
# ═══════════════════════════════════════════════════════════════

def load_candles(filepath):
    data = json.load(open(filepath))
    ts = np.array([c["open_time"] for c in data], dtype=np.int64)
    o = np.array([float(c["open"]) for c in data])
    h = np.array([float(c["high"]) for c in data])
    l = np.array([float(c["low"]) for c in data])
    c = np.array([float(c["close"]) for c in data])
    v = np.array([float(c["volume"]) for c in data])
    return ts, o, h, l, c, v


def align_1h_to_15m(ts_15m, dir_1h, ts_1h):
    """Map 1H supertrend direction to each 15m bar."""
    aligned = np.full(len(ts_15m), np.nan)
    j = 0
    for i in range(len(ts_15m)):
        while j < len(ts_1h) - 1 and ts_1h[j+1] <= ts_15m[i]:
            j += 1
        if j < len(dir_1h):
            aligned[i] = dir_1h[j]
    return aligned


# ═══════════════════════════════════════════════════════════════
# BACKTEST ENGINE WITH MTF + ADX
# ═══════════════════════════════════════════════════════════════

@dataclass
class MTFConfig:
    # 15m Supertrend
    st_atr: int = 8
    st_mult: float = 4.0
    st_source: str = "hlc3"
    # 1H Supertrend
    htf_atr: int = 10
    htf_mult: float = 4.0
    htf_source: str = "close"
    # ADX
    adx_period: int = 14
    adx_min: float = 15.0
    adx_rising_lookback: int = 4
    # Fees
    taker_fee: float = 0.00045
    slippage: float = 0.0001
    # Sizing
    starting_capital: float = 500.0
    position_pct: float = 0.25
    leverage: float = 10.0
    warmup: int = 200


@dataclass
class Trade:
    entry_bar: int
    entry_price: float
    direction: int
    size_usd: float
    exit_bar: int = 0
    exit_price: float = 0.0
    exit_reason: str = ""
    pnl: float = 0.0
    fees: float = 0.0


def run_mtf_backtest(
    ts_15m, opens, highs, lows, closes, volumes,
    ts_1h, h_1h, l_1h, c_1h, o_1h,
    config: MTFConfig,
    exit_on_15m_flip: bool = False,  # Strategy B
    start_bar: int = 0,
    end_bar: int = -1,
):
    n = len(closes)
    if end_bar < 0:
        end_bar = n

    # Slice
    o = opens[:end_bar]; h = highs[:end_bar]; l = lows[:end_bar]
    c = closes[:end_bar]; v = volumes[:end_bar]; ts = ts_15m[:end_bar]
    nn = len(c)

    # 15m Supertrend
    st_line_15m, st_dir_15m = calc_supertrend(h, l, c, config.st_atr, config.st_mult, config.st_source)

    # 1H Supertrend (on 1H data, then align to 15m)
    h1h = h_1h[:]; l1h = l_1h[:]; c1h = c_1h[:]
    _, st_dir_1h_raw = calc_supertrend(h1h, l1h, c1h, config.htf_atr, config.htf_mult, config.htf_source)
    st_dir_1h = align_1h_to_15m(ts, st_dir_1h_raw, ts_1h)

    # ADX on 15m
    adx = calc_adx(h, l, c, config.adx_period)

    # Simulation
    eff_start = max(start_bar, config.warmup)
    equity = config.starting_capital
    position = 0
    entry_price = 0.0
    entry_bar = 0
    position_size = 0.0
    trades = []
    equity_curve = []
    pending_action = None

    def apply_fill(price, direction, is_close):
        slip = price * config.slippage
        if is_close:
            return price - slip if direction == 1 else price + slip
        else:
            return price + slip if direction == 1 else price - slip

    def calc_fee(notional):
        return notional * config.taker_fee

    def filters_pass(bar_idx):
        """Check if 1H confirmation + ADX filters pass at this bar."""
        # 1H must agree with 15m
        if np.isnan(st_dir_1h[bar_idx]):
            return False
        if st_dir_15m[bar_idx] != st_dir_1h[bar_idx]:
            return False
        # ADX >= min and rising
        if np.isnan(adx[bar_idx]):
            return False
        if adx[bar_idx] < config.adx_min:
            return False
        lookback = config.adx_rising_lookback
        prev_bar = bar_idx - lookback
        if prev_bar >= 0 and not np.isnan(adx[prev_bar]):
            if adx[bar_idx] <= adx[prev_bar]:
                return False
        return True

    for i in range(eff_start, nn):
        # Execute pending
        if pending_action is not None and i > eff_start:
            action = pending_action
            pending_action = None

            if action == "close" and position != 0:
                fill_price = apply_fill(o[i], position, True)
                pnl_raw = (fill_price - entry_price) * position * (position_size / entry_price)
                fee = calc_fee(position_size)
                trades.append(Trade(entry_bar, entry_price, position, position_size,
                                    i, fill_price, "exit_15m_flip" if exit_on_15m_flip else "signal",
                                    pnl_raw - fee, fee))
                equity += pnl_raw - fee
                position = 0; position_size = 0.0

            elif action in ("open_long", "open_short"):
                new_dir = 1 if action == "open_long" else -1
                fill_price = apply_fill(o[i], new_dir, False)
                position_size = equity * config.position_pct * config.leverage
                fee = calc_fee(position_size)
                equity -= fee
                position = new_dir; entry_price = fill_price; entry_bar = i

            elif action in ("flip_long", "flip_short"):
                if position != 0:
                    fill_price_close = apply_fill(o[i], position, True)
                    pnl_raw = (fill_price_close - entry_price) * position * (position_size / entry_price)
                    fee_close = calc_fee(position_size)
                    trades.append(Trade(entry_bar, entry_price, position, position_size,
                                        i, fill_price_close, "flip", pnl_raw - fee_close, fee_close))
                    equity += pnl_raw - fee_close

                new_dir = 1 if action == "flip_long" else -1
                fill_price_open = apply_fill(o[i], new_dir, False)
                position_size = equity * config.position_pct * config.leverage
                fee_open = calc_fee(position_size)
                equity -= fee_open
                position = new_dir; entry_price = fill_price_open; entry_bar = i

        # MTM equity
        if position != 0:
            unrealized = (c[i] - entry_price) * position * (position_size / entry_price)
            equity_curve.append(equity + unrealized)
        else:
            equity_curve.append(equity)

        if i >= nn - 1:
            if position != 0:
                pending_action = "close"
            continue

        # Check indicators
        if np.isnan(st_dir_15m[i]) or np.isnan(st_line_15m[i]):
            continue

        curr_dir_15m = st_dir_15m[i]
        prev_dir_15m = st_dir_15m[i-1] if i > 0 and not np.isnan(st_dir_15m[i-1]) else curr_dir_15m
        direction_changed_15m = (curr_dir_15m != prev_dir_15m)

        # ─── Strategy B: Exit on 15m flip regardless of filters ───
        if exit_on_15m_flip and position != 0 and direction_changed_15m:
            new_signal = 1 if curr_dir_15m == 1 else -1
            if new_signal != position:
                # 15m flipped against us — close immediately
                # But only ENTER if filters pass
                if filters_pass(i):
                    pending_action = "flip_long" if new_signal == 1 else "flip_short"
                else:
                    pending_action = "close"
                continue

        # ─── Entry/Flip logic (both strategies) ───
        if not direction_changed_15m:
            continue

        new_signal_dir = 1 if curr_dir_15m == 1 else -1

        # All filters must pass for entry (both strategies)
        if not filters_pass(i):
            continue

        # Execute
        if position == 0:
            pending_action = "open_long" if new_signal_dir == 1 else "open_short"
        elif position != new_signal_dir:
            pending_action = "flip_long" if new_signal_dir == 1 else "flip_short"

    # Close remaining
    if position != 0 and pending_action == "close":
        last_i = nn - 1
        fill_price = apply_fill(c[last_i], position, True)
        pnl_raw = (fill_price - entry_price) * position * (position_size / entry_price)
        fee = calc_fee(position_size)
        trades.append(Trade(entry_bar, entry_price, position, position_size,
                            last_i, fill_price, "end_of_data", pnl_raw - fee, fee))
        equity += pnl_raw - fee
        if equity_curve:
            equity_curve[-1] = equity

    # Stats
    result = BacktestResult(config=None)
    result.trades = trades
    result.equity_curve = equity_curve
    result.num_trades = len(trades)
    result.final_equity = equity
    result.total_pnl = equity - config.starting_capital
    result.total_fees = sum(t.fees for t in trades)
    result.start_bar = eff_start
    result.end_bar = end_bar

    if trades:
        wins = [t for t in trades if t.pnl > 0]
        losses = [t for t in trades if t.pnl <= 0]
        result.win_rate = len(wins) / len(trades) * 100
        gross_profit = sum(t.pnl for t in wins)
        gross_loss = abs(sum(t.pnl for t in losses))
        result.profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')

    if equity_curve:
        ec = np.array(equity_curve)
        peak = np.maximum.accumulate(ec)
        drawdown = (peak - ec) / peak
        result.max_drawdown_pct = float(np.max(drawdown)) * 100
        if len(ec) > 1:
            returns = np.diff(ec) / ec[:-1]
            if np.std(returns) > 0:
                result.sharpe_ratio = float(np.mean(returns) / np.std(returns) * np.sqrt(35040))

    return result


# ═══════════════════════════════════════════════════════════════
# MAIN COMPARISON
# ═══════════════════════════════════════════════════════════════

def fmt_result(r):
    pf = f"{r.profit_factor:.2f}" if r.profit_factor < 9999 else "INF"
    return {
        "trades": r.num_trades,
        "win_rate": f"{r.win_rate:.1f}%",
        "pf": pf,
        "mdd": f"{r.max_drawdown_pct:.1f}%",
        "sharpe": f"{r.sharpe_ratio:.2f}",
        "pnl": f"${r.total_pnl:.2f}",
        "final": f"${r.final_equity:.2f}",
        "fees": f"${r.total_fees:.2f}",
    }


def print_comparison(label, result_a, result_b):
    a = fmt_result(result_a)
    b = fmt_result(result_b)

    print(f"\n{'─'*70}")
    print(f"  {label}")
    print(f"{'─'*70}")
    print(f"  {'Metric':<18} {'Strategy A (flip only)':<25} {'Strategy B (15m exit)':<25}")
    print(f"  {'─'*16}   {'─'*23}   {'─'*23}")
    for key in ["trades", "win_rate", "pf", "mdd", "sharpe", "pnl", "final", "fees"]:
        labels = {"trades": "Trades", "win_rate": "Win Rate", "pf": "Profit Factor",
                  "mdd": "Max Drawdown", "sharpe": "Sharpe", "pnl": "Total P&L",
                  "final": "Final Equity", "fees": "Total Fees"}
        print(f"  {labels[key]:<18} {a[key]:<25} {b[key]:<25}")


def main():
    print("=" * 70)
    print("  EXIT STRATEGY COMPARISON")
    print("  A = Flip only (current bot)  |  B = Exit on 15m flip")
    print("  Entry: ST(8,4.0,hlc3) + 1H ST(10,4.0,close) + ADX>=15 rising(4)")
    print("=" * 70)

    # Load data
    print("\nLoading data...")
    ts_15m, o_15m, h_15m, l_15m, c_15m, v_15m = load_candles(DATA_DIR / "binance_btc_15m.json")
    ts_1h, o_1h, h_1h, l_1h, c_1h, v_1h = load_candles(DATA_DIR / "binance_btc_1h.json")
    print(f"  15m: {len(c_15m)} bars ({len(c_15m)//96} days)")
    print(f"  1H:  {len(c_1h)} bars")

    config = MTFConfig()

    # ─── TEST 1: Full 730-day results ───
    print("\n\n" + "=" * 70)
    print("  TEST 1: FULL 730-DAY BACKTEST")
    print("=" * 70)

    result_a = run_mtf_backtest(ts_15m, o_15m, h_15m, l_15m, c_15m, v_15m,
                                 ts_1h, h_1h, l_1h, c_1h, o_1h, config,
                                 exit_on_15m_flip=False)
    result_b = run_mtf_backtest(ts_15m, o_15m, h_15m, l_15m, c_15m, v_15m,
                                 ts_1h, h_1h, l_1h, c_1h, o_1h, config,
                                 exit_on_15m_flip=True)
    print_comparison("Full Period", result_a, result_b)

    # ─── TEST 2: Walk-forward train/validate split ───
    print("\n\n" + "=" * 70)
    print("  TEST 2: WALK-FORWARD (70% train / 30% validate)")
    print("=" * 70)

    split = int(len(c_15m) * 0.7)
    # Train
    train_a = run_mtf_backtest(ts_15m, o_15m, h_15m, l_15m, c_15m, v_15m,
                                ts_1h, h_1h, l_1h, c_1h, o_1h, config,
                                exit_on_15m_flip=False, end_bar=split)
    train_b = run_mtf_backtest(ts_15m, o_15m, h_15m, l_15m, c_15m, v_15m,
                                ts_1h, h_1h, l_1h, c_1h, o_1h, config,
                                exit_on_15m_flip=True, end_bar=split)
    print_comparison("Train Period (70%)", train_a, train_b)

    # Validate
    val_a = run_mtf_backtest(ts_15m, o_15m, h_15m, l_15m, c_15m, v_15m,
                              ts_1h, h_1h, l_1h, c_1h, o_1h, config,
                              exit_on_15m_flip=False, start_bar=split)
    val_b = run_mtf_backtest(ts_15m, o_15m, h_15m, l_15m, c_15m, v_15m,
                              ts_1h, h_1h, l_1h, c_1h, o_1h, config,
                              exit_on_15m_flip=True, start_bar=split)
    print_comparison("Validate Period (30%)", val_a, val_b)

    # ─── TEST 3: 6 Starting Points ───
    print("\n\n" + "=" * 70)
    print("  TEST 3: 6 STARTING POINTS (staggered by ~120 days)")
    print("=" * 70)

    total_bars = len(c_15m)
    segment = total_bars // 6
    for sp in range(6):
        start = sp * segment
        r_a = run_mtf_backtest(ts_15m, o_15m, h_15m, l_15m, c_15m, v_15m,
                                ts_1h, h_1h, l_1h, c_1h, o_1h, config,
                                exit_on_15m_flip=False, start_bar=start)
        r_b = run_mtf_backtest(ts_15m, o_15m, h_15m, l_15m, c_15m, v_15m,
                                ts_1h, h_1h, l_1h, c_1h, o_1h, config,
                                exit_on_15m_flip=True, start_bar=start)
        days = (total_bars - start) // 96
        print_comparison(f"Start #{sp+1} (bar {start}, ~{days} days)", r_a, r_b)

    # ─── TEST 4: Parameter Robustness ───
    print("\n\n" + "=" * 70)
    print("  TEST 4: PARAMETER ROBUSTNESS")
    print("=" * 70)

    param_sets = [
        {"st_atr": 8,  "st_mult": 4.0, "htf_atr": 10, "htf_mult": 4.0, "adx_min": 15, "label": "Base (8/4+10/4 ADX15)"},
        {"st_atr": 10, "st_mult": 4.0, "htf_atr": 10, "htf_mult": 4.0, "adx_min": 15, "label": "ST ATR 10"},
        {"st_atr": 8,  "st_mult": 3.0, "htf_atr": 10, "htf_mult": 4.0, "adx_min": 15, "label": "ST Mult 3.0"},
        {"st_atr": 8,  "st_mult": 5.0, "htf_atr": 10, "htf_mult": 4.0, "adx_min": 15, "label": "ST Mult 5.0"},
        {"st_atr": 8,  "st_mult": 4.0, "htf_atr": 10, "htf_mult": 3.0, "adx_min": 15, "label": "1H Mult 3.0"},
        {"st_atr": 8,  "st_mult": 4.0, "htf_atr": 10, "htf_mult": 4.0, "adx_min": 20, "label": "ADX Min 20"},
        {"st_atr": 8,  "st_mult": 4.0, "htf_atr": 10, "htf_mult": 4.0, "adx_min": 10, "label": "ADX Min 10"},
    ]

    print(f"\n  {'Config':<25} {'A: PF':<10} {'A: WR':<10} {'A: MDD':<10} {'B: PF':<10} {'B: WR':<10} {'B: MDD':<10} {'Winner':<8}")
    print(f"  {'─'*23}   {'─'*8}   {'─'*8}   {'─'*8}   {'─'*8}   {'─'*8}   {'─'*8}   {'─'*6}")

    a_wins = 0
    b_wins = 0
    for ps in param_sets:
        cfg = MTFConfig(
            st_atr=ps["st_atr"], st_mult=ps["st_mult"],
            htf_atr=ps["htf_atr"], htf_mult=ps["htf_mult"],
            adx_min=ps["adx_min"],
        )
        r_a = run_mtf_backtest(ts_15m, o_15m, h_15m, l_15m, c_15m, v_15m,
                                ts_1h, h_1h, l_1h, c_1h, o_1h, cfg,
                                exit_on_15m_flip=False)
        r_b = run_mtf_backtest(ts_15m, o_15m, h_15m, l_15m, c_15m, v_15m,
                                ts_1h, h_1h, l_1h, c_1h, o_1h, cfg,
                                exit_on_15m_flip=True)

        pf_a = f"{r_a.profit_factor:.2f}" if r_a.profit_factor < 9999 else "INF"
        pf_b = f"{r_b.profit_factor:.2f}" if r_b.profit_factor < 9999 else "INF"
        winner = "A" if r_a.profit_factor > r_b.profit_factor else "B"
        if winner == "A": a_wins += 1
        else: b_wins += 1

        print(f"  {ps['label']:<25} {pf_a:<10} {r_a.win_rate:.1f}%{'':<5} {r_a.max_drawdown_pct:.1f}%{'':<5} "
              f"{pf_b:<10} {r_b.win_rate:.1f}%{'':<5} {r_b.max_drawdown_pct:.1f}%{'':<5} {winner}")

    print(f"\n  Parameter robustness: A wins {a_wins}/{len(param_sets)}, B wins {b_wins}/{len(param_sets)}")

    # ─── FINAL VERDICT ───
    print("\n" + "=" * 70)
    print("  FINAL VERDICT")
    print("=" * 70)
    pf_a_full = result_a.profit_factor
    pf_b_full = result_b.profit_factor
    if pf_a_full > pf_b_full:
        print(f"\n  Strategy A (flip only) is SUPERIOR")
        print(f"  PF: {pf_a_full:.2f} vs {pf_b_full:.2f}")
    else:
        print(f"\n  Strategy B (15m exit) is SUPERIOR")
        print(f"  PF: {pf_b_full:.2f} vs {pf_a_full:.2f}")
    print(f"  A trades: {result_a.num_trades}, B trades: {result_b.num_trades}")
    print(f"  A MDD: {result_a.max_drawdown_pct:.1f}%, B MDD: {result_b.max_drawdown_pct:.1f}%")
    print(f"  A WR: {result_a.win_rate:.1f}%, B WR: {result_b.win_rate:.1f}%")
    print("=" * 70)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Three-way exit strategy comparison: A vs B vs C

Strategy A — Flip only (current bot):
  Entry: 15m flip + 1H agrees + ADX>=15 rising(4) + squeeze off
  Exit: only when opposite direction passes ALL filters

Strategy B — Exit on 15m flip, go flat:
  Entry: 15m flip + 1H agrees + ADX>=15 rising(4) + squeeze off
  Exit: immediately on 15m flip against position, go flat
  Re-entry: only when all filters pass again

Strategy C — Always in, flip on 15m crossover:
  Entry: 15m flip + 1H agrees + ADX>=15 rising(4) + squeeze off
  Exit: on 15m flip against position, IMMEDIATELY open opposite
  No filters needed for the flip — filters only gate first entry from flat

Params: ST(8, 4.0, hlc3), 1H ST(10, 4.0, close), ADX(14)>=15 rising(4),
        Squeeze BB(20,2) KC(20,1.5), $125 fixed sizing, 10x leverage, 0.045% taker
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
# INDICATOR CALCULATIONS
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


def calc_squeeze(highs, lows, closes, bb_len=20, bb_mult=2.0, kc_len=20, kc_mult=1.5):
    """Returns boolean array: True = squeeze ON (blocked), False = squeeze OFF."""
    n = len(closes)
    squeeze = np.full(n, False)

    tr = calc_tr(highs, lows, closes)

    for i in range(max(bb_len, kc_len) - 1, n):
        # Bollinger Bands
        bb_window = closes[i - bb_len + 1:i + 1]
        bb_basis = np.mean(bb_window)
        bb_std = np.std(bb_window, ddof=0)
        upper_bb = bb_basis + bb_mult * bb_std
        lower_bb = bb_basis - bb_mult * bb_std

        # Keltner Channel
        kc_basis = np.mean(closes[i - kc_len + 1:i + 1])
        kc_atr = np.mean(tr[i - kc_len + 1:i + 1])
        upper_kc = kc_basis + kc_mult * kc_atr
        lower_kc = kc_basis - kc_mult * kc_atr

        squeeze[i] = (lower_bb > lower_kc) and (upper_bb < upper_kc)

    return squeeze


# ═══════════════════════════════════════════════════════════════
# DATA LOADING
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
    aligned = np.full(len(ts_15m), np.nan)
    j = 0
    for i in range(len(ts_15m)):
        while j < len(ts_1h) - 1 and ts_1h[j+1] <= ts_15m[i]:
            j += 1
        if j < len(dir_1h):
            aligned[i] = dir_1h[j]
    return aligned


# ═══════════════════════════════════════════════════════════════
# UNIFIED ENGINE — supports all 3 strategies via mode parameter
# ═══════════════════════════════════════════════════════════════

@dataclass
class MTFConfig:
    st_atr: int = 8
    st_mult: float = 4.0
    st_source: str = "hlc3"
    htf_atr: int = 10
    htf_mult: float = 4.0
    htf_source: str = "close"
    adx_period: int = 14
    adx_min: float = 15.0
    adx_rising_lookback: int = 4
    squeeze_enabled: bool = True
    sqz_bb_len: int = 20
    sqz_bb_mult: float = 2.0
    sqz_kc_len: int = 20
    sqz_kc_mult: float = 1.5
    taker_fee: float = 0.00045
    slippage: float = 0.0001
    starting_capital: float = 500.0
    fixed_size_usd: float = 125.0
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


def run_backtest(
    ts_15m, opens, highs, lows, closes, volumes,
    ts_1h, h_1h, l_1h, c_1h, o_1h,
    config: MTFConfig,
    mode: str = "A",  # "A" = flip only, "B" = 15m exit flat, "C" = always in flip
    start_bar: int = 0,
    end_bar: int = -1,
):
    n = len(closes)
    if end_bar < 0:
        end_bar = n

    o = opens[:end_bar]; h = highs[:end_bar]; l = lows[:end_bar]
    c = closes[:end_bar]; v = volumes[:end_bar]; ts = ts_15m[:end_bar]
    nn = len(c)

    # 15m Supertrend
    st_line_15m, st_dir_15m = calc_supertrend(h, l, c, config.st_atr, config.st_mult, config.st_source)

    # 1H Supertrend
    _, st_dir_1h_raw = calc_supertrend(h_1h, l_1h, c_1h, config.htf_atr, config.htf_mult, config.htf_source)
    st_dir_1h = align_1h_to_15m(ts, st_dir_1h_raw, ts_1h)

    # ADX on 15m
    adx = calc_adx(h, l, c, config.adx_period)

    # Squeeze on 15m
    squeeze = None
    if config.squeeze_enabled:
        squeeze = calc_squeeze(h, l, c, config.sqz_bb_len, config.sqz_bb_mult,
                               config.sqz_kc_len, config.sqz_kc_mult)

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

    def get_position_size():
        return config.fixed_size_usd * config.leverage

    def all_filters_pass(bar_idx):
        """Full entry filter: 1H agrees + ADX >= min & rising + squeeze off."""
        if np.isnan(st_dir_1h[bar_idx]):
            return False
        if st_dir_15m[bar_idx] != st_dir_1h[bar_idx]:
            return False
        if np.isnan(adx[bar_idx]):
            return False
        if adx[bar_idx] < config.adx_min:
            return False
        lb = config.adx_rising_lookback
        prev_bar = bar_idx - lb
        if prev_bar >= 0 and not np.isnan(adx[prev_bar]):
            if adx[bar_idx] <= adx[prev_bar]:
                return False
        if config.squeeze_enabled and squeeze is not None:
            if squeeze[bar_idx]:
                return False
        return True

    for i in range(eff_start, nn):
        # ─── Execute pending action at bar open ───
        if pending_action is not None and i > eff_start:
            action = pending_action
            pending_action = None

            if action == "close" and position != 0:
                fill_price = apply_fill(o[i], position, True)
                pnl_raw = (fill_price - entry_price) * position * (position_size / entry_price)
                fee = calc_fee(position_size)
                trades.append(Trade(entry_bar, entry_price, position, position_size,
                                    i, fill_price, "close", pnl_raw - fee, fee))
                equity += pnl_raw - fee
                position = 0; position_size = 0.0

            elif action in ("open_long", "open_short"):
                new_dir = 1 if action == "open_long" else -1
                fill_price = apply_fill(o[i], new_dir, False)
                position_size = get_position_size()
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
                position_size = get_position_size()
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

        if np.isnan(st_dir_15m[i]) or np.isnan(st_line_15m[i]):
            continue

        curr_dir = st_dir_15m[i]
        prev_dir = st_dir_15m[i-1] if i > 0 and not np.isnan(st_dir_15m[i-1]) else curr_dir
        flipped_15m = (curr_dir != prev_dir)
        new_signal = 1 if curr_dir == 1 else -1

        # ═══════════════════════════════════════════════════
        # STRATEGY-SPECIFIC EXIT LOGIC
        # ═══════════════════════════════════════════════════

        if mode == "A":
            # Strategy A: Only flip when ALL filters pass for new direction
            if not flipped_15m:
                continue
            if not all_filters_pass(i):
                continue
            if position == 0:
                pending_action = "open_long" if new_signal == 1 else "open_short"
            elif position != new_signal:
                pending_action = "flip_long" if new_signal == 1 else "flip_short"

        elif mode == "B":
            # Strategy B: Exit on 15m flip (go flat), re-enter only with filters
            if flipped_15m and position != 0 and new_signal != position:
                # 15m flipped against us — exit
                if all_filters_pass(i):
                    # Filters pass for new direction — flip directly
                    pending_action = "flip_long" if new_signal == 1 else "flip_short"
                else:
                    # Filters don't pass — just close, go flat
                    pending_action = "close"
                continue

            # Entry from flat or same-direction flip with filters
            if flipped_15m and all_filters_pass(i):
                if position == 0:
                    pending_action = "open_long" if new_signal == 1 else "open_short"
                elif position != new_signal:
                    pending_action = "flip_long" if new_signal == 1 else "flip_short"

        elif mode == "C":
            # Strategy C: Always in — flip on ANY 15m crossover
            # Filters only gate entry from flat
            if flipped_15m and position != 0 and new_signal != position:
                # Already in a position — flip immediately, no filters
                pending_action = "flip_long" if new_signal == 1 else "flip_short"
                continue

            # Entry from flat requires all filters
            if flipped_15m and position == 0 and all_filters_pass(i):
                pending_action = "open_long" if new_signal == 1 else "open_short"

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
# OUTPUT HELPERS
# ═══════════════════════════════════════════════════════════════

def fmt(r):
    pf = f"{r.profit_factor:.2f}" if r.profit_factor < 9999 else "INF"
    return {
        "trades": str(r.num_trades),
        "wr": f"{r.win_rate:.1f}%",
        "pf": pf,
        "mdd": f"{r.max_drawdown_pct:.1f}%",
        "sharpe": f"{r.sharpe_ratio:.2f}",
        "pnl": f"${r.total_pnl:+.2f}",
        "final": f"${r.final_equity:.2f}",
        "fees": f"${r.total_fees:.2f}",
    }


def print3(label, ra, rb, rc):
    a, b, c = fmt(ra), fmt(rb), fmt(rc)
    print(f"\n{'─'*80}")
    print(f"  {label}")
    print(f"{'─'*80}")
    print(f"  {'Metric':<16} {'A: Flip Only':<22} {'B: 15m Exit Flat':<22} {'C: Always In Flip':<22}")
    print(f"  {'─'*14}   {'─'*20}   {'─'*20}   {'─'*20}")
    for key in ["trades", "wr", "pf", "mdd", "sharpe", "pnl", "final", "fees"]:
        names = {"trades": "Trades", "wr": "Win Rate", "pf": "Profit Factor",
                 "mdd": "Max Drawdown", "sharpe": "Sharpe", "pnl": "Total P&L",
                 "final": "Final Equity", "fees": "Total Fees"}
        print(f"  {names[key]:<16} {a[key]:<22} {b[key]:<22} {c[key]:<22}")


# ═══════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════

def main():
    print("=" * 80)
    print("  THREE-WAY EXIT STRATEGY COMPARISON: A vs B vs C")
    print("  A = Flip only (current bot)")
    print("  B = Exit on 15m flip, go flat, re-enter with filters")
    print("  C = Always in — flip on any 15m crossover (no filters for flip)")
    print("  Entry: ST(8,4,hlc3) + 1H(10,4,close) + ADX>=15 rising(4) + SQZ off")
    print("  Sizing: $125 fixed × 10x leverage = $1,250 notional")
    print("=" * 80)

    print("\nLoading data...")
    ts_15m, o_15m, h_15m, l_15m, c_15m, v_15m = load_candles(DATA_DIR / "binance_btc_15m.json")
    ts_1h, o_1h, h_1h, l_1h, c_1h, v_1h = load_candles(DATA_DIR / "binance_btc_1h.json")
    print(f"  15m: {len(c_15m)} bars ({len(c_15m)//96} days)")
    print(f"  1H:  {len(c_1h)} bars")

    config = MTFConfig()

    # ═══ TEST 1: Full 730-day backtest ═══
    print("\n\n" + "=" * 80)
    print("  TEST 1: FULL 730-DAY BACKTEST")
    print("=" * 80)

    ra = run_backtest(ts_15m, o_15m, h_15m, l_15m, c_15m, v_15m,
                       ts_1h, h_1h, l_1h, c_1h, o_1h, config, mode="A")
    rb = run_backtest(ts_15m, o_15m, h_15m, l_15m, c_15m, v_15m,
                       ts_1h, h_1h, l_1h, c_1h, o_1h, config, mode="B")
    rc = run_backtest(ts_15m, o_15m, h_15m, l_15m, c_15m, v_15m,
                       ts_1h, h_1h, l_1h, c_1h, o_1h, config, mode="C")
    print3("Full Period (730 days)", ra, rb, rc)

    # ═══ TEST 2: Walk-forward ═══
    print("\n\n" + "=" * 80)
    print("  TEST 2: WALK-FORWARD (70% train / 30% validate)")
    print("=" * 80)

    split = int(len(c_15m) * 0.7)

    tra = run_backtest(ts_15m, o_15m, h_15m, l_15m, c_15m, v_15m,
                        ts_1h, h_1h, l_1h, c_1h, o_1h, config, mode="A", end_bar=split)
    trb = run_backtest(ts_15m, o_15m, h_15m, l_15m, c_15m, v_15m,
                        ts_1h, h_1h, l_1h, c_1h, o_1h, config, mode="B", end_bar=split)
    trc = run_backtest(ts_15m, o_15m, h_15m, l_15m, c_15m, v_15m,
                        ts_1h, h_1h, l_1h, c_1h, o_1h, config, mode="C", end_bar=split)
    print3("Train Period (70%)", tra, trb, trc)

    va = run_backtest(ts_15m, o_15m, h_15m, l_15m, c_15m, v_15m,
                       ts_1h, h_1h, l_1h, c_1h, o_1h, config, mode="A", start_bar=split)
    vb = run_backtest(ts_15m, o_15m, h_15m, l_15m, c_15m, v_15m,
                       ts_1h, h_1h, l_1h, c_1h, o_1h, config, mode="B", start_bar=split)
    vc = run_backtest(ts_15m, o_15m, h_15m, l_15m, c_15m, v_15m,
                       ts_1h, h_1h, l_1h, c_1h, o_1h, config, mode="C", start_bar=split)
    print3("Validate Period (30%)", va, vb, vc)

    wf_pass_a = va.profit_factor > 1.0
    wf_pass_b = vb.profit_factor > 1.0
    wf_pass_c = vc.profit_factor > 1.0

    # ═══ TEST 3: 6 Starting Points ═══
    print("\n\n" + "=" * 80)
    print("  TEST 3: 6 STARTING POINTS")
    print("=" * 80)

    total_bars = len(c_15m)
    segment = total_bars // 6
    sp_profitable = {"A": 0, "B": 0, "C": 0}

    for sp in range(6):
        start = sp * segment
        days = (total_bars - start) // 96
        sa = run_backtest(ts_15m, o_15m, h_15m, l_15m, c_15m, v_15m,
                           ts_1h, h_1h, l_1h, c_1h, o_1h, config, mode="A", start_bar=start)
        sb = run_backtest(ts_15m, o_15m, h_15m, l_15m, c_15m, v_15m,
                           ts_1h, h_1h, l_1h, c_1h, o_1h, config, mode="B", start_bar=start)
        sc = run_backtest(ts_15m, o_15m, h_15m, l_15m, c_15m, v_15m,
                           ts_1h, h_1h, l_1h, c_1h, o_1h, config, mode="C", start_bar=start)
        print3(f"Start #{sp+1} (bar {start}, ~{days} days)", sa, sb, sc)
        if sa.total_pnl > 0: sp_profitable["A"] += 1
        if sb.total_pnl > 0: sp_profitable["B"] += 1
        if sc.total_pnl > 0: sp_profitable["C"] += 1

    # ═══ TEST 4: Parameter Robustness ═══
    print("\n\n" + "=" * 80)
    print("  TEST 4: PARAMETER ROBUSTNESS")
    print("=" * 80)

    param_sets = [
        {"st_atr": 8,  "st_mult": 4.0, "htf_atr": 10, "htf_mult": 4.0, "adx_min": 15, "label": "Base (8/4+10/4 ADX15)"},
        {"st_atr": 10, "st_mult": 4.0, "htf_atr": 10, "htf_mult": 4.0, "adx_min": 15, "label": "ST ATR 10"},
        {"st_atr": 8,  "st_mult": 3.0, "htf_atr": 10, "htf_mult": 4.0, "adx_min": 15, "label": "ST Mult 3.0"},
        {"st_atr": 8,  "st_mult": 5.0, "htf_atr": 10, "htf_mult": 4.0, "adx_min": 15, "label": "ST Mult 5.0"},
        {"st_atr": 8,  "st_mult": 4.0, "htf_atr": 10, "htf_mult": 3.0, "adx_min": 15, "label": "1H Mult 3.0"},
        {"st_atr": 8,  "st_mult": 4.0, "htf_atr": 10, "htf_mult": 4.0, "adx_min": 20, "label": "ADX Min 20"},
        {"st_atr": 8,  "st_mult": 4.0, "htf_atr": 10, "htf_mult": 4.0, "adx_min": 10, "label": "ADX Min 10"},
    ]

    print(f"\n  {'Config':<25} {'A: PF':<8} {'A: MDD':<8} {'B: PF':<8} {'B: MDD':<8} {'C: PF':<8} {'C: MDD':<8} {'Best':<6}")
    print(f"  {'─'*23}   {'─'*6}  {'─'*6}  {'─'*6}  {'─'*6}  {'─'*6}  {'─'*6}  {'─'*4}")

    robustness = {"A": 0, "B": 0, "C": 0}
    for ps in param_sets:
        cfg = MTFConfig(st_atr=ps["st_atr"], st_mult=ps["st_mult"],
                        htf_atr=ps["htf_atr"], htf_mult=ps["htf_mult"], adx_min=ps["adx_min"])
        pa = run_backtest(ts_15m, o_15m, h_15m, l_15m, c_15m, v_15m,
                           ts_1h, h_1h, l_1h, c_1h, o_1h, cfg, mode="A")
        pb = run_backtest(ts_15m, o_15m, h_15m, l_15m, c_15m, v_15m,
                           ts_1h, h_1h, l_1h, c_1h, o_1h, cfg, mode="B")
        pc = run_backtest(ts_15m, o_15m, h_15m, l_15m, c_15m, v_15m,
                           ts_1h, h_1h, l_1h, c_1h, o_1h, cfg, mode="C")

        pfs = {"A": pa.profit_factor, "B": pb.profit_factor, "C": pc.profit_factor}
        best = max(pfs, key=pfs.get)
        robustness[best] += 1

        def fp(v): return f"{v:.2f}" if v < 9999 else "INF"
        print(f"  {ps['label']:<25} {fp(pa.profit_factor):<8} {pa.max_drawdown_pct:.1f}%{'':<3} "
              f"{fp(pb.profit_factor):<8} {pb.max_drawdown_pct:.1f}%{'':<3} "
              f"{fp(pc.profit_factor):<8} {pc.max_drawdown_pct:.1f}%{'':<3} {best}")

    print(f"\n  Robustness wins: A={robustness['A']}/7  B={robustness['B']}/7  C={robustness['C']}/7")

    # ═══ FINAL SCORECARD ═══
    print("\n\n" + "=" * 80)
    print("  FINAL SCORECARD")
    print("=" * 80)

    print(f"\n  {'Check':<35} {'A: Flip Only':<18} {'B: 15m Flat':<18} {'C: Always In':<18}")
    print(f"  {'─'*33}   {'─'*16}   {'─'*16}   {'─'*16}")
    print(f"  {'Full PF > 1.0':<35} {'PASS' if ra.profit_factor > 1 else 'FAIL':<18} {'PASS' if rb.profit_factor > 1 else 'FAIL':<18} {'PASS' if rc.profit_factor > 1 else 'FAIL':<18}")
    print(f"  {'Walk-forward PF > 1.0':<35} {'PASS' if wf_pass_a else 'FAIL':<18} {'PASS' if wf_pass_b else 'FAIL':<18} {'PASS' if wf_pass_c else 'FAIL':<18}")
    print(f"  {'All 6 starts profitable':<35} {sp_profitable['A']}/6{'':<14} {sp_profitable['B']}/6{'':<14} {sp_profitable['C']}/6")
    print(f"  {'Param robustness (wins/7)':<35} {robustness['A']}/7{'':<14} {robustness['B']}/7{'':<14} {robustness['C']}/7")
    print(f"  {'MDD < 50%':<35} {'PASS' if ra.max_drawdown_pct < 50 else 'FAIL':<18} {'PASS' if rb.max_drawdown_pct < 50 else 'FAIL':<18} {'PASS' if rc.max_drawdown_pct < 50 else 'FAIL':<18}")

    # Determine winner
    scores = {"A": 0, "B": 0, "C": 0}
    for s, r in [("A", ra), ("B", rb), ("C", rc)]:
        if r.profit_factor > 1: scores[s] += 1
    if wf_pass_a: scores["A"] += 1
    if wf_pass_b: scores["B"] += 1
    if wf_pass_c: scores["C"] += 1
    scores["A"] += sp_profitable["A"]
    scores["B"] += sp_profitable["B"]
    scores["C"] += sp_profitable["C"]
    scores["A"] += robustness["A"]
    scores["B"] += robustness["B"]
    scores["C"] += robustness["C"]

    winner = max(scores, key=scores.get)
    names = {"A": "Flip Only", "B": "15m Exit Flat", "C": "Always In Flip"}
    print(f"\n  WINNER: Strategy {winner} ({names[winner]})")
    print(f"  Scores: A={scores['A']}  B={scores['B']}  C={scores['C']}")
    print("=" * 80)


if __name__ == "__main__":
    main()

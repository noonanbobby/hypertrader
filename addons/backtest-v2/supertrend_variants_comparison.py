#!/usr/bin/env python3
"""
Supertrend Variants Comparison — Full Validation Suite

Tests 6 configurations:
  1. Baseline:    Standard ST(8,4,hlc3) + ADX>=15 rising(4) + squeeze off
  2. Evasive+F:   Evasive ST(8,4,nt=1.0,ea=0.5) + ADX + squeeze
  3. Recovery+F:  Recovery ST(8,4,ra=5,rt=1.0) + ADX + squeeze
  4. Evasive raw: Evasive ST only (no ADX/squeeze)
  5. Recovery raw: Recovery ST only (no ADX/squeeze)
  6. Baseline raw: Standard ST only (no ADX/squeeze)

All use Strategy B exit logic (exit on 15m flip, go flat, re-enter with filters).
1H confirmation ST(10,4,close) applied to all filtered variants.
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
    n = len(closes)
    squeeze = np.full(n, False)
    tr = calc_tr(highs, lows, closes)
    for i in range(max(bb_len, kc_len) - 1, n):
        bb_window = closes[i - bb_len + 1:i + 1]
        bb_basis = np.mean(bb_window)
        bb_std = np.std(bb_window, ddof=0)
        upper_bb = bb_basis + bb_mult * bb_std
        lower_bb = bb_basis - bb_mult * bb_std
        kc_basis = np.mean(closes[i - kc_len + 1:i + 1])
        kc_atr = np.mean(tr[i - kc_len + 1:i + 1])
        upper_kc = kc_basis + kc_mult * kc_atr
        lower_kc = kc_basis - kc_mult * kc_atr
        squeeze[i] = (lower_bb > lower_kc) and (upper_bb < upper_kc)
    return squeeze


# ═══════════════════════════════════════════════════════════════
# SUPERTREND VARIANTS
# ═══════════════════════════════════════════════════════════════

def calc_evasive_supertrend(highs, lows, closes, atr_period=8, multiplier=4.0,
                             noise_threshold=1.0, expansion_alpha=0.5):
    """
    Evasive SuperTrend — pushes band away from price during noisy conditions.
    When price is within noise_threshold * ATR of the band, the band expands
    away to avoid premature flips.
    """
    n = len(closes)
    src = (highs + lows) / 2  # hl2
    tr = calc_tr(highs, lows, closes)
    atr = calc_atr_rma(tr, atr_period)

    st_band = np.full(n, np.nan)
    direction = np.ones(n)  # 1 = bull, -1 = bear

    start = atr_period - 1
    # Initialize
    st_band[start] = src[start] - multiplier * atr[start]  # start bullish
    direction[start] = 1

    for i in range(start + 1, n):
        if np.isnan(atr[i]):
            st_band[i] = st_band[i-1]
            direction[i] = direction[i-1]
            continue

        upper_base = src[i] + multiplier * atr[i]
        lower_base = src[i] - multiplier * atr[i]
        prev_band = st_band[i-1]

        if direction[i-1] == 1:  # BULL
            dist = abs(closes[i] - prev_band)
            if dist < atr[i] * noise_threshold:
                # Noisy — push band DOWN away from price
                st_band[i] = prev_band - atr[i] * expansion_alpha
            else:
                # Standard: band can only go up
                st_band[i] = max(lower_base, prev_band)

            if closes[i] < st_band[i]:
                direction[i] = -1
                st_band[i] = upper_base
            else:
                direction[i] = 1

        else:  # BEAR
            dist = abs(closes[i] - prev_band)
            if dist < atr[i] * noise_threshold:
                # Noisy — push band UP away from price
                st_band[i] = prev_band + atr[i] * expansion_alpha
            else:
                # Standard: band can only go down
                st_band[i] = min(upper_base, prev_band)

            if closes[i] > st_band[i]:
                direction[i] = 1
                st_band[i] = lower_base
            else:
                direction[i] = -1

    return st_band, direction


def calc_recovery_supertrend(highs, lows, closes, atr_period=8, multiplier=4.0,
                              recovery_alpha=5.0, recovery_threshold=1.0):
    """
    SuperTrend Recovery — tightens the band when the trade is at a loss
    beyond recovery_threshold * ATR, using exponential smoothing toward price.
    This allows faster exit from losing trades while keeping winners running.
    """
    n = len(closes)
    src = (highs + lows) / 2  # hl2
    tr = calc_tr(highs, lows, closes)
    atr = calc_atr_rma(tr, atr_period)

    st_band = np.full(n, np.nan)
    direction = np.ones(n)
    switch_price = np.zeros(n)
    alpha = recovery_alpha / 100.0

    start = atr_period - 1
    st_band[start] = src[start] - multiplier * atr[start]
    direction[start] = 1
    switch_price[start] = closes[start]

    for i in range(start + 1, n):
        if np.isnan(atr[i]):
            st_band[i] = st_band[i-1]
            direction[i] = direction[i-1]
            switch_price[i] = switch_price[i-1]
            continue

        upper_base = src[i] + multiplier * atr[i]
        lower_base = src[i] - multiplier * atr[i]
        prev_band = st_band[i-1]
        deviation = recovery_threshold * atr[i]

        if direction[i-1] == 1:  # BULL
            is_at_loss = (switch_price[i-1] - closes[i]) > deviation
            if is_at_loss:
                target_band = alpha * closes[i] + (1 - alpha) * prev_band
            else:
                target_band = lower_base
            st_band[i] = max(target_band, prev_band)

            if closes[i] < st_band[i]:
                direction[i] = -1
                st_band[i] = upper_base
                switch_price[i] = closes[i]
            else:
                direction[i] = 1
                switch_price[i] = switch_price[i-1]

        else:  # BEAR
            is_at_loss = (closes[i] - switch_price[i-1]) > deviation
            if is_at_loss:
                target_band = alpha * closes[i] + (1 - alpha) * prev_band
            else:
                target_band = upper_base
            st_band[i] = min(target_band, prev_band)

            if closes[i] > st_band[i]:
                direction[i] = 1
                st_band[i] = lower_base
                switch_price[i] = closes[i]
            else:
                direction[i] = -1
                switch_price[i] = switch_price[i-1]

    return st_band, direction


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
# UNIFIED ENGINE — Strategy B with configurable ST variant
# ═══════════════════════════════════════════════════════════════

@dataclass
class Config:
    # ST variant
    st_variant: str = "standard"  # "standard", "evasive", "recovery"
    st_atr: int = 8
    st_mult: float = 4.0
    st_source: str = "hlc3"
    # Evasive params
    noise_threshold: float = 1.0
    expansion_alpha: float = 0.5
    # Recovery params
    recovery_alpha: float = 5.0
    recovery_threshold: float = 1.0
    # 1H confirmation
    htf_atr: int = 10
    htf_mult: float = 4.0
    htf_source: str = "close"
    # Filters
    use_filters: bool = True
    use_1h_confirm: bool = True
    adx_period: int = 14
    adx_min: float = 15.0
    adx_rising_lookback: int = 4
    squeeze_enabled: bool = True
    sqz_bb_len: int = 20
    sqz_bb_mult: float = 2.0
    sqz_kc_len: int = 20
    sqz_kc_mult: float = 1.5
    # Execution
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
    pnl: float = 0.0
    fees: float = 0.0


def compute_15m_supertrend(h, l, c, config):
    """Dispatch to the appropriate ST variant."""
    if config.st_variant == "evasive":
        return calc_evasive_supertrend(h, l, c, config.st_atr, config.st_mult,
                                        config.noise_threshold, config.expansion_alpha)
    elif config.st_variant == "recovery":
        return calc_recovery_supertrend(h, l, c, config.st_atr, config.st_mult,
                                         config.recovery_alpha, config.recovery_threshold)
    else:
        return calc_supertrend(h, l, c, config.st_atr, config.st_mult, config.st_source)


def run_backtest(ts_15m, opens, highs, lows, closes, volumes,
                  ts_1h, h_1h, l_1h, c_1h,
                  config: Config, start_bar=0, end_bar=-1):
    n = len(closes)
    if end_bar < 0:
        end_bar = n

    o = opens[:end_bar]; h = highs[:end_bar]; l = lows[:end_bar]
    c = closes[:end_bar]; ts = ts_15m[:end_bar]
    nn = len(c)

    # 15m Supertrend (variant)
    st_line, st_dir = compute_15m_supertrend(h, l, c, config)

    # 1H Supertrend (always standard for confirmation)
    _, st_dir_1h_raw = calc_supertrend(h_1h, l_1h, c_1h, config.htf_atr, config.htf_mult, config.htf_source)
    st_dir_1h = align_1h_to_15m(ts, st_dir_1h_raw, ts_1h)

    # Filters
    adx = calc_adx(h, l, c, config.adx_period) if config.use_filters else None
    squeeze = calc_squeeze(h, l, c, config.sqz_bb_len, config.sqz_bb_mult,
                           config.sqz_kc_len, config.sqz_kc_mult) if (config.use_filters and config.squeeze_enabled) else None

    eff_start = max(start_bar, config.warmup)
    equity = config.starting_capital
    position = 0; entry_price = 0.0; entry_bar = 0; position_size = 0.0
    trades = []; equity_curve = []; pending = None

    def fill(price, d, is_close):
        s = price * config.slippage
        return (price - s if d == 1 else price + s) if is_close else (price + s if d == 1 else price - s)

    def fee(notional):
        return notional * config.taker_fee

    def filters_pass(i):
        if not config.use_filters and not config.use_1h_confirm:
            return True
        # 1H must agree (if enabled)
        if config.use_1h_confirm:
            if np.isnan(st_dir_1h[i]) or st_dir[i] != st_dir_1h[i]:
                return False
        if not config.use_filters:
            return True
        # ADX
        if adx is not None:
            if np.isnan(adx[i]) or adx[i] < config.adx_min:
                return False
            prev = i - config.adx_rising_lookback
            if prev >= 0 and not np.isnan(adx[prev]) and adx[i] <= adx[prev]:
                return False
        # Squeeze
        if squeeze is not None and squeeze[i]:
            return False
        return True

    for i in range(eff_start, nn):
        if pending is not None and i > eff_start:
            act = pending; pending = None
            if act == "close" and position != 0:
                fp = fill(o[i], position, True)
                pnl = (fp - entry_price) * position * (position_size / entry_price)
                f = fee(position_size)
                trades.append(Trade(entry_bar, entry_price, position, position_size, i, fp, pnl - f, f))
                equity += pnl - f; position = 0; position_size = 0.0
            elif act in ("open_long", "open_short"):
                d = 1 if act == "open_long" else -1
                fp = fill(o[i], d, False)
                position_size = config.fixed_size_usd * config.leverage
                f = fee(position_size); equity -= f
                position = d; entry_price = fp; entry_bar = i
            elif act in ("flip_long", "flip_short"):
                if position != 0:
                    fp = fill(o[i], position, True)
                    pnl = (fp - entry_price) * position * (position_size / entry_price)
                    f = fee(position_size)
                    trades.append(Trade(entry_bar, entry_price, position, position_size, i, fp, pnl - f, f))
                    equity += pnl - f
                d = 1 if act == "flip_long" else -1
                fp2 = fill(o[i], d, False)
                position_size = config.fixed_size_usd * config.leverage
                f2 = fee(position_size); equity -= f2
                position = d; entry_price = fp2; entry_bar = i

        if position != 0:
            unr = (c[i] - entry_price) * position * (position_size / entry_price)
            equity_curve.append(equity + unr)
        else:
            equity_curve.append(equity)

        if i >= nn - 1:
            if position != 0: pending = "close"
            continue

        if np.isnan(st_dir[i]):
            continue

        curr = st_dir[i]
        prev = st_dir[i-1] if i > 0 and not np.isnan(st_dir[i-1]) else curr
        flipped = curr != prev
        sig = 1 if curr == 1 else -1

        # Strategy B: exit on 15m flip, re-enter only with filters
        if flipped and position != 0 and sig != position:
            if filters_pass(i):
                pending = "flip_long" if sig == 1 else "flip_short"
            else:
                pending = "close"
            continue

        if flipped and filters_pass(i):
            if position == 0:
                pending = "open_long" if sig == 1 else "open_short"
            elif position != sig:
                pending = "flip_long" if sig == 1 else "flip_short"

    if position != 0 and pending == "close":
        fp = fill(c[nn-1], position, True)
        pnl = (fp - entry_price) * position * (position_size / entry_price)
        f = fee(position_size)
        trades.append(Trade(entry_bar, entry_price, position, position_size, nn-1, fp, pnl - f, f))
        equity += pnl - f
        if equity_curve: equity_curve[-1] = equity

    r = BacktestResult(config=None)
    r.trades = trades; r.equity_curve = equity_curve
    r.num_trades = len(trades); r.final_equity = equity
    r.total_pnl = equity - config.starting_capital
    r.total_fees = sum(t.fees for t in trades)
    if trades:
        wins = [t for t in trades if t.pnl > 0]
        losses = [t for t in trades if t.pnl <= 0]
        r.win_rate = len(wins) / len(trades) * 100
        gp = sum(t.pnl for t in wins)
        gl = abs(sum(t.pnl for t in losses))
        r.profit_factor = gp / gl if gl > 0 else float('inf')
    if equity_curve:
        ec = np.array(equity_curve)
        pk = np.maximum.accumulate(ec)
        dd = (pk - ec) / pk
        r.max_drawdown_pct = float(np.max(dd)) * 100
        if len(ec) > 1:
            rets = np.diff(ec) / ec[:-1]
            if np.std(rets) > 0:
                r.sharpe_ratio = float(np.mean(rets) / np.std(rets) * np.sqrt(35040))
    return r


# ═══════════════════════════════════════════════════════════════
# DISPLAY
# ═══════════════════════════════════════════════════════════════

def fp(v):
    return f"{v:.2f}" if v < 9999 else "INF"

def run_suite(label, configs, ts_15m, o_15m, h_15m, l_15m, c_15m, v_15m, ts_1h, h_1h, l_1h, c_1h):
    """Run full validation suite for a list of named configs."""
    names = [c[0] for c in configs]
    cfgs = [c[1] for c in configs]
    ncols = len(cfgs)
    col_w = 20

    def header():
        h = f"  {'Metric':<14}"
        for nm in names:
            h += f" {nm:<{col_w}}"
        return h

    def row(metric, values):
        r = f"  {metric:<14}"
        for v in values:
            r += f" {v:<{col_w}}"
        return r

    def divider():
        return f"  {'─'*12}  " + "  ".join(["─" * (col_w - 2)] * ncols)

    # Full 730-day
    print(f"\n{'─'*90}")
    print(f"  {label} — Full Period")
    print(f"{'─'*90}")
    full_results = []
    for cfg in cfgs:
        full_results.append(run_backtest(ts_15m, o_15m, h_15m, l_15m, c_15m, v_15m,
                                          ts_1h, h_1h, l_1h, c_1h, cfg))
    print(header())
    print(divider())
    print(row("Trades", [str(r.num_trades) for r in full_results]))
    print(row("Win Rate", [f"{r.win_rate:.1f}%" for r in full_results]))
    print(row("Profit Factor", [fp(r.profit_factor) for r in full_results]))
    print(row("Max Drawdown", [f"{r.max_drawdown_pct:.1f}%" for r in full_results]))
    print(row("Sharpe", [f"{r.sharpe_ratio:.2f}" for r in full_results]))
    print(row("Total P&L", [f"${r.total_pnl:+.2f}" for r in full_results]))
    print(row("Final Equity", [f"${r.final_equity:.2f}" for r in full_results]))
    print(row("Fees", [f"${r.total_fees:.2f}" for r in full_results]))

    # Walk-forward
    split = int(len(c_15m) * 0.7)
    print(f"\n{'─'*90}")
    print(f"  {label} — Walk-Forward Validate (30%)")
    print(f"{'─'*90}")
    wf_results = []
    for cfg in cfgs:
        wf_results.append(run_backtest(ts_15m, o_15m, h_15m, l_15m, c_15m, v_15m,
                                        ts_1h, h_1h, l_1h, c_1h, cfg, start_bar=split))
    print(header())
    print(divider())
    print(row("Trades", [str(r.num_trades) for r in wf_results]))
    print(row("Profit Factor", [fp(r.profit_factor) for r in wf_results]))
    print(row("Max Drawdown", [f"{r.max_drawdown_pct:.1f}%" for r in wf_results]))
    print(row("Sharpe", [f"{r.sharpe_ratio:.2f}" for r in wf_results]))
    print(row("P&L", [f"${r.total_pnl:+.2f}" for r in wf_results]))

    # 6 starting points
    total_bars = len(c_15m)
    seg = total_bars // 6
    sp_profit = [0] * ncols
    sp_pfs = [[] for _ in range(ncols)]
    for sp in range(6):
        start = sp * seg
        for j, cfg in enumerate(cfgs):
            r = run_backtest(ts_15m, o_15m, h_15m, l_15m, c_15m, v_15m,
                              ts_1h, h_1h, l_1h, c_1h, cfg, start_bar=start)
            if r.total_pnl > 0:
                sp_profit[j] += 1
            sp_pfs[j].append(r.profit_factor)

    # Parameter robustness (+/-20% on ATR and mult)
    robust_wins = [0] * ncols
    robust_total = 0
    for atr_factor in [0.8, 1.0, 1.2]:
        for mult_factor in [0.8, 1.0, 1.2]:
            if atr_factor == 1.0 and mult_factor == 1.0:
                continue  # skip base
            robust_total += 1
            pfs = []
            for j, cfg in enumerate(cfgs):
                test_cfg = Config(
                    st_variant=cfg.st_variant,
                    st_atr=max(2, int(round(cfg.st_atr * atr_factor))),
                    st_mult=round(cfg.st_mult * mult_factor, 1),
                    st_source=cfg.st_source,
                    noise_threshold=cfg.noise_threshold,
                    expansion_alpha=cfg.expansion_alpha,
                    recovery_alpha=cfg.recovery_alpha,
                    recovery_threshold=cfg.recovery_threshold,
                    use_filters=cfg.use_filters,
                    adx_min=cfg.adx_min,
                )
                r = run_backtest(ts_15m, o_15m, h_15m, l_15m, c_15m, v_15m,
                                  ts_1h, h_1h, l_1h, c_1h, test_cfg)
                pfs.append(r.profit_factor)
            best_j = np.argmax(pfs)
            robust_wins[best_j] += 1

    # Scorecard
    print(f"\n{'─'*90}")
    print(f"  {label} — SCORECARD")
    print(f"{'─'*90}")
    print(header())
    print(divider())
    print(row("Full PF", [fp(r.profit_factor) for r in full_results]))
    print(row("Full PF > 1.0", ["PASS" if r.profit_factor > 1.0 else "FAIL" for r in full_results]))
    print(row("WF PF", [fp(r.profit_factor) for r in wf_results]))
    print(row("WF PF > 1.0", ["PASS" if r.profit_factor > 1.0 else "FAIL" for r in wf_results]))
    print(row("Starts 6/6", [f"{sp}/6" for sp in sp_profit]))
    print(row("MDD < 50%", ["PASS" if r.max_drawdown_pct < 50 else "FAIL" for r in full_results]))
    print(row("Robust wins", [f"{w}/{robust_total}" for w in robust_wins]))

    return full_results, wf_results, sp_profit, robust_wins


def main():
    print("=" * 90)
    print("  SUPERTREND VARIANTS — FULL VALIDATION SUITE")
    print("  All using Strategy B exit (15m flip → flat → re-enter with filters)")
    print("  Sizing: $125 × 10x = $1,250 notional | Fees: 0.045% taker")
    print("=" * 90)

    print("\nLoading data...")
    ts_15m, o_15m, h_15m, l_15m, c_15m, v_15m = load_candles(DATA_DIR / "binance_btc_15m.json")
    ts_1h, o_1h, h_1h, l_1h, c_1h, v_1h = load_candles(DATA_DIR / "binance_btc_1h.json")
    print(f"  15m: {len(c_15m)} bars ({len(c_15m)//96} days)")
    print(f"  1H:  {len(c_1h)} bars")

    # ═══════════════════════════════════════════════════
    # GROUP 1: WITH FILTERS (ADX + Squeeze + 1H confirm)
    # ═══════════════════════════════════════════════════

    filtered_configs = [
        ("Baseline+F", Config(st_variant="standard", st_source="hlc3")),
        ("Evasive+F", Config(st_variant="evasive")),
        ("Recovery+F", Config(st_variant="recovery")),
    ]

    f_full, f_wf, f_sp, f_rob = run_suite(
        "WITH FILTERS (ADX+SQZ+1H)", filtered_configs,
        ts_15m, o_15m, h_15m, l_15m, c_15m, v_15m, ts_1h, h_1h, l_1h, c_1h
    )

    # ═══════════════════════════════════════════════════
    # GROUP 2: RAW (no filters, just ST + 1H confirm)
    # ═══════════════════════════════════════════════════

    raw_configs = [
        ("Baseline raw", Config(st_variant="standard", st_source="hlc3", use_filters=False)),
        ("Evasive raw", Config(st_variant="evasive", use_filters=False)),
        ("Recovery raw", Config(st_variant="recovery", use_filters=False)),
    ]

    r_full, r_wf, r_sp, r_rob = run_suite(
        "RAW (no ADX/SQZ, 1H confirm only)", raw_configs,
        ts_15m, o_15m, h_15m, l_15m, c_15m, v_15m, ts_1h, h_1h, l_1h, c_1h
    )

    # ═══════════════════════════════════════════════════
    # GROUP 3: COMPLETELY STANDALONE (no filters, no 1H)
    # ═══════════════════════════════════════════════════

    solo_configs = [
        ("Baseline solo", Config(st_variant="standard", st_source="hlc3", use_filters=False, use_1h_confirm=False)),
        ("Evasive solo", Config(st_variant="evasive", use_filters=False, use_1h_confirm=False)),
        ("Recovery solo", Config(st_variant="recovery", use_filters=False, use_1h_confirm=False)),
    ]

    s_full, s_wf, s_sp, s_rob = run_suite(
        "STANDALONE (no filters, no 1H — pure indicator)", solo_configs,
        ts_15m, o_15m, h_15m, l_15m, c_15m, v_15m, ts_1h, h_1h, l_1h, c_1h
    )

    # ═══════════════════════════════════════════════════
    # GRAND SUMMARY TABLE
    # ═══════════════════════════════════════════════════

    all_names = [c[0] for c in filtered_configs] + [c[0] for c in raw_configs] + [c[0] for c in solo_configs]
    all_full = f_full + r_full + s_full
    all_wf = f_wf + r_wf + s_wf
    all_sp = f_sp + r_sp + s_sp
    all_rob = f_rob + r_rob + s_rob
    N = len(all_names)

    # Print in two tables for readability (filtered + raw, then standalone)
    def print_summary(title, names, fulls, wfs, sps, robs):
        nc = len(names)
        w = 18
        print(f"\n{'═' * (20 + nc * w)}")
        print(f"  {title}")
        print(f"{'═' * (20 + nc * w)}")
        hdr = f"  {'Metric':<16}"
        for nm in names:
            hdr += f" {nm:<{w}}"
        print(hdr)
        print(f"  {'─'*14}  " + "  ".join(["─" * (w-2)] * nc))
        def gr(label, vals):
            r = f"  {label:<16}"
            for v in vals:
                r += f" {v:<{w}}"
            return r
        print(gr("Trades", [str(r.num_trades) for r in fulls]))
        print(gr("Win Rate", [f"{r.win_rate:.1f}%" for r in fulls]))
        print(gr("Profit Factor", [fp(r.profit_factor) for r in fulls]))
        print(gr("Total P&L", [f"${r.total_pnl:+.0f}" for r in fulls]))
        print(gr("Max Drawdown", [f"{r.max_drawdown_pct:.1f}%" for r in fulls]))
        print(gr("Sharpe", [f"{r.sharpe_ratio:.2f}" for r in fulls]))
        print(gr("WF Valid PF", [fp(r.profit_factor) for r in wfs]))
        print(gr("Starts prof.", [f"{sp}/6" for sp in sps]))
        print(gr("Robust wins", [f"{rw}/8" for rw in robs]))
        print(gr("Full PF > 1", ["PASS" if r.profit_factor > 1 else "FAIL" for r in fulls]))
        print(gr("WF PF > 1", ["PASS" if r.profit_factor > 1 else "FAIL" for r in wfs]))
        print(gr("MDD < 50%", ["PASS" if r.max_drawdown_pct < 50 else "FAIL" for r in fulls]))

    print_summary("FILTERED (ADX + SQZ + 1H)",
                   [c[0] for c in filtered_configs], f_full, f_wf, f_sp, f_rob)
    print_summary("RAW (1H confirm only, no ADX/SQZ)",
                   [c[0] for c in raw_configs], r_full, r_wf, r_sp, r_rob)
    print_summary("STANDALONE (pure indicator, no filters, no 1H)",
                   [c[0] for c in solo_configs], s_full, s_wf, s_sp, s_rob)

    # Grand ranking
    scores = {}
    for i, nm in enumerate(all_names):
        s = 0
        if all_full[i].profit_factor > 1: s += 2
        if all_wf[i].profit_factor > 1: s += 2
        if all_full[i].max_drawdown_pct < 50: s += 1
        s += all_sp[i]
        s += all_rob[i]
        s += int(all_full[i].profit_factor * 10)  # weighted PF
        scores[nm] = s

    ranked = sorted(scores.items(), key=lambda x: -x[1])
    print(f"\n\n{'═' * 90}")
    print(f"  FINAL RANKING (all 9 variants, composite score)")
    print(f"{'═' * 90}")
    for rank, (nm, sc) in enumerate(ranked, 1):
        i = all_names.index(nm)
        r = all_full[i]
        print(f"  #{rank}  {nm:<18}  PF={fp(r.profit_factor):>5}  MDD={r.max_drawdown_pct:>5.1f}%  "
              f"P&L=${r.total_pnl:>+8.0f}  WR={r.win_rate:>5.1f}%  Trades={r.num_trades:>4}  score={sc}")
    print(f"{'═' * 90}")


if __name__ == "__main__":
    main()

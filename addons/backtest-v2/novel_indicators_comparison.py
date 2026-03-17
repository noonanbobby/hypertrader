#!/usr/bin/env python3
"""
Novel Indicators Comparison — NTS + NPC vs Recovery ST baseline

Tests 8 configurations:
  1. Recovery+F (champion baseline, PF 1.71)
  2. NTS standalone
  3. NPC standalone
  4. NTS + filters (replaces ST)
  5. NPC + filters (replaces ST)
  6. Recovery ST + NTS combined
  7. Recovery ST + NPC combined
  8. Recovery ST + NTS + NPC all three

All use Strategy B exit (15m flip → flat → re-enter with filters).
"""

import json
import sys
import numpy as np
from pathlib import Path
from dataclasses import dataclass
from collections import deque
import bisect

sys.path.insert(0, str(Path(__file__).parent))
from engine import calc_tr, calc_atr_rma, calc_supertrend, BacktestResult

DATA_DIR = Path(__file__).parent.parent / "backtest-data"


# ═══════════════════════════════════════════════════════════════
# EXISTING INDICATORS (from previous scripts)
# ═══════════════════════════════════════════════════════════════

def calc_adx(highs, lows, closes, period=14):
    n = len(highs)
    plus_dm = np.zeros(n)
    minus_dm = np.zeros(n)
    for i in range(1, n):
        up = highs[i] - highs[i-1]
        down = lows[i-1] - lows[i]
        if up > down and up > 0: plus_dm[i] = up
        if down > up and down > 0: minus_dm[i] = down
    tr = calc_tr(highs, lows, closes)
    def rma_smooth(data, p):
        out = np.zeros(n)
        out[p] = np.sum(data[1:p+1])
        for i in range(p+1, n): out[i] = out[i-1] - out[i-1]/p + data[i]
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
            if total > 0: dx[i] = 100 * abs(pdi - mdi) / total
    adx = np.full(n, np.nan)
    fv = period
    while fv < n and dx[fv] == 0: fv += 1
    if fv + period >= n: return adx
    adx[fv + period - 1] = np.mean(dx[fv:fv+period])
    for i in range(fv + period, n): adx[i] = (adx[i-1] * (period-1) + dx[i]) / period
    return adx


def calc_squeeze(highs, lows, closes, bb_len=20, bb_mult=2.0, kc_len=20, kc_mult=1.5):
    n = len(closes)
    squeeze = np.full(n, False)
    tr = calc_tr(highs, lows, closes)
    for i in range(max(bb_len, kc_len) - 1, n):
        w = closes[i - bb_len + 1:i + 1]
        bb_b = np.mean(w); bb_s = np.std(w, ddof=0)
        ub = bb_b + bb_mult * bb_s; lb = bb_b - bb_mult * bb_s
        kc_b = np.mean(closes[i - kc_len + 1:i + 1])
        kc_a = np.mean(tr[i - kc_len + 1:i + 1])
        uk = kc_b + kc_mult * kc_a; lk = kc_b - kc_mult * kc_a
        squeeze[i] = (lb > lk) and (ub < uk)
    return squeeze


def calc_recovery_supertrend(highs, lows, closes, atr_period=8, multiplier=4.0,
                              recovery_alpha=5.0, recovery_threshold=1.0):
    n = len(closes)
    src = (highs + lows) / 2
    tr = calc_tr(highs, lows, closes)
    atr = calc_atr_rma(tr, atr_period)
    st_band = np.full(n, np.nan)
    direction = np.ones(n)
    switch_price = np.zeros(n)
    alpha = recovery_alpha / 100.0
    start = atr_period - 1
    st_band[start] = src[start] - multiplier * atr[start]
    direction[start] = 1; switch_price[start] = closes[start]
    for i in range(start + 1, n):
        if np.isnan(atr[i]):
            st_band[i] = st_band[i-1]; direction[i] = direction[i-1]; switch_price[i] = switch_price[i-1]; continue
        ub = src[i] + multiplier * atr[i]; lb = src[i] - multiplier * atr[i]
        pb = st_band[i-1]; dev = recovery_threshold * atr[i]
        if direction[i-1] == 1:
            loss = (switch_price[i-1] - closes[i]) > dev
            tb = (alpha * closes[i] + (1 - alpha) * pb) if loss else lb
            st_band[i] = max(tb, pb)
            if closes[i] < st_band[i]:
                direction[i] = -1; st_band[i] = ub; switch_price[i] = closes[i]
            else:
                direction[i] = 1; switch_price[i] = switch_price[i-1]
        else:
            loss = (closes[i] - switch_price[i-1]) > dev
            tb = (alpha * closes[i] + (1 - alpha) * pb) if loss else ub
            st_band[i] = min(tb, pb)
            if closes[i] > st_band[i]:
                direction[i] = 1; st_band[i] = lb; switch_price[i] = closes[i]
            else:
                direction[i] = -1; switch_price[i] = switch_price[i-1]
    return st_band, direction


# ═══════════════════════════════════════════════════════════════
# NEW INDICATOR 1: NEIGHBORING TRAILING STOP (NTS)
# ═══════════════════════════════════════════════════════════════

def calc_nts(closes, N=50, k=5, percentile=50, smoothing=3):
    """
    Neighboring Trailing Stop.
    Maintains sorted buffer of last N closes, finds k neighbors
    above and below current price, calculates percentile level,
    smooths with SMA, and trails (can only move up in bull, down in bear).
    """
    n = len(closes)
    direction = np.full(n, np.nan)
    trail_level = np.full(n, np.nan)

    # Raw neighbor levels before smoothing
    raw_levels = np.full(n, np.nan)

    # Sorted buffer (maintained incrementally)
    buf = []  # sorted list
    buf_queue = deque()  # FIFO for removal

    warmup = max(N, smoothing + 1)

    for i in range(n):
        val = closes[i]

        # Add to buffer
        bisect.insort(buf, val)
        buf_queue.append(val)

        # Remove oldest if buffer exceeds N
        if len(buf_queue) > N:
            old = buf_queue.popleft()
            idx = bisect.bisect_left(buf, old)
            # Find exact match (handle duplicates)
            while idx < len(buf) and buf[idx] != old:
                idx += 1
            if idx < len(buf):
                buf.pop(idx)

        if len(buf) < max(2 * k + 1, 3):
            continue

        # Find position of current close in sorted buffer
        pos = bisect.bisect_left(buf, val)

        # Get k neighbors below and k above
        lo = max(0, pos - k)
        hi = min(len(buf), pos + k + 1)
        neighbors = buf[lo:hi]

        if len(neighbors) < 2:
            raw_levels[i] = val
            continue

        # Percentile within neighbors
        pct_idx = int(len(neighbors) * percentile / 100)
        pct_idx = max(0, min(pct_idx, len(neighbors) - 1))
        raw_levels[i] = neighbors[pct_idx]

    # Smooth with SMA
    smoothed = np.full(n, np.nan)
    for i in range(n):
        if i < smoothing - 1:
            continue
        window = raw_levels[i - smoothing + 1:i + 1]
        valid = window[~np.isnan(window)]
        if len(valid) == smoothing:
            smoothed[i] = np.mean(valid)

    # Trail and determine direction
    trend = 1  # start bullish
    prev_trail = np.nan

    for i in range(n):
        if np.isnan(smoothed[i]):
            continue

        if np.isnan(prev_trail):
            prev_trail = smoothed[i]
            trail_level[i] = smoothed[i]
            direction[i] = 1 if closes[i] > smoothed[i] else -1
            trend = direction[i]
            continue

        # Trail: can only move up in bull, down in bear
        if trend == 1:
            trail_level[i] = max(smoothed[i], prev_trail)
        else:
            trail_level[i] = min(smoothed[i], prev_trail)

        # Check for flip
        if trend == 1 and closes[i] < trail_level[i]:
            trend = -1
            trail_level[i] = smoothed[i]  # reset to raw level on flip
        elif trend == -1 and closes[i] > trail_level[i]:
            trend = 1
            trail_level[i] = smoothed[i]

        direction[i] = trend
        prev_trail = trail_level[i]

    return trail_level, direction


# ═══════════════════════════════════════════════════════════════
# NEW INDICATOR 2: NEURAL PROBABILITY CHANNEL (NPC)
# Rational Quadratic Kernel baseline, causal
# ═══════════════════════════════════════════════════════════════

def calc_npc(closes, h=8, alpha=1.0, lookback=50):
    """
    Rational Quadratic Kernel baseline indicator.
    For each bar, computes weighted average of past prices using
    RQ kernel weights. Trend determined by close vs baseline + slope.
    """
    n = len(closes)
    baseline = np.full(n, np.nan)
    direction = np.full(n, np.nan)

    for i in range(lookback, n):
        # Compute kernel-weighted average of past `lookback` bars
        total_weight = 0.0
        weighted_sum = 0.0

        for j in range(max(0, i - lookback), i + 1):
            dist = i - j
            # Rational Quadratic kernel: (1 + d^2 / (2 * alpha * h^2))^(-alpha)
            w = (1.0 + (dist * dist) / (2.0 * alpha * h * h)) ** (-alpha)
            weighted_sum += w * closes[j]
            total_weight += w

        if total_weight > 0:
            baseline[i] = weighted_sum / total_weight

    # Determine trend from baseline + slope
    prev_trend = 1
    for i in range(lookback, n):
        if np.isnan(baseline[i]):
            continue

        # Slope: compare current baseline to previous
        if i > lookback and not np.isnan(baseline[i-1]):
            slope = baseline[i] - baseline[i-1]
        else:
            slope = 0.0

        # Bull: close > baseline AND slope > 0
        # Bear: close < baseline AND slope < 0
        if closes[i] > baseline[i] and slope > 0:
            direction[i] = 1
        elif closes[i] < baseline[i] and slope < 0:
            direction[i] = -1
        else:
            # Ambiguous — maintain previous direction
            direction[i] = prev_trend

        prev_trend = direction[i]

    return baseline, direction


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
        if j < len(dir_1h): aligned[i] = dir_1h[j]
    return aligned


# ═══════════════════════════════════════════════════════════════
# UNIFIED ENGINE
# ═══════════════════════════════════════════════════════════════

@dataclass
class Cfg:
    # Primary indicator
    primary: str = "recovery_st"  # "recovery_st", "nts", "npc"
    # Recovery ST params
    st_atr: int = 8; st_mult: float = 4.0
    recovery_alpha: float = 5.0; recovery_threshold: float = 1.0
    # NTS params
    nts_N: int = 50; nts_k: int = 5; nts_pct: int = 50; nts_smooth: int = 3
    # NPC params
    npc_h: int = 8; npc_alpha: float = 1.0; npc_lookback: int = 50
    # Combination filters
    use_nts_filter: bool = False  # require NTS agreement
    use_npc_filter: bool = False  # require NPC agreement
    # Standard filters
    use_filters: bool = True
    use_1h_confirm: bool = True
    htf_atr: int = 10; htf_mult: float = 4.0; htf_source: str = "close"
    adx_period: int = 14; adx_min: float = 15.0; adx_rising_lookback: int = 4
    squeeze_enabled: bool = True
    sqz_bb_len: int = 20; sqz_bb_mult: float = 2.0; sqz_kc_len: int = 20; sqz_kc_mult: float = 1.5
    # Execution
    taker_fee: float = 0.00045; slippage: float = 0.0001
    starting_capital: float = 500.0; fixed_size_usd: float = 125.0; leverage: float = 10.0
    warmup: int = 200


@dataclass
class Trade:
    entry_bar: int; entry_price: float; direction: int; size_usd: float
    exit_bar: int = 0; exit_price: float = 0.0; pnl: float = 0.0; fees: float = 0.0


def run_backtest(ts_15m, opens, highs, lows, closes, volumes,
                  ts_1h, h_1h, l_1h, c_1h,
                  config: Cfg, start_bar=0, end_bar=-1):
    n = len(closes)
    if end_bar < 0: end_bar = n
    o = opens[:end_bar]; h = highs[:end_bar]; l = lows[:end_bar]
    c = closes[:end_bar]; ts = ts_15m[:end_bar]
    nn = len(c)

    # Primary indicator
    if config.primary == "recovery_st":
        _, prim_dir = calc_recovery_supertrend(h, l, c, config.st_atr, config.st_mult,
                                                config.recovery_alpha, config.recovery_threshold)
    elif config.primary == "nts":
        _, prim_dir = calc_nts(c, config.nts_N, config.nts_k, config.nts_pct, config.nts_smooth)
    elif config.primary == "npc":
        _, prim_dir = calc_npc(c, config.npc_h, config.npc_alpha, config.npc_lookback)
    else:
        _, prim_dir = calc_supertrend(h, l, c, config.st_atr, config.st_mult, "hlc3")

    # Combination filters
    nts_dir = None
    if config.use_nts_filter:
        _, nts_dir = calc_nts(c, config.nts_N, config.nts_k, config.nts_pct, config.nts_smooth)
    npc_dir = None
    if config.use_npc_filter:
        _, npc_dir = calc_npc(c, config.npc_h, config.npc_alpha, config.npc_lookback)

    # 1H confirmation
    st_dir_1h = None
    if config.use_1h_confirm:
        _, st_dir_1h_raw = calc_supertrend(h_1h, l_1h, c_1h, config.htf_atr, config.htf_mult, config.htf_source)
        st_dir_1h = align_1h_to_15m(ts, st_dir_1h_raw, ts_1h)

    # ADX + squeeze
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
        # 1H confirm
        if config.use_1h_confirm and st_dir_1h is not None:
            if np.isnan(st_dir_1h[i]) or prim_dir[i] != st_dir_1h[i]:
                return False
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
        # NTS agreement
        if nts_dir is not None:
            if np.isnan(nts_dir[i]) or nts_dir[i] != prim_dir[i]:
                return False
        # NPC agreement
        if npc_dir is not None:
            if np.isnan(npc_dir[i]) or npc_dir[i] != prim_dir[i]:
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

        if np.isnan(prim_dir[i]): continue
        curr = prim_dir[i]
        prev_d = prim_dir[i-1] if i > 0 and not np.isnan(prim_dir[i-1]) else curr
        flipped = curr != prev_d
        sig = 1 if curr == 1 else -1

        # Strategy B: exit on primary flip, re-enter with filters
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
        dd = (pk - ec) / pk; r.max_drawdown_pct = float(np.max(dd)) * 100
        if len(ec) > 1:
            rets = np.diff(ec) / ec[:-1]
            if np.std(rets) > 0:
                r.sharpe_ratio = float(np.mean(rets) / np.std(rets) * np.sqrt(35040))
    return r


# ═══════════════════════════════════════════════════════════════
# VALIDATION SUITE
# ═══════════════════════════════════════════════════════════════

def fp(v): return f"{v:.2f}" if v < 9999 else "INF"

def run_suite(name, cfg, ts_15m, o15, h15, l15, c15, v15, ts_1h, h1h, l1h, c1h):
    """Run full validation for one config, return summary dict."""
    # Full
    full = run_backtest(ts_15m, o15, h15, l15, c15, v15, ts_1h, h1h, l1h, c1h, cfg)

    # Walk-forward
    split = int(len(c15) * 0.7)
    wf = run_backtest(ts_15m, o15, h15, l15, c15, v15, ts_1h, h1h, l1h, c1h, cfg, start_bar=split)

    # 6 starting points
    total = len(c15); seg = total // 6
    sp_prof = 0
    for s in range(6):
        r = run_backtest(ts_15m, o15, h15, l15, c15, v15, ts_1h, h1h, l1h, c1h, cfg, start_bar=s * seg)
        if r.total_pnl > 0: sp_prof += 1

    # Param robustness: vary key params +/-20%
    rob_wins = 0; rob_total = 0
    base_pf = full.profit_factor
    for f1 in [0.8, 1.0, 1.2]:
        for f2 in [0.8, 1.0, 1.2]:
            if f1 == 1.0 and f2 == 1.0: continue
            rob_total += 1
            test_cfg = Cfg(
                primary=cfg.primary,
                st_atr=max(2, int(round(cfg.st_atr * f1))),
                st_mult=round(cfg.st_mult * f2, 1),
                recovery_alpha=cfg.recovery_alpha,
                recovery_threshold=cfg.recovery_threshold,
                nts_N=max(10, int(round(cfg.nts_N * f1))),
                nts_k=max(2, int(round(cfg.nts_k * f2))),
                nts_pct=cfg.nts_pct, nts_smooth=cfg.nts_smooth,
                npc_h=max(2, int(round(cfg.npc_h * f1))),
                npc_alpha=max(0.1, round(cfg.npc_alpha * f2, 1)),
                npc_lookback=max(10, int(round(cfg.npc_lookback * f1))),
                use_nts_filter=cfg.use_nts_filter, use_npc_filter=cfg.use_npc_filter,
                use_filters=cfg.use_filters, use_1h_confirm=cfg.use_1h_confirm,
                adx_min=cfg.adx_min,
            )
            tr = run_backtest(ts_15m, o15, h15, l15, c15, v15, ts_1h, h1h, l1h, c1h, test_cfg)
            if tr.profit_factor > 1.0: rob_wins += 1

    return {
        "name": name,
        "trades": full.num_trades,
        "wr": full.win_rate,
        "pf": full.profit_factor,
        "pnl": full.total_pnl,
        "mdd": full.max_drawdown_pct,
        "sharpe": full.sharpe_ratio,
        "fees": full.total_fees,
        "wf_pf": wf.profit_factor,
        "wf_mdd": wf.max_drawdown_pct,
        "sp": sp_prof,
        "rob": rob_wins,
        "rob_total": rob_total,
        "full_pass": full.profit_factor > 1.0,
        "wf_pass": wf.profit_factor > 1.0,
        "mdd_pass": full.max_drawdown_pct < 50.0,
    }


def main():
    print("=" * 110)
    print("  NOVEL INDICATORS + RECOVERY ST — FULL VALIDATION SUITE")
    print("  Strategy B exit | $125 × 10x | 0.045% fees | 730 days BTC 15m")
    print("=" * 110)

    print("\nLoading data...")
    ts_15m, o15, h15, l15, c15, v15 = load_candles(DATA_DIR / "binance_btc_15m.json")
    ts_1h, o1h, h1h, l1h, c1h, v1h = load_candles(DATA_DIR / "binance_btc_1h.json")
    print(f"  15m: {len(c15)} bars ({len(c15)//96} days) | 1H: {len(c1h)} bars")

    # Define all 8 configurations
    configs = [
        ("RecoveryST+F", Cfg(primary="recovery_st")),
        ("NTS solo", Cfg(primary="nts", use_filters=False, use_1h_confirm=False)),
        ("NPC solo", Cfg(primary="npc", use_filters=False, use_1h_confirm=False)),
        ("NTS+filters", Cfg(primary="nts")),
        ("NPC+filters", Cfg(primary="npc")),
        ("RecST+NTS", Cfg(primary="recovery_st", use_nts_filter=True)),
        ("RecST+NPC", Cfg(primary="recovery_st", use_npc_filter=True)),
        ("RecST+NTS+NPC", Cfg(primary="recovery_st", use_nts_filter=True, use_npc_filter=True)),
    ]

    results = []
    for name, cfg in configs:
        print(f"\n  Running: {name}...", end="", flush=True)
        r = run_suite(name, cfg, ts_15m, o15, h15, l15, c15, v15, ts_1h, h1h, l1h, c1h)
        results.append(r)
        print(f" PF={fp(r['pf'])} MDD={r['mdd']:.1f}% P&L=${r['pnl']:+.0f}")

    # Master table
    print("\n\n" + "=" * 140)
    print("  MASTER COMPARISON TABLE")
    print("=" * 140)

    w = 15
    header = f"  {'Metric':<14}"
    for r in results:
        header += f" {r['name']:<{w}}"
    print(header)
    print(f"  {'─'*12}  " + "  ".join(["─" * (w-2)] * len(results)))

    def row(label, vals):
        r = f"  {label:<14}"
        for v in vals: r += f" {v:<{w}}"
        return r

    print(row("Trades", [str(r["trades"]) for r in results]))
    print(row("Win Rate", [f"{r['wr']:.1f}%" for r in results]))
    print(row("Profit Factor", [fp(r["pf"]) for r in results]))
    print(row("Total P&L", [f"${r['pnl']:+.0f}" for r in results]))
    print(row("Max Drawdown", [f"{r['mdd']:.1f}%" for r in results]))
    print(row("Sharpe", [f"{r['sharpe']:.2f}" for r in results]))
    print(row("Fees", [f"${r['fees']:.0f}" for r in results]))
    print(row("WF Valid PF", [fp(r["wf_pf"]) for r in results]))
    print(row("6/6 starts", [f"{r['sp']}/6" for r in results]))
    print(row("Robust PF>1", [f"{r['rob']}/{r['rob_total']}" for r in results]))
    print(f"  {'─'*12}  " + "  ".join(["─" * (w-2)] * len(results)))
    print(row("Full PF>1", ["PASS" if r["full_pass"] else "FAIL" for r in results]))
    print(row("WF PF>1", ["PASS" if r["wf_pass"] else "FAIL" for r in results]))
    print(row("MDD<50%", ["PASS" if r["mdd_pass"] else "FAIL" for r in results]))

    # Count validation passes
    print(f"\n  {'Checks passed':<14}", end="")
    for r in results:
        checks = sum([r["full_pass"], r["wf_pass"], r["mdd_pass"], r["sp"] >= 5])
        print(f" {checks}/4{'':<{w-4}}", end="")
    print()

    # Ranking
    print(f"\n{'═' * 110}")
    print(f"  FINAL RANKING")
    print(f"{'═' * 110}")
    scored = []
    for r in results:
        score = 0
        if r["full_pass"]: score += 3
        if r["wf_pass"]: score += 3
        if r["mdd_pass"]: score += 2
        score += r["sp"]  # up to 6
        score += r["rob"]  # up to 8
        score += int(r["pf"] * 10)
        scored.append((r, score))
    scored.sort(key=lambda x: -x[1])

    for rank, (r, sc) in enumerate(scored, 1):
        checks = sum([r["full_pass"], r["wf_pass"], r["mdd_pass"], r["sp"] >= 5])
        print(f"  #{rank}  {r['name']:<16} PF={fp(r['pf']):>5}  MDD={r['mdd']:>5.1f}%  "
              f"P&L=${r['pnl']:>+8.0f}  WR={r['wr']:>5.1f}%  Trades={r['trades']:>4}  "
              f"WF={fp(r['wf_pf']):>5}  {r['sp']}/6 starts  {r['rob']}/{r['rob_total']} robust  "
              f"checks={checks}/4  score={sc}")

    print(f"{'═' * 110}")


if __name__ == "__main__":
    main()

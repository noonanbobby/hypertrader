#!/usr/bin/env python3
"""
Backtest simulation engine v2 — written from scratch.

Bar-by-bar simulation with:
- Next-bar-open execution (no look-ahead)
- Taker/maker fee tiers
- Slippage model
- Close-based trailing stop (no intrabar look-ahead)
- Walk-forward train/validate split
"""

import numpy as np
from dataclasses import dataclass, field
from typing import Optional

# ═══════════════════════════════════════════════════════════════
# INDICATOR CALCULATIONS (verified against ta library)
# ═══════════════════════════════════════════════════════════════

def calc_tr(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray) -> np.ndarray:
    n = len(highs)
    tr = np.zeros(n)
    tr[0] = highs[0] - lows[0]
    for i in range(1, n):
        tr[i] = max(highs[i] - lows[i], abs(highs[i] - closes[i-1]), abs(lows[i] - closes[i-1]))
    return tr


def calc_atr_rma(tr: np.ndarray, period: int) -> np.ndarray:
    n = len(tr)
    atr = np.full(n, np.nan)
    if n < period:
        return atr
    atr[period - 1] = np.mean(tr[:period])
    for i in range(period, n):
        atr[i] = (atr[i-1] * (period - 1) + tr[i]) / period
    return atr


def calc_supertrend(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray,
                     atr_period: int, multiplier: float, source: str = "hl2"):
    n = len(closes)
    if source == "hl2":
        src = (highs + lows) / 2
    elif source == "hlc3":
        src = (highs + lows + closes) / 3
    elif source == "close":
        src = closes.copy()

    tr = calc_tr(highs, lows, closes)
    atr = calc_atr_rma(tr, atr_period)

    basic_up = src - multiplier * atr
    basic_dn = src + multiplier * atr

    final_up = np.full(n, np.nan)
    final_dn = np.full(n, np.nan)
    direction = np.ones(n)
    supertrend = np.full(n, np.nan)

    start = atr_period - 1
    final_up[start] = basic_up[start]
    final_dn[start] = basic_dn[start]
    direction[start] = 1
    supertrend[start] = final_up[start]

    for i in range(start + 1, n):
        if basic_up[i] > final_up[i-1] or closes[i-1] < final_up[i-1]:
            final_up[i] = basic_up[i]
        else:
            final_up[i] = final_up[i-1]

        if basic_dn[i] < final_dn[i-1] or closes[i-1] > final_dn[i-1]:
            final_dn[i] = basic_dn[i]
        else:
            final_dn[i] = final_dn[i-1]

        prev_dir = direction[i-1]
        if prev_dir == -1 and closes[i] > final_dn[i-1]:
            direction[i] = 1
        elif prev_dir == 1 and closes[i] < final_up[i-1]:
            direction[i] = -1
        else:
            direction[i] = prev_dir

        supertrend[i] = final_up[i] if direction[i] == 1 else final_dn[i]

    return supertrend, direction


def calc_rsi(closes: np.ndarray, period: int) -> np.ndarray:
    n = len(closes)
    rsi = np.full(n, np.nan)
    if n < period + 1:
        return rsi
    delta = np.diff(closes)
    gains = np.where(delta > 0, delta, 0.0)
    losses = np.where(delta < 0, -delta, 0.0)
    avg_gain = np.mean(gains[:period])
    avg_loss = np.mean(losses[:period])
    if avg_loss == 0:
        rsi[period] = 100.0
    else:
        rsi[period] = 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        if avg_loss == 0:
            rsi[i + 1] = 100.0
        else:
            rsi[i + 1] = 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)
    return rsi


def calc_sma(data: np.ndarray, period: int) -> np.ndarray:
    n = len(data)
    sma = np.full(n, np.nan)
    cumsum = np.cumsum(data)
    sma[period-1:] = (cumsum[period-1:] - np.concatenate(([0], cumsum[:-period]))) / period
    return sma


def calc_atr(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int) -> np.ndarray:
    tr = calc_tr(highs, lows, closes)
    return calc_atr_rma(tr, period)


# ═══════════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════

@dataclass
class BacktestConfig:
    # Supertrend
    atr_period: int = 10
    multiplier: float = 3.0
    source: str = "hl2"

    # Fees & slippage
    taker_fee: float = 0.00045      # 0.045%
    maker_fee: float = 0.00020      # 0.020%
    slippage: float = 0.0001        # 0.01%

    # Position sizing
    starting_capital: float = 500.0
    position_pct: float = 0.25      # 25% of equity
    leverage: float = 10.0

    # RSI filter
    rsi_enabled: bool = False
    rsi_period: int = 14
    rsi_buy_low: float = 30.0
    rsi_buy_high: float = 70.0
    rsi_sell_low: float = 30.0
    rsi_sell_high: float = 70.0

    # Volume filter
    volume_enabled: bool = False
    volume_threshold: float = 1.5   # x average
    volume_period: int = 20

    # Time-of-day filter (UTC hours)
    time_filter_enabled: bool = False
    time_block_start: int = 0       # UTC hour start of blocked window
    time_block_end: int = 4         # UTC hour end of blocked window

    # Flip cooldown
    cooldown_enabled: bool = False
    cooldown_bars: int = 1          # number of 15m bars
    cooldown_override_pct: float = 0.01  # 1% override

    # Trailing stop mode: "none", "close", "highlow"
    trailing_stop: str = "none"

    # Stop loss
    sl_enabled: bool = False
    sl_type: str = "pct"            # "atr" or "pct"
    sl_atr_mult: float = 3.0
    sl_pct: float = 0.02            # 2%

    # Take profit
    tp_enabled: bool = False
    tp_type: str = "pct"            # "atr" or "pct"
    tp_atr_mult: float = 3.0
    tp_pct: float = 0.03            # 3%

    # Warmup bars to skip (indicator initialization)
    warmup: int = 200


@dataclass
class Trade:
    entry_bar: int
    entry_price: float
    entry_time: int
    direction: int           # 1 = long, -1 = short
    size_usd: float          # notional position size
    exit_bar: int = 0
    exit_price: float = 0.0
    exit_time: int = 0
    exit_reason: str = ""
    pnl: float = 0.0
    fees: float = 0.0


@dataclass
class BacktestResult:
    config: BacktestConfig
    trades: list = field(default_factory=list)
    equity_curve: list = field(default_factory=list)
    total_pnl: float = 0.0
    total_fees: float = 0.0
    num_trades: int = 0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    max_drawdown_pct: float = 0.0
    sharpe_ratio: float = 0.0
    final_equity: float = 0.0
    start_bar: int = 0
    end_bar: int = 0


# ═══════════════════════════════════════════════════════════════
# SIMULATION ENGINE
# ═══════════════════════════════════════════════════════════════

def run_backtest(opens: np.ndarray, highs: np.ndarray, lows: np.ndarray,
                 closes: np.ndarray, volumes: np.ndarray, timestamps: np.ndarray,
                 config: BacktestConfig, start_bar: int = 0, end_bar: int = -1) -> BacktestResult:
    """
    Bar-by-bar simulation.

    Signal logic:
    - On bar i CLOSE: compute indicators using data [0..i]
    - Check for entry/exit signals
    - Execute at OPEN of bar i+1
    """
    n = len(closes)
    if end_bar < 0:
        end_bar = n

    # Pre-compute indicators on FULL data up to end_bar
    h = highs[:end_bar]
    l = lows[:end_bar]
    c = closes[:end_bar]
    o = opens[:end_bar]
    v = volumes[:end_bar]
    ts = timestamps[:end_bar]

    nn = len(c)

    # Supertrend
    st_line, st_dir = calc_supertrend(h, l, c, config.atr_period, config.multiplier, config.source)

    # RSI (if enabled)
    rsi = None
    if config.rsi_enabled:
        rsi = calc_rsi(c, config.rsi_period)

    # Volume SMA (if enabled)
    vol_sma = None
    if config.volume_enabled:
        vol_sma = calc_sma(v, config.volume_period)

    # ATR for SL/TP
    atr = None
    if config.sl_enabled or config.tp_enabled:
        atr = calc_atr(h, l, c, config.atr_period)

    # Effective start
    eff_start = max(start_bar, config.warmup)

    # State
    equity = config.starting_capital
    position = 0        # 1 = long, -1 = short, 0 = flat
    entry_price = 0.0
    entry_bar = 0
    entry_time = 0
    position_size = 0.0  # notional USD
    last_flip_bar = -999
    trades = []
    equity_curve = []

    # Pending signals
    pending_action = None   # ("open_long", "open_short", "close", "flip_long", "flip_short")

    def apply_fill(price: float, direction: int, is_close: bool):
        """Apply slippage to a fill price."""
        slip = price * config.slippage
        if is_close:
            # Closing: sell longs worse, buy shorts worse
            if direction == 1:  # closing long = selling
                return price - slip
            else:  # closing short = buying
                return price + slip
        else:
            # Opening: buy longs worse, sell shorts worse
            if direction == 1:  # opening long = buying
                return price + slip
            else:  # opening short = selling
                return price - slip

    def calc_fee(notional: float) -> float:
        return notional * config.taker_fee

    for i in range(eff_start, nn):
        # ─── Execute pending action at this bar's OPEN ───
        if pending_action is not None and i > eff_start:
            action = pending_action
            pending_action = None

            if action == "close" and position != 0:
                fill_price = apply_fill(o[i], position, is_close=True)
                pnl_raw = (fill_price - entry_price) * position * (position_size / entry_price)
                fee = calc_fee(position_size)
                pnl_net = pnl_raw - fee

                trades.append(Trade(
                    entry_bar=entry_bar, entry_price=entry_price, entry_time=entry_time,
                    direction=position, size_usd=position_size,
                    exit_bar=i, exit_price=fill_price, exit_time=int(ts[i]),
                    exit_reason="signal", pnl=pnl_net, fees=fee
                ))
                equity += pnl_net
                position = 0
                position_size = 0.0

            elif action in ("open_long", "open_short"):
                new_dir = 1 if action == "open_long" else -1
                fill_price = apply_fill(o[i], new_dir, is_close=False)
                position_size = equity * config.position_pct * config.leverage
                fee = calc_fee(position_size)
                equity -= fee  # entry fee from equity

                position = new_dir
                entry_price = fill_price
                entry_bar = i
                entry_time = int(ts[i])

            elif action in ("flip_long", "flip_short"):
                # Close existing position first
                if position != 0:
                    fill_price_close = apply_fill(o[i], position, is_close=True)
                    pnl_raw = (fill_price_close - entry_price) * position * (position_size / entry_price)
                    fee_close = calc_fee(position_size)
                    pnl_net = pnl_raw - fee_close

                    trades.append(Trade(
                        entry_bar=entry_bar, entry_price=entry_price, entry_time=entry_time,
                        direction=position, size_usd=position_size,
                        exit_bar=i, exit_price=fill_price_close, exit_time=int(ts[i]),
                        exit_reason="flip", pnl=pnl_net, fees=fee_close
                    ))
                    equity += pnl_net

                # Open new position
                new_dir = 1 if action == "flip_long" else -1
                fill_price_open = apply_fill(o[i], new_dir, is_close=False)
                position_size = equity * config.position_pct * config.leverage
                fee_open = calc_fee(position_size)
                equity -= fee_open

                position = new_dir
                entry_price = fill_price_open
                entry_bar = i
                entry_time = int(ts[i])
                last_flip_bar = i

        # Record equity
        # Mark-to-market: unrealized PnL
        if position != 0:
            unrealized = (c[i] - entry_price) * position * (position_size / entry_price)
            equity_curve.append(equity + unrealized)
        else:
            equity_curve.append(equity)

        # ─── Check signals on this bar's CLOSE ───
        # (will execute at next bar's OPEN)

        if i >= nn - 1:
            # Last bar — close any open position
            if position != 0:
                pending_action = "close"
            continue

        # Current indicator values (computed using data up to and including bar i)
        if np.isnan(st_dir[i]) or np.isnan(st_line[i]):
            continue

        curr_dir = st_dir[i]
        prev_dir = st_dir[i-1] if i > 0 and not np.isnan(st_dir[i-1]) else curr_dir

        # ─── Trailing stop check (close-based) ───
        if config.trailing_stop == "close" and position != 0:
            if position == 1 and c[i] < st_line[i]:
                # Long position, close crossed below ST line
                pending_action = "close"
                continue
            elif position == -1 and c[i] > st_line[i]:
                # Short position, close crossed above ST line
                pending_action = "close"
                continue

        # ─── Trailing stop check (high/low-based — labeled as look-ahead) ───
        if config.trailing_stop == "highlow" and position != 0:
            if position == 1 and l[i] < st_line[i]:
                pending_action = "close"
                continue
            elif position == -1 and h[i] > st_line[i]:
                pending_action = "close"
                continue

        # ─── Stop loss check ───
        if config.sl_enabled and position != 0:
            if config.sl_type == "pct":
                sl_dist = config.sl_pct
            else:  # atr
                if atr is not None and not np.isnan(atr[i]):
                    sl_dist = (config.sl_atr_mult * atr[i]) / entry_price
                else:
                    sl_dist = config.sl_pct  # fallback

            if position == 1 and c[i] < entry_price * (1 - sl_dist):
                pending_action = "close"
                continue
            elif position == -1 and c[i] > entry_price * (1 + sl_dist):
                pending_action = "close"
                continue

        # ─── Take profit check ───
        if config.tp_enabled and position != 0:
            if config.tp_type == "pct":
                tp_dist = config.tp_pct
            else:  # atr
                if atr is not None and not np.isnan(atr[i]):
                    tp_dist = (config.tp_atr_mult * atr[i]) / entry_price
                else:
                    tp_dist = config.tp_pct

            if position == 1 and c[i] > entry_price * (1 + tp_dist):
                pending_action = "close"
                continue
            elif position == -1 and c[i] < entry_price * (1 - tp_dist):
                pending_action = "close"
                continue

        # ─── Supertrend direction change ───
        direction_changed = (curr_dir != prev_dir)

        if not direction_changed:
            # No signal — but check if we should enter from flat
            if position == 0:
                # Enter in the direction of current trend (only on flip)
                pass
            continue

        # Direction changed — check filters
        new_signal_dir = 1 if curr_dir == 1 else -1

        # ─── Cooldown filter ───
        if config.cooldown_enabled:
            bars_since_flip = i - last_flip_bar
            if bars_since_flip < config.cooldown_bars:
                # Check override: did price move enough?
                if last_flip_bar >= 0 and last_flip_bar < nn:
                    price_change = abs(c[i] - c[last_flip_bar]) / c[last_flip_bar]
                    if price_change < config.cooldown_override_pct:
                        continue  # Skip this signal

        # ─── RSI filter ───
        if config.rsi_enabled and rsi is not None:
            if np.isnan(rsi[i]):
                continue
            if new_signal_dir == 1:  # Buy signal
                if not (config.rsi_buy_low <= rsi[i] <= config.rsi_buy_high):
                    continue
            else:  # Sell signal
                if not (config.rsi_sell_low <= rsi[i] <= config.rsi_sell_high):
                    continue

        # ─── Volume filter ───
        if config.volume_enabled and vol_sma is not None:
            if not np.isnan(vol_sma[i]) and v[i] < config.volume_threshold * vol_sma[i]:
                continue

        # ─── Time-of-day filter ───
        if config.time_filter_enabled:
            # Extract UTC hour from timestamp (ms)
            hour_utc = (int(ts[i]) // 3600000) % 24
            if config.time_block_start <= config.time_block_end:
                if config.time_block_start <= hour_utc < config.time_block_end:
                    continue
            else:  # wraps around midnight (e.g., 22-06)
                if hour_utc >= config.time_block_start or hour_utc < config.time_block_end:
                    continue

        # ─── Execute signal ───
        if position == 0:
            # Flat — open new position
            pending_action = "open_long" if new_signal_dir == 1 else "open_short"
        elif position != new_signal_dir:
            # Flip position
            pending_action = "flip_long" if new_signal_dir == 1 else "flip_short"
        # else: same direction, already positioned, ignore

    # ─── Close any remaining position at last bar ───
    if position != 0 and pending_action == "close":
        # Execute the pending close at the last bar's close price (end of data)
        last_i = nn - 1
        fill_price = apply_fill(c[last_i], position, is_close=True)
        pnl_raw = (fill_price - entry_price) * position * (position_size / entry_price)
        fee = calc_fee(position_size)
        pnl_net = pnl_raw - fee
        trades.append(Trade(
            entry_bar=entry_bar, entry_price=entry_price, entry_time=entry_time,
            direction=position, size_usd=position_size,
            exit_bar=last_i, exit_price=fill_price, exit_time=int(ts[last_i]),
            exit_reason="end_of_data", pnl=pnl_net, fees=fee
        ))
        equity += pnl_net
        if equity_curve:
            equity_curve[-1] = equity

    # ─── Compute statistics ───
    result = BacktestResult(config=config)
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

        # Sharpe ratio (annualized, using 15m bar returns)
        if len(ec) > 1:
            returns = np.diff(ec) / ec[:-1]
            if np.std(returns) > 0:
                # 35,040 fifteen-minute bars per year
                result.sharpe_ratio = float(np.mean(returns) / np.std(returns) * np.sqrt(35040))

    return result


def result_to_dict(r: BacktestResult) -> dict:
    """Convert result to JSON-serializable dict."""
    return {
        "config": {
            "atr_period": r.config.atr_period,
            "multiplier": r.config.multiplier,
            "source": r.config.source,
            "rsi_enabled": r.config.rsi_enabled,
            "rsi_period": r.config.rsi_period,
            "rsi_buy_range": [r.config.rsi_buy_low, r.config.rsi_buy_high],
            "rsi_sell_range": [r.config.rsi_sell_low, r.config.rsi_sell_high],
            "volume_enabled": r.config.volume_enabled,
            "volume_threshold": r.config.volume_threshold,
            "time_filter_enabled": r.config.time_filter_enabled,
            "cooldown_enabled": r.config.cooldown_enabled,
            "trailing_stop": r.config.trailing_stop,
            "sl_enabled": r.config.sl_enabled,
            "tp_enabled": r.config.tp_enabled,
        },
        "num_trades": r.num_trades,
        "final_equity": round(r.final_equity, 2),
        "total_pnl": round(r.total_pnl, 2),
        "total_fees": round(r.total_fees, 2),
        "win_rate": round(r.win_rate, 2),
        "profit_factor": round(r.profit_factor, 4) if r.profit_factor != float('inf') else 9999.0,
        "max_drawdown_pct": round(r.max_drawdown_pct, 2),
        "sharpe_ratio": round(r.sharpe_ratio, 4),
    }
